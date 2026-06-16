"""GET /timeline — Tc-vs-year scatter points for the Plotly chart.

Walks ``Material.records`` (JSONB list of TcRecord-shaped dicts) and
flattens them into one row per *distinct* (material, year, Tc bucket,
pressure bucket) measurement. Optionally filters to a single family
("cuprate", "iron_based", "hydride", …) or to APS-sourced records.

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

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import Material, Paper
from models.search import TimelineCoverage, TimelinePoint, TimelineResponse
from routers.deps import Identity, peek_identity

router = APIRouter(tags=["timeline"])


# Display ceiling for a single Tc point on the timeline. Set ABOVE the
# aggregator's _TC_SANITY_MAX_K (250 K) on purpose: vetted near-room-
# temperature hydride claims (e.g. CaLuH12 ~294 K) are legitimately in
# the Materials catalog (needs_review=False) and should be visible on
# the chart too. This is a display-only filter — it does NOT affect
# ingestion-time needs_review flagging, so the two thresholds are now
# intentionally decoupled; do not "resync" them to the aggregator.
_TC_MAX_K = 300.0


# Known experimental measurement techniques. If a record's
# ``measurement`` field matches any of these we trust the value as a
# real measurement, regardless of what the (notoriously over-tagged)
# ``paper_type`` field claims. Counts taken from a recent DB sample —
# this list covers > 99% of explicit non-empty measurement values.
_EXPERIMENTAL_MEASUREMENTS = frozenset({
    "resistivity", "susceptibility", "specific_heat",
    "arpes", "musr", "stm", "neutron", "nmr", "nqr",
    "magnetization", "thermal_conductivity",
    "raman scattering", "raman", "andreev reflection",
    "nernst", "tunneling", "esr", "torque magnetometry",
    "hall effect", "hall_effect", "transport",
})

# Explicit calculation tags. NER uses these when the paper itself
# describes its method ("DFT", "first-principles study"). Mirrors
# the most common values surfacing on /materials.records.
_THEORETICAL_MEASUREMENTS = frozenset({
    "calculation", "dft", "first-principles", "first principles",
    "computational", "ab initio", "ab-initio",
    "allen-dynes", "eliashberg", "tight-binding",
})


def _is_theoretical(rec: dict) -> bool:
    """Hybrid classifier: was this Tc measured or calculated?

    Rule of precedence:

    1. Explicit experimental technique in ``measurement`` (resistivity,
       STM, ARPES, ...) → **experimental**, regardless of paper_type.
       The NER's paper_type label is unreliable; an explicit technique
       wins.
    2. Explicit calculation tag (calculation, DFT, ...) → **theoretical**.
    3. measurement empty / unknown — fall back to paper_type. If NER
       called the paper theoretical or computational and we have no
       measurement evidence to override that, treat the record as
       theoretical. Otherwise default to experimental, since most
       arXiv cond-mat.supr-con papers are experimental.
    """
    m = (rec.get("measurement") or "").strip().lower()
    if m in _EXPERIMENTAL_MEASUREMENTS:
        return False
    if m in _THEORETICAL_MEASUREMENTS:
        return True
    pt = (rec.get("paper_type") or "").strip().lower()
    if pt not in {"theoretical", "computational"}:
        return False
    # paper_type is the ONLY remaining signal here, and NER massively
    # over-tags it. Measured over the live timeline corpus: the
    # explicit-calc tag fires on 1/19922 records, so paper_type drives
    # ~100% of "theoretical" — and ~84% of those (2953 records) are
    # AMBIENT-pressure points that are demonstrably real experimental
    # classics (ErBa2Cu3O7, La1.86Sr0.14CuO4, Chevrel Mo6Se7.5,
    # RuSr2Gd1.5Ce0.5Cu2O10, picene C14H10 …) — three independent
    # random-100 scientific reviews all flagged this as THE systematic
    # error. Trust paper_type ONLY in the pressure-bearing prediction
    # zone, where the theory/experiment split is defensible and most
    # meaningful (super-hydride / high-pressure predictions). An
    # ambient paper_type-only "theoretical" is almost always a
    # mislabeled measurement → treat as experimental.
    p = _as_float(rec.get("pressure_gpa"))
    return p is not None and p > 0


def _is_aps_record(rec: dict) -> bool:
    paper_id = rec.get("paper_id")
    return isinstance(paper_id, str) and paper_id.startswith("aps:")


def _date_year(value) -> int | None:
    return value.year if value is not None else None


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
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> TimelineResponse:
    stmt = select(Material)
    if family:
        stmt = stmt.where(Material.family == family)
    if not include_pending:
        stmt = stmt.where(Material.needs_review.is_(False))

    mats = (await db.execute(stmt)).scalars().all()

    missing_year_paper_ids: set[str] = set()
    for m in mats:
        for rec in (m.records or []):
            if not isinstance(rec, dict):
                continue
            if only_aps and not _is_aps_record(rec):
                continue
            if rec.get("year") is not None or rec.get("measurement_year") is not None:
                continue
            paper_id = rec.get("paper_id")
            if isinstance(paper_id, str):
                missing_year_paper_ids.add(paper_id)

    paper_years: dict[str, int] = {}
    if missing_year_paper_ids:
        paper_rows = await db.execute(
            select(Paper.id, Paper.date_published, Paper.date_submitted)
            .where(Paper.id.in_(sorted(missing_year_paper_ids)))
        )
        for paper_id, date_published, date_submitted in paper_rows.all():
            year = _date_year(date_published) or _date_year(date_submitted)
            if year is not None:
                paper_years[paper_id] = year

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
            if only_aps and not _is_aps_record(rec):
                continue
            tc = rec.get("tc_kelvin")
            paper_id = rec.get("paper_id")
            year = (
                rec.get("year")
                or rec.get("measurement_year")
                or (paper_years.get(paper_id) if isinstance(paper_id, str) else None)
            )
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
            theory = _is_theoretical(rec)
            if experimental_only and theory:
                continue
            tc_bin = round(tc_f, 1)
            p_bin = round(p) if p is not None else None
            # Theoretical records dedup against theoretical, experimental
            # against experimental — so a theory paper's calculated 200 K
            # for H₃S and an experimental 200 K paper at the same year
            # don't collapse into one dot. The chart should show both.
            key = (m.id, year_i, tc_bin, p_bin, theory)
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
                is_theoretical=theory,
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
