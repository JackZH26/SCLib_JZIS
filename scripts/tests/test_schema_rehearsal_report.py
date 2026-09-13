"""Synthetic source-only receipt/runner boundary tests; no real services."""
from __future__ import annotations

import copy
import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import run_disposable_tests as runner
import schema_rehearsal_report as report


def fixture():
    """Shape fixture only; never archived or presented as an actual rehearsal."""
    inputs = [{"path": "scripts/synthetic.py", "sha256": "a" * 64, "size_bytes": 1}]
    ids = [str(UUID(int=index)) for index in range(1, 8)]
    return report.seal({
        "version": report.VERSION, "scope": "owned_disposable_migration_and_read_model_rehearsal",
        "synthetic": True, "production": False, "cleanup_verified": True,
        "authority": {key: False for key in ("deployment_approved", "scientific_acceptance", "ml_training_approved", "source_distribution_approved")},
        "started_at": "2026-09-08T01:00:00.000000Z", "completed_at": "2026-09-08T01:00:01.000000Z", "duration_ms": 1000,
        "source_schema": "0050_timeline_identity", "target_schema": "0066_result_impact_indexes",
        "runtime": {"backend": "native", "python": "3.12.14", "implementation": "CPython", "system": "Darwin", "machine": "arm64", "postgres_version_num": 160013},
        "provenance": {"head_revision": "a" * 40, "dirty_worktree": True, "source_dirty": True,
                       "tracked_diff_sha256": "b" * 64, "inputs": inputs, "inputs_sha256": report.sha(report.canonical(inputs)), "unchanged_during_rehearsal": True},
        "phases": [{"phase": phase, "schema": "0050_timeline_identity" if index == 0 else "0066_result_impact_indexes",
                    "counts": {key: 2 if key == "materials" or (phase == "final" and key in {"scientific_import_packages", "scientific_import_attempts", "scientific_import_outcomes"}) else 0 for key in report.TABLES}, "material_raw_records": 2} for index, phase in enumerate(report.PHASES)],
        "retention_checks": [{"check": name, "row_count": 2, "before_sha256": "a" * 64, "after_sha256": "a" * 64, "passed": True} for name in report.RETENTIONS],
        "fixture_outcomes": [{"code": code, "observed_count": 1} for code in report.OUTCOMES],
        "unmeasured": {key: None for key in report.UNMEASURED},
        "data_accounting": {"scope": "final_synthetic_scientific_import_ledger_only",
                            "scientific_import_packages": 2, "scientific_import_attempts": 2, "scientific_import_outcomes": 2,
                            "attempts_without_terminal": 0, "terminal_status_counts": {"success_pending": 1, "quarantined": 1, "failed": 0},
                            "quarantine_reason_counts": {"force_constants_unavailable": 1, "validated_coordinates_unavailable": 1}, "shadow_receipt_rows": 0, "shadow_data_exclusions": None},
        "read_model_rollback": {"generation_ids": ids[:2], "validation_ids": ids[2:4], "activation_event_ids": ids[4:6],
                                "rollback_activation_event_id": ids[6], "restored_generation_id": ids[0], "restored_activation_event_id": ids[6],
                                "retained_member_count": 1, "retained_text_sha256": "c" * 64, "retained_vector_sha256": "d" * 64,
                                "retained_vector_bytes": 3072, "verified": True,
                                "procedure": "validate_retained_generation_then_CAS_from_current_event_with_action_rollback"},
    })


def test_closed_receipt_roundtrip_and_no_authority():
    value = fixture()
    assert report.loads(report.canonical(value)) == value
    assert all(flag is False for flag in value["authority"].values())
    assert value["unmeasured"]["production_source_exclusions"] is None


@pytest.mark.parametrize("path,allowed", [
    ("api/services/ml08_pilot.schema.json", True),
    ("api/services/synthetic-v2.schema.json", True),
    ("api/services/private.json", False),
    ("api/models/ml08_pilot.schema.json", False),
    ("scripts/ml08_pilot.schema.json", False),
    ("api/services/nested/ml08_pilot.schema.json", False),
    ("api/services/../ml08_pilot.schema.json", False),
    ("api/services/.private.schema.json", False),
])
def test_schema_resource_path_allowance_is_narrow_and_roundtrippable(path, allowed):
    value = fixture()
    inputs = value["provenance"]["inputs"]
    inputs[0]["path"] = path
    value["provenance"]["inputs_sha256"] = report.sha(report.canonical(inputs))
    value = report.seal(value)
    if allowed:
        assert report.loads(report.canonical(value)) == value
    else:
        with pytest.raises(report.ReportError, match="invalid_report_input_path"):
            report.validate(value)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(extra="CANARY"),
    lambda d: d["authority"].update(scientific_acceptance=True),
    lambda d: d["authority"].update(ml_training_approved=0),
    lambda d: d.update(production=True),
    lambda d: d.update(cleanup_verified=False),
    lambda d: d.update(duration_ms=True),
    lambda d: d.update(duration_ms=-1),
    lambda d: d["runtime"].update(postgres_version_num="160013"),
    lambda d: d["runtime"].update(backend="production"),
    lambda d: d["runtime"].update(system="secret://hostname"),
    lambda d: d["provenance"].update(head_revision="main"),
    lambda d: d["provenance"].update(unchanged_during_rehearsal=False),
    lambda d: d["provenance"]["inputs"][0].update(path="../private/secret.py"),
    lambda d: d["provenance"]["inputs"][0].update(path="api/.env"),
    lambda d: d["provenance"]["inputs"].append(d["provenance"]["inputs"][0]),
    lambda d: d["phases"].pop(),
    lambda d: d["phases"][0]["counts"].update(materials=True),
    lambda d: d["phases"][0]["counts"].update(papers=-1),
    lambda d: d["retention_checks"][0].update(after_sha256="b" * 64),
    lambda d: d["retention_checks"][0].update(row_count=0),
    lambda d: d["fixture_outcomes"].pop(),
    lambda d: d["fixture_outcomes"][0].update(observed_count=0),
    lambda d: d["unmeasured"].update(production_source_exclusions=0),
    lambda d: d["data_accounting"].update(shadow_data_exclusions=0),
    lambda d: d["data_accounting"]["quarantine_reason_counts"].update(force_constants_unavailable=0),
    lambda d: d["data_accounting"]["terminal_status_counts"].update(quarantined=2),
    lambda d: d["data_accounting"].update(attempts_without_terminal=1),
    lambda d: d["read_model_rollback"].update(restored_generation_id=str(UUID(int=2))),
    lambda d: d["read_model_rollback"].update(rollback_activation_event_id=str(UUID(int=5))),
    lambda d: d["read_model_rollback"].update(retained_vector_bytes=0),
    lambda d: d.update(completed_at="2026-09-08T00:00:00.000000Z"),
])
def test_malformed_or_overclaiming_receipt_is_rejected(mutate):
    value = fixture()
    mutate(value)
    with pytest.raises(report.ReportError):
        report.validate(report.seal(value))


@pytest.mark.parametrize("payload", [b"{}", b"[]", b'{"x":1,"x":2}', b'{"x":NaN}', b"{" + b" " * report.MAX_BYTES, b"\xff"])
def test_json_byte_shape_duplicate_and_nonfinite_bounds(payload):
    with pytest.raises(report.ReportError):
        report.loads(payload)


def test_hash_and_cleanup_are_not_optional():
    value = fixture()
    value["duration_ms"] += 1
    with pytest.raises(report.ReportError, match="hash_mismatch"):
        report.validate(value)
    draft = report.seal({**fixture(), "cleanup_verified": False})
    assert report.validate(draft, internal=True) == draft
    with pytest.raises(report.ReportError, match="cleanup_not_verified"):
        report.validate(draft)


def test_exclusive_atomic_owner_only_report_and_replay_refusal(tmp_path):
    target = tmp_path.resolve() / "report.json"
    destination = report.ReportDestination(target)
    try:
        destination.publish(fixture())
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert target.stat().st_nlink == 1
        assert target.read_bytes() == report.canonical(fixture()) + b"\n"
        with pytest.raises(report.ReportError, match="exists"):
            destination.publish(fixture())
        assert not list(target.parent.glob(".sclib-rehearsal-*.tmp"))
    finally:
        destination.close()


@pytest.mark.parametrize("kind", ["existing", "symlink", "ancestor_symlink", "fifo", "hardlink", "traversal"])
def test_destination_admission_fail_closed(tmp_path, kind):
    root = tmp_path.resolve()
    target = root / "report.json"
    if kind == "existing":
        target.write_text("original")
    elif kind == "symlink":
        target.symlink_to(root / "missing")
    elif kind == "ancestor_symlink":
        (root / "link").symlink_to(root, target_is_directory=True)
        target = root / "link/report.json"
    elif kind == "fifo":
        os.mkfifo(target)
    elif kind == "hardlink":
        (root / "original").write_text("original")
        os.link(root / "original", target)
    else:
        target = root / "missing/../report.json"
    with pytest.raises(report.ReportError):
        report.ReportDestination(target)


def test_ancestor_replacement_and_competing_leaf_preserve_other_files(tmp_path):
    root = tmp_path.resolve()
    parent = root / "parent"
    parent.mkdir()
    destination = report.ReportDestination(parent / "report.json")
    try:
        parent.rename(root / "old")
        parent.mkdir()
        with pytest.raises(report.ReportError, match="changed"):
            destination.publish(fixture())
        assert not (root / "old/report.json").exists()
    finally:
        destination.close()
    destination = report.ReportDestination(parent / "report.json")
    try:
        (parent / "report.json").write_text("other")
        with pytest.raises(report.ReportError, match="exists"):
            destination.publish(fixture())
        assert (parent / "report.json").read_text() == "other"
    finally:
        destination.close()


@pytest.mark.parametrize("operation", ["fsync", "link"])
def test_publication_failure_never_exposes_partial_receipt(tmp_path, monkeypatch, operation):
    destination = report.ReportDestination(tmp_path.resolve() / "report.json")
    try:
        monkeypatch.setattr(report.os, operation, lambda *a, **k: (_ for _ in ()).throw(OSError("secret-canary")))
        with pytest.raises(report.ReportError, match="publication_failed"):
            destination.publish(fixture())
        assert list(tmp_path.iterdir()) == []
    finally:
        destination.close()


def test_failed_final_directory_sync_removes_only_own_complete_receipt(tmp_path, monkeypatch):
    destination = report.ReportDestination(tmp_path.resolve() / "report.json")
    real = report.os.fsync
    calls = []
    def fsync(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError("synthetic directory sync failure")
        return real(fd)
    monkeypatch.setattr(report.os, "fsync", fsync)
    try:
        with pytest.raises(report.ReportError):
            destination.publish(fixture())
        assert list(tmp_path.iterdir()) == []
    finally:
        destination.close()


def test_competitor_between_recheck_and_link_is_never_removed(tmp_path, monkeypatch):
    target = tmp_path.resolve() / "report.json"
    destination = report.ReportDestination(target)
    real = report.os.link
    def link(*args, **kwargs):
        target.write_text("competitor")
        return real(*args, **kwargs)
    monkeypatch.setattr(report.os, "link", link)
    try:
        with pytest.raises(report.ReportError):
            destination.publish(fixture())
        assert target.read_text() == "competitor"
        assert list(tmp_path.iterdir()) == [target]
    finally:
        destination.close()


@pytest.mark.parametrize("field", ["st_atime_ns", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"])
def test_private_capture_ignores_atime_but_detects_metadata_changes(tmp_path, monkeypatch, field):
    target = tmp_path.resolve() / "report.json"
    target.write_bytes(b"{}")
    target.chmod(0o600)
    real = report.os.fstat
    calls = []
    def fstat(fd):
        value = real(fd)
        calls.append(fd)
        if len(calls) == 2:
            values = {name: getattr(value, name) for name in dir(value) if name.startswith("st_")}
            values[field] += 1
            return SimpleNamespace(**values)
        return value
    monkeypatch.setattr(report.os, "fstat", fstat)
    if field == "st_atime_ns":
        assert report.read_private_report(target) == b"{}"
    else:
        with pytest.raises(report.ReportError, match="private_report_changed"):
            report.read_private_report(target)


def _mock_run(monkeypatch, tmp_path, *, child_status=0, child_kind="valid", cleanup_error=False, temp_cleanup_error=False):
    events, child_args = [], []
    class Services:
        def __init__(self, root, *args):
            self.root = root
        def start(self):
            events.append("start")
            return runner.child_environment()
        def close(self):
            events.append("close")
            if cleanup_error:
                raise RuntimeError("secret-cleanup-canary")
    def child(command, **kwargs):
        events.append("child")
        child_args.append((command, kwargs["env"]))
        private_path = Path(command[-1])
        assert private_path.name == "schema-rehearsal.json"
        assert private_path.parent.name.startswith("sclib-tests-")
        assert private_path.parent != tmp_path
        if child_kind != "missing":
            payload = report.canonical(report.seal({**fixture(), "cleanup_verified": False}))
            if child_kind == "malformed":
                payload = b'{"DSN":"secret-canary"}'
            elif child_kind == "large":
                payload = b"x" * (report.MAX_BYTES + 1)
            private_path.write_bytes(payload)
            private_path.chmod(0o600)
        return SimpleNamespace(returncode=child_status)
    monkeypatch.setattr(runner, "DisposableServices", Services)
    monkeypatch.setattr(runner.subprocess, "run", child)
    monkeypatch.setattr(runner, "capture_provenance", lambda repo: fixture()["provenance"])
    actual_temporary = runner.tempfile.TemporaryDirectory
    class Temporary:
        def __init__(self, *args, **kwargs):
            self.real = actual_temporary(*args, **kwargs)
        def __enter__(self):
            return self.real.__enter__()
        def __exit__(self, *args):
            result = self.real.__exit__(*args)
            events.append("temporary_removed")
            if temp_cleanup_error:
                raise OSError("secret-temporary-canary")
            return result
    monkeypatch.setattr(runner.tempfile, "TemporaryDirectory", Temporary)
    return events, child_args


def test_runner_only_publishes_after_both_cleanups_and_never_forwards_targets(tmp_path, monkeypatch, capsys):
    target = tmp_path.resolve() / "report.json"
    for name in ("DATABASE_URL", "REDIS_URL", "PYTHONPATH", "PYTEST_ADDOPTS", "GEMINI_API_KEY", "SCLIB_REHEARSAL_REPORT"):
        monkeypatch.setenv(name, "secret-canary")
    events, arguments = _mock_run(monkeypatch, tmp_path)
    original = report.ReportDestination.publish
    def publish(self, value, **kwargs):
        assert events[-2:] == ["close", "temporary_removed"]
        events.append("publish")
        return original(self, value, **kwargs)
    monkeypatch.setattr(report.ReportDestination, "publish", publish)
    monkeypatch.setattr(sys, "argv", ["runner", "--suite", "migrations", "--report", str(target)])
    assert runner.main() == 0
    assert report.loads(target.read_bytes())["cleanup_verified"] is True
    assert events == ["start", "child", "close", "temporary_removed", "publish"]
    assert str(target) not in arguments[0][0]
    assert "secret-canary" not in str(arguments[0][1]) + capsys.readouterr().out


@pytest.mark.parametrize("options", [
    {"child_status": 1}, {"child_kind": "missing"}, {"child_kind": "malformed"},
    {"child_kind": "large"}, {"cleanup_error": True}, {"temp_cleanup_error": True},
])
def test_no_success_receipt_on_any_failure(tmp_path, monkeypatch, capsys, options):
    target = tmp_path.resolve() / "report.json"
    events, _ = _mock_run(monkeypatch, tmp_path, **options)
    monkeypatch.setattr(sys, "argv", ["runner", "--suite", "migrations", "--report", str(target)])
    assert runner.main() != 0
    assert "close" in events
    assert not target.exists()
    output = capsys.readouterr()
    assert "secret-" not in output.err
    assert "Retained synthetic" not in output.out
    if options.get("temp_cleanup_error"):
        assert "Removed only" not in output.out


def test_source_mutation_after_child_success_prevents_publication(tmp_path, monkeypatch):
    target = tmp_path.resolve() / "report.json"
    _mock_run(monkeypatch, tmp_path)
    changed = fixture()["provenance"]
    changed["inputs_sha256"] = "f" * 64
    monkeypatch.setattr(runner, "capture_provenance", lambda repo: changed)
    monkeypatch.setattr(sys, "argv", ["runner", "--suite", "migrations", "--report", str(target)])
    assert runner.main() == 2
    assert not target.exists()


def test_existing_runner_target_is_refused_before_services(tmp_path, monkeypatch, capsys):
    target = tmp_path.resolve() / "secret-canary.json"
    target.write_text("preserve")
    monkeypatch.setattr(runner.DisposableServices, "start", lambda _: pytest.fail("must not start services"))
    monkeypatch.setattr(sys, "argv", ["runner", "--suite", "migrations", "--report", str(target)])
    assert runner.main() == 2
    assert target.read_text() == "preserve"
    assert "secret-canary" not in capsys.readouterr().err


@pytest.mark.parametrize("arguments", [
    ["--suite", "api", "--report", "private-canary.json"],
    ["--suite", "migrations", "--report", "postgresql://secret-canary/report.json"],
    ["--suite", "migrations", "--report", "private-canary.json", "--", "private-command"],
    ["--suite", "migrations", "--rep", "private-canary.json"],
])
def test_cli_refuses_before_clients_without_echoing_supplied_data(monkeypatch, capsys, arguments):
    monkeypatch.setattr(sys, "argv", ["runner", *arguments])
    monkeypatch.setattr(runner.DisposableServices, "start", lambda _: pytest.fail("must refuse before client"))
    with patch("socket.socket", side_effect=AssertionError("network forbidden")):
        assert runner.main() == 2
    output = capsys.readouterr()
    assert "canary" not in output.err + output.out


def test_child_guard_still_precedes_report_and_application_imports(monkeypatch):
    spec = importlib.util.spec_from_file_location("rehearsal_migration_guard_test", ROOT / "scripts/run_test_migrations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def refuse():
        raise RuntimeError("guard called first")
    monkeypatch.setattr(module, "validate_test_environment", refuse)
    monkeypatch.setattr(sys, "argv", ["child", "--report", "secret-canary.json"])
    with patch("socket.socket", side_effect=AssertionError("network forbidden")), pytest.raises(RuntimeError, match="guard called first"):
        module.main()


def test_source_before_after_comparison_ignores_only_unrelated_dirty_flag():
    before = fixture()["provenance"]
    report.source_unchanged(before, {**before, "dirty_worktree": False})
    for key in ("head_revision", "tracked_diff_sha256", "inputs", "inputs_sha256", "source_dirty"):
        changed = copy.deepcopy(before)
        changed[key] = "changed"
        with pytest.raises(report.ReportError, match="inputs_changed"):
            report.source_unchanged(before, changed)


def test_real_source_inventory_binds_worktree_not_only_head():
    # Read-only repository hashes; no process other than read-only git commands.
    captured = report.capture_provenance(ROOT)
    by_path = {row["path"]: row for row in captured["inputs"]}
    for path in ("scripts/run_test_migrations.py", "scripts/schema_rehearsal_report.py", "api/uv.lock",
                 "api/services/ml08_pilot.schema.json"):
        assert by_path[path]["sha256"] == report.sha((ROOT / path).read_bytes())
    assert captured["inputs_sha256"] == report.sha(report.canonical(captured["inputs"]))
    assert len(captured["inputs"]) <= report.MAX_FILES
    # Exercise the consumer contract too: collection alone misses rejected paths.
    synthetic = fixture()
    synthetic["provenance"] = captured
    sealed = report.seal(synthetic)
    assert report.loads(report.canonical(sealed)) == sealed


def test_current_report_schema_never_accepts_process_credentials():
    value = fixture()
    value["runtime"]["database_url"] = "postgresql://CANARY"
    with pytest.raises(report.ReportError):
        report.validate(report.seal(value))


def test_entrypoint_help_and_wrong_arguments_are_source_only():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/run_disposable_tests.py"), "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0 and "--report" in result.stdout
