"""Bounded resumable Luna batch over pinned original-source preflights."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sqlite3
import time

from ingestion.materials_ner import production_tc, core_tc, projector_proposals, reviewed_reader as rr
from ingestion.materials_ner.store import Store
from materials_ner_tc_prepare import prepare
from materials_ner_tc_projection import project
from materials_ner_tc_round import provider_round


def run(root,directory,sources,*,only_new_papers=False,max_concurrency=None):
    with provider_round(root):
        return run_locked(root,directory,sources,only_new_papers=only_new_papers,max_concurrency=max_concurrency)


def run_locked(root,directory,sources,*,only_new_papers=False,max_concurrency=None):
    if max_concurrency is not None and (type(max_concurrency) is not int or not 1<=max_concurrency<=3):
        raise ValueError('batch_concurrency_out_of_bounds')
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    store=Store(Path(root));manifest=directory/'BATCH.json'
    if manifest.exists():
        batch=json.loads(manifest.read_bytes())
        if batch['sources']!=sources:raise ValueError('batch_source_selection_changed')
        if batch.get('only_new_papers',False)!=only_new_papers:raise ValueError('batch_dispatch_policy_changed')
        workers=batch['max_concurrency']
        if type(workers) is not int or not 1<=workers<=3:raise ValueError('batch_concurrency_out_of_bounds')
        if max_concurrency is not None and workers!=max_concurrency:raise ValueError('batch_concurrency_policy_changed')
    else:
        workers=2 if max_concurrency is None else max_concurrency
        jobs=[];holds=[];skipped=[];dispatched=set()
        if only_new_papers:
            with sqlite3.connect(store.root/'queue.sqlite3') as db:
                dispatched={r[0] for r in db.execute('SELECT DISTINCT work_id FROM jobs')}
        for source in sources[:60]:
            if source['work_id'] in dispatched:
                skipped.append(dict(work_id=source['work_id'],reason='existing_provider_job_requires_explicit_retry'))
                continue
            d=directory/source['work_id'][6:].replace('/','_')
            try:
                core=source.get('profile')=='core'
                prepared=prepare(source['preflight'],d,evidence_transport=source.get('evidence_transport','source_catalog'),source_only=core)
                if core:
                    rr.put(d/'CORE_REQUEST.json',dict(schema=core_tc.INPUT_SCHEMA,scope=rr.reference(d/'SCOPE.json'),coverage=rr.reference(d/'COVERAGE.json')))
                    cp=core_tc.prepare(d/'CORE_REQUEST.json')
                    prepared.update(input=rr.reference(d/'CORE_REQUEST.json'),input_tokens_estimate=cp['input_tokens_estimate'],profile='core')
                    jobid=core_tc.enqueue(store,d/'CORE_REQUEST.json')
                else:jobid=production_tc.enqueue(store,d/'REQUEST.json')
                jobs.append({**prepared,'job_id':jobid})
            except ValueError as exc:
                holds.append(dict(work_id=source['work_id'],stage='source_preparation',error=str(exc)))
        batch=dict(schema='production90-batch/3',root=str(store.root),sources=sources,jobs=jobs,preparation_holds=holds,
            only_new_papers=only_new_papers,skipped_existing_papers=skipped,
            max_concurrency=workers,max_jobs=60,max_seconds=1800,
            audit_rule='Per-result triage; production admission follows the separately registered source-audit window.')
        rr.put(manifest,batch)
    started=time.monotonic()
    def process(job):
        d=directory/job['work_id'][6:].replace('/','_')
        if time.monotonic()-started>1800:return dict(work_id=job['work_id'],status='queued_next_round')
        # finite_stage.run recovers existing attempts under its file lock. It
        # never blindly redispatches an already-terminal or uncertain attempt.
        try:
            core=job.get('profile')=='core'
            result=(core_tc if core else production_tc).run(store,job['job_id']);rr.put(d/'RESULT.json',result)
            packet=(core_tc.build_packet if core else projector_proposals.build)(store.root,job['job_id']);rr.put(d/'PACKET.json',packet)
            projection=(core_tc.project if core else project)(packet);rr.put(d/('PROJECTION_CORE.json' if core else 'PROJECTION_V2.json'),projection)
            return dict(work_id=job['work_id'],job_id=job['job_id'],state=result['state'],
                raw_results=projection['raw_results'],eligible=sum(r['status']=='eligible_for_source_audit' for r in projection['records']),
                holds=[dict(result_id=r['result_id'],holds=r['holds']) for r in projection['records'] if r['status']=='held'])
        except Exception as exc:
            result=dict(work_id=job['work_id'],job_id=job['job_id'],status='requires_recovery_or_triage',error_class=type(exc).__name__,error=str(exc)[:1000])
            rr.put(d/('BATCH_ERROR-'+str(time.time_ns())+'.json'),result)
            return result
    reports=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(process,j) for j in batch['jobs']]):
            result=future.result();reports.append(result);print(json.dumps(result),flush=True)
    report=dict(reports=reports,preparation_holds=batch['preparation_holds'],elapsed_seconds=time.monotonic()-started,max_concurrency=workers,
        canonical_admissions=0,automatic_source_audit=False)
    rr.put(directory/('ROUND-'+str(time.time_ns())+'.json'),report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--directory',required=True);p.add_argument('--sources',required=True)
    p.add_argument('--only-new-papers',action='store_true',help='Skip every paper already represented in the authoritative job queue; use an explicit separate retry batch for recovery.')
    p.add_argument('--max-concurrency',type=int,choices=[1,2,3],default=None,help='New batches default to two calls; resumed batches retain their registered limit.')
    a=p.parse_args();run(a.root,a.directory,json.loads(Path(a.sources).read_bytes()),only_new_papers=a.only_new_papers,max_concurrency=a.max_concurrency)
