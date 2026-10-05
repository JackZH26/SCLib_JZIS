"""Additive table-cell intake guards; frozen 0083/0086 functions are retained."""
from __future__ import annotations

import sqlalchemy as sa

from models import material_field_cases_v1 as case_model
from models import material_literal_fields_v1 as literal_model
from models import source_expression_intake_v2 as source_model
from services import source_expression_contract_v2_1 as literal
from services import source_expression_contract_v2_2 as table
from services.research_release_manifest import canonical

FUNCTION_SIGNATURES = (
    ("sclib_material_table_binding_v1", "text,jsonb"),
    ("sclib_material_table_project_v1", "jsonb,text,jsonb"),
    ("sclib_material_table_source_insert_v1", ""),
    ("sclib_material_table_case_insert_v1", ""),
    ("sclib_material_table_select_v1", ""),
)


def replace_once(sql, old, new):
    if sql.count(old) != 1:
        raise RuntimeError("Frozen SQL composition anchor changed")
    return sql.replace(old, new)


def array(values):
    return "ARRAY[" + ",".join("'" + value + "'" for value in values) + "]"


def definitions():
    binding = r"""CREATE FUNCTION public.sclib_material_table_binding_v1(t text,r jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE g jsonb; hs jsonb; rs jsonb; caps jsonb; cell jsonb; rw jsonb; cells jsonb; label jsonb;
 ri integer; ci integer; nc integer; nr integer; previous_end integer; wa integer; wz integer;
 a integer; z integer; caption text; BEGIN
 g:=r->'table_binding';
 IF NOT public.sclib_material_field_closed_v1(g,ARRAY['version','caption_spans','header_spans','rows','row_index','column_index'])
  OR g->>'version' IS DISTINCT FROM 'source-table-grid/1.0.0'
  OR jsonb_typeof(g->'header_spans') IS DISTINCT FROM 'array'
  OR jsonb_typeof(g->'rows') IS DISTINCT FROM 'array'
  OR jsonb_typeof(g->'caption_spans') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'material_table_closed_grid' USING ERRCODE='23514'; END IF;
 hs:=g->'header_spans'; rs:=g->'rows'; caps:=g->'caption_spans';
 nc:=jsonb_array_length(hs); nr:=jsonb_array_length(rs);
 IF nc NOT BETWEEN 2 AND 16 OR nr NOT BETWEEN 1 AND 32 OR jsonb_array_length(caps)>1
  OR jsonb_typeof(g->'row_index') IS DISTINCT FROM 'number' OR g->>'row_index' !~ '^[0-9]{1,2}$'
  OR jsonb_typeof(g->'column_index') IS DISTINCT FROM 'number' OR g->>'column_index' !~ '^[0-9]{1,2}$' THEN
  RAISE EXCEPTION 'material_table_bounded_grid' USING ERRCODE='23514'; END IF;
 ri:=(g->>'row_index')::integer; ci:=(g->>'column_index')::integer;
 IF ri<0 OR ri>=nr OR ci<1 OR ci>=nc THEN
  RAISE EXCEPTION 'material_table_selected_cell' USING ERRCODE='23514'; END IF;
 caption:=NULLIF(public.sclib_source_expression_spans_v2(t,caps,1000,true),'');
 cells:=caps||hs;
 FOR rw IN SELECT value FROM jsonb_array_elements(rs) LOOP
  IF jsonb_typeof(rw) IS DISTINCT FROM 'array' OR jsonb_array_length(rw)<>nc THEN
   RAISE EXCEPTION 'material_table_rectangular_grid' USING ERRCODE='23514'; END IF;
  cells:=cells||rw;
 END LOOP;
 PERFORM public.sclib_source_expression_spans_v2(t,r->'window'->'label_spans',4096,false);
 wa:=(r->'window'->'label_spans'->0->>'start')::integer;
 wz:=(r->'window'->'label_spans'->0->>'end')::integer; previous_end:=wa;
 FOR cell IN SELECT value FROM jsonb_array_elements(cells) LOOP
  PERFORM public.sclib_source_expression_spans_v2(t,jsonb_build_array(cell),1200,false);
  a:=(cell->>'start')::integer; z:=(cell->>'end')::integer;
  IF a<wa OR z>wz OR a<previous_end THEN
   RAISE EXCEPTION 'material_table_ordered_cells' USING ERRCODE='23514'; END IF;
  previous_end:=z;
 END LOOP;
 IF r->'subject'->'formula_spans' IS DISTINCT FROM jsonb_build_array(hs->ci)
  OR r->'subject'->'sample_label_spans' IS DISTINCT FROM '[]'::jsonb
  OR r->'value_spans' IS DISTINCT FROM jsonb_build_array(rs->ri->ci) THEN
  RAISE EXCEPTION 'material_table_selected_subject_value' USING ERRCODE='23514'; END IF;
 label:=rs->ri->0;
 IF jsonb_array_length(r->'unit_spans')<>1
  OR (r->'unit_spans'->0->>'start')::integer<(label->>'start')::integer
  OR (r->'unit_spans'->0->>'end')::integer>(label->>'end')::integer
  OR (r->'cue_spans'->0->>'start')::integer<(label->>'start')::integer
  OR (r->'cue_spans'->0->>'end')::integer>(label->>'end')::integer
  OR (r->'cue_spans'->0->>'end')::integer>(r->'unit_spans'->0->>'start')::integer THEN
  RAISE EXCEPTION 'material_table_row_cue_unit' USING ERRCODE='23514'; END IF;
 IF r->'locator'->'row' IS DISTINCT FROM to_jsonb(ri+1) OR r->'locator'->'column' IS DISTINCT FROM to_jsonb(ci+1)
  OR jsonb_typeof(r->'locator'->'table') IS DISTINCT FROM 'string' OR length(r->'locator'->>'table')=0 THEN
  RAISE EXCEPTION 'material_table_locator_binding' USING ERRCODE='23514'; END IF;
 RETURN jsonb_build_object('version','source-table-grid/1.0.0',
  'grid_sha256',public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(g)),
  'verification','retained_spans_checked_layout_declared','row_index_0_based',ri,'column_index_0_based',ci,
  'row_count',nr,'column_count',nc,'raw_caption',caption,
  'raw_row_label',public.sclib_source_expression_spans_v2(t,jsonb_build_array(label),1200,false),
  'header_span',public.sclib_material_literal_span_v1(hs->ci),
  'row_label_span',public.sclib_material_literal_span_v1(label),
  'caption_span',public.sclib_material_literal_span_v1(caps->0));
END $$"""
    frozen = literal_model.upgrade_statements()

    def function(name):
        return next(sql for sql in frozen if sql.lstrip().startswith("CREATE FUNCTION public." + name + "("))

    project = function("sclib_material_literal_project_v1").replace("sclib_material_literal_project_v1", "sclib_material_table_project_v1")
    project = project.replace(literal.PROFILE, table.PROFILE)
    project = project.replace(canonical(literal.FIELDS).decode(), canonical(table.FIELDS).decode())
    project = replace_once(project, array(sorted(literal.EXPRESSION_KEYS)), array(sorted(table.EXPRESSION_KEYS)))
    project = replace_once(project, "vs jsonb; us jsonb; cs jsonb; xs jsonb;", "vs jsonb; us jsonb; cs jsonb; xs jsonb; tb jsonb;")
    start = project.index(" IF (cs->>'end')::integer>")
    end = project.index(" IF jsonb_typeof(r->'qualifiers')", start)
    project = project[:start] + """ tb:=public.sclib_material_table_binding_v1(t,r);
 IF xs IS NOT NULL AND ((xs->>'start')::integer<(vs->>'start')::integer OR (xs->>'end')::integer>(vs->>'end')::integer) THEN
  RAISE EXCEPTION 'material_table_uncertainty_in_cell' USING ERRCODE='23514'; END IF;
""" + project[end:]
    project = replace_once(project, "raw:=public.sclib_material_literal_trim_v1(substring(t FROM a+1 FOR z-a));", "raw:=amount;")
    project = replace_once(project, "'quantity',NULL,'normalization','none',", "'quantity',NULL,'normalization','none','unit_basis','table_row_label',")
    project = replace_once(project, "'subject',subject,'window',w,'source_role',r->'source_role','model',model);", "'subject',subject,'window',w,'source_role',r->'source_role','model',model,'table_binding',tb);")
    insert = function("sclib_material_literal_source_insert_v1")
    case = function("sclib_material_literal_case_insert_v1")
    for before, after in (("sclib_material_literal_source_insert_v1", "sclib_material_table_source_insert_v1"),
                          ("sclib_material_literal_case_insert_v1", "sclib_material_table_case_insert_v1"),
                          ("sclib_material_literal_project_v1", "sclib_material_table_project_v1"),
                          ("source-expression-package/2.1.0", table.VERSION),
                          ("source-expression-intake/2.1.0", "source-expression-intake/2.2.0"),
                          ("material-field-case-operation/1.1.0", "material-field-case-operation/1.2.0"),
                          ("material-field-case/1.1.0", "material-field-case/1.2.0"),
                          (literal.PROFILE, table.PROFILE)):
        insert = insert.replace(before, after)
        case = case.replace(before, after)
    case = replace_once(case, array(literal.FIELDS), array(table.FIELDS))
    selector = r"""CREATE FUNCTION public.sclib_material_table_select_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v text; f text; p public.source_expression_imports_v2%ROWTYPE; t public.material_field_targets_v1%ROWTYPE;
 raw boolean; tab boolean; BEGIN
 IF TG_TABLE_NAME='source_expression_imports_v2' THEN
  v:=NEW.package_json::jsonb->>'version';
  IF v IS NULL OR v NOT IN ('source-expression-package/2.0.0','source-expression-package/2.1.0','source-expression-package/2.2.0') THEN
   RAISE EXCEPTION 'material_table_package_version' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='source_expression_revisions_v2' THEN
  SELECT * INTO p FROM public.source_expression_imports_v2 WHERE id=NEW.import_receipt_id;
  v:=p.package_json::jsonb->>'version'; raw:=NEW.field_id=ANY(RAW_FIELDS); tab:=NEW.field_id=ANY(TABLE_FIELDS);
  IF p.id IS NULL OR v IS NULL OR v NOT IN ('source-expression-package/2.0.0','source-expression-package/2.1.0','source-expression-package/2.2.0')
   OR (v='source-expression-package/2.0.0' AND raw) OR (v='source-expression-package/2.1.0' AND NOT raw)
   OR (v='source-expression-package/2.2.0' AND NOT tab)
   OR (v='source-expression-package/2.2.0') IS DISTINCT FROM (NEW.projection_json::jsonb->>'profile' IS NOT DISTINCT FROM 'TABLE_PROFILE') THEN
   RAISE EXCEPTION 'material_table_revision_profile' USING ERRCODE='23514'; END IF;
 ELSE
  v:=NEW.request_json::jsonb->>'version'; f:=NEW.field_id; raw:=f=ANY(RAW_FIELDS); tab:=f=ANY(TABLE_FIELDS);
  IF v IS NULL OR v NOT IN ('material-field-case-operation/1.0.0','material-field-case-operation/1.1.0','material-field-case-operation/1.2.0') THEN
   RAISE EXCEPTION 'field_case_exact_request_required' USING ERRCODE='23514'; END IF;
  IF (v='material-field-case-operation/1.0.0' AND raw) OR (v='material-field-case-operation/1.1.0' AND NOT raw)
   OR (v='material-field-case-operation/1.2.0' AND NOT tab) THEN
   RAISE EXCEPTION 'material_table_case_profile' USING ERRCODE='23514'; END IF;
  IF NEW.operation<>'target' THEN
   SELECT * INTO t FROM public.material_field_targets_v1 WHERE id=NEW.target_id;
   IF t.id IS NULL OR t.field_id IS DISTINCT FROM f OR t.request_json::jsonb->>'version' IS DISTINCT FROM v THEN
    RAISE EXCEPTION 'material_table_target_profile' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$""".replace("RAW_FIELDS", array(literal.FIELDS)).replace("TABLE_FIELDS", array(table.FIELDS)).replace("TABLE_PROFILE", table.PROFILE)
    return [binding, project, insert, case, selector]


def upgrade_statements():
    statements = definitions()
    for name in source_model.TABLE_ORDER[1:]:
        statements += [f"DROP TRIGGER {trigger} ON public.{name}" for trigger in ("aa86_profile", "se83_insert", "se86_insert")]
        statements += [f"CREATE TRIGGER aa91_profile BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_material_table_select_v1()"]
        if name.endswith("imports_v2"):
            modes = [f"NEW.package_json::jsonb->>'version'='source-expression-package/{version}'" for version in ("2.0.0", "2.1.0", "2.2.0")]
        else:
            is_table = "NEW.projection_json::jsonb->>'profile' IS NOT DISTINCT FROM '" + table.PROFILE + "'"
            is_raw = "NEW.field_id=ANY(" + array(literal.FIELDS) + ")"
            modes = [f"NOT ({is_raw})", f"({is_raw}) AND NOT ({is_table})", is_table]
        for suffix, mode, function in zip(("83", "86", "91"), modes, ("sclib_source_expression_insert_v2", "sclib_material_literal_source_insert_v1", "sclib_material_table_source_insert_v1"), strict=True):
            statements.append(f"CREATE TRIGGER se{suffix}_insert BEFORE INSERT ON public.{name} FOR EACH ROW WHEN ({mode}) EXECUTE FUNCTION public.{function}()")
    for name in case_model.TABLE_ORDER:
        statements += [f"DROP TRIGGER {trigger} ON public.{name}" for trigger in ("aa86_profile", "fc84_insert", "fc86_insert")]
        statements += [f"CREATE TRIGGER aa91_profile BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_material_table_select_v1()"]
        for suffix, version, function in zip(("84", "86", "91"), ("1.0.0", "1.1.0", "1.2.0"), ("sclib_material_field_insert_v1", "sclib_material_literal_case_insert_v1", "sclib_material_table_case_insert_v1"), strict=True):
            statements.append(f"CREATE TRIGGER fc{suffix}_insert BEFORE INSERT ON public.{name} FOR EACH ROW WHEN (NEW.request_json::jsonb->>'version'='material-field-case-operation/{version}') EXECUTE FUNCTION public.{function}()")
    return statements


def downgrade_statements():
    statements = ["""DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.source_expression_imports_v2 WHERE package_json::jsonb->>'version'='source-expression-package/2.2.0')
 OR EXISTS(SELECT 1 FROM public.material_field_targets_v1 WHERE request_json::jsonb->>'version'='material-field-case-operation/1.2.0') THEN
 RAISE EXCEPTION 'table history retained; downgrade refused' USING ERRCODE='55000'; END IF; END $$"""]
    for name in source_model.TABLE_ORDER[1:]:
        statements += [f"DROP TRIGGER {trigger} ON public.{name}" for trigger in ("aa91_profile", "se83_insert", "se86_insert", "se91_insert")]
    for name in case_model.TABLE_ORDER:
        statements += [f"DROP TRIGGER {trigger} ON public.{name}" for trigger in ("aa91_profile", "fc84_insert", "fc86_insert", "fc91_insert")]
    statements += [sql for sql in literal_model.upgrade_statements() if sql.startswith("CREATE TRIGGER")]
    statements += [f"DROP FUNCTION public.{name}({args})" for name, args in reversed(FUNCTION_SIGNATURES)]
    return statements


def register(metadata):
    if metadata.info.get("material_table_fields_v1"):
        return
    metadata.info["material_table_fields_v1"] = True
    for sql in upgrade_statements():
        sa.event.listen(metadata, "after_create", sa.DDL(sql.replace("%", "%%")).execute_if(dialect="postgresql"))
