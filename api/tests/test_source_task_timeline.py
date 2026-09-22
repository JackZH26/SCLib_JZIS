"""Projection readiness fencing on owned disposable PostgreSQL.

Invalidation is deliberately not a rebuild or scientific acceptance. These
tests exercise the shared fence before source reads, including a cached ORM
singleton and stale database snapshots, without any production worker.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import TimelineProjectionPoint, TimelineProjectionState, get_engine
from services.timeline_projection import PROJECTION_SCHEMA_VERSION, refresh_timeline_projection
from tests.test_timeline_projection_identity import _read, _seed


@pytest_asyncio.fixture(loop_scope="function")
async def engine():
    database = get_engine()
    try:
        yield database
    finally:
        await database.dispose()


async def _invalidate(db):
    # Match the bounded task effect: readiness only, no points or watermark.
    await db.execute(sa.text("UPDATE timeline_projection_state SET schema_version=0 WHERE id=1"))


async def _state(db):
    table = TimelineProjectionState.__table__
    return (await db.execute(sa.select(table).where(table.c.id == 1))).mappings().one()


async def _points(db, material):
    table = TimelineProjectionPoint.__table__
    return (await db.execute(sa.select(table).where(table.c.material_id == material.id)
                            .order_by(table.c.id))).mappings().all()


@pytest.mark.asyncio
async def test_refresh_lock_failure_precedes_any_read_or_write():
    class BusySession:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(str(statement))
            raise RuntimeError("synthetic busy fence")

        async def get(self, *args, **options):
            raise AssertionError("Read occurred before the fence")

    session = BusySession()
    with pytest.raises(RuntimeError, match="synthetic busy fence"):
        await refresh_timeline_projection(session)
    assert session.statements == ["SELECT public.sclib_source_task_lock_v1()"]


@pytest.mark.asyncio
async def test_core_readiness_invalidation_is_seen_in_same_session(engine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        material, _ = await _seed(db)
        await refresh_timeline_projection(db)
        loaded = await db.get(TimelineProjectionState, 1)
        before = dict(await _state(db))
        points = await _points(db, material)
        assert loaded.schema_version == PROJECTION_SCHEMA_VERSION
        assert points
        await _invalidate(db)
        # Core SQL did not synchronize the loaded ORM identity.
        assert loaded.schema_version == PROJECTION_SCHEMA_VERSION
        assert await _read(db, material) is None
        assert loaded.schema_version == 0
        assert dict(await _state(db)) == {**before, "schema_version": 0}
        assert await _points(db, material) == points
        rebuilt = await refresh_timeline_projection(db)
        assert rebuilt.full_rebuild is True


@pytest.mark.asyncio
async def test_readiness_refresh_preserves_pending_orm_invalidation(engine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        material, _ = await _seed(db)
        await refresh_timeline_projection(db)
        loaded = await db.get(TimelineProjectionState, 1)
        loaded.schema_version = 0
        assert loaded in db.dirty
        assert await _read(db, material) is None
        assert loaded.schema_version == 0
        assert (await _state(db))["schema_version"] == 0


@pytest.mark.asyncio
async def test_read_committed_refresh_reloads_cached_readiness_after_invalidation(engine):
    async with AsyncSession(engine, expire_on_commit=False) as writer:
        await _seed(writer)
        await refresh_timeline_projection(writer)
        await writer.commit()
    async with AsyncSession(engine, expire_on_commit=False) as refresher:
        assert (await refresher.execute(sa.text("SHOW transaction_isolation"))).scalar_one() == "read committed"
        cached = await refresher.get(TimelineProjectionState, 1)
        assert cached.schema_version == PROJECTION_SCHEMA_VERSION
        async with AsyncSession(engine) as invalidator:
            await _invalidate(invalidator)
            await invalidator.commit()
        assert cached.schema_version == PROJECTION_SCHEMA_VERSION
        result = await refresh_timeline_projection(refresher)
        assert result.full_rebuild is True


@pytest.mark.asyncio
async def test_busy_invalidation_lock_rejects_refresh_before_orm_read(engine, monkeypatch):
    async with AsyncSession(engine) as invalidator, AsyncSession(engine) as refresher:
        await invalidator.execute(sa.text("SELECT public.sclib_source_task_lock_v1()"))
        reads = []
        original = refresher.get

        async def observed_get(*args, **kwargs):
            reads.append(args)
            return await original(*args, **kwargs)

        monkeypatch.setattr(refresher, "get", observed_get)
        with pytest.raises(DBAPIError) as failure:
            await refresh_timeline_projection(refresher)
        assert failure.value.orig.sqlstate == "55P03"
        assert reads == []
        await refresher.rollback()


@pytest.mark.asyncio
async def test_invalidation_cannot_overtake_uncommitted_refresh(engine):
    async with AsyncSession(engine) as refresher, AsyncSession(engine) as invalidator:
        await refresh_timeline_projection(refresher)
        with pytest.raises(DBAPIError) as failure:
            await _invalidate(invalidator)
        assert failure.value.orig.sqlstate == "55P03"
        await invalidator.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
async def test_stale_snapshot_refresh_is_epoch_fenced(engine, isolation):
    async with AsyncSession(engine.execution_options(isolation_level=isolation)) as stale:
        await stale.execute(sa.text("SELECT epoch FROM source_task_epoch WHERE id=1"))
        async with AsyncSession(engine) as current:
            # No singleton is required for the statement-level fence.
            await _invalidate(current)
            await current.commit()
        with pytest.raises(DBAPIError) as failure:
            await refresh_timeline_projection(stale)
        assert failure.value.orig.sqlstate == "40001"
        await stale.rollback()
