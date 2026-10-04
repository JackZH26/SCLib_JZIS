"""Independent finite SQL admission and two immutable metadata review tables."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = ("material_field_review_requests_v1", "material_field_review_decisions_v1")
FUNCTION_SIGNATURES = (
    ("sclib_material_field_review_json_v1", "jsonb,integer"),
    ("sclib_material_field_review_governance_v1", "jsonb"),
    ("sclib_material_field_review_raw_v1", "jsonb,text"),
    ("sclib_material_field_review_source_v1", "text"),
    ("sclib_material_field_review_admission_v1", "text,integer"),
    ("sclib_material_field_review_float_v1", "jsonb"),
    ("sclib_material_field_review_authority_v1", "uuid,uuid,integer,text"),
    ("sclib_material_field_review_expression_v1", "uuid"),
    ("sclib_material_field_review_subject_v1", "jsonb"),
    ("sclib_material_field_review_insert_v1", ""),
    ("sclib_material_field_review_immutable_v1", ""),
    ("sclib_material_field_review_complete_v1", ""),
)


def guard_statements():
    # These literals define the new finite policy. They are tested against the
    # frozen Python policy; they do not change its parser or source contract.
    sql = r"""
CREATE FUNCTION public.sclib_material_field_review_json_v1(v jsonb,d integer DEFAULT 0) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE z jsonb; k text; n numeric; BEGIN
 IF v IS NULL OR d>16 OR octet_length(v::text)>131072 THEN RETURN false; END IF;
 IF jsonb_typeof(v)='number' THEN
  IF v::text !~ '^(0|[1-9][0-9]{0,4})(\.[0-9]{0,5}[1-9]|\.0)?$' THEN RETURN false; END IF;
  n:=v::text::numeric; RETURN n=0 OR n>=0.0001;
 ELSIF jsonb_typeof(v)='string' THEN
  RETURN octet_length(v#>>'{}')=length(v#>>'{}') AND (v#>>'{}') !~ '[[:cntrl:]]' AND length(v#>>'{}')<=5000;
 ELSIF jsonb_typeof(v)='array' THEN
  IF jsonb_array_length(v)>1000 THEN RETURN false; END IF;
  FOR z IN SELECT value FROM jsonb_array_elements(v) LOOP
   IF NOT public.sclib_material_field_review_json_v1(z,d+1) THEN RETURN false; END IF;
  END LOOP;
 ELSIF jsonb_typeof(v)='object' THEN
  IF (SELECT count(*) FROM jsonb_object_keys(v))>1000 THEN RETURN false; END IF;
  FOR k,z IN SELECT * FROM jsonb_each(v) LOOP
   IF octet_length(k)<>length(k) OR k ~ '[[:cntrl:]]' OR NOT public.sclib_material_field_review_json_v1(z,d+1) THEN RETURN false; END IF;
  END LOOP;
 END IF;
 RETURN true;
END $$;
CREATE FUNCTION public.sclib_material_field_review_governance_v1(v jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE k text; x jsonb; BEGIN
 FOR k IN SELECT unnest(ARRAY['needs_review','retracted','disputed','corrected']) LOOP
  x:=v->k; IF x IS NOT NULL AND x<>'null'::jsonb AND x<>'false'::jsonb THEN RETURN false; END IF;
 END LOOP;
 FOR k IN SELECT unnest(ARRAY['status','review_status','source_status','validity_status','provenance_status']) LOOP
  x:=v->k;
  IF x IS NOT NULL AND x<>'null'::jsonb AND (jsonb_typeof(x)<>'string' OR length(x#>>'{}')>200
    OR lower(trim(x#>>'{}')) NOT IN ('','active','active_research','published','resolved','valid','approved')) THEN RETURN false; END IF;
 END LOOP;
 x:=v->'review_reason';
 RETURN x IS NULL OR x='null'::jsonb OR (jsonb_typeof(x)='string' AND length(x#>>'{}')<=200
  AND lower(ltrim(x#>>'{}')) NOT LIKE 'provenance_quarantine%');
END $$;
CREATE FUNCTION public.sclib_material_field_review_raw_v1(r jsonb,f text) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE k text; v jsonb; n numeric; tc numeric; p numeric; fam text; threshold numeric; units jsonb;
 raw jsonb; allowed text[]; BEGIN
 IF jsonb_typeof(r) IS DISTINCT FROM 'object' OR NOT public.sclib_material_field_review_json_v1(r)
  OR NOT public.sclib_material_field_review_governance_v1(r) THEN RETURN false; END IF;
 raw:=r-ARRAY['result_classification','pressure_semantics','property_evidence','anomaly_review','visibility','structure_evidence','ingestion_capture','temporal_provenance'];
 units:='{"tc_kelvin":"K","pressure_gpa":"GPa","hc2_tesla":"T","lattice_a":"angstrom","lattice_b":"angstrom","lattice_c":"angstrom","lattice_alpha":"degree","lattice_beta":"degree","lattice_gamma":"degree","t_afm_k":"K"}'::jsonb;
 allowed:=ARRAY['paper_id','formula','formula_raw','family','material_family','year','tc_type','tc_definition','tc_regime',
 'tc_criterion','criterion','transition_criterion','measurement','method','measurement_method','measurement_technique','experimental_method',
 'pressure_condition','pressure_conditions','pressure_state','tc_conditions','ambient_sc','knowledge_origin','result_origin','source_role',
 'confidence','paper_type','evidence_type','sample_form','space_group','crystal_structure','doping_type','doping_level','hc2_conditions',
 'credibility_tier','is_unconventional','synthetic','status','review_status','source_status','validity_status','provenance_status',
 'review_reason','needs_review','retracted','disputed','corrected'];
 FOR k,v IN SELECT * FROM jsonb_each(raw) LOOP
  IF units ? k THEN
   IF v='null'::jsonb THEN CONTINUE; END IF;
   IF jsonb_typeof(v)<>'number' THEN RETURN false; END IF;
   n:=v::text::numeric; IF n<0 OR n>99999 THEN RETURN false; END IF;
  ELSIF right(k,5)='_unit' AND units ? left(k,length(k)-5) THEN
   IF v<>'null'::jsonb AND (jsonb_typeof(v)<>'string' OR v#>>'{}'<>units->>left(k,length(k)-5)) THEN RETURN false; END IF;
  ELSIF NOT k=ANY(allowed) THEN RETURN false;
  ELSIF k IN ('confidence','doping_level') THEN
   IF v<>'null'::jsonb AND (jsonb_typeof(v)<>'number' OR v::text::numeric>1) THEN RETURN false; END IF;
  ELSIF k IN ('ambient_sc','is_unconventional','synthetic','needs_review','retracted','disputed','corrected') THEN
   IF v<>'null'::jsonb AND jsonb_typeof(v)<>'boolean' THEN RETURN false; END IF;
  ELSIF k='year' THEN
   IF v<>'null'::jsonb AND (jsonb_typeof(v) NOT IN ('number','string') OR v#>>'{}' !~ '^[0-9]{4}$'
    OR (v#>>'{}')::integer NOT BETWEEN 1900 AND extract(year FROM current_timestamp AT TIME ZONE 'UTC')::integer+1) THEN RETURN false; END IF;
  ELSIF v<>'null'::jsonb AND (jsonb_typeof(v)<>'string' OR length(v#>>'{}')>1000) THEN RETURN false; END IF;
 END LOOP;
 IF jsonb_typeof(raw->'tc_kelvin') IS DISTINCT FROM 'number' THEN RETURN false; END IF;
 tc:=(raw->>'tc_kelvin')::numeric; IF tc<=0 OR tc>152 THEN RETURN false; END IF;
 fam:=CASE WHEN length(raw->>'family')<=80 AND length(trim(raw->>'family'))>=1 THEN trim(raw->>'family')
  WHEN length(raw->>'material_family')<=80 AND length(trim(raw->>'material_family'))>=1 THEN trim(raw->>'material_family') ELSE f END;
 threshold:=('{"cuprate":180.0,"iron_based":110.0,"nickelate":110.0,"hydride":270.0,"mgb2":50.0,"fulleride":50.0,"bismuthate":45.0,"conventional":45.0,"chalcogenide":40.0,"elemental":40.0,"borocarbide":30.0,"bis2_layered":30.0,"heavy_fermion":30.0,"organic":25.0,"kagome":15.0,"ruthenate":10.0}'::jsonb->>fam)::numeric;
 IF tc>threshold THEN RETURN false; END IF;
 IF raw->'pressure_gpa' IS NOT NULL AND raw->'pressure_gpa'<>'null'::jsonb THEN
  p:=(raw->>'pressure_gpa')::numeric;
  IF p<=0 OR p>500 OR fam='hydride' AND tc>100 AND p<50 THEN RETURN false; END IF;
 END IF;
 -- Original state/condition assertions need the scientific pressure parser.
 FOR k IN SELECT unnest(ARRAY['pressure_state','pressure_condition','pressure_conditions','tc_conditions']) LOOP
  IF raw->k IS NOT NULL AND raw->k<>'null'::jsonb THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;
CREATE FUNCTION public.sclib_material_field_review_source_v1(p text) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w record; s public.papers%ROWTYPE; ev public.source_lifecycle_events%ROWTYPE; BEGIN
 SELECT * INTO s FROM public.papers WHERE id=p;
 SELECT * INTO ev FROM public.source_lifecycle_events WHERE paper_id=p ORDER BY revision DESC LIMIT 1;
 IF ev.id IS NOT NULL AND (ev.record_sha256 IS DISTINCT FROM public.sclib_source_lifecycle_record_hash_v1(to_jsonb(ev))
  OR ev.snapshot_sha256 IS DISTINCT FROM public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(s))) THEN
  RAISE EXCEPTION 'field_review_lifecycle_integrity' USING ERRCODE='23514'; END IF;
 FOR w IN SELECT x.* FROM public.paper_work_map m LEFT JOIN public.works x ON x.id=m.work_id
  WHERE m.paper_id=p AND m.review_status='accepted' LOOP
  SELECT * INTO ev FROM public.source_lifecycle_events WHERE work_id=w.id ORDER BY revision DESC LIMIT 1;
  IF ev.id IS NOT NULL AND (ev.record_sha256 IS DISTINCT FROM public.sclib_source_lifecycle_record_hash_v1(to_jsonb(ev))
   OR ev.snapshot_sha256 IS DISTINCT FROM public.sclib_source_lifecycle_snapshot_hash_v1('work',to_jsonb(w))) THEN
   RAISE EXCEPTION 'field_review_lifecycle_integrity' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF s.id IS NULL OR lower(trim(s.status)) NOT IN ('active','published') OR s.status IS NULL
  OR EXISTS(SELECT 1 FROM public.source_lifecycle_events WHERE paper_id=p) THEN RETURN false; END IF;
 FOR w IN SELECT x.* FROM public.paper_work_map m LEFT JOIN public.works x ON x.id=m.work_id
  WHERE m.paper_id=p AND m.review_status='accepted' LOOP
  IF w.id IS NULL OR w.publication_status IS NULL OR lower(trim(w.publication_status)) NOT IN ('active','published')
   OR EXISTS(SELECT 1 FROM public.source_lifecycle_events WHERE work_id=w.id) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;
CREATE FUNCTION public.sclib_material_field_review_admission_v1(mid text,idx integer) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE m public.materials%ROWTYPE; r jsonb; z jsonb; fam text; ok boolean:=true; all_ok boolean:=true;
 negative boolean:=false; context jsonb; pid text; rawsha text; rid text; n integer; BEGIN
 SELECT * INTO m FROM public.materials WHERE id=mid;
 IF m.id IS NULL OR jsonb_typeof(m.records) IS DISTINCT FROM 'array' OR jsonb_array_length(m.records) NOT BETWEEN 1 AND 5000
  OR octet_length(m.records::text)>4194304 OR idx<0 OR idx>=jsonb_array_length(m.records) THEN
  RETURN jsonb_build_object('eligible',false,'reason','retained_record_unavailable'); END IF;
 r:=m.records->idx; context:=COALESCE(m.anomaly_context,'{}'::jsonb);
 IF jsonb_typeof(context)<>'object' OR context-'family'-'compound_thresholds'-'selection_policy'<>'{}'::jsonb
  OR context->'compound_thresholds' IS NOT NULL AND context->'compound_thresholds'<>'[]'::jsonb
  OR m.parent_material_id IS NOT NULL OR NOT public.sclib_material_field_review_governance_v1(to_jsonb(m))
  OR m.status IS NOT NULL AND lower(trim(m.status)) NOT IN ('','active','active_research') THEN ok:=false; END IF;
 fam:=COALESCE(NULLIF(m.family,''),context->>'family');
 IF fam IS NOT NULL AND (length(fam)>80 OR jsonb_typeof(context->'family') NOT IN ('string','null')) THEN ok:=false; END IF;
 fam:=trim(fam);
 n:=0;
 FOR z IN SELECT value FROM jsonb_array_elements(m.records) LOOP
  pid:=z->>'paper_id';
  IF jsonb_typeof(z) IS DISTINCT FROM 'object' OR jsonb_typeof(z->'paper_id') IS DISTINCT FROM 'string'
   OR length(pid) NOT BETWEEN 1 AND 100 OR pid<>trim(pid) OR octet_length(pid)<>length(pid) OR pid ~ '[[:cntrl:]]'
   OR NOT public.sclib_material_field_review_governance_v1(z)
   OR NOT public.sclib_material_field_review_raw_v1(z,fam) THEN all_ok:=false; END IF;
  IF NOT public.sclib_material_field_review_source_v1(pid) THEN
   all_ok:=false;
   IF EXISTS(SELECT 1 FROM public.papers WHERE id=pid AND lower(trim(status)) IN ('retracted','withdrawn','corrected','disputed'))
    OR EXISTS(SELECT 1 FROM public.source_lifecycle_events WHERE paper_id=pid)
    OR EXISTS(SELECT 1 FROM public.paper_work_map x JOIN public.source_lifecycle_events e ON e.work_id=x.work_id WHERE x.paper_id=pid AND x.review_status='accepted')
    THEN negative:=true; END IF;
  END IF;
  n:=n+1;
 END LOOP;
 -- Every raw record must be a supported no-finding shape. Source-only holds
 -- may partition; unsupported raw governance/anomaly input never disappears.
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(m.records) AS record_item(value) WHERE NOT public.sclib_material_field_review_raw_v1(record_item.value,fam)
   OR NOT public.sclib_material_field_review_governance_v1(record_item.value)) THEN ok:=false; END IF;
 pid:=r->>'paper_id';
 ok:=ok AND jsonb_typeof(r->'paper_id')='string' AND length(pid) BETWEEN 1 AND 100 AND pid=trim(pid)
  AND octet_length(pid)=length(pid) AND pid !~ '[[:cntrl:]]'
  AND public.sclib_material_field_review_source_v1(pid) AND (all_ok OR negative)
  AND public.sclib_material_field_review_raw_v1(r,fam);
 IF public.sclib_material_field_review_json_v1(r) THEN
  rawsha:=public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(r));
  rid:='legacy-result:'||public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(jsonb_build_array(mid,
    r-ARRAY['result_classification','pressure_semantics','property_evidence','anomaly_review','visibility','structure_evidence','ingestion_capture','temporal_provenance'])));
 END IF;
 RETURN jsonb_build_object('eligible',COALESCE(ok,false),'reason',CASE WHEN ok THEN NULL ELSE 'finite_retained_eligibility_hold' END,
  'visibility_version',CASE WHEN all_ok THEN 'material-visibility/1.0.0' ELSE 'material-visibility/2.0.0' END,
  'paper_id',pid,'legacy_result_id',rid,'retained_record_sha256',rawsha);
END $$;
CREATE FUNCTION public.sclib_material_field_review_float_v1(q jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE k text; n numeric; BEGIN
 FOR k IN SELECT unnest(ARRAY['value','uncertainty']) LOOP
  IF jsonb_typeof(q->k)='number' THEN
   n:=(q->>k)::numeric;
   IF n=trunc(n) THEN q:=jsonb_set(q,ARRAY[k],(trunc(n)::text||'.0')::jsonb); END IF;
  END IF;
 END LOOP;
 RETURN q;
END $$;
CREATE FUNCTION public.sclib_material_field_review_authority_v1(actor uuid,grant_id uuid,actor_session integer,role_name text) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 -- Read-only counterpart of the frozen write role guard. Commit still uses
 -- the existing locked role guard; GET uses the fresh epoch/session fence.
 RETURN EXISTS(SELECT 1 FROM public.users u JOIN public.research_role_grants g ON g.user_id=u.id
  WHERE u.id=$1 AND u.is_active AND u.email_verified AND u.session_version=$3
   AND g.id=$2 AND g.role=$4
   AND g.record_sha256=public.sclib_research_distribution_record_hash_v1(to_jsonb(g)-'id')
   AND NOT EXISTS(SELECT 1 FROM public.research_role_revocations r WHERE r.grant_id=g.id));
END $$;
CREATE FUNCTION public.sclib_material_field_review_expression_v1(eid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE x public.source_expression_revisions_v2%ROWTYPE; c public.source_expression_captures_v2%ROWTYPE;
 i public.source_expression_imports_v2%ROWTYPE; projection jsonb; entry jsonb; current boolean; j integer; BEGIN
 SELECT * INTO x FROM public.source_expression_revisions_v2 WHERE id=eid;
 SELECT * INTO c FROM public.source_expression_captures_v2 WHERE id=x.capture_id;
 SELECT * INTO i FROM public.source_expression_imports_v2 WHERE id=x.import_receipt_id;
 IF x.id IS NULL OR c.id IS NULL OR i.id IS NULL
  OR x.record_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(x)-ARRAY['created_at','record_sha256']))
  OR c.record_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(c)-ARRAY['created_at','record_sha256']))
  OR i.record_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(i)-ARRAY['created_at','record_sha256','assembly_xid']))
  OR x.import_receipt_sha256 IS DISTINCT FROM i.record_sha256 OR i.capture_id IS DISTINCT FROM c.id
  OR public.sclib_source_property_hash_v1(c.source_text) IS DISTINCT FROM c.source_content_sha256
  OR public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(c.source_metadata)) IS DISTINCT FROM c.metadata_sha256
  OR public.sclib_source_property_hash_v1(i.package_json) IS DISTINCT FROM i.package_sha256 THEN
  RAISE EXCEPTION 'field_review_source_integrity' USING ERRCODE='23514'; END IF;
 entry:=i.package_json::jsonb->'expressions'->x.entry_index;
 projection:=public.sclib_source_expression_project_v2(c.source_metadata,c.source_text,entry);
 -- The frozen compiler returns Python floats for parsed quantities. Restore
 -- their integral .0 representation without changing any value or grammar.
 projection:=jsonb_set(projection,ARRAY['value'],public.sclib_material_field_review_float_v1(projection->'value'));
 FOR j IN 0..jsonb_array_length(projection->'conditions')-1 LOOP
  projection:=jsonb_set(projection,ARRAY['conditions',j::text,'value'],
    public.sclib_material_field_review_float_v1(projection->'conditions'->j->'value'));
 END LOOP;
 IF public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(entry)) IS DISTINCT FROM x.entry_sha256
  OR public.sclib_scientific_import_canonical_v1(projection) IS DISTINCT FROM x.projection_json
  OR public.sclib_source_property_hash_v1(x.projection_json) IS DISTINCT FROM x.projection_sha256 THEN
  RAISE EXCEPTION 'field_review_projection_integrity' USING ERRCODE='23514'; END IF;
 current:=NOT EXISTS(SELECT 1 FROM public.source_expression_revisions_v2 newer WHERE newer.predecessor_id=x.id)
  AND c.id=(SELECT id FROM public.source_expression_captures_v2 WHERE source_id=c.source_id ORDER BY created_at DESC,id DESC LIMIT 1)
  AND c.source_metadata->>'currentness'='declared_current' AND c.source_metadata->>'rights_status'='declared_private_inspection'
  AND public.sclib_material_field_review_authority_v1(c.actor_user_id,c.actor_grant_id,c.actor_session_version,'curator')
  AND public.sclib_material_field_review_authority_v1(i.actor_user_id,i.actor_grant_id,i.actor_session_version,'curator')
  AND public.sclib_material_field_review_authority_v1(x.actor_user_id,x.actor_grant_id,x.actor_session_version,'curator');
 RETURN jsonb_build_object('projection',projection,'entry',entry,'current',current,'capture_id',c.id,
  'importer_user_id',i.actor_user_id,'capture_user_id',c.actor_user_id,'record_sha256',x.record_sha256,
  'projection_sha256',x.projection_sha256,'import_receipt_sha256',i.record_sha256);
END $$;
CREATE FUNCTION public.sclib_material_field_review_subject_v1(p jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t public.material_field_targets_v1%ROWTYPE; a public.material_field_associations_v1%ROWTYPE;
 context_text text; original jsonb; r jsonb; admission jsonb; e jsonb; te jsonb; projection jsonb; parent jsonb;
 tuple_body jsonb; entry jsonb; part jsonb; candidate jsonb; inventory jsonb:='{}'; reasons text[]:=ARRAY[]::text[];
 field text; cf text; k text; method text; source_method text; coarse text; value_text text; origin text; method_count integer; missing boolean:=true; BEGIN
 IF public.sclib_material_field_closed_v1(p,ARRAY['target_id','target_sha256','field_id','association','expression','tc_expression','source_identity','component']) IS DISTINCT FROM true
  OR p->>'field_id' NOT IN ('tc_criterion','measurement_method','pressure_gpa') THEN
  RAISE EXCEPTION 'field_review_subject_shape' USING ERRCODE='23514'; END IF;
 IF jsonb_typeof(p->'target_id') IS DISTINCT FROM 'string' OR (p->>'target_id')::uuid::text IS DISTINCT FROM p->>'target_id'
  OR jsonb_typeof(p->'target_sha256') IS DISTINCT FROM 'string' OR p->>'target_sha256' !~ '^[a-f0-9]{64}$'
  OR public.sclib_material_field_closed_v1(p->'source_identity',ARRAY['paper_id','work_id']) IS DISTINCT FROM true
  OR jsonb_typeof(p->'source_identity'->'paper_id') IS DISTINCT FROM 'string'
  OR length(p->'source_identity'->>'paper_id') NOT BETWEEN 1 AND 100
  OR p->'source_identity'->>'paper_id' IS DISTINCT FROM trim(p->'source_identity'->>'paper_id')
  OR octet_length(p->'source_identity'->>'paper_id')<>length(p->'source_identity'->>'paper_id')
  OR p->'source_identity'->>'paper_id' ~ '[[:cntrl:]]'
  OR public.sclib_material_field_closed_v1(p->'component',ARRAY['kind','index','field_id','role']) IS DISTINCT FROM true
  OR jsonb_typeof(p->'component'->'kind') IS DISTINCT FROM 'string' OR p->'component'->>'kind' NOT IN ('condition','value') THEN
  RAISE EXCEPTION 'field_review_selector_shape' USING ERRCODE='23514'; END IF;
 IF p->'component'->>'kind'='condition' AND p->'tc_expression'<>'null'::jsonb
  OR p->'component'->>'kind'='value' AND (p->>'field_id'<>'measurement_method' OR p->'tc_expression'='null'::jsonb) THEN
  RAISE EXCEPTION 'field_review_tc_companion_scope' USING ERRCODE='23514'; END IF;
 FOR k IN SELECT unnest(ARRAY['expression','tc_expression','association']) LOOP
  IF k<>'expression' AND p->k='null'::jsonb THEN CONTINUE; END IF;
  IF public.sclib_material_field_closed_v1(p->k,CASE WHEN k='association' THEN ARRAY['id','record_sha256'] ELSE ARRAY['id','record_sha256','projection_sha256'] END) IS DISTINCT FROM true
   OR jsonb_typeof(p->k->'id') IS DISTINCT FROM 'string' OR (p->k->>'id')::uuid::text IS DISTINCT FROM p->k->>'id'
   OR jsonb_typeof(p->k->'record_sha256') IS DISTINCT FROM 'string' OR p->k->>'record_sha256' !~ '^[a-f0-9]{64}$'
   OR k<>'association' AND (jsonb_typeof(p->k->'projection_sha256') IS DISTINCT FROM 'string' OR p->k->>'projection_sha256' !~ '^[a-f0-9]{64}$') THEN
   RAISE EXCEPTION 'field_review_exact_selector_pin' USING ERRCODE='23514'; END IF;
 END LOOP;
 SELECT * INTO t FROM public.material_field_targets_v1 WHERE id=(p->>'target_id')::uuid;
 IF t.id IS NULL OR t.record_sha256 IS DISTINCT FROM p->>'target_sha256'
  OR t.record_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(t)-ARRAY['created_at','record_sha256']))
  OR t.payload->'target'->>'kind'<>'retained_result' OR t.field_id NOT IN ('tc_kelvin',p->>'field_id') THEN
  RAISE EXCEPTION 'field_review_target_pin' USING ERRCODE='23514'; END IF;
 original:=t.context_json::jsonb; r:=original->'result'; field:=p->>'field_id';
 IF NOT public.sclib_material_field_review_authority_v1(t.actor_user_id,t.actor_grant_id,t.actor_session_version,'curator') THEN
  reasons:=array_append(reasons,'target_authority_held'); END IF;
 BEGIN context_text:=public.sclib_material_field_context_v1(t.payload->'target');
 EXCEPTION WHEN check_violation THEN context_text:=NULL; END;
 IF context_text IS DISTINCT FROM t.context_json THEN reasons:=array_append(reasons,'target_changed'); END IF;
 admission:=public.sclib_material_field_review_admission_v1(original->>'material_id',(original->>'record_index')::integer);
 IF admission->'eligible' IS DISTINCT FROM 'true'::jsonb THEN reasons:=array_append(reasons,'finite_retained_eligibility_hold'); END IF;
 IF p->'source_identity'->>'paper_id' IS DISTINCT FROM r->>'paper_id' THEN reasons:=array_append(reasons,'source_identity_mismatch'); END IF;
 IF p->'source_identity'->>'work_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.paper_work_map
  WHERE paper_id=r->>'paper_id' AND work_id=(p->'source_identity'->>'work_id')::uuid AND review_status='accepted') THEN
  reasons:=array_append(reasons,'source_identity_mismatch'); END IF;
 e:=public.sclib_material_field_review_expression_v1((p->'expression'->>'id')::uuid);
 IF e->>'record_sha256' IS DISTINCT FROM p->'expression'->>'record_sha256'
  OR e->>'projection_sha256' IS DISTINCT FROM p->'expression'->>'projection_sha256' THEN
  RAISE EXCEPTION 'field_review_expression_pin' USING ERRCODE='23514'; END IF;
 projection:=e->'projection'; parent:=projection; entry:=e->'entry';
 IF e->'current' IS DISTINCT FROM 'true'::jsonb THEN reasons:=array_append(reasons,'source_expression_held'); END IF;
 IF p->'association'<>'null'::jsonb THEN
  SELECT * INTO a FROM public.material_field_associations_v1 WHERE id=(p->'association'->>'id')::uuid;
  IF a.id IS NULL OR a.record_sha256 IS DISTINCT FROM p->'association'->>'record_sha256' OR a.target_id IS DISTINCT FROM t.id
   OR a.expression_revision_id IS DISTINCT FROM (p->'expression'->>'id')::uuid THEN
   RAISE EXCEPTION 'field_review_association_pin' USING ERRCODE='23514'; END IF;
  IF a.payload->>'action'<>'propose' OR a.payload->'source_identity' IS DISTINCT FROM p->'source_identity'
   OR NOT public.sclib_material_field_review_authority_v1(a.actor_user_id,a.actor_grant_id,a.actor_session_version,'curator')
   OR EXISTS(SELECT 1 FROM public.material_field_associations_v1 successor WHERE successor.predecessor_id=a.id) THEN
   reasons:=array_append(reasons,'association_held'); END IF;
 END IF;
 cf:=CASE field WHEN 'tc_criterion' THEN 'criterion_statement' WHEN 'measurement_method' THEN 'method_statement' ELSE 'pressure_gpa' END;
 IF p->'component'->>'kind'='condition' THEN
  IF jsonb_typeof(p->'component'->'index') IS DISTINCT FROM 'number' OR p->'component'->>'index' !~ '^[0-7]$'
   OR p->'component'->>'role' IS DISTINCT FROM 'reported_result_condition'
   OR p->'component'->>'field_id' IS DISTINCT FROM cf THEN RAISE EXCEPTION 'field_review_component_shape' USING ERRCODE='23514'; END IF;
  part:=projection->'conditions'->(p->'component'->>'index')::integer;
  entry:=entry->'conditions'->(p->'component'->>'index')::integer;
  IF part IS NULL OR part->>'field_id' IS DISTINCT FROM cf OR part->>'role'<>'reported_result_condition' THEN
   RAISE EXCEPTION 'field_review_component_scope' USING ERRCODE='23514'; END IF;
 ELSE
  IF field<>'measurement_method' OR p->'component'->'index'<>'null'::jsonb OR p->'component'->'role'<>'null'::jsonb
   OR projection->>'field_id'<>'method_statement' OR p->'component'->>'field_id'<>'method_statement' THEN
   RAISE EXCEPTION 'field_review_component_shape' USING ERRCODE='23514'; END IF;
  part:=jsonb_build_object('value',projection->'value');
 END IF;
 IF p->'tc_expression'<>'null'::jsonb THEN
  te:=public.sclib_material_field_review_expression_v1((p->'tc_expression'->>'id')::uuid);
  IF te->>'record_sha256' IS DISTINCT FROM p->'tc_expression'->>'record_sha256'
   OR te->>'projection_sha256' IS DISTINCT FROM p->'tc_expression'->>'projection_sha256' THEN
   RAISE EXCEPTION 'field_review_tc_expression_pin' USING ERRCODE='23514'; END IF;
  parent:=te->'projection';
  IF te->'current' IS DISTINCT FROM 'true'::jsonb OR te->>'capture_id' IS DISTINCT FROM e->>'capture_id'
   OR parent->'subject' IS DISTINCT FROM projection->'subject' OR parent->'window' IS DISTINCT FROM projection->'window'
   OR parent->'source_role' IS DISTINCT FROM projection->'source_role' OR parent->'model' IS DISTINCT FROM projection->'model' THEN
   reasons:=array_append(reasons,'different_source_window'); END IF;
 END IF;
 IF parent->>'field_id'<>'tc_kelvin' OR parent->'value'->>'status'<>'parsed'
  OR parent->'value'->>'unit'<>'K' OR parent->'value'->'uncertainty'<>'null'::jsonb
  OR parent->'value'->'approximate'<>'false'::jsonb OR parent->'value'->>'relation'<>'exact'
  OR parent->'value'->'value' IS DISTINCT FROM r->'tc_kelvin' THEN reasons:=array_append(reasons,'different_tc_window'); END IF;
 IF parent->'subject'->>'formula' IS DISTINCT FROM r->>'formula' OR parent->'subject'->>'formula_scope'<>'retained_formula_span'
  OR parent->>'source_role'<>'source_reported' OR parent->'model'<>'null'::jsonb THEN
  reasons:=array_append(reasons,'subject_or_model_unresolved'); END IF;
 -- A matching numerical Tc cannot transfer an observed condition to an
 -- explicitly computed, inferred or nonequilibrium retained result.
 FOR k IN SELECT unnest(ARRAY['knowledge_origin','result_origin']) LOOP
  origin:=lower(trim(r->>k));
  IF origin IS NOT NULL AND origin NOT IN ('','unknown','not_reported','unreported')
   AND (origin NOT IN ('observed','computed') OR origin IS DISTINCT FROM lower(parent->>'knowledge_origin')) THEN
   reasons:=array_append(reasons,'retained_origin_requires_review'); END IF;
 END LOOP;
 FOR k IN SELECT unnest(ARRAY['paper_type','evidence_type']) LOOP
  origin:=lower(trim(r->>k));
  IF origin IS NOT NULL AND origin NOT IN ('','unknown','not_reported','unreported') THEN
   IF origin IN ('experimental','primary_experimental') THEN origin:='observed';
   ELSIF origin IN ('theoretical','computational','primary_theoretical','primary_computational') THEN origin:='computed';
   ELSE origin:=NULL; END IF;
   IF origin IS NULL OR origin IS DISTINCT FROM lower(parent->>'knowledge_origin') THEN
    reasons:=array_append(reasons,'retained_origin_requires_review'); END IF;
  END IF;
 END LOOP;
 FOR k IN SELECT unnest(ARRAY['measurement','method','measurement_method']) LOOP
  origin:=regexp_replace(lower(trim(r->>k)),'[[:space:]-]+','_','g');
  IF origin IN ('calculation','dft','dfpt','first_principles','first_principle','first_principles_calculation',
    'computational','ab_initio','abinitio','density_functional_theory','allen_dynes','allen_dynes_calculation',
    'eliashberg','tight_binding','scdft') AND parent->>'knowledge_origin' IS DISTINCT FROM 'Computed' THEN
   reasons:=array_append(reasons,'retained_origin_requires_review');
  ELSIF origin IN ('resistivity','resistance','resistive','electrical_resistivity','susceptibility','magnetic_susceptibility',
    'ac_susceptibility','dc_susceptibility','specific_heat','heat_capacity','specific_heat_capacity','arpes','musr','mu_sr',
    'muon_spin_rotation','muon_spin_relaxation','stm','neutron','nmr','nqr','magnetization','thermal_conductivity',
    'raman_scattering','raman','andreev_reflection','nernst','tunneling','esr','torque_magnetometry','hall_effect',
    'transport','electrical_transport') AND parent->>'knowledge_origin' IS DISTINCT FROM 'Observed' THEN
   reasons:=array_append(reasons,'retained_origin_requires_review');
  END IF;
 END LOOP;
 IF r->>'source_role' IS NOT NULL AND lower(trim(r->>'source_role')) NOT IN ('','unknown','source_reported')
  OR r->>'tc_regime' IS NOT NULL AND lower(trim(r->>'tc_regime')) NOT IN ('','unknown','bulk_equilibrium') THEN
  reasons:=array_append(reasons,'retained_regime_requires_review'); END IF;
 FOR k IN SELECT unnest(CASE field WHEN 'tc_criterion' THEN ARRAY['tc_criterion','criterion','transition_criterion']
  WHEN 'measurement_method' THEN ARRAY['measurement','method','measurement_method','measurement_technique','experimental_method']
  ELSE ARRAY['pressure_gpa','pressure','pressure_gpa_unit','pressure_unit','pressure_state','pressure_condition','pressure_conditions','tc_conditions'] END) LOOP
  inventory:=inventory||jsonb_build_object(k,jsonb_build_object('present',r ? k,'value',r->k));
  IF r->k IS NOT NULL AND r->k<>'null'::jsonb AND NOT (jsonb_typeof(r->k)='string' AND lower(trim(r->>k)) IN ('','unknown','not_reported','not reported','unreported')) THEN missing:=false; END IF;
 END LOOP;
 IF NOT missing THEN reasons:=array_append(reasons,'field_already_reported_or_ambiguous'); END IF;
 method:=COALESCE(NULLIF(NULLIF(lower(trim(r->>'measurement')),'unknown'),''),NULLIF(NULLIF(lower(trim(r->>'method')),'unknown'),''),NULLIF(NULLIF(lower(trim(r->>'measurement_method')),'unknown'),''));
 SELECT lower(replace(trim(z->'value'->>'raw_value'),' ','_')) INTO source_method FROM jsonb_array_elements(parent->'conditions') z
  WHERE z->>'field_id'='method_statement' AND z->>'role'='reported_result_condition' LIMIT 1;
 SELECT count(*) INTO method_count FROM jsonb_array_elements(parent->'conditions') z
  WHERE z->>'field_id'='method_statement' AND z->>'role'='reported_result_condition';
 IF method_count>1 THEN reasons:=array_append(reasons,'competing_source_components'); END IF;
 IF p->'component'->>'kind'='value' AND (method_count<>1 OR source_method IS DISTINCT FROM
  lower(replace(trim(part->'value'->>'raw_value'),' ','_'))) THEN
  reasons:=array_append(reasons,'different_measurement_window'); END IF;
 IF field<>'measurement_method' AND method IS NOT NULL AND source_method IS DISTINCT FROM replace(method,' ','_') THEN
  reasons:=array_append(reasons,'different_measurement_window'); END IF;
 IF field<>'measurement_method' THEN
  FOR k IN SELECT unnest(ARRAY['measurement','method','measurement_method','measurement_technique','experimental_method']) LOOP
   IF r->k IS NOT NULL AND r->k<>'null'::jsonb AND lower(trim(r->>k)) NOT IN ('','unknown','unreported','not_reported','not reported')
    AND lower(replace(trim(r->>k),' ','_')) IS DISTINCT FROM source_method THEN
    reasons:=array_append(reasons,'different_measurement_window'); END IF;
  END LOOP;
 END IF;
 IF (SELECT count(*) FROM jsonb_array_elements(parent->'conditions') z WHERE z->>'field_id'=cf AND z->>'role'='reported_result_condition')>1 THEN
  reasons:=array_append(reasons,'competing_source_components'); END IF;
 coarse:=COALESCE(r->>'tc_type',r->>'tc_definition'); value_text:=part->'value'->>'raw_value';
 IF field='tc_criterion' AND coarse IS NOT NULL AND lower(trim(coarse)) NOT IN ('','unknown','unreported','not_reported')
  AND NOT (lower(trim(coarse))='onset' AND lower(value_text) LIKE '%onset%'
   OR lower(trim(coarse))='zero_resistance' AND lower(value_text) LIKE '%zero%resistance%'
   OR lower(trim(coarse))='midpoint' AND lower(value_text) LIKE '%midpoint%') THEN
  reasons:=array_append(reasons,'coarse_criterion_requires_review'); END IF;
 IF field='tc_criterion' THEN
  FOR k IN SELECT unnest(ARRAY['tc_type','tc_definition']) LOOP
   coarse:=r->>k;
   IF coarse IS NOT NULL AND lower(trim(coarse)) NOT IN ('','unknown','unreported','not_reported')
    AND NOT (lower(trim(coarse))='onset' AND lower(value_text) LIKE '%onset%'
     OR lower(trim(coarse))='zero_resistance' AND lower(value_text) LIKE '%zero%resistance%'
     OR lower(trim(coarse))='midpoint' AND lower(value_text) LIKE '%midpoint%') THEN
    reasons:=array_append(reasons,'coarse_criterion_requires_review'); END IF;
  END LOOP;
 END IF;
 coarse:=COALESCE(r->>'tc_type',r->>'tc_definition');
 IF field='pressure_gpa' AND (part->'value'->>'status'<>'parsed' OR part->'value'->>'unit'<>'GPa'
  OR part->'value'->>'unit_basis'<>'source_printed' OR part->'value'->>'raw_unit' IS NULL) THEN
  reasons:=array_append(reasons,'unit_or_value_requires_review'); END IF;
 IF field<>'pressure_gpa' AND part->'value'->>'status'<>'source_statement' THEN reasons:=array_append(reasons,'value_requires_review'); END IF;
 tuple_body:=jsonb_build_object('subject',projection->'subject','window',projection->'window','source_role',projection->'source_role','model',projection->'model');
 candidate:=jsonb_build_object('field_id',field,'value',part->'value','value_spans',entry->'value_spans','unit_spans',entry->'unit_spans',
  'component',p->'component','window',projection->'window');
 SELECT COALESCE(array_agg(DISTINCT v ORDER BY v),ARRAY[]::text[]) INTO reasons FROM unnest(reasons) v;
 RETURN jsonb_build_object('target_id',t.id,'field_id',field,'context_sha256',t.context_sha256,'admission',admission,
  'retained_result_summary',jsonb_build_object('tc_kelvin',r->'tc_kelvin','paper_id',r->'paper_id','year',r->'year',
   'knowledge_origin',r->'knowledge_origin','tc_type',r->'tc_type'),
  'candidate',candidate,'missingness',jsonb_build_object('aliases',inventory,'missing',missing,'coarse_tc_type',coarse),
  'tuple',tuple_body,'candidate_sha256',public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(candidate)),
  'missingness_sha256',public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(jsonb_build_object('aliases',inventory,'missing',missing,'coarse_tc_type',coarse))),
  'tuple_sha256',public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(tuple_body)),
  'target_user_id',t.actor_user_id,'association_user_id',CASE WHEN p->'association'='null'::jsonb THEN NULL::uuid ELSE a.actor_user_id END,
  'importer_user_id',e->'importer_user_id','capture_user_id',e->'capture_user_id','tc_importer_user_id',te->'importer_user_id',
  'eligible',cardinality(reasons)=0,'reason_codes',to_jsonb(reasons));
END $$;
CREATE FUNCTION public.sclib_material_field_review_immutable_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'material field review is append-only' USING ERRCODE='55000'; END $$;
CREATE FUNCTION public.sclib_material_field_review_insert_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE q jsonb; item jsonb; subject jsonb; prior jsonb; req public.material_field_review_requests_v1%ROWTYPE;
 preview jsonb; k text; i integer; seen text[]:=ARRAY[]::text[]; chain text; BEGIN
 PERFORM public.sclib_material_field_lock_v1();
 IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,'reviewer')
  OR NOT EXISTS(SELECT 1 FROM public.users WHERE id=NEW.actor_user_id AND session_version=NEW.actor_session_version) THEN
  RAISE EXCEPTION 'field_review_live_reviewer_required' USING ERRCODE='42501'; END IF;
 IF TG_TABLE_NAME='material_field_review_requests_v1' THEN
  q:=NEW.request_json::jsonb;
  IF NOT public.sclib_material_field_closed_v1(q,ARRAY['version','profile_version','request_key','items'])
   OR jsonb_typeof(q->'version') IS DISTINCT FROM 'string' OR jsonb_typeof(q->'profile_version') IS DISTINCT FROM 'string'
   OR q->>'version'<>'material-field-review/1.0.0' OR q->>'profile_version'<>'retained-tc-field-fidelity/1.0.0'
   OR jsonb_typeof(q->'request_key')<>'string' OR q->>'request_key' IS DISTINCT FROM NEW.request_key
   OR jsonb_typeof(q->'items')<>'array' OR jsonb_array_length(q->'items') NOT BETWEEN 1 AND 8
   OR public.sclib_scientific_import_canonical_v1(q) IS DISTINCT FROM NEW.request_json
   OR public.sclib_source_property_hash_v1(NEW.request_json) IS DISTINCT FROM NEW.request_sha256 THEN
   RAISE EXCEPTION 'field_review_request_shape' USING ERRCODE='23514'; END IF;
  i:=0;
  FOR item IN SELECT value FROM jsonb_array_elements(q->'items') LOOP
   IF NOT public.sclib_material_field_closed_v1(item,ARRAY['target_id','target_sha256','field_id','association','expression','tc_expression','source_identity','component',
    'expected_subject_sha256','expected_candidate_sha256','expected_missingness_sha256','expected_tuple_sha256','decision','checks','source_inspection_attested','rationale','predecessor','resolves_decision_id'])
    OR jsonb_typeof(item->'target_id')<>'string' OR jsonb_typeof(item->'field_id')<>'string'
    OR item->>'decision' NOT IN ('accept','reject','request_clarification') OR jsonb_typeof(item->'decision')<>'string'
    OR jsonb_typeof(item->'source_inspection_attested')<>'boolean' OR jsonb_typeof(item->'rationale')<>'string'
    OR length(trim(item->>'rationale')) NOT BETWEEN 20 AND 1000 OR item->>'rationale' ~ '[\x01-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]'
    OR NOT public.sclib_material_field_closed_v1(item->'checks',ARRAY['source_identity_and_fragment','field_value_and_unit_boundary','retained_result_window_and_sample_scope','semantic_missingness_and_conflicts'])
    OR EXISTS(SELECT 1 FROM jsonb_each(item->'checks') z WHERE jsonb_typeof(z.value)<>'string' OR z.value#>>'{}' NOT IN ('satisfied','unresolved','not_applicable')) THEN
    RAISE EXCEPTION 'field_review_item_shape' USING ERRCODE='23514'; END IF;
   chain:=(item->>'target_id')||':'||(item->>'field_id');
   IF chain=ANY(seen) THEN RAISE EXCEPTION 'field_review_duplicate_target' USING ERRCODE='23514'; END IF;
   seen:=array_append(seen,chain);
   subject:=public.sclib_material_field_review_subject_v1(item-ARRAY['expected_subject_sha256','expected_candidate_sha256','expected_missingness_sha256','expected_tuple_sha256',
    'decision','checks','source_inspection_attested','rationale','predecessor','resolves_decision_id']);
   IF item->>'expected_subject_sha256' IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(subject))
    OR item->>'expected_candidate_sha256' IS DISTINCT FROM subject->>'candidate_sha256'
    OR item->>'expected_missingness_sha256' IS DISTINCT FROM subject->>'missingness_sha256'
    OR item->>'expected_tuple_sha256' IS DISTINCT FROM subject->>'tuple_sha256' THEN
    RAISE EXCEPTION 'field_review_exact_subject_required' USING ERRCODE='23514'; END IF;
   SELECT to_jsonb(d) INTO prior FROM public.material_field_review_decisions_v1 d WHERE d.target_id=(item->>'target_id')::uuid
    AND d.field_id=item->>'field_id' AND NOT EXISTS(SELECT 1 FROM public.material_field_review_decisions_v1 s WHERE s.predecessor_id=d.id);
   IF item->'predecessor' IS DISTINCT FROM (CASE WHEN prior IS NULL THEN 'null'::jsonb ELSE jsonb_build_object('id',prior->>'id','record_sha256',prior->>'record_sha256') END)
    OR (prior->>'decision'='request_clarification' AND item->>'decision'='accept' AND item->>'resolves_decision_id' IS DISTINCT FROM prior->>'id')
    OR item->>'resolves_decision_id' IS NOT NULL AND (prior IS NULL OR prior->>'decision'<>'request_clarification' OR item->>'resolves_decision_id' IS DISTINCT FROM prior->>'id') THEN
    RAISE EXCEPTION 'field_review_exact_head_required' USING ERRCODE='23514'; END IF;
   IF item->>'decision'='accept' AND (subject->'eligible' IS DISTINCT FROM 'true'::jsonb
    OR item->'source_inspection_attested'<>'true'::jsonb OR EXISTS(SELECT 1 FROM jsonb_each(item->'checks') z WHERE z.value<>'"satisfied"'::jsonb)
    OR NEW.actor_user_id::text IN (subject->>'importer_user_id',subject->>'capture_user_id',subject->>'tc_importer_user_id')
    OR EXISTS(SELECT 1 FROM public.material_field_targets_v1 WHERE id=(item->>'target_id')::uuid AND actor_user_id=NEW.actor_user_id)
    OR item->'association'<>'null'::jsonb AND EXISTS(SELECT 1 FROM public.material_field_associations_v1 WHERE id=(item->'association'->>'id')::uuid AND actor_user_id=NEW.actor_user_id)) THEN
    RAISE EXCEPTION 'field_review_acceptance_unavailable' USING ERRCODE='23514'; END IF;
   i:=i+1;
  END LOOP;
  preview:=jsonb_build_object('version','material-field-review/1.0.0','receipt_id',NEW.id,'actor_user_id',NEW.actor_user_id,
   'actor_grant_id',NEW.actor_grant_id,'actor_session_version',NEW.actor_session_version,'request_sha256',NEW.request_sha256);
  IF NEW.preview_json IS DISTINCT FROM public.sclib_scientific_import_canonical_v1(preview)
   OR NEW.preview_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(NEW.preview_json) THEN
   RAISE EXCEPTION 'field_review_exact_preview_required' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO req FROM public.material_field_review_requests_v1 WHERE id=NEW.request_id;
  item:=req.request_json::jsonb->'items'->NEW.item_index;
  IF req.id IS NULL OR NEW.actor_user_id IS DISTINCT FROM req.actor_user_id OR NEW.actor_grant_id IS DISTINCT FROM req.actor_grant_id
   OR NEW.actor_session_version IS DISTINCT FROM req.actor_session_version OR NEW.request_sha256 IS DISTINCT FROM req.record_sha256
   OR NEW.payload IS DISTINCT FROM item OR NEW.target_id IS DISTINCT FROM (item->>'target_id')::uuid
   OR NEW.field_id IS DISTINCT FROM item->>'field_id' OR NEW.decision IS DISTINCT FROM item->>'decision'
   OR NEW.predecessor_id IS DISTINCT FROM (item->'predecessor'->>'id')::uuid
   OR NEW.predecessor_sha256 IS DISTINCT FROM item->'predecessor'->>'record_sha256'
   OR NEW.chain_key IS DISTINCT FROM (item->>'target_id')||':'||(item->>'field_id') THEN
   RAISE EXCEPTION 'field_review_decision_binding' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.record_sha256 IS DISTINCT FROM public.sclib_source_property_hash_v1(public.sclib_scientific_import_canonical_v1(to_jsonb(NEW)-ARRAY['created_at','record_sha256','assembly_xid'])) THEN
  RAISE EXCEPTION 'field_review_exact_receipt_required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION public.sclib_material_field_review_complete_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.material_field_review_requests_v1%ROWTYPE; BEGIN
 IF TG_TABLE_NAME='material_field_review_requests_v1' THEN r:=NEW;
 ELSE SELECT * INTO r FROM public.material_field_review_requests_v1 WHERE id=NEW.request_id; END IF;
 IF (SELECT count(*) FROM public.material_field_review_decisions_v1 WHERE request_id=r.id)<>jsonb_array_length(r.request_json::jsonb->'items') THEN
  RAISE EXCEPTION 'field_review_complete_inventory' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
"""
    statements = [part + "$$;" for part in sql.split("$$;") if part.strip()]
    for name in TABLE_ORDER:
        statements.extend([
            f"CREATE TRIGGER fr85_insert BEFORE INSERT ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_material_field_review_insert_v1()",
            f"CREATE TRIGGER fr85_immutable BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.sclib_material_field_review_immutable_v1()",
            f"CREATE TRIGGER fr85_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_material_field_review_immutable_v1()",
            f"CREATE CONSTRAINT TRIGGER fr85_complete AFTER INSERT ON public.{name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sclib_material_field_review_complete_v1()",
        ])
    return statements


def register(metadata):
    def uid(name, parent=None, nullable=False):
        return sa.Column(name, UUID(as_uuid=True), *([sa.ForeignKey(parent, ondelete="RESTRICT", onupdate="RESTRICT")] if parent else []), nullable=nullable)
    def common():
        return [uid("id"), uid("actor_user_id", "users.id"), uid("actor_grant_id", "research_role_grants.id"),
            sa.Column("actor_session_version", sa.Integer, nullable=False), sa.Column("record_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()), sa.PrimaryKeyConstraint("id")]
    request = sa.Table(TABLE_ORDER[0], metadata, *common(), sa.Column("request_key", sa.String(160), nullable=False),
        sa.Column("request_json", sa.Text, nullable=False), sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("preview_json", sa.Text, nullable=False), sa.Column("preview_sha256", sa.String(64), nullable=False),
        sa.Column("assembly_xid", sa.BigInteger, nullable=False, server_default=sa.text("txid_current()")),
        sa.UniqueConstraint("actor_user_id", "request_key", name="uq_fr85_request"),
        sa.CheckConstraint("actor_session_version>=0 AND isfinite(created_at) AND octet_length(request_json) BETWEEN 2 AND 32768 AND octet_length(preview_json) BETWEEN 2 AND 4096 AND request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$'", name="ck_fr85_request_bounds"))
    decision = sa.Table(TABLE_ORDER[1], metadata, *common(), uid("request_id", TABLE_ORDER[0]+".id"),
        sa.Column("request_sha256", sa.String(64), nullable=False), sa.Column("item_index", sa.Integer, nullable=False),
        uid("target_id", "material_field_targets_v1.id"), sa.Column("field_id", sa.String(100), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False), sa.Column("payload", JSONB, nullable=False),
        sa.Column("chain_key", sa.String(140), nullable=False), uid("predecessor_id", TABLE_ORDER[1]+".id", nullable=True),
        sa.Column("predecessor_sha256", sa.String(64)), sa.UniqueConstraint("request_id", "item_index", name="uq_fr85_item"),
        sa.UniqueConstraint("predecessor_id", name="uq_fr85_successor"),
        sa.Index("uq_fr85_root", "chain_key", unique=True, postgresql_where=sa.text("predecessor_id IS NULL")),
        sa.CheckConstraint("actor_session_version>=0 AND isfinite(created_at) AND item_index BETWEEN 0 AND 7 AND (predecessor_id IS NULL)=(predecessor_sha256 IS NULL)", name="ck_fr85_decision_bounds"))
    for table in (request, decision):
        for column in table.c:
            if column.name.endswith("sha256"):
                table.append_constraint(sa.CheckConstraint(f"{column.name} IS NULL OR {column.name} ~ '^[a-f0-9]{{64}}$'", name=f"ck_fr85_{table.name}_{column.name}"))
    for name in ("materials", "papers", "works", "paper_work_map", "source_lifecycle_events", "material_field_targets_v1",
                 "material_field_associations_v1", "source_expression_revisions_v2", "source_expression_captures_v2", "source_expression_imports_v2"):
        decision.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(decision, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return {request.name: request, decision.name: decision}
