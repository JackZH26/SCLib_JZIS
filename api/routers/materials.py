"""GET /materials and GET /materials/{id} — public materials DB.

Section 7 of PROJECT_SPEC marks these as public, so we use
peek_identity (never consumes guest quota). Filters mirror the
frontend MaterialTable controls: family, tc_min, ordering, and
offset/limit pagination.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import Material
from models.search import MaterialDetail, MaterialListResponse, MaterialSummary
from routers.deps import Identity, peek_identity

router = APIRouter(tags=["materials"])


@router.get("/materials", response_model=MaterialListResponse)
async def list_materials(
    family: str | None = Query(
        None,
        description=(
            "Filter by material family. Accepts a single slug (``cuprate``) "
            "or a comma-separated list (``cuprate,iron_based``) to match any "
            "of several families with OR semantics."
        ),
    ),
    tc_min: float | None = Query(None, ge=0),
    # v2 filter params
    ambient_sc: bool | None = Query(None, description="Only ambient-pressure SC"),
    is_unconventional: bool | None = Query(None),
    is_topological: bool | None = Query(None),
    is_2d_or_interface: bool | None = Query(None),
    has_competing_order: bool | None = Query(None),
    pairing_symmetry: str | None = Query(None),
    structure_phase: str | None = Query(None),
    sort: str = Query("tc_max", pattern="^(tc_max|discovery_year|total_papers|tc_ambient)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_pending: bool = Query(
        False,
        description=(
            "Include materials flagged needs_review=True (physically "
            "implausible values, usually NER confusing Curie temp / "
            "melting point with Tc). Off by default so the list stays "
            "trustworthy; admins set it to audit / unflag."
        ),
    ),
    include_skeletons: bool = Query(
        False,
        description=(
            "Include materials with ``total_papers = 0`` — typically "
            "NIMS SuperCon reference-only catalog entries that carry "
            "no measured data (Tc / pressure / structure all null). "
            "Off by default so the list surfaces materials with real "
            "content. Turn on to browse the full NIMS index."
        ),
    ),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001 — presence sets guest counter header
    db: AsyncSession = Depends(get_db),
) -> MaterialListResponse:
    stmt = select(Material)
    count_stmt = select(func.count()).select_from(Material)

    def _apply(where_clause):
        nonlocal stmt, count_stmt
        stmt = stmt.where(where_clause)
        count_stmt = count_stmt.where(where_clause)

    # Automatic sanity gate. Rows where the aggregator detected an
    # implausible Tc (>250 K at ambient pressure) are hidden from the
    # public list; they remain fetchable via GET /materials/{id} so
    # old bookmarks keep working and admins can reach them to review.
    if not include_pending:
        _apply(Material.needs_review.is_(False))

    # Skeleton entries are rows that came from the NIMS CSV as a bare
    # DOI reference — no Tc, no pressure, total_papers = 0. Hiding
    # them by default keeps the default list feeling informative; the
    # opt-in flag lets admins / power users browse the full catalog.
    if not include_skeletons:
        _apply(Material.total_papers > 0)

    if family:
        # Multi-select: split on comma and match any. Single-value
        # requests ("?family=cuprate") still work — they reduce to an
        # IN clause with one element.
        slugs = [s.strip() for s in family.split(",") if s.strip()]
        if slugs:
            _apply(Material.family.in_(slugs))
    if tc_min is not None:
        _apply(Material.tc_max >= tc_min)
    if ambient_sc is not None:
        _apply(Material.ambient_sc.is_(ambient_sc))
    if is_unconventional is not None:
        _apply(Material.is_unconventional.is_(is_unconventional))
    if is_topological is not None:
        _apply(Material.is_topological.is_(is_topological))
    if is_2d_or_interface is not None:
        _apply(Material.is_2d_or_interface.is_(is_2d_or_interface))
    if has_competing_order is not None:
        _apply(Material.has_competing_order.is_(has_competing_order))
    if pairing_symmetry:
        _apply(Material.pairing_symmetry == pairing_symmetry)
    if structure_phase:
        _apply(Material.structure_phase == structure_phase)

    sort_col = {
        "tc_max": Material.tc_max,
        "tc_ambient": Material.tc_ambient,
        "discovery_year": Material.discovery_year,
        "total_papers": Material.total_papers,
    }[sort]
    # Postgres treats NULLS LAST as an extension — spell it out so
    # "sort by tc_max" doesn't put unmeasured materials on top.
    stmt = stmt.order_by(sort_col.desc().nulls_last()).limit(limit).offset(offset)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(stmt)).scalars().all()

    return MaterialListResponse(
        total=total,
        results=[MaterialSummary.model_validate(m) for m in rows],
        limit=limit,
        offset=offset,
    )


@router.get("/materials/{material_id}", response_model=MaterialDetail)
async def material_detail(
    material_id: str,
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> MaterialDetail:
    m = await db.get(Material, material_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Material {material_id!r} not found")
    return MaterialDetail.model_validate(m)
