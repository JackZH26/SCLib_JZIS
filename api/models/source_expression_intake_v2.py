"""Additive closed v2 private fragment and expression revision history."""

from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = (
    "source_expression_captures_v2",
    "source_expression_imports_v2",
    "source_expression_revisions_v2",
)
LOCK_FUNCTION = "sclib_source_expression_lock_v2"
EXPECTED_REGISTRY_SHA256 = "96aebf58ceffad643c5aa156697f6aff064fe7a43fcfd3b27c9ade53bac5535a"
FUNCTION_SIGNATURES = (
    (LOCK_FUNCTION, ""),
    ("sclib_source_expression_immutable_v2", ""),
    ("sclib_source_expression_spans_v2", "text,jsonb,integer,boolean"),
    ("sclib_source_expression_token_v2", "text,jsonb,text,boolean"),
    ("sclib_source_expression_quantity_v2", "text,text,text,boolean,boolean"),
    ("sclib_source_expression_project_v2", "jsonb,text,jsonb"),
    ("sclib_source_expression_insert_v2", ""),
    ("sclib_source_expression_complete_v2", ""),
)


def guard_statements():
    from services.source_expression_contract_v2 import FIELDS, REGISTRY_SHA256, UNIT_MAPS

    if REGISTRY_SHA256 != EXPECTED_REGISTRY_SHA256:
        raise RuntimeError("Frozen 0083 registry changed; use an additive contract and migration")

    definitions = r"""
CREATE FUNCTION public.sclib_source_expression_lock_v2() RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF current_setting('transaction_isolation')<>'serializable' THEN
  RAISE EXCEPTION 'source_expression_serializable_required' USING ERRCODE='25000'; END IF;
 PERFORM public.sclib_research_publication_lock_v1();
 IF NOT pg_try_advisory_xact_lock(830017026) THEN
  RAISE EXCEPTION 'source_expression_busy_retry' USING ERRCODE='55P03'; END IF;
END $$;
CREATE FUNCTION public.sclib_source_expression_immutable_v2() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'source expression history is append-only' USING ERRCODE='55000'; END $$;
CREATE FUNCTION public.sclib_source_expression_spans_v2(t text,s jsonb,b integer,optional boolean) RETURNS text
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v jsonb; a integer; z integer; previous_end integer:=-1; part text; result text:=''; BEGIN
 IF jsonb_typeof(s) IS DISTINCT FROM 'array' OR jsonb_array_length(s)>8
  OR (NOT optional AND jsonb_array_length(s)=0) THEN
  RAISE EXCEPTION 'source_expression_bounded_spans' USING ERRCODE='23514'; END IF;
 FOR v IN SELECT value FROM jsonb_array_elements(s) LOOP
  IF jsonb_typeof(v) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(v))<>3
   OR NOT v ?& ARRAY['start','end','sha256'] OR jsonb_typeof(v->'start') IS DISTINCT FROM 'number'
   OR jsonb_typeof(v->'end') IS DISTINCT FROM 'number' OR v->>'start' !~ '^[0-9]{1,7}$'
   OR v->>'end' !~ '^[0-9]{1,7}$' OR jsonb_typeof(v->'sha256') IS DISTINCT FROM 'string'
   OR v->>'sha256' !~ '^[a-f0-9]{64}$' THEN
   RAISE EXCEPTION 'source_expression_exact_span' USING ERRCODE='23514'; END IF;
  a:=(v->>'start')::integer; z:=(v->>'end')::integer;
  IF a<0 OR z<=a OR z>length(t) OR z-a>b OR a<previous_end THEN
   RAISE EXCEPTION 'source_expression_exact_span' USING ERRCODE='23514'; END IF;
  part:=substring(t FROM a+1 FOR z-a);
  IF encode(public.digest(convert_to(part,'UTF8'),'sha256'),'hex')<>v->>'sha256' THEN
   RAISE EXCEPTION 'source_expression_span_hash' USING ERRCODE='23514'; END IF;
  result:=result||part;
  previous_end:=z;
 END LOOP;
 IF length(result)>b THEN RAISE EXCEPTION 'source_expression_span_bound' USING ERRCODE='23514'; END IF;
 RETURN result;
END $$;
CREATE FUNCTION public.sclib_source_expression_token_v2(t text,s jsonb,kind text,is_unit boolean) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a integer:=(s->>'start')::integer; z integer:=(s->>'end')::integer;
 l text; r text; p text; n text; m text[]; i integer; tag text; BEGIN
 l:=substring(t FROM greatest(1,a-159) FOR least(a,160)); r:=substring(t FROM z+1 FOR 160);
 IF kind='xml_text' THEN
  FOR i IN 1..16 LOOP
   m:=regexp_match(l,'(</?([A-Za-z_][A-Za-z0-9_.:-]*)[^<>]*>)$');
   IF m IS NULL THEN EXIT; END IF;
   tag:=regexp_replace(m[2],'^.*:','');
   IF tag NOT IN ('t','r','rPr') THEN l:=''; EXIT; END IF;
   l:=left(l,length(l)-length(m[1]));
  END LOOP;
  FOR i IN 1..16 LOOP
   m:=regexp_match(r,'^(</?([A-Za-z_][A-Za-z0-9_.:-]*)[^<>]*>)');
   IF m IS NULL THEN EXIT; END IF;
   tag:=regexp_replace(m[2],'^.*:','');
   IF tag NOT IN ('t','r','rPr') THEN r:=''; EXIT; END IF;
   r:=substring(r FROM length(m[1])+1);
  END LOOP;
 END IF;
 p:=right(l,1); n:=left(r,1);
 IF is_unit THEN
  RETURN NOT (p ~ '[A-Za-z.*/^·_-]' OR n ~ '[A-Za-z0-9.*/^·_-]'
   OR (p<>'' AND ascii(p)>127 AND p !~ '[[:space:]]')
   OR (n<>'' AND ascii(n)>127 AND n !~ '[[:space:]]')
   OR (substring(t FROM a+1 FOR 1) ~ '[0-9]' AND p ~ '[0-9]'));
 END IF;
 RETURN NOT (p ~ '[A-Za-z0-9.+−±-]'
  OR (p<>'' AND ascii(p)>127 AND p !~ '[[:space:]]')
  OR (n<>'' AND ascii(n)>127 AND n !~ '[[:space:]]')
  OR l ~ '([+−<>≤≥~≈±≲≳-]|[<>]=)[[:space:]]*$'
  OR n ~ '[A-Za-z0-9+−/*^·-]' OR (n='.' AND substring(t FROM z FOR 1) ~ '[0-9]')
  OR r ~ '^[[:space:]]*(±|\+/-|\([0-9]+(\.[0-9]+)?\))'
  OR r ~ '^[[:space:]]*[×·*][[:space:]]*10([[:space:]]*\^|[⁰¹²³⁴⁵⁶⁷⁸⁹])'
  OR (n=',' AND substring(r FROM 2 FOR 1) ~ '[0-9]')
  OR (p=',' AND substring(l FROM greatest(1,length(l)-1) FOR 1) ~ '[0-9]'));
END $$;
CREATE FUNCTION public.sclib_source_expression_quantity_v2(raw text,explicit_unit text,field text,value_complete boolean,unit_complete boolean) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE target text; units jsonb; m text[]; inline_unit text; u text; v float8; uncertainty float8;
 result jsonb; BEGIN
 target:=('FIELDS_JSON'::jsonb)->>field; units:=('UNITS_JSON'::jsonb)->target;
 result:=jsonb_build_object('raw_value',raw,'raw_unit',explicit_unit,'value',NULL,'unit',NULL,
  'uncertainty',NULL,'uncertainty_interpretation',NULL,'approximate',false,'relation','unresolved',
  'status','value_requires_review','unit_basis','unresolved');
 IF NOT value_complete THEN RETURN result; END IF;
 m:=regexp_match(trim(replace(raw,'−','-')),'^(~|≈)?\s*([-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)(?:\s*(?:±|\+/-)\s*([-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?))?\s*([^0-9\s].*)?$');
 IF m IS NULL THEN RETURN result; END IF;
 inline_unit:=NULLIF(trim(m[4]),''); u:=COALESCE(inline_unit,explicit_unit);
 result:=result||jsonb_build_object('raw_unit',COALESCE(explicit_unit,inline_unit),'approximate',m[1] IS NOT NULL);
 IF u IS NULL THEN RETURN result||jsonb_build_object('status','unit_not_supplied'); END IF;
 IF NOT unit_complete OR NOT units ? u OR (inline_unit IS NOT NULL AND explicit_unit IS NOT NULL
  AND (NOT units ? explicit_unit OR units->u IS DISTINCT FROM units->explicit_unit)) THEN
  RETURN result||jsonb_build_object('status','unit_requires_review'); END IF;
 BEGIN v:=m[2]::float8*(units->>u)::float8;
  uncertainty:=CASE WHEN m[3] IS NULL THEN NULL ELSE m[3]::float8*(units->>u)::float8 END;
 EXCEPTION WHEN numeric_value_out_of_range OR invalid_text_representation THEN RETURN result; END;
 IF v IN ('Infinity'::float8,'-Infinity'::float8,'NaN'::float8)
  OR uncertainty IN ('Infinity'::float8,'-Infinity'::float8,'NaN'::float8) OR uncertainty<0 THEN RETURN result; END IF;
 RETURN result||jsonb_build_object('value',v,'unit',target,'uncertainty',uncertainty,
  'uncertainty_interpretation',CASE WHEN uncertainty IS NULL THEN NULL ELSE 'unspecified' END,
  'relation','exact','status','parsed','unit_basis','source_printed');
END $$;
CREATE FUNCTION public.sclib_source_expression_project_v2(s jsonb,t text,r jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE field text; identity jsonb; subject jsonb; w jsonb; model text; raw text; unit text;
 value_body jsonb; conditions jsonb:='[]'; c jsonb; k text; v jsonb; basis jsonb; BEGIN
 IF jsonb_typeof(r) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(r))<>12
  OR NOT r ?& ARRAY['field_id','subject','window','source_role','knowledge_origin','origin_basis',
    'model_spans','value_spans','unit_spans','conditions','locator','predecessor'] THEN
  RAISE EXCEPTION 'source_expression_closed_request' USING ERRCODE='23514'; END IF;
 field:=r->>'field_id';
 IF jsonb_typeof(r->'field_id') IS DISTINCT FROM 'string' OR jsonb_typeof(r->'source_role') IS DISTINCT FROM 'string'
  OR jsonb_typeof(r->'knowledge_origin') IS DISTINCT FROM 'string'
  OR NOT ('FIELDS_JSON'::jsonb) ? field OR r->>'source_role' NOT IN ('source_reported','source_fitted','source_model_estimate','source_proposed')
  OR r->>'knowledge_origin' NOT IN ('Observed','Computed','unknown')
  OR jsonb_typeof(r->'subject') IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(r->'subject'))<>2
  OR NOT (r->'subject') ?& ARRAY['formula_spans','sample_label_spans']
  OR jsonb_typeof(r->'window') IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(r->'window'))<>2
  OR NOT (r->'window') ?& ARRAY['id','label_spans'] OR jsonb_typeof(r->'window'->'id') IS DISTINCT FROM 'string'
  OR length(r->'window'->>'id') NOT BETWEEN 1 AND 160
  OR r->'window'->>'id'<>trim(r->'window'->>'id') OR r->'window'->>'id' ~ '[[:cntrl:]]' THEN
  RAISE EXCEPTION 'source_expression_closed_subject_role' USING ERRCODE='23514'; END IF;
 subject:=jsonb_build_object('formula',public.sclib_source_expression_spans_v2(t,r->'subject'->'formula_spans',200,false),
  'sample_label',NULLIF(public.sclib_source_expression_spans_v2(t,r->'subject'->'sample_label_spans',200,true),''),
  'formula_scope',CASE WHEN jsonb_array_length(r->'subject'->'formula_spans')=1 THEN 'retained_formula_span' ELSE 'declared_formula_span_assembly' END);
 w:=jsonb_build_object('id',r->'window'->'id','raw_label',NULLIF(public.sclib_source_expression_spans_v2(t,r->'window'->'label_spans',500,true),''));
 model:=NULLIF(public.sclib_source_expression_spans_v2(t,r->'model_spans',500,true),'');
 IF jsonb_typeof(r->'origin_basis') IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(r->'origin_basis'))<>2
  OR NOT (r->'origin_basis') ?& ARRAY['statement','spans']
  OR (jsonb_typeof(r->'origin_basis'->'statement') NOT IN ('null','string'))
  OR (jsonb_typeof(r->'origin_basis'->'statement')='string' AND (length(r->'origin_basis'->>'statement') NOT BETWEEN 1 AND 500
   OR r->'origin_basis'->>'statement'<>trim(r->'origin_basis'->>'statement') OR r->'origin_basis'->>'statement' ~ '[[:cntrl:]]')) THEN
  RAISE EXCEPTION 'source_expression_origin_scope' USING ERRCODE='23514'; END IF;
 basis:=jsonb_build_object('statement',r->'origin_basis'->'statement','retained_text',NULLIF(public.sclib_source_expression_spans_v2(t,r->'origin_basis'->'spans',1000,true),''),'verification','declared_inspection_basis');
 IF jsonb_typeof(r->'value_spans') IS DISTINCT FROM 'array' OR jsonb_array_length(r->'value_spans')<>1
  OR jsonb_typeof(r->'unit_spans') IS DISTINCT FROM 'array' OR jsonb_array_length(r->'unit_spans')>1 THEN
  RAISE EXCEPTION 'source_expression_contiguous_value_unit' USING ERRCODE='23514'; END IF;
 raw:=public.sclib_source_expression_spans_v2(t,r->'value_spans',1200,false);
 unit:=NULLIF(public.sclib_source_expression_spans_v2(t,r->'unit_spans',40,true),'');
 IF ('FIELDS_JSON'::jsonb)->>field IS NULL THEN
  IF unit IS NOT NULL THEN RAISE EXCEPTION 'source_expression_statement_unit' USING ERRCODE='23514'; END IF;
  value_body:=jsonb_build_object('raw_value',raw,'status','source_statement');
 ELSE value_body:=public.sclib_source_expression_quantity_v2(raw,unit,field,public.sclib_source_expression_token_v2(t,r->'value_spans'->0,s->>'content_kind',false),jsonb_array_length(r->'unit_spans')=0 OR public.sclib_source_expression_token_v2(t,r->'unit_spans'->0,s->>'content_kind',true)); END IF;
 IF jsonb_typeof(r->'conditions') IS DISTINCT FROM 'array' OR jsonb_array_length(r->'conditions')>8 THEN
  RAISE EXCEPTION 'source_expression_bounded_conditions' USING ERRCODE='23514'; END IF;
 FOR c IN SELECT value FROM jsonb_array_elements(r->'conditions') LOOP
  IF jsonb_typeof(c) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(c))<>4
   OR NOT c ?& ARRAY['field_id','role','value_spans','unit_spans']
   OR jsonb_typeof(c->'field_id') IS DISTINCT FROM 'string' OR jsonb_typeof(c->'role') IS DISTINCT FROM 'string'
   OR c->>'field_id' NOT IN ('pressure_gpa','measurement_temperature_k','magnetic_field_t','method_statement','criterion_statement','window_statement')
   OR c->>'role' NOT IN ('reported_result_condition','study_extent','synthesis_condition','fit_window') THEN
   RAISE EXCEPTION 'source_expression_closed_condition' USING ERRCODE='23514'; END IF;
  IF jsonb_typeof(c->'value_spans') IS DISTINCT FROM 'array' OR jsonb_array_length(c->'value_spans')<>1
   OR jsonb_typeof(c->'unit_spans') IS DISTINCT FROM 'array' OR jsonb_array_length(c->'unit_spans')>1 THEN
   RAISE EXCEPTION 'source_expression_contiguous_value_unit' USING ERRCODE='23514'; END IF;
  raw:=public.sclib_source_expression_spans_v2(t,c->'value_spans',1200,false);
  unit:=NULLIF(public.sclib_source_expression_spans_v2(t,c->'unit_spans',40,true),'');
  IF ('FIELDS_JSON'::jsonb)->>(c->>'field_id') IS NOT NULL THEN
   value_body:=public.sclib_source_expression_quantity_v2(raw,unit,c->>'field_id',public.sclib_source_expression_token_v2(t,c->'value_spans'->0,s->>'content_kind',false),jsonb_array_length(c->'unit_spans')=0 OR public.sclib_source_expression_token_v2(t,c->'unit_spans'->0,s->>'content_kind',true));
  ELSE
   IF unit IS NOT NULL THEN RAISE EXCEPTION 'source_expression_statement_unit' USING ERRCODE='23514'; END IF;
   value_body:=jsonb_build_object('raw_value',raw,'status','source_statement');
  END IF;
  conditions:=conditions||jsonb_build_array(jsonb_build_object('field_id',c->'field_id','role',c->'role','value',value_body));
 END LOOP;
 IF jsonb_typeof(r->'locator') IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(r->'locator'))<>7
  OR NOT (r->'locator') ?& ARRAY['page','slide','table','row','column','section','member'] THEN
  RAISE EXCEPTION 'source_expression_closed_locator' USING ERRCODE='23514'; END IF;
 FOR k,v IN SELECT * FROM jsonb_each(r->'locator') LOOP
  IF jsonb_typeof(v)='null' THEN CONTINUE; END IF;
  IF k IN ('page','slide','row','column') THEN
   IF jsonb_typeof(v)<>'number' OR v::text !~ '^[0-9]{1,6}$' OR v::text::integer NOT BETWEEN 1 AND 100000 THEN
    RAISE EXCEPTION 'source_expression_numeric_locator' USING ERRCODE='23514'; END IF;
  ELSIF jsonb_typeof(v)<>'string' OR length(v#>>'{}') NOT BETWEEN 1 AND 200
   OR v#>>'{}'<>trim(v#>>'{}') OR v#>>'{}' ~ '[[:cntrl:]]' THEN
   RAISE EXCEPTION 'source_expression_text_locator' USING ERRCODE='23514'; END IF;
 END LOOP;
 identity:=jsonb_build_object('source_id',s->'source_id','field_id',field,'subject',subject,'window',w,'source_role',r->'source_role','model',model);
 raw:=public.sclib_source_expression_spans_v2(t,r->'value_spans',1200,false);
 unit:=NULLIF(public.sclib_source_expression_spans_v2(t,r->'unit_spans',40,true),'');
 value_body:=CASE WHEN ('FIELDS_JSON'::jsonb)->>field IS NULL THEN jsonb_build_object('raw_value',raw,'status','source_statement') ELSE public.sclib_source_expression_quantity_v2(raw,unit,field,public.sclib_source_expression_token_v2(t,r->'value_spans'->0,s->>'content_kind',false),jsonb_array_length(r->'unit_spans')=0 OR public.sclib_source_expression_token_v2(t,r->'unit_spans'->0,s->>'content_kind',true)) END;
 RETURN identity||jsonb_build_object('expression_key',encode(public.digest(convert_to(public.sclib_scientific_import_canonical_v1(identity),'UTF8'),'sha256'),'hex'),
  'knowledge_origin',r->'knowledge_origin','origin_basis',basis,'value',value_body,'conditions',conditions,'locator',r->'locator',
  'status','pending','selected_result_association','unestablished','sample_identity_established',false,
  'phase_identity_established',false,'scientific_acceptance',false,'canonical_promotions',0,
  'missingness_scope','not_supplied_in_retained_expression_is_not_source_absence');
END $$;
CREATE FUNCTION public.sclib_source_expression_insert_v2() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE c public.source_expression_captures_v2%ROWTYPE; p public.source_expression_imports_v2%ROWTYPE;
 h public.source_expression_revisions_v2%ROWTYPE; body jsonb; s jsonb; r jsonb; expected jsonb; preview jsonb;
 key text; BEGIN
 PERFORM public.sclib_source_expression_lock_v2();
 IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,'curator')
  OR NOT EXISTS(SELECT 1 FROM public.users WHERE id=NEW.actor_user_id AND session_version=NEW.actor_session_version) THEN
  RAISE EXCEPTION 'source_expression_live_actor_required' USING ERRCODE='42501'; END IF;
 IF TG_TABLE_NAME='source_expression_captures_v2' THEN
  s:=NEW.source_metadata;
  IF encode(public.digest(convert_to(NEW.source_text,'UTF8'),'sha256'),'hex')<>NEW.source_content_sha256
   OR encode(public.digest(convert_to(public.sclib_scientific_import_canonical_v1(s),'UTF8'),'sha256'),'hex')<>NEW.metadata_sha256
   OR jsonb_typeof(s)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(s))<>11
   OR NOT s ?& ARRAY['source_id','url','kind','content_kind','revision','revision_status','original_parent_sha256','parent_hash_status','rights_status','currentness','captured_at']
   OR s->>'source_id' IS DISTINCT FROM NEW.source_id OR s->>'currentness' IS DISTINCT FROM NEW.declared_currentness
   OR s->>'kind' NOT IN ('primary_paper','conference_presentation','supplement','crystal_reference')
   OR s->>'content_kind' NOT IN ('plain_text','xml_text')
   OR s->>'rights_status' NOT IN ('unresolved','declared_private_inspection','restricted')
   OR s->>'currentness' NOT IN ('unresolved','declared_current','historical')
   OR EXISTS(SELECT 1 FROM jsonb_each(s) AS attribute WHERE attribute.key IN ('source_id','url','kind','content_kind','revision_status','parent_hash_status','rights_status','currentness','captured_at')
     AND (jsonb_typeof(attribute.value) IS DISTINCT FROM 'string' OR length(attribute.value#>>'{}') NOT BETWEEN 1 AND 2048 OR (attribute.value#>>'{}') ~ '[[:cntrl:]]'))
   OR s->>'url' !~ '^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(:443)?(/[^[:space:]#]*)?$'
   OR (jsonb_typeof(s->'revision') NOT IN ('null','string'))
   OR (jsonb_typeof(s->'revision')='string' AND (length(s->>'revision') NOT BETWEEN 1 AND 160
    OR s->>'revision'<>trim(s->>'revision') OR s->>'revision' ~ '[[:cntrl:]]'))
   OR s->>'captured_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[-+][0-9]{2}:[0-9]{2})$'
   OR (jsonb_typeof(s->'original_parent_sha256') NOT IN ('null','string'))
   OR (jsonb_typeof(s->'original_parent_sha256')='string' AND s->>'original_parent_sha256' !~ '^[a-f0-9]{64}$') THEN
   RAISE EXCEPTION 'source_expression_capture_integrity' USING ERRCODE='23514'; END IF;
  BEGIN PERFORM (s->>'captured_at')::timestamptz;
  EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format THEN
   RAISE EXCEPTION 'source_expression_declared_timestamp' USING ERRCODE='23514'; END;
  FOREACH key IN ARRAY ARRAY['revision','original_parent_sha256'] LOOP
   IF s->>(CASE WHEN key='revision' THEN 'revision_status' ELSE 'parent_hash_status' END) NOT IN ('declared','unresolved')
    OR (jsonb_typeof(s->key)='null') IS DISTINCT FROM (s->>(CASE WHEN key='revision' THEN 'revision_status' ELSE 'parent_hash_status' END)='unresolved') THEN
    RAISE EXCEPTION 'source_expression_declared_parent_revision' USING ERRCODE='23514'; END IF;
  END LOOP;
 ELSIF TG_TABLE_NAME='source_expression_imports_v2' THEN
  SELECT * INTO c FROM public.source_expression_captures_v2 WHERE id=NEW.capture_id;
  body:=NEW.package_json::jsonb;
  IF c.id IS NULL OR jsonb_typeof(body)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(body))<>4
   OR NOT body ?& ARRAY['version','source','source_content_sha256','expressions']
   OR body->>'version' IS DISTINCT FROM 'source-expression-package/2.0.0' OR body->'source' IS DISTINCT FROM c.source_metadata
   OR body->>'source_content_sha256' IS DISTINCT FROM c.source_content_sha256
   OR encode(public.digest(convert_to(NEW.package_json,'UTF8'),'sha256'),'hex')<>NEW.package_sha256
   OR NEW.package_json IS DISTINCT FROM public.sclib_scientific_import_canonical_v1(body)
   OR jsonb_typeof(body->'expressions') IS DISTINCT FROM 'array' OR jsonb_array_length(body->'expressions')<>NEW.expression_count
   OR NEW.request_sha256<>encode(public.digest(convert_to(public.sclib_scientific_import_canonical_v1(jsonb_build_object('version','source-expression-intake/2.0.0','package_sha256',NEW.package_sha256)),'UTF8'),'sha256'),'hex') THEN
   RAISE EXCEPTION 'source_expression_exact_receipt' USING ERRCODE='23514'; END IF;
  preview:=jsonb_build_object('version','source-expression-intake/2.0.0','request_key',NEW.request_key,'request_sha256',NEW.request_sha256,
   'actor',jsonb_build_object('actor_user_id',NEW.actor_user_id,'actor_grant_id',NEW.actor_grant_id,'actor_session_version',NEW.actor_session_version),
   'manifest',NEW.expression_manifest);
  IF encode(public.digest(convert_to(public.sclib_scientific_import_canonical_v1(preview),'UTF8'),'sha256'),'hex')<>NEW.preview_sha256 THEN
   RAISE EXCEPTION 'source_expression_exact_preview' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='source_expression_revisions_v2' THEN
  SELECT * INTO p FROM public.source_expression_imports_v2 WHERE id=NEW.import_receipt_id;
  SELECT * INTO c FROM public.source_expression_captures_v2 WHERE id=NEW.capture_id;
  IF p.id IS NULL OR c.id IS NULL OR p.assembly_xid<>txid_current() OR p.capture_id<>c.id
   OR NEW.import_receipt_sha256 IS DISTINCT FROM p.record_sha256
   OR p.actor_user_id<>NEW.actor_user_id OR p.actor_grant_id<>NEW.actor_grant_id OR p.actor_session_version<>NEW.actor_session_version
   OR NEW.entry_index<0 OR NEW.entry_index>=p.expression_count THEN
   RAISE EXCEPTION 'source_expression_atomic_revision' USING ERRCODE='23514'; END IF;
  r:=(p.package_json::jsonb)->'expressions'->NEW.entry_index;
  expected:=public.sclib_source_expression_project_v2(c.source_metadata,c.source_text,r);
  IF expected IS DISTINCT FROM NEW.projection_json::jsonb OR expected->>'expression_key'<>NEW.expression_key
   OR encode(public.digest(convert_to(public.sclib_scientific_import_canonical_v1(r),'UTF8'),'sha256'),'hex')<>NEW.entry_sha256
   OR expected->>'field_id'<>NEW.field_id
   OR encode(public.digest(convert_to(NEW.projection_json,'UTF8'),'sha256'),'hex')<>NEW.projection_sha256 THEN
   RAISE EXCEPTION 'source_expression_exact_projection' USING ERRCODE='23514'; END IF;
  SELECT * INTO h FROM public.source_expression_revisions_v2 WHERE expression_key=NEW.expression_key ORDER BY revision_number DESC LIMIT 1;
  IF h.id IS NULL THEN
   IF NEW.predecessor_id IS NOT NULL OR NEW.predecessor_sha256 IS NOT NULL OR NEW.revision_number<>1 OR r->'predecessor'<>'null'::jsonb THEN
    RAISE EXCEPTION 'source_expression_initial_head' USING ERRCODE='23514'; END IF;
  ELSE
   IF NEW.predecessor_id IS DISTINCT FROM h.id OR NEW.predecessor_sha256 IS DISTINCT FROM h.record_sha256
    OR NEW.revision_number<>h.revision_number+1 OR r->'predecessor' IS DISTINCT FROM jsonb_build_object('revision_id',h.id,'record_sha256',h.record_sha256,'revision_number',h.revision_number) THEN
    RAISE EXCEPTION 'source_expression_exact_successor' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 body:=to_jsonb(NEW)-ARRAY['created_at','record_sha256','assembly_xid'];
 IF encode(public.digest(convert_to(public.sclib_scientific_import_canonical_v1(body),'UTF8'),'sha256'),'hex')<>NEW.record_sha256 THEN
  RAISE EXCEPTION 'source_expression_record_hash' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION public.sclib_source_expression_complete_v2() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.source_expression_imports_v2%ROWTYPE; actual jsonb; BEGIN
 IF TG_TABLE_NAME='source_expression_imports_v2' THEN p:=NEW;
 ELSE SELECT * INTO p FROM public.source_expression_imports_v2 WHERE id=NEW.import_receipt_id; END IF;
 SELECT jsonb_agg(jsonb_build_object('entry_index',entry_index,'expression_key',expression_key,'projection_sha256',projection_sha256,
  'entry_sha256',entry_sha256,'predecessor_id',predecessor_id,'predecessor_sha256',predecessor_sha256,'revision_number',revision_number) ORDER BY entry_index)
 INTO actual FROM public.source_expression_revisions_v2 WHERE import_receipt_id=p.id;
 IF actual IS DISTINCT FROM p.expression_manifest OR jsonb_array_length(actual)<>p.expression_count THEN
  RAISE EXCEPTION 'source_expression_complete_inventory' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
""".replace("FIELDS_JSON", json.dumps(FIELDS, separators=(",", ":"))).replace(
        "UNITS_JSON", json.dumps(UNIT_MAPS, separators=(",", ":"))
    )
    statements = [part + "$$;" for part in definitions.split("$$;") if part.strip()]
    for name in TABLE_ORDER:
        statements.extend(
            [
                f"CREATE TRIGGER se83_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_source_expression_insert_v2()",
                f"CREATE TRIGGER se83_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_source_expression_immutable_v2()",
                f"CREATE TRIGGER se83_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_source_expression_immutable_v2()",
            ]
        )
    for name in TABLE_ORDER[1:]:
        statements.append(
            f"CREATE CONSTRAINT TRIGGER se83_complete AFTER INSERT ON public.{name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sclib_source_expression_complete_v2()"
        )
    return statements


def register(metadata):
    tables = {}

    def col(name, kind, *, nullable=False, default=None):
        return sa.Column(name, kind, nullable=nullable, server_default=default)

    def uid(name, target=None, *, nullable=False):
        return (
            col(name, UUID(as_uuid=True), nullable=nullable)
            if target is None
            else sa.Column(
                name,
                UUID(as_uuid=True),
                sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT"),
                nullable=nullable,
            )
        )

    def table(name, *items):
        i = TABLE_ORDER.index(name)
        tables[name] = sa.Table(
            name,
            metadata,
            uid("id"),
            uid("actor_user_id", "users.id"),
            uid("actor_grant_id", "research_role_grants.id"),
            col("actor_session_version", sa.Integer),
            *items,
            col("record_sha256", sa.String(64)),
            col("created_at", sa.DateTime(timezone=True), default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint(
                "actor_session_version>=0 AND isfinite(created_at)", name=f"ck_se83_{i}_actor"
            ),
            *[
                sa.CheckConstraint(
                    f"{c.name} IS NULL OR {c.name} ~ '^[a-f0-9]{{64}}$'",
                    name=f"ck_se83_{i}_{c.name}",
                )
                for c in items
                if isinstance(c, sa.Column) and c.name.endswith("sha256")
            ],
        )

    table(
        TABLE_ORDER[0],
        col("source_id", sa.String(160)),
        col("source_content_sha256", sa.String(64)),
        col("metadata_sha256", sa.String(64)),
        col("source_text", sa.Text),
        col("source_metadata", JSONB),
        col("declared_currentness", sa.String(30)),
        sa.UniqueConstraint("metadata_sha256", "source_content_sha256", name="uq_se83_capture"),
        sa.CheckConstraint(
            "octet_length(source_text) BETWEEN 1 AND 131072 AND source_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$' AND declared_currentness IN ('declared_current','historical','unresolved')",
            name="ck_se83_capture_bounds",
        ),
    )
    table(
        TABLE_ORDER[1],
        col("request_key", sa.String(160)),
        col("request_sha256", sa.String(64)),
        col("preview_sha256", sa.String(64)),
        uid("capture_id", TABLE_ORDER[0] + ".id"),
        col("package_json", sa.Text),
        col("package_sha256", sa.String(64)),
        col("expression_count", sa.Integer),
        col("expression_manifest", JSONB),
        col("assembly_xid", sa.BigInteger, default=sa.text("txid_current()")),
        sa.UniqueConstraint("actor_user_id", "request_key", name="uq_se83_request"),
        sa.UniqueConstraint("package_sha256", name="uq_se83_package"),
        sa.CheckConstraint(
            "request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$' AND expression_count BETWEEN 1 AND 20 AND octet_length(package_json) BETWEEN 2 AND 131072",
            name="ck_se83_receipt_bounds",
        ),
    )
    table(
        TABLE_ORDER[2],
        uid("import_receipt_id", TABLE_ORDER[1] + ".id"),
        col("import_receipt_sha256", sa.String(64)),
        uid("capture_id", TABLE_ORDER[0] + ".id"),
        col("entry_index", sa.Integer),
        col("entry_sha256", sa.String(64)),
        col("expression_key", sa.String(64)),
        col("field_id", sa.String(100)),
        col("revision_number", sa.Integer),
        uid("predecessor_id", TABLE_ORDER[2] + ".id", nullable=True),
        col("predecessor_sha256", sa.String(64), nullable=True),
        col("projection_json", sa.Text),
        col("projection_sha256", sa.String(64)),
        sa.UniqueConstraint(
            "expression_key", "revision_number", name="uq_se83_expression_revision"
        ),
        sa.UniqueConstraint("predecessor_id", name="uq_se83_successor"),
        sa.UniqueConstraint("import_receipt_id", "entry_index", name="uq_se83_receipt_entry"),
        sa.CheckConstraint(
            "entry_index BETWEEN 0 AND 19 AND revision_number BETWEEN 1 AND 10001 AND octet_length(projection_json) BETWEEN 2 AND 32768 AND ((revision_number=1 AND predecessor_id IS NULL AND predecessor_sha256 IS NULL) OR (revision_number>1 AND predecessor_id IS NOT NULL AND predecessor_sha256 IS NOT NULL))",
            name="ck_se83_revision_bounds",
        ),
    )
    last = tables[TABLE_ORDER[-1]]
    for name in ("users", "research_role_grants", "research_publication_epoch", *TABLE_ORDER[:-1]):
        last.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(
            last,
            "after_create",
            sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"),
        )
    return tables
