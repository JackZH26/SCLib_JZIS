"""Partial diagnostic review must preserve evidence and never promote eligibility."""
from copy import deepcopy
import json
import jsonschema
import pytest
from ingestion.materials_ner import source_piece_review as review, source_piece_inventory as pieces
from ingestion.materials_ner import source_role_inventory as role, typed_inventory_handoff as handoff
from ingestion.materials_ner.contract import canonical,digest
from ingestion.materials_ner.sources import sha
from test_materials_ner_source_pieces import snapshot


def fixture():
    bundle,_,receipt,captures,_=snapshot(continuation=True)
    captures={k:captures[k] for k in review.CAPTURE_KEYS}
    plan=pieces.KeyedPlan.model_validate_json(captures['role_raw']);plan.completion_state='partial'
    target=next(iter(plan.text));plan.text[target].review='unresolved';plan.text[target].reason='Boundary assertion requires review.'
    numeric=next((k for k,v in plan.numeric.items() if v.disposition!='outcome'),None)
    if numeric is not None:
        from ingestion.materials_ner.source_keyed_inventory import NumericUnresolved
        plan.numeric[numeric]=NumericUnresolved(disposition='unresolved',reason='Known number has unresolved ownership.')
    first=next(r for r,_,_,_,_ in pieces.records(plan,role.selection_catalog(bundle)))
    plan.contexts.append(pieces.ContextRecord(**dict(first.model_dump(),role='context')))
    for k,val in [('role_raw',plan.model_dump()),('role_plan',plan.model_dump()),('role_validation',pieces.inspect(plan,bundle))]:captures[k]=canonical(val)
    receipt=dict(schema=pieces.ATTEMPT,work_id=bundle.work_id,status='piece_plan_invalid',terminal=True,
        source_unchanged=True,scientific_acceptance=False,full_graph_extraction=False,provider_calls=1,
        **{k:dict(path='/authored/'+k,sha256=sha(v.encode())) for k,v in captures.items()})
    receipt['provider_responses']=[dict(stage='role',raw_output=receipt['role_raw'])]
    parent=review._build(canonical(receipt),captures,None)
    cat=role.selection_catalog(bundle)
    records={}
    for key,row in parent['records'].items():
        ids=list(dict.fromkeys(p['text_id'] for p in row['evidence']))[:2]
        records[key]=dict(decision='hold',proposed_role=row['role'],interpretation='Retained source proposal requires binding review.',
            checks={name:dict(status='unresolved',text_ids=ids,reason='Source binding requires adjudication.') for name in review.CHECKS},related_record_ids=[])
    numbers={}
    for key in parent['numeric_obligation_ids']:
        n=cat['numeric_catalog']['numeric_candidates'][key]
        ids=[k for k,t in cat['texts'].items() if t['block_id']==n['block_id'] and t['start_char']<n['end_char'] and t['end_char']>n['start_char']]
        numbers[key]=dict(decision='unresolved',record_ids=[],text_ids=ids,reason='Keep the original number while identity remains unresolved.')
    texts={k:dict(decision='unresolved',record_ids=[],text_ids=[k],reason='The original target assertion remains open.') for k in parent['text_obligation_ids']}
    result=review.Review(schema_version=review.VERSION,parent_id=parent['parent_id'],work_id=bundle.work_id,
        record_reviews=records,numeric_reviews=numbers,text_reviews=texts,limitations=['Authored diagnostic fixture; no scientific approval.'])
    return bundle,parent,result


def test_partial_review_preserves_context_records_and_every_original_obligation():
    bundle,parent,result=fixture()
    assert review.verify_parent(parent)==bundle
    assert parent['original_completion_state']=='partial' and parent['original_unresolved_text_ids']
    assert any(r['role']=='context' for r in parent['records'].values())
    jsonschema.validate(result.model_dump(),review.output_schema(parent))
    assert review.inspect(result,parent)['valid']
    raw=canonical(result.model_dump());packet=review.assemble(parent,raw)
    assert review.verify_packet(packet)==packet and packet['raw_review']==raw
    assert packet['parent']==parent and packet['original_completion_state']=='partial'
    assert packet['coverage_debt']['original_text']==parent['original_unresolved_text_ids']
    for key in ['full_source_coverage_established','scientific_acceptance','canonical_eligible','ml_training_eligible']:assert packet[key] is False
    with pytest.raises(ValueError,match='typed_frozen_receipt_not_admissible'):
        handoff.build(bundle,receipt_raw=canonical(packet),captures={})
    with pytest.raises(ValueError,match='source_piece_receipt_not_admissible'):
        handoff.build(bundle,receipt_raw=parent['source_receipt_raw'],captures=parent['captures'])


@pytest.mark.parametrize('name',['record_reviews','numeric_reviews','text_reviews'])
def test_omitted_or_unknown_review_keys_are_not_complete_accounting(name):
    _,parent,result=fixture();values=getattr(result,name);key=next(iter(values));value=values.pop(key)
    assert any(i['code']=='review_key_coverage_mismatch' for i in review.inspect(result,parent)['issues'])
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(result.model_dump(),review.output_schema(parent))
    values['UNKNOWN']=value
    assert not review.inspect(result,parent)['valid']


@pytest.mark.parametrize('field',review.CAPTURE_KEYS)
def test_parent_rejects_every_modified_first_read_capture(field):
    _,parent,_=fixture();captures=deepcopy(parent['captures']);captures[field]+=' '
    with pytest.raises(ValueError,match='partial_review_capture_hash_mismatch'):
        review._build(parent['source_receipt_raw'],captures,None)


def test_rehashed_original_output_change_cannot_replace_original_plan():
    _,parent,_=fixture();caps=deepcopy(parent['captures']);raw=json.loads(caps['role_raw']);raw['limitations'].append('Changed output.')
    caps['role_raw']=canonical(raw);receipt=json.loads(parent['source_receipt_raw']);receipt['role_raw']['sha256']=sha(caps['role_raw'].encode());receipt['provider_responses'][0]['raw_output']=deepcopy(receipt['role_raw'])
    with pytest.raises(ValueError,match='partial_review_original_output_rewritten'):review._build(canonical(receipt),caps,None)


def test_rehashed_parent_cannot_erase_coverage_debt_or_promote_completion():
    _,parent,_=fixture()
    for key,value in [('original_completion_state','complete'),('original_unresolved_text_ids',[]),('canonical_eligible',True),('scientific_acceptance',True)]:
        changed=deepcopy(parent);changed[key]=value;changed['parent_id']=digest({k:v for k,v in changed.items() if k!='parent_id'})
        with pytest.raises(ValueError,match='partial_review_parent_changed'):review.verify_parent(changed)


def test_other_structural_failures_cannot_enter_review_only_route():
    bundle,parent,_=fixture();caps=deepcopy(parent['captures']);plan=pieces.KeyedPlan.model_validate_json(caps['role_raw'])
    plan.contexts[0].subject_text_ids=['T_UNKNOWN'];receipt=json.loads(parent['source_receipt_raw'])
    for key,val in [('role_raw',plan.model_dump()),('role_plan',plan.model_dump()),('role_validation',pieces.inspect(plan,bundle))]:
        caps[key]=canonical(val);receipt[key]['sha256']=sha(caps[key].encode())
    receipt['provider_responses'][0]['raw_output']=deepcopy(receipt['role_raw'])
    with pytest.raises(ValueError,match='partial_review_structural_failure'):review._build(canonical(receipt),caps,None)


@pytest.mark.parametrize('check',review.CHECKS)
def test_supported_or_revised_checks_require_original_witnesses(check):
    _,parent,result=fixture();row=next(iter(result.record_reviews.values()));c=getattr(row.checks,check)
    c.status='supported';c.text_ids=[]
    assert any(i['code']=='review_witness_required' for i in review.inspect(result,parent)['issues'])
    c.text_ids=['T_UNKNOWN']
    assert any(i['code']=='review_unknown_reference' for i in review.inspect(result,parent)['issues'])


def test_context_claim_cannot_be_silently_retained_with_uncertain_subject():
    _,parent,result=fixture();key=next(k for k,v in parent['records'].items() if v['role']=='context')
    result.record_reviews[key].decision='retain_candidate'
    assert any(i['code']=='review_retention_inconsistent' for i in review.inspect(result,parent)['issues'])
    with pytest.raises(ValueError,match='partial_review_annotations_invalid'):review.assemble(parent,canonical(result.model_dump()))


def test_numeric_witness_must_locate_the_actual_number_and_text_anchor_is_required():
    _,parent,result=fixture();cat=role.selection_catalog(review.verify_parent(parent));key=next(iter(result.numeric_reviews))
    n=cat['numeric_catalog']['numeric_candidates'][key]
    other=next(k for k,v in cat['texts'].items() if v['block_id']!=n['block_id'])
    result.numeric_reviews[key].text_ids=[other]
    t=next(iter(result.text_reviews));result.text_reviews[t].text_ids=[other]
    codes={i['code'] for i in review.inspect(result,parent)['issues']}
    assert {'review_numeric_witness_disconnected','review_text_anchor_missing'}<=codes


def test_represented_obligation_requires_a_record_and_relations_cannot_self_link():
    _,parent,result=fixture();row=next(iter(result.numeric_reviews.values()));row.decision='represented';row.record_ids=[]
    a=next(iter(result.record_reviews));result.record_reviews[a].related_record_ids=[a]
    codes={i['code'] for i in review.inspect(result,parent)['issues']}
    assert {'review_representation_without_record','review_self_relation'}<=codes


@pytest.mark.parametrize('key,value',[('scientific_acceptance',True),('canonical_eligible',True),('ml_training_eligible',True),('full_source_coverage_established',True),('original_completion_state','complete')])
def test_even_rehashed_review_packets_cannot_promote_acceptance(key,value):
    _,parent,result=fixture();packet=review.assemble(parent,canonical(result.model_dump()));packet[key]=value
    packet['packet_id']=digest({k:v for k,v in packet.items() if k!='packet_id'})
    with pytest.raises(ValueError,match='partial_review_packet_changed'):review.verify_packet(packet)


def test_schema_and_prompt_include_all_sources_and_separate_target_from_availability():
    bundle,parent,_=fixture();text=review.render(parent)
    assert 'SOURCE AVAILABILITY:' in text and 'TARGET identifies coverage responsibility, not availability.' in text
    assert 'B_CONTEXT' in text and 'context' in text and 'PARENT ID: '+parent['parent_id'] in text
    schema=review.output_schema(parent);jsonschema.Draft202012Validator.check_schema(schema)
    assert schema['properties']['record_reviews']['required']==list(parent['records'])
    assert schema['properties']['numeric_reviews']['required']==parent['numeric_obligation_ids']
    assert schema['properties']['text_reviews']['required']==parent['text_obligation_ids']
