"""Source census accounting, source ownership and finite recovery boundaries."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ingestion.materials_ner import paper_coverage as pc, reviewed_reader as reader, scoped_evidence
from ingestion.materials_ner.census import stage
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.providers import ProviderFailure, ProviderResult
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_reviewed_proposals import prepared


class Fake:
    def __init__(self, response, error=None):
        self.text = canonical(response)
        self.error = error
        self.calls = 0

    def extract(self, prompt, schema, config, directory):
        self.calls += 1
        assert config['model'] == 'gpt-6-luna' and config['reasoning'] == 'medium'
        assert schema['properties']['schema_version']['const'] == stage.OUTPUT_SCHEMA
        (directory / 'response.json').write_text(self.text)
        (directory / 'events.jsonl').write_text('{"type":"turn.completed"}\n')
        if self.error:
            raise self.error
        return ProviderResult(self.text, {'input_tokens': 10, 'output_tokens': 20}, 'codex', 'gpt-6-luna', 'synthetic', .1)


@pytest.fixture
def case(prepared, tmp_path):
    _, _, scope, _, manifest = prepared
    coverage = tmp_path / 'coverage.json'
    coverage.write_text(canonical(manifest))
    request = tmp_path / 'request.json'
    request.write_text(canonical(dict(schema=stage.INPUT_SCHEMA, scope=reader.reference(scope), coverage=reader.reference(coverage))))
    return Store(tmp_path / 'census'), request, stage.prepare(request)


def response(p):
    owner = p['targets'][0]
    return dict(schema_version=stage.OUTPUT_SCHEMA, limitations=[], units={owner: dict(disposition='has_results',
        note='Synthetic reported result.', occurrences=[dict(witness_ids=[owner],
            quote='The sample showed a resistive onset at 5 K.', value_raw='5 K', category='reported_result',
            description='A resistive onset; ownership remains unreviewed.')])})


def evaluate(p, body, tmp_path):
    result = {}
    stage.evaluate(p, canonical(body), tmp_path / 'evaluation', result)
    return result, json.loads(reader.checked(result['census_validation']).read_bytes())


def test_census_replays_once_without_proposals_or_scientific_completion(case):
    store, request, p = case
    fake = Fake(response(p)); job = stage.enqueue(store, request)
    result = stage.run(store, job, provider_override=fake)
    assert result['state'] == 'succeeded' and result['complete_unit_accounting']
    assert result['occurrence_count'] == 1 and result == stage.run(Store(store.root), job, provider_override=fake)
    assert fake.calls == store.summary()['attempts'] == 1
    assert not any(result[k] for k in ['scientific_acceptance', 'proposal_generated', 'paper_completed',
        'ml_training_eligible', 'source_completeness_established', 'scientific_relationships_resolved'])
    assert not (store.root / 'proposals.sqlite3').exists()


def test_legacy_worker_retry_and_full_corpus_dispatch_gates(case, tmp_path):
    store, request, p = case
    job = stage.enqueue(store, request); fake = Fake(response(p))
    assert store.claim(job_id=job) is None and run_one(store, job_id=job, provider_override=fake) is None
    assert not fake.calls and not store.summary()['attempts']
    with pytest.raises(ValueError, match='one_automatic_attempt'):
        store.enqueue(work_id=p['work_id'], bundle_hash=p['bundle_sha256'], config=stage.configuration(p), max_attempts=2)
    blocked = Store(tmp_path / 'full-corpus')
    (blocked.root / 'STAGING_PREPARATION.json').write_text('{}')
    with pytest.raises(ValueError, match='staging_preparation_only'):
        stage.enqueue(blocked, request)
    assert not blocked.summary()['jobs']


@pytest.mark.parametrize('change', ['missing_unit', 'extra_unit', 'unknown_witness', 'empty_result', 'null_numeric', 'no_result_with_occurrence'])
def test_accounting_schema_refuses_incomplete_or_misleading_decisions(case, tmp_path, change):
    _, _, p = case; body = response(p); key = p['targets'][0]; unit = body['units'][key]
    if change == 'missing_unit': body['units'] = {}
    elif change == 'extra_unit': body['units']['NOT_A_SOURCE_UNIT'] = deepcopy(unit)
    elif change == 'unknown_witness': unit['occurrences'][0]['witness_ids'] = ['invented']
    elif change == 'empty_result': unit['occurrences'] = []
    elif change == 'null_numeric': unit['occurrences'][0]['value_raw'] = None
    else: unit['disposition'] = 'no_result'
    result, report = evaluate(p, body, tmp_path)
    assert result['state'] == 'quarantined' and not report['complete_unit_accounting'] and report['schema_issues']


@pytest.mark.parametrize('change', ['fabricated_quote', 'fabricated_value', 'clipped_word', 'duplicate_witness', 'duplicate_occurrence'])
def test_literal_source_failures_are_held_without_mutating_model_output(case, tmp_path, change):
    _, _, p = case; body = response(p); occurrences = body['units'][p['targets'][0]]['occurrences']; item = occurrences[0]
    if change == 'fabricated_quote': item['quote'] = 'The onset is at 500 K.'
    elif change == 'fabricated_value': item['value_raw'] = '15 K'
    elif change == 'clipped_word': item['value_raw'] = 'set'
    elif change == 'duplicate_witness': item['witness_ids'] *= 2
    else: occurrences.append(deepcopy(item))
    original = deepcopy(body); result, report = evaluate(p, body, tmp_path)
    assert result['state'] == 'quarantined' and result['held_occurrences'] == 1
    assert report['complete_unit_accounting'] and not report['source_completeness_established']
    assert body == original and json.loads(reader.checked(result['model_census']).read_bytes()) == original


def test_context_value_cannot_be_reassigned_to_target_owner(case):
    _, _, p = case; p = deepcopy(p); block = p['bundle'].blocks[0]
    cut = block.text.index('The criterion')
    p['scope']['passages'] = [dict(block_id=block.id, start_char=0, end_char=cut, role='context'),
        dict(block_id=block.id, start_char=cut, end_char=len(block.text), role='target')]
    p['source_catalog'] = scoped_evidence.build(p['bundle'], p['scope']); p['targets'] = ['E0002']
    item = response(p)['units']['E0002']['occurrences'][0]; item['witness_ids'] = ['E0001', 'E0002']
    with pytest.raises(ValueError, match='wrong_owner'):
        stage.resolve_occurrence(p, 'E0002', item)


def test_adjacent_original_units_support_a_cross_boundary_value(case):
    _, _, p = case; p = deepcopy(p); block = p['bundle'].blocks[0]
    cut = block.text.index('5 K') + 1
    p['scope']['passages'] = [dict(block_id=block.id, start_char=0, end_char=cut, role='target'),
        dict(block_id=block.id, start_char=cut, end_char=len(block.text), role='target')]
    p['source_catalog'] = scoped_evidence.build(p['bundle'], p['scope']); p['targets'] = ['E0001', 'E0002']
    item = response(p)['units']['E0001']['occurrences'][0]; item['witness_ids'] = ['E0001', 'E0002']
    resolved = stage.resolve_occurrence(p, 'E0001', item)
    assert resolved['value_anchor']['quote'] == '5 K'
    with pytest.raises(ValueError, match='wrong_owner'):
        stage.resolve_occurrence(p, 'E0002', item)


def test_all_units_labelled_no_result_are_only_model_claims(case, tmp_path):
    _, _, p = case; body = response(p)
    body['units'][p['targets'][0]] = dict(disposition='no_result', occurrences=[], note='Synthetic incorrect absence claim.')
    result, report = evaluate(p, body, tmp_path)
    assert result['state'] == 'succeeded' and report['complete_unit_accounting']
    assert not report['source_completeness_established'] and not report['scientific_acceptance']


def test_unresolved_unit_is_not_completed_even_with_a_resolved_quote(case, tmp_path):
    _, _, p = case; body = response(p); body['units'][p['targets'][0]]['disposition'] = 'unresolved'
    result, report = evaluate(p, body, tmp_path)
    assert result['state'] == 'quarantined' and report['unresolved_units'] == p['targets']
    assert not report['held_occurrences']


def test_reference_inventory_is_withheld_and_budgets_do_not_truncate(case, monkeypatch):
    _, request, p = case; content = json.loads(request.read_bytes()); path = Path(content['coverage']['path'])
    m = p['coverage']; b = p['bundle']
    m = pc.build(bundle=b, **{**{k: m[k] for k in ('source', 'roles', 'visuals', 'dependencies', 'supplement', 'author', 'created_at')},
        'assertions': [dict(id='private', kind='text_result', visual=None, note='PRIVATE_REFERENCE_NEVER_SEND',
            anchor=dict(block_id=b.blocks[0].id, start_char=0, end_char=3, quote='The'))]})
    path.write_text(canonical(m)); content['coverage'] = reader.reference(path); request.write_text(canonical(content))
    after = stage.prepare(request)
    assert after['prompt'] == p['prompt'] and after['schema'] == p['schema']
    assert 'PRIVATE_REFERENCE' not in after['prompt']
    monkeypatch.setattr(stage, 'MAX_INPUT_TOKENS', 1)
    with pytest.raises(ValueError, match='input_budget_exceeded'): stage.prepare(request)


@pytest.mark.parametrize('artifact', ['input', 'response', 'model_census', 'census_validation', 'source_catalog', 'implementation'])
def test_changed_artifact_never_triggers_a_second_call(case, artifact):
    store, request, p = case; fake = Fake(response(p)); job = stage.enqueue(store, request)
    result = stage.run(store, job, provider_override=fake)
    if artifact == 'input': path = request
    elif artifact == 'response': path = next(store.root.glob('census-attempts/*/*/response.json'))
    elif artifact == 'implementation': path = next(store.root.glob('census-attempts/*/*/implementation/materials_ner/census/stage.py'))
    else: path = Path(result[artifact]['path'])
    path.write_text(path.read_text() + '\n')
    with pytest.raises(ValueError): stage.run(store, job, provider_override=fake)
    assert fake.calls == 1


def test_post_return_crash_recovers_without_redrafting(case, monkeypatch):
    store, request, p = case; fake = Fake(response(p)); job = stage.enqueue(store, request); original = stage.terminal
    def crash(*args, **kwargs): raise SystemExit('Synthetic post-return interruption.')
    monkeypatch.setattr(stage, 'terminal', crash)
    with pytest.raises(SystemExit): stage.run(store, job, provider_override=fake)
    monkeypatch.setattr(stage, 'terminal', original)
    recovered = stage.recover(store, job)
    assert recovered['recovered_without_provider_call'] and recovered['state'] == 'succeeded'
    assert stage.run(store, job, provider_override=fake) == recovered and fake.calls == 1


def test_uncertain_provider_completion_holds_queue(case):
    store, request, p = case; job = stage.enqueue(store, request)
    fake = Fake(response(p), ProviderFailure('codex_turn_failed', retryable=True))
    result = stage.run(store, job, provider_override=fake)
    assert result['outcome'] == 'completion_unknown' and (store.root / 'READER_DISPATCH_HOLD.json').exists()
    assert stage.run(store, job, provider_override=fake) == result and fake.calls == 1
