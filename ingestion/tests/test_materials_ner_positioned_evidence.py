"""Original-source evidence regressions; technical checks do not certify data."""
from copy import deepcopy
from pathlib import Path
import json

import pytest
from pydantic import ValidationError

from ingestion.materials_ner.contract import Evidence, canonical, parse_extraction
from ingestion.materials_ner.contract_v11 import PositionedEvidence
from ingestion.materials_ner import source_atoms as atoms, table_value_binding as tables
from ingestion.materials_ner.proposals import review_rows
from ingestion.materials_ner.source_occurrence import positioned_witness
from ingestion.materials_ner.validation import resolve_evidence, validate_extraction
from test_materials_ner_scientific_row_stages import fixture


def scientific(value):
    if isinstance(value,dict):return {k:scientific(v) for k,v in value.items() if k not in {'evidence','schema_version'}}
    if isinstance(value,list):return [scientific(v) for v in value]
    return value


@pytest.fixture(scope='module')
def source_projection():
    bundle,inventory,_,_,scope,adapter,palette,raw=fixture()
    # A duplicate source formula here exercises an evidence parent; it is not
    # asserted to be a correct scientific alternative composition.
    sample=raw['samples'][0]
    sample['alternative_formulas']=[dict(formula=deepcopy(sample['formula']),basis=deepcopy(sample['basis']),
        context=deepcopy(sample['scope_support']))]
    choices=atoms.CatalogChoices.model_validate(raw);ownership=adapter.ownership(bundle)
    args=dict(candidate_catalog=palette['catalog'],dimensionless_variable_amounts=True)
    legacy=atoms.project(choices,bundle,ownership,**args)
    positioned=atoms.project(choices,bundle,ownership,positioned_evidence=True,**args)
    return bundle,ownership,scope,legacy,positioned


def with_result(source_projection):
    bundle,ownership,_,_,projection=source_projection
    value=json.loads((Path(__file__).parent/'fixtures/materials_ner_positioned_evidence_regression.json').read_bytes())
    data=deepcopy(projection['graph']);result=deepcopy(value['native_result'])
    binding=tables.compile_binding(bundle,ownership,'T1:R1:C2')
    result['evidence']=[e for e in binding['evidence'] if e['field']!='/quantity_name_raw']
    data['results']=[result]
    return data,binding


def test_repeated_units_need_exact_positions_and_unicode_offsets():
    text='μ K K';legacy=Evidence(block_id='b',quote='K',field='/quantity/unit')
    with pytest.raises(ValueError,match='ambiguous_quote_locator'):resolve_evidence(text,legacy)
    first=PositionedEvidence(**legacy.model_dump(),start_char=2,end_char=3)
    second=PositionedEvidence(**legacy.model_dump(),start_char=4,end_char=5)
    assert resolve_evidence(text,first)==(2,3)
    assert resolve_evidence(text,second)==(4,5)
    assert first.quote==second.quote


@pytest.mark.parametrize('positions',[
    dict(start_char=-1,end_char=1),dict(start_char=0,end_char=0),dict(start_char=2,end_char=1),
    dict(start_char=True,end_char=2),dict(start_char=0.0,end_char=1),
    dict(start_char='0',end_char=1),dict(start_char=0),dict(end_char=1)])
def test_invalid_selector_shapes_are_not_coerced(positions):
    with pytest.raises(ValidationError):
        PositionedEvidence(block_id='b',quote='K',field='/quantity/unit',**positions)


@pytest.mark.parametrize('quote,start,end,code',[
    ('K',1,2,'evidence_position_quote_mismatch'),('K',8,9,'evidence_position_out_of_bounds'),
    ('K K',0,4,'evidence_position_quote_mismatch')])
def test_bad_positions_do_not_fall_back_to_text_search(quote,start,end,code):
    item=PositionedEvidence(block_id='b',quote=quote,field='/quantity/unit',start_char=start,end_char=end)
    with pytest.raises(ValueError,match=code):resolve_evidence('K  K',item)


def test_native_contract_is_opt_in_and_preserves_scientific_fields(source_projection):
    bundle,_,_,old,new=source_projection
    assert old['graph']['schema_version']=='materials-ner/10'
    assert new['graph']['schema_version']=='materials-ner/11'
    assert scientific(old['graph'])==scientific(new['graph'])
    assert not any('start_char' in e for group in ('samples','states','protocols')
        for entity in old['graph'][group] for e in entity['evidence'])
    graph=parse_extraction(new['graph'])
    assert parse_extraction(json.loads(canonical(graph.model_dump()))).model_dump()==graph.model_dump()
    with pytest.raises(ValidationError):parse_extraction(dict(new['graph'],schema_version='materials-ner/10'))
    old_report=validate_extraction(parse_extraction(old['graph']),bundle)
    new_report=validate_extraction(graph,bundle)
    assert old_report['validator_version']=='materials-ner-validation/1.21.0'
    assert new_report['validator_version']=='materials-ner-validation/1.22.0'
    assert not {'field_evidence_missing','quantity_raw_not_in_field_evidence'} & {x['code'] for x in new_report['issues']}
    assert not new_report['scientific_acceptance'] and not new_report['ml_training_eligible']


def test_original_five_cells_keep_units_uncertainty_and_source_column_identity(source_projection):
    bundle,ownership,scope,_,_=source_projection
    proofs=[tables.compile_binding(bundle,ownership,c) for c in scope['cell_ids']]
    assert [p['quantity']['value'] for p in proofs]==[91.19,90.99,91.35,91.16,44.63]
    assert [p['quantity']['uncertainty']['plus'] for p in proofs]==[.05,.04,.04,.04,.03]
    assert all(p['quantity']['unit']=='K' for p in proofs)
    assert proofs[0]['source']['unit']['quote']==proofs[1]['source']['unit']['quote']=='K'
    assert proofs[0]['source']['unit']['start_char']!=proofs[1]['source']['unit']['start_char']
    for proof in proofs:
        assert tables.verify_binding(json.loads(canonical(proof)),bundle,ownership)==proof
        assert not proof['scientific_ownership_verified'] and not proof['scientific_acceptance']


def test_an_equal_unit_in_the_other_column_does_not_verify(source_projection):
    bundle,ownership,_,_,_=source_projection
    first=tables.compile_binding(bundle,ownership,'T1:R1:C2')
    second=tables.compile_binding(bundle,ownership,'T1:R1:C3')
    first['source']['unit']=second['source']['unit']
    with pytest.raises(ValueError,match='table_value_binding_changed'):tables.verify_binding(first,bundle,ownership)


def test_wrong_column_and_missing_printed_unit_remain_holds(source_projection):
    bundle,ownership,_,_,_=source_projection
    altered=deepcopy(ownership);next(c for c in altered['cells'] if c['id']=='T1:R1:C2')['column']=3
    with pytest.raises(ValueError,match='table_value_column_binding_mismatch'):
        tables.compile_binding(bundle,altered,'T1:R1:C2')
    with pytest.raises(ValueError,match='table_value_unit_row_missing'):
        tables.compile_binding(bundle,ownership,'T1:R1:C4')


@pytest.mark.parametrize('change,code',[
    ('whole_table_unit','field_unit_witness_mismatch'),('numeric_value','numeric_value_disagrees_with_raw'),
    ('uncertainty','uncertainty_disagrees_with_raw'),('unit_position','evidence_position_quote_mismatch')])
def test_strict_quantity_and_locator_checks_survive_positioned_transport(source_projection,change,code):
    bundle=source_projection[0];data,binding=with_result(source_projection);result=data['results'][0]
    unit=next(e for e in result['evidence'] if e['field']=='/quantity/unit')
    if change=='whole_table_unit':unit.update(positioned_witness(bundle,binding['source']['unit_row']))
    elif change=='numeric_value':result['quantity']['value']+=1
    elif change=='uncertainty':result['quantity']['uncertainty']['plus']=.5
    else:unit['start_char']-=1
    report=validate_extraction(parse_extraction(data),bundle)
    assert code in {x['code'] for x in report['issues']}
    assert not report['valid'] and not report['ml_training_eligible']


def test_real_result_quantity_evidence_keeps_other_defects_and_proposal_positions(source_projection):
    bundle=source_projection[0];data,binding=with_result(source_projection)
    graph=parse_extraction(data);report=validate_extraction(graph,bundle)
    quantity_errors=[x for x in report['issues'] if x['path']=='/results/0/quantity'
        or x['path'].startswith('/results/0/quantity/')]
    assert not quantity_errors
    assert any(x['code']=='source_literal_evidence_missing' for x in report['issues'])
    rows=review_rows(graph,report)
    assert {'sample_relations','condition_supports'} <= set(rows)
    saved=rows['results'][0]
    assert saved['review_status']=='quarantined'
    assert saved['payload']['evidence']==data['results'][0]['evidence']
    unit=next(e for e in report['resolved_evidence'] if e['path']=='/results/0/quantity/unit')
    assert (unit['start_char'],unit['end_char'])==(binding['source']['unit']['start_char'],binding['source']['unit']['end_char'])


def test_nested_condition_quantity_unit_is_checked_in_v11(source_projection):
    bundle=source_projection[0];data=deepcopy(source_projection[-1]['graph'])
    data['states'][0]['conditions'][1]['quantity']['unit']='mK'
    report=validate_extraction(parse_extraction(data),bundle)
    assert any(x['code']=='numeric_source_unit_mismatch' and x['path']=='/states/0/conditions/1/quantity'
        for x in report['issues'])
