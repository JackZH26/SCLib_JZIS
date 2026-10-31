"""0095: extend the existing append-only review ledger to exact Tc claims.

Only two nullable FK columns are added. Legacy property history, hashes and
profiles remain v1. The historical property_row_sha256 column holds the root
row hash for either target; the public v2 DTO calls it result_row_sha256.
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from models import scientific_adjudication_v1 as old
from services import materials_adjudication_contract as contract

SUBJECT_VERSION = "scientific-result-subject/2.0.0"
REQUEST_VERSION = contract.VERSION
SQL = old._SQL
FUNCTIONS = (
    ("sclib_materials_claim_impact_v2", "uuid"),
    ("sclib_materials_adjudication_item_v2", "jsonb"),
    ("sclib_materials_adjudication_decision_v2", "jsonb,jsonb,jsonb"),
    ("sclib_materials_adjudication_current_v2", "uuid"),
    ("sclib_scientific_adjudication_current_legacy_v1", "uuid"),
    ("sclib_materials_adjudication_insert_v2", ""),
)


def impact_sql():
    return f"""
CREATE OR REPLACE FUNCTION public.sclib_materials_claim_impact_v2(identifier uuid) RETURNS text {SQL} STABLE AS $$
DECLARE event_id uuid; items jsonb; nodes jsonb; releases uuid[]; counts jsonb; body text; item record;
 phase integer; batch integer; query text; name text;
BEGIN
 PERFORM public.sclib_scientific_adjudication_read_guard_v1();
 SELECT c.event_id INTO event_id FROM public.material_claims c WHERE c.id=identifier;
 IF event_id IS NULL THEN RAISE EXCEPTION 'materials_claim_impact_target_unavailable' USING ERRCODE='23514'; END IF;
 items:=jsonb_build_array(
   jsonb_build_object('table','material_claims','row_id',identifier::text,'relation','target_claim','via_table','research_events','via_id',event_id::text),
   jsonb_build_object('table','research_events','row_id',event_id::text,'relation','target_event','via_table','research_events','via_id',event_id::text));
 FOR phase IN 1..7 LOOP
  SELECT COALESCE(jsonb_agg(x),'[]'::jsonb) INTO nodes FROM
   (SELECT DISTINCT value->>'table' AS table_name,value->>'row_id' AS row_id FROM jsonb_array_elements(items)) x;
  SELECT array_agg(DISTINCT (value->>'row_id')::uuid) INTO releases FROM jsonb_array_elements(items) WHERE value->>'table'='research_releases';
  query:=CASE phase
   WHEN 1 THEN 'SELECT i.id,i.input_claim_id,x.id AS example_id,x.dataset_snapshot_id AS dataset_id FROM public.ml_example_inputs i JOIN public.ml_examples x ON x.id=i.example_id WHERE i.input_event_id=$1 LIMIT 1001'
   WHEN 2 THEN 'SELECT id,dataset_snapshot_id FROM public.ml_examples WHERE claim_id=$4 LIMIT 1001'
   WHEN 3 THEN 'SELECT id,snapshot_id FROM public.snapshot_event_memberships WHERE event_id=$1 LIMIT 1001'
   WHEN 4 THEN 'SELECT id,event_id,input_claim_id FROM public.event_evidence WHERE input_event_id=$1 AND link_type=''derives_from'' LIMIT 1001'
   WHEN 5 THEN 'SELECT p.id,p.release_id,p.table_name,p.row_id FROM public.research_release_pins p JOIN jsonb_to_recordset($2) x(table_name text,row_id text) ON x.table_name=p.table_name AND x.row_id=p.row_id LIMIT 1001'
   WHEN 6 THEN 'SELECT id,release_id FROM public.research_publication_proposals WHERE release_id=ANY($3) LIMIT 1001'
   WHEN 7 THEN 'SELECT d.id,d.package_id,d.table_name,d.row_id FROM public.research_distribution_dependencies d JOIN jsonb_to_recordset($2) x(table_name text,row_id text) ON x.table_name=d.table_name AND x.row_id=d.row_id LIMIT 1001' END;
  batch:=0;
  FOR item IN EXECUTE query USING event_id,nodes,releases,identifier LOOP
   batch:=batch+1; IF batch>1000 THEN RAISE EXCEPTION 'materials_claim_impact_query_limit' USING ERRCODE='54000'; END IF;
   IF phase=1 THEN
    IF item.input_claim_id=identifier THEN items:=items||jsonb_build_array(jsonb_build_object('table','ml_example_inputs','row_id',item.id::text,'relation','input_claim_reference','via_table','material_claims','via_id',identifier::text)); END IF;
    items:=items||jsonb_build_array(
     jsonb_build_object('table','ml_example_inputs','row_id',item.id::text,'relation','input_event_context_reference','via_table','research_events','via_id',event_id::text),
     jsonb_build_object('table','ml_examples','row_id',item.example_id::text,'relation','input_owner','via_table','ml_example_inputs','via_id',item.id::text),
     jsonb_build_object('table','ml_dataset_snapshots','row_id',item.dataset_id::text,'relation','example_dataset_membership','via_table','ml_examples','via_id',item.example_id::text));
   ELSIF phase=2 THEN items:=items||jsonb_build_array(
     jsonb_build_object('table','ml_examples','row_id',item.id::text,'relation','label_claim_reference','via_table','material_claims','via_id',identifier::text),
     jsonb_build_object('table','ml_dataset_snapshots','row_id',item.dataset_snapshot_id::text,'relation','example_dataset_membership','via_table','ml_examples','via_id',item.id::text));
   ELSIF phase=3 THEN items:=items||jsonb_build_array(
     jsonb_build_object('table','snapshot_event_memberships','row_id',item.id::text,'relation','event_membership','via_table','research_events','via_id',event_id::text),
     jsonb_build_object('table','source_snapshots','row_id',item.snapshot_id::text,'relation','membership_snapshot','via_table','snapshot_event_memberships','via_id',item.id::text));
   ELSIF phase=4 THEN
    items:=items||jsonb_build_array(
     jsonb_build_object('table','event_evidence','row_id',item.id::text,'relation','derives_from_input_event','via_table','research_events','via_id',event_id::text),
     jsonb_build_object('table','research_events','row_id',item.event_id::text,'relation','one_hop_derivation_output','via_table','event_evidence','via_id',item.id::text));
    IF item.input_claim_id=identifier THEN items:=items||jsonb_build_array(jsonb_build_object('table','event_evidence','row_id',item.id::text,'relation','derives_from_input_claim','via_table','material_claims','via_id',identifier::text)); END IF;
   ELSIF phase=5 THEN items:=items||jsonb_build_array(
     jsonb_build_object('table','research_release_pins','row_id',item.id::text,'relation','historical_exact_row_pin','via_table',item.table_name,'via_id',item.row_id),
     jsonb_build_object('table','research_releases','row_id',item.release_id::text,'relation','historical_pin_release','via_table','research_release_pins','via_id',item.id::text));
   ELSIF phase=6 THEN items:=items||jsonb_build_array(jsonb_build_object('table','research_publication_proposals','row_id',item.id::text,'relation','historical_release_proposal','via_table','research_releases','via_id',item.release_id::text));
   ELSE items:=items||jsonb_build_array(
     jsonb_build_object('table','research_distribution_dependencies','row_id',item.id::text,'relation','historical_exact_row_dependency','via_table',item.table_name,'via_id',item.row_id),
     jsonb_build_object('table','research_distribution_packages','row_id',item.package_id::text,'relation','historical_dependency_package','via_table','research_distribution_dependencies','via_id',item.id::text)); END IF;
   IF jsonb_array_length(items)>8000 OR octet_length(items::text)>2097152 THEN RAISE EXCEPTION 'materials_claim_impact_limit' USING ERRCODE='54000'; END IF;
  END LOOP;
  SELECT jsonb_agg(value) INTO items FROM (SELECT DISTINCT value FROM jsonb_array_elements(items)) q;
  IF jsonb_array_length(items)>4000 THEN RAISE EXCEPTION 'materials_claim_impact_limit' USING ERRCODE='54000'; END IF;
 END LOOP;
 batch:=0;
 FOR item IN SELECT id,package_id,ARRAY[capsule_release_0,capsule_release_1,capsule_release_2,capsule_release_3,capsule_release_4,capsule_release_5,capsule_release_6,capsule_release_7] AS capsules
  FROM public.research_distribution_dependencies WHERE capsule_release_0=ANY(releases) OR capsule_release_1=ANY(releases)
   OR capsule_release_2=ANY(releases) OR capsule_release_3=ANY(releases) OR capsule_release_4=ANY(releases)
   OR capsule_release_5=ANY(releases) OR capsule_release_6=ANY(releases) OR capsule_release_7=ANY(releases) LIMIT 1001 LOOP
  batch:=batch+1; IF batch>1000 THEN RAISE EXCEPTION 'materials_claim_impact_query_limit' USING ERRCODE='54000'; END IF;
  FOR name IN SELECT DISTINCT value::text FROM unnest(item.capsules) value WHERE value=ANY(releases) LOOP
   items:=items||jsonb_build_array(jsonb_build_object('table','research_distribution_dependencies','row_id',item.id::text,'relation','historical_capsule_reference','via_table','research_releases','via_id',name)); END LOOP;
  items:=items||jsonb_build_array(jsonb_build_object('table','research_distribution_packages','row_id',item.package_id::text,'relation','historical_dependency_package','via_table','research_distribution_dependencies','via_id',item.id::text));
  IF jsonb_array_length(items)>16000 OR octet_length(items::text)>4194304 THEN RAISE EXCEPTION 'materials_claim_impact_limit' USING ERRCODE='54000'; END IF;
 END LOOP;
 SELECT jsonb_agg(value ORDER BY value->>'table' COLLATE "C",value->>'row_id' COLLATE "C",value->>'relation' COLLATE "C",value->>'via_table' COLLATE "C",value->>'via_id' COLLATE "C") INTO items FROM (SELECT DISTINCT value FROM jsonb_array_elements(items)) q;
 SELECT jsonb_build_object('total_relations',jsonb_array_length(items),'total_nodes',(SELECT count(*) FROM
  (SELECT DISTINCT value->>'table',value->>'row_id' FROM jsonb_array_elements(items)) x)) INTO counts;
 IF (counts->>'total_nodes')::int>2000 OR (counts->>'total_relations')::int>4000 THEN RAISE EXCEPTION 'materials_claim_impact_limit' USING ERRCODE='54000'; END IF;
 body:=public.sclib_scientific_adjudication_canonical_v1(jsonb_build_object('version','materials-claim-impact/2.0.0',
  'scope',jsonb_build_array('exact_claim_label_and_input_references','owning_event_context_references','direct_event_snapshots','one_hop_derivation','reached_row_release_publication_distribution_references'),
  'unsupported_scopes',jsonb_build_array('transitive_dependencies','sibling_result_causality','unregistered_text_or_formula_matches','external_files_caches_and_vectors','future_dependencies','scientific_or_distribution_authority'),
  'complete_for_scope',true,'counts',counts,'items',items));
 IF octet_length(body)>1048576 THEN RAISE EXCEPTION 'materials_claim_impact_byte_limit' USING ERRCODE='54000'; END IF;
 RETURN body;
END $$
"""


def item_sql():
    literal = old._literal
    return f"""
CREATE OR REPLACE FUNCTION public.sclib_materials_adjudication_item_v2(item jsonb) RETURNS void {SQL} AS $$
DECLARE keys text[]:=ARRAY[{','.join(repr(k) for k in sorted(contract.ITEM_KEYS))}]; key text; ref jsonb;
 profiles jsonb:={literal(contract.PROFILES)};
BEGIN
 IF jsonb_typeof(item) IS DISTINCT FROM 'object' OR NOT(item ?& keys) OR item-keys<>'{{}}'::jsonb
  OR item->>'result_kind' IS DISTINCT FROM 'claim' THEN RAISE EXCEPTION 'materials_review_exact_claim_item_required' USING ERRCODE='23514'; END IF;
 FOREACH key IN ARRAY ARRAY['decision_id','subject_id','result_id','expected_previous_decision_id','resolves_decision_id','extraction_decision_id'] LOOP
  IF key IN ('expected_previous_decision_id','resolves_decision_id','extraction_decision_id') AND item->key='null'::jsonb THEN CONTINUE; END IF;
  IF jsonb_typeof(item->key) IS DISTINCT FROM 'string' OR item->>key !~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$' THEN RAISE EXCEPTION 'materials_review_uuid_required' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['expected_subject_sha256','expected_impact_sha256'] LOOP
  IF jsonb_typeof(item->key) IS DISTINCT FROM 'string' OR item->>key !~ '^[0-9a-f]{{64}}$' THEN RAISE EXCEPTION 'materials_review_hash_required' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['scope','profile_version','decision','reason_code','proposition','rationale'] LOOP
  IF jsonb_typeof(item->key) IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'materials_review_text_required' USING ERRCODE='23514'; END IF; END LOOP;
 IF NOT profiles ? (item->>'profile_version') OR profiles->(item->>'profile_version')->>0 IS DISTINCT FROM item->>'scope'
  OR profiles->(item->>'profile_version')->>1 IS DISTINCT FROM item->>'proposition'
  OR item->'limitations' IS DISTINCT FROM {literal(contract.LIMITATIONS)}
  OR char_length(item->>'rationale') NOT BETWEEN 20 AND 2000
  OR char_length(btrim(item->>'rationale',E' \\n\\r\\t'||chr(160)||chr(5760)||chr(8192)||chr(8193)||chr(8194)||chr(8195)||chr(8196)||chr(8197)||chr(8198)||chr(8199)||chr(8200)||chr(8201)||chr(8202)||chr(8232)||chr(8233)||chr(8239)||chr(8287)||chr(12288)))<20
  OR regexp_replace(item->>'rationale',E'[\\n\\t]','','g') ~ '[[:cntrl:]]'
  OR EXISTS(SELECT 1 FROM regexp_split_to_table(item->>'rationale','') ch WHERE ascii(ch) BETWEEN 127 AND 159)
  OR jsonb_typeof(item->'source_inspection_attested') IS DISTINCT FROM 'boolean'
  OR NOT public.sclib_materials_closed_object_v1(item->'checks',ARRAY[{','.join(repr(k) for k in contract.CHECKS)}])
  OR jsonb_typeof(item->'evidence_refs') IS DISTINCT FROM 'array' OR jsonb_array_length(item->'evidence_refs')>50 THEN
  RAISE EXCEPTION 'materials_review_profile_shape_required' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_each(item->'checks') WHERE jsonb_typeof(value)<>'string' OR value#>>'{{}}' NOT IN ('satisfied','not_applicable','unresolved')) THEN
  RAISE EXCEPTION 'materials_review_check_state_required' USING ERRCODE='23514'; END IF;
 IF NOT ((item->>'decision'='accept' AND item->>'reason_code'='evidence_and_scope_match')
  OR (item->>'decision'='reject' AND item->>'reason_code' IN ('source_mismatch','quantity_or_unit_mismatch','state_association_mismatch','method_or_scope_mismatch','scientific_concern'))
  OR (item->>'decision'='request_clarification' AND item->>'reason_code' IN ('insufficient_evidence','unresolved_state','unresolved_method','conflicting_evidence'))) THEN
  RAISE EXCEPTION 'materials_review_reason_required' USING ERRCODE='23514'; END IF;
 IF item->>'decision'='accept' AND (item->'source_inspection_attested'<>'true'::jsonb OR jsonb_array_length(item->'evidence_refs')=0
  OR EXISTS(SELECT 1 FROM jsonb_each_text(item->'checks') WHERE value<>'satisfied')) THEN RAISE EXCEPTION 'materials_review_acceptance_checks_required' USING ERRCODE='23514'; END IF;
 IF ((item->>'scope'='scientific_result' AND item->>'decision'='accept') IS DISTINCT FROM (item->'extraction_decision_id'<>'null'::jsonb))
  OR (item->'resolves_decision_id'<>'null'::jsonb AND item->'resolves_decision_id' IS DISTINCT FROM item->'expected_previous_decision_id') THEN
  RAISE EXCEPTION 'materials_review_dependency_shape_required' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(item->'evidence_refs') LOOP
  IF NOT public.sclib_materials_closed_object_v1(ref,ARRAY['occurrence_id','source_revision_id','capture_id','bytes_sha256']) THEN
   RAISE EXCEPTION 'materials_review_exact_evidence_required' USING ERRCODE='23514'; END IF;
  FOREACH key IN ARRAY ARRAY['occurrence_id','source_revision_id','capture_id'] LOOP
   IF jsonb_typeof(ref->key) IS DISTINCT FROM 'string' OR ref->>key !~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$' THEN RAISE EXCEPTION 'materials_review_evidence_uuid_required' USING ERRCODE='23514'; END IF; END LOOP;
  IF jsonb_typeof(ref->'bytes_sha256') IS DISTINCT FROM 'string' OR ref->>'bytes_sha256' !~ '^[0-9a-f]{{64}}$' THEN RAISE EXCEPTION 'materials_review_evidence_hash_required' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF (SELECT count(DISTINCT value->>'occurrence_id') FROM jsonb_array_elements(item->'evidence_refs'))<>jsonb_array_length(item->'evidence_refs')
  OR item->'evidence_refs' IS DISTINCT FROM (SELECT COALESCE(jsonb_agg(value ORDER BY value->>'occurrence_id'),'[]'::jsonb) FROM jsonb_array_elements(item->'evidence_refs')) THEN
  RAISE EXCEPTION 'materials_review_sorted_unique_evidence_required' USING ERRCODE='23514'; END IF;
END $$
"""


def decision_sql():
    return f"""
CREATE OR REPLACE FUNCTION public.sclib_materials_adjudication_decision_v2(d jsonb,item jsonb,body jsonb) RETURNS void {SQL} AS $$
DECLARE c jsonb; e jsonb; s jsonb; ref jsonb; witness record; dependency public.scientific_result_decisions%ROWTYPE;
BEGIN
 SELECT value->'snapshot' INTO c FROM jsonb_array_elements(body->'rows') WHERE value->>'table'='material_claims' AND value->>'row_id'=d->>'claim_id';
 SELECT value->'snapshot' INTO e FROM jsonb_array_elements(body->'rows') WHERE value->>'table'='research_events' AND value->>'row_id'=d->>'event_id';
 SELECT value->'snapshot' INTO s FROM jsonb_array_elements(body->'rows') WHERE value->>'table'='material_states' AND value->>'row_id'=e->>'state_id';
 IF c IS NULL OR e IS NULL OR s IS NULL
  OR (d->>'profile_version'='reported-non-detection-fidelity/1.0.0' AND c->>'property_type' IS DISTINCT FROM 'non_transition')
  OR (d->>'profile_version' IN ('reported-tc-fidelity/1.0.0','experimental-tc-review/1.0.0') AND c->>'property_type' IS DISTINCT FROM 'tc') THEN
  RAISE EXCEPTION 'materials_review_profile_quantity_mismatch' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(item->'evidence_refs') LOOP
  SELECT o.binding_status,r.version_status,cap.representation INTO witness FROM public.claim_source_occurrences o
   JOIN public.source_captures cap ON cap.id=o.capture_id AND cap.source_revision_id=o.source_revision_id
   JOIN public.source_revisions r ON r.id=o.source_revision_id
   WHERE o.id::text=ref->>'occurrence_id' AND o.claim_id::text=d->>'claim_id'
    AND o.source_revision_id::text=ref->>'source_revision_id' AND o.capture_id::text=ref->>'capture_id'
    AND cap.bytes_sha256=ref->>'bytes_sha256';
  IF NOT FOUND THEN RAISE EXCEPTION 'materials_review_exact_claim_source_required' USING ERRCODE='23514'; END IF;
  IF d->>'decision'='accept' AND (witness.binding_status<>'reviewed' OR witness.version_status<>'pinned'
    OR (d->>'scope'='scientific_result' AND witness.representation='abstract')) THEN
   RAISE EXCEPTION 'materials_review_pinned_reviewed_source_required' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF d->>'decision'='accept' AND c->>'property_type'='non_transition'
  AND (c->>'result_status' IS DISTINCT FROM 'not_detected' OR c->>'value_relation' IS DISTINCT FROM 'unreported') THEN
  RAISE EXCEPTION 'materials_review_non_detection_no_numeric_tc' USING ERRCODE='23514'; END IF;
 IF d->>'decision'='accept' AND d->>'scope'='scientific_result' THEN
  IF c->>'property_type' IS DISTINCT FROM 'tc' OR c->>'result_status' IS DISTINCT FROM 'observed'
   OR c->>'evidence_role' IS DISTINCT FROM 'primary_experimental' OR c->>'value_relation'='unreported'
   OR e->>'event_type' IS DISTINCT FROM 'measurement' OR e->>'knowledge_origin' IS DISTINCT FROM 'Observed'
   OR s->>'resolution'='unresolved' OR length(btrim(COALESCE(c->>'measurement_method','')))=0
   OR c->>'pressure_state' IS DISTINCT FROM s->>'pressure_status' OR c->'pressure_gpa' IS DISTINCT FROM s->'pressure_gpa'
   OR (c->>'value_relation'='exact' AND (c->>'value_kelvin')::float8<=0) THEN
   RAISE EXCEPTION 'materials_review_experimental_tc_scope_required' USING ERRCODE='23514'; END IF;
  SELECT * INTO dependency FROM public.scientific_result_decisions WHERE id=(d->>'extraction_decision_id')::uuid;
  IF dependency.id IS NULL OR dependency.subject_id::text IS DISTINCT FROM d->>'subject_id'
   OR dependency.claim_id::text IS DISTINCT FROM d->>'claim_id' OR dependency.scope<>'extraction_fidelity'
   OR dependency.decision<>'accept' OR dependency.actor_user_id::text=d->>'actor_user_id'
   OR EXISTS(SELECT 1 FROM public.scientific_result_decisions WHERE predecessor_id=dependency.id)
   OR NOT public.sclib_research_distribution_role_v1(dependency.actor_user_id,dependency.actor_grant_id,'reviewer') THEN
   RAISE EXCEPTION 'materials_review_independent_current_fidelity_required' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(body->'rows') r JOIN public.source_lifecycle_events l
    ON (r->>'table'='papers' AND l.paper_id=r->>'row_id') OR (r->>'table'='works' AND l.work_id::text=r->>'row_id'))
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(body->'rows') r JOIN public.papers p ON r->>'table'='papers' AND p.id=r->>'row_id' WHERE lower(p.status) IN ('retracted','withdrawn','corrected','disputed'))
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(body->'rows') r JOIN public.works w ON r->>'table'='works' AND w.id::text=r->>'row_id' WHERE lower(w.publication_status) IN ('retracted','withdrawn','corrected','disputed'))
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(body->'rows') r JOIN public.research_events e ON r->>'table'='research_events' AND e.id::text=r->>'row_id' WHERE e.validity_status IN ('disputed','retracted','excluded') OR e.review_status='rejected')
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(body->'rows') r JOIN public.material_claims c ON r->>'table'='material_claims' AND c.id::text=r->>'row_id' WHERE c.validity_status IN ('disputed','retracted','excluded')) THEN
   RAISE EXCEPTION 'materials_review_source_held' USING ERRCODE='23514'; END IF;
 END IF;
END $$
"""


def current_sql():
    # Give the unchanged old checker its own name; dispatch does not invoke a
    # trigger function as a regular function or reinterpret old request bytes.
    legacy = old._current_guard()[0].replace("FUNCTION public.sclib_scientific_adjudication_current_v1(",
                                            "FUNCTION public.sclib_scientific_adjudication_current_legacy_v1(", 1)
    return [legacy, f"""
CREATE OR REPLACE FUNCTION public.sclib_materials_adjudication_current_v2(identifier uuid) RETURNS void {SQL} AS $$
DECLARE request public.scientific_adjudication_requests%ROWTYPE; row record; body text; impact text; item jsonb;
BEGIN
 SELECT * INTO request FROM public.scientific_adjudication_requests WHERE id=identifier;
 IF request.id IS NULL OR request.assembly_xid<>txid_current() OR request.request_version<>'{REQUEST_VERSION}' THEN
  RAISE EXCEPTION 'materials_review_current_assembly_required' USING ERRCODE='23514'; END IF;
 IF NOT public.sclib_research_distribution_role_v1(request.actor_user_id,request.actor_grant_id,'reviewer') THEN
  RAISE EXCEPTION 'materials_review_current_reviewer_required' USING ERRCODE='42501'; END IF;
 FOR row IN SELECT d.*,s.basis_json FROM public.scientific_result_decisions d JOIN public.scientific_result_subjects s ON s.id=d.subject_id WHERE d.request_id=identifier LOOP
  body:=public.sclib_scientific_subject_capture_v2('claim',row.claim_id);
  impact:=public.sclib_materials_claim_impact_v2(row.claim_id);
  item:=request.request_json::jsonb->'items'->row.item_index;
  IF body IS DISTINCT FROM row.basis_json OR item->>'expected_impact_sha256' IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(impact) THEN
   RAISE EXCEPTION 'materials_review_assembly_changed' USING ERRCODE='23514'; END IF;
  PERFORM public.sclib_materials_adjudication_decision_v2(to_jsonb(row),item,body::jsonb);
 END LOOP;
END $$
""", f"""
CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_current_v1(identifier uuid) RETURNS void {SQL} AS $$
DECLARE version text;
BEGIN
 SELECT request_version INTO version FROM public.scientific_adjudication_requests WHERE id=identifier;
 IF version='{old.REQUEST_VERSION}' THEN PERFORM public.sclib_scientific_adjudication_current_legacy_v1(identifier);
 ELSIF version='{REQUEST_VERSION}' THEN PERFORM public.sclib_materials_adjudication_current_v2(identifier);
 ELSE RAISE EXCEPTION 'materials_review_request_version_required' USING ERRCODE='23514'; END IF;
END $$
"""]


def insert_sql():
    return f"""
CREATE OR REPLACE FUNCTION public.sclib_materials_adjudication_insert_v2() RETURNS trigger {SQL} AS $$
DECLARE body text; snapshot jsonb; target jsonb; result jsonb; item jsonb; amount integer;
 request public.scientific_adjudication_requests%ROWTYPE; subject public.scientific_result_subjects%ROWTYPE;
 prior public.scientific_result_decisions%ROWTYPE;
BEGIN
 PERFORM public.{old.LOCK_FUNCTION}();
 IF TG_TABLE_NAME='scientific_result_subjects' THEN
  body:=public.sclib_scientific_subject_capture_v2('claim',NEW.claim_id); snapshot:=body::jsonb; target:=snapshot->'target';
  SELECT value->'snapshot' INTO result FROM jsonb_array_elements(snapshot->'rows') WHERE value->>'table'='material_claims' AND value->>'row_id'=NEW.claim_id::text;
  IF NEW.property_id IS NOT NULL OR NEW.basis_json IS DISTINCT FROM body
   OR NEW.subject_sha256 IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(body)
   OR NEW.property_row_sha256 IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(public.sclib_scientific_adjudication_canonical_v1(result))
   OR NEW.subject_version IS DISTINCT FROM '{SUBJECT_VERSION}'
   OR NEW.event_id::text IS DISTINCT FROM target->>'event_id' OR NEW.event_revision IS DISTINCT FROM (target->>'event_revision')::int
   OR NEW.material_id IS DISTINCT FROM target->>'material_id' OR NEW.state_id::text IS DISTINCT FROM target->>'state_id'
   OR NEW.sample_id::text IS DISTINCT FROM target->>'sample_id' OR NEW.structure_id::text IS DISTINCT FROM target->>'structure_id'
   OR NEW.producer_run_id::text IS DISTINCT FROM target->>'producer_run_id' OR NEW.native_outcome_id IS NOT NULL THEN
   RAISE EXCEPTION 'materials_review_exact_subject_required' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='scientific_adjudication_requests' THEN
  IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,'reviewer') THEN RAISE EXCEPTION 'materials_review_current_reviewer_required' USING ERRCODE='42501'; END IF;
  IF octet_length(NEW.request_json)>131072 THEN RAISE EXCEPTION 'materials_review_request_limit' USING ERRCODE='54000'; END IF;
  snapshot:=NEW.request_json::jsonb;
  IF NOT public.sclib_materials_closed_object_v1(snapshot,ARRAY['version','request_key','items'])
   OR snapshot->>'version' IS DISTINCT FROM '{REQUEST_VERSION}' OR NEW.request_version IS DISTINCT FROM '{REQUEST_VERSION}'
   OR jsonb_typeof(snapshot->'request_key') IS DISTINCT FROM 'string' OR snapshot->>'request_key' IS DISTINCT FROM NEW.request_key
   OR jsonb_typeof(snapshot->'items') IS DISTINCT FROM 'array'
   OR NEW.request_sha256 IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(NEW.request_json)
   OR NEW.request_json IS DISTINCT FROM public.sclib_scientific_adjudication_canonical_v1(snapshot) THEN RAISE EXCEPTION 'materials_review_exact_request_required' USING ERRCODE='23514'; END IF;
  amount:=jsonb_array_length(snapshot->'items');
  IF amount NOT BETWEEN 1 AND 20 OR NEW.item_count<>amount
   OR (SELECT count(DISTINCT (value->>'result_kind',value->>'result_id',value->>'scope')) FROM jsonb_array_elements(snapshot->'items'))<>amount
   OR (SELECT count(DISTINCT value->>'decision_id') FROM jsonb_array_elements(snapshot->'items'))<>amount THEN RAISE EXCEPTION 'materials_review_unique_items_required' USING ERRCODE='23514'; END IF;
  amount:=0;
  FOR item IN SELECT value FROM jsonb_array_elements(snapshot->'items') LOOP
   PERFORM public.sclib_materials_adjudication_item_v2(item); amount:=amount+jsonb_array_length(item->'evidence_refs');
   IF EXISTS(SELECT 1 FROM jsonb_array_elements(snapshot->'items') other WHERE other->>'decision_id'=item->>'extraction_decision_id') THEN RAISE EXCEPTION 'materials_review_independent_current_fidelity_required' USING ERRCODE='23514'; END IF;
  END LOOP;
  IF amount>200 THEN RAISE EXCEPTION 'materials_review_reference_limit' USING ERRCODE='54000'; END IF;
  NEW.assembly_xid:=txid_current();
 ELSE
  IF NOT public.sclib_research_distribution_role_v1(NEW.actor_user_id,NEW.actor_grant_id,'reviewer') THEN RAISE EXCEPTION 'materials_review_current_reviewer_required' USING ERRCODE='42501'; END IF;
  SELECT * INTO request FROM public.scientific_adjudication_requests WHERE id=NEW.request_id;
  IF request.id IS NULL OR request.request_version<>'{REQUEST_VERSION}' OR request.assembly_xid<>txid_current()
   OR NEW.item_index NOT BETWEEN 0 AND request.item_count-1 OR NEW.actor_user_id<>request.actor_user_id OR NEW.actor_grant_id<>request.actor_grant_id THEN
   RAISE EXCEPTION 'materials_review_request_actor_required' USING ERRCODE='23514'; END IF;
  item:=request.request_json::jsonb->'items'->NEW.item_index;
  IF NEW.property_id IS NOT NULL OR NEW.id::text IS DISTINCT FROM item->>'decision_id' OR NEW.subject_id::text IS DISTINCT FROM item->>'subject_id'
   OR NEW.claim_id::text IS DISTINCT FROM item->>'result_id' OR NEW.scope IS DISTINCT FROM item->>'scope'
   OR NEW.profile_version IS DISTINCT FROM item->>'profile_version' OR NEW.decision IS DISTINCT FROM item->>'decision'
   OR NEW.reason_code IS DISTINCT FROM item->>'reason_code' OR NEW.predecessor_id::text IS DISTINCT FROM item->>'expected_previous_decision_id'
   OR NEW.resolves_decision_id::text IS DISTINCT FROM item->>'resolves_decision_id' OR NEW.extraction_decision_id::text IS DISTINCT FROM item->>'extraction_decision_id'
   OR NEW.item_sha256 IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(public.sclib_scientific_adjudication_canonical_v1(item)) THEN
   RAISE EXCEPTION 'materials_review_exact_request_item_required' USING ERRCODE='23514'; END IF;
  SELECT * INTO subject FROM public.scientific_result_subjects WHERE id=NEW.subject_id;
  IF subject.id IS NULL OR subject.claim_id IS DISTINCT FROM NEW.claim_id OR subject.event_id<>NEW.event_id
   OR subject.subject_sha256 IS DISTINCT FROM item->>'expected_subject_sha256'
   OR subject.basis_json IS DISTINCT FROM public.sclib_scientific_subject_capture_v2('claim',NEW.claim_id)
   OR item->>'expected_impact_sha256' IS DISTINCT FROM public.sclib_scientific_adjudication_text_hash_v1(public.sclib_materials_claim_impact_v2(NEW.claim_id)) THEN
   RAISE EXCEPTION 'materials_review_preview_changed' USING ERRCODE='23514'; END IF;
  SELECT d.* INTO prior FROM public.scientific_result_decisions d WHERE d.claim_id=NEW.claim_id AND d.scope=NEW.scope
   AND NOT EXISTS(SELECT 1 FROM public.scientific_result_decisions successor WHERE successor.predecessor_id=d.id) LIMIT 1;
  IF NEW.predecessor_id IS DISTINCT FROM prior.id OR (NEW.resolves_decision_id IS NOT NULL AND NEW.resolves_decision_id IS DISTINCT FROM prior.id)
   OR (NEW.decision='accept' AND prior.subject_id=NEW.subject_id AND prior.decision IN ('reject','request_clarification')
     AND (NEW.actor_user_id=prior.actor_user_id OR NEW.resolves_decision_id IS DISTINCT FROM prior.id)) THEN
   RAISE EXCEPTION 'materials_review_exact_current_head_required' USING ERRCODE='23514'; END IF;
  PERFORM public.sclib_materials_adjudication_decision_v2(to_jsonb(NEW),item,subject.basis_json::jsonb);
 END IF;
 NEW.created_at:=clock_timestamp(); NEW.record_sha256:=public.sclib_scientific_adjudication_record_hash_v1(to_jsonb(NEW)); RETURN NEW;
END $$
"""


def trigger_sql(*, legacy_only=False):
    statements = []
    for name in old.TABLE_ORDER:
        statements += [f"DROP TRIGGER IF EXISTS sa67_insert ON public.{name}", f"DROP TRIGGER IF EXISTS ma95_insert ON public.{name}"]
        condition = (f"NEW.request_version='{REQUEST_VERSION}'" if name == "scientific_adjudication_requests" else "NEW.claim_id IS NOT NULL")
        old_when = "" if legacy_only else f" WHEN (NOT ({condition}))"
        statements.append(f"CREATE TRIGGER sa67_insert BEFORE INSERT ON public.{name} FOR EACH ROW{old_when} EXECUTE FUNCTION public.sclib_scientific_adjudication_insert_v1()")
        if not legacy_only:
            statements.append(f"CREATE TRIGGER ma95_insert BEFORE INSERT ON public.{name} FOR EACH ROW WHEN ({condition}) EXECUTE FUNCTION public.sclib_materials_adjudication_insert_v2()")
    return statements


def guard_statements():
    return ["""
CREATE OR REPLACE FUNCTION public.sclib_scientific_adjudication_record_hash_v1(body jsonb) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT public.sclib_scientific_adjudication_text_hash_v1(public.sclib_scientific_adjudication_canonical_v1(
  (CASE WHEN body->'claim_id'='null'::jsonb THEN body-'claim_id' ELSE body END)
  -ARRAY['created_at','record_sha256','basis_json','request_json','assembly_xid']))
$$
""", impact_sql(), item_sql(), decision_sql(), *current_sql(), insert_sql(), *trigger_sql()]


def register(metadata):
    for name in ("scientific_result_subjects", "scientific_result_decisions"):
        table = metadata.tables[name]
        table.c.property_id.nullable = True
        table.append_column(sa.Column("claim_id", UUID(as_uuid=True), nullable=True))
        table.append_constraint(sa.ForeignKeyConstraint(["claim_id", "event_id"], ["material_claims.id", "material_claims.event_id"],
            name="fk_ma95_" + name, ondelete="RESTRICT", onupdate="RESTRICT"))
        table.append_constraint(sa.CheckConstraint("num_nonnulls(property_id,claim_id)=1", name="ck_ma95_" + name))
    subjects = metadata.tables["scientific_result_subjects"]
    subjects.append_constraint(sa.CheckConstraint(f"(claim_id IS NULL AND subject_version='{old.SUBJECT_VERSION}') OR (claim_id IS NOT NULL AND subject_version='{SUBJECT_VERSION}')", name="ck_ma95_subject_version"))
    subjects.append_constraint(sa.UniqueConstraint("claim_id", "subject_sha256", name="uq_ma95_claim_subject"))
    decisions = metadata.tables["scientific_result_decisions"]
    sa.Index("uq_ma95_initial_head", decisions.c.claim_id, decisions.c.scope, unique=True, postgresql_where=sa.text("predecessor_id IS NULL"))
    sa.Index("idx_ma95_claim_head", decisions.c.claim_id, decisions.c.scope)
    for statement in guard_statements():
        sa.event.listen(metadata, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))


def upgrade_statements():
    result = []
    for name in ("scientific_result_subjects", "scientific_result_decisions"):
        result.append(f"ALTER TABLE public.{name} ADD COLUMN claim_id uuid, ALTER COLUMN property_id DROP NOT NULL, ADD CONSTRAINT fk_ma95_{name} FOREIGN KEY (claim_id,event_id) REFERENCES public.material_claims(id,event_id) ON DELETE RESTRICT ON UPDATE RESTRICT, ADD CONSTRAINT ck_ma95_{name} CHECK (num_nonnulls(property_id,claim_id)=1)")
    result += [f"ALTER TABLE public.scientific_result_subjects ADD CONSTRAINT ck_ma95_subject_version CHECK ((claim_id IS NULL AND subject_version='{old.SUBJECT_VERSION}') OR (claim_id IS NOT NULL AND subject_version='{SUBJECT_VERSION}')), ADD CONSTRAINT uq_ma95_claim_subject UNIQUE (claim_id,subject_sha256)",
        "CREATE UNIQUE INDEX uq_ma95_initial_head ON public.scientific_result_decisions(claim_id,scope) WHERE predecessor_id IS NULL",
        "CREATE INDEX idx_ma95_claim_head ON public.scientific_result_decisions(claim_id,scope)"]
    return result + guard_statements()


def downgrade_statements():
    result = ["LOCK TABLE public.scientific_result_subjects,public.scientific_adjudication_requests,public.scientific_result_decisions IN ACCESS EXCLUSIVE MODE",
        f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.scientific_result_subjects WHERE claim_id IS NOT NULL)
         OR EXISTS(SELECT 1 FROM public.scientific_result_decisions WHERE claim_id IS NOT NULL)
         OR EXISTS(SELECT 1 FROM public.scientific_adjudication_requests WHERE request_version='{REQUEST_VERSION}') THEN
         RAISE EXCEPTION 'materials_review_retained_history_refuses_downgrade' USING ERRCODE='23514'; END IF; END $$""",
        *trigger_sql(legacy_only=True), old._current_guard()[0],
        next(sql for sql in old.guard_statements() if "FUNCTION public.sclib_scientific_adjudication_record_hash_v1(body" in sql),
        "ALTER TABLE public.scientific_result_subjects DROP CONSTRAINT ck_ma95_subject_version, DROP CONSTRAINT uq_ma95_claim_subject",
        "DROP INDEX public.uq_ma95_initial_head", "DROP INDEX public.idx_ma95_claim_head"]
    for name in ("scientific_result_subjects", "scientific_result_decisions"):
        result.append(f"ALTER TABLE public.{name} DROP CONSTRAINT ck_ma95_{name}, DROP CONSTRAINT fk_ma95_{name}, DROP COLUMN claim_id, ALTER COLUMN property_id SET NOT NULL")
    result += [f"DROP FUNCTION public.{name}({args})" for name, args in reversed(FUNCTIONS)]
    return result
