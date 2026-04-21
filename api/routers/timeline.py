"""GET /timeline — Tc-vs-year scatter points for the Plotly chart.

Walks ``Material.records`` (JSONB list of TcRecord-shaped dicts) and
flattens them into one row per *distinct* (material, year, Tc bucket,
pressure bucket) measurement. Optionally filters to a single family
("cuprate", "iron_based", "hydride", …).

Filtering rules (mirrors the /materials list endpoint's "honesty
defaults" — we never surface data the aggregator already flagged as
implausible):

1. **needs_review materials are excluded.** Xe at 5000 K, manganites
   at 347 K etc. are held back from both the list and the chart
   until a human confirms.
2. **Per-record Tc sanity:** any individual record with
   ``tc_kelvin > 250`` or ``tc_kelvin < 0`` is skipped even on
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

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import Material
from models.search import TimelineCoverage, TimelinePoint, TimelineResponse
from routers.deps import Identity, peek_identity

router = APIRouter(tags=["timeline"])


# Physical sanity ceiling for a single Tc measurement. Matches the
# aggregator's _TC_SANITY_MAX_K; anything above this is almost
# certainly NER confusing a Curie / structural / theoretical transition
# with the SC Tc. Keep the two thresholds in sync if either changes.
_TC_MAX_K = 250.0


@router.get("/timeline", response_model=TimelineResponse)
async def timeline(
    family: str | None = Query(None, description="Restrict to one family"),
    include_pending: bool = Query(
        False,
        description=(
            "Surface materials flagged needs_review=True (implausible "
            "Tc). Off by default so the chart reflects vetted data only."
        ),
    ),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> TimelineResponse:
    stmt = select(Material)
    if family:
        stmt = stmt.where(Material.family == family)
    if not include_pending:
        stmt = stmt.where(Material.needs_review.is_(False))

    mats = (await db.execute(stmt)).scalars().all()

    current_year = datetime.now(timezone.utc).year
    year_hi = current_year + 1

    # Dedup key: (mat_id, year, Tc bin 0.1 K, pressure bin 1 GPa).
    # Collapses near-duplicates the NER emits when a paper reports the
    # same Tc under multiple measurement techniques (resistivity vs
    # susceptibility → two records with identical values).
    seen: dict[tuple, TimelinePoint] = {}

    for m in mats:
        for rec in (m.records or []):
            if not isinstance(rec, dict):
                continue
            tc = rec.get("tc_kelvin")
            year = rec.get("year") or rec.get("measurement_year")
            if tc is None or year is None:
                continue
            try:
                tc_f = float(tc)
                year_i = int(year)
            except (TypeError, ValueError):
                continue

            # Per-record sanity filters
            if tc_f <= 0 or tc_f > _TC_MAX_K:
                continue
            if year_i < 1900 or year_i > year_hi:
                continue

            p = _as_float(rec.get("pressure_gpa"))
            tc_bin = round(tc_f, 1)
            p_bin = round(p) if p is not None else None
            key = (m.id, year_i, tc_bin, p_bin)
            if key in seen:
                continue

            seen[key] = TimelinePoint(
                material=m.formula,
                formula_latex=m.formula_latex,
                family=m.family,
                tc_kelvin=tc_f,
                year=year_i,
                pressure_gpa=p,
                paper_id=rec.get("paper_id"),
            )

    points = sorted(seen.values(), key=lambda p: (p.year, -p.tc_kelvin))

    coverage: TimelineCoverage | None = None
    if points:
        years = [p.year for p in points]
        coverage = TimelineCoverage(
            total_points=len(points),
            total_materials=len({(p.material, p.family) for p in points}),
            year_min=min(years),
            year_max=max(years),
        )
    else:
        coverage = TimelineCoverage(
            total_points=0, total_materials=0, year_min=None, year_max=None,
        )

    return TimelineResponse(family=family, points=points, coverage=coverage)


def _as_float(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
