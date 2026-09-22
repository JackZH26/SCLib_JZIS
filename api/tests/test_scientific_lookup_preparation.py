"""Real retained-parent preparation; synthetic inputs are not scientific gold.

Only run through scripts/run_disposable_tests.py. Providers are never used.
"""
from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import FrozenInstanceError, replace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

from config import get_settings
from models.db import Paper, PaperWorkMap, Work, get_session_factory
from services import index_retrieval, index_vector_adapter, retrieval_currentness
from services.rag_evidence_contract import input_record_sha256
from services.scientific_query import interpret_scientific_query
from services.scientific_query_lookup import (
    lookup_scientific_results,
    prepare_scientific_lookup,
)
from tests.index_generation_fixtures import RESOURCE, publish_and_activate
from tests.test_scientific_query_http import record, stage_records


@pytest_asyncio.fixture(loop_scope="function")
async def prepared_runtime(monkeypatch):
    logical = "scientific-prepare-" + uuid4().hex
    monkeypatch.setattr(get_settings(), "retrieval_logical_index", logical)
    index_vector_adapter.clear_disposable()
    index_vector_adapter.register_disposable(RESOURCE)
    values = [record(tc="39 K", sample_label="Synthetic sample A", raw_extraction={
        "tc_kelvin": "39 K", "source_context": "Synthetic exact context, not independently reviewed.",
        "custom_payload": {"preserve": ["all", "raw", "fields"]}}), record(tc="20 K"), record(tc="38 K")]
    async with get_session_factory()() as db:
        meta, chunks, staged = await stage_records(monkeypatch, db, logical, values)
        active, _, _ = await publish_and_activate(db, staged)
        pin = await index_retrieval.load_pin(db)
        assert pin["activation_event_id"] == active["activation_event_id"]
        yield db, pin, values, meta, chunks
    index_vector_adapter.clear_disposable()


def numerical():
    return interpret_scientific_query("What is the Tc of MgB2?")


async def test_prepare_preserves_caller_transaction_and_exact_full_parent(prepared_runtime, monkeypatch):
    db, pin, values, _, _ = prepared_runtime
    transaction = db.get_transaction()
    forbidden = AsyncMock(side_effect=AssertionError("Preparation must not finish/check a transaction"))
    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", forbidden)
        patch.setattr(db, "rollback", forbidden)
        patch.setattr(retrieval_currentness, "check_selected_sources", forbidden)
        patch.setattr(index_retrieval, "require_current_pin", forbidden)
        prepared = await prepare_scientific_lookup(db, pin, numerical(), sort="tc")
    forbidden.assert_not_called()
    assert db.get_transaction() is transaction
    inputs = prepared.consume()
    assert [row.result.tc.value for row in inputs.outcome.results] == [39, 38, 20]
    assert len(inputs.parents) == len(inputs.selection_pins) == 3
    for parent, row, selected_pin in zip(inputs.parents, inputs.outcome.results, inputs.selection_pins, strict=True):
        actual = (await db.execute(sa.text("SELECT input_record_sha256,record_sha256 FROM rag_extraction_revisions WHERE id=:id"),
                                  {"id": UUID(parent.parent_result_revision_id)})).mappings().one()
        assert parent.input_record_sha256 == actual["input_record_sha256"] == input_record_sha256(parent.raw_record)
        assert row.binding.parent_result_sha256 == actual["record_sha256"]
        assert parent.parent_result_revision_id == row.binding.parent_result_revision_id
        assert parent.paper_id == row.binding.paper_id == selected_pin.paper_id
        assert parent.vector_id == row.binding.vector_id == selected_pin.chunk_id
        assert parent.source_snapshot_sha256 == parent.member["source_snapshot_sha256"]
        assert parent.raw_record == parent.member["snapshot_json"]["materials_mentioned"][parent.record_index]
        assert selected_pin.grouping_sha256 is not None
        assert "vector_bytes" not in parent.member
    assert inputs.parents[0].raw_record == values[0]


async def test_all_exposed_nested_data_are_detached_and_handle_is_one_shot(prepared_runtime):
    db, pin, values, _, _ = prepared_runtime
    prepared = await prepare_scientific_lookup(db, pin, numerical(), sort="tc")
    original_pin = deepcopy(pin)
    prepared.outcome.results.clear()
    prepared.outcome.status.reason_codes.append("mutated")
    parent = prepared.parents[0]
    parent.raw_record["raw_extraction"]["custom_payload"]["preserve"].clear()
    parent.member["snapshot_json"]["materials_mentioned"].clear()
    parent.member["paper_snapshot_json"].clear()
    pin["profile"].clear()
    with pytest.raises(FrozenInstanceError):
        parent.paper_id = "mutated"
    with pytest.raises(FrozenInstanceError):
        parent.selection_pin.input_sha256 = "0" * 64
    for copier in (copy, deepcopy):
        with pytest.raises(TypeError, match="single-consumption"):
            copier(prepared)
    inputs = prepared.consume()
    assert inputs.parents[0].raw_record == values[0]
    assert len(inputs.outcome.results) == 3
    assert "mutated" not in inputs.outcome.status.reason_codes
    assert inputs.generation_pin == original_pin
    inputs.outcome.results.clear()
    inputs.generation_pin["profile"].clear()
    assert len(inputs.outcome.results) == 3 and inputs.generation_pin == original_pin
    for access in (prepared.consume, lambda: prepared.outcome, lambda: prepared.parents, lambda: prepared.selection_pins):
        with pytest.raises(ValueError, match="already been consumed"):
            access()


@pytest.mark.parametrize("mutation", ["swap", "drop", "duplicate", "raw", "identity", "pin"])
async def test_private_inputs_reject_broken_result_parent_pin_bijection(prepared_runtime, mutation):
    db, pin, _, _, _ = prepared_runtime
    inputs = (await prepare_scientific_lookup(db, pin, numerical(), sort="tc")).consume()
    parents = list(inputs.parents)
    if mutation == "swap":
        parents.reverse()
    elif mutation == "drop":
        parents.pop()
    elif mutation == "duplicate":
        parents[1] = parents[0]
    elif mutation == "raw":
        parents[0] = replace(parents[0], _raw_record_json='{"formula":"Nb"}')
    elif mutation == "identity":
        parents[0] = replace(parents[0], parent_result_revision_id=str(uuid4()))
    elif mutation == "pin":
        parents[0] = replace(parents[0], selection_pin=replace(parents[0].selection_pin, chunk_id=parents[1].vector_id))
    with pytest.raises(ValueError, match="one-to-one|binding mismatch"):
        replace(inputs, parents=tuple(parents))


async def test_prepare_exception_propagates_without_rollback_or_hidden_fresh_check(prepared_runtime, monkeypatch):
    db, pin, _, _, _ = prepared_runtime
    real = index_retrieval.resolve_evidence
    async def mismatched(db, chunks):
        values = await real(db, chunks)
        for value in values.values():
            value["parent_result_sha256"] = "0" * 64
        return values
    forbidden = AsyncMock(side_effect=AssertionError("Caller owns failed transaction cleanup"))
    with monkeypatch.context() as patch:
        patch.setattr(index_retrieval, "resolve_evidence", mismatched)
        patch.setattr(db, "rollback", forbidden)
        patch.setattr(db, "commit", forbidden)
        patch.setattr(retrieval_currentness, "check_selected_sources", forbidden)
        with pytest.raises(ValueError, match="parent binding changed"):
            await prepare_scientific_lookup(db, pin, numerical())
    forbidden.assert_not_called()
    assert db.in_transaction()


async def test_second_hydration_cannot_change_the_full_raw_parent(prepared_runtime, monkeypatch):
    db, pin, _, _, _ = prepared_runtime
    real = index_retrieval.hydrate
    async def mismatched(db, pin, ids):
        chunks = await real(db, pin, ids)
        for chunk in chunks.values():
            for value in chunk.materials_mentioned:
                value["unprojected_raw_field"] = "changed"
        return chunks
    monkeypatch.setattr(index_retrieval, "hydrate", mismatched)
    with pytest.raises(ValueError, match="raw parent changed"):
        await prepare_scientific_lookup(db, pin, numerical())


async def test_wrapper_preserves_order_limit_and_checks_after_exactly_one_rollback(prepared_runtime, monkeypatch):
    db, pin, _, _, _ = prepared_runtime
    expected = (await prepare_scientific_lookup(db, pin, numerical(), sort="tc", limit=2)).consume()
    real_rollback, real_check, real_require = db.rollback, retrieval_currentness.check_selected_sources, index_retrieval.require_current_pin
    events = []
    async def rollback():
        events.append("rollback")
        return await real_rollback()
    async def check(pins, **kwargs):
        assert tuple(pins) == expected.selection_pins
        events.append("fresh")
        return await real_check(pins, **kwargs)
    async def require(db, pin):
        events.append("current_generation")
        return await real_require(db, pin)
    with monkeypatch.context() as patch:
        patch.setattr(db, "rollback", rollback)
        patch.setattr(retrieval_currentness, "check_selected_sources", check)
        patch.setattr(index_retrieval, "require_current_pin", require)
        outcome = await lookup_scientific_results(db, pin, numerical(), sort="tc", limit=2)
    assert events == ["rollback", "fresh", "current_generation"]
    assert outcome == expected.outcome
    assert outcome.status.has_more and outcome.status.returned_count == 2


async def test_wrapper_withdraws_all_rows_when_fresh_check_changes(prepared_runtime, monkeypatch):
    db, pin, _, _, _ = prepared_runtime
    check = AsyncMock(return_value=retrieval_currentness.CurrentnessCheck("changed", "retrieval_source_changed"))
    require = AsyncMock(side_effect=AssertionError("A failed inventory has no publishable subset"))
    monkeypatch.setattr(retrieval_currentness, "check_selected_sources", check)
    monkeypatch.setattr(index_retrieval, "require_current_pin", require)
    outcome = await lookup_scientific_results(db, pin, numerical())
    assert outcome.results == [] and outcome.status.status == "unavailable"
    assert len(check.call_args.args[0]) == 3
    require.assert_not_called()


async def test_consumed_handle_stays_consumed_after_actual_source_hold(prepared_runtime):
    db, pin, _, meta, _ = prepared_runtime
    prepared = await prepare_scientific_lookup(db, pin, numerical())
    inputs = prepared.consume()
    await db.rollback()
    async with get_session_factory()() as writer:
        await writer.execute(sa.update(Paper).where(Paper.id == meta.paper_id).values(status="retracted"))
        await writer.commit()
    checked = await retrieval_currentness.check_selected_sources(inputs.selection_pins,
        evidence_resolver=index_retrieval.resolve_evidence)
    assert checked.status == "changed"
    with pytest.raises(ValueError, match="already been consumed"):
        prepared.consume()


@pytest.mark.parametrize("before,after", [(None, "accepted"), ("accepted", "rejected"), ("pending", "accepted")])
async def test_every_numerical_parent_pin_withholds_on_actual_work_mapping_change(prepared_runtime, before, after):
    db, pin, _, meta, _ = prepared_runtime
    await db.rollback()
    async with get_session_factory()() as writer:
        work = Work(canonical_title="Synthetic preparation Work", publication_status="active")
        writer.add(work)
        await writer.flush()
        work_id = work.id
        if before is not None:
            writer.add(PaperWorkMap(paper_id=meta.paper_id, work_id=work_id, match_method="manual", review_status=before))
        await writer.commit()
    inputs = (await prepare_scientific_lookup(db, pin, numerical())).consume()
    await db.rollback()
    assert len(inputs.selection_pins) == 3
    assert all(value.grouping_sha256 is not None for value in inputs.selection_pins)
    assert (await retrieval_currentness.check_selected_sources(inputs.selection_pins,
        evidence_resolver=index_retrieval.resolve_evidence)).status == "unchanged"
    async with get_session_factory()() as writer:
        if before is None:
            writer.add(PaperWorkMap(paper_id=meta.paper_id, work_id=work_id, match_method="manual", review_status=after))
        else:
            await writer.execute(sa.update(PaperWorkMap).where(PaperWorkMap.paper_id == meta.paper_id).values(review_status=after))
        await writer.commit()
    current = await retrieval_currentness.check_selected_sources(inputs.selection_pins,
        evidence_resolver=index_retrieval.resolve_evidence)
    assert current.status == "changed" and current.reason_code == "retrieval_grouping_changed"


@pytest.mark.parametrize("limit", [0, 21, True, 1.5, "2"])
async def test_result_bounds_are_checked_without_consuming_transaction(prepared_runtime, limit, monkeypatch):
    db, pin, _, _, _ = prepared_runtime
    forbidden = AsyncMock(side_effect=AssertionError("Invalid bounds must fail before SQL"))
    with monkeypatch.context() as patch:
        patch.setattr(db, "execute", forbidden)
        with pytest.raises(ValueError, match="bounded result count"):
            await prepare_scientific_lookup(db, pin, numerical(), limit=limit)
    forbidden.assert_not_called()


@pytest.mark.parametrize("mode", ["missing_generation", "clarification", "empty"])
async def test_nonselected_results_are_explicit_without_invented_parents(prepared_runtime, mode, monkeypatch):
    db, pin, _, _, _ = prepared_runtime
    query = interpret_scientific_query("Tc of 13C" if mode == "clarification" else "What is the Tc of Nb?")
    forbidden = AsyncMock(side_effect=AssertionError("Preparation must not check or end reads"))
    with monkeypatch.context() as patch:
        patch.setattr(db, "rollback", forbidden)
        patch.setattr(db, "commit", forbidden)
        patch.setattr(retrieval_currentness, "check_selected_sources", forbidden)
        prepared = await prepare_scientific_lookup(db, None if mode == "missing_generation" else pin, query)
    inputs = prepared.consume()
    assert not inputs.parents and not inputs.selection_pins and not inputs.outcome.results
    assert inputs.outcome.status.status == {
        "missing_generation": "unavailable", "clarification": "clarification_required", "empty": "completed"}[mode]
    forbidden.assert_not_called()
