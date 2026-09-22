"""Actual coordinated refresh failure preserves the last committed projection."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, TimelineProjectionPoint, TimelineProjectionState, get_engine
from services import background_jobs
from services.timeline_projection import refresh_timeline_projection
from tests.test_timeline_projection_identity import _seed


async def snapshot(engine):
    async with engine.connect() as db:
        return [list((await db.execute(sa.select(model.__table__).order_by(model.id))).mappings())
                for model in (TimelineProjectionState, TimelineProjectionPoint)]


@pytest.mark.asyncio
async def test_failed_real_refresh_keeps_last_good_projection_and_recovers_same_cycle(monkeypatch):
    engine = get_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await _seed(db)
            await refresh_timeline_projection(db)
            await db.commit()
        before = await snapshot(engine)
        table = Base.metadata.tables["background_job_cycles"]
        async with engine.connect() as db:
            latest = await db.scalar(sa.select(sa.func.max(table.c.scheduled_for)).where(
                table.c.job_name == "timeline_projection"))
        due = latest + timedelta(seconds=1) if latest else datetime(2000, 1, 1, tzinfo=UTC)
        seen = []

        async def failing(db, scheduled_for, cycle_id):
            seen.append((scheduled_for, cycle_id))
            await refresh_timeline_projection(db, force_full_rebuild=True)
            raise RuntimeError("Synthetic failure after real projection writes")

        arguments = dict(interval_seconds=1, engine=engine, scheduled_for=due)
        failed = await background_jobs.run_background_cycle("timeline_projection", handler=failing, **arguments)
        assert failed["status"] == "failed" and failed["error_code"] == "execution_failed"
        assert await snapshot(engine) == before
        waiting = await background_jobs.run_background_cycle("timeline_projection", handler=failing, **arguments)
        assert waiting["status"] == "retry_wait" and len(seen) == 1

        clock = background_jobs._clock

        async def after_retry(db):
            # Advance only coordinator test time; projection still uses real UTC.
            return await clock(db) + timedelta(seconds=31)

        monkeypatch.setattr(background_jobs, "_clock", after_retry)

        async def successful(db, scheduled_for, cycle_id):
            assert (scheduled_for, cycle_id) == seen[0]
            result = await refresh_timeline_projection(db, force_full_rebuild=True)
            return {"active_points": result.active_points}

        recovered = await background_jobs.run_background_cycle("timeline_projection", handler=successful, **arguments)
        assert recovered["status"] == "succeeded" and recovered["recovered"] is True
        assert recovered["cycle_id"] == failed["cycle_id"] and recovered["attempts"] == 2
        after = await snapshot(engine)
        assert after[0][0]["source_watermark"] >= before[0][0]["source_watermark"]
        assert after[0][0]["refreshed_at"] >= before[0][0]["refreshed_at"]
        assert len(after[1]) == len(before[1])
    finally:
        await engine.dispose()
