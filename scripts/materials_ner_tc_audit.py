"""Run a frozen Tc source audit with Luna, retaining every sampled outcome."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

from ingestion.materials_ner import core_tc_audit as stage, reviewed_reader as rr
from ingestion.materials_ner.store import Store
from materials_ner_tc_intake import checked_projection, quality, source_provenance
from materials_ner_tc_round import provider_round


def unavailable(selection,run_id,reason):
    """An unavailable model check is indeterminate, never a passing verdict."""
    entry=next(e for e in selection['source_entries']
        if json.loads(rr.checked(e['projection']).read_bytes())['run_id']==run_id)
    packet,p=checked_projection(entry);pre=json.loads(source_provenance(packet)['preflight_json'])
    blocks={b['id']:b for b in packet['bundle']['blocks']};rows=[]
    for row in selection['records']:
        if row['run_id']!=run_id:continue
        record=next(r for r in p['records'] if r['result_id']==row['result_id'])
        witnesses=record['graph']['results'][0]['evidence']
        q=next(e for e in witnesses if e['field']=='/quantity')
        evidence=dict(original_source=pre['bundle'],block_id=q['block_id'],start_char=q['start_char'],
            end_char=q['end_char'],quote=blocks[q['block_id']]['text'][q['start_char']:q['end_char']])
        rows.append({**row,'verdict':'indeterminate',
            'rationale':'The source-check job did not yield a valid completed review: '+reason+
                '. The attached original candidate context is not an endorsement of this result.',
            'source_evidence':[evidence],'review_completed':False,
            'verdict_authorship':'deterministic_unavailable_review_classification'})
    return rows


def run(selection_path,directory,audit_root,ner_root):
    with provider_round(ner_root):
        return run_locked(selection_path,directory,audit_root,ner_root)


def run_locked(selection_path,directory,audit_root,ner_root):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    # Extraction and auditing share the two-call budget. Do not launch another
    # pair while an extraction round still has queued or running work.
    with sqlite3.connect(Path(ner_root)/'queue.sqlite3') as db:
        if db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]:
            raise ValueError('finish_active_ner_round_before_source_audit')
    selection_path=Path(selection_path).resolve();selection=json.loads(selection_path.read_bytes())
    run_ids=sorted({r['run_id'] for r in selection['records']})
    if not 1<=len(run_ids)<=60:raise ValueError('audit_round_requires_1_to_60_source_runs')
    store=Store(Path(audit_root).resolve());manifest=directory/'BATCH.json'
    if manifest.exists():
        batch=json.loads(manifest.read_bytes())
        if batch['selection']!=rr.reference(selection_path):raise ValueError('audit_selection_changed')
    else:
        jobs=[];holds=[]
        for run_id in run_ids:
            folder=directory/run_id;folder.mkdir(exist_ok=True)
            request=dict(schema=stage.INPUT_SCHEMA,selection=rr.reference(selection_path),run_id=run_id)
            rr.put(folder/'REQUEST.json',request)
            try:
                job_id=stage.enqueue(store,folder/'REQUEST.json')
                jobs.append(dict(run_id=run_id,job_id=job_id))
            except ValueError as exc:
                holds.append(dict(run_id=run_id,error=str(exc)))
        batch=dict(schema='materials-production90-source-audit-batch/1',selection=rr.reference(selection_path),
            created_at=datetime.now(timezone.utc).isoformat(),jobs=jobs,preparation_holds=holds,
            max_concurrency=2,max_jobs=60,max_seconds=1800,automatic_retries=0)
        rr.put(manifest,batch)
    started=time.monotonic();outcomes=[]
    def process(job):
        if time.monotonic()-started>1800:return dict(**job,state='queued_next_round')
        result=stage.run(store,job['job_id'])
        rr.put(directory/job['run_id']/'RESULT.json',result)
        return dict(**job,state=result['state'],source_audit=result.get('source_audit'),
            error_code=result.get('error_code'),usage=result['usage'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(process,j) for j in batch['jobs']]):
            outcome=f.result();outcomes.append(outcome);print(json.dumps(outcome),flush=True)
    if any(r['state']=='queued_next_round' for r in outcomes):
        rr.put(directory/('ROUND-'+str(time.time_ns())+'.json'),dict(outcomes=outcomes,complete=False))
        return None
    rows=[]
    for hold in batch['preparation_holds']:rows.extend(unavailable(selection,hold['run_id'],hold['error']))
    for item in outcomes:
        if item.get('source_audit'):
            result=json.loads(rr.checked(item['source_audit']).read_bytes())
            if result['selection_sha256']!=selection['selection_sha256']:raise ValueError('audit_response_selection_changed')
            rows.extend({**r,'source_audit_job_id':item['job_id'],'source_audit_receipt':item['source_audit']}
                for r in result['records'])
        else:rows.extend(unavailable(selection,item['run_id'],item.get('error_code') or item['state']))
    rows.sort(key=lambda r:(r['work_id'],r['run_id'],r['result_id']))
    audit=dict(schema='materials-source-audit/1',selection_sha256=selection['selection_sha256'],
        reviewer_kind='model',reviewer_identity='gpt-6-luna in separate original-source check invocations',
        reviewer_model='gpt-6-luna',reviewer_reasoning='high',independent_expert_review=False,
        created_at=batch['created_at'],candidate_verdicts_in_model_input=False,records=rows)
    report=quality(selection,audit)
    rr.put(directory/'SOURCE_AUDIT.json',audit);rr.put(directory/'QUALITY_REPORT.json',report)
    print(json.dumps(dict(quality=report,review_completed=sum(r['review_completed'] for r in rows))),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['selection','directory','audit-root','ner-root']:p.add_argument('--'+name,required=True)
    p.add_argument('--database-url',help='Admit qualifying records after the source audit finishes.')
    a=p.parse_args();report=run(a.selection,a.directory,a.audit_root,a.ner_root)
    if report and report['qualified'] and a.database_url:
        from materials_ner_tc_admit import admit
        asyncio.run(admit(a.selection,Path(a.directory)/'SOURCE_AUDIT.json',
            Path(a.directory)/'admission',a.database_url))
