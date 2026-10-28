"""Authored completeness, source-key and replay tests; no scientific Gold."""
from copy import deepcopy
import json
import jsonschema
import pytest

from ingestion.materials_ner import source_keyed_inventory as keyed,source_role_inventory as role,page_images
from ingestion.materials_ner import typed_inventory_handoff as handoff,frozen_inventory,item_worker
from ingestion.materials_ner.contract import canonical,digest
from ingestion.materials_ner.sources import sha
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.proposals import ProposalDatabase,import_packet,verify_packet
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_source_role_inventory import selected_fixture
from test_materials_ner_item_stages import StageProvider,responses


def fixture(pdf=False):
    original,b,scope,p,v,rest=selected_fixture()
    if pdf:
        raw=original.model_dump();raw['documents'][0]['source_kind']='original_pdf';raw['blocks'][0]['locator']='pdf_page:1'
        original=role.Bundle.model_validate(raw);b,scope=role.scope(original,[x.id for x in original.blocks])
    cat=role.selection_catalog(b)
    numeric={}
    for key in cat['numeric_obligation_ids']:
        records=[c.model_dump(exclude={'role','numeric_candidate_id'}) for c in p.claims if c.role=='numeric_result' and c.numeric_candidate_id==key]
        numeric[key]=dict(disposition='outcome',records=records) if records else dict(disposition='condition',reason='Authored condition.')
    text={k:dict(review='read',unvalued_records=[c.model_dump() for c in p.claims if c.role=='unvalued_result' and c.statement.first_text_id==k],
        reason='Every assertion in this authored text unit was examined.') for k in cat['target_text_ids']}
    plan=keyed.KeyedPlan(schema_version=keyed.VERSION,work_id=b.work_id,catalog_sha256=cat['catalog_sha256'],
        completion_state='complete',numeric=numeric,text=text,additional_numeric=[],
        contexts=[c.model_dump() for c in p.claims if c.role not in {'numeric_result','unvalued_result'}],limitations=[])
    # The source explicitly reports two methods sharing one printed thickness.
    # The older transport fixture omitted this distinction in its descriptions.
    thickness=next(e for e in plan.numeric.values() if e.disposition=='outcome' and len(e.records)==2)
    thickness.records[0].description='Total thickness measured by X-ray reflectivity.'
    thickness.records[1].description='Total thickness measured by TEM.'
    selected,_=keyed.project_plan(plan,b)
    bindings=keyed.KeyedBindings(schema_version=keyed.BINDING,work_id=b.work_id,plan_sha256=digest(plan.model_dump()),
        decisions=v.decisions,coverage_checks={k:dict(decision='non_outcome_supported',reason='Authored source review.') for k in role.selected_coverage(selected,cat)})
    return original,b,scope,plan,bindings,rest


def snapshot(pdf=False):
    from test_materials_ner_page_images import png
    original,b,scope,p,v,rest=fixture(pdf)
    images=page_images.freeze(original,[] if not pdf else [dict(pdf_sha256=original.documents[0].source_sha256,
        pdf_page=1,rendering={'producer':'authored-fixture'},raw=png())])
    image_inputs=[dict(path='/authored/'+row['image_id']+'.png',**{k:row[k] for k in ['image_id','sha256','width','height','media_type']}) for row in images['pages']]
    model,inventory,proof=keyed.compile(p,v,b)
    captures=dict(original_bundle=canonical(original.model_dump()),source_bundle=canonical(b.model_dump()),
        source_catalog=canonical(source_catalog(b)),scope=canonical(scope),numeric_catalog=canonical(role.catalog(b)),
        selection_catalog=canonical(role.selection_catalog(b)),source_layout='null',page_images=canonical(images),
        role_image_inputs=canonical(page_images.receipt(image_inputs)),binding_image_inputs=canonical(page_images.receipt(image_inputs)),
        role_prompt=keyed.render(original,b,scope,images),role_schema=canonical(keyed.output_schema(b)),
        role_raw=canonical(p.model_dump()),role_plan=canonical(p.model_dump()),role_validation=canonical(proof['keyed_validation']),
        binding_prompt=keyed.render_bindings(original,b,scope,p,images),binding_schema=canonical(keyed.binding_schema(b,p)),
        binding_raw=canonical(v.model_dump()),bindings=canonical(v.model_dump()),typed_inventory=canonical(model.model_dump()),
        inventory=canonical(inventory.model_dump()),projection=canonical(proof),validation=canonical(proof['typed_projection']['validation']))
    receipt=dict(schema=keyed.ATTEMPT,work_id=b.work_id,status='source_keyed_inventory_valid',terminal=True,
        provider_calls=2,source_unchanged=True,scientific_acceptance=False,full_graph_extraction=False,item_count=len(inventory.items),
        **{k:dict(path='/authored/'+k,sha256=sha(raw.encode())) for k,raw in captures.items()})
    parent=handoff.build(b,receipt_raw=canonical(receipt),captures=captures)
    return b,parent,receipt,captures,rest


def test_records_are_required_under_the_source_and_joins_are_mechanical():
    _,b,_,p,v,_=fixture()
    jsonschema.validate(p.model_dump(),keyed.output_schema(b));jsonschema.validate(v.model_dump(),keyed.binding_schema(b,p))
    selected,mapping=keyed.project_plan(p,b)
    assert all('claim_numbers' not in canonical(entry.model_dump()) for entry in p.numeric.values())
    assert len(mapping)==len(selected.claims)
    model,inventory,proof=keyed.compile(p,v,b)
    assert [e.value_raw for e in model.entries[:-1]]==['39 K','37 K','8 nm','8 nm']
    assert model.entries[-1].type=='unvalued_result'
    assert len([x for x in proof['source_record_mapping'].values() if '/records/' in x['source_record_path']])==4
    assert not proof['scientific_acceptance'] and not proof['full_source_coverage_established']


@pytest.mark.parametrize('variant',['empty_records','missing_records','cross_branch_records','global_claims','numeric_id_in_record','unvalued_field_in_numeric','claim_numbers'])
def test_generation_schema_rejects_missing_records_and_parallel_claim_ledgers(variant):
    _,b,_,p,_,_=fixture();raw=p.model_dump();entry=next(v for v in raw['numeric'].values() if v['disposition']=='outcome')
    if variant=='empty_records':entry['records']=[]
    elif variant=='missing_records':entry.pop('records')
    elif variant=='cross_branch_records':entry['disposition']='condition';entry['reason']='Not a result.'
    elif variant=='global_claims':raw['claims']=[]
    elif variant=='numeric_id_in_record':entry['records'][0]['numeric_candidate_id']='N999'
    elif variant=='unvalued_field_in_numeric':entry['records'][0]['statement']=None
    else:entry['claim_numbers']=[]
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(raw,keyed.output_schema(b))
    with pytest.raises(ValueError):keyed.KeyedPlan.model_validate(raw)


@pytest.mark.parametrize('variant',['partial','insufficient_source','missing_text','missing_numeric','wrong_hash','duplicate_record','bad_anchor','extra_mandatory','unknown_property','unknown_subject','unknown_support'])
def test_incomplete_or_source_invalid_records_cannot_reach_binding(variant):
    _,b,_,p,_,_=fixture()
    record=next(v.records[0] for v in p.numeric.values() if v.disposition=='outcome')
    if variant in {'partial','insufficient_source'}:p.completion_state=variant
    elif variant=='missing_text':p.text.pop(next(iter(p.text)))
    elif variant=='missing_numeric':p.numeric.pop(next(iter(p.numeric)))
    elif variant=='wrong_hash':p.catalog_sha256='0'*64
    elif variant=='duplicate_record':next(v for v in p.numeric.values() if v.disposition=='outcome').records.append(record)
    elif variant=='bad_anchor':next(v for v in p.text.values() if v.unvalued_records).unvalued_records[0].statement.first_text_id='T999'
    elif variant=='extra_mandatory':p.additional_numeric=[keyed.AdditionalNumeric(numeric_candidate_id=next(iter(p.numeric)),records=[record])]
    elif variant=='unknown_property':record.property_evidence.first_text_id='T999'
    elif variant=='unknown_subject':record.subject_evidence[0].first_text_id='T999'
    else:record.support_text_ids=['T999']
    result=keyed.inspect(p,b);assert not result['valid']
    with pytest.raises(ValueError,match='keyed_plan_not_valid'):keyed.binding_schema(b,p)


def test_unresolved_source_assertion_cannot_be_cleared_by_a_non_outcome_vote():
    _,b,_,p,v,_=fixture();key=next(iter(p.text));p.text[key].review='unresolved'
    p.text[key].reason='A second assertion in this unit cannot be assigned to a specimen.'
    v.plan_sha256=digest(p.model_dump());selected,_=keyed.project_plan(p,b)
    v.coverage_checks={k:role.CoverageCheck(decision='non_outcome_supported',reason='Fallible review agrees.') for k in role.selected_coverage(selected,role.selection_catalog(b))}
    model,inventory,proof=keyed.compile(p,v,b)
    assert any(h['claim_id']=='keyed:text:'+key for h in proof['held_outcomes'])
    assert any('cannot be assigned' in c.description for c in model.context_assertions)
    assert not proof['scientific_acceptance']


def test_unresolved_numeric_role_remains_a_hold_after_second_reader_agreement():
    _,b,_,p,v,_=fixture();key=next(k for k,e in p.numeric.items() if e.disposition!='outcome')
    p.numeric[key]=keyed.NumericUnresolved(disposition='unresolved',reason='Could be a reported crossover or a chosen setting.')
    v.plan_sha256=digest(p.model_dump())
    _,_,proof=keyed.compile(p,v,b)
    assert any(h['claim_id']=='keyed:numeric:'+key for h in proof['held_outcomes'])


def test_rehashed_attachment_receipt_cannot_claim_a_different_image():
    b,_,receipt,captures,_=snapshot(pdf=True)
    raw=json.loads(captures['role_image_inputs']);raw['images'][0]['sha256']='f'*64
    captures['role_image_inputs']=canonical(raw);receipt['role_image_inputs']['sha256']=sha(captures['role_image_inputs'].encode())
    with pytest.raises(ValueError,match='page_image_provider_capture_mismatch'):
        handoff.build(b,receipt_raw=canonical(receipt),captures=captures)


@pytest.mark.parametrize('key',keyed.CAPTURE_KEYS)
def test_every_capture_including_pixels_and_provider_attachment_receipts_is_hash_bound(key):
    b,_,receipt,captures,_=snapshot();captures[key]+=' '
    with pytest.raises(ValueError,match='keyed_capture_hash_mismatch'):handoff.build(b,receipt_raw=canonical(receipt),captures=captures)


def test_rehashed_output_rewrite_is_rejected():
    b,_,receipt,captures,_=snapshot();raw=json.loads(captures['role_plan']);raw['completion_state']='partial'
    captures['role_plan']=canonical(raw);receipt['role_plan']['sha256']=sha(captures['role_plan'].encode())
    with pytest.raises(ValueError,match='keyed_output_rewritten'):handoff.build(b,receipt_raw=canonical(receipt),captures=captures)


def test_invalid_receipt_is_rejected_before_missing_captures(tmp_path):
    _,b,*_=fixture();p=tmp_path/'invalid.json';p.write_text(canonical(dict(schema=keyed.ATTEMPT,status='keyed_plan_invalid',terminal=True)))
    with pytest.raises(ValueError,match='source_keyed_receipt_not_admissible'):frozen_inventory.from_files(b,p,None)


def test_real_consumer_and_idempotent_private_import_use_keyed_parent(tmp_path):
    b,parent,_,_,rest=snapshot(pdf=True);catalog,decisions,links=rest
    assert len(frozen_inventory.verify(parent).items)==5
    store=Store(tmp_path/'worker');job=item_worker.enqueue(store,parent,group_size=2)
    result=run_one(store,job_id=job,provider_override=StageProvider(responses(b,catalog,decisions,links)))
    assert result['state']=='succeeded',result
    packet=import_packet(store,job);verify_packet(packet)
    assert packet['receipt']['frozen_source_accounting']['materialized_items']==5
    db=ProposalDatabase(tmp_path/'private')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
