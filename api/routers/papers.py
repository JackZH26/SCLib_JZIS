"""GET /paper/{id} — single-paper detail.

Public endpoint (no quota consumption). Returns the full paper row
including the extracted materials array and quality flags, so the
frontend can render the full PaperPage without extra round-trips.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import Paper
from models.search import PaperDetail
from routers.deps import Identity, peek_identity
from services.material_visibility import sanitize_review_metadata
from services.source_visibility import (
    project_source_occurrences,
    resolve_explicit_materials,
    source_visibility,
)

router = APIRouter(tags=["papers"])


@router.get("/paper/{paper_id:path}", response_model=PaperDetail)
async def paper_detail(
    paper_id: str,
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> PaperDetail:
    paper = await db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Paper {paper_id!r} not found")
    linked_materials = await resolve_explicit_materials(db, [paper.materials_extracted])
    records, summary = project_source_occurrences(
        paper.materials_extracted, paper_status=paper.status, linked_materials=linked_materials,
    )
    payload = {name: getattr(paper, name) for name in PaperDetail.model_fields if hasattr(paper, name)}
    payload.update(materials_extracted=records, source_visibility=source_visibility(paper.status),
                   occurrence_visibility_summary=summary, quality_flags=sanitize_review_metadata(paper.quality_flags))
    return PaperDetail.model_validate(payload)
