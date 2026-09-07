"""Synthetic additive shadow-ledger constraints on guarded disposable PostgreSQL.

These direct SQL fixtures test storage boundaries, not authorized import review
or the loader's manifest/parity verification. No live source data is accessed.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from models.db import Base, get_session_factory
from models.research_import_v1 import TABLE_ORDER


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


async def add(db, name, **values):
    table = Base.metadata.tables[name]
    return (await db.execute(table.insert().values(**values).returning(table))).mappings().one()


def snapshot(**changes):
    return dict(id=uuid4(), export_manifest_sha256=uuid4().hex * 2,
                export_manifest={"scope": "synthetic-database-export-not-source-version"},
                dataset_version="synthetic-ri53", site_git_sha="a" * 40,
                database_watermark=datetime(2026, 9, 7, tzinfo=UTC),
                source_alembic_revision="0052_source_provenance", schema_version="sclib-source-export/v1",
                paper_count=1, material_count=1, chunk_count=0, input_record_count=1,
                license_manifest_sha256="b" * 64, record_sha256="c" * 64, **changes)


def revision(occurrence, **changes):
    result = dict(id=uuid4(), occurrence_id=occurrence["id"], revision_number=1,
                  mapper_version="synthetic-mapper/1", interpretation_sha256="d" * 64,
                  payload={"validity_status": "pending", "tc_kelvin": 39}, record_sha256="e" * 64)
    result.update(changes)
    return result


def membership(capture, occurrence, interpreted, **changes):
    result = dict(id=uuid4(), snapshot_id=capture["id"], occurrence_id=occurrence["id"],
                  revision_id=interpreted["id"], source_record_sha256=occurrence["source_record_sha256"],
                  raw_records=[{"record_ordinal": 0, "raw_record": {"formula": "MgB2", "tc_kelvin": 39}}],
                  record_sha256="f" * 64)
    result.update(changes)
    return result


async def seed(db):
    work = await add(db, "works", canonical_title="Synthetic ledger work")
    material = "ri53-" + uuid4().hex
    await add(db, "materials", id=material, formula="MgB2", formula_normalized="MgB2")
    paper = "arxiv:ri53-" + uuid4().hex
    await add(db, "papers", id=paper, source="arxiv", title="Synthetic ledger paper",
              authors=[], abstract="", status="published")
    await add(db, "paper_work_map", paper_id=paper, work_id=work["id"], relation_type="preprint",
              match_method="manual", review_status="accepted")
    capture = await add(db, "research_import_snapshots", **snapshot())
    occurrence_id = uuid4()
    occurrence = await add(db, "research_import_occurrences", id=occurrence_id, legacy_claim_id=occurrence_id,
                           material_id=material, paper_id=paper, work_id=work["id"],
                           source_record_sha256="a" * 64, raw_record={"formula": "MgB2", "tc_kelvin": 39},
                           source_locator={"table": "1"}, identity_version="sclib-source-record/v1",
                           record_sha256="b" * 64)
    interpreted = await add(db, "research_import_revisions", **revision(occurrence))
    member = await add(db, "research_import_memberships", **membership(capture, occurrence, interpreted))
    review = await add(db, "evidence_artifacts", kind="review", schema_version="synthetic-review/1",
                       source="synthetic-test-only", record_sha256="a" * 64, hash_status="not_applicable",
                       access="restricted")
    receipt = await add(db, "research_import_receipts", id=uuid4(), snapshot_id=capture["id"],
                        plan_manifest_sha256=uuid4().hex * 2, loader_version="synthetic-loader/1",
                        approval_artifact_id=review["id"], approval_artifact_sha256=review["record_sha256"],
                        selection_manifest={"membership_ids": [str(member["id"])]}, accounting={"inserted": 1},
                        completed_at=datetime(2026, 9, 7, tzinfo=UTC), record_sha256="b" * 64)
    return capture, occurrence, interpreted, member, receipt


def test_shadow_tables_do_not_require_legacy_claims_or_modify_old_unique_boundary():
    assert len(TABLE_ORDER) == 5 and set(TABLE_ORDER) <= set(Base.metadata.tables)
    legacy = Base.metadata.tables["material_claims"]
    assert "uq_material_claims_material_source_hash" in {item.name for item in legacy.constraints}
    new_targets = {fk.target_fullname for name in TABLE_ORDER for fk in Base.metadata.tables[name].foreign_keys}
    assert not any(target.startswith(("material_claims.", "research_events.", "source_snapshots.", "source_revisions."))
                   for target in new_targets)
    assert "source_version_public_at" not in Base.metadata.tables["research_import_snapshots"].c
    assert "available_at" not in Base.metadata.tables["research_import_revisions"].c


async def test_pending_defaults_and_same_legacy_uuid_without_v1_claim_insert(db_session):
    capture, occurrence, interpreted, _, _ = await seed(db_session)
    assert capture["status"] == "captured"
    assert occurrence["id"] == occurrence["legacy_claim_id"]
    assert interpreted["review_status"] == "pending" and interpreted["scientific_acceptance"] is False
    table = Base.metadata.tables["material_claims"]
    assert (await db_session.execute(sa.select(table.c.id).where(table.c.id == occurrence["id"]))).first() is None


@pytest.mark.parametrize("name", TABLE_ORDER)
@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
async def test_all_shadow_history_is_sql_append_only(db_session, name, operation):
    await seed(db_session)
    table = Base.metadata.tables[name]
    statement = {"update": table.update().values(record_sha256="e" * 64),
                 "delete": table.delete(), "truncate": sa.text(f"TRUNCATE {name} CASCADE")}[operation]
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(statement)


@pytest.mark.parametrize("change", [
    {"review_status": "approved"}, {"scientific_acceptance": True},
    {"payload": {"validity_status": "accepted"}}, {"payload": []},
    {"revision_number": 0}, {"revision_number": 2},
    {"revision_number": 2, "supersedes_id": uuid4()},
])
async def test_revision_never_auto_accepts_or_skips_exact_predecessor(db_session, change):
    _, occurrence, _, _, _ = await seed(db_session)
    data = revision(occurrence, mapper_version="other", interpretation_sha256="f" * 64, **change)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(db_session, "research_import_revisions", **data)


async def test_exact_same_occurrence_revision_chain_is_append_only_and_not_forkable(db_session):
    _, occurrence, first, _, _ = await seed(db_session)
    second = await add(db_session, "research_import_revisions", **revision(
        occurrence, revision_number=2, supersedes_id=first["id"], supersedes_revision_number=1,
        mapper_version="synthetic-mapper/2", interpretation_sha256="f" * 64,
    ))
    third = await add(db_session, "research_import_revisions", **revision(
        occurrence, revision_number=3, supersedes_id=second["id"], supersedes_revision_number=2,
        mapper_version="synthetic-mapper/3", interpretation_sha256="f" * 64,
    ))
    assert third["supersedes_id"] == second["id"]
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(db_session, "research_import_revisions", **revision(
                occurrence, revision_number=3, supersedes_id=first["id"], supersedes_revision_number=2,
                mapper_version="fork", interpretation_sha256="a" * 64,
            ))


async def test_predecessor_cannot_reference_another_occurrence(db_session):
    _, occurrence, _, _, _ = await seed(db_session)
    _, _, another, _, _ = await seed(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(db_session, "research_import_revisions", **revision(
                occurrence, revision_number=2, supersedes_id=another["id"], supersedes_revision_number=1,
                mapper_version="new", interpretation_sha256="f" * 64,
            ))


async def test_repeated_export_only_adds_membership_and_preserves_full_annotation_variants(db_session):
    capture, occurrence, interpreted, _, _ = await seed(db_session)
    second_capture = await add(db_session, "research_import_snapshots", **snapshot())
    originals = [
        {"record_ordinal": 0, "raw_record": {"formula": "MgB2", "tc_kelvin": 39, "ingestion_capture": {"attempt": "new"}}},
        {"record_ordinal": 3, "raw_record": {"formula": "MgB2", "tc_kelvin": 39, "temporal_provenance": {"status": "untrusted"}}},
    ]
    member = await add(db_session, "research_import_memberships", **membership(
        second_capture, occurrence, interpreted, raw_records=originals,
    ))
    assert member["raw_records"] == originals and member["snapshot_id"] != capture["id"]
    revisions = Base.metadata.tables["research_import_revisions"]
    assert (await db_session.execute(sa.select(sa.func.count()).select_from(revisions).where(
        revisions.c.occurrence_id == occurrence["id"],
    ))).scalar_one() == 1


async def test_one_export_can_pin_multiple_interpretations_without_duplicating_occurrence(db_session):
    capture, occurrence, first, _, _ = await seed(db_session)
    second = await add(db_session, "research_import_revisions", **revision(
        occurrence, revision_number=2, supersedes_id=first["id"], supersedes_revision_number=1,
        mapper_version="synthetic-mapper/2", interpretation_sha256="f" * 64,
    ))
    await add(db_session, "research_import_memberships", **membership(capture, occurrence, second))
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(db_session, "research_import_memberships", **membership(capture, occurrence, second))


@pytest.mark.parametrize("change", [{"source_record_sha256": "f" * 64}, {"revision_id": uuid4()}])
async def test_membership_source_and_revision_bindings_cannot_drift(db_session, change):
    capture, occurrence, interpreted, _, _ = await seed(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(db_session, "research_import_memberships", **membership(capture, occurrence, interpreted, **change))


@pytest.mark.parametrize("raw_records", [[], {}, [True], [{"record_ordinal": 0}],
                                         [{"record_ordinal": -1, "raw_record": {}}],
                                         [{"record_ordinal": True, "raw_record": {}}],
                                         [{"record_ordinal": 0.5, "raw_record": {}}],
                                         [{"record_ordinal": 0, "raw_record": []}]])
async def test_full_raw_archive_requires_explicit_ordinal_and_record_object(db_session, raw_records):
    _, occurrence, interpreted, _, _ = await seed(db_session)
    capture = await add(db_session, "research_import_snapshots", **snapshot())
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await add(db_session, "research_import_memberships", **membership(
                capture, occurrence, interpreted, raw_records=raw_records,
            ))


async def test_occurrence_cannot_change_historical_uuid_reference(db_session):
    _, occurrence, _, _, _ = await seed(db_session)
    row = {key: value for key, value in occurrence.items() if key != "created_at"}
    row["id"], row["legacy_claim_id"] = uuid4(), uuid4()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(db_session, "research_import_occurrences", **row)


async def test_receipt_requires_review_artifact_kind_not_just_any_artifact(db_session):
    _, _, _, _, receipt = await seed(db_session)
    artifact = await add(db_session, "evidence_artifacts", kind="policy", schema_version="synthetic/1",
                         source="synthetic", record_sha256="c" * 64, hash_status="not_applicable", access="restricted")
    row = {key: value for key, value in receipt.items() if key != "created_at"}
    row.update(id=uuid4(), plan_manifest_sha256=uuid4().hex * 2, approval_artifact_id=artifact["id"])
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(db_session, "research_import_receipts", **row)


@pytest.mark.parametrize("changes", [{"status": "frozen"}, {"status": "validated"}, {"paper_count": -1},
                                     {"database_watermark": "infinity"}, {"export_manifest": []}])
async def test_import_snapshot_is_neither_ml_release_nor_unvalidated_counter(db_session, changes):
    row = snapshot()
    row.update(changes)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await add(db_session, "research_import_snapshots", **row)


def test_migration_has_empty_only_guard_and_no_legacy_alterations():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0053_research_import.py"
    source = path.read_text()
    assert 'down_revision = "0052_source_provenance"' in source
    assert "ACCESS EXCLUSIVE MODE" in source and "Refusing destructive" in source
    assert "op.add_column" not in source and "op.drop_constraint" not in source
