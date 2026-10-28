"""Prospective 500-result windows and independent source-checked admission.

Extraction batches remain bounded to 60 papers and up to three calls. Audit windows close
at a predeclared completed-batch boundary, never in response to audit scores.
"""
import argparse
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from ingestion.materials_ner import core_tc, core_tc_audit, reviewed_reader as rr
from materials_ner_tc_pipeline import (SCRIPT_DIRECTORY, STAGE_SCRIPTS, now, progress,
    executable_path, source_batch, prefetch_source, queue_rows, database_counts, reconcile_batch)
from materials_ner_tc_batch import run as extract_batch
from materials_ner_tc_audit import run as audit_batch
from materials_ner_tc_admit import admit
from materials_ner_tc_intake import checked_projection, freeze
from materials_ner_tc_sampling import RANDOM_METHOD, BATCH_ROUTE, RECORD_ROUTE

VERSION='production90-prospective-pipeline/4'
TARGET=500


def window_due(members,*,tail=False):
    count=sum(m['eligible_results'] for m in members)
    return count>0 and (count>=TARGET or tail)


def member_entries(members):
    entries=[];seen=set()
    for member in members:
        for entry in member['source_entries']:
            key=(entry['packet']['sha256'],entry['projection']['sha256'])
            if key in seen:raise ValueError('duplicate_window_source_entry')
            seen.add(key);entries.append(entry)
    return entries


def register_window(args,index,first_batch):
    directory=args.directory/'windows'/f'window-{index:03}'
    directory.mkdir(parents=True,exist_ok=True)
    policy=dict(schema='production90-prospective-window-plan/1',index=index,first_batch=first_batch,
        pipeline_plan=rr.reference(args.directory/'PLAN.json'),candidate_target=TARGET,
        boundary='First completed extraction batch reaching 500 eligible results; final phase tail may be smaller.',
        method=RANDOM_METHOD,sample_size=50,seed=hashlib.sha256(
            ('production90-500-window:'+rr.reference(args.directory/'PLAN.json')['sha256']+':'+str(index)).encode()).hexdigest(),
        threshold=0.9,indeterminate_counts_as_correct=False,independent_source_check_route=True,
        no_score_dependent_window_regrouping=True)
    rr.put(directory/'PLAN.json',policy)
    return directory,policy


def extraction_receipt(args,directory):
    manifest=json.loads((directory/'BATCH.json').read_bytes());jobs=queue_rows(args.root,manifest)
    if any(j['state'] in {'queued','running'} for j in jobs):raise ValueError('ner_round_incomplete')
    deferred=[];deferral_evidence=[]
    if any(j['state'] in {'blocked','failed'} for j in jobs):
        from materials_ner_tc_capacity import checked_deferrals
        deferred=checked_deferrals(args.root,directory)
        allowed={r['job_id'] for r in deferred}
        if any(j['id'] not in allowed for j in jobs if j['state'] in {'blocked','failed'}):
            raise ValueError('provider_failure_requires_attempt_reconciliation_without_retry')
        recovery=directory/'CAPACITY_CONTINUATION'/'RESULT.json'
        if not recovery.exists():raise ValueError('capacity_continuation_receipt_required')
        receipt=json.loads(recovery.read_bytes())
        for pin in receipt['completion_evidence']:rr.checked(pin)
        deferral_evidence=[rr.reference(recovery)]
    entries=[];projection_pins=[];raw=eligible=0;holds=Counter()
    for job in manifest['jobs']:
        folder=directory/job['work_id'][6:].replace('/','_')
        path=folder/('PROJECTION_CORE.json' if job.get('profile')=='core' else 'PROJECTION_V2.json')
        if not path.exists():continue
        entry=dict(packet=rr.reference(folder/'PACKET.json'),projection=rr.reference(path))
        _,projection=checked_projection(entry);projection_pins.append(entry['projection'])
        n=sum(r['status']=='eligible_for_source_audit' for r in projection['records'])
        raw+=projection['raw_results'];eligible+=n
        for row in projection['records']:
            if row['status']=='held':holds.update(row['holds'])
        if n:entries.append(entry)
    counts=asyncio.run(database_counts(args.database_url,[j['work_id'] for j in manifest['jobs']]))
    corpus=reconcile_batch(args.root,args.campaign,directory,counts)
    return dict(schema='production90-extracted-batch/1',batch=directory.name,at=now(),
        completed_papers=sum(j['state'] in {'succeeded','quarantined'} for j in jobs),
        deferred_provider_failures=deferred,preparation_holds=manifest['preparation_holds'],
        raw_results=raw,eligible_results=eligible,source_entries=entries,held_reasons=dict(holds),
        canonical_admission_state='awaiting_prospective_quality_window' if eligible else 'no_eligible_results',
        canonical_records=counts['total'],corpus=corpus,
        completion_evidence=[rr.reference(directory/'BATCH.json'),*projection_pins,*deferral_evidence],
        full_paper_recall_measured=False,production_deployed=False)


def reconcile_window(args,members):
    works=[]
    for member in members:
        manifest=json.loads((args.campaign/member['batch']/'BATCH.json').read_bytes())
        works.extend(j['work_id'] for j in manifest['jobs'])
    counts=asyncio.run(database_counts(args.database_url,sorted(set(works))))
    # Update every affected paper in one ledger transaction before comparing the
    # ledger total with the canonical database total.
    with sqlite3.connect(args.root/'corpus.sqlite3') as ledger:
        for work in set(works):
            count=counts['by_paper'].get(work,0)
            ledger.execute("UPDATE papers SET retained_rows=?,state=CASE WHEN ?>0 AND full_ner_done=1 "
                "THEN 'tc_pass_partial_ingested' ELSE state END WHERE work_id=?",(count,count,work))
        if ledger.execute('SELECT sum(retained_rows) FROM papers').fetchone()[0]!=counts['total']:
            raise ValueError('window_canonical_ledger_count_mismatch')
    corpus=reconcile_batch(args.root,args.campaign,args.campaign/members[-1]['batch'],counts)
    return counts,corpus


def finish_window(args,directory,policy,members):
    membership=dict(schema='production90-prospective-window-members/1',plan=rr.reference(directory/'PLAN.json'),
        batches=[m['batch'] for m in members],eligible_results=sum(m['eligible_results'] for m in members),
        extraction_receipts=[rr.reference(args.directory/f"BATCH_{int(m['batch'].split('-')[1])-args.batch_start:03}.json") for m in members])
    rr.put(directory/'MEMBERS.json',membership)
    selected=directory/'FROZEN_SAMPLE.json'
    if not selected.exists():
        rr.put(selected,freeze(member_entries(members),seed=policy['seed'],sampling_method=RANDOM_METHOD))
    selection=json.loads(selected.read_bytes())
    if selection['source_entries']!=member_entries(members):raise ValueError('prospective_window_population_changed')
    if selection['eligible_results']!=membership['eligible_results']:raise ValueError('prospective_window_count_changed')
    baseline=directory/'ADMISSION_BASELINE.json'
    if not baseline.exists():rr.put(baseline,asyncio.run(database_counts(args.database_url)))
    before=json.loads(baseline.read_bytes())
    progress(args.directory/'STATUS.json',dict(state='source_audit_and_admission',window=directory.name,
        owner_pid=os.getpid(),at=now(),eligible_results=selection['eligible_results'],sample_size=len(selection['records'])))
    quality=audit_batch(selected,directory/'luna-audit',args.audit_root,args.root)
    if quality is None:raise ValueError('source_audit_round_incomplete')
    route=BATCH_ROUTE if quality['qualified'] else RECORD_ROUTE;admissions=[]
    if quality['qualified'] or quality['correct']:
        admissions=asyncio.run(admit(selected,directory/'luna-audit/SOURCE_AUDIT.json',
            directory/'admission',args.database_url,admission_route=route))
    if any(r.get('status')=='committed_verification_incomplete' for r in admissions):
        raise ValueError('committed_database_verification_incomplete')
    after,corpus=reconcile_window(args,members)
    result=dict(schema='production90-prospective-window-result/1',window=directory.name,batch=directory.name,
        at=now(),state='admission_processed' if admissions else 'scientific_window_held',
        admission_route=route,quality=quality,admissions=admissions,
        claims_before=before['total'],claims_after=after['total'],new_claims=after['total']-before['total'],
        eligible_results=selection['eligible_results'],sample_size=len(selection['records']),
        failed_window_unsampled_records_held=not quality['qualified'],corpus=corpus,production_deployed=False)
    files=[directory/'PLAN.json',directory/'MEMBERS.json',selected,directory/'luna-audit/SOURCE_AUDIT.json',
        directory/'luna-audit/QUALITY_REPORT.json']
    if (directory/'admission/DATABASE_READBACK.json').exists():files.append(directory/'admission/DATABASE_READBACK.json')
    result['completion_evidence']=[rr.reference(p) for p in files]
    rr.put(directory/'RESULT.json',result)
    print(json.dumps(dict(window=directory.name,route=route,eligible_results=selection['eligible_results'],
        sample_size=len(selection['records']),observed_precision=quality['observed_precision'],
        new_claims=result['new_claims'],total_claims=after['total'])),flush=True)
    return result


def run(args):
    workers=getattr(args,'max_concurrency',2)
    if type(workers) is not int or not 1<=workers<=3:raise ValueError('batch_concurrency_out_of_bounds')
    args.directory.mkdir(parents=True,exist_ok=True)
    with (args.root/'.production90-pipeline.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        files=[SCRIPT_DIRECTORY/p for p in STAGE_SCRIPTS]
        files += [SCRIPT_DIRECTORY/'materials_ner_tc_capacity.py',Path(__file__),SCRIPT_DIRECTORY/'materials_ner_production90.py',Path(core_tc.__file__),Path(core_tc_audit.__file__)]
        files += [Path(rr.__file__),Path(rr.__file__).with_name('source_metadata.py')]
        plan=dict(schema=VERSION,source_plan=rr.reference(args.plan),goal=rr.reference(args.goal),
            root=str(args.root),campaign=str(args.campaign),audit_root=str(args.audit_root),
            source_python=str(args.source_python),ssh_host=args.ssh_host,source_start=args.source_start,
            batch_start=args.batch_start,max_batches=args.max_batches,candidate_window_target=TARGET,
            sample_size=50,sampling_method=RANDOM_METHOD,threshold=0.9,individual_source_check_route=True,
            boundary='completed_extraction_batch',stage_sources=[rr.reference(p) for p in files],
            database_url_sha256=hashlib.sha256(args.database_url.encode()).hexdigest(),
            max_concurrent_model_calls=workers,max_provider_jobs_per_round=60,max_provider_round_seconds=1800,
            deployment_enabled=False)
        rr.put(args.directory/'PLAN.json',plan)
        closed=set();window_index=1
        for path in sorted((args.directory/'windows').glob('window-*/RESULT.json')):
            receipt=json.loads(path.read_bytes())
            for pin in receipt['completion_evidence']:rr.checked(pin)
            membership=json.loads((path.parent/'MEMBERS.json').read_bytes())
            if closed.intersection(membership['batches']):raise ValueError('duplicate_closed_window_batch')
            closed.update(membership['batches']);window_index+=1
        members=[];window_directory=None;window_policy=None;prefetched=None;terminal='bounded_phase_complete'
        try:
            with ThreadPoolExecutor(max_workers=1,thread_name_prefix='source-prefetch') as pool:
                try:
                    for offset in range(args.max_batches):
                        for pin in plan['stage_sources']:rr.checked(pin)
                        batch_dir=args.campaign/f'batch-{args.batch_start+offset:03}'
                        if batch_dir.name in closed:continue
                        if (args.directory/'STOP_AFTER_BATCH').exists():
                            terminal='stopped_at_batch_boundary';break
                        if window_directory is None:
                            window_directory,window_policy=register_window(args,window_index,batch_dir.name)
                        path=args.directory/f'BATCH_{offset:03}.json'
                        if path.exists():
                            member=json.loads(path.read_bytes())
                            for pin in member['completion_evidence']:rr.checked(pin)
                        else:
                            source_dir=args.campaign/f'source-batch-{args.source_start+offset:03}'
                            if prefetched is not None:
                                expected,future=prefetched
                                if expected!=source_dir:raise ValueError('source_prefetch_order_changed')
                                sources=future.result();prefetched=None
                            else:sources=source_batch(args,source_dir,args.directory/'STATUS.json')
                            if not sources and not json.loads((source_dir/'COHORT.json').read_bytes())['papers']:
                                terminal='queued_source_scope_exhausted';break
                            if offset+1<args.max_batches:
                                next_dir=args.campaign/f'source-batch-{args.source_start+offset+1:03}'
                                prefetched=(next_dir,pool.submit(prefetch_source,args,next_dir,args.directory/f'PREFETCH_{offset+1:03}.json'))
                            progress(args.directory/'STATUS.json',dict(state='extracting',batch=batch_dir.name,
                                owner_pid=os.getpid(),at=now(),window=window_directory.name,
                                pending_eligible_results=sum(m['eligible_results'] for m in members)))
                            extract_batch(args.root,batch_dir,sources,only_new_papers=True,max_concurrency=workers)
                            manifest=json.loads((batch_dir/'BATCH.json').read_bytes())
                            if any(j['state'] in {'blocked','failed'} for j in queue_rows(args.root,manifest)):
                                from materials_ner_tc_capacity import continue_pending
                                continue_pending(args.root,batch_dir)
                            member=extraction_receipt(args,batch_dir);rr.put(path,member)
                            print(json.dumps(dict(batch=member['batch'],completed_papers=member['completed_papers'],
                                eligible_results=member['eligible_results'],canonical_records=member['canonical_records'])),flush=True)
                        members.append(member)
                        progress(args.directory/'OPEN_WINDOW.json',dict(window=window_directory.name,
                            batches=[m['batch'] for m in members],eligible_results=sum(m['eligible_results'] for m in members),at=now()))
                        if window_due(members):
                            finish_window(args,window_directory,window_policy,members)
                            closed.update(m['batch'] for m in members)
                            members=[];window_index+=1;window_directory=window_policy=None
                    if members and window_due(members,tail=True) and terminal!='stopped_at_batch_boundary':
                        finish_window(args,window_directory,window_policy,members)
                        members=[]
                finally:
                    if prefetched is not None and not prefetched[1].done():
                        progress(args.directory/'STATUS.json',dict(state='finishing_source_prefetch',
                            owner_pid=os.getpid(),at=now(),source_batch=prefetched[0].name))
            progress(args.directory/'STATUS.json',dict(state=terminal,at=now(),full_corpus_complete=False,
                production_deployed=False,pending_eligible_results=sum(m['eligible_results'] for m in members)))
        except Exception as exc:
            progress(args.directory/'STATUS.json',dict(state='stopped_for_review',at=now(),
                error_class=type(exc).__name__,error=str(exc)[:1000],full_corpus_complete=False,production_deployed=False))
            raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['root','campaign','directory','audit-root','plan','goal']:
        p.add_argument('--'+name,required=True,type=lambda v:Path(v).resolve())
    p.add_argument('--source-python',required=True,type=executable_path)
    for name in ['source-start','batch-start','max-batches']:p.add_argument('--'+name,required=True,type=int)
    p.add_argument('--database-url',required=True);p.add_argument('--ssh-host',default='jzis-vps2')
    p.add_argument('--max-concurrency',type=int,choices=[1,2,3],default=2)
    a=p.parse_args()
    if min(a.source_start,a.batch_start,a.max_batches)<1:raise ValueError('positive_pipeline_bounds_required')
    run(a)
