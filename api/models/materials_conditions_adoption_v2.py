"""0101: adopt source-reported magnetic fields without inferring B, H or mu0 H.

No tables or scientific columns are added. Historical validators and subject
serialization stay intact. Trigger replacements extend explicit version checks;
the old definitions are restored verbatim by an empty-data downgrade.
"""
from __future__ import annotations

import sqlalchemy as sa

from models import materials_conditions_v1 as previous
from models import materials_conditions_v2 as candidate
from models import materials_claim_outcomes_v1 as claims
from models import materials_observation_outcomes_v1 as observations

VERSIONS = (previous.VERSION, candidate.VERSION)
VERSION_SQL = "('materials-conditions/1','materials-conditions/2')"
LOCK = "LOCK TABLE public.material_states,public.material_claims,public.research_events,public.event_properties,public.research_release_pins,public.scientific_result_subjects IN ACCESS EXCLUSIVE MODE"


def _replace(sql, old, new, count=1):
    # Fail at migration construction if an imported historical definition drifts.
    if sql.count(old) != count:
        raise ValueError("materials_conditions_migration_definition_drift")
    return sql.replace(old, new)


def historical_triggers():
    return [sql for sql in previous.functions() + claims.functions() + observations.functions()
            if "RETURNS trigger" in sql and "condition_schema_version" in sql]


def replacements():
    result = []
    for sql in historical_triggers():
        sql = _replace(sql, "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")
        # Equality, inequality and null-safe rejection have different semantics.
        for owner in ("OLD.", "NEW.", "s.", ""):
            old = owner + "condition_schema_version='materials-conditions/1'"
            if old in sql:
                sql = _replace(sql, old, owner + "condition_schema_version IN " + VERSION_SQL,
                               sql.count(old))
        old = "s.condition_schema_version IS DISTINCT FROM 'materials-conditions/1'"
        if old in sql:
            sql = _replace(sql, old, "(s.condition_schema_version IS NULL OR s.condition_schema_version NOT IN " + VERSION_SQL + ")")
        if "sclib_materials_state_insert_v1()" in sql:
            sql = _replace(sql, "NEW.condition_schema_version<>'materials-conditions/1'",
                           "NEW.condition_schema_version NOT IN " + VERSION_SQL)
            sql = _replace(sql, "DECLARE p jsonb; q jsonb; chosen jsonb; BEGIN", """DECLARE p jsonb; q jsonb; chosen jsonb; BEGIN
 IF TG_OP<>'DELETE' AND NEW.condition_schema_version LIKE 'materials-conditions/%'
  AND NEW.condition_schema_version NOT IN ('materials-conditions/1','materials-conditions/2') THEN
  RAISE EXCEPTION 'materials_state_condition_version_unsupported' USING ERRCODE='23514'; END IF;""")
            sql = _replace(sql, "public.sclib_materials_conditions_v1(NEW.conditions)",
                           "(CASE NEW.condition_schema_version WHEN 'materials-conditions/1' THEN public.sclib_materials_conditions_v1(NEW.conditions) ELSE public.sclib_materials_conditions_v2(NEW.conditions) END)")
        if "sclib_materials_state_legacy_gate_v1()" in sql:
            for prefix in ("NEW.row_data->>", "r->'snapshot'->>"):
                old = prefix + "'condition_schema_version'='materials-conditions/1'"
                sql = _replace(sql, old, prefix + "'condition_schema_version' IN " + VERSION_SQL)
        if "sclib_materials_observation_insert_v1()" in sql:
            # Only device/non-SC windows admit an unresolved source field.
            # Its source interval is preserved; no common field axis is derived.
            sql = _replace(sql,
                "('temperature','thickness','pressure','magnetic_flux_density','magnetic_field_strength','mu0_h')",
                "('temperature','thickness','pressure','magnetic_flux_density','magnetic_field_strength','mu0_h','reported_magnetic_field')")
        result.append(sql)
    if len(result) != 7:
        raise ValueError("materials_conditions_migration_trigger_inventory")
    return result


def _pressure_constraints(versions):
    return [
        "ALTER TABLE public.material_states DROP CONSTRAINT ck_rv2_state_pressure, DROP CONSTRAINT ck_rv2_state_pressure_required",
        f"ALTER TABLE public.material_states ADD CONSTRAINT ck_rv2_state_pressure CHECK (condition_schema_version IN {versions} OR ({previous.LEGACY_STATE_PRESSURE})), ADD CONSTRAINT ck_rv2_state_pressure_required CHECK (condition_schema_version IN {versions} OR ({previous.LEGACY_STATE_REQUIRED}))",
    ]


def _retained_v2():
    return """EXISTS(SELECT 1 FROM public.material_states
 WHERE condition_schema_version LIKE 'materials-conditions/%' AND condition_schema_version<>'materials-conditions/1')
 OR EXISTS(SELECT 1 FROM public.research_release_pins WHERE table_name='material_states'
  AND row_data->>'condition_schema_version' LIKE 'materials-conditions/%'
  AND row_data->>'condition_schema_version'<>'materials-conditions/1')
 OR EXISTS(SELECT 1 FROM public.scientific_result_subjects s,
  LATERAL jsonb_array_elements(s.basis_json::jsonb->'rows') r WHERE r->>'table'='material_states'
  AND r->'snapshot'->>'condition_schema_version' LIKE 'materials-conditions/%'
  AND r->'snapshot'->>'condition_schema_version'<>'materials-conditions/1')"""


def upgrade_statements():
    return [LOCK, f"""DO $$ BEGIN
 IF {_retained_v2()} THEN
  RAISE EXCEPTION 'materials_conditions_v2_reserved_collision' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM public.material_states WHERE condition_schema_version='materials-conditions/1'
  AND public.sclib_materials_conditions_v1(conditions) IS DISTINCT FROM true) THEN
  RAISE EXCEPTION 'materials_conditions_v1_preflight_invalid' USING ERRCODE='23514'; END IF;
 END $$""", *candidate.functions(), *replacements(), * _pressure_constraints(VERSION_SQL)]


def downgrade_statements():
    return [LOCK, f"""DO $$ BEGIN IF {_retained_v2()} THEN
 RAISE EXCEPTION 'materials_conditions_v2_retained_history_refuses_downgrade' USING ERRCODE='23514';
 END IF; END $$""",
        *[sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1) for sql in historical_triggers()],
        *_pressure_constraints("('materials-conditions/1')"), *candidate.removal_statements()]


def register(metadata):
    for sql in upgrade_statements():
        sa.event.listen(metadata, "after_create", sa.DDL(sql.replace("%", "%%")).execute_if(dialect="postgresql"))
    for sql in candidate.removal_statements():
        sa.event.listen(metadata, "after_drop", sa.DDL(sql.replace("DROP FUNCTION", "DROP FUNCTION IF EXISTS", 1)).execute_if(dialect="postgresql"))
