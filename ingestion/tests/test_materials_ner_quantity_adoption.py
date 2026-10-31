"""Located source quantities plus authored transport tests; no Gold labels."""
from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner import quantities, quantities_v2 as adopted
from ingestion.materials_ner import typed_inventory as typed, typed_inventory_v2 as typed2
from ingestion.materials_ner import task_features
from ingestion.materials_ner.contract import Quantity, parse_extraction
from ingestion.materials_ner.contract_v11 import PositionedEvidence
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.proposals import review_rows
from ingestion.materials_ner.sources import make_blocks
from ingestion.materials_ner.validation import validate_extraction, resolve_evidence
from ingestion.materials_ner.wire_v9 import ScopedExtraction
from test_materials_ner_pipeline import quantity
from test_materials_ner_scoped_conditions import fixture
from test_materials_ner_typed_inventory import inputs

CASES=json.loads((Path(__file__).parent/'fixtures/materials_ner_quantity_adoption_source_cases.json').read_bytes())['cases']


@pytest.mark.parametrize('case',CASES,ids=['slope-helium','slope-anvil','resistivity-reference'])
def test_original_pdf_numeric_shape_unit_uncertainty_and_positions(case):
    q=Quantity.model_validate(case['quantity']);source=case['source'];context=case['context'][0]['source']
    evidence=[]
    for key in ('raw','unit'):
        witness=source['evidence'][key]
        e=PositionedEvidence(block_id=source['block_id'],quote=witness['quote'],field='/quantity/'+key,
            start_char=witness['start_char'],end_char=witness['end_char'])
        # The complete original block is verified separately in the source audit.
        snippet=context['quote'];offset=context['start_char']
        local=e.model_copy(update={'start_char':e.start_char-offset,'end_char':e.end_char-offset})
        assert resolve_evidence(snippet,local)==(local.start_char,local.end_char)
        evidence.append(e)
    assert adopted.quantity_source_issues(case['kind'],q,evidence,'/quantity')==[]
    value=adopted.normalize(case['kind'],q)['normalized']
    assert value['value']==pytest.approx(case['expected_value'])
    assert value['unit']==case['expected_unit']
    assert value['uncertainty']['plus']==pytest.approx(case['expected_error'])
    assert value['uncertainty']['minus']==pytest.approx(case['expected_error'])
    assert value['approximate']==q.approximate
    assert value['conversion']['input_unit']==q.unit
    assert value['conversion']['registry']==adopted.REGISTRY_VERSION
    with pytest.raises(ValueError,match='unregistered_quantity'):quantities.normalize(case['kind'],q)


@pytest.mark.parametrize('kind,unit,value,expected',[
    ('tc_pressure_slope','K/kbar',-.11,-1.1),('tc_pressure_slope','mK/GPa',-1100,-1.1),
    ('electrical_resistivity','Ω cm',.0003,3e-6),('electrical_resistivity','mΩ cm',.3,3e-6)])
def test_prefixes_and_signed_derivative_preserve_dimensions(kind,unit,value,expected):
    result=adopted.normalize(kind,Quantity.model_validate(quantity(value,unit,f'{value} {unit}')))
    assert result['normalized']['value']==pytest.approx(expected)


@pytest.mark.parametrize('kind,unit',[('tc_pressure_slope','K'),('tc_pressure_slope','GPa'),
    ('electrical_resistivity','Ω'),('electrical_resistivity','Ω/square'),('electrical_resistivity','1')])
def test_resistance_and_normalized_trace_cannot_be_called_resistivity(kind,unit):
    with pytest.raises(ValueError,match='unregistered_unit'):
        adopted.normalize(kind,Quantity.model_validate(quantity(1,unit,f'1 {unit}')))


def test_resistivity_domain_does_not_restrict_signed_slope():
    with pytest.raises(ValueError,match='quantity_outside_domain'):
        adopted.normalize('electrical_resistivity',Quantity.model_validate(quantity(-1,'Ω m','-1 Ω m')))
    assert adopted.normalize('tc_pressure_slope',Quantity.model_validate(quantity(-1,'K/GPa','-1 K/GPa')))['normalized']['value']==-1


def native(kind='tc_pressure_slope'):
    b,_,wire=fixture();old=ScopedExtraction.model_validate(wire).expand(b).model_dump()
    raw=deepcopy(old);raw['schema_version']='materials-ner/12'
    case=CASES[0 if kind=='tc_pressure_slope' else 2]
    name='dTc /dp' if kind=='tc_pressure_slope' else 'absolute resistivity'
    words=f'AUTHORED TRANSPORT TEST. Sample A has {name} {case["quantity"]["raw"]}. This is an authored observed primary result.'
    block=make_blocks('doc:adopted-authored',[('synthetic:quantity',words)])[0]
    block.document_id=b.documents[0].id;b.blocks.append(block);raw['processed_block_ids'].append(block.id)
    r=deepcopy(raw['results'][0]);r.update(id='adopted',quantity_kind=kind,quantity=deepcopy(case['quantity']),
        quantity_name_raw=name,definition=dict(criterion='unspecified',criterion_raw=None,parameters=[]),
        dependencies=[],qualifiers=[])
    r['evidence']=[dict(block_id=block.id,quote=words,field=f) for f in
        ('/quantity','/quantity_kind','/quantity_name_raw','/sample_id','/state_id','/protocol_id','/origin','/source_role')]
    for key in ('raw','unit'):
        literal=r['quantity'][key];start=words.index(literal)
        r['evidence'].append(dict(block_id=block.id,quote=literal,field='/quantity/'+key,start_char=start,end_char=start+len(literal)))
    raw['results'].append(r)
    return b,raw,old


@pytest.mark.parametrize('kind',list(adopted.ADDITIONS))
def test_opt_in_native_proposal_preserves_source_and_normalization(kind):
    b,raw,_=native(kind);model=parse_extraction(raw);report=validate_extraction(model,b)
    assert report['valid'],report['issues']
    assert report['validator_version']=='materials-ner-validation/1.23.0'
    assert report['registry_version']==adopted.REGISTRY_VERSION
    row=review_rows(model,report)['results'][-1]
    assert row['payload']==model.results[-1].model_dump() and row['review_status']=='pending_review'
    assert len(row['normalized'])==1
    assert not report['scientific_acceptance'] and not report['ml_training_eligible']
    with pytest.raises(ValidationError):parse_extraction(dict(raw,schema_version='materials-ner/11'))


@pytest.mark.parametrize('error,code',[('name','adopted_quantity_source_name_not_literal'),
    ('sign','numeric_value_disagrees_with_raw'),('uncertainty','uncertainty_disagrees_with_raw'),
    ('unit','field_unit_witness_mismatch'),('position','evidence_position_quote_mismatch')])
def test_native_rejects_scientific_shape_and_binding_corruption(error,code):
    b,raw,_=native();r=raw['results'][-1]
    if error=='name':r['quantity_name_raw']='unreported property'
    elif error=='sign':r['quantity']['value']=1.1
    elif error=='uncertainty':r['quantity']['uncertainty']['plus']=1
    elif error=='unit':r['quantity']['unit']='K/kbar'
    else:r['evidence'][-1]['start_char']-=1
    report=validate_extraction(parse_extraction(raw),b)
    assert code in {i['code'] for i in report['issues']}
    assert not report['valid']


def test_native_requires_explicit_source_quantity_name():
    b,raw,_=native();raw['results'][-1]['quantity_name_raw']=None
    with pytest.raises(ValidationError,match='adopted_quantity_requires_source_property_name'):parse_extraction(raw)


@pytest.mark.parametrize('case',CASES)
def test_typed_first_read_v2_admits_source_units_and_old_vocabulary_stays_closed(case):
    b,m,*_=inputs();words='AUTHORED inventory specimen. '+case['quantity']['raw']
    block=make_blocks('doc:inventory-adopted',[('synthetic:quantity',words)])[0];block.document_id=b.documents[0].id;b.blocks.append(block)
    cat=source_catalog(b);spans=[k for k,v in cat['spans'].items() if v['block_id']==block.id]
    raw=m.model_dump();raw['schema_version']=typed2.VERSION
    raw['entries'].append(dict(type='numeric_result',sample_description='Authored specimen',quantity_description=case['kind'],
        quantity_kind=case['kind'],value_raw=case['quantity']['raw'],unit=case['quantity']['unit'],source_span_ids=spans,
        context_span_ids=[],unit_span_ids=spans,unresolved_reason=None,
        attribution=dict(origin='unknown',source_role='unknown',span_ids=[])))
    for span in typed.targets(cat):
        raw['span_assessments'].setdefault(span,dict(read=True,non_result_role='context_only',reason='Authored inventory context.'))
    model=typed2.TypedInventoryV2.model_validate(raw);jsonschema.validate(model.model_dump(),typed2.output_schema(b))
    inv,proof=typed2.project(model,b)
    assert proof['schema']==typed2.PROJECTION and proof['validation']['schema']==typed2.VALIDATION
    assert proof['projected_validation']['valid'] and inv.items[-1].value_raw==case['quantity']['raw']
    assert 'typed_inventory_kind_unknown' in {x['code'] for x in typed.inspect(model,b)['issues']}
    with pytest.raises(ValidationError):typed.TypedInventory.model_validate(raw)


def test_tc_slope_is_an_outcome_ancestor_and_never_a_tc_label():
    b,raw,_=native();raw['results'][2]['dependencies']=[dict(result_id='adopted',relation='derived_from')]
    graph=parse_extraction(raw);check=validate_extraction(graph,b);report=task_features.assess_tasks(graph,b,check)
    assert report['schema']==task_features.ADOPTED_VERSION
    assert all(x['label_candidate'] is None for x in report['results'][-1]['tasks'].values())
    geometry=report['results'][0]['tasks']['T2-conditions-tc']['condition_dispositions'][0]
    assert 'feature_has_outcome_ancestor' in geometry['reason_codes']
    assert geometry['provenance']['outcome_ancestor_result_ids']==['adopted']
    assert not report['ml_training_eligible']
    config=dict(task_feature_version=task_features.ADOPTED_VERSION,task_feature_policy_sha256=task_features.ADOPTED_POLICY_SHA256)
    task_features.verify_assessment(report,graph,b,check,config)
    with pytest.raises(ValueError,match='task_feature_policy_pin_mismatch'):
        task_features.verify_assessment(report,graph,b,check,dict(task_feature_version=task_features.VERSION,task_feature_policy_sha256=task_features.POLICY_SHA256))
