"""Bookmarks — users save papers + materials for later.

Strictly private: no public-profile endpoint exposes a user's saves
(product decision — see project memory). Target type is constrained
at the DB level to {'paper', 'material'}; the unique index on
(user_id, target_type, target_id) is what turns duplicate POSTs into
409s without a race.

Endpoints:

* ``POST   /bookmarks``            — create; 409 on duplicate, 404 if target missing
* ``DELETE /bookmarks/{id}``       — remove by bookmark id
* ``GET    /bookmarks/papers``     — list with papers.* hydrated
* ``GET    /bookmarks/materials``  — list with materials.* hydrated

Listing hits two separate endpoints rather than one polymorphic route
so each response has a precise, typed shape (the dashboard renders
papers and materials with different columns anyway).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import Bookmark, Material, Paper, User
from models.personal import (
    BookmarkCreate,
    BookmarkRead,
    BookmarkedMaterial,
    BookmarkedMaterialsResponse,
    BookmarkedPaper,
    BookmarkedPapersResponse,
)
from models.user import MessageResponse
from routers.auth import current_user_from_jwt

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


@router.post("", response_model=BookmarkRead, status_code=201)
async def create_bookmark(
    body: BookmarkCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
) -> BookmarkRead:
    # Confirm the target exists so we don't accumulate dead pointers.
    # This also gives the user a clear 404 instead of a silent success
    # that renders as "Untitled" on the dashboard later.
    if body.target_type == "paper":
        exists = await db.get(Paper, body.target_id)
    else:  # "material"
        exists = await db.get(Material, body.target_id)
    if exists is None:
        raise HTTPException(404, f"{body.target_type} '{body.target_id}' not found")

    bm = Bookmark(
        user_id=user.id,
        target_type=body.target_type,
        target_id=body.target_id,
    )
    db.add(bm)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Already bookmarked") from None
    await db.refresh(bm)
    return BookmarkRead.model_validate(bm)


@router.delete("/{bookmark_id}", response_model=MessageResponse)
async def delete_bookmark(
    bookmark_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
) -> MessageResponse:
    bm = await db.get(Bookmark, bookmark_id)
    if bm is None or bm.user_id != user.id:
        raise HTTPException(404, "Bookmark not found")
    await db.delete(bm)
    await db.commit()
    return MessageResponse(message="Deleted")


@router.get("/papers", response_model=BookmarkedPapersResponse)
async def list_paper_bookmarks(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
) -> BookmarkedPapersResponse:
    """List paper bookmarks joined with papers.* so the dashboard can
    render title + authors without an extra fetch per row."""
    total_q = await db.execute(
        select(func.count()).select_from(Bookmark)
        .where(Bookmark.user_id == user.id, Bookmark.target_type == "paper")
    )
    total = int(total_q.scalar_one() or 0)

    q = await db.execute(
        select(Bookmark, Paper)
        .join(Paper, Paper.id == Bookmark.target_id)
        .where(Bookmark.user_id == user.id, Bookmark.target_type == "paper")
        .order_by(Bookmark.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows: list[BookmarkedPaper] = []
    for bm, paper in q.all():
        rows.append(BookmarkedPaper(
            id=bm.id,
            target_id=bm.target_id,
            created_at=bm.created_at,
            title=paper.title,
            authors=_authors_names(paper.authors or []),
            date_submitted=paper.date_submitted,
            material_family=paper.material_family,
            status=paper.status,
            citation_count=paper.citation_count,
        ))
    return BookmarkedPapersResponse(total=total, results=rows)


@router.get("/materials", response_model=BookmarkedMaterialsResponse)
async def list_material_bookmarks(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
) -> BookmarkedMaterialsResponse:
    total_q = await db.execute(
        select(func.count()).select_from(Bookmark)
        .where(Bookmark.user_id == user.id, Bookmark.target_type == "material")
    )
    total = int(total_q.scalar_one() or 0)

    q = await db.execute(
        select(Bookmark, Material)
        .join(Material, Material.id == Bookmark.target_id)
        .where(Bookmark.user_id == user.id, Bookmark.target_type == "material")
        .order_by(Bookmark.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows: list[BookmarkedMaterial] = []
    for bm, mat in q.all():
        rows.append(BookmarkedMaterial(
            id=bm.id,
            target_id=bm.target_id,
            created_at=bm.created_at,
            formula=mat.formula,
            formula_latex=mat.formula_latex,
            family=mat.family,
            tc_max=mat.tc_max,
            tc_ambient=mat.tc_ambient,
            discovery_year=mat.discovery_year,
        ))
    return BookmarkedMaterialsResponse(total=total, results=rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _authors_names(authors: list) -> list[str]:
    """Flatten the authors JSONB blob to a list of plain strings.

    Papers store authors as either ``["Alice Smith", ...]`` or
    ``[{"name": "Alice Smith"}, ...]`` depending on ingestion source.
    This normalizes both so the dashboard can just render strings.
    """
    out: list[str] = []
    for a in authors:
        if isinstance(a, str):
            out.append(a)
        elif isinstance(a, dict):
            n = a.get("name") or a.get("family") or ""
            if n:
                out.append(str(n))
    return out
