"""Real pooled-connection uncertainty and atomic callback recovery regressions."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from models.background_jobs_v1 import JOB_LOCK_KEYS
from models.db import AuditReport, Base, get_engine
from services import background_jobs as service

_JOB = "formula_audit"
_CONFIG = {"synthetic_recovery_contract": "background-recovery/1"}


@pytest_asyncio.fixture(loop_scope="function")
async def pooled_engine():
    # Deliberately use a retained pool, not NullPool: leaked session locks must
    # be detected before the pool closes their physical backend connections.
    engine = create_async_engine(get_engine().url, pool_size=1, max_overflow=1)
    try:
        yield engine
    finally:
        async with engine.connect() as connection:
            await connection.execute(sa.text("SELECT pg_advisory_unlock_all()"))
            await connection.rollback()
        await engine.dispose()


async def active_locks(engine, *, pid=None):
    async with engine.connect() as connection:
        return (await connection.execute(sa.text("""SELECT pid FROM pg_locks WHERE locktype='advisory'
            AND classid=0 AND objid=:key AND objsubid=1 AND granted AND mode='ExclusiveLock'
            AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
            AND (:pid IS NULL OR pid=:pid)""").bindparams(sa.bindparam("pid", type_=sa.Integer)),
            {"key": JOB_LOCK_KEYS[_JOB], "pid": pid})).scalars().all()


async def next_due(engine):
    table = Base.metadata.tables["background_job_cycles"]
    async with engine.connect() as connection:
        latest = await connection.scalar(sa.select(sa.func.max(table.c.scheduled_for)).where(table.c.job_name == _JOB))
    due = latest + timedelta(seconds=1) if latest else datetime(2000, 1, 1, tzinfo=UTC)
    for _ in range(80):
        async with engine.connect() as connection:
            now = await connection.scalar(sa.select(sa.func.clock_timestamp()))
        if due <= now:
            return due
        await asyncio.sleep(0.05)
    pytest.fail("Synthetic recovery cycle would require a future schedule")


async def reports(engine, rule):
    async with engine.connect() as connection:
        return (await connection.execute(sa.select(AuditReport.__table__).where(
            AuditReport.rule_name == rule))).mappings().all()


async def cycle(engine, identifier):
    table = Base.metadata.tables["background_job_cycles"]
    async with engine.connect() as connection:
        return (await connection.execute(sa.select(table).where(table.c.id == UUID(identifier)))).mappings().one()


def reporter(rule):
    async def effect(session, scheduled_for, cycle_id):
        await session.execute(sa.insert(AuditReport).values(started_at=scheduled_for,
            completed_at=sa.func.clock_timestamp(), rule_name=rule, severity="info", rows_flagged=1,
            sample_ids=[str(cycle_id)], suggested_fixes=[{"synthetic": True}]))
        return {"audit_reports_created": 1}
    return effect


async def test_uncertain_acquisition_does_not_return_lock_holding_backend_to_pool(pooled_engine):
    async with pooled_engine.connect() as connection:
        original_pid = await connection.scalar(sa.text("SELECT pg_backend_pid()"))
    injected = False

    def after_lock(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal injected
        if not injected and statement.startswith("SELECT pg_try_advisory_lock("):
            injected = True
            # The database already granted the session lock, but the caller
            # has not consumed the result and assigned its local locked flag.
            raise RuntimeError("Synthetic post-acquisition response failure")

    sa.event.listen(pooled_engine.sync_engine, "after_cursor_execute", after_lock)
    handler = AsyncMock(return_value={})
    try:
        with pytest.raises(RuntimeError, match="post-acquisition"):
            await service.run_background_cycle(_JOB, interval_seconds=1, handler=handler, engine=pooled_engine)
    finally:
        sa.event.remove(pooled_engine.sync_engine, "after_cursor_execute", after_lock)
    handler.assert_not_awaited()
    assert injected and await active_locks(pooled_engine, pid=original_pid) == []


async def test_unlock_failure_invalidates_backend_after_durable_success(pooled_engine):
    rule = "en03-unlock:" + uuid4().hex
    due = await next_due(pooled_engine)
    injected = False

    def before_unlock(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal injected
        if not injected and statement.startswith("SELECT pg_advisory_unlock("):
            injected = True
            # Leave the granted lock in place. Cleanup must physically discard
            # the connection instead of handing the locked session to the pool.
            raise RuntimeError("Synthetic unlock request failure")

    sa.event.listen(pooled_engine.sync_engine, "before_cursor_execute", before_unlock)
    try:
        result = await service.run_background_cycle(_JOB, interval_seconds=1, handler=reporter(rule),
            engine=pooled_engine, scheduled_for=due, config=_CONFIG)
    finally:
        sa.event.remove(pooled_engine.sync_engine, "before_cursor_execute", before_unlock)
    assert result["status"] == "succeeded" and injected
    assert len(await reports(pooled_engine, rule)) == 1
    assert (await cycle(pooled_engine, result["cycle_id"]))["status"] == "succeeded"
    assert await active_locks(pooled_engine) == []


async def test_lost_application_ack_after_commit_reconciles_success_without_reexecution(pooled_engine, monkeypatch):
    rule = "en03-commit-ack:" + uuid4().hex
    due = await next_due(pooled_engine)
    original = service._execute
    executions = 0

    async def lost_ack(*args):
        nonlocal executions
        executions += 1
        await original(*args)
        raise RuntimeError("Synthetic application failure after actual commit")

    monkeypatch.setattr(service, "_execute", lost_ack)
    arguments = dict(interval_seconds=1, handler=reporter(rule), engine=pooled_engine,
                     scheduled_for=due, config=_CONFIG)
    result = await service.run_background_cycle(_JOB, **arguments)
    assert result["status"] == "succeeded" and executions == 1
    assert len(await reports(pooled_engine, rule)) == 1
    replay = await service.run_background_cycle(_JOB, **arguments)
    assert replay["status"] == "already_succeeded" and replay["cycle_id"] == result["cycle_id"]
    assert executions == 1 and len(await reports(pooled_engine, rule)) == 1
    assert await active_locks(pooled_engine) == []


@pytest.mark.parametrize("operation", ["commit", "rollback"])
async def test_callback_cannot_end_outer_transaction_and_recovery_keeps_one_effect(pooled_engine, monkeypatch, operation):
    rule = "en03-callback:" + uuid4().hex
    due = await next_due(pooled_engine)
    good = reporter(rule)

    async def invalid_callback(session, scheduled_for, cycle_id):
        result = await good(session, scheduled_for, cycle_id)
        await getattr(session, operation)()
        return result

    arguments = dict(interval_seconds=1, engine=pooled_engine, scheduled_for=due, config=_CONFIG)
    failed = await service.run_background_cycle(_JOB, handler=invalid_callback, **arguments)
    assert failed["status"] == "failed" and failed["error_code"] == "execution_failed"
    assert await reports(pooled_engine, rule) == []
    waiting = await service.run_background_cycle(_JOB, handler=good, **arguments)
    assert waiting["status"] == "retry_wait"
    assert await reports(pooled_engine, rule) == []
    original_clock = service._clock

    async def retry_clock(connection):
        return await original_clock(connection) + timedelta(seconds=40)

    monkeypatch.setattr(service, "_clock", retry_clock)
    recovered = await service.run_background_cycle(_JOB, handler=good, **arguments)
    assert recovered["status"] == "succeeded" and recovered["attempts"] == 2 and recovered["recovered"] is True
    assert recovered["cycle_id"] == failed["cycle_id"]
    assert len(await reports(pooled_engine, rule)) == 1
    assert await active_locks(pooled_engine) == []


async def test_nested_callback_savepoint_commit_is_not_an_outer_commit(pooled_engine):
    rule = "en03-savepoint:" + uuid4().hex
    due = await next_due(pooled_engine)
    good = reporter(rule)

    async def nested_callback(session, scheduled_for, cycle_id):
        async with session.begin_nested():
            return await good(session, scheduled_for, cycle_id)

    result = await service.run_background_cycle(_JOB, interval_seconds=1, handler=nested_callback,
        engine=pooled_engine, scheduled_for=due, config=_CONFIG)
    assert result["status"] == "succeeded" and len(await reports(pooled_engine, rule)) == 1
    assert await active_locks(pooled_engine) == []
