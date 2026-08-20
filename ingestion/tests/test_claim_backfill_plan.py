"""Integration contracts for the offline ML Foundation backfill planner."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.plan_typed_claim_backfill import (
    build_backfill_plan,
    write_jsonl,
    write_plan_artifacts,
)


def _sample_rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    papers = [
        {
            "id": "arxiv:2306.07275",
            "source": "arxiv",
            "arxiv_id": "2306.07275",
            "title": "A test work",
            "date_submitted": "2023-06-12",
        }
    ]
    materials = [
        {
            "id": "mat:mgb2",
            "formula": "MgB2",
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
    assert snapshot["status"] == "validated"

    third_dir = tmp_path / "different-license"
    changed_license_hash = write_plan_artifacts(
        plan,
        output_dir=third_dir,
        **{**kwargs, "license_manifest_sha256": "c" * 64},
    )
    assert changed_license_hash != first_hash


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
