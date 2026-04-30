"""Recompute the ``stats_cache['dashboard']`` row.

Run on a schedule (Phase 5 cron) so ``GET /stats`` serves a single
O(1) row lookup instead of scanning papers + materials every hit.
The same function can be invoked from a CLI script or unit test —
callers just need to pass an ``AsyncSession``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Chunk, Material, Paper, StatsCache

log = logging.getLogger(__name__)


async def compute_stats(db: AsyncSession) -> dict:
    """Pure read-side aggregation — no writes. Returns a dict whose
    shape matches ``models.search.StatsResponse`` so the API can
    serialize it straight through."""

    total_papers = (await db.execute(select(func.count()).select_from(Paper))).scalar_one()
    total_materials = (
        await db.execute(select(func.count()).select_from(Material))
    ).scalar_one()
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

    last_ingest_row = await db.execute(
        select(func.max(Paper.indexed_at))
    )
    last_ingest_at = last_ingest_row.scalar_one()
    last_ingest_iso = last_ingest_at.isoformat() if last_ingest_at is not None else None
    # Calver dataset_version mirrors Materials Project's
    # `database_version` so users have a stable handle for citing
    # "which data snapshot". Bumps every day the ingest adds papers.
    dataset_version = (
        f"v{last_ingest_at:%Y.%m.%d}" if last_ingest_at is not None else None
    )

    return {
        "total_papers": int(total_papers),
        "total_materials": int(total_materials),
        "total_chunks": int(total_chunks),
        "papers_by_year": papers_by_year,
        "top_material_families": top_material_families,
        "last_ingest_at": last_ingest_iso,
        "dataset_version": dataset_version,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def refresh_dashboard_cache(db: AsyncSession) -> dict:
    """Compute stats and upsert the ``dashboard`` row.

    Uses Postgres' ``ON CONFLICT DO UPDATE`` so the first call
    inserts and subsequent calls replace atomically — no read /
    modify / write race against a concurrent ``GET /stats``.
    """
    payload = await compute_stats(db)

    stmt = (
        pg_insert(StatsCache)
        .values(key="dashboard", value=payload)
        .on_conflict_do_update(
            index_elements=[StatsCache.key],
            set_={
                "value": payload,
                "updated_at": datetime.now(timezone.utc),
            },
        )
    )
    await db.execute(stmt)
    await db.commit()
    log.info(
        "stats_cache[dashboard] refreshed: %d papers / %d materials / %d chunks",
        payload["total_papers"],
        payload["total_materials"],
        payload["total_chunks"],
    )
    return payload
