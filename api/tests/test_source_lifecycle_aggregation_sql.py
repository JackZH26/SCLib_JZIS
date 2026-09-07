"""Real PostgreSQL checks of synthetic SC08 ingestion upsert statements.

The API conftest capability gate runs before this module is collected. These
fixtures assert write semantics, never scientific validity or source approval.
No ingestion engine, source importer, cloud client or production data is used.
"""
from __future__ import annotations

import importlib
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from models.db import Material, get_session_factory


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    # Keep any read transaction and its teardown on the test's event loop.
    async with get_session_factory()() as session:
        try:
            yield session
        finally:
            await session.rollback()
            identities = session.info.get("sc08_synthetic_material_ids", [])
            if identities:
                # Delete only this test's explicitly tracked disposable rows;
                # no existing material or immutable research object is touched.
                await session.execute(delete(Material).where(Material.id.in_(identities)))
                await session.commit()


@pytest.fixture(scope="module")
def aggregator():
    # Import the real ingestion table/builder only after the disposable API
    # bootstrap; refuse all ingestion configuration/session factory calls.
    from test_safety import validate_test_environment

    validate_test_environment()

    def prohibited(*args, **kwargs):
        raise AssertionError("Ingestion settings/engine/session must not be used in API SQL tests")

    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "ingestion"))
        config = importlib.import_module("ingestion.config")
        patch.setattr(config.IngestionSettings, "model_config", {
            **config.IngestionSettings.model_config, "env_file": None,
        })
        indexer = importlib.import_module("ingestion.index.indexer")
        module = importlib.import_module("ingestion.extract.materials_aggregator")
        patch.setattr(config, "get_settings", prohibited)
        patch.setattr(indexer, "get_settings", prohibited)
        patch.setattr(indexer, "_session_factory", prohibited)
        patch.setattr(module, "_session_factory", prohibited)
        yield module


def record(paper_id="synthetic:sc08-held", **changes):
    return {"formula": "YBa2Cu3O7", "paper_id": paper_id,
            "tc_kelvin": 90.0, "pressure_gpa": 0.0,
            "pressure_state": "explicit_ambient", "measurement": "resistivity",
            "evidence_type": "primary_experimental", "confidence": 0.95,
            "year": 2024, **changes}


def summary(aggregator, records=None, statuses=None):
    return aggregator._derive_summary("YBa2Cu3O7", [record()] if records is None else records,
        source_statuses=statuses, current_year=2026)


async def seed(db, aggregator, **changes):
    identity = "mat:sc08-sql-" + uuid4().hex
    db.add(Material(**{
        "id": identity, "status": "active_research", **summary(aggregator),
        "updated_at": datetime(2000, 1, 1, tzinfo=UTC), **changes,
    }))
    await db.commit()
    db.info.setdefault("sc08_synthetic_material_ids", []).append(identity)
    return identity


async def read(db, aggregator, identity):
    table = aggregator.materials_table
    result = await db.execute(select(table).where(table.c.id == identity))
    return dict(result.mappings().one())


async def upsert(db, aggregator, identity, derived, **options):
    statement = aggregator._material_upsert_statement(identity, derived, **options)
    result = await db.execute(statement.returning(aggregator.materials_table.c.updated_at))
    changed_at = result.scalar_one_or_none()
    await db.commit()
    return changed_at


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", (None, {"approved": True}, {"approved": False}))
async def test_existing_hold_and_private_reason_survive_fresh_valid_summary(db_session, aggregator, decision):
    identity = await seed(db_session, aggregator, needs_review=True,
                          review_reason="synthetic prior review hold", admin_decision=decision)
    derived = summary(aggregator)
    assert derived["needs_review"] is False
    await upsert(db_session, aggregator, identity, derived)
    row = await read(db_session, aggregator, identity)
    assert row["needs_review"] is True
    assert row["review_reason"] == "synthetic prior review hold"
    assert row["admin_decision"] == decision


@pytest.mark.asyncio
async def test_quarantine_prefix_with_false_legacy_flag_cannot_be_cleared(db_session, aggregator):
    reason = "  Provenance_Quarantine: synthetic restricted source"
    identity = await seed(db_session, aggregator, needs_review=False,
                          review_reason=reason, admin_decision=None)
    await upsert(db_session, aggregator, identity, summary(aggregator))
    row = await read(db_session, aggregator, identity)
    assert row["needs_review"] is True
    assert row["review_reason"] == reason


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", (None, {"approved": True, "note": "historical, not current approval"}))
async def test_new_source_hold_overrides_historical_positive_decision(db_session, aggregator, decision):
    identity = await seed(db_session, aggregator, needs_review=False, admin_decision=decision)
    derived = summary(aggregator, statuses={"synthetic:sc08-held": "retracted"})
    await upsert(db_session, aggregator, identity, derived)
    row = await read(db_session, aggregator, identity)
    assert row["needs_review"] is True
    assert row["review_reason"].startswith("source_support_unavailable:")
    assert row["tc_max"] is None and row["tc_ambient"] is None
    assert row["total_papers"] == 0
    assert row["records"] == [record()]
    assert row["admin_decision"] == decision
    assert row["retracted"] is False and row["disputed"] is False


@pytest.mark.asyncio
async def test_only_source_invalidation_keeps_identity_links_and_existing_scientific_flags(db_session, aggregator):
    parent = await seed(db_session, aggregator)
    identity_fields = {
        "formula": "YBa2Cu3O7.01", "formula_normalized": "synthetic-historical-identity",
        "family": "synthetic-family", "formula_substrate": "synthetic-substrate",
        "formula_overlayer": "synthetic-overlayer", "parent_material_id": parent,
        "variant_count": 7, "mp_id": "synthetic-mp-id", "retracted": True,
        "disputed": True, "status": "under_review",
    }
    identity = await seed(db_session, aggregator, **identity_fields)
    derived = summary(aggregator, statuses={"synthetic:sc08-held": "corrected"})
    await upsert(db_session, aggregator, identity, derived, preserve_identity=True)
    row = await read(db_session, aggregator, identity)
    assert row["id"] == identity
    for key, value in identity_fields.items():
        assert row[key] == value, key
    assert row["tc_max"] is None and row["total_papers"] == 0
    assert row["records"] == [record()] and row["needs_review"] is True


@pytest.mark.asyncio
async def test_actual_change_advances_watermark_but_replay_is_noop_across_transactions(db_session, aggregator):
    identity = await seed(db_session, aggregator)
    first = summary(aggregator, [record(tc_kelvin=80)])
    first_time = await upsert(db_session, aggregator, identity, first)
    assert first_time > datetime(2000, 1, 1, tzinfo=UTC)
    # No returned row proves PostgreSQL did not execute the UPDATE branch.
    assert await upsert(db_session, aggregator, identity, deepcopy(first)) is None
    row = await read(db_session, aggregator, identity)
    assert row["updated_at"] == first_time and row["tc_max"] == 80
    await db_session.commit()
    changed = summary(aggregator, [record(tc_kelvin=81)])
    second_time = await upsert(db_session, aggregator, identity, changed)
    assert second_time > first_time
    row = await read(db_session, aggregator, identity)
    assert row["updated_at"] == second_time and row["tc_max"] == 81


@pytest.mark.asyncio
async def test_mixed_summary_keeps_both_raw_records_but_only_independent_support(db_session, aggregator):
    held = record(tc_kelvin=130)
    independent = record("synthetic:sc08-independent", tc_kelvin=80, year=2025)
    records = [held, independent]
    identity = await seed(db_session, aggregator, records=deepcopy(records), total_papers=2, tc_max=130)
    derived = summary(aggregator, records,
        {held["paper_id"]: "retracted", independent["paper_id"]: "published"})
    await upsert(db_session, aggregator, identity, derived)
    row = await read(db_session, aggregator, identity)
    assert row["id"] == identity and row["records"] == records
    assert row["tc_max"] == row["tc_ambient"] == 80
    assert row["total_papers"] == 1 and row["arxiv_year"] == 2025
    assert independent["paper_id"] in row["tc_max_conditions"]
    assert held["paper_id"] not in row["tc_max_conditions"]
    assert row["retracted"] is False and row["disputed"] is False
    # This test does not claim catalogue admission: SC07 still conservatively
    # holds a material with retained held-source records pending scoped review.
