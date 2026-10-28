"""Role-stage provenance, evidence, isolation and no-retry behavior."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ingestion.materials_ner import reviewed_reader as reader
from ingestion.materials_ner.census import roles, stage as census
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.providers import ProviderFailure, ProviderResult
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_source_census import case, response as census_response, Fake as CensusFake
from test_materials_ner_reviewed_proposals import prepared


class Fake:
    def __init__(self, body, error=None):
        self.text = canonical(body); self.calls = 0; self.error = error

    def extract(self, prompt, schema, config, directory):
        self.calls += 1
        assert config['workflow'] == roles.WORKFLOW and config['model'] == 'gpt-6-luna'
        assert 'PRIVATE_CENSUS_DESCRIPTION' not in prompt and '"category"' not in prompt
        (directory / 'response.json').write_text(self.text)
        if self.error:
            raise self.error
        return ProviderResult(self.text, {'input_tokens': 10, 'output_tokens': 20}, 'codex', 'gpt-6-luna', 'synthetic', .1)


@pytest.fixture
def role_case(case, tmp_path):
    store, source_request, p = case
    body = census_response(p)
    for unit in body['units'].values():
        for item in unit['occurrences']:
            item['category'] = 'comparison'
            item['description'] = 'PRIVATE_CENSUS_DESCRIPTION'
    job = census.enqueue(store, source_request)
    census.run(store, job, provider_override=CensusFake(body))
    receipt = reader.reference(census.row(store, job)['result_path'])
    request = tmp_path / 'roles-input.json'
    reader.put(request, dict(schema=roles.INPUT_SCHEMA, census_request=reader.reference(source_request), census_receipt=receipt))
    return Store(tmp_path / 'roles'), request, roles.prepare(request)


def response(p):
    return dict(schema_version=roles.OUTPUT_SCHEMA, limitations=[], decisions={key: dict(
        role='property_result', origin='current_work', basis='measured', quantity_raw='resistive onset',
        subject_raw='sample', evidence=[dict(witness_ids=[value['owner']], quote=value['quote'])],
        note='The supplied sentence explicitly reports an observed resistive onset.')
        for key, value in p['occurrences'].items()})


def evaluate(p, body, tmp_path):
    result = {}
    roles.evaluate(p, canonical(body), tmp_path / 'evaluation', result)
    return result, json.loads(reader.checked(result['role_validation']).read_bytes())


def test_model_labels_withheld_and_replay_does_not_admit_science(role_case):
    store, request, p = role_case
    assert 'PRIVATE_CENSUS_DESCRIPTION' not in p['prompt'] and '"category"' not in p['prompt']
    fake = Fake(response(p)); job = roles.enqueue(store, request)
    result = roles.run(store, job, provider_override=fake)
    assert result['state'] == 'succeeded' and result['occurrence_count'] == 1
    assert roles.run(Store(store.root), job, provider_override=fake) == result
    assert fake.calls == store.summary()['attempts'] == 1
    assert not any(result[k] for k in ['scientific_acceptance', 'proposal_generated', 'paper_completed',
        'ml_training_eligible', 'scientific_roles_reviewed', 'scientific_relationships_resolved', 'source_completeness_established'])
    assert not (store.root / 'proposals.sqlite3').exists()


@pytest.mark.parametrize('change', ['missing', 'extra', 'invented_role', 'invented_origin'])
def test_every_occurrence_requires_one_typed_decision(role_case, tmp_path, change):
    _, _, p = role_case; body = response(p); key = next(iter(p['occurrences']))
    if change == 'missing': body['decisions'].pop(key)
    elif change == 'extra': body['decisions']['invented'] = deepcopy(body['decisions'][key])
    elif change == 'invented_role': body['decisions'][key]['role'] = 'accepted_material'
    else: body['decisions'][key]['origin'] = 'external_knowledge'
    result, report = evaluate(p, body, tmp_path)
    assert result['state'] == 'quarantined' and report['schema_issues']


@pytest.mark.parametrize('change', ['quote', 'subject', 'quantity', 'wrong_value', 'duplicate_witness', 'unknown_witness'])
def test_claims_need_source_support_for_the_locked_occurrence(role_case, tmp_path, change):
    _, _, p = role_case; body = response(p); item = next(iter(body['decisions'].values()))
    if change == 'quote': item['evidence'][0]['quote'] = 'Observed superconductivity at 500 K.'
    elif change == 'subject': item['subject_raw'] = 'InventedCompound'
    elif change == 'quantity': item['quantity_raw'] = 'critical pressure'
    elif change == 'wrong_value': item['evidence'][0]['quote'] = 'The sample showed a resistive onset'
    elif change == 'duplicate_witness': item['evidence'][0]['witness_ids'] *= 2
    else: item['evidence'][0]['witness_ids'] = ['unknown']
    result, report = evaluate(p, body, tmp_path)
    assert result['state'] == 'quarantined'
    assert report['schema_issues'] or report['held_decisions'] == 1
    assert json.loads(reader.checked(result['model_roles']).read_bytes()) == body


def test_unresolved_is_retained_as_a_hold(role_case, tmp_path):
    _, _, p = role_case; body = response(p); next(iter(body['decisions'].values()))['role'] = 'unresolved'
    result, report = evaluate(p, body, tmp_path)
    assert result['state'] == 'quarantined' and report['decisions'][0]['holds'] == ['roles_unresolved']


def test_budgets_and_default_worker_and_full_corpus_remain_closed(role_case, tmp_path, monkeypatch):
    store, request, p = role_case
    job = roles.enqueue(store, request); fake = Fake(response(p))
    assert store.claim(job_id=job) is None and run_one(store, job_id=job, provider_override=fake) is None
    assert fake.calls == store.summary()['attempts'] == 0
    with pytest.raises(ValueError, match='one_automatic_attempt'):
        store.enqueue(work_id=p['work_id'], bundle_hash=p['bundle_sha256'], config=roles.configuration(p), max_attempts=2)
    blocked = Store(tmp_path / 'full-corpus'); (blocked.root / 'STAGING_PREPARATION.json').write_text('{}')
    with pytest.raises(ValueError, match='staging_preparation_only'): roles.enqueue(blocked, request)
    assert blocked.summary()['jobs'] == 0
    monkeypatch.setattr(roles, 'MAX_OCCURRENCES', 0)
    with pytest.raises(ValueError, match='occurrence_budget'): roles.prepare(request)
    monkeypatch.setattr(roles, 'MAX_OCCURRENCES', 64)
    monkeypatch.setattr(roles, 'MAX_INPUT_TOKENS', 1)
    with pytest.raises(ValueError, match='input_budget'): roles.prepare(request)


@pytest.mark.parametrize('artifact', ['input', 'model_roles', 'role_validation', 'raw_response', 'source_receipt'])
def test_corruption_cannot_trigger_another_provider_call(role_case, artifact):
    store, request, p = role_case; fake = Fake(response(p)); job = roles.enqueue(store, request)
    result = roles.run(store, job, provider_override=fake)
    if artifact == 'input': path = request
    elif artifact == 'raw_response': path = next((store.root / roles.ATTEMPTS_DIRECTORY).rglob('response.json'))
    elif artifact == 'source_receipt': path = Path(json.loads(request.read_bytes())['census_receipt']['path'])
    else: path = Path(result[artifact]['path'])
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError): roles.run(store, job, provider_override=fake)
    assert fake.calls == store.summary()['attempts'] == 1


def test_unknown_provider_completion_is_terminal_without_retry(role_case):
    store, request, p = role_case
    fake = Fake(response(p), ProviderFailure('codex_timeout'))
    job = roles.enqueue(store, request); result = roles.run(store, job, provider_override=fake)
    assert result['state'] == 'blocked' and result['outcome'] == 'completion_unknown'
    assert roles.recover(store, job) == result
    assert roles.run(store, job, provider_override=fake) == result and fake.calls == 1


def test_dispatched_job_without_return_recovers_without_provider(role_case):
    store, request, p = role_case; job = roles.enqueue(store, request)
    claimed = store.claim(job_id=job, workflow=roles.WORKFLOW)
    directory = store.root / roles.ATTEMPTS_DIRECTORY / job / claimed['lease_token']
    reader.put(directory / 'DISPATCH_INTENT.json', dict(job_id=job))
    result = roles.recover(store, job)
    assert result['state'] == 'blocked' and result['outcome'] == 'completion_unknown'
    assert result['recovered_without_provider_call'] and store.summary()['attempts'] == 1
