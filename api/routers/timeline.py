"""GET /timeline — Tc-vs-year scatter points for the Plotly chart.

Reads the incremental Timeline projection when it is ready. During rollout or
if that derived read path fails, the endpoint safely falls back to flattening
``Material.records`` with the exact same classification rules.

Filtering rules (mirrors the /materials list endpoint's "honesty
defaults" — we never surface data the aggregator already flagged as
implausible):

1. **needs_review materials are excluded.** Xe at 5000 K, manganites
   at 347 K etc. are held back from both the list and the chart
   until a human confirms.
2. **Per-record Tc sanity:** any individual record with
   ``tc_kelvin > 300`` or ``tc_kelvin < 0`` is skipped even on
   non-flagged materials (the headline aggregate may be fine while
   a single NER-mis-extracted record pollutes the chart).
3. **Year validity:** record year must be in [1900, current_year + 1];
   anything else is probably a parse error.
4. **Deduplication:** records collapsed by (material_id, year,
   round(Tc, 1), round(pressure, 0)) — same claim reported multiple
   times in one paper doesn't render as N overlapping dots.

Set ``?include_pending=true`` to surface the filtered-out rows (admin
audit of the NER hallucinations).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import Material, Paper
from models.search import TimelineCoverage, TimelinePoint, TimelineResponse
from services.http_cache import conditional_json_response, weak_etag
from services.rate_limit import get_redis
from services.timeline_points import (
    extract_timeline_points,
    missing_year_paper_ids,
)
from services.timeline_projection import fetch_projected_timeline_points

router = APIRouter(tags=["timeline"])
log = logging.getLogger(__name__)

_CACHE_SCHEMA_VERSION = "v4"
_CACHE_TTL_SECONDS = 900
_CACHE_CONTROL = (
    "public, max-age=60, s-maxage=900, stale-while-revalidate=3600"
)


def _weak_etag(payload: str) -> str:
    """Backward-compatible local alias used by cache contract tests."""
    return weak_etag(payload)


def _date_year(value) -> int | None:
    return value.year if value is not None else None


def _cache_key(
    family: str | None,
    include_pending: bool,
    experimental_only: bool,
    only_aps: bool,
    max_points: int | None,
    compact: bool,
    offset: int = 0,
    limit: int | None = None,
    schema_version: str = "1",
) -> str:
    options = json.dumps(
        {
            "experimental_only": experimental_only,
            "family": family,
            "include_pending": include_pending,
            "max_points": max_points,
            "only_aps": only_aps,
            "compact": compact,
            "offset": offset,
            "limit": limit,
            "schema_version": schema_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    variant = hashlib.sha256(options.encode()).hexdigest()[:20]
    return f"timeline:{_CACHE_SCHEMA_VERSION}:{variant}"


def _evenly_sample(
    points: list[TimelinePoint],
    max_points: int | None,
) -> list[TimelinePoint]:
    """Return a deterministic sample while preserving timeline density.

    Points are already sorted by year and descending Tc. Selecting evenly
    spaced indexes therefore retains the temporal distribution and both
    endpoints without the memory and CPU cost of a second grouping pass.
    """
    if max_points is None or len(points) <= max_points:
        return points
    if max_points <= 0:
        raise ValueError("max_points must be positive")
    if max_points == 1:
        return [points[0]]
    total = len(points)
    return [
        points[round(index * (total - 1) / (max_points - 1))]
        for index in range(max_points)
    ]


def _serialize_timeline(data: TimelineResponse, *, compact: bool) -> str:
    if not compact:
        return data.model_dump_json()
    return data.model_dump_json(
        exclude={"points": {"__all__": {"formula_latex"}}},
    )


def _http_response(
    request: Request,
    payload: str,
    *,
    cache_status: str,
) -> Response:
    data_version_value, last_modified = _payload_metadata(payload)
    return conditional_json_response(
        request,
        payload,
        cache_control=_CACHE_CONTROL,
        data_version_value=data_version_value,
        last_modified=last_modified,
        cache_header="X-Timeline-Cache",
        cache_status=cache_status,
    )


def _payload_metadata(payload: str) -> tuple[str, datetime | None]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        parsed = {}
    version = parsed.get("data_version") if isinstance(parsed, dict) else None
    updated_at = parsed.get("data_updated_at") if isinstance(parsed, dict) else None
    last_modified: datetime | None = None
    if isinstance(updated_at, str):
        try:
            last_modified = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError:
            pass
    if not isinstance(version, str) or not version:
        version = "timeline-v1-unknown"
    return version, last_modified


def _timeline_data_version(updated_at: datetime | None) -> str:
    if updated_at is None:
        return "timeline-v1-unknown"
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    stamp = updated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"timeline-v1-{stamp}"


@router.get(
    "/timeline",
    response_model=TimelineResponse,
    responses={304: {"description": "Cached representation is still current"}},
)
async def timeline(
    request: Request,
    family: str | None = Query(
        None,
        min_length=1,
        max_length=50,
        description="Restrict to one family",
    ),
    include_pending: bool = Query(
        False,
        description=(
            "Surface materials flagged needs_review=True (implausible "
            "Tc). Off by default so the chart reflects vetted data only."
        ),
    ),
    experimental_only: bool = Query(
        False,
        description=(
            "Drop records classified as theoretical (DFT / first-"
            "principles calculations, see _is_theoretical()). When set, "
            "only points originating from a real experimental "
            "measurement technique survive — useful when the user is "
            "looking for ground truth and not predictions."
        ),
    ),
    only_aps: bool = Query(
        False,
        description="Only show Tc records whose paper_id is APS-sourced.",
    ),
    max_points: Literal[5000, 10000, 20000, 50000] | None = Query(
        None,
        description=(
            "Deterministically downsample large results to one of the supported "
            "rendering budgets. Coverage totals still describe the full result."
        ),
    ),
    compact: bool = Query(
        False,
        description="Omit display fields that the interactive chart does not use.",
    ),
    offset: int = Query(0, ge=0, le=1_000_000),
    limit: int | None = Query(
        None,
        ge=1,
        le=50_000,
        description="Page size after optional deterministic downsampling.",
    ),
    schema_version: Literal["1"] = Query("1", description="Response schema version"),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> Response:
    cache_key = _cache_key(
        family,
        include_pending,
        experimental_only,
        only_aps,
        max_points,
        compact,
        offset,
        limit,
        schema_version,
    )
    redis = get_redis()
    try:
        cached = await redis.get(cache_key)
    except Exception:  # noqa: BLE001 - cache outage must not break public reads
        log.warning("timeline cache read failed; falling back to DB", exc_info=True)
        cached = None

    if isinstance(cached, bytes):
        cached = cached.decode("utf-8")
    if isinstance(cached, str):
        return _http_response(request, cached, cache_status="HIT")

    try:
        projected = await fetch_projected_timeline_points(
            db,
            family=family,
            include_pending=include_pending,
            experimental_only=experimental_only,
            only_aps=only_aps,
        )
    except Exception:  # noqa: BLE001 - deployment-safe dual-read fallback
        await db.rollback()
        log.warning(
            "timeline projection read failed; using JSONB fallback",
            exc_info=True,
        )
        projected = None

    if projected is None:
        data = await _build_timeline_fallback(
            family=family,
            include_pending=include_pending,
            experimental_only=experimental_only,
            only_aps=only_aps,
            max_points=max_points,
            offset=offset,
            limit=limit,
            db=db,
        )
    else:
        data = _timeline_response(
            family=family,
            points=projected.points,
            max_points=max_points,
            offset=offset,
            limit=limit,
            data_updated_at=projected.refreshed_at,
        )
    payload = _serialize_timeline(data, compact=compact)
    try:
        await redis.set(cache_key, payload, ex=_CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001 - serve the computed response regardless
        log.warning("timeline cache write failed; serving uncached", exc_info=True)
    return _http_response(request, payload, cache_status="MISS")


def _timeline_response(
    *,
    family: str | None,
    points: list[TimelinePoint],
    max_points: int | None,
    offset: int = 0,
    limit: int | None = None,
    data_updated_at: datetime | None = None,
) -> TimelineResponse:
    total_points = len(points)
    available_points = _evenly_sample(points, max_points)
    end = offset + limit if limit is not None else None
    returned_points = available_points[offset:end]
    if points:
        years = [point.year for point in points]
        coverage = TimelineCoverage(
            total_points=total_points,
            total_materials=len({(point.material, point.family) for point in points}),
            year_min=min(years),
            year_max=max(years),
            returned_points=len(returned_points),
            available_points=len(available_points),
        )
    else:
        coverage = TimelineCoverage(
            total_points=0,
            total_materials=0,
            year_min=None,
            year_max=None,
            returned_points=0,
            available_points=0,
        )
    return TimelineResponse(
        data_version=_timeline_data_version(data_updated_at),
        data_updated_at=data_updated_at,
        family=family,
        points=returned_points,
        coverage=coverage,
        offset=offset,
        limit=limit,
        has_more=offset + len(returned_points) < len(available_points),
    )


async def _build_timeline_fallback(
    *,
    family: str | None,
    include_pending: bool,
    experimental_only: bool,
    only_aps: bool,
    max_points: int | None,
    offset: int,
    limit: int | None,
    db: AsyncSession,
) -> TimelineResponse:
    stmt = select(Material)
    if family:
        stmt = stmt.where(Material.family == family)
    if not include_pending:
        stmt = stmt.where(Material.needs_review.is_(False))

    mats = (await db.execute(stmt)).scalars().all()
    data_updated_at = max(
        (material.updated_at for material in mats if material.updated_at is not None),
        default=None,
    )

    paper_ids: set[str] = set()
    for material in mats:
        paper_ids.update(
            missing_year_paper_ids(material.records, only_aps=only_aps)
        )

    paper_years: dict[str, int] = {}
    if paper_ids:
        paper_rows = await db.execute(
            select(Paper.id, Paper.date_published, Paper.date_submitted)
            .where(Paper.id.in_(sorted(paper_ids)))
        )
        for paper_id, date_published, date_submitted in paper_rows.all():
            year = _date_year(date_published) or _date_year(date_submitted)
            if year is not None:
                paper_years[paper_id] = year

    points: list[TimelinePoint] = []
    for material in mats:
        for projected in extract_timeline_points(
            material.id,
            material.records,
            paper_years,
        ):
            if only_aps and not projected.is_aps:
                continue
            if experimental_only and projected.is_theoretical:
                continue
            points.append(TimelinePoint(
                material=material.formula,
                formula_latex=material.formula_latex,
                family=material.family,
                tc_kelvin=projected.tc_kelvin,
                year=projected.year,
                pressure_gpa=projected.pressure_gpa,
                paper_id=projected.paper_id,
                is_theoretical=projected.is_theoretical,
            ))

    points.sort(key=lambda point: (point.year, -point.tc_kelvin))
    return _timeline_response(
        family=family,
        points=points,
        max_points=max_points,
        offset=offset,
        limit=limit,
        data_updated_at=data_updated_at,
    )
