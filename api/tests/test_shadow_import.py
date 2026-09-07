"""Independent ML03 loader integration on guarded disposable PostgreSQL.

Baseline inputs really pass the offline source-export/plan verifier. Deliberate
in-memory revisions below simulate separately reviewed future mapper outputs;
none of these synthetic processing artifacts is scientific or public approval.
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

from models.db import Base, get_session_factory
from models.research_import_v1 import TABLE_ORDER
from services import shadow_import as loader

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ingestion"))

from scripts import export_ml_foundation_snapshot as exporter  # noqa: E402
from scripts import plan_typed_claim_backfill as planner  # noqa: E402
from scripts import verify_shadow_import as verifier  # noqa: E402

LEGACY_TABLES = (
    "materials", "papers", "works", "paper_work_map", "material_claims", "source_snapshots",
    "research_events", "material_states", "event_properties", "snapshot_event_memberships",
    "ml_dataset_snapshots", "ml_examples", "source_revisions", "source_captures", "claim_source_occurrences",
)


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        await session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        yield session


async def add(db, name, **values):
    return (await db.execute(Base.metadata.tables[name].insert().values(**values).returning(
        Base.metadata.tables[name],
    ))).mappings().one()


async def table_state(db, names=None):
    result = {}
    for name in names or LEGACY_TABLES:
        rows = (await db.execute(sa.select(Base.metadata.tables[name]))).mappings().all()
        result[name] = sorted((dict(row) for row in rows), key=lambda row: json.dumps(row, sort_keys=True, default=str))
    return result


async def counts(db):
    return {name: (await db.execute(sa.select(sa.func.count()).select_from(Base.metadata.tables[name]))).scalar_one()
            for name in TABLE_ORDER}


def _normalized(value):
    return json.loads(json.dumps(value, default=planner._json_default, ensure_ascii=False))


def reseal(verified):
    """Deliberate reviewed-adapter mutation for negative or future-policy tests."""
    verified.pop("payload_sha256", None)
    verified["payload_sha256"] = loader.digest(verified)
    return verified


def verify_fixture(root, materials, papers, mappings, *, snapshot_id=None):
    """Create and verify only owned temporary synthetic bundles; no DB I/O."""
    root = root.resolve()
    root.mkdir(parents=True)
    source_dir, plan_dir = root / "source", root / "plan"
    source_dir.mkdir()
    snapshot_id = snapshot_id or uuid4()
    watermark = "2026-09-07T00:00:00+00:00"
    rows = {"materials": materials, "papers": papers, "paper_work_map": mappings}
    files = {}
    for name, records in rows.items():
        path = source_dir / f"{name}.jsonl"
        path.write_bytes(b"".join(exporter.canonical_json_bytes(row) + b"\n" for row in records))
        files[name] = {"path": path.name, "sha256": exporter.file_sha256(path),
                       "bytes": path.stat().st_size, "rows": len(records)}
    record_count = sum(len(row["records"]) for row in materials)
    license_payload = exporter.build_license_manifest(
        source_snapshot_id=snapshot_id, dataset_version="synthetic-shadow-v1",
        database_watermark=watermark, material_scope="public", paper_source_counts={"arxiv": len(papers)},
        material_record_source_counts={"arxiv_ner": record_count},
    )
    license_path = source_dir / "license_manifest.json"
    license_path.write_text(json.dumps(license_payload, sort_keys=True, indent=2) + "\n")
    files["license_manifest"] = {"path": license_path.name, "sha256": exporter.file_sha256(license_path),
                                 "bytes": license_path.stat().st_size, "rows": 1}
    state = exporter.SnapshotState(
        database_watermark=watermark, database_name="synthetic-disposable-fixture", postgres_version="16",
        transaction_isolation="repeatable read", transaction_read_only="on", transaction_snapshot="1:1:",
        wal_lsn=None, alembic_revision="0053_research_import", paper_work_map_table_present=True,
        counts={"materials": len(materials), "papers": len(papers), "chunks": 0, "paper_work_map": len(mappings)},
        max_material_updated_at=watermark, max_paper_updated_at=watermark,
        paper_source_counts={"arxiv": len(papers)}, material_record_source_counts={"arxiv_ner": record_count},
        material_record_count=record_count,
    )
    manifest = exporter.build_export_manifest(
        source_snapshot_id=snapshot_id, dataset_version="synthetic-shadow-v1", site_git_sha="a" * 40,
        material_scope="public", state=state, files=files, queries={key: "SELECT synthetic_fixture" for key in rows},
        include_paper_work_map=True,
    )
    source_path = source_dir / "export_manifest.json"
    source_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    exporter._write_checksum_files(source_dir, [entry["path"] for entry in files.values()] + [source_path.name])
    source = planner.load_source_export_manifest(source_path)
    plan = planner.build_backfill_plan(materials, papers, source_snapshot_id=snapshot_id, existing_paper_work=mappings)
    planner.write_plan_artifacts(
        plan, output_dir=plan_dir, materials_path=source["materials_path"], papers_path=source["papers_path"],
        existing_map_path=source["existing_map_path"], dataset_version=source["dataset_version"],
        site_git_sha=source["site_git_sha"], database_watermark=source["database_watermark"], chunk_count=0,
        license_manifest_sha256=source["license_manifest_sha256"], source_export_manifest_path=source_path,
        source_export_manifest_sha256=source["manifest_sha256"], source_alembic_revision=source["alembic_revision"],
    )
    plan_path = plan_dir / "manifest.json"
    return verifier.verify_shadow_import(
        source_manifest=source_path, plan_manifest=plan_path,
        expected_source_manifest_sha256=exporter.file_sha256(source_path),
        expected_plan_manifest_sha256=exporter.file_sha256(plan_path),
    )


async def seed_verified(db, tmp_path, *, records=None, paper_status="published", work_status="active", material_overrides=None):
    token = uuid4().hex
    pid, mid, wid = f"arxiv:shadow-{token}", f"mat:shadow-{token}", uuid4()
    if records is None:
        records = [{"tc_kelvin": 39.0, "measurement": "resistivity", "pressure_gpa": 0,
                    "knowledge_origin": "Observed", "source_role": "primary", "source": "arxiv_ner"}]
    records = [{"formula": "MgB2", "paper_id": pid, **row} for row in deepcopy(records)]
    material = {"id": mid, "formula": "MgB2", "formula_normalized": "MgB2", "records": records}
    paper = {"id": pid, "source": "arxiv", "arxiv_id": None, "doi": None, "related_paper_id": None,
             "title": f"Synthetic shadow study {token}", "date_submitted": "2023-06-12", "date_published": None,
             "status": paper_status, "paper_type": "experimental"}
    mapping = {"paper_id": pid, "work_id": str(wid), "relation_type": "preprint",
               "match_method": "manual", "review_status": "accepted"}
    await add(db, "papers", **{**paper, "date_submitted": date(2023, 6, 12), "authors": [], "abstract": ""})
    await add(db, "works", id=wid, canonical_title=paper["title"], publication_status=work_status)
    await add(db, "paper_work_map", **{**mapping, "work_id": wid})
    await add(db, "materials", **{**material, "total_papers": 1, "needs_review": False, **(material_overrides or {})})
    return verify_fixture(tmp_path / token, [material], [paper], [mapping])


async def approved(db, verified, *, review_overrides=None, artifact_overrides=None):
    preview = await loader.preview_shadow_import(db, verified)
    review = loader.processing_review_payload(preview)
    review.update(review_overrides or {})
    values = {"kind": "review", "schema_version": loader.REVIEW_VERSION, "source": "synthetic-processing-review",
              "record_sha256": loader.digest(review), "hash_status": "verified", "bytes_sha256": "d" * 64,
              "access": "restricted", "metadata": {"shadow_import_review": review}, **(artifact_overrides or {})}
    artifact = await add(db, "evidence_artifacts", **values)
    return preview, artifact["id"]


async def test_real_offline_verified_bundle_dry_run_accounts_without_any_table_changes(db_session, tmp_path):
    verified = await seed_verified(db_session, tmp_path)
    preview, review_id = await approved(db_session, verified)
    before = await table_state(db_session, (*LEGACY_TABLES, *TABLE_ORDER, "evidence_artifacts"))
    report = await loader.import_shadow_research(db_session, verified, review_artifact_id=review_id)
    assert report["dry_run"] is True and report["committed"] is False
    assert report["accounting"]["input_occurrences"] == preview["accounting"]["input_occurrences"] == 1
    assert report["accounting"]["inserted"] == 1 and report["rows_inserted"] == 5
    assert before == await table_state(db_session, (*LEGACY_TABLES, *TABLE_ORDER, "evidence_artifacts"))
    assert verified["claims"][0]["available_at"] is None and verified["claims"][0]["validity_status"] == "pending"


async def test_commit_and_retry_reuse_original_receipt_ids_hashes_and_accounting(db_session, tmp_path):
    verified = await seed_verified(db_session, tmp_path)
    _, review_id = await approved(db_session, verified)
    legacy_before = await table_state(db_session)
    first = await loader.import_shadow_research(db_session, verified, review_artifact_id=review_id, dry_run=False)
    initial = await table_state(db_session, TABLE_ORDER)
    await db_session.commit()
    await db_session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    replay = await loader.import_shadow_research(db_session, verified, review_artifact_id=review_id, dry_run=False)
    assert replay["replayed"] is True and replay["receipt_id"] == first["receipt_id"] and replay["rows_inserted"] == 0
    assert replay["original_accounting"] == first["accounting"]
    assert initial == await table_state(db_session, TABLE_ORDER)
    assert legacy_before == await table_state(db_session)


async def test_new_snapshot_capture_metadata_only_adds_membership_not_revision(db_session, tmp_path):
    verified = await seed_verified(db_session, tmp_path)
    _, review_id = await approved(db_session, verified)
    await loader.import_shadow_research(db_session, verified, review_artifact_id=review_id, dry_run=False)
    before = await counts(db_session)
    materials = deepcopy(verified["materials"])
    materials[0]["records"][0]["ingestion_capture"] = {"captured_at": "2026-09-08", "status": "untrusted"}
    materials[0]["records"].append({**materials[0]["records"][0], "temporal_provenance": {"status": "unknown"}})
    table = Base.metadata.tables["materials"]
    await db_session.execute(table.update().where(table.c.id == materials[0]["id"]).values(records=materials[0]["records"]))
    newer = verify_fixture(tmp_path / uuid4().hex, materials, verified["papers"], verified["existing_paper_work"])
    assert newer["claims"][0]["id"] == verified["claims"][0]["id"]
    preview, second_review = await approved(db_session, newer)
    assert preview["accounting"]["reused"] == 2 and preview["accounting"]["input_occurrences"] == 2
    await loader.import_shadow_research(db_session, newer, review_artifact_id=second_review, dry_run=False)
    after = await counts(db_session)
    assert after["research_import_occurrences"] == before["research_import_occurrences"]
    assert after["research_import_revisions"] == before["research_import_revisions"]
    assert after["research_import_memberships"] == before["research_import_memberships"] + 1
    rows = (await table_state(db_session, ["research_import_memberships"]))["research_import_memberships"]
    new_row = next(row for row in rows if str(row["snapshot_id"]) == newer["source_manifest"]["source_snapshot_id"])
    assert new_row["raw_records"] == [{"record_ordinal": index, "raw_record": row}
                                      for index, row in enumerate(materials[0]["records"])]


async def test_changed_mapper_proposal_creates_exact_superseding_revision(db_session, tmp_path):
    verified = await seed_verified(db_session, tmp_path)
    _, review_id = await approved(db_session, verified)
    await loader.import_shadow_research(db_session, verified, review_artifact_id=review_id, dry_run=False)
    newer = deepcopy(verified)
    newer["plan_manifest"]["claim_mapper_version"] = "synthetic-future-mapper/2"
    newer["claims"][0]["extractor_version"] = "synthetic-future-mapper/2"
    newer["claims"][0]["extraction_metadata"]["synthetic_interpretation_revision"] = 2
    newer["plan_manifest_sha256"] = loader.digest(newer["plan_manifest"])
    reseal(newer)
    preview, revised_review = await approved(db_session, newer)
    assert preview["accounting"]["revised"] == 1
    await loader.import_shadow_research(db_session, newer, review_artifact_id=revised_review, dry_run=False)
    table = Base.metadata.tables["research_import_revisions"]
    revisions = (await db_session.execute(sa.select(table).where(table.c.occurrence_id == UUID(verified["claims"][0]["id"]))
                                         .order_by(table.c.revision_number))).mappings().all()
    assert len(revisions) == 2 and revisions[1]["supersedes_id"] == revisions[0]["id"]
    assert revisions[1]["supersedes_revision_number"] == 1
    assert all(row["review_status"] == "pending" and row["scientific_acceptance"] is False for row in revisions)


@pytest.mark.parametrize("mutation", ["preview_hash", "approved_false", "kind", "policy", "unverified", "record_hash"])
async def test_tampered_or_unqualified_processing_review_is_rejected(db_session, tmp_path, mutation):
    verified = await seed_verified(db_session, tmp_path)
    reviews, artifacts = {}, {}
    if mutation == "preview_hash":
        reviews["preview_sha256"] = "f" * 64
    elif mutation == "approved_false":
        reviews["restricted_internal_processing_approved"] = False
    elif mutation == "kind":
        artifacts["kind"] = "policy"
    elif mutation == "policy":
        artifacts["schema_version"] = "unknown-policy"
    elif mutation == "unverified":
        artifacts.update(hash_status="unavailable", bytes_sha256=None)
    else:
        artifacts["record_sha256"] = "f" * 64
    _, review_id = await approved(db_session, verified, review_overrides=reviews, artifact_overrides=artifacts)
    before = await counts(db_session)
    with pytest.raises(loader.ShadowImportError):
        await loader.import_shadow_research(db_session, verified, review_artifact_id=review_id, dry_run=False)
    assert await counts(db_session) == before


async def test_payload_mutation_after_approval_cannot_be_hidden_by_resealing(db_session, tmp_path):
    verified = await seed_verified(db_session, tmp_path)
    _, review_id = await approved(db_session, verified)
    changed = deepcopy(verified)
    changed["claims"][0]["measurement_method"] = "susceptibility"
    for payload in (changed, reseal(deepcopy(changed))):
        before = await counts(db_session)
        with pytest.raises(loader.ShadowImportError):
            await loader.import_shadow_research(db_session, payload, review_artifact_id=review_id, dry_run=False)
        assert await counts(db_session) == before


@pytest.mark.parametrize("mutation", ["work_mapping", "material_hold", "paper_drift", "raw_drift"])
async def test_stale_review_or_unaccepted_live_mapping_prevents_writes(db_session, tmp_path, mutation):
    verified = await seed_verified(db_session, tmp_path)
    _, review_id = await approved(db_session, verified)
    if mutation == "work_mapping":
        table = Base.metadata.tables["paper_work_map"]
        await db_session.execute(table.update().where(table.c.paper_id == verified["papers"][0]["id"]).values(review_status="pending"))
    elif mutation == "paper_drift":
        table = Base.metadata.tables["papers"]
        await db_session.execute(table.update().where(table.c.id == verified["papers"][0]["id"]).values(status="retracted"))
    else:
        table = Base.metadata.tables["materials"]
        updates = {"needs_review": True} if mutation == "material_hold" else {"records": [{"tc_kelvin": 999}]}
        await db_session.execute(table.update().where(table.c.id == verified["materials"][0]["id"]).values(**updates))
    before = await counts(db_session)
    with pytest.raises(loader.ShadowImportError):
        await loader.import_shadow_research(db_session, verified, review_artifact_id=review_id, dry_run=False)
    assert await counts(db_session) == before


async def test_interrupted_write_rolls_back_every_shadow_table_then_retry_is_clean(db_session, tmp_path, monkeypatch):
    verified = await seed_verified(db_session, tmp_path)
    _, review_id = await approved(db_session, verified)
    before = await table_state(db_session, (*LEGACY_TABLES, *TABLE_ORDER))
    original = loader._write_identical
    class ForcedInterruption(BaseException):
        pass
    async def interrupt(db, name, row):
        result = await original(db, name, row)
        if name == "research_import_revisions":
            raise ForcedInterruption()
        return result
    monkeypatch.setattr(loader, "_write_identical", interrupt)
    with pytest.raises(ForcedInterruption):
        await loader.import_shadow_research(db_session, verified, review_artifact_id=review_id, dry_run=False)
    assert before == await table_state(db_session, (*LEGACY_TABLES, *TABLE_ORDER))
    monkeypatch.setattr(loader, "_write_identical", original)
    result = await loader.import_shadow_research(db_session, verified, review_artifact_id=review_id, dry_run=False)
    assert result["accounting"]["inserted"] == 1


@pytest.mark.parametrize("case", ["retracted", "negative"])
async def test_held_or_unqualified_negative_is_accounted_as_quarantine(db_session, tmp_path, case):
    records = [{"result_status": "not_detected", "measurement": "resistivity", "knowledge_origin": "Observed"}] if case == "negative" else None
    verified = await seed_verified(db_session, tmp_path, records=records, paper_status="retracted" if case == "retracted" else "published")
    preview, review_id = await approved(db_session, verified)
    assert preview["accounting"]["quarantined"] == 1 and preview["accounting"]["failed"] == 0
    before = await counts(db_session)
    await loader.import_shadow_research(db_session, verified, review_artifact_id=review_id, dry_run=False)
    after = await counts(db_session)
    assert after["research_import_snapshots"] == before["research_import_snapshots"] + 1
    assert after["research_import_receipts"] == before["research_import_receipts"] + 1
    for name in ("research_import_occurrences", "research_import_revisions", "research_import_memberships"):
        assert after[name] == before[name]


async def test_nonserializable_session_is_rejected_without_reading_legacy_dates(db_session, tmp_path):
    verified = await seed_verified(db_session, tmp_path)
    await db_session.commit()
    await db_session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
    with pytest.raises(loader.ShadowImportError, match="SERIALIZABLE"):
        await loader.preview_shadow_import(db_session, verified)


async def test_malformed_canonical_numeric_shape_is_failed_not_imported(db_session, tmp_path):
    verified = await seed_verified(db_session, tmp_path)
    verified["claims"][0]["pressure_gpa"] = -1
    reseal(verified)
    preview = await loader.preview_shadow_import(db_session, verified)
    assert preview["accounting"]["failed"] == 1
    assert preview["selection_manifest"]["selected"] == []


@pytest.mark.parametrize("target", ["unused_paper", "zero_record_material"])
@pytest.mark.parametrize("change", ["mutated", "missing"])
async def test_all_exported_rows_are_checked_even_without_selected_occurrences(
    db_session, tmp_path, target, change,
):
    original = await seed_verified(db_session, tmp_path)
    materials, papers, mappings = (deepcopy(original[key]) for key in (
        "materials", "papers", "existing_paper_work",
    ))
    unused_paper = {**papers[0], "id": f"arxiv:unused-{uuid4().hex}", "title": "Synthetic unused exported paper"}
    unused_work = uuid4()
    await add(db_session, "papers", **{**unused_paper, "date_submitted": date(2023, 6, 12),
                                       "authors": [], "abstract": ""})
    await add(db_session, "works", id=unused_work, canonical_title=unused_paper["title"], publication_status="active")
    unused_mapping = {"paper_id": unused_paper["id"], "work_id": str(unused_work),
                      "relation_type": "preprint", "match_method": "manual", "review_status": "accepted"}
    await add(db_session, "paper_work_map", **{**unused_mapping, "work_id": unused_work})
    empty_material = {"id": f"mat:empty-{uuid4().hex}", "formula": "Nb", "formula_normalized": "Nb", "records": []}
    await add(db_session, "materials", **empty_material, total_papers=0, needs_review=False)
    papers.append(unused_paper)
    mappings.append(unused_mapping)
    materials.append(empty_material)
    materials.sort(key=lambda row: row["id"])
    papers.sort(key=lambda row: row["id"])
    mappings.sort(key=lambda row: row["paper_id"])
    verified = verify_fixture(tmp_path / uuid4().hex, materials, papers, mappings)
    assert len(verified["claims"]) == 1
    assert all(row["paper_id"] != unused_paper["id"] and row["material_id"] != empty_material["id"]
               for row in verified["claims"])
    preview, review_id = await approved(db_session, verified)
    assert preview["accounting"]["inserted"] == 1
    if target == "unused_paper":
        table, row_id, label = Base.metadata.tables["papers"], unused_paper["id"], "paper"
        mutation = {"title": "Changed after processing review"}
    else:
        table, row_id, label = Base.metadata.tables["materials"], empty_material["id"], "material"
        mutation = {"formula": "Ta", "formula_normalized": "Ta"}
    statement = table.delete() if change == "missing" else table.update().values(**mutation)
    await db_session.execute(statement.where(table.c.id == row_id))
    before = await table_state(db_session, (*LEGACY_TABLES, *TABLE_ORDER))
    expected = f"live {label} " + ("capture incomplete" if change == "missing" else "source capture drift")
    with pytest.raises(loader.ShadowImportError, match=expected):
        await loader.preview_shadow_import(db_session, verified)
    with pytest.raises(loader.ShadowImportError, match=expected):
        await loader.import_shadow_research(db_session, verified, review_artifact_id=review_id, dry_run=False)
    assert await table_state(db_session, (*LEGACY_TABLES, *TABLE_ORDER)) == before


@pytest.mark.parametrize("operation,field,value", [
    ("add", "event_id", str(uuid4())),
    ("add", "interpretation_revision", 1),
    ("add", "scientific_acceptance", True),
    ("add", "unregistered_scientific_property", 123),
    ("remove", "available_at", None),
    ("remove", "semantic_fingerprint", None),
])
async def test_exact_claim_field_allowlist_rejects_added_or_missing_fields_even_when_resealed(
    db_session, tmp_path, operation, field, value,
):
    verified = await seed_verified(db_session, tmp_path)
    _, review_id = await approved(db_session, verified)
    changed = deepcopy(verified)
    if operation == "add":
        assert field not in changed["claims"][0]
        changed["claims"][0][field] = value
    else:
        assert field in changed["claims"][0]
        changed["claims"][0].pop(field)
    reseal(changed)
    before = await table_state(db_session, (*LEGACY_TABLES, *TABLE_ORDER))
    with pytest.raises(loader.ShadowImportError, match="unsupported proposed claim fields"):
        await loader.preview_shadow_import(db_session, changed)
    with pytest.raises(loader.ShadowImportError, match="unsupported proposed claim fields"):
        await loader.import_shadow_research(db_session, changed, review_artifact_id=review_id, dry_run=False)
    assert await table_state(db_session, (*LEGACY_TABLES, *TABLE_ORDER)) == before
