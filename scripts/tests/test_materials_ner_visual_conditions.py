"""Synthetic boundary tests; they do not measure scientific accuracy or recall."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ingestion/tests'))
from test_materials_ner_reviewed_proposals import prepared, at, AUTHOR, NOW
from test_materials_ner_visual_regions import region_case
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.sources import Bundle
import materials_ner_visual_conditions as visual


@pytest.fixture
def case(region_case):
    old, _ = region_case
    graph = old['extraction'].model_dump()
    graph['states'][0]['conditions'] = [dict(id='c', kind='temperature', role='measurement',
        quantity=deepcopy(graph['results'][0]['quantity']), orientation_raw=None,
        basis_raw=None, window_position=None)]
    graph['protocols'][0]['context_uses'] = [dict(state_id='st', condition_id='c')]
    return dict(bundle=old['bundle'], graph=graph, scope=old['scope'], assets=old['assets'],
        panels=[dict(id='panel',asset_id=old['assets'][0]['asset_id'],region=[.1,.05,.85,.35],
            caption=at(old['bundle'].blocks[0],old['bundle'].blocks[0].text),
            basis=[at(old['bundle'].blocks[0],old['bundle'].blocks[0].text)],
            protocol_id='p',result_ids=['r'],interpretation_note='Synthetic association.')],
        bindings=[dict(panel_id='panel',state_id='st',condition_id='c',
            selector=dict(line_id='line:0',start_char=5,end_char=8),transcription='5 K',
            interpretation_note='Synthetic numeric label.')],author=deepcopy(AUTHOR),created_at=NOW)


def test_portable_context_binding_preserves_source_and_result_count(case, monkeypatch):
    before = deepcopy(case['bundle'].model_dump()), deepcopy(case['graph'])
    support = visual.build(**case)
    bundle = Bundle.model_validate(json.loads(json.dumps(case['bundle'].model_dump())))
    support = json.loads(json.dumps(support))
    def forbidden(*args, **kwargs): raise AssertionError('Portable replay accessed a file')
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    monkeypatch.setattr(Path, 'read_text', forbidden)
    resolved = visual.resolve(support, bundle, case['graph'], case['scope'])
    assert resolved[0]['path'] == '/states/0/conditions/0/quantity'
    assert resolved[0]['result_ids'] == ['r'] and len(case['graph']['results']) == 1
    assert resolved[0]['normalized']['normalized']['value'] == 5
    assert not {'start_char','end_char','quote','quote_sha256'} & set(resolved[0])
    assert (case['bundle'].model_dump(), case['graph']) == before
    assert not resolved[0]['scientific_acceptance'] and not resolved[0]['ml_training_eligible']


@pytest.mark.parametrize('mutation', ['value','unit','kind','role','unknown_condition',
    'unused_context','other_protocol','cross_sample','wrong_panel','wrong_line',
    'substring','inexact_raw','duplicate_target','duplicate_label','context_page',
    'partial_page','wrong_caption','text_quantity_competition','self_approval'])
def test_source_target_and_relation_conflicts_are_rejected(case, mutation):
    g=case['graph']; c=g['states'][0]['conditions'][0]; binding=case['bindings'][0]
    if mutation=='value': c['quantity']['value']=7
    elif mutation=='unit': c['quantity']['unit']='GPa'
    elif mutation=='kind': c['kind']='pressure'
    elif mutation=='role': c['role']='synthesis'
    elif mutation=='unknown_condition': binding['condition_id']='missing'
    elif mutation=='unused_context': g['protocols'][0]['context_uses']=[]
    elif mutation=='other_protocol':
        other=deepcopy(g['protocols'][0]);other['id']='other';g['protocols'].append(other)
        g['results'][0]['protocol_id']='other'
    elif mutation=='cross_sample':
        other=deepcopy(g['samples'][0]);other['id']='other';g['samples'].append(other)
        other_state=deepcopy(g['states'][0]);other_state.update(id='other-st',sample_id='other')
        g['states'].append(other_state);binding['state_id']='other-st'
        g['protocols'][0]['context_uses'].append(dict(state_id='other-st',condition_id='c'))
    elif mutation=='wrong_panel': case['panels'][0]['region']=[.01,.6,.9,.9]
    elif mutation=='wrong_line': binding['selector']['line_id']='missing'
    elif mutation=='substring': binding['selector']['start_char']=6;binding['transcription']=' K'
    elif mutation=='inexact_raw': c['quantity']['raw']='5.0 K'
    elif mutation=='duplicate_target': case['bindings'].append(deepcopy(binding))
    elif mutation=='duplicate_label':
        other=deepcopy(c);other['id']='second';g['states'][0]['conditions'].append(other)
        g['protocols'][0]['context_uses'].append(dict(state_id='st',condition_id='second'))
        other=deepcopy(binding);other['condition_id']='second';case['bindings'].append(other)
    elif mutation=='context_page': case['scope']['passages'][0]['role']='context'
    elif mutation=='partial_page': case['scope']['passages'][0]['start_char']=1
    elif mutation=='wrong_caption': case['panels'][0]['caption']['quote']='Invented caption'
    elif mutation=='text_quantity_competition':
        g['states'][0]['evidence'].append(dict(field='/conditions/0/quantity',
            **at(case['bundle'].blocks[0],case['bundle'].blocks[0].text)))
    elif mutation=='self_approval': case['author']['kind']='human'
    with pytest.raises(ValueError): visual.build(**case)


@pytest.mark.parametrize('mutation',['graph','bundle','scope','authority','pixels'])
def test_rehashed_support_does_not_weaken_bound_inputs(case, mutation):
    support=visual.build(**case)
    if mutation=='graph': case['graph']['states'][0]['conditions'][0]['quantity']['value']=7
    elif mutation=='bundle': case['bundle'].title='Changed title'
    elif mutation=='scope': case['scope']['passages'][0]['role']='context'
    elif mutation=='authority': support['scientific_acceptance']=True
    elif mutation=='pixels': support['assets'][0]['capture']['pages'][0]['png_base64']='AA=='
    support['support_sha256']=digest({k:v for k,v in support.items() if k!='support_sha256'})
    with pytest.raises(ValueError): visual.resolve(support,case['bundle'],case['graph'],case['scope'])


def test_assessment_keeps_missing_relation_evidence_and_original_native_failure(case):
    support=visual.build(**case)
    report=visual.assess(support,case['bundle'],case['graph'],case['scope'])
    assert not report['native_validation']['valid']
    assert report['numeric_text_holds_addressed_by_visual'] == [dict(
        code='quantity_raw_not_in_field_evidence',path='/states/0/conditions/0/quantity')]
    assert dict(code='field_evidence_missing',path='/protocols/0/context_uses/0') in report['remaining_native_issues']
    assert dict(code='field_evidence_missing',path='/states/0/conditions/0') in report['remaining_native_issues']
    assert not report['production_validator_overridden'] and not report['proposal_import_permitted']
