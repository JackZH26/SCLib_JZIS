"""Operational cycle state and backend-lock guards on disposable PostgreSQL."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from models.background_jobs_v1 import JOB_LOCK_KEYS, TABLE_NAME
from models.db import Base, get_engine
from tests.test_research_freeze import add

_START = datetime(2026, 9, 7, tzinfo=UTC)


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    engine = get_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                yield session
            finally:
                await session.rollback()
                await session.execute(sa.text("SELECT pg_advisory_unlock_all()"))
                await session.rollback()
    finally:
        await engine.dispose()


async def lock(db, job="stats_refresh"):
    assert await db.scalar(sa.text("SELECT pg_try_advisory_lock(:key)"), {"key": JOB_LOCK_KEYS[job]}) is True


async def values(db, job="stats_refresh"):
    return dict(job_name=job, scheduled_for=_START, schedule_sha256="a" * 64,
                status="running", owner_id=uuid4(), backend_pid=await db.scalar(sa.text("SELECT pg_backend_pid()")),
                attempts=1, started_at=_START)


async def claim(db, job="stats_refresh"):
    await lock(db, job)
    return await add(db, TABLE_NAME, **await values(db, job))


async def update(db, row, **changes):
    table = Base.metadata.tables[TABLE_NAME]
    return (await db.execute(table.update().where(table.c.id == row["id"]).values(**changes).returning(table))).mappings().one()


async def complete(db, row, *, success=True):
    return await update(db, row, status="succeeded" if success else "failed",
        completed_at=row["started_at"] + timedelta(seconds=1), duration_ms=1000,
        error_code=None if success else "execution_failed",
        next_retry_at=None if success else row["started_at"] + timedelta(seconds=30),
        result_json={"rows": 5} if success else {})


@pytest.mark.parametrize("job", JOB_LOCK_KEYS)
async def test_each_job_requires_its_exact_current_backend_lock(db_session, job):
    payload = await values(db_session, job)
    with pytest.raises(DBAPIError, match="current_backend_lock_required"):
        async with db_session.begin_nested():
            await add(db_session, TABLE_NAME, **payload)
    await lock(db_session, job)
    row = await add(db_session, TABLE_NAME, **payload)
    assert row["attempts"] == 1 and row["result_json"] == {}
    done = await complete(db_session, row)
    assert done["status"] == "succeeded" and done["result_json"] == {"rows": 5}


@pytest.mark.parametrize("mode", ["different_job", "shared", "two_integer_namespace"])
async def test_nearby_or_shared_locks_cannot_claim_job_authority(db_session, mode):
    if mode == "different_job":
        await lock(db_session, "nightly_audit")
    elif mode == "shared":
        assert await db_session.scalar(sa.text("SELECT pg_try_advisory_lock_shared(:key)"),
                                       {"key": JOB_LOCK_KEYS["stats_refresh"]}) is True
    else:
        assert await db_session.scalar(sa.text("SELECT pg_try_advisory_lock(0,:key)"),
                                       {"key": JOB_LOCK_KEYS["stats_refresh"]}) is True
    with pytest.raises(DBAPIError, match="current_backend_lock_required"):
        async with db_session.begin_nested():
            await add(db_session, TABLE_NAME, **await values(db_session))


@pytest.mark.parametrize("field,value", [("status", "succeeded"), ("attempts", 2), ("attempts", 0),
    ("backend_pid", 1), ("schedule_sha256", "A" * 64), ("result_json", []),
    ("result_json", {"oversized": "x" * 16384}), ("completed_at", _START),
    ("error_code", "raw_exception_text"), ("started_at", _START - timedelta(seconds=1))])
async def test_invalid_initial_cycle_shapes_rejected(db_session, field, value):
    await lock(db_session)
    payload = await values(db_session)
    payload[field] = value
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await add(db_session, TABLE_NAME, **payload)


async def test_nonfinite_cycle_timestamp_rejected(db_session):
    row = await claim(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("UPDATE background_job_cycles SET status='succeeded', "
                "completed_at='infinity',duration_ms=1 WHERE id=:id"), {"id": row["id"]})


async def test_schedule_identity_is_unique_independent_of_owner(db_session):
    await claim(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await add(db_session, TABLE_NAME, **await values(db_session))


@pytest.mark.parametrize("field,value", [("id", uuid4()), ("job_name", "timeline_projection"),
    ("schedule_sha256", "b" * 64), ("scheduled_for", _START - timedelta(seconds=1))])
async def test_cycle_identity_cannot_change(db_session, field, value):
    row = await claim(db_session)
    await lock(db_session, "timeline_projection")
    with pytest.raises(DBAPIError, match="cycle_identity_immutable"):
        async with db_session.begin_nested():
            await update(db_session, row, **{field: value})


@pytest.mark.parametrize("field,value", [("attempts", 2), ("owner_id", uuid4()),
    ("backend_pid", 1), ("started_at", _START - timedelta(seconds=1))])
async def test_completion_must_belong_to_exact_attempt_owner(db_session, field, value):
    row = await claim(db_session)
    with pytest.raises(DBAPIError, match="exact_owner_completion_required"):
        async with db_session.begin_nested():
            await update(db_session, row, status="succeeded", completed_at=_START + timedelta(seconds=1),
                         duration_ms=1000, **{field: value})


async def test_failed_attempt_retries_once_with_new_owner_and_cleared_terminal_fields(db_session):
    row = await complete(db_session, await claim(db_session), success=False)
    owner = uuid4()
    retry = await update(db_session, row, status="running", attempts=2, owner_id=owner,
        started_at=row["next_retry_at"], completed_at=None, duration_ms=None, next_retry_at=None,
        error_code=None, result_json={})
    assert retry["attempts"] == 2 and retry["owner_id"] == owner
    assert (await complete(db_session, retry))["status"] == "succeeded"


@pytest.mark.parametrize("mode", ["early", "skipped_attempt", "same_attempt", "uncleared_failure"])
async def test_retry_cannot_skip_attempt_or_recorded_backoff(db_session, mode):
    row = await complete(db_session, await claim(db_session), success=False)
    changes = dict(status="running", attempts=2, owner_id=uuid4(), started_at=row["next_retry_at"],
                   completed_at=None, duration_ms=None, next_retry_at=None, error_code=None, result_json={})
    if mode == "early":
        changes["started_at"] -= timedelta(seconds=1)
    elif mode == "skipped_attempt":
        changes["attempts"] = 3
    elif mode == "same_attempt":
        changes["attempts"] = 1
    else:
        changes["error_code"] = "execution_failed"
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await update(db_session, row, **changes)


async def test_abandoned_running_claim_requires_increment_even_if_owner_is_same(db_session):
    row = await claim(db_session)
    with pytest.raises(DBAPIError, match="exact_retry_claim_required"):
        async with db_session.begin_nested():
            await update(db_session, row, started_at=_START + timedelta(seconds=30))
    row = await update(db_session, row, attempts=2, started_at=_START + timedelta(seconds=30))
    assert row["attempts"] == 2


async def test_succeeded_cycle_is_immutable_but_lock_owned_noop_is_allowed(db_session):
    row = await complete(db_session, await claim(db_session))
    assert dict(await update(db_session, row, result_json=row["result_json"])) == dict(row)
    with pytest.raises(DBAPIError, match="success_immutable"):
        async with db_session.begin_nested():
            await update(db_session, row, result_json={"rows": 999})
    with pytest.raises(DBAPIError, match="success_immutable"):
        async with db_session.begin_nested():
            await update(db_session, row, status="running", attempts=2)


@pytest.mark.parametrize("operation", ["delete", "truncate"])
async def test_cycle_history_cannot_be_removed(db_session, operation):
    row = await claim(db_session)
    statement = "DELETE FROM background_job_cycles WHERE id=:id" if operation == "delete" else "TRUNCATE background_job_cycles"
    with pytest.raises(DBAPIError, match="history cannot be deleted"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(statement), {"id": row["id"]})


async def test_completion_and_effect_can_roll_back_together(db_session):
    row = await claim(db_session)
    savepoint = await db_session.begin_nested()
    done = await complete(db_session, row)
    assert done["status"] == "succeeded"
    await savepoint.rollback()
    table = Base.metadata.tables[TABLE_NAME]
    actual = (await db_session.execute(sa.select(table).where(table.c.id == row["id"]))).mappings().one()
    assert dict(actual) == dict(row)


async def test_session_lock_survives_claim_commit_and_releases_to_new_backend(db_session):
    engine = get_engine()
    # A generic engine-bound Session may check out a different pooled backend
    # after commit. The cycle protocol must hold an explicit physical connection.
    async with engine.connect() as first, engine.connect() as second:
        async with AsyncSession(first, expire_on_commit=False) as owner, AsyncSession(second, expire_on_commit=False) as contender:
            try:
                payload = await values(owner)
                # This receipt is intentionally committed and retained for
                # later tests. Keep its schedule on an exact, safely past UTC
                # boundary so it cannot push coordinator replay fixtures into
                # a fractional or not-yet-due cycle.
                payload["scheduled_for"] = datetime(2000, 1, 1, tzinfo=UTC)
                payload["started_at"] = datetime.now(UTC)
                await lock(owner)
                row = await add(owner, TABLE_NAME, **payload)
                await owner.commit()
                assert await owner.scalar(sa.text("SELECT public.sclib_background_job_has_lock_v1('stats_refresh')")) is True
                assert await contender.scalar(sa.text("SELECT pg_try_advisory_lock(:key)"), {"key": JOB_LOCK_KEYS["stats_refresh"]}) is False
                await owner.execute(sa.text("SELECT pg_advisory_unlock(:key)"), {"key": JOB_LOCK_KEYS["stats_refresh"]})
                assert await contender.scalar(sa.text("SELECT pg_try_advisory_lock(:key)"), {"key": JOB_LOCK_KEYS["stats_refresh"]}) is True
                other_pid = await contender.scalar(sa.text("SELECT pg_backend_pid()"))
                with pytest.raises(DBAPIError, match="exact_owner_completion_required"):
                    async with contender.begin_nested():
                        await complete(contender, row)
                retry = await update(contender, row, attempts=2, owner_id=uuid4(), backend_pid=other_pid,
                                     started_at=datetime.now(UTC))
                assert retry["backend_pid"] != row["backend_pid"]
                assert (await complete(contender, retry))["status"] == "succeeded"
                await contender.commit()
            finally:
                for session in (owner, contender):
                    await session.rollback()
                    await session.execute(sa.text("SELECT pg_advisory_unlock_all()"))
                    await session.rollback()
