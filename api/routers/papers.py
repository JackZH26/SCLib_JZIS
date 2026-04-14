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
    return PaperDetail.model_validate(paper)
