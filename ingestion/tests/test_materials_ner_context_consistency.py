"""Role-sensitive consistency controls; authored cases are not scientific Gold."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from ingestion.materials_ner import source_projector as stage, projector_proposals as pp
from ingestion.materials_ner import reviewed_reader as reader, projection_binding
from ingestion.materials_ner.contract import Quantity, canonical, digest, parse_extraction
from ingestion.materials_ner.contract_v14 import StateV14
from ingestion.materials_ner.proposals import ProposalDatabase, review_rows, verify_packet
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import (
    CONTEXT_CONSISTENCY_VERSION as VERSION, CONTEXT_VALIDATOR_VERSION,
    validate_extraction, check_consistency_version, training_exclusions,
)
from ingestion.materials_ner.validation_v6 import validate_pressure_consistency
from ingestion.materials_ner.sources import make_blocks
from test_materials_ner_source_focus import focused_case, Fake
from test_materials_ner_catalog_projector import catalog_case
from test_materials_ner_reviewed_proposals import prepared, graph, at


def condition(identifier='pressure', role='measurement', value=1.3, unit='GPa', **updates):
    result = dict(id=identifier, kind='pressure', role=role, orientation_raw=None,
        basis_raw=f'{value} {unit}', window_position=None,
        quantity=Quantity(status='reported', raw=f'{value} {unit}', relation='exact', value=value, unit=unit).model_dump())
    result.update(updates)
    return result


def state(conditions=(), availability='not_reported', selected=None, regime='unknown'):
    return StateV14.model_validate(dict(id='st', sample_id='s', label=None, preparation_raw=None,
        conditions=list(conditions), pressure=dict(availability=availability, regime=regime,
        condition_id=selected, basis_raw='ambient pressure' if regime=='explicit_ambient' else None), evidence=[]))


def issues(s):
    found=[]
    validate_pressure_consistency(SimpleNamespace(states=[s]), lambda code,path:found.append(dict(code=code,path=path)))
    return found


@pytest.mark.parametrize('role', ['measurement', 'simulation'])
@pytest.mark.parametrize('availability,code', [
    ('not_reported', 'pressure_declaration_contradicts_reported_condition'),
    ('not_applicable', 'pressure_declaration_contradicts_reported_condition'),
    ('not_extracted', 'pressure_condition_selection_requires_review'),
    ('not_accessible', 'pressure_condition_selection_requires_review'),
    ('ambiguous', 'pressure_condition_selection_requires_review'),
    ('conflicted', 'pressure_condition_selection_requires_review'),
])
def test_reported_operative_pressure_cannot_disappear_into_missingness(role, availability, code):
    s=state([condition(role=role)], availability); before=canonical(s.model_dump())
    assert issues(s)==[dict(code=code,path='/states/0/pressure')]
    assert canonical(s.model_dump())==before


@pytest.mark.parametrize('role', ['synthesis', 'detection_window', 'study_extent', 'extrapolation_target', 'unknown'])
def test_other_pressure_roles_do_not_define_the_measurement_setting(role):
    assert issues(state([condition(role=role)]))==[]


@pytest.mark.parametrize('status', ['not_reported', 'not_extracted', 'not_accessible', 'ambiguous', 'conflicted', 'not_applicable'])
def test_missing_condition_quantity_does_not_create_a_reported_pressure(status):
    c=condition(quantity=Quantity(status=status).model_dump())
    assert issues(state([c]))==[]


@pytest.mark.parametrize('value', [0, 0.000101325, 1.3])
def test_selected_numeric_pressure_does_not_infer_an_ambient_regime(value):
    s=state([condition(value=value)], 'reported', 'pressure')
    assert issues(s)==[] and s.pressure.regime=='unknown'


def test_qualitative_ambient_needs_no_fabricated_zero_but_does_not_hide_a_numeric_condition():
    s=state(availability='reported', regime='explicit_ambient')
    assert issues(s)==[] and s.conditions==[] and s.pressure.condition_id is None
    for value in (0, 1.3):
        s=state([condition(value=value)], 'reported', regime='explicit_ambient')
        assert issues(s)==[dict(code='pressure_condition_selection_requires_review',path='/states/0/pressure')]


def test_equivalent_units_repeat_but_distinct_or_uncertain_alternatives_need_review():
    first=condition(); equivalent=condition('repeat', value=13, unit='kbar')
    assert issues(state([first,equivalent], 'reported', 'pressure'))==[]
    alternatives=[condition('other',value=2), condition('other',value=13,unit='unregistered')]
    approximate=deepcopy(equivalent); approximate['quantity']['approximate']=True; alternatives.append(approximate)
    for other in alternatives:
        s=state([first,other], 'reported', 'pressure')
        assert issues(s)==[dict(code='pressure_state_alternatives_require_review',path='/states/0/pressure')]
    # Synthesis at a different pressure is a legitimate separate context.
    assert issues(state([first,condition('synthesis',role='synthesis',value=9)], 'reported', 'pressure'))==[]


def test_checked_source_graph_is_held_and_holds_reach_related_results(prepared):
    b=prepared[3].model_copy(deep=True); g=graph(b);g['schema_version']='materials-ner/14'
    text='The measurement pressure was 1.3 GPa.'
    block=make_blocks(b.documents[0].id,[('authored pressure control',text)])[0]
    block.id='authored-pressure';b.blocks.append(block);g['processed_block_ids'].append(block.id)
    s=g['states'][0];s['conditions']=[condition()];s['pressure']['availability']='not_reported'
    s['evidence'] += [dict(field='/conditions/0',**at(block,text))]
    model=parse_extraction(g);before=canonical(model.model_dump())
    old=validate_extraction(model,b);new=validate_extraction(model,b,consistency_version=VERSION)
    assert old['valid'], old['issues']
    assert not new['valid'] and new['validator_version']==CONTEXT_VALIDATOR_VERSION
    assert new['base_validator_version']==old['validator_version']=='materials-ner-validation/1.26.0'
    assert new['context_consistency_version']==VERSION
    assert new['issues']==[dict(code='pressure_declaration_contradicts_reported_condition',path='/states/0/pressure')]
    rows=review_rows(model,new)
    assert rows['states'][0]['review_status']=='quarantined'
    assert 'state_has_validation_issues' in rows['results'][0]['issues']
    assert not training_exclusions(model,b,new)['task_feature_assessment']['results'][0]['tasks']['T2-conditions-tc']['eligible_for_training']
    assert canonical(model.model_dump())==before
    assert validate_extraction(model,b)==old


def select(focused_case,tmp_path):
    request=json.loads(focused_case[0].read_bytes());request['consistency_version']=VERSION
    path=tmp_path/'consistency-request.json';reader.put(path,request)
    return path


def test_new_validator_selection_preserves_native_schema_prompt_and_old_configuration(focused_case,tmp_path):
    path=select(focused_case,tmp_path);old=focused_case[1];new=stage.prepare(path)
    for key in ('prompt','schema','source_catalog','bundle','scope'):assert new[key]==old[key]
    assert 'consistency_version' not in stage.configuration(old)
    assert stage.configuration(new)['consistency_version']==VERSION


@pytest.mark.parametrize('version', [None, '', False, {}, 'materials-context-consistency/2'])
def test_unknown_explicit_validator_selection_rejected_before_dispatch(focused_case,tmp_path,version):
    request=json.loads(focused_case[0].read_bytes());request['consistency_version']=version
    path=tmp_path/'invalid.json';reader.put(path,request);store=Store(tmp_path/'invalid-queue')
    with pytest.raises(ValueError,match='unsupported_context_consistency_version'):stage.enqueue(store,path)
    assert store.summary()['jobs']==0


def test_inapplicable_legacy_contract_cannot_claim_new_validation():
    with pytest.raises(ValueError,match='unsupported_context_consistency_version'):
        check_consistency_version(VERSION,'materials-ner/12')


@pytest.mark.parametrize('conflict', [False,True])
def test_durable_synthetic_run_and_portable_import_retain_version_and_raw_facts(focused_case,tmp_path,monkeypatch,conflict):
    path=select(focused_case,tmp_path);g=deepcopy(focused_case[2])
    if conflict:
        g['states'][0]['conditions']=[condition()]
        g['states'][0]['pressure']['availability']='not_reported'
    store=Store(tmp_path/'synthetic-queue');fake=Fake(g)
    identifier=stage.enqueue(store,path);result=stage.run(store,identifier,provider_override=fake)
    assert result['state']==('quarantined' if conflict else 'succeeded'), result
    assert stage.run(store,identifier,provider_override=fake)==result and fake.calls==1
    packet=pp.build(store.root,identifier)
    v=packet['receipt']['validation'];assert v['context_consistency_version']==VERSION
    assert any(i['code']=='pressure_declaration_contradicts_reported_condition' for i in v['issues'])==conflict
    assert projection_binding.scientific_payload(packet['receipt']['extraction'])==projection_binding.scientific_payload(g)
    db=ProposalDatabase(tmp_path/'synthetic-proposals')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    with db.connect() as c:
        restored=json.loads(c.execute('SELECT payload FROM runs').fetchone()[0])
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
    def forbidden(*a,**k):raise AssertionError('Portable validation read a live file or called a provider.')
    monkeypatch.setattr(reader,'checked',forbidden);monkeypatch.setattr(fake,'extract',forbidden)
    verify_packet(restored)
    assert not restored['scientific_acceptance'] and not restored['ml_training_eligible']
    altered=deepcopy(restored);provenance=altered['receipt']['projector_provenance']
    provenance['config'].pop('consistency_version')
    altered['run_id']=digest(altered['receipt'])
    altered['packet_hash']=digest({k:v for k,v in altered.items() if k!='packet_hash'})
    with pytest.raises(ValueError):verify_packet(altered)
