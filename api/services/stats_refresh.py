"""Recompute the ``stats_cache['dashboard']`` row.

Run on a schedule (Phase 5 cron) so ``GET /stats`` serves a single
O(1) row lookup instead of scanning papers + materials every hit.
The same function can be invoked from a CLI script or unit test —
callers just need to pass an ``AsyncSession``.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Chunk, Material, Paper, StatsCache
from models.search import StatsDataPipeline
from services.metrics import update_dataset_metrics

log = logging.getLogger(__name__)
_PIPELINE_CACHE_KEY = "data_pipeline"


async def compute_stats(db: AsyncSession) -> dict:
    """Pure read-side aggregation — no writes. Returns a dict whose
    shape matches ``models.search.StatsResponse`` so the API can
    serialize it straight through."""

    total_papers = (await db.execute(select(func.count()).select_from(Paper))).scalar_one()
    # Public count only: needs_review=True covers both data-quality
    # flags and the NIMS provenance quarantine
    # (review_reason='provenance_quarantine_nims'). Mirrors the default
    # /materials list gate (materials.py) so the headline MATERIALS
    # number reflects the trustworthy arXiv-derived catalogue.
    total_materials = (
        await db.execute(
            select(func.count())
            .select_from(Material)
            .where(Material.needs_review.is_(False))
        )
    ).scalar_one()
    total_chunks = (await db.execute(select(func.count()).select_from(Chunk))).scalar_one()

    arxiv_year_expr = func.extract("year", Paper.date_submitted)
    arxiv_by_year_rows = (
        await db.execute(
            select(arxiv_year_expr, func.count())
            .where(Paper.source == "arxiv", Paper.date_submitted.is_not(None))
            .group_by(arxiv_year_expr)
            .order_by(arxiv_year_expr)
        )
    ).all()
    papers_by_year_arxiv = {
        str(int(y)): int(c) for y, c in arxiv_by_year_rows if y is not None
    }

    aps_year_expr = func.extract("year", Paper.date_published)
    aps_by_year_rows = (
        await db.execute(
            select(aps_year_expr, func.count())
            .where(Paper.source == "aps", Paper.date_published.is_not(None))
            .group_by(aps_year_expr)
            .order_by(aps_year_expr)
        )
    ).all()
    papers_by_year_aps = {
        str(int(y)): int(c) for y, c in aps_by_year_rows if y is not None
    }

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

    refreshed_at = datetime.now(UTC)
    refreshed_at_iso = refreshed_at.isoformat()
    return {
        "total_papers": int(total_papers),
        "total_materials": int(total_materials),
        "total_chunks": int(total_chunks),
        # Keep the legacy field aligned with the default visible tab on
        # /stats so older clients still receive a sensible histogram.
        "papers_by_year": papers_by_year_arxiv,
        "papers_by_year_arxiv": papers_by_year_arxiv,
        "papers_by_year_aps": papers_by_year_aps,
        "top_material_families": top_material_families,
        "last_ingest_at": last_ingest_iso,
        "dataset_version": dataset_version,
        "stats_refreshed_at": refreshed_at_iso,
        # Backward-compatible alias; new clients use stats_refreshed_at.
        "updated_at": refreshed_at_iso,
    }


async def get_data_pipeline_status(db: AsyncSession) -> StatsDataPipeline:
    """Read pipeline state from its own cache row.

    Keeping this separate from ``stats_cache['dashboard']`` prevents an
    hourly counter refresh from overwriting the most recent cron stage report.
    """
    cached = await db.get(StatsCache, _PIPELINE_CACHE_KEY)
    if cached is None:
        return StatsDataPipeline()
    try:
        return StatsDataPipeline.model_validate(cached.value or {})
    except Exception:  # noqa: BLE001 - corrupt optional status must not block stats
        log.warning("invalid data_pipeline status in stats cache; resetting to unknown")
        return StatsDataPipeline()


async def refresh_dashboard_cache(
    db: AsyncSession,
    *,
    data_pipeline: StatsDataPipeline | None = None,
) -> dict:
    """Compute stats and upsert the ``dashboard`` row.

    Uses Postgres' ``ON CONFLICT DO UPDATE`` so the first call inserts and
    subsequent calls replace atomically. When cron supplies ``data_pipeline``,
    that state is written to a separate cache row so an unrelated hourly
    dashboard refresh cannot overwrite it.
    """
    payload = await compute_stats(db)
    refreshed_at = datetime.fromisoformat(payload["stats_refreshed_at"])
    current_pipeline = data_pipeline or await get_data_pipeline_status(db)

    stmt = (
        pg_insert(StatsCache)
        .values(key="dashboard", value=payload)
        .on_conflict_do_update(
            index_elements=[StatsCache.key],
            set_={
                "value": payload,
                "updated_at": refreshed_at,
            },
        )
    )
    await db.execute(stmt)
    if data_pipeline is not None:
        pipeline_stmt = (
            pg_insert(StatsCache)
            .values(
                key=_PIPELINE_CACHE_KEY,
                value=data_pipeline.model_dump(mode="json"),
                updated_at=refreshed_at,
            )
            .on_conflict_do_update(
                index_elements=[StatsCache.key],
                set_={
                    "value": data_pipeline.model_dump(mode="json"),
                    "updated_at": refreshed_at,
                },
            )
        )
        await db.execute(pipeline_stmt)
    await db.commit()
    payload["data_pipeline"] = current_pipeline.model_dump(mode="json")
    update_dataset_metrics(payload, current_pipeline.stages)
    log.info(
        "stats_cache[dashboard] refreshed: %d papers / %d materials / %d chunks",
        payload["total_papers"],
        payload["total_materials"],
        payload["total_chunks"],
    )
    return payload
