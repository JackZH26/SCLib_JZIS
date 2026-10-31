import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

import materials_ner_tc_continue as continuation


@pytest.fixture
def scenario(tmp_path):
    root = tmp_path / 'root'; root.mkdir()
    with sqlite3.connect(root / 'corpus.sqlite3') as db:
        db.execute('CREATE TABLE papers (work_id TEXT)')
        db.executemany('INSERT INTO papers VALUES (?)', [('one',), ('two',)])
    after = tmp_path / 'pipeline-003'; after.mkdir()
    original = tmp_path / 'source.json'; original.write_text('{}')
    stage = tmp_path / 'stage.py'; stage.write_text('# pinned\n')
    receipt = tmp_path / 'receipt.json'; receipt.write_text('{}')
    previous = dict(root=str(root), campaign=str(tmp_path), audit_root=str(root / 'audit'),
                    source_plan=continuation.pin(original), source_python='/venv/bin/python',
                    source_start=12, batch_start=19, max_batches=1, ssh_host='test-host',
                    stage_sources=[continuation.pin(stage)], prefetch_next_source=True,
                    database_url_sha256=hashlib.sha256(b'local-dsn').hexdigest())
    result = dict(batch='batch-019', state='scientific_batch_held',
                  completion_evidence=[continuation.pin(receipt)])
    continuation.write(after / 'PLAN.json', previous)
    continuation.write(after / 'BATCH_000.json', result)
    continuation.write(after / 'STATUS.json', dict(state='bounded_run_finished', completed=[result]))
    args = SimpleNamespace(after=after, directory=tmp_path / 'continuation',
                           next_directory=tmp_path / 'pipeline-004', database_url='local-dsn',
                           max_batches=None, poll_seconds=0.01)
    return args, previous, stage, receipt


def forbid_launch(*args, **kwargs):
    pytest.fail('An unsafe or uncertain state must not start another pipeline')


def test_serial_handoff_waits_for_real_lock_then_launches_once(scenario, monkeypatch):
    args, previous, _, _ = scenario
    root = Path(previous['root'])
    lock = (root / '.production90-pipeline.lock').open('a')
    continuation.fcntl.flock(lock, continuation.fcntl.LOCK_EX)
    sleeps = []
    def release(_):
        assert not (args.directory / 'CHILD_STARTED.json').exists()
        sleeps.append(True)
        continuation.fcntl.flock(lock, continuation.fcntl.LOCK_UN)
    monkeypatch.setattr(continuation.time, 'sleep', release)
    calls = []
    def launch(command, **kwargs):
        assert sleeps
        assert (args.directory / 'CHILD_STARTED.json').exists()
        calls.append(command)
        args.next_directory.mkdir()
        continuation.write(args.next_directory / 'STATUS.json', dict(state='queued_source_scope_exhausted'))
        return SimpleNamespace(pid=123, poll=lambda: 0, returncode=0)
    monkeypatch.setattr(continuation.subprocess, 'Popen', launch)
    try:
        result = continuation.run(args)
        assert result['state'] == 'queued_source_scope_exhausted'
        assert result['full_corpus_complete'] is False
        command = calls[0]
        assert command[command.index('--source-start') + 1] == '13'
        assert command[command.index('--batch-start') + 1] == '20'
        assert command[command.index('--max-batches') + 1] == '2'
        assert '--prefetch-next-source' in command
        assert 'local-dsn' not in (args.directory / 'PLAN.json').read_text()
        assert continuation.run(args) == result
        assert len(calls) == 1
    finally:
        lock.close()


@pytest.mark.parametrize('problem', ['failed', 'missing_terminal', 'changed_stage', 'changed_receipt',
                                    'uncertain_child', 'existing_next', 'different_database'])
def test_unsafe_history_cannot_launch(scenario, monkeypatch, problem):
    args, _, stage, receipt = scenario
    args.directory.mkdir()
    if problem == 'failed':
        continuation.write(args.after / 'STATUS.json', dict(state='stopped_for_review'))
    elif problem == 'missing_terminal':
        (args.after / 'STATUS.json').unlink()
    elif problem == 'changed_stage':
        stage.write_text('# changed\n')
    elif problem == 'changed_receipt':
        receipt.write_text('{"changed":true}')
    elif problem == 'uncertain_child':
        continuation.write(args.directory / 'CHILD_STARTED.json', dict(launch_intent=True))
    elif problem == 'existing_next':
        args.next_directory.mkdir()
    else:
        args.database_url = 'other-dsn'
    monkeypatch.setattr(continuation.subprocess, 'Popen', forbid_launch)
    with pytest.raises((ValueError, FileNotFoundError)):
        continuation.run(args)
    assert continuation.read(args.directory / 'RESULT.json')['state'] == 'stopped_for_review'


@pytest.mark.parametrize('state', ['stopped', 'exhausted'])
def test_intentional_stop_or_exhaustion_does_not_launch(scenario, monkeypatch, state):
    args, _, _, _ = scenario
    if state == 'stopped':
        (args.after / 'STOP_AFTER_BATCH').touch()
    else:
        continuation.write(args.after / 'STATUS.json', dict(state='queued_source_scope_exhausted'))
    monkeypatch.setattr(continuation.subprocess, 'Popen', forbid_launch)
    result = continuation.run(args)
    assert result['state'] in {'stopped_before_continuation', 'queued_source_scope_already_exhausted'}


def test_child_failure_is_recorded_without_automatic_retry(scenario, monkeypatch):
    args, _, _, _ = scenario
    calls = []
    def launch(*a, **k):
        calls.append(True)
        return SimpleNamespace(pid=123, poll=lambda: 1, returncode=1)
    monkeypatch.setattr(continuation.subprocess, 'Popen', launch)
    with pytest.raises(ValueError, match='continued_pipeline_failed'):
        continuation.run(args)
    result = continuation.run(args)
    assert result['state'] == 'stopped_for_review'
    assert len(calls) == 1


def test_stop_during_child_run_drains_existing_batch(scenario, monkeypatch):
    args, _, _, _ = scenario
    def launch(*a, **k):
        args.next_directory.mkdir()
        (args.directory / 'STOP').touch()
        values = iter([None, 0])
        continuation.write(args.next_directory / 'STATUS.json', dict(state='stopped_at_batch_boundary'))
        return SimpleNamespace(pid=123, poll=lambda: next(values), returncode=0)
    monkeypatch.setattr(continuation.subprocess, 'Popen', launch)
    monkeypatch.setattr(continuation.time, 'sleep', lambda _: None)
    assert continuation.run(args)['state'] == 'stopped_at_batch_boundary'
    assert (args.next_directory / 'STOP_AFTER_BATCH').exists()
