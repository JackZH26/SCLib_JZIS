"""GET /stats — dashboard counters.

Reads from the ``stats_cache`` row keyed ``dashboard``. The daily
ingest job is responsible for refreshing that row (see Phase 5
cron). If the cache is empty (fresh install, tests) we fall back
to a live count so the endpoint still returns something sensible.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import Chunk, Material, Paper, StatsCache
from models.search import StatsResponse
from routers.deps import Identity, peek_identity

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsResponse)
async def stats(
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> StatsResponse:
    cached = await db.get(StatsCache, "dashboard")
    if cached is not None:
        v = dict(cached.value or {})
        v.setdefault("updated_at", cached.updated_at.isoformat())
        return StatsResponse(**v)

    # Live fallback — kept cheap because it only runs on fresh DBs.
    total_papers = (await db.execute(select(func.count()).select_from(Paper))).scalar_one()
    total_materials = (await db.execute(select(func.count()).select_from(Material))).scalar_one()
    total_chunks = (await db.execute(select(func.count()).select_from(Chunk))).scalar_one()

    year_expr = func.extract("year", Paper.date_submitted)
    by_year_rows = (
        await db.execute(
            select(year_expr, func.count())
            .where(Paper.date_submitted.is_not(None))
            .group_by(year_expr)
            .order_by(year_expr)
        )
    ).all()
    papers_by_year = {str(int(y)): int(c) for y, c in by_year_rows if y is not None}

    fam_rows = (
        await db.execute(
            select(Paper.material_family, func.count())
            .where(Paper.material_family.is_not(None))
            .group_by(Paper.material_family)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()
    top_material_families = [{"family": f, "count": int(c)} for f, c in fam_rows]

    return StatsResponse(
        total_papers=int(total_papers),
        total_materials=int(total_materials),
        total_chunks=int(total_chunks),
        papers_by_year=papers_by_year,
        top_material_families=top_material_families,
        last_ingest_at=None,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
