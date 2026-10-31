"""Task-specific leakage controls; fixtures are development tests, not Gold."""
from copy import deepcopy
import json

import pytest

from materials_private_fixtures import private_json

from ingestion.materials_ner.contract import digest, parse_extraction
from ingestion.materials_ner.sources import Bundle, make_blocks
from ingestion.materials_ner.task_features import assess_tasks, verify_assessment, VERSION, POLICY_SHA256
from ingestion.materials_ner.validation import validate_extraction, training_exclusions
from ingestion.materials_ner.worker import configuration, run_one
from ingestion.materials_ner.wire_v8 import RelationalExtraction
from ingestion.materials_ner.wire_v10 import DetectionExtraction
from ingestion.materials_ner import item_worker, selected_catalog_stages as selected
from ingestion.materials_ner.proposals import import_packet, verify_packet
from ingestion.materials_ner.store import Store
from test_materials_ner_pipeline import example, quantity
from test_materials_ner_relations import fixture as relation_fixture
from test_materials_ner_non_detection_targets import fixture as negative_fixture, window
from test_materials_ner_selected_catalog_stages import worker_outputs
from test_materials_ner_item_stages import parent_packet, StageProvider

T1='T1-composition-tc'
T2='T2-conditions-tc'
T3='T3-computed-tc'
T4='T4-superconductivity-non-detection'


def assessed(bundle,raw):
    graph=parse_extraction(raw) if isinstance(raw,dict) else raw
    check=validate_extraction(graph,bundle)
    return graph,check,assess_tasks(graph,bundle,check)


def task(report,task_id=T2,index=0):
    return report['results'][index]['tasks'][task_id]


def add_temperature(bundle,raw,value=39,role='measurement'):
    wording=f'The reported {role} temperature was {value} K.'
    block=make_blocks(bundle.documents[0].id,[('synthetic:temperature',wording)])[0]
    block.id='block:synthetic-temperature'
    bundle.blocks.append(block);raw['processed_block_ids'].append(block.id)
    raw['states'][0]['conditions'].append(dict(kind='temperature',role=role,quantity=quantity(value,'K',f'{value} K'),
        orientation_raw=None,basis_raw=None))
    raw['states'][0]['evidence'].append(dict(block_id=block.id,quote=wording,field='/conditions/1'))


def test_actual_luna_target_temperature_failure_is_excluded_without_changing_source_graph():
    case=private_json('materials_ner_task_feature_failure.json')
    bundle=Bundle.model_validate(case['bundle']);raw=case['extraction'];before=deepcopy(raw)
    graph,check,report=assessed(bundle,raw)
    assert len(report['results'])==2
    assert all(len(r['diagnostics'])==1 for r in report['results'])
    for row in report['results']:
        assert row['diagnostics'][0]['scientific_error_established'] is False
        for key in (T1,T2,T3):
            temperatures=[x for x in row['tasks'][key]['condition_dispositions'] if x['kind']=='temperature']
            assert len(temperatures)==1 and temperatures[0]['disposition']=='excluded'
            assert 'temperature_not_an_input_for_this_tc_task' in temperatures[0]['reason_codes']
            assert 'normalized' not in temperatures[0]
        assert not any(c['kind']=='temperature' for c in row['tasks'][T2]['condition_candidates'])
    assert raw==before and graph.model_dump()==raw
    assert report['validation_sha256']==digest(check)
    assert not report['training_matrix_created'] and not report['source_graph_modified']
    assert not case['scientific_acceptance'] and not report['ml_training_eligible']


@pytest.mark.parametrize('role,value',[('measurement',39),('measurement',40),('synthesis',39),('synthesis',800)])
def test_all_tc_task_temperatures_are_excluded_but_equality_alone_is_not_error(role,value):
    bundle,raw=example();add_temperature(bundle,raw,value,role)
    _,check,report=assessed(bundle,raw)
    assert check['valid'],check['issues']
    assert bool(report['results'][0]['diagnostics'])==(value==39)
    assert not task(report,T1)['condition_candidates']
    features=task(report,T2)['condition_candidates']
    assert len(features)==1 and features[0]['kind']=='pressure'
    assert features[0]['quantity']['value']==2 and features[0]['quantity']['unit']=='GPa'
    assert all(not d['scientific_error_established'] for d in report['results'][0]['diagnostics'])


@pytest.mark.parametrize('origin,expected',[
    ('observed',{T1,T2}),('computed',{T3}),('model_derived',set()),('unknown',set())])
def test_observed_computed_and_model_derived_labels_are_separate(origin,expected):
    bundle,raw=example();raw['results'][0]['origin']=origin
    if origin=='computed':raw['states'][0]['conditions'][0]['role']='simulation'
    _,_,report=assessed(bundle,raw)
    assert {k for k,v in report['results'][0]['tasks'].items() if v['label_candidate']}==expected
    assert all(not t['eligible_for_training'] for t in report['results'][0]['tasks'].values())
    if origin=='computed':
        assert task(report,T3)['condition_candidates'][0]['role']=='simulation'


@pytest.mark.parametrize('mutation',['cited','unspecified','approximate','interval'])
def test_non_point_unresolved_and_cited_labels_do_not_enter_observed_tc_task(mutation):
    bundle,raw=example();r=raw['results'][0]
    if mutation=='cited':r.update(source_role='cited',cited_source_raw='Prior study')
    elif mutation=='unspecified':raw['protocols'][0].update(criterion='unspecified',criterion_raw=None)
    elif mutation=='approximate':r['quantity']['approximate']=True
    else:r['quantity'].update(relation='interval',value=None,lower=38,upper=39)
    _,_,report=assessed(bundle,raw)
    assert task(report)['label_candidate'] is None
    assert not task(report)['condition_candidates']


@pytest.mark.parametrize('mutation',['absent','not_reported','zero','interval','uncertainty'])
def test_no_implicit_ambient_or_imputation_and_full_quantity_shapes_survive(mutation):
    bundle,raw=example();c=raw['states'][0]['conditions'][0]
    if mutation=='absent':raw['states'][0]['conditions']=[];raw['states'][0]['evidence']=[]
    elif mutation=='not_reported':c['quantity']={'status':'not_reported'}
    else:
        if mutation=='zero':c['quantity']=quantity(0,'GPa','0 GPa')
        elif mutation=='interval':c['quantity']=quantity(None,'GPa','1-2 GPa',relation='interval',lower=1,upper=2)
        else:c['quantity']=quantity(2,'GPa','2 +/- 0.1 GPa',uncertainty={
            'minus':0.1,'plus':0.1,'kind':'reported_unspecified','raw':'+/- 0.1 GPa'})
        quote='The measurement pressure was '+c['quantity']['raw']+'.'
        block=make_blocks(bundle.documents[0].id,[('synthetic:pressure',quote)])[0]
        block.id='block:synthetic-pressure'
        bundle.blocks.append(block);raw['processed_block_ids'].append(block.id)
        raw['states'][0]['evidence']=[e for e in raw['states'][0]['evidence'] if e['field']!='/conditions/0']
        raw['states'][0]['evidence'].append(dict(block_id=block.id,quote=quote,field='/conditions/0'))
    _,check,report=assessed(bundle,raw);features=task(report)['condition_candidates']
    if mutation in {'absent','not_reported'}:assert not features
    else:
        assert check['valid'],check['issues']
        q=features[0]['quantity']
        if mutation=='zero':assert q['value']==0
        elif mutation=='interval':assert 'value' not in q and (q['lower'],q['upper'])==(1,2)
        else:assert q['uncertainty']['minus']==q['uncertainty']['plus']==0.1


@pytest.mark.parametrize('relation,excluded',[
    ('derived_from',True),('same_measurement',True),('compares_with',False),('none',False)])
def test_feature_support_checks_causal_ancestry_without_treating_comparison_as_causality(relation,excluded):
    bundle,_,raw=relation_fixture()
    if relation!='none':
        raw['observations'][2]['result']['dependencies']=[dict(result_id=raw['observations'][0]['id'],relation=relation)]
    graph=RelationalExtraction.model_validate(raw).expand(bundle)
    _,_,report=assessed(bundle,graph);t=task(report)
    disposition=t['condition_dispositions'][0]
    assert (disposition['disposition']=='excluded')==excluded
    if relation=='derived_from':assert 'feature_has_outcome_ancestor' in disposition['reason_codes']
    if relation=='same_measurement':assert 'feature_shares_outcome_measurement_requires_review' in disposition['reason_codes']
    if not excluded:
        q=t['condition_candidates'][0]['quantity']
        assert q['value']==8 and q['unit']=='nm'


def test_transitive_outcome_ancestor_cannot_reenter_as_independently_measured_geometry():
    bundle,_,raw=relation_fixture();observations=raw['observations']
    observations[2]['result']['dependencies']=[dict(result_id=observations[3]['id'],relation='derived_from')]
    observations[3]['result']['dependencies']=[dict(result_id=observations[0]['id'],relation='derived_from')]
    _,_,report=assessed(bundle,RelationalExtraction.model_validate(raw).expand(bundle))
    assert 'feature_has_outcome_ancestor' in task(report)['condition_dispositions'][0]['reason_codes']


@pytest.mark.parametrize('relation',['same_measurement','compares_with'])
def test_same_measurement_is_symmetric_but_a_reverse_comparison_is_not_a_dependency(relation):
    bundle,_,raw=relation_fixture();observations=raw['observations']
    observations[0]['result']['dependencies']=[dict(result_id=observations[2]['id'],relation=relation)]
    _,_,report=assessed(bundle,RelationalExtraction.model_validate(raw).expand(bundle))
    disposition=task(report)['condition_dispositions'][0]
    assert ('feature_shares_outcome_measurement_requires_review' in disposition['reason_codes'])==(relation=='same_measurement')
    assert bool(task(report)['condition_candidates'])==(relation=='compares_with')


@pytest.mark.parametrize('target',['superconductivity','supercurrent','josephson_phase_transition'])
def test_negative_target_and_window_scope_never_become_tc_zero_or_intrinsic_nonsuperconductor(target):
    bundle,_,raw=negative_fixture(target);window(bundle,raw)
    _,check,report=assessed(bundle,DetectionExtraction.model_validate(raw).expand(bundle))
    assert check['valid'],check['issues']
    t=task(report,T4,-1)
    if target=='superconductivity':
        assert t['label_candidate']['tc_kelvin'] is None
        assert t['label_candidate']['intrinsic_superconductivity_status']=='not_established'
        w=next(c for c in t['condition_candidates'] if c['condition_id']=='W')
        assert w['quantity']['value']==1.8 and w['window_position']=='lower_limit'
    else:
        assert t['label_candidate'] is None and not t['condition_candidates']
    assert all(task(report,k,-1)['label_candidate'] is None for k in (T1,T2,T3))


@pytest.mark.parametrize('mutation',['no_window','unreported','wrong_role','no_endpoint','foreign_id'])
def test_unresolved_negative_windows_remain_out_of_label_scope(mutation):
    bundle,_,raw=negative_fixture('superconductivity')
    if mutation!='no_window':
        c=window(bundle,raw)
        if mutation=='unreported':c['quantity']={'status':'not_reported'}
        elif mutation=='wrong_role':c['role']='measurement';c['window_position']=None
        elif mutation=='no_endpoint':c['window_position']='unspecified'
        else:raw['observations'][-1]['result']['qualifiers'][0]['window_condition_ids']=['missing']
    _,_,report=assessed(bundle,DetectionExtraction.model_validate(raw).expand(bundle))
    assert task(report,T4,-1)['label_candidate'] is None
    assert not task(report,T4,-1)['condition_candidates']


@pytest.mark.parametrize('mutation',['extraction','bundle','audit','policy','version','validation'])
def test_audit_bindings_and_policy_tampering_fail_closed(mutation):
    bundle,raw=example();graph,check,report=assessed(bundle,raw);config=configuration()
    assert config['task_feature_version']==VERSION and config['task_feature_policy_sha256']==POLICY_SHA256
    verify_assessment(json.loads(json.dumps(report)),graph,bundle,check,config)
    if mutation=='extraction':graph.results[0].quantity.value=40
    elif mutation=='bundle':bundle.title='changed'
    elif mutation=='audit':report['results'][0]['tasks'][T2]['eligible_for_training']=True
    elif mutation=='policy':config['task_feature_policy_sha256']='0'*64
    elif mutation=='version':config['task_feature_version']='unknown'
    else:check['issues'].append(dict(path='/results/0',code='new_issue'))
    with pytest.raises(ValueError,match='task_feature_'):verify_assessment(report,graph,bundle,check,config)


def test_worker_and_packet_recompute_new_audits_and_reject_rehashed_tampering(tmp_path):
    parent,_,_,_,_=parent_packet(tmp_path/'parent');bundle,outputs=worker_outputs()
    store=Store(tmp_path/'worker');job=item_worker.enqueue(store,parent,workflow=selected.WORKFLOW)
    outcome=run_one(store,job_id=job,provider_override=StageProvider(outputs))
    assert outcome['state']=='succeeded'
    packet=import_packet(store,job);verify_packet(json.loads(json.dumps(packet)))
    for mutation in ('audit','remove','pin'):
        bad=deepcopy(packet);receipt=bad['receipt']
        if mutation=='audit':receipt['training_assessment']['task_feature_assessment']['ml_training_eligible']=True
        elif mutation=='remove':receipt['training_assessment'].pop('task_feature_assessment')
        else:receipt['config']['task_feature_policy_sha256']='0'*64
        bad['run_id']=digest(receipt);bad['packet_hash']=digest({k:v for k,v in bad.items() if k!='packet_hash'})
        with pytest.raises(ValueError,match='task_feature_'):verify_packet(bad)
    graph=parse_extraction(packet['receipt']['extraction'])
    assessment=training_exclusions(graph,bundle,packet['receipt']['validation'])
    assert all(not row['eligible'] for row in assessment['results'])
