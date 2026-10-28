"""Scheduling/recovery tests; mock verdicts never constitute scientific QA."""
import json
from pathlib import Path
import sqlite3
import subprocess
import threading
from types import SimpleNamespace
import venv

import pytest

import materials_ner_tc_pipeline as pipeline


def test_child_python_retains_its_virtual_environment(tmp_path):
    environment=tmp_path/'source-venv'
    venv.EnvBuilder(with_pip=False,symlinks=True).create(environment)
    executable=pipeline.executable_path(environment/'bin/python')
    prefix=subprocess.check_output([str(executable),'-c','import sys;print(sys.prefix)'],text=True).strip()
    assert Path(prefix)==environment


def test_existing_source_producer_is_joined_without_duplicate_download(tmp_path,monkeypatch):
    directory=tmp_path/'source';directory.mkdir()
    expected=[dict(work_id='arxiv:paper-1')]
    seen=threading.Event();failure=[]
    original=pipeline.progress
    def progress(path,value):
        original(path,value)
        if value['state']=='waiting_existing_source_acquisition':seen.set()
    monkeypatch.setattr(pipeline,'progress',progress)
    def forbidden(*a,**kw):pytest.fail('The completed producer must be reused')
    monkeypatch.setattr(pipeline.subprocess,'Popen',forbidden)
    with (directory/'.lock').open('a') as owner:
        pipeline.fcntl.flock(owner,pipeline.fcntl.LOCK_EX)
        def join():
            try:assert pipeline.source_batch(None,directory,tmp_path/'status.json')==expected
            except BaseException as exc:failure.append(exc)
        thread=threading.Thread(target=join);thread.start()
        assert seen.wait(3)
        pipeline.rr.put(directory/'NER_SOURCES.json',expected)
        pipeline.fcntl.flock(owner,pipeline.fcntl.LOCK_UN)
    thread.join(3)
    assert not thread.is_alive() and not failure


def batch(tmp_path,state='quarantined'):
    root=tmp_path/'queue';root.mkdir()
    directory=tmp_path/'batch';directory.mkdir()
    with sqlite3.connect(root/'queue.sqlite3') as db:
        db.execute('CREATE TABLE jobs(id TEXT,state TEXT,attempts INTEGER,result_path TEXT)')
        db.execute('INSERT INTO jobs VALUES(?,?,1,NULL)',('job-1',state))
    with sqlite3.connect(root/'corpus.sqlite3') as db:
        db.execute('CREATE TABLE papers(work_id TEXT,state TEXT,full_ner_done INTEGER,retained_rows INTEGER,last_receipt TEXT)')
        db.execute("INSERT INTO papers VALUES('arxiv:paper-1','queued',0,0,NULL)")
    pipeline.rr.put(directory/'BATCH.json',dict(jobs=[dict(job_id='job-1',work_id='arxiv:paper-1',profile='core')],preparation_holds=[]))
    return root,directory


@pytest.mark.parametrize('state',['queued','running','blocked','failed'])
def test_incomplete_or_provider_failure_cannot_freeze_a_passing_sample(tmp_path,state):
    root,directory=batch(tmp_path,state)
    with pytest.raises(ValueError):pipeline.freeze_batch(root,directory)
    assert not (directory/'FROZEN_SAMPLE.json').exists()
    assert not (directory/'NO_ELIGIBLE_RECORDS.json').exists()


def test_invalid_output_has_no_accuracy_or_no_superconductivity_claim(tmp_path):
    root,directory=batch(tmp_path)
    assert pipeline.freeze_batch(root,directory) is None
    receipt=json.loads((directory/'NO_ELIGIBLE_RECORDS.json').read_bytes())
    assert not receipt['scientific_accuracy_measured']
    assert not receipt['no_superconductivity_claimed']
    assert not receipt['full_paper_recall_measured']


def test_subthreshold_batch_is_retained_as_a_hold_and_not_admitted(tmp_path,monkeypatch):
    root,directory=batch(tmp_path)
    selection=directory/'FROZEN_SAMPLE.json';selection.write_text('{}')
    monkeypatch.setattr(pipeline,'freeze_batch',lambda *a:selection)
    monkeypatch.setattr(pipeline,'audit_batch',lambda *a:dict(qualified=False,observed_precision=0.8))
    async def counts(*a):return dict(total=0,by_paper={})
    async def forbidden(*a):pytest.fail('A subthreshold batch must not be admitted')
    monkeypatch.setattr(pipeline,'database_counts',counts)
    monkeypatch.setattr(pipeline,'admit',forbidden)
    result=pipeline.finish_batch(root,tmp_path,directory,tmp_path/'audit','unused')
    assert result['state']=='scientific_batch_held' and result['new_claims']==0
    with sqlite3.connect(root/'corpus.sqlite3') as db:
        assert db.execute('SELECT state,retained_rows FROM papers').fetchone()==('candidates_held',0)


def test_partial_commit_is_recorded_then_stops_advancement(tmp_path,monkeypatch):
    root,directory=batch(tmp_path)
    selection=directory/'FROZEN_SAMPLE.json';selection.write_text('{}')
    monkeypatch.setattr(pipeline,'freeze_batch',lambda *a:selection)
    monkeypatch.setattr(pipeline,'audit_batch',lambda *a:dict(qualified=True,observed_precision=0.95))
    values=iter([dict(total=0,by_paper={}),dict(total=1,by_paper={'arxiv:paper-1':1})])
    async def counts(*a):return next(values)
    async def admit(*a):return [dict(status='committed_verification_incomplete',committed=True)]
    monkeypatch.setattr(pipeline,'database_counts',counts)
    monkeypatch.setattr(pipeline,'admit',admit)
    with pytest.raises(ValueError,match='committed_database_verification_incomplete'):
        pipeline.finish_batch(root,tmp_path,directory,tmp_path/'audit','unused')
    receipt=json.loads(next(directory.glob('PIPELINE_RESULT-*.json')).read_bytes())
    assert receipt['claims_after']==1 and receipt['new_claims']==1
    with sqlite3.connect(root/'corpus.sqlite3') as db:
        assert db.execute('SELECT retained_rows FROM papers').fetchone()[0]==1


def test_resume_skips_completed_batches_and_continues_after_scientific_hold(tmp_path,monkeypatch):
    root=tmp_path/'queue';root.mkdir()
    campaign=tmp_path/'campaign';campaign.mkdir()
    plan=tmp_path/'source-plan.json';plan.write_text('{}')
    args=SimpleNamespace(root=root,campaign=campaign,directory=tmp_path/'pipeline',
        audit_root=tmp_path/'audit',plan=plan,source_python=Path('/test/python'),
        source_start=1,batch_start=1,max_batches=2,database_url='unused',ssh_host='unused')
    calls=[];interrupt=[True]
    def source(args,directory,status):
        calls.append(('source',directory.name));return [dict(work_id='arxiv:paper-1')]
    def extract(root,directory,sources,**kwargs):
        calls.append(('extract',directory.name));directory.mkdir(exist_ok=True)
        pipeline.rr.put(directory/'BATCH.json',dict(test=True))
    def finish(root,campaign,directory,audit_root,database_url):
        calls.append(('finish',directory.name))
        if directory.name=='batch-002' and interrupt[0]:
            interrupt[0]=False;raise RuntimeError('simulated interruption')
        return dict(batch=directory.name,state='scientific_batch_held',new_claims=0,claims_after=0)
    monkeypatch.setattr(pipeline,'source_batch',source)
    monkeypatch.setattr(pipeline,'extract_batch',extract)
    monkeypatch.setattr(pipeline,'finish_batch',finish)
    with pytest.raises(RuntimeError,match='simulated interruption'):pipeline.run(args)
    assert json.loads((args.directory/'STATUS.json').read_bytes())['state']=='stopped_for_review'
    assert (args.directory/'BATCH_000.json').exists()
    pipeline.run(args)
    assert calls.count(('source','source-batch-001'))==1
    assert calls.count(('extract','batch-001'))==1
    assert calls.count(('finish','batch-001'))==1
    assert calls.count(('finish','batch-002'))==2
    count=len(calls);pipeline.run(args)
    assert len(calls)==count
    status=json.loads((args.directory/'STATUS.json').read_bytes())
    assert status['state']=='bounded_run_finished' and not status['full_corpus_complete']
    assert len(status['completed'])==2


@pytest.mark.parametrize('outcome',['continue','stop','provider_failure','source_failure'])
def test_prefetch_overlaps_current_ner_without_dispatching_another_model_round(tmp_path,monkeypatch,outcome):
    root=tmp_path/'queue';root.mkdir()
    campaign=tmp_path/'campaign';campaign.mkdir()
    plan=tmp_path/'source-plan.json';plan.write_text('{}')
    args=SimpleNamespace(root=root,campaign=campaign,directory=tmp_path/'pipeline',
        audit_root=tmp_path/'audit',plan=plan,source_python=Path('/test/python'),
        source_start=1,batch_start=1,max_batches=2,database_url='unused',ssh_host='unused',
        prefetch_next_source=True)
    downloading=threading.Event();release=threading.Event();calls=[]
    main_thread=threading.get_ident()
    def source(args,directory,status):
        calls.append(('source',directory.name))
        if directory.name=='source-batch-002':
            assert threading.get_ident()!=main_thread
            assert status.name=='PREFETCH_001.json'
            downloading.set()
            assert release.wait(3),'Current NER must run while the next source is downloading'
            if outcome=='source_failure':raise RuntimeError('simulated source failure')
        return [dict(work_id=directory.name)]
    def extract(root,directory,sources,**kwargs):
        assert threading.get_ident()==main_thread
        calls.append(('extract',directory.name))
        directory.mkdir(exist_ok=True);pipeline.rr.put(directory/'BATCH.json',dict(test=True))
        if directory.name=='batch-001':
            try:
                assert downloading.wait(3),'Next source must start before current NER finishes'
                assert json.loads((args.directory/'STATUS.json').read_bytes())['state']=='extracting'
            finally:release.set()
            if outcome=='provider_failure':raise RuntimeError('simulated provider failure')
        else:assert ('finish','batch-001') in calls
    def finish(root,campaign,directory,audit_root,database_url):
        calls.append(('finish',directory.name))
        if outcome=='stop':(args.directory/'STOP_AFTER_BATCH').touch()
        return dict(batch=directory.name,state='scientific_batch_held',new_claims=0,claims_after=0)
    monkeypatch.setattr(pipeline,'source_batch',source)
    monkeypatch.setattr(pipeline,'extract_batch',extract)
    monkeypatch.setattr(pipeline,'finish_batch',finish)
    if outcome.endswith('_failure'):
        with pytest.raises(RuntimeError,match='simulated .* failure'):pipeline.run(args)
    else:pipeline.run(args)
    assert calls.count(('source','source-batch-001'))==1
    assert calls.count(('source','source-batch-002'))==1
    assert calls.count(('extract','batch-001'))==1
    assert calls.count(('extract','batch-002'))==int(outcome=='continue')
    status=json.loads((args.directory/'STATUS.json').read_bytes())
    expected='bounded_run_finished' if outcome=='continue' else 'stopped_at_batch_boundary' if outcome=='stop' else 'stopped_for_review'
    assert status['state']==expected and not status['full_corpus_complete']
    prefetch=json.loads((args.directory/'PREFETCH_001.json').read_bytes())
    assert prefetch['state']==('source_prefetch_failed' if outcome=='source_failure' else 'source_prefetch_ready')
    if outcome=='continue':
        count=len(calls);pipeline.run(args)
        assert len(calls)==count,'Resuming completed batches must not restart downloads or models'
