"""Production orchestration tests use fake extraction, never scientific results."""
from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3
import pytest

from ingestion.materials_ner import reviewed_reader as rr
import materials_ner_tc_production as production


def test_window_boundary_does_not_depend_on_verdicts_or_paper_count():
    assert not production.window_due([dict(eligible_results=499)])
    assert production.window_due([dict(eligible_results=499),dict(eligible_results=7)])
    assert production.window_due([dict(eligible_results=13)],tail=True)
    assert not production.window_due([dict(eligible_results=0)],tail=True)


def test_window_ledger_updates_all_member_papers_before_total_check(tmp_path,monkeypatch):
    root=tmp_path/'root';root.mkdir();campaign=tmp_path/'campaign';campaign.mkdir()
    with sqlite3.connect(root/'corpus.sqlite3') as db:
        db.execute('CREATE TABLE papers(work_id TEXT,retained_rows INTEGER,state TEXT,full_ner_done INTEGER)')
        db.executemany('INSERT INTO papers VALUES(?,?,?,?)',[
            ('arxiv:a',0,'candidates_held',1),('arxiv:b',0,'candidates_held',1),('arxiv:old',7,'tc_pass_partial_ingested',1)])
    for name,work in [('batch-124','arxiv:a'),('batch-125','arxiv:b')]:
        (campaign/name).mkdir();rr.put(campaign/name/'BATCH.json',dict(jobs=[dict(work_id=work)]))
    async def counts(url,works):return dict(total=12,by_paper={'arxiv:a':2,'arxiv:b':3})
    monkeypatch.setattr(production,'database_counts',counts)
    def reconcile(root,campaign,directory,counts):
        with sqlite3.connect(root/'corpus.sqlite3') as db:
            assert db.execute('SELECT sum(retained_rows) FROM papers').fetchone()[0]==12
            assert db.execute("SELECT count(*) FROM papers WHERE state='candidates_held'").fetchone()[0]==0
        return dict(canonical_records=12)
    monkeypatch.setattr(production,'reconcile_batch',reconcile)
    args=SimpleNamespace(root=root,campaign=campaign,database_url='synthetic')
    counts,corpus=production.reconcile_window(args,[dict(batch='batch-124'),dict(batch='batch-125')])
    assert counts['total']==corpus['canonical_records']==12


@pytest.mark.parametrize('workers',[2,3])
def test_window_is_registered_before_extraction_and_closed_batches_resume_without_calls(tmp_path,monkeypatch,workers):
    root=tmp_path/'root';root.mkdir();campaign=tmp_path/'campaign';campaign.mkdir()
    plan=tmp_path/'source-plan.json';rr.put(plan,dict(synthetic=True))
    goal=tmp_path/'goal.txt';goal.write_text('Synthetic orchestration test.')
    args=SimpleNamespace(root=root,campaign=campaign,directory=tmp_path/'pipeline',
        audit_root=tmp_path/'audit',plan=plan,goal=goal,source_python=Path('/synthetic/python'),
        ssh_host='synthetic',source_start=117,batch_start=124,max_batches=2,database_url='synthetic',max_concurrency=workers)
    calls=[]
    def source(*unused):return [dict(work_id='arxiv:synthetic')]
    def extract(root,batch,sources,only_new_papers,max_concurrency=2):
        assert (args.directory/'windows/window-001/PLAN.json').exists()
        assert max_concurrency==workers
        assert json.loads((args.directory/'PLAN.json').read_text())['max_concurrent_model_calls']==workers
        calls.append(('extract',batch.name));batch.mkdir();rr.put(batch/'BATCH.json',dict(synthetic=True))
    def receipt(args,batch):
        return dict(batch=batch.name,completed_papers=1,eligible_results=300 if batch.name=='batch-124' else 200,
            canonical_records=0,source_entries=[],completion_evidence=[rr.reference(batch/'BATCH.json')])
    def finish(args,directory,policy,members):
        calls.append(('audit',[m['batch'] for m in members]))
        assert sum(m['eligible_results'] for m in members)==500 and policy['sample_size']==50
        rr.put(directory/'MEMBERS.json',dict(batches=[m['batch'] for m in members]))
        rr.put(directory/'RESULT.json',dict(completion_evidence=[rr.reference(directory/'MEMBERS.json')]))
    monkeypatch.setattr(production,'source_batch',source)
    monkeypatch.setattr(production,'prefetch_source',source)
    monkeypatch.setattr(production,'extract_batch',extract)
    monkeypatch.setattr(production,'extraction_receipt',receipt)
    monkeypatch.setattr(production,'queue_rows',lambda root,manifest: [])
    monkeypatch.setattr(production,'finish_window',finish)
    production.run(args)
    assert calls==[('extract','batch-124'),('extract','batch-125'),('audit',['batch-124','batch-125'])]
    original=list(calls);production.run(args)
    assert calls==original
    assert json.loads((args.directory/'STATUS.json').read_bytes())['state']=='bounded_phase_complete'
