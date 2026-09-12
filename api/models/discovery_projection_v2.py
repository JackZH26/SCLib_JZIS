"""Incremental0070 paired-version guards over frozen0069 governance tables.

The historical0069 module is never changed: its exact insert function is the
downgrade target. Only its one payload-version predicate is extended, preserving
all transaction, role, disclosure, currentness and scientific-review guards.
"""
from __future__ import annotations

import sqlalchemy as sa

from models import discovery_projection_v1 as frozen

FUNCTION_SIGNATURES = (
    ("sclib_discovery_barrier_text_v2", "jsonb, integer"),
    ("sclib_discovery_main_barrier_v2", "jsonb, jsonb, jsonb"),
    ("sclib_discovery_projection_versions_v2", "jsonb, jsonb, jsonb"),
)


def frozen_insert_statement():
    matches = [statement for statement in frozen.guard_statements()
        if "CREATE OR REPLACE FUNCTION public.sclib_discovery_projection_insert_v1()" in statement]
    if len(matches) != 1:
        raise RuntimeError("Discovery0069 insert definition is ambiguous")
    return matches[0]


def guard_statements():
    original = frozen_insert_statement()
    predicate = "NEW.payload_json::jsonb->>'version' IS DISTINCT FROM 'discovery-scientific-projection/1.0.0'"
    if original.count(predicate) != 1:
        raise RuntimeError("Discovery0069 version predicate changed")
    upgraded = original.replace(predicate,
        "NOT public.sclib_discovery_projection_versions_v2(NEW.payload_json::jsonb,NEW.selection_json::jsonb,NEW.public_bundle_json::jsonb)")
    return [r"""
      CREATE OR REPLACE FUNCTION public.sclib_discovery_barrier_text_v2(value jsonb,maximum integer) RETURNS boolean
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT CASE WHEN jsonb_typeof(value)='string' THEN
          char_length(value#>>'{}') BETWEEN 1 AND maximum
          AND btrim(value#>>'{}',U&'\0009\000A\000D\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')<>''
          AND (value#>>'{}') !~ '[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]'
          ELSE false END
      $$
    """, r"""
      CREATE OR REPLACE FUNCTION public.sclib_discovery_main_barrier_v2(barrier jsonb,result jsonb,cells jsonb) RETURNS boolean
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC' AS $$
      DECLARE ref jsonb; item jsonb; category text; identity text; previous text:=NULL; matches integer;
      BEGIN
        IF jsonb_typeof(barrier) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
        IF barrier->>'status'='not_declared' THEN RETURN barrier='{"status":"not_declared"}'::jsonb; END IF;
        IF barrier->>'status' IS DISTINCT FROM 'declared'
          OR NOT barrier ?& ARRAY['status','category','statement','rationale','basis_refs']
          OR barrier-ARRAY['status','category','statement','rationale','basis_refs']<>'{}'::jsonb
          OR jsonb_typeof(barrier->'category') IS DISTINCT FROM 'string'
          OR barrier->>'category' NOT IN ('evidence_gap','execution_constraint','scientific_hypothesis','recorded_policy_reason')
          OR NOT public.sclib_discovery_barrier_text_v2(barrier->'statement',500)
          OR NOT public.sclib_discovery_barrier_text_v2(barrier->'rationale',2000)
          OR jsonb_typeof(barrier->'basis_refs') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
        IF jsonb_array_length(barrier->'basis_refs') NOT BETWEEN 1 AND 8 THEN RETURN false; END IF;
        category:=barrier->>'category';
        FOR ref IN SELECT value FROM jsonb_array_elements(barrier->'basis_refs') LOOP
          IF jsonb_typeof(ref) IS DISTINCT FROM 'object' OR jsonb_typeof(ref->'kind') IS DISTINCT FROM 'string' THEN RETURN false; END IF;
          IF ref->>'kind' IN ('assessment_reason','execution_constraint') THEN
            IF NOT ref ?& ARRAY['kind','code'] OR ref-ARRAY['kind','code']<>'{}'::jsonb
              OR NOT public.sclib_discovery_barrier_text_v2(ref->'code',200) THEN RETURN false; END IF;
            identity:=(ref->>'kind')||':'||(ref->>'code');
            IF category='recorded_policy_reason' THEN
              IF ref->>'kind'<>'assessment_reason' OR jsonb_typeof(result->'reason_codes') IS DISTINCT FROM 'array'
                OR NOT (result->'reason_codes') @> jsonb_build_array(ref->>'code') THEN RETURN false; END IF;
            ELSIF category='execution_constraint' THEN
              IF ref->>'kind'<>'execution_constraint' OR jsonb_typeof(result->'execution_constraint_reasons') IS DISTINCT FROM 'array'
                OR NOT (result->'execution_constraint_reasons') @> jsonb_build_array(ref->>'code') THEN RETURN false; END IF;
            ELSE RETURN false;
            END IF;
          ELSIF ref->>'kind'='scientific_cell' THEN
            IF NOT ref ?& ARRAY['kind','property_key'] OR ref-ARRAY['kind','property_key']<>'{}'::jsonb
              OR jsonb_typeof(ref->'property_key') IS DISTINCT FROM 'string'
              OR ref->>'property_key' NOT IN ('formation_energy_per_atom','energy_above_hull','band_gap','dos_at_fermi',
                'electron_phonon_lambda','omega_log','phonon_min_frequency','superfluid_stiffness')
              OR jsonb_typeof(cells) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
            identity:='scientific_cell:'||(ref->>'property_key');
            SELECT count(*) INTO matches FROM jsonb_array_elements(cells) c WHERE c->>'property_key'=ref->>'property_key';
            IF matches<>1 THEN RETURN false; END IF;
            SELECT c INTO item FROM jsonb_array_elements(cells) c WHERE c->>'property_key'=ref->>'property_key';
            IF category='evidence_gap' THEN
              IF item->>'availability' IS NULL OR item->>'availability' NOT IN ('unknown','not_computed','conflicted') THEN RETURN false; END IF;
            ELSIF category='scientific_hypothesis' THEN
              IF item->>'availability' IS NULL OR item->>'availability' NOT IN ('reported','conflicted')
                OR jsonb_typeof(item->'observations') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
              IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(item->'observations') o
                WHERE o->'quantity'->>'relation' IN ('exact','interval','lt','le','gt','ge')) THEN RETURN false; END IF;
            ELSE RETURN false;
            END IF;
          ELSE RETURN false;
          END IF;
          IF previous IS NOT NULL AND identity COLLATE "C" <= previous COLLATE "C" THEN RETURN false; END IF;
          previous:=identity;
        END LOOP;
        RETURN true;
      END $$
    """, r"""
      CREATE OR REPLACE FUNCTION public.sclib_discovery_projection_versions_v2(payload jsonb,selection jsonb,bundle jsonb) RETURNS boolean
      LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC' AS $$
      DECLARE choice jsonb; row_value jsonb; cell jsonb; selected_cell jsonb; assessment jsonb; i integer; matches integer;
      BEGIN
        IF payload->>'version'='discovery-scientific-projection/1.0.0'
          AND selection->>'version'='discovery-scientific-selection/1.0.0' THEN RETURN true; END IF;
        IF payload->>'version' IS DISTINCT FROM 'discovery-scientific-projection/2.0.0'
          OR selection->>'version' IS DISTINCT FROM 'discovery-scientific-selection/2.0.0'
          OR jsonb_typeof(selection->'representatives') IS DISTINCT FROM 'array'
          OR jsonb_typeof(payload->'rows') IS DISTINCT FROM 'array'
          OR jsonb_typeof(bundle->'rows') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
        IF jsonb_array_length(selection->'representatives') NOT BETWEEN 1 AND 25
          OR jsonb_array_length(selection->'representatives')<>jsonb_array_length(payload->'rows') THEN RETURN false; END IF;
        FOR i IN 0..jsonb_array_length(selection->'representatives')-1 LOOP
          choice:=selection->'representatives'->i;
          row_value:=payload->'rows'->i;
          IF choice->'main_barrier' IS DISTINCT FROM row_value->'main_barrier'
            OR choice->'assessment' IS DISTINCT FROM row_value->'representative'
            OR jsonb_typeof(row_value->'cells') IS DISTINCT FROM 'array'
            OR jsonb_typeof(choice->'cells') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
          IF jsonb_array_length(row_value->'cells')<>8 OR jsonb_array_length(choice->'cells')<>8 THEN RETURN false; END IF;
          SELECT count(*) INTO matches FROM jsonb_array_elements(bundle->'rows') a
            WHERE a->>'id'=choice->'assessment'->>'id' AND a->'revision'=choice->'assessment'->'revision'
              AND a->>'material_id'=choice->'material'->>'id';
          IF matches<>1 THEN RETURN false; END IF;
          SELECT a INTO assessment FROM jsonb_array_elements(bundle->'rows') a WHERE a->>'id'=choice->'assessment'->>'id';
          IF row_value->'assessment' IS DISTINCT FROM assessment THEN RETURN false; END IF;
          FOR cell IN SELECT value FROM jsonb_array_elements(row_value->'cells') LOOP
            SELECT count(*) INTO matches FROM jsonb_array_elements(choice->'cells') c WHERE c->>'property_key'=cell->>'property_key';
            IF matches<>1 THEN RETURN false; END IF;
            SELECT c INTO selected_cell FROM jsonb_array_elements(choice->'cells') c WHERE c->>'property_key'=cell->>'property_key';
            IF cell-ARRAY['unit','group','observations','availability_basis'] IS DISTINCT FROM selected_cell THEN RETURN false; END IF;
          END LOOP;
          IF NOT public.sclib_discovery_main_barrier_v2(choice->'main_barrier',assessment->'result',row_value->'cells') THEN RETURN false; END IF;
        END LOOP;
        RETURN true;
      END $$
    """, upgraded]


def register(metadata):
    """Install after frozen0069 for fresh metadata-created databases too."""
    last = metadata.tables[frozen.TABLE_ORDER[-1]]
    for statement in guard_statements():
        sa.event.listen(last, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
