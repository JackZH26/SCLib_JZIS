"""Additive 0086 raw literals. Frozen numeric functions are never replaced."""
from __future__ import annotations

import sqlalchemy as sa

from models import material_field_cases_v1 as case_model
from models import source_expression_intake_v2 as source_model
from services import source_expression_contract_v2_1 as raw_contract
from services.material_literal_field_contract import FIELDS, PROFILE, QUALIFIERS
from services.research_release_manifest import canonical

FUNCTION_SIGNATURES = (
    ("sclib_material_literal_trim_v1", "text"),
    ("sclib_material_literal_span_v1", "jsonb"),
    ("sclib_material_literal_project_v1", "jsonb,text,jsonb"),
    ("sclib_material_literal_source_insert_v1", ""),
    ("sclib_material_literal_case_insert_v1", ""),
    ("sclib_material_literal_select_v1", ""),
)


def _function(model, name):
    return next(s for s in model.guard_statements() if s.lstrip().startswith("CREATE FUNCTION public." + name + "("))


def upgrade_statements():
    fields = canonical(FIELDS).decode().replace("'", "''")
    field_array = "ARRAY[" + ",".join("'" + f + "'" for f in FIELDS) + "]"
    qualifier_array = "ARRAY[" + ",".join("'" + f + "'" for f in QUALIFIERS) + "]"
    keys = "ARRAY[" + ",".join("'" + f + "'" for f in sorted(raw_contract.EXPRESSION_KEYS)) + "]"
    whitespace = [*range(9, 14), *range(28, 33), 133, 160, 5760, *range(8192, 8203), 8232, 8233, 8239, 8287, 12288]
    trim = "CREATE FUNCTION public.sclib_material_literal_trim_v1(v text) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$ SELECT btrim(v," + "||".join("chr(" + str(n) + ")" for n in whitespace) + ") $$"
    span = """CREATE FUNCTION public.sclib_material_literal_span_v1(s jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT CASE WHEN s IS NULL THEN 'null'::jsonb ELSE jsonb_build_object('char_start',s->'start','char_end',s->'end','text_sha256',s->'sha256') END $$"""
    project = r"""CREATE FUNCTION public.sclib_material_literal_project_v1(s jsonb,t text,r jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE field text; role text; identity jsonb; subject jsonb; w jsonb; model text; basis jsonb; raw text; unit text;
 cue text; uncertainty text; amount text; value_body jsonb; v jsonb; k text; a integer; z integer; wa integer; wz integer;
 vs jsonb; us jsonb; cs jsonb; xs jsonb; BEGIN
 IF NOT public.sclib_material_field_closed_v1(r,KEYS)
  OR jsonb_typeof(r->'field_id') IS DISTINCT FROM 'string' OR NOT ('FIELDS'::jsonb) ? (r->>'field_id')
  OR r->>'profile' IS DISTINCT FROM 'PROFILE' OR jsonb_typeof(r->'profile') IS DISTINCT FROM 'string'
  OR jsonb_typeof(r->'field_role') IS DISTINCT FROM 'string'
  OR r->>'field_role' IS DISTINCT FROM ('FIELDS'::jsonb)->>(r->>'field_id')
  OR jsonb_typeof(r->'source_role') IS DISTINCT FROM 'string'
  OR r->>'source_role' NOT IN ('source_reported','source_fitted','source_model_estimate','source_proposed')
  OR jsonb_typeof(r->'knowledge_origin') IS DISTINCT FROM 'string' OR r->>'knowledge_origin' NOT IN ('Observed','Computed','unknown')
  OR NOT public.sclib_material_field_closed_v1(r->'subject',ARRAY['formula_spans','sample_label_spans'])
  OR NOT public.sclib_material_field_closed_v1(r->'window',ARRAY['id','label_spans'])
  OR jsonb_typeof(r->'window'->'id') IS DISTINCT FROM 'string' OR length(r->'window'->>'id') NOT BETWEEN 1 AND 160
  OR r->'window'->>'id'<>public.sclib_material_literal_trim_v1(r->'window'->>'id') OR r->'window'->>'id' ~ '[[:cntrl:]]'
  OR r->'conditions' IS DISTINCT FROM '[]'::jsonb THEN
  RAISE EXCEPTION 'material_literal_closed_profile' USING ERRCODE='23514'; END IF;
 field:=r->>'field_id'; role:=('FIELDS'::jsonb)->>field;
 IF jsonb_typeof(r->'subject'->'formula_spans') IS DISTINCT FROM 'array' OR jsonb_array_length(r->'subject'->'formula_spans')<>1
  OR jsonb_typeof(r->'window'->'label_spans') IS DISTINCT FROM 'array' OR jsonb_array_length(r->'window'->'label_spans')<>1
  OR jsonb_typeof(r->'value_spans') IS DISTINCT FROM 'array' OR jsonb_array_length(r->'value_spans')<>1
  OR jsonb_typeof(r->'unit_spans') IS DISTINCT FROM 'array' OR jsonb_array_length(r->'unit_spans')>1
  OR jsonb_typeof(r->'cue_spans') IS DISTINCT FROM 'array' OR jsonb_array_length(r->'cue_spans')<>1
  OR jsonb_typeof(r->'uncertainty_spans') IS DISTINCT FROM 'array' OR jsonb_array_length(r->'uncertainty_spans')>1 THEN
  RAISE EXCEPTION 'material_literal_contiguous_spans' USING ERRCODE='23514'; END IF;
 subject:=jsonb_build_object('formula',public.sclib_source_expression_spans_v2(t,r->'subject'->'formula_spans',200,false),
  'sample_label',NULLIF(public.sclib_source_expression_spans_v2(t,r->'subject'->'sample_label_spans',200,true),''),'formula_scope','retained_formula_span');
 w:=jsonb_build_object('id',r->'window'->'id','raw_label',public.sclib_source_expression_spans_v2(t,r->'window'->'label_spans',4096,false));
 amount:=public.sclib_source_expression_spans_v2(t,r->'value_spans',1200,false);
 unit:=CASE WHEN jsonb_array_length(r->'unit_spans')=0 THEN NULL ELSE public.sclib_material_literal_trim_v1(public.sclib_source_expression_spans_v2(t,r->'unit_spans',120,true)) END;
 cue:=public.sclib_source_expression_spans_v2(t,r->'cue_spans',200,false);
 uncertainty:=NULLIF(public.sclib_source_expression_spans_v2(t,r->'uncertainty_spans',200,true),'');
 wa:=(r->'window'->'label_spans'->0->>'start')::integer; wz:=(r->'window'->'label_spans'->0->>'end')::integer;
 FOR v IN SELECT value FROM jsonb_array_elements((r->'subject'->'formula_spans')||(r->'value_spans')||(r->'unit_spans')||(r->'cue_spans')||(r->'uncertainty_spans')) LOOP
  IF (v->>'start')::integer<wa OR (v->>'end')::integer>wz THEN
   RAISE EXCEPTION 'material_literal_same_window' USING ERRCODE='23514'; END IF;
 END LOOP;
 vs:=r->'value_spans'->0; us:=r->'unit_spans'->0; cs:=r->'cue_spans'->0; xs:=r->'uncertainty_spans'->0;
 IF (cs->>'end')::integer>(vs->>'start')::integer OR (vs->>'start')::integer-(cs->>'end')::integer>128
  OR (us IS NOT NULL AND ((us->>'start')::integer<(vs->>'end')::integer OR (us->>'start')::integer-(vs->>'end')::integer>128))
  OR (xs IS NOT NULL AND ((xs->>'start')::integer<(vs->>'start')::integer OR (xs->>'end')::integer>(vs->>'end')::integer)) THEN
  RAISE EXCEPTION 'material_literal_ordered_spans' USING ERRCODE='23514'; END IF;
 IF jsonb_typeof(r->'qualifiers') IS DISTINCT FROM 'array' OR jsonb_array_length(r->'qualifiers')>4
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(r->'qualifiers') q WHERE jsonb_typeof(q) IS DISTINCT FROM 'string' OR q#>>'{}' NOT IN (SELECT unnest(QUALIFIERS)))
  OR (SELECT count(DISTINCT q) FROM jsonb_array_elements(r->'qualifiers') q)<>jsonb_array_length(r->'qualifiers') THEN
  RAISE EXCEPTION 'material_literal_declared_qualifiers' USING ERRCODE='23514'; END IF;
 model:=NULLIF(public.sclib_source_expression_spans_v2(t,r->'model_spans',500,true),'');
 IF NOT public.sclib_material_field_closed_v1(r->'origin_basis',ARRAY['statement','spans'])
  OR (jsonb_typeof(r->'origin_basis'->'statement') NOT IN ('null','string'))
  OR (jsonb_typeof(r->'origin_basis'->'statement')='string' AND (length(r->'origin_basis'->>'statement') NOT BETWEEN 1 AND 500
   OR r->'origin_basis'->>'statement'<>public.sclib_material_literal_trim_v1(r->'origin_basis'->>'statement') OR r->'origin_basis'->>'statement' ~ '[[:cntrl:]]')) THEN
  RAISE EXCEPTION 'source_expression_origin_scope' USING ERRCODE='23514'; END IF;
 basis:=jsonb_build_object('statement',r->'origin_basis'->'statement','retained_text',NULLIF(public.sclib_source_expression_spans_v2(t,r->'origin_basis'->'spans',1000,true),''),'verification','declared_inspection_basis');
 IF NOT public.sclib_material_field_closed_v1(r->'locator',ARRAY['page','slide','table','row','column','section','member']) THEN
  RAISE EXCEPTION 'source_expression_closed_locator' USING ERRCODE='23514'; END IF;
 FOR k,v IN SELECT * FROM jsonb_each(r->'locator') LOOP
  IF jsonb_typeof(v)='null' THEN CONTINUE; END IF;
  IF k IN ('page','slide','row','column') THEN
   IF jsonb_typeof(v)<>'number' OR v::text !~ '^[0-9]{1,6}$' OR v::text::integer NOT BETWEEN 1 AND 100000 THEN
    RAISE EXCEPTION 'source_expression_numeric_locator' USING ERRCODE='23514'; END IF;
  ELSIF jsonb_typeof(v)<>'string' OR length(v#>>'{}') NOT BETWEEN 1 AND 200
   OR v#>>'{}'<>public.sclib_material_literal_trim_v1(v#>>'{}') OR v#>>'{}' ~ '[[:cntrl:]]' THEN
   RAISE EXCEPTION 'source_expression_text_locator' USING ERRCODE='23514'; END IF;
 END LOOP;
 a:=(vs->>'start')::integer; z:=COALESCE((us->>'end')::integer,(vs->>'end')::integer);
 raw:=public.sclib_material_literal_trim_v1(substring(t FROM a+1 FOR z-a));
 value_body:=jsonb_build_object('status','raw_literal','raw_value',raw,'raw_amount',amount,'raw_unit',unit,'raw_uncertainty',uncertainty,
  'quantity',NULL,'normalization','none','field_cue',cue,'role',role,'qualifiers',r->'qualifiers',
  'value_span',public.sclib_material_literal_span_v1(vs),'unit_span',public.sclib_material_literal_span_v1(us),
  'cue_span',public.sclib_material_literal_span_v1(cs),'uncertainty_span',public.sclib_material_literal_span_v1(xs));
 identity:=jsonb_build_object('source_id',s->'source_id','field_id',field,'profile','PROFILE','field_role',role,
  'subject',subject,'window',w,'source_role',r->'source_role','model',model);
 RETURN identity||jsonb_build_object('expression_key',public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(identity)),
  'knowledge_origin',r->'knowledge_origin','origin_basis',basis,'value',value_body,'conditions','[]'::jsonb,'locator',r->'locator',
  'status','pending','selected_result_association','unestablished','sample_identity_established',false,'phase_identity_established',false,
  'scientific_acceptance',false,'canonical_promotions',0,'field_interpretation_reviewed',false,'public_content_release',false,'ml_training_approved',false,
  'missingness_scope','not_supplied_in_retained_expression_is_not_source_absence');
END $$""".replace("'FIELDS'", "'" + fields + "'").replace("KEYS", keys).replace("QUALIFIERS", qualifier_array).replace("PROFILE", PROFILE)
    insert = _function(source_model, "sclib_source_expression_insert_v2").replace("sclib_source_expression_insert_v2", "sclib_material_literal_source_insert_v1")
    insert = insert.replace("source-expression-package/2.0.0", raw_contract.VERSION).replace("source-expression-intake/2.0.0", "source-expression-intake/2.1.0")
    insert = insert.replace("jsonb_object_keys(body))<>4", "jsonb_object_keys(body))<>5").replace("ARRAY['version','source','source_content_sha256','expressions']", "ARRAY['version','source','source_content_sha256','expressions','profile']")
    insert = insert.replace("OR body->'source' IS DISTINCT FROM c.source_metadata", "OR body->>'profile' IS DISTINCT FROM '" + PROFILE + "' OR body->'source' IS DISTINCT FROM c.source_metadata")
    insert = insert.replace("public.sclib_source_expression_project_v2(", "public.sclib_material_literal_project_v1(")
    case_insert = _function(case_model, "sclib_material_field_insert_v1").replace("sclib_material_field_insert_v1", "sclib_material_literal_case_insert_v1")
    case_insert = case_insert.replace("material-field-case-operation/1.0.0", "material-field-case-operation/1.1.0").replace("material-field-case/1.0.0", "material-field-case/1.1.0")
    from services.material_field_case_contract import FIELDS as old_fields
    old_array = "ARRAY[" + ",".join("'" + f + "'" for f in old_fields) + "]"
    case_insert = case_insert.replace(old_array, field_array).replace("public.sclib_source_expression_project_v2(", "public.sclib_material_literal_project_v1(")
    case_insert = case_insert.replace("OR receipt.record_sha256 IS DISTINCT FROM x.import_receipt_sha256", "OR receipt.record_sha256 IS DISTINCT FROM x.import_receipt_sha256\n    OR receipt.package_json::jsonb->>'version' IS DISTINCT FROM 'source-expression-package/2.1.0'\n    OR receipt.package_json::jsonb->>'profile' IS DISTINCT FROM '" + PROFILE + "'")
    selector = r"""CREATE FUNCTION public.sclib_material_literal_select_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v text; f text; t public.material_field_targets_v1%ROWTYPE; p public.source_expression_imports_v2%ROWTYPE;
 raw boolean; BEGIN
 IF TG_TABLE_NAME='source_expression_imports_v2' THEN
  v:=NEW.package_json::jsonb->>'version';
  IF v NOT IN ('source-expression-package/2.0.0','source-expression-package/2.1.0') OR v IS NULL THEN
   RAISE EXCEPTION 'material_literal_package_version' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='source_expression_revisions_v2' THEN
  SELECT * INTO p FROM public.source_expression_imports_v2 WHERE id=NEW.import_receipt_id;
  v:=p.package_json::jsonb->>'version'; raw:=NEW.field_id=ANY(FIELDS);
  IF p.id IS NULL OR v NOT IN ('source-expression-package/2.0.0','source-expression-package/2.1.0') OR v IS NULL
   OR (v='source-expression-package/2.1.0') IS DISTINCT FROM raw THEN
   RAISE EXCEPTION 'material_literal_revision_profile' USING ERRCODE='23514'; END IF;
 ELSE
  v:=NEW.request_json::jsonb->>'version'; f:=NEW.field_id; raw:=f=ANY(FIELDS);
  IF v NOT IN ('material-field-case-operation/1.0.0','material-field-case-operation/1.1.0') OR v IS NULL THEN
   RAISE EXCEPTION 'field_case_exact_request_required' USING ERRCODE='23514'; END IF;
  IF (v='material-field-case-operation/1.1.0') IS DISTINCT FROM raw THEN
   RAISE EXCEPTION 'material_literal_case_profile' USING ERRCODE='23514'; END IF;
  IF NEW.operation<>'target' THEN
   SELECT * INTO t FROM public.material_field_targets_v1 WHERE id=NEW.target_id;
   IF t.id IS NULL OR t.field_id IS DISTINCT FROM f OR t.request_json::jsonb->>'version' IS DISTINCT FROM v THEN
    RAISE EXCEPTION 'material_literal_target_profile' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$""".replace("FIELDS", field_array)
    statements = [trim, span, project, insert, case_insert, selector]
    for table in source_model.TABLE_ORDER[1:]:
        raw_when = "NEW.package_json::jsonb->>'version'='source-expression-package/2.1.0'" if table.endswith("imports_v2") else "NEW.field_id=ANY(" + field_array + ")"
        statements.extend([
            f"DROP TRIGGER se83_insert ON public.{table}",
            f"CREATE TRIGGER aa86_profile BEFORE INSERT ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.sclib_material_literal_select_v1()",
            f"CREATE TRIGGER se83_insert BEFORE INSERT ON public.{table} FOR EACH ROW WHEN (NOT ({raw_when})) EXECUTE FUNCTION public.sclib_source_expression_insert_v2()",
            f"CREATE TRIGGER se86_insert BEFORE INSERT ON public.{table} FOR EACH ROW WHEN ({raw_when}) EXECUTE FUNCTION public.sclib_material_literal_source_insert_v1()",
        ])
    for table in case_model.TABLE_ORDER:
        raw_when = "NEW.request_json::jsonb->>'version'='material-field-case-operation/1.1.0'"
        statements.extend([
            f"DROP TRIGGER fc84_insert ON public.{table}",
            f"CREATE TRIGGER aa86_profile BEFORE INSERT ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.sclib_material_literal_select_v1()",
            f"CREATE TRIGGER fc84_insert BEFORE INSERT ON public.{table} FOR EACH ROW WHEN (NOT ({raw_when})) EXECUTE FUNCTION public.sclib_material_field_insert_v1()",
            f"CREATE TRIGGER fc86_insert BEFORE INSERT ON public.{table} FOR EACH ROW WHEN ({raw_when}) EXECUTE FUNCTION public.sclib_material_literal_case_insert_v1()",
        ])
    return statements


def downgrade_statements():
    statements = ["""DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.source_expression_imports_v2 WHERE package_json::jsonb->>'version'='source-expression-package/2.1.0') OR EXISTS(SELECT 1 FROM public.material_field_targets_v1 WHERE request_json::jsonb->>'version'='material-field-case-operation/1.1.0') THEN RAISE EXCEPTION 'literal history retained; downgrade refused' USING ERRCODE='55000'; END IF; END $$"""]
    for table in source_model.TABLE_ORDER[1:]:
        statements.extend([f"DROP TRIGGER aa86_profile ON public.{table}", f"DROP TRIGGER se86_insert ON public.{table}", f"DROP TRIGGER se83_insert ON public.{table}", f"CREATE TRIGGER se83_insert BEFORE INSERT ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.sclib_source_expression_insert_v2()"])
    for table in case_model.TABLE_ORDER:
        statements.extend([f"DROP TRIGGER aa86_profile ON public.{table}", f"DROP TRIGGER fc86_insert ON public.{table}", f"DROP TRIGGER fc84_insert ON public.{table}", f"CREATE TRIGGER fc84_insert BEFORE INSERT ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.sclib_material_field_insert_v1()"])
    statements += [f"DROP FUNCTION public.{name}({arguments})" for name, arguments in reversed(FUNCTION_SIGNATURES)]
    return statements


def register(metadata):
    """Attach after frozen 0083/0084/0085 hooks; root owns registration."""
    if metadata.info.get("material_literal_fields_v1"):
        return
    metadata.info["material_literal_fields_v1"] = True
    for sql in upgrade_statements():
        sa.event.listen(metadata, "after_create", sa.DDL(sql.replace("%", "%%")).execute_if(dialect="postgresql"))
