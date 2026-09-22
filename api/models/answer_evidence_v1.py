"""0068 immutable final Ask snapshots; neither live evidence nor authority.

Only new, explicitly marked AskHistory rows can own receipts. Historical
generation references never consult the active pointer. Receipt removal follows
the parent history's owner deletion/account cascade/retention deletion only.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

VERSION = "ask-answer-evidence/1.0.0"
TABLE_NAME = "answer_evidence_receipts"
TABLE_ORDER = (TABLE_NAME,)
MAX_BYTES = 1024 * 1024
PARENTS = ("ask_history", "index_generations", "index_activation_events",
           "index_generation_members", "rag_evidence_revisions", "rag_extraction_revisions")
FUNCTION_SIGNATURES = (
    ("sclib_answer_evidence_canonical_v1", "jsonb"),
    ("sclib_answer_evidence_text_hash_v1", "text"),
    ("sclib_answer_evidence_record_hash_v1", "jsonb"),
    ("sclib_answer_evidence_json_safe_v1", "jsonb"),
    ("sclib_answer_evidence_parent_v1", ""),
    ("sclib_answer_evidence_complete_v1", ""),
    ("sclib_answer_evidence_immutable_v1", ""),
    ("sclib_answer_evidence_insert_v1", ""),
)
RESPONSE_KEYS = (
    "scientific_mixed", "evidence_packing", "input_budget", "retrieval_generation", "scientific_query",
    "scientific_lookup", "scientific_results", "answer", "sources", "tokens_used", "query_time_ms",
    "citation_valid", "citation_warnings", "support_policy_version", "citation_indices_valid",
    "lexical_support_checked", "scientific_support_status", "claim_assessments", "support_warnings",
    "support_coverage", "answer_mode", "assessment_scope",
)
BINDING_KEYS = (
    "kind", "position", "paper_id", "chunk_id", "content_sha256", "member_record_sha256",
    "chunk_revision_sha256", "vector_sha256", "source_snapshot_sha256", "evidence_revision_id",
    "evidence_record_sha256", "parent_result_revision_id", "parent_result_sha256",
    "selection_input_sha256", "selection_generation_pin_sha256", "selection_grouping_sha256", "has_evidence_pin",
)
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"


def _array(values):
    return "ARRAY[" + ",".join("'" + value + "'" for value in values) + "]"


def guard_statements():
    return [f"""
      CREATE OR REPLACE FUNCTION public.sclib_answer_evidence_canonical_v1(body jsonb) RETURNS text
      {_SQL} IMMUTABLE AS $$ DECLARE result text; BEGIN
        IF jsonb_typeof(body)='object' THEN
          SELECT '{{'||COALESCE(string_agg(to_jsonb(key)::text||':'||public.sclib_answer_evidence_canonical_v1(value),
            ',' ORDER BY key COLLATE "C"),'')||'}}' INTO result FROM jsonb_each(body);
        ELSIF jsonb_typeof(body)='array' THEN
          SELECT '['||COALESCE(string_agg(public.sclib_answer_evidence_canonical_v1(value),',' ORDER BY n),'')||']'
            INTO result FROM jsonb_array_elements(body) WITH ORDINALITY a(value,n);
        ELSE result:=body::text; END IF; RETURN result;
      END $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_answer_evidence_text_hash_v1(body text) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT encode(public.digest(convert_to(body,'UTF8'),'sha256'),'hex')
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_answer_evidence_record_hash_v1(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT public.sclib_answer_evidence_text_hash_v1(public.sclib_answer_evidence_canonical_v1(
          body-ARRAY['created_at','record_sha256','request_json','response_json','bindings_json']))
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_answer_evidence_json_safe_v1(body jsonb) RETURNS boolean
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        WITH RECURSIVE nodes(value,depth) AS (
          SELECT body,0 UNION ALL
          SELECT child.value,n.depth+1 FROM nodes n CROSS JOIN LATERAL (
            SELECT value FROM jsonb_each(CASE WHEN jsonb_typeof(n.value)='object' THEN n.value ELSE '{}'::jsonb END)
            UNION ALL SELECT value FROM jsonb_array_elements(CASE WHEN jsonb_typeof(n.value)='array' THEN n.value ELSE '[]'::jsonb END)
          ) child WHERE n.depth<25
        ) SELECT count(*)<=100000 AND max(depth)<=24 FROM nodes
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_answer_evidence_parent_v1() RETURNS trigger {_SQL} AS $$ BEGIN
        IF TG_OP='UPDATE' THEN
          IF OLD.evidence_receipt_version IS NOT NULL OR NEW.evidence_receipt_version IS DISTINCT FROM OLD.evidence_receipt_version THEN
            RAISE EXCEPTION 'answer_evidence_history_immutable' USING ERRCODE='55000'; END IF;
        ELSIF NEW.evidence_receipt_version IS NOT NULL THEN
          IF NEW.evidence_receipt_version<>'{VERSION}' THEN
            RAISE EXCEPTION 'answer_evidence_marker_invalid' USING ERRCODE='23514'; END IF;
          NEW.created_at:=clock_timestamp();
        END IF;
        RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_answer_evidence_complete_v1() RETURNS trigger {_SQL} AS $$ BEGIN
        IF EXISTS(SELECT 1 FROM public.ask_history h WHERE h.id=NEW.id AND h.evidence_receipt_version IS NOT NULL)
          AND NOT EXISTS(SELECT 1 FROM public.answer_evidence_receipts r WHERE r.history_id=NEW.id AND r.version='{VERSION}') THEN
          RAISE EXCEPTION 'answer_evidence_complete_receipt_required' USING ERRCODE='23514'; END IF;
        RETURN NULL;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_answer_evidence_immutable_v1() RETURNS trigger {_SQL} AS $$ BEGIN
        IF TG_OP='DELETE' AND NOT EXISTS(SELECT 1 FROM public.ask_history WHERE id=OLD.history_id) THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'answer_evidence_receipt_immutable' USING ERRCODE='55000';
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_answer_evidence_insert_v1() RETURNS trigger {_SQL} AS $$
      DECLARE request jsonb; response jsonb; bindings jsonb; item jsonb; output jsonb; descriptor jsonb; pin jsonb;
        h public.ask_history%ROWTYPE; g public.index_generations%ROWTYPE; a public.index_activation_events%ROWTYPE;
        m public.index_generation_members%ROWTYPE; e public.rag_evidence_revisions%ROWTYPE; x public.rag_extraction_revisions%ROWTYPE;
        field text; sources integer:=0; results integer:=0; position integer; seen text[]:=ARRAY[]::text[];
        result_started boolean:=false; generation boolean; total integer; generation_pin_hash text;
      BEGIN
        IF NEW.version<>'{VERSION}' OR octet_length(NEW.request_json)+octet_length(NEW.response_json)+octet_length(NEW.bindings_json)>{MAX_BYTES} THEN
          RAISE EXCEPTION 'answer_evidence_payload_bound' USING ERRCODE='23514'; END IF;
        request:=NEW.request_json::jsonb; response:=NEW.response_json::jsonb; bindings:=NEW.bindings_json::jsonb;
        IF NOT public.sclib_answer_evidence_json_safe_v1(request) OR NOT public.sclib_answer_evidence_json_safe_v1(response)
          OR NOT public.sclib_answer_evidence_json_safe_v1(bindings) THEN
          RAISE EXCEPTION 'answer_evidence_json_bound' USING ERRCODE='23514'; END IF;
        IF NEW.request_json IS DISTINCT FROM public.sclib_answer_evidence_canonical_v1(request)
          OR NEW.response_json IS DISTINCT FROM public.sclib_answer_evidence_canonical_v1(response)
          OR NEW.bindings_json IS DISTINCT FROM public.sclib_answer_evidence_canonical_v1(bindings)
          OR NEW.request_sha256 IS DISTINCT FROM public.sclib_answer_evidence_text_hash_v1(NEW.request_json)
          OR NEW.response_sha256 IS DISTINCT FROM public.sclib_answer_evidence_text_hash_v1(NEW.response_json)
          OR NEW.bindings_sha256 IS DISTINCT FROM public.sclib_answer_evidence_text_hash_v1(NEW.bindings_json) THEN
          RAISE EXCEPTION 'answer_evidence_canonical_hash_mismatch' USING ERRCODE='23514'; END IF;
        IF jsonb_typeof(request)<>'object' OR request-ARRAY['question','max_sources','language']<>'{{}}'::jsonb
          OR NOT request ?& ARRAY['question','max_sources','language'] OR jsonb_typeof(request->'question')<>'string'
          OR length(request->>'question') NOT BETWEEN 3 AND 2000 OR btrim(request->>'question')=''
          OR jsonb_typeof(request->'language')<>'string' OR request->>'language' NOT IN ('auto','en','zh')
          OR jsonb_typeof(request->'max_sources')<>'number' OR (request->>'max_sources') !~ '^[0-9]+$'
          OR (request->>'max_sources')::numeric NOT BETWEEN 1 AND 20
          OR jsonb_typeof(response)<>'object' OR response-{_array(RESPONSE_KEYS)}<>'{{}}'::jsonb
          OR NOT response ?& {_array(RESPONSE_KEYS)} OR jsonb_typeof(response->'answer')<>'string'
          OR jsonb_typeof(response->'sources')<>'array' OR jsonb_typeof(response->'scientific_results')<>'array'
          OR jsonb_typeof(response->'query_time_ms')<>'number' OR (response->>'query_time_ms') !~ '^[0-9]+$'
          OR (response->>'query_time_ms')::numeric>2147483647
          OR NOT (response->'tokens_used'='null'::jsonb OR (jsonb_typeof(response->'tokens_used')='number'
              AND (response->>'tokens_used') ~ '^[0-9]+$' AND (response->>'tokens_used')::numeric<=2147483647)) THEN
          RAISE EXCEPTION 'answer_evidence_request_response_shape' USING ERRCODE='23514'; END IF;
        SELECT * INTO h FROM public.ask_history WHERE id=NEW.history_id FOR KEY SHARE;
        IF h.id IS NULL OR h.evidence_receipt_version IS DISTINCT FROM NEW.version OR h.question IS DISTINCT FROM request->>'question'
          OR h.answer IS DISTINCT FROM response->>'answer' OR h.sources IS DISTINCT FROM response->'sources'
          OR h.language IS DISTINCT FROM request->>'language' OR to_jsonb(h.tokens_used) IS DISTINCT FROM NULLIF(response->'tokens_used','null'::jsonb)
          OR h.latency_ms IS DISTINCT FROM (response->>'query_time_ms')::integer THEN
          RAISE EXCEPTION 'answer_evidence_exact_new_history_required' USING ERRCODE='23514'; END IF;
        IF jsonb_typeof(bindings)<>'object' OR bindings-ARRAY['version','mode','generation_id','activation_event_id','manifest_sha256','items']<>'{{}}'::jsonb
          OR NOT bindings ?& ARRAY['version','mode','generation_id','activation_event_id','manifest_sha256','items']
          OR bindings->>'version' IS DISTINCT FROM NEW.version OR jsonb_typeof(bindings->'items')<>'array'
          OR jsonb_typeof(response->'retrieval_generation')<>'object' THEN
          RAISE EXCEPTION 'answer_evidence_bindings_shape' USING ERRCODE='23514'; END IF;
        total:=jsonb_array_length(bindings->'items');
        IF total>20 OR total>(request->>'max_sources')::integer
          OR total<>jsonb_array_length(response->'sources')+jsonb_array_length(response->'scientific_results') THEN
          RAISE EXCEPTION 'answer_evidence_complete_selection_required' USING ERRCODE='23514'; END IF;
        pin:=response->'retrieval_generation'; generation:=NEW.generation_id IS NOT NULL;
        IF pin-ARRAY['version','mode','generation_id','activation_event_id','manifest_sha256']<>'{{}}'::jsonb
          OR NOT pin ?& ARRAY['version','mode','generation_id','activation_event_id','manifest_sha256']
          OR pin->>'version' IS DISTINCT FROM 'index-read/1.0.0'
          OR bindings->'generation_id' IS DISTINCT FROM pin->'generation_id'
          OR bindings->'activation_event_id' IS DISTINCT FROM pin->'activation_event_id'
          OR bindings->'manifest_sha256' IS DISTINCT FROM pin->'manifest_sha256'
          OR bindings->>'mode' IS DISTINCT FROM (CASE WHEN total=0 THEN 'no_selected_evidence'
             WHEN generation THEN 'generation_bound' ELSE 'snapshot_only' END) THEN
          RAISE EXCEPTION 'answer_evidence_generation_envelope' USING ERRCODE='23514'; END IF;
        IF generation THEN
          SELECT * INTO g FROM public.index_generations WHERE id=NEW.generation_id;
          SELECT * INTO a FROM public.index_activation_events WHERE id=NEW.activation_event_id;
          IF g.id IS NULL OR a.id IS NULL OR a.generation_id IS DISTINCT FROM g.id OR a.logical_index IS DISTINCT FROM g.logical_index
            OR g.record_sha256 IS DISTINCT FROM public.sclib_index_record_hash_v1(to_jsonb(g))
            OR a.record_sha256 IS DISTINCT FROM public.sclib_index_record_hash_v1(to_jsonb(a))
            OR pin->>'mode' IS DISTINCT FROM 'generation_snapshot' OR pin->>'generation_id' IS DISTINCT FROM g.id::text
            OR pin->>'activation_event_id' IS DISTINCT FROM a.id::text OR pin->>'manifest_sha256' IS DISTINCT FROM g.manifest_sha256 THEN
            RAISE EXCEPTION 'answer_evidence_exact_historical_generation_required' USING ERRCODE='23514'; END IF;
          generation_pin_hash:=public.sclib_answer_evidence_text_hash_v1(public.sclib_answer_evidence_canonical_v1(
            jsonb_build_object('generation_id',g.id::text,'activation_event_id',a.id::text,
              'manifest_sha256',g.manifest_sha256,'profile',g.profile,'resource',g.resource)));
        ELSIF NEW.activation_event_id IS NOT NULL OR pin->>'mode' IS DISTINCT FROM 'legacy_lexical_only'
          OR pin->'generation_id'<>'null'::jsonb OR pin->'activation_event_id'<>'null'::jsonb OR pin->'manifest_sha256'<>'null'::jsonb THEN
          RAISE EXCEPTION 'answer_evidence_legacy_has_no_generation' USING ERRCODE='23514'; END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(bindings->'items') LOOP
          IF jsonb_typeof(item)<>'object' OR item-{_array(BINDING_KEYS)}<>'{{}}'::jsonb OR NOT item ?& {_array(BINDING_KEYS)}
            OR jsonb_typeof(item->'kind')<>'string' OR item->>'kind' NOT IN ('source','scientific_result')
            OR jsonb_typeof(item->'position')<>'number' OR (item->>'position') !~ '^[0-9]+$'
            OR (item->>'position')::numeric NOT BETWEEN 1 AND 20
            OR jsonb_typeof(item->'paper_id')<>'string' OR length(item->>'paper_id') NOT BETWEEN 1 AND 100
            OR jsonb_typeof(item->'chunk_id')<>'string' OR length(item->>'chunk_id') NOT BETWEEN 1 AND 200
            OR (item->>'chunk_id')=ANY(seen) OR jsonb_typeof(item->'has_evidence_pin')<>'boolean' THEN
            RAISE EXCEPTION 'answer_evidence_selection_shape' USING ERRCODE='23514'; END IF;
          seen:=array_append(seen,item->>'chunk_id'); position:=(item->>'position')::integer;
          FOREACH field IN ARRAY ARRAY['content_sha256','selection_input_sha256'] LOOP
            IF jsonb_typeof(item->field)<>'string' OR (item->>field) !~ '^[0-9a-f]{{64}}$' THEN
              RAISE EXCEPTION 'answer_evidence_selection_hash_required' USING ERRCODE='23514'; END IF;
          END LOOP;
          FOREACH field IN ARRAY ARRAY['member_record_sha256','chunk_revision_sha256','vector_sha256','source_snapshot_sha256',
              'evidence_record_sha256','parent_result_sha256','selection_generation_pin_sha256','selection_grouping_sha256'] LOOP
            IF item->field<>'null'::jsonb AND (jsonb_typeof(item->field)<>'string' OR (item->>field) !~ '^[0-9a-f]{{64}}$') THEN
              RAISE EXCEPTION 'answer_evidence_optional_hash_invalid' USING ERRCODE='23514'; END IF;
          END LOOP;
          FOREACH field IN ARRAY ARRAY['evidence_revision_id','parent_result_revision_id'] LOOP
            IF item->field<>'null'::jsonb AND (jsonb_typeof(item->field)<>'string'
              OR (item->>field) !~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$') THEN
              RAISE EXCEPTION 'answer_evidence_optional_uuid_invalid' USING ERRCODE='23514'; END IF;
          END LOOP;
          IF (item->'evidence_revision_id'='null'::jsonb) IS DISTINCT FROM (item->'evidence_record_sha256'='null'::jsonb)
            OR (item->'parent_result_revision_id'='null'::jsonb) IS DISTINCT FROM (item->'parent_result_sha256'='null'::jsonb)
            OR (item->'parent_result_revision_id'<>'null'::jsonb AND item->'evidence_revision_id'='null'::jsonb)
            OR (item->'has_evidence_pin'='false'::jsonb AND item->'evidence_revision_id'<>'null'::jsonb) THEN
            RAISE EXCEPTION 'answer_evidence_reference_pair_required' USING ERRCODE='23514'; END IF;
          IF generation THEN
            SELECT * INTO m FROM public.index_generation_members WHERE generation_id=g.id AND vector_id=item->>'chunk_id';
            IF m.vector_id IS NULL OR m.paper_id IS DISTINCT FROM item->>'paper_id'
              OR m.record_sha256 IS DISTINCT FROM public.sclib_index_record_hash_v1(to_jsonb(m))
              OR m.record_sha256 IS DISTINCT FROM item->>'member_record_sha256'
              OR m.chunk_revision_sha256 IS DISTINCT FROM item->>'chunk_revision_sha256'
              OR m.vector_sha256 IS DISTINCT FROM item->>'vector_sha256' OR m.content_sha256 IS DISTINCT FROM item->>'content_sha256'
              OR m.source_snapshot_sha256 IS DISTINCT FROM item->>'source_snapshot_sha256'
              OR m.evidence_revision_id::text IS DISTINCT FROM item->>'evidence_revision_id'
              OR m.evidence_record_sha256 IS DISTINCT FROM item->>'evidence_record_sha256'
              OR item->>'selection_generation_pin_sha256' IS DISTINCT FROM generation_pin_hash
              OR item->'has_evidence_pin'<>'true'::jsonb THEN
              RAISE EXCEPTION 'answer_evidence_exact_member_required' USING ERRCODE='23514'; END IF;
          ELSE
            FOREACH field IN ARRAY ARRAY['member_record_sha256','chunk_revision_sha256','vector_sha256','source_snapshot_sha256','selection_generation_pin_sha256'] LOOP
              IF item->field<>'null'::jsonb THEN RAISE EXCEPTION 'answer_evidence_snapshot_only_no_member' USING ERRCODE='23514'; END IF;
            END LOOP;
          END IF;
          e:=NULL; x:=NULL;
          IF item->'evidence_revision_id'<>'null'::jsonb THEN
            SELECT * INTO e FROM public.rag_evidence_revisions WHERE id=(item->>'evidence_revision_id')::uuid;
            IF e.id IS NULL OR e.record_sha256 IS DISTINCT FROM public.sclib_rag_evidence_record_hash_v1(to_jsonb(e))
              OR e.paper_id IS DISTINCT FROM item->>'paper_id' OR e.content_sha256 IS DISTINCT FROM item->>'content_sha256'
              OR e.record_sha256 IS DISTINCT FROM item->>'evidence_record_sha256'
              OR e.chunk_key IS DISTINCT FROM (CASE WHEN generation THEN m.chunk_key ELSE item->>'chunk_id' END)
              OR (generation AND e.source_snapshot_sha256 IS DISTINCT FROM m.source_snapshot_sha256)
              OR e.parent_extraction_revision_id::text IS DISTINCT FROM item->>'parent_result_revision_id' THEN
              RAISE EXCEPTION 'answer_evidence_exact_revision_required' USING ERRCODE='23514'; END IF;
            IF e.parent_extraction_revision_id IS NOT NULL THEN
              SELECT * INTO x FROM public.rag_extraction_revisions WHERE id=e.parent_extraction_revision_id;
              IF x.id IS NULL OR x.record_sha256 IS DISTINCT FROM public.sclib_rag_evidence_record_hash_v1(to_jsonb(x))
                OR x.paper_id IS DISTINCT FROM e.paper_id OR x.source_snapshot_sha256 IS DISTINCT FROM e.source_snapshot_sha256
                OR x.record_sha256 IS DISTINCT FROM item->>'parent_result_sha256' THEN
                RAISE EXCEPTION 'answer_evidence_exact_parent_required' USING ERRCODE='23514'; END IF;
            END IF;
          END IF;
          IF item->>'kind'='source' THEN
            sources:=sources+1;
            IF result_started OR position<>sources THEN RAISE EXCEPTION 'answer_evidence_selection_order' USING ERRCODE='23514'; END IF;
            output:=response->'sources'->(position-1); descriptor:=output->'evidence_provenance';
            IF jsonb_typeof(output)<>'object' OR output->'index' IS DISTINCT FROM item->'position'
              OR output->>'paper_id' IS DISTINCT FROM item->>'paper_id'
              OR jsonb_typeof(output->'packing_info') IS DISTINCT FROM 'object'
              OR output->'packing_info'->>'chunk_id' IS DISTINCT FROM item->>'chunk_id'
              OR output->'packing_info'->'position' IS DISTINCT FROM item->'position'
              OR output->'packing_info'->'source_snapshot_sha256' IS DISTINCT FROM item->'source_snapshot_sha256'
              OR (item->'has_evidence_pin'='false'::jsonb AND descriptor IS DISTINCT FROM '{{}}'::jsonb)
              OR (item->'has_evidence_pin'='true'::jsonb AND (
                 descriptor->>'content_sha256' IS DISTINCT FROM item->>'content_sha256'
              OR descriptor->>'evidence_revision_id' IS DISTINCT FROM item->>'evidence_revision_id'
              OR descriptor->>'evidence_record_sha256' IS DISTINCT FROM item->>'evidence_record_sha256'
              OR descriptor->>'parent_result_revision_id' IS DISTINCT FROM item->>'parent_result_revision_id'
              OR descriptor->>'parent_result_sha256' IS DISTINCT FROM item->>'parent_result_sha256')) THEN
              RAISE EXCEPTION 'answer_evidence_source_position_binding' USING ERRCODE='23514'; END IF;
            IF item->'has_evidence_pin'='true'::jsonb THEN
              IF descriptor->>'version' IS DISTINCT FROM 'rag-evidence/1.0.0'
                OR descriptor->>'root_status' IS DISTINCT FROM 'unresolved'
                OR descriptor->'support_eligible' IS DISTINCT FROM 'false'::jsonb
                OR descriptor->'independent_evidence' IS DISTINCT FROM 'false'::jsonb
                OR descriptor->'scientific_acceptance' IS DISTINCT FROM 'false'::jsonb THEN
                RAISE EXCEPTION 'answer_evidence_descriptor_no_authority' USING ERRCODE='23514'; END IF;
              IF e.id IS NOT NULL AND (descriptor->>'chunk_kind' IS DISTINCT FROM e.chunk_kind
                OR descriptor->>'extraction_version' IS DISTINCT FROM e.extraction_version
                OR descriptor->>'rendering_version' IS DISTINCT FROM e.rendering_version
                OR descriptor->>'source_capture_id' IS DISTINCT FROM e.source_capture_id::text
                OR descriptor->'source_locator' IS DISTINCT FROM e.source_locator) THEN
                RAISE EXCEPTION 'answer_evidence_exact_source_descriptor' USING ERRCODE='23514'; END IF;
              IF e.id IS NULL AND descriptor->>'chunk_kind' IS DISTINCT FROM 'legacy_unknown' THEN
                RAISE EXCEPTION 'answer_evidence_unresolved_source_descriptor' USING ERRCODE='23514'; END IF;
            END IF;
          ELSE
            result_started:=true; results:=results+1; output:=response->'scientific_results'->(position-1);
            descriptor:=output->'binding';
            IF NOT generation OR position<>results OR x.id IS NULL OR e.chunk_kind<>'derived_fact'
              OR descriptor->>'paper_id' IS DISTINCT FROM item->>'paper_id' OR descriptor->>'vector_id' IS DISTINCT FROM item->>'chunk_id'
              OR descriptor->>'generation_id' IS DISTINCT FROM g.id::text OR descriptor->>'activation_event_id' IS DISTINCT FROM a.id::text
              OR descriptor->>'manifest_sha256' IS DISTINCT FROM g.manifest_sha256
              OR descriptor->>'content_sha256' IS DISTINCT FROM item->>'content_sha256'
              OR descriptor->>'evidence_revision_id' IS DISTINCT FROM item->>'evidence_revision_id'
              OR descriptor->>'evidence_record_sha256' IS DISTINCT FROM item->>'evidence_record_sha256'
              OR descriptor->>'parent_result_revision_id' IS DISTINCT FROM item->>'parent_result_revision_id'
              OR descriptor->>'parent_result_sha256' IS DISTINCT FROM item->>'parent_result_sha256'
              OR output->'result'->'scientific_acceptance' IS DISTINCT FROM 'false'::jsonb
              OR output->'result'->'ml_training_eligible' IS DISTINCT FROM 'false'::jsonb THEN
              RAISE EXCEPTION 'answer_evidence_result_position_binding' USING ERRCODE='23514'; END IF;
          END IF;
        END LOOP;
        IF sources<>jsonb_array_length(response->'sources') OR results<>jsonb_array_length(response->'scientific_results') THEN
          RAISE EXCEPTION 'answer_evidence_complete_selection_required' USING ERRCODE='23514'; END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_answer_evidence_record_hash_v1(to_jsonb(NEW)); RETURN NEW;
      EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range OR program_limit_exceeded THEN
        RAISE EXCEPTION 'answer_evidence_invalid_bounded_json' USING ERRCODE='23514';
      END $$
    """, "CREATE TRIGGER ae68_parent BEFORE INSERT OR UPDATE ON public.ask_history FOR EACH ROW EXECUTE FUNCTION public.sclib_answer_evidence_parent_v1()",
        "CREATE CONSTRAINT TRIGGER ae68_complete AFTER INSERT ON public.ask_history DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sclib_answer_evidence_complete_v1()",
        f"CREATE TRIGGER ae68_insert BEFORE INSERT ON public.{TABLE_NAME} FOR EACH ROW EXECUTE FUNCTION public.sclib_answer_evidence_insert_v1()",
        f"CREATE TRIGGER ae68_immutable BEFORE UPDATE OR DELETE ON public.{TABLE_NAME} FOR EACH ROW EXECUTE FUNCTION public.sclib_answer_evidence_immutable_v1()",
        f"CREATE TRIGGER ae68_truncate BEFORE TRUNCATE ON public.{TABLE_NAME} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_answer_evidence_immutable_v1()"]


def register(metadata):
    table = sa.Table(TABLE_NAME, metadata,
        sa.Column("history_id", UUID(as_uuid=True), sa.ForeignKey("ask_history.id", ondelete="CASCADE", onupdate="RESTRICT"), primary_key=True),
        sa.Column("version", sa.String(50), nullable=False, server_default=VERSION),
        sa.Column("generation_id", UUID(as_uuid=True), sa.ForeignKey("index_generations.id", ondelete="RESTRICT", onupdate="RESTRICT")),
        sa.Column("activation_event_id", UUID(as_uuid=True), sa.ForeignKey("index_activation_events.id", ondelete="RESTRICT", onupdate="RESTRICT")),
        *[sa.Column(name, sa.Text, nullable=False) for name in ("request_json", "response_json", "bindings_json")],
        *[sa.Column(name, sa.String(64), nullable=False) for name in ("request_sha256", "response_sha256", "bindings_sha256")],
        sa.Column("record_sha256", sa.String(64), nullable=False, server_default="0" * 64),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.CheckConstraint("version='" + VERSION + "' AND ((generation_id IS NULL)=(activation_event_id IS NULL))", name="ck_ae68_version_pin"),
        sa.CheckConstraint(" AND ".join(name + " ~ '^[0-9a-f]{64}$'" for name in
            ("request_sha256", "response_sha256", "bindings_sha256", "record_sha256")), name="ck_ae68_hashes"),
        sa.Index("idx_ae68_generation", "generation_id"))
    for name in PARENTS:
        table.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(table, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return {TABLE_NAME: table}
