"""Bounded worker behavior with synthetic calls; no provider requests are made."""
import importlib.util
import inspect
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner(monkeypatch):
    path = os.environ.get('MATERIALS_BATCH_CANDIDATE') or str(Path(__file__).parents[1] / 'materials_ner_tc_batch.py')
    spec = importlib.util.spec_from_file_location('bounded_batch_candidate', path)
    batch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(batch)
    if 'max_concurrency' not in inspect.signature(batch.run_locked).parameters:
        pytest.skip('Bounded concurrency candidate has not been activated')
    monkeypatch.setattr(batch, 'Store', lambda root: SimpleNamespace(root=root))
    return batch


@pytest.mark.parametrize('workers', [1, 2, 3])
def test_resumed_batch_uses_registered_limit_and_calls_each_job_once(runner, tmp_path, monkeypatch, workers):
    jobs = [dict(job_id=str(i), work_id=f'arxiv:synthetic-{i}', profile='core') for i in range(workers * 2)]
    folder = tmp_path / 'batch'
    folder.mkdir()
    manifest = folder / 'BATCH.json'
    manifest.write_text(json.dumps(dict(sources=[], jobs=jobs, only_new_papers=False,
        max_concurrency=workers, max_jobs=60, max_seconds=1800, preparation_holds=[])))
    original = manifest.read_bytes()
    lock = threading.Lock()
    barrier = threading.Barrier(workers)
    active = peak = 0
    called = []
    def provider(store, identifier):
        nonlocal active, peak
        with lock:
            assert identifier not in called
            called.append(identifier)
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=3)
        time.sleep(0.01)
        with lock:
            active -= 1
        return dict(state='quarantined')
    monkeypatch.setattr(runner.core_tc, 'run', provider)
    monkeypatch.setattr(runner.core_tc, 'build_packet', lambda root, identifier: dict(job_id=identifier))
    monkeypatch.setattr(runner.core_tc, 'project', lambda packet: dict(raw_results=0, records=[]))
    result = runner.run_locked(tmp_path / 'queue', folder, [])
    assert peak == workers
    assert len(called) == workers * 2
    assert all(row['state'] == 'quarantined' for row in result['reports'])
    assert result['max_concurrency'] == workers
    assert manifest.read_bytes() == original


def test_requested_change_cannot_rewrite_existing_batch_policy(runner, tmp_path):
    manifest = tmp_path / 'BATCH.json'
    manifest.write_text(json.dumps(dict(sources=[], jobs=[], max_concurrency=2)))
    original = manifest.read_bytes()
    with pytest.raises(ValueError, match='batch_concurrency_policy_changed'):
        runner.run_locked(tmp_path / 'queue', tmp_path, [], max_concurrency=3)
    assert manifest.read_bytes() == original
    assert not list(tmp_path.glob('ROUND-*.json'))


@pytest.mark.parametrize('workers', [0, 4, True, 1.5])
def test_invalid_limits_rejected_before_preparation(runner, tmp_path, workers):
    folder = tmp_path / 'uncreated'
    with pytest.raises(ValueError, match='batch_concurrency_out_of_bounds'):
        runner.run_locked(tmp_path, folder, [], max_concurrency=workers)
    assert not folder.exists()


@pytest.mark.parametrize(('requested', 'registered'), [(None, 2), (3, 3)])
def test_new_batch_registers_limit_before_any_dispatch(runner, tmp_path, requested, registered):
    folder = tmp_path / 'batch'
    runner.run_locked(tmp_path / 'queue', folder, [], max_concurrency=requested)
    manifest = json.loads((folder / 'BATCH.json').read_text())
    assert manifest['max_concurrency'] == registered
    assert manifest['max_jobs'] == 60 and manifest['max_seconds'] == 1800
