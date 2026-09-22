#!/usr/bin/env python3
"""Resumable full-corpus operator over explicit exact input/receipt artifacts.

Plan, stage, publish, readback and activation are separate commands. No command
implicitly activates. All source, receipt and partition guards remain enabled.
Application DB writes require --apply and an explicit process DATABASE_URL.
"""

from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import time
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "api"), str(ROOT / "ingestion")]
from legacy_index_pack import Pack, canonical, require, sha, PackError
from embed_legacy_index_pack import file_sha
from repair_legacy_index_pack import private_db, VERSION as INVENTORY_VERSION

VERSION = "sclib-corpus-operator/1.0.0"


class Inputs:
    def __init__(self, pack, completions, completion_sha):
        self.pack = Pack(pack, readonly=True)
        self.db = private_db(completions)
        require(
            file_sha(completions) == completion_sha, "completion_file_hash_mismatch"
        )
        row = self.db.execute("SELECT body FROM metadata WHERE key='report'").fetchone()
        require(row is not None, "sealed_completions_required")
        self.report = json.loads(row[0])
        self.pack_sha = file_sha(pack)
        require(
            self.pack.sealed
            and self.report["version"] == INVENTORY_VERSION
            and self.report["input_pack_sha256"] == self.pack_sha
            and self.report["embedding_completion_verified"] is True
            and self.report["retained_text_coverage_complete"] is True,
            "complete_effective_inventory_required",
        )
        self.pack_report = json.loads(self.pack.sealed[0])
        self.count = self.pack_report["members"]
        stats = self.db.execute(
            "SELECT count(*),min(seq),max(seq) FROM completions"
        ).fetchone()
        require(
            stats == (self.count, 1, self.count)
            and self.report["members"] == self.count,
            "completion_sequence_incomplete",
        )

    def entries(self, after=0, until=None):
        for (
            seq,
            source_seq,
            part,
            key,
            raw,
            source_raw,
            paper_raw,
        ) in self.pack.db.execute(
            """SELECT m.seq,m.source_seq,m.partition_id,m.id,m.body,s.body,p.body
            FROM members m JOIN sources s ON s.seq=m.source_seq JOIN papers p ON p.id=s.paper_id
            WHERE m.seq>? AND m.seq<=? ORDER BY m.seq""",
            (after, until or self.count),
        ):
            found = self.db.execute(
                "SELECT member_id,partition_id,vector,receipt FROM completions WHERE seq=?",
                (seq,),
            ).fetchone()
            require(
                found is not None and found[:2] == (key, part),
                "completion_member_mismatch",
            )
            chunk = json.loads(source_raw)
            paper = json.loads(paper_raw)
            yield dict(
                pack_sha256=self.pack_sha,
                source_seq=source_seq,
                source_raw=canonical(
                    {"chunk": chunk, "paper_sha256": sha(canonical(paper))}
                ).decode(),
                paper_raw=paper_raw,
                member_seq=seq,
                input_partition=part,
                member_raw=raw,
                vector=list(struct.unpack(">768f", found[2])),
                receipt=json.loads(found[3]),
            )

    def batches(self, after=0, until=None):
        batch = []
        size = 0
        for entry in self.entries(after, until):
            amount = sum(
                len(entry[k].encode())
                for k in ("source_raw", "paper_raw", "member_raw")
            )
            if batch and (len(batch) >= 500 or size + amount > 4 * 1024 * 1024):
                yield batch
                batch = []
                size = 0
            require(amount <= 32 * 1024 * 1024, "single_retained_input_resource_limit")
            batch.append(entry)
            size += amount
        if batch:
            yield batch

    def close(self):
        self.pack.close()
        self.db.close()


class Journal:
    def __init__(self, path, spec):
        created = not Path(path).exists()
        self.db = private_db(path, create=created)
        if not created:
            self.db.close()
            self.db = sqlite3.connect(
                Path(path).absolute().as_uri() + "?mode=rw", uri=True
            )
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA trusted_schema=OFF")
        if created:
            self.db.executescript("""CREATE TABLE metadata(key TEXT PRIMARY KEY,body TEXT NOT NULL);
                CREATE TABLE plans(part INTEGER PRIMARY KEY,first_seq INTEGER NOT NULL,last_seq INTEGER NOT NULL,body TEXT NOT NULL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY,body TEXT NOT NULL);""")
            for table in ("metadata", "plans", "events"):
                for action in ("UPDATE", "DELETE"):
                    self.db.execute(
                        f"CREATE TRIGGER immutable_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_corpus_journal'); END"
                    )
            self.db.execute(
                "INSERT INTO metadata VALUES('spec',?)", (canonical(spec).decode(),)
            )
            self.db.commit()
        require(
            json.loads(
                self.db.execute(
                    "SELECT body FROM metadata WHERE key='spec'"
                ).fetchone()[0]
            )
            == spec,
            "operator_identity_changed",
        )

    def event(self, body):
        body = {"at": datetime.now(timezone.utc).isoformat(), **body}
        with self.db:
            self.db.execute(
                "INSERT INTO events(body) VALUES(?)", (canonical(body).decode(),)
            )
        print(json.dumps(body), flush=True)

    def plans(self):
        return [
            json.loads(x[0])
            for x in self.db.execute("SELECT body FROM plans ORDER BY part")
        ]


async def import_batch(db, entries):
    from services.retained_corpus_import import import_completions

    # Byte/count bounded sub-batches; no per-input DB round trips.
    items = []
    current = []
    size = 0
    for entry in entries:
        amount = sum(
            len(entry[k].encode()) for k in ("source_raw", "paper_raw", "member_raw")
        )
        if current and (len(current) == 100 or size + amount > 32 * 1024 * 1024):
            items.extend(await import_completions(db, entries=current))
            current = []
            size = 0
        current.append(entry)
        size += amount
    if current:
        items.extend(await import_completions(db, entries=current))
    return items


async def run(args):
    require(
        args.apply and bool(os.environ.get("DATABASE_URL")),
        "explicit_apply_and_database_required",
    )
    from models.db import get_session_factory, get_engine
    from services.schema_lifecycle import check_connection_schema
    from services import (
        index_corpus as corpus,
        index_generations as generations,
        index_vector_adapter as adapter,
    )
    from services.retained_corpus_import import remove_replayed_chunks, plan_completions

    inputs = Inputs(args.pack, args.completions, args.completion_sha256)
    resource = json.loads(Path(args.resource).read_text())
    identifier = str(UUID(args.generation_id))
    resource = generations._resource(resource)
    spec = {
        "version": VERSION,
        "generation_id": identifier,
        "resource": resource,
        "pack_sha256": inputs.pack_sha,
        "completions_sha256": args.completion_sha256,
        "expected_members": inputs.count,
    }
    journal = Journal(args.journal, spec)
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.run_sync(check_connection_schema)
        if args.command == "plan":
            last = journal.db.execute(
                "SELECT COALESCE(max(last_seq),0),count(*) FROM plans"
            ).fetchone()
            after, part = last
            made = 0
            for entries in inputs.batches(after):
                part += 1
                require(part <= 20000, "corpus_partition_limit")
                async with get_session_factory()() as db:
                    members = await plan_completions(
                        db, generation_id=identifier, entries=entries
                    )
                    plan = corpus.partition_plan(members, part)
                    await db.rollback()
                with journal.db:
                    journal.db.execute(
                        "INSERT INTO plans VALUES(?,?,?,?)",
                        (
                            part,
                            entries[0]["member_seq"],
                            entries[-1]["member_seq"],
                            canonical(plan).decode(),
                        ),
                    )
                made += 1
                journal.event(
                    {
                        "stage": "planned",
                        "partition": part,
                        "through_member": entries[-1]["member_seq"],
                        "expected_members": inputs.count,
                    }
                )
                if made >= args.max_new_partitions:
                    break
            plans = journal.plans()
            if sum(p["expected_member_count"] for p in plans) == inputs.count:
                body = {
                    "manifest_sha256": corpus.root_manifest(plans),
                    "partitions": len(plans),
                    "members": inputs.count,
                }
                old = journal.db.execute(
                    "SELECT body FROM metadata WHERE key='planned'"
                ).fetchone()
                if old:
                    require(json.loads(old[0]) == body)
                else:
                    with journal.db:
                        journal.db.execute(
                            "INSERT INTO metadata VALUES('planned',?)",
                            (canonical(body).decode(),),
                        )
                journal.event({"stage": "plan_complete", **body})
            return
        require(
            journal.db.execute("SELECT 1 FROM metadata WHERE key='planned'").fetchone(),
            "complete_partition_plan_required",
        )
        plans = journal.plans()
        async with get_session_factory()() as db:
            pin = await corpus.create_corpus(
                db,
                generation_id=identifier,
                resource=resource,
                pack_sha256=inputs.pack_sha,
                input_manifest_sha256=inputs.pack_report["member_manifest_sha256"],
                expected_sources=inputs.pack_report["sources"],
                partitions=plans,
            )
            await db.commit()
        if args.command == "stage":
            made = 0
            for part, first, last, raw in journal.db.execute(
                "SELECT * FROM plans ORDER BY part"
            ):
                async with get_session_factory()() as db:
                    import sqlalchemy as sa

                    sealed = await db.scalar(
                        sa.text(
                            "SELECT manifest_sha256 FROM index_corpus_seals WHERE generation_id=:id AND partition_id=:part"
                        ),
                        {"id": UUID(identifier), "part": part},
                    )
                    if sealed is not None:
                        require(
                            sealed == json.loads(raw)["manifest_sha256"],
                            "existing_partition_seal_conflict",
                        )
                        continue
                    entries = list(inputs.entries(first - 1, last))
                    items = await import_batch(db, entries)
                    await corpus.stage_partition(
                        db, generation_id=identifier, partition_id=part, items=items
                    )
                    await remove_replayed_chunks(
                        db, chunk_ids=[x["chunk_id"] for x in items]
                    )
                    await db.commit()
                journal.event(
                    {"stage": "staged", "partition": part, "through_member": last}
                )
                made += 1
                if made >= args.max_new_partitions:
                    break
            return
        if args.command in ("publish", "observe"):
            session = adapter.CorpusTransportSession(pin)
            started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            observations = []
            for plan in plans:
                part = plan["partition_id"]
                async with get_session_factory()() as db:
                    members = await corpus.partition_members(
                        db, generation_id=identifier, partition_id=part
                    )
                    require(
                        len(members) == plan["expected_member_count"],
                        "staged_partition_missing",
                    )
                selected = {**pin, "manifest_sha256": plan["manifest_sha256"]}
                if args.command == "publish":
                    result = await asyncio.to_thread(
                        adapter.publish, selected, members, session=session
                    )
                    journal.event({"stage": "published", "partition": part, **result})
                else:
                    observation = await asyncio.to_thread(
                        adapter.observe, selected, members, session=session
                    )
                    async with get_session_factory()() as db:
                        row = await corpus.record_partition_observation(
                            db,
                            generation_id=identifier,
                            partition_id=part,
                            observation=observation,
                        )
                        await db.commit()
                    require(
                        row["outcome"] == "validated", "remote_partition_incomplete"
                    )
                    observations.append(row["id"])
                    journal.event(
                        {
                            "stage": "observed",
                            "partition": part,
                            "observation_id": row["id"],
                        }
                    )
            if args.command == "observe":
                async with get_session_factory()() as db:
                    result = await corpus.validate_corpus(
                        db,
                        generation_id=identifier,
                        observation_ids=observations,
                        started_at=started,
                    )
                    await db.commit()
                journal.event({"stage": "validated", **result})
            return
        require(
            args.validation_id
            and args.expected_event_id is not None
            and args.idempotency_key,
            "exact_activation_predecessor_required",
        )
        async with get_session_factory()() as db:
            result = await generations.activate_generation(
                db,
                generation_id=identifier,
                validation_id=args.validation_id,
                expected_event_id=None
                if args.expected_event_id == "none"
                else args.expected_event_id,
                idempotency_key=args.idempotency_key,
                dry_run=False,
            )
            await db.commit()
        journal.event({"stage": "activated", **result})
    finally:
        await engine.dispose()
        inputs.close()
        journal.db.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "command", choices=["plan", "stage", "publish", "observe", "activate"]
    )
    for name in (
        "pack",
        "completions",
        "completion-sha256",
        "resource",
        "generation-id",
        "journal",
    ):
        p.add_argument("--" + name, required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--max-new-partitions", type=int, default=20000)
    p.add_argument("--validation-id")
    p.add_argument("--expected-event-id")
    p.add_argument("--idempotency-key")
    args = p.parse_args()
    require(1 <= args.max_new_partitions <= 20000)
    asyncio.run(run(args))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "stage": "failed",
                    "reason": str(exc)
                    if isinstance(exc, PackError)
                    else type(exc).__name__,
                }
            ),
            flush=True,
        )
        destination = os.environ.get("SCLIB_CORPUS_DIAGNOSTICS")
        if destination:
            import traceback

            fd = os.open(
                Path(destination) / ("corpus-error-" + str(time.time_ns()) + ".txt"),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(fd, "w") as stream:
                traceback.print_exc(file=stream)
        raise SystemExit(2)
