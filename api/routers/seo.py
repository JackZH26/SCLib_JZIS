"""Low-payload public resource inventory for search-engine sitemaps."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import Material, Paper
from models.search import SitemapResource, SitemapResourcePage
from services.material_visibility import visibility_allows_view
from services.material_visibility_adapter import material_prefilter, prepare_material_views

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
    response.headers["Cache-Control"] = "private, no-store"

    if kind == "material":
        stmt = select(Material).where(*material_prefilter(), Material.total_papers > 0).order_by(Material.id)
        stream = await db.stream_scalars(stmt.execution_options(yield_per=128))
        total, results = 0, []
        try:
            async for batch in stream.partitions(128):
                for material in await prepare_material_views(db, batch):
                    if not visibility_allows_view(material.visibility):
                        continue
                    if offset <= total < offset + limit:
                        results.append(SitemapResource(kind=kind, id=material.id, updated_at=material.updated_at))
                    total += 1
        finally:
            await stream.close()
        return SitemapResourcePage(total=total, limit=limit, offset=offset, results=results)

    if kind == "paper":
        model = Paper
        filters = (Paper.status == "published",)

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
    return SitemapResourcePage(
        total=total,
        limit=limit,
        offset=offset,
        results=[
            SitemapResource(kind=kind, id=row.id, updated_at=row.updated_at)
            for row in rows
        ],
    )
