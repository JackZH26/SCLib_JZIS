"""Neutral occurrence focus preserves the native graph and portable audit trail."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ingestion.materials_ner import source_focus, source_projector as projector, reviewed_reader as reader
from ingestion.materials_ner import projector_proposals, projection_binding
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.proposals import ProposalDatabase, verify_packet
from ingestion.materials_ner.providers import ProviderResult, ProviderFailure
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_catalog_projector import catalog_case
from test_materials_ner_reviewed_proposals import prepared, at


@pytest.fixture
def focused_case(catalog_case, tmp_path):
    old_path, old, graph = catalog_case
    request = json.loads(old_path.read_bytes())
    request.update(schema=projector.NATIVE14_INPUT_SCHEMA, graph_schema='materials-ner/14')
    native = tmp_path / 'native.json'; reader.put(native, request)
    native_prepared = projector.prepare(native)
    body = dict(schema=source_focus.VERSION, work_id=old['work_id'], bundle_sha256=old['bundle_sha256'],
        source_catalog_sha256=digest(old['source_catalog']), all_occurrence_ids=['E0001:1', 'E0001:2'],
        occurrences={'E0001:1': dict(owner='E0001',
            anchor=at(old['bundle'].blocks[0], 'The sample showed a resistive onset at 5 K.'),
            value_anchor=at(old['bundle'].blocks[0], '5 K'))})
    focus = tmp_path / 'focus.json'; reader.put(focus, body)
    request.update(schema=projector.FOCUSED_INPUT_SCHEMA, source_focus=reader.reference(focus),
        execution_profile=dict(schema=projector.EXECUTION_PROFILE_SCHEMA, model='gpt-6-luna', reasoning='high'))
    path = tmp_path / 'focused.json'; reader.put(path, request)
    graph = deepcopy(graph); graph['schema_version'] = 'materials-ner/14'
    return path, projector.prepare(path), graph, native_prepared


class Fake:
    def __init__(self, graph, error=None):
        self.graph = graph; self.calls = 0; self.error = error

    def extract(self, prompt, schema, config, directory):
        self.calls += 1
        assert config['model'] == 'gpt-6-luna' and config['reasoning'] == 'high'
        assert config['execution_profile']['reasoning'] == 'high'
        assert 'ORIGINAL OCCURRENCE FOCUS' in prompt
        text = canonical(self.graph); (directory / 'response.json').write_text(text)
        if self.error: raise self.error
        return ProviderResult(text, {'input_tokens': 10, 'output_tokens': 20}, 'codex', 'gpt-6-luna', 'synthetic', .1)


def test_focus_changes_input_not_native_scientific_contract(focused_case):
    _, p, _, previous = focused_case
    assert p['schema'] == previous['schema']
    assert p['source_catalog'] == previous['source_catalog'] and p['scope'] == previous['scope']
    assert p['prompt'].startswith(previous['prompt'])
    assert 'ORIGINAL OCCURRENCE FOCUS' not in previous['prompt']
    assert projector.configuration(previous)['reasoning'] == 'medium'
    assert 'source_focus_sha256' not in projector.configuration(previous)
    assert projector.configuration(p)['source_focus_sha256'] == digest(p['source_focus'])


def test_focused_graph_and_inventory_replay_portably_without_scientific_admission(focused_case, tmp_path, monkeypatch):
    path, p, graph, _ = focused_case
    store = Store(tmp_path / 'focused-queue'); fake = Fake(graph)
    job = projector.enqueue(store, path); result = projector.run(store, job, provider_override=fake)
    assert result['state'] == 'succeeded', result
    inventory = json.loads(reader.checked(result['source_focus_inventory']).read_bytes())
    mapping = json.loads(reader.checked(result['source_focus_mapping']).read_bytes())
    assert inventory['selected_count'] == 1 and inventory['unselected_occurrence_ids'] == ['E0001:2']
    assert mapping['literal_candidate_count'] == 1 and mapping['unrepresented_count'] == 0
    assert mapping['occurrences'][0]['disposition'] == 'literal_candidates_pending_review'
    assert not mapping['scientific_acceptance'] and not mapping['paper_completed']
    assert projector.run(Store(store.root), job, provider_override=fake) == result and fake.calls == 1
    packet = projector_proposals.build(store.root, job)
    review = packet['receipt']['paper_review']['source_focus']
    assert review['inventory'] == inventory and review['mapping'] == mapping
    assert not review['scientific_mapping_reviewed']
    assert projection_binding.scientific_payload(packet['receipt']['extraction']) == projection_binding.scientific_payload(graph)
    db = ProposalDatabase(tmp_path / 'synthetic-proposals')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    with db.connect() as connection:
        restored = json.loads(connection.execute('SELECT payload FROM runs').fetchone()[0])
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    def forbidden(*args, **kwargs): raise AssertionError('Portable verification touched live files or provider.')
    monkeypatch.setattr(reader, 'checked', forbidden); monkeypatch.setattr(fake, 'extract', forbidden)
    verify_packet(restored)
    assert not restored['scientific_acceptance'] and not restored['ml_training_eligible']


@pytest.mark.parametrize('change', ['work', 'bundle', 'catalog', 'extra_label', 'owner', 'quote',
    'value_outside', 'clipped_literal', 'duplicate', 'missing_selected_id', 'duplicate_inventory', 'too_many'])
def test_invalid_or_answer_bearing_focus_fails_before_dispatch(focused_case, tmp_path, change):
    path, p, _, _ = focused_case
    body = deepcopy(p['source_focus']); item = body['occurrences']['E0001:1']
    if change == 'work': body['work_id'] = 'other-work'
    elif change == 'bundle': body['bundle_sha256'] = '0' * 64
    elif change == 'catalog': body['source_catalog_sha256'] = '0' * 64
    elif change == 'extra_label': item['expected_role'] = 'property_result'
    elif change == 'owner': item['owner'] = 'E9999'
    elif change == 'quote': item['anchor']['quote'] = 'Invented superconductivity.'
    elif change == 'value_outside': item['anchor'] = at(p['bundle'].blocks[0], 'The criterion is onset.')
    elif change == 'clipped_literal':
        anchor = at(p['bundle'].blocks[0], 'onset')
        item['value_anchor'] = {**anchor, 'start_char': anchor['start_char'] + 2, 'quote': 'set'}
    elif change == 'duplicate': body['occurrences']['E0001:2'] = deepcopy(item)
    elif change == 'missing_selected_id': body['all_occurrence_ids'] = ['E0001:2']
    elif change == 'duplicate_inventory': body['all_occurrence_ids'] *= 2
    else:
        body['all_occurrence_ids'] = [f'E0001:{i}' for i in range(1, 10)]
        body['occurrences'] = {key: deepcopy(item) for key in body['all_occurrence_ids']}
    focus = tmp_path / 'invalid-focus.json'; reader.put(focus, body)
    request = json.loads(path.read_bytes()); request['source_focus'] = reader.reference(focus)
    target = tmp_path / 'invalid.json'; reader.put(target, request)
    store = Store(tmp_path / 'invalid-queue')
    with pytest.raises(ValueError): projector.enqueue(store, target)
    assert store.summary()['jobs'] == 0


@pytest.mark.parametrize('change', ['missing_focus', 'legacy', 'wrong_model', 'wrong_effort', 'profile_extra'])
def test_focused_request_requires_explicit_supported_profile(focused_case, change):
    path, _, _, _ = focused_case; request = json.loads(path.read_bytes())
    if change == 'missing_focus': request.pop('source_focus')
    elif change == 'legacy': request['schema'] = projector.NATIVE14_INPUT_SCHEMA
    elif change == 'wrong_model': request['execution_profile']['model'] = 'gpt-6.1-sol'
    elif change == 'wrong_effort': request['execution_profile']['reasoning'] = 'max'
    else: request['execution_profile']['temperature'] = 0
    with pytest.raises(ValueError, match='projector_(input_shape|execution_profile_invalid)'):
        projector.request_contract(request)


def test_broad_quantity_context_does_not_discharge_literal_accounting(focused_case, tmp_path):
    path, p, graph, _ = focused_case; store = Store(tmp_path / 'mapping-queue')
    result = projector.run(store, projector.enqueue(store, path), provider_override=Fake(graph))
    compiled = json.loads(reader.checked(result['graph']).read_bytes())
    for entity in compiled['results']:
        entity['evidence'] = [e for e in entity['evidence'] if e['field'] != '/quantity/raw']
    report = source_focus.mapping(p['source_focus'], compiled)
    assert report['selected_count'] == report['unrepresented_count'] == 1
    assert report['occurrences'][0]['disposition'] == 'unrepresented_pending_review'


def test_native_contract_failure_keeps_all_focused_occurrences(focused_case, tmp_path):
    path, _, graph, _ = focused_case
    graph['results'][0]['quantity']['value'] = None
    store = Store(tmp_path / 'bad-graph'); result = projector.run(store, projector.enqueue(store, path), provider_override=Fake(graph))
    assert result['state'] == 'quarantined'
    assert json.loads(reader.checked(result['source_focus_inventory']).read_bytes())['selected_count'] == 1
    assert 'source_focus_mapping' not in result
    packet = projector_proposals.build(store.root, result['job_id'])
    assert packet['receipt']['paper_review']['source_focus']['mapping'] is None
    assert not packet['scientific_acceptance']


@pytest.mark.parametrize('change', ['focus_json', 'mapping', 'review_flag'])
def test_rehashed_portable_packet_cannot_change_focus_or_approve_it(focused_case, tmp_path, change):
    path, _, graph, _ = focused_case; store = Store(tmp_path / 'packet')
    result = projector.run(store, projector.enqueue(store, path), provider_override=Fake(graph))
    packet = projector_proposals.build(store.root, result['job_id']); receipt = packet['receipt']
    if change == 'focus_json': receipt['projector_provenance']['source_focus_json'] += '\n'
    elif change == 'mapping': receipt['paper_review']['source_focus']['mapping']['occurrences'] = []
    else: receipt['paper_review']['source_focus']['scientific_mapping_reviewed'] = True
    packet['run_id'] = digest(receipt); packet['packet_hash'] = digest({k: v for k, v in packet.items() if k != 'packet_hash'})
    with pytest.raises(ValueError): verify_packet(packet)


def test_focus_drift_and_uncertain_completion_never_retry(focused_case, tmp_path):
    path, p, graph, _ = focused_case; store = Store(tmp_path / 'drift')
    job = projector.enqueue(store, path); focus = Path(p['request']['source_focus']['path'])
    original = focus.read_bytes(); focus.write_bytes(original + b' ')
    fake = Fake(graph); result = projector.run(store, job, provider_override=fake)
    assert result['state'] == 'blocked' and result['outcome'] == 'not_dispatched' and fake.calls == 0
    focus.write_bytes(original)
    store = Store(tmp_path / 'uncertain'); job = projector.enqueue(store, path)
    fake = Fake(graph, ProviderFailure('codex_timeout_or_interruption'))
    result = projector.run(store, job, provider_override=fake)
    assert result['state'] == 'blocked' and result['outcome'] == 'completion_unknown'
    assert projector.run(store, job, provider_override=fake) == result and fake.calls == 1


def test_focused_requests_do_not_enable_default_or_corpus_dispatch(focused_case, tmp_path):
    path, _, graph, _ = focused_case; store = Store(tmp_path / 'isolated')
    job = projector.enqueue(store, path); fake = Fake(graph)
    assert run_one(store, job_id=job, provider_override=fake) is None and fake.calls == 0
    blocked = Store(tmp_path / 'full-corpus'); (blocked.root / 'STAGING_PREPARATION.json').write_text('{}')
    with pytest.raises(ValueError, match='staging_preparation_only'): projector.enqueue(blocked, path)
    assert blocked.summary()['jobs'] == 0
