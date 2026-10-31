"""Failure isolation uses synthetic receipts; no provider calls are made."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ingestion.materials_ner import reviewed_reader as rr
from ingestion.materials_ner.contract import digest
import materials_ner_tc_batch as batch_runner
import materials_ner_tc_capacity as capacity


def failed_job(root, number=1, message=capacity.CAPACITY_MESSAGE):
    identifier, attempt = f'{number:064x}', f'{number:032x}'
    folder = root / 'core-tc-attempts' / identifier / attempt
    folder.mkdir(parents=True)
    config = dict(workflow='core_tc_v1', model='gpt-6-luna', input_pins=[])
    events = folder / 'events.jsonl'
    events.write_text(json.dumps(dict(type='turn.failed', error=dict(message=message))) + '\n')
    rr.put(folder / 'failure.json', dict(error_code='codex_turn_failed',
        exception_class='ProviderFailure', usage={}, raw_artifacts=[rr.reference(events)]))
    rr.put(folder / 'receipt.json', dict(job_id=identifier, attempt_id=attempt,
        work_id=f'arxiv:test-{number}', config_sha256=digest(config), state='blocked',
        error_code='codex_turn_failed', provider_dispatch_intent_recorded=True,
        failure=rr.reference(folder / 'failure.json')))
    pin = rr.reference(folder / 'receipt.json')
    return dict(id=identifier, work_id=f'arxiv:test-{number}', state='blocked', attempts=1,
        max_attempts=1, config_json=json.dumps(config), result_path=pin['path'],
        result_hash=pin['sha256'], created_at=100, updated_at=500)


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    root = tmp_path / 'root'; root.mkdir()
    directory = tmp_path / 'batch-001'; directory.mkdir()
    failure = failed_job(root)
    rows = {failure['id']: failure}
    for number in [2, 3, 4]:
        key = f'{number:064x}'
        rows[key] = dict(id=key, work_id=f'arxiv:test-{number}', state='queued', attempts=0,
            max_attempts=1, result_path=None, result_hash=None, created_at=100, updated_at=100)
    dispatched = []
    def complete(identifier):
        row = rows[identifier]
        assert row['state'] == 'queued' and row['attempts'] == 0
        path = root / (identifier + '.json')
        rr.put(path, dict(job_id=identifier, state='succeeded', synthetic=True))
        pin = rr.reference(path)
        row.update(state='succeeded', attempts=1, result_path=pin['path'], result_hash=pin['sha256'])
        dispatched.append(identifier)
    complete(f'{4:064x}'); dispatched.clear()
    manifest = dict(jobs=[dict(job_id=k, work_id=v['work_id'], profile='core') for k, v in rows.items()],
        sources=[], preparation_holds=[], only_new_papers=True)
    rr.put(directory / 'BATCH.json', manifest)
    hold = root / 'READER_DISPATCH_HOLD.json'
    rr.put(hold, dict(schema='materials-reviewed-reader-dispatch-hold/1',
        reason='uncertain_provider_completion_requires_reconciliation', automatic_resume=False))
    monkeypatch.setattr(capacity, 'queue_snapshot', lambda unused: {k:dict(v) for k,v in rows.items()})
    monkeypatch.setattr(capacity, '_probe', lambda root,directory,job: complete(job['job_id']))
    def remaining(*args, **kwargs):
        for key, row in rows.items():
            if row['state'] == 'queued': complete(key)
    monkeypatch.setattr(batch_runner, 'run_locked', remaining)
    return SimpleNamespace(root=root, directory=directory, rows=rows, failure=failure,
        dispatched=dispatched, complete=complete, remaining=remaining, hold=hold, manifest=manifest)


def test_explicit_terminal_capacity_failure_preserves_unknown_usage(tmp_path):
    job = failed_job(tmp_path)
    result = capacity.capacity_evidence(job)
    assert result['disposition'] == 'deferred_without_retry'
    assert not result['paper_completed'] and not result['usage_known']


@pytest.mark.parametrize('message', ['You have reached your usage limit.',
    'Authentication required.', 'The request timed out.', 'Unexpected provider error.'])
def test_other_provider_errors_are_never_automatically_cleared(tmp_path, message):
    with pytest.raises(ValueError, match='not_confirmed_capacity'):
        capacity.capacity_evidence(failed_job(tmp_path, message=message))


def test_capacity_with_output_requires_explicit_reconciliation(tmp_path):
    job = failed_job(tmp_path)
    (Path(job['result_path']).parent / 'response.json').write_text('{}')
    with pytest.raises(ValueError, match='unreconciled_output'):
        capacity.capacity_evidence(job)


def test_changed_evidence_is_rejected(tmp_path):
    job = failed_job(tmp_path)
    (Path(job['result_path']).parent / 'events.jsonl').write_text('changed')
    with pytest.raises(ValueError): capacity.capacity_evidence(job)


def test_only_uncalled_siblings_execute_and_replay_makes_no_calls(scenario):
    s = scenario; failed_before = dict(s.failure)
    report = capacity.continue_pending(s.root, s.directory)
    assert report['completed_jobs'] == 3 and report['deferred_jobs'] == 1
    assert report['newly_completed_jobs'] == 2
    assert s.dispatched == [f'{2:064x}', f'{3:064x}']
    assert s.failure == failed_before and not s.hold.exists()
    assert capacity.continue_pending(s.root, s.directory) == report
    assert s.dispatched == [f'{2:064x}', f'{3:064x}']


def test_failed_probe_stops_remaining_work_and_is_not_retried(scenario, monkeypatch):
    s = scenario
    def fail(root, directory, job):
        s.dispatched.append(job['job_id'])
        s.rows[job['job_id']].update(state='blocked', attempts=1)
        rr.put(s.hold, dict(schema='materials-reviewed-reader-dispatch-hold/1',
            reason='uncertain_provider_completion_requires_reconciliation', automatic_resume=False))
    monkeypatch.setattr(capacity, '_probe', fail)
    with pytest.raises(ValueError, match='probe_not_completed'):
        capacity.continue_pending(s.root, s.directory)
    with pytest.raises(ValueError, match='second_failure_requires_review'):
        capacity.continue_pending(s.root, s.directory)
    assert s.dispatched == [f'{2:064x}'] and s.hold.exists()
    assert s.rows[f'{3:064x}']['attempts'] == 0


def test_resume_after_completed_probe_never_repeats_it(scenario, monkeypatch):
    s = scenario
    def interrupted(*args, **kwargs): raise RuntimeError('synthetic process interruption')
    monkeypatch.setattr(batch_runner, 'run_locked', interrupted)
    with pytest.raises(RuntimeError, match='synthetic'):
        capacity.continue_pending(s.root, s.directory)
    assert s.dispatched == [f'{2:064x}']
    monkeypatch.setattr(batch_runner, 'run_locked', s.remaining)
    capacity.continue_pending(s.root, s.directory)
    assert s.dispatched == [f'{2:064x}', f'{3:064x}']


def test_last_job_failure_is_deferred_without_an_extra_probe(scenario):
    s = scenario
    s.complete(f'{2:064x}'); s.complete(f'{3:064x}'); s.dispatched.clear()
    report = capacity.continue_pending(s.root, s.directory)
    assert report['completed_jobs'] == 3 and report['newly_completed_jobs'] == 0
    assert report['deferred_jobs'] == 1 and not s.dispatched


def test_new_generic_hold_is_not_mistaken_for_original_hold(scenario, monkeypatch):
    s = scenario; original = s.hold.read_bytes()
    def interrupted(*args, **kwargs):
        s.hold.write_bytes(original)
        raise RuntimeError('synthetic new dispatch hold')
    monkeypatch.setattr(batch_runner, 'run_locked', interrupted)
    with pytest.raises(RuntimeError): capacity.continue_pending(s.root, s.directory)
    monkeypatch.setattr(batch_runner, 'run_locked', s.remaining)
    with pytest.raises(ValueError, match='new_dispatch_hold'):
        capacity.continue_pending(s.root, s.directory)
    assert s.dispatched == [f'{2:064x}'] and s.hold.exists()


@pytest.mark.parametrize('fault', ['running', 'queued_attempt', 'unrelated_failure'])
def test_unreconciled_state_retains_hold_without_calls(scenario, fault):
    s = scenario
    if fault == 'running': s.rows[f'{2:064x}']['state'] = 'running'
    elif fault == 'queued_attempt': s.rows[f'{2:064x}']['attempts'] = 1
    else: s.rows['outside'] = dict(id='outside', state='blocked', updated_at=400)
    with pytest.raises(ValueError): capacity.continue_pending(s.root, s.directory)
    assert s.hold.exists() and not s.dispatched


def test_production_counts_deferred_paper_as_failed_not_completed(scenario, monkeypatch):
    source = os.environ.get('MATERIALS_PRODUCTION_CANDIDATE')
    if not source: pytest.skip('Run with the prepared production candidate, then with the activated source.')
    spec = importlib.util.spec_from_file_location('capacity_production_candidate', source)
    production = importlib.util.module_from_spec(spec); spec.loader.exec_module(production)
    s = scenario
    capacity.continue_pending(s.root, s.directory)
    monkeypatch.setattr(production, 'queue_rows', lambda root, manifest: list(s.rows.values()))
    async def counts(*args): return dict(total=0, by_paper={})
    monkeypatch.setattr(production, 'database_counts', counts)
    monkeypatch.setattr(production, 'reconcile_batch', lambda *args: dict(synthetic=True))
    args = SimpleNamespace(root=s.root, campaign=s.directory.parent, database_url='synthetic')
    receipt = production.extraction_receipt(args, s.directory)
    assert receipt['completed_papers'] == 3
    assert len(receipt['deferred_provider_failures']) == 1
    assert receipt['eligible_results'] == 0
    assert not receipt['full_paper_recall_measured']
    assert any(Path(p['path']).parent.name == 'CAPACITY_CONTINUATION'
               for p in receipt['completion_evidence'])
