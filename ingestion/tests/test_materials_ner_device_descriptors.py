"""Real source expressions, synthetic graph controls; no independent Gold."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ingestion.materials_ner.contract import Quantity, parse_extraction
from ingestion.materials_ner.contract_v14 import ConditionV14
from ingestion.materials_ner.contract_v15 import ConditionV15, DefinitionV15
from ingestion.materials_ner import quantities_v3, quantities_v4 as registry
from ingestion.materials_ner.proposals import review_rows
from ingestion.materials_ner.sources import make_blocks
from ingestion.materials_ner.validation import validate_extraction
from test_materials_ner_reviewed_proposals import prepared, graph, at

CASE=json.loads((Path(__file__).parent/'fixtures/materials_ner_device_descriptors_source_case.json').read_bytes())


def descriptors():
    return [dict(id='angle',kind='twist_angle',role='sample_geometry',
        quantity=Quantity(status='reported',raw=r'\sim$1.27$^{\circ}',relation='exact',value=1.27,unit='°',approximate=True).model_dump(),
        basis_raw=CASE['twist']['quote'],orientation_raw=None,window_position=None),
        dict(id='D',kind='reported_displacement_field',role='measurement',
        quantity=Quantity(status='reported',raw='+0.61',relation='exact',value=.61,unit='V/nm').model_dump(),
        basis_raw=CASE['displacement']['quote'],orientation_raw=None,window_position=None)]


def authored_graph(prepared):
    # Deliberately synthetic relationship graph: never scientific device/Tc data.
    b=prepared[3].model_copy(deep=True);g=graph(b);g['schema_version']='materials-ner/15'
    text='\n\n'.join(CASE[k]['quote'] for k in ('twist','displacement','criterion_anchor'))
    block=make_blocks(b.documents[0].id,[('original excerpts in synthetic graph',text)])[0]
    block.id+=':descriptor';b.blocks.append(block);g['processed_block_ids'].append(block.id)
    st=g['states'][0];st['conditions']=descriptors()
    for i,c in enumerate(st['conditions']):
        st['evidence'] += [dict(field=f'/conditions/{i}'+suffix,**at(block,c['basis_raw']))
            for suffix in ('','/kind','/role','/basis_raw','/quantity')]
        st['evidence'].append(dict(field=f'/conditions/{i}/quantity/raw',**at(block,c['quantity']['raw'])))
        if i==1: st['evidence'].append(dict(field=f'/conditions/{i}/quantity/unit',**at(block,'V/nm')))
    r=g['results'][0];r['definition']=dict(criterion='linear_fit_intersection',criterion_raw=CASE['criterion'],parameters=[])
    r['evidence']=[e for e in r['evidence'] if not e['field'].startswith('/definition')]
    r['evidence'] += [dict(field=f'/definition/{k}',**at(block,CASE['criterion'])) for k in ('criterion','criterion_raw')]
    g['limitations'].append('Synthetic relationship graph, not a scientific extraction of the cited paper.')
    return b,g


def test_new_graph_preserves_definitions_conditions_relations_and_authority(prepared):
    b,g=authored_graph(prepared);m=parse_extraction(g);v=validate_extraction(m,b)
    assert v['valid'],v['issues']
    assert v['validator_version']=='materials-ner-validation/1.29.0'
    assert v['registry_version']==registry.REGISTRY_VERSION
    assert v['normalized']['/states/0/conditions/0/quantity']['normalized']['value']==1.27
    assert v['normalized']['/states/0/conditions/1/quantity']['normalized'] is None
    rows=review_rows(m,v)
    assert rows['states'][0]['payload']['conditions']==m.states[0].model_dump()['conditions']
    assert rows['results'][0]['payload']['definition']['criterion']=='linear_fit_intersection'
    assert 'sample_relations' in rows and 'condition_supports' in rows
    assert not v['scientific_acceptance'] and not v['ml_training_eligible']
    from ingestion.materials_ner import task_features
    tasks=task_features.assess_tasks(m,b,v)
    assert tasks['schema']==task_features.DEVICE_VERSION
    task_features.verify_assessment(tasks,m,b,v,dict(task_feature_version=task_features.DEVICE_VERSION,
        task_feature_policy_sha256=task_features.DEVICE_POLICY_SHA256))
    assert 'displacement_field_convention_unresolved' in str(tasks)


@pytest.mark.parametrize('change,code',[('basis','source_literal_not_in_field_evidence'),('missing_kind','field_evidence_missing'),('wrong_sign','numeric_value_disagrees_with_raw'),('wrong_unit','unregistered_reported_displacement_field_unit')])
def test_descriptor_errors_remain_actionable(prepared,change,code):
    b,g=authored_graph(prepared);st=g['states'][0]
    if change=='basis': st['conditions'][1]['basis_raw']='Invented source convention'
    if change=='missing_kind': st['evidence']=[e for e in st['evidence'] if e['field']!='/conditions/1/kind']
    if change=='wrong_sign': st['conditions'][1]['quantity']['value']=-.61
    if change=='wrong_unit': st['conditions'][1]['quantity']['unit']='V'
    v=validate_extraction(parse_extraction(g),b)
    assert not v['valid']
    assert code in {x['code'] for x in v['issues']},v['issues']


def test_old_contract_and_registries_do_not_silently_change():
    for c in descriptors():
        ConditionV15.model_validate(c)
        with pytest.raises(ValidationError): ConditionV14.model_validate(c)
        with pytest.raises(ValidationError): ConditionV15.model_validate(dict(c,basis_raw=None))
        with pytest.raises(ValueError): quantities_v3.normalize(c['kind'],Quantity.model_validate(c['quantity']))
    with pytest.raises(ValidationError): DefinitionV15(criterion='linear_fit_intersection',criterion_raw=None,parameters=[])


@pytest.mark.parametrize('shape',[dict(relation='exact',value=-1.27),dict(relation='interval',lower=-1.3,upper=-1.1),dict(relation='ge',lower=1.27)])
def test_angle_keeps_signed_shapes_without_symmetry_reduction(shape):
    q=Quantity(status='reported',raw='synthetic shape control',unit='°',**shape)
    n=registry.normalize('twist_angle',q)['normalized']
    assert all(n[k]==v for k,v in shape.items()) and n['unit']=='deg'
    assert registry.normalize('twist_angle',Quantity(status='not_extracted'))['normalized'] is None
