"""Offline synthetic contract/filesystem tests; no service or recovery claims."""
from __future__ import annotations

import copy
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import research_restore_contract as contract
import research_restore_index as index_contract

from scripts.tests import test_research_release_verifier as release_fixture
from scripts.tests.test_research_release_verifier import fixture as capsule_fixture


def provenance():
    files = [{"path": path, "sha256": "a" * 64, "size_bytes": 1} for path in sorted(contract._SOURCE_FILES)]
    return {"head_revision": "b" * 40, "dirty_worktree": True, "source_dirty": True,
        "tracked_diff_sha256": "c" * 64, "inputs": files, "inputs_sha256": contract.sha(contract.canonical(files)),
        "unchanged_during_rehearsal": True}


def stage_fixture(stage):
    return {"version": contract.STAGE_VERSION, "stage": stage, "status": "passed",
        "run_id": "2" * 32 if stage == "verify" else "1" * 32,
        "schema_revision": "0067_scientific_adjudication", "descriptor_sha256": None if stage == "migrate" else "d" * 64,
        "sql_snapshot_sha256": None if stage == "migrate" else "8" * 64,
        "index_check": index_report() if stage == "verify" else None,
        "checks": list(contract.CHECKS[stage]),
        "measurements": {key: 0 if stage == "migrate" else value for key, value in {
            "sql_tables": 100, "sql_rows": 200, "artifact_count": 5, "artifact_bytes": 3000, "index_members": 2}.items()}}


def index_report():
    return {"version": index_contract.REPORT_VERSION, **index_contract._REPORT_COUNTS,
        **{key: True for key in index_contract._REPORT_TRUE},
        **{key: False for key in index_contract._REPORT_FALSE},
        **{key: "e" * 64 for key in index_contract._REPORT_HASHES}}


def report_fixture():
    return contract.build_report(provenance=provenance(), backend="native",
        started_at="2026-09-09T00:00:00.000000Z", completed_at="2026-09-09T00:00:01.000000Z",
        duration_ms=1000, stage_results={stage: stage_fixture(stage) for stage in contract.STAGES},
        stage_durations_ms={name: 100 for name in contract.DURATIONS},
        transfer={"descriptor_sha256": "d" * 64, "manifest_sha256": "e" * 64, "bundle_sha256": "f" * 64,
                  "artifact_count": 5, "artifact_bytes": 3000, "dump_sha256": "9" * 64, "dump_bytes": 10000},
        cleanup_verified=True, source_postgres_version_num=160013, target_postgres_version_num=160013)


def index_descriptor():
    generation = str(UUID(int=100))
    return {"version": "research-restore-index/1.0.0", "logical_index": "restore-drill-" + UUID(generation).hex,
        "generation_id": generation, "activation_event_id": str(UUID(int=101)), "validation_id": str(UUID(int=102)),
        "claim_id": str(UUID(int=103)), "paper_id": "synthetic-paper", "material_id": "synthetic-material", "member_count": 2,
        **{key: "e" * 64 for key in ("claim_record_sha256", "raw_record_sha256", "pin_sha256", "member_manifest_sha256",
                                   "member_inventory_sha256", "hydration_sha256")}}


def descriptor(metadata):
    tables = [{"table": "materials", "row_count": 1, "bytes": 40, "sha256": "f" * 64}]
    return {"version": contract.DESCRIPTOR_VERSION, "fixture_version": contract.FIXTURE_VERSION,
        "source_run_id": "1" * 32, "schema_revision": "0067_scientific_adjudication", "release_id": str(UUID(int=10)),
        "manifest_sha256": metadata["manifest_sha256"], "bundle_sha256": metadata["bundle_sha256"],
        "artifact_files": [{"sha256": item["sha256"], "size_bytes": item["size_bytes"]}
            for item in metadata["files"] if item["path"].startswith("artifacts/")],
        "sql_snapshot": {"version": "research-restore-sql-snapshot/1.0.0", "tables": tables,
                         "sha256": contract.sha(contract.canonical(tables))},
        "actors": {key: str(UUID(int=index)) for index, key in enumerate(("admin", "curator", "reviewer", "publisher", "member", "revoked"), 20)},
        "access_targets": {key: str(UUID(int=index)) for index, key in enumerate(("claim_id", "work_id", "dataset_id", "publication_proposal_id"), 40)},
        "index": index_descriptor(),
        "authority": {key: False for key in ("scientific_acceptance", "ml_training_approved", "public_release_authorized")}}


def private_dir(path):
    path.mkdir(mode=0o700)
    return path


def bundle_fixture(tmp_path, *, physical_artifacts=False):
    root = private_dir(tmp_path.resolve() / "source")
    manifest, artifacts = capsule_fixture(graph=True)
    if physical_artifacts:
        base = release_fixture.contract.base_manifest(manifest)
        artifacts = {item["sha256"]: artifacts[item["sha256"]] for item in base["artifacts"]}
        coordinate, coordinate_bytes = release_fixture.artifact("coordinates", b"synthetic retained coordinates", kind="coordinates")
        input_row, input_bytes = release_fixture.artifact("run-input", b"synthetic exact producer input", kind="run_manifest")
        output_row, output_bytes = release_fixture.artifact("run-output", b"synthetic exact producer output", kind="run_manifest")
        artifacts.update(dict((coordinate_bytes, input_bytes, output_bytes)))
        structure = release_fixture.row("structure_records", "structure", material_id="MgB2", artifact_id=coordinate["row_id"],
            coordinate_artifact_kind="coordinates", structure_kind="calculated")
        run = release_fixture.row("research_runs", "run", run_kind="dft", input_manifest_id=input_row["row_id"],
            output_manifest_id=output_row["row_id"], status="completed")
        rows = base["rows"]
        event = next(row for row in rows if row["table"] == "research_events")
        event["data"].update(structure_id=structure["row_id"], producer_run_id=run["row_id"], assessment_run_kind="dft")
        event["row_sha256"] = release_fixture.contract.digest(event["data"])
        base = release_fixture.contract.build_manifest(dataset_id=base["dataset_id"],
            rows=[*rows, coordinate, input_row, output_row, structure, run],
            policy_artifact_ids=base["policy_artifact_ids"], source_roots=base["source_roots"], artifact_bytes=artifacts)
        manifest, artifacts = release_fixture.review(base, artifacts)
    manifest_bytes = contract.canonical(manifest)
    manifest_hash = contract.sha(manifest_bytes)
    contract.safe_write_new(root, "research-bundle/manifest.json", manifest_bytes)
    for checksum, payload in artifacts.items():
        contract.safe_write_new(root, "research-bundle/artifacts/" + checksum, payload)
    metadata = contract.capture_bundle(root, expected_manifest_sha256=manifest_hash)
    document = descriptor(metadata)
    raw = contract.canonical(document)
    contract.safe_write_new(root, "source-descriptor.json", raw)
    return root, contract.sha(raw), metadata, artifacts


def test_report_roundtrip_and_unknown_production_recovery():
    value = report_fixture()
    assert contract.loads_report(contract.canonical(value)) == value
    assert all(flag is False for flag in value["authority"].values())
    assert all(item is None for item in value["unmeasured"].values())
    assert value["source_run_id"] != value["target_run_id"]


@pytest.mark.parametrize("change", [
    lambda d: d.update(extra="private"),
    lambda d: d.update(synthetic=1), lambda d: d.update(production=0),
    lambda d: d["authority"].update(scientific_acceptance=True),
    lambda d: d["authority"].update(public_release_authorized=0),
    lambda d: d["unmeasured"].update(production_rto_seconds=1),
    lambda d: d["unmeasured"].update(production_rpo_seconds=0),
    lambda d: d.update(cleanup_verified=False), lambda d: d.update(cleanup_verified=1),
    lambda d: d.update(duration_ms=True), lambda d: d.update(duration_ms=799),
    lambda d: d["durations_ms"].update(verify=-1), lambda d: d["durations_ms"].update(unmeasured=1),
    lambda d: d.update(target_run_id=d["source_run_id"]),
    lambda d: d.update(source_run_id="secret://host"),
    lambda d: d.update(completed_at="2026-09-08T00:00:00.000000Z"),
    lambda d: d["runtime"].update(source_postgres_version_num="160013"),
    lambda d: d["runtime"].update(target_postgres_version_num=160014),
    lambda d: d["runtime"].update(system="private@host"),
    lambda d: d["runtime"].update(backend="remote"),
    lambda d: d["runtime"].update(backend={"secret": "private"}),
    lambda d: d["stages"].pop(),
    lambda d: d["stages"].append(copy.deepcopy(d["stages"][0])),
    lambda d: d["stages"][2]["result"].update(run_id=d["source_run_id"]),
    lambda d: d["stages"][1]["result"]["checks"].pop(),
    lambda d: d["stages"][1]["result"]["checks"].append("synthetic_rows_seeded"),
    lambda d: d["stages"][2]["result"]["measurements"].update(sql_rows=199),
    lambda d: d["stages"][2]["result"].update(sql_snapshot_sha256="0" * 64),
    lambda d: d["stages"][2]["result"].update(index_check=None),
    lambda d: d["stages"][2]["result"]["index_check"].update(provider_io_performed=True),
    lambda d: d["stages"][2]["result"]["index_check"].update(replay_upsert_count=2),
    lambda d: d["stages"][1]["result"].update(index_check=index_report()),
    lambda d: d["transfer"].update(dump_bytes=0),
    lambda d: d["transfer"].update(artifact_bytes=3001),
    lambda d: d["provenance"].update(unchanged_during_rehearsal=False),
    lambda d: d["provenance"]["inputs"].pop(),
    lambda d: d["provenance"]["inputs"][0].update(path="api/.env"),
    lambda d: d["provenance"]["inputs"].append(copy.deepcopy(d["provenance"]["inputs"][0])),
])
def test_invalid_or_overclaiming_report_rejected_even_when_resealed(change):
    value = report_fixture()
    change(value)
    with pytest.raises(contract.RestoreContractError):
        contract.validate_report(contract.seal(value))


@pytest.mark.parametrize("stage", contract.STAGES)
def test_closed_stage_report(stage):
    value = stage_fixture(stage)
    assert contract.loads_stage(contract.canonical(value), stage) == value
    with pytest.raises(contract.RestoreContractError):
        contract.loads_stage(contract.canonical(value) + b"\n", stage)
    value["checks"][0] = "arbitrary_success"
    with pytest.raises(contract.RestoreContractError):
        contract.validate_stage(value, stage)


@pytest.mark.parametrize("payload", [b"[]", b"{}", b'{"x":1,"x":2}', b'{"x":NaN}',
    b'{"x":1e999}', b'{"x":"\\ud800"}', b"\xff", b"[" * 10000 + b"]" * 10000])
def test_hostile_report_json_is_sanitized(payload):
    with pytest.raises(contract.RestoreContractError) as error:
        contract.loads_report(payload)
    assert re_safe(error.value)


def re_safe(error):
    import re
    return re.fullmatch(r"[a-z_]+", str(error))


def test_private_bundle_copy_is_exact_and_has_no_science_authority(tmp_path):
    source, pin, metadata, artifacts = bundle_fixture(tmp_path)
    target = private_dir(tmp_path.resolve() / "target")
    result = contract.copy_recovery_inputs(source, target, expected_descriptor_sha256=pin)
    assert result == {"descriptor_sha256": pin, **{key: metadata[key] for key in (
        "manifest_sha256", "bundle_sha256", "artifact_count", "artifact_bytes")}}
    assert contract.capture_bundle(target, expected_manifest_sha256=metadata["manifest_sha256"]) == metadata
    assert contract.read_artifact_bytes(target, expected_manifest_sha256=metadata["manifest_sha256"]) == artifacts
    assert contract.read_source_descriptor(target, expected_descriptor_sha256=pin) == contract.read_source_descriptor(source, expected_descriptor_sha256=pin)
    for path in target.rglob("*"):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)
        if path.is_file():
            assert path.stat().st_nlink == 1


@pytest.mark.parametrize("change", ["missing", "corrupt", "extra", "symlink", "hardlink", "directory", "world_readable", "manifest", "descriptor"])
def test_missing_corrupt_or_aliased_bundle_never_copies(tmp_path, change):
    source, pin, metadata, artifacts = bundle_fixture(tmp_path)
    target = private_dir(tmp_path.resolve() / "target")
    artifact = source / "research-bundle" / "artifacts" / next(iter(artifacts))
    if change == "missing":
        artifact.unlink()
    elif change == "corrupt":
        artifact.write_bytes(b"corrupt")
    elif change == "extra":
        extra = artifact.parent / ("0" * 64)
        extra.write_bytes(b"extra")
        extra.chmod(0o600)
    elif change in {"symlink", "hardlink"}:
        elsewhere = tmp_path / "private-original"
        artifact.rename(elsewhere)
        if change == "symlink":
            artifact.symlink_to(elsewhere)
        else:
            os.link(elsewhere, artifact)
    elif change == "directory":
        artifact.unlink()
        artifact.mkdir(mode=0o700)
    elif change == "world_readable":
        artifact.chmod(0o644)
    elif change == "manifest":
        (source / "research-bundle" / "manifest.json").write_bytes(b"{}")
    else:
        (source / "source-descriptor.json").write_bytes(b"{}")
    with pytest.raises(contract.RestoreContractError):
        contract.copy_recovery_inputs(source, target, expected_descriptor_sha256=pin)
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("collision", ["source", "nested", "descriptor", "bundle", "target_symlink", "ancestor_symlink"])
def test_distinct_private_destination_and_no_overwrite(tmp_path, collision):
    source, pin, _, _ = bundle_fixture(tmp_path)
    target = private_dir(tmp_path.resolve() / "target")
    if collision == "source":
        target = source
    elif collision == "nested":
        target = private_dir(source / "nested")
    elif collision in {"descriptor", "bundle"}:
        path = target / ("source-descriptor.json" if collision == "descriptor" else "research-bundle")
        path.write_bytes(b"KEEP")
    elif collision == "target_symlink":
        link = tmp_path.resolve() / "link"
        link.symlink_to(target, target_is_directory=True)
        target = link
    else:
        parent = tmp_path.resolve() / "parent-link"
        parent.symlink_to(tmp_path.resolve(), target_is_directory=True)
        target = parent / "target"
    with pytest.raises(contract.RestoreContractError):
        contract.copy_recovery_inputs(source, target, expected_descriptor_sha256=pin)
    if collision in {"descriptor", "bundle"}:
        assert path.read_bytes() == b"KEEP"


def test_bundle_directory_swap_during_read_is_detected(tmp_path, monkeypatch):
    source, pin, _, _ = bundle_fixture(tmp_path)
    target = private_dir(tmp_path.resolve() / "target")
    original = contract._read
    swapped = False

    def swap(directory, name, maximum):
        nonlocal swapped
        value = original(directory, name, maximum)
        if name == "manifest.json" and not swapped:
            swapped = True
            directory.path.rename(directory.path.with_name("saved-bundle"))
            directory.path.mkdir(mode=0o700)
        return value

    monkeypatch.setattr(contract, "_read", swap)
    with pytest.raises(contract.RestoreContractError):
        contract.copy_recovery_inputs(source, target, expected_descriptor_sha256=pin)
    assert swapped and list(target.iterdir()) == []


def test_source_mutation_during_copy_is_rejected_without_deleting_any_old_data(tmp_path, monkeypatch):
    source, pin, _, artifacts = bundle_fixture(tmp_path)
    target = private_dir(tmp_path.resolve() / "target")
    unrelated = target / "keep.txt"
    unrelated.write_bytes(b"KEEP")
    original = contract.safe_write_new
    changed = False

    def mutate(root, relative, payload):
        nonlocal changed
        original(root, relative, payload)
        if Path(root) == target and not changed:
            changed = True
            (source / "research-bundle" / "artifacts" / next(iter(artifacts))).write_bytes(b"altered")

    monkeypatch.setattr(contract, "safe_write_new", mutate)
    with pytest.raises(contract.RestoreContractError):
        contract.copy_recovery_inputs(source, target, expected_descriptor_sha256=pin)
    assert changed and unrelated.read_bytes() == b"KEEP"


def test_source_pin_and_missing_artifact_descriptor_are_not_self_repaired(tmp_path):
    source, pin, metadata, _ = bundle_fixture(tmp_path)
    target = private_dir(tmp_path.resolve() / "target")
    with pytest.raises(contract.RestoreContractError):
        contract.copy_recovery_inputs(source, target, expected_descriptor_sha256="a" * 64)
    with pytest.raises(contract.RestoreContractError):
        contract.copy_recovery_inputs(source, target, expected_descriptor_sha256=pin, expected_manifest_sha256="b" * 64)
    value = descriptor(metadata)
    value["artifact_files"].pop()
    raw = contract.canonical(value)
    (source / "source-descriptor.json").write_bytes(raw)
    with pytest.raises(contract.RestoreContractError, match="artifact_mismatch"):
        contract.copy_recovery_inputs(source, target, expected_descriptor_sha256=contract.sha(raw))


@pytest.mark.parametrize("kind", ["coordinates", "input_manifest_id", "output_manifest_id"])
@pytest.mark.parametrize("change", ["missing", "corrupt"])
def test_bound_structure_and_run_artifact_bytes_cannot_be_missing_or_replaced(tmp_path, kind, change):
    source, pin, metadata, _ = bundle_fixture(tmp_path, physical_artifacts=True)
    manifest = contract._json((source / "research-bundle" / "manifest.json").read_bytes(), contract.MAX_FILE_BYTES)
    if kind == "coordinates":
        artifact_id = next(row["data"]["artifact_id"] for row in manifest["rows"] if row["table"] == "structure_records")
    else:
        artifact_id = next(row["data"][kind] for row in manifest["rows"] if row["table"] == "research_runs")
    checksum = next(row["data"]["bytes_sha256"] for row in manifest["rows"] if row["table"] == "evidence_artifacts" and row["row_id"] == artifact_id)
    leaf = source / "research-bundle" / "artifacts" / checksum
    if change == "missing":
        leaf.unlink()
    else:
        leaf.write_bytes(b"changed retained bytes")
    target = private_dir(tmp_path.resolve() / "target")
    with pytest.raises(contract.RestoreContractError):
        contract.copy_recovery_inputs(source, target, expected_descriptor_sha256=pin)
    assert not list(target.iterdir())


@pytest.mark.parametrize("limit,value", [("MAX_FILE_BYTES", 10), ("MAX_BUNDLE_BYTES", 10), ("MAX_ARTIFACTS", 1)])
def test_actual_capture_resource_limits_fail_closed(tmp_path, monkeypatch, limit, value):
    source, pin, _, _ = bundle_fixture(tmp_path)
    target = private_dir(tmp_path.resolve() / "target")
    monkeypatch.setattr(contract, limit, value)
    with pytest.raises(contract.RestoreContractError):
        contract.copy_recovery_inputs(source, target, expected_descriptor_sha256=pin)
    assert not list(target.iterdir())


@pytest.mark.parametrize("change", [
    lambda d: d.update(extra="private"),
    lambda d: d["actors"].update(reviewer=d["actors"]["curator"]),
    lambda d: d["index"].update(member_count=True),
    lambda d: d["sql_snapshot"]["tables"][0].update(row_count=True),
    lambda d: d["sql_snapshot"]["tables"].append(copy.deepcopy(d["sql_snapshot"]["tables"][0])),
    lambda d: d["sql_snapshot"]["tables"][0].update(table="private;SELECT"),
    lambda d: d["artifact_files"][0].update(size_bytes=-1),
    lambda d: d["artifact_files"].append(copy.deepcopy(d["artifact_files"][0])),
    lambda d: d["authority"].update(scientific_acceptance=0),
])
def test_private_descriptor_is_deeply_closed(tmp_path, change):
    source, pin, _, _ = bundle_fixture(tmp_path)
    value = contract.read_source_descriptor(source, expected_descriptor_sha256=pin)
    change(value)
    with pytest.raises(contract.RestoreContractError):
        contract.validate_descriptor(value)


@pytest.mark.parametrize("relative", ["../escape", "/absolute", "config.json", "research-bundle/../escape", "research-bundle/artifacts/not-hash"])
def test_fixed_leaf_writer_rejects_paths(tmp_path, relative):
    root = private_dir(tmp_path.resolve() / "private")
    with pytest.raises(contract.RestoreContractError):
        contract.safe_write_new(root, relative, b"private")
    assert not list(root.iterdir())


def test_private_writer_collision_preserves_bytes(tmp_path):
    root = private_dir(tmp_path.resolve() / "private")
    contract.safe_write_new(root, "source-descriptor.json", b"original")
    with pytest.raises(contract.RestoreContractError):
        contract.safe_write_new(root, "source-descriptor.json", b"replacement")
    assert (root / "source-descriptor.json").read_bytes() == b"original"


def test_regular_read_atime_change_is_not_reported_as_content_mutation(tmp_path, monkeypatch):
    root = private_dir(tmp_path.resolve() / "private")
    contract.safe_write_new(root, "source-descriptor.json", b"actual bytes")
    original = os.fstat
    calls = 0
    def atime_only(fd):
        nonlocal calls
        observed = original(fd)
        calls += 1
        return SimpleNamespace(**{key: getattr(observed, key) for key in (
            "st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_size", "st_mtime_ns", "st_ctime_ns")},
            st_atime_ns=calls)
    monkeypatch.setattr(contract.os, "fstat", atime_only)
    assert contract.read_private_json(root / "source-descriptor.json") == b"actual bytes"


def test_copy_detects_target_directory_swap_without_touching_replacement(tmp_path, monkeypatch):
    source, pin, _, _ = bundle_fixture(tmp_path)
    target = private_dir(tmp_path.resolve() / "target")
    original = contract.safe_write_new
    replacement_file = target / "keep"
    swapped = False
    def swap(root, relative, payload):
        nonlocal swapped
        original(root, relative, payload)
        if Path(root) == target and not swapped:
            swapped = True
            target.rename(target.with_name("held-target"))
            target.mkdir(mode=0o700)
            replacement_file.write_bytes(b"untouched replacement")
    monkeypatch.setattr(contract, "safe_write_new", swap)
    with pytest.raises(contract.RestoreContractError):
        contract.copy_recovery_inputs(source, target, expected_descriptor_sha256=pin)
    assert swapped and list(target.iterdir()) == [replacement_file]
    assert replacement_file.read_bytes() == b"untouched replacement"


def test_report_publication_requires_cleanup_and_preserves_previous_file(tmp_path):
    path = tmp_path.resolve() / "restore.json"
    destination = contract.RestoreReportDestination(path)
    try:
        value = report_fixture()
        unfinished = contract.seal({**value, "cleanup_verified": False})
        assert contract.validate_report(unfinished, internal=True)
        with pytest.raises(contract.RestoreContractError):
            destination.publish(unfinished)
        with pytest.raises(contract.RestoreContractError):
            destination.publish(unfinished, internal=True)
        assert not path.exists()
        destination.publish(value)
        assert contract.loads_report(path.read_bytes()) == value
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        before = path.read_bytes()
        with pytest.raises((contract.RestoreContractError, contract.legacy.ReportError)):
            destination.publish(value)
        assert path.read_bytes() == before
    finally:
        destination.close()


def test_report_path_swap_before_publication_refuses(tmp_path):
    parent = private_dir(tmp_path.resolve() / "output")
    destination = contract.RestoreReportDestination(parent / "restore.json")
    try:
        parent.rename(parent.with_name("held"))
        parent.mkdir(mode=0o700)
        with pytest.raises(contract.legacy.ReportError):
            destination.publish(report_fixture())
        assert not list(parent.iterdir()) and not list(parent.with_name("held").iterdir())
    finally:
        destination.close()


def test_exact_source_inventory_must_include_new_runner_and_sources():
    value = provenance()
    contract.source_unchanged(value, copy.deepcopy(value))
    changed = copy.deepcopy(value)
    changed["inputs"][0]["sha256"] = "f" * 64
    changed["inputs_sha256"] = contract.sha(contract.canonical(changed["inputs"]))
    with pytest.raises(contract.RestoreContractError, match="source_changed"):
        contract.source_unchanged(value, changed)
    value["inputs"] = [row for row in value["inputs"] if row["path"] != "scripts/research_restore_contract.py"]
    value["inputs_sha256"] = contract.sha(contract.canonical(value["inputs"]))
    with pytest.raises(contract.RestoreContractError):
        contract.source_unchanged(value, value)


def test_actual_repository_provenance_retains_packaged_schema_bytes():
    value = contract.capture_provenance(ROOT)
    schema_path = "api/services/ml08_pilot.schema.json"
    schema = next(item for item in value["inputs"] if item["path"] == schema_path)
    assert schema["sha256"] == contract.sha((ROOT / schema_path).read_bytes())
    contract.source_unchanged(value, copy.deepcopy(value))
    changed = copy.deepcopy(value)
    next(item for item in changed["inputs"] if item["path"] == schema_path)["sha256"] = "f" * 64
    changed["inputs_sha256"] = contract.sha(contract.canonical(changed["inputs"]))
    with pytest.raises(contract.RestoreContractError, match="restore_source_changed"):
        contract.source_unchanged(value, changed)


@pytest.mark.parametrize("path", [
    "api/services/private.json",
    "api/models/ml08_pilot.schema.json",
    "scripts/ml08_pilot.schema.json",
    "api/services/nested/ml08_pilot.schema.json",
    "api/services/../ml08_pilot.schema.json",
    "api/services/.private.schema.json",
])
def test_restore_provenance_rejects_out_of_scope_json_even_after_resealing(path):
    value = provenance()
    value["inputs"].append({"path": path, "sha256": "d" * 64, "size_bytes": 1})
    value["inputs"].sort(key=lambda item: item["path"])
    value["inputs_sha256"] = contract.sha(contract.canonical(value["inputs"]))
    with pytest.raises(contract.RestoreContractError, match="invalid_restore_input_path"):
        contract.source_unchanged(value, value)
