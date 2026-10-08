"""SQLite transactions and immutable local artifacts, isolated from production DBs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .contracts import (
    ACTIVE_STATES,
    Completion,
    Failure,
    Heartbeat,
    JobSpec,
    NodeRegistration,
    canonical,
    digest,
)


class ComputeError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class Limits:
    lease_seconds: int = 180
    retry_grace_seconds: int = 60
    max_cpu_cores: int = 2
    max_wall_seconds: int = 300
    max_memory_bytes: int = 2 * 1024**3
    max_artifact_bytes: int = 1024**2
    max_input_bytes: int = 4 * 1024**2
    max_output_bytes: int = 4 * 1024**2
    total_cpu_core_seconds: int = 7200
    total_artifact_bytes: int = 256 * 1024**2
    min_free_bytes: int = 64 * 1024**2
    max_jobs: int = 1000
    max_claim_requests: int = 10000

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in self.__dict__.values()):
            raise ValueError("all compute limits must be positive integers")


DEFAULT_LIMITS = Limits()


class Store:
    def __init__(self, root: Path, limits: Limits = DEFAULT_LIMITS, clock: Callable[[], float] = time.time):
        self.root, self.limits, self.clock = root.absolute(), limits, clock
        # Reject symlink ancestors; all subsequent names are server-generated.
        for path in [self.root, *self.root.parents]:
            if path.is_symlink():
                raise ValueError("compute data path must not contain symlinks")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.stat().st_mode & 0o022:
            raise ValueError("compute data directory must not be group/world writable")
        self.objects = self.root / "objects"
        self.objects.mkdir(mode=0o700, exist_ok=True)
        if self.objects.is_symlink():
            raise ValueError("object store must not be a symlink")
        self.db_path = self.root / "compute.sqlite3"
        if self.db_path.is_symlink():
            raise ValueError("queue DB must not be a symlink")
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY, registration TEXT NOT NULL,
                    drain INTEGER NOT NULL DEFAULT 0, registered_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, spec TEXT NOT NULL, spec_sha TEXT NOT NULL,
                    status TEXT NOT NULL, fence INTEGER NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0, current_attempt TEXT,
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, node_id TEXT NOT NULL,
                    fence INTEGER NOT NULL, status TEXT NOT NULL, lease_until REAL NOT NULL,
                    started_at REAL NOT NULL, phase TEXT NOT NULL DEFAULT 'leased',
                    elapsed_seconds INTEGER NOT NULL DEFAULT 0, memory_bytes INTEGER NOT NULL DEFAULT 0,
                    completion_sha TEXT, receipt TEXT, failure_code TEXT,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id));
                CREATE TABLE IF NOT EXISTS claims (
                    node_id TEXT NOT NULL, request_id TEXT NOT NULL, attempt_id TEXT,
                    PRIMARY KEY(node_id, request_id));
                CREATE TABLE IF NOT EXISTS blobs (
                    sha256 TEXT PRIMARY KEY, bytes INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts (
                    attempt_id TEXT NOT NULL, name TEXT NOT NULL, sha256 TEXT NOT NULL,
                    bytes INTEGER NOT NULL, PRIMARY KEY(attempt_id,name));
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                    kind TEXT NOT NULL, node_id TEXT, job_id TEXT, attempt_id TEXT,
                    payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounting (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    reserved_cpu_core_seconds INTEGER NOT NULL DEFAULT 0);
                INSERT OR IGNORE INTO accounting(singleton) VALUES(1);
                CREATE INDEX IF NOT EXISTS attempts_node ON attempts(node_id,status);
                CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created_at);
            """)
        os.chmod(self.db_path, 0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def event(self, db, kind: str, *, node=None, job=None, attempt=None, payload=None):
        db.execute("INSERT INTO events(at,kind,node_id,job_id,attempt_id,payload) VALUES(?,?,?,?,?,?)",
                   (self.clock(), kind, node, job, attempt, canonical(payload or {}).decode()))

    def put_blob(self, data: bytes, expected_sha: str) -> dict:
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_sha:
            raise ComputeError("artifact_checksum_mismatch", 422)
        if len(data) > self.limits.max_artifact_bytes:
            raise ComputeError("artifact_too_large", 413)
        if shutil.disk_usage(self.root).free - len(data) < self.limits.min_free_bytes:
            raise ComputeError("insufficient_disk", 507)
        path = self.objects / actual
        with self.transaction() as db:
            prior = db.execute("SELECT bytes FROM blobs WHERE sha256=?", (actual,)).fetchone()
            if prior:
                self.read_blob(actual, prior["bytes"])
                return {"sha256": actual, "bytes": len(data)}
            used = db.execute("SELECT COALESCE(SUM(bytes),0) AS used FROM blobs").fetchone()["used"]
            if used + len(data) > self.limits.total_artifact_bytes:
                raise ComputeError("artifact_budget_exceeded", 507)
            if path.exists() or path.is_symlink():
                # Recover a crash after object persistence but before DB commit.
                self.read_blob(actual, len(data))
            else:
                temporary = self.objects / ("pending-" + uuid.uuid4().hex)
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                try:
                    with os.fdopen(fd, "wb") as output:
                        output.write(data)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, path)
                    directory = os.open(self.objects, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                finally:
                    temporary.unlink(missing_ok=True)
            db.execute("INSERT INTO blobs(sha256,bytes) VALUES(?,?)", (actual, len(data)))
        return {"sha256": actual, "bytes": len(data)}

    def read_blob(self, sha: str, expected_bytes: int) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ComputeError("artifact_hash_invalid", 422)
        try:
            fd = os.open(self.objects / sha, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ComputeError("artifact_not_regular", 409)
                data = source.read(self.limits.max_artifact_bytes + 1)
        except OSError as exc:
            raise ComputeError("artifact_unavailable", 409) from exc
        if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != sha:
            raise ComputeError("artifact_corrupted", 409)
        return data

    def register(self, node: str, registration: NodeRegistration):
        payload = canonical(registration.model_dump(mode="json")).decode()
        with self.transaction() as db:
            old = db.execute("SELECT * FROM nodes WHERE node_id=?", (node,)).fetchone()
            if old and old["registration"] != payload:
                raise ComputeError("node_registration_changed", 409)
            if not old:
                db.execute("INSERT INTO nodes(node_id,registration,registered_at) VALUES(?,?,?)", (node, payload, self.clock()))
                self.event(db, "node_registered", node=node)
        return {"node_id": node, "status": "registered_staging", "scientific_authority": False}

    def enqueue(self, spec: JobSpec):
        if (spec.resources.cpu_cores > self.limits.max_cpu_cores
                or spec.resources.wall_seconds > self.limits.max_wall_seconds
                or spec.resources.memory_bytes > self.limits.max_memory_bytes
                or spec.resources.output_bytes > self.limits.max_output_bytes
                or any(rule.max_bytes > self.limits.max_artifact_bytes for rule in spec.output_rules)
                or any(pin.bytes > self.limits.max_artifact_bytes for pin in spec.input_artifacts)
                or sum(pin.bytes for pin in spec.input_artifacts) > self.limits.max_input_bytes):
            raise ComputeError("job_resource_limit", 422)
        if spec.deadline_unix <= self.clock():
            raise ComputeError("job_deadline_elapsed", 422)
        payload = spec.model_dump(mode="json")
        sha = digest(payload)
        with self.transaction() as db:
            old = db.execute("SELECT * FROM jobs WHERE job_id=?", (spec.job_id,)).fetchone()
            if old:
                if old["spec_sha"] != sha:
                    raise ComputeError("job_id_content_changed", 409)
                return self.job_view(old)
            if db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] >= self.limits.max_jobs:
                raise ComputeError("campaign_job_limit", 409)
            for pin in spec.input_artifacts:
                blob = db.execute("SELECT bytes FROM blobs WHERE sha256=?", (pin.sha256,)).fetchone()
                if not blob or blob["bytes"] != pin.bytes:
                    raise ComputeError("input_not_staged", 422)
                self.read_blob(pin.sha256, pin.bytes)
            db.execute("INSERT INTO jobs(job_id,spec,spec_sha,status,created_at) VALUES(?,?,?,?,?)",
                       (spec.job_id, canonical(payload).decode(), sha, "queued", self.clock()))
            self.event(db, "job_queued", job=spec.job_id, payload={"spec_sha256": sha})
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (spec.job_id,)).fetchone()
        return self.job_view(row)

    @staticmethod
    def job_view(row):
        return {key: row[key] for key in ["job_id", "status", "spec_sha", "fence", "attempt_count", "current_attempt"]}

    def _reconcile(self, db):
        now = self.clock()
        for attempt in db.execute("SELECT * FROM attempts WHERE status IN ('leased','preparing','running','uploading') AND lease_until<=?", (now,)).fetchall():
            db.execute("UPDATE attempts SET status='lost',failure_code='lease_expired' WHERE attempt_id=?", (attempt["attempt_id"],))
            db.execute("UPDATE jobs SET status='lost' WHERE job_id=? AND current_attempt=? AND status='leased'", (attempt["job_id"], attempt["attempt_id"]))
            self.event(db, "attempt_lost", node=attempt["node_id"], job=attempt["job_id"], attempt=attempt["attempt_id"])
        for job in db.execute("SELECT * FROM jobs WHERE status='lost'").fetchall():
            attempt = db.execute("SELECT * FROM attempts WHERE attempt_id=?", (job["current_attempt"],)).fetchone()
            if now < attempt["lease_until"] + self.limits.retry_grace_seconds:
                continue
            spec = JobSpec.model_validate_json(job["spec"])
            status = "queued" if job["attempt_count"] < spec.max_attempts and now < spec.deadline_unix else "failed"
            db.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job["job_id"]))
            self.event(db, "lost_attempt_reconciled", job=job["job_id"], attempt=attempt["attempt_id"], payload={"status": status})
        for job in db.execute("SELECT * FROM jobs WHERE status='queued'").fetchall():
            if self.clock() >= JobSpec.model_validate_json(job["spec"]).deadline_unix:
                db.execute("UPDATE jobs SET status='failed' WHERE job_id=?", (job["job_id"],))
                self.event(db, "job_deadline_elapsed", job=job["job_id"])

    def reconcile(self):
        with self.transaction() as db:
            self._reconcile(db)
        return {"status": "reconciled"}

    def claim(self, node: str, request_id: str):
        with self.transaction() as db:
            self._reconcile(db)
            old = db.execute("SELECT * FROM claims WHERE node_id=? AND request_id=?", (node, request_id)).fetchone()
            if old:
                return self._claim_view(db, old["attempt_id"])
            if db.execute("SELECT COUNT(*) FROM claims").fetchone()[0] >= self.limits.max_claim_requests:
                raise ComputeError("campaign_claim_limit", 409)
            registration = db.execute("SELECT * FROM nodes WHERE node_id=?", (node,)).fetchone()
            if not registration:
                raise ComputeError("node_not_registered", 403)
            if registration["drain"]:
                raise ComputeError("node_draining", 409)
            for active in db.execute("SELECT status,lease_until FROM attempts WHERE node_id=?", (node,)).fetchall():
                if active["status"] in ACTIVE_STATES or (active["status"] == "lost" and self.clock() < active["lease_until"] + self.limits.retry_grace_seconds):
                    raise ComputeError("node_busy", 409)
            if db.execute("SELECT 1 FROM jobs j JOIN attempts a ON j.current_attempt=a.attempt_id WHERE j.status='lost' AND a.node_id=? AND a.lease_until+?>?", (node, self.limits.retry_grace_seconds, self.clock())).fetchone():
                raise ComputeError("node_in_retry_grace", 409)
            declared = NodeRegistration.model_validate_json(registration["registration"])
            selected = None
            for row in db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,job_id").fetchall():
                spec = JobSpec.model_validate_json(row["spec"])
                if spec.kind in declared.capabilities and spec.runtime_id == declared.runtime_id:
                    selected = row
                    break
            if selected is None:
                # Empty replies are also durable: retrying this request cannot claim a later job.
                db.execute("INSERT INTO claims(node_id,request_id,attempt_id) VALUES(?,?,NULL)", (node, request_id))
                return {"attempt": None}
            spec = JobSpec.model_validate_json(selected["spec"])
            reserve = spec.resources.cpu_cores * spec.resources.wall_seconds
            used = db.execute("SELECT reserved_cpu_core_seconds FROM accounting WHERE singleton=1").fetchone()[0]
            if used + reserve > self.limits.total_cpu_core_seconds:
                raise ComputeError("campaign_cpu_budget_exceeded", 409)
            attempt_id, fence, now = "attempt-" + uuid.uuid4().hex, selected["fence"] + 1, self.clock()
            lease = min(now + self.limits.lease_seconds, now + spec.resources.wall_seconds, spec.deadline_unix)
            db.execute("INSERT INTO attempts(attempt_id,job_id,node_id,fence,status,lease_until,started_at) VALUES(?,?,?,?,?,?,?)",
                       (attempt_id, spec.job_id, node, fence, "leased", lease, now))
            db.execute("UPDATE jobs SET status='leased',fence=?,attempt_count=attempt_count+1,current_attempt=? WHERE job_id=?",
                       (fence, attempt_id, spec.job_id))
            db.execute("INSERT INTO claims(node_id,request_id,attempt_id) VALUES(?,?,?)", (node, request_id, attempt_id))
            db.execute("UPDATE accounting SET reserved_cpu_core_seconds=reserved_cpu_core_seconds+? WHERE singleton=1", (reserve,))
            self.event(db, "attempt_claimed", node=node, job=spec.job_id, attempt=attempt_id, payload={"fencing_token": fence, "reserved_cpu_core_seconds": reserve})
            return self._claim_view(db, attempt_id)

    def _claim_view(self, db, attempt_id):
        if attempt_id is None:
            return {"attempt": None}
        attempt = db.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        job = db.execute("SELECT * FROM jobs WHERE job_id=?", (attempt["job_id"],)).fetchone()
        return {"attempt": self.attempt_view(attempt), "job": json.loads(job["spec"]), "input_manifest_sha256": JobSpec.model_validate_json(job["spec"]).input_manifest_sha256, "receipt": json.loads(attempt["receipt"]) if attempt["receipt"] else None}

    @staticmethod
    def attempt_view(row):
        return {"attempt_id": row["attempt_id"], "job_id": row["job_id"], "node_id": row["node_id"], "fencing_token": row["fence"], "status": row["status"], "lease_until_unix": row["lease_until"], "started_at_unix": row["started_at"], "elapsed_seconds": row["elapsed_seconds"], "phase": row["phase"]}

    def _owned(self, db, node, attempt_id):
        row = db.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        if not row or row["node_id"] != node:
            raise ComputeError("attempt_not_found", 404)
        return row

    def _live(self, db, attempt, token):
        job = db.execute("SELECT * FROM jobs WHERE job_id=?", (attempt["job_id"],)).fetchone()
        if (attempt["fence"] != token or job["fence"] != token or job["current_attempt"] != attempt["attempt_id"]
                or job["status"] != "leased" or attempt["status"] not in ACTIVE_STATES or self.clock() >= attempt["lease_until"]):
            raise ComputeError("attempt_lease_or_fence_invalid", 409)
        return job

    def get_attempt(self, node, attempt_id):
        with self.transaction() as db:
            self._reconcile(db)
            self._owned(db, node, attempt_id)
            return self._claim_view(db, attempt_id)

    def heartbeat(self, node, attempt_id, beat: Heartbeat):
        with self.transaction() as db:
            self._reconcile(db)
            attempt = self._owned(db, node, attempt_id)
            if attempt["receipt"]:
                return {"continue": False, "receipt": json.loads(attempt["receipt"])}
            try:
                job = self._live(db, attempt, beat.fencing_token)
            except ComputeError:
                return {"continue": False, "cancel": True, "status": attempt["status"]}
            spec = JobSpec.model_validate_json(job["spec"])
            order = ["leased", "preparing", "running", "uploading"]
            if order.index(beat.phase) < order.index(attempt["phase"]):
                raise ComputeError("phase_regression", 409)
            if beat.elapsed_seconds < attempt["elapsed_seconds"] or beat.observed_memory_bytes > spec.resources.memory_bytes:
                raise ComputeError("resource_or_progress_invalid", 422)
            until = min(self.clock() + self.limits.lease_seconds, attempt["started_at"] + spec.resources.wall_seconds, spec.deadline_unix)
            db.execute("UPDATE attempts SET status=?,phase=?,lease_until=?,elapsed_seconds=?,memory_bytes=? WHERE attempt_id=?", (beat.phase, beat.phase, until, beat.elapsed_seconds, beat.observed_memory_bytes, attempt_id))
            drain = db.execute("SELECT drain FROM nodes WHERE node_id=?", (node,)).fetchone()[0]
            return {"continue": True, "cancel": False, "drain": bool(drain), "lease_until_unix": until}

    def input_file(self, node, attempt_id, name, token):
        with self.connection() as db:
            attempt = self._owned(db, node, attempt_id)
            job = self._live(db, attempt, token)
            spec = JobSpec.model_validate_json(job["spec"])
            pin = next((item for item in spec.input_artifacts if item.name == name), None)
            if pin is None:
                raise ComputeError("input_name_not_allowed", 404)
            return self.read_blob(pin.sha256, pin.bytes)

    def output_rule(self, node, attempt_id, name, token):
        with self.connection() as db:
            attempt = self._owned(db, node, attempt_id)
            if attempt["fence"] != token:
                raise ComputeError("attempt_fence_invalid", 409)
            job = db.execute("SELECT * FROM jobs WHERE job_id=?", (attempt["job_id"],)).fetchone()
            spec = JobSpec.model_validate_json(job["spec"])
            rule = next((item for item in spec.output_rules if item.name == name), None)
            if rule is None:
                raise ComputeError("output_name_not_allowed", 422)
            return rule

    def attach_output(self, node, attempt_id, name, token, data, expected_sha):
        rule = self.output_rule(node, attempt_id, name, token)
        if len(data) > rule.max_bytes:
            raise ComputeError("output_too_large", 413)
        pin = self.put_blob(data, expected_sha)
        with self.transaction() as db:
            attempt = self._owned(db, node, attempt_id)
            if attempt["fence"] != token:
                raise ComputeError("attempt_fence_invalid", 409)
            old = db.execute("SELECT * FROM artifacts WHERE attempt_id=? AND name=?", (attempt_id, name)).fetchone()
            if old and (old["sha256"] != expected_sha or old["bytes"] != len(data)):
                raise ComputeError("immutable_artifact_changed", 409)
            if not old:
                job = db.execute("SELECT spec FROM jobs WHERE job_id=?", (attempt["job_id"],)).fetchone()
                spec = JobSpec.model_validate_json(job["spec"])
                used = db.execute("SELECT COALESCE(SUM(bytes),0) FROM artifacts WHERE attempt_id=?", (attempt_id,)).fetchone()[0]
                if used + len(data) > spec.resources.output_bytes:
                    raise ComputeError("attempt_output_budget_exceeded", 413)
                db.execute("INSERT INTO artifacts(attempt_id,name,sha256,bytes) VALUES(?,?,?,?)", (attempt_id, name, expected_sha, len(data)))
                self.event(db, "artifact_staged", node=node, job=attempt["job_id"], attempt=attempt_id, payload={"name": name, **pin})
        return pin

    def complete(self, node, attempt_id, completion: Completion):
        complete_sha = digest(completion.model_dump(mode="json"))
        with self.transaction() as db:
            self._reconcile(db)
            attempt = self._owned(db, node, attempt_id)
            if attempt["fence"] != completion.fencing_token:
                raise ComputeError("attempt_fence_invalid", 409)
            if attempt["receipt"]:
                if attempt["completion_sha"] != complete_sha:
                    raise ComputeError("completion_id_content_changed", 409)
                return json.loads(attempt["receipt"])
            job = db.execute("SELECT * FROM jobs WHERE job_id=?", (attempt["job_id"],)).fetchone()
            spec = JobSpec.model_validate_json(job["spec"])
            reason = None
            try:
                self._live(db, attempt, completion.fencing_token)
            except ComputeError:
                reason = "stale_attempt"
            if completion.input_manifest_sha256 != spec.input_manifest_sha256 or completion.runtime_id != spec.runtime_id:
                reason = "input_or_runtime_mismatch"
            if completion.elapsed_seconds > spec.resources.wall_seconds:
                reason = "reported_resource_limit_exceeded"
            declared = {item.name: item for item in completion.manifest}
            staged = db.execute("SELECT * FROM artifacts WHERE attempt_id=?", (attempt_id,)).fetchall()
            if set(declared) != {item.name for item in spec.output_rules} or set(declared) != {item["name"] for item in staged}:
                raise ComputeError("output_manifest_incomplete", 422)
            for row in staged:
                pin = declared[row["name"]]
                if pin.sha256 != row["sha256"] or pin.bytes != row["bytes"]:
                    raise ComputeError("output_manifest_mismatch", 422)
                self.read_blob(pin.sha256, pin.bytes)
            status = "quarantined" if reason else "returned"
            receipt = {"schema_version": "sclib-compute-receipt/1", "attempt_id": attempt_id, "job_id": spec.job_id, "node_id": node, "fencing_token": attempt["fence"], "status": status, "reason": reason, "completion_sha256": complete_sha, "input_manifest_sha256": spec.input_manifest_sha256, "manifest_sha256": digest([pin.model_dump(mode="json") for pin in completion.manifest]), "received_at_unix": self.clock(), "solver_outcome": completion.solver_outcome, "scientific_status": "not_assessed", "scientific_publication_authority": False, "production_database_access": False}
            db.execute("UPDATE attempts SET status=?,completion_sha=?,receipt=? WHERE attempt_id=?", (status, complete_sha, canonical(receipt).decode(), attempt_id))
            if not reason:
                db.execute("UPDATE jobs SET status='returned' WHERE job_id=?", (spec.job_id,))
            elif reason != "stale_attempt" and job["current_attempt"] == attempt_id:
                db.execute("UPDATE jobs SET status='failed',fence=fence+1 WHERE job_id=?", (spec.job_id,))
            self.event(db, "result_" + status, node=node, job=spec.job_id, attempt=attempt_id, payload={"completion_sha256": complete_sha, "reason": reason})
            return receipt

    def fail(self, node, attempt_id, failure: Failure):
        recoverable = failure.code in {"download_interrupted", "upload_interrupted", "worker_crash", "execution_timeout"}
        with self.transaction() as db:
            self._reconcile(db)
            attempt = self._owned(db, node, attempt_id)
            job = self._live(db, attempt, failure.fencing_token)
            spec = JobSpec.model_validate_json(job["spec"])
            db.execute("UPDATE attempts SET status='failed',failure_code=? WHERE attempt_id=?", (failure.code, attempt_id))
            status = "queued" if recoverable and job["attempt_count"] < spec.max_attempts and self.clock() < spec.deadline_unix else "failed"
            db.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, spec.job_id))
            self.event(db, "attempt_failed", node=node, job=spec.job_id, attempt=attempt_id, payload={"code": failure.code, "retry": status == "queued"})
            return {"status": status, "attempt_status": "failed"}

    def cancel(self, job_id):
        with self.transaction() as db:
            job = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not job:
                raise ComputeError("job_not_found", 404)
            if job["status"] == "returned":
                raise ComputeError("job_already_returned", 409)
            if job["status"] == "cancelled":
                return {"status": "cancelled"}
            db.execute("UPDATE jobs SET status='cancelled',fence=fence+1 WHERE job_id=?", (job_id,))
            if job["current_attempt"]:
                db.execute("UPDATE attempts SET status='cancelled' WHERE attempt_id=? AND receipt IS NULL", (job["current_attempt"],))
            self.event(db, "job_cancelled", job=job_id, attempt=job["current_attempt"])
        return {"status": "cancelled"}

    def drain(self, node, enabled):
        with self.transaction() as db:
            changed = db.execute("UPDATE nodes SET drain=? WHERE node_id=?", (int(enabled), node)).rowcount
            if not changed:
                raise ComputeError("node_not_found", 404)
            self.event(db, "node_drain_changed", node=node, payload={"enabled": enabled})
        return {"node_id": node, "drain": enabled}

    def status(self):
        with self.connection() as db:
            counts = {row["status"]: row["n"] for row in db.execute("SELECT status,COUNT(*) AS n FROM jobs GROUP BY status")}
            reserved = db.execute("SELECT reserved_cpu_core_seconds FROM accounting WHERE singleton=1").fetchone()[0]
            return {"schema_version": "sclib-compute-status/1", "jobs": counts, "reserved_cpu_core_seconds": reserved, "scientific_status": "not_assessed", "production_database_access": False}

    def events(self, node, after):
        with self.connection() as db:
            query, args = "SELECT * FROM events WHERE seq>?", [after]
            if node is not None:
                query += " AND node_id=?"
                args.append(node)
            rows = db.execute(query + " ORDER BY seq LIMIT 100", args).fetchall()
            return {"events": [{**dict(row), "payload": json.loads(row["payload"])} for row in rows], "cursor": rows[-1]["seq"] if rows else after}
