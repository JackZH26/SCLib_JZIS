"""GET /timeline — Tc-vs-year scatter points for the Plotly chart.

Walks Material.records (JSONB list of TcRecord-shaped dicts) and
flattens them into one row per measurement. Optionally filters to
a single family ("cuprate", "iron", "hydride", ...).

Materials with no records are silently skipped; records missing
either tc_kelvin or a year are skipped individually. The Plotly
component on the frontend expects strictly one dot per measurement.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import Material
from models.search import TimelinePoint, TimelineResponse
from routers.deps import Identity, peek_identity

router = APIRouter(tags=["timeline"])


@router.get("/timeline", response_model=TimelineResponse)
async def timeline(
    family: str | None = Query(None, description="Restrict to one family"),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> TimelineResponse:
    stmt = select(Material)
    if family:
        stmt = stmt.where(Material.family == family)

    mats = (await db.execute(stmt)).scalars().all()
    points: list[TimelinePoint] = []
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
            points.append(
                TimelinePoint(
                    material=m.formula,
                    formula_latex=m.formula_latex,
                    family=m.family,
                    tc_kelvin=tc_f,
                    year=year_i,
                    pressure_gpa=_as_float(rec.get("pressure_gpa")),
                    paper_id=rec.get("paper_id"),
                )
            )

    points.sort(key=lambda p: (p.year, -p.tc_kelvin))
    return TimelineResponse(family=family, points=points)


def _as_float(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
