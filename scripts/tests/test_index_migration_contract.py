"""Offline contract/filesystem adversaries, not a measured database rehearsal.

The corpus fixture is measured locally with sockets denied. Protocol examples
are deliberately synthetic shape fixtures; native measurement is a separate gate.
"""
from __future__ import annotations

import copy
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import index_migration_contract as contract

from scripts.tests import test_index_migration_corpus as corpus_tests
from scripts.tests.test_index_migration_protocol import migration_report

measured_corpus = corpus_tests.measured


def provenance():
    inputs = [{"path": path, "sha256": contract.BASELINE_SHA256 if path == contract.BASELINE_PATH else "a" * 64,
               "size_bytes": 1} for path in sorted(contract.REQUIRED_INPUTS)]
    return {"head_revision": "b" * 40, "dirty_worktree": True, "source_dirty": True,
        "tracked_diff_sha256": "c" * 64, "inputs": inputs,
        "inputs_sha256": contract.sha(contract.canonical(inputs)), "unchanged_during_rehearsal": True}


def migrate():
    return {"version": contract.STAGE_VERSION, "stage": "migrate", "run_id": "1" * 32,
        "status": "passed", "schema_revision": "0068_answer_evidence", "measurement": None}


def reseal(value):
    value = copy.deepcopy(value)
    value["report_sha256"] = contract.sha(contract.canonical({key: item for key, item in value.items() if key != "report_sha256"}))
    return value


@pytest.fixture(scope="module")
def report(measured_corpus):
    """Real nested validators; only the migration observations are declared test data."""
    migration = migration_report()
    first = migrate()
    first["run_id"] = migration["run_id"]
    first["schema_revision"] = migration["schema_revision"]
    second = {**first, "stage": "measure", "measurement": {
        "corpus": measured_corpus, "migration": migration}}
    return contract.build_report(provenance=provenance(), backend="native", postgres_version_num=160013,
        started_at="2026-09-09T01:00:00.000000Z", completed_at="2026-09-09T01:00:01.000000Z",
        duration_ms=1000, phase_durations_ms={key: 100 for key in contract.DURATIONS},
        stages={"migrate": first, "measure": second}, cleanup_verified=True)


def test_real_nested_contract_report_round_trip_and_exclusive_publication(report, tmp_path):
    assert contract.loads_report(contract.canonical(report)) == report
    assert report["stages"][1]["measurement"]["migration"] == migration_report()
    assert all(value is None for value in report["unmeasured"].values())
    path = tmp_path.resolve() / "declared-unit-report.json"
    destination = contract.IndexMigrationDestination(path)
    try:
        destination.publish(report)
    finally:
        destination.close()
    assert contract.loads_report(path.read_bytes()) == report
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("path,value", [
    (("extra",), "PRIVATE"), (("scope",), "production_migration"), (("status",), "passed"),
    (("synthetic",), 1), (("production",), 0), (("cleanup_verified",), False),
    (("authority", "scientific_acceptance"), 0), (("authority", "deployment_approved"), True),
    (("unmeasured", "real_embedding_provider_cost_usd"), 0),
    (("unmeasured", "real_embedding_provider_tokens"), 0), (("unmeasured", "real_ann_latency_ms"), 0.0),
    (("unmeasured", "scientific_recall"), 1.0), (("unmeasured", "production_coverage"), "unknown"),
    (("runtime", "backend"), "existing"), (("runtime", "postgres_version_num"), True),
    (("runtime", "python"), "PRIVATE://credential"), (("runtime", "extra"), "private"),
    (("started_at",), "2026-09-10T01:00:00.000000Z"), (("completed_at",), "2026-09-10T01:00:00.000000Z"),
    (("completed_at",), "2026-02-30T01:00:00.000000Z"), (("duration_ms",), True),
    (("duration_ms",), 0), (("duration_ms",), 3600001), (("phase_durations_ms", "measure"), -1),
    (("phase_durations_ms", "measure"), True), (("phase_durations_ms", "measure"), 1001),
    (("phase_durations_ms", "extra"), 0), (("run_id",), "f" * 32),
])
def test_report_cannot_promote_unknown_cost_or_authority_or_cross_identity(report, path, value):
    changed = copy.deepcopy(report)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(contract.IndexMigrationError):
        contract.validate_report(reseal(changed))


@pytest.mark.parametrize("change", ["missing_stage", "duplicate_stage", "reordered", "different_schema",
    "different_run", "crossed_protocol", "corpus_identity", "case_identity", "legacy_coverage_invented",
    "legacy_facts_comparison", "provider_cost_zero", "scientific_authority", "matrix_missing", "hash"])
def test_nested_fixture_identity_phase_completeness_and_integrity_are_not_stubbed(report, change):
    value = copy.deepcopy(report)
    corpus = value["stages"][1]["measurement"]["corpus"]
    migration = value["stages"][1]["measurement"]["migration"]
    if change == "missing_stage": value["stages"].pop()
    elif change == "duplicate_stage": value["stages"].append(copy.deepcopy(value["stages"][0]))
    elif change == "reordered": value["stages"].reverse()
    elif change == "different_schema": value["stages"][0]["schema_revision"] = "0067_different"
    elif change == "different_run": value["stages"][0]["run_id"] = "e" * 32
    elif change == "crossed_protocol":
        migration["run_id"] = "e" * 32
        migration["logical_index"] = "migration-" + "e" * 32
    elif change == "corpus_identity": corpus["corpus_sha256"] = "f" * 64
    elif change == "case_identity": corpus["cases"][0]["input_sha256"] = "f" * 64
    elif change == "legacy_coverage_invented": corpus["cases"][0]["before"]["locator_coverage"] = {}
    elif change == "legacy_facts_comparison": corpus["baseline"]["facts_compared"] = True
    elif change == "provider_cost_zero": migration["embedding"]["provider_cost_usd"] = 0
    elif change == "scientific_authority": migration["authority"]["scientific_acceptance"] = True
    elif change == "matrix_missing": migration["queries"]["after"]["samples"].pop()
    else: value["report_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        contract.validate_report(value if change == "hash" else reseal(value))


@pytest.mark.parametrize("payload", [b"", b"{}", b"[]", b"null", b'"PRIVATE"',
    b'{"stage":"migrate","stage":"measure"}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}',
    b'{"x":"\\ud800"}', b"\xff", b"[" * 10000 + b"]" * 10000, b" " * (contract.MAX_BYTES + 1)])
def test_hostile_json_refuses_with_static_reason(payload):
    with pytest.raises(contract.IndexMigrationError) as error:
        contract.loads_stage(payload, "migrate")
    assert re.fullmatch(r"[a-z_]+", str(error.value))


@pytest.mark.parametrize("value", [{1: "private"}, {"x": {1}}, {"x": b"private"}, [float("nan")],
    [float("inf")], ["x" * (contract.MAX_BYTES + 1)], [None] * 100001])
def test_canonicalization_rejects_non_json_and_resource_overflow(value):
    with pytest.raises(contract.IndexMigrationError):
        contract.canonical(value)


def test_deep_tree_and_cycle_rejected_before_json_serialization():
    tree = leaf = {}
    for _ in range(33):
        leaf["next"] = {}
        leaf = leaf["next"]
    cycle = []
    cycle.append(cycle)
    for value in (tree, cycle):
        with pytest.raises(contract.IndexMigrationError):
            contract.canonical(value)


@pytest.mark.parametrize("field,value", [("extra", "PRIVATE"), ("version", "wrong"), ("stage", "measure"),
    ("run_id", "2" * 31), ("run_id", "A" * 32), ("status", "failed"), ("schema_revision", "secret://host"),
    ("schema_revision", None), ("measurement", {}), ("status", True)])
def test_closed_migrate_stage(field, value):
    original = migrate()
    assert contract.loads_stage(contract.canonical(original), "migrate") == original
    original[field] = value
    with pytest.raises(contract.IndexMigrationError):
        contract.validate_stage(original, "migrate")


@pytest.mark.parametrize("change", ["missing", "duplicate", "unsorted", "bad_hash", "bool_size", "negative_size",
    "overlarge_file", "traversal", "env", "baseline_hash", "inventory_hash", "authority_flag", "extra"])
def test_complete_source_inventory_and_frozen_baseline_are_required(change):
    value = provenance()
    contract._provenance(value)
    if change == "missing": value["inputs"].pop()
    elif change == "duplicate": value["inputs"].append(copy.deepcopy(value["inputs"][0]))
    elif change == "unsorted": value["inputs"].reverse()
    elif change == "bad_hash": value["inputs"][0]["sha256"] = "G" * 64
    elif change == "bool_size": value["inputs"][0]["size_bytes"] = True
    elif change == "negative_size": value["inputs"][0]["size_bytes"] = -1
    elif change == "overlarge_file": value["inputs"][0]["size_bytes"] = 4 * contract.MAX_BYTES + 1
    elif change == "traversal": value["inputs"][0]["path"] = "api/../secret.py"
    elif change == "env": value["inputs"][0]["path"] = "api/.env"
    elif change == "baseline_hash":
        next(row for row in value["inputs"] if row["path"] == contract.BASELINE_PATH)["sha256"] = "d" * 64
    elif change == "inventory_hash": value["inputs_sha256"] = "d" * 64
    elif change == "authority_flag": value["unchanged_during_rehearsal"] = 1
    else: value["extra"] = "PRIVATE"
    if change != "inventory_hash":
        value["inputs_sha256"] = contract.sha(contract.canonical(value["inputs"]))
    with pytest.raises(contract.IndexMigrationError):
        contract._provenance(value)


@pytest.mark.parametrize("field", ["head_revision", "tracked_diff_sha256", "inputs", "source_dirty"])
def test_changed_source_inventory_not_hidden_by_recalculated_summary(field):
    before, after = provenance(), provenance()
    if field == "head_revision": after[field] = "e" * 40
    elif field == "tracked_diff_sha256": after[field] = "e" * 64
    elif field == "source_dirty": after[field] = False
    else:
        after[field][0]["sha256"] = "e" * 64
        after["inputs_sha256"] = contract.sha(contract.canonical(after["inputs"]))
    with pytest.raises(contract.IndexMigrationError, match="changed"):
        contract.source_unchanged(before, after)
    after = provenance()
    after["dirty_worktree"] = False  # Unrelated documentation dirtiness is not executed-source drift.
    contract.source_unchanged(before, after)


def test_private_stage_publication_is_complete_0600_and_never_overwrites(tmp_path):
    path = tmp_path.resolve() / "stage.json"
    destination = contract.IndexMigrationDestination(path)
    try:
        destination.publish(migrate(), stage="migrate")
        assert contract.loads_stage(path.read_bytes(), "migrate") == migrate()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600 and path.stat().st_nlink == 1
        with pytest.raises(contract.legacy.ReportError):
            destination.publish(migrate(), stage="migrate")
    finally:
        destination.close()
    assert not list(path.parent.glob(".sclib-index-measurement-*"))


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "hardlink", "fifo"])
def test_destination_rejects_all_existing_targets(tmp_path, kind):
    path = tmp_path.resolve() / "report.json"
    if kind == "directory": path.mkdir()
    elif kind == "fifo": os.mkfifo(path)
    elif kind in {"symlink", "hardlink"}:
        target = tmp_path / "retained"
        target.write_bytes(b"DO_NOT_OVERWRITE")
        path.symlink_to(target) if kind == "symlink" else os.link(target, path)
    else: path.write_bytes(b"DO_NOT_OVERWRITE")
    with pytest.raises(contract.legacy.ReportError):
        contract.IndexMigrationDestination(path)
    if kind in {"file", "symlink", "hardlink"}:
        assert path.read_bytes() == b"DO_NOT_OVERWRITE"


def test_destination_rejects_symlink_ancestor_and_swapped_held_directory(tmp_path):
    parent = tmp_path.resolve() / "parent"
    parent.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(parent, target_is_directory=True)
    with pytest.raises(contract.legacy.ReportError):
        contract.IndexMigrationDestination(alias / "report.json")
    destination = contract.IndexMigrationDestination(parent / "report.json")
    parent.rename(tmp_path / "held-original")
    parent.mkdir()
    try:
        with pytest.raises(contract.legacy.ReportError):
            destination.publish(migrate(), stage="migrate")
    finally:
        destination.close()
    assert not list(parent.iterdir()) and not list((tmp_path / "held-original").iterdir())


@pytest.mark.parametrize("failure", ["file_fsync", "link", "directory_fsync", "cancel"])
def test_publication_failure_removes_only_owned_temporary_inode(tmp_path, monkeypatch, failure):
    path = tmp_path.resolve() / "report.json"
    destination = contract.IndexMigrationDestination(path)
    original_fsync, original_link = contract.os.fsync, contract.os.link
    def fsync(fd):
        is_dir = stat.S_ISDIR(os.fstat(fd).st_mode)
        if (failure == "file_fsync" and not is_dir) or (failure == "directory_fsync" and is_dir):
            raise OSError("PRIVATE filesystem detail")
        original_fsync(fd)
    def link(*args, **kwargs):
        if failure == "cancel": raise KeyboardInterrupt
        if failure == "link": raise OSError("PRIVATE filesystem detail")
        return original_link(*args, **kwargs)
    monkeypatch.setattr(contract.os, "fsync", fsync)
    monkeypatch.setattr(contract.os, "link", link)
    try:
        with pytest.raises(KeyboardInterrupt if failure == "cancel" else contract.IndexMigrationError):
            destination.publish(migrate(), stage="migrate")
    finally:
        destination.close()
    assert not path.exists() and not list(path.parent.glob(".sclib-index-measurement-*"))


def test_publication_racing_unrelated_file_is_preserved(tmp_path, monkeypatch):
    path = tmp_path.resolve() / "report.json"
    destination = contract.IndexMigrationDestination(path)
    original = contract.os.link
    def collision(*args, **kwargs):
        path.write_bytes(b"UNRELATED_NEW_FILE")
        return original(*args, **kwargs)
    monkeypatch.setattr(contract.os, "link", collision)
    try:
        with pytest.raises(contract.IndexMigrationError):
            destination.publish(migrate(), stage="migrate")
    finally:
        destination.close()
    assert path.read_bytes() == b"UNRELATED_NEW_FILE"
    assert not list(path.parent.glob(".sclib-index-measurement-*"))


@pytest.mark.parametrize("kind", ["valid", "empty", "oversized", "wrong_mode", "symlink", "hardlink", "fifo", "directory", "missing"])
def test_private_stage_reader_is_nonblocking_bounded_regular_owned_single_link(tmp_path, monkeypatch, kind):
    path = tmp_path.resolve() / "stage.json"
    if kind == "directory": path.mkdir()
    elif kind == "fifo": os.mkfifo(path, 0o600)
    elif kind != "missing":
        original = tmp_path / "original.json" if kind in {"symlink", "hardlink"} else path
        original.write_bytes(b"" if kind == "empty" else b"x" * (contract.MAX_BYTES + 1)
            if kind == "oversized" else contract.canonical(migrate()))
        original.chmod(0o644 if kind == "wrong_mode" else 0o600)
        if kind == "symlink": path.symlink_to(original)
        elif kind == "hardlink": os.link(original, path)
    original_open = os.open
    def nonblocking(target, flags, *args, **kwargs):
        assert flags & os.O_NONBLOCK and flags & os.O_NOFOLLOW
        return original_open(target, flags, *args, **kwargs)
    monkeypatch.setattr(contract.os, "open", nonblocking)
    if kind == "valid":
        assert contract.read_private_stage(path, "migrate") == migrate()
    else:
        with pytest.raises(contract.IndexMigrationError):
            contract.read_private_stage(path, "migrate")


@pytest.mark.parametrize("change", ["uid", "mtime", "size"])
def test_private_stage_rejects_owner_mismatch_and_mid_read_changes(tmp_path, monkeypatch, change):
    path = tmp_path.resolve() / "stage.json"
    path.write_bytes(contract.canonical(migrate()))
    path.chmod(0o600)
    original_fstat, count = contract.os.fstat, 0
    def fstat(fd):
        nonlocal count
        count += 1
        info = original_fstat(fd)
        if change == "uid" or count == 2:
            fields = {key: getattr(info, key) for key in dir(info) if key.startswith("st_")}
            key = {"uid": "st_uid", "mtime": "st_mtime_ns", "size": "st_size"}[change]
            fields[key] += 1
            return SimpleNamespace(**fields)
        return info
    monkeypatch.setattr(contract.os, "fstat", fstat)
    with pytest.raises(contract.IndexMigrationError):
        contract.read_private_stage(path, "migrate")


def source_tree(tmp_path, monkeypatch):
    """Only synthetic local bytes plus the pinned historical public source file."""
    for relative in contract.REQUIRED_INPUTS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes() if relative == contract.BASELINE_PATH else b"synthetic source\n")
    def git(argv, **kwargs):
        assert argv[0] == "git" and kwargs["cwd"] == tmp_path
        assert kwargs["env"] == {"PATH": os.defpath, "LANG": "C"}
        assert kwargs["timeout"] == 10 and kwargs["capture_output"] is True and kwargs["check"] is True
        return SimpleNamespace(stdout=b"b" * 40 + b"\n" if argv[1] == "rev-parse" else b"")
    monkeypatch.setattr(contract.subprocess, "run", git)
    return tmp_path


def test_source_capture_includes_all_runtime_trees_and_exact_frozen_baseline_without_secrets(tmp_path, monkeypatch):
    repo = source_tree(tmp_path, monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN", "PRIVATE_TOKEN")
    for relative in ("api/new_service.py", "scripts/new_worker.py", "ingestion/ingestion/new_parser.py",
                     "ingestion/uv.lock", "ingestion/pyproject.toml", "api/.env", "ingestion/.env",
                     "api/__pycache__/ignored.py", "scripts/.hidden/ignored.py"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PRIVATE_TOKEN" if ".env" in relative else b"new-synthetic-content")
    result = contract.capture_provenance(repo)
    inputs = {item["path"]: item for item in result["inputs"]}
    assert contract.REQUIRED_INPUTS <= inputs.keys()
    assert {"api/new_service.py", "scripts/new_worker.py", "ingestion/ingestion/new_parser.py",
        "ingestion/uv.lock", "ingestion/pyproject.toml"} <= inputs.keys()
    assert not any(".env" in key or "ignored" in key for key in inputs)
    assert "PRIVATE_TOKEN" not in contract.canonical(result).decode()
    assert inputs[contract.BASELINE_PATH]["sha256"] == contract.BASELINE_SHA256
    before = result
    (repo / "ingestion/ingestion/new_parser.py").write_bytes(b"changed source")
    with pytest.raises(contract.IndexMigrationError, match="changed"):
        contract.source_unchanged(before, contract.capture_provenance(repo))


@pytest.mark.parametrize("root", ["api", "scripts", "ingestion"])
@pytest.mark.parametrize("kind", ["fifo", "symlink_file", "symlink_directory"])
def test_every_source_tree_uses_nonblocking_no_follow_file_admission(tmp_path, monkeypatch, root, kind):
    repo = source_tree(tmp_path, monkeypatch)
    path = repo / root / "unsafe.py"
    if kind == "fifo": os.mkfifo(path)
    elif kind == "symlink_file": path.symlink_to(repo / "api/models/db.py")
    else: path.symlink_to(repo / "api/models", target_is_directory=True)
    original_open = os.open
    def nonblocking(target, flags, *args, **kwargs):
        assert flags & os.O_NONBLOCK and flags & os.O_NOFOLLOW
        return original_open(target, flags, *args, **kwargs)
    monkeypatch.setattr(contract.os, "open", nonblocking)
    with pytest.raises(contract.IndexMigrationError):
        contract.capture_provenance(repo)


def test_contract_import_and_validation_have_no_application_clients_or_site_dependencies():
    code = ("import runpy,sys; sys.path.insert(0,sys.argv[1]); "
        "runpy.run_path(sys.argv[1]+'/index_migration_contract.py'); "
        "assert not any(name in sys.modules for name in ['sqlalchemy','models','google','pytest','tiktoken'])")
    result = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(ROOT / "scripts")],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
