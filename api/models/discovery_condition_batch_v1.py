"""0088 owner-private condition batches and exact initial-child lineage.

Generation is reconstructed from a native immutable design, never from uploaded
proposals. Decimal identities use exact coefficient/exponent strings. The two
tables retain proposals and grant no scientific, publication or training rights.
SQL checks exact source closure and explicit governance/ancestry holds; the HTTP
service independently applies the existing current catalogue parser policy.
These SQL guards do not claim full parity with that frozen anomaly policy.
"""
import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = ("discovery_condition_batches_v1", "discovery_condition_child_links_v1")
LOCK_FUNCTION = "sclib_discovery_condition_batch_lock_v1"
FUNCTION_SIGNATURES = (
    (LOCK_FUNCTION, ""),
    ("sclib_discovery_condition_batch_decimal_v1", "jsonb"),
    ("sclib_discovery_condition_batch_axes_v1", "jsonb"),
    ("sclib_discovery_condition_batch_governance_v1", "jsonb"),
    ("sclib_discovery_condition_batch_parent_v1", "jsonb,uuid,uuid,bigint"),
    ("sclib_discovery_condition_batch_body_v1", "jsonb,jsonb,uuid,uuid,bigint"),
    ("sclib_discovery_condition_batch_manifest_v1", "jsonb,jsonb,uuid,uuid,bigint"),
    ("sclib_discovery_condition_batch_insert_v1", ""),
    ("sclib_discovery_condition_batch_immutable_v1", ""),
)


def guard_statements():
    # These integer bounds are the exact IEEE binary64 overflow rounding
    # boundary and twice the inverse underflow rounding boundary. No float
    # conversion participates in identities or SQL/TS admission parity.
    overflow = str(2 ** 1024 - 2 ** 970)
    inverse_half_minimum = str(2 ** 1075)
    definitions = r"""
CREATE FUNCTION public.sclib_discovery_condition_batch_lock_v1() RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 PERFORM public.sclib_discovery_design_lock_v1();
 IF NOT pg_try_advisory_xact_lock(880017026) THEN
  RAISE EXCEPTION 'condition_batch_busy_retry' USING ERRCODE='55P03'; END IF;
END $$;
CREATE FUNCTION public.sclib_discovery_condition_batch_decimal_v1(v jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE raw text; parts text[]; fractional text; digits text; coefficient text;
 exponent numeric; magnitude numeric; exact_value numeric; BEGIN
 IF NOT public.sclib_discovery_design_text_v1(v,64) THEN
  RAISE EXCEPTION 'condition_batch_decimal_invalid' USING ERRCODE='23514'; END IF;
 raw:=v#>>'{}';
 parts:=regexp_match(raw,'^(?:([0-9]+)(?:\.([0-9]*))?|\.([0-9]+))(?:[eE]([+-]?[0-9]+))?$');
 IF parts IS NULL THEN RAISE EXCEPTION 'condition_batch_decimal_invalid' USING ERRCODE='23514'; END IF;
 fractional:=coalesce(parts[2],parts[3],'');
 digits:=regexp_replace(coalesce(parts[1],'')||fractional,'^0+','');
 exponent:=coalesce(parts[4],'0')::numeric-length(fractional);
 IF exponent < -1999999999999999997::numeric OR exponent > 999999999999999999::numeric THEN
  RAISE EXCEPTION 'condition_batch_decimal_invalid' USING ERRCODE='23514'; END IF;
 IF digits='' THEN RETURN '0e0'; END IF;
 coefficient:=regexp_replace(digits,'0+$','');
 exponent:=exponent+length(digits)-length(coefficient);
 magnitude:=exponent+length(coefficient)-1;
 IF magnitude < -324 OR magnitude > 308 THEN
  RAISE EXCEPTION 'condition_batch_decimal_invalid' USING ERRCODE='23514'; END IF;
 exact_value:=(coefficient||'e'||exponent::text)::numeric;
 IF exact_value >= __OVERFLOW__::numeric OR exact_value*__INVERSE_HALF_MINIMUM__::numeric <= 1 THEN
  RAISE EXCEPTION 'condition_batch_decimal_invalid' USING ERRCODE='23514'; END IF;
 RETURN coefficient||'e'||exponent::text;
END $$;
CREATE FUNCTION public.sclib_discovery_condition_batch_axes_v1(a jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p jsonb; t jsonb; key text; pressures jsonb; temperatures jsonb;
 pm jsonb:='{}'::jsonb; tm jsonb:='{}'::jsonb; pc integer; tc integer; pu integer; tu integer;
 reasons jsonb:='[]'::jsonb; BEGIN
 IF NOT public.sclib_material_field_closed_v1(a,ARRAY['pressures','temperatures_k'])
  OR jsonb_typeof(a->'pressures') IS DISTINCT FROM 'array'
  OR jsonb_typeof(a->'temperatures_k') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'condition_batch_axes_invalid' USING ERRCODE='23514'; END IF;
 pc:=jsonb_array_length(a->'pressures'); tc:=jsonb_array_length(a->'temperatures_k');
 IF pc NOT BETWEEN 1 AND 8 OR tc NOT BETWEEN 1 AND 8 THEN
  RAISE EXCEPTION 'condition_batch_axis_bound' USING ERRCODE='23514'; END IF;
 FOR p IN SELECT value FROM jsonb_array_elements(a->'pressures') LOOP
  IF NOT public.sclib_material_field_closed_v1(p,ARRAY['kind','raw_gpa'])
   OR jsonb_typeof(p->'kind') IS DISTINCT FROM 'string'
   OR p->>'kind' NOT IN ('ambient','specified','unspecified') THEN
   RAISE EXCEPTION 'condition_batch_pressure_invalid' USING ERRCODE='23514'; END IF;
  IF p->>'kind'='specified' THEN
   key:='specified:'||public.sclib_discovery_condition_batch_decimal_v1(p->'raw_gpa');
  ELSE
   IF p->'raw_gpa' IS DISTINCT FROM 'null'::jsonb THEN
    RAISE EXCEPTION 'condition_batch_pressure_invalid' USING ERRCODE='23514'; END IF;
   key:=p->>'kind';
  END IF;
  IF NOT pm ? key THEN pm:=pm||jsonb_build_object(key,p); END IF;
 END LOOP;
 FOR t IN SELECT value FROM jsonb_array_elements(a->'temperatures_k') LOOP
  key:=CASE WHEN t='null'::jsonb THEN 'unknown'
   ELSE 'specified:'||public.sclib_discovery_condition_batch_decimal_v1(t) END;
  IF NOT tm ? key THEN tm:=tm||jsonb_build_object(key,t); END IF;
 END LOOP;
 SELECT jsonb_agg(jsonb_build_object('key',k,'raw',value) ORDER BY k COLLATE "C"),count(*) INTO pressures,pu FROM jsonb_each(pm) item(k,value);
 SELECT jsonb_agg(jsonb_build_object('key',k,'raw',value) ORDER BY k COLLATE "C"),count(*) INTO temperatures,tu FROM jsonb_each(tm) item(k,value);
 IF pu*tu>64 THEN RAISE EXCEPTION 'condition_batch_scenario_bound' USING ERRCODE='23514'; END IF;
 IF pu<>pc THEN reasons:=reasons||jsonb_build_array('pressure_aliases_collapsed'); END IF;
 IF tu<>tc THEN reasons:=reasons||jsonb_build_array('temperature_aliases_collapsed'); END IF;
 RETURN jsonb_build_object('pressures',pressures,'temperatures',temperatures,'estimate',jsonb_build_object(
  'raw_cartesian_count',pc*tc,'unique_cartesian_count',pu*tu,
  'pressure',jsonb_build_object('raw_count',pc,'unique_count',pu,'collapsed_count',pc-pu),
  'temperature',jsonb_build_object('raw_count',tc,'unique_count',tu,'collapsed_count',tc-tu),
  'collapsed_reason_codes',reasons,'max_scenarios',64));
END $$;
CREATE FUNCTION public.sclib_discovery_condition_batch_governance_v1(x jsonb) RETURNS void
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE m jsonb; record jsonb; field text; token text; cursor_id text; seen text[]; n integer; BEGIN
 m:=x->'base'->'material';
 seen:=ARRAY[m->>'id'];
 cursor_id:=m->>'parent_material_id';
 -- Intrinsic negative governance is enforced independently of HTTP policy.
 -- Every ancestor is checked with the same 32-edge bound; no formula/family
 -- heuristic can replace an actual parent FK or resolve a cycle.
 FOR n IN 0..32 LOOP
  token:=lower(trim(coalesce(m->>'status','')));
  IF token NOT IN ('','active','active_research')
   OR m->'needs_review'='true'::jsonb OR m->'disputed'='true'::jsonb OR m->'retracted'='true'::jsonb
   OR lower(ltrim(coalesce(m->>'review_reason',''))) LIKE 'provenance_quarantine%' THEN
   RAISE EXCEPTION 'condition_batch_material_governance_hold' USING ERRCODE='23514'; END IF;
  IF cursor_id IS NULL OR cursor_id='' THEN EXIT; END IF;
  IF n=32 OR cursor_id=ANY(seen) THEN
   RAISE EXCEPTION 'condition_batch_material_ancestry_hold' USING ERRCODE='23514'; END IF;
  seen:=array_append(seen,cursor_id);
  SELECT to_jsonb(item) INTO m FROM public.materials item WHERE id=cursor_id;
  IF m IS NULL THEN RAISE EXCEPTION 'condition_batch_material_ancestry_hold' USING ERRCODE='23514'; END IF;
  cursor_id:=m->>'parent_material_id';
 END LOOP;
 IF x->>'kind'='retained_result' THEN
  record:=x->'base'->'result';
  FOR field IN SELECT unnest(ARRAY['needs_review','disputed','retracted','corrected']) LOOP
   IF record->field='true'::jsonb OR (record->field IS NOT NULL AND record->field<>'null'::jsonb AND jsonb_typeof(record->field)<>'boolean') THEN
    RAISE EXCEPTION 'condition_batch_record_governance_hold' USING ERRCODE='23514'; END IF;
  END LOOP;
  IF lower(ltrim(coalesce(record->>'review_reason',''))) LIKE 'provenance_quarantine%'
   OR lower(trim(coalesce(record->>'provenance_status',''))) IN ('quarantined','quarantine') THEN
   RAISE EXCEPTION 'condition_batch_record_governance_hold' USING ERRCODE='23514'; END IF;
  FOR field IN SELECT unnest(ARRAY['status','review_status','source_status','validity_status','provenance_status','review_reason']) LOOP
   IF record->field IS NOT NULL AND record->field<>'null'::jsonb AND jsonb_typeof(record->field)<>'string' THEN
    RAISE EXCEPTION 'condition_batch_record_governance_hold' USING ERRCODE='23514'; END IF;
   IF field IN ('status','review_status','source_status','validity_status')
    AND lower(trim(coalesce(record->>field,''))) IN ('quarantined','provenance_quarantined','retracted','withdrawn','disputed','refuted',
     'corrected','pending','needs_review','under_review','unreviewed','excluded','rejected') THEN
    RAISE EXCEPTION 'condition_batch_record_governance_hold' USING ERRCODE='23514'; END IF;
  END LOOP;
 END IF;
END $$;
CREATE FUNCTION public.sclib_discovery_condition_batch_parent_v1(p jsonb,u uuid,g uuid,s bigint) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.discovery_design_revisions_v1%ROWTYPE; head_id uuid; expected text; x jsonb; BEGIN
 PERFORM public.sclib_discovery_condition_batch_lock_v1();
 IF s NOT BETWEEN 0 AND 9007199254740991 OR public.sclib_research_distribution_role_v1(u,g,'curator') IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM public.users WHERE id=u AND session_version=s) THEN
  RAISE EXCEPTION 'condition_batch_live_actor_required' USING ERRCODE='42501'; END IF;
 IF NOT public.sclib_material_field_closed_v1(p,ARRAY['design_id','revision_id','revision','record_sha256'])
  OR jsonb_typeof(p->'design_id') IS DISTINCT FROM 'string'
  OR jsonb_typeof(p->'revision_id') IS DISTINCT FROM 'string'
  OR (p->>'design_id')::uuid::text IS DISTINCT FROM p->>'design_id'
  OR (p->>'revision_id')::uuid::text IS DISTINCT FROM p->>'revision_id'
  OR jsonb_typeof(p->'revision') IS DISTINCT FROM 'number' OR p->>'revision' !~ '^[1-9][0-9]{0,3}$'
  OR jsonb_typeof(p->'record_sha256') IS DISTINCT FROM 'string' OR p->>'record_sha256' !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'condition_batch_parent_pin_required' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM public.discovery_design_revisions_v1 WHERE id=(p->>'revision_id')::uuid;
 SELECT id INTO head_id FROM public.discovery_design_revisions_v1 WHERE design_id=r.design_id ORDER BY revision DESC LIMIT 1;
 IF r.id IS NULL OR r.id IS DISTINCT FROM head_id OR r.actor_user_id IS DISTINCT FROM u OR r.operation='withdraw'
  OR p IS DISTINCT FROM jsonb_build_object('design_id',r.design_id::text,'revision_id',r.id::text,'revision',r.revision,'record_sha256',r.record_sha256)
  OR r.baseline->>'kind' NOT IN ('retained_result','native_property') THEN
  RAISE EXCEPTION 'condition_batch_current_parent_required' USING ERRCODE='23514'; END IF;
 expected:=public.sclib_discovery_design_context_v1(r.baseline);
 IF r.context_json IS DISTINCT FROM expected OR r.context_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(expected)
  OR r.projection IS DISTINCT FROM public.sclib_discovery_design_projection_v1(expected)
  OR r.projection_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(r.projection)) THEN
  RAISE EXCEPTION 'condition_batch_source_pin_changed' USING ERRCODE='23514'; END IF;
 x:=expected::jsonb;
 IF coalesce((x->'base'->'material'->>'needs_review')::boolean,false)
  OR coalesce((x->'base'->'material'->>'retracted')::boolean,false)
  OR coalesce((x->'base'->'material'->>'disputed')::boolean,false)
  OR lower(coalesce(x->'base'->'material'->>'status','')) IN ('retracted','disputed','corrected')
  OR x->'base'->'event'->>'validity_status' IN ('disputed','retracted','excluded')
  OR x->'base'->'event'->>'review_status'='rejected'
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(x->'sources') item WHERE item->'lifecycle'<>'null'::jsonb
   OR lower(coalesce(item->'row'->>'status',item->'row'->>'publication_status','')) IN ('retracted','withdrawn','corrected','disputed')) THEN
  RAISE EXCEPTION 'condition_batch_current_source_hold' USING ERRCODE='23514'; END IF;
 PERFORM public.sclib_discovery_condition_batch_governance_v1(x);
 RETURN to_jsonb(r);
END $$;
CREATE FUNCTION public.sclib_discovery_condition_batch_body_v1(r jsonb,a jsonb,u uuid,g uuid,s bigint) RETURNS text
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE axes jsonb; parent jsonb; pins jsonb; input_json text; p jsonb; t jsonb; b jsonb;
 candidate text; conditions jsonb; scenarios jsonb:='[]'::jsonb; budgets jsonb:='[]'::jsonb; body text; BEGIN
 axes:=public.sclib_discovery_condition_batch_axes_v1(a);
 parent:=jsonb_build_object('design_id',r->'design_id','revision_id',r->'id','revision',r->'revision','record_sha256',r->'record_sha256');
 pins:=jsonb_build_object('baseline',r->'baseline','context_sha256',r->'context_sha256','projection_sha256',r->'projection_sha256',
  'event_id',r->'projection'->'event_id','state_id',r->'projection'->'state_id','producer_run_id',r->'projection'->'producer_run_id');
 input_json:=public.sclib_scientific_import_canonical_v1(jsonb_build_object('version','discovery-condition-sweep/1.0.0','parent',parent,'source_pins',pins,'axes',a));
 FOR p IN SELECT value FROM jsonb_array_elements(axes->'pressures') LOOP
  FOR t IN SELECT value FROM jsonb_array_elements(axes->'temperatures') LOOP
   candidate:=public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(jsonb_build_object(
    'version','discovery-condition-sweep-candidate/1.0.0','parent_record_sha256',r->'record_sha256','pressure_identity',p->'key','temperature_identity',t->'key')));
   conditions:=jsonb_build_object('pressure',p->'raw','temperature_k',t->'raw');
   scenarios:=scenarios||jsonb_build_array(jsonb_build_object('candidate_id','condition-scenario:'||candidate,'candidate_sha256',candidate,
    'conditions',conditions,'proposal',jsonb_set(r->'design','{target_conditions}',conditions)));
  END LOOP;
 END LOOP;
 FOR b IN SELECT value FROM jsonb_array_elements(r->'design'->'next_action'->'budget') LOOP
  budgets:=budgets||jsonb_build_array(jsonb_build_object('resource',b->'resource','unit',b->'unit',
   'status',CASE WHEN b->>'status'='unknown' THEN 'unknown' ELSE 'not_aggregated' END,'total',NULL));
 END LOOP;
 body:=public.sclib_scientific_import_canonical_v1(jsonb_build_object('version','discovery-condition-sweep/1.0.0','scope','local_private_condition_sweep',
  'actor',jsonb_build_object('actor_user_id',u::text,'session_version',s,'curator_grant_id',g::text),
  'parent',parent,'source_pins',pins,'input_canonical_json',input_json,'input_sha256',public.sclib_source_property_hash_v1(input_json),
  'estimate',axes->'estimate','scenarios',scenarios,'budget_totals',budgets,'scientific_acceptance',false,'canonical_promotions',0,
  'ml_training_approved',false,'public_release',false,'calculation_executed',false,'database_changed',false,'batch_saved',false,'atomic_sites_generated',false));
 IF octet_length(body)>4194304 THEN RAISE EXCEPTION 'condition_batch_manifest_bound' USING ERRCODE='23514'; END IF;
 RETURN body;
END $$;
CREATE FUNCTION public.sclib_discovery_condition_batch_manifest_v1(p jsonb,a jsonb,u uuid,g uuid,s bigint) RETURNS text
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RETURN public.sclib_discovery_condition_batch_body_v1(public.sclib_discovery_condition_batch_parent_v1(p,u,g,s),a,u,g,s);
END $$;
CREATE FUNCTION public.sclib_discovery_condition_batch_immutable_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'condition batch history is append-only' USING ERRCODE='55000'; END $$;
CREATE FUNCTION public.sclib_discovery_condition_batch_insert_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE q jsonb; p jsonb; preview jsonb; body text; artifact text; manifest jsonb; candidate jsonb;
 batch_row public.discovery_condition_batches_v1%ROWTYPE; child_row public.discovery_design_revisions_v1%ROWTYPE;
 parent_row jsonb; expected text; BEGIN
 PERFORM public.sclib_discovery_condition_batch_lock_v1();
 IF NEW.actor_session_version NOT BETWEEN 0 AND 9007199254740991
  OR public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,'curator') IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM public.users WHERE id=NEW.actor_user_id AND session_version=NEW.actor_session_version) THEN
  RAISE EXCEPTION 'condition_batch_live_actor_required' USING ERRCODE='42501'; END IF;
 q:=NEW.request_json::jsonb; p:=q->'payload';
 IF NOT public.sclib_material_field_closed_v1(q,ARRAY['version','request_key','operation','payload'])
  OR q->>'version' IS DISTINCT FROM 'discovery-condition-batch-operation/1.0.0'
  OR jsonb_typeof(q->'request_key') IS DISTINCT FROM 'string' OR q->>'request_key' IS DISTINCT FROM NEW.request_key
  OR q->>'operation' IS DISTINCT FROM NEW.operation OR q->'payload' IS DISTINCT FROM NEW.payload
  OR NEW.request_json IS DISTINCT FROM public.sclib_scientific_import_canonical_v1(q)
  OR NEW.request_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.request_json)
  OR EXISTS(SELECT 1 FROM public.discovery_condition_batches_v1 WHERE actor_user_id=NEW.actor_user_id AND request_key=NEW.request_key)
  OR EXISTS(SELECT 1 FROM public.discovery_condition_child_links_v1 WHERE actor_user_id=NEW.actor_user_id AND request_key=NEW.request_key) THEN
  RAISE EXCEPTION 'condition_batch_exact_unique_request_required' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='discovery_condition_batches_v1' THEN
  IF NEW.operation IS DISTINCT FROM 'retain_batch'
   OR NOT public.sclib_material_field_closed_v1(p,ARRAY['parent','axes','expected_input_sha256','expected_manifest_sha256'])
   OR NEW.parent IS DISTINCT FROM p->'parent' THEN
   RAISE EXCEPTION 'condition_batch_retain_shape' USING ERRCODE='23514'; END IF;
  body:=public.sclib_discovery_condition_batch_manifest_v1(NEW.parent,p->'axes',NEW.actor_user_id,NEW.actor_grant_id,NEW.actor_session_version);
  manifest:=body::jsonb;
  expected:=public.sclib_source_property_hash_v1(body);
  artifact:=public.sclib_scientific_import_canonical_v1(manifest||jsonb_build_object('manifest_sha256',expected));
  IF NEW.manifest_json IS DISTINCT FROM artifact OR NEW.manifest_sha256 IS DISTINCT FROM expected
   OR p->'expected_manifest_sha256' IS DISTINCT FROM to_jsonb(expected)
   OR NEW.input_json IS DISTINCT FROM manifest->>'input_canonical_json'
   OR NEW.input_sha256 IS DISTINCT FROM manifest->>'input_sha256'
   OR p->'expected_input_sha256' IS DISTINCT FROM manifest->'input_sha256'
   OR NEW.source_pins IS DISTINCT FROM manifest->'source_pins'
   OR NEW.scenario_total IS DISTINCT FROM jsonb_array_length(manifest->'scenarios') THEN
   RAISE EXCEPTION 'condition_batch_exact_manifest_required' USING ERRCODE='23514'; END IF;
  preview:=jsonb_build_object('version','discovery-condition-batch/1.0.0','actor',jsonb_build_object(
   'actor_user_id',NEW.actor_user_id::text,'actor_grant_id',NEW.actor_grant_id::text,'actor_session_version',NEW.actor_session_version),
   'request_sha256',NEW.request_sha256,'receipt_id',NEW.id::text,'batch_id',NEW.id::text,'parent',NEW.parent,
   'input_sha256',NEW.input_sha256,'manifest_sha256',NEW.manifest_sha256,'scenario_total',NEW.scenario_total);
  expected:=public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(NEW)-ARRAY['created_at','record_sha256','manifest_json']));
 ELSE
  IF NEW.operation IS DISTINCT FROM 'propose_candidate_child'
   OR NOT public.sclib_material_field_closed_v1(p,ARRAY['batch','candidate_sha256'])
   OR NOT public.sclib_material_field_closed_v1(p->'batch',ARRAY['id','record_sha256','manifest_sha256'])
   OR p->'batch' IS DISTINCT FROM jsonb_build_object('id',NEW.batch_id::text,'record_sha256',NEW.batch_record_sha256,'manifest_sha256',NEW.manifest_sha256)
   OR p->'candidate_sha256' IS DISTINCT FROM to_jsonb(NEW.candidate_sha256) THEN
   RAISE EXCEPTION 'condition_batch_child_shape' USING ERRCODE='23514'; END IF;
  SELECT * INTO batch_row FROM public.discovery_condition_batches_v1 WHERE id=NEW.batch_id;
  IF batch_row.id IS NULL OR batch_row.actor_user_id IS DISTINCT FROM NEW.actor_user_id
   OR batch_row.record_sha256 IS DISTINCT FROM NEW.batch_record_sha256
   OR batch_row.manifest_sha256 IS DISTINCT FROM NEW.manifest_sha256 THEN
   RAISE EXCEPTION 'condition_batch_exact_owner_batch_required' USING ERRCODE='23514'; END IF;
  parent_row:=public.sclib_discovery_condition_batch_parent_v1(batch_row.parent,NEW.actor_user_id,NEW.actor_grant_id,NEW.actor_session_version);
  body:=public.sclib_discovery_condition_batch_body_v1(parent_row,batch_row.payload->'axes',batch_row.actor_user_id,batch_row.actor_grant_id,batch_row.actor_session_version);
  manifest:=body::jsonb;
  artifact:=public.sclib_scientific_import_canonical_v1(manifest||jsonb_build_object('manifest_sha256',public.sclib_source_property_hash_v1(body)));
  IF batch_row.manifest_json IS DISTINCT FROM artifact OR batch_row.manifest_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(body) THEN
   RAISE EXCEPTION 'condition_batch_historical_manifest_changed' USING ERRCODE='23514'; END IF;
  SELECT value INTO candidate FROM jsonb_array_elements(manifest->'scenarios') WHERE value->>'candidate_sha256'=NEW.candidate_sha256;
  SELECT * INTO child_row FROM public.discovery_design_revisions_v1 WHERE id=NEW.child_revision_id;
  IF candidate IS NULL OR child_row.id IS NULL OR child_row.actor_user_id IS DISTINCT FROM NEW.actor_user_id
   OR child_row.actor_grant_id IS DISTINCT FROM NEW.actor_grant_id OR child_row.actor_session_version IS DISTINCT FROM NEW.actor_session_version
   OR child_row.operation IS DISTINCT FROM 'propose' OR child_row.revision<>1
   OR child_row.design_id IS DISTINCT FROM NEW.child_design_id OR child_row.record_sha256 IS DISTINCT FROM NEW.child_record_sha256
   OR child_row.baseline IS DISTINCT FROM parent_row->'baseline' OR child_row.design IS DISTINCT FROM candidate->'proposal'
   OR child_row.parent IS DISTINCT FROM jsonb_build_object('design_id',batch_row.parent->'design_id','revision_id',batch_row.parent->'revision_id','record_sha256',batch_row.parent->'record_sha256')
   OR child_row.context_sha256 IS DISTINCT FROM batch_row.source_pins->>'context_sha256'
   OR child_row.projection_sha256 IS DISTINCT FROM batch_row.source_pins->>'projection_sha256'
   OR EXISTS(SELECT 1 FROM public.discovery_design_revisions_v1 WHERE design_id=child_row.design_id AND revision>1) THEN
   RAISE EXCEPTION 'condition_batch_exact_candidate_child_required' USING ERRCODE='23514'; END IF;
  preview:=jsonb_build_object('version','discovery-condition-batch/1.0.0','actor',jsonb_build_object(
   'actor_user_id',NEW.actor_user_id::text,'actor_grant_id',NEW.actor_grant_id::text,'actor_session_version',NEW.actor_session_version),
   'request_sha256',NEW.request_sha256,'receipt_id',NEW.id::text,'batch_id',NEW.batch_id::text,'batch_record_sha256',NEW.batch_record_sha256,
   'manifest_sha256',NEW.manifest_sha256,'candidate_sha256',NEW.candidate_sha256,
   'child',jsonb_build_object('design_id',NEW.child_design_id::text,'revision_id',NEW.child_revision_id::text,'record_sha256',NEW.child_record_sha256));
  expected:=public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(NEW)-ARRAY['created_at','record_sha256']));
 END IF;
 IF NEW.scientific_acceptance OR NEW.ml_training_approved OR NEW.public_release OR NEW.calculation_executed OR NEW.canonical_promotions<>0
  OR NEW.preview_json IS DISTINCT FROM public.sclib_scientific_import_canonical_v1(preview)
  OR NEW.preview_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.preview_json)
  OR NEW.record_sha256 IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'condition_batch_exact_no_authority_receipt_required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
""".replace("__OVERFLOW__", overflow).replace("__INVERSE_HALF_MINIMUM__", inverse_half_minimum)
    return [*re.split(r";\n(?=CREATE FUNCTION)", definitions.strip()), *[
        f"CREATE TRIGGER cb88_{suffix} {event} ON public.{name} {scope} EXECUTE FUNCTION public.{function}()"
        for name in TABLE_ORDER
        for suffix, event, scope, function in (
            ("insert", "BEFORE INSERT", "FOR EACH ROW", "sclib_discovery_condition_batch_insert_v1"),
            ("immutable", "BEFORE UPDATE OR DELETE", "FOR EACH ROW", "sclib_discovery_condition_batch_immutable_v1"),
            ("truncate", "BEFORE TRUNCATE", "FOR EACH STATEMENT", "sclib_discovery_condition_batch_immutable_v1"),
        )]]


def install_guards(metadata):
    """Install once after both FK-linked tables exist, including metadata QA."""
    for statement in guard_statements():
        sa.event.listen(metadata.tables[TABLE_ORDER[-1]], "after_create",
                        sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))


def register(metadata):
    def uid(name, target=None):
        return sa.Column(name, UUID(as_uuid=True),
                         *([sa.ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")] if target else []),
                         nullable=False)

    def common(prefix, operation):
        return [uid("id"), uid("actor_user_id", "users.id"), uid("actor_grant_id", "research_role_grants.id"),
            sa.Column("actor_session_version", sa.BigInteger, nullable=False), sa.Column("operation", sa.String(30), nullable=False),
            sa.Column("request_key", sa.String(160), nullable=False), sa.Column("request_json", sa.Text, nullable=False),
            sa.Column("payload", JSONB, nullable=False), sa.Column("request_sha256", sa.String(64), nullable=False),
            sa.Column("preview_json", sa.Text, nullable=False), sa.Column("preview_sha256", sa.String(64), nullable=False),
            *[sa.Column(key, sa.Boolean, nullable=False) for key in ("scientific_acceptance", "ml_training_approved", "public_release", "calculation_executed")],
            sa.Column("canonical_promotions", sa.Integer, nullable=False), sa.Column("record_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
            sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("actor_user_id", "request_key", name=f"uq_{prefix}_request"),
            sa.CheckConstraint(f"actor_session_version BETWEEN 0 AND 9007199254740991 AND isfinite(created_at) AND operation='{operation}'", name=f"ck_{prefix}_identity"),
            sa.CheckConstraint("NOT scientific_acceptance AND NOT ml_training_approved AND NOT public_release AND NOT calculation_executed AND canonical_promotions=0", name=f"ck_{prefix}_no_authority"),
            sa.CheckConstraint("request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$' AND octet_length(request_json) BETWEEN 2 AND 16384 AND octet_length(preview_json) BETWEEN 2 AND 4096", name=f"ck_{prefix}_bounds"),
            *[sa.CheckConstraint(f"{key} ~ '^[a-f0-9]{{64}}$'", name=f"ck_{prefix}_{key}") for key in ("request_sha256", "preview_sha256", "record_sha256")]]

    batch = sa.Table(TABLE_ORDER[0], metadata, *common("cb88", "retain_batch"),
        sa.Column("parent", JSONB, nullable=False), sa.Column("source_pins", JSONB, nullable=False),
        sa.Column("input_json", sa.Text, nullable=False), sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_json", sa.Text, nullable=False), sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("scenario_total", sa.Integer, nullable=False),
        sa.Index("idx_cb88_owner", "actor_user_id", "created_at", "id"),
        sa.CheckConstraint("scenario_total BETWEEN 1 AND 64 AND octet_length(input_json) BETWEEN 2 AND 16384 AND octet_length(manifest_json) BETWEEN 2 AND 4194432", name="ck_cb88_manifest_bounds"),
        *[sa.CheckConstraint(f"{key} ~ '^[a-f0-9]{{64}}$'", name=f"ck_cb88_{key}") for key in ("input_sha256", "manifest_sha256")])
    link = sa.Table(TABLE_ORDER[1], metadata, *common("cl88", "propose_candidate_child"),
        uid("batch_id", TABLE_ORDER[0]+".id"), sa.Column("batch_record_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False), sa.Column("candidate_sha256", sa.String(64), nullable=False),
        uid("child_revision_id", "discovery_design_revisions_v1.id"), uid("child_design_id"),
        sa.Column("child_record_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("batch_id", "candidate_sha256", name="uq_cl88_candidate"),
        sa.UniqueConstraint("child_revision_id", name="uq_cl88_child"),
        sa.Index("idx_cl88_owner", "actor_user_id", "created_at", "id"),
        *[sa.CheckConstraint(f"{key} ~ '^[a-f0-9]{{64}}$'", name=f"ck_cl88_{key}") for key in ("batch_record_sha256", "manifest_sha256", "candidate_sha256", "child_record_sha256")])
    batch.add_is_dependent_on(metadata.tables["discovery_design_revisions_v1"])
    link.add_is_dependent_on(batch)
    install_guards(metadata)
    return {TABLE_ORDER[0]: batch, TABLE_ORDER[1]: link}
