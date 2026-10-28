"""0097: typed state conditions and source quantities in existing objects.

Ambient statements, numeric pressure and a condition's experimental role are
independent. Legacy scalar columns are generated projections for this version.
Geometry support points to an existing condition, never a duplicate result.
"""
from __future__ import annotations

import json
import sqlalchemy as sa
from models.materials_result_definitions_v1 import PROPERTY_CHECK

VERSION = "materials-conditions/1"
LINK_VERSION = "materials-state-link/1"
SOURCE_VERSION = "materials-source-quantity/1"
SUPPORT_VERSION = "materials-condition-support/1"
REGISTRY_VERSION = "materials-properties/2"

# Explicit unit registry. Factors convert retained source units into the
# existing scalar columns. Temperature conversion has an additive offset.
UNITS = {
    "pressure":{"Pa":[1e-9,0],"kPa":[1e-6,0],"MPa":[0.001,0],"GPa":[1,0],"bar":[0.0001,0],"kbar":[0.1,0],"atm":[0.000101325,0]},
    "temperature":{"K":[1,0],"°C":[1,273.15],"C":[1,273.15]},
    "magnetic_flux_density":{"T":[1,0],"mT":[0.001,0],"G":[0.0001,0]},
    "mu0_h":{"T":[1,0],"mT":[0.001,0]},
    "magnetic_field_strength":{"A/m":[1,0],"kA/m":[1000,0],"Oe":[79.57747154594767,0]},
    "thickness":{"nm":[1,0],"Å":[0.1,0],"angstrom":[0.1,0],"um":[1000,0],"µm":[1000,0],"μm":[1000,0]},
    "radius":{"nm":[1,0],"um":[1000,0],"µm":[1000,0],"μm":[1000,0],"mm":[1e6,0],"m":[1e9,0]},
    "strain":{"1":[1,0],"%":[0.01,0]},
    "carrier_density":{"cm^-3":[1,0],"cm^-2":[1,0]},
    "gate_voltage":{"V":[1,0],"mV":[0.001,0]},
    "delay":{"s":[1,0],"ms":[0.001,0],"us":[1e-6,0],"µs":[1e-6,0],"ns":[1e-9,0],"ps":[1e-12,0],"fs":[1e-15,0]},
}
LEGACY_STATE_PRESSURE = "(pressure_status='explicit_ambient' AND pressure_gpa=0) OR (pressure_status='reported' AND pressure_gpa>=0 AND pressure_gpa<'Infinity'::float8) OR (pressure_status IN ('not_reported','ambiguous') AND pressure_gpa IS NULL)"
LEGACY_STATE_REQUIRED = "pressure_status NOT IN ('explicit_ambient','reported') OR pressure_gpa IS NOT NULL"
LEGACY_CLAIM_STATE = "pressure_state IN ('explicit_ambient','reported','not_reported','ambiguous')"
LEGACY_CLAIM_PRESSURE = "(pressure_state='explicit_ambient' AND pressure_gpa=0) OR (pressure_state='reported' AND pressure_gpa IS NOT NULL) OR (pressure_state='not_reported' AND pressure_gpa IS NULL) OR pressure_state='ambiguous'"
LEGACY_CLAIM_REQUIRED = "pressure_state NOT IN ('explicit_ambient','reported') OR pressure_gpa IS NOT NULL"
FUNCTIONS = (
    ("sclib_materials_condition_number_v1","text,jsonb,text"),
    ("sclib_materials_conditions_v1","jsonb"),
    ("sclib_materials_state_insert_v1",""),
    ("sclib_materials_state_claim_v1",""),
    ("sclib_materials_state_event_v1",""),
    ("sclib_materials_source_quantity_v1",""),
    ("sclib_materials_state_legacy_gate_v1",""),
)


def functions():
    units="'"+json.dumps(UNITS,separators=(",",":"),ensure_ascii=False).replace("'","''")+"'::jsonb"
    return [f"""
CREATE FUNCTION public.sclib_materials_condition_number_v1(kind text,q jsonb,part text) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE units jsonb:={units}; conversion jsonb; BEGIN
 IF part NOT IN ('value','lower','upper') OR part IS NULL THEN
  RAISE EXCEPTION 'materials_condition_numeric_part' USING ERRCODE='23514'; END IF;
 IF q->part='null'::jsonb THEN RETURN NULL; END IF;
 conversion:=units->kind->(q->>'unit');
 IF conversion IS NULL OR jsonb_typeof(q->part) IS DISTINCT FROM 'number' THEN
  RAISE EXCEPTION 'materials_condition_unit_or_number' USING ERRCODE='23514'; END IF;
 RETURN (q->>part)::numeric*(conversion->>0)::numeric+(conversion->>1)::numeric;
END $$""", f"""
CREATE FUNCTION public.sclib_materials_conditions_v1(j jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE c jsonb; q jsonb; p jsonb; chosen jsonb; k text; seen text[]:='{{}}'; units jsonb:={units}; BEGIN
 IF NOT public.sclib_materials_closed_object_v1(j,ARRAY['items','pressure','temperature_condition_id'])
  OR jsonb_typeof(j->'items') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(j->'items')>64 THEN RETURN false; END IF;
 FOR c IN SELECT value FROM jsonb_array_elements(j->'items') LOOP
  IF NOT public.sclib_materials_closed_object_v1(c,ARRAY['id','kind','role','quantity','orientation_raw','basis_raw','window_position'])
   OR NOT public.sclib_materials_text_v1(c->'id',100,false)
   OR jsonb_typeof(c->'kind') IS DISTINCT FROM 'string' OR NOT units ? (c->>'kind')
   OR jsonb_typeof(c->'role') IS DISTINCT FROM 'string'
   OR c->>'role' NOT IN ('measurement','synthesis','simulation','detection_window','pump','sample_geometry','study_extent','fit_window','unknown')
   OR NOT public.sclib_materials_text_v1(c->'orientation_raw',1000,true)
   OR NOT public.sclib_materials_text_v1(c->'basis_raw',2000,true)
   OR public.sclib_materials_quantity_v1(c->'quantity') IS DISTINCT FROM true THEN RETURN false; END IF;
  IF (c->>'id')=ANY(seen) THEN RETURN false; END IF; seen:=array_append(seen,c->>'id');
  IF c->>'role'='detection_window' THEN
   IF jsonb_typeof(c->'window_position') IS DISTINCT FROM 'string'
    OR c->>'window_position' NOT IN ('lower_limit','upper_limit','interval','unspecified') THEN RETURN false; END IF;
  ELSIF c->'window_position'<>'null'::jsonb THEN RETURN false; END IF;
  q:=c->'quantity';
  IF q->>'status'='reported' THEN
   IF NOT (units->(c->>'kind')) ? (q->>'unit') THEN RETURN false; END IF;
   IF c->>'kind' IN ('pressure','temperature','thickness','radius','carrier_density') THEN
    FOREACH k IN ARRAY ARRAY['value','lower','upper'] LOOP
     IF public.sclib_materials_condition_number_v1(c->>'kind',q,k)<0 THEN RETURN false; END IF;
    END LOOP;
   END IF;
  END IF;
 END LOOP;
 p:=j->'pressure';
 IF NOT public.sclib_materials_closed_object_v1(p,ARRAY['availability','regime','condition_id','basis_raw'])
  OR jsonb_typeof(p->'availability') IS DISTINCT FROM 'string'
  OR p->>'availability' NOT IN ('reported','not_reported','not_extracted','not_accessible','ambiguous','conflicted','not_applicable')
  OR jsonb_typeof(p->'regime') IS DISTINCT FROM 'string' OR p->>'regime' NOT IN ('explicit_ambient','nonambient','unknown')
  OR NOT public.sclib_materials_text_v1(p->'condition_id',100,true)
  OR NOT public.sclib_materials_text_v1(p->'basis_raw',2000,true) THEN RETURN false; END IF;
 IF p->>'regime'<>'unknown' AND NOT public.sclib_materials_text_v1(p->'basis_raw',2000,false) THEN RETURN false; END IF;
 IF p->'condition_id'<>'null'::jsonb THEN
  SELECT value INTO chosen FROM jsonb_array_elements(j->'items') WHERE value->>'id'=p->>'condition_id';
  IF chosen IS NULL OR chosen->>'kind'<>'pressure' OR chosen->>'role' NOT IN ('measurement','simulation')
   OR chosen->'quantity'->>'status' IS DISTINCT FROM p->>'availability' THEN RETURN false; END IF;
 ELSIF p->>'availability'='reported' AND p->>'regime'<>'explicit_ambient' THEN RETURN false; END IF;
 IF p->>'availability'<>'reported' AND p->>'regime'<>'unknown' THEN RETURN false; END IF;
 IF NOT public.sclib_materials_text_v1(j->'temperature_condition_id',100,true) THEN RETURN false; END IF;
 IF j->'temperature_condition_id'<>'null'::jsonb THEN
  SELECT value INTO chosen FROM jsonb_array_elements(j->'items') WHERE value->>'id'=j->>'temperature_condition_id';
  IF chosen IS NULL OR chosen->>'kind'<>'temperature' OR chosen->>'role' NOT IN ('measurement','synthesis','simulation') THEN RETURN false; END IF;
 END IF;
 RETURN true;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_state_insert_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p jsonb; q jsonb; chosen jsonb; BEGIN
 IF TG_OP IN ('UPDATE','DELETE') AND OLD.condition_schema_version='materials-conditions/1' THEN
  IF TG_OP='DELETE' OR to_jsonb(OLD) IS DISTINCT FROM to_jsonb(NEW) THEN
   RAISE EXCEPTION 'materials_state_history_is_immutable' USING ERRCODE='55000'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='DELETE' OR NEW.condition_schema_version<>'materials-conditions/1' THEN RETURN COALESCE(NEW,OLD); END IF;
 IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'materials_state_new_identity_required' USING ERRCODE='55000'; END IF;
 PERFORM public.sclib_research_integrity_lock_v1();
 IF NEW.sample_id IS NULL OR octet_length(NEW.conditions::text)>131072
  OR public.sclib_materials_conditions_v1(NEW.conditions) IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM public.evidence_artifacts WHERE id=NEW.source_artifact_id AND kind='literature_locator') THEN
  RAISE EXCEPTION 'materials_state_condition_contract' USING ERRCODE='23514'; END IF;
 p:=NEW.conditions->'pressure';
 NEW.pressure_status:=CASE WHEN p->>'availability'='reported' AND p->>'regime'='explicit_ambient'
  THEN 'explicit_ambient' ELSE p->>'availability' END;
 NEW.pressure_gpa:=NULL;
 SELECT value INTO chosen FROM jsonb_array_elements(NEW.conditions->'items') WHERE value->>'id'=p->>'condition_id';
 IF chosen->'quantity'->>'status'='reported' AND chosen->'quantity'->>'relation'='exact' THEN
  NEW.pressure_gpa:=public.sclib_materials_condition_number_v1('pressure',chosen->'quantity','value')::float8; END IF;
 NEW.temperature_role:='unknown'; NEW.temperature_k:=NULL;
 SELECT value INTO chosen FROM jsonb_array_elements(NEW.conditions->'items') WHERE value->>'id'=NEW.conditions->>'temperature_condition_id';
 IF chosen IS NOT NULL THEN
  NEW.temperature_role:=chosen->>'role';
  IF chosen->'quantity'->>'status'='reported' AND chosen->'quantity'->>'relation'='exact' THEN
   NEW.temperature_k:=public.sclib_materials_condition_number_v1('temperature',chosen->'quantity','value')::float8; END IF;
 END IF;
 NEW.context_sha256:=public.sclib_scientific_adjudication_text_hash_v1(public.sclib_scientific_adjudication_canonical_v1(
  jsonb_build_object('material_id',NEW.material_id,'sample_id',NEW.sample_id,'resolution',NEW.resolution,
   'version',NEW.condition_schema_version,'conditions',NEW.conditions,'source_artifact_id',NEW.source_artifact_id)));
 RETURN NEW;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_state_claim_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE s public.material_states%ROWTYPE; j jsonb:=NEW.extraction_metadata->'state_semantics'; BEGIN
 SELECT st.* INTO s FROM public.research_events e JOIN public.material_states st ON st.id=e.state_id WHERE e.id=NEW.event_id;
 IF s.condition_schema_version='materials-conditions/1' THEN
  IF NOT public.sclib_materials_closed_object_v1(j,ARRAY['version']) OR j->>'version' IS DISTINCT FROM 'materials-state-link/1' THEN
   RAISE EXCEPTION 'materials_claim_state_link_required' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' AND (OLD.event_id IS DISTINCT FROM NEW.event_id OR OLD.extraction_metadata->'state_semantics' IS DISTINCT FROM j) THEN
   RAISE EXCEPTION 'materials_claim_new_state_identity_required' USING ERRCODE='55000'; END IF;
  NEW.pressure_state:=s.pressure_status; NEW.pressure_gpa:=s.pressure_gpa;
 ELSIF NEW.extraction_metadata ? 'state_semantics' OR (TG_OP='UPDATE' AND OLD.extraction_metadata ? 'state_semantics') THEN
  RAISE EXCEPTION 'materials_claim_typed_state_required' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_state_event_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE selected uuid; linked boolean; BEGIN
 selected:=CASE WHEN TG_OP='DELETE' THEN OLD.state_id ELSE NEW.state_id END;
 SELECT EXISTS(SELECT 1 FROM public.material_states WHERE id=selected AND condition_schema_version='materials-conditions/1') INTO linked;
 IF TG_OP='UPDATE' THEN
  linked:=linked OR EXISTS(SELECT 1 FROM public.material_states WHERE id=OLD.state_id AND condition_schema_version='materials-conditions/1');
  IF linked AND (to_jsonb(NEW)-ARRAY['review_status','validity_status','decision_artifact_id','record_sha256'])
   IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['review_status','validity_status','decision_artifact_id','record_sha256']) THEN
   RAISE EXCEPTION 'materials_event_new_state_revision_required' USING ERRCODE='55000'; END IF;
 ELSIF TG_OP='DELETE' AND linked THEN
  RAISE EXCEPTION 'materials_event_new_state_revision_required' USING ERRCODE='55000'; END IF;
 RETURN COALESCE(NEW,OLD);
END $$""", r"""
CREATE FUNCTION public.sclib_materials_source_quantity_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE j jsonb; q jsonb; c jsonb; edge jsonb; source_kind text; number numeric; s public.material_states%ROWTYPE;
 e public.research_events%ROWTYPE; p public.research_protocols%ROWTYPE; supports jsonb; seen text[]:='{}'; k text; BEGIN
 IF TG_OP IN ('UPDATE','DELETE') AND (OLD.raw ? 'source_quantity' OR OLD.raw ? 'condition_support') THEN
  IF TG_OP='DELETE' OR to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
   RAISE EXCEPTION 'materials_source_quantity_history_is_immutable' USING ERRCODE='55000'; END IF; RETURN NEW;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 IF NOT NEW.raw ? 'source_quantity' THEN
  IF NEW.raw ? 'condition_support' OR NEW.registry_version='materials-properties/2' THEN
   RAISE EXCEPTION 'materials_source_quantity_required' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'materials_source_quantity_new_result_required' USING ERRCODE='55000'; END IF;
 PERFORM public.sclib_research_integrity_lock_v1();
 j:=NEW.raw->'source_quantity';q:=j->'quantity';
 IF NOT public.sclib_materials_closed_object_v1(j,ARRAY['version','quantity'])
  OR j->>'version' IS DISTINCT FROM 'materials-source-quantity/1'
  OR public.sclib_materials_quantity_v1(q) IS DISTINCT FROM true OR q->>'status'<>'reported'
  OR NOT NEW.raw ? 'result_semantics' OR NEW.registry_version NOT IN ('materials-properties/1','materials-properties/2') THEN
  RAISE EXCEPTION 'materials_source_quantity_contract' USING ERRCODE='23514'; END IF;
 SELECT * INTO e FROM public.research_events WHERE id=NEW.event_id;
 SELECT * INTO s FROM public.material_states WHERE id=e.state_id;
 IF s.condition_schema_version IS DISTINCT FROM 'materials-conditions/1' THEN
  RAISE EXCEPTION 'materials_source_quantity_typed_state_required' USING ERRCODE='23514'; END IF;
 source_kind:=CASE NEW.property_key WHEN 'hc2' THEN 'magnetic_flux_density'
  WHEN 'coherence_length' THEN 'thickness' WHEN 'superconducting_layer_thickness' THEN 'thickness'
  WHEN 'thickness' THEN 'thickness' END;
 IF source_kind IS NULL OR NEW.relation IS DISTINCT FROM q->>'relation' THEN
  RAISE EXCEPTION 'materials_source_quantity_registry_or_shape' USING ERRCODE='23514'; END IF;
 FOREACH k IN ARRAY ARRAY['value','lower','upper'] LOOP
  number:=public.sclib_materials_condition_number_v1(source_kind,q,k);
  IF (to_jsonb(NEW)->>k)::float8 IS DISTINCT FROM number::float8 THEN
   RAISE EXCEPTION 'materials_source_quantity_scalar_projection' USING ERRCODE='23514'; END IF;
 END LOOP;
 -- Preserve uncertainty in its source unit in q. The old untyped uncertainty
 -- column is not allowed to introduce a second, inconsistent authority.
 IF NEW.uncertainty<>'{}'::jsonb THEN
  RAISE EXCEPTION 'materials_source_quantity_uses_typed_uncertainty' USING ERRCODE='23514'; END IF;
 IF NEW.raw ? 'condition_support' THEN
  supports:=NEW.raw->'condition_support';
  IF NOT public.sclib_materials_closed_object_v1(supports,ARRAY['version','targets'])
   OR supports->>'version' IS DISTINCT FROM 'materials-condition-support/1'
   OR jsonb_typeof(supports->'targets') IS DISTINCT FROM 'array' THEN
   RAISE EXCEPTION 'materials_condition_support_contract' USING ERRCODE='23514'; END IF;
  IF jsonb_array_length(supports->'targets') NOT BETWEEN 1 AND 16 OR NEW.property_key<>'thickness'
   OR e.event_type<>'measurement' OR e.knowledge_origin<>'Observed' THEN
   RAISE EXCEPTION 'materials_condition_support_measurement_required' USING ERRCODE='23514'; END IF;
  SELECT * INTO p FROM public.research_protocols WHERE id=(e.context#>>'{materials_context,protocol_id}')::uuid;
  IF p.id IS NULL OR p.method_class IN ('unspecified','calculation') OR p.method_raw IS NULL THEN
   RAISE EXCEPTION 'materials_condition_support_method_required' USING ERRCODE='23514'; END IF;
  FOR edge IN SELECT value FROM jsonb_array_elements(supports->'targets') LOOP
   IF NOT public.sclib_materials_closed_object_v1(edge,ARRAY['state_id','condition_id','relation','relation_raw'])
    OR edge->>'state_id' IS DISTINCT FROM s.id::text OR edge->>'relation' IS DISTINCT FROM 'measures'
    OR NOT public.sclib_materials_text_v1(edge->'condition_id',100,false)
    OR NOT public.sclib_materials_text_v1(edge->'relation_raw',2000,false) OR (edge->>'condition_id')=ANY(seen) THEN
    RAISE EXCEPTION 'materials_condition_support_owner' USING ERRCODE='23514'; END IF;
   seen:=array_append(seen,edge->>'condition_id');
   SELECT value INTO c FROM jsonb_array_elements(s.conditions->'items') WHERE value->>'id'=edge->>'condition_id';
   IF c IS NULL OR c->>'kind'<>'thickness' OR c->>'role'<>'sample_geometry' OR c->'quantity'->>'status'<>'reported'
    OR c->'quantity'->>'relation' IS DISTINCT FROM NEW.relation THEN
    RAISE EXCEPTION 'materials_condition_support_target' USING ERRCODE='23514'; END IF;
   FOREACH k IN ARRAY ARRAY['value','lower','upper'] LOOP
    IF public.sclib_materials_condition_number_v1('thickness',c->'quantity',k)
     IS DISTINCT FROM public.sclib_materials_condition_number_v1('thickness',q,k) THEN
     RAISE EXCEPTION 'materials_condition_support_numeric_mismatch' USING ERRCODE='23514'; END IF;
   END LOOP;
  END LOOP;
 END IF;
 NEW.record_sha256:=public.sclib_scientific_adjudication_record_hash_v1(to_jsonb(NEW));
 RETURN NEW;
END $$""", r"""
CREATE FUNCTION public.sclib_materials_state_legacy_gate_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF TG_TABLE_NAME='research_release_pins' THEN
  IF (NEW.table_name='material_states' AND NEW.row_data->>'condition_schema_version'='materials-conditions/1')
   OR (NEW.table_name='event_properties' AND (NEW.row_data->'raw' ? 'source_quantity' OR NEW.row_data->'raw' ? 'condition_support'))
   OR (NEW.table_name='material_claims' AND NEW.row_data->'extraction_metadata' ? 'state_semantics') THEN
   RAISE EXCEPTION 'materials_conditions_release_contract_required' USING ERRCODE='23514'; END IF;
 ELSE
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.basis_json::jsonb->'rows') r
   WHERE r->>'table'='material_states' AND r->'snapshot'->>'condition_schema_version'='materials-conditions/1') THEN
   RAISE EXCEPTION 'materials_conditions_review_contract_required' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$"""]


def upgrade_statements():
    new_property=f"({PROPERTY_CHECK}) OR (raw ? 'result_semantics' AND public.sclib_materials_result_semantics_v1(raw->'result_semantics','property') AND registry_version='{REGISTRY_VERSION}' AND property_key='thickness' AND unit='nm')"
    return ["LOCK TABLE public.material_states,public.material_claims,public.event_properties IN ACCESS EXCLUSIVE MODE",f"""DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.material_states WHERE condition_schema_version='{VERSION}')
  OR EXISTS(SELECT 1 FROM public.material_claims WHERE extraction_metadata ? 'state_semantics')
  OR EXISTS(SELECT 1 FROM public.event_properties WHERE raw ? 'source_quantity' OR raw ? 'condition_support' OR registry_version='{REGISTRY_VERSION}') THEN
  RAISE EXCEPTION 'materials_conditions_reserved_collision' USING ERRCODE='23514'; END IF; END $$""",
        *functions(),
        "ALTER TABLE public.material_states DROP CONSTRAINT ck_rv2_state_pressure, DROP CONSTRAINT ck_rv2_state_pressure_required",
        f"ALTER TABLE public.material_states ADD CONSTRAINT ck_rv2_state_pressure CHECK (condition_schema_version='{VERSION}' OR ({LEGACY_STATE_PRESSURE})), ADD CONSTRAINT ck_rv2_state_pressure_required CHECK (condition_schema_version='{VERSION}' OR ({LEGACY_STATE_REQUIRED}))",
        "ALTER TABLE public.material_claims DROP CONSTRAINT ck_material_claims_pressure_state, DROP CONSTRAINT ck_material_claims_pressure_semantics, DROP CONSTRAINT ck_ci47_claim_pressure_required",
        f"ALTER TABLE public.material_claims ADD CONSTRAINT ck_material_claims_pressure_state CHECK (extraction_metadata ? 'state_semantics' OR ({LEGACY_CLAIM_STATE})), ADD CONSTRAINT ck_material_claims_pressure_semantics CHECK (extraction_metadata ? 'state_semantics' OR ({LEGACY_CLAIM_PRESSURE})), ADD CONSTRAINT ck_ci47_claim_pressure_required CHECK (extraction_metadata ? 'state_semantics' OR ({LEGACY_CLAIM_REQUIRED}))",
        "ALTER TABLE public.event_properties DROP CONSTRAINT ck_rv2_property_registry",
        f"ALTER TABLE public.event_properties ADD CONSTRAINT ck_rv2_property_registry CHECK (({new_property}) IS TRUE)",
        "CREATE TRIGGER aa_mc97_state BEFORE INSERT OR UPDATE OR DELETE ON public.material_states FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_state_insert_v1()",
        "CREATE TRIGGER aa_mc97_claim BEFORE INSERT OR UPDATE ON public.material_claims FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_state_claim_v1()",
        "CREATE TRIGGER aa_mc97_event BEFORE UPDATE OR DELETE ON public.research_events FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_state_event_v1()",
        "CREATE TRIGGER aa_mc97_quantity BEFORE INSERT OR UPDATE OR DELETE ON public.event_properties FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_source_quantity_v1()",
        *[f"CREATE TRIGGER aa_mc97_legacy BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_state_legacy_gate_v1()" for name in ("research_release_pins","scientific_result_subjects")]]


def downgrade_statements():
    return ["LOCK TABLE public.material_states,public.material_claims,public.event_properties IN ACCESS EXCLUSIVE MODE",f"""DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.material_states WHERE condition_schema_version='{VERSION}')
  OR EXISTS(SELECT 1 FROM public.material_claims WHERE extraction_metadata ? 'state_semantics')
  OR EXISTS(SELECT 1 FROM public.event_properties WHERE raw ? 'source_quantity' OR raw ? 'condition_support' OR registry_version='{REGISTRY_VERSION}') THEN
  RAISE EXCEPTION 'materials_conditions_retained_history_refuses_downgrade' USING ERRCODE='23514'; END IF; END $$""",
        *[f"DROP TRIGGER {trigger} ON public.{table}" for table,trigger in [("material_states","aa_mc97_state"),("material_claims","aa_mc97_claim"),("research_events","aa_mc97_event"),("event_properties","aa_mc97_quantity"),("research_release_pins","aa_mc97_legacy"),("scientific_result_subjects","aa_mc97_legacy")]],
        "ALTER TABLE public.material_states DROP CONSTRAINT ck_rv2_state_pressure, DROP CONSTRAINT ck_rv2_state_pressure_required",
        f"ALTER TABLE public.material_states ADD CONSTRAINT ck_rv2_state_pressure CHECK ({LEGACY_STATE_PRESSURE}), ADD CONSTRAINT ck_rv2_state_pressure_required CHECK ({LEGACY_STATE_REQUIRED})",
        "ALTER TABLE public.material_claims DROP CONSTRAINT ck_material_claims_pressure_state, DROP CONSTRAINT ck_material_claims_pressure_semantics, DROP CONSTRAINT ck_ci47_claim_pressure_required",
        f"ALTER TABLE public.material_claims ADD CONSTRAINT ck_material_claims_pressure_state CHECK ({LEGACY_CLAIM_STATE}), ADD CONSTRAINT ck_material_claims_pressure_semantics CHECK ({LEGACY_CLAIM_PRESSURE}), ADD CONSTRAINT ck_ci47_claim_pressure_required CHECK ({LEGACY_CLAIM_REQUIRED})",
        "ALTER TABLE public.event_properties DROP CONSTRAINT ck_rv2_property_registry",
        f"ALTER TABLE public.event_properties ADD CONSTRAINT ck_rv2_property_registry CHECK ({PROPERTY_CHECK})",
        *[f"DROP FUNCTION public.{name}({args})" for name,args in reversed(FUNCTIONS)]]


def register(metadata):
    for sql in upgrade_statements():
        sa.event.listen(metadata,"after_create",sa.DDL(sql.replace("%","%%")).execute_if(dialect="postgresql"))
    for name,args in reversed(FUNCTIONS):
        sa.event.listen(metadata,"after_drop",sa.DDL(f"DROP FUNCTION IF EXISTS public.{name}({args})").execute_if(dialect="postgresql"))
