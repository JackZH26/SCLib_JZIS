"""Condition validator for unresolved magnetic-field conventions.

Adopted by materials_conditions_adoption_v2 and Alembic increment 0101.
The historical v1 validator and unit conversion functions remain unchanged.
"""
VERSION = 'materials-conditions/2'
UNRESOLVED_FIELD_UNITS = ('T', 'mT', 'μT', 'µT', 'G', 'kG', 'A/m', 'kA/m', 'Oe', 'kOe')


def functions():
    units = ','.join("'"+x+"'" for x in UNRESOLVED_FIELD_UNITS)
    return [f"""
CREATE FUNCTION public.sclib_materials_conditions_v2(j jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE c jsonb; legacy jsonb; q jsonb; seen text[]:='{{}}'; BEGIN
 IF NOT public.sclib_materials_closed_object_v1(j,ARRAY['items','pressure','temperature_condition_id'])
  OR jsonb_typeof(j->'items') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(j->'items')>64 THEN RETURN false; END IF;
 -- Keep all original v1 pressure/temperature selection and regular-kind rules.
 SELECT COALESCE(jsonb_agg(value),'[]'::jsonb) INTO legacy
  FROM jsonb_array_elements(j->'items') WHERE value->>'kind' IS DISTINCT FROM 'reported_magnetic_field';
 IF public.sclib_materials_conditions_v1(jsonb_set(j,'{{items}}',legacy)) IS DISTINCT FROM true THEN RETURN false; END IF;
 FOR c IN SELECT value FROM jsonb_array_elements(j->'items') LOOP
  IF (c->>'id')=ANY(seen) THEN RETURN false; END IF; seen:=array_append(seen,c->>'id');
  IF c->>'kind' IS DISTINCT FROM 'reported_magnetic_field' THEN CONTINUE; END IF;
  IF NOT public.sclib_materials_closed_object_v1(c,ARRAY['id','kind','role','quantity','orientation_raw','basis_raw','window_position'])
   OR NOT public.sclib_materials_text_v1(c->'id',100,false)
   OR jsonb_typeof(c->'role') IS DISTINCT FROM 'string'
   OR c->>'role' NOT IN ('measurement','synthesis','simulation','detection_window','pump','sample_geometry','study_extent','fit_window','unknown')
   OR NOT public.sclib_materials_text_v1(c->'orientation_raw',1000,true)
   OR NOT public.sclib_materials_text_v1(c->'basis_raw',2000,false)
   OR public.sclib_materials_quantity_v1(c->'quantity') IS DISTINCT FROM true THEN RETURN false; END IF;
  IF c->>'role'='detection_window' THEN
   IF jsonb_typeof(c->'window_position') IS DISTINCT FROM 'string'
    OR c->>'window_position' NOT IN ('lower_limit','upper_limit','interval','unspecified') THEN RETURN false; END IF;
  ELSIF c->'window_position'<>'null'::jsonb THEN RETURN false; END IF;
  q:=c->'quantity';
  IF q->>'status'='reported' AND (q->>'unit' IS NULL OR q->>'unit' NOT IN ({units})) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$""", """
CREATE FUNCTION public.sclib_materials_condition_number_v2(kind text,q jsonb,part text) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF kind='reported_magnetic_field' THEN
  RAISE EXCEPTION 'materials_magnetic_field_convention_unresolved' USING ERRCODE='23514'; END IF;
 RETURN public.sclib_materials_condition_number_v1(kind,q,part);
END $$"""]


def removal_statements():
    """Remove helpers only after the adoption migration's retained-data gate."""
    return [
        'DROP FUNCTION public.sclib_materials_condition_number_v2(text,jsonb,text)',
        'DROP FUNCTION public.sclib_materials_conditions_v2(jsonb)',
    ]
