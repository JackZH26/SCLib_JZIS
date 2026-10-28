"""Continue uncalled papers after a proven, terminal Luna capacity failure.

This reconciles one known provider error. It does not retry failed jobs, alter
their receipts, bypass quota/authentication failures, or change scientific gates.
The caller must own the production pipeline lock. The shared provider-round
lock prevents extraction and audit calls from overlapping during reconciliation.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from ingestion.materials_ner import core_tc, finite_stage, reviewed_reader as rr
from ingestion.materials_ner.store import Store
from materials_ner_tc_round import provider_round

VERSION = 'production90-capacity-continuation/1'
CAPACITY_MESSAGE = 'Selected model is at capacity. Please try a different model.'
COMPLETED = {'succeeded', 'quarantined'}


def queue_snapshot(root):
    path = (Path(root) / 'queue.sqlite3').resolve()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return {r['id']: dict(r) for r in db.execute('SELECT * FROM jobs')}


def capacity_evidence(job):
    """Read-only classification; every provider artifact must still be intact."""
    if job['state'] != 'blocked' or job['attempts'] != 1 or job['max_attempts'] != 1:
        raise ValueError('capacity_failure_not_terminal_single_attempt')
    config = json.loads(job['config_json'])
    if config.get('workflow') != core_tc.WORKFLOW or config.get('model') != 'gpt-6-luna':
        raise ValueError('capacity_failure_unsupported_workflow')
    receipt = finite_stage.existing(dict(job, config=config), core_tc)
    path = Path(job['result_path'])
    if (receipt.get('state') != 'blocked' or receipt.get('error_code') != 'codex_turn_failed'
            or receipt.get('work_id') != job['work_id']
            or receipt.get('attempt_id') != path.parent.name
            or not receipt.get('provider_dispatch_intent_recorded')):
        raise ValueError('capacity_failure_receipt_mismatch')
    failure = json.loads(rr.checked(receipt['failure']).read_bytes())
    if failure.get('exception_class') != 'ProviderFailure' or failure.get('error_code') != 'codex_turn_failed':
        raise ValueError('capacity_failure_not_provider_error')
    event_pin = next((p for p in failure['raw_artifacts']
                      if Path(p['path']) == path.parent / 'events.jsonl'), None)
    if event_pin is None:
        raise ValueError('capacity_failure_events_missing')
    events = [json.loads(line) for line in rr.checked(event_pin).read_text().splitlines() if line.strip()]
    expected = dict(type='turn.failed', error=dict(message=CAPACITY_MESSAGE))
    if not events or events[-1] != expected or any(e.get('type') == 'turn.completed' for e in events):
        raise ValueError('provider_failure_not_confirmed_capacity')
    if any((path.parent / name).exists() for name in ['provider-result.json', 'response.json']):
        raise ValueError('capacity_failure_has_unreconciled_output')
    return dict(job_id=job['id'], work_id=job['work_id'], receipt=rr.reference(path),
        failure=receipt['failure'], events=event_pin, reason='provider_capacity_unavailable',
        disposition='deferred_without_retry', paper_completed=False, usage_known=False)


def checked_deferrals(root, directory):
    """Only terminal receipts explicitly reconciled for this batch may be skipped."""
    path = Path(directory) / 'CAPACITY_CONTINUATION' / 'PLAN.json'
    if not path.exists():
        return []
    plan = json.loads(path.read_bytes())
    rr.checked(plan['batch'])
    if Path(plan['batch']['path']) != Path(directory).resolve() / 'BATCH.json':
        raise ValueError('capacity_deferral_batch_mismatch')
    current = queue_snapshot(root)
    for failure in plan['deferred']:
        if capacity_evidence(current[failure['job_id']]) != failure:
            raise ValueError('capacity_deferred_receipt_changed')
    return plan['deferred']


def _probe(root, directory, job):
    result = core_tc.run(Store(root), job['job_id'])
    if result['state'] not in COMPLETED:
        raise ValueError('capacity_probe_not_completed')
    folder = Path(directory) / job['work_id'][6:].replace('/', '_')
    rr.put(folder / 'RESULT.json', result)
    # An invalid scientific output is still a completed call, not a capacity
    # error. Preserve it for normal deterministic triage without redrafting.
    try:
        packet = core_tc.build_packet(root, job['job_id'])
        rr.put(folder / 'PACKET.json', packet)
        rr.put(folder / 'PROJECTION_CORE.json', core_tc.project(packet))
    except (ValueError, KeyError) as exc:
        rr.put(folder / 'CAPACITY_PROBE_OUTPUT_HOLD.json',
               dict(error_class=type(exc).__name__, error=str(exc)[:1000], automatic_retry=False))


def continue_pending(root, directory):
    """One reconciliation/probe per batch, only for never-dispatched siblings."""
    from materials_ner_tc_batch import run_locked

    root, directory = Path(root).resolve(), Path(directory).resolve()
    here = directory / 'CAPACITY_CONTINUATION'
    with provider_round(root):
        current = queue_snapshot(root)
        if any(r['state'] == 'running' for r in current.values()):
            raise ValueError('capacity_continuation_has_active_or_unreconciled_job')
        batch = json.loads((directory / 'BATCH.json').read_bytes())
        ids = {j['job_id'] for j in batch['jobs']}
        if len(ids) != len(batch['jobs']) or not ids or len(ids) > 60:
            raise ValueError('capacity_continuation_batch_bounds')
        if any(j.get('profile') != 'core' for j in batch['jobs']):
            raise ValueError('capacity_continuation_requires_core_jobs')
        jobs = [current[j['job_id']] for j in batch['jobs']]
        if (here / 'RESULT.json').exists():
            report = json.loads((here / 'RESULT.json').read_bytes())
            checked_deferrals(root, directory)
            for pin in report['completion_evidence']:
                rr.checked(pin)
            return report
        hold = root / 'READER_DISPATCH_HOLD.json'
        plan_path = here / 'PLAN.json'
        if not plan_path.exists():
            failed = [r for r in jobs if r['state'] not in COMPLETED | {'queued'}]
            if not failed:
                raise ValueError('capacity_continuation_has_no_failed_job')
            deferred = [capacity_evidence(r) for r in failed]
            # A hold from another operation cannot be cleared by this batch.
            oldest = min(r['created_at'] for r in jobs)
            if any(r['id'] not in ids and r['state'] in {'failed', 'blocked'}
                   and r['updated_at'] >= oldest for r in current.values()):
                raise ValueError('capacity_continuation_unrelated_failure')
            pending = [r for r in jobs if r['state'] == 'queued']
            if any(r['attempts'] != 0 or r['max_attempts'] != 1 for r in pending):
                raise ValueError('capacity_continuation_would_retry_attempt')
            marker = json.loads(hold.read_bytes())
            if (marker.get('schema') != 'materials-reviewed-reader-dispatch-hold/1'
                    or marker.get('reason') != 'uncertain_provider_completion_requires_reconciliation'
                    or marker.get('automatic_resume') is not False):
                raise ValueError('capacity_continuation_unknown_hold')
            here.mkdir(exist_ok=True)
            archive = here / 'ORIGINAL_DISPATCH_HOLD.json'
            rr.immutable(archive, hold.read_bytes())
            plan = dict(schema=VERSION, at=datetime.now(timezone.utc).isoformat(),
                batch=rr.reference(directory / 'BATCH.json'), deferred=deferred,
                dispatch_hold=rr.reference(archive), pending_job_ids=[r['id'] for r in pending],
                probe_job_id=pending[0]['id'] if pending else None,
                preserved_receipts=[rr.reference(r['result_path']) for r in jobs if r['state'] != 'queued'],
                failed_attempts_retried=False, maximum_reconciliations=1,
                dispatch_policy='One uncalled-paper probe, then the remaining uncalled papers using their registered bounded worker round.')
            rr.put(plan_path, plan)
        else:
            plan = json.loads(plan_path.read_bytes())
            checked_deferrals(root, directory)
        for pin in [plan['batch'], plan['dispatch_hold'], *plan['preserved_receipts']]:
            rr.checked(pin)
        for identifier in plan['pending_job_ids']:
            row = current[identifier]
            if row['state'] == 'queued' and row['attempts'] != 0:
                raise ValueError('capacity_continuation_would_retry_attempt')
            if row['state'] not in COMPLETED | {'queued'}:
                raise ValueError('capacity_continuation_second_failure_requires_review')
        if hold.exists():
            # A reappearing marker after any new dispatch is a second failure;
            # equal generic marker bytes must not disguise it as the old hold.
            if any(current[i]['attempts'] for i in plan['pending_job_ids']):
                raise ValueError('capacity_continuation_new_dispatch_hold')
            if hold.read_bytes() != rr.checked(plan['dispatch_hold']).read_bytes():
                raise ValueError('capacity_continuation_dispatch_hold_changed')
            hold.unlink()
        probe_id = plan['probe_job_id']
        if probe_id is not None and current[probe_id]['state'] == 'queued':
            _probe(root, directory, next(j for j in batch['jobs'] if j['job_id'] == probe_id))
        current = queue_snapshot(root)
        if hold.exists() or (probe_id and current[probe_id]['state'] not in COMPLETED):
            raise ValueError('capacity_probe_not_completed')
        if any(current[i]['state'] == 'queued' for i in plan['pending_job_ids']):
            run_locked(root, directory, batch['sources'], only_new_papers=batch.get('only_new_papers', False))
        after = queue_snapshot(root)
        for pin in plan['preserved_receipts']:
            rr.checked(pin)
        checked_deferrals(root, directory)
        if hold.exists() or any(after[i]['state'] not in COMPLETED or after[i]['attempts'] != 1
                                for i in plan['pending_job_ids']):
            raise ValueError('capacity_continuation_incomplete_requires_review')
        report = dict(schema=VERSION, at=datetime.now(timezone.utc).isoformat(),
            state='completed_with_deferred_capacity_failure', batch=directory.name,
            completed_jobs=sum(after[i]['state'] in COMPLETED for i in ids),
            newly_completed_jobs=len(plan['pending_job_ids']), deferred_jobs=len(plan['deferred']),
            original_receipts_unchanged=True, failed_attempts_retried=False,
            completion_evidence=[rr.reference(plan_path), *plan['preserved_receipts'],
                *[rr.reference(after[i]['result_path']) for i in plan['pending_job_ids']]])
        rr.put(here / 'RESULT.json', report)
        return report
