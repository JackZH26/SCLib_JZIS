"""Closed measurements of one owned synthetic index migration, not an SLA.

Importing the contract never initializes application settings, a tokenizer, a
database, a provider or a network client. Existing receipt versions stay frozen.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import secrets
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import schema_rehearsal_report as legacy

VERSION = "index-migration-rehearsal/1.0.0"
STAGE_VERSION = "index-migration-stage/1.0.0"
SCOPE = "owned_synthetic_chunking_and_index_migration_measurement"
STAGES = ("migrate", "measure")
DURATIONS = ("setup", "migrate", "measure", "cleanup")
MAX_BYTES = 1024 * 1024
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_DURATION_MS = 60 * 60 * 1000
BASELINE_PATH = "scripts/fixtures/index_migration_legacy_chunker_44fd6ce.py.txt"
BASELINE_SHA256 = "43ee1e764a32fd39ac3c7f13c99bf94e525a54ab11a46ad4be0ea36336435139"
AUTHORITY = {key: False for key in ("scientific_acceptance", "ml_training_approved",
    "public_release_authorized", "deployment_approved", "production_sla_established")}
UNMEASURED = {key: None for key in ("production_coverage", "scientific_recall", "scientific_precision",
    "real_embedding_provider_tokens", "real_embedding_provider_cost_usd", "real_ann_latency_ms",
    "production_index_cleanup", "production_throughput", "production_rpo_seconds", "production_rto_seconds")}
REQUIRED_INPUTS = frozenset({
    "scripts/index_migration_contract.py", "scripts/index_migration_corpus.py", "scripts/index_migration_protocol.py",
    "scripts/index_migration_worker.py", "scripts/run_index_migration_rehearsal.py", "scripts/run_disposable_tests.py",
    "scripts/test_safety.py", "scripts/schema_rehearsal_report.py", "scripts/research_restore_worker.py",
    "api/models/db.py", "api/config.py", "api/uv.lock", "api/pyproject.toml", "api/alembic.ini",
    "api/services/index_generations.py", "api/services/index_vector_adapter.py", "api/services/index_retrieval.py",
    "api/services/answer_evidence.py", "api/services/research_freeze.py", "api/models/answer_evidence_v1.py",
    "ingestion/ingestion/chunk/chunker.py", "ingestion/ingestion/embedding_contract.py",
    "ingestion/ingestion/extract/fact_sentences.py", "ingestion/ingestion/index/indexer.py", BASELINE_PATH,
})


class IndexMigrationError(ValueError):
    """Static diagnostics only; no source, DSN, private path or driver text."""


def require(condition, code="invalid_index_migration_measurement"):
    if not condition:
        raise IndexMigrationError(code)


def canonical(value):
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        require(count <= 100000 and depth <= 32, "index_measurement_json_resource_limit")
        if type(item) is dict:
            require(all(type(key) is str for key in item), "invalid_index_measurement_json")
            pending.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        else:
            require(item is None or type(item) in {str, int, float, bool}, "invalid_index_measurement_json")
        require(count + len(pending) <= 100000, "index_measurement_json_resource_limit")
    try:
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        require(len(payload) <= MAX_BYTES, "index_measurement_byte_limit")
        return payload
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as exc:
        if isinstance(exc, IndexMigrationError):
            raise
        raise IndexMigrationError("invalid_index_measurement_json") from None


def sha(payload):
    require(type(payload) is bytes)
    return hashlib.sha256(payload).hexdigest()


def _keys(value, keys):
    require(type(value) is dict and set(value) == set(keys), "invalid_index_measurement_shape")


def _hash(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "invalid_index_measurement_hash")


def _int(value, maximum=2**63 - 1, *, positive=False):
    require(type(value) is int and (1 if positive else 0) <= value <= maximum, "invalid_index_measurement_integer")


def _run(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value), "invalid_index_measurement_run")


def _schema(value):
    require(type(value) is str and re.fullmatch(r"[0-9]{4}_[a-z0-9_]{1,100}", value), "invalid_index_measurement_schema")


def _timestamp(value):
    require(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", value), "invalid_index_measurement_time")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        raise IndexMigrationError("invalid_index_measurement_time") from None


def _json(payload):
    require(type(payload) is bytes and 0 < len(payload) <= MAX_BYTES, "index_measurement_byte_limit")
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_index_measurement_key")
            result[key] = value
        return result
    def constant(_value):
        raise IndexMigrationError("nonfinite_index_measurement_number")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        canonical(value)
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        if isinstance(exc, IndexMigrationError):
            raise
        raise IndexMigrationError("invalid_index_measurement_json") from None


def validate_stage(value, stage):
    require(stage in STAGES, "invalid_index_measurement_stage")
    _keys(value, ("version", "stage", "run_id", "status", "schema_revision", "measurement"))
    require(value["version"] == STAGE_VERSION and value["stage"] == stage and value["status"] == "passed")
    _run(value["run_id"])
    _schema(value["schema_revision"])
    if stage == "migrate":
        require(value["measurement"] is None)
    else:
        _keys(value["measurement"], ("corpus", "migration"))
        # Validators remain standard-library-only. Application/tokenizer work
        # belongs in the capability-guarded worker, never report consumption.
        from index_migration_corpus import validate_corpus_report
        from index_migration_protocol import validate_migration_report
        validate_corpus_report(value["measurement"]["corpus"])
        migration = validate_migration_report(value["measurement"]["migration"])
        require(migration["run_id"] == value["run_id"] and migration["schema_revision"] == value["schema_revision"],
            "crossed_index_measurement_identity")
    canonical(value)
    return value


def loads_stage(payload, stage):
    return validate_stage(_json(payload), stage)


def read_private_stage(path, stage):
    """Bounded nonblocking receipt admission, including hostile FIFO leaves."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            require(stat.S_ISREG(before.st_mode) and stat.S_IMODE(before.st_mode) == 0o600
                and before.st_nlink == 1 and before.st_uid == os.getuid()
                and 1 <= before.st_size <= MAX_BYTES, "unsafe_private_index_stage")
            payload = handle.read(MAX_BYTES + 1)
            after = os.fstat(handle.fileno())
        require(legacy._stable_stat(before) == legacy._stable_stat(after) and len(payload) == before.st_size,
            "private_index_stage_changed")
        return loads_stage(payload, stage)
    except OSError:
        raise IndexMigrationError("private_index_stage_unavailable") from None


def _provenance(value):
    _keys(value, ("head_revision", "dirty_worktree", "source_dirty", "tracked_diff_sha256", "inputs",
                  "inputs_sha256", "unchanged_during_rehearsal"))
    require(type(value["head_revision"]) is str and re.fullmatch(r"[0-9a-f]{40}", value["head_revision"]))
    require(type(value["dirty_worktree"]) is bool and type(value["source_dirty"]) is bool
        and value["unchanged_during_rehearsal"] is True)
    _hash(value["tracked_diff_sha256"])
    _hash(value["inputs_sha256"])
    inputs = value["inputs"]
    require(type(inputs) is list and 1 <= len(inputs) <= 2048)
    paths, total = [], 0
    for item in inputs:
        _keys(item, ("path", "sha256", "size_bytes"))
        path = item["path"]
        require(type(path) is str and len(path) <= 250 and ".." not in Path(path).parts
            and re.fullmatch(r"(?:api|scripts|ingestion)/[A-Za-z0-9_./-]+", path))
        require(path.endswith(".py") or path in {"api/uv.lock", "api/pyproject.toml", "api/alembic.ini",
            "ingestion/uv.lock", "ingestion/pyproject.toml", BASELINE_PATH})
        _hash(item["sha256"])
        _int(item["size_bytes"], 4 * MAX_BYTES)
        paths.append(path)
        total += item["size_bytes"]
        if path == BASELINE_PATH:
            require(item["sha256"] == BASELINE_SHA256, "index_baseline_source_changed")
    require(paths == sorted(set(paths)) and REQUIRED_INPUTS <= set(paths) and total <= MAX_INPUT_BYTES)
    require(value["inputs_sha256"] == sha(canonical(inputs)), "index_source_inventory_hash_mismatch")


def _source_file(repo, path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= 4 * MAX_BYTES, "index_source_file_limit")
        payload = handle.read(4 * MAX_BYTES + 1)
        after = os.fstat(handle.fileno())
    require(legacy._stable_stat(before) == legacy._stable_stat(after) and len(payload) == before.st_size,
        "index_source_file_changed")
    return {"path": str(path.relative_to(repo)), "size_bytes": len(payload), "sha256": sha(payload)}


def capture_provenance(repo):
    repo = Path(repo)
    try:
        inputs, total = [], 0
        for label in ("api", "scripts", "ingestion"):
            root = repo / label
            require(root.is_dir() and not root.is_symlink(), "index_source_directory_unavailable")
            config_names = {"uv.lock", "pyproject.toml", "alembic.ini"} if label == "api" else {"uv.lock", "pyproject.toml"} if label == "ingestion" else set()
            for parent, directories, files in os.walk(root, followlinks=False):
                directories[:] = sorted(name for name in directories if not name.startswith(".") and name not in {"__pycache__", "node_modules"})
                require(not any((Path(parent) / name).is_symlink() for name in directories), "index_source_directory_symlink")
                for name in sorted(files):
                    if name.endswith(".py") or Path(parent) == root and name in config_names:
                        item = _source_file(repo, Path(parent) / name)
                        inputs.append(item)
                        total += item["size_bytes"]
                        require(len(inputs) <= 2048 and total <= MAX_INPUT_BYTES, "index_source_inventory_limit")
        # Its .txt suffix keeps the deliberately unmodified historical source
        # out of automatic module import/lint; the exact bytes are still pinned.
        require(not (repo / "scripts/fixtures").is_symlink(), "index_source_directory_symlink")
        inputs.append(_source_file(repo, repo / BASELINE_PATH))
        inputs.sort(key=lambda item: item["path"])
        environment = {"PATH": os.defpath, "LANG": "C"}
        def git(*args):
            return subprocess.run(["git", *args], cwd=repo, env=environment, capture_output=True,
                check=True, timeout=10).stdout
        value = {"head_revision": git("rev-parse", "HEAD").decode().strip(),
            "dirty_worktree": bool(git("status", "--porcelain", "--untracked-files=all")),
            "source_dirty": bool(git("status", "--porcelain", "--untracked-files=all", "--", "api", "scripts", "ingestion")),
            "tracked_diff_sha256": sha(git("diff", "HEAD", "--binary", "--", "api", "scripts", "ingestion")),
            "inputs": inputs, "inputs_sha256": sha(canonical(inputs)), "unchanged_during_rehearsal": True}
        _provenance(value)
        return value
    except (OSError, subprocess.SubprocessError, legacy.ReportError):
        raise IndexMigrationError("index_source_provenance_unavailable") from None


def source_unchanged(before, after):
    _provenance(before)
    _provenance(after)
    try:
        legacy.source_unchanged(before, after)
    except legacy.ReportError:
        raise IndexMigrationError("index_source_changed_during_measurement") from None


def validate_report(value):
    _keys(value, ("version", "scope", "status", "synthetic", "production", "run_id", "authority", "runtime",
        "started_at", "completed_at", "duration_ms", "phase_durations_ms", "stages", "provenance", "unmeasured",
        "cleanup_verified", "report_sha256"))
    require(value["version"] == VERSION and value["scope"] == SCOPE and value["status"] == "measured")
    require(value["synthetic"] is True and value["production"] is False and value["cleanup_verified"] is True)
    _run(value["run_id"])
    _keys(value["authority"], AUTHORITY)
    require(all(item is False for item in value["authority"].values()), "index_measurement_is_not_authority")
    _keys(value["unmeasured"], UNMEASURED)
    require(all(item is None for item in value["unmeasured"].values()), "unmeasured_index_metrics_must_remain_unknown")
    _keys(value["runtime"], ("backend", "python", "implementation", "system", "machine", "postgres_version_num"))
    require(value["runtime"]["backend"] in {"native", "docker"})
    for key in ("python", "implementation", "system", "machine"):
        label = value["runtime"][key]
        require(type(label) is str and re.fullmatch(r"[A-Za-z0-9._+-]{1,120}", label))
    _int(value["runtime"]["postgres_version_num"], 999999, positive=True)
    start, end = _timestamp(value["started_at"]), _timestamp(value["completed_at"])
    require(end >= start and (end - start).total_seconds() <= 3600)
    _int(value["duration_ms"], MAX_DURATION_MS, positive=True)
    _keys(value["phase_durations_ms"], DURATIONS)
    for duration in value["phase_durations_ms"].values():
        _int(duration, MAX_DURATION_MS)
    require(sum(value["phase_durations_ms"].values()) <= value["duration_ms"])
    stages = value["stages"]
    require(type(stages) is list and len(stages) == 2)
    for stage, label in zip(stages, STAGES, strict=True):
        validate_stage(stage, label)
        require(stage["run_id"] == value["run_id"], "crossed_index_measurement_run")
    require(stages[0]["schema_revision"] == stages[1]["schema_revision"], "crossed_index_measurement_schema")
    _provenance(value["provenance"])
    _hash(value["report_sha256"])
    require(value["report_sha256"] == sha(canonical({key: item for key, item in value.items() if key != "report_sha256"})),
        "index_measurement_report_hash_mismatch")
    canonical(value)
    return value


def build_report(*, provenance, backend, postgres_version_num, started_at, completed_at, duration_ms,
                 phase_durations_ms, stages, cleanup_verified):
    require(type(stages) is dict and set(stages) == set(STAGES))
    document = {"version": VERSION, "scope": SCOPE, "status": "measured", "synthetic": True, "production": False,
        "run_id": stages["migrate"]["run_id"], "authority": dict(AUTHORITY),
        "runtime": {"backend": backend, "python": platform.python_version(), "implementation": platform.python_implementation(),
            "system": platform.system(), "machine": platform.machine(), "postgres_version_num": postgres_version_num},
        "started_at": started_at, "completed_at": completed_at, "duration_ms": duration_ms,
        "phase_durations_ms": phase_durations_ms, "stages": [stages[label] for label in STAGES],
        "provenance": provenance, "unmeasured": dict(UNMEASURED), "cleanup_verified": cleanup_verified}
    document["report_sha256"] = sha(canonical(document))
    return validate_report(document)


def loads_report(payload):
    return validate_report(_json(payload))


class IndexMigrationDestination(legacy.ReportDestination):
    """Held-directory, no-clobber publication of this report or one private stage."""
    def publish(self, document, *, stage=None):
        checked = validate_report(document) if stage is None else validate_stage(document, stage)
        payload = canonical(checked) + b"\n"
        require(len(payload) <= MAX_BYTES, "index_measurement_byte_limit")
        self.recheck()
        name = ".sclib-index-measurement-" + secrets.token_hex(16) + ".tmp"
        fd, identity = None, None
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            os.fchmod(fd, 0o600)
            info = os.fstat(fd)
            identity = (info.st_dev, info.st_ino)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unsafe_index_measurement_file")
            with os.fdopen(fd, "wb") as handle:
                fd = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            self.recheck()
            os.link(name, self.path.name, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
            os.unlink(name, dir_fd=self.fd)
            os.fsync(self.fd)
        except BaseException as exc:
            if identity is not None:
                for leaf in (name, self.path.name):
                    try:
                        info = os.stat(leaf, dir_fd=self.fd, follow_symlinks=False)
                        if (info.st_dev, info.st_ino) == identity:
                            os.unlink(leaf, dir_fd=self.fd)
                    except OSError:
                        pass
            if not isinstance(exc, Exception):
                raise
            raise IndexMigrationError("index_measurement_publication_failed") from None
        finally:
            if fd is not None:
                os.close(fd)


def write_stage(root, value):
    require(type(value) is dict and value.get("stage") in STAGES)
    destination = IndexMigrationDestination(Path(root) / ("index-migration-" + value["stage"] + ".json"))
    try:
        destination.publish(value, stage=value["stage"])
    finally:
        destination.close()
