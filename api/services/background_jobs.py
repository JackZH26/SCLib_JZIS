"""Cross-process, transaction-owned coordination for the five existing jobs.

A dedicated PostgreSQL session lock spans the committed claim and the atomic
work/result transaction. Connection loss releases ownership; a later invocation
recovers the same unfinished cycle. No TTL lease can expire under a live writer.
Callbacks are trusted SQL-only application code, not user-supplied workflows.
"""
from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from models.background_jobs_v1 import JOB_LOCK_KEYS
from models.db import Base, get_engine
from services.metrics import BACKGROUND_DURATION, BACKGROUND_RESULTS
from services.research_release_manifest import canonical, digest

POLICY_VERSION = "background-cycle/1.0.0"
MAX_RESULT_BYTES = 16 * 1024


class BackgroundJobError(ValueError):
    """An internal job contract is invalid; never contains source or DSN text."""


def _table():
    return Base.metadata.tables["background_job_cycles"]


def due_cycle(now, interval_seconds, offset_seconds=0):
    if (type(interval_seconds) is not int or not 1 <= interval_seconds <= 31_622_400
            or type(offset_seconds) is not int or not 0 <= offset_seconds < interval_seconds):
        raise BackgroundJobError("Invalid background job cadence")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise BackgroundJobError("An explicit timezone-aware job time is required")
    stamp = math.floor(now.timestamp())
    return datetime.fromtimestamp(((stamp - offset_seconds) // interval_seconds) * interval_seconds + offset_seconds, UTC)


def _summary(row, status=None, *, recovered=False):
    return {"status": status or row["status"], "cycle_id": str(row["id"]),
            "scheduled_for": row["scheduled_for"].isoformat(), "attempts": row["attempts"],
            "recovered": recovered, "result": row["result_json"],
            "error_code": row["error_code"],
            "next_retry_at": row["next_retry_at"].isoformat() if row["next_retry_at"] else None,
            "completion_scope": "database_effects_only"}


async def _clock(connection):
    return (await connection.execute(sa.text("SELECT clock_timestamp()"))).scalar_one()


async def _select_cycle(connection, job_name, due, schedule_hash, owner):
    table = _table()
    # Never overtake a crashed/failed earlier cycle. A changed schedule cannot
    # silently reinterpret its retained hash: an operator must restore/reconcile
    # the original configuration before delivery continues.
    pending = (await connection.execute(sa.select(table).where(table.c.job_name == job_name,
        table.c.status != "succeeded", table.c.scheduled_for <= due)
        .order_by(table.c.scheduled_for).limit(1))).mappings().one_or_none()
    row = pending or (await connection.execute(sa.select(table).where(
        table.c.job_name == job_name, table.c.scheduled_for == due))).mappings().one_or_none()
    now = await _clock(connection)
    if row is not None:
        if row["schedule_sha256"] != schedule_hash:
            return row, "configuration_conflict", False
        if row["status"] == "succeeded":
            return row, "already_succeeded", False
        if row["status"] == "failed" and row["next_retry_at"] > now:
            return row, "retry_wait", True
    elif (await connection.execute(sa.select(table.c.id).where(table.c.job_name == job_name,
            table.c.status == "succeeded", table.c.scheduled_for > due).limit(1))).first():
        # Explicit delayed/out-of-order invocations cannot overwrite newer
        # committed projections. No fabricated old success row is inserted.
        return None, "superseded", False
    pid = (await connection.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one()
    values = dict(status="running", owner_id=owner, backend_pid=pid, started_at=now,
                  completed_at=None, duration_ms=None, next_retry_at=None, error_code=None, result_json={})
    if row is None:
        statement = table.insert().values(job_name=job_name, scheduled_for=due,
            schedule_sha256=schedule_hash, attempts=1, **values)
    else:
        statement = table.update().where(table.c.id == row["id"]).values(attempts=row["attempts"] + 1, **values)
    claimed = (await connection.execute(statement.returning(table))).mappings().one()
    return claimed, None, row is not None


async def _finish(db, claimed, *, result=None, error_code=None):
    table = _table()
    now = await _clock(db)
    values = {"status": "failed" if error_code else "succeeded", "completed_at": now,
              "duration_ms": max(0, int((now - claimed["started_at"]).total_seconds() * 1000)),
              "error_code": error_code, "result_json": result or {}, "next_retry_at": None}
    if error_code:
        values["next_retry_at"] = now + timedelta(seconds=min(300, 30 * 2 ** min(claimed["attempts"] - 1, 4)))
    row = (await db.execute(table.update().where(table.c.id == claimed["id"],
        table.c.owner_id == claimed["owner_id"], table.c.attempts == claimed["attempts"], table.c.status == "running")
        .values(**values).returning(table))).mappings().one_or_none()
    if row is None:
        raise BackgroundJobError("Background cycle ownership changed")
    return row


async def _execute(connection, claimed, handler, timeout_seconds):
    async with AsyncSession(bind=connection, expire_on_commit=False) as session:
        async with session.begin():
            await session.execute(sa.text("SET LOCAL statement_timeout = '60000ms'"))
            def no_callback_commit(sync_session):
                if not sync_session.in_nested_transaction():
                    raise BackgroundJobError("A background callback cannot commit its outer transaction")
            sa.event.listen(session.sync_session, "before_commit", no_callback_commit)
            try:
                async with asyncio.timeout(timeout_seconds):
                    result = await handler(session, claimed["scheduled_for"], claimed["id"])
                    if type(result) is not dict or len(canonical(result)) > MAX_RESULT_BYTES:
                        raise BackgroundJobError("A bounded object job result is required")
            finally:
                sa.event.remove(session.sync_session, "before_commit", no_callback_commit)
            if not session.in_transaction():
                raise BackgroundJobError("A background callback ended its outer transaction")
            return await _finish(session, claimed, result=result)


async def run_background_cycle(job_name, *, interval_seconds, handler, offset_seconds=0,
        config=None, owner_id=None, engine=None, scheduled_for=None, timeout_seconds=900):
    """Run/recover at most one due cycle, returning only after durable commit.

The optional exact past scheduled_for is for a controlled replay, not a future
schedule. Replays cannot overtake an unfinished cycle or regress a newer success.
Database/commit-outcome uncertainty escapes for recovery through the same cycle.
External cache invalidation is deliberately a separate idempotent operation.
"""
    if job_name not in JOB_LOCK_KEYS or not callable(handler):
        raise BackgroundJobError("Unsupported background job")
    due_cycle(datetime.now(UTC), interval_seconds, offset_seconds)
    if type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= 3600:
        raise BackgroundJobError("Invalid background job timeout")
    if scheduled_for is not None:
        aligned = due_cycle(scheduled_for, interval_seconds, offset_seconds)
        if scheduled_for.astimezone(UTC) != aligned:
            raise BackgroundJobError("A replay must name an exact cadence boundary")
    config = {} if config is None else config
    if type(config) is not dict or len(canonical(config)) > 4096:
        raise BackgroundJobError("A bounded job configuration is required")
    schedule_hash = digest({"version": POLICY_VERSION, "job_name": job_name,
        "interval_seconds": interval_seconds, "offset_seconds": offset_seconds, "config": config})
    owner = uuid4() if owner_id is None else UUID(str(owner_id))
    database = engine if engine is not None else get_engine()
    lock_key = JOB_LOCK_KEYS[job_name]
    async with database.connect() as connection:
        locked = False
        lock_confirmed = False
        try:
            locked = bool((await connection.execute(sa.text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key})).scalar_one())
            lock_confirmed = True
            await connection.commit()
            if not locked:
                BACKGROUND_RESULTS.labels(job_name, "busy").inc()
                return {"status": "busy", "cycle_id": None, "result": {}, "completion_scope": "database_effects_only"}
            async with connection.begin():
                now = await _clock(connection)
                due = scheduled_for.astimezone(UTC) if scheduled_for is not None else due_cycle(now, interval_seconds, offset_seconds)
                if due > now:
                    raise BackgroundJobError("A future background cycle cannot execute")
                claimed, outcome, recovered = await _select_cycle(connection, job_name, due, schedule_hash, owner)
            if outcome:
                BACKGROUND_RESULTS.labels(job_name, outcome).inc()
                return (_summary(claimed, outcome, recovered=recovered) if claimed else
                        {"status": outcome, "cycle_id": None, "result": {}, "completion_scope": "database_effects_only"})
            try:
                completed = await _execute(connection, claimed, handler, timeout_seconds)
            except (Exception, asyncio.CancelledError) as exc:
                # If COMMIT outcome/connection state is unknown, do not issue
                # another effect or guess a failed result. Next invocation must
                # inspect the same durable cycle under a new ownership lock.
                await connection.rollback()
                if connection.invalidated:
                    raise
                async with connection.begin():
                    table = _table()
                    current = (await connection.execute(sa.select(table).where(table.c.id == claimed["id"]))).mappings().one()
                    if current["status"] == "succeeded":
                        completed = current
                    else:
                        code = ("cancelled" if isinstance(exc, asyncio.CancelledError) else
                                "timeout" if isinstance(exc, TimeoutError) else "execution_failed")
                        completed = await _finish(connection, claimed, error_code=code)
                if isinstance(exc, asyncio.CancelledError):
                    raise
            BACKGROUND_RESULTS.labels(job_name, completed["status"]).inc()
            BACKGROUND_DURATION.labels(job_name, completed["status"]).observe(completed["duration_ms"] / 1000)
            return _summary(completed, recovered=recovered)
        finally:
            if not lock_confirmed:
                # The backend may have acquired the session lock even when
                # its result never reached Python. Transaction rollback alone
                # does not release it: never return this connection to a pool.
                await connection.invalidate()
            elif locked:
                # Session locks must NEVER be returned to a connection pool.
                # On failed cleanup, invalidate the physical connection instead.
                try:
                    await connection.rollback()
                    released = (await connection.execute(sa.text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})).scalar_one()
                    if released is not True:
                        raise BackgroundJobError("Background ownership lock unavailable")
                    await connection.commit()
                except BaseException:
                    await connection.invalidate()


async def inspect_background_jobs(db):
    """Bounded operational status; owner is active only if its DB lock is observed."""
    table = _table()
    result = []
    for job_name, lock_key in JOB_LOCK_KEYS.items():
        rows = (await db.execute(sa.select(table).where(table.c.job_name == job_name)
            .order_by(table.c.scheduled_for.desc()).limit(20))).mappings().all()
        last_success = (await db.execute(sa.select(table).where(table.c.job_name == job_name,
            table.c.status == "succeeded").order_by(table.c.scheduled_for.desc()).limit(1))).mappings().one_or_none()
        pending = (await db.execute(sa.select(table).where(table.c.job_name == job_name,
            table.c.status != "succeeded").order_by(table.c.scheduled_for).limit(1))).mappings().one_or_none()
        active = None
        if pending and pending["status"] == "running":
            held = (await db.execute(sa.text("""SELECT EXISTS(SELECT 1 FROM pg_locks
                WHERE locktype='advisory' AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
                AND classid=0 AND objid=:key AND objsubid=1 AND pid=:pid AND granted AND mode='ExclusiveLock')"""),
                {"key": lock_key, "pid": pending["backend_pid"]})).scalar_one()
            if held:
                active = str(pending["owner_id"])
        def public_row(row):
            if row is None:
                return None
            return {**_summary(row), "started_at": row["started_at"].isoformat(),
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                "duration_ms": row["duration_ms"]}
        result.append({"job_name": job_name, "active_owner_id": active,
            "lock_observation": "current_query_only", "last_success": public_row(last_success),
            "oldest_unfinished": public_row(pending), "recent_cycles": [public_row(row) for row in rows]})
    return {"version": POLICY_VERSION, "jobs": result, "scope": "database_cycles_not_external_cache_delivery"}
