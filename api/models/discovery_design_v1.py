"""0087 private owner research-design revisions, separate from scientific objects."""
import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = ("discovery_design_revisions_v1",)
LOCK_FUNCTION = "sclib_discovery_design_lock_v1"
FUNCTION_SIGNATURES = ((LOCK_FUNCTION, ""), ("sclib_discovery_design_text_v1", "jsonb,integer"),
    ("sclib_discovery_design_decimal_v1", "jsonb,boolean"), ("sclib_discovery_design_plan_v1", "jsonb"),
    ("sclib_discovery_design_context_v1", "jsonb"), ("sclib_discovery_design_projection_v1", "text"),
    ("sclib_discovery_design_insert_v1", ""), ("sclib_discovery_design_immutable_v1", ""))


def guard_statements():
    definitions = r"""
CREATE FUNCTION public.sclib_discovery_design_lock_v1() RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF current_setting('transaction_isolation')<>'serializable' THEN
  RAISE EXCEPTION 'design_serializable_required' USING ERRCODE='25000'; END IF;
 PERFORM public.sclib_research_integrity_lock_v1();
 PERFORM public.sclib_research_publication_lock_v1();
 PERFORM public.sclib_source_lifecycle_lock_v1();
 IF NOT pg_try_advisory_xact_lock(870017026) THEN
  RAISE EXCEPTION 'design_busy_retry' USING ERRCODE='55P03'; END IF;
END $$;
CREATE FUNCTION public.sclib_discovery_design_text_v1(v jsonb,n integer) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT coalesce(jsonb_typeof(v)='string' AND length(v#>>'{}') BETWEEN 1 AND n
  AND v#>>'{}'=trim(v#>>'{}') AND v#>>'{}' !~ '[[:cntrl:]]',false)
$$;
CREATE FUNCTION public.sclib_discovery_design_decimal_v1(v jsonb,optional boolean) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t text; f double precision; BEGIN
 IF optional AND v='null'::jsonb THEN RETURN true; END IF;
 IF NOT public.sclib_discovery_design_text_v1(v,80) THEN RETURN false; END IF;
 t:=v#>>'{}';
 IF t !~ '^([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$' THEN RETURN false; END IF;
 f:=t::double precision;
 RETURN f>=0 AND f<'Infinity'::double precision AND NOT (f=0 AND split_part(lower(t),'e',1) ~ '[1-9]');
 EXCEPTION WHEN numeric_value_out_of_range OR invalid_text_representation THEN RETURN false;
END $$;
CREATE FUNCTION public.sclib_discovery_design_plan_v1(d jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t jsonb; p jsonb; a jsonb; x jsonb; expected text; BEGIN
 IF NOT public.sclib_material_field_closed_v1(d,ARRAY['host_label','state_label','modifications','target_conditions','pairing_hypothesis','hypothesis','next_action'])
  OR NOT public.sclib_discovery_design_text_v1(d->'host_label',500)
  OR NOT public.sclib_discovery_design_text_v1(d->'state_label',500)
  OR NOT public.sclib_discovery_design_text_v1(d->'hypothesis',4000)
  OR jsonb_typeof(d->'pairing_hypothesis') IS DISTINCT FROM 'string'
  OR d->>'pairing_hypothesis' NOT IN ('unresolved','epc','correlated','multiband','interface')
  OR jsonb_typeof(d->'modifications') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(d->'modifications') NOT BETWEEN 1 AND 8 THEN RETURN false; END IF;
 FOR x IN SELECT value FROM jsonb_array_elements(d->'modifications') LOOP
  IF NOT public.sclib_material_field_closed_v1(x,ARRAY['kind','parameters'])
   OR jsonb_typeof(x->'kind') IS DISTINCT FROM 'string'
   OR x->>'kind' NOT IN ('doping','substitution','vacancy','strain','interface','layer','twist','pressure')
   OR NOT public.sclib_discovery_design_text_v1(x->'parameters',2000) THEN RETURN false; END IF;
 END LOOP;
 t:=d->'target_conditions'; p:=t->'pressure'; a:=d->'next_action';
 IF NOT public.sclib_material_field_closed_v1(t,ARRAY['pressure','temperature_k'])
  OR NOT public.sclib_material_field_closed_v1(p,ARRAY['kind','raw_gpa'])
  OR jsonb_typeof(p->'kind') IS DISTINCT FROM 'string' OR p->>'kind' NOT IN ('unspecified','ambient','specified')
  OR NOT public.sclib_discovery_design_decimal_v1(t->'temperature_k',true)
  OR (p->>'kind'='specified' AND NOT public.sclib_discovery_design_decimal_v1(p->'raw_gpa',false))
  OR (p->>'kind'<>'specified' AND p->'raw_gpa' IS DISTINCT FROM 'null'::jsonb)
  OR NOT public.sclib_material_field_closed_v1(a,ARRAY['kind','question','prerequisites','outcomes','budget'])
  OR jsonb_typeof(a->'kind') IS DISTINCT FROM 'string' OR a->>'kind' NOT IN ('source_review','calculation','experiment')
  OR NOT public.sclib_discovery_design_text_v1(a->'question',2000)
  OR jsonb_typeof(a->'prerequisites') IS DISTINCT FROM 'array'
  OR jsonb_typeof(a->'outcomes') IS DISTINCT FROM 'array'
  OR jsonb_typeof(a->'budget') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(a->'prerequisites') NOT BETWEEN 1 AND 16
  OR jsonb_array_length(a->'outcomes') NOT BETWEEN 2 AND 8 OR jsonb_array_length(a->'budget')<>5 THEN RETURN false; END IF;
 FOR x IN SELECT value FROM jsonb_array_elements(a->'prerequisites') LOOP
  IF NOT public.sclib_discovery_design_text_v1(x,1000) THEN RETURN false; END IF;
 END LOOP;
 FOR x IN SELECT value FROM jsonb_array_elements(a->'outcomes') LOOP
  IF NOT public.sclib_material_field_closed_v1(x,ARRAY['observation','decision'])
   OR NOT public.sclib_discovery_design_text_v1(x->'observation',1000)
   OR jsonb_typeof(x->'decision') IS DISTINCT FROM 'string'
   OR x->>'decision' NOT IN ('continue','stop','redirect') THEN RETURN false; END IF;
 END LOOP;
 IF (SELECT count(DISTINCT lower(item->>'observation')) FROM jsonb_array_elements(a->'outcomes') item)<>jsonb_array_length(a->'outcomes')
  OR (SELECT count(DISTINCT item->>'decision') FROM jsonb_array_elements(a->'outcomes') item)<2 THEN RETURN false; END IF;
 FOR x IN SELECT value FROM jsonb_array_elements(a->'budget') LOOP
  IF NOT public.sclib_material_field_closed_v1(x,ARRAY['resource','status','raw_upper','unit'])
   OR jsonb_typeof(x->'resource') IS DISTINCT FROM 'string'
   OR x->>'resource' NOT IN ('cpu_hours','gpu_hours','memory','storage','human_hours')
   OR jsonb_typeof(x->'status') IS DISTINCT FROM 'string' OR x->>'status' NOT IN ('unknown','estimated')
   OR jsonb_typeof(x->'unit') IS DISTINCT FROM 'string' THEN RETURN false; END IF;
  expected:=CASE x->>'resource' WHEN 'cpu_hours' THEN 'core-hour' WHEN 'gpu_hours' THEN 'gpu-hour'
   WHEN 'human_hours' THEN 'person-hour' ELSE 'GiB' END;
  IF x->>'unit' IS DISTINCT FROM expected
   OR (x->>'status'='unknown' AND x->'raw_upper' IS DISTINCT FROM 'null'::jsonb)
   OR (x->>'status'='estimated' AND NOT public.sclib_discovery_design_decimal_v1(x->'raw_upper',false)) THEN RETURN false; END IF;
 END LOOP;
 RETURN (SELECT count(DISTINCT item->>'resource') FROM jsonb_array_elements(a->'budget') item)=5;
END $$;
CREATE FUNCTION public.sclib_discovery_design_context_v1(b jsonb) RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE k text; base jsonb; subject jsonb; result jsonb; source_rows jsonb; papers text[]; works uuid[]; t jsonb; BEGIN
 IF NOT public.sclib_material_field_closed_v1(b,ARRAY['kind','material_id','record_index','property_id','expected_context_sha256'])
  OR jsonb_typeof(b->'kind') IS DISTINCT FROM 'string' OR b->>'kind' NOT IN ('unanchored','retained_result','native_property')
  OR jsonb_typeof(b->'expected_context_sha256') IS DISTINCT FROM 'string'
  OR b->>'expected_context_sha256' !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'design_baseline_selector_required' USING ERRCODE='23514'; END IF;
 k:=b->>'kind';
 IF k='unanchored' THEN
  IF b->'material_id' IS DISTINCT FROM 'null'::jsonb OR b->'record_index' IS DISTINCT FROM 'null'::jsonb
   OR b->'property_id' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'design_unanchored_selector_required' USING ERRCODE='23514'; END IF;
  RETURN public.sclib_scientific_import_canonical_v1(jsonb_build_object('version','discovery-design-context/1.0.0','kind',k,'base',NULL,'subject',NULL,'sources','[]'::jsonb));
 END IF;
 IF NOT public.sclib_discovery_design_text_v1(b->'material_id',100) THEN RAISE EXCEPTION 'design_material_selector_required' USING ERRCODE='23514'; END IF;
 IF k='retained_result' THEN
  IF b->'property_id' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'design_retained_selector_required' USING ERRCODE='23514'; END IF;
  t:=jsonb_build_object('kind','retained_result','material_id',b->'material_id','record_index',b->'record_index','entity_id',NULL,'expected_context_sha256',b->'expected_context_sha256');
  base:=public.sclib_material_field_context_v1(t)::jsonb;
  result:=base->'result';
  IF jsonb_typeof(result->'paper_id')='string' THEN papers:=ARRAY[result->>'paper_id']; ELSE papers:=ARRAY[]::text[]; END IF;
  -- A raw legacy Work label is not a reviewed FK. Only the catalogue's
  -- explicitly accepted paper-to-Work map carries related lifecycle holds.
  works:=ARRAY[]::uuid[];
 ELSE
  IF b->'record_index' IS DISTINCT FROM 'null'::jsonb OR jsonb_typeof(b->'property_id') IS DISTINCT FROM 'string'
   OR (b->>'property_id')::uuid::text<>b->>'property_id' THEN RAISE EXCEPTION 'design_native_selector_required' USING ERRCODE='23514'; END IF;
  t:=jsonb_build_object('kind','event_property','material_id',b->'material_id','record_index',NULL,'entity_id',b->'property_id','expected_context_sha256',b->'expected_context_sha256');
  base:=public.sclib_material_field_context_v1(t)::jsonb;
  subject:=public.sclib_scientific_subject_capture_v1((b->>'property_id')::uuid)::jsonb;
  IF subject->'target'->>'material_id' IS DISTINCT FROM b->>'material_id'
   OR subject->'target'->>'property_id' IS DISTINCT FROM b->>'property_id' THEN
   RAISE EXCEPTION 'design_native_subject_mismatch' USING ERRCODE='23514'; END IF;
  SELECT coalesce(array_agg(DISTINCT id ORDER BY id),ARRAY[]::text[]) INTO papers FROM (
   SELECT CASE WHEN x->>'table'='papers' THEN x->>'row_id' ELSE x->'snapshot'->>'paper_id' END AS id
   FROM jsonb_array_elements(subject->'rows') x) ids WHERE id IS NOT NULL;
  SELECT coalesce(array_agg(DISTINCT id ORDER BY id),ARRAY[]::uuid[]) INTO works FROM (
   SELECT (CASE WHEN x->>'table'='works' THEN x->>'row_id' ELSE x->'snapshot'->>'work_id' END)::uuid AS id
   FROM jsonb_array_elements(subject->'rows') x) ids WHERE id IS NOT NULL;
 END IF;
 SELECT coalesce(array_agg(DISTINCT id ORDER BY id),ARRAY[]::uuid[]) INTO works FROM (
  SELECT unnest(works) AS id UNION SELECT work_id FROM public.paper_work_map WHERE paper_id=ANY(papers) AND review_status='accepted') ids;
 SELECT coalesce(jsonb_agg(item ORDER BY item->>'kind',item->>'id'),'[]'::jsonb) INTO source_rows FROM (
  SELECT jsonb_build_object('kind','paper','id',p.id,'row',to_jsonb(p),'lifecycle',
   (SELECT to_jsonb(e) FROM public.source_lifecycle_events e WHERE paper_id=p.id ORDER BY revision DESC LIMIT 1),
   'accepted_work_maps',(SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY m.work_id),'[]'::jsonb) FROM public.paper_work_map m WHERE m.paper_id=p.id AND m.review_status='accepted')) AS item FROM public.papers p WHERE p.id=ANY(papers)
  UNION ALL SELECT jsonb_build_object('kind','work','id',w.id,'row',to_jsonb(w),'lifecycle',
   (SELECT to_jsonb(e) FROM public.source_lifecycle_events e WHERE work_id=w.id ORDER BY revision DESC LIMIT 1),'accepted_work_maps','[]'::jsonb)
  FROM public.works w WHERE w.id=ANY(works)) collected;
 IF jsonb_array_length(source_rows)>1000 THEN RAISE EXCEPTION 'design_source_bound' USING ERRCODE='23514'; END IF;
 RETURN public.sclib_scientific_import_canonical_v1(jsonb_build_object('version','discovery-design-context/1.0.0','kind',k,'base',base,'subject',subject,'sources',source_rows));
END $$;
CREATE FUNCTION public.sclib_discovery_design_projection_v1(c text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE b jsonb; p jsonb; e jsonb; s jsonb; field text; expected text; values jsonb; v jsonb; BEGIN
 b:=c::jsonb;
 IF b->>'kind'='unanchored' THEN RETURN jsonb_build_object('kind','unanchored','material_id',NULL,'formula',NULL,'record_index',NULL,'property_id',NULL,'event_id',NULL,'state_id',NULL,'producer_run_id',NULL,'source_snapshot_sha256',public.sclib_source_property_hash_v1(c),'values','[]'::jsonb,'knowledge_origin',NULL,'pressure_status',NULL,'pressure_gpa',NULL,'temperature_k',NULL); END IF;
 p:=b->'base'->'result'; e:=b->'base'->'event'; s:=b->'base'->'state'; values:='[]'::jsonb;
 IF b->>'kind'='native_property' THEN
  field:=p->>'property_key'; expected:=CASE field WHEN 'formation_energy_per_atom' THEN 'eV/atom' WHEN 'energy_above_hull' THEN 'eV/atom'
   WHEN 'band_gap' THEN 'eV' WHEN 'dos_at_fermi' THEN 'states/eV/formula_unit' WHEN 'electron_phonon_lambda' THEN '1'
   WHEN 'omega_log' THEN 'K' WHEN 'phonon_min_frequency' THEN 'THz' WHEN 'superfluid_stiffness' THEN 'K' ELSE NULL END;
  IF expected IS NULL OR p->>'unit' IS DISTINCT FROM expected OR p->>'relation' IS DISTINCT FROM 'exact'
   OR jsonb_typeof(p->'value') IS DISTINCT FROM 'number'
   OR (p->>'value')::double precision IN ('Infinity'::double precision,'-Infinity'::double precision,'NaN'::double precision) THEN
   RAISE EXCEPTION 'design_native_finite_exact_property_required' USING ERRCODE='23514'; END IF;
  values:=jsonb_build_array(jsonb_build_object('field_id',field,'value',p->'value','unit',expected,'relation','exact'));
 ELSE
  IF jsonb_typeof(p->'tc_kelvin')='number' THEN
   v:=p->'tc_kelvin'; IF public.sclib_discovery_design_decimal_v1(to_jsonb(v#>>'{}'),false) THEN
    values:=jsonb_build_array(jsonb_build_object('field_id','tc_kelvin','value',v,'unit','K','relation','source_reported_unspecified_criterion')); END IF;
  END IF;
 END IF;
 RETURN jsonb_build_object('kind',b->>'kind','material_id',b->'base'->>'material_id','formula',
  CASE WHEN public.sclib_discovery_design_text_v1(b->'base'->'material'->'formula',500) THEN b->'base'->'material'->'formula' ELSE 'null'::jsonb END,
  'record_index',b->'base'->'record_index','property_id',CASE WHEN b->>'kind'='native_property' THEN p->'id' ELSE 'null'::jsonb END,
  'event_id',e->'id','state_id',s->'id','producer_run_id',e->'producer_run_id','source_snapshot_sha256',public.sclib_source_property_hash_v1(c),
  'values',values,'knowledge_origin',CASE WHEN coalesce(e->>'knowledge_origin',p->>'knowledge_origin') IN ('Observed','Computed') THEN coalesce(e->'knowledge_origin',p->'knowledge_origin') ELSE 'null'::jsonb END,
  'pressure_status',CASE WHEN b->>'kind'='native_property' AND s->>'pressure_status' IN ('explicit_ambient','reported','not_reported','ambiguous') THEN s->'pressure_status' ELSE 'null'::jsonb END,
  'pressure_gpa',CASE WHEN b->>'kind'='native_property' AND jsonb_typeof(s->'pressure_gpa')='number' AND public.sclib_discovery_design_decimal_v1(to_jsonb(s->>'pressure_gpa'),false) THEN s->'pressure_gpa' WHEN b->>'kind'='retained_result' AND jsonb_typeof(p->'pressure_gpa')='number' AND public.sclib_discovery_design_decimal_v1(to_jsonb(p->>'pressure_gpa'),false) THEN p->'pressure_gpa' ELSE 'null'::jsonb END,
  'temperature_k',CASE WHEN b->>'kind'='native_property' AND jsonb_typeof(s->'temperature_k')='number' AND public.sclib_discovery_design_decimal_v1(to_jsonb(s->>'temperature_k'),false) THEN s->'temperature_k' ELSE 'null'::jsonb END);
END $$;
CREATE FUNCTION public.sclib_discovery_design_immutable_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'research design history is append-only' USING ERRCODE='55000'; END $$;
CREATE FUNCTION public.sclib_discovery_design_insert_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE q jsonb; p jsonb; previous public.discovery_design_revisions_v1%ROWTYPE;
 parent_row public.discovery_design_revisions_v1%ROWTYPE; root_row public.discovery_design_revisions_v1%ROWTYPE;
 expected text; preview jsonb; x jsonb; seen uuid[]; cursor_id uuid; n integer; BEGIN
 PERFORM public.sclib_discovery_design_lock_v1();
 IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,'curator')
  OR NOT EXISTS(SELECT 1 FROM public.users WHERE id=NEW.actor_user_id AND session_version=NEW.actor_session_version) THEN
  RAISE EXCEPTION 'design_live_actor_required' USING ERRCODE='42501'; END IF;
 q:=NEW.request_json::jsonb; p:=q->'payload';
 IF NOT public.sclib_material_field_closed_v1(q,ARRAY['version','request_key','operation','payload'])
  OR q->>'version' IS DISTINCT FROM 'discovery-design-operation/1.0.0'
  OR jsonb_typeof(q->'request_key') IS DISTINCT FROM 'string' OR q->>'request_key' IS DISTINCT FROM NEW.request_key
  OR q->>'operation' IS DISTINCT FROM NEW.operation OR q->'payload' IS DISTINCT FROM NEW.payload
  OR NEW.request_json IS DISTINCT FROM public.sclib_scientific_import_canonical_v1(q)
  OR NEW.request_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.request_json) THEN
  RAISE EXCEPTION 'design_exact_request_required' USING ERRCODE='23514'; END IF;
 IF NEW.operation='propose' THEN
  IF NOT public.sclib_material_field_closed_v1(p,ARRAY['baseline','design','parent']) OR NEW.revision<>1
   OR NEW.predecessor_id IS NOT NULL OR NEW.predecessor_sha256 IS NOT NULL
   OR EXISTS(SELECT 1 FROM public.discovery_design_revisions_v1 WHERE design_id=NEW.design_id) THEN
   RAISE EXCEPTION 'design_proposal_shape' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.operation='revise' THEN
   IF NOT public.sclib_material_field_closed_v1(p,ARRAY['baseline','design','parent','design_id','predecessor']) THEN
    RAISE EXCEPTION 'design_revision_shape' USING ERRCODE='23514'; END IF;
  ELSIF NEW.operation='withdraw' THEN
   IF NOT public.sclib_material_field_closed_v1(p,ARRAY['design_id','predecessor','reason']) OR NOT public.sclib_discovery_design_text_v1(p->'reason',2000) THEN
    RAISE EXCEPTION 'design_withdraw_shape' USING ERRCODE='23514'; END IF;
  ELSE RAISE EXCEPTION 'design_operation_required' USING ERRCODE='23514'; END IF;
  SELECT * INTO previous FROM public.discovery_design_revisions_v1 WHERE design_id=NEW.design_id ORDER BY revision DESC LIMIT 1;
  IF previous.id IS NULL OR previous.actor_user_id<>NEW.actor_user_id OR previous.operation='withdraw'
   OR p->>'design_id' IS DISTINCT FROM NEW.design_id::text
   OR NOT public.sclib_material_field_closed_v1(p->'predecessor',ARRAY['id','record_sha256'])
   OR p->'predecessor' IS DISTINCT FROM jsonb_build_object('id',previous.id::text,'record_sha256',previous.record_sha256)
   OR NEW.predecessor_id IS DISTINCT FROM previous.id OR NEW.predecessor_sha256 IS DISTINCT FROM previous.record_sha256
   OR NEW.revision<>previous.revision+1 THEN RAISE EXCEPTION 'design_exact_owner_head_required' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.operation='withdraw' THEN
  IF NEW.baseline IS DISTINCT FROM previous.baseline OR NEW.design IS DISTINCT FROM previous.design OR NEW.parent IS DISTINCT FROM previous.parent
   OR NEW.context_json IS DISTINCT FROM previous.context_json OR NEW.projection IS DISTINCT FROM previous.projection THEN
   RAISE EXCEPTION 'design_withdraw_context_required' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.baseline IS DISTINCT FROM p->'baseline' OR NEW.design IS DISTINCT FROM p->'design' OR NEW.parent IS DISTINCT FROM p->'parent'
   OR NOT public.sclib_discovery_design_plan_v1(NEW.design) THEN RAISE EXCEPTION 'design_plan_required' USING ERRCODE='23514'; END IF;
  expected:=public.sclib_discovery_design_context_v1(NEW.baseline);
  IF NEW.context_json IS DISTINCT FROM expected OR NEW.context_sha256 IS DISTINCT FROM NEW.baseline->>'expected_context_sha256'
   OR NEW.projection IS DISTINCT FROM public.sclib_discovery_design_projection_v1(expected) THEN
   RAISE EXCEPTION 'design_source_pin_changed' USING ERRCODE='23514'; END IF;
  x:=expected::jsonb;
  IF coalesce((x->'base'->'material'->>'needs_review')::boolean,false)
   OR coalesce((x->'base'->'material'->>'retracted')::boolean,false)
   OR coalesce((x->'base'->'material'->>'disputed')::boolean,false)
   OR lower(coalesce(x->'base'->'material'->>'status','')) IN ('retracted','disputed','corrected')
   OR x->'base'->'event'->>'validity_status' IN ('disputed','retracted','excluded')
   OR x->'base'->'event'->>'review_status'='rejected'
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(x->'sources') source_item
     WHERE source_item->'lifecycle'<>'null'::jsonb OR lower(coalesce(source_item->'row'->>'status',source_item->'row'->>'publication_status','')) IN ('retracted','withdrawn','corrected','disputed')) THEN
   RAISE EXCEPTION 'design_current_source_hold' USING ERRCODE='23514'; END IF;
  IF NEW.operation='revise' AND NEW.parent IS DISTINCT FROM previous.parent THEN
   RAISE EXCEPTION 'design_parent_fixed_per_chain' USING ERRCODE='23514'; END IF;
  IF NEW.parent<>'null'::jsonb THEN
   IF NOT public.sclib_material_field_closed_v1(NEW.parent,ARRAY['design_id','revision_id','record_sha256']) THEN
    RAISE EXCEPTION 'design_parent_pin_required' USING ERRCODE='23514'; END IF;
   SELECT * INTO parent_row FROM public.discovery_design_revisions_v1 WHERE id=(NEW.parent->>'revision_id')::uuid;
   SELECT * INTO root_row FROM public.discovery_design_revisions_v1 WHERE design_id=parent_row.design_id ORDER BY revision DESC LIMIT 1;
   IF parent_row.id IS NULL OR parent_row.actor_user_id<>NEW.actor_user_id OR parent_row.operation='withdraw'
    OR root_row.operation='withdraw' OR NEW.parent->>'design_id' IS DISTINCT FROM parent_row.design_id::text
    OR NEW.parent->>'record_sha256' IS DISTINCT FROM parent_row.record_sha256 THEN
    RAISE EXCEPTION 'design_owner_parent_unavailable' USING ERRCODE='23514'; END IF;
   seen:=ARRAY[NEW.design_id]; cursor_id:=parent_row.design_id;
   FOR n IN 1..32 LOOP
    IF cursor_id=ANY(seen) THEN RAISE EXCEPTION 'design_parent_cycle' USING ERRCODE='23514'; END IF;
    seen:=array_append(seen,cursor_id);
    SELECT * INTO root_row FROM public.discovery_design_revisions_v1 WHERE design_id=cursor_id AND revision=1;
    IF root_row.parent='null'::jsonb THEN cursor_id:=NULL; EXIT; END IF;
    cursor_id:=(root_row.parent->>'design_id')::uuid;
   END LOOP;
   IF cursor_id IS NOT NULL THEN RAISE EXCEPTION 'design_parent_depth_bound' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF NEW.context_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.context_json)
  OR NEW.projection_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(NEW.projection))
  OR NEW.scientific_acceptance OR NEW.ml_training_approved OR NEW.public_release OR NEW.calculation_executed OR NEW.canonical_promotions<>0 THEN
  RAISE EXCEPTION 'design_no_authority_required' USING ERRCODE='23514'; END IF;
 preview:=jsonb_build_object('version','discovery-design/1.0.0','actor',jsonb_build_object('actor_user_id',NEW.actor_user_id::text,'actor_grant_id',NEW.actor_grant_id::text,'actor_session_version',NEW.actor_session_version),
  'request_sha256',NEW.request_sha256,'receipt_id',NEW.id::text,'design_id',NEW.design_id::text,'revision',NEW.revision,'context_sha256',NEW.context_sha256);
 IF NEW.preview_json IS DISTINCT FROM public.sclib_scientific_import_canonical_v1(preview)
  OR NEW.preview_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.preview_json)
  OR NEW.record_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(NEW)-ARRAY['created_at','record_sha256','context_json','projection'])) THEN
  RAISE EXCEPTION 'design_exact_receipt_required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""
    return [*re.split(r";\n(?=CREATE FUNCTION)", definitions.strip()),
        "CREATE TRIGGER dd87_insert BEFORE INSERT ON public.discovery_design_revisions_v1 FOR EACH ROW EXECUTE FUNCTION public.sclib_discovery_design_insert_v1()",
        "CREATE TRIGGER dd87_immutable BEFORE UPDATE OR DELETE ON public.discovery_design_revisions_v1 FOR EACH ROW EXECUTE FUNCTION public.sclib_discovery_design_immutable_v1()",
        "CREATE TRIGGER dd87_truncate BEFORE TRUNCATE ON public.discovery_design_revisions_v1 FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_discovery_design_immutable_v1()"]


def register(metadata):
    def uid(name, target=None, nullable=False):
        return sa.Column(name, UUID(as_uuid=True), *([sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")] if target else []), nullable=nullable)
    name = TABLE_ORDER[0]
    table = sa.Table(name, metadata, uid("id"), uid("design_id"), sa.Column("revision", sa.Integer, nullable=False),
        uid("actor_user_id", "users.id"), uid("actor_grant_id", "research_role_grants.id"),
        sa.Column("actor_session_version", sa.Integer, nullable=False), sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("request_key", sa.String(160), nullable=False), sa.Column("request_json", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False), sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("preview_json", sa.Text, nullable=False), sa.Column("preview_sha256", sa.String(64), nullable=False),
        sa.Column("baseline", JSONB, nullable=False), sa.Column("design", JSONB, nullable=False), sa.Column("parent", JSONB, nullable=False),
        uid("predecessor_id", name + ".id", nullable=True), sa.Column("predecessor_sha256", sa.String(64)),
        sa.Column("context_json", sa.Text, nullable=False), sa.Column("context_sha256", sa.String(64), nullable=False),
        sa.Column("projection", JSONB, nullable=False), sa.Column("projection_sha256", sa.String(64), nullable=False),
        *[sa.Column(key, sa.Boolean, nullable=False) for key in ("scientific_acceptance", "ml_training_approved", "public_release", "calculation_executed")],
        sa.Column("canonical_promotions", sa.Integer, nullable=False), sa.Column("record_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("actor_user_id", "request_key", name="uq_dd87_request"),
        sa.UniqueConstraint("design_id", "revision", name="uq_dd87_revision"),
        sa.UniqueConstraint("predecessor_id", name="uq_dd87_successor"), sa.Index("idx_dd87_owner", "actor_user_id", "design_id"),
        sa.CheckConstraint("revision BETWEEN 1 AND 1000 AND actor_session_version>=0 AND isfinite(created_at) AND operation IN ('propose','revise','withdraw') AND (predecessor_id IS NULL)=(predecessor_sha256 IS NULL)", name="ck_dd87_identity"),
        sa.CheckConstraint("NOT scientific_acceptance AND NOT ml_training_approved AND NOT public_release AND NOT calculation_executed AND canonical_promotions=0", name="ck_dd87_no_authority"),
        sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$' AND octet_length(request_json) BETWEEN 2 AND 65536 AND octet_length(preview_json) BETWEEN 2 AND 4096 AND octet_length(context_json) BETWEEN 2 AND 9437184", name="ck_dd87_bounds"),
        *[sa.CheckConstraint(f"{key} IS NULL OR {key} ~ '^[a-f0-9]{{64}}$'", name=f"ck_dd87_{key}") for key in ("request_sha256", "preview_sha256", "context_sha256", "record_sha256", "projection_sha256", "predecessor_sha256")])
    for dependency in ("material_field_targets_v1", "scientific_result_decisions", "materials", "users", "research_role_grants", "research_publication_epoch", "source_lifecycle_epoch", "event_properties"):
        if dependency in metadata.tables:
            table.add_is_dependent_on(metadata.tables[dependency])
    for statement in guard_statements():
        sa.event.listen(table, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return {name: table}
