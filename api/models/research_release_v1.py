"""Additive 0054 integrity capsules over existing canonical research objects.

Pins copy actual rows; they are neither a new scientific-object registry nor
scientific/public approval. Catalogue governance remains live and mutable.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from services.research_release_spec import FKS, SPEC

TABLE_ORDER = (
    "research_integrity_epoch", "research_releases", "research_release_pins", "research_release_notices",
)
SCIENTIFIC_TABLES = (
    "evidence_artifacts", "research_runs", "research_samples", "material_states", "structure_records",
    "research_events", "event_properties", "event_evidence", "snapshot_event_memberships",
    "ml_example_inputs", "material_claims", "claim_qc", "source_snapshots", "ml_dataset_snapshots", "ml_examples",
)
IMMUTABLE_SOURCE_TABLES = (
    "source_revisions", "source_captures", "claim_source_occurrences", "research_import_snapshots",
    "research_import_occurrences", "research_import_revisions", "research_import_memberships", "research_import_receipts",
)
CATALOGUE_TABLES = ("materials", "papers", "works", "paper_work_map", "chunks")
ALLOWED_TABLES = SCIENTIFIC_TABLES + IMMUTABLE_SOURCE_TABLES + CATALOGUE_TABLES
GUARDED_TABLES = SCIENTIFIC_TABLES + IMMUTABLE_SOURCE_TABLES
OWNED_RELATIONS = {
    "ml_dataset_snapshots": (("ml_examples", "dataset_snapshot_id"),),
    "ml_examples": (("ml_example_inputs", "example_id"),),
    "research_events": (("material_claims", "event_id"), ("event_properties", "event_id"),
                        ("event_evidence", "event_id")),
    "material_claims": (("claim_qc", "claim_id"),),
    "source_snapshots": (("snapshot_event_memberships", "snapshot_id"),),
    "papers": (("paper_work_map", "paper_id"),),
}
LOCK_KEY = 540017026
LOCK_FUNCTION = "sclib_research_integrity_lock_v1"
FUNCTION = LOCK_FUNCTION
FUNCTION_NAMES = (
    LOCK_FUNCTION, "sclib_research_writer_v1", "sclib_research_frozen_guard_v1",
    "sclib_research_cycle_guard_v1", "sclib_research_release_immutable_v1",
    "sclib_research_release_insert_v1", "sclib_research_pin_insert_v1",
    "sclib_research_release_complete_v1", "sclib_research_cycle_preflight_v1",
)
_SQL_SETTINGS = "LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp SET TimeZone = 'UTC'"


def guard_statements() -> list[str]:
    """Fixed, public-qualified SQL, shared by migrations and test metadata."""
    allowed = ",".join("'" + name + "'" for name in ALLOWED_TABLES)
    fk_rules = json.dumps(FKS, separators=(",", ":")).replace("'", "''")
    owned_rules = json.dumps({name: [[child, field, SPEC[child]["fields"][field]["type"]]
                                   for child, field in relations] for name, relations in OWNED_RELATIONS.items()},
                            separators=(",", ":")).replace("'", "''")
    sql = [f"""
      CREATE OR REPLACE FUNCTION public.{LOCK_FUNCTION}() RETURNS void {_SQL_SETTINGS} AS $$
      BEGIN
        IF NOT pg_try_advisory_xact_lock({LOCK_KEY}) THEN
          RAISE EXCEPTION 'research_integrity_busy_retry_transaction' USING ERRCODE='55P03';
        END IF;
        UPDATE public.research_integrity_epoch SET epoch=epoch+1 WHERE id=1;
        IF NOT FOUND THEN
          RAISE EXCEPTION 'research_integrity_epoch_missing' USING ERRCODE='55000';
        END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_writer_v1() RETURNS trigger {_SQL_SETTINGS} AS $$
      BEGIN PERFORM public.{LOCK_FUNCTION}(); RETURN NULL; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_release_immutable_v1() RETURNS trigger {_SQL_SETTINGS} AS $$
      BEGIN RAISE EXCEPTION 'research release history is append-only: %', TG_TABLE_NAME USING ERRCODE='55000'; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_frozen_guard_v1() RETURNS trigger {_SQL_SETTINGS} AS $$
      DECLARE owner_table text; owner_field text; item jsonb;
      BEGIN
        IF TG_OP='TRUNCATE' THEN
          IF EXISTS (SELECT 1 FROM public.research_release_pins WHERE table_name=TG_TABLE_NAME) THEN
            RAISE EXCEPTION 'frozen_research_table_truncate: %', TG_TABLE_NAME USING ERRCODE='55000';
          END IF;
          RETURN NULL;
        END IF;
        IF TG_OP IN ('UPDATE','DELETE') AND EXISTS (
          SELECT 1 FROM public.research_release_pins WHERE table_name=TG_TABLE_NAME AND row_id=to_jsonb(OLD)->>'id'
        ) THEN
          RAISE EXCEPTION 'frozen_research_row: %', TG_TABLE_NAME USING ERRCODE='55000';
        END IF;
        IF TG_TABLE_NAME='evidence_artifacts' AND TG_OP IN ('UPDATE','DELETE') AND EXISTS (
          SELECT 1 FROM public.research_release_notices WHERE review_artifact_id=(to_jsonb(OLD)->>'id')::uuid
        ) THEN
          RAISE EXCEPTION 'frozen_research_notice_review' USING ERRCODE='55000';
        END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(CASE TG_OP
          WHEN 'INSERT' THEN jsonb_build_array(to_jsonb(NEW)) WHEN 'DELETE' THEN jsonb_build_array(to_jsonb(OLD))
          ELSE jsonb_build_array(to_jsonb(OLD),to_jsonb(NEW)) END)
        LOOP
          FOR owner_table,owner_field IN SELECT owner,col FROM (VALUES
            ('material_claims','research_events','event_id'),
            ('material_claims','source_snapshots','source_snapshot_id'),
            ('claim_qc','material_claims','claim_id'),
            ('event_properties','research_events','event_id'),
            ('event_evidence','research_events','event_id'),
            ('snapshot_event_memberships','source_snapshots','snapshot_id'),
            ('ml_examples','ml_dataset_snapshots','dataset_snapshot_id'),
            ('ml_example_inputs','ml_examples','example_id')
          ) AS owners(child,owner,col) WHERE child=TG_TABLE_NAME
          LOOP
            IF EXISTS (SELECT 1 FROM public.research_release_pins
              WHERE table_name=owner_table AND row_id=item->>owner_field) THEN
              RAISE EXCEPTION 'frozen_research_owned_dependency: %', TG_TABLE_NAME USING ERRCODE='55000';
            END IF;
          END LOOP;
        END LOOP;
        IF TG_OP='DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_cycle_guard_v1() RETURNS trigger {_SQL_SETTINGS} AS $$
      DECLARE destination uuid; origin uuid; cyclic boolean; parent_field text;
      BEGIN
        IF TG_TABLE_NAME='event_evidence' THEN
          IF NEW.link_type<>'derives_from' THEN RETURN NULL; END IF;
          origin:=NEW.event_id; destination:=NEW.input_event_id;
          WITH RECURSIVE reachable(id) AS (
            SELECT destination UNION
            SELECT edge.input_event_id FROM public.event_evidence edge JOIN reachable r ON edge.event_id=r.id
              WHERE edge.link_type='derives_from'
          ) SELECT EXISTS (SELECT 1 FROM reachable WHERE id=origin) INTO cyclic;
        ELSE
          parent_field:=CASE TG_TABLE_NAME WHEN 'research_runs' THEN 'parent_run_id'
            WHEN 'structure_records' THEN 'parent_structure_id' ELSE 'supersedes_id' END;
          origin:=NEW.id; destination:=(to_jsonb(NEW)->>parent_field)::uuid;
          IF destination IS NULL THEN RETURN NULL; END IF;
          EXECUTE format('WITH RECURSIVE reachable(id) AS (SELECT $1::uuid UNION '
            'SELECT edge.%I FROM public.%I edge JOIN reachable r ON edge.id=r.id WHERE edge.%I IS NOT NULL) '
            'SELECT EXISTS (SELECT 1 FROM reachable WHERE id=$2)',parent_field,TG_TABLE_NAME,parent_field)
            INTO cyclic USING destination,origin;
        END IF;
        IF cyclic THEN RAISE EXCEPTION 'research_dependency_cycle: %',TG_TABLE_NAME USING ERRCODE='23514'; END IF;
        RETURN NULL;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_release_insert_v1() RETURNS trigger {_SQL_SETTINGS} AS $$
      BEGIN
        IF current_setting('transaction_isolation')<>'serializable' THEN
          RAISE EXCEPTION 'research_release_requires_serializable' USING ERRCODE='25000';
        END IF;
        NEW.assembly_xid:=pg_current_xact_id()::text::numeric; RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_pin_insert_v1() RETURNS trigger {_SQL_SETTINGS} AS $$
      DECLARE actual jsonb; assembly numeric; declared jsonb; key_column text;
      BEGIN
        IF NEW.table_name NOT IN ({allowed}) THEN
          RAISE EXCEPTION 'research_pin_table_unsupported' USING ERRCODE='23514';
        END IF;
        SELECT assembly_xid,manifest->'rows' INTO assembly,declared FROM public.research_releases WHERE id=NEW.release_id;
        IF assembly IS DISTINCT FROM pg_current_xact_id()::text::numeric THEN
          RAISE EXCEPTION 'research_release_assembly_closed' USING ERRCODE='55000';
        END IF;
        IF jsonb_typeof(declared) IS DISTINCT FROM 'array' THEN
          RAISE EXCEPTION 'research_pin_not_declared' USING ERRCODE='23514';
        END IF;
        IF (SELECT count(*) FROM jsonb_array_elements(declared) expected
          WHERE expected->>'table'=NEW.table_name AND expected->>'row_id'=NEW.row_id
            AND expected->'data'=NEW.row_data AND expected->>'row_sha256'=NEW.row_sha256)<>1 THEN
          RAISE EXCEPTION 'research_pin_not_declared' USING ERRCODE='23514';
        END IF;
        key_column:=CASE WHEN NEW.table_name='paper_work_map' THEN 'paper_id' ELSE 'id' END;
        EXECUTE format('SELECT to_jsonb(item) FROM public.%I item WHERE %I=$1::%s',NEW.table_name,key_column,
          CASE WHEN NEW.table_name IN ('materials','papers','paper_work_map','chunks') THEN 'text' ELSE 'uuid' END)
          INTO actual USING NEW.row_id;
        IF actual IS NULL OR actual IS DISTINCT FROM NEW.row_data THEN
          RAISE EXCEPTION 'research_pin_canonical_row_mismatch' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_release_complete_v1() RETURNS trigger {_SQL_SETTINGS} AS $$
      DECLARE target uuid; dataset uuid; body jsonb; expected_count bigint; actual_count bigint; matches bigint;
        pinned record; rule jsonb; field text; position integer; complete boolean; related jsonb;
        missing boolean; inventory jsonb; dependency record; identifier jsonb; receipt_count integer;
        fk_rules jsonb:='{fk_rules}'::jsonb; owned_rules jsonb:='{owned_rules}'::jsonb;
      BEGIN
        target:=(to_jsonb(NEW)->>CASE WHEN TG_TABLE_NAME='research_releases' THEN 'id' ELSE 'release_id' END)::uuid;
        SELECT manifest,dataset_snapshot_id INTO body,dataset FROM public.research_releases WHERE id=target;
        IF jsonb_typeof(body->'rows') IS DISTINCT FROM 'array' THEN
          RAISE EXCEPTION 'research_release_manifest_rows_missing' USING ERRCODE='23514';
        END IF;
        expected_count:=jsonb_array_length(body->'rows');
        IF expected_count>1000 OR octet_length(body::text)>8388608 THEN
          RAISE EXCEPTION 'research_release_closure_budget' USING ERRCODE='23514';
        END IF;
        IF EXISTS (SELECT 1 FROM jsonb_array_elements(body->'rows') expected
          WHERE jsonb_typeof(expected) IS DISTINCT FROM 'object'
            OR NOT (expected ?& ARRAY['table','row_id','data','row_sha256'])
            OR expected-ARRAY['table','row_id','data','row_sha256']<>'{{}}'::jsonb
            OR jsonb_typeof(expected->'table') IS DISTINCT FROM 'string'
            OR jsonb_typeof(expected->'row_id') IS DISTINCT FROM 'string'
            OR jsonb_typeof(expected->'data') IS DISTINCT FROM 'object'
            OR jsonb_typeof(expected->'row_sha256') IS DISTINCT FROM 'string')
          OR (SELECT count(DISTINCT (expected->>'table',expected->>'row_id'))
              FROM jsonb_array_elements(body->'rows') expected)<>expected_count THEN
          RAISE EXCEPTION 'research_release_manifest_rows_invalid' USING ERRCODE='23514';
        END IF;
        SELECT count(*) INTO actual_count FROM public.research_release_pins WHERE release_id=target;
        SELECT count(*) INTO matches FROM public.research_release_pins p
          JOIN jsonb_array_elements(body->'rows') expected ON expected->>'table'=p.table_name AND expected->>'row_id'=p.row_id
            AND expected->'data'=p.row_data AND expected->>'row_sha256'=p.row_sha256
          WHERE p.release_id=target;
        IF expected_count=0 OR expected_count<>actual_count OR matches<>actual_count THEN
          RAISE EXCEPTION 'research_release_incomplete_pin_manifest' USING ERRCODE='23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM public.research_release_pins WHERE release_id=target
          AND table_name='ml_dataset_snapshots' AND row_id=dataset::text) THEN
          RAISE EXCEPTION 'research_release_dataset_pin_missing' USING ERRCODE='23514';
        END IF;
        SELECT row_data INTO related FROM public.research_release_pins WHERE release_id=target
          AND table_name='ml_dataset_snapshots' AND row_id=dataset::text;
        SELECT count(*) INTO actual_count FROM public.research_release_pins WHERE release_id=target
          AND table_name='ml_examples' AND row_data->>'dataset_snapshot_id'=dataset::text;
        IF actual_count=0 OR actual_count>100 OR (related->>'row_count')::bigint<>actual_count THEN
          RAISE EXCEPTION 'research_release_dataset_count_mismatch' USING ERRCODE='23514';
        END IF;
        FOR pinned IN SELECT * FROM public.research_release_pins WHERE release_id=target LOOP
          FOR rule IN SELECT value FROM jsonb_array_elements(fk_rules->pinned.table_name) LOOP
            complete:=true;
            FOR field IN SELECT jsonb_array_elements_text(rule->0) LOOP
              IF pinned.row_data->field IS NULL OR pinned.row_data->field='null'::jsonb THEN complete:=false; END IF;
            END LOOP;
            IF NOT complete THEN CONTINUE; END IF;
            SELECT row_data INTO related FROM public.research_release_pins WHERE release_id=target
              AND table_name=rule->>1 AND row_id=pinned.row_data->>(rule->0->>0);
            IF related IS NULL THEN
              RAISE EXCEPTION 'research_release_missing_fk_dependency: %',pinned.table_name USING ERRCODE='23514';
            END IF;
            FOR position IN 0..jsonb_array_length(rule->0)-1 LOOP
              IF pinned.row_data->(rule->0->>position) IS DISTINCT FROM related->(rule->2->>position) THEN
                RAISE EXCEPTION 'research_release_composite_dependency_mismatch: %',pinned.table_name USING ERRCODE='23514';
              END IF;
            END LOOP;
          END LOOP;
          FOR rule IN SELECT value FROM jsonb_array_elements(COALESCE(owned_rules->pinned.table_name,'[]'::jsonb)) LOOP
            EXECUTE format('SELECT EXISTS(SELECT 1 FROM public.%I child WHERE child.%I=$1::%s AND NOT EXISTS '
              '(SELECT 1 FROM public.research_release_pins p WHERE p.release_id=$2 AND p.table_name=$3 '
              'AND p.row_id=child.%I::text))',rule->>0,rule->>1,
              CASE WHEN rule->>2='UUID' THEN 'uuid' ELSE 'text' END,
              CASE WHEN rule->>0='paper_work_map' THEN 'paper_id' ELSE 'id' END)
              INTO missing USING pinned.row_id,target,rule->>0;
            IF missing THEN
              RAISE EXCEPTION 'research_release_missing_owned_dependency: %',pinned.table_name USING ERRCODE='23514';
            END IF;
          END LOOP;
          IF pinned.table_name='research_import_receipts' THEN
            inventory:=pinned.row_data->'selection_manifest'->'row_ids';
            IF jsonb_typeof(inventory) IS DISTINCT FROM 'object' THEN
              RAISE EXCEPTION 'research_release_receipt_inventory_invalid' USING ERRCODE='23514';
            END IF;
            receipt_count:=0;
            FOR dependency IN SELECT * FROM jsonb_each(inventory) LOOP
              IF dependency.key NOT IN ('research_import_snapshots','research_import_occurrences',
                'research_import_revisions','research_import_memberships') OR jsonb_typeof(dependency.value)<>'array' THEN
                RAISE EXCEPTION 'research_release_receipt_inventory_invalid' USING ERRCODE='23514';
              END IF;
              receipt_count:=receipt_count+jsonb_array_length(dependency.value);
              IF receipt_count>1000 THEN
                RAISE EXCEPTION 'research_release_receipt_inventory_budget' USING ERRCODE='23514';
              END IF;
              FOR identifier IN SELECT value FROM jsonb_array_elements(dependency.value) LOOP
                IF jsonb_typeof(identifier)<>'string' OR length(identifier#>>'{{}}') NOT BETWEEN 1 AND 200
                  OR NOT EXISTS (SELECT 1 FROM public.research_release_pins WHERE release_id=target
                    AND table_name=dependency.key AND row_id=identifier#>>'{{}}') THEN
                  RAISE EXCEPTION 'research_release_missing_receipt_dependency' USING ERRCODE='23514';
                END IF;
              END LOOP;
            END LOOP;
          END IF;
        END LOOP;
        RETURN NULL;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_research_cycle_preflight_v1() RETURNS void {_SQL_SETTINGS} AS $$
      DECLARE relation text; parent_field text; cyclic boolean;
      BEGIN
        WITH RECURSIVE paths(origin,destination) AS (
          SELECT event_id,input_event_id FROM public.event_evidence WHERE link_type='derives_from' UNION
          SELECT p.origin,e.input_event_id FROM paths p JOIN public.event_evidence e ON e.event_id=p.destination
            WHERE e.link_type='derives_from'
        ) SELECT EXISTS(SELECT 1 FROM paths WHERE origin=destination) INTO cyclic;
        IF cyclic THEN RAISE EXCEPTION 'existing_research_dependency_cycle: event_evidence' USING ERRCODE='23514'; END IF;
        FOR relation,parent_field IN SELECT * FROM (VALUES ('research_runs','parent_run_id'),
          ('structure_records','parent_structure_id'),('research_events','supersedes_id')) AS parents(tab,col)
        LOOP
          EXECUTE format('WITH RECURSIVE paths(origin,destination) AS (SELECT id,%I FROM public.%I WHERE %I IS NOT NULL '
            'UNION SELECT p.origin,e.%I FROM paths p JOIN public.%I e ON e.id=p.destination WHERE e.%I IS NOT NULL) '
            'SELECT EXISTS(SELECT 1 FROM paths WHERE origin=destination)',parent_field,relation,parent_field,
            parent_field,relation,parent_field) INTO cyclic;
          IF cyclic THEN RAISE EXCEPTION 'existing_research_dependency_cycle: %',relation USING ERRCODE='23514'; END IF;
        END LOOP;
      END $$
    """, "INSERT INTO public.research_integrity_epoch(id,epoch) VALUES(1,0) ON CONFLICT(id) DO NOTHING"]
    # Statement-level locking also covers DELETE/TRUNCATE and empty statements.
    for name in GUARDED_TABLES + TABLE_ORDER[1:]:
        sql.append(f"CREATE TRIGGER rf54_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{name} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_writer_v1()")
    for name in SCIENTIFIC_TABLES:
        sql.extend([
            f"CREATE TRIGGER rf54_frozen_row BEFORE INSERT OR UPDATE OR DELETE ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_research_frozen_guard_v1()",
            f"CREATE TRIGGER rf54_frozen_truncate BEFORE TRUNCATE ON public.{name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_frozen_guard_v1()",
        ])
    for name in ("event_evidence", "research_runs", "structure_records", "research_events"):
        sql.append(f"CREATE TRIGGER rf54_cycle AFTER INSERT OR UPDATE ON public.{name} "
                   "FOR EACH ROW EXECUTE FUNCTION public.sclib_research_cycle_guard_v1()")
    for name in TABLE_ORDER[1:]:
        sql.extend([
            f"CREATE TRIGGER rf54_immutable_row BEFORE UPDATE OR DELETE ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.sclib_research_release_immutable_v1()",
            f"CREATE TRIGGER rf54_immutable_truncate BEFORE TRUNCATE ON public.{name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_research_release_immutable_v1()",
        ])
    sql.extend([
        "CREATE TRIGGER rf54_release_insert BEFORE INSERT ON public.research_releases "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_research_release_insert_v1()",
        "CREATE TRIGGER rf54_pin_insert BEFORE INSERT ON public.research_release_pins "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_research_pin_insert_v1()",
        "CREATE CONSTRAINT TRIGGER rf54_complete AFTER INSERT ON public.research_releases "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sclib_research_release_complete_v1()",
        "SELECT public.sclib_research_cycle_preflight_v1()",
    ])
    return sql


def remove_guard_statements() -> list[str]:
    result = []
    for name in GUARDED_TABLES:
        result.append(f"DROP TRIGGER IF EXISTS rf54_writer ON public.{name}")
        if name in SCIENTIFIC_TABLES:
            result.extend(f"DROP TRIGGER IF EXISTS {trigger} ON public.{name}"
                          for trigger in ("rf54_frozen_row", "rf54_frozen_truncate"))
        if name in ("event_evidence", "research_runs", "structure_records", "research_events"):
            result.append(f"DROP TRIGGER IF EXISTS rf54_cycle ON public.{name}")
    return result


def register(metadata: sa.MetaData) -> dict[str, sa.Table]:
    tables = {}

    def uid(name, target=None, *, required=True):
        args = [sa.ForeignKey(f"{target}.id", ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=not required)

    def col(name, kind, *, required=True, default=None):
        return sa.Column(name, kind, nullable=not required, server_default=default)

    def ck(expression, name):
        return sa.CheckConstraint(expression, name=f"ck_rr54_{name}")

    def table(name, *items):
        tables[name] = sa.Table(name, metadata, uid("id"), *items, sa.PrimaryKeyConstraint("id"))

    tables["research_integrity_epoch"] = sa.Table(
        "research_integrity_epoch", metadata, col("id", sa.Integer), col("epoch", sa.BigInteger),
        sa.PrimaryKeyConstraint("id"), ck("id=1 AND epoch>=0", "epoch_singleton"),
    )
    table(
        "research_releases", uid("dataset_snapshot_id", "ml_dataset_snapshots"), col("manifest", JSONB),
        col("manifest_sha256", sa.String(64)), col("bundle_sha256", sa.String(64)),
        col("closure_policy_version", sa.String(100)), col("scientific_acceptance", sa.Boolean, default=sa.false()),
        col("public_release", sa.Boolean, default=sa.false()), col("assembly_xid", sa.Numeric, default=sa.text("0")),
        col("created_at", sa.DateTime(timezone=True), default=sa.func.now()),
        sa.UniqueConstraint("manifest_sha256", name="uq_rr54_manifest"),
        ck("manifest_sha256 ~ '^[0-9a-f]{64}$' AND bundle_sha256 ~ '^[0-9a-f]{64}$'", "release_hashes"),
        ck("jsonb_typeof(manifest)='object'", "manifest_object"),
        ck("scientific_acceptance=false AND public_release=false", "integrity_only"),
        ck("btrim(closure_policy_version)<>'' AND isfinite(created_at) AND assembly_xid>0", "release_labels"),
    )
    table(
        "research_release_pins", uid("release_id", "research_releases"), col("table_name", sa.String(100)),
        col("row_id", sa.String(200)), col("row_data", JSONB), col("row_sha256", sa.String(64)),
        sa.UniqueConstraint("release_id", "table_name", "row_id", name="uq_rr54_release_row"),
        ck("table_name IN (" + ",".join("'" + name + "'" for name in ALLOWED_TABLES) + ")", "pin_table"),
        ck("btrim(row_id)<>'' AND jsonb_typeof(row_data)='object'", "pin_object"),
        ck("row_sha256 ~ '^[0-9a-f]{64}$'", "pin_hash"),
        sa.Index("idx_rr54_pinned_object", "table_name", "row_id"),
    )
    table(
        "research_release_notices", uid("release_id", "research_releases"), col("kind", sa.String(20)),
        uid("successor_release_id", "research_releases", required=False), uid("review_artifact_id"),
        col("review_artifact_kind", sa.String(30), default="review"), col("review_sha256", sa.String(64)),
        col("reason_code", sa.String(160)), col("record_sha256", sa.String(64)),
        col("created_at", sa.DateTime(timezone=True), default=sa.func.now()),
        sa.ForeignKeyConstraint(["review_artifact_id", "review_artifact_kind"],
                                ["evidence_artifacts.id", "evidence_artifacts.kind"],
                                ondelete="RESTRICT", onupdate="RESTRICT", name="fk_rr54_notice_review_kind"),
        ck("kind IN ('superseded','withdrawn','correction') AND review_artifact_kind='review'", "notice_kind"),
        ck("(kind='superseded' AND successor_release_id IS NOT NULL) OR kind<>'superseded'", "notice_successor"),
        ck("successor_release_id IS NULL OR successor_release_id<>release_id", "notice_not_self"),
        ck("review_sha256 ~ '^[0-9a-f]{64}$' AND record_sha256 ~ '^[0-9a-f]{64}$'", "notice_hashes"),
        ck("btrim(reason_code)<>'' AND isfinite(created_at)", "notice_reason"),
        sa.Index("idx_rr54_notice_release", "release_id"),
    )
    # Last new table follows every controlled table during metadata.create_all.
    # Migrations create only TABLE_ORDER explicitly, against existing parents.
    last = tables[TABLE_ORDER[-1]]
    for name in ALLOWED_TABLES + TABLE_ORDER[:-1]:
        last.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(last, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return tables
