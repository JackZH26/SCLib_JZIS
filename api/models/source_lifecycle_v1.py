"""Frozen additive 0056 negative source-governance history.

These are database observations, not provider revisions or scientific approval.
No transition or review reinstates a tracked source. Ordinary unheld catalogue
rows need no fabricated baseline. SQL-owner/trigger disabling is outside these
ordinary-DML guards; authenticated actor identity belongs to the trusted caller.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

TABLE_ORDER = ("source_lifecycle_epoch", "source_lifecycle_events", "source_lifecycle_reviews")
PARENT_TABLES = ("papers", "works", "material_claims", "users", "research_role_grants", "evidence_artifacts")
LOCK_KEY = 560017026
LOCK_FUNCTION = "sclib_source_lifecycle_lock_v1"
POLICY_VERSION = "source-lifecycle-review/1.0.0"
FUNCTION_SIGNATURES = (
    ("sclib_source_lifecycle_record_hash_v1", "jsonb"),
    ("sclib_source_lifecycle_snapshot_hash_v1", "text, jsonb"),
    (LOCK_FUNCTION, ""),
    ("sclib_source_lifecycle_immutable_v1", ""),
    ("sclib_source_lifecycle_capture_v1", ""),
    ("sclib_source_lifecycle_event_v1", ""),
    ("sclib_source_lifecycle_review_writer_v1", ""),
    ("sclib_source_lifecycle_review_v1", ""),
    ("sclib_source_lifecycle_artifact_v1", ""),
)
_SQL = "LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp SET TimeZone = 'UTC'"
PAPER_FIELDS = (
    "id", "source", "arxiv_id", "doi", "external_id", "id_scheme", "related_paper_id",
    "title", "authors", "affiliations", "date_submitted", "date_published", "journal",
    "journal_abbrev", "publication_ref", "abstract", "categories", "material_family",
    "status", "retraction_date", "retraction_reason", "materials_extracted", "quality_flags",
    "credibility_tier", "paper_type",
)
WORK_FIELDS = ("id", "canonical_title", "canonical_doi", "canonical_arxiv_id",
               "publication_status", "available_at", "identity_metadata")


def guard_statements() -> list[str]:
    paper_fields = ",".join("'" + value + "'" for value in PAPER_FIELDS)
    work_fields = ",".join("'" + value + "'" for value in WORK_FIELDS)
    statements = ["""
      CREATE OR REPLACE FUNCTION public.sclib_source_lifecycle_record_hash_v1(body jsonb)
      RETURNS text LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, public, pg_temp AS $$
        SELECT encode(public.digest(convert_to('{'||COALESCE(string_agg(
          to_jsonb(key)::text||':'||value::text,',' ORDER BY key COLLATE "C"),'')||'}','UTF8'),'sha256'),'hex')
        FROM jsonb_each(body-ARRAY['created_at','record_sha256'])
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_lifecycle_snapshot_hash_v1(kind text, body jsonb)
      RETURNS text {_SQL} IMMUTABLE AS $$
      DECLARE snapshot jsonb; fields text[];
      BEGIN
        IF jsonb_typeof(body) IS DISTINCT FROM 'object' THEN
          RAISE EXCEPTION 'source_lifecycle_object_snapshot_required' USING ERRCODE='23514';
        END IF;
        IF kind='claim' THEN snapshot:=body-ARRAY['created_at','updated_at'];
        ELSE
          fields:=CASE kind WHEN 'paper' THEN ARRAY[{paper_fields}] WHEN 'work' THEN ARRAY[{work_fields}] END;
          IF fields IS NULL THEN RAISE EXCEPTION 'source_lifecycle_snapshot_kind' USING ERRCODE='23514'; END IF;
          SELECT jsonb_object_agg(field,body->field) INTO snapshot FROM unnest(fields) field;
        END IF;
        RETURN encode(public.digest(convert_to(jsonb_build_object(
          'version','source-lifecycle-snapshot/1.0.0','kind',kind,'snapshot',snapshot)::text,'UTF8'),'sha256'),'hex');
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.{LOCK_FUNCTION}() RETURNS void {_SQL} AS $$
      BEGIN
        IF NOT pg_try_advisory_xact_lock({LOCK_KEY}) THEN
          RAISE EXCEPTION 'source_lifecycle_busy_retry_transaction' USING ERRCODE='55P03';
        END IF;
        UPDATE public.source_lifecycle_epoch SET epoch=epoch+1 WHERE id=1;
        IF NOT FOUND THEN RAISE EXCEPTION 'source_lifecycle_epoch_missing' USING ERRCODE='55000'; END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_lifecycle_immutable_v1() RETURNS trigger {_SQL} AS $$
      BEGIN RAISE EXCEPTION 'source lifecycle history is append-only: %',TG_TABLE_NAME USING ERRCODE='55000'; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_lifecycle_capture_v1() RETURNS trigger {_SQL} AS $$
      DECLARE prior public.source_lifecycle_events%ROWTYPE; kind text; current_status text;
        previous_status text; current_hash text; previous_hash text; identifier text; operation text;
      BEGIN
        kind:=CASE TG_TABLE_NAME WHEN 'papers' THEN 'paper' ELSE 'work' END;
        identifier:=to_jsonb(NEW)->>'id';
        current_status:=lower(btrim(to_jsonb(NEW)->>CASE kind WHEN 'paper' THEN 'status' ELSE 'publication_status' END));
        IF TG_OP='UPDATE' THEN
          previous_status:=lower(btrim(to_jsonb(OLD)->>CASE kind WHEN 'paper' THEN 'status' ELSE 'publication_status' END));
        END IF;
        SELECT * INTO prior FROM public.source_lifecycle_events
          WHERE (kind='paper' AND paper_id=identifier) OR (kind='work' AND work_id::text=identifier)
          ORDER BY revision DESC LIMIT 1;
        IF prior.id IS NULL AND current_status NOT IN ('retracted','withdrawn','corrected','disputed')
          AND COALESCE(previous_status,'') NOT IN ('retracted','withdrawn','corrected','disputed') THEN RETURN NULL; END IF;
        current_hash:=public.sclib_source_lifecycle_snapshot_hash_v1(kind,to_jsonb(NEW));
        IF TG_OP='UPDATE' THEN previous_hash:=public.sclib_source_lifecycle_snapshot_hash_v1(kind,to_jsonb(OLD)); END IF;
        IF prior.id IS NOT NULL AND current_hash=prior.snapshot_sha256 THEN RETURN NULL; END IF;
        PERFORM public.{LOCK_FUNCTION}();
        -- The epoch fences stale RR/SERIALIZABLE snapshots; source-row locking
        -- and unique predecessors serialize successive READ COMMITTED writes.
        SELECT * INTO prior FROM public.source_lifecycle_events
          WHERE (kind='paper' AND paper_id=identifier) OR (kind='work' AND work_id::text=identifier)
          ORDER BY revision DESC LIMIT 1;
        IF prior.id IS NOT NULL AND current_hash=prior.snapshot_sha256 THEN RETURN NULL; END IF;
        operation:=CASE WHEN previous_status IS DISTINCT FROM current_status AND TG_OP='UPDATE' THEN 'lifecycle_change'
          WHEN prior.id IS NULL THEN 'baseline_observed' ELSE 'catalogue_revision' END;
        INSERT INTO public.source_lifecycle_events(paper_id,work_id,revision,predecessor_id,old_snapshot_sha256,
          snapshot_sha256,prior_status,observed_status,event_kind)
        VALUES (CASE WHEN kind='paper' THEN identifier END,CASE WHEN kind='work' THEN identifier::uuid END,
          COALESCE(prior.revision,0)+1,prior.id,previous_hash,current_hash,previous_status,current_status,operation);
        RETURN NULL;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_lifecycle_event_v1() RETURNS trigger {_SQL} AS $$
      DECLARE prior public.source_lifecycle_events%ROWTYPE; actual jsonb; kind text;
      BEGIN
        IF pg_trigger_depth()<2 THEN RAISE EXCEPTION 'source_lifecycle_capture_trigger_only' USING ERRCODE='42501'; END IF;
        kind:=CASE WHEN NEW.paper_id IS NOT NULL THEN 'paper' ELSE 'work' END;
        IF kind='paper' THEN SELECT to_jsonb(p) INTO actual FROM public.papers p WHERE id=NEW.paper_id;
        ELSE SELECT to_jsonb(w) INTO actual FROM public.works w WHERE id=NEW.work_id; END IF;
        SELECT * INTO prior FROM public.source_lifecycle_events
          WHERE (NEW.paper_id IS NOT NULL AND paper_id=NEW.paper_id) OR (NEW.work_id IS NOT NULL AND work_id=NEW.work_id)
          ORDER BY revision DESC LIMIT 1;
        IF actual IS NULL OR NEW.snapshot_sha256 IS DISTINCT FROM public.sclib_source_lifecycle_snapshot_hash_v1(kind,actual)
          OR NEW.observed_status IS DISTINCT FROM lower(btrim(actual->>CASE kind WHEN 'paper' THEN 'status' ELSE 'publication_status' END))
          OR NEW.predecessor_id IS DISTINCT FROM prior.id OR NEW.revision<>COALESCE(prior.revision,0)+1
          OR (prior.id IS NOT NULL AND (NEW.old_snapshot_sha256 IS DISTINCT FROM prior.snapshot_sha256
            OR NEW.prior_status IS DISTINCT FROM prior.observed_status)) THEN
          RAISE EXCEPTION 'source_lifecycle_exact_current_revision_required' USING ERRCODE='23514';
        END IF;
        IF prior.id IS NULL AND NEW.observed_status NOT IN ('retracted','withdrawn','corrected','disputed')
          AND COALESCE(NEW.prior_status,'') NOT IN ('retracted','withdrawn','corrected','disputed') THEN
          RAISE EXCEPTION 'source_lifecycle_negative_root_required' USING ERRCODE='23514';
        END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_source_lifecycle_record_hash_v1(to_jsonb(NEW)); RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_lifecycle_review_writer_v1() RETURNS trigger {_SQL} AS $$
      BEGIN
        PERFORM public.sclib_research_integrity_lock_v1();
        PERFORM public.sclib_research_publication_lock_v1();
        PERFORM public.{LOCK_FUNCTION}(); RETURN NULL;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_lifecycle_review_v1() RETURNS trigger {_SQL} AS $$
      DECLARE event public.source_lifecycle_events%ROWTYPE; prior public.source_lifecycle_reviews%ROWTYPE;
        artifact public.evidence_artifacts%ROWTYPE; actual jsonb; claim jsonb; kind text; expected jsonb;
      BEGIN
        IF NOT public.sclib_research_publication_role_v1(NEW.reviewer_id,NEW.reviewer_grant_id,'reviewer') THEN
          RAISE EXCEPTION 'source_lifecycle_explicit_active_reviewer_required' USING ERRCODE='42501';
        END IF;
        SELECT * INTO event FROM public.source_lifecycle_events WHERE id=NEW.event_id;
        IF event.id IS NULL OR event.record_sha256 IS DISTINCT FROM NEW.event_sha256
          OR event.snapshot_sha256 IS DISTINCT FROM NEW.source_snapshot_sha256
          OR EXISTS(SELECT 1 FROM public.source_lifecycle_events WHERE predecessor_id=event.id) THEN
          RAISE EXCEPTION 'source_lifecycle_current_event_required' USING ERRCODE='23514';
        END IF;
        kind:=CASE WHEN event.paper_id IS NOT NULL THEN 'paper' ELSE 'work' END;
        IF kind='paper' THEN SELECT to_jsonb(p) INTO actual FROM public.papers p WHERE id=event.paper_id FOR SHARE;
        ELSE SELECT to_jsonb(w) INTO actual FROM public.works w WHERE id=event.work_id FOR SHARE; END IF;
        IF actual IS NULL OR public.sclib_source_lifecycle_snapshot_hash_v1(kind,actual)<>NEW.source_snapshot_sha256 THEN
          RAISE EXCEPTION 'source_lifecycle_source_revision_changed' USING ERRCODE='23514';
        END IF;
        IF NEW.claim_id IS NOT NULL THEN
          SELECT to_jsonb(c) INTO claim FROM public.material_claims c WHERE id=NEW.claim_id FOR SHARE;
          IF claim IS NULL OR public.sclib_source_lifecycle_snapshot_hash_v1('claim',claim) IS DISTINCT FROM NEW.claim_revision_sha256
            OR (kind='paper' AND claim->>'paper_id' IS DISTINCT FROM event.paper_id)
            OR (kind='work' AND claim->>'work_id' IS DISTINCT FROM event.work_id::text) THEN
            RAISE EXCEPTION 'source_lifecycle_exact_claim_revision_required' USING ERRCODE='23514';
          END IF;
        END IF;
        SELECT * INTO prior FROM public.source_lifecycle_reviews r WHERE r.event_id=NEW.event_id
          AND r.claim_id IS NOT DISTINCT FROM NEW.claim_id
          AND NOT EXISTS(SELECT 1 FROM public.source_lifecycle_reviews next WHERE next.supersedes_id=r.id);
        IF NEW.supersedes_id IS DISTINCT FROM prior.id THEN
          RAISE EXCEPTION 'source_lifecycle_exact_review_predecessor_required' USING ERRCODE='23514';
        END IF;
        SELECT * INTO artifact FROM public.evidence_artifacts WHERE id=NEW.review_artifact_id FOR SHARE;
        expected:=jsonb_build_object('event_id',NEW.event_id,'event_sha256',NEW.event_sha256,
          'source_snapshot_sha256',NEW.source_snapshot_sha256,'claim_id',NEW.claim_id,
          'claim_revision_sha256',NEW.claim_revision_sha256,'decision',NEW.decision,'reason_code',NEW.reason_code,
          'policy_version',NEW.policy_version,'reviewer_id',NEW.reviewer_id,'reviewer_grant_id',NEW.reviewer_grant_id,
          'scientific_acceptance',false,'ml_training_approved',false,'source_reinstatement',false);
        IF artifact.id IS NULL OR artifact.kind<>'review' OR artifact.record_sha256<>NEW.review_artifact_sha256
          OR artifact.hash_status<>'verified' OR artifact.bytes_sha256 IS DISTINCT FROM NEW.review_bytes_sha256
          OR artifact.record_sha256 IS DISTINCT FROM public.sclib_source_lifecycle_record_hash_v1(expected)
          OR artifact.bytes_sha256 IS DISTINCT FROM public.sclib_source_lifecycle_record_hash_v1(expected)
          OR artifact.metadata->'source_lifecycle_review' IS DISTINCT FROM expected THEN
          RAISE EXCEPTION 'source_lifecycle_exact_review_artifact_required' USING ERRCODE='23514';
        END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_source_lifecycle_record_hash_v1(to_jsonb(NEW)); RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_lifecycle_artifact_v1() RETURNS trigger {_SQL} AS $$
      BEGIN
        IF TG_OP='TRUNCATE' THEN
          IF EXISTS(SELECT 1 FROM public.source_lifecycle_reviews) THEN
            RAISE EXCEPTION 'source_lifecycle_review_artifact_immutable' USING ERRCODE='55000'; END IF;
          RETURN NULL;
        END IF;
        IF EXISTS(SELECT 1 FROM public.source_lifecycle_reviews WHERE review_artifact_id=OLD.id) THEN
          RAISE EXCEPTION 'source_lifecycle_review_artifact_immutable' USING ERRCODE='55000'; END IF;
        IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
      END $$
    """, "INSERT INTO public.source_lifecycle_epoch(id,epoch) VALUES (1,0)"]
    for name in TABLE_ORDER[1:]:
        statements.extend([
            f"CREATE TRIGGER sl56_immutable_row BEFORE UPDATE OR DELETE ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_source_lifecycle_immutable_v1()",
            f"CREATE TRIGGER sl56_immutable_truncate BEFORE TRUNCATE ON public.{name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_source_lifecycle_immutable_v1()",
        ])
    for name in ("papers", "works"):
        statements.append(f"CREATE TRIGGER sl56_capture AFTER INSERT OR UPDATE ON public.{name} "
                          "FOR EACH ROW EXECUTE FUNCTION public.sclib_source_lifecycle_capture_v1()")
    statements.extend([
        "CREATE TRIGGER sl56_event BEFORE INSERT ON public.source_lifecycle_events "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_source_lifecycle_event_v1()",
        "CREATE TRIGGER sl56_review_writer BEFORE INSERT ON public.source_lifecycle_reviews "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_source_lifecycle_review_writer_v1()",
        "CREATE TRIGGER sl56_review BEFORE INSERT ON public.source_lifecycle_reviews "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_source_lifecycle_review_v1()",
        "CREATE TRIGGER sl56_artifact_row BEFORE UPDATE OR DELETE ON public.evidence_artifacts "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_source_lifecycle_artifact_v1()",
        "CREATE TRIGGER sl56_artifact_truncate BEFORE TRUNCATE ON public.evidence_artifacts "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_source_lifecycle_artifact_v1()",
    ])
    return statements


def remove_parent_guards() -> list[str]:
    return ["DROP TRIGGER IF EXISTS sl56_capture ON public." + name for name in ("papers", "works")] + [
        "DROP TRIGGER IF EXISTS sl56_artifact_row ON public.evidence_artifacts",
        "DROP TRIGGER IF EXISTS sl56_artifact_truncate ON public.evidence_artifacts",
    ]


def register(metadata: sa.MetaData) -> dict[str, sa.Table]:
    tables = {}

    def uid(name, target=None, *, required=True):
        args = [sa.ForeignKey(f"{target}.id", ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=not required)

    def col(name, kind, *, required=True, default=None):
        return sa.Column(name, kind, nullable=not required, server_default=default)

    def ck(expression, name):
        return sa.CheckConstraint(expression, name=f"ck_sl56_{name}")

    def table(name, *items):
        checks = [ck(f"{item.name} IS NULL OR {item.name} ~ '^[0-9a-f]{{64}}$'", item.name) for item in items
                  if isinstance(item, sa.Column) and item.name.endswith("sha256")]
        tables[name] = sa.Table(name, metadata,
            sa.Column("id", UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            *items, col("record_sha256", sa.String(64), default="0" * 64),
            col("created_at", sa.DateTime(timezone=True), default=sa.func.clock_timestamp()),
            ck("record_sha256 ~ '^[0-9a-f]{64}$' AND isfinite(created_at)", "record_time"),
            *checks, sa.PrimaryKeyConstraint("id"))

    tables[TABLE_ORDER[0]] = sa.Table(TABLE_ORDER[0], metadata, col("id", sa.Integer), col("epoch", sa.BigInteger),
        sa.PrimaryKeyConstraint("id"), ck("id=1 AND epoch>=0", "epoch_singleton"))
    table("source_lifecycle_events",
        sa.Column("paper_id", sa.String(100), sa.ForeignKey("papers.id", ondelete="RESTRICT", onupdate="RESTRICT")),
        uid("work_id", "works", required=False), col("revision", sa.Integer),
        uid("predecessor_id", "source_lifecycle_events", required=False),
        col("old_snapshot_sha256", sa.String(64), required=False), col("snapshot_sha256", sa.String(64)),
        col("prior_status", sa.String(20), required=False), col("observed_status", sa.String(20)),
        col("event_kind", sa.String(30)),
        ck("(paper_id IS NULL)<>(work_id IS NULL) AND revision>=1", "source_revision"),
        ck("event_kind IN ('baseline_observed','lifecycle_change','catalogue_revision')", "event_kind"),
        ck("predecessor_id IS NULL OR predecessor_id<>id", "event_not_self"),
        ck("length(observed_status)>0", "event_status"),
        sa.UniqueConstraint("predecessor_id", name="uq_sl56_event_successor"),
        sa.UniqueConstraint("paper_id", "revision", name="uq_sl56_paper_revision"),
        sa.UniqueConstraint("work_id", "revision", name="uq_sl56_work_revision"),
        sa.Index("uq_sl56_paper_root", "paper_id", unique=True, postgresql_where=sa.text("predecessor_id IS NULL")),
        sa.Index("uq_sl56_work_root", "work_id", unique=True, postgresql_where=sa.text("predecessor_id IS NULL")))
    table("source_lifecycle_reviews", uid("event_id", "source_lifecycle_events"),
        col("event_sha256", sa.String(64)), col("source_snapshot_sha256", sa.String(64)),
        uid("claim_id", "material_claims", required=False), col("claim_revision_sha256", sa.String(64), required=False),
        uid("supersedes_id", "source_lifecycle_reviews", required=False), col("decision", sa.String(40)),
        col("policy_version", sa.String(80)), col("reason_code", sa.String(160)),
        uid("reviewer_id", "users"), uid("reviewer_grant_id", "research_role_grants"),
        uid("review_artifact_id", "evidence_artifacts"), col("review_artifact_sha256", sa.String(64)),
        col("review_bytes_sha256", sa.String(64)), col("request_key", sa.String(160)),
        ck("(claim_id IS NULL)=(claim_revision_sha256 IS NULL)", "claim_pair"),
        ck("decision IN ('retain_hold','requires_supersession')", "negative_decision_only"),
        ck(f"policy_version='{POLICY_VERSION}'", "review_policy"),
        ck("reason_code ~ '^[a-z][a-z0-9_]{0,159}$' AND request_key ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$'", "review_tokens"),
        ck("supersedes_id IS NULL OR supersedes_id<>id", "review_not_self"),
        sa.UniqueConstraint("supersedes_id", name="uq_sl56_review_successor"),
        sa.UniqueConstraint("reviewer_id", "request_key", name="uq_sl56_review_request"),
        sa.Index("uq_sl56_source_review_root", "event_id", unique=True,
                 postgresql_where=sa.text("claim_id IS NULL AND supersedes_id IS NULL")),
        sa.Index("uq_sl56_claim_review_root", "event_id", "claim_id", unique=True,
                 postgresql_where=sa.text("claim_id IS NOT NULL AND supersedes_id IS NULL")))
    last = tables[TABLE_ORDER[-1]]
    for name in PARENT_TABLES + TABLE_ORDER[:-1] + ("research_publication_actions",):
        last.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(last, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return tables
