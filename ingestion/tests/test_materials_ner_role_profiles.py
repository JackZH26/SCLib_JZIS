"""Per-job reasoning profiles change execution, not source or scientific claims."""
from copy import deepcopy
import json

import pytest

from ingestion.materials_ner import reviewed_reader as reader
from ingestion.materials_ner.census import roles
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.providers import ProviderFailure
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_compact_roles import compact_case, response
from test_materials_ner_census_roles import role_case, Fake
from test_materials_ner_source_census import case
from test_materials_ner_reviewed_proposals import prepared


def request_for(path, original, effort):
    data = json.loads(original.read_bytes())
    data.update(schema=roles.PROFILED_INPUT_SCHEMA, execution_profile=dict(
        schema=roles.EXECUTION_PROFILE_SCHEMA, model='gpt-6-luna', reasoning=effort))
    reader.put(path, data)
    return path


@pytest.mark.parametrize('effort', ['medium', 'high'])
def test_explicit_profile_reaches_provider_and_terminal_replay(compact_case, tmp_path, effort):
    store, original, legacy = compact_case
    request = request_for(tmp_path / 'profile.json', original, effort)
    p = roles.prepare(request)
    assert p['prompt'] == legacy['prompt'] and p['schema'] == legacy['schema']
    assert p['source_catalog'] == legacy['source_catalog'] and p['occurrences'] == legacy['occurrences']
    assert roles.configuration(legacy)['reasoning'] == 'medium'
    assert 'execution_profile' not in roles.configuration(legacy)
    class Capturing(Fake):
        def extract(self, prompt, schema, config, directory):
            assert config['reasoning'] == effort
            assert config['execution_profile'] == p['execution_profile']
            return super().extract(prompt, schema, config, directory)
    fake = Capturing(response(p))
    job = roles.enqueue(store, request)
    result = roles.run(store, job, provider_override=fake)
    assert result['state'] == 'succeeded' and result['interface_version'] == 2
    saved = roles.row(store, job)['config']
    assert saved['reasoning'] == effort and saved['execution_profile'] == p['execution_profile']
    assert not result['scientific_acceptance'] and not result['ml_training_eligible']
    assert roles.run(Store(store.root), job, provider_override=fake) == result
    assert fake.calls == store.summary()['attempts'] == 1


def test_reasoning_alone_changes_job_configuration_identity(compact_case, tmp_path):
    _, original, _ = compact_case
    p = roles.prepare(request_for(tmp_path / 'profile.json', original, 'medium'))
    high = deepcopy(p)
    high['execution_profile']['reasoning'] = 'high'
    medium_config = roles.configuration(p)
    high_config = roles.configuration(high)
    assert digest(medium_config) != digest(high_config)
    assert {key for key in medium_config if medium_config[key] != high_config[key]} == {'reasoning', 'execution_profile'}
    assert medium_config['prompt_sha256'] == high_config['prompt_sha256']
    assert medium_config['schema_sha256'] == high_config['schema_sha256']


@pytest.mark.parametrize('change', ['missing', 'null', 'list', 'string', 'version', 'model',
    'effort', 'effort_list', 'extra', 'missing_model', 'profile_on_legacy'])
def test_invalid_profiles_fail_before_enqueue(compact_case, tmp_path, change):
    store, original, _ = compact_case
    request = request_for(tmp_path / 'profile.json', original, 'high')
    data = json.loads(request.read_bytes())
    if change == 'missing': del data['execution_profile']
    elif change == 'null': data['execution_profile'] = None
    elif change == 'list': data['execution_profile'] = []
    elif change == 'string': data['execution_profile'] = 'high'
    elif change == 'version': data['execution_profile']['schema'] = 'unknown/1'
    elif change == 'model': data['execution_profile']['model'] = 'gpt-6.1-sol'
    elif change == 'effort': data['execution_profile']['reasoning'] = 'max'
    elif change == 'effort_list': data['execution_profile']['reasoning'] = ['high']
    elif change == 'extra': data['execution_profile']['temperature'] = 0
    elif change == 'missing_model': del data['execution_profile']['model']
    else: data['schema'] = roles.COMPACT_INPUT_SCHEMA
    request.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='roles_(input_shape|execution_profile_invalid)'):
        roles.enqueue(store, request)
    assert store.summary()['jobs'] == 0


def test_profile_drift_is_held_before_provider_dispatch(compact_case, tmp_path):
    store, original, _ = compact_case
    request = request_for(tmp_path / 'profile.json', original, 'medium')
    p = roles.prepare(request)
    job = roles.enqueue(store, request)
    data = json.loads(request.read_bytes())
    data['execution_profile']['reasoning'] = 'high'
    request.write_text(json.dumps(data))
    fake = Fake(response(p))
    result = roles.run(store, job, provider_override=fake)
    assert result['state'] == 'blocked' and result['outcome'] == 'not_dispatched'
    assert not result['provider_dispatch_intent_recorded'] and fake.calls == 0


def test_high_profile_timeout_is_not_retried(compact_case, tmp_path):
    store, original, _ = compact_case
    request = request_for(tmp_path / 'profile.json', original, 'high')
    p = roles.prepare(request)
    job = roles.enqueue(store, request)
    fake = Fake(response(p), ProviderFailure('codex_timeout_or_interruption'))
    result = roles.run(store, job, provider_override=fake)
    assert result['state'] == 'blocked' and result['outcome'] == 'completion_unknown'
    assert roles.recover(store, job) == result
    assert roles.run(store, job, provider_override=fake) == result
    assert fake.calls == store.summary()['attempts'] == 1


def test_profile_cannot_enable_default_or_full_corpus_dispatch(compact_case, tmp_path):
    store, original, _ = compact_case
    request = request_for(tmp_path / 'profile.json', original, 'high')
    p = roles.prepare(request)
    job = roles.enqueue(store, request)
    fake = Fake(response(p))
    assert run_one(store, job_id=job, provider_override=fake) is None and fake.calls == 0
    blocked = Store(tmp_path / 'full-corpus')
    (blocked.root / 'STAGING_PREPARATION.json').write_text('{}')
    with pytest.raises(ValueError, match='staging_preparation_only'):
        roles.enqueue(blocked, request)
    assert blocked.summary()['jobs'] == 0
