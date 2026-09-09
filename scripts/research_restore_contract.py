"""Closed technical recovery receipts and bounded private capsule transport.

No database, network, provider or subprocess is contacted merely by importing
this module. An archived success describes owned synthetic services only.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import secrets
import stat
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import schema_rehearsal_report as legacy

VERSION = "research-restore-rehearsal/1.0.0"
SCOPE = "owned_synthetic_postgres_and_research_artifact_restore"
STAGE_VERSION = "research-restore-stage/1.0.0"
DESCRIPTOR_VERSION = "synthetic-research-restore-source/1.0.0"
FIXTURE_VERSION = "sclib-research-restore-fixture/1.0.0"
MAX_REPORT_BYTES = 1024 * 1024
MAX_DESCRIPTOR_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_ARTIFACTS = 200
MAX_SQL_TABLES = 512
MAX_SQL_ROWS = 20000
MAX_SQL_BYTES = 32 * 1024 * 1024
MAX_DURATION_MS = 24 * 60 * 60 * 1000
STAGES = ("migrate", "seed", "verify", "source-check")
PHASES = ("source_migrate", "source_seed", "target_verify", "source_check")
DURATIONS = ("migrate", "seed", "dump", "copy", "restore", "verify", "source_check", "cleanup")
MEASUREMENTS = ("sql_tables", "sql_rows", "artifact_count", "artifact_bytes", "index_members")
AUTHORITY = {key: False for key in ("production_recovery_approved", "deployment_approved",
    "scientific_acceptance", "ml_training_approved", "public_release_authorized")}
UNMEASURED = {key: None for key in ("production_rpo_seconds", "production_rto_seconds",
    "production_backup_completeness", "production_restore", "production_roles_and_secrets",
    "external_vector_service_restore", "corpus_scale_performance", "scientific_validity")}
CHECKS = {
    "migrate": ("capability_verified", "guard_identity_verified", "alembic_head_applied", "schema_head_verified"),
    "seed": ("capability_verified", "guard_identity_verified", "synthetic_rows_seeded", "release_and_pins_verified",
        "complete_artifact_bytes_verified", "restricted_access_verified", "metadata_publication_verified",
        "index_generation_seeded", "sql_snapshot_recorded", "source_descriptor_written"),
    "verify": ("capability_verified", "guard_identity_verified", "restored_sql_snapshot_matches",
        "release_and_pins_verified", "complete_artifact_bytes_verified", "restricted_access_verified",
        "metadata_publication_verified", "index_rebuild_verified", "index_rebuild_idempotent",
        "exact_index_hydration_verified", "sql_snapshot_unchanged"),
    "source-check": ("capability_verified", "guard_identity_verified", "source_sql_snapshot_unchanged",
        "release_and_pins_verified", "complete_artifact_bytes_verified", "source_bundle_unchanged"),
}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_RUN = re.compile(r"[0-9a-f]{32}\Z")
_SCHEMA = re.compile(r"[0-9]{4}_[a-z0-9_]{1,100}\Z")
_LABEL = re.compile(r"[A-Za-z0-9._+-]{1,120}\Z")
_TRANSFER = ("descriptor_sha256", "manifest_sha256", "bundle_sha256", "artifact_count", "artifact_bytes", "dump_sha256", "dump_bytes")
_SOURCE_FILES = frozenset({"scripts/research_restore_contract.py", "scripts/run_research_restore_rehearsal.py",
    "scripts/research_restore_worker.py", "scripts/research_restore_index.py", "scripts/test_safety.py",
    "scripts/run_disposable_tests.py", "scripts/schema_rehearsal_report.py", "api/models/db.py",
    "api/config.py", "api/uv.lock", "api/pyproject.toml", "api/alembic.ini",
    "api/services/research_release_manifest.py", "api/services/research_freeze.py"})


class RestoreContractError(ValueError):
    """Static reason codes only; never disclose input text, paths or credentials."""


def require(condition, code="invalid_restore_contract"):
    if not condition:
        raise RestoreContractError(code)


def canonical(value):
    """Bound JSON resources before serializing; booleans stay distinct numbers."""
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        require(count <= 250000 and depth <= 48, "restore_json_resource_limit")
        if type(item) is dict:
            require(all(type(key) is str for key in item), "invalid_restore_json")
            pending.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        else:
            require(item is None or type(item) in {str, int, bool, float}, "invalid_restore_json")
        require(count + len(pending) <= 250000, "restore_json_resource_limit")
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise RestoreContractError("invalid_restore_json") from None


def sha(payload):
    require(type(payload) is bytes)
    return hashlib.sha256(payload).hexdigest()


def _keys(value, keys):
    require(type(value) is dict and set(value) == set(keys), "invalid_restore_shape")


def _hash(value):
    require(type(value) is str and _HASH.fullmatch(value) is not None, "invalid_restore_hash")


def _int(value, maximum=2**63 - 1, *, positive=False):
    require(type(value) is int and (1 if positive else 0) <= value <= maximum, "invalid_restore_integer")


def _uuid(value):
    try:
        require(type(value) is str and str(UUID(value)) == value, "invalid_restore_identity")
    except ValueError:
        raise RestoreContractError("invalid_restore_identity") from None


def _run(value):
    require(type(value) is str and _RUN.fullmatch(value) is not None, "invalid_restore_run")


def _schema(value):
    require(type(value) is str and _SCHEMA.fullmatch(value) is not None, "invalid_restore_schema")


def _time(value):
    require(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", value), "invalid_restore_time")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        raise RestoreContractError("invalid_restore_time") from None


def _json(payload, maximum):
    require(type(payload) is bytes and 0 < len(payload) <= maximum, "restore_json_byte_limit")
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_restore_json_key")
            result[key] = value
        return result
    def bad(_value):
        raise RestoreContractError("nonfinite_restore_json")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=bad)
        canonical(value)
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        if isinstance(exc, RestoreContractError):
            raise
        raise RestoreContractError("invalid_restore_json") from None


def validate_stage(value, stage):
    require(stage in STAGES, "invalid_restore_stage")
    _keys(value, ("version", "stage", "run_id", "status", "schema_revision", "descriptor_sha256",
                  "sql_snapshot_sha256", "index_check", "checks", "measurements"))
    require(value["version"] == STAGE_VERSION and value["stage"] == stage and value["status"] == "passed", "invalid_restore_stage")
    _run(value["run_id"])
    _schema(value["schema_revision"])
    require(type(value["checks"]) is list and value["checks"] == list(CHECKS[stage]), "incomplete_restore_checks")
    _keys(value["measurements"], MEASUREMENTS)
    limits = {"sql_tables": MAX_SQL_TABLES, "sql_rows": MAX_SQL_ROWS, "artifact_count": MAX_ARTIFACTS,
              "artifact_bytes": MAX_BUNDLE_BYTES, "index_members": 1000}
    for key, maximum in limits.items():
        _int(value["measurements"][key], maximum, positive=stage != "migrate")
    if stage == "migrate":
        require(value["descriptor_sha256"] is None and value["sql_snapshot_sha256"] is None
                and all(number == 0 for number in value["measurements"].values()), "invalid_restore_migration_stage")
    else:
        _hash(value["descriptor_sha256"])
        _hash(value["sql_snapshot_sha256"])
    if stage == "verify":
        try:
            from research_restore_index import validate_report as validate_index
            validate_index(value["index_check"])
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RestoreContractError("invalid_restore_index_check") from None
        require(value["index_check"]["member_count"] == value["measurements"]["index_members"], "restore_index_count_mismatch")
    else:
        require(value["index_check"] is None, "unexpected_restore_index_check")
    require(len(canonical(value)) <= MAX_REPORT_BYTES, "restore_report_size_limit")
    return value


def loads_stage(payload, stage):
    value = _json(payload, MAX_REPORT_BYTES)
    require(payload == canonical(value), "noncanonical_restore_stage")
    return validate_stage(value, stage)


def _provenance(value):
    _keys(value, ("head_revision", "dirty_worktree", "source_dirty", "tracked_diff_sha256", "inputs", "inputs_sha256", "unchanged_during_rehearsal"))
    require(type(value["head_revision"]) is str and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value["head_revision"]), "invalid_restore_revision")
    require(type(value["dirty_worktree"]) is bool and type(value["source_dirty"]) is bool
            and value["unchanged_during_rehearsal"] is True, "restore_source_changed")
    _hash(value["tracked_diff_sha256"])
    inputs = value["inputs"]
    require(type(inputs) is list and 1 <= len(inputs) <= legacy.MAX_FILES, "invalid_restore_inputs")
    paths, total = [], 0
    for item in inputs:
        _keys(item, ("path", "sha256", "size_bytes"))
        path = item["path"]
        require(type(path) is str and re.fullmatch(r"(?:api|scripts)/[A-Za-z0-9_./-]{1,240}", path)
                and all(part not in {"", ".", ".."} for part in path.split("/")), "invalid_restore_input_path")
        require(path.endswith(".py") or path in {"api/uv.lock", "api/pyproject.toml", "api/alembic.ini"}, "invalid_restore_input_path")
        _hash(item["sha256"])
        _int(item["size_bytes"], 4 * 1024 * 1024)
        total += item["size_bytes"]
        paths.append(path)
    require(paths == sorted(set(paths)) and _SOURCE_FILES <= set(paths) and total <= MAX_BUNDLE_BYTES
            and value["inputs_sha256"] == sha(canonical(inputs)), "invalid_restore_inputs")


def capture_provenance(repo):
    try:
        value = legacy.capture_provenance(repo)
        _provenance(value)
        return value
    except legacy.ReportError:
        raise RestoreContractError("restore_provenance_unavailable") from None


def source_unchanged(before, after):
    _provenance(before)
    _provenance(after)
    try:
        legacy.source_unchanged(before, after)
    except legacy.ReportError:
        raise RestoreContractError("restore_source_changed") from None


def seal(value):
    body = {key: item for key, item in value.items() if key != "report_sha256"}
    return {**body, "report_sha256": sha(canonical(body))}


def validate_report(value, *, internal=False):
    _keys(value, ("version", "scope", "synthetic", "production", "authority", "cleanup_verified",
        "started_at", "completed_at", "duration_ms", "runtime", "provenance", "source_run_id",
        "target_run_id", "schema_revision", "stages", "durations_ms", "transfer", "unmeasured", "report_sha256"))
    require(value["version"] == VERSION and value["scope"] == SCOPE, "invalid_restore_version")
    require(value["synthetic"] is True and value["production"] is False, "invalid_restore_authority")
    _keys(value["authority"], AUTHORITY)
    require(all(item is False for item in value["authority"].values()), "invalid_restore_authority")
    require(type(value["cleanup_verified"]) is bool and (internal or value["cleanup_verified"] is True), "restore_cleanup_unverified")
    require(_time(value["completed_at"]) >= _time(value["started_at"]), "invalid_restore_time")
    _int(value["duration_ms"], MAX_DURATION_MS)
    _keys(value["durations_ms"], DURATIONS)
    for duration in value["durations_ms"].values():
        _int(duration, MAX_DURATION_MS)
    require(sum(value["durations_ms"].values()) <= value["duration_ms"], "restore_duration_double_counted")
    runtime = value["runtime"]
    _keys(runtime, ("backend", "python", "implementation", "system", "machine", "source_postgres_version_num", "target_postgres_version_num"))
    require(type(runtime["backend"]) is str and runtime["backend"] in {"native", "docker"}, "invalid_restore_runtime")
    for key in ("python", "implementation", "system", "machine"):
        require(type(runtime[key]) is str and _LABEL.fullmatch(runtime[key]), "invalid_restore_runtime")
    for key in ("source_postgres_version_num", "target_postgres_version_num"):
        _int(runtime[key], 999999, positive=True)
    require(runtime["source_postgres_version_num"] == runtime["target_postgres_version_num"], "restore_runtime_mismatch")
    _provenance(value["provenance"])
    _run(value["source_run_id"])
    _run(value["target_run_id"])
    require(value["source_run_id"] != value["target_run_id"], "restore_service_identity_collision")
    _schema(value["schema_revision"])
    stages = value["stages"]
    require(type(stages) is list and len(stages) == 4, "invalid_restore_stages")
    for item, phase, stage in zip(stages, PHASES, STAGES):
        _keys(item, ("phase", "result"))
        require(item["phase"] == phase, "invalid_restore_stages")
        result = validate_stage(item["result"], stage)
        expected_run = value["target_run_id"] if stage == "verify" else value["source_run_id"]
        require(result["run_id"] == expected_run and result["schema_revision"] == value["schema_revision"], "restore_stage_identity_mismatch")
    transfer = value["transfer"]
    _keys(transfer, _TRANSFER)
    for key in ("descriptor_sha256", "manifest_sha256", "bundle_sha256", "dump_sha256"):
        _hash(transfer[key])
    _int(transfer["dump_bytes"], 256 * 1024 * 1024, positive=True)
    _int(transfer["artifact_count"], MAX_ARTIFACTS, positive=True)
    _int(transfer["artifact_bytes"], MAX_BUNDLE_BYTES, positive=True)
    baseline = stages[1]["result"]["measurements"]
    sql_hash = stages[1]["result"]["sql_snapshot_sha256"]
    for item in stages[1:]:
        result = item["result"]
        require(result["descriptor_sha256"] == transfer["descriptor_sha256"]
                and result["sql_snapshot_sha256"] == sql_hash and result["measurements"] == baseline, "restore_stage_inventory_mismatch")
    require(all(baseline[key] == transfer[key] for key in ("artifact_count", "artifact_bytes")), "restore_transfer_inventory_mismatch")
    _keys(value["unmeasured"], UNMEASURED)
    require(all(item is None for item in value["unmeasured"].values()), "restore_unmeasured_must_remain_unknown")
    _hash(value["report_sha256"])
    require(seal(value)["report_sha256"] == value["report_sha256"], "restore_report_hash_mismatch")
    require(len(canonical(value)) <= MAX_REPORT_BYTES, "restore_report_size_limit")
    return value


def loads_report(payload, *, internal=False):
    return validate_report(_json(payload, MAX_REPORT_BYTES), internal=internal)


def build_report(*, provenance, backend, started_at, completed_at, duration_ms, stage_results,
                 stage_durations_ms, transfer, cleanup_verified, source_postgres_version_num,
                 target_postgres_version_num):
    _keys(stage_results, STAGES)
    value = {"version": VERSION, "scope": SCOPE, "synthetic": True, "production": False,
        "authority": dict(AUTHORITY), "cleanup_verified": cleanup_verified, "started_at": started_at,
        "completed_at": completed_at, "duration_ms": duration_ms,
        "runtime": {"backend": backend, "python": platform.python_version(), "implementation": platform.python_implementation(),
                    "system": platform.system(), "machine": platform.machine(),
                    "source_postgres_version_num": source_postgres_version_num,
                    "target_postgres_version_num": target_postgres_version_num},
        "provenance": provenance, "source_run_id": stage_results["seed"]["run_id"],
        "target_run_id": stage_results["verify"]["run_id"], "schema_revision": stage_results["seed"]["schema_revision"],
        "stages": [{"phase": phase, "result": stage_results[stage]} for phase, stage in zip(PHASES, STAGES)],
        "durations_ms": stage_durations_ms, "transfer": transfer, "unmeasured": dict(UNMEASURED)}
    return validate_report(seal(value), internal=not cleanup_verified)


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class _Directory:
    def __init__(self, path):
        self.path = Path(path)
        require(self.path.is_absolute() and ".." not in self.path.parts, "unsafe_restore_directory")
        self.fd, self.chain = self._walk()
        info = os.fstat(self.fd)
        if not (stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.getuid()):
            self.close()
            raise RestoreContractError("unsafe_restore_directory")

    def _walk(self):
        fd = os.open(self.path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        chain = []
        try:
            for part in self.path.parts[1:]:
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = following
                info = os.fstat(fd)
                chain.append((info.st_dev, info.st_ino))
            return fd, tuple(chain)
        except BaseException:
            os.close(fd)
            raise

    def recheck(self):
        fd, chain = self._walk()
        try:
            info = os.fstat(fd)
            require(stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.getuid()
                    and chain == self.chain and (info.st_dev, info.st_ino) ==
                    (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino), "restore_directory_changed")
        finally:
            os.close(fd)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


@contextmanager
def _directory(path):
    directory = None
    try:
        directory = _Directory(path)
        yield directory
        directory.recheck()
    except OSError:
        raise RestoreContractError("restore_filesystem_unavailable") from None
    finally:
        if directory is not None:
            directory.close()


def _read(directory, name, maximum):
    require(type(name) is str and "/" not in name and name not in {"", ".", ".."}, "unsafe_restore_leaf")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory.fd)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.getuid()
                and stat.S_IMODE(before.st_mode) == 0o600 and 0 < before.st_size <= maximum, "unsafe_restore_file")
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, maximum - size + 1))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            require(size <= maximum, "restore_file_byte_limit")
        after = os.fstat(fd)
        require(_signature(before) == _signature(after) and size == before.st_size, "restore_file_changed")
        linked = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
        require(_signature(linked) == _signature(after), "restore_file_changed")
        return b"".join(chunks), _signature(after)
    finally:
        os.close(fd)


def read_private_json(path, *, maximum=MAX_REPORT_BYTES):
    path = Path(path)
    with _directory(path.parent) as directory:
        payload, _ = _read(directory, path.name, maximum)
        return payload


def _names(directory, maximum):
    result = []
    with os.scandir(directory.fd) as entries:
        for entry in entries:
            result.append(entry.name)
            require(len(result) <= maximum, "restore_file_inventory_limit")
    return sorted(result)


def _release_verify(manifest, artifacts, expected):
    # Lazy pure verifier import. No API ORM, test conftest or DB configuration.
    api = str(Path(__file__).resolve().parents[1] / "api")
    if api not in sys.path:
        sys.path.insert(0, api)
    from services.research_release_manifest import (
        ResearchReleaseVerificationError,
        verify_manifest,
    )
    try:
        verify_manifest(manifest, artifact_bytes=artifacts, expected_manifest_sha256=expected)
    except ResearchReleaseVerificationError:
        raise RestoreContractError("restore_capsule_verification_failed") from None


def _capture_bundle(root, expected):
    _hash(expected)
    with _directory(root) as outer, _directory(Path(root) / "research-bundle") as bundle:
        require(_names(bundle, 2) == ["artifacts", "manifest.json"], "restore_bundle_inventory_mismatch")
        payload, signature = _read(bundle, "manifest.json", MAX_FILE_BYTES)
        require(sha(payload) == expected, "restore_manifest_pin_mismatch")
        manifest = _json(payload, MAX_FILE_BYTES)
        require(canonical(manifest) == payload, "noncanonical_restore_manifest")
        entries = manifest.get("artifacts") if type(manifest) is dict else None
        require(type(entries) is list and 1 <= len(entries) <= MAX_ARTIFACTS, "invalid_restore_artifact_inventory")
        declared = []
        for entry in entries:
            require(type(entry) is dict and "sha256" in entry, "invalid_restore_artifact_inventory")
            _hash(entry["sha256"])
            declared.append(entry["sha256"])
        require(len(declared) == len(set(declared)), "duplicate_restore_artifact")
        files = {"manifest.json": payload}
        signatures = {"manifest.json": signature}
        with _directory(Path(root) / "research-bundle" / "artifacts") as artifacts:
            names = _names(artifacts, MAX_ARTIFACTS)
            require(names == sorted(declared), "restore_artifact_inventory_mismatch")
            total = len(payload)
            for name in names:
                item, item_signature = _read(artifacts, name, MAX_FILE_BYTES)
                require(sha(item) == name, "restore_artifact_pin_mismatch")
                total += len(item)
                require(total <= MAX_BUNDLE_BYTES, "restore_bundle_byte_limit")
                files["artifacts/" + name] = item
                signatures["artifacts/" + name] = item_signature
            require(_names(artifacts, MAX_ARTIFACTS) == names, "restore_artifact_inventory_changed")
        _release_verify(manifest, {name[10:]: item for name, item in files.items() if name.startswith("artifacts/")}, expected)
        require(_names(bundle, 2) == ["artifacts", "manifest.json"], "restore_bundle_inventory_changed")
        outer.recheck()
        return files, signatures, (outer.chain, bundle.chain, artifacts.chain)


def _bundle_metadata(files):
    inventory = [{"path": name, "sha256": sha(payload), "size_bytes": len(payload)} for name, payload in sorted(files.items())]
    return {"manifest_sha256": sha(files["manifest.json"]), "bundle_sha256": sha(canonical(inventory)),
        "artifact_count": len(files) - 1, "artifact_bytes": sum(len(payload) for name, payload in files.items() if name != "manifest.json"),
        "files": inventory}


def capture_bundle(root, *, expected_manifest_sha256):
    first = _capture_bundle(root, expected_manifest_sha256)
    require(first == _capture_bundle(root, expected_manifest_sha256), "restore_bundle_changed")
    return _bundle_metadata(first[0])


def read_artifact_bytes(root, *, expected_manifest_sha256):
    first = _capture_bundle(root, expected_manifest_sha256)
    require(first == _capture_bundle(root, expected_manifest_sha256), "restore_bundle_changed")
    return {name[10:]: payload for name, payload in first[0].items() if name.startswith("artifacts/")}


def validate_descriptor(value):
    _keys(value, ("version", "fixture_version", "source_run_id", "schema_revision", "release_id",
        "manifest_sha256", "bundle_sha256", "artifact_files", "sql_snapshot", "actors", "access_targets", "index", "authority"))
    require(value["version"] == DESCRIPTOR_VERSION and value["fixture_version"] == FIXTURE_VERSION, "invalid_restore_descriptor_version")
    _run(value["source_run_id"])
    _schema(value["schema_revision"])
    _uuid(value["release_id"])
    _hash(value["manifest_sha256"])
    _hash(value["bundle_sha256"])
    files = value["artifact_files"]
    require(type(files) is list and 1 <= len(files) <= MAX_ARTIFACTS, "invalid_restore_artifact_inventory")
    hashes, total = [], 0
    for item in files:
        _keys(item, ("sha256", "size_bytes"))
        _hash(item["sha256"])
        _int(item["size_bytes"], MAX_FILE_BYTES, positive=True)
        hashes.append(item["sha256"])
        total += item["size_bytes"]
    require(hashes == sorted(set(hashes)) and total <= MAX_BUNDLE_BYTES, "invalid_restore_artifact_inventory")
    snapshot = value["sql_snapshot"]
    _keys(snapshot, ("version", "tables", "sha256"))
    require(snapshot["version"] == "research-restore-sql-snapshot/1.0.0", "invalid_restore_sql_snapshot")
    tables = snapshot["tables"]
    require(type(tables) is list and 1 <= len(tables) <= MAX_SQL_TABLES, "restore_sql_table_limit")
    names, row_count, byte_count = [], 0, 0
    for row in tables:
        _keys(row, ("table", "row_count", "bytes", "sha256"))
        require(type(row["table"]) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,62}", row["table"]), "invalid_restore_sql_table")
        _int(row["row_count"], MAX_SQL_ROWS)
        _int(row["bytes"], MAX_SQL_BYTES)
        _hash(row["sha256"])
        names.append(row["table"])
        row_count += row["row_count"]
        byte_count += row["bytes"]
    require(names == sorted(set(names)) and row_count <= MAX_SQL_ROWS and byte_count <= MAX_SQL_BYTES,
            "restore_sql_snapshot_limit")
    require(snapshot["sha256"] == sha(canonical(tables)), "restore_sql_snapshot_hash_mismatch")
    _keys(value["actors"], ("admin", "curator", "reviewer", "publisher", "member", "revoked"))
    for actor in value["actors"].values():
        _uuid(actor)
    require(len(set(value["actors"].values())) == 6, "restore_actor_identity_collision")
    _keys(value["access_targets"], ("claim_id", "work_id", "dataset_id", "publication_proposal_id"))
    for key, identifier in value["access_targets"].items():
        if key == "publication_proposal_id" and identifier is None:
            continue
        _uuid(identifier)
    _keys(value["authority"], ("scientific_acceptance", "ml_training_approved", "public_release_authorized"))
    require(all(flag is False for flag in value["authority"].values()), "invalid_restore_authority")
    try:
        from research_restore_index import validate_descriptor as validate_index
        require(validate_index(value["index"]) == value["index"], "invalid_restore_index_descriptor")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        if isinstance(exc, RestoreContractError):
            raise
        raise RestoreContractError("invalid_restore_index_descriptor") from None
    require(len(canonical(value)) <= MAX_DESCRIPTOR_BYTES, "restore_descriptor_size_limit")
    return value


def _descriptor_capture(root, expected):
    _hash(expected)
    with _directory(root) as directory:
        payload, signature = _read(directory, "source-descriptor.json", MAX_DESCRIPTOR_BYTES)
        require(sha(payload) == expected, "restore_descriptor_pin_mismatch")
        value = _json(payload, MAX_DESCRIPTOR_BYTES)
        require(canonical(value) == payload, "noncanonical_restore_descriptor")
        validate_descriptor(value)
        return value, payload, signature, directory.chain


def read_source_descriptor(root, *, expected_descriptor_sha256):
    first = _descriptor_capture(root, expected_descriptor_sha256)
    require(first == _descriptor_capture(root, expected_descriptor_sha256), "restore_descriptor_changed")
    return first[0]


def copy_recovery_inputs(source_root, target_root, *, expected_descriptor_sha256, expected_manifest_sha256=None):
    """Copy only the pinned capsule and descriptor; partial failures are not success.

    The parent owns both private temporary roots and cleans them on any failure.
    No cleanup here recursively removes a supplied directory or old target data.
    """
    source_path, target_path = Path(source_root), Path(target_root)
    require(source_path != target_path and source_path not in target_path.parents
            and target_path not in source_path.parents, "restore_directory_identity_collision")
    with _directory(source_path) as source, _directory(target_path) as target:
        require(source.chain[-1] != target.chain[-1], "restore_directory_identity_collision")
        for name in ("source-descriptor.json", "research-bundle"):
            try:
                os.stat(name, dir_fd=target.fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise RestoreContractError("restore_target_collision")
        descriptor = _descriptor_capture(source_path, expected_descriptor_sha256)
        manifest_hash = descriptor[0]["manifest_sha256"]
        if expected_manifest_sha256 is not None:
            _hash(expected_manifest_sha256)
            require(manifest_hash == expected_manifest_sha256, "restore_manifest_pin_mismatch")
        captured = _capture_bundle(source_path, manifest_hash)
        metadata = _bundle_metadata(captured[0])
        require(metadata["bundle_sha256"] == descriptor[0]["bundle_sha256"], "restore_bundle_pin_mismatch")
        expected_files = [{"sha256": item["sha256"], "size_bytes": item["size_bytes"]}
                          for item in metadata["files"] if item["path"].startswith("artifacts/")]
        require(expected_files == descriptor[0]["artifact_files"], "restore_descriptor_artifact_mismatch")
        for relative, payload in sorted(captured[0].items()):
            source.recheck()
            target.recheck()
            safe_write_new(target_path, "research-bundle/" + relative, payload)
        safe_write_new(target_path, "source-descriptor.json", descriptor[1])
        require(captured == _capture_bundle(source_path, manifest_hash)
                and descriptor == _descriptor_capture(source_path, expected_descriptor_sha256), "restore_source_inputs_changed")
        restored = _capture_bundle(target_path, manifest_hash)
        require(restored[0] == captured[0]
                and _descriptor_capture(target_path, expected_descriptor_sha256)[1] == descriptor[1], "restore_copy_mismatch")
        source.recheck()
        target.recheck()
        return {"descriptor_sha256": expected_descriptor_sha256,
                **{key: metadata[key] for key in ("manifest_sha256", "bundle_sha256", "artifact_count", "artifact_bytes")}}


def _fixed_relative(relative):
    require(type(relative) is str, "unsafe_restore_relative_path")
    allowed = {"source-descriptor.json", "research-bundle/manifest.json", *(f"stage-{stage}.json" for stage in STAGES)}
    require(relative in allowed or re.fullmatch(r"research-bundle/artifacts/[0-9a-f]{64}", relative), "unsafe_restore_relative_path")
    return relative.split("/")


def _ensure_child(parent, name):
    parent.recheck()
    try:
        os.mkdir(name, 0o700, dir_fd=parent.fd)
    except FileExistsError:
        pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent.fd)
    child = None
    try:
        child = _Directory(parent.path / name)
        held, named = os.fstat(fd), os.fstat(child.fd)
        require((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino), "restore_directory_changed")
        parent.recheck()
        return child
    except BaseException:
        if child is not None:
            child.close()
        raise
    finally:
        os.close(fd)


def safe_write_new(root, relative, payload):
    parts = _fixed_relative(relative)
    maximum = MAX_FILE_BYTES if len(parts) > 1 else MAX_DESCRIPTOR_BYTES
    require(type(payload) is bytes and 0 < len(payload) <= maximum, "restore_file_byte_limit")
    with _directory(root) as outer:
        parents, current, fd, identity = [], outer, None, None
        try:
            for name in parts[:-1]:
                current = _ensure_child(current, name)
                parents.append(current)
            for parent in (outer, *parents):
                parent.recheck()
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=current.fd)
            os.fchmod(fd, 0o600)
            info = os.fstat(fd)
            identity = (info.st_dev, info.st_ino)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unsafe_restore_file")
            with os.fdopen(fd, "wb") as handle:
                fd = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            for parent in (outer, *parents):
                parent.recheck()
            observed, _ = _read(current, parts[-1], maximum)
            require(observed == payload, "restore_file_changed")
            os.fsync(current.fd)
        except BaseException:
            if identity is not None:
                try:
                    info = os.stat(parts[-1], dir_fd=current.fd, follow_symlinks=False)
                    if (info.st_dev, info.st_ino) == identity:
                        os.unlink(parts[-1], dir_fd=current.fd)
                except OSError:
                    pass
            raise
        finally:
            if fd is not None:
                os.close(fd)
            for parent in reversed(parents):
                parent.close()


class RestoreReportDestination(legacy.ReportDestination):
    """Reuse held ancestor identity checks; publish this version only after cleanup."""
    def publish(self, document, *, internal=False):
        require(internal is False, "restore_cleanup_unverified")
        payload = canonical(validate_report(document)) + b"\n"
        require(len(payload) <= MAX_REPORT_BYTES, "restore_report_size_limit")
        self.recheck()
        name = ".sclib-restore-" + secrets.token_hex(16) + ".tmp"
        fd, identity = None, None
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            os.fchmod(fd, 0o600)
            info = os.fstat(fd)
            identity = (info.st_dev, info.st_ino)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unsafe_restore_report")
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
            raise RestoreContractError("restore_report_publication_failed") from None
        finally:
            if fd is not None:
                os.close(fd)
