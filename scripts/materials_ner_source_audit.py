#!/usr/bin/env python3
"""One source-only Luna audit of a frozen proposal; prior results are hidden."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ingestion'))
from ingestion.materials_ner.contract import canonical,digest
from ingestion.materials_ner.proposals import verify_packet
from ingestion.materials_ner.sources import Bundle,save_bundle,private_write
from ingestion.materials_ner.source_audit_worker import configuration,run_one
from ingestion.materials_ner.store import Store


def run(root,packet_path,label,repair_receipt=None,local_context=False):
    destination=root/'runs'/label
    if destination.exists():raise ValueError('Use a fresh audit label; retain previous output')
    packet=json.loads(packet_path.read_bytes());verify_packet(packet)
    parent={k:packet[k] for k in ['run_id','receipt','raw_output']};bundle=Bundle.model_validate(packet['bundle'])
    bundle_hash,_=save_bundle(root,bundle);store=Store(root)
    repair_parent=None
    if repair_receipt is not None:
        prior=json.loads(repair_receipt.read_bytes())
        repair_parent={'run_id':digest(prior),'receipt':prior,'raw_output':repair_receipt.with_name('output.json').read_text()}
    config=configuration(parent,repair_parent=repair_parent,local_context=local_context,
        timeout_seconds=300,max_input_tokens=60000,max_output_tokens=16000)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=config,max_attempts=1)
    existing=next(x for x in store.results() if x['id']==job)
    if existing['state']!='queued':raise ValueError('Inspect the existing audit receipt or live handle; do not relaunch')
    state={'schema':'materials-source-audit-run/1','started_at':datetime.now(timezone.utc).isoformat(),
        'job_id':job,'baseline_run_id':parent['run_id'],'baseline_packet_path':str(packet_path),
        'bundle_sha256':bundle_hash,'state':'running','scientific_acceptance':False,'independent_gold':False}
    private_write(destination/'state.json',canonical(state).encode())
    outcome=run_one(store,job,parent,bundle,repair_parent=repair_parent)
    state.update(state='checkpointed',outcome=outcome);private_write(destination/'state.json',canonical(state).encode())
    print(canonical(outcome))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--baseline-packet',type=Path,required=True)
    parser.add_argument('--label',required=True);parser.add_argument('--repair-receipt',type=Path)
    parser.add_argument('--local-context',action='store_true');args=parser.parse_args()
    if not args.label.replace('-','').isalnum():parser.error('label must be alphanumeric with optional hyphens')
    run(args.root,args.baseline_packet,args.label,args.repair_receipt,args.local_context)
