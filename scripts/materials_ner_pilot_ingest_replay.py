#!/usr/bin/env python3
"""Replay terminal real attempts into a private proposal DB, including failures.

This checks proposal import and SQLite restoration only. It neither migrates
canonical PostgreSQL data nor qualifies a scientific/ML dataset release.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"ingestion"))
from ingestion.materials_ner.contract import canonical,digest
from ingestion.materials_ner.proposals import ProposalDatabase,import_packet,verify_packet,TABLES
from ingestion.materials_ner.sources import private_write,sha
from ingestion.materials_ner.store import Store


def replay(root,labels,output):
    if output.exists():
        raise ValueError("Use a new output directory for the private import replay")
    output.mkdir(parents=True,mode=0o700)
    store=Store(root);database=ProposalDatabase(output/"database")
    imported=[];seen=set()
    for label in labels:
        state=json.loads((root/"runs"/label/"state.json").read_bytes())
        if state.get("state")!="checkpointed":
            raise ValueError("Only terminal/checkpointed runs may be replayed")
        for job in state["jobs"]:
            if job["id"] in seen:
                raise ValueError("Requested runs repeat an identical extraction job")
            seen.add(job["id"])
            packet=import_packet(store,job["id"]);verify_packet(packet)
            first=database.ingest(packet);second=database.ingest(packet)
            if not first["inserted"] or second["inserted"]:
                raise ValueError("Idempotent insertion check failed")
            private_write(output/"packets"/(packet["run_id"]+".json"),canonical(packet).encode())
            imported.append({"label":label,"work_id":job["work_id"],"job_id":job["id"],
                "run_id":packet["run_id"],"packet_hash":packet["packet_hash"],
                "worker_state":packet["receipt"]["state"],"candidate_results":len(packet["rows"]["results"]),
                "idempotent_second_import":not second["inserted"]})
    with database.connect() as connection:
        foreign_keys=[list(r) for r in connection.execute("PRAGMA foreign_key_check")]
        integrity=[r[0] for r in connection.execute("PRAGMA integrity_check")]
        if foreign_keys or integrity!=["ok"]:
            raise ValueError("Private database integrity failed")
        snapshot=output/"restored-proposals.sqlite3"
        with sqlite3.connect(snapshot) as restored:
            connection.backup(restored)
    with sqlite3.connect(snapshot) as restored:
        restored_counts={t:restored.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
        restored_fks=restored.execute("PRAGMA foreign_key_check").fetchall()
        for (payload,) in restored.execute("SELECT payload FROM runs"):
            packet=json.loads(payload);verify_packet(packet)
            saved=json.loads((output/"packets"/(packet["run_id"]+".json")).read_bytes())
            if digest(saved)!=digest(packet):
                raise ValueError("Restored packet differs from immutable export")
        forbidden=restored.execute("SELECT count(*) FROM runs WHERE scientific_acceptance!=0 OR ml_training_eligible!=0").fetchone()[0]
    summary=database.summary()
    if restored_counts!=summary["tables"] or restored_fks or forbidden:
        raise ValueError("Restore count, ownership or qualification flag mismatch")
    manifest={"schema":"materials-private-proposal-import-replay/1", "created_at":datetime.now(timezone.utc).isoformat(),
        "script_sha256":sha(Path(__file__).read_bytes()),"runs":imported,"summary":summary,
        "source_run_root":str(root),"restored_database":str(snapshot),"restored_counts":restored_counts,
        "foreign_key_violations":0,"integrity_check":"ok","restored_packet_hashes_verified":True,
        "qualified_rows":0,"scientific_acceptance":False,"ml_training_eligible":False,
        "canonical_postgres_migration_executed":False,"production_writes":False,
        "restore_scope":"Private proposal database plus packets; not canonical dataset-release dependency closure"}
    private_write(output/"manifest.json",canonical(manifest).encode())
    private_write(output/"replay-script.py",Path(__file__).read_bytes())
    return manifest


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--labels",nargs="+",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    print(canonical(replay(args.root,args.labels,args.output)))
