#!/usr/bin/env python3
"""Audit frozen staged packets without editing a queue or scientific database."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ingestion'))
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.occurrence_audit import audit_packet, POLICY
from ingestion.materials_ner.sources import sha


def run(paths,out):
    if out.exists():raise ValueError('Use a new audit path; existing reports are immutable')
    reports=[]
    for path in paths:
        raw=path.read_bytes();report=audit_packet(json.loads(raw))
        reports.append(dict(packet_path=str(path.resolve()),packet_file_sha256=sha(raw),report=report))
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x') as handle:
        handle.write(canonical(dict(schema='materials-occurrence-audit-report/1',policy=POLICY,packets=reports))+'\n')
    return dict(path=str(out.resolve()),packets=len(reports),scientific_acceptance=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet',type=Path,action='append',required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();print(canonical(run(args.packet,args.out)))
