"""Bounded infrastructure probes and non-gating data-health summaries."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy import text

from models import get_session_factory
from models.db import StatsCache, TimelineProjectionState
from models.health import DataComponentHealth, DependencyCheck, DependencyHealth
from models.search import StatsDataPipeline
from services.rate_limit import get_redis
from services.timeline_projection import PROJECTION_SCHEMA_VERSION

_PROBE_TIMEOUT_SECONDS = 2.0


async def _check_postgres() -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SELECT 1"))


async def _check_redis() -> None:
    if not await get_redis().ping():
        raise RuntimeError("Redis ping returned false")


async def _timed_probe(
    probe: Callable[[], Awaitable[None]],
    *,
    timeout_seconds: float = _PROBE_TIMEOUT_SECONDS,
) -> DependencyCheck:
    started = perf_counter()
    try:
        await asyncio.wait_for(probe(), timeout=timeout_seconds)
    except Exception:  # noqa: BLE001 - health responses intentionally hide internals
        status = "error"
    else:
        status = "ok"
    latency_ms = max(0, round((perf_counter() - started) * 1000))
    return DependencyCheck(status=status, latency_ms=latency_ms)


async def collect_dependency_health() -> DependencyHealth:
    postgres, redis = await asyncio.gather(
        _timed_probe(_check_postgres),
        _timed_probe(_check_redis),
    )
    dependencies = {"postgres": postgres, "redis": redis}
    ready = all(check.status == "ok" for check in dependencies.values())
    return DependencyHealth(
        status="ok" if ready else "unavailable",
        checked_at=datetime.now(UTC),
        dependencies=dependencies,
    )


def _pipeline_status(row: StatsCache | None) -> StatsDataPipeline:
    if row is None:
        return StatsDataPipeline()
    try:
        return StatsDataPipeline.model_validate(row.value or {})
    except Exception:  # noqa: BLE001 - malformed state is reported as unknown
        return StatsDataPipeline()


async def collect_database_data_health() -> dict[str, DataComponentHealth]:
    """Read cheap cache/projection metadata without applying age thresholds."""
    factory = get_session_factory()
    async with factory() as session:
        dashboard = await session.get(StatsCache, "dashboard")
        pipeline_row = await session.get(StatsCache, "data_pipeline")
        timeline = await session.get(TimelineProjectionState, 1)

    stats_value = dict(dashboard.value or {}) if dashboard is not None else {}
    stats_updated_at = dashboard.updated_at.isoformat() if dashboard is not None else None
    pipeline = _pipeline_status(pipeline_row)
    timeline_ready = (
        timeline is not None
        and timeline.schema_version == PROJECTION_SCHEMA_VERSION
        and timeline.source_year == datetime.now(UTC).year
    )

    return {
        "stats": DataComponentHealth(
            status="ready" if dashboard is not None else "missing",
            updated_at=stats_updated_at,
        ),
        "dataset": DataComponentHealth(
            status="ready" if stats_value.get("last_ingest_at") else "missing",
            updated_at=stats_value.get("last_ingest_at"),
            details={
                "dataset_version": stats_value.get("dataset_version"),
                "total_papers": stats_value.get("total_papers"),
                "total_materials": stats_value.get("total_materials"),
                "total_chunks": stats_value.get("total_chunks"),
            },
        ),
        "pipeline": DataComponentHealth(
            status=pipeline.status,
            updated_at=pipeline.last_run_at,
            details={
                "stages": {
                    name: stage.model_dump(mode="json")
                    for name, stage in pipeline.stages.items()
                }
            },
        ),
        "timeline_projection": DataComponentHealth(
            status="ready" if timeline_ready else "not_ready",
            updated_at=(
                timeline.refreshed_at.isoformat() if timeline is not None else None
            ),
            details={
                "schema_version": timeline.schema_version if timeline is not None else None,
                "source_year": timeline.source_year if timeline is not None else None,
                "material_count": timeline.material_count if timeline is not None else None,
                "active_point_count": (
                    timeline.active_point_count if timeline is not None else None
                ),
            },
        ),
    }
