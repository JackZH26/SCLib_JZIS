"""Integration contracts for the offline ML Foundation backfill planner."""

from __future__ import annotations

import hashlib
import json
import stat
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts import export_ml_foundation_snapshot as source_exporter
from scripts import plan_typed_claim_backfill as planner
from scripts.plan_typed_claim_backfill import (
    build_backfill_plan,
    load_source_export_manifest,
    main,
    write_jsonl,
    write_plan_artifacts,
)


def _sample_rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    papers = [
        {
            "id": "arxiv:2306.07275",
            "source": "arxiv",
            "arxiv_id": "2306.07275",
            "doi": None,
            "related_paper_id": None,
            "title": "A test work",
            "date_submitted": "2023-06-12",
            "date_published": None,
            "status": "published",
            "paper_type": "preprint",
        }
    ]
    materials = [
        {
            "id": "mat:mgb2",
            "formula": "MgB2",
            "formula_normalized": "MgB2",
            "records": [
                {
                    "paper_id": "arxiv:2306.07275",
                    "tc_kelvin": 39.0,
                    "measurement": "resistivity",
                }
            ],
        }
    ]
    return materials, papers


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_temporal_dry_run_distinguishes_changed_and_unverifiable_without_backdating():
    materials, papers = _sample_rows()
    materials[0]["records"].append({"tc_kelvin": 12})
    materials[0]["records"].append({"paper_id": papers[0]["id"], "tc_kelvin": 20,
                                     "available_at": "2020-01-02"})
    original = json.dumps([materials, papers], sort_keys=True)
    snapshot_id = uuid.UUID("de419872-4383-4227-b16d-67cebd598cb3")
    plan = build_backfill_plan(materials, papers, source_snapshot_id=snapshot_id)
    assert plan == build_backfill_plan(materials, papers, source_snapshot_id=snapshot_id)
    assert json.dumps([materials, papers], sort_keys=True) == original
    audit = plan["summary"]["temporal_projection_audit"]
    assert audit["changed_projection_claims"] == 2
    assert audit["unchanged_projection_claims"] == 1
    assert audit["unverifiable_source_version_claims"] == 3
    assert audit["database_mutated"] is False
    assert all(row["available_at"] is None for row in plan["claims"])
    per_claim = audit["claims"]
    assert {row["legacy_mapper_available_at_hint"] for row in per_claim} == {None, "2020-01-02", "2023-06-12"}
    assert all(row["source_version_verifiable"] is False for row in per_claim)


def _source_export(tmp_path: Path) -> Path:
    export_dir = tmp_path / "source-export"
    export_dir.mkdir()
    materials, papers = _sample_rows()
    materials_path = export_dir / "materials.jsonl"
    papers_path = export_dir / "papers.jsonl"
    license_path = export_dir / "license_manifest.json"
    materials_path.write_bytes(source_exporter.canonical_json_bytes(materials[0]) + b"\n")
    papers_path.write_bytes(source_exporter.canonical_json_bytes(papers[0]) + b"\n")
    snapshot_id = uuid.uuid4()
    database_watermark = "2026-08-20T00:00:00+00:00"
    license_manifest = {
        "schema_version": "sclib-license-manifest/v1",
        "source_snapshot_id": str(snapshot_id),
        "dataset_version": "v-test",
        "database_watermark": database_watermark,
        "material_scope": "public",
        "distribution_status": "not_cleared_for_public_release",
        "content_policy": {
            "paper_abstracts_exported": False,
            "paper_authors_exported": False,
            "chunk_payloads_exported": False,
            "vector_index_frozen": False,
            "legacy_material_records_exported": True,
        },
    }
    license_path.write_text(json.dumps(license_manifest, indent=2, sort_keys=True) + "\n")
    file_entries = {
        "materials": {
            "path": materials_path.name,
            "sha256": _sha256(materials_path),
            "rows": 1,
            "bytes": materials_path.stat().st_size,
        },
        "papers": {
            "path": papers_path.name,
            "sha256": _sha256(papers_path),
            "rows": 1,
            "bytes": papers_path.stat().st_size,
        },
        "license_manifest": {
            "path": license_path.name,
            "sha256": _sha256(license_path),
            "rows": 1,
            "bytes": license_path.stat().st_size,
        },
    }
    manifest = {
        "schema_version": "sclib-source-export/v1",
        "exporter_version": "sclib-ml-source-exporter/v1",
        "source_snapshot_id": str(snapshot_id),
        "dataset_version": "v-test",
        "site_git_sha": "a" * 40,
        "database_watermark": database_watermark,
        "alembic_revision": "0044_ml_foundation",
        "chunk_count": 3,
        "license_manifest_sha256": _sha256(license_path),
        "material_scope": "public",
        "counts": {
            "materials": 1,
            "papers": 1,
            "chunks": 3,
            "paper_work_map": 0,
            "material_records": 1,
        },
        "files": file_entries,
        "queries": {"materials": "b" * 64, "papers": "c" * 64},
        "database": {
            "name": "sclib_test",
            "postgres_version": "16",
            "transaction_isolation": "repeatable read",
            "transaction_read_only": "on",
            "transaction_snapshot": "1:1:",
            "wal_lsn": None,
        },
        "metadata": {
            "max_material_updated_at": database_watermark,
            "max_paper_updated_at": database_watermark,
            "paper_source_counts": {"arxiv": 1},
            "material_record_source_counts": {"arxiv_ner": 1},
            "paper_work_map_table_present": False,
            "paper_work_map_included": False,
            "chunk_inventory_exported": False,
            "vector_index_frozen": False,
        },
    }
    manifest_path = export_dir / "export_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (export_dir / "export_manifest.sha256").write_text(
        f"{_sha256(manifest_path)}  export_manifest.json\n"
    )
    checksums = {entry["path"]: entry["sha256"] for entry in file_entries.values()}
    checksums["export_manifest.json"] = _sha256(manifest_path)
    (export_dir / "checksums.sha256").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items()))
    )
    source_exporter.verify_export_bundle(export_dir)
    return manifest_path


def test_plan_binds_every_claim_to_snapshot_and_emits_db_shaped_composition() -> None:
    materials, papers = _sample_rows()
    snapshot_id = uuid.uuid4()

    plan = build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=snapshot_id,
    )

    assert plan["failures"] == []
    assert plan["claims"][0]["source_snapshot_id"] == snapshot_id
    assert set(plan["compositions"][0]) == {
        "material_id",
        "composition_status",
        "composition_data",
    }
    assert plan["compositions"][0]["material_id"] == "mat:mgb2"
    assert plan["compositions"][0]["composition_status"] == "exact"
    assert plan["compositions"][0]["composition_data"]["formula_reduced"] == "MgB2"
    assert "composition_status" not in plan["compositions"][0]["composition_data"]


def test_plan_reports_unknown_papers_duplicate_materials_and_non_array_records() -> None:
    snapshot_id = uuid.uuid4()
    plan = build_backfill_plan(
        [
            {"id": "mat:bad-records", "formula": "Nb", "records": {}},
            {"id": "mat:bad-records", "formula": "Nb", "records": []},
            {
                "id": "mat:unknown-paper",
                "formula": "Pb",
                "records": [{"paper_id": "arxiv:missing", "tc_kelvin": 7.2}],
            },
        ],
        [],
        source_snapshot_id=snapshot_id,
    )

    assert {row["code"] for row in plan["failures"]} == {
        "records_not_array",
        "duplicate_material_id",
        "unknown_paper_id",
    }
    assert plan["claims"] == []


def test_plan_clears_unverified_chunk_fk_but_preserves_locator() -> None:
    materials, papers = _sample_rows()
    materials[0]["records"][0]["chunk_id"] = "arxiv:2306.07275_chunk_9"

    plan = build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=uuid.uuid4(),
    )

    claim = plan["claims"][0]
    assert claim["chunk_id"] is None
    assert claim["source_locator"]["chunk_id"] == "arxiv:2306.07275_chunk_9"
    assert [warning["code"] for warning in plan["warnings"]] == ["unverified_chunk_fk_cleared"]


def test_plan_does_not_abort_on_unrepresentable_legacy_number() -> None:
    materials, papers = _sample_rows()
    materials[0]["records"][0]["tc_kelvin"] = 10**400

    plan = build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=uuid.uuid4(),
    )

    assert plan["failures"] == []
    assert plan["claims"][0]["value_relation"] == "unreported"
    assert plan["claims"][0]["raw_record"]["tc_kelvin"] == 10**400


def test_plan_uses_only_accepted_existing_work_mappings_as_identity_edges() -> None:
    work_id = uuid.uuid4()
    papers = [
        {"id": "legacy:one", "title": "First"},
        {"id": "legacy:two", "title": "Second"},
    ]
    existing = [
        {
            "paper_id": paper["id"],
            "work_id": str(work_id),
            "review_status": "accepted",
            "match_method": "manual",
            "relation_type": "canonical_version",
        }
        for paper in papers
    ]

    plan = build_backfill_plan(
        [],
        papers,
        source_snapshot_id=uuid.uuid4(),
        existing_paper_work=existing,
    )

    assert len(plan["works"]) == 1
    assert plan["works"][0]["id"] == work_id
    assert {row["work_id"] for row in plan["paper_work_map"]} == {work_id}
    assert {row["review_status"] for row in plan["paper_work_map"]} == {"accepted"}
    assert plan["summary"]["accepted_existing_paper_work_rows"] == 2


@pytest.mark.parametrize("review_status", ["pending", "rejected"])
def test_plan_never_promotes_nonaccepted_existing_work_mapping(review_status: str) -> None:
    old_work_id = uuid.uuid4()
    papers = [
        {"id": "legacy:one", "title": "First"},
        {"id": "legacy:two", "title": "Second"},
    ]
    existing = [
        {
            "paper_id": paper["id"],
            "work_id": str(old_work_id),
            "review_status": review_status,
            "match_method": "manual",
            "relation_type": "canonical_version",
        }
        for paper in papers
    ]

    plan = build_backfill_plan(
        [],
        papers,
        source_snapshot_id=uuid.uuid4(),
        existing_paper_work=existing,
    )

    assert len(plan["works"]) == 2
    assert old_work_id not in {row["id"] for row in plan["works"]}
    assert {row["review_status"] for row in plan["paper_work_map"]} == {"accepted"}
    assert {row["match_method"] for row in plan["paper_work_map"]} == {"singleton"}
    assert {row["relation_type"] for row in plan["paper_work_map"]} == {"canonical_version"}
    assert plan["summary"]["accepted_existing_paper_work_rows"] == 0
    assert [warning["code"] for warning in plan["warnings"]] == [
        "nonaccepted_existing_mapping_not_authoritative",
        "nonaccepted_existing_mapping_not_authoritative",
    ]
    assert {warning["old_work_id"] for warning in plan["warnings"]} == {str(old_work_id)}
    assert {warning["old_review_status"] for warning in plan["warnings"]} == {review_status}
    assert {warning["proposed_work_id"] for warning in plan["warnings"]} == {
        str(row["work_id"]) for row in plan["paper_work_map"]
    }


def test_existing_work_export_requires_review_status() -> None:
    with pytest.raises(ValueError, match="review_status"):
        build_backfill_plan(
            [],
            [{"id": "legacy:one", "title": "First"}],
            source_snapshot_id=uuid.uuid4(),
            existing_paper_work=[{"paper_id": "legacy:one", "work_id": str(uuid.uuid4())}],
        )


def test_plan_bundle_has_reproducible_manifest_and_snapshot_payload(tmp_path: Path) -> None:
    materials, papers = _sample_rows()
    materials_path = tmp_path / "materials.jsonl"
    papers_path = tmp_path / "papers.jsonl"
    write_jsonl(materials_path, materials)
    write_jsonl(papers_path, papers)
    snapshot_id = uuid.uuid4()
    plan = build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=snapshot_id,
    )

    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    kwargs = {
        "materials_path": materials_path,
        "papers_path": papers_path,
        "existing_map_path": None,
        "dataset_version": "v-test",
        "site_git_sha": "a" * 40,
        "database_watermark": "2026-08-20T00:00:00Z",
        "chunk_count": 3,
        "license_manifest_sha256": "b" * 64,
    }
    first_hash = write_plan_artifacts(plan, output_dir=first_dir, **kwargs)
    second_hash = write_plan_artifacts(plan, output_dir=second_dir, **kwargs)

    assert first_hash == second_hash
    assert (first_dir / "manifest.sha256").read_text().startswith(first_hash)
    snapshot = json.loads((first_dir / "source_snapshots.jsonl").read_text())
    assert snapshot["id"] == str(snapshot_id)
    assert snapshot["manifest_sha256"] == first_hash
    assert snapshot["status"] == "building"
    parity = json.loads((first_dir / "parity_report.json").read_text())
    manifest = json.loads((first_dir / "manifest.json").read_text())
    assert parity["gate_status"] == "pass"
    assert manifest["summary"]["parity_gate_status"] == "pass"
    assert manifest["outputs"]["parity_report.json"]["sha256"] == _sha256(
        first_dir / "parity_report.json"
    )
    assert snapshot["metadata"]["parity_report_sha256"] == _sha256(first_dir / "parity_report.json")
    assert stat.S_IMODE(first_dir.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600 for path in first_dir.iterdir() if path.is_file()
    )

    third_dir = tmp_path / "different-license"
    changed_license_hash = write_plan_artifacts(
        plan,
        output_dir=third_dir,
        **{**kwargs, "license_manifest_sha256": "c" * 64},
    )
    assert changed_license_hash != first_hash


def test_source_export_manifest_is_the_capture_identity_and_is_rehashed(
    tmp_path: Path,
) -> None:
    source_manifest_path = _source_export(tmp_path)
    source = load_source_export_manifest(source_manifest_path)
    materials = json.loads(source["materials_path"].read_text())
    papers = json.loads(source["papers_path"].read_text())
    plan = build_backfill_plan(
        [materials],
        [papers],
        source_snapshot_id=source["source_snapshot_id"],
    )

    output_dir = tmp_path / "plan"
    plan_hash = write_plan_artifacts(
        plan,
        output_dir=output_dir,
        materials_path=source["materials_path"],
        papers_path=source["papers_path"],
        existing_map_path=None,
        dataset_version=source["dataset_version"],
        site_git_sha=source["site_git_sha"],
        database_watermark=source["database_watermark"],
        chunk_count=source["chunk_count"],
        license_manifest_sha256=source["license_manifest_sha256"],
        source_export_manifest_path=source["manifest_path"],
        source_export_manifest_sha256=source["manifest_sha256"],
        source_alembic_revision=source["alembic_revision"],
    )

    plan_manifest = json.loads((output_dir / "manifest.json").read_text())
    snapshot = json.loads((output_dir / "source_snapshots.jsonl").read_text())
    assert plan_manifest["source_export_manifest_sha256"] == source["manifest_sha256"]
    assert plan_manifest["source_alembic_revision"] == "0044_ml_foundation"
    assert plan_manifest["inputs"]["source_export_manifest"]["sha256"] == source["manifest_sha256"]
    assert snapshot["manifest_sha256"] == plan_hash
    assert snapshot["status"] == "building"
    assert snapshot["metadata"]["source_export_manifest_sha256"] == source["manifest_sha256"]


@pytest.mark.parametrize(
    ("field", "forged_value", "message"),
    [
        (
            "source_snapshot_id",
            "22222222-2222-4222-8222-222222222222",
            "source_snapshot_id",
        ),
        ("dataset_version", "v-forged", "dataset_version"),
        ("site_git_sha", "d" * 40, "site_git_sha"),
        (
            "database_watermark",
            "2026-08-21T00:00:00+00:00",
            "database_watermark",
        ),
        ("chunk_count", 4, "chunk_count"),
        ("source_alembic_revision", "0045_forged", "alembic_revision"),
    ],
)
def test_plan_writer_binds_every_source_capture_scalar(
    tmp_path: Path,
    field: str,
    forged_value: object,
    message: str,
) -> None:
    source = load_source_export_manifest(_source_export(tmp_path))
    materials = [json.loads(source["materials_path"].read_text())]
    papers = [json.loads(source["papers_path"].read_text())]
    plan = build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=source["source_snapshot_id"],
    )
    kwargs: dict[str, object] = {
        "output_dir": tmp_path / f"forged-{field}",
        "materials_path": source["materials_path"],
        "papers_path": source["papers_path"],
        "existing_map_path": None,
        "dataset_version": source["dataset_version"],
        "site_git_sha": source["site_git_sha"],
        "database_watermark": source["database_watermark"],
        "chunk_count": source["chunk_count"],
        "license_manifest_sha256": source["license_manifest_sha256"],
        "source_export_manifest_path": source["manifest_path"],
        "source_export_manifest_sha256": source["manifest_sha256"],
        "source_alembic_revision": source["alembic_revision"],
    }
    if field == "source_snapshot_id":
        plan["summary"]["source_snapshot_id"] = forged_value
    else:
        kwargs[field] = forged_value

    with pytest.raises(ValueError, match=message):
        write_plan_artifacts(plan, **kwargs)

    assert not kwargs["output_dir"].exists()
    assert not list(tmp_path.glob(f".forged-{field}.partial-*"))


def test_plan_writer_rechecks_capture_scalars_at_final_sealing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_manifest_path = _source_export(tmp_path)
    source = load_source_export_manifest(source_manifest_path)
    materials = [json.loads(source["materials_path"].read_text())]
    papers = [json.loads(source["papers_path"].read_text())]
    plan = build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=source["source_snapshot_id"],
    )
    real_loader = planner.load_source_export_manifest
    calls = 0

    def changing_loader(path: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        verified = real_loader(path)
        if calls == 2:
            verified = {**verified, "chunk_count": verified["chunk_count"] + 1}
        return verified

    monkeypatch.setattr(planner, "load_source_export_manifest", changing_loader)
    output_dir = tmp_path / "final-scalar-mismatch"

    with pytest.raises(ValueError, match="chunk_count.*final sealing"):
        write_plan_artifacts(
            plan,
            output_dir=output_dir,
            materials_path=source["materials_path"],
            papers_path=source["papers_path"],
            existing_map_path=None,
            dataset_version=source["dataset_version"],
            site_git_sha=source["site_git_sha"],
            database_watermark=source["database_watermark"],
            chunk_count=source["chunk_count"],
            license_manifest_sha256=source["license_manifest_sha256"],
            source_export_manifest_path=source["manifest_path"],
            source_export_manifest_sha256=source["manifest_sha256"],
            source_alembic_revision=source["alembic_revision"],
        )

    assert calls == 2
    assert not output_dir.exists()
    assert not list(tmp_path.glob(".final-scalar-mismatch.partial-*"))


def test_source_export_manifest_rejects_tampered_leaf_file(tmp_path: Path) -> None:
    source_manifest_path = _source_export(tmp_path)
    materials_path = source_manifest_path.parent / "materials.jsonl"
    materials_path.write_text(materials_path.read_text() + "{}\n")

    with pytest.raises(ValueError, match="checksum mismatch for materials"):
        load_source_export_manifest(source_manifest_path)


def test_plan_writer_reverifies_source_bundle_after_initial_load(tmp_path: Path) -> None:
    source_manifest_path = _source_export(tmp_path)
    source = load_source_export_manifest(source_manifest_path)
    materials = json.loads(source["materials_path"].read_text())
    papers = json.loads(source["papers_path"].read_text())
    plan = build_backfill_plan(
        [materials],
        [papers],
        source_snapshot_id=source["source_snapshot_id"],
    )
    source["materials_path"].write_text(source["materials_path"].read_text() + "{}\n")
    output_dir = tmp_path / "must-not-exist"

    with pytest.raises(ValueError, match="checksum mismatch for materials"):
        write_plan_artifacts(
            plan,
            output_dir=output_dir,
            materials_path=source["materials_path"],
            papers_path=source["papers_path"],
            existing_map_path=None,
            dataset_version=source["dataset_version"],
            site_git_sha=source["site_git_sha"],
            database_watermark=source["database_watermark"],
            chunk_count=source["chunk_count"],
            license_manifest_sha256=source["license_manifest_sha256"],
            source_export_manifest_path=source["manifest_path"],
            source_export_manifest_sha256=source["manifest_sha256"],
            source_alembic_revision=source["alembic_revision"],
        )

    assert not output_dir.exists()
    assert not list(tmp_path.glob(".must-not-exist.partial-*"))


def test_plan_writer_never_overwrites_an_existing_bundle(tmp_path: Path) -> None:
    materials, papers = _sample_rows()
    materials_path = tmp_path / "materials.jsonl"
    papers_path = tmp_path / "papers.jsonl"
    write_jsonl(materials_path, materials)
    write_jsonl(papers_path, papers)
    output_dir = tmp_path / "existing-plan"
    output_dir.mkdir()
    sentinel = output_dir / "keep.txt"
    sentinel.write_text("do not overwrite")
    plan = build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=uuid.uuid4(),
    )

    with pytest.raises(FileExistsError, match="already exists"):
        write_plan_artifacts(
            plan,
            output_dir=output_dir,
            materials_path=materials_path,
            papers_path=papers_path,
            existing_map_path=None,
            dataset_version="v-test",
            site_git_sha="a" * 40,
            database_watermark="2026-08-20T00:00:00Z",
            chunk_count=3,
            license_manifest_sha256="b" * 64,
        )

    assert sentinel.read_text() == "do not overwrite"
    assert set(output_dir.iterdir()) == {sentinel}


def test_plan_writer_rejects_a_symlink_output_path(tmp_path: Path) -> None:
    materials, papers = _sample_rows()
    materials_path = tmp_path / "materials.jsonl"
    papers_path = tmp_path / "papers.jsonl"
    write_jsonl(materials_path, materials)
    write_jsonl(papers_path, papers)
    output_link = tmp_path / "plan-link"
    output_link.symlink_to(tmp_path / "outside-target", target_is_directory=True)
    plan = build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=uuid.uuid4(),
    )

    with pytest.raises(ValueError, match="must not be a symlink"):
        write_plan_artifacts(
            plan,
            output_dir=output_link,
            materials_path=materials_path,
            papers_path=papers_path,
            existing_map_path=None,
            dataset_version="v-test",
            site_git_sha="a" * 40,
            database_watermark="2026-08-20T00:00:00Z",
            chunk_count=3,
            license_manifest_sha256="b" * 64,
        )

    assert not (tmp_path / "outside-target").exists()


def test_source_export_manifest_rejects_path_escape(tmp_path: Path) -> None:
    source_manifest_path = _source_export(tmp_path)
    manifest = json.loads(source_manifest_path.read_text())
    manifest["files"]["materials"]["path"] = "../outside.jsonl"
    source_manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    source_manifest_path.with_suffix(".sha256").write_text(
        f"{_sha256(source_manifest_path)}  export_manifest.json\n"
    )

    with pytest.raises(ValueError, match="plain relative filename"):
        load_source_export_manifest(source_manifest_path)


def test_source_export_manifest_mode_rejects_manual_capture_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_manifest_path = _source_export(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "plan_typed_claim_backfill.py",
            "--source-export-manifest",
            str(source_manifest_path),
            "--chunk-count",
            "3",
        ],
    )

    with pytest.raises(SystemExit, match="2"):
        main()


def test_plan_bundle_rejects_input_output_overlap_before_writing(tmp_path: Path) -> None:
    materials, papers = _sample_rows()
    materials_path = tmp_path / "claims.jsonl"
    papers_path = tmp_path / "papers-input.jsonl"
    existing_map_path = tmp_path / "paper_work_map.jsonl"
    write_jsonl(materials_path, materials)
    write_jsonl(papers_path, papers)
    write_jsonl(existing_map_path, [])
    original_inputs = {
        path: path.read_bytes() for path in (materials_path, papers_path, existing_map_path)
    }
    plan = build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=uuid.uuid4(),
    )

    with pytest.raises(ValueError, match="input path overlaps planned output"):
        write_plan_artifacts(
            plan,
            output_dir=tmp_path,
            materials_path=materials_path,
            papers_path=papers_path,
            existing_map_path=existing_map_path,
            dataset_version="v-test",
            site_git_sha="a" * 40,
            database_watermark="2026-08-20T00:00:00Z",
            chunk_count=3,
            license_manifest_sha256="b" * 64,
        )

    assert all(path.read_bytes() == content for path, content in original_inputs.items())
    assert not (tmp_path / "works.jsonl").exists()
    assert not (tmp_path / "summary.json").exists()
    assert not (tmp_path / "manifest.json").exists()
    assert not (tmp_path / "source_snapshots.jsonl").exists()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"dataset_version": ""}, "dataset_version"),
        ({"dataset_version": "x" * 51}, "dataset_version"),
        ({"site_git_sha": "not-a-sha"}, "site_git_sha"),
        ({"database_watermark": "2026-08-20T00:00:00"}, "timezone"),
        ({"database_watermark": "not-a-time"}, "ISO-8601"),
        ({"chunk_count": -1}, "chunk_count"),
    ],
)
def test_plan_bundle_rejects_payloads_that_source_snapshot_cannot_store(
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    materials, papers = _sample_rows()
    materials_path = tmp_path / "materials.jsonl"
    papers_path = tmp_path / "papers.jsonl"
    write_jsonl(materials_path, materials)
    write_jsonl(papers_path, papers)
    plan = build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=uuid.uuid4(),
    )
    kwargs: dict[str, object] = {
        "output_dir": tmp_path / "out",
        "materials_path": materials_path,
        "papers_path": papers_path,
        "existing_map_path": None,
        "dataset_version": "v-test",
        "site_git_sha": "a" * 40,
        "database_watermark": "2026-08-20T00:00:00Z",
        "chunk_count": 3,
        "license_manifest_sha256": "b" * 64,
    }
    kwargs.update(overrides)

    with pytest.raises(ValueError, match=message):
        write_plan_artifacts(plan, **kwargs)

    assert not (tmp_path / "out").exists()
