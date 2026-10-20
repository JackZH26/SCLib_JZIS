"""Private durable pilot queue: fenced leases and immutable attempt receipts."""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .contract import canonical, digest


class LeaseError(RuntimeError):
    pass


class Ledger:
    def __init__(self, path: Path):
        if path.is_symlink():
            raise ValueError("ledger_symlink_refused")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          job_key TEXT PRIMARY KEY, config_sha TEXT NOT NULL, input_sha TEXT NOT NULL,
          fence INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'queued', result BLOB, result_sha TEXT);
        CREATE TABLE IF NOT EXISTS attempts (
          job_key TEXT NOT NULL REFERENCES jobs(job_key), block_id TEXT NOT NULL,
          sequence INTEGER NOT NULL, fence INTEGER NOT NULL, status TEXT NOT NULL,
          receipt BLOB NOT NULL, receipt_sha TEXT NOT NULL,
          PRIMARY KEY(job_key, block_id, sequence));
        CREATE TABLE IF NOT EXISTS blocks (
          job_key TEXT NOT NULL REFERENCES jobs(job_key), block_id TEXT NOT NULL,
          input_sha TEXT NOT NULL, status TEXT NOT NULL, result BLOB,
          PRIMARY KEY(job_key, block_id));
        """)
        self.db.execute("PRAGMA foreign_keys=ON")

    def close(self):
        self.db.close()

    @contextmanager
    def _transaction(self):
        # Claim and every fenced write take the same write lock before reading.
        # A deferred transaction could check an old fence then write after reclaim.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def enqueue(self, job_key: str, config_sha: str, input_sha: str):
        with self._transaction():
            self.db.execute(
                "INSERT OR IGNORE INTO jobs(job_key,config_sha,input_sha) VALUES(?,?,?)",
                (job_key, config_sha, input_sha),
            )
            row = self.db.execute(
                "SELECT config_sha,input_sha FROM jobs WHERE job_key=?", (job_key,)
            ).fetchone()
            if (row["config_sha"], row["input_sha"]) != (config_sha, input_sha):
                raise LeaseError("job_key_configuration_conflict")

    def claim(self, key, *, lease_seconds=3600, now=None):
        now = time.time() if now is None else now
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT * FROM jobs WHERE job_key=?", (key,)).fetchone()
            if row is None:
                raise LeaseError("unknown_job")
            if row["status"] in {"completed", "failed"}:
                self.db.rollback()
                return None
            if row["status"] == "running" and row["expires"] > now:
                raise LeaseError("job_already_leased")
            fence = row["fence"] + 1
            self.db.execute(
                "UPDATE jobs SET fence=?,expires=?,status='running' WHERE job_key=?",
                (fence, now + lease_seconds, key),
            )
            self.db.commit()
            return fence
        except BaseException:
            self.db.rollback()
            raise

    def _check(self, key, fence):
        row = self.db.execute(
            "SELECT fence,status,expires FROM jobs WHERE job_key=?", (key,)
        ).fetchone()
        if (
            row is None
            or row["fence"] != fence
            or row["status"] != "running"
            or row["expires"] < time.time()
        ):
            raise LeaseError("stale_or_expired_lease")

    def heartbeat(self, key, fence, *, lease_seconds=3600):
        with self._transaction():
            self._check(key, fence)
            self.db.execute(
                "UPDATE jobs SET expires=? WHERE job_key=?", (time.time() + lease_seconds, key)
            )

    def attempt_count(self, key):
        return self.db.execute("SELECT count(*) FROM attempts WHERE job_key=?", (key,)).fetchone()[
            0
        ]

    def record_attempt(self, key, fence, block_id, status, receipt):
        with self._transaction():
            self._check(key, fence)
            sequence = self.db.execute(
                "SELECT coalesce(max(sequence),0)+1 FROM attempts WHERE job_key=? AND block_id=?",
                (key, block_id),
            ).fetchone()[0]
            self.db.execute(
                "INSERT INTO attempts VALUES(?,?,?,?,?,?,?)",
                (key, block_id, sequence, fence, status, canonical(receipt), digest(receipt)),
            )

    def put_block(self, key, fence, block, status, result):
        with self._transaction():
            self._check(key, fence)
            sha = digest(block)
            old = self.db.execute(
                "SELECT * FROM blocks WHERE job_key=? AND block_id=?", (key, block["block_id"])
            ).fetchone()
            if old and (
                old["input_sha"] != sha
                or old["status"] != status
                or old["result"] != canonical(result)
            ):
                raise LeaseError("immutable_block_completion_conflict")
            self.db.execute(
                "INSERT OR IGNORE INTO blocks VALUES(?,?,?,?,?)",
                (key, block["block_id"], sha, status, canonical(result)),
            )

    def cached_block(self, key, block):
        import json

        row = self.db.execute(
            "SELECT * FROM blocks WHERE job_key=? AND block_id=?", (key, block["block_id"])
        ).fetchone()
        if not row:
            return None
        if row["input_sha"] != digest(block):
            raise LeaseError("block_input_hash_conflict")
        return row["status"], json.loads(row["result"])

    def complete(self, key, fence, result):
        with self._transaction():
            self._check(key, fence)
            status = "completed" if result["coverage"]["machine_text_complete"] else "failed"
            self.db.execute(
                "UPDATE jobs SET status=?,result=?,result_sha=?,expires=0 WHERE job_key=?",
                (status, canonical(result), digest(result), key),
            )

    def result(self, key):
        import json

        row = self.db.execute(
            "SELECT result,result_sha FROM jobs WHERE job_key=?", (key,)
        ).fetchone()
        if row and row["result"] is not None:
            value = json.loads(row["result"])
            if digest(value) != row["result_sha"]:
                raise LeaseError("stored_result_hash_mismatch")
            return value
        return None

    def attempts(self, key):
        import json

        return [
            dict(
                status=r["status"],
                block_id=r["block_id"],
                sequence=r["sequence"],
                receipt=json.loads(r["receipt"]),
            )
            for r in self.db.execute(
                "SELECT * FROM attempts WHERE job_key=? ORDER BY block_id,sequence", (key,)
            )
        ]
