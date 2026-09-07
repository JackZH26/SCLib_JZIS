"""Synthetic scientific-persistence adversaries for the internal ML03 loader.

These fixtures are deliberately synthetic, not adjudicated scientific evidence
or a training dataset. The guarded disposable runner owns all service access.
"""
from __future__ import annotations

import asyncio
import copy
from uuid import UUID

import pytest
import sqlalchemy as sa

from models.db import Base, Material, get_session_factory
from models.research_import_v1 import TABLE_ORDER
from services import shadow_import as loader
from services.shadow_import import ShadowImportError, import_shadow_research, preview_shadow_import
from tests.test_shadow_import import approved, reseal, seed_verified, table_state
from tests.test_shadow_import import db_session as _serializable_db_session

db_session = _serializable_db_session

_CANONICAL_TABLES = (
    "materials", "material_claims", "source_snapshots", "research_events",
    "material_states", "research_samples", "structure_records", "source_revisions", "source_captures",
    "claim_source_occurrences", "snapshot_event_memberships", "event_properties", "event_evidence",
    "research_runs", "ml_example_inputs",
)


async def _import_and_read(db, verified):
    preview, review_id = await approved(db, verified)
    names = [name for name in _CANONICAL_TABLES if name in Base.metadata.tables]
    before = await table_state(db, names=names)
    result = await import_shadow_research(db, verified, review_artifact_id=review_id, dry_run=False)
    assert result["scientific_acceptance"] is False
    assert result["committed"] is False  # the caller owns the outer transaction
    assert preview["public_release"] is False
    assert await table_state(db, names=names) == before
    state = await table_state(db, names=["research_import_revisions", "research_import_memberships"])
    claim_ids = {str(claim["id"]) for claim in verified["claims"]}
    state = {name: [row for row in rows if str(row["occurrence_id"]) in claim_ids]
             for name, rows in state.items()}
    return preview, result, state


@pytest.mark.asyncio
@pytest.mark.parametrize("tc,unit,pressure,pressure_unit", [
    (39000, "mK", 20, "kbar"), (39, "K", 2000, "MPa"),
    (39, "K", 2_000_000_000, "Pa"),
])
async def test_mixed_units_survive_shadow_import_without_rewriting_raw_or_canonical_state(
    db_session, tmp_path, tc, unit, pressure, pressure_unit,
):
    verified = await seed_verified(db_session, tmp_path, records=[{
        "tc_kelvin": tc, "tc_kelvin_unit": unit,
        "pressure_gpa": pressure, "pressure_unit": pressure_unit,
        "measurement": "resistivity", "source_role": "primary",
    }])
    original = copy.deepcopy(verified["materials"][0]["records"])
    preview, _, state = await _import_and_read(db_session, verified)
    assert preview["accounting"]["inserted"] == 1
    revision = state["research_import_revisions"][0]
    payload = revision["payload"]
    assert payload["value_kelvin"] == 39
    assert payload["pressure_gpa"] == 2
    assert payload["pressure_state"] == "reported"
    assert payload["validity_status"] == "pending"
    assert revision["review_status"] == "pending" and revision["scientific_acceptance"] is False
    assert "available_at" not in payload
    assert "temporal_provenance" not in payload["extraction_metadata"]
    assert state["research_import_memberships"][0]["raw_records"] == [
        {"record_ordinal": 0, "raw_record": original[0]},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("bound,relation", [("< 1.8 K", "lt"), ("<= 1.8 K", "le")])
async def test_qualified_censored_negative_remains_pending_upper_bound_not_positive_tc(
    db_session, tmp_path, bound, relation,
):
    verified = await seed_verified(db_session, tmp_path, records=[{
        "tc_kelvin": bound, "result_status": "not_detected", "minimum_temperature_k": 1.8,
        "measurement": "resistivity", "source_role": "primary", "pressure_gpa": "20 kbar",
    }])
    preview, _, state = await _import_and_read(db_session, verified)
    assert preview["accounting"]["inserted"] == 1
    payload = state["research_import_revisions"][0]["payload"]
    assert payload["property_type"] == "non_transition"
    assert payload["result_status"] == "not_detected"
    assert payload["value_relation"] == relation
    assert payload["value_kelvin"] is None and payload["value_lower_kelvin"] is None
    assert payload["value_upper_kelvin"] == payload["minimum_temperature_k"] == 1.8
    assert payload["pressure_gpa"] == 2
    assert payload["validity_status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("pressure_fields,state,scalar,relation", [
    ({"pressure_gpa": "1-2 GPa"}, "ambiguous", None, "interval"),
    ({"pressure_gpa": "> 2 GPa"}, "ambiguous", None, "gt"),
    ({"pressure_gpa": 2, "pressure_state": "ambiguous"}, "ambiguous", 2, "exact"),
    ({}, "not_reported", None, "unreported"),
    ({"pressure_gpa": 0}, "ambiguous", 0, "exact"),
])
async def test_pressure_unresolved_shapes_are_preserved_without_invented_ambient_state(
    db_session, tmp_path, pressure_fields, state, scalar, relation,
):
    verified = await seed_verified(db_session, tmp_path, records=[{
        "tc_kelvin": 39, "measurement": "resistivity", "source_role": "primary", **pressure_fields,
    }])
    preview, _, rows = await _import_and_read(db_session, verified)
    assert preview["accounting"]["inserted"] == 1
    payload = rows["research_import_revisions"][0]["payload"]
    assert payload["pressure_state"] == state
    assert payload["pressure_gpa"] == scalar
    assert payload["extraction_metadata"]["pressure_semantics"]["relation"] == relation
    assert payload["validity_status"] == "pending"


@pytest.mark.asyncio
async def test_missing_tc_is_unknown_not_a_synthetic_negative(db_session, tmp_path):
    verified = await seed_verified(db_session, tmp_path, records=[{
        "measurement": "resistivity", "source_role": "primary",
    }])
    preview, _, rows = await _import_and_read(db_session, verified)
    assert preview["accounting"]["inserted"] == 1
    payload = rows["research_import_revisions"][0]["payload"]
    assert payload["result_status"] == "unknown"
    assert payload["property_type"] == "tc"
    assert payload["value_relation"] == "unreported" and payload["value_kelvin"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field,original,mutated", [
    ("tc_kelvin", 1, True), ("ambient_sc", False, 0),
])
async def test_boolean_numeric_live_raw_drift_is_not_python_equality_compatible(
    db_session, tmp_path, field, original, mutated,
):
    record = {"tc_kelvin": 39, "measurement": "resistivity", "source_role": "primary", field: original}
    verified = await seed_verified(db_session, tmp_path, records=[record])
    material = verified["materials"][0]
    changed = copy.deepcopy(material["records"])
    changed[0][field] = mutated
    await db_session.execute(sa.update(Material).where(Material.id == material["id"]).values(records=changed))
    with pytest.raises(ShadowImportError, match="live material source capture drift"):
        await preview_shadow_import(db_session, verified)
    # No separate processing review can make stale source bytes importable.
    with pytest.raises(ShadowImportError, match="live material source capture drift"):
        await import_shadow_research(
            db_session, verified, review_artifact_id="00000000-0000-4000-8000-000000000000", dry_run=False,
        )


@pytest.mark.asyncio
async def test_busy_import_lock_fails_without_waiting_or_partial_writes(db_session, tmp_path):
    verified = await seed_verified(db_session, tmp_path)
    _, review_id = await approved(db_session, verified)
    await db_session.commit()
    await db_session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    names = (*_CANONICAL_TABLES, *TABLE_ORDER, "evidence_artifacts")
    before = await table_state(db_session, names=names)
    caller_pid = (await db_session.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one()
    caller_database = (await db_session.execute(sa.text("SELECT current_database()"))).scalar_one()
    # The normal guarded session factory supplies a distinct connection to the
    # same owned disposable database. No manually supplied DSN is involved.
    async with get_session_factory()() as holder:
        await holder.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        assert not holder.new and not holder.dirty and not holder.deleted
        assert (await holder.execute(sa.text("SHOW transaction_isolation"))).scalar_one() == "serializable"
        assert (await holder.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one() != caller_pid
        assert (await holder.execute(sa.text("SELECT current_database()"))).scalar_one() == caller_database
        assert (await holder.execute(sa.text("SELECT pg_try_advisory_xact_lock(:key)"), {
            "key": loader._LOCK_KEY,
        })).scalar_one() is True
        # The holder remains open until the call returns. A blocking lock call
        # would time out here, rather than passing after the lock is released.
        with pytest.raises(ShadowImportError, match="busy; retry the entire transaction"):
            await asyncio.wait_for(import_shadow_research(
                db_session, verified, review_artifact_id=review_id, dry_run=False,
            ), timeout=5)
        assert await table_state(db_session, names=names) == before
        await holder.rollback()
    # A controlled retry after release succeeds as a dry run and still leaves
    # the caller's source rows, review artifact and shadow ledger unchanged.
    await db_session.rollback()
    await db_session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    retry = await import_shadow_research(db_session, verified, review_artifact_id=review_id)
    assert retry["accounting"]["inserted"] == 1 and retry["dry_run"] is True
    assert await table_state(db_session, names=names) == before


@pytest.mark.asyncio
async def test_original_receipt_replay_keeps_its_selection_after_a_newer_interpretation(
    db_session, tmp_path,
):
    verified = await seed_verified(db_session, tmp_path)
    _, original_review = await approved(db_session, verified)
    first = await import_shadow_research(
        db_session, verified, review_artifact_id=original_review, dry_run=False,
    )
    receipt_table = Base.metadata.tables["research_import_receipts"]
    original_receipt = dict((await db_session.execute(sa.select(receipt_table).where(
        receipt_table.c.id == UUID(first["receipt_id"]),
    ))).mappings().one())
    original_selection = copy.deepcopy(original_receipt["selection_manifest"])
    original_revision_id = original_selection["selected"][0]["revision_id"]
    await db_session.commit()
    await db_session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

    # Match the main helper's deliberately reviewed future-adapter simulation;
    # this is not an assertion that the current offline verifier approves a
    # different mapper version or that a new interpretation is scientifically accepted.
    newer = copy.deepcopy(verified)
    newer["plan_manifest"]["claim_mapper_version"] = "synthetic-replay-mapper/2"
    newer["claims"][0]["extractor_version"] = "synthetic-replay-mapper/2"
    newer["claims"][0]["extraction_metadata"]["synthetic_interpretation_revision"] = 2
    newer["plan_manifest_sha256"] = loader.digest(newer["plan_manifest"])
    reseal(newer)
    revised_preview, revised_review = await approved(db_session, newer)
    assert revised_preview["accounting"]["revised"] == 1
    second = await import_shadow_research(
        db_session, newer, review_artifact_id=revised_review, dry_run=False,
    )
    assert second["receipt_id"] != first["receipt_id"]
    revision_table = Base.metadata.tables["research_import_revisions"]
    revisions = (await db_session.execute(sa.select(revision_table).where(
        revision_table.c.occurrence_id == UUID(verified["claims"][0]["id"]),
    ).order_by(revision_table.c.revision_number))).mappings().all()
    assert [row["revision_number"] for row in revisions] == [1, 2]
    assert str(revisions[0]["id"]) == original_revision_id
    assert revisions[1]["supersedes_id"] == revisions[0]["id"]
    await db_session.commit()
    await db_session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

    before_replay = await table_state(db_session, names=(*_CANONICAL_TABLES, *TABLE_ORDER))
    replay = await import_shadow_research(
        db_session, verified, review_artifact_id=original_review, dry_run=False,
    )
    assert replay["replayed"] is True and replay["receipt_id"] == first["receipt_id"]
    assert replay["rows_inserted"] == 0 and replay["committed"] is False
    assert replay["current_eligibility_reassessed"] is False
    assert replay["scientific_acceptance"] is False
    assert replay["original_accounting"] == first["accounting"]
    assert await table_state(db_session, names=(*_CANONICAL_TABLES, *TABLE_ORDER)) == before_replay
    replayed_receipt = dict((await db_session.execute(sa.select(receipt_table).where(
        receipt_table.c.id == UUID(first["receipt_id"]),
    ))).mappings().one())
    assert replayed_receipt == original_receipt
    assert replayed_receipt["selection_manifest"] == original_selection
    assert replayed_receipt["selection_manifest"]["selected"][0]["revision_id"] != str(revisions[1]["id"])
