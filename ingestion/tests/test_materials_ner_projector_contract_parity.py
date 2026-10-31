"""Consolidated provider constraints agree with native science; remaining gates stay explicit."""
from copy import deepcopy
from itertools import product
import json
from typing import get_args

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError
import pytest

from ingestion.materials_ner import projector_schema as schema, source_projector as stage
from ingestion.materials_ner import projector_proposals as pp, projection_binding, reviewed_reader as r
from ingestion.materials_ner.contract import Quantity, parse_extraction
from ingestion.materials_ner.contract_v8 import NonDetectionV8
from ingestion.materials_ner.contract_v9 import SampleV9
from ingestion.materials_ner.contract_v14 import ExtractionV14, ConditionV14
from ingestion.materials_ner.proposals import verify_packet, ProposalDatabase
from ingestion.materials_ner.store import Store
from test_materials_ner_source_focus import focused_case, Fake
from test_materials_ner_catalog_projector import catalog_case
from test_materials_ner_reviewed_proposals import prepared


V7 = schema.CONSOLIDATED_NATIVE14_VERSION
V6 = schema.NATIVE14_VERSION
CATALOG = {'spans': {'E0001': {}}}
NEW = schema.output_schema(graph_schema='materials-ner/14', source_catalog=CATALOG, selected_interface=V7)
OLD = schema.output_schema(graph_schema='materials-ner/14', source_catalog=CATALOG)


def component(name):
    return Draft202012Validator({'$defs': NEW['$defs'], '$ref': '#/$defs/' + name})


def accepts(model, value):
    try:
        model.model_validate(value)
        return True
    except ValidationError:
        return False


def native_graph(g):
    return parse_extraction(dict(projection_binding.native_graph(g), schema_version='materials-ner/14')).model_dump()


def response_graph(g):
    g = deepcopy(g)
    for group in projection_binding.GROUPS:
        for entity in g[group]:
            entity['evidence'] = []
    return g


def select(focused_case, tmp_path):
    old_path, _, graph, _ = focused_case
    body = json.loads(old_path.read_bytes())
    body['interface_version'] = V7
    path = tmp_path / 'consolidated-request.json'; r.put(path, body)
    return path, graph


def test_explicit_interface_preserves_old_schema_native_contract_prompt_and_sources(focused_case, tmp_path):
    old_path, old, _, _ = focused_case
    path, _ = select(focused_case, tmp_path)
    new = stage.prepare(path)
    assert new['prompt'] == old['prompt'] and new['bundle'] == old['bundle']
    assert new['scope'] == old['scope'] and new['source_catalog'] == old['source_catalog']
    assert stage.configuration(old)['interface_version'] == V6
    assert stage.configuration(new)['interface_version'] == V7
    assert stage.prepare(old_path)['schema'] == old['schema']
    assert new['schema'] != old['schema']
    assert schema.output_schema(graph_schema='materials-ner/14', source_catalog=CATALOG, selected_interface=V6) == OLD
    Draft202012Validator.check_schema(NEW)
    def walk(node):
        if isinstance(node, dict):
            assert not {'if', 'then', 'else', 'allOf', 'not', 'contains', 'uniqueItems', '$data'} & node.keys()
            if node.get('type') == 'object':
                assert node['additionalProperties'] is False
                assert set(node['required']) == set(node['properties'])
            for value in node.values(): walk(value)
        elif isinstance(node, list):
            for value in node: walk(value)
    walk(NEW)
    assert 'anyOf' not in ExtractionV14.model_json_schema()['$defs']['SampleV11']


@pytest.mark.parametrize('value', [None, '', 'materials-source-projector-interface/5', 'materials-source-projector-interface/8', True, {}])
def test_unknown_explicit_interface_rejected_before_queue(focused_case, tmp_path, value):
    path, _ = select(focused_case, tmp_path)
    body = json.loads(path.read_bytes()); body['interface_version'] = value
    path.write_text(json.dumps(body))
    store = Store(tmp_path / 'invalid-request')
    with pytest.raises(ValueError): stage.enqueue(store, path)
    assert store.summary()['jobs'] == 0


@pytest.mark.parametrize('legacy', [stage.INPUT_SCHEMA, stage.NATIVE14_INPUT_SCHEMA])
def test_interface_selector_requires_explicit_focused_request(focused_case, tmp_path, legacy):
    path, _ = select(focused_case, tmp_path); body = json.loads(path.read_bytes())
    body['schema'] = legacy
    with pytest.raises(ValueError, match='projector_input_shape'): stage.request_contract(body)


def test_formula_matrix_uses_native_validator_as_oracle(focused_case):
    sample = native_graph(focused_case[2])['samples'][0]
    validator = component('SampleV11')
    missing = dict(status='not_extracted', explanation='Source applicability pending.', checked_block_ids=[])
    count = valid = 0
    for formula, gap, basis in product([None, '', ' ', '\t\n', 'LaFeAsO'], [None, missing],
                                     ['nominal', 'measured', 'unresolved']):
        value = dict(sample, formula_raw=formula, formula_unavailability=gap, composition_basis=basis)
        assert validator.is_valid(value) == accepts(SampleV9, value), value
        valid += accepts(SampleV9, value)
        count += 1
    assert count == 30 and valid == 4
    value = dict(sample, formula_raw=None, formula_unavailability=None)
    old_component = Draft202012Validator({'$defs': OLD['$defs'], '$ref': '#/$defs/SampleV11'})
    assert old_component.is_valid(value) and not validator.is_valid(value)


def test_condition_bases_cover_both_inherited_native_requirements():
    count = valid = 0
    for kind, role, basis in product(['temperature', 'reported_magnetic_field'],
                                    ['measurement', 'extrapolation_target'], [None, '', ' ', '\n', 'source basis']):
        value = dict(id='c', kind=kind, role=role, basis_raw=basis, orientation_raw=None,
            quantity=Quantity(status='not_extracted').model_dump(), window_position=None)
        assert component('ConditionV14').is_valid(value) == accepts(ConditionV14, value), value
        valid += accepts(ConditionV14, value)
        count += 1
    assert count == 20 and valid == 8


def negative(**updates):
    value = dict(kind='non_detection', raw='No signal in the stated window.',
        existence='not_established',
        window_status='reported', target='superconductivity', observable='zero_resistance',
        window_condition_ids=['window'], sensitivities=[])
    value.update(updates)
    return value


def test_negative_target_observable_and_window_matrix():
    props = NonDetectionV8.model_json_schema()['properties']; count = valid = 0
    for target, observable, status, ids in product(props['target']['enum'], props['observable']['enum'],
            props['window_status']['enum'], [[], ['window']]):
        value = negative(target=target, observable=observable, window_status=status, window_condition_ids=ids)
        assert component('NonDetectionV8').is_valid(value) == accepts(NonDetectionV8, value), value
        valid += accepts(NonDetectionV8, value)
        count += 1
    assert count == 168 and valid == 28


def test_property_name_matrix_preserves_native_distinctions(focused_case):
    graph = response_graph(native_graph(focused_case[2])); count = valid = 0
    for kind, name in product(['tc', 'unmapped', *schema.V12_NAMES, *schema.V14_NAMES], [None, '', ' ', 'source name']):
        value = deepcopy(graph); value['results'][0].update(quantity_kind=kind, quantity_name_raw=name)
        assert Draft202012Validator(NEW).is_valid(value) == accepts(ExtractionV14, value), (kind, name)
        valid += accepts(ExtractionV14, value)
        count += 1
    assert count == 4 * (2 + len(schema.V12_NAMES) + len(schema.V14_NAMES))
    assert valid > 0


def test_negative_quantity_and_positive_qualifier_kind_constraints(focused_case):
    graph = response_graph(native_graph(focused_case[2]))
    for kind, status, use_negative in product(['tc', 'non_detection'], ['reported', 'not_applicable'], [False, True]):
        value = deepcopy(graph); result = value['results'][0]
        result.update(quantity_kind=kind, qualifiers=[negative(window_status='unresolved', window_condition_ids=[])] if use_negative else [])
        if status == 'not_applicable': result['quantity'] = Quantity(status=status).model_dump()
        provider = Draft202012Validator(NEW).is_valid(value); native = accepts(ExtractionV14, value)
        if provider != native:
            # Supported schemas cannot require a particular unordered array
            # member without contains; exact negative cardinality stays native.
            assert provider and kind == 'non_detection' and status == 'not_applicable' and not use_negative
        else:
            assert provider == native


def test_qualitative_ambient_remains_numeric_free(focused_case):
    value = response_graph(native_graph(focused_case[2])); state = value['states'][0]
    state.update(conditions=[], pressure=dict(availability='reported', regime='explicit_ambient',
        condition_id=None, basis_raw='ambient pressure'))
    assert Draft202012Validator(NEW).is_valid(value) and accepts(ExtractionV14, value)
    assert not state['conditions'] and state['pressure']['condition_id'] is None


@pytest.mark.parametrize('defect', ['dangling_protocol', 'missing_pressure', 'ambient_status', 'formula_placeholder',
                                  'duplicate_id', 'reversed_interval', 'negative_count', 'duplicate_window'])
def test_remaining_gates_are_not_misrepresented_as_provider_guarantees(focused_case, defect):
    value = response_graph(native_graph(focused_case[2])); state = value['states'][0]; result = value['results'][0]
    if defect == 'dangling_protocol': result['protocol_id'] = 'absent'
    elif defect == 'missing_pressure':
        state.update(conditions=[], pressure=dict(availability='reported', regime='nonambient', condition_id='absent', basis_raw='1 GPa'))
    elif defect == 'ambient_status':
        state.update(conditions=[dict(id='ambient', kind='pressure', role='measurement', basis_raw='ambient pressure',
            orientation_raw=None, window_position=None, quantity=Quantity(status='not_applicable').model_dump())],
            pressure=dict(availability='reported', regime='explicit_ambient', condition_id='ambient', basis_raw='ambient pressure'))
    elif defect == 'formula_placeholder': value['samples'][0].update(formula_raw='UNKNOWN', formula_unavailability=None)
    elif defect == 'duplicate_id': value['samples'].append(deepcopy(value['samples'][0]))
    elif defect == 'reversed_interval': result['quantity'].update(relation='interval', value=None, lower=5.0, upper=1.0)
    else:
        qualifier = negative(window_status='unresolved', window_condition_ids=[])
        if defect == 'duplicate_window': qualifier = negative(window_condition_ids=['x', 'x'])
        result.update(quantity_kind='non_detection', quantity=Quantity(status='not_applicable').model_dump(),
            qualifiers=[qualifier, deepcopy(qualifier)] if defect == 'negative_count' else [qualifier])
    assert Draft202012Validator(NEW).is_valid(value), defect
    assert not accepts(ExtractionV14, value), defect


def test_all_reachable_native_model_validators_are_accounted_for():
    pending, seen, checks = [ExtractionV14], set(), set()
    while pending:
        model = pending.pop()
        if model in seen: continue
        seen.add(model)
        for decorator in model.__pydantic_decorators__.model_validators.values():
            checks.add(decorator.func.__qualname__)
        def add(annotation):
            if isinstance(annotation, type) and issubclass(annotation, BaseModel): pending.append(annotation)
            else:
                for arg in get_args(annotation): add(arg)
        for field in model.model_fields.values(): add(field.annotation)
    assert checks == {
        'Quantity.shape', 'Extraction.references', 'ExtractionV6.condition_method_references',
        'NonDetectionV8.target_scope', 'ResultV8.negative_shape', 'SampleV9.formula_shape',
        'ExtractionV9.formula_scope', 'ConditionV10.unresolved_field_basis', 'PositionedEvidence.ordered',
        'ResultV12.explicit_new_property_name', 'PressureDeclaration.supported_declaration',
        'StateV13.pressure_condition', 'ConditionV14.extrapolation_basis', 'ResultV14.explicit_inverse_depth_name'}


def test_new_interface_attempt_is_portable_idempotent_and_unqualified(focused_case, tmp_path, monkeypatch):
    path, graph = select(focused_case, tmp_path); store = Store(tmp_path / 'consolidated-queue')
    fake = Fake(graph); job = stage.enqueue(store, path)
    assert stage.row(store, job)['config']['interface_version'] == V7
    result = stage.run(store, job, provider_override=fake)
    assert result['state'] == 'succeeded', result
    assert stage.run(store, job, provider_override=fake) == result and fake.calls == 1
    packet = pp.build(store.root, job); database = ProposalDatabase(tmp_path / 'candidate-store')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    with database.connect() as connection:
        restored = json.loads(connection.execute('SELECT payload FROM runs').fetchone()[0])
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    def forbidden(*args, **kwargs): raise AssertionError('Portable replay accessed a source or provider.')
    monkeypatch.setattr(r, 'checked', forbidden)
    verify_packet(restored)
    assert not restored['scientific_acceptance'] and not restored['ml_training_eligible']
    assert restored['rows']['results'][0]['review_status'] == 'pending_review'


def test_invalid_native_return_is_preserved_without_posthoc_repair(focused_case, tmp_path):
    path, graph = select(focused_case, tmp_path); graph['results'][0]['protocol_id'] = 'missing'
    store = Store(tmp_path / 'failed-native'); fake = Fake(graph); job = stage.enqueue(store, path)
    result = stage.run(store, job, provider_override=fake)
    assert result['state'] == 'quarantined' and result['error_code'] == 'projector_schema_invalid'
    assert json.loads(r.checked(result['model_graph']).read_bytes()) == graph
    packet = pp.build(store.root, job)
    assert not any(packet['rows'].values())
    assert stage.run(store, job, provider_override=fake) == result and fake.calls == 1
