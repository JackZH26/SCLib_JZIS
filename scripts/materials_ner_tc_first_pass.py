"""Account for every frozen arXiv paper without dispatching or changing data.

Terminal model receipts prove an attempted available-text Tc pass, not complete
paper coverage, recall or scientific acceptance. Isolated source/provider holds
are retained in the denominator and the follow-up queue.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3


VERSION = 'materials-first-pass-accounting/1'
TERMINAL = {'succeeded', 'quarantined', 'failed', 'blocked'}
PENDING = {'queued', 'running'}
SITE = Path(__file__).resolve().parent.parent


def pin(path):
    path = Path(path)
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def read(path):
    return json.loads(Path(path).read_bytes())


def resolved(path):
    path = Path(path)
    return path if path.is_absolute() else SITE / path


def checked_receipt(job):
    path = resolved(job['result_path'])
    receipt_pin = pin(path)
    if receipt_pin['sha256'] != job['result_hash']:
        raise ValueError('terminal_receipt_hash_mismatch')
    receipt = read(path)
    if any(receipt.get(key) != job[field] for key, field in
        [('job_id', 'id'), ('work_id', 'work_id'), ('state', 'state')]):
        raise ValueError('terminal_receipt_identity_mismatch')
    config = json.loads(job['config_json'])
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    if hashlib.sha256(canonical.encode()).hexdigest() != receipt.get('config_sha256'):
        raise ValueError('terminal_receipt_configuration_mismatch')
    return dict(job_id=job['id'], state=job['state'], receipt=receipt_pin,
        model=config.get('model'), workflow=config.get('workflow'),
        outcome=receipt.get('outcome'), error_code=receipt.get('error_code'),
        reported_candidates=receipt.get('core_results', receipt.get('result_count')))


def checked_source_hold(paper):
    path = resolved(paper['last_receipt'])
    receipt_pin, receipt = pin(path), read(path)
    if receipt.get('work_id') == paper['work_id'] and receipt.get('state') == 'source_route_held':
        reason = receipt.get('reason') or receipt.get('error')
        if reason:
            return dict(reason=reason, receipt=receipt_pin)
    for hold in receipt.get('preparation_holds', []):
        if hold.get('work_id') == paper['work_id'] and hold.get('error'):
            return dict(reason=hold['error'], stage=hold.get('stage'), receipt=receipt_pin)
    raise ValueError('source_hold_not_bound_to_paper_and_reason')


def paper_outcome(paper, jobs):
    row = dict(work_id=paper['work_id'], ledger_state=paper['state'],
        ledger_tc_pass_done=bool(paper['full_ner_done']),
        historical_canonical_records=paper['retained_rows'],
        source_inventory_disposition=paper['source_disposition'],
        coverage_scope='available_original_text_explicit_tc',
        whole_paper_recall_measured=False, first_pass_resolved=False)
    row['job_states'] = dict(Counter(job['state'] for job in jobs))
    if any(job['state'] in PENDING for job in jobs):
        row.update(outcome='pending_provider_work', next_action='finish_existing_jobs_without_redispatch')
        return row
    evidence, issues = [], []
    for job in jobs:
        if job['state'] not in TERMINAL:
            issues.append('unknown_job_state:' + job['state'])
            continue
        try:
            evidence.append(checked_receipt(job))
        except (ValueError, OSError, TypeError, KeyError) as exc:
            issues.append(type(exc).__name__ + ':' + str(exc))
    row['terminal_jobs'] = evidence
    if issues:
        row.update(outcome='receipt_reconciliation_required', issues=issues,
            next_action='inspect_existing_receipts_without_redispatch')
        return row
    successful = any(job['state'] in {'succeeded', 'quarantined'} for job in evidence)
    if successful:
        if not paper['full_ner_done']:
            row.update(outcome='pending_ledger_reconciliation', next_action='reconcile_completed_batch_receipts')
        elif paper['state'] == 'no_target_returned_unverified' and (
            not any(job['reported_candidates'] == 0 for job in evidence)
            or any((job['reported_candidates'] or 0) > 0 for job in evidence)):
            row.update(outcome='ledger_no_target_result_mismatch',
                next_action='reconcile_existing_result_counts_without_redispatch')
        else:
            outcome = ('processed_with_historical_canonical_results' if paper['retained_rows']
                else 'no_target_returned_unverified' if paper['state'] == 'no_target_returned_unverified'
                else 'processed_candidates_or_output_held')
            row.update(outcome=outcome, first_pass_resolved=True,
                next_action='resolve_quality_window_or_record_followup')
        return row
    if evidence:
        if paper['full_ner_done']:
            row.update(outcome='ledger_claims_pass_without_completed_extraction',
                next_action='reconcile_existing_receipts_without_redispatch')
        else:
            row.update(outcome='provider_failure_or_uncertain_completion_deferred',
                first_pass_resolved=True, next_action='inspect_existing_attempt_before_any_retry')
        return row
    if paper['full_ner_done']:
        row.update(outcome='ledger_claims_pass_without_job', next_action='locate_missing_attempt_evidence')
    elif paper['state'] == 'source_route_held':
        try:
            row.update(source_hold=checked_source_hold(paper), outcome='source_or_preparation_deferred',
                first_pass_resolved=True, next_action='source_followup_after_main_pass')
        except (ValueError, OSError, TypeError, KeyError) as exc:
            row.update(outcome='source_hold_receipt_reconciliation_required',
                issues=[type(exc).__name__ + ':' + str(exc)], next_action='locate_bound_source_hold_receipt')
    elif paper['retained_rows']:
        row.update(outcome='pending_first_pass_with_preexisting_results',
            next_action='run_available_text_pass_preserving_and_deduplicating_existing_results')
    elif paper['state'] == 'source_ready':
        row.update(outcome='source_ready_awaiting_dispatch', next_action='consume_existing_prepared_source')
    elif paper['state'] == 'queued':
        row.update(outcome='queued_for_first_pass', next_action='continue_registered_source_queue')
    else:
        row.update(outcome='unresolved_ledger_state', next_action='inspect_ledger_and_existing_receipts')
    return row


def account(papers, jobs, expected_ids):
    observed = {paper['work_id'] for paper in papers}
    if len(observed) != len(papers) or observed != set(expected_ids):
        raise ValueError('frozen_arxiv_denominator_mismatch')
    by_work = defaultdict(list)
    for job in jobs:
        if job['work_id'] not in observed:
            raise ValueError('provider_job_outside_frozen_arxiv_denominator')
        by_work[job['work_id']].append(job)
    return [paper_outcome(paper, by_work[paper['work_id']])
        for paper in sorted(papers, key=lambda item: item['work_id'])]


def capture(root, plan_path, plan_sha256, pipeline, output):
    root, pipeline, output = Path(root).resolve(), Path(pipeline).resolve(), Path(output).resolve()
    frozen_pin = pin(plan_path)
    if frozen_pin['sha256'] != plan_sha256:
        raise ValueError('frozen_plan_changed')
    plan = read(plan_path)
    expected = [paper['id'] for paper in plan['papers'] if paper['source'] == 'arxiv']
    if len(set(expected)) != len(expected):
        raise ValueError('duplicate_paper_in_frozen_plan')
    # Attached SQLite databases are read in one transaction. During production,
    # cross-store changes are still reported as a live observation, not closeout.
    with sqlite3.connect((root / 'corpus.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('ATTACH DATABASE ? AS queue', ((root / 'queue.sqlite3').as_uri() + '?mode=ro',))
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        papers = [dict(row) for row in db.execute('SELECT * FROM papers')]
        jobs = [dict(row) for row in db.execute('SELECT * FROM queue.jobs ORDER BY id')]
    rows = account(papers, jobs, expected)
    with sqlite3.connect((root / 'source-audit-v1/queue.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        audit_states = dict(db.execute('SELECT state,count(*) FROM jobs GROUP BY state'))
    status_path = pipeline / 'STATUS.json'
    status = read(status_path)
    pipeline_running = True
    lock_path = root / '.production90-pipeline.lock'
    with lock_path.open('rb') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            pipeline_running = False
        except BlockingIOError:
            pass
    counts = Counter(row['outcome'] for row in rows)
    unresolved = sum(not row['first_pass_resolved'] for row in rows)
    finished = (not pipeline_running and unresolved == 0
        and not sum(audit_states.get(state, 0) for state in PENDING)
        and status.get('state') in {'queued_source_scope_exhausted', 'bounded_phase_complete'}
        and status.get('pending_eligible_results') == 0)
    report = dict(schema=VERSION, captured_at=datetime.now(timezone.utc).isoformat(),
        frozen_plan=frozen_pin, frozen_arxiv_papers=len(expected), paper_outcomes=dict(counts),
        verified_terminal_paper_conclusions=len(rows) - unresolved, pending_paper_conclusions=unresolved,
        provider_jobs=len(jobs), provider_job_states=dict(Counter(job['state'] for job in jobs)),
        audit_job_states=audit_states, ledger_completed_text_passes=sum(paper['full_ner_done'] for paper in papers),
        ledger_historical_canonical_records=sum(paper['retained_rows'] for paper in papers),
        pipeline_status=pin(status_path), observed_pipeline_state=status,
        pipeline_owner_lock_held=pipeline_running, first_pass_accounted_for=finished,
        whole_corpus_scientific_accuracy_measured=False, full_goal_complete=False,
        provider_calls=0, database_writes=False, deployment_allowed_by_this_report=False,
        limitations=[
            'Counts cover available-text Tc passes, not complete-paper extraction or measured recall.',
            'Historical canonical counts include later exclusions; use the canonical API/export for current usable counts.',
            'A source or provider deferral remains in the denominator and is not a successful extraction.',
            'No-target output does not establish absence of superconducting results.',
            'Scientific quality windows, current database export, deployment and rollback are separate requirements.',
        ])
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'PAPER_OUTCOMES.jsonl').open('x') as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + '\n')
    followup = [row for row in rows if row['outcome'] not in {
        'processed_with_historical_canonical_results', 'no_target_returned_unverified',
        'queued_for_first_pass', 'source_ready_awaiting_dispatch', 'pending_provider_work'}]
    with (output / 'FOLLOWUP_QUEUE.jsonl').open('x') as stream:
        for row in followup:
            stream.write(json.dumps(row, sort_keys=True) + '\n')
    report['paper_outcome_file'] = pin(output / 'PAPER_OUTCOMES.jsonl')
    report['followup_file'] = pin(output / 'FOLLOWUP_QUEUE.jsonl')
    (output / 'RESULT.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['root', 'plan', 'pipeline', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(capture(args.root, args.plan, args.plan_sha256, args.pipeline, args.output), indent=2))
