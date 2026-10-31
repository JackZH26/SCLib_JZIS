"""0099: target-specific non-detections in existing event properties.

The scalar compatibility columns contain no Tc or invented upper bound. This
closed, sparse branch preserves device and superconductivity observations
without reinterpreting any older superconductivity-only claim. All new rows
remain private candidates pending a versioned scientific review policy.
"""
import sqlalchemy as sa

from models.materials_result_definitions_v1 import PROPERTY_CHECK
from models.materials_conditions_v1 import REGISTRY_VERSION as CONDITIONS_REGISTRY

VERSION='materials-observation-outcome/1'
REGISTRY_VERSION='materials-observables/1'
MEMBER='observation_outcome'
PREVIOUS_PROPERTY_CHECK=f"({PROPERTY_CHECK}) OR (raw ? 'result_semantics' AND public.sclib_materials_result_semantics_v1(raw->'result_semantics','property') AND registry_version='{CONDITIONS_REGISTRY}' AND property_key='thickness' AND unit='nm')"
FUNCTIONS=(
    ('sclib_materials_sensitivity_v1','jsonb'),
    ('sclib_materials_observation_shape_v1','jsonb'),
    ('sclib_materials_observation_insert_v1',''),
    ('sclib_materials_observation_event_gate_v1',''),
    ('sclib_materials_observation_release_gate_v1',''),
)


def functions():
    return [r"""
CREATE FUNCTION public.sclib_materials_sensitivity_v1(j jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE q jsonb; k text; BEGIN
 IF NOT public.sclib_materials_closed_object_v1(j,ARRAY['role','quantity_kind','quantity','raw'])
  OR jsonb_typeof(j->'role') IS DISTINCT FROM 'string'
  OR j->>'role' NOT IN ('measurement_step','instrument_resolution','detection_threshold','noise_floor')
  OR j->>'quantity_kind' IS DISTINCT FROM 'electric_current'
  OR NOT public.sclib_materials_text_v1(j->'raw',4000,false)
  OR public.sclib_materials_quantity_v1(j->'quantity') IS DISTINCT FROM true THEN RETURN false; END IF;
 q:=j->'quantity';
 IF q->>'status' IS DISTINCT FROM 'reported' OR q->>'unit' NOT IN ('A','mA','uA','μA','µA','nA','pA') THEN RETURN false; END IF;
 FOREACH k IN ARRAY ARRAY['value','lower','upper'] LOOP
  IF q->k<>'null'::jsonb AND ((q->>k)::numeric<0 OR (q->>k)::numeric>1.7976931348623157e308) THEN RETURN false; END IF;
 END LOOP;
 -- A lexical conflict is a hold, never an automatic reinterpretation.
 IF j->>'role'<>'measurement_step' AND j->>'raw' ~* '\m(step|increment)\M' THEN RETURN false; END IF;
 RETURN true;
END $$""",r"""
CREATE FUNCTION public.sclib_materials_observation_shape_v1(j jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE keys text[]:=ARRAY['version','kind','result_key','target','observable','existence','raw','window','sensitivities','source_role','cited_source_raw'];
 w jsonb; item jsonb; seen text[]:='{}'; BEGIN
 IF j ? 'conditional' THEN keys:=array_append(keys,'conditional');
  IF j->>'target' IS DISTINCT FROM 'superconductivity'
   OR public.sclib_materials_conditional_tc_v1(j->'conditional') IS DISTINCT FROM true THEN RETURN false; END IF;
 END IF;
 IF NOT public.sclib_materials_closed_object_v1(j,keys) OR octet_length(j::text)>65536
  OR j->>'version' IS DISTINCT FROM 'materials-observation-outcome/1'
  OR j->>'kind' IS DISTINCT FROM 'non_detection' OR j->>'existence' IS DISTINCT FROM 'not_established'
  OR NOT public.sclib_materials_text_v1(j->'result_key',120,false)
  OR NOT public.sclib_materials_text_v1(j->'raw',4000,false)
  OR NOT public.sclib_materials_text_v1(j->'cited_source_raw',4000,true)
  OR jsonb_typeof(j->'source_role') IS DISTINCT FROM 'string'
  OR j->>'source_role' NOT IN ('primary','cited','unknown') THEN RETURN false; END IF;
 IF j->>'source_role'='cited' AND NOT public.sclib_materials_text_v1(j->'cited_source_raw',4000,false) THEN RETURN false; END IF;
 IF ((j->>'target'='superconductivity' AND j->>'observable' IN
    ('resistive_transition','zero_resistance','diamagnetic_signal','heat_capacity_anomaly','unspecified'))
   OR (j->>'target'='supercurrent' AND j->>'observable'='supercurrent')
   OR (j->>'target'='josephson_phase_transition' AND j->>'observable'='zero_pi_transition')) IS DISTINCT FROM true THEN RETURN false; END IF;
 IF j->>'target'='superconductivity' AND (j->>'raw' ~* 'supercurrent'
   OR replace(j->>'raw','$','') ~* '(0|zero)[[:space:]]*(-|–|−)+[[:space:]]*(\\pi|π|pi)') THEN RETURN false; END IF;
 w:=j->'window';
 IF NOT public.sclib_materials_closed_object_v1(w,ARRAY['availability','condition_ids'])
  OR jsonb_typeof(w->'availability') IS DISTINCT FROM 'string'
  OR w->>'availability' NOT IN ('reported','not_reported','not_extracted','not_accessible','ambiguous','conflicted')
  OR jsonb_typeof(w->'condition_ids') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF (w->>'availability'='reported' AND jsonb_array_length(w->'condition_ids') NOT BETWEEN 1 AND 16)
  OR (w->>'availability'<>'reported' AND jsonb_array_length(w->'condition_ids')<>0) THEN RETURN false; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(w->'condition_ids') LOOP
  IF NOT public.sclib_materials_text_v1(item,100,false) OR (item#>>'{}')=ANY(seen) THEN RETURN false; END IF;
  seen:=array_append(seen,item#>>'{}');
 END LOOP;
 IF jsonb_typeof(j->'sensitivities') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(j->'sensitivities')>16 THEN RETURN false; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(j->'sensitivities') LOOP
  IF public.sclib_materials_sensitivity_v1(item) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$""",r"""
CREATE FUNCTION public.sclib_materials_observation_insert_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE j jsonb; c jsonb; q jsonb; k text; e public.research_events%ROWTYPE;
 s public.material_states%ROWTYPE; p public.research_protocols%ROWTYPE; BEGIN
 IF TG_OP IN ('UPDATE','DELETE') AND OLD.raw ? 'observation_outcome' THEN
  IF TG_OP='DELETE' OR to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
   RAISE EXCEPTION 'materials_observation_history_is_immutable' USING ERRCODE='55000'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 IF NOT NEW.raw ? 'observation_outcome' AND NEW.registry_version<>'materials-observables/1' THEN RETURN NEW; END IF;
 IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'materials_observation_new_result_required' USING ERRCODE='55000'; END IF;
 PERFORM public.sclib_research_integrity_lock_v1();
 j:=NEW.raw->'observation_outcome';
 IF NOT public.sclib_materials_closed_object_v1(NEW.raw,ARRAY['observation_outcome'])
  OR public.sclib_materials_observation_shape_v1(j) IS DISTINCT FROM true
  OR NEW.registry_version<>'materials-observables/1' OR NEW.property_key<>'non_detection'
  OR NEW.unit<>'not_applicable' OR NEW.relation<>'unreported'
  OR NEW.value IS NOT NULL OR NEW.lower IS NOT NULL OR NEW.upper IS NOT NULL OR NEW.uncertainty<>'{}'::jsonb THEN
  RAISE EXCEPTION 'materials_observation_contract' USING ERRCODE='23514'; END IF;
 SELECT * INTO e FROM public.research_events WHERE id=NEW.event_id;
 SELECT * INTO s FROM public.material_states WHERE id=e.state_id;
 SELECT * INTO p FROM public.research_protocols WHERE id=(e.context#>>'{materials_context,protocol_id}')::uuid;
 IF s.condition_schema_version IS DISTINCT FROM 'materials-conditions/1'
  OR e.event_type IS DISTINCT FROM 'measurement' OR e.knowledge_origin IS DISTINCT FROM 'Observed'
  OR p.id IS NULL OR p.method_class IN ('unspecified','calculation') OR p.method_raw IS NULL
  OR NOT EXISTS(SELECT 1 FROM public.research_samples x WHERE x.id=s.sample_id AND x.work_id=p.work_id) THEN
  RAISE EXCEPTION 'materials_observation_source_scoped_measurement_required' USING ERRCODE='23514'; END IF;
 IF e.review_status='approved' OR e.validity_status='accepted' THEN
  RAISE EXCEPTION 'materials_observation_review_policy_required' USING ERRCODE='23514'; END IF;
 FOR k IN SELECT value FROM jsonb_array_elements_text(j#>'{window,condition_ids}') LOOP
  SELECT value INTO c FROM jsonb_array_elements(s.conditions->'items') WHERE value->>'id'=k;
  IF c IS NULL OR c->'quantity'->>'status'<>'reported' THEN
   RAISE EXCEPTION 'materials_observation_window_state_ownership' USING ERRCODE='23514'; END IF;
  IF (j->>'target'='superconductivity' AND (c->>'kind'<>'temperature' OR c->>'role'<>'detection_window'))
   OR (j->>'target'<>'superconductivity' AND (c->>'kind' NOT IN
     ('temperature','thickness','pressure','magnetic_flux_density','magnetic_field_strength','mu0_h')
     OR c->>'role' NOT IN ('detection_window','study_extent'))) THEN
   RAISE EXCEPTION 'materials_observation_window_role' USING ERRCODE='23514'; END IF;
  q:=c->'quantity';
  IF q->>'relation'='exact' AND COALESCE(c->>'window_position','unspecified') NOT IN ('lower_limit','upper_limit') THEN
   RAISE EXCEPTION 'materials_observation_point_is_not_scan_window' USING ERRCODE='23514'; END IF;
  IF c->>'role'='detection_window' AND (
   (q->>'relation'='interval') IS DISTINCT FROM (c->>'window_position'='interval')
   OR (c->>'window_position'='lower_limit' AND q->>'relation' IN ('lt','le'))
   OR (c->>'window_position'='upper_limit' AND q->>'relation' IN ('gt','ge'))) THEN
   RAISE EXCEPTION 'materials_observation_window_shape' USING ERRCODE='23514'; END IF;
 END LOOP;
 NEW.record_sha256:=public.sclib_scientific_adjudication_record_hash_v1(to_jsonb(NEW));
 RETURN NEW;
END $$""",r"""
CREATE FUNCTION public.sclib_materials_observation_event_gate_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 PERFORM public.sclib_research_integrity_lock_v1();
 IF (NEW.review_status='approved' OR NEW.validity_status='accepted') AND EXISTS(
  SELECT 1 FROM public.event_properties WHERE event_id=NEW.id AND raw ? 'observation_outcome') THEN
  RAISE EXCEPTION 'materials_observation_review_policy_required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$""",r"""
CREATE FUNCTION public.sclib_materials_observation_release_gate_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF NEW.table_name='event_properties' AND NEW.row_data->'raw' ? 'observation_outcome' THEN
  RAISE EXCEPTION 'materials_observation_release_policy_required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$"""]


def upgrade_statements():
    return ["LOCK TABLE public.event_properties,public.research_events,public.research_release_pins IN ACCESS EXCLUSIVE MODE",r"""
DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.event_properties WHERE raw ? 'observation_outcome' OR registry_version='materials-observables/1') THEN
 RAISE EXCEPTION 'materials_observation_reserved_member_collision' USING ERRCODE='23514'; END IF; END $$""",
        *functions(),
        "ALTER TABLE public.event_properties DROP CONSTRAINT ck_rv2_property_registry",
        f"ALTER TABLE public.event_properties ADD CONSTRAINT ck_rv2_property_registry CHECK (((NOT raw ? '{MEMBER}' AND ({PREVIOUS_PROPERTY_CHECK})) OR (registry_version='{REGISTRY_VERSION}' AND property_key='non_detection' AND unit='not_applicable' AND public.sclib_materials_observation_shape_v1(raw->'{MEMBER}'))) IS TRUE)",
        "DROP INDEX public.uq_mrd93_legacy_component",
        "CREATE UNIQUE INDEX uq_mrd93_legacy_component ON public.event_properties(event_id,property_key,registry_version,component_key) WHERE NOT (raw ? 'result_semantics' OR raw ? 'observation_outcome')",
        "DROP INDEX public.uq_mrd93_event_result_key",
        "CREATE UNIQUE INDEX uq_mrd93_event_result_key ON public.event_properties(event_id,(COALESCE(raw#>>'{result_semantics,result_key}',raw#>>'{observation_outcome,result_key}'))) WHERE raw ? 'result_semantics' OR raw ? 'observation_outcome'",
        "CREATE TRIGGER ab_mo99_property BEFORE INSERT OR UPDATE OR DELETE ON public.event_properties FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_observation_insert_v1()",
        "CREATE TRIGGER ab_mo99_event BEFORE INSERT OR UPDATE ON public.research_events FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_observation_event_gate_v1()",
        "CREATE TRIGGER ab_mo99_release BEFORE INSERT OR UPDATE ON public.research_release_pins FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_observation_release_gate_v1()"]


def downgrade_statements():
    return ["LOCK TABLE public.event_properties,public.research_events,public.research_release_pins IN ACCESS EXCLUSIVE MODE",r"""
DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.event_properties WHERE raw ? 'observation_outcome') THEN
 RAISE EXCEPTION 'materials_observation_retained_history_refuses_downgrade' USING ERRCODE='23514'; END IF; END $$""",
        "DROP TRIGGER ab_mo99_release ON public.research_release_pins",
        "DROP TRIGGER ab_mo99_event ON public.research_events",
        "DROP TRIGGER ab_mo99_property ON public.event_properties",
        "DROP INDEX public.uq_mrd93_event_result_key",
        "DROP INDEX public.uq_mrd93_legacy_component",
        "CREATE UNIQUE INDEX uq_mrd93_legacy_component ON public.event_properties(event_id,property_key,registry_version,component_key) WHERE NOT (raw ? 'result_semantics')",
        "CREATE UNIQUE INDEX uq_mrd93_event_result_key ON public.event_properties(event_id,(raw#>>'{result_semantics,result_key}')) WHERE raw ? 'result_semantics'",
        "ALTER TABLE public.event_properties DROP CONSTRAINT ck_rv2_property_registry",
        f"ALTER TABLE public.event_properties ADD CONSTRAINT ck_rv2_property_registry CHECK (({PREVIOUS_PROPERTY_CHECK}) IS TRUE)",
        *[f"DROP FUNCTION public.{name}({args})" for name,args in reversed(FUNCTIONS)]]


def register(metadata):
    for sql in upgrade_statements():
        sa.event.listen(metadata,'after_create',sa.DDL(sql.replace('%','%%')).execute_if(dialect='postgresql'))
    for name,args in reversed(FUNCTIONS):
        sa.event.listen(metadata,'after_drop',sa.DDL(f'DROP FUNCTION IF EXISTS public.{name}({args})').execute_if(dialect='postgresql'))
