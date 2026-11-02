"""Capacity/import rehearsal on an owned, network-isolated backup restore only.

This is not a production publisher and cannot activate a retrieval generation.
No DSN, existing production container, credentials or arbitrary SQL is accepted.
The restore receipt, immutable image, container/volume labels and network mode
must agree before any database connection. Default phase is read-only inspect.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pgvector_wire import projection_copy

SCHEMA = "sclib_pgvector_rehearsal"
TABLE = SCHEMA + ".vectors"
FIELDS = "vector_id,paper_id,content_sha256,vector_sha256,chunk_revision_sha256,embedding"
PURPOSE = "pgvector-production-backup-drill"


class Rehearsal:
    def __init__(self, args):
        self.args = args
        self.root = args.restore_report.resolve().parent
        self.receipt = json.loads(args.restore_report.read_text())
        if self.receipt.get("status") != "restored_and_readable":
            raise ValueError("A completed backup restore receipt is required")
        self.identifier = self.receipt["target"]["container_id"]
        if not re.fullmatch(r"[0-9a-f]{64}", self.identifier):
            raise ValueError("The restore receipt must identify an exact container")
        observed = json.loads(subprocess.check_output(["docker", "inspect", self.identifier]))
        if len(observed) != 1:
            raise ValueError("Restore container identity mismatch")
        c = observed[0]
        labels = c["Config"].get("Labels", {})
        volumes = [m["Name"] for m in c["Mounts"] if m["Type"] == "volume"]
        if (c["Id"] != self.identifier or c["Image"] != self.receipt["target"]["image"]
                or c["HostConfig"]["NetworkMode"] != "none"
                or labels.get("org.jzis.sclib.purpose") != PURPOSE
                or self.receipt["target"]["volume"] not in volumes
                or not c["State"]["Running"]):
            raise ValueError("Refusing a non-owned or network-connected database")
        v = json.loads(subprocess.check_output(["docker", "volume", "inspect", self.receipt["target"]["volume"]]))[0]
        if (v.get("Labels", {}).get("org.jzis.sclib.purpose") != PURPOSE
                or v["Labels"].get("org.jzis.sclib.run") != labels.get("org.jzis.sclib.run")):
            raise ValueError("Restore volume ownership mismatch")
        self.generation = str(UUID(args.source_generation))
        if not re.fullmatch(r"[0-9a-f]{64}", args.manifest):
            raise ValueError("An exact source manifest is required")
        self.source = self.json_sql(f"""SELECT json_build_object('generation_id',id,'manifest_sha256',manifest_sha256,
          'members',expected_member_count,'profile',profile,'root',sclib_corpus_root_v1(id))
          FROM index_generations WHERE id='{self.generation}'""")
        if (self.source["manifest_sha256"] != args.manifest or self.source["root"] != args.manifest
                or self.source["profile"]["model"] != "text-embedding-005"
                or self.source["profile"]["output_dimensionality"] != 768):
            raise ValueError("Restored source generation/profile/manifest mismatch")

    def sql(self, statement, *, payload=None):
        with (self.root / "pgvector-rehearsal-private.log").open("ab") as log:
            p = subprocess.run(["docker", "exec", "-i", self.identifier, "psql", "-X", "-A", "-t", "-q",
                "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "sclib_restore_drill", "-c", statement],
                input=payload, stdout=subprocess.PIPE, stderr=log)
        if p.returncode:
            raise RuntimeError("Rehearsal SQL failed; private log retained")
        return p.stdout

    def json_sql(self, statement):
        return json.loads(self.sql(statement))

    def event(self, phase, **data):
        value = {"at": datetime.now(timezone.utc).isoformat(), "phase": phase, **data}
        with (self.root / "pgvector-rehearsal.events.jsonl").open("a") as f:
            f.write(json.dumps(value) + "\n")
        print(json.dumps(value), flush=True)

    def budget(self):
        fs = os.statvfs(self.root)
        free = fs.f_bavail * fs.f_frsize / 2**30
        if free < 210:
            raise RuntimeError("Paused at APS reservation plus disk floor; no data was deleted")
        return free

    def initialize(self):
        self.sql(f"""CREATE SCHEMA IF NOT EXISTS {SCHEMA};
          CREATE TABLE IF NOT EXISTS {SCHEMA}.source (singleton boolean PRIMARY KEY CHECK(singleton),
            generation_id uuid NOT NULL, manifest text NOT NULL);
          INSERT INTO {SCHEMA}.source VALUES(true,'{self.generation}','{self.args.manifest}') ON CONFLICT DO NOTHING;
          DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM {SCHEMA}.source WHERE generation_id='{self.generation}'
              AND manifest='{self.args.manifest}') THEN RAISE EXCEPTION 'rehearsal_source_changed'; END IF; END $$;
          CREATE TABLE IF NOT EXISTS {TABLE} (vector_id text COLLATE "C" PRIMARY KEY,paper_id text NOT NULL,
            content_sha256 text NOT NULL,vector_sha256 text NOT NULL,chunk_revision_sha256 text NOT NULL,
            embedding vector(768) NOT NULL);
          CREATE TABLE IF NOT EXISTS {SCHEMA}.incoming (LIKE {TABLE} INCLUDING DEFAULTS);
        """)

    def import_vectors(self):
        self.initialize()
        cursor = self.json_sql(f"SELECT json_build_object('cursor',max(vector_id),'count',count(*)) FROM {TABLE}")
        last, count = cursor["cursor"] or "", cursor["count"]
        started = time.monotonic()
        while True:
            self.budget()
            if not re.fullmatch(r"[A-Za-z0-9_-]{0,120}", last):
                raise ValueError("Unexpected resume cursor")
            statement = f"""COPY (SELECT m.vector_id,m.paper_id,m.content_sha256,m.vector_sha256,
              m.chunk_revision_sha256,m.vector_bytes,COALESCE(
              m.content_sha256=encode(sha256(convert_to(m.snapshot_json->>'text','UTF8')),'hex')
              AND m.snapshot_sha256=sclib_index_hash_v1(jsonb_build_object('chunk',m.snapshot_json,'paper',m.paper_snapshot_json))
              AND m.chunk_revision_sha256=sclib_index_revision_hash_v1(to_jsonb(m))
              AND e.record_sha256=m.evidence_record_sha256 AND e.content_sha256=m.content_sha256
              AND e.record_sha256=sclib_rag_evidence_record_hash_v1(to_jsonb(e))
              AND r.record_sha256=m.receipt_record_sha256 AND r.vector_sha256=m.vector_sha256
              AND r.record_sha256=sclib_embedding_receipt_hash_v1(to_jsonb(r)),false)
              FROM (SELECT * FROM index_generation_members
                WHERE generation_id='{self.generation}' AND vector_id>'{last}'
                ORDER BY vector_id LIMIT 1000) m
              LEFT JOIN rag_evidence_revisions e ON e.id=m.evidence_revision_id
              LEFT JOIN embedding_completion_receipts r ON r.id=m.receipt_id
              ORDER BY m.vector_id COLLATE "C") TO STDOUT WITH(FORMAT binary)"""
            payload, inventory = projection_copy(self.sql(statement))
            if not inventory:
                break
            self.sql(f"TRUNCATE {SCHEMA}.incoming")
            self.sql(f"COPY {SCHEMA}.incoming({FIELDS}) FROM STDIN WITH(FORMAT binary)", payload=payload)
            self.sql(f"""BEGIN;
              DO $$ BEGIN IF EXISTS(SELECT 1 FROM {SCHEMA}.incoming n JOIN {TABLE} p USING(vector_id)
                WHERE to_jsonb(n) IS DISTINCT FROM to_jsonb(p)) THEN RAISE EXCEPTION 'replay_binding_mismatch'; END IF; END $$;
              INSERT INTO {TABLE} SELECT * FROM {SCHEMA}.incoming ON CONFLICT DO NOTHING;
              COMMIT;""")
            last = inventory[-1][0]
            count += len(inventory)
            if count % 25000 < len(inventory):
                self.event("import_progress", members=count, elapsed_seconds=round(time.monotonic()-started, 2), free_gib=self.budget())
        self.event("import_complete", members=count, expected=self.source["members"], elapsed_seconds=time.monotonic()-started)
        if count != self.source["members"]:
            raise ValueError("Incomplete projection inventory")

    def verify(self):
        # Enumerate every declared member and every projection row; verify the
        # database's binary vector readback, not just our inserted bytes/count.
        value = self.json_sql(f"""SELECT json_build_object('members',count(*),
          'missing',count(*) FILTER(WHERE p.vector_id IS NULL),
          'mismatched',count(*) FILTER(WHERE p.paper_id IS DISTINCT FROM m.paper_id
            OR p.content_sha256 IS DISTINCT FROM m.content_sha256 OR p.vector_sha256 IS DISTINCT FROM m.vector_sha256
            OR p.chunk_revision_sha256 IS DISTINCT FROM m.chunk_revision_sha256
            OR substring(vector_send(p.embedding) FROM 5) IS DISTINCT FROM m.vector_bytes),
          'extra',(SELECT count(*) FROM {TABLE} p WHERE NOT EXISTS(SELECT 1 FROM index_generation_members m
            WHERE m.generation_id='{self.generation}' AND m.vector_id=p.vector_id)),
          'table_bytes',pg_table_size('{TABLE}'),'total_bytes',pg_total_relation_size('{TABLE}'))
          FROM index_generation_members m LEFT JOIN {TABLE} p USING(vector_id)
          WHERE m.generation_id='{self.generation}'""")
        value.update(source_generation=self.generation, source_manifest=self.args.manifest,
                     at=datetime.now(timezone.utc).isoformat())
        if value["members"] != self.source["members"] or any(value[k] for k in ("missing", "mismatched", "extra")):
            self.event("verification_failed", **value)
            raise ValueError("Full projection readback did not match the declared source")
        (self.root / "pgvector-full-readback.json").write_text(json.dumps(value, indent=2) + "\n")
        self.event("full_readback_verified", **value)

    def build(self):
        self.verify()
        free = self.budget()
        if free < 218:
            raise RuntimeError("Insufficient measured headroom for HNSW construction")
        started = time.monotonic()
        self.event("hnsw_started", free_gib=free, m=16, ef_construction=64, maintenance_work_mem="4GB")
        self.sql(f"SET maintenance_work_mem='4GB'; SET max_parallel_maintenance_workers=1; "
                 f"CREATE INDEX IF NOT EXISTS vectors_hnsw ON {TABLE} USING hnsw "
                 "(embedding vector_cosine_ops) WITH(m=16,ef_construction=64)")
        self.sql(f"ANALYZE {TABLE}")
        self.event("hnsw_complete", elapsed_seconds=time.monotonic()-started, free_gib=self.budget(),
                   sizes=self.json_sql(f"SELECT json_build_object('table',pg_table_size('{TABLE}'),"
                                       f"'total',pg_total_relation_size('{TABLE}'))"))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--restore-report", required=True, type=Path)
    parser.add_argument("--source-generation", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--phase", choices=("inspect", "import", "verify", "build"), default="inspect")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.phase in {"import", "build"} and not args.apply:
        parser.error("Mutating rehearsal phases require --apply")
    with (args.restore_report.parent / "pgvector-rehearsal.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run = Rehearsal(args)
        if args.phase == "inspect":
            run.event("inspect", source=run.source, free_gib=run.budget())
        else:
            {"import": run.import_vectors, "verify": run.verify, "build": run.build}[args.phase]()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
        raise SystemExit("Rehearsal refused or failed; source and production remain unchanged. Inspect private receipts.") from None
