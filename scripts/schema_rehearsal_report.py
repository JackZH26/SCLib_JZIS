"""Bounded, text-free receipts for owned synthetic migration rehearsals.

Standard library only: importing this module never opens a service connection.
The receipt is engineering evidence, not deployment or scientific authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import stat
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

VERSION = "schema-rehearsal/1.0.0"
MAX_BYTES = 1024 * 1024
MAX_FILES = 2048
TABLES = (
    "materials", "papers", "chunks", "material_states", "structure_records",
    "structure_variants", "research_runs", "research_events", "material_claims",
    "source_snapshots", "snapshot_event_memberships", "ml_dataset_snapshots", "ml_examples",
    "event_properties", "source_revisions", "source_captures", "claim_source_occurrences",
    "research_import_snapshots", "research_import_occurrences", "research_import_revisions",
    "research_import_memberships", "research_import_receipts", "research_releases",
    "research_release_pins", "research_release_notices", "research_publication_proposals",
    "research_publication_actions", "index_generations", "index_generation_members",
    "index_generation_validations", "index_activation_events", "research_distribution_packages",
    "ml_feature_source_bindings", "scientific_import_packages", "scientific_import_attempts",
    "scientific_import_outcomes",
)
PHASES = ("legacy_seeded", "first_head", "before_read_cutover", "final")
RETENTIONS = ("seeded_legacy_materials", "seeded_source_revision", "frozen_release_and_pins")
OUTCOMES = (
    "correction_history_downgrade_refused", "source_history_downgrade_refused",
    "shadow_history_downgrade_refused", "release_history_downgrade_refused",
    "publication_history_downgrade_refused", "source_task_history_downgrade_refused",
    "background_history_downgrade_refused", "rag_history_downgrade_refused",
    "embedding_history_downgrade_refused", "generation_history_downgrade_refused",
    "distribution_history_downgrade_refused", "feature_history_downgrade_refused",
    "scientific_import_history_downgrade_refused", "empty_index_roundtrip_preserved",
    "populated_index_roundtrip_preserved", "missing_force_constants_quarantined_without_scientific_rows",
)
UNMEASURED = ("production_source_exclusions", "scientific_review", "deployment_approval",
              "production_backup_restore", "production_role_provisioning", "corpus_scale_parity")


class ReportError(ValueError):
    """Static messages only; no supplied paths, service identities or contents."""


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ReportError("invalid_runner_arguments") from None


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def _keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ReportError("invalid_report_shape")


def _int(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= 2**63 - 1:
        raise ReportError("invalid_report_integer")


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ReportError("invalid_report_hash")


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ReportError("invalid_report_identity")


def _label(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._+-]{1,120}", value):
        raise ReportError("invalid_report_label")


def _timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", value):
        raise ReportError("invalid_report_time")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def timestamp():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def validate(document, *, internal=False):
    """Validate a complete measured receipt; internal permits pre-cleanup draft."""
    try:
        _keys(document, ("version", "scope", "synthetic", "production", "authority", "cleanup_verified",
                         "started_at", "completed_at", "duration_ms", "source_schema", "target_schema",
                         "runtime", "provenance", "phases", "retention_checks", "fixture_outcomes",
                         "unmeasured", "read_model_rollback", "data_accounting", "report_sha256"))
        if document["version"] != VERSION or document["scope"] != "owned_disposable_migration_and_read_model_rehearsal":
            raise ReportError("invalid_report_version")
        if document["synthetic"] is not True or document["production"] is not False:
            raise ReportError("invalid_report_authority")
        _keys(document["authority"], ("deployment_approved", "scientific_acceptance", "ml_training_approved", "source_distribution_approved"))
        if any(value is not False for value in document["authority"].values()):
            raise ReportError("invalid_report_authority")
        if type(document["cleanup_verified"]) is not bool or (not internal and not document["cleanup_verified"]):
            raise ReportError("cleanup_not_verified")
        if _timestamp(document["completed_at"]) < _timestamp(document["started_at"]):
            raise ReportError("invalid_report_time")
        _int(document["duration_ms"])
        if document["source_schema"] != "0050_timeline_identity":
            raise ReportError("invalid_report_source_schema")
        _label(document["target_schema"])
        _keys(document["runtime"], ("backend", "python", "implementation", "system", "machine", "postgres_version_num"))
        if document["runtime"]["backend"] not in {"native", "docker"}:
            raise ReportError("invalid_report_backend")
        for key in ("python", "implementation", "system", "machine"):
            _label(document["runtime"][key])
        _int(document["runtime"]["postgres_version_num"], positive=True)
        provenance = document["provenance"]
        _keys(provenance, ("head_revision", "dirty_worktree", "source_dirty", "tracked_diff_sha256", "inputs", "inputs_sha256", "unchanged_during_rehearsal"))
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", provenance["head_revision"]):
            raise ReportError("invalid_report_revision")
        if any(type(provenance[key]) is not bool for key in ("dirty_worktree", "source_dirty")) or provenance["unchanged_during_rehearsal"] is not True:
            raise ReportError("invalid_report_provenance")
        _hash(provenance["tracked_diff_sha256"])
        inputs = provenance["inputs"]
        if not isinstance(inputs, list) or not 1 <= len(inputs) <= MAX_FILES:
            raise ReportError("invalid_report_inputs")
        paths = []
        for item in inputs:
            _keys(item, ("path", "sha256", "size_bytes"))
            path = item["path"]
            if not isinstance(path, str) or not re.fullmatch(r"(?:api|scripts)/[A-Za-z0-9_./-]{1,240}", path) or any(part in {"", ".", ".."} for part in path.split("/")):
                raise ReportError("invalid_report_input_path")
            if not (path.endswith(".py") or path in {"api/uv.lock", "api/pyproject.toml", "api/alembic.ini"}
                    or re.fullmatch(r"api/services/[A-Za-z0-9_-]+\.schema\.json", path)):
                raise ReportError("invalid_report_input_path")
            _hash(item["sha256"])
            _int(item["size_bytes"])
            paths.append(path)
        if paths != sorted(set(paths)) or provenance["inputs_sha256"] != sha(canonical(inputs)):
            raise ReportError("invalid_report_inputs")
        phases = document["phases"]
        if not isinstance(phases, list) or [row.get("phase") for row in phases] != list(PHASES):
            raise ReportError("invalid_report_phases")
        for row in phases:
            _keys(row, ("phase", "schema", "counts", "material_raw_records"))
            _label(row["schema"])
            _keys(row["counts"], TABLES)
            for value in row["counts"].values():
                if value is not None:
                    _int(value)
            _int(row["material_raw_records"])
        if phases[0]["schema"] != document["source_schema"] or any(row["schema"] != document["target_schema"] for row in phases[1:]):
            raise ReportError("invalid_report_phase_schema")
        retentions = document["retention_checks"]
        if not isinstance(retentions, list) or [row.get("check") for row in retentions] != list(RETENTIONS):
            raise ReportError("invalid_report_retention")
        for row in retentions:
            _keys(row, ("check", "row_count", "before_sha256", "after_sha256", "passed"))
            _int(row["row_count"], positive=True)
            _hash(row["before_sha256"])
            if row["passed"] is not True or row["after_sha256"] != row["before_sha256"]:
                raise ReportError("invalid_report_retention")
        outcomes = document["fixture_outcomes"]
        if not isinstance(outcomes, list) or [row.get("code") for row in outcomes] != list(OUTCOMES):
            raise ReportError("invalid_report_outcomes")
        for row in outcomes:
            _keys(row, ("code", "observed_count"))
            _int(row["observed_count"], positive=True)
        _keys(document["unmeasured"], UNMEASURED)
        if any(value is not None for value in document["unmeasured"].values()):
            raise ReportError("unmeasured_must_remain_unknown")
        accounting = document["data_accounting"]
        _keys(accounting, ("scope", "scientific_import_packages", "scientific_import_attempts", "scientific_import_outcomes",
                           "attempts_without_terminal", "terminal_status_counts", "quarantine_reason_counts",
                           "shadow_receipt_rows", "shadow_data_exclusions"))
        if accounting["scope"] != "final_synthetic_scientific_import_ledger_only" or accounting["shadow_data_exclusions"] is not None:
            raise ReportError("invalid_report_data_accounting")
        for key in ("scientific_import_packages", "scientific_import_attempts", "scientific_import_outcomes", "attempts_without_terminal", "shadow_receipt_rows"):
            _int(accounting[key])
        _keys(accounting["terminal_status_counts"], ("success_pending", "quarantined", "failed"))
        _keys(accounting["quarantine_reason_counts"], ("force_constants_unavailable", "validated_coordinates_unavailable"))
        for value in (*accounting["terminal_status_counts"].values(), *accounting["quarantine_reason_counts"].values()):
            _int(value)
        if sum(accounting["terminal_status_counts"].values()) != accounting["scientific_import_outcomes"] or accounting["scientific_import_outcomes"] + accounting["attempts_without_terminal"] != accounting["scientific_import_attempts"]:
            raise ReportError("invalid_report_data_accounting")
        if any(accounting["terminal_status_counts"]["quarantined"] != value for value in accounting["quarantine_reason_counts"].values()):
            raise ReportError("invalid_report_data_accounting")
        if any(accounting[key] != phases[-1]["counts"][key] for key in ("scientific_import_packages", "scientific_import_attempts", "scientific_import_outcomes")) or accounting["shadow_receipt_rows"] != phases[-1]["counts"]["research_import_receipts"]:
            raise ReportError("invalid_report_data_accounting")
        rollback = document["read_model_rollback"]
        _keys(rollback, ("generation_ids", "validation_ids", "activation_event_ids", "rollback_activation_event_id", "restored_generation_id", "restored_activation_event_id", "retained_member_count", "retained_text_sha256", "retained_vector_sha256", "retained_vector_bytes", "verified", "procedure"))
        for key in ("generation_ids", "validation_ids", "activation_event_ids"):
            values = rollback[key]
            if not isinstance(values, list) or len(values) != 2 or len(set(values)) != 2:
                raise ReportError("invalid_report_rollback")
            for value in values:
                _uuid(value)
        for key in ("rollback_activation_event_id", "restored_generation_id", "restored_activation_event_id"):
            _uuid(rollback[key])
        if rollback["rollback_activation_event_id"] in rollback["activation_event_ids"] or rollback["restored_generation_id"] != rollback["generation_ids"][0] or rollback["restored_activation_event_id"] != rollback["rollback_activation_event_id"] or rollback["verified"] is not True:
            raise ReportError("invalid_report_rollback")
        if rollback["procedure"] != "validate_retained_generation_then_CAS_from_current_event_with_action_rollback":
            raise ReportError("invalid_report_rollback")
        _int(rollback["retained_member_count"], positive=True)
        _int(rollback["retained_vector_bytes"], positive=True)
        _hash(rollback["retained_text_sha256"])
        _hash(rollback["retained_vector_sha256"])
        _hash(document["report_sha256"])
        if document["report_sha256"] != sha(canonical({k: v for k, v in document.items() if k != "report_sha256"})):
            raise ReportError("report_hash_mismatch")
        if len(canonical(document)) > MAX_BYTES:
            raise ReportError("report_size_exceeded")
        return document
    except (TypeError, KeyError, OverflowError, AttributeError, ValueError) as exc:
        if isinstance(exc, ReportError):
            raise
        raise ReportError("invalid_report") from None


def seal(document):
    document = {k: v for k, v in document.items() if k != "report_sha256"}
    return {**document, "report_sha256": sha(canonical(document))}


def loads(payload, *, internal=False):
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_BYTES:
        raise ReportError("report_size_exceeded")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ReportError("duplicate_report_key")
            result[key] = value
        return result
    try:
        value = json.loads(payload, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ReportError("nonfinite_report")))
        return validate(value, internal=internal)
    except (UnicodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, ReportError):
            raise
        raise ReportError("invalid_report_json") from None


class ReportDestination:
    """Hold a no-symlink ancestor chain and publish only a brand-new 0600 file."""
    def __init__(self, path):
        self.fd = None
        self.path = Path(os.path.abspath(os.fspath(path)))
        # Inspect the original spelling: abspath must not launder '..' or links.
        if ".." in Path(path).parts or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}\.json", self.path.name):
            raise ReportError("invalid_report_destination")
        try:
            self.fd, self.chain = self._walk()
            self._absent()
        except OSError:
            self.close()
            raise ReportError("unsafe_report_destination") from None
        except Exception:
            self.close()
            raise

    def _walk(self):
        fd = os.open(self.path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        chain = []
        try:
            for part in self.path.parent.parts[1:]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
                info = os.fstat(fd)
                chain.append((info.st_dev, info.st_ino))
            return fd, chain
        except Exception:
            os.close(fd)
            raise

    def _absent(self):
        try:
            os.stat(self.path.name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise ReportError("report_destination_exists")

    def recheck(self):
        fd = None
        try:
            fd, chain = self._walk()
            fresh, held = os.fstat(fd), os.fstat(self.fd)
            if chain != self.chain or (fresh.st_dev, fresh.st_ino) != (held.st_dev, held.st_ino):
                raise ReportError("report_destination_changed")
            self._absent()
        except OSError:
            raise ReportError("report_destination_changed") from None
        finally:
            if fd is not None:
                os.close(fd)

    def publish(self, document, *, internal=False):
        payload = canonical(validate(document, internal=internal)) + b"\n"
        if len(payload) > MAX_BYTES:
            raise ReportError("report_size_exceeded")
        self.recheck()
        fd, identity = None, None
        temporary = ".sclib-rehearsal-" + secrets.token_hex(16) + ".tmp"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            os.fchmod(fd, 0o600)
            info = os.fstat(fd)
            identity = (info.st_dev, info.st_ino)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ReportError("unsafe_report_file")
            with os.fdopen(fd, "wb", closefd=True) as handle:
                fd = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            self.recheck()
            # Same-directory no-clobber link publishes only complete bytes.
            os.link(temporary, self.path.name, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
            os.unlink(temporary, dir_fd=self.fd)
            os.fsync(self.fd)
        except BaseException as exc:
            if identity is not None:
                for name in (temporary, self.path.name):
                    try:
                        current = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
                        if (current.st_dev, current.st_ino) == identity:
                            os.unlink(name, dir_fd=self.fd)
                    except OSError:
                        pass
            if not isinstance(exc, Exception):
                raise
            raise ReportError("report_publication_failed") from None
        finally:
            if fd is not None:
                os.close(fd)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def read_private_report(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1 or before.st_uid != os.getuid() or not 1 <= before.st_size <= MAX_BYTES:
                raise ReportError("unsafe_private_report")
            payload = handle.read(MAX_BYTES + 1)
            after = os.fstat(handle.fileno())
        if _stable_stat(before) != _stable_stat(after) or len(payload) != before.st_size:
            raise ReportError("private_report_changed")
        return payload
    except OSError:
        raise ReportError("private_report_unavailable") from None


def _stable_stat(info):
    # Reading may legitimately update atime. Identity, permissions, link count
    # and modification/metadata times must not change underneath the capture.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def capture_provenance(repo):
    """Hash bounded installed source inputs, never write source bytes to report."""
    repo = Path(repo)
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=repo, env={"PATH": os.defpath, "LANG": "C"},
                                  capture_output=True, check=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            raise ReportError("source_provenance_unavailable") from None
    inputs, total = [], 0
    for root in ("api", "scripts"):
        if (repo / root).is_symlink():
            raise ReportError("source_input_symlink")
        for parent, directories, files in os.walk(repo / root, followlinks=False):
            directories[:] = sorted(name for name in directories if not name.startswith(".") and name not in {"__pycache__", "node_modules"})
            if any((Path(parent) / name).is_symlink() for name in directories):
                raise ReportError("source_input_symlink")
            for name in sorted(files):
                if not (name.endswith(".py") or (Path(parent) == repo / "api" and name in {"uv.lock", "pyproject.toml", "alembic.ini"})
                        or (Path(parent) == repo / "api/services" and name.endswith(".schema.json"))):
                    continue
                path = Path(parent) / name
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                    with os.fdopen(fd, "rb") as handle:
                        before = os.fstat(handle.fileno())
                        if not stat.S_ISREG(before.st_mode) or before.st_size > 4 * MAX_BYTES:
                            raise ReportError("source_input_size_exceeded")
                        payload = handle.read(4 * MAX_BYTES + 1)
                        after = os.fstat(handle.fileno())
                    if _stable_stat(before) != _stable_stat(after) or len(payload) != before.st_size:
                        raise ReportError("source_input_changed")
                except OSError:
                    raise ReportError("source_input_unavailable") from None
                total += len(payload)
                inputs.append({"path": str(path.relative_to(repo)), "sha256": sha(payload), "size_bytes": len(payload)})
                if len(inputs) > MAX_FILES or total > 64 * MAX_BYTES:
                    raise ReportError("source_inventory_size_exceeded")
    inputs.sort(key=lambda row: row["path"])
    return {"head_revision": git("rev-parse", "HEAD").decode().strip(),
            "dirty_worktree": bool(git("status", "--porcelain", "--untracked-files=all")),
            "source_dirty": bool(git("status", "--porcelain", "--untracked-files=all", "--", "api", "scripts")),
            "tracked_diff_sha256": sha(git("diff", "HEAD", "--binary", "--", "api", "scripts")),
            "inputs": inputs, "inputs_sha256": sha(canonical(inputs)), "unchanged_during_rehearsal": True}


def source_unchanged(before, after):
    # Unrelated documentation edits are allowed; executed input bytes are not.
    keys = ("head_revision", "tracked_diff_sha256", "inputs", "inputs_sha256", "source_dirty")
    if any(before[key] != after[key] for key in keys):
        raise ReportError("rehearsal_inputs_changed")


class Recorder:
    def __init__(self, repo, backend):
        self.repo, self.backend = Path(repo), backend
        self.started_at, self.started_clock = timestamp(), time.monotonic_ns()
        self.provenance = capture_provenance(repo)
        self.phases, self.retentions, self.outcomes = [], [], {}
        self.rollback = None

    def phase(self, connection, phase):
        from sqlalchemy import text
        connection.execute(text("SET LOCAL statement_timeout='5000ms'"))
        counts = {}
        for table in TABLES:
            present = connection.execute(text("SELECT to_regclass(:name)"), {"name": "public." + table}).scalar_one()
            counts[table] = None if present is None else connection.execute(text(f"SELECT count(*) FROM public.{table}")).scalar_one()
        rows = connection.execute(text("SELECT coalesce(sum(jsonb_array_length(records)),0) FROM public.materials")).scalar_one()
        schema = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
        self.phases.append({"phase": phase, "schema": schema, "counts": counts, "material_raw_records": int(rows)})

    def outcome(self, code):
        if code not in OUTCOMES or code in self.outcomes:
            raise ReportError("invalid_fixture_observation")
        self.outcomes[code] = 1

    def retention(self, name, before, after):
        if before != after:
            raise ReportError("retained_rows_changed")
        self.retentions.append({"check": name, "row_count": before[0], "before_sha256": before[1], "after_sha256": after[1], "passed": True})

    def finish(self, connection):
        from sqlalchemy import text
        source_unchanged(self.provenance, capture_provenance(self.repo))
        document = {"version": VERSION, "scope": "owned_disposable_migration_and_read_model_rehearsal",
                    "synthetic": True, "production": False, "cleanup_verified": False,
                    "authority": {key: False for key in ("deployment_approved", "scientific_acceptance", "ml_training_approved", "source_distribution_approved")},
                    "started_at": self.started_at, "completed_at": timestamp(),
                    "duration_ms": (time.monotonic_ns() - self.started_clock) // 1_000_000,
                    "source_schema": "0050_timeline_identity", "target_schema": self.phases[-1]["schema"],
                    "runtime": {"backend": self.backend, "python": platform.python_version(), "implementation": platform.python_implementation(),
                                "system": platform.system(), "machine": platform.machine(),
                                "postgres_version_num": int(connection.execute(text("SHOW server_version_num")).scalar_one())},
                    "provenance": self.provenance, "phases": self.phases, "retention_checks": self.retentions,
                    "fixture_outcomes": [{"code": code, "observed_count": self.outcomes[code]} for code in OUTCOMES],
                    "unmeasured": {key: None for key in UNMEASURED}, "read_model_rollback": self.rollback,
                    "data_accounting": self.data_accounting(connection)}
        return validate(seal(document), internal=True)

    def data_accounting(self, connection):
        from sqlalchemy import text
        result = {"scope": "final_synthetic_scientific_import_ledger_only", "shadow_data_exclusions": None}
        for table in ("scientific_import_packages", "scientific_import_attempts", "scientific_import_outcomes"):
            result[table] = connection.execute(text(f"SELECT count(*) FROM public.{table}")).scalar_one()
        result["shadow_receipt_rows"] = connection.execute(text("SELECT count(*) FROM public.research_import_receipts")).scalar_one()
        result["attempts_without_terminal"] = connection.execute(text("SELECT count(*) FROM public.scientific_import_attempts a LEFT JOIN public.scientific_import_outcomes o ON o.attempt_id=a.id WHERE o.id IS NULL")).scalar_one()
        statuses = dict(connection.execute(text("SELECT outcome,count(*) FROM public.scientific_import_outcomes GROUP BY outcome")).all())
        reasons = dict(connection.execute(text("SELECT code,count(*) FROM public.scientific_import_outcomes o CROSS JOIN LATERAL jsonb_array_elements_text(o.reason_codes) code WHERE o.outcome='quarantined' GROUP BY code LIMIT 3")).all())
        if set(statuses) - {"success_pending", "quarantined", "failed"} or set(reasons) - {"force_constants_unavailable", "validated_coordinates_unavailable"}:
            raise ReportError("unrecognized_fixture_accounting")
        result["terminal_status_counts"] = {key: statuses.get(key, 0) for key in ("success_pending", "quarantined", "failed")}
        result["quarantine_reason_counts"] = {key: reasons.get(key, 0) for key in ("force_constants_unavailable", "validated_coordinates_unavailable")}
        return result
