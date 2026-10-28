"""Prefetch one future GCS cohort while the existing reader verifies originals.

The existing source runner still performs every official HTTP request, version
check, parse and corpus-ledger update. This helper only prepares its immutable
cohort and bounded GCS receipt, using the same source/acquisition locks.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import time

from ingestion.materials_ner import reviewed_reader as rr
from ingestion.materials_ner.planning import acquire_batch, load_plan
from materials_ner_tc_sources import select_papers, write_progress


TERMINAL = {'bounded_run_finished', 'queued_source_scope_exhausted',
            'stopped_at_batch_boundary', 'stopped_for_review'}


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_bytes())


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def locked(path):
    if not path.exists():
        return False
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def prefetch(parent, target, plan_path, queue_root, cache, ssh_host):
    parent, target = Path(parent), Path(target)
    match = re.fullmatch(r'source-batch-(\d+)', parent.name)
    if (not match or target.parent != parent.parent
            or target.name != f'source-batch-{int(match[1]) + 1:03d}'):
        raise ValueError('source_sequence_changed')
    target.mkdir(parents=True, exist_ok=True)
    with (target / '.lock').open('a') as owner:
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'state': 'next_source_already_owned'}
        # Own the future directory before checking the predecessor. Therefore
        # the main pipeline cannot race between its shared-lock check and spawn.
        if (target / 'COHORT.json').exists():
            return {'state': 'next_cohort_already_registered'}
        if ((parent / 'NER_SOURCES.json').exists()
                or not (parent / 'GCS_ACQUISITION.json').exists()
                or not locked(parent / '.lock')):
            return {'state': 'predecessor_not_in_official_reading_phase'}
        parent_cohort = read(parent / 'COHORT.json')
        source_pin = rr.reference(plan_path)
        if parent_cohort['source_plan'] != source_pin:
            raise ValueError('predecessor_source_plan_changed')
        plan, plan_hash = load_plan(plan_path)
        reserved = {p['id'] for p in parent_cohort['papers']}
        # Parent papers are still queued until their official checks finish.
        # Explicitly exclude every reserved parent ID, not just completed rows.
        choices, denominator, dispatched = select_papers(plan, queue_root, 60 + len(reserved))
        papers = [p for p in choices if p['id'] not in reserved][:60]
        if not papers:
            return {'state': 'no_unreserved_papers'}
        if {p['id'] for p in papers} & dispatched:
            raise ValueError('lookahead_selected_dispatched_paper')
        started = now()
        cohort = dict(schema='production90-source-cohort/1', source_plan=source_pin,
            source_plan_sha256=plan_hash, created_at=started, papers=papers,
            selection='Frozen family-stratified deterministic order; no previous NER values used.',
            full_corpus_denominator=denominator, max_download_bytes=256 * 1024**2,
            lookahead_parent_cohort=rr.reference(parent / 'COHORT.json'))
        rr.put(target / 'COHORT.json', cohort)
        ids = [p['id'] for p in papers if p['acquisition_status'] == 'available_in_gcs']
        acquired = None
        if ids:
            acquired = acquire_batch(cache, plan_path, limit=len(ids),
                max_bytes=cohort['max_download_bytes'], ssh_host=ssh_host,
                processing_allowed=True, work_ids=ids, retry_failed=False)
            rr.put(target / 'GCS_ACQUISITION.json', acquired)
        result = dict(schema='materials-gcs-lookahead-result/1', state='gcs_prefetched',
            started_at=started, finished_at=now(), parent_cohort=cohort['lookahead_parent_cohort'],
            cohort=rr.reference(target / 'COHORT.json'), selected_papers=len(papers),
            acquisition=rr.reference(target / 'GCS_ACQUISITION.json') if acquired else None,
            attempted_papers=acquired['attempted_papers'] if acquired else 0,
            reserved_download_bytes=acquired['reserved_download_bytes'] if acquired else 0,
            official_http_calls=0, model_calls=0, corpus_ledger_writes=0,
            source_ready_asserted=False, scientific_acceptance=False)
        rr.put(target / 'GCS_LOOKAHEAD.json', result)
        return result


def run(args):
    args.directory.mkdir(parents=True, exist_ok=True)
    with (args.directory / '.lock').open('a') as watcher:
        fcntl.flock(watcher, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (args.directory / 'RESULT.json').exists():
            return read(args.directory / 'RESULT.json')
        pipeline = read(args.pipeline / 'PLAN.json')
        if not 1 <= args.max_cohorts <= pipeline['max_batches']:
            raise ValueError('lookahead_bound_exceeds_pipeline')
        config = dict(schema='materials-gcs-lookahead-plan/1', created_at=now(),
            pipeline_plan=rr.reference(args.pipeline / 'PLAN.json'), helper=rr.reference(Path(__file__)),
            max_cohorts=args.max_cohorts, max_papers_per_cohort=60,
            max_download_bytes_per_cohort=256 * 1024**2, poll_seconds=args.poll_seconds,
            official_http_calls=0, model_calls=0, corpus_ledger_writes=0,
            automatic_retry=False)
        if (args.directory / 'PLAN.json').exists():
            raise ValueError('lookahead_previous_outcome_requires_review')
        rr.put(args.directory / 'PLAN.json', config)
        results = []
        state = 'bounded_prefetch_finished'
        try:
            while len(results) < args.max_cohorts:
                rr.checked(config['pipeline_plan']); rr.checked(config['helper'])
                status = read(args.pipeline / 'STATUS.json')
                if (args.directory / 'STOP').exists():
                    state = 'stopped_at_cohort_boundary'; break
                if status['state'] in TERMINAL or not alive(status['owner_pid']):
                    state = 'main_pipeline_terminal_or_process_missing'; break
                candidates = sorted(args.pipeline.glob('PREFETCH_*.json'), reverse=True)
                candidate = None
                for path in candidates:
                    observed = read(path)
                    if (observed.get('state') == 'source_acquisition'
                            and observed.get('owner_pid') == status['owner_pid']
                            and alive(observed['child_pid'])):
                        candidate = observed
                        break
                outcome = {'state': 'waiting_for_source_window'}
                if candidate:
                    parent = Path(pipeline['campaign']) / candidate['source_batch']
                    number = int(parent.name.rsplit('-', 1)[1])
                    target = parent.with_name(f'source-batch-{number + 1:03d}')
                    write_progress(args.directory / 'STATUS.json', dict(
                        state='checking_source_window', at=now(), owner_pid=os.getpid(),
                        parent=str(parent), target=str(target), completed_cohorts=len(results)))
                    outcome = prefetch(parent, target, Path(pipeline['source_plan']['path']),
                        Path(pipeline['root']), Path(pipeline['root']) / 'source-cache', pipeline['ssh_host'])
                    if outcome['state'] == 'gcs_prefetched':
                        receipt = target / 'GCS_LOOKAHEAD.json'
                        results.append(rr.reference(receipt))
                        print(json.dumps({'state': 'gcs_prefetched', 'cohort': target.name,
                            'attempted_papers': outcome['attempted_papers'],
                            'reserved_download_bytes': outcome['reserved_download_bytes']}), flush=True)
                write_progress(args.directory / 'STATUS.json', dict(state=outcome['state'], at=now(),
                    owner_pid=os.getpid(), completed_cohorts=len(results), results=results))
                if len(results) < args.max_cohorts:
                    time.sleep(args.poll_seconds)
        except Exception as exc:
            failure = dict(state='stopped_for_review', at=now(), owner_pid=os.getpid(),
                error_class=type(exc).__name__, completed_cohorts=len(results), results=results,
                main_pipeline_stopped=False, automatic_retry=False)
            rr.put(args.directory / 'RESULT.json', failure)
            write_progress(args.directory / 'STATUS.json', failure)
            raise
        result = dict(state=state, at=now(), owner_pid=os.getpid(), completed_cohorts=len(results),
            results=results, official_http_calls=0, model_calls=0, corpus_ledger_writes=0,
            main_pipeline_stopped=False)
        rr.put(args.directory / 'RESULT.json', result)
        write_progress(args.directory / 'STATUS.json', result)
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pipeline', required=True, type=Path)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--max-cohorts', type=int, default=2)
    parser.add_argument('--poll-seconds', type=float, default=10)
    args = parser.parse_args()
    if not 1 <= args.poll_seconds <= 60:
        raise ValueError('invalid_poll_interval')
    print(json.dumps(run(args)))
