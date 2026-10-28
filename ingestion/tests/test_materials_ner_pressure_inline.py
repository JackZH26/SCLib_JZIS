"""Authored boundary controls; these do not supply scientific Gold labels."""
from copy import deepcopy

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner import wire_v16 as wire, typed_inventory_v3 as typed
from ingestion.materials_ner import canonical_preview, task_features
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.contract_v13 import PressureDeclaration, StateV13
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.sources import save_bundle, sha
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import configuration, run_one
from ingestion.materials_ner.proposals import import_packet, verify_packet
from ingestion.materials_ner.validation import validate_extraction, training_exclusions
from test_materials_ner_inline_native import fixture as previous_fixture
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_pipeline import quantity


def fixture(*, ambient=False):
    b, first, raw = previous_fixture()
    raw['schema_version'] = wire.WIRE_VERSION
    raw['context_decisions'] = {c['context_id']: {k: v for k, v in c.items() if k != 'context_id'}
        for c in raw.pop('context_dispositions')}
    for state in raw['states']:
        state['pressure'] = dict(availability='not_extracted', regime='unknown', condition_id=None, basis_raw=None)
    if ambient:
        text = 'The measurement on the reference sample was performed at ambient pressure.'
        block = type(b.blocks[0])(id='authored-pressure-context', document_id=b.blocks[0].document_id,
            ordinal=max(x.ordinal for x in b.blocks) + 1, locator='context:authored pressure', text=text, sha256=sha(text.encode()))
        b.blocks.append(block)
        source = source_catalog(b)
        raw['processed_block_ids'] = list(source['blocks'])
        from ingestion.materials_ner.inventory import targets
        for span in targets(source):
            first['span_assessments'].setdefault(span, dict(read=True, non_result_role='context_only',
                reason='Authored pressure context with no additional result.'))
        cat = typed.catalog(b)
        selection = next(k for k, v in cat['witness_selections'].items() if v['quote'] == text)
        state = raw['states'][0]
        assert not any(c['kind'] == 'pressure' and c['role'] == 'measurement' for c in state['conditions'])
        state['pressure'] = dict(availability='reported', regime='explicit_ambient', condition_id=None, basis_raw='ambient pressure')
        state['evidence'].append(dict(selection_id=selection, fields=['/pressure', '/pressure/basis_raw']))
    inventory, _ = typed.project(typed.TypedInventory.model_validate(first), b)
    return b, first, raw, inventory


def graph(raw, inventory, bundle):
    compact, proof = wire.AccountedExtraction.model_validate(raw).project(inventory, bundle)
    return compact.expand(bundle), proof


@pytest.mark.parametrize('ambient', [False, True])
def test_new_contract_round_trip_keeps_qualitative_pressure_without_zero(ambient):
    b, _, raw, inventory = fixture(ambient=ambient)
    schema = wire.output_schema(b, inventory)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(raw, schema)
    result, proof = graph(raw, inventory, b)
    checked = validate_extraction(result, b)
    assert checked['valid'], checked['issues']
    assert result.schema_version == 'materials-ner/13'
    assert result.states[0].pressure.model_dump() == raw['states'][0]['pressure']
    assert proof['schema'] == wire.PROJECTION_VERSION
    assessment = training_exclusions(result, b, checked)
    features = assessment['task_feature_assessment']
    assert features['schema'] == task_features.PRESSURE_VERSION
    for row in features['results']:
        for task in row['tasks'].values():
            assert not task['pressure_declaration']['numeric_value_imputed']
            assert not task['eligible_for_training']
    if ambient:
        assert result.states[0].pressure.condition_id is None
        assert all('measurement_pressure_unknown' not in x['reason_codes'] for x in assessment['results']
                   if next(r for r in result.results if r.id == x['result_id']).state_id == result.states[0].id)


@pytest.mark.parametrize('field', ['/value', '/pressure', '/measurement', '/quantity_status', '/imaginary'])
def test_generation_rejects_non_native_result_evidence_paths(field):
    b, _, raw, inventory = fixture()
    raw['decisions']['I1']['observation']['result']['evidence'][0]['fields'] = [field]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, wire.output_schema(b, inventory))


@pytest.mark.parametrize('status,selection', [('ambiguous', 'keep'), (None, None)])
def test_quantity_xor_is_enforced_before_and_after_generation(status, selection):
    b, _, raw, inventory = fixture()
    result = raw['decisions']['I1']['observation']['result']
    result['quantity_status'] = status
    if selection is None:
        result['quantity_selection_id'] = None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, wire.output_schema(b, inventory))
    with pytest.raises(ValidationError):
        wire.AccountedExtraction.model_validate(raw)


def test_invalid_ambient_zero_shape_is_rejected_at_generation_time():
    b, _, raw, inventory = fixture()
    raw['states'][0]['conditions'][0]['quantity'] = dict(status='reported', raw='ambient pressure',
        value=0, relation=None, unit='GPa', approximate=False, lower=None, upper=None, uncertainty=None)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, wire.output_schema(b, inventory))
    with pytest.raises(ValidationError):
        wire.AccountedExtraction.model_validate(raw)


@pytest.mark.parametrize('change', [dict(basis_raw=None), dict(availability='not_reported'), dict(regime='nonambient')])
def test_unsupported_pressure_declarations_rejected(change):
    b, _, raw, inventory = fixture(ambient=True)
    raw['states'][0]['pressure'].update(change)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, wire.output_schema(b, inventory))
    with pytest.raises(ValidationError):
        wire.AccountedExtraction.model_validate(raw)


@pytest.mark.parametrize('pressure', [0, 5.77])
def test_numeric_pressure_is_retained_only_with_its_explicit_condition(pressure):
    b, _, raw, inventory = fixture()
    result, _ = graph(raw, inventory, b)
    state = result.states[0].model_dump()
    state['conditions'].append(dict(id='reported-pressure', kind='pressure', role='measurement',
        quantity=quantity(pressure, 'GPa', f'{pressure} GPa'), orientation_raw=None, basis_raw=f'{pressure} GPa', window_position=None))
    state['pressure'] = dict(availability='reported', regime='unknown', condition_id='reported-pressure', basis_raw=f'{pressure} GPa')
    parsed = StateV13.model_validate(state)
    assert parsed.conditions[-1].quantity.value == pressure
    # The native type retains a reported number; original-source validation
    # remains mandatory and rejects an authored number absent from the bundle.
    result.states[0] = parsed
    assert not validate_extraction(result, b)['valid']
    state['pressure']['condition_id'] = 'missing'
    with pytest.raises(ValidationError, match='pressure_condition_reference_invalid'):
        StateV13.model_validate(state)


@pytest.mark.parametrize('decision', ['missing', 'unresolved', 'carried'])
def test_contexts_must_be_closed_and_carried_fields_have_source_evidence(decision):
    b, _, raw, inventory = fixture(ambient=True)
    state = raw['states'][0]
    source = source_catalog(b)
    span = next(k for k, v in source['spans'].items() if v['block_id'] == 'authored-pressure-context')
    from ingestion.materials_ner.inventory import ContextAssertion
    inventory.context_assertions.append(ContextAssertion(id='C1', kind='condition',
        description='Authored ambient condition.', span_ids=[span]))
    if decision == 'missing':
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(raw, wire.output_schema(b, inventory))
        with pytest.raises(ValueError, match='context_keys_not_closed'):
            graph(raw, inventory, b)
        return
    raw['context_decisions']['C1'] = (dict(resolution='unresolved', bindings=[], explanation='Source applicability needs review.')
        if decision == 'unresolved' else dict(resolution='carried', explanation=None,
            bindings=[dict(entity='state', entity_id=state['id'], field='/pressure')]))
    jsonschema.validate(raw, wire.output_schema(b, inventory))
    compact, _ = wire.AccountedExtraction.model_validate(raw).project(inventory, b)
    coverage = wire.validate_coverage(compact, inventory, b)
    assert coverage['valid'] == (decision == 'carried')
    if decision == 'unresolved':
        assert any(x['code'] == 'source_context_unresolved' for x in coverage['issues'])


def test_operation_temperature_remains_excluded_from_tc_features():
    b, _, raw, inventory = fixture()
    result, _ = graph(raw, inventory, b)
    state = result.states[0]
    condition = state.conditions[0].model_copy(deep=True)
    condition.id = 'operation'
    condition.kind = 'temperature'
    condition.role = 'unknown'
    condition.basis_raw = 'pressure was changed at 10 K'
    condition.quantity = type(condition.quantity).model_validate(quantity(10, 'K', '10 K'))
    condition.window_position = None
    state.conditions.append(condition)
    checked = validate_extraction(result, b)
    tasks = task_features.assess_tasks(result, b, checked)
    for row in tasks['results']:
        for task in row['tasks'].values():
            operation = [d for d in task['condition_dispositions'] if d['condition_id'] == 'operation']
            assert all(x['disposition'] == 'excluded' for x in operation)
            assert not any(c['condition_id'] == 'operation' for c in task['condition_candidates'])


def test_two_stage_worker_retains_pressure_in_proposal_and_canonical_preview(tmp_path):
    b, first, raw, _ = fixture(ambient=True)
    store = Store(tmp_path / 'queue')
    hashed, _ = save_bundle(store.root, b)
    job = store.enqueue(work_id=b.work_id, bundle_hash=hashed,
        config=configuration(workflow='inventory_v16'), max_attempts=1)
    provider = SequenceProvider([first, raw])
    outcome = run_one(store, job_id=job, provider_override=provider)
    packet = import_packet(store, job)
    verify_packet(packet)
    assert outcome['state'] == 'succeeded', outcome
    assert provider.calls == 2
    assert packet['receipt']['extraction']['schema_version'] == 'materials-ner/13'
    preview = canonical_preview.build(packet)
    assert preview['schema'] == canonical_preview.PRESSURE_VERSION
    assert canonical_preview.retained_graph(preview, packet) == packet['receipt']['extraction']
    states = [e['candidate_fields'] for e in preview['entities'] if e['candidate_destination'] == 'material_states']
    assert states[0]['conditions']['pressure'] == raw['states'][0]['pressure']
    assert states[0]['conditions']['temperature_condition_id'] is None
    assert not preview['database_writes'] and not preview['ml_training_eligible']
    altered = deepcopy(packet)
    altered['receipt']['extraction']['states'][0]['pressure']['regime'] = 'unknown'
    altered['run_id'] = digest(altered['receipt'])
    with pytest.raises(ValueError):
        verify_packet(altered)
