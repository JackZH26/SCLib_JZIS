"""Bounded generation snapshots/CAS on owned synthetic services only."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base, Chunk, PaperWorkMap, Work, get_session_factory
from models.index_generations_v1 import HISTORY_TABLES
from services import index_generations as service
from services.index_generations import (
    IndexGenerationError,
    activate_generation,
    load_active_generation,
    load_generation_members,
    manifest_sha256,
    record_validation,
    stage_generation,
)
from tests.test_embedding_receipts import prepared
from tests.test_research_freeze import state


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


def resource(backend="disposable"):
    return {"backend": backend, "project": "synthetic", "location": "local", "index_resource": "synthetic-index",
            "endpoint_resource": "synthetic-endpoint", "deployed_index_id": "synthetic-deployed",
            "distance_measure": "COSINE_DISTANCE", "feature_norm": "NONE"}


async def staged(db, *, identifier=None, parser="synthetic-parser/1", backend="disposable", logical_index="sclib-main"):
    from services.embedding_receipts import append_embedding_receipt

    chunk, vector, receipt, _ = await prepared(db)
    completed = await append_embedding_receipt(db, chunk_id=chunk, vector=vector, receipt=receipt, dry_run=False)
    items = [{"chunk_id": chunk, "receipt_id": completed["receipt_id"], "vector": vector, "parser_version": parser}]
    result = await stage_generation(db, generation_id=identifier or uuid4(), items=items, resource=resource(backend), logical_index=logical_index, dry_run=False)
    return result, items


async def observation(db, generation, *, complete=True):
    members = await load_generation_members(db, generation_id=generation["generation_id"])
    return {"version": "sclib-index-observation/1.0.0", "observation_id": str(uuid4()), "resource": generation["resource"],
            "observed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "profile": generation["profile"], "adapter_version": "synthetic/1", "full_inventory_observed": complete,
            "vectors": [{key: row[key] for key in ("vector_id", "content_sha256", "vector_sha256")} for row in members]}


async def validated(db, generation, *, complete=True):
    return await record_validation(db, generation_id=generation["generation_id"],
                                   observation=await observation(db, generation, complete=complete), dry_run=False)


def test_no_historical_fk_to_mutable_chunks_and_full_bytes_retained():
    table = Base.metadata.tables["index_generation_members"]
    assert all(key.column.table.name != "chunks" for key in table.foreign_keys)
    assert {"snapshot_json", "paper_snapshot_json", "vector_bytes", "evidence_revision_id", "receipt_id"} <= set(table.c.keys())


async def test_staging_dryrun_outer_rollback_and_exact_replay_are_full_state_noops(db_session):
    first, items = await staged(db_session)
    before = await state(db_session)
    second_id = uuid4()
    dry = await stage_generation(db_session, generation_id=second_id, items=items, resource=resource())
    assert dry["committed"] is False and dry["activation_event_id"] is None
    assert await state(db_session) == before
    replay = await stage_generation(db_session, generation_id=first["generation_id"], items=deepcopy(items), resource=resource(), dry_run=False)
    assert replay == first and await state(db_session) == before
    members = await load_generation_members(db_session, generation_id=first["generation_id"])
    assert manifest_sha256(members) == first["manifest_sha256"]
    assert members[0]["snapshot_json"]["text"] and len(members[0]["vector_bytes"]) == 3072
    assert "paper_geo" not in members[0]["paper_snapshot_json"]
    await db_session.rollback()
    assert await load_generation_members(db_session, generation_id=first["generation_id"]) == []


@pytest.mark.parametrize("backend,complete", [("disposable", True), ("vertex-public", False)])
async def test_exact_declared_members_validate_without_claiming_orphan_absence(db_session, backend, complete):
    generation, _ = await staged(db_session, backend=backend)
    report = await observation(db_session, generation, complete=complete)
    before = await state(db_session)
    dry = await record_validation(db_session, generation_id=generation["generation_id"], observation=report)
    assert dry["outcome"] == "validated" and dry["validation_scope"] == "declared_generation_members"
    assert await state(db_session) == before
    result = await record_validation(db_session, generation_id=generation["generation_id"], observation=report, dry_run=False)
    written = await state(db_session)
    assert await record_validation(db_session, generation_id=generation["generation_id"], observation=report, dry_run=False) == result
    assert await state(db_session) == written
    another = await record_validation(db_session, generation_id=generation["generation_id"], observation={**report, "observation_id": str(uuid4())}, dry_run=False)
    assert another["validation_id"] != result["validation_id"]


@pytest.mark.parametrize("bad", ["missing", "extra", "hash", "duplicate", "profile", "resource"])
async def test_partial_mismatched_or_wrong_space_observations_cannot_activate(db_session, bad):
    generation, _ = await staged(db_session)
    report = await observation(db_session, generation)
    if bad == "missing": report["vectors"] = []
    elif bad == "extra": report["vectors"].append({**report["vectors"][0], "vector_id": "orphan"})
    elif bad == "hash": report["vectors"][0]["vector_sha256"] = "0" * 64
    elif bad == "duplicate": report["vectors"] *= 2
    elif bad == "profile": report["profile"]["model"] = "wrong"
    else: report["resource"]["index_resource"] = "wrong"
    if bad in {"duplicate", "profile", "resource"}:
        with pytest.raises((ValueError, DBAPIError)):
            await record_validation(db_session, generation_id=generation["generation_id"], observation=report, dry_run=False)
    else:
        result = await record_validation(db_session, generation_id=generation["generation_id"], observation=report, dry_run=False)
        assert result["outcome"] == "rejected"
        with pytest.raises(DBAPIError, match="cas_or_validation"):
            await activate_generation(db_session, generation_id=generation["generation_id"], validation_id=result["validation_id"],
                                      expected_event_id=None, idempotency_key="bad", dry_run=False)
    assert await load_active_generation(db_session) is None


async def test_activation_cas_rollback_preserves_old_bytes_and_epoch_noop(db_session):
    first, items = await staged(db_session)
    v1 = await validated(db_session, first)
    before = await state(db_session)
    args = dict(generation_id=first["generation_id"], validation_id=v1["validation_id"], expected_event_id=None, idempotency_key="first")
    await activate_generation(db_session, **args)
    assert await state(db_session) == before
    a1 = await activate_generation(db_session, **args, dry_run=False)
    written = await state(db_session)
    assert await activate_generation(db_session, **args, dry_run=False) == a1
    assert await state(db_session) == written
    second = await stage_generation(db_session, generation_id=uuid4(), items=[{**items[0], "parser_version": "synthetic-parser/2"}], resource=resource(), dry_run=False)
    v2 = await validated(db_session, second)
    with pytest.raises(DBAPIError, match="cas_or_validation"):
        await activate_generation(db_session, generation_id=second["generation_id"], validation_id=v2["validation_id"],
                                  expected_event_id=None, idempotency_key="wrong-predecessor", dry_run=False)
    a2 = await activate_generation(db_session, generation_id=second["generation_id"], validation_id=v2["validation_id"],
                                   expected_event_id=a1["activation_event_id"], idempotency_key="second", dry_run=False)
    retained = await load_generation_members(db_session, generation_id=first["generation_id"])
    await db_session.execute(sa.delete(Chunk).where(Chunk.id == items[0]["chunk_id"]))
    assert await load_generation_members(db_session, generation_id=first["generation_id"]) == retained
    rollback = await activate_generation(db_session, generation_id=first["generation_id"], validation_id=v1["validation_id"],
                                        expected_event_id=a2["activation_event_id"], idempotency_key="rollback", action="rollback", dry_run=False)
    assert (await load_active_generation(db_session))["activation_event_id"] == rollback["activation_event_id"]
    with pytest.raises(DBAPIError, match="cas_or_validation"):
        await activate_generation(db_session, generation_id=second["generation_id"], validation_id=v2["validation_id"],
                                  expected_event_id=a1["activation_event_id"], idempotency_key="aba", dry_run=False)


@pytest.mark.parametrize("table", HISTORY_TABLES)
@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
async def test_history_is_append_only(db_session, table, operation):
    generation, _ = await staged(db_session)
    validation = await validated(db_session, generation)
    await activate_generation(db_session, generation_id=generation["generation_id"], validation_id=validation["validation_id"],
                              expected_event_id=None, idempotency_key="initial", dry_run=False)
    sql = {"update": f"UPDATE {table} SET record_sha256=record_sha256", "delete": f"DELETE FROM {table}", "truncate": f"TRUNCATE {table} CASCADE"}[operation]
    with pytest.raises(DBAPIError, match="append-only|requires_activation_event"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(sql))


async def test_pointer_cannot_be_changed_without_an_activation(db_session):
    generation, _ = await staged(db_session)
    validation = await validated(db_session, generation)
    await activate_generation(db_session, generation_id=generation["generation_id"], validation_id=validation["validation_id"],
                              expected_event_id=None, idempotency_key="initial", dry_run=False)
    for statement in ("UPDATE index_active_pointer SET generation_id=generation_id", "DELETE FROM index_active_pointer", "TRUNCATE index_active_pointer"):
        with pytest.raises(DBAPIError, match="requires_activation_event"):
            async with db_session.begin_nested():
                await db_session.execute(sa.text(statement))


async def test_source_correction_blocks_rollback_without_deleting_history(db_session):
    generation, items = await staged(db_session)
    validation = await validated(db_session, generation)
    active = await activate_generation(db_session, generation_id=generation["generation_id"], validation_id=validation["validation_id"],
                                       expected_event_id=None, idempotency_key="initial", dry_run=False)
    members = await load_generation_members(db_session, generation_id=generation["generation_id"])
    await db_session.execute(sa.text("UPDATE papers SET status='corrected' WHERE id=:id"), {"id": members[0]["paper_id"]})
    with pytest.raises((IndexGenerationError, DBAPIError), match="hold"):
        await activate_generation(db_session, generation_id=generation["generation_id"], validation_id=validation["validation_id"],
                                  expected_event_id=active["activation_event_id"], idempotency_key="held", action="rollback", dry_run=False)
    assert await load_generation_members(db_session, generation_id=generation["generation_id"]) == members


async def test_pilot_member_cap_fails_before_writes(db_session):
    before = await state(db_session)
    with pytest.raises(IndexGenerationError, match="1..1000"):
        await stage_generation(db_session, generation_id=uuid4(), items=[{}] * 1001, resource=resource(), dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("parser", ["unknown", "legacy_unknown", "unrecorded", "title with spaces", "解析/1"])
async def test_new_generations_require_actual_parser_labels(db_session, parser):
    generation, items = await staged(db_session)
    before = await state(db_session)
    with pytest.raises(IndexGenerationError, match="parser version"):
        await stage_generation(db_session, generation_id=uuid4(), items=[{**items[0], "parser_version": parser}], resource=resource(), dry_run=False)
    assert await state(db_session) == before


async def test_observation_identity_cannot_be_reused_for_changed_report(db_session):
    generation, _ = await staged(db_session)
    report = await observation(db_session, generation)
    await record_validation(db_session, generation_id=generation["generation_id"], observation=report, dry_run=False)
    before = await state(db_session)
    with pytest.raises(IndexGenerationError, match="identity/content conflict"):
        await record_validation(db_session, generation_id=generation["generation_id"], observation={**report, "vectors": []}, dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("age,expected", [(0, True), (899, True), (900, True), (901, False), (-1, False)])
async def test_database_validation_freshness_has_exact_fifteen_minute_boundary(db_session, age, expected):
    value = await db_session.scalar(sa.text("SELECT public.sclib_index_validation_fresh_v1(checked_at-make_interval(secs=>:age),checked_at) FROM (SELECT clock_timestamp() AS checked_at) t"), {"age": age})
    assert value is expected


@pytest.mark.parametrize("prefix", [b"\x7f\x80\x00\x00", b"\x7f\xc0\x00\x00", b"\x80\x00\x00\x00", None])
async def test_raw_sql_member_requires_canonical_finite_nonzero_float32_bytes(db_session, prefix):
    generation, _ = await staged(db_session)
    row, = await load_generation_members(db_session, generation_id=generation["generation_id"])
    values = {key: UUID(value) if key in {"generation_id", "evidence_revision_id", "receipt_id"} else value for key, value in row.items()}
    values["vector_bytes"] = prefix + values["vector_bytes"][4:] if prefix is not None else bytes(3072)
    with pytest.raises(DBAPIError, match="canonical_vector_required"):
        async with db_session.begin_nested():
            await db_session.execute(Base.metadata.tables["index_generation_members"].insert().values(**values))


@pytest.mark.parametrize("minutes", [-16, 1])
async def test_delayed_or_future_unrecorded_observation_cannot_be_made_fresh(db_session, minutes):
    generation, _ = await staged(db_session)
    report = await observation(db_session, generation)
    report["observed_at"] = (datetime.now(UTC) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="observation_not_fresh"):
        await record_validation(db_session, generation_id=generation["generation_id"], observation=report, dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("kind", ["paper", "accepted_work"])
async def test_raw_sql_activation_cannot_bypass_lifecycle_aba_holds(db_session, kind):
    generation, _ = await staged(db_session)
    validation = await validated(db_session, generation)
    member, = await load_generation_members(db_session, generation_id=generation["generation_id"])
    if kind == "paper":
        for status in ("corrected", "published"):
            await db_session.execute(sa.text("UPDATE papers SET status=:status WHERE id=:id"), {"status": status, "id": member["paper_id"]})
    else:
        work_id = uuid4()
        await db_session.execute(sa.insert(Work).values(id=work_id, canonical_title="Synthetic held work", publication_status="active"))
        await db_session.execute(sa.insert(PaperWorkMap).values(paper_id=member["paper_id"], work_id=work_id,
            relation_type="published_version", match_method="manual", review_status="accepted"))
        for status in ("corrected", "active"):
            await db_session.execute(sa.update(Work).where(Work.id == work_id).values(publication_status=status))
    with pytest.raises(DBAPIError, match="current_source_hold"):
        async with db_session.begin_nested():
            await db_session.execute(Base.metadata.tables["index_activation_events"].insert().values(
                id=uuid4(), logical_index="sclib-main", generation_id=UUID(generation["generation_id"]),
                validation_id=UUID(validation["validation_id"]), predecessor_id=None, event_number=1, action="promote", idempotency_key="raw-held"))
    assert await load_active_generation(db_session) is None


async def test_snapshot_byte_preflight_rejects_before_selecting_private_payloads(db_session, monkeypatch):
    _, items = await staged(db_session)
    before = await state(db_session)
    original = db_session.execute

    async def guarded(statement, *args, **kwargs):
        assert "SELECT c.id AS chunk_key" not in str(statement), "Full payload was fetched before its byte budget was admitted"
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(service, "MAX_SNAPSHOT_BYTES", 1)
    monkeypatch.setattr(db_session, "execute", guarded)
    with pytest.raises(IndexGenerationError, match="pilot scope"):
        await stage_generation(db_session, generation_id=uuid4(), items=items, resource=resource(), dry_run=False)
    assert await state(db_session) == before


async def test_two_actual_backends_cannot_both_win_the_same_activation_cas(db_session):
    logical_index = "synthetic-concurrency-" + uuid4().hex
    generation, _ = await staged(db_session, logical_index=logical_index)
    validation = await validated(db_session, generation)
    await db_session.commit()

    async def contender(key):
        async with get_session_factory()() as session:
            try:
                result = await activate_generation(session, generation_id=generation["generation_id"], validation_id=validation["validation_id"],
                                                   expected_event_id=None, idempotency_key=key, dry_run=False)
                await session.commit()
                return result
            except DBAPIError:
                await session.rollback()
                return None

    results = await asyncio.gather(contender("first"), contender("second"))
    successful = [result for result in results if result is not None]
    assert len(successful) == 1
    active = await load_active_generation(db_session, logical_index=logical_index)
    assert active["activation_event_id"] == successful[0]["activation_event_id"]
    assert await db_session.scalar(sa.text("SELECT count(*) FROM index_activation_events WHERE logical_index=:key"), {"key": logical_index}) == 1
    inspected = await service.inspect_generation(db_session, generation_id=generation["generation_id"])
    assert inspected["current_active_pin"] == active and inspected["is_current"] is True
    assert "snapshot_json" not in str(inspected) and "vector_bytes" not in str(inspected)
