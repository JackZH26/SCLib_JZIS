"""Inventory bookkeeping cannot manufacture or certify a scientific result."""
from copy import deepcopy
import json

import jsonschema
import pytest

from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.inventory import Inventory, ContextAssertion
from ingestion.materials_ner.proposals import ProposalDatabase, import_packet, verify_packet
from ingestion.materials_ner.sources import save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.wire_v10 import DetectionExtraction
from ingestion.materials_ner.wire_v11 import (AccountedExtraction, AccountingError,
    output_schema, scientific_graph, validate_coverage, verify_extraction, render)
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_non_detection_targets import fixture as previous_fixture


def fixture():
    bundle, inventory, previous = previous_fixture()
    raw = deepcopy(previous)
    raw.update(schema_version='materials-ner-shared/7', inventory_dispositions={}, no_result_reason=None)
    raw.pop('completion'); raw.pop('unextracted_items')
    for observation in raw['observations']:
        for identifier in observation.pop('inventory_item_ids'):
            raw['inventory_dispositions'][identifier] = {'kind': 'emitted', 'result_id': observation['id']}
    return bundle, Inventory.model_validate(inventory), raw, previous


def empty_fixture():
    bundle, inventory, raw, _ = fixture()
    inventory.items = []; inventory.context_assertions = []
    for disposition in inventory.span_dispositions:
        disposition.role = 'no_relevant_result'; disposition.item_ids = []; disposition.reason = 'Synthetic empty source control.'
    for key in ('samples', 'states', 'protocols', 'observations', 'sample_relations', 'condition_supports', 'context_dispositions'):
        raw[key] = []
    raw['inventory_dispositions'] = {}; raw['no_result_reason'] = 'Synthetic empty source control.'
    return bundle, inventory, raw


def test_keyed_schema_and_projection_preserve_the_complete_scientific_graph():
    bundle, inventory, raw, previous = fixture()
    schema = output_schema(bundle, inventory)
    jsonschema.Draft202012Validator.check_schema(schema); jsonschema.validate(raw, schema)
    projected, proof = AccountedExtraction.model_validate(raw).project(inventory, bundle)
    assert projected.model_dump() == previous
    assert scientific_graph(raw) == scientific_graph(projected.model_dump())
    assert proof['scientific_assertions_unchanged'] and not proof['scientific_acceptance']
    assert validate_coverage(projected, inventory, bundle)['valid']
    assert validate_extraction(projected.expand(bundle), bundle)['valid']
    assert AccountedExtraction.parse_response(canonical(raw)).project(inventory, bundle)[1] == proof
    assert 'outcome=' not in render(bundle, inventory)


@pytest.mark.parametrize('mutation,code', [
    ('missing_key', 'accounting_inventory_keys_not_closed'),
    ('invented_key', 'accounting_inventory_keys_not_closed'),
    ('unknown_result', 'accounting_result_reference_missing'),
    ('duplicate_result', 'accounting_duplicate_result_id'),
    ('orphan_result', 'accounting_result_without_source_item'),
    ('reason_with_results', 'accounting_reason_with_observations'),
])
def test_projection_refuses_missing_keys_or_invented_graph_links(mutation, code):
    bundle, inventory, raw, _ = fixture()
    key = inventory.items[0].id
    if mutation == 'missing_key': raw['inventory_dispositions'].pop(key)
    if mutation == 'invented_key': raw['inventory_dispositions']['invented'] = deepcopy(raw['inventory_dispositions'][key])
    if mutation == 'unknown_result': raw['inventory_dispositions'][key]['result_id'] = 'invented'
    if mutation == 'duplicate_result': raw['observations'].append(deepcopy(raw['observations'][0]))
    if mutation == 'orphan_result': raw['observations'].append(dict(deepcopy(raw['observations'][0]), id='unlinked'))
    if mutation == 'reason_with_results': raw['no_result_reason'] = 'Contradicts the graph.'
    if mutation in {'missing_key', 'invented_key'}:
        with pytest.raises(jsonschema.ValidationError): jsonschema.validate(raw, output_schema(bundle, inventory))
    with pytest.raises(AccountingError, match=code):
        AccountedExtraction.model_validate(raw).project(inventory, bundle)


def test_duplicate_json_keys_cannot_be_silently_discarded_before_accounting():
    with pytest.raises(AccountingError, match='accounting_duplicate_json_key'):
        AccountedExtraction.parse_response('{"inventory_dispositions":{"I1":{},"I1":{}}}')
    with pytest.raises(AccountingError, match='accounting_invalid_json'):
        AccountedExtraction.parse_response('{')


def test_emitted_inventory_with_empty_observations_is_not_a_successful_empty_or_partial_graph():
    # Failure observed in the real methods-window prompt retest: named results
    # describe intended work but the observation objects were never emitted.
    bundle, inventory, raw, _ = fixture()
    raw['observations'] = []
    raw['no_result_reason'] = 'The graph could not be completed.'
    before = deepcopy(raw)
    with pytest.raises(AccountingError, match='accounting_result_reference_missing'):
        AccountedExtraction.model_validate(raw).project(inventory, bundle)
    assert raw == before


def test_additional_ids_avoid_collisions_and_equal_values_do_not_merge_results():
    bundle, inventory, raw, _ = fixture()
    original_id = inventory.items[0].id; inventory.items[0].id = 'additional:1'
    raw['inventory_dispositions']['additional:1'] = raw['inventory_dispositions'].pop(original_id)
    for span in inventory.span_dispositions:
        span.item_ids = ['additional:1' if key == original_id else key for key in span.item_ids]
    raw['additional_items'] = [dict(inventory.items[0].model_dump(exclude={'id'}),
        disposition={'kind': 'emitted', 'result_id': 'distinct-result'})]
    raw['observations'].append(dict(deepcopy(raw['observations'][0]), id='distinct-result'))
    projected, proof = AccountedExtraction.model_validate(raw).project(inventory, bundle)
    assert proof['additional_id_assignments'] == [{'index': 0, 'id': 'additional:additional:1'}]
    assert len(projected.observations) == len(raw['observations'])
    assert projected.observations[-1].inventory_item_ids == ['additional:additional:1']
    assert projected.additional_items[0].value_raw == inventory.items[0].value_raw
    assert validate_coverage(projected, inventory, bundle)['valid']


@pytest.mark.parametrize('reason', ['not_a_result', 'insufficient_context', 'unresolved'])
def test_held_source_items_never_become_successful_empty_or_scientific_negatives(reason):
    bundle, inventory, raw, _ = fixture()
    raw['observations'] = []; raw['context_dispositions'] = []; raw['condition_supports'] = []; inventory.context_assertions = []
    raw['inventory_dispositions'] = {item.id: {'kind': 'held', 'reason': reason,
        'explanation': 'The statement concerns a theoretical phase, with no measurement.'} for item in inventory.items}
    raw['no_result_reason'] = 'No measured result was represented.'
    projected, proof = AccountedExtraction.model_validate(raw).project(inventory, bundle)
    assert projected.completion.outcome == 'incomplete'
    assert len(projected.unextracted_items) == len(inventory.items)
    assert projected.expand(bundle).results == []
    assert 'held_source_items' in proof['incomplete_reasons']
    assert not validate_coverage(projected, inventory, bundle)['valid']


def test_empty_requires_reason_complete_source_and_no_unresolved_context():
    bundle, inventory, raw = empty_fixture()
    projected, _ = AccountedExtraction.model_validate(raw).project(inventory, bundle)
    assert projected.expand(bundle).outcome == 'empty'
    missing = deepcopy(raw); missing['no_result_reason'] = None
    with pytest.raises(AccountingError, match='accounting_empty_reason_missing'):
        AccountedExtraction.model_validate(missing).project(inventory, bundle)
    unread = deepcopy(raw); unread['unread_block_ids'] = unread['processed_block_ids']; unread['processed_block_ids'] = []
    assert AccountedExtraction.model_validate(unread).project(inventory, bundle)[0].completion.outcome == 'incomplete'
    lost = deepcopy(raw); lost['processed_block_ids'] = []
    assert AccountedExtraction.model_validate(lost).project(inventory, bundle)[0].completion.outcome == 'incomplete'
    inventory.context_assertions.append(ContextAssertion(id='C1', kind='condition', description='unresolved', span_ids=['S1']))
    raw['context_dispositions'] = [{'context_id': 'C1', 'resolution': 'unresolved',
                                    'bindings': [], 'explanation': 'Unresolved source context.'}]
    assert AccountedExtraction.model_validate(raw).project(inventory, bundle)[0].completion.outcome == 'incomplete'


def test_worker_and_private_packet_replay_accounting_without_promoting(tmp_path):
    bundle, inventory, raw, _ = fixture(); store = Store(tmp_path)
    bundle_hash, _ = save_bundle(tmp_path, bundle); config = configuration(workflow='inventory_v11')
    assert config['max_evidence_patches'] == config['max_extraction_repairs'] == 0
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=config)
    outcome = run_one(store, job_id=job, provider_override=SequenceProvider([inventory.model_dump(), raw]))
    assert outcome['state'] == 'succeeded', outcome
    packet = import_packet(store, job); verify_packet(packet)
    assert packet['receipt']['extraction']['schema_version'] == 'materials-ner/8'
    assert packet['receipt']['inventory_accounting_projection']['completion']['outcome'] == 'results'
    database = ProposalDatabase(tmp_path/'private')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    with database.connect() as connection:
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert json.loads(connection.execute('SELECT payload FROM runs').fetchone()[0]) == packet
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    changed = deepcopy(packet['receipt']); changed['inventory_accounting_projection']['completion']['outcome'] = 'empty'
    with pytest.raises(ValueError, match='inventory_accounting_proof_mismatch'):
        verify_extraction(changed, bundle, canonical(raw))
    changed = deepcopy(packet['receipt']); changed['extraction']['results'][0]['quantity']['value'] = 999
    with pytest.raises(ValueError, match='accounted_extraction_reconstruction_mismatch'):
        verify_extraction(changed, bundle, canonical(raw))


def test_worker_retains_invalid_accounting_as_a_failed_raw_attempt(tmp_path):
    bundle, inventory, raw, _ = fixture(); raw['inventory_dispositions'][inventory.items[0].id]['result_id'] = 'unknown'
    store = Store(tmp_path); key, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=key, config=configuration(workflow='inventory_v11'))
    outcome = run_one(store, job_id=job, provider_override=SequenceProvider([inventory.model_dump(), raw]))
    assert outcome['state'] == 'quarantined'
    packet = import_packet(store, job); verify_packet(packet)
    assert packet['receipt']['inventory_accounting_error']['code'] == 'accounting_result_reference_missing'
    assert json.loads(packet['raw_output']) == raw
    assert not packet['receipt'].get('extraction')
