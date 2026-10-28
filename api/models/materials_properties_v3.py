"""0102: source-tested pressure slopes and resistivity in existing property rows.

Source quantity/uncertainty and result definitions reuse their existing typed
members. New rows remain pending review and the existing release gate applies.
"""
from decimal import Decimal
import sqlalchemy as sa
from models import materials_conditions_adoption_v2 as conditions
from models import materials_observation_outcomes_v1 as observations

REGISTRY_VERSION = 'materials-properties/3'
PROPERTY_UNITS = {'tc_pressure_slope': 'K/GPa', 'electrical_resistivity': 'Ω m'}
FACTORS = {
    'tc_pressure_slope': {'K/GPa': 1, 'K GPa^-1': 1, 'K GPa-1': 1, 'K GPa−1': 1,
        'K GPa⁻¹': 1, 'K/kbar': 10, 'mK/GPa': .001},
    'electrical_resistivity': {'Ω m': 1, 'Ω cm': .01, 'mΩ cm': 1e-5,
        'μΩ cm': 1e-8, 'µΩ cm': 1e-8, 'uΩ cm': 1e-8, 'µΩ·cm': 1e-8},
}
LOCK = conditions.LOCK
PREVIOUS_CHECK = f"((NOT raw ? 'observation_outcome' AND ({observations.PREVIOUS_PROPERTY_CHECK})) OR (registry_version='{observations.REGISTRY_VERSION}' AND property_key='non_detection' AND unit='not_applicable' AND public.sclib_materials_observation_shape_v1(raw->'observation_outcome'))) IS TRUE"
CURRENT_CHECK = f"(({PREVIOUS_CHECK}) OR (registry_version='{REGISTRY_VERSION}' AND raw ? 'source_quantity' AND raw ? 'result_semantics' AND NOT raw ? 'observation_outcome' AND public.sclib_materials_result_semantics_v1(raw->'result_semantics','property') AND (" + ' OR '.join(f"(property_key='{k}' AND unit='{u}')" for k,u in PROPERTY_UNITS.items()) + '))) IS TRUE'
PREVIOUS_DOMAIN = "property_key IN ('formation_energy_per_atom','phonon_min_frequency') OR ((value IS NULL OR value>=0) AND (lower IS NULL OR lower>=0) AND (upper IS NULL OR upper>=0))"
CURRENT_DOMAIN = f"({PREVIOUS_DOMAIN}) OR (registry_version='{REGISTRY_VERSION}' AND property_key='tc_pressure_slope')"


def normalized_uncertainty(kind, quantity):
    factor = FACTORS[kind][quantity['unit']]
    uncertainty = quantity['uncertainty']
    return None if uncertainty is None else dict({k:uncertainty[k] for k in ('kind','level')},
        minus=float(Decimal(str(uncertainty['minus'])) * Decimal(str(factor))),
        plus=float(Decimal(str(uncertainty['plus'])) * Decimal(str(factor))))


def number_function():
    cases = []
    for kind, units in FACTORS.items():
        options = ' '.join(f"WHEN '{unit}' THEN {factor}" for unit, factor in units.items())
        cases.append(f"WHEN '{kind}' THEN CASE q->>'unit' {options} END")
    return f"""CREATE FUNCTION public.sclib_materials_property_number_v2(kind text,q jsonb,part text)
RETURNS numeric LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE factor numeric; n numeric; BEGIN
 IF kind NOT IN ('tc_pressure_slope','electrical_resistivity') THEN
  RETURN public.sclib_materials_condition_number_v1(kind,q,part); END IF;
 IF public.sclib_materials_quantity_v1(q) IS DISTINCT FROM true OR q->>'status'<>'reported'
  OR part NOT IN ('value','lower','upper') THEN
  RAISE EXCEPTION 'materials_property_quantity_shape' USING ERRCODE='23514'; END IF;
 factor:=CASE kind {' '.join(cases)} END;
 IF factor IS NULL THEN RAISE EXCEPTION 'materials_property_unit_unregistered' USING ERRCODE='23514'; END IF;
 n:=(q->>part)::numeric;
 IF kind='electrical_resistivity' AND n<0 THEN
  RAISE EXCEPTION 'materials_property_quantity_domain' USING ERRCODE='23514'; END IF;
 RETURN n*factor;
END $$"""


def previous_source_trigger():
    return next(sql for sql in conditions.replacements() if 'sclib_materials_source_quantity_v1()' in sql)


def source_trigger():
    sql = previous_source_trigger()
    changes = [
        ("NEW.registry_version='materials-properties/2'", "NEW.registry_version IN ('materials-properties/2','materials-properties/3')"),
        ("NEW.registry_version NOT IN ('materials-properties/1','materials-properties/2')", "NEW.registry_version NOT IN ('materials-properties/1','materials-properties/2','materials-properties/3')"),
        ("WHEN 'thickness' THEN 'thickness' END", "WHEN 'thickness' THEN 'thickness' WHEN 'tc_pressure_slope' THEN 'tc_pressure_slope' WHEN 'electrical_resistivity' THEN 'electrical_resistivity' END"),
        ("public.sclib_materials_condition_number_v1(source_kind,q,k)", "public.sclib_materials_property_number_v2(source_kind,q,k)"),
    ]
    for before, after in changes:
        sql = conditions._replace(sql, before, after)
    return sql


def retained():
    return """EXISTS(SELECT 1 FROM public.event_properties WHERE registry_version='materials-properties/3')
 OR EXISTS(SELECT 1 FROM public.research_release_pins WHERE table_name='event_properties'
  AND row_data->>'registry_version'='materials-properties/3')
 OR EXISTS(SELECT 1 FROM public.scientific_result_subjects s,
  LATERAL jsonb_array_elements(s.basis_json::jsonb->'rows') r WHERE r->>'table'='event_properties'
  AND r->'snapshot'->>'registry_version'='materials-properties/3')"""


def _constraint(check, name='ck_rv2_property_registry'):
    return [f'ALTER TABLE public.event_properties DROP CONSTRAINT {name}',
        f'ALTER TABLE public.event_properties ADD CONSTRAINT {name} CHECK (' + check + ')']


def upgrade_statements():
    return [LOCK, f"DO $$ BEGIN IF {retained()} THEN RAISE EXCEPTION 'materials_properties_v3_reserved_collision' USING ERRCODE='23514'; END IF; END $$",
        number_function(), source_trigger(), *_constraint(CURRENT_CHECK),
        *_constraint(CURRENT_DOMAIN,'ck_rv2_property_nonnegative')]


def downgrade_statements():
    return [LOCK, f"DO $$ BEGIN IF {retained()} THEN RAISE EXCEPTION 'materials_properties_v3_retained_history_refuses_downgrade' USING ERRCODE='23514'; END IF; END $$",
        previous_source_trigger(), *_constraint(PREVIOUS_CHECK),
        *_constraint(PREVIOUS_DOMAIN,'ck_rv2_property_nonnegative'),
        'DROP FUNCTION public.sclib_materials_property_number_v2(text,jsonb,text)']


def register(metadata):
    for sql in upgrade_statements():
        sa.event.listen(metadata, 'after_create', sa.DDL(sql.replace('%','%%')).execute_if(dialect='postgresql'))
    sa.event.listen(metadata, 'after_drop', sa.DDL('DROP FUNCTION IF EXISTS public.sclib_materials_property_number_v2(text,jsonb,text)').execute_if(dialect='postgresql'))
