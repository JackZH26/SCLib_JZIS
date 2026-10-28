"""Source-shape and authority boundaries, using authored controls rather than Gold."""
from copy import deepcopy
import json

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner import wire_v17 as wire, wire_v16, typed_inventory_v3 as typed
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.inventory import targets
from ingestion.materials_ner.sources import sha, save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import configuration, run_one
from ingestion.materials_ner.proposals import import_packet, verify_packet
from ingestion.materials_ner.providers import ProviderResult
from ingestion.materials_ner.validation import validate_extraction
from test_materials_ner_pressure_inline import fixture as prior_fixture
from test_materials_ner_inventory_v2 import SequenceProvider


def text_choice(bundle, text):
    candidates = [(key, row) for key, row in typed.catalog(bundle)['witness_selections'].items()
        if text in row['quote'] and row['quote'].count(text) == 1]
    assert candidates, text
    key, row = min(candidates, key=lambda pair: (len(pair[1]['quote']), pair[0]))
    return dict(selection_id=key, quote=None if text == row['quote'] else text)


def encode(bundle, value, name=None):
    if name and (name.endswith('_raw') or name == 'raw'):
        return None if value is None else text_choice(bundle, value)
    if isinstance(value, list):
        return [encode(bundle, child) for child in value]
    if not isinstance(value, dict):
        return value
    if {'status', 'raw', 'relation', 'approximate'} <= set(value):
        if value['status'] != 'reported':
            return dict(quantity_selection_id=None, quantity_status=value['status'])
        key = next(k for k, row in typed.catalog(bundle)['numeric_catalog']['numeric_candidates'].items()
            if row['selectable'] and row['quote'] == value['raw'])
        return dict(quantity_selection_id=key, quantity_status=None)
    return {key: encode(bundle, child, key) for key, child in value.items()}


def fixture(ambient=True):
    bundle, first, raw, inventory = prior_fixture(ambient=ambient)
    encoded = encode(bundle, raw)
    encoded['schema_version'] = wire.WIRE_VERSION
    encoded['block_decisions'] = {key: 'processed' for key in encoded.pop('processed_block_ids')}
    encoded['block_decisions'].update({key: 'unread' for key in encoded.pop('unread_block_ids')})
    return bundle, first, encoded, inventory


def projected(raw, inventory, bundle):
    compact, proof = wire.AccountedExtraction.model_validate(raw).project(inventory, bundle)
    return compact.expand(bundle), proof


@pytest.mark.parametrize('ambient', [False, True])
def test_source_selected_graph_roundtrip_keeps_native13_and_exact_literals(ambient):
    bundle, _, raw, inventory = fixture(ambient)
    before = deepcopy(raw)
    schema = wire.output_schema(bundle, inventory)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(raw, schema)
    graph, proof = projected(raw, inventory, bundle)
    assert raw == before
    checked = validate_extraction(graph, bundle)
    assert checked['valid'], checked['issues']
    assert graph.schema_version == 'materials-ner/13'
    assert proof['schema'] == wire.PROJECTION_VERSION
    assert proof['copied_literal_fields'] and proof['copied_condition_or_parameter_quantities']
    assert not proof['scientific_relations_inferred_by_compiler']
    if ambient:
        assert graph.states[0].pressure.basis_raw == 'ambient pressure'
        assert graph.states[0].pressure.condition_id is None
        assert not any(c.quantity.value == 0 and c.kind == 'pressure' for c in graph.states[0].conditions)


@pytest.mark.parametrize('mutation', ['paraphrase', 'unknown_selection', 'ordinary_string'])
def test_raw_fields_reject_unselected_or_rewritten_scientific_text(mutation):
    bundle, _, raw, inventory = fixture()
    field = raw['states'][0]['pressure']
    if mutation == 'paraphrase': field['basis_raw']['quote'] = 'the pressure was normal'
    elif mutation == 'unknown_selection': field['basis_raw']['selection_id'] = 'T_unknown'
    else: field['basis_raw'] = 'ambient pressure'
    with pytest.raises((ValueError, ValidationError)):
        projected(raw, inventory, bundle)
    if mutation != 'paraphrase':
        with pytest.raises(jsonschema.ValidationError): jsonschema.validate(raw, wire.output_schema(bundle, inventory))


def test_approximate_temperature_never_modifies_exact_pressure_selection():
    bundle, first, old, _ = prior_fixture()
    text = 'The measurement pressure is 3.2 GPa. The transition temperature is approximately 4.7 K.'
    block = type(bundle.blocks[0])(id='authored-numeric-boundary', document_id=bundle.blocks[0].document_id,
        ordinal=max(b.ordinal for b in bundle.blocks) + 1, locator='context:authored boundary', text=text, sha256=sha(text.encode()))
    bundle.blocks.append(block)
    for span in targets(source_catalog(bundle)):
        first['span_assessments'].setdefault(span, dict(read=True, non_result_role='context_only', reason='Authored numeric boundary context.'))
    inventory, _ = typed.project(typed.TypedInventory.model_validate(first), bundle)
    raw = encode(bundle, old)
    raw['schema_version'] = wire.WIRE_VERSION
    raw.pop('processed_block_ids'); raw.pop('unread_block_ids')
    raw['block_decisions'] = {key: 'processed' for key in source_catalog(bundle)['blocks']}
    numbers = typed.catalog(bundle)['numeric_catalog']['numeric_candidates']
    pressure = next(k for k, row in numbers.items() if row['quote'] == '3.2 GPa')
    condition = deepcopy(raw['states'][0]['conditions'][0])
    condition.update(id='pressure-boundary', kind='pressure', role='measurement', window_position=None,
        quantity=dict(quantity_selection_id=pressure, quantity_status=None),
        basis_raw=text_choice(bundle, 'measurement pressure'), orientation_raw=None)
    raw['states'][0]['conditions'].append(condition)
    graph, proof = projected(raw, inventory, bundle)
    q = graph.states[0].conditions[-1].quantity
    assert q.value == 3.2 and q.unit == 'GPa' and q.raw == '3.2 GPa' and not q.approximate
    assert proof['copied_condition_or_parameter_quantities'][-1]['source']['quote'] == '3.2 GPa'
    # The input adapter does not accept hand-typed condition numbers at all.
    raw['states'][0]['conditions'][-1]['quantity'] = q.model_dump() | {'approximate': True}
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(raw, wire.output_schema(bundle, inventory))
    with pytest.raises((ValueError, ValidationError)): projected(raw, inventory, bundle)


@pytest.mark.parametrize('choice', [dict(quantity_selection_id=None, quantity_status=None),
    dict(quantity_selection_id='N1', quantity_status='ambiguous')])
def test_condition_quantity_selection_xor_is_required(choice):
    bundle, _, raw, inventory = fixture()
    raw['states'][0]['conditions'][0]['quantity'] = choice
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(raw, wire.output_schema(bundle, inventory))
    with pytest.raises((ValueError, ValidationError)): projected(raw, inventory, bundle)


@pytest.mark.parametrize('mutation', ['missing', 'unknown', 'unread'])
def test_block_decisions_are_closed_and_do_not_silently_claim_reading(mutation):
    bundle, _, raw, inventory = fixture()
    key = next(iter(raw['block_decisions']))
    if mutation == 'missing': raw['block_decisions'].pop(key)
    elif mutation == 'unknown': raw['block_decisions']['B_unknown'] = 'processed'
    else: raw['block_decisions'][key] = 'unread'
    if mutation == 'unread':
        graph, _ = projected(raw, inventory, bundle)
        assert graph.unread_block_ids == [source_catalog(bundle)['blocks'][key]['block_id']]
        assert graph.outcome == 'incomplete'
        assert not validate_extraction(graph, bundle)['valid']
    else:
        with pytest.raises(jsonschema.ValidationError): jsonschema.validate(raw, wire.output_schema(bundle, inventory))
        with pytest.raises(ValueError, match='source_block_decisions_not_closed'): projected(raw, inventory, bundle)


def test_false_positive_can_be_held_without_becoming_a_result_or_erased():
    bundle, _, raw, inventory = fixture()
    key = next(iter(raw['decisions']))
    raw['decisions'][key] = dict(decision='held', reason='not_a_result', explanation='Authored ordinary setting rather than a physical result.')
    graph, proof = projected(raw, inventory, bundle)
    assert all(result.id != 'item:' + key for result in graph.results)
    assert graph.outcome == 'incomplete'
    assert not proof['scientific_acceptance']
    assert raw['decisions'][key]['reason'] == 'not_a_result'


def test_prompt_uses_existing_coordinate_ledger_without_first_read_interpretation():
    bundle, _, _, inventory = fixture()
    inventory.items[0].sample_raw = 'INVENTORY_INTERPRETATION_CANARY'
    inventory.items[0].quantity_name_raw = 'UNVERIFIED_CRITICAL_PRESSURE_CANARY'
    before = inventory.model_dump()
    prompt = wire.render(bundle, inventory)
    assert 'INVENTORY_INTERPRETATION_CANARY' not in prompt
    assert 'UNVERIFIED_CRITICAL_PRESSURE_CANARY' not in prompt
    assert 'SOURCE_COORDINATE_LEDGER' in prompt and inventory.items[0].value_raw in prompt
    assert inventory.model_dump() == before
    # Historical policy still sees its historical inventory representation.
    assert 'INVENTORY_INTERPRETATION_CANARY' in wire_v16.render(bundle, inventory)


def test_real_worker_route_and_proposal_replay_preserve_the_original_response(tmp_path):
    bundle, first, raw, _ = fixture()
    store = Store(tmp_path)
    checksum, _ = save_bundle(store.root, bundle)
    config = configuration(workflow='inventory_v17')
    assert config['native_output_schema'] == 'materials-ner/13'
    assert config['max_inventory_repairs'] == config['max_extraction_repairs'] == config['max_evidence_patches'] == 0
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=checksum, config=config)
    run_one(store, job_id=job, provider_override=SequenceProvider([first, raw]))
    packet = import_packet(store, job)
    verify_packet(packet)
    assert packet['receipt']['state'] == 'succeeded', packet['receipt'].get('error_code')
    assert json.loads(packet['raw_output']) == raw
    assert packet['receipt']['extraction']['schema_version'] == 'materials-ner/13'
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']


@pytest.mark.parametrize('fault', ['nonliteral_quote', 'malformed_evidence'])
def test_bad_source_choice_closes_job_and_preserves_raw_failure(tmp_path, fault):
    bundle, first, raw, _ = fixture()
    if fault == 'nonliteral_quote':
        raw['states'][0]['pressure']['basis_raw']['quote'] = 'invented source phrase'
    else:
        raw['states'][0]['evidence'] = None
    store = Store(tmp_path)
    checksum, _ = save_bundle(store.root, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=checksum, config=configuration(workflow='inventory_v17'))
    class FaultInjectionProvider(SequenceProvider):
        def extract(self, prompt, schema, config, directory):
            if not self.calls:
                return super().extract(prompt, schema, config, directory)
            self.calls += 1
            # Intentionally exercise the worker's input boundary, even when a
            # normal constrained provider would reject this authored payload.
            return ProviderResult(canonical(raw), {}, 'authored_fault', 'gpt-6-luna', 'fixture', .01)
    run_one(store, job_id=job, provider_override=FaultInjectionProvider([first, raw]))
    packet = import_packet(store, job)
    verify_packet(packet)
    assert packet['receipt']['state'] == 'quarantined'
    assert packet['receipt']['error_code'] == 'inventory_accounting_projection_invalid'
    assert json.loads(packet['raw_output']) == raw
    assert not packet['rows']['results']
