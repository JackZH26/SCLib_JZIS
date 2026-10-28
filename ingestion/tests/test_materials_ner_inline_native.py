"""Inline record completeness and exact copying are not scientific approval."""
from copy import deepcopy

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner import wire_v15 as wire, typed_inventory_v3 as typed
from ingestion.materials_ner import canonical_preview, item_stages
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.sources import save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import configuration, run_one
from ingestion.materials_ner.proposals import import_packet, verify_packet
from test_materials_ner_selected_native import fixture as previous_fixture
from test_materials_ner_inventory_v2 import SequenceProvider


def fixture(kind='tc_pressure_slope'):
    bundle, first, raw = previous_fixture(kind)
    cat = typed.catalog(bundle)
    item_by_result = {v['result_id']: k for k, v in raw['inventory_dispositions'].items()}
    result_ids = {key: item_stages.result_id(value) for key, value in item_by_result.items()}
    def convert(value):
        if isinstance(value, list):
            return [convert(v) for v in value]
        if isinstance(value, dict):
            if set(value) == {'selection_id', 'quote', 'fields'}:
                return {k: value[k] for k in ('selection_id', 'fields')}
            return {k: result_ids.get(v, v) if k == 'result_id' and isinstance(v, str) else convert(v)
                    for k, v in value.items()}
        return value
    transport = convert(raw); transport['schema_version'] = wire.WIRE_VERSION
    transport['decisions'] = {}
    for observation in transport.pop('observations'):
        key = item_by_result[observation.pop('id')]
        result = observation['result']; quantity = result.pop('quantity')
        number = next(k for k, v in cat['numeric_catalog']['numeric_candidates'].items()
                      if v['selectable'] and v['quote'] == quantity['raw'])
        result.update(quantity_selection_id=number, quantity_status=None)
        transport['decisions'][key] = dict(decision='emitted', observation=observation)
    transport.pop('inventory_dispositions')
    return bundle, first, transport


@pytest.mark.parametrize('kind', ['tc_pressure_slope', 'electrical_resistivity'])
def test_inline_schema_and_projection_preserve_source_shape(kind):
    b, first, raw = fixture(kind)
    inventory, _ = typed.project(typed.TypedInventory.model_validate(first), b)
    schema = wire.output_schema(b, inventory)
    jsonschema.Draft202012Validator.check_schema(schema); jsonschema.validate(raw, schema)
    compact, proof = wire.AccountedExtraction.model_validate(raw).project(inventory, b)
    graph = compact.expand(b)
    assert len(graph.results) == len(first['entries'])
    row = proof['copied_quantities'][-1]
    assert graph.results[-1].quantity.model_dump() == row['quantity']
    assert graph.results[-1].quantity.raw == row['source']['quote']
    assert graph.results[-1].quantity.uncertainty is not None
    assert graph.results[-1].quantity.approximate == (kind == 'tc_pressure_slope')
    assert not proof['scientific_acceptance']


@pytest.mark.parametrize('damage', ['missing_record', 'old_pointer', 'missing_decision', 'raw_quote'])
def test_schema_cannot_express_an_emitted_pointer_without_its_record(damage):
    b, first, raw = fixture()
    inventory, _ = typed.project(typed.TypedInventory.model_validate(first), b)
    if damage == 'missing_record':
        raw['decisions']['I1'].pop('observation')
    elif damage == 'old_pointer':
        raw['decisions']['I1'] = dict(decision='emitted', result_id='not_created')
    elif damage == 'missing_decision':
        raw['decisions'].pop('I1')
    else:
        raw['samples'][0]['evidence'][0]['quote'] = 'Invented source quotation'
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, wire.output_schema(b, inventory))


def run_fixture(tmp_path):
    b, first, raw = fixture()
    store = Store(tmp_path/'queue'); hashed, _ = save_bundle(store.root, b)
    job = store.enqueue(work_id=b.work_id, bundle_hash=hashed,
        config=configuration(workflow='inventory_v15'), max_attempts=1)
    provider = SequenceProvider([first, raw]); outcome = run_one(store, job_id=job, provider_override=provider)
    packet = import_packet(store, job); verify_packet(packet)
    return provider, outcome, packet


def test_worker_replay_and_read_only_mapping(tmp_path):
    provider, outcome, packet = run_fixture(tmp_path)
    assert outcome['state'] == 'succeeded', outcome
    assert provider.calls == 2
    assert packet['receipt']['inventory_accounting_projection']['schema'] == wire.PROJECTION_VERSION
    assert packet['receipt']['extraction']['schema_version'] == 'materials-ner/12'
    preview = canonical_preview.build(packet)
    assert canonical_preview.retained_graph(preview, packet) == packet['receipt']['extraction']
    assert any(x['candidate_fields'] for x in preview['results'])
    assert not preview['database_writes'] and not preview['scientific_acceptance']


@pytest.mark.parametrize('shared', [True, False])
def test_repeated_mention_is_explicit_and_equal_values_do_not_auto_merge(shared):
    b, first, raw = fixture()
    first['entries'].append(deepcopy(first['entries'][0]))
    key = f"I{len(first['entries'])}"
    if shared:
        raw['decisions'][key] = dict(decision='repeated_mention', emitted_item_id='I1',
            explanation='Authored repeated-mention decision, not a deduplication inference.',
            evidence=deepcopy(raw['decisions']['I1']['observation']['result']['evidence']))
    else:
        raw['decisions'][key] = deepcopy(raw['decisions']['I1'])
    inventory, _ = typed.project(typed.TypedInventory.model_validate(first), b)
    compact, proof = wire.AccountedExtraction.model_validate(raw).project(inventory, b)
    assert len(compact.observations) == len(first['entries']) - int(shared)
    assert bool(proof['repeated_mentions']) == shared
    assert not proof['scientific_acceptance']


@pytest.mark.parametrize('damage', ['unknown_number', 'two_quantity_sources', 'held_leader'])
def test_incompatible_or_unfulfilled_selections_are_not_compiled(damage):
    b, first, raw = fixture()
    inventory, _ = typed.project(typed.TypedInventory.model_validate(first), b)
    if damage == 'unknown_number':
        raw['decisions']['I1']['observation']['result']['quantity_selection_id'] = 'N404'
    elif damage == 'two_quantity_sources':
        raw['decisions']['I1']['observation']['result']['quantity_status'] = 'ambiguous'
    else:
        evidence = raw['decisions']['I1']['observation']['result']['evidence']
        raw['decisions']['I1'] = dict(decision='repeated_mention', emitted_item_id='I2', explanation='Authored invalid reference.', evidence=evidence)
        raw['decisions']['I2'] = dict(decision='held', reason='unresolved', explanation='No emitted leader exists.')
    with pytest.raises((ValueError, ValidationError)):
        wire.AccountedExtraction.model_validate(raw).project(inventory, b)


def test_receipt_replay_rejects_a_tampered_quantity_projection(tmp_path):
    _, _, packet = run_fixture(tmp_path)
    broken = deepcopy(packet)
    broken['receipt']['inventory_accounting_projection']['copied_quantities'][0]['quantity']['value'] = 999
    broken['run_id'] = digest(broken['receipt'])
    with pytest.raises(ValueError):
        verify_packet(broken)
