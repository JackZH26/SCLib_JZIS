"""Mac-friendly durable queue: SQLite WAL, leases and append-only attempts."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from . import PIPELINE_VERSION
from .contract import canonical, digest


class LostLease(RuntimeError):
    pass


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.path = self.root / "queue.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, work_id TEXT NOT NULL, bundle_hash TEXT NOT NULL,
                    config_json TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
                    attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL,
                    lease_token TEXT, lease_until REAL, available_at REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, last_error TEXT,
                    result_path TEXT, result_hash TEXT);
                CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(state,available_at,created_at);
                CREATE TABLE IF NOT EXISTS attempts(
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                    ordinal INTEGER NOT NULL, started_at REAL NOT NULL, finished_at REAL,
                    status TEXT NOT NULL, error_code TEXT, duration_seconds REAL,
                    usage_json TEXT, receipt_path TEXT, receipt_hash TEXT,
                    UNIQUE(job_id, ordinal));
                CREATE TABLE IF NOT EXISTS audit(
                    id INTEGER PRIMARY KEY, job_id TEXT, at REAL NOT NULL,
                    event TEXT NOT NULL, payload_json TEXT NOT NULL);
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def enqueue(self, *, work_id: str, bundle_hash: str, config: dict, max_attempts=3) -> str:
        self._require_dispatch_enabled()
        if config.get("workflow") in {"reviewed_reader_v1", "source_projector_v1", "assertion_audit_v1", "source_census_v1", "source_roles_v1"} and max_attempts != 1:
            raise ValueError("reviewed_reader_requires_one_automatic_attempt")
        if config.get("workflow") == "assertion_audit_v1":
            identity = config.get("single_pass_identity")
            if not isinstance(identity, str) or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
                raise ValueError("assertion_audit_requires_frozen_identity")
        if not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        body = {"work_id": work_id, "bundle_hash": bundle_hash, "config": config,
                "pipeline_version": PIPELINE_VERSION}
        identifier, now = digest(body), time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if config.get("workflow") == "assertion_audit_v1":
                # Queue-local one-pass policy survives renamed input files and
                # config changes. A fresh namespace is not a global billing lock.
                prior = db.execute("""SELECT id FROM jobs
                    WHERE json_extract(config_json,'$.workflow')='assertion_audit_v1'
                    AND json_extract(config_json,'$.single_pass_identity')=?""",
                    (config["single_pass_identity"],)).fetchone()
                if prior is not None:
                    return prior[0]
            db.execute("""INSERT OR IGNORE INTO jobs
                (id,work_id,bundle_hash,config_json,max_attempts,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)""",
                       (identifier, work_id, bundle_hash, canonical(config), max_attempts, now, now))
        return identifier

    def claim(self, lease_seconds: int = 1200, job_id: str | None = None,
              *, workflow: str | None = None) -> dict | None:
        self._require_dispatch_enabled()
        if lease_seconds < 1:
            raise ValueError("lease must be positive")
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            expired = db.execute("SELECT * FROM jobs WHERE state='running' AND lease_until<?", (now,)).fetchall()
            for row in expired:
                db.execute("""UPDATE attempts SET status='lease_expired',finished_at=?,
                    error_code='lease_expired' WHERE id=? AND status='running'""", (now, row["lease_token"]))
                db.execute("""UPDATE jobs SET state=?,lease_token=NULL,lease_until=NULL,
                    last_error='lease_expired',updated_at=? WHERE id=?""",
                           ("queued" if row["attempts"] < row["max_attempts"] else "failed", now, row["id"]))
                self._audit(db, row["id"], "lease_expired", {})
            row = db.execute("""SELECT * FROM jobs
                WHERE state='queued' AND available_at<=? AND attempts<max_attempts
                AND (? IS NULL OR id=?)
                AND ((? IS NULL AND COALESCE(json_extract(config_json,'$.workflow'),'') NOT IN ('reviewed_reader_v1','source_projector_v1','assertion_audit_v1','source_census_v1','source_roles_v1'))
                     OR (? IS NOT NULL AND json_extract(config_json,'$.workflow')=?))
                ORDER BY created_at,id LIMIT 1""",
                             (now, job_id, job_id, workflow, workflow, workflow)).fetchone()
            if row is None:
                return None
            token, ordinal = uuid.uuid4().hex, row["attempts"] + 1
            db.execute("""UPDATE jobs SET state='running',attempts=?,lease_token=?,
                lease_until=?,updated_at=? WHERE id=?""", (ordinal, token, now + lease_seconds, now, row["id"]))
            db.execute("""INSERT INTO attempts(id,job_id,ordinal,started_at,status)
                VALUES(?,?,?,?,'running')""", (token, row["id"], ordinal, now))
            self._audit(db, row["id"], "claimed", {"attempt": ordinal, "lease": token})
            return {**dict(row), "lease_token": token, "attempts": ordinal,
                    "config": json.loads(row["config_json"])}

    def _require_dispatch_enabled(self):
        # A prepared full-corpus namespace is intentionally incompatible with the
        # historical single-pass/window runners. No boolean in a mutable config
        # can bypass source preflight or stand in for a reviewed-drafting adapter.
        if (self.root / "STAGING_PREPARATION.json").exists():
            raise ValueError("staging_preparation_only: reviewed drafting dispatch is not enabled")
        if (self.root / "READER_DISPATCH_HOLD.json").exists():
            raise ValueError("reader_dispatch_hold: reconcile uncertain provider completion before new calls")

    def heartbeat(self, job: dict, lease_seconds=1200):
        now = time.time()
        with self.connect() as db:
            changed = db.execute("""UPDATE jobs SET lease_until=?,updated_at=?
                WHERE id=? AND lease_token=? AND state='running' AND lease_until>?""",
                                 (now + lease_seconds, now, job["id"], job["lease_token"], now)).rowcount
            if changed != 1:
                raise LostLease("lease no longer owned")

    def supersede_unstarted(self, identifiers: list[str], replacement_config_hash: str):
        """Archive only never-started jobs after an explicit configuration repair.

Keep the original queue rows and audit trail; do not fabricate attempts/results.
An active or previously attempted job makes the whole operation fail.
"""
        if len(set(identifiers)) != len(identifiers) or len(replacement_config_hash) != 64:
            raise ValueError("invalid supersession request")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for identifier in identifiers:
                row = db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
                if (row is None or row["state"] != "queued" or row["attempts"] != 0
                        or row["result_path"] is not None):
                    raise ValueError("supersession requires an unstarted queued job")
            for identifier in identifiers:
                db.execute("UPDATE jobs SET state='superseded',last_error='configuration_superseded',updated_at=? WHERE id=?",
                           (time.time(), identifier))
                self._audit(db, identifier, "configuration_superseded", {
                    "replacement_config_sha256": replacement_config_hash,
                    "model_called": False})
        return len(identifiers)

    def finish(self, job: dict, *, state: str, receipt_path: str, receipt_hash: str,
               usage: dict, duration_seconds: float, error_code=None, retryable=False):
        if state not in {"succeeded", "success_empty", "quarantined", "blocked", "failed"}:
            raise ValueError("invalid terminal outcome")
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if (row["state"] != "running" or row["lease_token"] != job["lease_token"]
                    or row["lease_until"] <= now):
                raise LostLease("late attempt cannot replace the current result")
            next_state = "queued" if state == "failed" and retryable and row["attempts"] < row["max_attempts"] else state
            db.execute("""UPDATE attempts SET finished_at=?,status=?,error_code=?,duration_seconds=?,
                usage_json=?,receipt_path=?,receipt_hash=? WHERE id=? AND status='running'""",
                       (now, state, error_code, duration_seconds, canonical(usage),
                        receipt_path, receipt_hash, job["lease_token"]))
            db.execute("""UPDATE jobs SET state=?,lease_token=NULL,lease_until=NULL,
                available_at=?,updated_at=?,last_error=?,result_path=?,result_hash=? WHERE id=?""",
                       (next_state, now + min(300, 5 * 2 ** row["attempts"]), now, error_code,
                        receipt_path, receipt_hash, job["id"]))
            self._audit(db, job["id"], "finished", {"state": state, "next_state": next_state,
                                                  "receipt_sha256": receipt_hash})

    def _audit(self, db, job_id, event, payload):
        db.execute("INSERT INTO audit(job_id,at,event,payload_json) VALUES(?,?,?,?)",
                   (job_id, time.time(), event, canonical(payload)))

    def summary(self) -> dict:
        with self.connect() as db:
            states = {row[0]: row[1] for row in db.execute("SELECT state,count(*) FROM jobs GROUP BY state")}
            attempts = [dict(row) for row in db.execute(
                "SELECT status,duration_seconds,usage_json FROM attempts ORDER BY started_at")]
            work_count = db.execute("SELECT count(DISTINCT work_id) FROM jobs").fetchone()[0]
        usage = {}
        for attempt in attempts:
            for key, value in json.loads(attempt["usage_json"] or "{}").items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    usage[key] = usage.get(key, 0) + value
        durations = sorted(row["duration_seconds"] for row in attempts if row["duration_seconds"] is not None)
        return {"schema": "materials-ner-queue-status/1", "jobs": sum(states.values()),
                "works": work_count, "states": states, "attempts": len(attempts), "usage": usage,
                "attempt_seconds_total": sum(durations),
                "attempt_seconds_median": durations[len(durations) // 2] if durations else None,
                "technical_success_is_scientific_acceptance": False,
                "scientific_acceptance": False, "production_writes": False}

    def results(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY work_id,id")]
