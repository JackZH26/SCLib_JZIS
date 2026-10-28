"""0104: sparse device conditions and source-defined fit intersections.

No tables or nullable catalogue columns. Historical validators remain callable.
New histories require new identities and cannot pass the old publication gates.
"""
from __future__ import annotations

import sqlalchemy as sa
from models import materials_conditions_adoption_v2 as previous
from models import materials_properties_v3 as properties
from models import materials_result_definitions_v1 as definitions

VERSION = 'materials-conditions/3'
DEFINITION_VERSION = 'materials-result-semantics/2'
VERSION_SQL = "('materials-conditions/1','materials-conditions/2','materials-conditions/3')"
FUNCTIONS = [('sclib_materials_conditions_v3', 'jsonb'),
             ('sclib_materials_condition_number_v3', 'text,jsonb,text'),
             ('sclib_materials_result_semantics_v2', 'jsonb,text')]


def functions():
    return [r"""
CREATE FUNCTION public.sclib_materials_conditions_v3(j jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE c jsonb; q jsonb; legacy jsonb:='[]'; seen text[]:='{}'; BEGIN
 IF NOT public.sclib_materials_closed_object_v1(j,ARRAY['items','pressure','temperature_condition_id'])
  OR jsonb_typeof(j->'items') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(j->'items')>64 THEN RETURN false; END IF;
 FOR c IN SELECT value FROM jsonb_array_elements(j->'items') LOOP
  IF (c->>'id')=ANY(seen) THEN RETURN false; END IF; seen:=array_append(seen,c->>'id');
  IF c->>'kind' IN ('twist_angle','reported_displacement_field') THEN
   IF NOT public.sclib_materials_closed_object_v1(c,ARRAY['id','kind','role','quantity','orientation_raw','basis_raw','window_position'])
    OR NOT public.sclib_materials_text_v1(c->'id',100,false)
    OR jsonb_typeof(c->'role') IS DISTINCT FROM 'string'
    OR c->>'role' NOT IN ('measurement','synthesis','simulation','detection_window','pump','sample_geometry','study_extent','fit_window','extrapolation_target','unknown')
    OR NOT public.sclib_materials_text_v1(c->'orientation_raw',1000,true)
    OR NOT public.sclib_materials_text_v1(c->'basis_raw',2000,false)
    OR public.sclib_materials_quantity_v1(c->'quantity') IS DISTINCT FROM true THEN RETURN false; END IF;
   IF c->>'role'='detection_window' THEN
    IF jsonb_typeof(c->'window_position') IS DISTINCT FROM 'string'
     OR c->>'window_position' NOT IN ('lower_limit','upper_limit','interval','unspecified') THEN RETURN false; END IF;
   ELSIF c->'window_position'<>'null'::jsonb THEN RETURN false; END IF;
   q:=c->'quantity';
   IF q->>'status'='reported' THEN
    IF c->>'kind'='twist_angle' AND (q->>'unit' IS NULL OR q->>'unit' NOT IN ('deg','°')) THEN RETURN false; END IF;
    IF c->>'kind'='reported_displacement_field' AND q->>'unit' IS DISTINCT FROM 'V/nm' THEN RETURN false; END IF;
   END IF;
  ELSE
   IF c->>'role'='extrapolation_target' THEN
    IF NOT public.sclib_materials_text_v1(c->'basis_raw',2000,false) THEN RETURN false; END IF;
    -- Validation-only role substitution; the stored object is never rewritten.
    legacy:=legacy||jsonb_build_array(jsonb_set(c,'{role}','"fit_window"'));
   ELSE legacy:=legacy||jsonb_build_array(c); END IF;
  END IF;
 END LOOP;
 -- A new descriptor cannot be selected as pressure or measurement temperature.
 RETURN public.sclib_materials_conditions_v2(jsonb_set(j,'{items}',legacy));
END $$""", r"""
CREATE FUNCTION public.sclib_materials_condition_number_v3(kind text,q jsonb,part text) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF kind='reported_displacement_field' THEN
  RAISE EXCEPTION 'materials_displacement_field_convention_unresolved' USING ERRCODE='23514'; END IF;
 IF kind='twist_angle' THEN
  IF part IS NULL OR part NOT IN ('value','lower','upper') OR q->>'unit' IS NULL OR q->>'unit' NOT IN ('deg','°') THEN
   RAISE EXCEPTION 'materials_twist_angle_unit_or_number' USING ERRCODE='23514'; END IF;
  IF q->part='null'::jsonb THEN RETURN NULL; END IF;
  IF jsonb_typeof(q->part) IS DISTINCT FROM 'number' THEN
   RAISE EXCEPTION 'materials_twist_angle_unit_or_number' USING ERRCODE='23514'; END IF;
  RETURN (q->>part)::numeric;
 END IF;
 RETURN public.sclib_materials_condition_number_v2(kind,q,part);
END $$""", r"""
CREATE FUNCTION public.sclib_materials_result_semantics_v2(j jsonb,target text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE legacy jsonb; BEGIN
 IF j->>'version'='materials-result-semantics/1' THEN
  RETURN public.sclib_materials_result_semantics_v1(j,target); END IF;
 IF j->>'version' IS DISTINCT FROM 'materials-result-semantics/2' THEN RETURN false; END IF;
 legacy:=jsonb_set(j,'{version}','"materials-result-semantics/1"');
 IF j#>>'{definition,criterion}'='linear_fit_intersection' THEN
  IF NOT public.sclib_materials_text_v1(j#>'{definition,criterion_raw}',4000,false)
   OR j#>'{definition,parameters}' IS DISTINCT FROM '[]'::jsonb THEN RETURN false; END IF;
  legacy:=jsonb_set(legacy,'{definition,criterion}','"fit_parameter"');
 END IF;
 RETURN public.sclib_materials_result_semantics_v1(legacy,target);
END $$"""]


def historical_triggers():
    return [properties.source_trigger() if 'sclib_materials_source_quantity_v1()' in sql else sql
            for sql in previous.replacements()]


def replacements():
    result=[]
    for sql in historical_triggers():
        sql=previous._replace(sql, previous.VERSION_SQL, VERSION_SQL, sql.count(previous.VERSION_SQL))
        old="WHEN 'materials-conditions/1' THEN public.sclib_materials_conditions_v1(NEW.conditions) ELSE public.sclib_materials_conditions_v2(NEW.conditions) END"
        if old in sql:
            sql=previous._replace(sql,old,"WHEN 'materials-conditions/1' THEN public.sclib_materials_conditions_v1(NEW.conditions) WHEN 'materials-conditions/2' THEN public.sclib_materials_conditions_v2(NEW.conditions) ELSE public.sclib_materials_conditions_v3(NEW.conditions) END")
        sql=sql.replace('sclib_materials_result_semantics_v1(', 'sclib_materials_result_semantics_v2(')
        result.append(sql)
    return result


def retained():
    # Include immutable review/release snapshots even when live data is absent.
    return """EXISTS(SELECT 1 FROM public.material_states WHERE condition_schema_version='materials-conditions/3')
 OR EXISTS(SELECT 1 FROM public.material_claims WHERE extraction_metadata#>>'{result_semantics,version}'='materials-result-semantics/2')
 OR EXISTS(SELECT 1 FROM public.event_properties WHERE raw#>>'{result_semantics,version}'='materials-result-semantics/2')
 OR EXISTS(SELECT 1 FROM public.research_release_pins WHERE
  row_data->>'condition_schema_version'='materials-conditions/3'
  OR row_data#>>'{extraction_metadata,result_semantics,version}'='materials-result-semantics/2'
  OR row_data#>>'{raw,result_semantics,version}'='materials-result-semantics/2')
 OR EXISTS(SELECT 1 FROM public.scientific_result_subjects s,
  LATERAL jsonb_array_elements(s.basis_json::jsonb->'rows') r WHERE
  r#>>'{snapshot,condition_schema_version}'='materials-conditions/3'
  OR r#>>'{snapshot,extraction_metadata,result_semantics,version}'='materials-result-semantics/2'
  OR r#>>'{snapshot,raw,result_semantics,version}'='materials-result-semantics/2')"""


def constraints(new):
    replace=lambda sql: sql.replace('sclib_materials_result_semantics_v1(', 'sclib_materials_result_semantics_v2(') if new else sql
    return [*previous._pressure_constraints(VERSION_SQL if new else previous.VERSION_SQL),
        'ALTER TABLE public.material_claims DROP CONSTRAINT ck_material_claims_tc_definition',
        'ALTER TABLE public.material_claims ADD CONSTRAINT ck_material_claims_tc_definition CHECK ('+replace(definitions.CLAIM_CHECK)+')',
        *properties._constraint(replace(properties.CURRENT_CHECK))]


def upgrade_statements():
    return [previous.LOCK, f"DO $$ BEGIN IF {retained()} THEN RAISE EXCEPTION 'materials_device_descriptor_reserved_collision' USING ERRCODE='23514'; END IF; END $$",
            *functions(), *replacements(), *constraints(True)]


def downgrade_statements():
    return [previous.LOCK, f"DO $$ BEGIN IF {retained()} THEN RAISE EXCEPTION 'materials_device_descriptor_retained_history_refuses_downgrade' USING ERRCODE='23514'; END IF; END $$",
            *historical_triggers(), *constraints(False),
            *[f'DROP FUNCTION public.{name}({args})' for name,args in reversed(FUNCTIONS)]]


def register(metadata):
    for sql in upgrade_statements():
        sa.event.listen(metadata,'after_create',sa.DDL(sql.replace('%','%%')).execute_if(dialect='postgresql'))
    for name,args in reversed(FUNCTIONS):
        sa.event.listen(metadata,'after_drop',sa.DDL(f'DROP FUNCTION IF EXISTS public.{name}({args})').execute_if(dialect='postgresql'))
