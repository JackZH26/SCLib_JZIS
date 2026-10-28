"""Synthetic source scheduling tests; no network or scientific accuracy claim."""
import fcntl
from pathlib import Path

import pytest

from ingestion.materials_ner import reviewed_reader as rr
import materials_ner_gcs_lookahead as lookahead


@pytest.fixture
def source_window(tmp_path, monkeypatch):
    parent = tmp_path / 'source-batch-040'
    target = tmp_path / 'source-batch-041'
    parent.mkdir()
    plan_path = tmp_path / 'PLAN.json'
    papers = [dict(id=f'arxiv:synthetic-{i:03d}', acquisition_status='available_in_gcs')
              for i in range(120)]
    rr.put(plan_path, {'papers': papers})
    rr.put(parent / 'COHORT.json', {'source_plan': rr.reference(plan_path), 'papers': papers[:60]})
    rr.put(parent / 'GCS_ACQUISITION.json', {'synthetic': True})
    handle = (parent / '.lock').open('a')
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setattr(lookahead, 'load_plan', lambda path: ({'papers': papers}, 'plan-hash'))
    monkeypatch.setattr(lookahead, 'select_papers', lambda plan, root, limit: (papers[:limit], 120, set()))
    calls = []
    def acquire(*args, **kwargs):
        calls.append(kwargs)
        return dict(attempted_papers=len(kwargs['work_ids']), reserved_download_bytes=600,
                    outcomes=[], scientific_acceptance=False)
    monkeypatch.setattr(lookahead, 'acquire_batch', acquire)
    yield dict(parent=parent, target=target, plan_path=plan_path, queue_root=tmp_path,
               cache=tmp_path / 'cache', ssh_host='synthetic-bridge'), calls, handle, papers
    handle.close()


def test_parent_reservations_and_bounds_are_preserved_without_ready_or_ledger_writes(source_window):
    args, calls, _, papers = source_window
    ledger = args['queue_root'] / 'corpus.sqlite3'
    ledger.write_bytes(b'unchanged synthetic ledger')
    result = lookahead.prefetch(**args)
    cohort = lookahead.read(args['target'] / 'COHORT.json')
    assert cohort['papers'] == papers[60:]
    assert calls[0]['work_ids'] == [p['id'] for p in papers[60:]]
    assert calls[0]['limit'] == 60 and calls[0]['max_bytes'] == 256 * 1024**2
    assert calls[0]['retry_failed'] is False and calls[0]['processing_allowed'] is True
    assert result['state'] == 'gcs_prefetched'
    assert result['official_http_calls'] == result['model_calls'] == result['corpus_ledger_writes'] == 0
    assert not result['source_ready_asserted']
    assert not (args['target'] / 'NER_SOURCES.json').exists()
    assert not (args['target'] / 'SOURCE_PROGRESS.json').exists()
    assert ledger.read_bytes() == b'unchanged synthetic ledger'


@pytest.mark.parametrize('condition', ['gcs_not_finished', 'official_finished', 'producer_not_live'])
def test_only_enter_while_the_predecessor_still_owns_its_official_phase(source_window, condition):
    args, calls, handle, _ = source_window
    if condition == 'gcs_not_finished':
        (args['parent'] / 'GCS_ACQUISITION.json').unlink()
    elif condition == 'official_finished':
        rr.put(args['parent'] / 'NER_SOURCES.json', [])
    else:
        fcntl.flock(handle, fcntl.LOCK_UN)
    assert lookahead.prefetch(**args)['state'] == 'predecessor_not_in_official_reading_phase'
    assert not calls and not (args['target'] / 'COHORT.json').exists()


def test_never_competes_with_an_existing_next_source_owner(source_window):
    args, calls, _, _ = source_window
    args['target'].mkdir()
    with (args['target'] / '.lock').open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert lookahead.prefetch(**args)['state'] == 'next_source_already_owned'
    assert not calls and not (args['target'] / 'COHORT.json').exists()


def test_existing_cohort_is_never_reselected_or_overwritten(source_window):
    args, calls, _, _ = source_window
    args['target'].mkdir()
    rr.put(args['target'] / 'COHORT.json', {'existing': True})
    before = (args['target'] / 'COHORT.json').read_bytes()
    assert lookahead.prefetch(**args)['state'] == 'next_cohort_already_registered'
    assert not calls and (args['target'] / 'COHORT.json').read_bytes() == before


def test_failed_acquisition_leaves_a_resumable_cohort_and_releases_its_lock(source_window, monkeypatch):
    args, calls, _, _ = source_window
    def fail(*a, **kw):
        raise ValueError('synthetic transfer failure')
    monkeypatch.setattr(lookahead, 'acquire_batch', fail)
    with pytest.raises(ValueError, match='synthetic transfer failure'):
        lookahead.prefetch(**args)
    assert (args['target'] / 'COHORT.json').exists()
    assert not (args['target'] / 'GCS_ACQUISITION.json').exists()
    assert not (args['target'] / 'NER_SOURCES.json').exists()
    with (args['target'] / '.lock').open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_changed_source_plan_is_rejected_before_transfer(source_window):
    args, calls, _, _ = source_window
    args['plan_path'].write_text('{"changed":true}')
    with pytest.raises(ValueError, match='source_plan_changed'):
        lookahead.prefetch(**args)
    assert not calls and not (args['target'] / 'COHORT.json').exists()


def test_nonconsecutive_source_directory_is_rejected(source_window):
    args, calls, _, _ = source_window
    args['target'] = args['target'].with_name('source-batch-042')
    with pytest.raises(ValueError, match='source_sequence_changed'):
        lookahead.prefetch(**args)
    assert not calls and not args['target'].exists()


def test_dispatched_papers_cannot_be_reserved_again(source_window, monkeypatch):
    args, calls, _, papers = source_window
    monkeypatch.setattr(lookahead, 'select_papers',
                        lambda plan, root, limit: (papers, 120, {papers[60]['id']}))
    with pytest.raises(ValueError, match='selected_dispatched_paper'):
        lookahead.prefetch(**args)
    assert not calls and not (args['target'] / 'COHORT.json').exists()
