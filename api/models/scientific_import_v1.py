"""Private pending scientific imports with retained bytes and explicit unknown starts.

The caller authenticates actors; these guards independently enforce current
explicit curator grants. A completed parser run is not an attested calculation,
scientific acceptance, source permission, publication or ML training approval.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = (
    "scientific_import_packages", "scientific_import_attempts", "scientific_import_blobs",
    "scientific_import_files", "scientific_import_outcomes",
)
LOCK_KEY = 650017026
LOCK_FUNCTION = "sclib_scientific_import_lock_v1"
PARENTS = ("users", "research_role_grants", "evidence_artifacts", "materials", "research_runs",
           "material_states", "structure_records", "research_events", "event_properties")
FUNCTION_SIGNATURES = (
    ("sclib_scientific_import_canonical_v1", "jsonb"),
    ("sclib_scientific_import_text_hash_v1", "text"),
    ("sclib_scientific_import_record_hash_v1", "jsonb"),
    (LOCK_FUNCTION, ""),
    ("sclib_scientific_import_immutable_v1", ""),
    ("sclib_scientific_import_complete_v1", "uuid"),
    ("sclib_scientific_import_deferred_v1", ""),
    ("sclib_scientific_import_insert_v1", ""),
)
_SQL = "LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"


def guard_statements():
    statements = ["""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_import_canonical_v1(body jsonb) RETURNS text
      LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
      DECLARE result text;
      BEGIN
        IF jsonb_typeof(body)='object' THEN
          SELECT '{'||COALESCE(string_agg(to_jsonb(key)::text||':'||
            public.sclib_scientific_import_canonical_v1(value),',' ORDER BY key COLLATE "C"),'')||'}'
            INTO result FROM jsonb_each(body);
        ELSIF jsonb_typeof(body)='array' THEN
          SELECT '['||COALESCE(string_agg(public.sclib_scientific_import_canonical_v1(value),',' ORDER BY ordinal),'')||']'
            INTO result FROM jsonb_array_elements(body) WITH ORDINALITY AS items(value,ordinal);
        ELSE result:=body::text; END IF;
        RETURN result;
      END $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_scientific_import_text_hash_v1(body text) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT encode(public.digest(convert_to(body,'UTF8'),'sha256'),'hex')
      $$
    """, """
      CREATE OR REPLACE FUNCTION public.sclib_scientific_import_record_hash_v1(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT public.sclib_scientific_import_text_hash_v1(public.sclib_scientific_import_canonical_v1(
          body-ARRAY['created_at','record_sha256','assembly_xid','manifest_json','context_json','request_json',
                     'artifact_projection_json','payload','report_json','row_snapshots_json']))
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.{LOCK_FUNCTION}() RETURNS void {_SQL} AS $$
      BEGIN
        IF current_setting('transaction_isolation')<>'serializable' THEN
          RAISE EXCEPTION 'scientific_import_serializable_required' USING ERRCODE='25000'; END IF;
        PERFORM public.sclib_research_integrity_lock_v1();
        PERFORM public.sclib_research_publication_lock_v1();
        IF NOT pg_try_advisory_xact_lock({LOCK_KEY}) THEN
          RAISE EXCEPTION 'scientific_import_busy_retry_transaction' USING ERRCODE='55P03'; END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_import_immutable_v1() RETURNS trigger {_SQL} AS $$
      BEGIN RAISE EXCEPTION 'scientific import history is append-only' USING ERRCODE='55000'; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_import_complete_v1(identifier uuid) RETURNS void {_SQL} AS $$
      DECLARE p public.scientific_import_packages%ROWTYPE; item jsonb; n integer;
      BEGIN
        SELECT * INTO p FROM public.scientific_import_packages WHERE id=identifier;
        IF p.id IS NULL THEN RAISE EXCEPTION 'scientific_import_package_required' USING ERRCODE='23514'; END IF;
        n:=jsonb_array_length(p.request_json::jsonb->'files');
        IF (SELECT count(*) FROM public.scientific_import_files WHERE package_id=p.id)<>n THEN
          RAISE EXCEPTION 'scientific_import_complete_source_inventory_required' USING ERRCODE='23514'; END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(p.request_json::jsonb->'files') LOOP
          IF NOT EXISTS(SELECT 1 FROM public.scientific_import_files f JOIN public.scientific_import_blobs b
            ON b.package_id=f.package_id AND b.artifact_id=f.artifact_id
            JOIN public.evidence_artifacts a ON a.id=b.artifact_id
            WHERE f.package_id=p.id AND f.logical_name=item->>'logical_name' AND f.role=item->>'role'
              AND f.sha256=item->>'sha256' AND f.size_bytes=(item->>'size_bytes')::bigint
              AND b.bytes_sha256=f.sha256 AND b.size_bytes=f.size_bytes AND b.attempt_id IS NULL
              AND b.artifact_projection_json::jsonb=to_jsonb(a)) THEN
            RAISE EXCEPTION 'scientific_import_exact_source_bytes_required' USING ERRCODE='23514'; END IF;
        END LOOP;
        IF EXISTS(SELECT 1 FROM public.scientific_import_blobs b WHERE b.package_id=p.id AND b.attempt_id IS NULL
          AND NOT EXISTS(SELECT 1 FROM public.scientific_import_files f WHERE f.package_id=p.id AND f.artifact_id=b.artifact_id)) THEN
          RAISE EXCEPTION 'scientific_import_undeclared_source_blob' USING ERRCODE='23514'; END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_import_deferred_v1() RETURNS trigger {_SQL} AS $$
      BEGIN
        IF TG_TABLE_NAME='scientific_import_packages' THEN
          PERFORM public.sclib_scientific_import_complete_v1(NEW.id);
        ELSE PERFORM public.sclib_scientific_import_complete_v1(NEW.package_id); END IF;
        RETURN NULL;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_scientific_import_insert_v1() RETURNS trigger {_SQL} AS $$
      DECLARE p public.scientific_import_packages%ROWTYPE; attempt public.scientific_import_attempts%ROWTYPE;
        head public.scientific_import_attempts%ROWTYPE; item jsonb; request jsonb; manifest jsonb; context jsonb;
        actual jsonb; snapshot jsonb; run jsonb; event jsonb; property jsonb; state jsonb; structure jsonb;
        artifact jsonb; expected_files jsonb; source_size bigint; terminal text;
      BEGIN
        PERFORM public.{LOCK_FUNCTION}();
        IF TG_TABLE_NAME IN ('scientific_import_packages','scientific_import_attempts','scientific_import_outcomes','scientific_import_blobs') THEN
          IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,'curator') THEN
            RAISE EXCEPTION 'scientific_import_current_curator_required' USING ERRCODE='42501'; END IF;
        END IF;
        IF TG_TABLE_NAME='scientific_import_packages' THEN
          IF octet_length(NEW.manifest_json)>65536 OR octet_length(NEW.context_json)>16384
            OR octet_length(NEW.request_json)>131072 THEN
            RAISE EXCEPTION 'scientific_import_request_byte_limit' USING ERRCODE='23514'; END IF;
          manifest:=NEW.manifest_json::jsonb; context:=NEW.context_json::jsonb; request:=NEW.request_json::jsonb;
          IF public.sclib_scientific_import_canonical_v1(manifest) IS DISTINCT FROM NEW.manifest_json
            OR public.sclib_scientific_import_canonical_v1(context) IS DISTINCT FROM NEW.context_json
            OR public.sclib_scientific_import_canonical_v1(request) IS DISTINCT FROM NEW.request_json
            OR public.sclib_scientific_import_text_hash_v1(NEW.manifest_json)<>NEW.manifest_sha256
            OR public.sclib_scientific_import_text_hash_v1(NEW.context_json)<>NEW.context_sha256
            OR public.sclib_scientific_import_text_hash_v1(NEW.request_json)<>NEW.package_key
            OR request IS DISTINCT FROM jsonb_build_object('version','scientific-pending-import/1.0.0',
              'manifest_sha256',NEW.manifest_sha256,'context_sha256',NEW.context_sha256,
              'compiler_sha256',NEW.compiler_sha256,'manifest',manifest,'context',context,'files',request->'files')
            OR jsonb_typeof(request->'files') IS DISTINCT FROM 'array'
            OR jsonb_array_length(request->'files') NOT BETWEEN 4 AND 19
            OR manifest->>'version' IS DISTINCT FROM 'scientific-program-package/1.0.0'
            OR manifest->>'adapter_id' IS DISTINCT FROM NEW.adapter_id
            OR jsonb_typeof(manifest->'files') IS DISTINCT FROM 'array'
            OR jsonb_array_length(manifest->'files') NOT BETWEEN 2 AND 16
            OR NOT manifest ?& ARRAY['version','adapter_id','files','context','declarations']
            OR manifest-ARRAY['version','adapter_id','files','context','declarations']<>'{{}}'::jsonb
            OR manifest->'declarations' IS DISTINCT FROM '{{"review_status":"unreviewed","execution_attested":false,"ml_training_approved":false}}'::jsonb
            OR context IS DISTINCT FROM jsonb_build_object('version','scientific-import-context/1.0.0',
              'material_id',context->'material_id','expected_material_row_sha256',context->'expected_material_row_sha256',
              'force_constants',context->'force_constants')
            OR jsonb_typeof(context->'material_id') IS DISTINCT FROM 'string'
            OR length(context->>'material_id') NOT BETWEEN 1 AND 100
            OR btrim(context->>'material_id') IS DISTINCT FROM context->>'material_id'
            OR context->>'material_id' ~ '[[:cntrl:]]'
            OR jsonb_typeof(context->'expected_material_row_sha256') IS DISTINCT FROM 'string'
            OR context->>'expected_material_row_sha256' !~ '^[0-9a-f]{{64}}$' THEN
            RAISE EXCEPTION 'scientific_import_exact_closed_request_required' USING ERRCODE='23514'; END IF;
          item:=manifest->'context';
          IF jsonb_typeof(item) IS DISTINCT FROM 'object'
            OR NOT item ?& ARRAY['material_formula','material_id','geometry_scope','source_url','source_revision','license_spdx']
            OR item-ARRAY['material_formula','material_id','geometry_scope','source_url','source_revision','license_spdx']<>'{{}}'::jsonb
            OR jsonb_typeof(item->'geometry_scope') IS DISTINCT FROM 'string'
            OR item->>'geometry_scope' NOT IN ('bulk_3d','other','unknown') THEN
            RAISE EXCEPTION 'scientific_import_original_context_required' USING ERRCODE='23514'; END IF;
          FOREACH terminal IN ARRAY ARRAY['material_formula','material_id','source_url','source_revision','license_spdx'] LOOP
            IF item->terminal IS DISTINCT FROM 'null'::jsonb AND (
              jsonb_typeof(item->terminal) IS DISTINCT FROM 'string' OR length(item->>terminal)<1
              OR length(item->>terminal)>CASE terminal WHEN 'material_formula' THEN 200 WHEN 'material_id' THEN 100
                WHEN 'source_url' THEN 2048 WHEN 'source_revision' THEN 160 ELSE 120 END
              OR item->>terminal ~ '[[:cntrl:]]') THEN
              RAISE EXCEPTION 'scientific_import_original_context_value_required' USING ERRCODE='23514'; END IF;
          END LOOP;
          IF item->'source_url' IS DISTINCT FROM 'null'::jsonb AND item->>'source_url' !~ '^https://[^/@?#[:space:]]+([/?#][^[:space:]]*)?$' THEN
            RAISE EXCEPTION 'scientific_import_original_source_url_required' USING ERRCODE='23514'; END IF;
          expected_files:='[]'::jsonb;
          FOR item IN SELECT value FROM jsonb_array_elements(manifest->'files') LOOP
            IF item IS DISTINCT FROM jsonb_build_object('role',item->'role','logical_name',item->'logical_name',
                'sha256',item->'sha256','size_bytes',item->'size_bytes')
              OR jsonb_typeof(item->'role') IS DISTINCT FROM 'string' OR item->>'role' NOT IN ('input','frequency','license','provenance')
              OR jsonb_typeof(item->'logical_name') IS DISTINCT FROM 'string'
              OR item->>'logical_name' !~ '^[A-Za-z0-9][A-Za-z0-9_.-]{{0,119}}$' OR position('..' in item->>'logical_name')>0
              OR jsonb_typeof(item->'sha256') IS DISTINCT FROM 'string' OR item->>'sha256' !~ '^[0-9a-f]{{64}}$'
              OR jsonb_typeof(item->'size_bytes') IS DISTINCT FROM 'number' OR item->>'size_bytes' !~ '^[0-9]+$'
              OR (item->>'size_bytes')::numeric NOT BETWEEN 1 AND 4194304 THEN
              RAISE EXCEPTION 'scientific_import_source_entry_required' USING ERRCODE='23514'; END IF;
            expected_files:=expected_files||jsonb_build_array(item||jsonb_build_object('logical_name','package/'||(item->>'logical_name')));
          END LOOP;
          IF (SELECT count(*) FROM jsonb_array_elements(manifest->'files') WHERE value->>'role'='input')<>1
            OR (SELECT count(*) FROM jsonb_array_elements(manifest->'files') WHERE value->>'role'='frequency')<>1
            OR (SELECT count(DISTINCT value->>'logical_name') FROM jsonb_array_elements(manifest->'files'))<>jsonb_array_length(manifest->'files') THEN
            RAISE EXCEPTION 'scientific_import_unique_input_frequency_required' USING ERRCODE='23514'; END IF;
          expected_files:=expected_files||jsonb_build_array(
            jsonb_build_object('role','manifest','logical_name','import/package.json','sha256',NEW.manifest_sha256,'size_bytes',octet_length(NEW.manifest_json)),
            jsonb_build_object('role','context','logical_name','import/context.json','sha256',NEW.context_sha256,'size_bytes',octet_length(NEW.context_json)));
          item:=context->'force_constants';
          IF item IS DISTINCT FROM 'null'::jsonb THEN
            IF jsonb_typeof(item) IS DISTINCT FROM 'object' OR item IS DISTINCT FROM jsonb_build_object(
                'logical_name',item->'logical_name','sha256',item->'sha256','size_bytes',item->'size_bytes')
              OR jsonb_typeof(item->'logical_name') IS DISTINCT FROM 'string'
              OR item->>'logical_name' !~ '^[A-Za-z0-9][A-Za-z0-9_.-]{{0,119}}$' OR position('..' in item->>'logical_name')>0
              OR jsonb_typeof(item->'sha256') IS DISTINCT FROM 'string' OR item->>'sha256' !~ '^[0-9a-f]{{64}}$'
              OR jsonb_typeof(item->'size_bytes') IS DISTINCT FROM 'number' OR item->>'size_bytes' !~ '^[0-9]+$'
              OR (item->>'size_bytes')::numeric NOT BETWEEN 1 AND 8388608 THEN
              RAISE EXCEPTION 'scientific_import_force_constants_pin_required' USING ERRCODE='23514'; END IF;
            expected_files:=expected_files||jsonb_build_array(item||jsonb_build_object('role','force_constants','logical_name','force_constants/'||(item->>'logical_name')));
          END IF;
          IF jsonb_array_length(expected_files)<>jsonb_array_length(request->'files')
            OR NOT expected_files @> (request->'files') OR NOT (request->'files') @> expected_files
            OR (SELECT count(DISTINCT value->>'logical_name') FROM jsonb_array_elements(request->'files'))<>jsonb_array_length(expected_files) THEN
            RAISE EXCEPTION 'scientific_import_exact_augmented_inventory_required' USING ERRCODE='23514'; END IF;
          SELECT sum(size) INTO source_size FROM (SELECT DISTINCT value->>'sha256', (value->>'size_bytes')::bigint AS size
            FROM jsonb_array_elements(manifest->'files')) entries;
          IF source_size+octet_length(NEW.manifest_json)>8388608 THEN
            RAISE EXCEPTION 'scientific_import_original_package_byte_limit' USING ERRCODE='23514'; END IF;
          NEW.assembly_xid:=txid_current();
        ELSIF TG_TABLE_NAME='scientific_import_outcomes' THEN
          IF octet_length(NEW.report_json)>8388608 OR octet_length(NEW.row_snapshots_json)>8388608
            OR octet_length(NEW.reason_codes::text)>8192 THEN
            RAISE EXCEPTION 'scientific_import_outcome_byte_limit' USING ERRCODE='23514'; END IF;
          SELECT * INTO attempt FROM public.scientific_import_attempts WHERE id=NEW.attempt_id;
          SELECT * INTO p FROM public.scientific_import_packages WHERE id=attempt.package_id;
          SELECT * INTO head FROM public.scientific_import_attempts WHERE package_id=p.id ORDER BY attempt_number DESC LIMIT 1;
          IF attempt.id IS NULL OR head.id IS DISTINCT FROM attempt.id THEN
            RAISE EXCEPTION 'scientific_import_current_attempt_required' USING ERRCODE='23514'; END IF;
          IF NEW.report_sha256<>public.sclib_scientific_import_text_hash_v1(NEW.report_json)
            OR jsonb_typeof(NEW.report_json::jsonb) IS DISTINCT FROM 'object'
            OR NEW.report_json::jsonb->>'version' IS DISTINCT FROM 'scientific-pending-import-report/1.0.0'
            OR NEW.report_json::jsonb->>'status' IS DISTINCT FROM NEW.outcome
            OR NEW.report_json::jsonb->'reason_codes' IS DISTINCT FROM NEW.reason_codes
            OR NEW.report_json::jsonb->>'cost_scope' IS DISTINCT FROM 'parser_worker_only'
            OR NEW.report_json::jsonb->'actual_calculation_costs' IS DISTINCT FROM 'null'::jsonb
            OR NEW.report_json::jsonb->'authority' IS DISTINCT FROM '{{"scientific_accepted":false,"ml_training_approved":false,"public_release":false,"execution_attested":false,"source_time_verified":false,"redistribution_authorized":false}}'::jsonb
            OR jsonb_typeof(NEW.reason_codes) IS DISTINCT FROM 'array'
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.reason_codes) AS codes(value)
              WHERE jsonb_typeof(value) IS DISTINCT FROM 'string' OR value#>>'{{}}' !~ '^[a-z][a-z0-9_]{{0,159}}$')
            OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(NEW.reason_codes))<>jsonb_array_length(NEW.reason_codes) THEN
            RAISE EXCEPTION 'scientific_import_exact_terminal_report_required' USING ERRCODE='23514'; END IF;
          FOREACH terminal IN ARRAY ARRAY['scientific_accepted','scientific_acceptance','ml_training_approved','public_release',
            'execution_attested','source_time_verified','redistribution_authorized'] LOOP
            IF ((NEW.report_json::jsonb) ? terminal AND NEW.report_json::jsonb->terminal IS DISTINCT FROM 'false'::jsonb)
              OR ((NEW.report_json::jsonb->'authority') ? terminal AND NEW.report_json::jsonb->'authority'->terminal IS DISTINCT FROM 'false'::jsonb) THEN
              RAISE EXCEPTION 'scientific_import_no_approval_authority' USING ERRCODE='23514'; END IF;
          END LOOP;
          IF NEW.outcome='success_pending' THEN
            PERFORM public.sclib_scientific_import_complete_v1(p.id);
            snapshot:=NEW.row_snapshots_json::jsonb;
            IF NEW.row_snapshots_sha256<>public.sclib_scientific_import_text_hash_v1(NEW.row_snapshots_json)
              OR jsonb_typeof(snapshot) IS DISTINCT FROM 'object'
              OR NOT snapshot ?& ARRAY['run','state','structure','event','property']
              OR snapshot-ARRAY['run','state','structure','event','property']<>'{{}}'::jsonb THEN
              RAISE EXCEPTION 'scientific_import_exact_result_snapshots_required' USING ERRCODE='23514'; END IF;
            SELECT to_jsonb(r) INTO run FROM public.research_runs r WHERE id=NEW.run_id;
            SELECT to_jsonb(s) INTO state FROM public.material_states s WHERE id=NEW.state_id;
            SELECT to_jsonb(s) INTO structure FROM public.structure_records s WHERE id=NEW.structure_id;
            SELECT to_jsonb(e) INTO event FROM public.research_events e WHERE id=NEW.event_id;
            SELECT to_jsonb(v) INTO property FROM public.event_properties v WHERE id=NEW.property_id;
            IF run IS NULL OR state IS NULL OR structure IS NULL OR event IS NULL OR property IS NULL
              OR snapshot IS DISTINCT FROM jsonb_build_object('run',run,'state',state,'structure',structure,'event',event,'property',property)
              OR run->>'run_kind' IS DISTINCT FROM 'extraction' OR run->>'status' IS DISTINCT FROM 'completed'
              OR event->>'event_type' IS DISTINCT FROM 'extraction' OR event->>'knowledge_origin' IS DISTINCT FROM 'Computed'
              OR event->>'producer_run_id' IS DISTINCT FROM NEW.run_id::text
              OR event->>'state_id' IS DISTINCT FROM NEW.state_id::text OR event->>'structure_id' IS DISTINCT FROM NEW.structure_id::text
              OR event->>'material_id' IS DISTINCT FROM p.context_json::jsonb->>'material_id'
              OR state->>'material_id' IS DISTINCT FROM event->>'material_id' OR structure->>'material_id' IS DISTINCT FROM event->>'material_id'
              OR event->>'review_status' IS DISTINCT FROM 'pending' OR event->>'validity_status' IS DISTINCT FROM 'pending'
              OR event->'decision_artifact_id' IS DISTINCT FROM 'null'::jsonb
              OR property->>'event_id' IS DISTINCT FROM NEW.event_id::text
              OR property->>'property_key' IS DISTINCT FROM 'phonon_min_frequency' OR property->>'unit' IS DISTINCT FROM 'THz'
              OR property->>'registry_version' IS DISTINCT FROM 'rv2/1' OR property->>'relation' IS DISTINCT FROM 'exact'
              OR (SELECT count(*) FROM public.event_properties WHERE event_id=NEW.event_id)<>1
              OR state->>'resolution' IS DISTINCT FROM 'source_scoped' OR state->>'pressure_status' IS DISTINCT FROM 'not_reported'
              OR state->'pressure_gpa' IS DISTINCT FROM 'null'::jsonb OR state->>'temperature_role' IS DISTINCT FROM 'simulation'
              OR state->'temperature_k' IS DISTINCT FROM 'null'::jsonb
              OR structure->>'structure_kind' IS DISTINCT FROM 'coordinates' THEN
              RAISE EXCEPTION 'scientific_import_pending_exact_result_required' USING ERRCODE='23514'; END IF;
            FOR item IN SELECT value FROM jsonb_array_elements(jsonb_build_array(
              jsonb_build_object('id',structure->>'artifact_id','kind','structure','schema','sclib-coordinate/1.0.0'),
              jsonb_build_object('id',run->>'input_manifest_id','kind','run_manifest','schema','scientific-import-run/1.0.0'),
              jsonb_build_object('id',run->>'output_manifest_id','kind','run_manifest','schema','scientific-import-run/1.0.0'))) LOOP
              IF NOT EXISTS(SELECT 1 FROM public.scientific_import_blobs b JOIN public.evidence_artifacts a ON a.id=b.artifact_id
                WHERE b.package_id=p.id AND b.attempt_id=attempt.id AND b.artifact_id::text=item->>'id'
                  AND a.kind=item->>'kind' AND a.schema_version=item->>'schema'
                  AND b.artifact_projection_json::jsonb=to_jsonb(a)) THEN
                RAISE EXCEPTION 'scientific_import_generated_artifact_required' USING ERRCODE='23514'; END IF;
            END LOOP;
            IF NOT EXISTS(SELECT 1 FROM public.scientific_import_blobs b JOIN public.evidence_artifacts a ON a.id=b.artifact_id
              WHERE b.package_id=p.id AND b.attempt_id=attempt.id AND a.kind='other'
                AND a.schema_version='scientific-import-report/1.0.0' AND b.bytes_sha256=NEW.report_sha256
                AND b.payload=convert_to(NEW.report_json,'UTF8') AND b.artifact_projection_json::jsonb=to_jsonb(a)) THEN
              RAISE EXCEPTION 'scientific_import_retained_report_required' USING ERRCODE='23514'; END IF;
          END IF;
        ELSE
          SELECT * INTO p FROM public.scientific_import_packages WHERE id=NEW.package_id;
          IF p.id IS NULL THEN RAISE EXCEPTION 'scientific_import_package_required' USING ERRCODE='23514'; END IF;
          IF TG_TABLE_NAME='scientific_import_attempts' THEN
            PERFORM public.sclib_scientific_import_complete_v1(p.id);
            SELECT * INTO head FROM public.scientific_import_attempts WHERE package_id=p.id ORDER BY attempt_number DESC LIMIT 1;
            IF (head.id IS NULL AND (NEW.attempt_number<>1 OR NEW.predecessor_id IS NOT NULL))
              OR (head.id IS NOT NULL AND (NEW.predecessor_id IS DISTINCT FROM head.id OR NEW.attempt_number<>head.attempt_number+1))
              OR EXISTS(SELECT 1 FROM public.scientific_import_outcomes o JOIN public.scientific_import_attempts a ON a.id=o.attempt_id
                WHERE a.package_id=p.id AND o.outcome='success_pending') THEN
              RAISE EXCEPTION 'scientific_import_exact_attempt_chain_required' USING ERRCODE='23514'; END IF;
          ELSIF TG_TABLE_NAME='scientific_import_files' THEN
            IF p.assembly_xid<>txid_current() OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p.request_json::jsonb->'files')
              WHERE value=jsonb_build_object('role',NEW.role,'logical_name',NEW.logical_name,'sha256',NEW.sha256,'size_bytes',NEW.size_bytes)) THEN
              RAISE EXCEPTION 'scientific_import_initial_source_inventory_only' USING ERRCODE='23514'; END IF;
          ELSE
            IF octet_length(NEW.payload)>8388608 OR octet_length(NEW.artifact_projection_json)>65536 THEN
              RAISE EXCEPTION 'scientific_import_blob_byte_limit' USING ERRCODE='23514'; END IF;
            IF NEW.attempt_id IS NULL THEN
              IF p.assembly_xid<>txid_current() THEN
                RAISE EXCEPTION 'scientific_import_initial_source_blob_only' USING ERRCODE='23514'; END IF;
              IF NOT public.sclib_research_distribution_role_v1(p.actor_user_id,p.actor_grant_id,'curator') THEN
                RAISE EXCEPTION 'scientific_import_current_curator_required' USING ERRCODE='42501'; END IF;
            ELSE
              SELECT * INTO attempt FROM public.scientific_import_attempts WHERE id=NEW.attempt_id;
              SELECT * INTO head FROM public.scientific_import_attempts WHERE package_id=p.id ORDER BY attempt_number DESC LIMIT 1;
              IF attempt.package_id IS DISTINCT FROM p.id OR head.id IS DISTINCT FROM attempt.id
                OR EXISTS(SELECT 1 FROM public.scientific_import_outcomes WHERE attempt_id=attempt.id) THEN
                RAISE EXCEPTION 'scientific_import_open_attempt_blob_required' USING ERRCODE='23514'; END IF;
            END IF;
            SELECT to_jsonb(a) INTO artifact FROM public.evidence_artifacts a WHERE id=NEW.artifact_id;
            IF artifact IS NULL OR artifact IS DISTINCT FROM NEW.artifact_projection_json::jsonb
              OR NEW.artifact_row_sha256<>public.sclib_scientific_import_text_hash_v1(NEW.artifact_projection_json)
              OR artifact->>'kind' IS DISTINCT FROM NEW.artifact_kind OR artifact->>'access' IS DISTINCT FROM 'restricted'
              OR artifact->>'hash_status' IS DISTINCT FROM 'verified' OR artifact->>'bytes_sha256' IS DISTINCT FROM NEW.bytes_sha256
              OR NEW.bytes_sha256<>encode(public.digest(NEW.payload,'sha256'),'hex') OR octet_length(NEW.payload)<>NEW.size_bytes
              OR (NEW.attempt_id IS NULL AND (NEW.artifact_kind<>'other' OR artifact->>'schema_version' IS DISTINCT FROM 'scientific-import-source/1.0.0'))
              OR (NEW.attempt_id IS NOT NULL AND NOT ((NEW.artifact_kind='structure' AND artifact->>'schema_version'='sclib-coordinate/1.0.0')
                OR (NEW.artifact_kind='run_manifest' AND artifact->>'schema_version'='scientific-import-run/1.0.0')
                OR (NEW.artifact_kind='other' AND artifact->>'schema_version'='scientific-import-report/1.0.0')))
              OR (SELECT count(*) FROM public.scientific_import_blobs WHERE package_id=p.id)>=64
              OR (SELECT COALESCE(sum(size_bytes),0) FROM public.scientific_import_blobs WHERE package_id=p.id)+NEW.size_bytes>25165824 THEN
              RAISE EXCEPTION 'scientific_import_exact_bounded_artifact_bytes_required' USING ERRCODE='23514'; END IF;
          END IF;
        END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_scientific_import_record_hash_v1(to_jsonb(NEW));
        RETURN NEW;
      END $$
    """]
    for name in TABLE_ORDER:
        statements.extend([
            f"CREATE TRIGGER si65_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_scientific_import_insert_v1()",
            f"CREATE TRIGGER si65_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_scientific_import_immutable_v1()",
            f"CREATE TRIGGER si65_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_scientific_import_immutable_v1()",
        ])
    for name in ("scientific_import_packages", "scientific_import_files"):
        statements.append(f"CREATE CONSTRAINT TRIGGER si65_complete AFTER INSERT ON public.{name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sclib_scientific_import_deferred_v1()")
    return statements


def register(metadata):
    tables = {}

    def uid(name, target=None, *, nullable=False):
        refs = [sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *refs, nullable=nullable)

    def col(name, kind, *, nullable=False, default=None):
        return sa.Column(name, kind, nullable=nullable, server_default=default)

    def actor():
        return uid("actor_user_id", "users.id"), uid("actor_grant_id", "research_role_grants.id")

    def ck(body, name):
        return sa.CheckConstraint(body, name="ck_si65_" + name)

    def table(name, *items):
        checks = [ck(f"{item.name} IS NULL OR {item.name} ~ '^[0-9a-f]{{64}}$'", name + "_" + item.name)
                  for item in items if isinstance(item, sa.Column) and (item.name.endswith("sha256") or item.name == "package_key")]
        tables[name] = sa.Table(name, metadata,
            col("id", UUID(as_uuid=True), default=sa.text("gen_random_uuid()")), *items,
            col("record_sha256", sa.String(64), default=""), col("created_at", sa.DateTime(timezone=True), default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"), ck("record_sha256 ~ '^[0-9a-f]{64}$'", name + "_record"),
            ck("isfinite(created_at)", name + "_time"), *checks)

    table("scientific_import_packages", col("package_key", sa.String(64)), col("manifest_sha256", sa.String(64)),
          col("context_sha256", sa.String(64)), col("compiler_sha256", sa.String(64)),
          col("adapter_id", sa.String(40), default="qe-matdyn-flfrq"),
          col("adapter_version", sa.String(80), default="qe-matdyn-import/1.0.0"),
          col("manifest_json", sa.Text), col("context_json", sa.Text), col("request_json", sa.Text),
          *actor(), col("assembly_xid", sa.BigInteger, default=sa.text("txid_current()")),
          sa.UniqueConstraint("package_key", name="uq_si65_package_key"),
          ck("adapter_id='qe-matdyn-flfrq' AND adapter_version='qe-matdyn-import/1.0.0'", "adapter"),
          ck("octet_length(manifest_json) BETWEEN 2 AND 65536 AND octet_length(context_json) BETWEEN 2 AND 16384 AND octet_length(request_json) BETWEEN 2 AND 131072", "request_bounds"))
    table("scientific_import_attempts", uid("package_id", "scientific_import_packages.id"),
          col("attempt_number", sa.Integer), uid("predecessor_id", "scientific_import_attempts.id", nullable=True),
          *actor(), col("request_key", sa.String(160)),
          ck("attempt_number>0 AND (predecessor_id IS NULL OR predecessor_id<>id)", "attempt_number"),
          ck("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$'", "request_key"),
          sa.UniqueConstraint("actor_user_id", "request_key", name="uq_si65_request_key"),
          sa.UniqueConstraint("package_id", "attempt_number", name="uq_si65_attempt_number"),
          sa.UniqueConstraint("predecessor_id", name="uq_si65_attempt_successor"),
          sa.Index("idx_si65_package_attempt", "package_id", "attempt_number"))
    table("scientific_import_blobs", uid("package_id", "scientific_import_packages.id"),
          uid("attempt_id", "scientific_import_attempts.id", nullable=True), *actor(), uid("artifact_id"),
          col("artifact_kind", sa.String(30)), col("artifact_row_sha256", sa.String(64)), col("artifact_projection_json", sa.Text),
          col("bytes_sha256", sa.String(64)), col("size_bytes", sa.BigInteger), col("payload", sa.LargeBinary),
          sa.ForeignKeyConstraint(["artifact_id", "artifact_kind"], ["evidence_artifacts.id", "evidence_artifacts.kind"],
                                  ondelete="RESTRICT", onupdate="RESTRICT", name="fk_si65_blob_artifact"),
          sa.UniqueConstraint("package_id", "artifact_id", name="uq_si65_package_artifact"),
          ck("size_bytes BETWEEN 1 AND 8388608 AND octet_length(payload)=size_bytes AND octet_length(artifact_projection_json) BETWEEN 2 AND 65536", "blob_bounds"),
          sa.Index("idx_si65_blob_package", "package_id"))
    table("scientific_import_files", uid("package_id", "scientific_import_packages.id"),
          col("role", sa.String(30)), col("logical_name", sa.String(160)), col("sha256", sa.String(64)),
          col("size_bytes", sa.BigInteger), uid("artifact_id"),
          sa.ForeignKeyConstraint(["package_id", "artifact_id"], ["scientific_import_blobs.package_id", "scientific_import_blobs.artifact_id"],
                                  ondelete="RESTRICT", onupdate="RESTRICT", name="fk_si65_file_blob"),
          sa.UniqueConstraint("package_id", "logical_name", name="uq_si65_source_name"),
          ck("size_bytes BETWEEN 1 AND 8388608 AND role IN ('manifest','context','input','frequency','license','provenance','force_constants')", "source_file"))
    table("scientific_import_outcomes", uid("attempt_id", "scientific_import_attempts.id"), *actor(),
          col("outcome", sa.String(30)), col("reason_codes", JSONB),
          col("cost_scope", sa.String(30), default="parser_worker_only"),
          col("import_wall_ms", sa.BigInteger, nullable=True), col("import_cpu_ms", sa.BigInteger, nullable=True),
          col("calculation_cpu_seconds", sa.Float, nullable=True), col("calculation_wall_seconds", sa.Float, nullable=True),
          col("calculation_monetary_cost", sa.Float, nullable=True),
          col("report_json", sa.Text), col("report_sha256", sa.String(64)),
          uid("run_id", "research_runs.id", nullable=True), uid("state_id", "material_states.id", nullable=True),
          uid("structure_id", "structure_records.id", nullable=True), uid("event_id", "research_events.id", nullable=True),
          uid("property_id", "event_properties.id", nullable=True), col("row_snapshots_json", sa.Text, nullable=True),
          col("row_snapshots_sha256", sa.String(64), nullable=True),
          sa.UniqueConstraint("attempt_id", name="uq_si65_attempt_outcome"),
          ck("outcome IN ('success_pending','quarantined','failed') AND jsonb_typeof(reason_codes)='array' AND jsonb_array_length(reason_codes)<=32 AND octet_length(reason_codes::text)<=8192", "outcome"),
          ck("(outcome='success_pending' AND reason_codes='[]'::jsonb) OR (outcome<>'success_pending' AND jsonb_array_length(reason_codes)>0)", "reasons"),
          ck("cost_scope='parser_worker_only' AND (import_wall_ms IS NULL OR import_wall_ms>=0) AND (import_cpu_ms IS NULL OR import_cpu_ms>=0) AND calculation_cpu_seconds IS NULL AND calculation_wall_seconds IS NULL AND calculation_monetary_cost IS NULL", "costs"),
          ck("octet_length(report_json) BETWEEN 2 AND 8388608 AND (row_snapshots_json IS NULL OR octet_length(row_snapshots_json) BETWEEN 2 AND 8388608)", "result_bounds"),
          ck("(outcome='success_pending' AND run_id IS NOT NULL AND state_id IS NOT NULL AND structure_id IS NOT NULL AND event_id IS NOT NULL AND property_id IS NOT NULL AND row_snapshots_json IS NOT NULL AND row_snapshots_sha256 IS NOT NULL) OR (outcome<>'success_pending' AND run_id IS NULL AND state_id IS NULL AND structure_id IS NULL AND event_id IS NULL AND property_id IS NULL AND row_snapshots_json IS NULL AND row_snapshots_sha256 IS NULL)", "pending_links"))
    last = tables[TABLE_ORDER[-1]]
    for name in (*PARENTS, *TABLE_ORDER[:-1]):
        last.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(last, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return tables
