"""GET /stats — dashboard counters + POST /stats/refresh admin hook.

Reads from the ``stats_cache`` row keyed ``dashboard``. The daily
ingest job is responsible for refreshing that row (see the
``refresh_dashboard_cache`` service). If the cache is empty (fresh
install, tests) we fall back to a live count so the endpoint still
returns something sensible.

``POST /stats/refresh`` is an internal admin hook intended for the
Phase 5 cron (``scripts/cron_daily_ingest.sh``). It requires an
``X-Internal-Key`` header matching ``INTERNAL_API_KEY`` in the env
so the endpoint stays safe even if accidentally exposed through
Nginx.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models import get_db
from models.db import StatsCache
from models.search import StatsRefreshRequest, StatsResponse
from routers.deps import Identity, peek_identity
from services.stats_refresh import (
    compute_stats,
    get_data_pipeline_status,
    refresh_dashboard_cache,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsResponse)
async def stats(
    identity: Identity = Depends(peek_identity),  # noqa: ARG001, B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> StatsResponse:
    cached = await db.get(StatsCache, "dashboard")
    if cached is not None:
        v = dict(cached.value or {})
        refreshed_at = cached.updated_at.isoformat()
        v["stats_refreshed_at"] = refreshed_at
        v["updated_at"] = refreshed_at
        v["data_pipeline"] = (
            await get_data_pipeline_status(db)
        ).model_dump(mode="json")
        return StatsResponse(**v)

    # Live fallback — only hit on fresh DBs before the first refresh.
    payload = await compute_stats(db)
    payload["data_pipeline"] = (
        await get_data_pipeline_status(db)
    ).model_dump(mode="json")
    return StatsResponse(**payload)


@router.post("/stats/refresh", response_model=StatsResponse)
async def refresh_stats(
    body: StatsRefreshRequest | None = None,
    x_internal_key: str | None = Header(default=None, alias="X-Internal-Key"),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> StatsResponse:
    """Recompute and persist the dashboard stats row.

    Intended for the nightly cron. Not exposed through Nginx's
    public location — the internal key gate is belt-and-braces.
    """
    settings = get_settings()
    expected = settings.internal_api_key
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "INTERNAL_API_KEY is not configured on this instance",
        )
    # Constant-time comparison — prevents byte-by-byte timing leaks of
    # INTERNAL_API_KEY via response latency measurements.
    if not hmac.compare_digest(x_internal_key or "", expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal key")

    payload = await refresh_dashboard_cache(
        db,
        data_pipeline=body.data_pipeline if body is not None else None,
    )
    return StatsResponse(**payload)
