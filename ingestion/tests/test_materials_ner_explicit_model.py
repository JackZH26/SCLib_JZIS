"""Synthetic execution/identity checks, never model accuracy or live provider tests."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ingestion.materials_ner import source_projector as stage, reviewed_reader as reader
from ingestion.materials_ner import projector_proposals, providers
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.proposals import verify_packet
from ingestion.materials_ner.store import Store
from test_materials_ner_source_focus import focused_case
from test_materials_ner_catalog_projector import catalog_case
from test_materials_ner_reviewed_proposals import prepared


def selected(focused_case, tmp_path, model='gpt-6.1-sol'):
    old, before, graph, _ = focused_case
    request = json.loads(old.read_bytes())
    request['execution_profile'].update(schema=stage.EXPLICIT_MODEL_PROFILE_SCHEMA, model=model)
    path = tmp_path / 'explicit.json'; reader.put(path, request)
    return path, before, graph


class Synthetic:
    def __init__(self, graph, *, error=None, returned_model=None):
        self.graph, self.error, self.returned_model = graph, error, returned_model
        self.calls = 0

    def extract(self, prompt, schema, config, directory):
        self.calls += 1
        assert config['model'] == config['execution_profile']['model']
        assert config['reasoning'] == 'high'
        text = canonical(self.graph)
        (directory / 'response.json').write_text(text)
        if self.error:
            raise self.error
        return providers.ProviderResult(text, {'input_tokens': 10, 'output_tokens': 20}, 'codex',
            self.returned_model or config['model'], 'synthetic:not-a-real-model-response', .1)


@pytest.mark.parametrize('model', ['gpt-6-luna', 'gpt-6.1-sol'])
def test_selection_changes_execution_only(focused_case, tmp_path, model):
    path, before, _ = selected(focused_case, tmp_path, model)
    after = stage.prepare(path)
    for key in ['prompt', 'schema', 'bundle', 'scope', 'coverage', 'source_catalog', 'source_focus']:
        assert after[key] == before[key]
    assert stage.configuration(after)['model'] == model
    assert stage.configuration(before)['model'] == 'gpt-6-luna'
    assert stage.provenance(stage.configuration(before)) == stage.PROVENANCE


@pytest.mark.parametrize('mutation', ['old_profile_sol', 'unknown_model', 'unknown_profile', 'effort', 'extra', 'no_focus'])
def test_explicit_profile_never_silently_falls_back(focused_case, tmp_path, mutation):
    path, _, _ = selected(focused_case, tmp_path)
    request = json.loads(path.read_bytes()); profile = request['execution_profile']
    if mutation == 'old_profile_sol': profile['schema'] = stage.EXECUTION_PROFILE_SCHEMA
    elif mutation == 'unknown_model': profile['model'] = 'other-model'
    elif mutation == 'unknown_profile': profile['schema'] = 'materials-source-projector-execution/99'
    elif mutation == 'effort': profile['reasoning'] = 'max'
    elif mutation == 'extra': profile['fallback_model'] = 'gpt-6-luna'
    else: request['schema'] = stage.NATIVE14_INPUT_SCHEMA
    with pytest.raises(ValueError): stage.request_contract(request)


@pytest.mark.parametrize('model', ['gpt-6-luna', 'gpt-6.1-sol'])
def test_one_attempt_portable_replay_preserves_requested_only_identity(focused_case, tmp_path, monkeypatch, model):
    path, _, graph = selected(focused_case, tmp_path, model)
    store = Store(tmp_path / 'synthetic-queue'); fake = Synthetic(graph)
    job = stage.enqueue(store, path); result = stage.run(store, job, provider_override=fake)
    assert result['state'] == 'succeeded', result
    assert result['graph_authorship'] == model
    identity = result['provider_model_identity']
    assert identity['requested_model'] == model and identity['verification'] == 'requested_only'
    assert identity['served_model'] is identity['immutable_model_version'] is None
    assert stage.run(Store(store.root), job, provider_override=fake) == result
    assert fake.calls == store.summary()['attempts'] == 1
    packet = projector_proposals.build(store.root, job)
    assert packet['receipt']['provider_model_identity'] == identity
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    def forbidden(*args, **kwargs): raise AssertionError('Portable replay accessed provider or live files')
    monkeypatch.setattr(reader, 'checked', forbidden)
    monkeypatch.setattr(fake, 'extract', forbidden)
    verify_packet(packet)


def test_returned_model_mismatch_is_quarantined(focused_case, tmp_path):
    path, _, graph = selected(focused_case, tmp_path)
    store = Store(tmp_path / 'synthetic-queue'); fake = Synthetic(graph, returned_model='gpt-6-luna')
    job = stage.enqueue(store, path); result = stage.run(store, job, provider_override=fake)
    assert result['state'] == 'quarantined' and 'graph' not in result
    assert stage.run(store, job, provider_override=fake) == result and fake.calls == 1
    with pytest.raises(ValueError): projector_proposals.build(store.root, job)


@pytest.mark.parametrize('failure', [providers.ProviderFailure('codex_timeout_or_interruption'), SystemExit('synthetic-crash')])
def test_unknown_completion_cannot_redeliver_or_start_remaining_work(focused_case, tmp_path, failure):
    path, _, graph = selected(focused_case, tmp_path)
    store = Store(tmp_path / 'synthetic-queue'); fake = Synthetic(graph, error=failure)
    job = stage.enqueue(store, path)
    another = tmp_path / 'second.json'; another.write_bytes(path.read_bytes())
    second = stage.enqueue(store, another)
    if isinstance(failure, SystemExit):
        with pytest.raises(SystemExit): stage.run(store, job, provider_override=fake)
        result = stage.recover(store, job)
    else: result = stage.run(store, job, provider_override=fake)
    assert result['outcome'] == 'completion_unknown'
    assert stage.run(store, job, provider_override=fake) == result and fake.calls == 1
    with pytest.raises(ValueError, match='reader_dispatch_hold'):
        stage.run(store, second, provider_override=fake)
    assert stage.row(store, second)['attempts'] == 0


def test_recorded_return_recovers_with_selected_model_without_redelivery(focused_case, tmp_path, monkeypatch):
    path, _, graph = selected(focused_case, tmp_path)
    store = Store(tmp_path / 'synthetic-queue'); fake = Synthetic(graph); job = stage.enqueue(store, path)
    terminal = stage.terminal
    def crash(*args, **kwargs): raise SystemExit('synthetic crash after return')
    monkeypatch.setattr(stage, 'terminal', crash)
    with pytest.raises(SystemExit): stage.run(store, job, provider_override=fake)
    monkeypatch.setattr(stage, 'terminal', terminal)
    result = stage.recover(store, job)
    assert result['state'] == 'succeeded' and result['recovered_without_provider_call']
    assert result['graph_authorship'] == 'gpt-6.1-sol'
    assert stage.run(store, job, provider_override=fake) == result and fake.calls == 1
    verify_packet(projector_proposals.build(store.root, job))


@pytest.mark.parametrize('mutation', ['served_model', 'snapshot', 'verification', 'remove_identity', 'requested_model'])
def test_rehashed_terminal_cannot_invent_model_attestation(focused_case, tmp_path, mutation):
    path, p, graph = selected(focused_case, tmp_path)
    store = Store(tmp_path / 'synthetic-queue'); job = stage.enqueue(store, path)
    stage.run(store, job, provider_override=Synthetic(graph))
    packet = projector_proposals.build(store.root, job)
    provenance = deepcopy(packet['receipt']['projector_provenance'])
    terminal = json.loads(provenance['terminal_json'])
    if mutation == 'remove_identity': terminal.pop('provider_model_identity')
    else:
        field = {'snapshot': 'immutable_model_version'}.get(mutation, mutation)
        terminal['provider_model_identity'][field] = 'synthetic:unverified-claim'
    provenance['terminal_json'] = canonical(terminal)
    provenance['terminal_pin'].update(sha256=digest(terminal), bytes=len(canonical(terminal).encode()))
    with pytest.raises(ValueError, match='projector_proposal_model_attestation'):
        projector_proposals.make_receipt(p['bundle'], provenance)


@pytest.mark.parametrize('model', ['gpt-6-luna', 'gpt-6.1-sol'])
def test_codex_argv_uses_exact_selected_model_with_no_actual_subprocess(monkeypatch, tmp_path, model):
    """Mock only the subprocess boundary; inspect the real adapter's command and files."""
    calls = []
    monkeypatch.setattr(providers.subprocess, 'run', lambda *args, **kwargs:
        SimpleNamespace(returncode=0, stdout='synthetic-cli-version'))
    class Process:
        def __init__(self, command, **kwargs):
            calls.append(command); self.returncode = 0
            Path(command[command.index('--output-last-message') + 1]).write_text('{}')
            kwargs['stdout'].write(b'{"type":"thread.started","thread_id":"synthetic"}\n'
                                  b'{"type":"turn.completed","usage":{"input_tokens":1}}\n')
        def communicate(self, *, input, timeout):
            assert input == b'synthetic' and timeout == 10
    monkeypatch.setattr(providers.subprocess, 'Popen', Process)
    response = providers.CodexProvider(executable='synthetic-codex').extract('synthetic', {},
        dict(model=model, reasoning='high', timeout_seconds=10), tmp_path)
    assert len(calls) == 1 and response.model == model
    command = json.loads((tmp_path / 'command.json').read_bytes())
    assert command[command.index('--model') + 1] == model
    assert command.count('--model') == 1 and '--ignore-user-config' in command
    assert command[command.index('--sandbox') + 1] == 'read-only'
    assert command[-1] == '-' and 'web_search="disabled"' in command
