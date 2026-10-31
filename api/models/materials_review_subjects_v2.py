"""Exact claim/property subjects without changing the v1 review authority.

0094 installs one read-only function. It neither adds review decisions nor
converts a Tc claim into a duplicate event property. The existing v1 projection
fixes the source-row wire shape; new canonical source types need a later,
explicitly versioned closure extension.
"""
import json
import sqlalchemy as sa

from services.research_release_spec import FKS, SPEC

VERSION = "scientific-result-subject/2.0.0"
FUNCTION = "sclib_scientific_subject_capture_v2"


def upgrade_statements():
    fields = {name: set(spec["fields"]) for name, spec in SPEC.items()}
    fields["research_events"] -= {"review_status", "validity_status", "decision_artifact_id", "record_sha256", "updated_at"}
    fields["evidence_artifacts"] -= {"access", "license"}
    rules = {name: [[child, target, parent] for child, target, parent in edges
                     if all(key in fields[name] for key in child)] for name, edges in FKS.items()}
    rules_sql = "'" + json.dumps(rules, separators=(",", ":")).replace("'", "''") + "'::jsonb"
    return [f"""
      CREATE OR REPLACE FUNCTION public.{FUNCTION}(result_kind text, identifier uuid) RETURNS text
      LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC' AS $$
      DECLARE pending jsonb; seen jsonb:='{{}}'; records jsonb:='[]'; artifacts jsonb:='[]';
        support jsonb; current jsonb; snapshot jsonb; root_result jsonb; event jsonb; state jsonb; run jsonb;
        target text; row_id text; key text; rule jsonb; child text; parent_id text; relation text; extra record;
        rules jsonb:={rules_sql}; n integer:=0; size bigint:=0; body text; property_body jsonb;
      BEGIN
        PERFORM public.sclib_scientific_adjudication_read_guard_v1();
        IF result_kind IS NULL OR result_kind NOT IN ('claim','property') OR identifier IS NULL THEN
          RAISE EXCEPTION 'scientific_subject_exact_typed_target_required' USING ERRCODE='23514'; END IF;
        IF result_kind='property' THEN
          property_body:=public.sclib_scientific_subject_capture_v1(identifier)::jsonb;
          property_body:=jsonb_set(property_body,'{{version}}',to_jsonb('{VERSION}'::text));
          property_body:=jsonb_set(property_body,'{{target}}',
            ((property_body->'target')-'property_id')||jsonb_build_object('result_kind','property','result_id',identifier));
          body:=public.sclib_scientific_adjudication_canonical_v1(property_body);
          IF octet_length(body)>8388608 THEN RAISE EXCEPTION 'scientific_subject_byte_limit' USING ERRCODE='54000'; END IF;
          RETURN body;
        END IF;
        pending:=jsonb_build_array(jsonb_build_object('table','material_claims','row_id',identifier::text));
        WHILE jsonb_array_length(pending)>0 LOOP
          current:=pending->0; pending:=pending-0; target:=current->>'table'; row_id:=current->>'row_id'; key:=target||':'||row_id;
          IF seen ? key THEN CONTINUE; END IF;
          n:=n+1; IF n>1000 THEN RAISE EXCEPTION 'scientific_subject_row_limit' USING ERRCODE='54000'; END IF;
          snapshot:=public.sclib_scientific_subject_projection_v1(target,row_id);
          size:=size+octet_length(snapshot::text)+octet_length(row_id)+octet_length(target)+100;
          IF size>8388608 THEN RAISE EXCEPTION 'scientific_subject_byte_limit' USING ERRCODE='54000'; END IF;
          seen:=seen||jsonb_build_object(key,true);
          records:=records||jsonb_build_array(jsonb_build_object('table',target,'row_id',row_id,'snapshot',snapshot));
          IF target='material_claims' AND row_id=identifier::text THEN root_result:=snapshot; END IF;
          FOR rule IN SELECT value FROM jsonb_array_elements(COALESCE(rules->target,'[]'::jsonb)) LOOP
            child:=rule->0->>0; parent_id:=snapshot->>child; relation:=rule->>1;
            IF parent_id IS NOT NULL THEN
              pending:=pending||jsonb_build_array(jsonb_build_object('table',relation,'row_id',parent_id)); END IF;
          END LOOP;
          IF target='research_events' THEN
            FOR extra IN SELECT id,'event_evidence' AS tab FROM public.event_evidence WHERE event_id=row_id::uuid
              UNION ALL SELECT id,'snapshot_event_memberships' FROM public.snapshot_event_memberships WHERE event_id=row_id::uuid
              LIMIT 1001 LOOP
              pending:=pending||jsonb_build_array(jsonb_build_object('table',extra.tab,'row_id',extra.id::text)); END LOOP;
          ELSIF target='material_claims' THEN
            FOR extra IN SELECT id FROM public.claim_source_occurrences WHERE claim_id=row_id::uuid LIMIT 1001 LOOP
              pending:=pending||jsonb_build_array(jsonb_build_object('table','claim_source_occurrences','row_id',extra.id::text)); END LOOP;
          ELSIF target='papers' AND EXISTS(SELECT 1 FROM public.paper_work_map WHERE paper_id=row_id) THEN
            pending:=pending||jsonb_build_array(jsonb_build_object('table','paper_work_map','row_id',row_id));
          END IF;
          IF jsonb_array_length(pending)+n>3000 THEN RAISE EXCEPTION 'scientific_subject_reference_limit' USING ERRCODE='54000'; END IF;
          IF target='evidence_artifacts' THEN
            artifacts:=artifacts||jsonb_build_array(jsonb_build_object('artifact_id',row_id,
              'bytes_sha256',snapshot->'bytes_sha256','hash_status',snapshot->'hash_status'));
            IF jsonb_array_length(artifacts)>200 THEN RAISE EXCEPTION 'scientific_subject_artifact_limit' USING ERRCODE='54000'; END IF;
          END IF;
        END LOOP;
        SELECT value->'snapshot' INTO event FROM jsonb_array_elements(records)
          WHERE value->>'table'='research_events' AND value->>'row_id'=root_result->>'event_id';
        SELECT value->'snapshot' INTO state FROM jsonb_array_elements(records)
          WHERE value->>'table'='material_states' AND value->>'row_id'=event->>'state_id';
        SELECT value->'snapshot' INTO run FROM jsonb_array_elements(records)
          WHERE value->>'table'='research_runs' AND value->>'row_id'=event->>'producer_run_id';
        IF root_result->>'property_type' NOT IN ('tc','non_transition') OR event IS NULL OR state IS NULL
          OR event->>'event_type'='priority_assessment' OR event->>'material_id' IS DISTINCT FROM root_result->>'material_id'
          OR state->>'material_id' IS DISTINCT FROM event->>'material_id' THEN
          RAISE EXCEPTION 'scientific_subject_claim_event_state_required' USING ERRCODE='23514'; END IF;
        SELECT COALESCE(jsonb_agg(to_jsonb(id) ORDER BY id),'[]'::jsonb) INTO support FROM (
          SELECT artifact_id::text AS id FROM public.event_evidence WHERE event_id=(event->>'id')::uuid AND artifact_id IS NOT NULL
          UNION SELECT state->>'source_artifact_id' UNION SELECT run->>'input_manifest_id' UNION SELECT run->>'output_manifest_id'
        ) q WHERE id IS NOT NULL;
        SELECT jsonb_agg(value ORDER BY value->>'table' COLLATE "C",value->>'row_id' COLLATE "C") INTO records FROM jsonb_array_elements(records);
        SELECT COALESCE(jsonb_agg(value ORDER BY value->>'artifact_id'),'[]'::jsonb) INTO artifacts FROM jsonb_array_elements(artifacts);
        body:=public.sclib_scientific_adjudication_canonical_v1(jsonb_build_object('version','{VERSION}',
          'target',jsonb_build_object('result_kind','claim','result_id',identifier,'event_id',event->'id',
            'event_revision',event->'revision','material_id',event->'material_id','state_id',event->'state_id',
            'sample_id',state->'sample_id','structure_id',event->'structure_id','producer_run_id',event->'producer_run_id',
            'native_outcome_id',NULL),
          'rows',records,'artifacts',artifacts,'support_artifact_ids',support,'native_import',NULL));
        IF octet_length(body)>8388608 THEN RAISE EXCEPTION 'scientific_subject_byte_limit' USING ERRCODE='54000'; END IF;
        RETURN body;
      END $$
    """]


def downgrade_statements():
    return [f"DROP FUNCTION IF EXISTS public.{FUNCTION}(text,uuid)"]


def register(metadata):
    for sql in upgrade_statements():
        sa.event.listen(metadata, "after_create", sa.DDL(sql.replace("%", "%%")).execute_if(dialect="postgresql"))
    for sql in downgrade_statements():
        sa.event.listen(metadata, "before_drop", sa.DDL(sql).execute_if(dialect="postgresql"))
