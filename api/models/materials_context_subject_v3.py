"""0096 read-only closure extension; v1/v2 review writers remain unchanged."""
import json

import sqlalchemy as sa

from models.materials_context_v1 import TABLE_FIELDS, FKS as CONTEXT_FKS
from services.research_release_spec import FKS, SPEC

VERSION = "scientific-result-subject/3.0.0"
FUNCTION = "sclib_scientific_subject_capture_v3"


def statements():
    fields = {name: set(spec["fields"]) for name, spec in SPEC.items()}
    fields["research_events"] -= {"review_status", "validity_status", "decision_artifact_id", "record_sha256", "updated_at"}
    fields["evidence_artifacts"] -= {"access", "license"}
    rules = {name: [[child[0], target] for child, target, parent in edges if all(key in fields[name] for key in child)]
             for name, edges in FKS.items()}
    rules.update(CONTEXT_FKS)

    def literal(value):
        return "'" + json.dumps(value, separators=(",", ":")).replace("'", "''") + "'::jsonb"

    return [f"""
CREATE FUNCTION public.{FUNCTION}(result_kind text,identifier uuid) RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC' AS $$
DECLARE body jsonb; rows jsonb:='[]'; seen jsonb:='{{}}'; pending jsonb; current jsonb; snapshot jsonb;
 target text; rid text; key text; expression text; rule jsonb; ctx jsonb; extra record; support jsonb;
 artifacts jsonb:='[]'; result text; n integer:=0; size bigint:=0;
 rules jsonb:={literal(rules)}; fields jsonb:={literal(TABLE_FIELDS)};
BEGIN
 -- Preserve v2's native-import and exact target semantics. Its full base rows
 -- seed traversal; all new references are explicit, never "latest for sample".
 body:=public.sclib_scientific_subject_capture_v2(result_kind,identifier)::jsonb;
 pending:=body->'rows'; support:=body->'support_artifact_ids';
 WHILE jsonb_array_length(pending)>0 LOOP
  current:=pending->0; pending:=pending-0;
  target:=current->>'table'; rid:=current->>'row_id'; key:=target||':'||rid;
  IF seen ? key THEN CONTINUE; END IF;
  n:=n+1; IF n>1000 THEN RAISE EXCEPTION 'scientific_subject_row_limit' USING ERRCODE='54000'; END IF;
  IF fields ? target THEN
   SELECT 'jsonb_build_object('||string_agg(quote_literal(value)||',t.'||quote_ident(value),',' ORDER BY value COLLATE "C")||')'
    INTO expression FROM jsonb_array_elements_text(fields->target);
   EXECUTE format('SELECT %s FROM public.%I t WHERE id=$1::uuid',expression,target) INTO snapshot USING rid;
   IF snapshot IS NULL THEN RAISE EXCEPTION 'scientific_subject_source_unavailable' USING ERRCODE='23514'; END IF;
  ELSIF current ? 'snapshot' THEN snapshot:=current->'snapshot';
  ELSE snapshot:=public.sclib_scientific_subject_projection_v1(target,rid); END IF;
  size:=size+octet_length(snapshot::text)+length(target)+length(rid)+100;
  IF size>8388608 THEN RAISE EXCEPTION 'scientific_subject_byte_limit' USING ERRCODE='54000'; END IF;
  seen:=seen||jsonb_build_object(key,true);
  rows:=rows||jsonb_build_array(jsonb_build_object('table',target,'row_id',rid,'snapshot',snapshot));
  FOR rule IN SELECT value FROM jsonb_array_elements(COALESCE(rules->target,'[]'::jsonb)) LOOP
   IF snapshot->>(rule->>0) IS NOT NULL THEN
    pending:=pending||jsonb_build_array(jsonb_build_object('table',rule->>1,'row_id',snapshot->>(rule->>0))); END IF;
  END LOOP;
  IF fields ? target THEN
   support:=support||jsonb_build_array(snapshot->'source_artifact_id');
  ELSIF target='research_events' THEN
   IF snapshot->'context' ? 'materials_context' THEN
    ctx:=snapshot->'context'->'materials_context';
    IF public.sclib_materials_context_shape_v1(ctx) IS DISTINCT FROM true THEN
     RAISE EXCEPTION 'materials_event_context_contract' USING ERRCODE='23514'; END IF;
    FOR extra IN SELECT 'sample_compositions' AS tab,value AS id FROM jsonb_array_elements_text(ctx->'composition_ids')
     UNION ALL SELECT 'sample_relations',value FROM jsonb_array_elements_text(ctx->'relation_ids')
     UNION ALL SELECT 'research_protocols',ctx->>'protocol_id' WHERE ctx->>'protocol_id' IS NOT NULL LOOP
     pending:=pending||jsonb_build_array(jsonb_build_object('table',extra.tab,'row_id',extra.id)); END LOOP;
   END IF;
   FOR extra IN SELECT id,'event_evidence' AS tab FROM public.event_evidence WHERE event_id=rid::uuid
    UNION ALL SELECT id,'snapshot_event_memberships' FROM public.snapshot_event_memberships WHERE event_id=rid::uuid LIMIT 1001 LOOP
    pending:=pending||jsonb_build_array(jsonb_build_object('table',extra.tab,'row_id',extra.id::text)); END LOOP;
  ELSIF target='material_claims' THEN
   FOR extra IN SELECT id FROM public.claim_source_occurrences WHERE claim_id=rid::uuid LIMIT 1001 LOOP
    pending:=pending||jsonb_build_array(jsonb_build_object('table','claim_source_occurrences','row_id',extra.id::text)); END LOOP;
  ELSIF target='papers' AND EXISTS(SELECT 1 FROM public.paper_work_map WHERE paper_id=rid) THEN
   pending:=pending||jsonb_build_array(jsonb_build_object('table','paper_work_map','row_id',rid));
  END IF;
  IF jsonb_array_length(pending)+n>3000 THEN RAISE EXCEPTION 'scientific_subject_reference_limit' USING ERRCODE='54000'; END IF;
  IF target='evidence_artifacts' THEN
   artifacts:=artifacts||jsonb_build_array(jsonb_build_object('artifact_id',rid,'bytes_sha256',snapshot->'bytes_sha256','hash_status',snapshot->'hash_status'));
   IF jsonb_array_length(artifacts)>200 THEN RAISE EXCEPTION 'scientific_subject_artifact_limit' USING ERRCODE='54000'; END IF;
  END IF;
 END LOOP;
 SELECT jsonb_agg(value ORDER BY value->>'table' COLLATE "C",value->>'row_id' COLLATE "C") INTO rows FROM jsonb_array_elements(rows);
 SELECT COALESCE(jsonb_agg(value ORDER BY value->>'artifact_id'),'[]'::jsonb) INTO artifacts FROM jsonb_array_elements(artifacts);
 SELECT COALESCE(jsonb_agg(value ORDER BY value),'[]'::jsonb) INTO support FROM (SELECT DISTINCT value FROM jsonb_array_elements_text(support)) q;
 body:=body||jsonb_build_object('version','{VERSION}','rows',rows,'artifacts',artifacts,'support_artifact_ids',support);
 result:=public.sclib_scientific_adjudication_canonical_v1(body);
 IF octet_length(result)>8388608 THEN RAISE EXCEPTION 'scientific_subject_byte_limit' USING ERRCODE='54000'; END IF;
 RETURN result;
END $$"""]


def register(metadata):
    for sql in statements():
        sa.event.listen(metadata, "after_create", sa.DDL(sql.replace("%", "%%")).execute_if(dialect="postgresql"))
    sa.event.listen(metadata, "before_drop", sa.DDL(f"DROP FUNCTION IF EXISTS public.{FUNCTION}(text,uuid)").execute_if(dialect="postgresql"))
