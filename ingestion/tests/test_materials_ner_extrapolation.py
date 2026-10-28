"""Original-source numeric regression and explicitly authored graph controls.

The source fixture is assistant reviewed, not independent Gold. Structural
fixtures reuse synthetic sample identities and must not become scientific data.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ingestion.materials_ner import quantities_v2, quantities_v3, review_amendments as amendments
from ingestion.materials_ner.contract import Quantity, parse_extraction, canonical
from ingestion.materials_ner.contract_v13 import ExtractionV13
from ingestion.materials_ner.contract_v14 import ExtractionV14, ConditionV14
from ingestion.materials_ner.contract_v10 import ConditionV10
from ingestion.materials_ner.proposals import review_rows
from ingestion.materials_ner.sources import make_blocks
from ingestion.materials_ner.validation import validate_extraction, resolve_evidence, training_exclusions
from ingestion.materials_ner.contract_v11 import PositionedEvidence
from test_materials_ner_reviewed_proposals import graph, prepared, packet, AUTHOR, NOW, at
from test_materials_ner_quantity_adoption import native

CASE=json.loads((Path(__file__).parent/'fixtures/materials_ner_extrapolation_source_case.json').read_bytes())


@pytest.mark.parametrize('case',CASE['quantities'],ids=['inverse-depth','powder-depth','in-plane-depth'])
def test_original_numeric_expressions_units_and_exact_anchors(case):
    q=Quantity.model_validate(case['quantity']);context=CASE['context'];evidence=[]
    for binding in case['evidence']:
        e=PositionedEvidence.model_validate(binding)
        local=e.model_copy(update=dict(start_char=e.start_char-context['start_char'],end_char=e.end_char-context['start_char']))
        assert resolve_evidence(context['quote'],local)==(local.start_char,local.end_char)
        evidence.append(e)
    assert quantities_v3.quantity_source_issues(case['kind'],q,evidence,'/quantity')==[]
    norm=quantities_v3.normalize(case['kind'],q)['normalized']
    expected=CASE['expected_inverse_square_nm'] if case['result_id']=='r1' else q.value
    assert norm['value']==pytest.approx(expected) and norm['approximate'] is True
    assert norm['conversion']['input_unit']==q.unit and norm['conversion']['registry']==quantities_v3.REGISTRY_VERSION


@pytest.mark.parametrize('unit,factor',[(r'$\mu$m$^{-2}$',1e-6),('μm⁻²',1e-6),('µm^-2',1e-6),('um^-2',1e-6),('nm⁻²',1),('m^-2',1e-18)])
@pytest.mark.parametrize('shape',[
    dict(relation='exact',value=7,uncertainty=dict(minus=.2,plus=.3,kind='reported_unspecified',raw='authored asymmetric error')),
    dict(relation='interval',lower=5,upper=7),dict(relation='lt',upper=7),dict(relation='ge',lower=5)])
def test_inverse_square_prefixes_scale_all_endpoints_and_errors(unit,factor,shape):
    q=Quantity.model_validate(dict(status='reported',raw='authored shape control',unit=unit,**shape))
    n=quantities_v3.normalize('inverse_square_penetration_depth',q)['normalized']
    assert n['relation']==q.relation and n['unit']=='nm^-2'
    for key in ('value','lower','upper'):
        if getattr(q,key) is not None:assert n[key]==pytest.approx(getattr(q,key)*factor)
    if q.uncertainty:
        assert n['uncertainty']['minus']==pytest.approx(.2*factor)
        assert n['uncertainty']['plus']==pytest.approx(.3*factor)


@pytest.mark.parametrize('unit',['nm','K','1','cm^-3','meV','μm^2'])
def test_incompatible_physical_dimensions_are_refused(unit):
    q=Quantity.model_validate(dict(status='reported',raw='7',relation='exact',value=7,unit=unit))
    with pytest.raises(ValueError,match='unregistered_unit'):quantities_v3.normalize('inverse_square_penetration_depth',q)


def test_domain_missingness_and_historical_registry_remain_distinct():
    q=Quantity.model_validate(CASE['quantities'][0]['quantity'])
    with pytest.raises(ValueError,match='unregistered_quantity'):quantities_v2.normalize('inverse_square_penetration_depth',q)
    with pytest.raises(ValueError,match='unregistered_unit'):quantities_v3.normalize('superfluid_stiffness',q)
    with pytest.raises(ValueError,match='quantity_outside_domain'):quantities_v3.normalize('inverse_square_penetration_depth',q.model_copy(update={'value':-7}))
    assert quantities_v3.normalize('inverse_square_penetration_depth',Quantity(status='not_extracted'))==dict(status='not_extracted',normalized=None)


def source_graph(prepared):
    b=prepared[3].model_copy(deep=True);g=graph(b)
    block=make_blocks('doc:excerpt-in-authored-wrapper',[('source excerpt in synthetic graph',CASE['context']['quote'])])[0]
    block.document_id=b.documents[0].id;b.blocks.append(block);g['processed_block_ids'].append(block.id)
    g['schema_version']='materials-ner/14';r=g['results'][0];case=CASE['quantities'][0]
    r.update(quantity_kind=case['kind'],quantity_name_raw=case['quantity_name_raw'],quantity=deepcopy(case['quantity']),origin='model_derived',
        definition=dict(criterion='unspecified',criterion_raw=None,parameters=[]))
    r['evidence']=[e for e in r['evidence'] if not (e['field'].startswith('/quantity') or e['field'].startswith('/definition') or e['field']=='/origin')]
    for e in case['evidence']:
        r['evidence'].append(dict(e,block_id=block.id,start_char=e['start_char']-CASE['context']['start_char'],end_char=e['end_char']-CASE['context']['start_char']))
    r['evidence'] += [dict(field=f,**at(block,CASE['basis'])) for f in ('/quantity_kind','/origin')]
    condition=dict(id='target',kind='temperature',role='extrapolation_target',basis_raw=CASE['basis'],orientation_raw=None,
        quantity=dict(status='reported',raw='0',relation='exact',value=0,unit='K'),window_position=None)
    g['states'][0]['conditions']=[condition]
    g['states'][0]['evidence'] += [dict(field=f,**at(block,CASE['basis'])) for f in ('/conditions/0','/conditions/0/role','/conditions/0/basis_raw')]
    return b,g


def test_opt_in_changes_no_field_shapes_and_preserves_previous_roles_and_kinds():
    for collection in ('states','results'):
        assert set(ExtractionV13.model_fields[collection].annotation.__args__[0].model_fields)==set(ExtractionV14.model_fields[collection].annotation.__args__[0].model_fields)
    from typing import get_args
    for field in ('role','kind'):
        assert set(get_args(ConditionV10.model_fields[field].annotation))<=set(get_args(ConditionV14.model_fields[field].annotation))


def test_v14_retains_adopted_properties_and_source_checks():
    b,g,_=native();g['schema_version']='materials-ner/13'
    for state in g['states']:state['pressure']=dict(availability='not_extracted',regime='unknown',condition_id=None,basis_raw=None)
    old=parse_extraction(g);old_check=validate_extraction(old,b)
    new=parse_extraction(dict(g,schema_version='materials-ner/14'));check=validate_extraction(new,b)
    assert check['issues']==old_check['issues']
    assert check['normalized'][f"/results/{len(g['results'])-1}/quantity"]['normalized']['value']==-1.1


def test_extrapolation_requires_literal_basis_and_field_role_witness(prepared):
    b,g=source_graph(prepared);check=validate_extraction(parse_extraction(g),b)
    assert not [i for i in check['issues'] if i['path'].startswith('/results/0/quantity')],check
    assert check['validator_version']=='materials-ner-validation/1.26.0'
    assert check['registry_version']==quantities_v3.REGISTRY_VERSION
    bad=deepcopy(g);bad['states'][0]['conditions'][0]['basis_raw']=None
    with pytest.raises(ValidationError,match='extrapolation_target_requires_source_basis'):parse_extraction(bad)
    bad=deepcopy(g);bad['states'][0]['evidence']=[e for e in bad['states'][0]['evidence'] if e['field']!='/conditions/0/role']
    issues=validate_extraction(parse_extraction(bad),b)['issues']
    assert dict(code='field_evidence_missing',path='/states/0/conditions/0/role') in issues
    bad=deepcopy(g);bad['states'][0]['conditions'][0]['basis_raw']='unreported extrapolation method'
    assert dict(code='source_literal_not_in_field_evidence',path='/states/0/conditions/0/basis_raw') in validate_extraction(parse_extraction(bad),b)['issues']
    with pytest.raises(ValidationError):parse_extraction(dict(g,schema_version='materials-ner/13'))


@pytest.mark.parametrize('origin,code',[('observed','extrapolation_target_observed_result_conflict'),('unknown','extrapolation_target_origin_requires_review')])
def test_invalid_origin_holds_propagate_to_derived_results(prepared,origin,code):
    b,g=source_graph(prepared);r=g['results'][0];r['origin']=origin
    other=deepcopy(r);other['id']='derived';other['origin']='model_derived';other['dependencies']=[dict(result_id=r['id'],relation='derived_from')];g['results'].append(other)
    model=parse_extraction(g);check=validate_extraction(model,b)
    assert dict(code=code,path='/results/0/origin') in check['issues']
    rows=review_rows(model,check)['results']
    assert 'derived_input_has_validation_issues' in rows[1]['issues']


def test_extrapolation_is_not_promoted_to_ml_control_or_label(prepared):
    b,g=source_graph(prepared);model=parse_extraction(g);check=validate_extraction(model,b)
    report=training_exclusions(model,b,check)['task_feature_assessment']
    assert report['schema']=='materials-ner-task-features/4'
    for task in report['results'][0]['tasks'].values():
        assert task['label_candidate'] is None and task['condition_candidates']==[] and not task['eligible_for_training']
        assert 'extrapolation_target_is_not_measured_control' in task['condition_dispositions'][0]['reason_codes']


def test_explicit_upgrade_replays_without_mutating_parent_or_default_projection(prepared):
    from ingestion.materials_ner.reviewed_proposals import validate_graph
    parent=packet(prepared);original=canonical(parent);anchor=at(prepared[3].blocks[0],'The criterion is onset.')
    changes=[dict(path='/schema_version',before='materials-ner/13',after='materials-ner/14',reason='Authored upgrade transport control.',anchors=[anchor])]
    a=amendments.build(parent,bundle=parent['bundle'],changes=changes,reviews=[dict(result_id='r',fields={f:dict(disposition='not_reviewed',note='Authored transport control.',anchors=[]) for f in amendments.FIELDS},holds=[])],author=AUTHOR,created_at=NOW)
    assert amendments.verify(a,parent)==a and canonical(parent)==original and a['affected_result_ids']==['r']
    assert amendments.review_mapping(a)['schema']=='materials-reviewed-result-mapping/1'
    with pytest.raises(ValueError,match='canonical_tc_mapping_contract_not_qualified'):amendments.tc_mapping(a)
    with pytest.raises(ValueError,match='reviewed_proposal_existing_contract_required'):
        validate_graph(a['graph'],prepared[3],{},prepared[4])
    bad=deepcopy(a);bad['changes'][0]['after']='materials-ner/unsupported'
    with pytest.raises(ValueError,match='amendment_contract_upgrade_not_supported'):amendments.verify(bad,parent)
