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
    family: str | None = Query(None, description="Filter by material family"),
    tc_min: float | None = Query(None, ge=0),
    sort: str = Query("tc_max", pattern="^(tc_max|discovery_year|total_papers)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001 — presence sets guest counter header
    db: AsyncSession = Depends(get_db),
) -> MaterialListResponse:
    stmt = select(Material)
    count_stmt = select(func.count()).select_from(Material)

    if family:
        stmt = stmt.where(Material.family == family)
        count_stmt = count_stmt.where(Material.family == family)
    if tc_min is not None:
        stmt = stmt.where(Material.tc_max >= tc_min)
        count_stmt = count_stmt.where(Material.tc_max >= tc_min)

    sort_col = {
        "tc_max": Material.tc_max,
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
