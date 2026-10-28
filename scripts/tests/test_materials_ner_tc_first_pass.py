"""First-pass coverage cannot be fabricated from existing results or missing rows."""
import hashlib
import json
import fcntl
import sqlite3

import pytest

from materials_ner_tc_first_pass import account, capture, paper_outcome


def paper(**changes):
    return dict(work_id='arxiv:2401.00001', state='queued', source_disposition='gcs_acquisition_required',
        full_ner_done=0, retained_rows=0, last_receipt=None, **changes)


def job(tmp_path, *, state='succeeded', candidates=0):
    config = dict(model='gpt-6-luna', workflow='core_tc_v1')
    raw_config = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    receipt = dict(job_id='job', work_id='arxiv:2401.00001', state=state,
        config_sha256=hashlib.sha256(raw_config.encode()).hexdigest(), core_results=candidates,
        outcome='core_tc_candidates')
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(receipt))
    return dict(id='job', work_id=receipt['work_id'], state=state, config_json=raw_config,
        result_path=str(path), result_hash=hashlib.sha256(path.read_bytes()).hexdigest())


def changed_paper(**changes):
    value = paper()
    value.update(changes)
    return value


def test_prior_admission_without_a_paper_pass_stays_pending():
    row = paper_outcome(changed_paper(state='retained_partial_ingested', retained_rows=5), [])
    assert row['outcome'] == 'pending_first_pass_with_preexisting_results'
    assert row['historical_canonical_records'] == 5
    assert row['first_pass_resolved'] is False


def test_zero_target_output_is_not_a_claim_of_no_superconductivity(tmp_path):
    row = paper_outcome(changed_paper(state='no_target_returned_unverified', full_ner_done=1), [job(tmp_path)])
    assert row['outcome'] == 'no_target_returned_unverified'
    assert row['first_pass_resolved'] is True
    assert row['whole_paper_recall_measured'] is False


def test_stale_no_target_label_cannot_override_returned_candidates(tmp_path):
    row = paper_outcome(changed_paper(state='no_target_returned_unverified', full_ner_done=1),
        [job(tmp_path, candidates=2)])
    assert row['outcome'] == 'ledger_no_target_result_mismatch'
    assert row['first_pass_resolved'] is False


@pytest.mark.parametrize('change', ['bytes', 'work', 'configuration'])
def test_missing_or_rebound_terminal_proof_never_completes_the_paper(tmp_path, change):
    record = job(tmp_path)
    if change == 'bytes':
        (tmp_path / 'receipt.json').write_text('{}')
    elif change == 'work':
        record['work_id'] = 'arxiv:2401.00002'
    else:
        record['config_json'] = '{}'
    row = paper_outcome(changed_paper(full_ner_done=1), [record])
    assert row['outcome'] == 'receipt_reconciliation_required'
    assert row['first_pass_resolved'] is False


def test_uncertain_failed_call_is_deferred_without_claiming_extraction_success(tmp_path):
    row = paper_outcome(changed_paper(state='extraction_failed_or_uncertain'), [job(tmp_path, state='blocked')])
    assert row['outcome'] == 'provider_failure_or_uncertain_completion_deferred'
    assert row['first_pass_resolved'] is True
    assert row['ledger_tc_pass_done'] is False
    assert row['next_action'] == 'inspect_existing_attempt_before_any_retry'


def test_running_job_prevents_closeout_even_with_previous_results():
    row = paper_outcome(changed_paper(retained_rows=3, full_ner_done=1), [dict(state='running')])
    assert row['outcome'] == 'pending_provider_work'
    assert row['first_pass_resolved'] is False


@pytest.mark.parametrize('bound', [True, False])
def test_source_holds_need_a_paper_specific_reason(tmp_path, bound):
    path = tmp_path / 'source.json'
    path.write_text(json.dumps(dict(work_id='arxiv:2401.00001' if bound else 'arxiv:2401.00002',
        state='source_route_held', reason='official_version_unavailable')))
    row = paper_outcome(changed_paper(state='source_route_held', last_receipt=str(path)), [])
    assert row['first_pass_resolved'] is bound


def test_missing_paper_cannot_shrink_frozen_denominator():
    with pytest.raises(ValueError, match='denominator_mismatch'):
        account([paper()], [], {'arxiv:2401.00001', 'arxiv:2401.00002'})


def test_multiple_terminal_jobs_do_not_inflate_paper_count(tmp_path):
    jobs = [job(tmp_path), job(tmp_path)]
    rows = account([changed_paper(full_ner_done=1, state='no_target_returned_unverified')],
        jobs, {'arxiv:2401.00001'})
    assert len(rows) == 1 and rows[0]['first_pass_resolved'] is True


@pytest.mark.parametrize('unfinished', [None, 'audit', 'owner'])
def test_closeout_requires_finished_papers_audit_and_owner_and_never_writes_sql(tmp_path, unfinished):
    root, pipeline = tmp_path / 'runtime', tmp_path / 'pipeline'
    (root / 'source-audit-v1').mkdir(parents=True)
    pipeline.mkdir()
    source_hold = tmp_path / 'source-hold.json'
    source_hold.write_text(json.dumps(dict(work_id='arxiv:2401.00002', state='source_route_held',
        reason='official_version_unavailable')))
    papers = [changed_paper(state='no_target_returned_unverified', full_ner_done=1),
        changed_paper(work_id='arxiv:2401.00002', state='source_route_held', last_receipt=str(source_hold))]
    with sqlite3.connect(root / 'corpus.sqlite3') as db:
        db.execute('CREATE TABLE papers (work_id TEXT PRIMARY KEY,state TEXT,source_disposition TEXT,'
            'full_ner_done INTEGER,retained_rows INTEGER,last_receipt TEXT)')
        for item in papers:
            db.execute('INSERT INTO papers VALUES (:work_id,:state,:source_disposition,'
                ':full_ner_done,:retained_rows,:last_receipt)', item)
    record = job(tmp_path)
    with sqlite3.connect(root / 'queue.sqlite3') as db:
        db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY,work_id TEXT,state TEXT,config_json TEXT,'
            'result_path TEXT,result_hash TEXT)')
        db.execute('INSERT INTO jobs VALUES (:id,:work_id,:state,:config_json,:result_path,:result_hash)', record)
    with sqlite3.connect(root / 'source-audit-v1/queue.sqlite3') as db:
        db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY,state TEXT)')
        if unfinished == 'audit':
            db.execute("INSERT INTO jobs VALUES ('audit', 'running')")
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps(dict(papers=[dict(id=item['work_id'], source='arxiv') for item in papers]
        + [dict(id='aps:example', source='aps')])))
    (pipeline / 'STATUS.json').write_text(json.dumps(dict(state='queued_source_scope_exhausted',
        pending_eligible_results=0)))
    databases = [root / 'corpus.sqlite3', root / 'queue.sqlite3', root / 'source-audit-v1/queue.sqlite3']
    before = [path.read_bytes() for path in databases]
    with (root / '.production90-pipeline.lock').open('a') as owner:
        if unfinished == 'owner':
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = capture(root, plan, hashlib.sha256(plan.read_bytes()).hexdigest(), pipeline, tmp_path / 'output')
    assert report['frozen_arxiv_papers'] == 2
    assert report['verified_terminal_paper_conclusions'] == 2
    assert report['first_pass_accounted_for'] is (unfinished is None)
    assert report['full_goal_complete'] is False and report['database_writes'] is False
    assert before == [path.read_bytes() for path in databases]
