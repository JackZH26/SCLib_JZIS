"""0093: result-owned definitions without adding sparse catalogue columns.

This is a bounded canonical storage increment, not a promotion/release policy.
The JSON member is reserved, closed and versioned. Legacy records and release
row shapes stay unchanged. New-format results cannot enter the old release
contract until its review/closure policy is explicitly upgraded.
"""
from __future__ import annotations

import sqlalchemy as sa

from models.research_schema_v2 import PROPERTY_UNITS

VERSION = "materials-result-semantics/1"
REGISTRY_VERSION = "materials-properties/1"
# Only source-tested additions in this increment. Hc2 is the reported mu0 Hc2
# field scale in tesla; this does not accept H in A/m as an interchangeable unit.
NEW_PROPERTY_UNITS = {
    "hc2": "T",
    "coherence_length": "nm",
    "superconducting_layer_thickness": "nm",
}
CRITERIA = (
    "onset", "midpoint", "zero_resistance", "offset", "diamagnetic_onset",
    "heat_capacity_anomaly", "gap_closure", "bkt", "fit_parameter",
    "unspecified", "not_applicable", "resistance_fraction",
)
LEGACY_CRITERIA = "tc_definition IN ('onset','zero_resistance','midpoint','diamagnetic','heat_capacity','unknown')"
LEGACY_REGISTRY = "registry_version='rv2/1' AND (" + " OR ".join(
    f"(property_key='{key}' AND unit='{unit}')" for key, unit in PROPERTY_UNITS.items()
) + ")"
PROPERTY_PRESENT = "raw ? 'result_semantics'"
CLAIM_PRESENT = "extraction_metadata ? 'result_semantics'"
FUNCTION_SIGNATURES = (
    ("sclib_materials_closed_object_v1", "jsonb,text[]"),
    ("sclib_materials_result_semantics_v1", "jsonb,text"),
    ("sclib_materials_definition_release_gate_v1", ""),
)


def functions():
    return [r"""CREATE FUNCTION public.sclib_materials_closed_object_v1(j jsonb,ks text[])
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF jsonb_typeof(j) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
 RETURN j ?& ks AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(j) k WHERE NOT k=ANY(ks));
END $$""", r"""CREATE FUNCTION public.sclib_materials_result_semantics_v1(j jsonb,target text)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE ks text[]; d jsonb; p jsonb; q jsonb; u jsonb; z jsonb; c text; n numeric;
BEGIN
 IF target NOT IN ('claim','property') OR target IS NULL THEN RETURN false; END IF;
 ks:=ARRAY['version','definition','qualifiers'];
 IF target='property' THEN ks:=ks||'result_key'::text; END IF;
 IF NOT public.sclib_materials_closed_object_v1(j,ks)
  OR j->>'version' IS DISTINCT FROM 'materials-result-semantics/1' THEN RETURN false; END IF;
 IF target='property' AND (jsonb_typeof(j->'result_key') IS DISTINCT FROM 'string'
  OR length(btrim(j->>'result_key')) NOT BETWEEN 1 AND 120) THEN RETURN false; END IF;
 d:=j->'definition';
 IF NOT public.sclib_materials_closed_object_v1(d,ARRAY['criterion','criterion_raw','parameters'])
  OR jsonb_typeof(d->'criterion') IS DISTINCT FROM 'string'
  OR d->>'criterion' NOT IN ('onset','midpoint','zero_resistance','offset','diamagnetic_onset',
      'heat_capacity_anomaly','gap_closure','bkt','fit_parameter','unspecified','not_applicable','resistance_fraction')
  OR jsonb_typeof(d->'parameters') IS DISTINCT FROM 'array'
  OR jsonb_typeof(j->'qualifiers') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 c:=d->>'criterion';
 IF jsonb_typeof(d->'criterion_raw') NOT IN ('string','null') THEN RETURN false; END IF;
 IF jsonb_typeof(d->'criterion_raw')='string' AND length(btrim(d->>'criterion_raw'))=0 THEN RETURN false; END IF;
 IF c NOT IN ('unspecified','not_applicable') AND (jsonb_typeof(d->'criterion_raw') IS DISTINCT FROM 'string'
  OR length(btrim(d->>'criterion_raw'))=0) THEN RETURN false; END IF;
 IF jsonb_array_length(d->'parameters')>1 OR jsonb_array_length(j->'qualifiers')>1 THEN RETURN false; END IF;
 IF c='resistance_fraction' AND jsonb_array_length(d->'parameters')<>1 THEN RETURN false; END IF;
 FOR p IN SELECT value FROM jsonb_array_elements(d->'parameters') LOOP
  IF NOT public.sclib_materials_closed_object_v1(p,ARRAY['kind','name_raw','quantity'])
   OR p->>'kind' IS DISTINCT FROM 'resistance_fraction'
   OR jsonb_typeof(p->'name_raw') IS DISTINCT FROM 'string' OR length(btrim(p->>'name_raw'))=0 THEN RETURN false; END IF;
  q:=p->'quantity';
  IF NOT public.sclib_materials_closed_object_v1(q,ARRAY['status','raw','relation','value','lower','upper','unit','approximate','uncertainty'])
   OR q->>'status' IS DISTINCT FROM 'reported' OR q->>'relation' IS DISTINCT FROM 'exact'
   OR jsonb_typeof(q->'raw') IS DISTINCT FROM 'string' OR length(btrim(q->>'raw'))=0
   OR jsonb_typeof(q->'value') IS DISTINCT FROM 'number'
   OR q->'lower' IS DISTINCT FROM 'null'::jsonb OR q->'upper' IS DISTINCT FROM 'null'::jsonb
   OR jsonb_typeof(q->'approximate') IS DISTINCT FROM 'boolean'
   OR jsonb_typeof(q->'unit') IS DISTINCT FROM 'string' OR q->>'unit' NOT IN ('%','1') THEN RETURN false; END IF;
  n:=(q->>'value')::numeric;
  IF n<0 OR n>(CASE WHEN q->>'unit'='%' THEN 100 ELSE 1 END) THEN RETURN false; END IF;
  u:=q->'uncertainty';
  IF u IS DISTINCT FROM 'null'::jsonb THEN
   IF NOT public.sclib_materials_closed_object_v1(u,ARRAY['kind','minus','plus','level','raw'])
    OR u->>'kind' NOT IN ('standard_deviation','standard_error','confidence_interval','resolution','reported_unspecified')
    OR jsonb_typeof(u->'kind') IS DISTINCT FROM 'string'
    OR jsonb_typeof(u->'minus') IS DISTINCT FROM 'number' OR jsonb_typeof(u->'plus') IS DISTINCT FROM 'number'
    OR jsonb_typeof(u->'raw') IS DISTINCT FROM 'string' OR length(btrim(u->>'raw'))=0 THEN RETURN false; END IF;
   IF (u->>'minus')::numeric<0 OR (u->>'plus')::numeric<0 THEN RETURN false; END IF;
   IF u->'level' IS DISTINCT FROM 'null'::jsonb THEN
    IF jsonb_typeof(u->'level') IS DISTINCT FROM 'number' THEN RETURN false; END IF;
    IF (u->>'level')::numeric<=0 OR (u->>'level')::numeric>=1 THEN RETURN false; END IF;
   END IF;
  END IF;
 END LOOP;
 FOR z IN SELECT value FROM jsonb_array_elements(j->'qualifiers') LOOP
  IF NOT public.sclib_materials_closed_object_v1(z,ARRAY['kind','stage','raw'])
   OR z->>'kind' IS DISTINCT FROM 'transition_stage' OR jsonb_typeof(z->'stage') IS DISTINCT FROM 'string'
   OR z->>'stage' NOT IN ('primary','secondary','other')
   OR jsonb_typeof(z->'raw') IS DISTINCT FROM 'string' OR length(btrim(z->>'raw'))=0 THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$""", r"""CREATE FUNCTION public.sclib_materials_definition_release_gate_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 -- V1 release shape still verifies old captures exactly. A new definition is
 -- intentionally refused until definition evidence/review closure is versioned.
 IF (NEW.table_name='material_claims' AND NEW.row_data->'extraction_metadata' ? 'result_semantics')
  OR (NEW.table_name='event_properties' AND NEW.row_data->'raw' ? 'result_semantics') THEN
  RAISE EXCEPTION 'materials_result_definition_release_policy_pending' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$"""]


CLAIM_CHECK = f"""(
 (NOT ({CLAIM_PRESENT}) AND ({LEGACY_CRITERIA})) OR
 (({CLAIM_PRESENT}) AND public.sclib_materials_result_semantics_v1(extraction_metadata->'result_semantics','claim')
  AND event_id IS NOT NULL AND result_key IS NOT NULL AND btrim(result_key)<>''
  AND property_type='tc'
  AND tc_definition=extraction_metadata#>>'{{result_semantics,definition,criterion}}')
) IS TRUE"""
PROPERTY_CHECK = f"""(
 (NOT ({PROPERTY_PRESENT}) AND ({LEGACY_REGISTRY})) OR
 (({PROPERTY_PRESENT}) AND public.sclib_materials_result_semantics_v1(raw->'result_semantics','property')
  AND registry_version='{REGISTRY_VERSION}' AND (""" + " OR ".join(
    f"(property_key='{key}' AND unit='{unit}')" for key, unit in NEW_PROPERTY_UNITS.items()
) + ")) ) IS TRUE"


def upgrade_statements():
    return [
        "LOCK TABLE public.material_claims,public.event_properties,public.research_release_pins IN ACCESS EXCLUSIVE MODE",
        # Never reinterpret a pre-existing arbitrary JSON member as this contract.
        """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.material_claims WHERE extraction_metadata ? 'result_semantics')
         OR EXISTS(SELECT 1 FROM public.event_properties WHERE raw ? 'result_semantics') THEN
         RAISE EXCEPTION 'materials_result_semantics_reserved_member_collision' USING ERRCODE='23514'; END IF; END $$""",
        *functions(),
        "ALTER TABLE public.material_claims DROP CONSTRAINT ck_material_claims_tc_definition",
        f"ALTER TABLE public.material_claims ADD CONSTRAINT ck_material_claims_tc_definition CHECK ({CLAIM_CHECK})",
        "ALTER TABLE public.event_properties DROP CONSTRAINT ck_rv2_property_registry",
        f"ALTER TABLE public.event_properties ADD CONSTRAINT ck_rv2_property_registry CHECK ({PROPERTY_CHECK})",
        "ALTER TABLE public.event_properties DROP CONSTRAINT uq_rv2_event_property_component",
        f"CREATE UNIQUE INDEX uq_mrd93_legacy_component ON public.event_properties(event_id,property_key,registry_version,component_key) WHERE NOT ({PROPERTY_PRESENT})",
        f"CREATE UNIQUE INDEX uq_mrd93_event_result_key ON public.event_properties(event_id,(raw#>>'{{result_semantics,result_key}}')) WHERE ({PROPERTY_PRESENT})",
        "CREATE TRIGGER mrd93_release_gate BEFORE INSERT OR UPDATE ON public.research_release_pins FOR EACH ROW EXECUTE FUNCTION public.sclib_materials_definition_release_gate_v1()",
    ]


def downgrade_statements():
    return [
        "LOCK TABLE public.material_claims,public.event_properties,public.research_release_pins IN ACCESS EXCLUSIVE MODE",
        """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.material_claims WHERE extraction_metadata ? 'result_semantics')
         OR EXISTS(SELECT 1 FROM public.event_properties WHERE raw ? 'result_semantics') THEN
         RAISE EXCEPTION 'materials_result_definition_retained_data_refuses_downgrade' USING ERRCODE='23514'; END IF; END $$""",
        "DROP TRIGGER mrd93_release_gate ON public.research_release_pins",
        "DROP INDEX public.uq_mrd93_event_result_key",
        "DROP INDEX public.uq_mrd93_legacy_component",
        "ALTER TABLE public.event_properties ADD CONSTRAINT uq_rv2_event_property_component UNIQUE(event_id,property_key,registry_version,component_key)",
        "ALTER TABLE public.event_properties DROP CONSTRAINT ck_rv2_property_registry",
        f"ALTER TABLE public.event_properties ADD CONSTRAINT ck_rv2_property_registry CHECK ({LEGACY_REGISTRY})",
        "ALTER TABLE public.material_claims DROP CONSTRAINT ck_material_claims_tc_definition",
        f"ALTER TABLE public.material_claims ADD CONSTRAINT ck_material_claims_tc_definition CHECK ({LEGACY_CRITERIA})",
        *[f"DROP FUNCTION public.{name}({arguments})" for name, arguments in reversed(FUNCTION_SIGNATURES)],
    ]


def register(metadata):
    # Same post-create integration as the existing literal/table field contracts.
    # SQL changes constraints/indexes only; no public ORM fields are introduced.
    for sql in upgrade_statements():
        sa.event.listen(metadata, "after_create", sa.DDL(sql.replace("%", "%%")).execute_if(dialect="postgresql"))
    # metadata.drop_all drops the referenced tables/constraints first.
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        sql = f"DROP FUNCTION IF EXISTS public.{name}({arguments})"
        sa.event.listen(metadata, "after_drop", sa.DDL(sql).execute_if(dialect="postgresql"))
