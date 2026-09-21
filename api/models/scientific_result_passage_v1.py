"""Reviewed exact result-to-original-passage links.

The ledger binds immutable extraction and passage revisions through closed,
hash-only claim/sample identities.  It records a review decision; it does not
copy source text, grant source rights, establish causality, or confer general
scientific acceptance.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

TABLE = "scientific_result_passage_links"
VERSION = "scientific-result-passage-link/1.0.0"
CLAIM_VERSION = "scientific-claim-identity/1.0.0"
SAMPLE_VERSION = "scientific-sample-identity/1.0.0"
FUNCTIONS = (
    ("sclib_scientific_result_passage_hash_v1", "jsonb"),
    ("sclib_scientific_result_passage_insert_v1", ""),
    ("sclib_scientific_result_passage_immutable_v1", ""),
)
PARENTS = (
    "users", "research_role_grants", "papers", "rag_extraction_revisions",
    "rag_evidence_revisions",
)


def guards():
    return [
        """
        CREATE OR REPLACE FUNCTION public.sclib_scientific_result_passage_hash_v1(body jsonb)
        RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
          SELECT encode(public.digest(convert_to((body-ARRAY['created_at','record_sha256'])::text,'UTF8'),'sha256'),'hex')
        $$
        """,
        """
        CREATE OR REPLACE FUNCTION public.sclib_scientific_result_passage_immutable_v1()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
        BEGIN
          RAISE EXCEPTION 'scientific result-passage history is append-only' USING ERRCODE='55000';
        END $$
        """,
        f"""
        CREATE OR REPLACE FUNCTION public.sclib_scientific_result_passage_insert_v1()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC' AS $$
        DECLARE parent public.rag_extraction_revisions%ROWTYPE;
          passage public.rag_evidence_revisions%ROWTYPE;
          prior public.{TABLE}%ROWTYPE;
          expected_claim text;
          expected_sample text;
          current_source text;
        BEGIN
          PERFORM public.sclib_research_publication_lock_v1();
          IF NOT public.sclib_research_publication_role_v1(
              NEW.actor_user_id,NEW.actor_grant_id,'reviewer') THEN
            RAISE EXCEPTION 'result_passage_current_reviewer_required' USING ERRCODE='42501';
          END IF;
          SELECT * INTO parent FROM public.rag_extraction_revisions
            WHERE id=NEW.parent_result_revision_id;
          SELECT * INTO passage FROM public.rag_evidence_revisions
            WHERE id=NEW.source_evidence_revision_id;
          IF parent.id IS NULL OR passage.id IS NULL
            OR parent.record_sha256<>public.sclib_rag_evidence_record_hash_v1(to_jsonb(parent))
            OR passage.record_sha256<>public.sclib_rag_evidence_record_hash_v1(to_jsonb(passage))
            OR NEW.parent_result_sha256<>parent.record_sha256
            OR NEW.source_evidence_record_sha256<>passage.record_sha256
            OR NEW.source_content_sha256<>passage.content_sha256
            OR NEW.paper_id<>parent.paper_id OR NEW.paper_id<>passage.paper_id
            OR NEW.source_snapshot_sha256<>parent.source_snapshot_sha256
            OR NEW.source_snapshot_sha256<>passage.source_snapshot_sha256
            OR passage.chunk_kind<>'original_passage'
            OR passage.parent_extraction_revision_id IS NOT NULL
            OR passage.permission_status='restricted' THEN
            RAISE EXCEPTION 'result_passage_exact_evidence_required' USING ERRCODE='23514';
          END IF;
          SELECT public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p))
            INTO current_source FROM public.papers p WHERE p.id=NEW.paper_id;
          IF current_source IS DISTINCT FROM NEW.source_snapshot_sha256
            OR NOT EXISTS(SELECT 1 FROM public.chunk_evidence_current c
              WHERE c.chunk_id=passage.chunk_key AND c.evidence_revision_id=passage.id)
            OR NOT EXISTS(SELECT 1 FROM public.chunk_evidence_current c
              JOIN public.rag_evidence_revisions e ON e.id=c.evidence_revision_id
              WHERE e.parent_extraction_revision_id=parent.id
                AND e.paper_id=parent.paper_id
                AND e.source_snapshot_sha256=parent.source_snapshot_sha256
                AND e.chunk_kind='derived_fact'
                AND e.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(e))) THEN
            RAISE EXCEPTION 'result_passage_current_inputs_required' USING ERRCODE='23514';
          END IF;
          expected_claim:=jsonb_build_object(
            'version','{CLAIM_VERSION}',
            'parent_result_revision_id',parent.id::text,
            'parent_result_sha256',parent.record_sha256,
            'input_record_sha256',parent.input_record_sha256,
            'projection_sha256',encode(public.digest(convert_to(parent.projection_json::text,'UTF8'),'sha256'),'hex'))::text;
          expected_sample:=jsonb_build_object(
            'version','{SAMPLE_VERSION}',
            'parent_result_revision_id',parent.id::text,
            'input_record_sha256',parent.input_record_sha256,
            'scope','exact_retained_result_record')::text;
          IF NEW.claim_identity_json IS DISTINCT FROM expected_claim
            OR NEW.sample_identity_json IS DISTINCT FROM expected_sample
            OR NEW.claim_identity_sha256<>encode(public.digest(convert_to(expected_claim,'UTF8'),'sha256'),'hex')
            OR NEW.sample_identity_sha256<>encode(public.digest(convert_to(expected_sample,'UTF8'),'sha256'),'hex')
            OR NEW.source_locator_sha256<>encode(public.digest(convert_to(passage.source_locator::text,'UTF8'),'sha256'),'hex') THEN
            RAISE EXCEPTION 'result_passage_closed_identity_required' USING ERRCODE='23514';
          END IF;
          IF NEW.predecessor_id IS NULL THEN
            IF NEW.action<>'establish' OR NEW.predecessor_sha256 IS NOT NULL
              OR EXISTS(SELECT 1 FROM public.{TABLE} h
                WHERE h.parent_result_revision_id=NEW.parent_result_revision_id
                  AND h.source_evidence_revision_id=NEW.source_evidence_revision_id) THEN
              RAISE EXCEPTION 'result_passage_root_required' USING ERRCODE='23514';
            END IF;
          ELSE
            SELECT * INTO prior FROM public.{TABLE} WHERE id=NEW.predecessor_id;
            IF prior.id IS NULL OR NEW.predecessor_sha256<>prior.record_sha256
              OR EXISTS(SELECT 1 FROM public.{TABLE} successor WHERE successor.predecessor_id=prior.id)
              OR prior.parent_result_revision_id<>NEW.parent_result_revision_id
              OR prior.source_evidence_revision_id<>NEW.source_evidence_revision_id
              OR prior.parent_result_sha256<>NEW.parent_result_sha256
              OR prior.source_evidence_record_sha256<>NEW.source_evidence_record_sha256
              OR prior.source_content_sha256<>NEW.source_content_sha256
              OR prior.source_locator_sha256<>NEW.source_locator_sha256
              OR prior.claim_identity_sha256<>NEW.claim_identity_sha256
              OR prior.sample_identity_sha256<>NEW.sample_identity_sha256
              OR prior.claim_identity_json<>NEW.claim_identity_json
              OR prior.sample_identity_json<>NEW.sample_identity_json
              OR prior.paper_id<>NEW.paper_id
              OR prior.source_snapshot_sha256<>NEW.source_snapshot_sha256
              OR (prior.action='establish' AND NEW.action<>'withdraw')
              OR (prior.action='withdraw' AND NEW.action<>'establish') THEN
              RAISE EXCEPTION 'result_passage_exact_head_required' USING ERRCODE='23514';
            END IF;
          END IF;
          IF (SELECT count(*) FROM public.{TABLE}
              WHERE parent_result_revision_id=NEW.parent_result_revision_id
                AND source_evidence_revision_id=NEW.source_evidence_revision_id)>=100 THEN
            RAISE EXCEPTION 'result_passage_history_limit' USING ERRCODE='54000';
          END IF;
          NEW.created_at:=clock_timestamp();
          NEW.record_sha256:=public.sclib_scientific_result_passage_hash_v1(to_jsonb(NEW));
          RETURN NEW;
        END $$
        """,
        f"CREATE TRIGGER srp78_insert BEFORE INSERT ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.sclib_scientific_result_passage_insert_v1()",
        f"CREATE TRIGGER srp78_immutable BEFORE UPDATE OR DELETE ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.sclib_scientific_result_passage_immutable_v1()",
        f"CREATE TRIGGER srp78_no_truncate BEFORE TRUNCATE ON public.{TABLE} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_scientific_result_passage_immutable_v1()",
    ]


def register(metadata):
    def uid(name, target=None, nullable=False):
        args = [sa.ForeignKey(target + ".id", ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=nullable)

    table = sa.Table(
        TABLE, metadata,
        uid("id"),
        sa.Column("version", sa.String(60), nullable=False),
        uid("actor_user_id", "users"),
        uid("actor_grant_id", "research_role_grants"),
        uid("parent_result_revision_id", "rag_extraction_revisions"),
        sa.Column("parent_result_sha256", sa.String(64), nullable=False),
        uid("source_evidence_revision_id", "rag_evidence_revisions"),
        sa.Column("source_evidence_record_sha256", sa.String(64), nullable=False),
        sa.Column("source_content_sha256", sa.String(64), nullable=False),
        sa.Column("source_locator_sha256", sa.String(64), nullable=False),
        sa.Column("paper_id", sa.String(100), sa.ForeignKey("papers.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
        sa.Column("source_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("claim_identity_json", sa.Text, nullable=False),
        sa.Column("claim_identity_sha256", sa.String(64), nullable=False),
        sa.Column("sample_identity_json", sa.Text, nullable=False),
        sa.Column("sample_identity_sha256", sa.String(64), nullable=False),
        sa.Column("relation", sa.String(40), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        uid("predecessor_id", TABLE, nullable=True),
        sa.Column("predecessor_sha256", sa.String(64), nullable=True),
        sa.Column("request_key", sa.String(160), nullable=False),
        sa.Column("record_sha256", sa.String(64), nullable=False, server_default="0" * 64),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_user_id", "request_key", name="uq_srp78_actor_request"),
        sa.UniqueConstraint("predecessor_id", name="uq_srp78_predecessor"),
        sa.CheckConstraint(f"version='{VERSION}'", name="ck_srp78_version"),
        sa.CheckConstraint("relation='exact_result_original_passage'", name="ck_srp78_relation"),
        sa.CheckConstraint("action IN ('establish','withdraw')", name="ck_srp78_action"),
        sa.CheckConstraint("(action='establish' AND reason_code='reviewed_exact_claim_sample_passage') OR (action='withdraw' AND reason_code='review_withdrawn')", name="ck_srp78_reason"),
        sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$'", name="ck_srp78_request"),
        sa.CheckConstraint("parent_result_sha256 ~ '^[0-9a-f]{64}$' AND source_evidence_record_sha256 ~ '^[0-9a-f]{64}$' AND source_content_sha256 ~ '^[0-9a-f]{64}$' AND source_locator_sha256 ~ '^[0-9a-f]{64}$' AND source_snapshot_sha256 ~ '^[0-9a-f]{64}$' AND claim_identity_sha256 ~ '^[0-9a-f]{64}$' AND sample_identity_sha256 ~ '^[0-9a-f]{64}$' AND record_sha256 ~ '^[0-9a-f]{64}$'", name="ck_srp78_hashes"),
        sa.CheckConstraint("(predecessor_id IS NULL)=(predecessor_sha256 IS NULL)", name="ck_srp78_predecessor_pair"),
        sa.Index("idx_srp78_pair", "parent_result_revision_id", "source_evidence_revision_id", "created_at"),
    )
    for statement in guards():
        sa.event.listen(table, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return table
