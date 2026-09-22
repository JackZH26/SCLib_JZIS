"""Offline synthetic adversarial tests; never open a database or provider."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts import export_ml_foundation_snapshot as exporter
from scripts import plan_typed_claim_backfill as planner
from scripts import verify_shadow_import as verifier


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _reseal_source(path: Path) -> None:
    manifest = json.loads(path.read_bytes())
    for entry in manifest["files"].values():
        leaf = path.parent / entry["path"]
        entry.update(sha256=_digest(leaf), bytes=leaf.stat().st_size)
    manifest["license_manifest_sha256"] = manifest["files"]["license_manifest"]["sha256"]
    _write_json(path, manifest)
    names = [entry["path"] for entry in manifest["files"].values()] + [path.name]
    (path.parent / "checksums.sha256").write_text(
        "".join(f"{_digest(path.parent / name)}  {name}\n" for name in sorted(names))
    )
    (path.parent / "export_manifest.sha256").write_text(f"{_digest(path)}  {path.name}\n")


def _reseal_plan(path: Path) -> None:
    manifest = json.loads(path.read_bytes())
    for name, entry in manifest["outputs"].items():
        entry["sha256"] = _digest(path.parent / name)
    _write_json(path, manifest)
    (path.parent / "manifest.sha256").write_text(f"{_digest(path)}  manifest.json\n")
    convenience = json.loads((path.parent / "source_snapshots.jsonl").read_bytes())
    convenience["manifest_sha256"] = _digest(path)
    planner.write_jsonl(path.parent / "source_snapshots.jsonl", [convenience])


def _source(root: Path, *, records: list | str | None = None, existing: bool = False) -> Path:
    root.mkdir()
    papers = [
        {
            "id": "arxiv:2306.07275",
            "source": "arxiv",
            "arxiv_id": "2306.07275",
            "doi": None,
            "related_paper_id": None,
            "title": "SOURCE_PRIVATE_TOKEN",
            "date_submitted": "2023-06-12",
            "date_published": None,
            "status": "published",
            "paper_type": "preprint",
        }
    ]
    if records is None:
        records = [{"paper_id": papers[0]["id"], "tc_kelvin": 39.0, "measurement": "resistivity"}]
    materials = [
        {"id": "mat:mgb2", "formula": "MgB2", "formula_normalized": "MgB2", "records": records}
    ]
    mapping = [
        {
            "paper_id": papers[0]["id"],
            "work_id": "22222222-2222-4222-8222-222222222222",
            "relation_type": "preprint",
            "match_method": "manual",
            "review_status": "accepted",
        }
    ]
    rows = {"materials": materials, "papers": papers}
    if existing:
        rows["paper_work_map"] = mapping
    files = {}
    for key, values in rows.items():
        path = root / f"{key}.jsonl"
        path.write_bytes(b"".join(exporter.canonical_json_bytes(row) + b"\n" for row in values))
        files[key] = {
            "path": path.name,
            "sha256": _digest(path),
            "bytes": path.stat().st_size,
            "rows": len(values),
        }
    snapshot = uuid.UUID("11111111-1111-4111-8111-111111111111")
    watermark = "2026-09-07T00:00:00+00:00"
    license_payload = exporter.build_license_manifest(
        source_snapshot_id=snapshot,
        dataset_version="synthetic-v1",
        database_watermark=watermark,
        material_scope="public",
        paper_source_counts={"arxiv": 1},
        material_record_source_counts={
            "arxiv_ner": len(json.loads(records) if isinstance(records, str) else records)
        },
    )
    license_path = root / "license_manifest.json"
    _write_json(license_path, license_payload)
    files["license_manifest"] = {
        "path": license_path.name,
        "sha256": _digest(license_path),
        "bytes": license_path.stat().st_size,
        "rows": 1,
    }
    state = exporter.SnapshotState(
        database_watermark=watermark,
        database_name="synthetic-only",
        postgres_version="16",
        transaction_isolation="repeatable read",
        transaction_read_only="on",
        transaction_snapshot="1:1:",
        wal_lsn=None,
        alembic_revision="0053_synthetic",
        paper_work_map_table_present=existing,
        counts={"materials": 1, "papers": 1, "chunks": 3, "paper_work_map": int(existing)},
        max_material_updated_at=watermark,
        max_paper_updated_at=watermark,
        paper_source_counts={"arxiv": 1},
        material_record_source_counts={"arxiv_ner": 1},
        material_record_count=len(json.loads(records) if isinstance(records, str) else records),
    )
    manifest = exporter.build_export_manifest(
        source_snapshot_id=snapshot,
        dataset_version="synthetic-v1",
        site_git_sha="a" * 40,
        material_scope="public",
        state=state,
        files=files,
        queries={key: "SELECT synthetic" for key in rows},
        include_paper_work_map=existing,
    )
    path = root / "export_manifest.json"
    _write_json(path, manifest)
    exporter._write_checksum_files(root, [entry["path"] for entry in files.values()] + [path.name])
    return path


def _plan(source_path: Path, root: Path) -> Path:
    source = planner.load_source_export_manifest(source_path)
    plan = planner.build_backfill_plan(
        planner.load_jsonl(source["materials_path"]),
        planner.load_jsonl(source["papers_path"]),
        source_snapshot_id=source["source_snapshot_id"],
        existing_paper_work=planner.load_jsonl(source["existing_map_path"])
        if source["existing_map_path"]
        else [],
    )
    planner.write_plan_artifacts(
        plan,
        output_dir=root,
        materials_path=source["materials_path"],
        papers_path=source["papers_path"],
        existing_map_path=source["existing_map_path"],
        dataset_version=source["dataset_version"],
        site_git_sha=source["site_git_sha"],
        database_watermark=source["database_watermark"],
        chunk_count=source["chunk_count"],
        license_manifest_sha256=source["license_manifest_sha256"],
        source_export_manifest_path=source_path,
        source_export_manifest_sha256=source["manifest_sha256"],
        source_alembic_revision=source["alembic_revision"],
    )
    return root / "manifest.json"


@pytest.fixture
def bundle(tmp_path: Path) -> dict:
    root = tmp_path.resolve()
    source_path = _source(root / "source", existing=True)
    plan_path = _plan(source_path, root / "plan")
    return {
        "source_manifest": source_path,
        "plan_manifest": plan_path,
        "expected_source_manifest_sha256": _digest(source_path),
        "expected_plan_manifest_sha256": _digest(plan_path),
    }


def _reject(args: dict, match: str | None = None) -> None:
    with pytest.raises(verifier.ShadowImportVerificationError, match=match):
        verifier.verify_shadow_import(**args)


def test_valid_payload_is_replayed_normalized_and_not_approval(bundle: dict) -> None:
    first = verifier.verify_shadow_import(**bundle)
    assert first == verifier.verify_shadow_import(**bundle)
    assert json.loads(json.dumps(first)) == first
    assert first["claims"][0]["available_at"] is None
    assert first["proposed_source_snapshot"]["status"] == "building"
    assert first["proposed_source_snapshot"]["metadata"]["failure_count"] == 0
    assert first["paper_work_map"][0]["work_id"] == "22222222-2222-4222-8222-222222222222"
    for flag in (
        "scientific_acceptance",
        "permissions_verified",
        "historical_result_availability_verified",
        "database_verified",
        "public_release_authorized",
    ):
        assert first["verified_metadata"][flag] is False
    unsigned = copy.deepcopy(first)
    digest = unsigned.pop("payload_sha256")
    assert digest == hashlib.sha256(verifier._canonical(unsigned)).hexdigest()
    unsigned["papers"][0]["title"] = "mutated"
    assert digest != hashlib.sha256(verifier._canonical(unsigned)).hexdigest()


@pytest.mark.parametrize(
    "key", ["expected_source_manifest_sha256", "expected_plan_manifest_sha256"]
)
@pytest.mark.parametrize("bad_hash", [None, "A" * 64, "0" * 64, "../manifest.json"])
def test_operator_pins_are_required_and_not_read_from_sidecars(
    bundle: dict, key: str, bad_hash: str
) -> None:
    bundle[key] = bad_hash
    _reject(bundle)


@pytest.mark.parametrize(
    "kind,name",
    [
        ("source", "materials.jsonl"),
        ("source", "checksums.sha256"),
        ("source", "license_manifest.json"),
        ("plan", "claims.jsonl"),
        ("plan", "source_snapshots.jsonl"),
        ("plan", "manifest.sha256"),
    ],
)
def test_missing_leaf_rejected(bundle: dict, kind: str, name: str) -> None:
    bundle[f"{kind}_manifest"].parent.joinpath(name).unlink()
    _reject(bundle)


@pytest.mark.parametrize("kind,name", [("source", "materials.jsonl"), ("plan", "claims.jsonl")])
def test_leaf_tamper_rejected_without_resealing(bundle: dict, kind: str, name: str) -> None:
    path = bundle[f"{kind}_manifest"].parent / name
    path.write_bytes(path.read_bytes() + b"{}\n")
    _reject(bundle)


@pytest.mark.parametrize(
    "name,field,value",
    [
        ("claims", "value_kelvin", 999),
        ("claims", "available_at", "1900-01-01"),
        ("claims", "validity_status", "accepted"),
        ("works", "canonical_title", "forged"),
        ("paper_work_map", "review_status", "rejected"),
        ("compositions", "composition_status", "invalid"),
    ],
)
def test_rehashed_plan_cannot_change_replayed_payload(
    bundle: dict, name: str, field: str, value: object
) -> None:
    path = bundle["plan_manifest"].parent / f"{name}.jsonl"
    rows = planner.load_jsonl(path)
    rows[0][field] = value
    planner.write_jsonl(path, rows)
    _reseal_plan(bundle["plan_manifest"])
    bundle["expected_plan_manifest_sha256"] = _digest(bundle["plan_manifest"])
    _reject(bundle, "reconstructed")


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_version", "wrong"),
        ("database_watermark", "2026-01-01T00:00:00Z"),
        ("source_snapshot_id", "33333333-3333-4333-8333-333333333333"),
        ("chunk_count", 4),
        ("source_export_manifest_sha256", "f" * 64),
        ("source_alembic_revision", "wrong"),
        ("claim_mapper_version", "unknown"),
        ("formula_parser_version", "unknown"),
        ("work_identity_version", "unknown"),
    ],
)
def test_rehashed_manifest_cannot_change_capture_or_version(
    bundle: dict, field: str, value: object
) -> None:
    path = bundle["plan_manifest"]
    document = json.loads(path.read_bytes())
    document[field] = value
    _write_json(path, document)
    _reseal_plan(path)
    bundle["expected_plan_manifest_sha256"] = _digest(path)
    _reject(bundle)


def test_changed_source_capture_with_new_pin_still_cannot_match_old_plan(bundle: dict) -> None:
    path = bundle["source_manifest"]
    leaf = path.parent / "papers.jsonl"
    rows = planner.load_jsonl(leaf)
    rows[0]["title"] = "A changed source capture"
    leaf.write_bytes(exporter.canonical_json_bytes(rows[0]) + b"\n")
    _reseal_source(path)
    bundle["expected_source_manifest_sha256"] = _digest(path)
    _reject(bundle, "source capture hash")


@pytest.mark.parametrize(
    "field,value", [("status", "ready"), ("paper_count", 1000), ("manifest_sha256", "f" * 64)]
)
def test_unchecksummed_snapshot_never_becomes_authority(
    bundle: dict, field: str, value: object
) -> None:
    path = bundle["plan_manifest"].parent / "source_snapshots.jsonl"
    row = json.loads(path.read_bytes())
    row[field] = value
    planner.write_jsonl(path, [row])
    _reject(bundle, "convenience snapshot")


@pytest.mark.parametrize("kind", ["source", "plan"])
@pytest.mark.parametrize("alias", ["symlink", "hardlink", "directory", "fifo"])
def test_unsafe_leaf_types_and_aliases_are_rejected(
    bundle: dict, kind: str, alias: str, tmp_path: Path
) -> None:
    leaf = bundle[f"{kind}_manifest"].parent / (
        "papers.jsonl" if kind == "source" else "claims.jsonl"
    )
    outside = tmp_path / "outside"
    outside.write_bytes(leaf.read_bytes())
    leaf.unlink()
    if alias == "symlink":
        leaf.symlink_to(outside)
    elif alias == "hardlink":
        os.link(outside, leaf)
    elif alias == "directory":
        leaf.mkdir()
    else:
        os.mkfifo(leaf)
    _reject(bundle)


@pytest.mark.parametrize("kind", ["source", "plan"])
def test_symlink_ancestor_and_traversal_rejected(bundle: dict, kind: str, tmp_path: Path) -> None:
    original = bundle[f"{kind}_manifest"]
    alias = tmp_path / "alias"
    alias.symlink_to(original.parent, target_is_directory=True)
    bundle[f"{kind}_manifest"] = alias / original.name
    _reject(bundle)
    bundle[f"{kind}_manifest"] = original.parent / ".." / original.parent.name / original.name
    _reject(bundle, "traversal")


@pytest.mark.parametrize("kind", ["source", "plan"])
def test_unexpected_file_payload_rejected(bundle: dict, kind: str) -> None:
    (bundle[f"{kind}_manifest"].parent / "secret.json").write_text('{"payload":"not allowed"}')
    _reject(bundle)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"nested":{"x":1,"x":2}}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":1e10000}',
        b'{"value":"\\ud800"}',
    ],
)
def test_strict_json_rejects_ambiguous_and_nonfinite_payload(bundle: dict, raw: bytes) -> None:
    path = bundle["plan_manifest"].parent / "claims.jsonl"
    path.write_bytes(raw + b"\n")
    _reseal_plan(bundle["plan_manifest"])
    bundle["expected_plan_manifest_sha256"] = _digest(bundle["plan_manifest"])
    _reject(bundle)


def test_duplicate_manifest_key_rejected_even_with_pin(bundle: dict) -> None:
    path = bundle["plan_manifest"]
    payload = path.read_bytes().replace(b"{", b'{"schema_version":"evil",', 1)
    path.write_bytes(payload)
    bundle["expected_plan_manifest_sha256"] = _digest(path)
    _reject(bundle, "duplicate JSON key")


@pytest.mark.parametrize(
    "name", ["../papers.jsonl", "/papers.jsonl", "subdir/papers.jsonl", "papers\\file.jsonl"]
)
def test_source_manifest_cannot_redirect_leaf_reads(bundle: dict, name: str) -> None:
    path = bundle["source_manifest"]
    document = json.loads(path.read_bytes())
    document["files"]["papers"]["path"] = name
    _write_json(path, document)
    bundle["expected_source_manifest_sha256"] = _digest(path)
    _reject(bundle, "unsafe or duplicate source artifact path")


@pytest.mark.parametrize("change", ["extra_field", "nonfinite", "duplicate_key", "boolean_count"])
def test_resealed_source_payload_still_passes_strict_egress_checks(
    bundle: dict, change: str
) -> None:
    path = bundle["source_manifest"]
    leaf = path.parent / "materials.jsonl"
    raw = leaf.read_bytes()
    if change == "extra_field":
        row = json.loads(raw)
        row["unexported_summary"] = True
        leaf.write_bytes(exporter.canonical_json_bytes(row) + b"\n")
    elif change == "nonfinite":
        leaf.write_bytes(raw.replace(b"39.0", b"1e10000"))
    elif change == "duplicate_key":
        leaf.write_bytes(raw.replace(b"{", b'{"id":"duplicate",', 1))
    else:
        document = json.loads(path.read_bytes())
        document["files"]["license_manifest"]["rows"] = True
        _write_json(path, document)
    _reseal_source(path)
    bundle["expected_source_manifest_sha256"] = _digest(path)
    _reject(bundle)


@pytest.mark.parametrize(
    "name,field,value",
    [
        ("parity_report.json", "gate_status", "fail"),
        ("summary.json", "input_records", 0),
        ("summary.json", "parity_gate_failures", True),
    ],
)
def test_resealed_report_and_summary_are_not_self_verifying(
    bundle: dict, name: str, field: str, value: object
) -> None:
    path = bundle["plan_manifest"].parent / name
    payload = json.loads(path.read_bytes())
    payload[field] = value
    _write_json(path, payload)
    _reseal_plan(bundle["plan_manifest"])
    bundle["expected_plan_manifest_sha256"] = _digest(bundle["plan_manifest"])
    _reject(bundle, "mismatch")


def test_valid_bundle_without_existing_mapping_and_at_occurrence_limit(tmp_path: Path) -> None:
    source = _source(tmp_path.resolve() / "source", records=[{"tc_kelvin": 2.0}] * 1000)
    plan = _plan(source, tmp_path.resolve() / "plan")
    result = verifier.verify_shadow_import(
        source_manifest=source,
        plan_manifest=plan,
        expected_source_manifest_sha256=_digest(source),
        expected_plan_manifest_sha256=_digest(plan),
    )
    assert result["existing_paper_work"] == []
    assert result["summary"]["input_records"] == 1000
    assert result["summary"]["exact_duplicate_records"] == 999
    assert len(result["claims"]) == 1


def test_valid_replayed_plan_still_requires_independent_parity(bundle: dict, monkeypatch) -> None:
    original = verifier.build_shadow_parity_report

    def failing_parity(*args, **kwargs):
        report = original(*args, **kwargs)
        report["gate_status"] = "fail"
        report["gate_failures"] = [{"code": "synthetic_independent_failure", "count": 1}]
        return report

    monkeypatch.setattr(verifier, "build_shadow_parity_report", failing_parity)
    _reject(bundle, "independent parity gate failed")


def test_embedded_records_json_uses_strict_parser(tmp_path: Path) -> None:
    source = _source(tmp_path.resolve() / "source", records='[{"tc_kelvin":1,"tc_kelvin":2}]')
    plan = _plan(source, tmp_path.resolve() / "plan")
    _reject(
        {
            "source_manifest": source,
            "plan_manifest": plan,
            "expected_source_manifest_sha256": _digest(source),
            "expected_plan_manifest_sha256": _digest(plan),
        },
        "duplicate JSON key",
    )


@pytest.mark.parametrize(
    "limit",
    [
        "file_bytes",
        "jsonl_row_bytes",
        "combined_bytes",
        "json_depth",
        "json_nodes",
        "formula_chars",
        "occurrences",
        "materials",
        "papers",
    ],
)
def test_fixed_resource_caps_fail_closed(bundle: dict, monkeypatch, limit: str) -> None:
    monkeypatch.setitem(verifier.LIMITS, limit, 0)
    _reject(bundle)


def test_1001_duplicate_occurrences_are_not_silently_sampled(tmp_path: Path) -> None:
    records = [{"tc_kelvin": 2.0}] * 1001
    source = _source(tmp_path.resolve() / "source", records=records)
    plan = _plan(source, tmp_path.resolve() / "plan")
    _reject(
        {
            "source_manifest": source,
            "plan_manifest": plan,
            "expected_source_manifest_sha256": _digest(source),
            "expected_plan_manifest_sha256": _digest(plan),
        },
        "occurrence canary limit",
    )


def test_nonzero_failures_remain_in_denominator_and_reject(tmp_path: Path) -> None:
    source = _source(
        tmp_path.resolve() / "source", records=[{"paper_id": "missing", "tc_kelvin": 2.0}]
    )
    plan = _plan(source, tmp_path.resolve() / "plan")
    _reject(
        {
            "source_manifest": source,
            "plan_manifest": plan,
            "expected_source_manifest_sha256": _digest(source),
            "expected_plan_manifest_sha256": _digest(plan),
        },
        "failures must be zero",
    )


def test_mutation_during_replay_rejected(bundle: dict, monkeypatch) -> None:
    original = verifier.planner.build_backfill_plan

    def replay(*args, **kwargs):
        result = original(*args, **kwargs)
        path = bundle["source_manifest"].parent / "papers.jsonl"
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(verifier.planner, "build_backfill_plan", replay)
    _reject(bundle, "changed during verification")


def test_cli_summary_omits_records_and_no_database_modules_are_imported(bundle: dict) -> None:
    arguments = [
        item for key, value in bundle.items() for item in ("--" + key.replace("_", "-"), str(value))
    ]
    code = """import importlib.abc, sys
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sqlalchemy', 'asyncpg', 'psycopg2', 'httpx', 'requests', 'google'}:
            raise AssertionError('Forbidden import: ' + fullname)
sys.meta_path.insert(0, Deny())
sys.path.insert(0, sys.argv.pop(1))
from scripts.verify_shadow_import import main
raise SystemExit(main(sys.argv[1:]))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(REPO_ROOT), *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": os.defpath, "PYTHONNOUSERSITE": "1"},
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "claims" not in payload and "papers" not in payload
    assert "SOURCE_PRIVATE_TOKEN" not in result.stdout
    assert "MgB2" not in result.stdout
