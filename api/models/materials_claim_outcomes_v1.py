"""0098: source Tc quantities, explicit non-detection and conditional assertions.

The three alternatives describe different scientific statements. Compatibility
columns are generated; an observation window never supplies an implicit Tc
bound. New scientific values are immutable and require a later review policy.
"""
import sqlalchemy as sa

VERSION = "materials-claim-outcome/1"
MEMBER = "materials_outcome"
FUNCTIONS = (
    ("sclib_materials_tc_number_v1", "jsonb,text"),
    ("sclib_materials_tc_quantity_v1", "jsonb"),
    ("sclib_materials_conditional_tc_v1", "jsonb"),
    ("sclib_materials_claim_outcome_v1", ""),
)


def functions():
    return [r"""
CREATE FUNCTION public.sclib_materials_tc_number_v1(q jsonb,k text) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF k IS NULL OR k NOT IN ('value','lower','upper') THEN
  RAISE EXCEPTION 'materials_tc_numeric_part' USING ERRCODE='23514'; END IF;
 IF q->k='null'::jsonb THEN RETURN NULL; END IF;
 IF jsonb_typeof(q->k) IS DISTINCT FROM 'number' OR q->>'unit' NOT IN ('K','mK') OR q->>'unit' IS NULL THEN
  RAISE EXCEPTION 'materials_tc_unit_or_number' USING ERRCODE='23514'; END IF;
 RETURN (q->>k)::numeric * CASE q->>'unit' WHEN 'mK' THEN 0.001 ELSE 1 END;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_tc_quantity_v1(q jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE k text; n numeric; BEGIN
 IF public.sclib_materials_quantity_v1(q) IS DISTINCT FROM true OR q->>'status'='not_applicable' THEN RETURN false; END IF;
 IF q->'unit'<>'null'::jsonb AND q->>'unit' NOT IN ('K','mK') THEN RETURN false; END IF;
 IF q->>'status'='reported' THEN
  FOREACH k IN ARRAY ARRAY['value','lower','upper'] LOOP
   n:=public.sclib_materials_tc_number_v1(q,k);
   IF n<0 OR n>1.7976931348623157e308 THEN RETURN false; END IF;
  END LOOP;
 END IF;
 RETURN true;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_conditional_tc_v1(j jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF NOT public.sclib_materials_closed_object_v1(j,ARRAY['condition','raw','tc_bound'])
  OR j->>'condition' IS DISTINCT FROM 'if_superconducting'
  OR NOT public.sclib_materials_text_v1(j->'raw',4000,false) THEN RETURN false; END IF;
 IF j->'tc_bound'<>'null'::jsonb THEN
  IF public.sclib_materials_tc_quantity_v1(j->'tc_bound') IS DISTINCT FROM true
   OR j->'tc_bound'->>'status' IS DISTINCT FROM 'reported'
   OR j->'tc_bound'->>'relation' NOT IN ('lt','le','interval') THEN RETURN false; END IF;
 END IF;
 RETURN true;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_claim_outcome_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE j jsonb; q jsonb; w jsonb; c jsonb; k text; keys text[]; seen text[]:='{}'; key jsonb;
 s public.material_states%ROWTYPE; e public.research_events%ROWTYPE; p public.research_protocols%ROWTYPE;
 floor_value numeric; lower_count integer:=0; unresolved_lower boolean:=false; BEGIN
 IF TG_OP='DELETE' THEN
  IF OLD.extraction_metadata ? 'materials_outcome' THEN
   RAISE EXCEPTION 'materials_outcome_history_is_immutable' USING ERRCODE='55000'; END IF;
  RETURN OLD;
 END IF;
 IF TG_OP='UPDATE' AND OLD.extraction_metadata ? 'materials_outcome' THEN
  IF (to_jsonb(NEW)-ARRAY['validity_status','updated_at']) IS DISTINCT FROM
   (to_jsonb(OLD)-ARRAY['validity_status','updated_at']) THEN
   RAISE EXCEPTION 'materials_outcome_new_claim_revision_required' USING ERRCODE='55000'; END IF;
 ELSIF TG_OP='UPDATE' AND NEW.extraction_metadata ? 'materials_outcome' THEN
  RAISE EXCEPTION 'materials_outcome_new_claim_revision_required' USING ERRCODE='55000';
 END IF;
 IF NOT NEW.extraction_metadata ? 'materials_outcome' THEN RETURN NEW; END IF;
 PERFORM public.sclib_research_integrity_lock_v1();
 IF NEW.validity_status='accepted' THEN
  RAISE EXCEPTION 'materials_outcome_review_policy_required' USING ERRCODE='23514'; END IF;
 j:=NEW.extraction_metadata->'materials_outcome';
 IF jsonb_typeof(j) IS DISTINCT FROM 'object' OR octet_length(j::text)>65536
  OR j->>'version' IS DISTINCT FROM 'materials-claim-outcome/1' OR j->>'kind' IS NULL
  OR j->>'kind' NOT IN ('tc','non_detection','conditional_tc') THEN
  RAISE EXCEPTION 'materials_outcome_contract' USING ERRCODE='23514'; END IF;
 SELECT * INTO e FROM public.research_events WHERE id=NEW.event_id;
 SELECT * INTO s FROM public.material_states WHERE id=e.state_id;
 IF s.condition_schema_version IS DISTINCT FROM 'materials-conditions/1'
  OR NEW.result_key IS NULL OR length(btrim(NEW.result_key))=0 OR NEW.work_id IS NULL
  OR NOT EXISTS(SELECT 1 FROM public.research_samples WHERE id=s.sample_id AND work_id=NEW.work_id)
  OR NEW.extraction_metadata#>>'{state_semantics,version}' IS DISTINCT FROM 'materials-state-link/1' THEN
  RAISE EXCEPTION 'materials_outcome_typed_state_and_work_required' USING ERRCODE='23514'; END IF;
 SELECT * INTO p FROM public.research_protocols WHERE id=(e.context#>>'{materials_context,protocol_id}')::uuid;
 -- A selected method is the authority. Its absence/unspecified state never
 -- becomes a guessed method in the legacy scalar column.
 NEW.measurement_method:=CASE WHEN p.id IS NOT NULL AND p.method_class<>'unspecified' THEN p.method_class ELSE NULL END;
 NEW.minimum_temperature_k:=NULL;
 NEW.value_kelvin:=NULL;NEW.value_lower_kelvin:=NULL;NEW.value_upper_kelvin:=NULL;NEW.value_relation:='unreported';
 IF j->>'kind'='tc' THEN
  IF NOT public.sclib_materials_closed_object_v1(j,ARRAY['version','kind','quantity'])
   OR public.sclib_materials_tc_quantity_v1(j->'quantity') IS DISTINCT FROM true
   OR public.sclib_materials_result_semantics_v1(NEW.extraction_metadata->'result_semantics','claim') IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'materials_outcome_tc_quantity_and_definition' USING ERRCODE='23514'; END IF;
  q:=j->'quantity';NEW.property_type:='tc';
  NEW.tc_definition:=NEW.extraction_metadata#>>'{result_semantics,definition,criterion}';
  NEW.result_status:=CASE WHEN q->>'status'='reported' THEN 'observed'
   WHEN q->>'status' IN ('ambiguous','conflicted') THEN 'inconclusive' ELSE 'unknown' END;
  IF q->>'status'='reported' THEN
   NEW.value_relation:=q->>'relation';
   NEW.value_kelvin:=public.sclib_materials_tc_number_v1(q,'value')::float8;
   NEW.value_lower_kelvin:=public.sclib_materials_tc_number_v1(q,'lower')::float8;
   NEW.value_upper_kelvin:=public.sclib_materials_tc_number_v1(q,'upper')::float8;
  END IF;
 ELSE
  IF NEW.extraction_metadata ? 'result_semantics' THEN
   RAISE EXCEPTION 'materials_outcome_negative_is_not_tc_definition' USING ERRCODE='23514'; END IF;
  NEW.property_type:='non_transition';NEW.tc_definition:='unknown';
  IF j->>'kind'='conditional_tc' THEN
   IF NOT public.sclib_materials_closed_object_v1(j,ARRAY['version','kind','conditional'])
    OR public.sclib_materials_conditional_tc_v1(j->'conditional') IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'materials_outcome_conditional_contract' USING ERRCODE='23514'; END IF;
   NEW.result_status:='inconclusive';
  ELSE
   keys:=ARRAY['version','kind','target','observable','raw','window'];
   IF j ? 'conditional' THEN keys:=array_append(keys,'conditional');
    IF public.sclib_materials_conditional_tc_v1(j->'conditional') IS DISTINCT FROM true THEN
     RAISE EXCEPTION 'materials_outcome_conditional_contract' USING ERRCODE='23514'; END IF;
   END IF;
   IF NOT public.sclib_materials_closed_object_v1(j,keys) OR j->>'target' IS DISTINCT FROM 'superconductivity'
    OR jsonb_typeof(j->'observable') IS DISTINCT FROM 'string'
    OR j->>'observable' NOT IN ('resistive_transition','zero_resistance','diamagnetic_signal','heat_capacity_anomaly','unspecified')
    OR NOT public.sclib_materials_text_v1(j->'raw',4000,false)
    OR e.event_type IS DISTINCT FROM 'measurement' OR e.knowledge_origin IS DISTINCT FROM 'Observed'
    OR NEW.evidence_role='primary_theoretical' OR p.method_class='calculation' THEN
    RAISE EXCEPTION 'materials_outcome_observed_non_detection_required' USING ERRCODE='23514'; END IF;
   NEW.result_status:='not_detected';w:=j->'window';
   IF NOT public.sclib_materials_closed_object_v1(w,ARRAY['availability','condition_ids'])
    OR jsonb_typeof(w->'availability') IS DISTINCT FROM 'string'
    OR w->>'availability' NOT IN ('reported','not_reported','not_extracted','not_accessible','ambiguous','conflicted')
    OR jsonb_typeof(w->'condition_ids') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'materials_outcome_window_contract' USING ERRCODE='23514'; END IF;
   IF (w->>'availability'='reported' AND jsonb_array_length(w->'condition_ids') NOT BETWEEN 1 AND 16)
    OR (w->>'availability'<>'reported' AND jsonb_array_length(w->'condition_ids')<>0) THEN
    RAISE EXCEPTION 'materials_outcome_window_availability' USING ERRCODE='23514'; END IF;
   FOR key IN SELECT value FROM jsonb_array_elements(w->'condition_ids') LOOP
    IF NOT public.sclib_materials_text_v1(key,100,false) OR (key#>>'{}')=ANY(seen) THEN
     RAISE EXCEPTION 'materials_outcome_window_identity' USING ERRCODE='23514'; END IF;
    k:=key#>>'{}';seen:=array_append(seen,k);
    SELECT value INTO c FROM jsonb_array_elements(s.conditions->'items') WHERE value->>'id'=k;
    IF c IS NULL OR c->>'kind'<>'temperature' OR c->>'role'<>'detection_window'
     OR c->'quantity'->>'status'<>'reported' THEN
     RAISE EXCEPTION 'materials_outcome_window_state_ownership' USING ERRCODE='23514'; END IF;
    q:=c->'quantity';
    IF (q->>'relation'='interval') IS DISTINCT FROM (c->>'window_position'='interval')
     OR (c->>'window_position'='lower_limit' AND q->>'relation' IN ('lt','le'))
     OR (c->>'window_position'='upper_limit' AND q->>'relation' IN ('gt','ge')) THEN
     RAISE EXCEPTION 'materials_outcome_window_shape' USING ERRCODE='23514'; END IF;
    IF c->>'window_position'='interval' THEN
     floor_value:=public.sclib_materials_condition_number_v1('temperature',q,'lower');lower_count:=lower_count+1;
    ELSIF c->>'window_position'='lower_limit' AND q->>'relation'='exact' THEN
     floor_value:=public.sclib_materials_condition_number_v1('temperature',q,'value');lower_count:=lower_count+1;
    ELSIF c->>'window_position' IN ('lower_limit','unspecified') THEN unresolved_lower:=true;
    END IF;
   END LOOP;
   IF lower_count=1 AND NOT unresolved_lower THEN NEW.minimum_temperature_k:=floor_value::float8; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$"""]


def upgrade_statements():
    return ["LOCK TABLE public.material_claims IN ACCESS EXCLUSIVE MODE", r"""
DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.material_claims WHERE extraction_metadata ? 'materials_outcome') THEN
 RAISE EXCEPTION 'materials_outcome_reserved_member_collision' USING ERRCODE='23514'; END IF; END $$""",
        *functions(),
        "CREATE TRIGGER ab_mo98_claim BEFORE INSERT OR UPDATE OR DELETE ON public.material_claims FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_claim_outcome_v1()"]


def downgrade_statements():
    return ["LOCK TABLE public.material_claims IN ACCESS EXCLUSIVE MODE", r"""
DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.material_claims WHERE extraction_metadata ? 'materials_outcome') THEN
 RAISE EXCEPTION 'materials_outcome_retained_history_refuses_downgrade' USING ERRCODE='23514'; END IF; END $$""",
        "DROP TRIGGER ab_mo98_claim ON public.material_claims",
        *[f"DROP FUNCTION public.{name}({args})" for name,args in reversed(FUNCTIONS)]]


def register(metadata):
    for sql in upgrade_statements():
        sa.event.listen(metadata,"after_create",sa.DDL(sql.replace("%","%%")).execute_if(dialect="postgresql"))
    for name,args in reversed(FUNCTIONS):
        sa.event.listen(metadata,"after_drop",sa.DDL(f"DROP FUNCTION IF EXISTS public.{name}({args})").execute_if(dialect="postgresql"))
