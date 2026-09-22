"""0062 bounded private rollback artifacts, not science or source-use approval."""
from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = ("index_generation_epoch", "index_generations", "index_generation_members",
               "index_generation_validations", "index_activation_events", "index_active_pointer")
HISTORY_TABLES = TABLE_ORDER[1:5]
LOCK_KEY = 620017026
PROFILE = {"version": "sclib-index-profile/1.0.0", "provider": "google-vertex-ai", "model": "text-embedding-005",
           "output_dimensionality": 768, "document_task": "RETRIEVAL_DOCUMENT", "query_task": "RETRIEVAL_QUERY"}
PAPER_FIELDS = ("id", "source", "arxiv_id", "doi", "external_id", "id_scheme", "related_paper_id", "title", "authors",
                "date_submitted", "date_published", "materials_extracted", "material_family", "citation_count",
                "publication_ref", "quality_flags")
FUNCTION_SIGNATURES = (
    ("sclib_index_hash_v1", "jsonb"), ("sclib_index_record_hash_v1", "jsonb"),
    ("sclib_index_lock_v1", ""), ("sclib_index_immutable_v1", ""),
    ("sclib_index_paper_snapshot_v1", "jsonb"), ("sclib_index_revision_hash_v1", "jsonb"),
    ("sclib_index_manifest_v1", "uuid"), ("sclib_index_manifest_hash_v1", "jsonb"),
    ("sclib_index_validation_fresh_v1", "timestamp with time zone, timestamp with time zone"), ("sclib_index_insert_v1", ""),
    ("sclib_index_observation_fresh_v1", "timestamp with time zone, timestamp with time zone"),
    ("sclib_index_activate_v1", ""), ("sclib_index_pointer_v1", ""),
)
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"


def guard_statements():
    paper_fields = ",".join("'" + key + "'" for key in PAPER_FIELDS)
    profile = json.dumps(PROFILE)
    statements = ["""
      CREATE OR REPLACE FUNCTION public.sclib_index_hash_v1(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT encode(public.digest(convert_to(body::text,'UTF8'),'sha256'),'hex')
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_index_record_hash_v1(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT public.sclib_index_hash_v1(body-ARRAY['created_at','record_sha256'])
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_index_lock_v1() RETURNS void {_SQL} AS $$
      BEGIN
        PERFORM public.sclib_research_integrity_lock_v1();
        PERFORM public.sclib_source_lifecycle_lock_v1();
        IF NOT pg_try_advisory_xact_lock({LOCK_KEY}) THEN
          RAISE EXCEPTION 'index_generation_busy_retry_transaction' USING ERRCODE='55P03'; END IF;
        UPDATE public.index_generation_epoch SET epoch=epoch+1 WHERE id=1;
        IF NOT FOUND THEN RAISE EXCEPTION 'index_generation_epoch_missing' USING ERRCODE='55000'; END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_index_immutable_v1() RETURNS trigger {_SQL} AS $$
      BEGIN RAISE EXCEPTION 'index generation history is append-only' USING ERRCODE='55000'; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_index_paper_snapshot_v1(body jsonb) RETURNS jsonb
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT jsonb_object_agg(key,body->key) FROM unnest(ARRAY[{paper_fields}]) key
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_index_revision_hash_v1(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT public.sclib_index_hash_v1(jsonb_object_agg(key,body->key)) FROM unnest(ARRAY[
          'chunk_key','paper_id','snapshot_sha256','evidence_revision_id','evidence_record_sha256',
          'receipt_id','receipt_record_sha256','source_snapshot_sha256','parser_version','chunker_version',
          'content_sha256','vector_sha256']) key
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_index_manifest_v1(identifier uuid) RETURNS jsonb
      LANGUAGE sql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT COALESCE(jsonb_agg(jsonb_build_object('vector_id',vector_id,'content_sha256',content_sha256,
          'vector_sha256',vector_sha256) ORDER BY vector_id COLLATE "C"),'[]'::jsonb)
        FROM public.index_generation_members WHERE generation_id=identifier
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_index_manifest_hash_v1(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT encode(public.digest(convert_to(COALESCE(string_agg((value->>'vector_id')||E'\\t'||
          (value->>'content_sha256')||E'\\t'||(value->>'vector_sha256')||E'\\n','' ORDER BY value->>'vector_id' COLLATE "C"),''),
          'UTF8'),'sha256'),'hex') FROM jsonb_array_elements(body)
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_index_validation_fresh_v1(recorded_at timestamptz, checked_at timestamptz) RETURNS boolean
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT recorded_at IS NOT NULL AND checked_at IS NOT NULL AND isfinite(recorded_at) AND isfinite(checked_at)
          AND recorded_at<=checked_at AND recorded_at>=checked_at-interval '15 minutes'
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_index_observation_fresh_v1(observed_at timestamptz, checked_at timestamptz) RETURNS boolean
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT observed_at IS NOT NULL AND checked_at IS NOT NULL AND isfinite(observed_at) AND isfinite(checked_at)
          AND observed_at<=checked_at+interval '30 seconds' AND observed_at>=checked_at-interval '15 minutes'
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_index_insert_v1() RETURNS trigger {_SQL} AS $$
      DECLARE g public.index_generations%ROWTYPE; e public.rag_evidence_revisions%ROWTYPE;
        r public.embedding_completion_receipts%ROWTYPE; v public.index_generation_validations%ROWTYPE;
        prior public.index_activation_events%ROWTYPE; actual jsonb; paper jsonb; expected jsonb; observed jsonb;
        item jsonb; field text; total integer; bytes bigint; source_hash text;
      BEGIN
        PERFORM public.sclib_index_lock_v1();
        IF TG_TABLE_NAME='index_generations' THEN
          IF NEW.profile IS DISTINCT FROM '{profile}'::jsonb OR jsonb_typeof(NEW.resource) IS DISTINCT FROM 'object'
            OR NEW.resource-ARRAY['backend','project','location','index_resource','endpoint_resource','deployed_index_id','distance_measure','feature_norm']<>'{{}}'::jsonb
            OR NOT NEW.resource ?& ARRAY['backend','project','location','index_resource','endpoint_resource','deployed_index_id','distance_measure','feature_norm']
            OR COALESCE(NEW.resource->>'backend','') NOT IN ('vertex-public','disposable')
            OR NEW.resource->>'distance_measure' IS DISTINCT FROM 'COSINE_DISTANCE'
            OR NEW.resource->>'feature_norm' IS DISTINCT FROM 'NONE' THEN
            RAISE EXCEPTION 'index_generation_closed_profile_resource_required' USING ERRCODE='23514'; END IF;
          FOR field IN SELECT jsonb_object_keys(NEW.resource) LOOP
            IF jsonb_typeof(NEW.resource->field)<>'string' OR length(NEW.resource->>field) NOT BETWEEN 1 AND 500
              OR btrim(NEW.resource->>field)='' OR (NEW.resource->>field) ~ '[[:cntrl:]]' THEN
              RAISE EXCEPTION 'index_generation_resource_invalid' USING ERRCODE='23514'; END IF;
          END LOOP;
        ELSIF TG_TABLE_NAME='index_generation_members' THEN
          IF NEW.parser_version !~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{{0,159}}$'
            OR lower(NEW.parser_version) IN ('unknown','legacy_unknown','unrecorded') THEN
            RAISE EXCEPTION 'index_generation_actual_parser_label_required' USING ERRCODE='23514'; END IF;
          IF octet_length(NEW.vector_bytes)<>3072 OR NEW.vector_bytes=decode(repeat('00',3072),'hex') THEN
            RAISE EXCEPTION 'index_generation_canonical_vector_required' USING ERRCODE='23514'; END IF;
          FOR total IN 0..767 LOOP
            IF ((get_byte(NEW.vector_bytes,total*4)&127)=127 AND (get_byte(NEW.vector_bytes,total*4+1)&128)=128)
              OR substring(NEW.vector_bytes FROM total*4+1 FOR 4)=decode('80000000','hex') THEN
              RAISE EXCEPTION 'index_generation_canonical_vector_required' USING ERRCODE='23514'; END IF;
          END LOOP;
          SELECT * INTO g FROM public.index_generations WHERE id=NEW.generation_id;
          IF EXISTS(SELECT 1 FROM public.index_generation_validations WHERE generation_id=g.id AND outcome='validated') THEN
            RAISE EXCEPTION 'index_generation_members_sealed' USING ERRCODE='23514'; END IF;
          SELECT to_jsonb(c),to_jsonb(p) INTO actual,paper FROM public.chunks c JOIN public.papers p ON p.id=c.paper_id WHERE c.id=NEW.chunk_key;
          SELECT * INTO e FROM public.rag_evidence_revisions WHERE id=NEW.evidence_revision_id;
          SELECT * INTO r FROM public.embedding_completion_receipts WHERE id=NEW.receipt_id;
          source_hash:=public.sclib_source_lifecycle_snapshot_hash_v1('paper',paper);
          IF g.id IS NULL OR actual IS NULL OR e.id IS NULL OR r.id IS NULL
            OR NEW.snapshot_json IS DISTINCT FROM actual
            OR NEW.paper_snapshot_json IS DISTINCT FROM public.sclib_index_paper_snapshot_v1(paper)
            OR NEW.paper_id IS DISTINCT FROM actual->>'paper_id' OR NEW.chunk_key IS DISTINCT FROM e.chunk_key
            OR NOT EXISTS(SELECT 1 FROM public.chunk_evidence_current WHERE chunk_id=NEW.chunk_key AND evidence_revision_id=e.id)
            OR e.source_snapshot_sha256 IS DISTINCT FROM source_hash OR NEW.source_snapshot_sha256 IS DISTINCT FROM source_hash
            OR NEW.evidence_record_sha256<>e.record_sha256 OR e.record_sha256<>public.sclib_rag_evidence_record_hash_v1(to_jsonb(e))
            OR NEW.receipt_record_sha256<>r.record_sha256 OR r.record_sha256<>public.sclib_embedding_receipt_hash_v1(to_jsonb(r))
            OR r.evidence_revision_id<>e.id OR r.chunk_key<>NEW.chunk_key OR r.evidence_record_sha256<>e.record_sha256
            OR r.chunk_binding_sha256<>e.chunk_binding_sha256 OR e.chunk_binding_sha256<>public.sclib_rag_chunk_hash_v1(actual)
            OR NEW.content_sha256<>r.content_sha256 OR NEW.content_sha256<>e.content_sha256
            OR NEW.content_sha256<>encode(public.digest(convert_to(actual->>'text','UTF8'),'sha256'),'hex')
            OR NEW.vector_sha256<>r.vector_sha256 OR NEW.vector_sha256<>encode(public.digest(NEW.vector_bytes,'sha256'),'hex')
            OR NEW.chunker_version IS DISTINCT FROM e.rendering_version
            OR NOT public.sclib_embedding_metadata_valid_v1(r.metadata_json,NEW.content_sha256,NEW.vector_sha256)
            OR NEW.snapshot_sha256<>public.sclib_index_hash_v1(jsonb_build_object('chunk',NEW.snapshot_json,'paper',NEW.paper_snapshot_json))
            OR NEW.chunk_revision_sha256<>public.sclib_index_revision_hash_v1(to_jsonb(NEW))
            OR NEW.vector_id<>'ig62_'||replace(NEW.generation_id::text,'-','')||'_'||NEW.chunk_revision_sha256 THEN
            RAISE EXCEPTION 'index_generation_exact_current_member_required' USING ERRCODE='23514'; END IF;
          SELECT count(*),COALESCE(sum(octet_length(snapshot_json::text)+octet_length(paper_snapshot_json::text)),0)
            INTO total,bytes FROM public.index_generation_members WHERE generation_id=g.id;
          IF total>=g.expected_member_count OR total>=1000 OR bytes+octet_length(NEW.snapshot_json::text)+octet_length(NEW.paper_snapshot_json::text)>16777216 THEN
            RAISE EXCEPTION 'index_generation_pilot_scope_limit' USING ERRCODE='23514'; END IF;
        ELSIF TG_TABLE_NAME='index_generation_validations' THEN
          SELECT * INTO g FROM public.index_generations WHERE id=NEW.generation_id;
          actual:=NEW.observation;
          IF g.id IS NULL OR jsonb_typeof(actual) IS DISTINCT FROM 'object' OR octet_length(actual::text)>1048576
            OR actual-ARRAY['version','observation_id','observed_at','resource','profile','adapter_version','full_inventory_observed','vectors']<>'{{}}'::jsonb
            OR NOT actual ?& ARRAY['version','observation_id','observed_at','resource','profile','adapter_version','full_inventory_observed','vectors']
            OR actual->>'version' IS DISTINCT FROM 'sclib-index-observation/1.0.0'
            OR jsonb_typeof(actual->'observation_id') IS DISTINCT FROM 'string'
            OR (actual->>'observation_id') !~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
            OR jsonb_typeof(actual->'observed_at') IS DISTINCT FROM 'string'
            OR (actual->>'observed_at') !~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}[.][0-9]{{6}}Z$'
            OR actual->'resource' IS DISTINCT FROM g.resource OR actual->'profile' IS DISTINCT FROM g.profile
            OR jsonb_typeof(actual->'adapter_version') IS DISTINCT FROM 'string' OR length(actual->>'adapter_version') NOT BETWEEN 1 AND 160
            OR btrim(actual->>'adapter_version')='' OR (actual->>'adapter_version') ~ '[[:cntrl:]]'
            OR jsonb_typeof(actual->'full_inventory_observed') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(actual->'vectors') IS DISTINCT FROM 'array' OR jsonb_array_length(actual->'vectors')>1000 THEN
            RAISE EXCEPTION 'index_generation_closed_observation_required' USING ERRCODE='23514'; END IF;
          FOR item IN SELECT value FROM jsonb_array_elements(actual->'vectors') LOOP
            IF jsonb_typeof(item) IS DISTINCT FROM 'object' OR item-ARRAY['vector_id','content_sha256','vector_sha256']<>'{{}}'::jsonb
              OR NOT item ?& ARRAY['vector_id','content_sha256','vector_sha256']
              OR jsonb_typeof(item->'vector_id') IS DISTINCT FROM 'string' OR length(item->>'vector_id') NOT BETWEEN 1 AND 200
              OR (item->>'vector_id') !~ '^[A-Za-z0-9_-]+$'
              OR jsonb_typeof(item->'content_sha256') IS DISTINCT FROM 'string' OR (item->>'content_sha256') !~ '^[0-9a-f]{{64}}$'
              OR jsonb_typeof(item->'vector_sha256') IS DISTINCT FROM 'string' OR (item->>'vector_sha256') !~ '^[0-9a-f]{{64}}$' THEN
              RAISE EXCEPTION 'index_generation_observation_vector_invalid' USING ERRCODE='23514'; END IF;
          END LOOP;
          SELECT count(DISTINCT value->>'vector_id'),COALESCE(jsonb_agg(value ORDER BY value->>'vector_id' COLLATE "C"),'[]'::jsonb)
            INTO total,observed FROM jsonb_array_elements(actual->'vectors');
          IF total<>jsonb_array_length(actual->'vectors') THEN
            RAISE EXCEPTION 'index_generation_observation_duplicate_id' USING ERRCODE='23514'; END IF;
          expected:=public.sclib_index_manifest_v1(g.id);
          IF jsonb_array_length(expected)<>g.expected_member_count OR public.sclib_index_manifest_hash_v1(expected)<>g.manifest_sha256 THEN
            RAISE EXCEPTION 'index_generation_incomplete_staging' USING ERRCODE='23514'; END IF;
          NEW.observed_manifest_sha256:=public.sclib_index_manifest_hash_v1(observed);
          NEW.observation_id:=(actual->>'observation_id')::uuid;
          NEW.observed_at:=(actual->>'observed_at')::timestamptz;
          IF to_char(NEW.observed_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')<>actual->>'observed_at'
            OR NOT public.sclib_index_observation_fresh_v1(NEW.observed_at,clock_timestamp()) THEN
            RAISE EXCEPTION 'index_generation_observation_not_fresh' USING ERRCODE='23514'; END IF;
          NEW.outcome:=CASE WHEN observed<>expected THEN 'rejected'
            ELSE 'validated' END;
        ELSE
          SELECT * INTO g FROM public.index_generations WHERE id=NEW.generation_id;
          SELECT * INTO v FROM public.index_generation_validations WHERE id=NEW.validation_id;
          SELECT * INTO prior FROM public.index_activation_events WHERE logical_index=NEW.logical_index ORDER BY event_number DESC LIMIT 1;
          IF g.id IS NULL OR v.id IS NULL OR g.logical_index<>NEW.logical_index OR v.generation_id<>g.id OR v.outcome<>'validated'
            OR NOT public.sclib_index_validation_fresh_v1(v.created_at,clock_timestamp())
            OR NOT public.sclib_index_observation_fresh_v1(v.observed_at,clock_timestamp())
            OR NEW.predecessor_id IS DISTINCT FROM prior.id OR NEW.event_number<>COALESCE(prior.event_number,0)+1
            OR (NEW.action='rollback' AND NOT EXISTS(SELECT 1 FROM public.index_activation_events WHERE logical_index=NEW.logical_index AND generation_id=g.id))
            OR public.sclib_index_manifest_hash_v1(public.sclib_index_manifest_v1(g.id))<>g.manifest_sha256 THEN
            RAISE EXCEPTION 'index_generation_activation_cas_or_validation_failed' USING ERRCODE='23514'; END IF;
          IF EXISTS(SELECT 1 FROM public.index_generation_members m LEFT JOIN public.papers p ON p.id=m.paper_id
            WHERE m.generation_id=g.id AND (p.id IS NULL OR lower(btrim(p.status)) IN ('corrected','retracted','disputed','withdrawn')
              OR m.source_snapshot_sha256 IS DISTINCT FROM public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p))
              OR EXISTS(SELECT 1 FROM public.source_lifecycle_events held WHERE held.paper_id=m.paper_id)
              OR EXISTS(SELECT 1 FROM public.paper_work_map mapping LEFT JOIN public.works work ON work.id=mapping.work_id
                WHERE mapping.paper_id=m.paper_id AND mapping.review_status='accepted' AND
                  (work.id IS NULL OR lower(btrim(work.publication_status)) IN ('corrected','retracted','disputed','withdrawn')
                    OR EXISTS(SELECT 1 FROM public.source_lifecycle_events held_work WHERE held_work.work_id=mapping.work_id)))
              OR EXISTS(SELECT 1 FROM public.rag_evidence_revisions restriction WHERE restriction.chunk_key=m.chunk_key AND restriction.permission_status='restricted'))) THEN
            RAISE EXCEPTION 'index_generation_current_source_hold' USING ERRCODE='23514'; END IF;
        END IF;
        NEW.created_at:=clock_timestamp(); NEW.record_sha256:=public.sclib_index_record_hash_v1(to_jsonb(NEW)); RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_index_activate_v1() RETURNS trigger {_SQL} AS $$
      BEGIN
        INSERT INTO public.index_active_pointer(logical_index,activation_event_id,generation_id)
          VALUES(NEW.logical_index,NEW.id,NEW.generation_id)
          ON CONFLICT(logical_index) DO UPDATE SET activation_event_id=EXCLUDED.activation_event_id,generation_id=EXCLUDED.generation_id;
        RETURN NULL;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_index_pointer_v1() RETURNS trigger {_SQL} AS $$
      BEGIN
        IF TG_OP IN ('DELETE','TRUNCATE') OR pg_trigger_depth()<2 THEN
          RAISE EXCEPTION 'index_generation_pointer_requires_activation_event' USING ERRCODE='55000'; END IF;
        IF NOT EXISTS(SELECT 1 FROM public.index_activation_events e WHERE e.id=NEW.activation_event_id
          AND e.logical_index=NEW.logical_index AND e.generation_id=NEW.generation_id
          AND e.event_number=(SELECT max(event_number) FROM public.index_activation_events WHERE logical_index=NEW.logical_index)) THEN
          RAISE EXCEPTION 'index_generation_pointer_head_required' USING ERRCODE='23514'; END IF;
        RETURN NEW;
      END $$
    """]
    for name in HISTORY_TABLES:
        statements.extend([
            f"CREATE TRIGGER ig62_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_index_insert_v1()",
            f"CREATE TRIGGER ig62_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_index_immutable_v1()",
            f"CREATE TRIGGER ig62_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_index_immutable_v1()",
        ])
    statements.extend([
        "CREATE TRIGGER ig62_activate AFTER INSERT ON public.index_activation_events FOR EACH ROW EXECUTE FUNCTION public.sclib_index_activate_v1()",
        "CREATE TRIGGER ig62_pointer BEFORE INSERT OR UPDATE OR DELETE ON public.index_active_pointer FOR EACH ROW EXECUTE FUNCTION public.sclib_index_pointer_v1()",
        "CREATE TRIGGER ig62_pointer_truncate BEFORE TRUNCATE ON public.index_active_pointer FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_index_pointer_v1()",
        "INSERT INTO public.index_generation_epoch(id,epoch) VALUES(1,0)",
    ])
    return statements


def register(metadata):
    tables = {}

    def column(name, kind, required=True, default=None):
        return sa.Column(name, kind, nullable=not required, server_default=default)

    def uid(name, target=None, required=True):
        return sa.Column(name, UUID(as_uuid=True), *([sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")] if target else []), nullable=not required)

    def history(name, *items):
        tables[name] = sa.Table(name, metadata, *items,
            column("record_sha256", sa.String(64), default="0" * 64),
            column("created_at", sa.DateTime(timezone=True), default=sa.func.clock_timestamp()),
            sa.CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'", name="ck_ig62_" + name + "_hash"))
        return tables[name]

    tables[TABLE_ORDER[0]] = sa.Table(TABLE_ORDER[0], metadata, sa.Column("id", sa.Integer, primary_key=True),
        column("epoch", sa.BigInteger, default="0"), sa.CheckConstraint("id=1 AND epoch>=0", name="ck_ig62_epoch"))
    history("index_generations", uid("id"), column("logical_index", sa.String(128)), column("profile", JSONB),
        column("resource", JSONB), column("expected_member_count", sa.Integer), column("manifest_sha256", sa.String(64)),
        sa.PrimaryKeyConstraint("id"), sa.CheckConstraint("btrim(logical_index)<>'' AND expected_member_count BETWEEN 1 AND 1000 AND manifest_sha256 ~ '^[0-9a-f]{64}$'", name="ck_ig62_generation"))
    history("index_generation_members", uid("generation_id", "index_generations.id"), column("vector_id", sa.String(120)),
        column("chunk_key", sa.String(200)), column("paper_id", sa.String(100)),
        column("snapshot_json", JSONB), column("paper_snapshot_json", JSONB), column("vector_bytes", sa.LargeBinary),
        uid("evidence_revision_id", "rag_evidence_revisions.id"), uid("receipt_id", "embedding_completion_receipts.id"),
        *[column(name, sa.String(64)) for name in ("snapshot_sha256", "chunk_revision_sha256", "evidence_record_sha256",
            "receipt_record_sha256", "source_snapshot_sha256", "content_sha256", "vector_sha256")],
        column("parser_version", sa.String(160)), column("chunker_version", sa.String(160)),
        sa.PrimaryKeyConstraint("generation_id", "vector_id"), sa.UniqueConstraint("generation_id", "chunk_key", name="uq_ig62_member_chunk"),
        sa.CheckConstraint("octet_length(vector_bytes)=3072 AND btrim(parser_version)<>'' AND btrim(chunker_version)<>'' AND jsonb_typeof(snapshot_json)='object' AND jsonb_typeof(paper_snapshot_json)='object'", name="ck_ig62_member"),
        sa.Index("idx_ig62_member_paper", "generation_id", "paper_id"))
    history("index_generation_validations", uid("id"), uid("generation_id", "index_generations.id"),
        uid("observation_id"),
        column("observed_at", sa.DateTime(timezone=True)),
        column("observation", JSONB), column("outcome", sa.String(20), default="unverified"),
        column("validation_scope", sa.String(50), default="declared_generation_members"),
        column("observed_manifest_sha256", sa.String(64), default="0" * 64), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_id", name="uq_ig62_observation_id"),
        sa.CheckConstraint("outcome IN ('validated','unverified','rejected') AND validation_scope='declared_generation_members'", name="ck_ig62_validation"),
        sa.Index("idx_ig62_validation_generation", "generation_id"))
    history("index_activation_events", uid("id"), column("logical_index", sa.String(128)), uid("generation_id", "index_generations.id"),
        uid("validation_id", "index_generation_validations.id"), uid("predecessor_id", "index_activation_events.id", required=False),
        column("event_number", sa.Integer), column("action", sa.String(20)), column("idempotency_key", sa.String(160)),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("logical_index", "event_number", name="uq_ig62_event_number"),
        sa.UniqueConstraint("logical_index", "idempotency_key", name="uq_ig62_event_key"),
        sa.UniqueConstraint("predecessor_id", name="uq_ig62_event_predecessor"),
        sa.CheckConstraint("event_number>0 AND action IN ('promote','rollback') AND btrim(idempotency_key)<>''", name="ck_ig62_event"))
    tables["index_active_pointer"] = sa.Table("index_active_pointer", metadata,
        sa.Column("logical_index", sa.String(128), primary_key=True), uid("activation_event_id", "index_activation_events.id"),
        uid("generation_id", "index_generations.id"))
    tables["index_active_pointer"].add_is_dependent_on(tables["index_generation_members"])
    tables["index_active_pointer"].add_is_dependent_on(tables["index_generation_epoch"])
    for statement in guard_statements():
        sa.event.listen(tables[TABLE_ORDER[-1]], "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return tables
