"""PostgreSQL integration tests for the ML foundation source exporter."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import Json

from models.db import Chunk, Material, Paper, PaperWorkMap, Work

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_ml_foundation_snapshot.py"
_SPEC = importlib.util.spec_from_file_location("sclib_ml_source_exporter", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
EXPORTER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = EXPORTER
_SPEC.loader.exec_module(EXPORTER)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_canonical_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_bytes(b"".join(EXPORTER.canonical_json_bytes(row) + b"\n" for row in rows))


def _refresh_bundle_integrity(bundle: Path) -> None:
    """Simulate an attacker who can rewrite every hash and sidecar."""
    manifest_path = bundle / EXPORTER.MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"].values():
        artifact_path = bundle / entry["path"]
        entry["sha256"] = EXPORTER.file_sha256(artifact_path)
        entry["bytes"] = artifact_path.stat().st_size
    manifest["license_manifest_sha256"] = manifest["files"]["license_manifest"]["sha256"]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_hash = EXPORTER.file_sha256(manifest_path)
    checksums = {entry["path"]: entry["sha256"] for entry in manifest["files"].values()}
    checksums[EXPORTER.MANIFEST_FILE] = manifest_hash
    (bundle / EXPORTER.CHECKSUMS_FILE).write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())),
        encoding="utf-8",
    )
    (bundle / EXPORTER.MANIFEST_HASH_FILE).write_text(
        f"{manifest_hash}  {EXPORTER.MANIFEST_FILE}\n",
        encoding="utf-8",
    )


def test_canonical_json_and_error_redaction_are_deterministic() -> None:
    left = {"formula": "La₂CuO₄", "nested": {"b": 2, "a": 1}}
    right = {"nested": {"a": 1, "b": 2}, "formula": "La₂CuO₄"}
    assert EXPORTER.canonical_json_bytes(left) == EXPORTER.canonical_json_bytes(right)

    secret_url = "postgresql://sclib:super-secret@example.test:5432/sclib"
    message = EXPORTER.safe_error_message(
        RuntimeError(f"could not connect to {secret_url}; password=super-secret"),
        secret_url,
    )
    assert "super-secret" not in message
    assert secret_url not in message
    assert "redacted" in message

    license_manifest = EXPORTER.build_license_manifest(
        source_snapshot_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        dataset_version="v2026.08.20",
        database_watermark="2026-08-20T00:00:00+00:00",
        material_scope="all",
        paper_source_counts={"arxiv": 1},
        material_record_source_counts={"nims": 2},
    )
    assert license_manifest["contains_nims_records"] is True
    nims_terms = license_manifest["source_terms"]["nims"]
    assert "CC BY 4.0" in nims_terms
    assert "10.48505/nims.3735" in nims_terms
    assert "non-commercial" not in nims_terms.lower()
    assert "restricted" not in nims_terms.lower()


@pytest.mark.asyncio
async def test_export_uses_one_stable_read_only_snapshot_and_public_material_scope(
    db_session,
    tmp_path: Path,
) -> None:
    suffix = uuid.uuid4().hex
    paper_id = f"arxiv:export-{suffix}"
    late_paper_id = f"arxiv:export-late-{suffix}"
    public_material_id = f"mat:export-public-{suffix}"
    pending_material_id = f"mat:export-pending-{suffix}"
    quarantine_material_id = f"mat:export-quarantine-{suffix}"
    skeleton_material_id = f"mat:export-skeleton-{suffix}"
    work_id = uuid.uuid4()

    db_session.add(
        Paper(
            id=paper_id,
            source="arxiv",
            arxiv_id=f"2608.{suffix[:5]}",
            title="Exporter snapshot integration paper",
            authors=["Snapshot Tester"],
            abstract="Not exported.",
            status="published",
            paper_type="experimental",
            chunk_count=1,
        )
    )
    db_session.add(
        Work(
            id=work_id,
            canonical_title="Exporter snapshot integration paper",
            canonical_arxiv_id=f"2608.{suffix[:5]}",
            publication_status="active",
        )
    )
    db_session.add_all(
        [
            Material(
                id=public_material_id,
                formula="MgB2",
                formula_normalized="MgB2",
                total_papers=1,
                needs_review=False,
                records=[
                    {
                        "formula": "MgB2",
                        "paper_id": paper_id,
                        "tc_kelvin": 39.0,
                        "source": "arxiv_ner",
                    }
                ],
            ),
            Material(
                id=pending_material_id,
                formula="Pending2",
                formula_normalized="Pending2",
                total_papers=1,
                needs_review=True,
                records=[],
            ),
            Material(
                id=quarantine_material_id,
                formula="Nims2",
                formula_normalized="Nims2",
                total_papers=1,
                needs_review=False,
                review_reason="provenance_quarantine_nims",
                records=[{"formula": "Nims2", "source": "nims"}],
            ),
            Material(
                id=skeleton_material_id,
                formula="Skeleton2",
                formula_normalized="Skeleton2",
                total_papers=0,
                needs_review=False,
                records=[],
            ),
        ]
    )
    await db_session.flush()
    db_session.add(
        PaperWorkMap(
            paper_id=paper_id,
            work_id=work_id,
            relation_type="preprint",
            match_method="exact_arxiv",
            match_score=1.0,
            review_status="accepted",
        )
    )
    db_session.add(
        Chunk(
            id=f"chunk:export:{suffix}",
            paper_id=paper_id,
            title="Exporter snapshot integration paper",
            year=2026,
            section="Abstract",
            chunk_index=0,
            text="Authorized test chunk.",
            materials_mentioned=["MgB2"],
            has_equation=False,
            has_table=False,
        )
    )
    await db_session.commit()

    database_url = os.environ["DATABASE_URL"]
    hook_state = None

    def insert_after_snapshot(state) -> None:
        nonlocal hook_state
        hook_state = state
        assert state.transaction_isolation == "repeatable read"
        assert state.transaction_read_only == "on"
        with psycopg2.connect(EXPORTER._to_sync_dsn(database_url)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO papers (
                        id, source, title, authors, abstract, status,
                        citation_count, chunk_count, materials_extracted, quality_flags
                    ) VALUES (%s, 'arxiv', %s, %s, %s, 'published', 0, 0, '[]', '[]')
                    """,
                    (
                        late_paper_id,
                        "Inserted after the exporter snapshot",
                        Json(["Concurrent Writer"]),
                        "Must not appear in the active snapshot.",
                    ),
                )

    bundle = tmp_path / "source-bundle"
    snapshot_id = uuid.uuid4()
    manifest = EXPORTER.export_snapshot(
        database_url=database_url,
        output_dir=bundle,
        dataset_version="v2026.08.20-test",
        site_git_sha="a" * 40,
        source_snapshot_id=snapshot_id,
        batch_size=1,
        snapshot_hook=insert_after_snapshot,
    )

    assert hook_state is not None
    assert manifest["schema_version"] == "sclib-source-export/v1"
    assert manifest["source_snapshot_id"] == str(snapshot_id)
    assert manifest["database"]["transaction_isolation"] == "repeatable read"
    assert manifest["database"]["transaction_read_only"] == "on"
    assert manifest["alembic_revision"]
    assert manifest["chunk_count"] == manifest["counts"]["chunks"]
    assert manifest["files"]["materials"]["path"] == "materials.jsonl"
    assert manifest["files"]["papers"]["path"] == "papers.jsonl"
    assert manifest["files"]["paper_work_map"]["path"] == "paper_work_map.jsonl"
    assert manifest["license_manifest_sha256"] == manifest["files"]["license_manifest"]["sha256"]

    verified = EXPORTER.verify_export_bundle(bundle)
    assert verified == manifest
    material_ids = {row["id"] for row in _read_jsonl(bundle / "materials.jsonl")}
    assert public_material_id in material_ids
    assert pending_material_id not in material_ids
    assert quarantine_material_id not in material_ids
    assert skeleton_material_id not in material_ids

    paper_ids = {row["id"] for row in _read_jsonl(bundle / "papers.jsonl")}
    assert paper_id in paper_ids
    assert late_paper_id not in paper_ids
    mappings = {row["paper_id"]: row for row in _read_jsonl(bundle / "paper_work_map.jsonl")}
    assert mappings[paper_id]["review_status"] == "accepted"
    assert mappings[paper_id]["work_id"] == str(work_id)

    license_manifest = json.loads((bundle / "license_manifest.json").read_text())
    assert license_manifest["distribution_status"] == "not_cleared_for_public_release"
    assert license_manifest["content_policy"]["chunk_payloads_exported"] is False
    assert (bundle / "checksums.sha256").is_file()
    assert (bundle / "export_manifest.sha256").is_file()

    # Any byte-level change invalidates the bundle.
    with (bundle / "materials.jsonl").open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(EXPORTER.VerificationError, match="checksum mismatch"):
        EXPORTER.verify_export_bundle(bundle)


@pytest.mark.asyncio
async def test_optional_map_and_failed_export_never_publish_partial_directory(
    db_session,
    tmp_path: Path,
) -> None:
    null_paper_id = f"other:null-export-fields-{uuid.uuid4().hex}"
    db_session.add(
        Paper(
            id=null_paper_id,
            source="other",
            title="Paper with legitimate nullable export fields",
            authors=[],
            abstract="Not exported.",
            status="published",
            paper_type=None,
        )
    )
    # Commit so the synchronous exporter can acquire its independent read-only
    # snapshot without inheriting pending work.
    await db_session.commit()
    database_url = os.environ["DATABASE_URL"]
    no_map_bundle = tmp_path / "without-map"
    manifest = EXPORTER.export_snapshot(
        database_url=database_url,
        output_dir=no_map_bundle,
        dataset_version="v2026.08.20-no-map",
        site_git_sha="b" * 40,
        include_paper_work_map=False,
        batch_size=7,
    )
    assert "paper_work_map" not in manifest["files"]
    assert not (no_map_bundle / "paper_work_map.jsonl").exists()
    assert manifest["metadata"]["paper_work_map_included"] is False
    EXPORTER.verify_export_bundle(no_map_bundle)

    null_paper = next(
        row for row in _read_jsonl(no_map_bundle / "papers.jsonl") if row["id"] == null_paper_id
    )
    assert set(null_paper) == set(EXPORTER._JSONL_EXPORT_FIELDS["papers"])
    for nullable_field in (
        "arxiv_id",
        "doi",
        "related_paper_id",
        "date_submitted",
        "date_published",
        "paper_type",
    ):
        assert null_paper[nullable_field] is None

    # Hashes are an integrity mechanism, not an egress allowlist. Even if an
    # attacker rewrites every checksum, extra sensitive fields must be denied.
    sensitive_payloads = {
        "abstract": "full abstract must not leave the source database",
        "authors": ["Sensitive Author"],
        "chunk": {"text": "chunk payload"},
        "chunks": [{"text": "chunk payload"}],
        "text": "raw chunk text",
    }
    for field, payload in sensitive_payloads.items():
        attack_bundle = tmp_path / f"attack-{field}"
        shutil.copytree(no_map_bundle, attack_bundle)
        paper_path = attack_bundle / "papers.jsonl"
        paper_rows = _read_jsonl(paper_path)
        next(row for row in paper_rows if row["id"] == null_paper_id)[field] = payload
        _write_canonical_jsonl(paper_path, paper_rows)
        _refresh_bundle_integrity(attack_bundle)
        with pytest.raises(
            EXPORTER.VerificationError,
            match=rf"unknown fields: {field}",
        ):
            EXPORTER.verify_export_bundle(attack_bundle)

    missing_bundle = tmp_path / "attack-missing-required-field"
    shutil.copytree(no_map_bundle, missing_bundle)
    missing_paper_path = missing_bundle / "papers.jsonl"
    missing_rows = _read_jsonl(missing_paper_path)
    del next(row for row in missing_rows if row["id"] == null_paper_id)["paper_type"]
    _write_canonical_jsonl(missing_paper_path, missing_rows)
    _refresh_bundle_integrity(missing_bundle)
    with pytest.raises(
        EXPORTER.VerificationError,
        match=r"missing fields: paper_type",
    ):
        EXPORTER.verify_export_bundle(missing_bundle)

    bundle_link = tmp_path / "bundle-link"
    bundle_link.symlink_to(no_map_bundle, target_is_directory=True)
    with pytest.raises(EXPORTER.VerificationError, match="must not be a symlink"):
        EXPORTER.verify_export_bundle(bundle_link)

    # The verifier is also a data-egress boundary: untracked payloads such as
    # chunk text must make the bundle invalid even when every declared file is
    # still intact.
    unexpected_chunks = no_map_bundle / "chunks.jsonl"
    unexpected_chunks.write_text('{"text":"must not be exported"}\n')
    with pytest.raises(EXPORTER.VerificationError, match="file inventory mismatch"):
        EXPORTER.verify_export_bundle(no_map_bundle)
    unexpected_chunks.unlink()

    license_path = no_map_bundle / "license_manifest.json"
    license_manifest = json.loads(license_path.read_text())
    license_manifest["content_policy"]["chunk_payloads_exported"] = True
    license_path.write_text(json.dumps(license_manifest, indent=2, sort_keys=True) + "\n")
    _refresh_bundle_integrity(no_map_bundle)
    with pytest.raises(EXPORTER.VerificationError, match="chunk_payloads_exported=false"):
        EXPORTER.verify_export_bundle(no_map_bundle)

    failed_bundle = tmp_path / "must-not-exist"

    def fail_after_snapshot(_state) -> None:
        raise RuntimeError("intentional integration-test failure")

    with pytest.raises(RuntimeError, match="intentional"):
        EXPORTER.export_snapshot(
            database_url=database_url,
            output_dir=failed_bundle,
            dataset_version="v2026.08.20-failure",
            site_git_sha="c" * 40,
            snapshot_hook=fail_after_snapshot,
        )
    assert not failed_bundle.exists()
    assert not list(tmp_path.glob(".must-not-exist.partial-*"))
