"""Provider/native agreement for the interface invariants, not scientific truth."""
from copy import deepcopy
from itertools import product

from jsonschema import Draft202012Validator
from pydantic import ValidationError
import pytest

from ingestion.materials_ner import projector_schema
from ingestion.materials_ner.contract_v13 import PressureDeclaration
from ingestion.materials_ner.contract import Quantity


SCHEMA = projector_schema.output_schema()


def test_schema_is_valid_and_uses_supported_composition_keywords():
    Draft202012Validator.check_schema(SCHEMA)
    def walk(node):
        if isinstance(node, dict):
            assert not {'if','then','else','allOf','not','dependentRequired','dependentSchemas'} & node.keys()
            if node.get('type') == 'object':
                assert node['additionalProperties'] is False
                assert set(node['required']) == set(node['properties'])
            for child in node.values(): walk(child)
        elif isinstance(node, list):
            for child in node: walk(child)
    walk(SCHEMA)
    assert SCHEMA['type'] == 'object'


def test_pressure_schema_matches_native_cross_field_validator_matrix():
    validator = Draft202012Validator(SCHEMA['$defs']['PressureDeclaration'])
    statuses = PressureDeclaration.model_json_schema()['properties']['availability']['enum']
    cases = list(product(statuses, ['explicit_ambient','nonambient','unknown'],
        [None,'','p'], [None,'','   ','\t\n','source statement']))
    assert len(cases) == 315
    for status, regime, condition, basis in cases:
        value = dict(availability=status, regime=regime, condition_id=condition, basis_raw=basis)
        try: PressureDeclaration.model_validate(value); native = True
        except ValidationError: native = False
        assert validator.is_valid(value) == native, value


def field_schema(group):
    entity = SCHEMA['$defs'][SCHEMA['properties'][group]['items']['$ref'].split('/')[-1]]
    evidence = SCHEMA['$defs'][entity['properties']['evidence']['items']['anyOf'][0]['$ref'].split('/')[-1]]
    return evidence['properties']['field']


@pytest.mark.parametrize('group,path,valid', [
    ('results','/quantity/raw',True), ('results','/definition/parameters/0/quantity/value',True),
    ('results','/dependencies/120/result_id',True), ('states','/conditions/0/quantity/unit',True),
    ('states','/pressure/basis_raw',True), ('samples','/variables/0/amount/raw',True),
    ('protocols','/method_class',True), ('protocols','/parameters/0/quantity',True),
    ('results','/results/r/quantity',False), ('states','/states/s/pressure',False),
    ('states','/conditions/pressure',False), ('states','/conditions/-1/quantity',False),
    ('states','/conditions/01/quantity',False), ('results','/quantity/imagined',False),
    ('protocols','/protocols/p',False), ('results','/',False), ('results','/evidence/0',False),
])
def test_entity_relative_address_language(group,path,valid):
    assert Draft202012Validator(field_schema(group)).is_valid(path) == valid


def test_each_entity_has_its_own_evidence_schema_without_mutating_native():
    from ingestion.materials_ner.contract_v13 import ExtractionV13
    native = ExtractionV13.model_json_schema()
    assert native['$defs']['Evidence']['properties']['field']['pattern'] == '^/'
    altered = deepcopy(SCHEMA)
    altered['$defs']['resultsEvidence']['properties']['field']['pattern'] = 'changed'
    assert projector_schema.output_schema() == SCHEMA


def quantity_validator():
    return Draft202012Validator(dict(SCHEMA['$defs']['Quantity'],**{'$defs':SCHEMA['$defs']}))


def test_all_quantity_shapes_match_native_except_explicitly_deferred_interval_order():
    validator=quantity_validator();count=0;deferred=[];both_valid=0
    statuses=Quantity.model_json_schema()['properties']['status']['enum']
    for status,relation,values,raw,unit in product(statuses,[None,'exact','interval','lt','le','gt','ge'],
            product([None,0.0,1.0],repeat=3),[None,'','1'],[None,'','K']):
        value=dict(status=status,relation=relation,value=values[0],lower=values[1],upper=values[2],
            raw=raw,unit=unit,approximate=False,uncertainty=None)
        try:Quantity.model_validate(value);native=True;error=None
        except ValidationError as exc:native=False;error=exc.errors()[0]['msg']
        provider=validator.is_valid(value);count+=1
        if provider!=native:
            assert provider and not native and 'reversed quantity interval' in error,value
            deferred.append(value)
        if provider and native:both_valid+=1
    assert count==11907 and both_valid==67 and len(deferred)==1


@pytest.mark.parametrize('status',Quantity.model_json_schema()['properties']['status']['enum'])
@pytest.mark.parametrize('approximate',[False,True])
def test_unavailable_quantities_do_not_select_uncertainty_but_preserve_raw_and_unit(status,approximate):
    uncertainty=dict(kind='reported_unspecified',minus=.1,plus=.1,level=None,raw='0.1')
    value=dict(status=status,raw='conflicting source expression',relation='exact' if status=='reported' else None,
        value=1.0 if status=='reported' else None,lower=None,upper=None,unit='1',approximate=approximate,uncertainty=uncertainty)
    assert quantity_validator().is_valid(value)==(status=='reported')
    value['uncertainty']=None
    assert quantity_validator().is_valid(value)
    assert Quantity.model_validate(value).unit=='1'


def test_every_quantity_use_references_one_constrained_definition():
    paths=[]
    def visit(node,path=''):
        if isinstance(node,dict):
            if node.get('$ref')=='#/$defs/Quantity':paths.append(path)
            for key,value in node.items():visit(value,path+'/'+key)
        elif isinstance(node,list):
            for index,value in enumerate(node):visit(value,path+'/'+str(index))
    visit(SCHEMA)
    assert len(paths)>=5
    assert any('Condition' in p for p in paths)
    assert any('Parameter' in p for p in paths)
    assert any('Sensitivity' in p for p in paths)
    assert any('Result' in p for p in paths)
    assert 'anyOf' in SCHEMA['$defs']['Quantity']
    from ingestion.materials_ner.contract_v13 import ExtractionV13
    assert 'properties' in ExtractionV13.model_json_schema()['$defs']['Quantity']
