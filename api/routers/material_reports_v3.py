"""Read-only, source-governed report pagination; mounted before material catch-all."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Material, Paper, PaperWorkMap, User, get_db
from routers.admin import current_reviewer_or_admin
from services.material_reports_v3 import report_projection
from services.material_source_scope import current_visibility_allows_view
from services.material_visibility_adapter import material_view
from services.materials_v3_snapshots import read_candidate_snapshot

router = APIRouter(tags=["materials"])


@router.get("/admin/materials-v3/snapshots/{snapshot_id}/materials/{material_id:path}")
async def candidate_material_reports(
    snapshot_id: UUID,
    material_id: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_reviewer_or_admin)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    report = await read_candidate_snapshot(db, snapshot_id, material_id, offset=offset, limit=limit)
    if report is None:
        raise HTTPException(404, "Candidate preview unavailable in the current source scope")
    response.headers["Cache-Control"] = "private, no-store"
    return report


@router.get("/materials/{material_id:path}/reports")
async def material_reports(
    material_id: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    context = await material_view(db, await db.get(Material, material_id))
    if context is None or not current_visibility_allows_view(
        context.visibility, include_archive=False
    ):
        raise HTTPException(404, "Material reports are unavailable in the current source scope")
    records = context.current_records()
    ids = sorted(
        {
            r.get("paper_id")
            for r in records
            if isinstance(r, dict) and isinstance(r.get("paper_id"), str)
        }
    )
    work_map, papers = {}, {}
    if ids:
        mappings = await db.execute(
            select(PaperWorkMap.paper_id, PaperWorkMap.work_id).where(
                PaperWorkMap.paper_id.in_(ids), PaperWorkMap.review_status == "accepted"
            )
        )
        work_map = dict(mappings.all())
        metadata = await db.execute(
            select(Paper.id, Paper.title, Paper.date_published, Paper.date_submitted).where(
                Paper.id.in_(ids)
            )
        )
        papers = {
            row.id: {
                "title": row.title,
                "year": (row.date_published or row.date_submitted).year
                if (row.date_published or row.date_submitted)
                else None,
            }
            for row in metadata
        }
    response.headers["Cache-Control"] = "no-store"
    return report_projection(
        material_id,
        records,
        work_map=work_map,
        papers=papers,
        offset=offset,
        limit=limit,
        original_indices=list(context.source_scope.eligible_indices)
        if context.source_scope
        else None,
    )
