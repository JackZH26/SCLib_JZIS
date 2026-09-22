"""Coordinator acceptance on disposable SQL; no real periodic job is invoked."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

from models.background_jobs_v1 import JOB_LOCK_KEYS
from models.db import Base, StatsCache, get_engine
from services import background_jobs as service
from services.research_release_manifest import digest

JOB = "stats_refresh"


@pytest_asyncio.fixture(loop_scope="function")
async def engine():
    database = get_engine()
    try:
        yield database
    finally:
        await database.dispose()


def test_due_cycle_uses_utc_grid_and_exact_offset_boundary():
    at = datetime(2026, 9, 8, 2, 0, tzinfo=UTC)
    assert service.due_cycle(at, 86400, 7200) == at
    assert service.due_cycle(at - timedelta(microseconds=1), 86400, 7200) == at - timedelta(days=1)
    assert service.due_cycle(at.astimezone(timezone(timedelta(hours=8))), 86400, 7200) == at
    assert service.due_cycle(at + timedelta(seconds=59, microseconds=999999), 60) == at


def test_due_cycle_rounds_pre_epoch_fraction_down_not_toward_zero():
    before = datetime(1969, 12, 31, 23, 59, 59, 500000, tzinfo=UTC)
    assert service.due_cycle(before, 1) == before.replace(microsecond=0)


@pytest.mark.parametrize("interval,offset", [(0, 0), (-1, 0), (31_622_401, 0), (True, 0),
                                            (1.0, 0), (1, -1), (1, 1), (2, 0.5), (2, True)])
def test_due_cycle_rejects_invalid_cadence(interval, offset):
    with pytest.raises(service.BackgroundJobError):
        service.due_cycle(datetime.now(UTC), interval, offset)


@pytest.mark.parametrize("now", [None, "2026-09-08", datetime(2026, 9, 8)])
def test_due_cycle_requires_an_aware_datetime(now):
    with pytest.raises(service.BackgroundJobError):
        service.due_cycle(now, 1)


@pytest.mark.parametrize("change", [
    {"job_name": "unknown"}, {"handler": None}, {"interval_seconds": 0},
    {"offset_seconds": True}, {"scheduled_for": datetime(2026, 1, 1)},
    {"scheduled_for": datetime(2026, 1, 1, 0, 0, 0, 1, tzinfo=UTC)},
    {"config": []}, {"config": {"oversized": "x" * 4097}},
    {"config": {"nonfinite": float("nan")}}, {"config": {"not_json": object()}},
    {"timeout_seconds": True}, {"timeout_seconds": 0}, {"timeout_seconds": float("nan")},
    {"timeout_seconds": 3601}, {"owner_id": "not-a-uuid"},
])
async def test_invalid_contract_is_rejected_before_database_connection(change):
    class NoConnection:
        def connect(self):
            pytest.fail("Invalid job contract attempted a database connection")

    async def unused(*_args):
        pytest.fail("Invalid job contract reached its callback")

    arguments = {"job_name": JOB, "interval_seconds": 1, "handler": unused, "engine": NoConnection(), **change}
    with pytest.raises(ValueError):
        await service.run_background_cycle(**arguments)


async def context(engine):
    cycles = Base.metadata.tables["background_job_cycles"]
    async with engine.begin() as connection:
        latest = (await connection.execute(sa.select(sa.func.max(cycles.c.scheduled_for)).where(
            cycles.c.job_name == JOB))).scalar_one()
        # Leave a missing grid point before this cycle for the superseded test.
        due = latest + timedelta(seconds=2) if latest else datetime(2001, 1, 1, tzinfo=UTC)
        now = (await connection.execute(sa.select(sa.func.clock_timestamp()))).scalar_one()
        assert due <= now and due.microsecond == 0
        key = "en03-coordinator-" + uuid4().hex
        await connection.execute(sa.insert(StatsCache).values(key=key, value={"generation": "last_good"}))
    return {"key": key, "due": due, "config": {"synthetic_stats_key": key}}


async def run(engine, fixture, handler, **changes):
    return await service.run_background_cycle(JOB, interval_seconds=1, handler=handler, engine=engine,
        **{"scheduled_for": fixture["due"], "config": fixture["config"], **changes})


async def write_effect(db, fixture, cycle_id, generation="fresh"):
    await db.execute(sa.update(StatsCache).where(StatsCache.key == fixture["key"]).values(
        value={"generation": generation, "cycle_id": str(cycle_id)}))


def good_handler(fixture):
    async def good(db, scheduled_for, cycle_id):
        await write_effect(db, fixture, cycle_id)
        return {"synthetic": True, "scheduled_for": scheduled_for.isoformat(), "rows_updated": 1}
    return good


async def value(engine, fixture):
    async with engine.connect() as connection:
        return (await connection.execute(sa.select(StatsCache.value).where(StatsCache.key == fixture["key"]))).scalar_one()


async def row(engine, cycle_id):
    table = Base.metadata.tables["background_job_cycles"]
    async with engine.connect() as connection:
        return dict((await connection.execute(sa.select(table).where(table.c.id == UUID(cycle_id)))).mappings().one())


async def repair(engine, fixture, monkeypatch, *, handler=None, scheduled_for=None):
    # This is a local retry-clock fixture, not a claim that 31 seconds elapsed.
    original = service._clock

    async def after_retry(connection):
        return await original(connection) + timedelta(seconds=31)

    with monkeypatch.context() as patch:
        patch.setattr(service, "_clock", after_retry)
        return await run(engine, fixture, handler or good_handler(fixture),
                         scheduled_for=scheduled_for or fixture["due"])


async def test_success_is_durable_replay_is_noop_and_missing_older_cycle_is_superseded(engine):
    fixture = await context(engine)
    done = await run(engine, fixture, good_handler(fixture))
    assert done["status"] == "succeeded" and done["attempts"] == 1
    assert done["completion_scope"] == "database_effects_only"
    assert await value(engine, fixture) == {"generation": "fresh", "cycle_id": done["cycle_id"]}
    stored = await row(engine, done["cycle_id"])

    async def forbidden(*_args):
        pytest.fail("A replay/superseded cycle invoked its callback")

    again = await run(engine, fixture, forbidden)
    assert again["status"] == "already_succeeded" and again["cycle_id"] == done["cycle_id"]
    assert await row(engine, done["cycle_id"]) == stored
    old = await run(engine, fixture, forbidden, scheduled_for=fixture["due"] - timedelta(seconds=1))
    assert old["status"] == "superseded" and old["cycle_id"] is None
    assert await row(engine, done["cycle_id"]) == stored


@pytest.mark.parametrize("failure", ["exception", "outer_commit", "outer_rollback", "oversized", "non_object", "non_json"])
async def test_callback_failure_keeps_last_good_cache_and_recovers_same_cycle(engine, monkeypatch, failure):
    fixture = await context(engine)

    async def broken(db, scheduled_for, cycle_id):
        await write_effect(db, fixture, cycle_id, "must_rollback")
        if failure == "exception":
            raise RuntimeError("PRIVATE CALLBACK CONTENT")
        if failure == "outer_commit":
            await db.commit()
        if failure == "outer_rollback":
            await db.rollback()
        if failure == "oversized":
            return {"value": "x" * (service.MAX_RESULT_BYTES + 1)}
        if failure == "non_object":
            return ["invalid"]
        if failure == "non_json":
            return {"value": float("nan")}
        return {}

    failed = await run(engine, fixture, broken)
    try:
        assert failed["status"] == "failed" and failed["error_code"] == "execution_failed"
        assert failed["result"] == {} and "PRIVATE" not in repr(failed)
        assert await value(engine, fixture) == {"generation": "last_good"}
        previous = await row(engine, failed["cycle_id"])
        waiting = await run(engine, fixture, good_handler(fixture))
        assert waiting["status"] == "retry_wait" and waiting["attempts"] == 1
        assert await row(engine, failed["cycle_id"]) == previous
        assert await value(engine, fixture) == {"generation": "last_good"}
    finally:
        fixed = await repair(engine, fixture, monkeypatch)
    assert fixed["status"] == "succeeded" and fixed["attempts"] == 2 and fixed["recovered"] is True
    assert fixed["cycle_id"] == failed["cycle_id"]
    assert await value(engine, fixture) == {"generation": "fresh", "cycle_id": failed["cycle_id"]}


async def test_pending_cycle_keeps_original_due_and_configuration_conflict_has_no_effect(engine, monkeypatch):
    fixture = await context(engine)

    async def broken(*_args):
        raise RuntimeError("Synthetic failure before effect")

    failed = await run(engine, fixture, broken)
    original = await row(engine, failed["cycle_id"])
    later = fixture["due"] + timedelta(seconds=5)
    try:
        conflict = await run(engine, fixture, good_handler(fixture), scheduled_for=later,
                             config={"different": True})
        assert conflict["status"] == "configuration_conflict"
        assert await row(engine, failed["cycle_id"]) == original
        assert await value(engine, fixture) == {"generation": "last_good"}
    finally:
        fixed = await repair(engine, fixture, monkeypatch, scheduled_for=later)
    assert fixed["status"] == "succeeded" and fixed["cycle_id"] == failed["cycle_id"]
    assert datetime.fromisoformat(fixed["scheduled_for"]) == fixture["due"]
    assert datetime.fromisoformat(fixed["result"]["scheduled_for"]) == fixture["due"]
    # Recovery handles one old cycle, not both it and the newly due cycle.
    table = Base.metadata.tables["background_job_cycles"]
    async with engine.connect() as connection:
        assert (await connection.execute(sa.select(table.c.id).where(
            table.c.job_name == JOB, table.c.scheduled_for == later))).first() is None


async def test_future_cycle_rejected_without_claim_or_cache_mutation(engine):
    fixture = await context(engine)
    future = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    with pytest.raises(service.BackgroundJobError, match="future"):
        await run(engine, fixture, good_handler(fixture), scheduled_for=future)
    assert await value(engine, fixture) == {"generation": "last_good"}
    table = Base.metadata.tables["background_job_cycles"]
    async with engine.connect() as connection:
        assert (await connection.execute(sa.select(table.c.id).where(
            table.c.job_name == JOB, table.c.scheduled_for == future))).first() is None


async def test_inspection_distinguishes_live_lock_from_abandoned_running_claim(engine):
    fixture = await context(engine)
    owner = uuid4()
    schedule_hash = digest({"version": service.POLICY_VERSION, "job_name": JOB,
        "interval_seconds": 1, "offset_seconds": 0, "config": fixture["config"]})
    claimed = None
    try:
        async with engine.connect() as locker:
            assert await locker.scalar(sa.text("SELECT pg_try_advisory_lock(:key)"),
                                       {"key": JOB_LOCK_KEYS[JOB]}) is True
            await locker.commit()
            async with locker.begin():
                claimed, outcome, recovered = await service._select_cycle(
                    locker, JOB, fixture["due"], schedule_hash, owner)
                assert outcome is None and recovered is False
            async with engine.connect() as reader:
                report = await service.inspect_background_jobs(reader)
            current = next(item for item in report["jobs"] if item["job_name"] == JOB)
            assert current["active_owner_id"] == str(owner)
            assert current["oldest_unfinished"]["status"] == "running"
            assert len(current["recent_cycles"]) <= 20
        # NullPool physically closed the connection; the durable claim remains
        # running, but it must no longer be shown as actively owned.
        async with engine.connect() as reader:
            report = await service.inspect_background_jobs(reader)
        abandoned = next(item for item in report["jobs"] if item["job_name"] == JOB)
        assert abandoned["active_owner_id"] is None
        assert abandoned["oldest_unfinished"]["status"] == "running"
        assert await value(engine, fixture) == {"generation": "last_good"}
    finally:
        if claimed is not None:
            finished = await run(engine, fixture, good_handler(fixture))
            assert finished["status"] == "succeeded" and finished["recovered"] is True
