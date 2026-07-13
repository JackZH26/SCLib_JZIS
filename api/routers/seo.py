"""Low-payload public resource inventory for search-engine sitemaps."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import Material, Paper
from models.search import SitemapResource, SitemapResourcePage

router = APIRouter(tags=["seo"])


@router.get("/sitemap/resources", response_model=SitemapResourcePage)
async def sitemap_resources(
    response: Response,
    kind: Literal["paper", "material"] = Query(...),
    limit: int = Query(10_000, ge=1, le=10_000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> SitemapResourcePage:
    """Return only stable IDs and update times, never paper/material payloads."""

    if kind == "paper":
        model = Paper
        filters = (Paper.status == "published",)
    else:
        model = Material
        filters = (
            or_(
                Material.review_reason.is_(None),
                Material.review_reason != "provenance_quarantine_nims",
            ),
            Material.needs_review.is_(False),
            Material.total_papers > 0,
            or_(Material.retracted.is_(False), Material.retracted.is_(None)),
        )

    total_stmt = select(func.count()).select_from(model).where(*filters)
    rows_stmt = (
        select(model.id, model.updated_at)
        .where(*filters)
        .order_by(model.id)
        .limit(limit)
        .offset(offset)
    )
    total = (await db.execute(total_stmt)).scalar_one()
    rows = (await db.execute(rows_stmt)).all()
    response.headers["Cache-Control"] = "public, max-age=300, s-maxage=3600"
    return SitemapResourcePage(
        total=total,
        limit=limit,
        offset=offset,
        results=[
            SitemapResource(kind=kind, id=row.id, updated_at=row.updated_at)
            for row in rows
        ],
    )
