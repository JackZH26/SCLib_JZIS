"""Resume bounded source -> extraction -> frozen audit -> admission rounds.

The runner never deploys, retries an uncertain model call, or edits a schema.
Individual scientific holds continue to the next batch. Provider/DB failures
stop advancement with a receipt. The database remains the count authority.
"""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ingestion.materials_ner import core_tc, core_tc_audit, reviewed_reader as rr
from materials_ner_tc_admit import admit
from materials_ner_tc_audit import run as audit_batch
from materials_ner_tc_batch import run as extract_batch
from materials_ner_tc_intake import checked_projection, freeze

SCRIPT_DIRECTORY=Path(__file__).resolve().parent
STAGE_SCRIPTS=('materials_ner_tc_pipeline.py','materials_ner_tc_sources.py',
    'materials_ner_tc_batch.py','materials_ner_tc_prepare.py','materials_ner_tc_round.py',
    'materials_ner_tc_audit.py','materials_ner_tc_intake.py','materials_ner_tc_sampling.py',
    'materials_ner_tc_admit.py')


def now():return datetime.now(timezone.utc).isoformat()


def executable_path(value):
    # Resolving the venv's interpreter symlink selects the base installation
    # and loses the source reader's httpx/pypdf dependencies.
    return Path(value).expanduser().absolute()


def progress(path,value):
    path=Path(path);temporary=path.with_suffix('.writing')
    temporary.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n');temporary.replace(path)


def queue_rows(root,manifest):
    with sqlite3.connect(Path(root)/'queue.sqlite3') as db:
        db.row_factory=sqlite3.Row
        rows={r['id']:dict(r) for r in db.execute('SELECT id,state,attempts,result_path FROM jobs')}
    return [rows[j['job_id']] for j in manifest['jobs']]


def freeze_batch(root,directory):
    directory=Path(directory);manifest=json.loads((directory/'BATCH.json').read_bytes())
    jobs=queue_rows(root,manifest)
    if any(j['state'] in {'queued','running'} for j in jobs):raise ValueError('ner_round_incomplete')
    if any(j['state'] in {'blocked','failed'} for j in jobs):raise ValueError('provider_failure_requires_review')
    entries=[];eligible=0
    for job in manifest['jobs']:
        folder=directory/job['work_id'][6:].replace('/','_')
        p=folder/('PROJECTION_CORE.json' if job.get('profile')=='core' else 'PROJECTION_V2.json')
        if not p.exists():
            # Preserve an invalid model/schema output as a processed hold.
            continue
        entry=dict(packet=rr.reference(folder/'PACKET.json'),projection=rr.reference(p))
        _,projection=checked_projection(entry)
        eligible+=sum(r['status']=='eligible_for_source_audit' for r in projection['records'])
        entries.append(entry)
    if eligible==0:
        rr.put(directory/'NO_ELIGIBLE_RECORDS.json',dict(schema='production90-empty-retained-set/1',
            source_entries=entries,scientific_accuracy_measured=False,
            no_superconductivity_claimed=False,full_paper_recall_measured=False))
        return None
    path=directory/'FROZEN_SAMPLE.json'
    if path.exists():
        selected=json.loads(path.read_bytes())
        if selected['source_entries']!=entries:raise ValueError('completed_batch_population_changed')
    else:
        selected=freeze(entries,seed='production90-automatic-source-audit:'+rr.reference(directory/'BATCH.json')['sha256'])
        rr.put(path,selected)
    return path


async def database_counts(database_url,works=None):
    engine=create_async_engine(database_url)
    try:
        async with engine.connect() as db:
            total=(await db.execute(text("SELECT count(*) FROM material_claims WHERE extraction_metadata->'production_admission'->>'policy'='production90/1'"))).scalar_one()
            counts=dict((await db.execute(text("SELECT paper_id,count(*) FROM material_claims WHERE paper_id=ANY(:works) AND extraction_metadata->'production_admission'->>'policy'='production90/1' GROUP BY paper_id"),dict(works=works or []))).all())
        return dict(total=total,by_paper=counts)
    finally:await engine.dispose()


def reconcile_batch(root,campaign,directory,counts):
    """Incrementally update this batch; avoid full evidence exports every round."""
    directory=Path(directory);manifest=json.loads((directory/'BATCH.json').read_bytes())
    jobs={j['id']:j for j in queue_rows(root,manifest)}
    with sqlite3.connect(Path(root)/'corpus.sqlite3') as ledger:
        for held in manifest['preparation_holds']:
            ledger.execute('UPDATE papers SET state=?,last_receipt=? WHERE work_id=?',
                ('source_route_held',str(directory/'BATCH.json'),held['work_id']))
        for item in manifest['jobs']:
            job=jobs[item['job_id']];work=item['work_id'];folder=directory/work[6:].replace('/','_')
            packet=folder/'PACKET.json';candidates=None
            if packet.exists():candidates=len(json.loads(json.loads(packet.read_bytes())['raw_output'])['results'])
            count=counts['by_paper'].get(work,0)
            done=job['state'] in {'succeeded','quarantined'}
            state=('tc_pass_partial_ingested' if count else 'no_target_returned_unverified' if candidates==0
                else 'candidates_held' if candidates or job['state']=='quarantined'
                else job['state'] if job['state'] in {'queued','running'} else 'extraction_failed_or_uncertain')
            ledger.execute('UPDATE papers SET state=?,full_ner_done=?,retained_rows=?,last_receipt=? WHERE work_id=?',
                (state,int(done),count,job['result_path'] or str(directory/'BATCH.json'),work))
        report=dict(frozen_arxiv_works=ledger.execute('SELECT count(*) FROM papers').fetchone()[0],
            by_state=dict(ledger.execute('SELECT state,count(*) FROM papers GROUP BY state')),
            new_tc_text_passes=ledger.execute('SELECT sum(full_ner_done) FROM papers').fetchone()[0],
            canonical_records=counts['total'],updated_at=now(),full_corpus_complete=False,production_deployed=False,
            coverage_scope='Available-text explicit Tc passes; neither whole-paper coverage nor full-paper recall.')
        if ledger.execute('SELECT sum(retained_rows) FROM papers').fetchone()[0]!=counts['total']:
            raise ValueError('pipeline_canonical_ledger_count_mismatch')
    progress(Path(campaign)/'CORPUS_PROGRESS.json',report)
    return report


def finish_batch(root,campaign,directory,audit_root,database_url):
    directory=Path(directory);manifest=json.loads((directory/'BATCH.json').read_bytes())
    works=[j['work_id'] for j in manifest['jobs']];before=asyncio.run(database_counts(database_url,works))
    selection=freeze_batch(root,directory);quality=None;admissions=[]
    if selection:
        audit_dir=directory/'luna-audit';quality=audit_batch(selection,audit_dir,audit_root,root)
        if quality is None:raise ValueError('source_audit_round_incomplete')
        if quality['qualified']:
            admissions=asyncio.run(admit(selection,audit_dir/'SOURCE_AUDIT.json',audit_dir/'admission',database_url))
    after=asyncio.run(database_counts(database_url,works))
    corpus=reconcile_batch(root,campaign,directory,after)
    result=dict(schema='production90-pipeline-batch/1',batch=directory.name,finished_at=now(),
        state='no_eligible_candidates' if selection is None else 'admission_processed' if quality['qualified'] else 'scientific_batch_held',
        quality=quality,admissions=admissions,claims_before=before['total'],claims_after=after['total'],
        new_claims=after['total']-before['total'],corpus=corpus,production_deployed=False)
    rr.put(directory/('PIPELINE_RESULT-'+str(time.time_ns())+'.json'),result)
    if any(r.get('status')=='committed_verification_incomplete' for r in admissions):
        raise ValueError('committed_database_verification_incomplete')
    if admissions and all(r.get('status')=='held' for r in admissions):
        raise ValueError('all_canonical_admissions_failed')
    return result


def source_batch(args,directory,pipeline_status):
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'NER_SOURCES.json'
    # A manually started acquisition may already own this immutable cohort.
    # Join its actual process lock before deciding whether another child is
    # needed. After a crashed producer, the source runner resumes its receipts.
    with (directory/'.lock').open('a') as producer:
        try:fcntl.flock(producer,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError:
            progress(pipeline_status,dict(state='waiting_existing_source_acquisition',
                source_batch=directory.name,owner_pid=os.getpid(),at=now()))
            fcntl.flock(producer,fcntl.LOCK_SH)
        if path.exists():return json.loads(path.read_bytes())
    command=[str(args.source_python),'scripts/materials_ner_tc_sources.py','--plan',str(args.plan),
        '--queue-root',str(args.root),'--directory',str(directory),'--cache',str(args.root/'source-cache'),
        '--limit','60','--ssh-host',args.ssh_host]
    with (directory/'PIPELINE_SOURCE.log').open('ab') as log:
        child=subprocess.Popen(command,stdout=log,stderr=log,cwd=SCRIPT_DIRECTORY.parent)
        progress(pipeline_status,dict(state='source_acquisition',source_batch=directory.name,
            owner_pid=os.getpid(),child_pid=child.pid,started_at=now()))
        code=child.wait()
    if code or not path.exists():raise ValueError('source_process_failed_or_incomplete')
    return json.loads(path.read_bytes())


def prefetch_source(args,directory,status):
    """Prepare one following cohort without using any model-worker slots."""
    try:
        sources=source_batch(args,directory,status)
        progress(status,dict(state='source_prefetch_ready',source_batch=directory.name,
            sources=len(sources),owner_pid=os.getpid(),at=now()))
        return sources
    except Exception as exc:
        progress(status,dict(state='source_prefetch_failed',source_batch=directory.name,
            error_class=type(exc).__name__,error=str(exc)[:500],at=now()))
        raise


def run(args):
    args.directory.mkdir(parents=True,exist_ok=True)
    with (args.root/'.production90-pipeline.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('production90_pipeline_already_running') from None
        manifest=args.directory/'PLAN.json';status=args.directory/'STATUS.json'
        config=dict(schema='production90-pipeline-plan/1',source_plan=rr.reference(args.plan),
            root=str(args.root),campaign=str(args.campaign),audit_root=str(args.audit_root),
            source_python=str(args.source_python),ssh_host=args.ssh_host,
            source_start=args.source_start,batch_start=args.batch_start,max_batches=args.max_batches,
            prefetch_next_source=getattr(args,'prefetch_next_source',False),
            database_url_sha256=hashlib.sha256(args.database_url.encode()).hexdigest(),
            max_concurrent_model_calls=2,max_provider_jobs_per_round=60,max_provider_round_seconds=1800,
            stage_sources=[rr.reference(SCRIPT_DIRECTORY/p) for p in STAGE_SCRIPTS]+
                [rr.reference(Path(p)) for p in [core_tc.__file__,core_tc_audit.__file__]],
            deployment_enabled=False)
        if manifest.exists():
            if json.loads(manifest.read_bytes())!=config:raise ValueError('pipeline_configuration_changed')
        else:rr.put(manifest,config)
        results=[];prefetched=None;terminal=None
        try:
            with ThreadPoolExecutor(max_workers=1,thread_name_prefix='source-prefetch') as pool:
                try:
                    for offset in range(args.max_batches):
                        for pin in config['stage_sources']:rr.checked(pin)
                        if (args.directory/'STOP_AFTER_BATCH').exists():
                            terminal='stopped_at_batch_boundary';break
                        source_dir=args.campaign/f'source-batch-{args.source_start+offset:03}'
                        batch_dir=args.campaign/f'batch-{args.batch_start+offset:03}'
                        result_path=args.directory/f'BATCH_{offset:03}.json'
                        if result_path.exists():
                            previous=json.loads(result_path.read_bytes())
                            for pin in previous['completion_evidence']:rr.checked(pin)
                            results.append(previous);continue
                        if prefetched is not None:
                            expected,future=prefetched
                            if expected!=source_dir:raise ValueError('source_prefetch_order_changed')
                            progress(status,dict(state='joining_source_prefetch',source_batch=source_dir.name,
                                owner_pid=os.getpid(),at=now()))
                            sources=future.result();prefetched=None
                        else:sources=source_batch(args,source_dir,status)
                        if not sources:
                            cohort=json.loads((source_dir/'COHORT.json').read_bytes())
                            if not cohort['papers']:
                                terminal='queued_source_scope_exhausted';break
                        if config['prefetch_next_source'] and offset+1<args.max_batches and not (args.directory/'STOP_AFTER_BATCH').exists():
                            next_dir=args.campaign/f'source-batch-{args.source_start+offset+1:03}'
                            prefetched=(next_dir,pool.submit(prefetch_source,args,next_dir,
                                args.directory/f'PREFETCH_{offset+1:03}.json'))
                        progress(status,dict(state='extracting',batch=batch_dir.name,owner_pid=os.getpid(),at=now()))
                        extract_batch(args.root,batch_dir,sources,only_new_papers=True)
                        progress(status,dict(state='source_audit_and_admission',batch=batch_dir.name,
                            owner_pid=os.getpid(),at=now()))
                        result=finish_batch(args.root,args.campaign,batch_dir,args.audit_root,args.database_url)
                        evidence=[rr.reference(batch_dir/'BATCH.json')]
                        for name in ['FROZEN_SAMPLE.json','NO_ELIGIBLE_RECORDS.json','luna-audit/SOURCE_AUDIT.json',
                            'luna-audit/QUALITY_REPORT.json','luna-audit/admission/DATABASE_READBACK.json']:
                            if (batch_dir/name).exists():evidence.append(rr.reference(batch_dir/name))
                        result['completion_evidence']=evidence;rr.put(result_path,result);results.append(result)
                        print(json.dumps(dict(batch=result['batch'],state=result['state'],new_claims=result['new_claims'],
                            total_claims=result['claims_after'])),flush=True)
                finally:
                    # Finish the one bounded download before reporting a terminal
                    # pipeline state. It never dispatches another model round.
                    if prefetched is not None and not prefetched[1].done():
                        progress(status,dict(state='finishing_source_prefetch',source_batch=prefetched[0].name,
                            owner_pid=os.getpid(),at=now(),completed=results))
            progress(status,dict(state=terminal or 'bounded_run_finished',at=now(),completed=results,full_corpus_complete=False))
        except Exception as exc:
            progress(status,dict(state='stopped_for_review',at=now(),error_class=type(exc).__name__,
                error=str(exc)[:500],completed=results,full_corpus_complete=False))
            raise


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['root','campaign','directory','audit-root','plan']:
        p.add_argument('--'+name,required=True,type=lambda v:Path(v).resolve())
    p.add_argument('--source-python',required=True,type=executable_path)
    for name in ['source-start','batch-start','max-batches']:p.add_argument('--'+name,required=True,type=int)
    p.add_argument('--database-url',required=True);p.add_argument('--ssh-host',default='jzis-vps2')
    p.add_argument('--prefetch-next-source',action='store_true',
        help='Prepare one following source batch concurrently with extraction and audit; model concurrency stays at two.')
    a=p.parse_args()
    if min(a.source_start,a.batch_start,a.max_batches)<1:raise ValueError('positive_pipeline_bounds_required')
    run(a)
