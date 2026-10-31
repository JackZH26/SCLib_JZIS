"""Compact role selections preserve original evidence and complete accounting."""
from copy import deepcopy
import json

import pytest

from ingestion.materials_ner import reviewed_reader as reader, scoped_evidence
from ingestion.materials_ner.census import roles, stage as census
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_census_roles import role_case, Fake, evaluate
from test_materials_ner_source_census import case, response as census_response, Fake as CensusFake
from test_materials_ner_reviewed_proposals import prepared


@pytest.fixture
def compact_case(role_case, tmp_path):
    _, request, p = role_case
    data=json.loads(request.read_bytes())
    data.update(schema=roles.COMPACT_INPUT_SCHEMA, occurrence_ids=list(p['occurrences']))
    new=tmp_path/'compact-input.json';reader.put(new,data)
    return Store(tmp_path/'compact'),new,roles.prepare(new)


def response(p):
    return dict(schema_version=roles.COMPACT_OUTPUT_SCHEMA,limitations=[],decisions={key:dict(
        role='property_result',origin='current_work',basis='measured',witness_ids=[value['owner']],
        note='The original source reports a resistive onset.') for key,value in p['occurrences'].items()})


def test_compact_support_uses_original_units_without_scientific_admission(compact_case):
    store,request,p=compact_case
    fake=Fake(response(p));job=roles.enqueue(store,request);result=roles.run(store,job,provider_override=fake)
    assert result['state']=='succeeded' and result['interface_version']==2
    report=json.loads(reader.checked(result['role_validation']).read_bytes())
    anchor=report['decisions'][0]['evidence'][0]
    block=p['bundle'].blocks[0]
    assert block.text[anchor['start_char']:anchor['end_char']]==anchor['quote']==block.text
    assert roles.run(store,job,provider_override=fake)==result and fake.calls==1
    assert not any(result[k] for k in ['scientific_acceptance','proposal_generated','paper_completed',
        'ml_training_eligible','scientific_roles_reviewed','source_completeness_established'])
    assert 'PRIVATE_CENSUS_DESCRIPTION' not in p['prompt'] and '"category"' not in p['prompt']


@pytest.mark.parametrize('change',['empty','duplicate','unknown','not_list','too_many','extra_key'])
def test_selection_does_not_silently_drop_or_invent_ids(compact_case,tmp_path,change):
    _,request,p=compact_case;data=json.loads(request.read_bytes());ids=data['occurrence_ids']
    if change=='empty': data['occurrence_ids']=[]
    elif change=='duplicate': data['occurrence_ids']=ids*2
    elif change=='unknown': data['occurrence_ids']=['not-an-occurrence']
    elif change=='not_list': data['occurrence_ids']=ids[0]
    elif change=='too_many': data['occurrence_ids']=ids*9
    else: data['assistant_reference']={'role':'property_result'}
    path=tmp_path/'invalid-input.json';reader.put(path,data)
    with pytest.raises(ValueError,match='roles_(occurrence_selection_invalid|input_shape)'):roles.prepare(path)


@pytest.mark.parametrize('change',['missing','extra','unknown_witness','duplicate_witness','retyped_quote','retyped_subject','result_null_basis','condition_nonnull_basis'])
def test_compact_contract_refuses_partial_or_retyped_payloads(compact_case,tmp_path,change):
    _,_,p=compact_case;body=response(p);key=next(iter(body['decisions']));d=body['decisions'][key]
    if change=='missing':body['decisions'].pop(key)
    elif change=='extra':body['decisions']['invented']=deepcopy(d)
    elif change=='unknown_witness':d['witness_ids']=['unknown']
    elif change=='duplicate_witness':d['witness_ids']*=2
    elif change=='retyped_quote':d['quote']='Invented quotation'
    elif change=='retyped_subject':d['subject_raw']='Invented material'
    elif change=='result_null_basis':d['basis']=None
    else:d.update(role='measurement_condition',basis='measured')
    result,report=evaluate(p,body,tmp_path)
    assert result['state']=='quarantined' and (report['schema_issues'] or report['held_decisions'])
    assert json.loads(reader.checked(result['model_roles']).read_bytes())==body


def test_a_structural_role_pass_cannot_certify_correct_science(compact_case,tmp_path):
    _,_,p=compact_case;body=response(p)
    next(iter(body['decisions'].values())).update(role='qualitative_statement',basis=None)
    result,report=evaluate(p,body,tmp_path)
    assert result['state']=='succeeded'  # Deliberately wrong scientific label.
    assert not report['scientific_roles_reviewed'] and not report['scientific_acceptance']


def test_original_value_must_be_covered_even_with_context_ids(compact_case):
    _,_,p=compact_case;p=deepcopy(p);block=p['bundle'].blocks[0];cut=block.text.index('5 K')+1
    p['scope']['passages']=[dict(block_id=block.id,start_char=0,end_char=cut,role='target'),
        dict(block_id=block.id,start_char=cut,end_char=len(block.text),role='target')]
    p['source_catalog']=scoped_evidence.build(p['bundle'],p['scope'])
    occurrence=next(iter(p['occurrences'].values()));decision=next(iter(response(p)['decisions'].values()))
    decision['witness_ids']=['E0002']
    with pytest.raises(ValueError,match='does_not_cover_occurrence'):roles.resolve_support(p,decision,occurrence)
    decision['witness_ids']=['E0001']
    with pytest.raises(ValueError,match='does_not_cover_occurrence'):roles.resolve_support(p,decision,occurrence)
    decision['witness_ids']=['E0001','E0002']
    assert roles.resolve_support(p,decision,occurrence)[0]['quote']==block.text


def test_group_accounting_keeps_unselected_occurrences_and_full_context(case,tmp_path):
    store,source_request,p=case;body=census_response(p);owner=p['targets'][0]
    prototype=body['units'][owner]['occurrences'][0]
    body['units'][owner]['occurrences']=[{**prototype,'value_raw':word,'category':'uncertain'}
        for word in ['The','sample','showed','a','resistive','onset','at','5 K']]
    body['units'][owner]['occurrences'].append({**prototype,'quote':'The criterion is onset.',
        'value_raw':'criterion','category':'uncertain'})
    job=census.enqueue(store,source_request);out=census.run(store,job,provider_override=CensusFake(body))
    assert out['state']=='succeeded' and out['occurrence_count']==9
    data=dict(schema=roles.COMPACT_INPUT_SCHEMA,census_request=reader.reference(source_request),
        census_receipt=reader.reference(census.row(store,job)['result_path']),
        occurrence_ids=[f'{owner}:{i}' for i in range(1,9)])
    path=tmp_path/'group.json';reader.put(path,data);selected=roles.prepare(path)
    assert len(selected['occurrences'])==8 and len(selected['all_occurrence_ids'])==9
    assert selected['unselected_occurrence_ids']==[f'{owner}:9']
    assert selected['source_catalog']==p['source_catalog']
    assert 'The criterion is onset.' in selected['prompt']
    result,report=evaluate(selected,response(selected),tmp_path)
    assert result['total_source_occurrences']==9 and report['unselected_occurrence_ids']==[f'{owner}:9']
    assert not result['paper_completed'] if 'paper_completed' in result else not report['paper_completed']


def test_separate_replicates_have_identical_prompts_but_distinct_jobs(compact_case,tmp_path):
    store,path,p=compact_case;second=tmp_path/'explicit-second-trial.json'
    reader.put(second,json.loads(path.read_bytes()));p2=roles.prepare(second)
    assert p['prompt']==p2['prompt'] and p['schema']==p2['schema']
    first=roles.enqueue(store,path);other=roles.enqueue(store,second);assert first!=other
    fake=Fake(response(p))
    roles.run(store,first,provider_override=fake);roles.run(store,other,provider_override=fake)
    assert fake.calls==2 and store.summary()['attempts']==2
    roles.run(store,first,provider_override=fake);assert fake.calls==2


def test_default_worker_and_full_corpus_do_not_dispatch_compact_roles(compact_case,tmp_path):
    store,path,p=compact_case;job=roles.enqueue(store,path);fake=Fake(response(p))
    assert run_one(store,job_id=job,provider_override=fake) is None and fake.calls==0
    blocked=Store(tmp_path/'full-corpus');(blocked.root/'STAGING_PREPARATION.json').write_text('{}')
    with pytest.raises(ValueError,match='staging_preparation_only'):roles.enqueue(blocked,path)
    assert blocked.summary()['jobs']==0
