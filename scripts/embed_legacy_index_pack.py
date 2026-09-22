"""Durable, bounded embedding of an independently verified retained-input pack.

The input is read-only. Every possibly billable request is committed before
network I/O; an interrupted request is never refunded. Completed vectors and
provider statistics are immutable, bound to exact input bytes, and reusable.
This command does not publish an index or assert scientific/source authority.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
from collections import deque
import fcntl
import hashlib
import json
import os
import sqlite3
import stat
import struct
import sys
import threading
import time
from pathlib import Path

from legacy_index_pack import Pack, PackError, canonical, member, require, sha

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "api"), str(ROOT / "ingestion")]
from services.embedding_contract import (  # noqa: E402
    LOCAL_DOCUMENT_COUNT_METHOD,
    LOCAL_DOCUMENT_INPUT_LIMIT,
    LOCAL_DOCUMENT_REQUEST_LIMIT,
    validate_embedding_inputs,
    validate_embedding_provenance,
    validate_embedding_response,
)

VERSION = "sclib-legacy-embedding-ledger/1.0.0"
FAILURES = {
    "provider_failure",
    "provider_response_invalid",
    "provider_throttled",
    "provider_input_limit",
    "provider_http_400",
    "provider_http_401",
    "provider_http_403",
    "provider_http_404",
    "provider_http_500",
    "provider_http_503",
    "provider_http_504",
}
PROFILE = dict(
    model="text-embedding-005",
    dimension=768,
    task_type="RETRIEVAL_DOCUMENT",
    local_count_method=LOCAL_DOCUMENT_COUNT_METHOD,
    local_input_limit=LOCAL_DOCUMENT_INPUT_LIMIT,
    local_request_limit=LOCAL_DOCUMENT_REQUEST_LIMIT,
)


def file_sha(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Ledger:
    def __init__(self, path, pack, pack_sha256, *, create=False):
        self.pack = pack
        self.db = None
        self.lock = None
        try:
            self._open(path, pack_sha256, create)
        except BaseException:
            self.close()
            raise

    def _open(self, path, pack_sha256, create):
        require(
            self.pack.readonly and self.pack.sealed, "sealed_readonly_pack_required"
        )
        require(
            file_sha(self.pack.path) == pack_sha256, "verified_pack_file_hash_required"
        )
        report = json.loads(self.pack.sealed[0])
        require(
            report["inadmissible_embedding_inputs"] == 0
            and report["retained_text_coverage_complete"] is True,
            "complete_admissible_input_inventory_required",
        )
        self.report = report
        self.spec = {
            "version": VERSION,
            "input_pack_sha256": pack_sha256,
            "profile": PROFILE,
            "input_report_sha256": sha(canonical(report)),
            "members": report["members"],
            # A hard 5% ceiling includes failures and interrupted calls.
            "max_characters": (report["input_characters"] * 105 + 99) // 100,
            "max_local_tokens": (report["local_tokens"] * 105 + 99) // 100,
            "max_requests": max(10, report["members"]),
            "max_attempts_per_member": 3,
        }
        path = Path(path).absolute()
        parent = path.parent.lstat()
        require(
            stat.S_ISDIR(parent.st_mode)
            and stat.S_IMODE(parent.st_mode) == 0o700
            and parent.st_uid == os.getuid(),
            "private_ledger_directory_required",
        )
        self.lock = os.open(
            str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        info = os.fstat(self.lock)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600,
            "unsafe_ledger_lock",
        )
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PackError("embedding_worker_already_running") from None
        if create:
            fd = os.open(
                path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
            os.close(fd)
        info = path.lstat()
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600,
            "unsafe_embedding_ledger",
        )
        self.db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)
        self.db.executescript(
            "PRAGMA foreign_keys=ON; PRAGMA trusted_schema=OFF; PRAGMA journal_mode=DELETE;"
            "PRAGMA synchronous=FULL; PRAGMA cache_size=-16384; PRAGMA max_page_count=8388608;"
        )
        if create:
            self.db.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE attempts(id INTEGER PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE outcomes(attempt_id INTEGER PRIMARY KEY REFERENCES attempts(id), body TEXT NOT NULL);
                CREATE TABLE tries(seq INTEGER PRIMARY KEY, n INTEGER NOT NULL CHECK(n BETWEEN 1 AND 3));
                CREATE TABLE completions(seq INTEGER PRIMARY KEY, member_id TEXT UNIQUE NOT NULL,
                    partition_id INTEGER NOT NULL, vector BLOB NOT NULL CHECK(length(vector)=3072),
                    receipt TEXT NOT NULL, attempt_id INTEGER NOT NULL REFERENCES attempts(id));
                CREATE INDEX completions_partition ON completions(partition_id,seq);
            """)
            for table in ("metadata", "attempts", "outcomes", "completions"):
                for operation in ("UPDATE", "DELETE"):
                    self.db.execute(
                        f"CREATE TRIGGER immutable_{table}_{operation} BEFORE {operation} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'immutable_embedding_history'); END"
                    )
            self.db.execute(
                "INSERT INTO metadata VALUES('spec',?)",
                (canonical(self.spec).decode(),),
            )
            self.db.commit()
        row = self.db.execute("SELECT body FROM metadata WHERE key='spec'").fetchone()
        require(
            row and json.loads(row[0]) == self.spec,
            "embedding_ledger_pack_or_policy_changed",
        )
        # Additive failure inventory. Existing attempt/completion bytes are
        # unchanged, and rejected inputs can never satisfy seal()/verify().
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS input_rejections(seq INTEGER PRIMARY KEY,
                attempt_id INTEGER NOT NULL REFERENCES attempts(id));
            CREATE TRIGGER IF NOT EXISTS immutable_input_rejections_update BEFORE UPDATE ON input_rejections
                BEGIN SELECT RAISE(ABORT,'immutable_embedding_history'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_input_rejections_delete BEFORE DELETE ON input_rejections
                BEGIN SELECT RAISE(ABORT,'immutable_embedding_history'); END;
        """)
        self.budget = [0, 0, 0]
        for (raw,) in self.db.execute("SELECT body FROM attempts ORDER BY id"):
            attempt = json.loads(raw)
            self.budget[0] += attempt["characters"]
            self.budget[1] += attempt["local_tokens"]
            self.budget[2] += 1
        self._source = None
        self.sealed = self.db.execute(
            "SELECT body FROM metadata WHERE key='report'"
        ).fetchone()

    def input(self, row):
        seq, source_seq, partition, identifier, raw = row
        value = json.loads(raw)
        if self._source is None or self._source[0] != source_seq:
            source = self.pack.db.execute(
                "SELECT s.sha,s.body,p.sha FROM sources s JOIN papers p ON p.id=s.paper_id "
                "WHERE s.seq=?",
                (source_seq,),
            ).fetchone()
            require(source is not None, "embedding_source_missing")
            chunk = json.loads(source[1])
            require(
                source[0]
                == sha(canonical({"chunk": chunk, "paper_sha256": source[2]})),
                "embedding_source_changed",
            )
            self._source = source_seq, source[0], chunk
        _, source_hash, chunk = self._source
        start, end, prefix = value["char_start"], value["char_end"], value["prefix"]
        require(
            type(start) is int
            and type(end) is int
            and 0 <= start < end <= len(chunk["text"]),
            "invalid_input_span",
        )
        text = prefix + chunk["text"][start:end]
        from ingestion.chunk.chunker import count_tokens

        count = count_tokens(text)
        require(
            value == member(source_hash, start, end, prefix, chunk["text"], count)
            and value["id"] == identifier
            and value["embedding_input_admissible"],
            "embedding_member_changed",
        )
        return {
            "seq": seq,
            "id": identifier,
            "partition": partition,
            "text": text,
            "content_sha256": value["content_sha256"],
            "tokens": count,
        }

    def pending(self, max_inputs=250):
        """Keyset scan with bounded batches, without retaining the corpus in RAM."""
        require(
            type(max_inputs) is int and 1 <= max_inputs <= 250,
            "invalid_batch_input_limit",
        )
        batch, tokens = [], 0
        cursor = self.pack.db.execute(
            "SELECT seq,source_seq,partition_id,id,body FROM members ORDER BY seq"
        )
        for row in cursor:
            if self.db.execute(
                "SELECT 1 FROM completions WHERE seq=?", (row[0],)
            ).fetchone():
                continue
            if self.db.execute(
                "SELECT 1 FROM input_rejections WHERE seq=?", (row[0],)
            ).fetchone():
                continue
            item = self.input(row)
            if batch and (
                tokens + item["tokens"] > LOCAL_DOCUMENT_REQUEST_LIMIT
                or len(batch) == max_inputs
            ):
                yield batch
                batch, tokens = [], 0
            batch.append(item)
            tokens += item["tokens"]
        if batch:
            yield batch

    def reserve(self, batch):
        require(not self.sealed, "sealed_embedding_ledger")
        texts, counts = (
            [item["text"] for item in batch],
            [item["tokens"] for item in batch],
        )
        validate_embedding_inputs(texts, local_counts=counts, **PROFILE)
        cost = [sum(map(len, texts)), sum(counts), 1]
        require(
            all(
                a + b <= maximum
                for a, b, maximum in zip(
                    self.budget,
                    cost,
                    (
                        self.spec["max_characters"],
                        self.spec["max_local_tokens"],
                        self.spec["max_requests"],
                    ),
                    strict=True,
                )
            ),
            "embedding_call_budget_exhausted",
        )
        require(
            len({item["seq"] for item in batch}) == len(batch),
            "duplicate_embedding_input",
        )
        body = {
            "seqs": [item["seq"] for item in batch],
            "input_sha256": sha(
                canonical([[item["id"], item["content_sha256"]] for item in batch])
            ),
            "characters": cost[0],
            "local_tokens": cost[1],
            "reserved_at": time.time(),
        }
        with self.db:
            for item in batch:
                require(
                    not self.db.execute(
                        "SELECT 1 FROM completions WHERE seq=?", (item["seq"],)
                    ).fetchone(),
                    "embedding_already_completed",
                )
                tried = self.db.execute(
                    "SELECT n FROM tries WHERE seq=?", (item["seq"],)
                ).fetchone()
                require(
                    not tried or tried[0] < self.spec["max_attempts_per_member"],
                    "embedding_retry_limit",
                )
                self.db.execute(
                    "INSERT INTO tries VALUES (?,1) ON CONFLICT(seq) DO UPDATE SET n=n+1",
                    (item["seq"],),
                )
            identifier = self.db.execute(
                "INSERT INTO attempts(body) VALUES (?)", (canonical(body).decode(),)
            ).lastrowid
        self.budget = [a + b for a, b in zip(self.budget, cost, strict=True)]
        return identifier

    def finish(self, attempt_id, batch, result):
        require(not self.sealed, "sealed_embedding_ledger")
        attempt = json.loads(
            self.db.execute(
                "SELECT body FROM attempts WHERE id=?", (attempt_id,)
            ).fetchone()[0]
        )
        require(
            attempt["seqs"] == [item["seq"] for item in batch]
            and attempt["input_sha256"]
            == sha(canonical([[i["id"], i["content_sha256"]] for i in batch])),
            "embedding_attempt_binding_mismatch",
        )
        rows = []
        require(
            type(result) is list and len(result) == len(batch),
            "embedding_completion_count_mismatch",
        )
        for item, (vector, receipt) in zip(batch, result, strict=True):
            validate_embedding_provenance(
                receipt,
                text=item["text"],
                vector=vector,
                expected_task="RETRIEVAL_DOCUMENT",
            )
            require(
                receipt["local_count"] == item["tokens"],
                "embedding_completion_local_count_mismatch",
            )
            rows.append(
                (
                    item["seq"],
                    item["id"],
                    item["partition"],
                    struct.pack(">768f", *vector),
                    canonical(receipt).decode(),
                    attempt_id,
                )
            )
        with self.db:
            self.db.executemany("INSERT INTO completions VALUES (?,?,?,?,?,?)", rows)
            self.db.execute(
                "INSERT INTO outcomes VALUES (?,?)",
                (
                    attempt_id,
                    canonical(
                        {
                            "status": "complete",
                            "finished_at": time.time(),
                            "members": len(rows),
                        }
                    ).decode(),
                ),
            )

    def fail(self, attempt_id, code):
        require(code in FAILURES, "invalid_failure_code")
        with self.db:
            self.db.execute(
                "INSERT INTO outcomes VALUES (?,?)",
                (
                    attempt_id,
                    canonical(
                        {
                            "status": code,
                            "finished_at": time.time(),
                            "potentially_billable": True,
                        }
                    ).decode(),
                ),
            )
            if code == "provider_input_limit":
                attempt = json.loads(
                    self.db.execute(
                        "SELECT body FROM attempts WHERE id=?", (attempt_id,)
                    ).fetchone()[0]
                )
                if len(attempt["seqs"]) == 1:
                    self.db.execute(
                        "INSERT INTO input_rejections VALUES (?,?)",
                        (attempt["seqs"][0], attempt_id),
                    )

    def status(self):
        return {
            "stage": "embedding",
            "completed_members": self.db.execute(
                "SELECT count(*) FROM completions"
            ).fetchone()[0],
            "expected_members": self.spec["members"],
            "reserved_characters": self.budget[0],
            "reserved_local_tokens": self.budget[1],
            "reserved_requests": self.budget[2],
            "rejected_inputs": self.db.execute(
                "SELECT count(*) FROM input_rejections"
            ).fetchone()[0],
            "max_characters": self.spec["max_characters"],
            "sealed": bool(self.sealed),
        }

    def verify(self):
        require(
            self.db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
            and not self.db.execute("PRAGMA foreign_key_check").fetchall(),
            "embedding_ledger_integrity",
        )
        digest = hashlib.sha256()
        count = provider_tokens = 0
        for seq, member_id, partition, vector, raw, attempt_id in self.db.execute(
            "SELECT * FROM completions ORDER BY seq"
        ):
            count += 1
            require(seq == count, "incomplete_embedding_inventory")
            source = self.pack.db.execute(
                "SELECT seq,source_seq,partition_id,id,body FROM members WHERE seq=?",
                (seq,),
            ).fetchone()
            item = self.input(source)
            receipt = json.loads(raw)
            require(
                member_id == item["id"]
                and partition == item["partition"]
                and receipt["local_count"] == item["tokens"],
                "embedding_member_receipt_mismatch",
            )
            validate_embedding_provenance(
                receipt,
                text=item["text"],
                vector=list(struct.unpack(">768f", vector)),
                expected_task="RETRIEVAL_DOCUMENT",
            )
            outcome = self.db.execute(
                "SELECT body FROM outcomes WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            require(
                outcome and json.loads(outcome[0])["status"] == "complete",
                "embedding_attempt_not_completed",
            )
            attempt = json.loads(
                self.db.execute(
                    "SELECT body FROM attempts WHERE id=?", (attempt_id,)
                ).fetchone()[0]
            )
            require(seq in attempt["seqs"], "embedding_attempt_member_mismatch")
            provider_tokens += receipt["provider_token_count"]
            digest.update(
                canonical(
                    [
                        seq,
                        member_id,
                        partition,
                        sha(vector),
                        sha(canonical(receipt)),
                        attempt_id,
                    ]
                )
                + b"\n"
            )
        require(count == self.spec["members"], "incomplete_embedding_inventory")
        return {
            "version": VERSION,
            "input_pack_sha256": self.spec["input_pack_sha256"],
            "members": count,
            "completion_manifest_sha256": digest.hexdigest(),
            "provider_tokens": provider_tokens,
            "embedding_completion_verified": True,
            "index_publication_verified": False,
            "scientific_acceptance": False,
            "activation_eligible": False,
        }

    def seal(self):
        report = self.verify()
        if self.sealed:
            require(
                json.loads(self.sealed[0]) == report, "sealed_embedding_ledger_changed"
            )
        else:
            with self.db:
                self.db.execute(
                    "INSERT INTO metadata VALUES('report',?)",
                    (canonical(report).decode(),),
                )
            self.sealed = (canonical(report).decode(),)
        return report

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None


_CLIENT_LOCAL = threading.local()
_CLIENTS = []
_CLIENT_LOCK = threading.Lock()


def provider(project, location, batch):
    from google import genai
    from google.genai import types

    # Exactly one SDK attempt. The durable ledger, not hidden SDK retries,
    # accounts for every request. Exceptions never expose provider payloads.
    try:
        # Each worker owns a client so ADC and connection pools can refresh and
        # reuse safely. Creating one client per batch repeats STS/IAM exchanges
        # and dominates a million-input migration with short-lived credentials.
        key = (project, location)
        if getattr(_CLIENT_LOCAL, "key", None) != key:
            client = genai.Client(
                vertexai=True,
                project=project,
                location=location,
                http_options=types.HttpOptions(
                    api_version="v1",
                    timeout=60000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
            _CLIENT_LOCAL.key, _CLIENT_LOCAL.client = key, client
            with _CLIENT_LOCK:
                _CLIENTS.append(client)
        response = _CLIENT_LOCAL.client.models.embed_content(
            model=PROFILE["model"],
            contents=[i["text"] for i in batch],
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=768,
                auto_truncate=False,
            ),
        )
    except Exception as exc:
        status = getattr(exc, "code", None)
        code = "provider_throttled" if status == 429 else "provider_failure"
        if type(status) is int and status in {400, 401, 403, 404, 500, 503, 504}:
            code = f"provider_http_{status}"
        if (
            status == 400
            and "token" in str(exc).lower()
            and any(word in str(exc).lower() for word in ("limit", "exceed", "maximum", "supports up to"))
        ):
            code = "provider_input_limit"
        if code.startswith("provider_"):
            # Preserve private provider diagnostics for the operator, without
            # putting response bodies or retained text in progress logs.
            diagnostic_dir = os.environ.get("SCLIB_EMBED_DIAGNOSTICS")
            if diagnostic_dir:
                destination = (
                    Path(diagnostic_dir) / f"provider-{status}-{time.time_ns()}.json"
                )
                fd = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                with os.fdopen(fd, "w") as stream:
                    json.dump(
                        {
                            "code": status,
                            "message": str(exc),
                            "member_seqs": [i["seq"] for i in batch],
                        },
                        stream,
                    )
        return code, None
    try:
        return "complete", validate_embedding_response(
            [i["text"] for i in batch],
            response,
            local_counts=[i["tokens"] for i in batch],
            **PROFILE,
        )
    except Exception:
        return "provider_response_invalid", None


def run(ledger, args, call=provider):
    require(
        1 <= args.concurrency <= 8
        and 1 <= args.requests_per_minute <= 600
        and 1 <= args.max_new_requests <= ledger.spec["max_requests"],
        "invalid_worker_limits",
    )
    pending = iter(ledger.pending(getattr(args, "max_batch_inputs", 250)))
    retry_batches = deque()
    inflight = {}
    stopped = exhausted = False
    sent = 0
    next_call = last_log = 0.0
    with futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        while inflight or not exhausted and not stopped:
            while (
                not stopped
                and not exhausted
                and len(inflight) < args.concurrency
                and sent < args.max_new_requests
            ):
                if time.monotonic() < next_call:
                    break
                try:
                    batch = retry_batches.popleft() if retry_batches else next(pending)
                except StopIteration:
                    exhausted = True
                    break
                attempt = ledger.reserve(batch)
                inflight[pool.submit(call, args.project, args.location, batch)] = (
                    attempt,
                    batch,
                )
                sent += 1
                next_call = time.monotonic() + 60 / args.requests_per_minute
            if sent >= args.max_new_requests:
                stopped = True
            if inflight:
                completed, _ = futures.wait(
                    inflight, timeout=0.1, return_when=futures.FIRST_COMPLETED
                )
                for future in completed:
                    attempt, batch = inflight.pop(future)
                    code, result = future.result()
                    if code == "complete":
                        ledger.finish(attempt, batch, result)
                    else:
                        ledger.fail(attempt, code)
                        if code == "provider_input_limit":
                            # An oversized *request* and an oversized *input*
                            # are distinct. One-input calls identify the latter
                            # without truncation. Known rejected inputs remain
                            # explicit holes for a later exact re-windowing pack.
                            if len(batch) > 1:
                                retry_batches.extend([item] for item in batch)
                                exhausted = False
                            print(
                                json.dumps(
                                    {
                                        "stage": "input_limit",
                                        "attempt": attempt,
                                        "members": len(batch),
                                        "action": "split_request"
                                        if len(batch) > 1
                                        else "retain_rejection",
                                    }
                                ),
                                flush=True,
                            )
                            continue
                        # Drain already reserved work; require an explicit resume
                        # after diagnosis. A failing provider cannot churn budget.
                        stopped = True
                        print(
                            json.dumps(
                                {"stage": "stopped", "reason": code, "attempt": attempt}
                            ),
                            flush=True,
                        )
            elif not exhausted and not stopped:
                time.sleep(min(0.1, max(0, next_call - time.monotonic())))
            if time.monotonic() - last_log >= 30:
                print(json.dumps(ledger.status()), flush=True)
                last_log = time.monotonic()
    status = ledger.status()
    if status["completed_members"] == status["expected_members"]:
        print(json.dumps(ledger.seal()), flush=True)
    else:
        print(json.dumps(status), flush=True)
    return 0 if status["completed_members"] == status["expected_members"] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "verify", "status"))
    parser.add_argument("--pack", required=True)
    parser.add_argument("--pack-sha256", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--project", default="jzis-sclib")
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--requests-per-minute", type=int, default=300)
    parser.add_argument("--max-new-requests", type=int, default=60000)
    parser.add_argument("--max-batch-inputs", type=int, default=250)
    args = parser.parse_args()
    pack = ledger = None
    try:
        pack = Pack(args.pack, readonly=True)
        ledger = Ledger(args.ledger, pack, args.pack_sha256, create=args.create)
        if args.command == "run":
            return run(ledger, args)
        print(
            json.dumps(ledger.seal() if args.command == "verify" else ledger.status()),
            flush=True,
        )
        return 0
    except PackError as exc:
        print(json.dumps({"stage": "failed", "reason": str(exc)}), flush=True)
        return 1
    except Exception:
        print(
            json.dumps({"stage": "failed", "reason": "embedding_operation_rejected"}),
            flush=True,
        )
        return 1
    finally:
        with _CLIENT_LOCK:
            for client in _CLIENTS:
                client.close()
            _CLIENTS.clear()
        if ledger is not None:
            ledger.close()
        if pack is not None:
            pack.close()


if __name__ == "__main__":
    raise SystemExit(main())
