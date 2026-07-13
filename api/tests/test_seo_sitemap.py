"""Sitemap inventory stays paginated, public, and payload-minimal."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from starlette.responses import Response

from routers.seo import sitemap_resources


class _Result:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one(self):
        return self.scalar

    def all(self):
        return self.rows


class _Session:
    def __init__(self, results):
        self.results = iter(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return next(self.results)


@pytest.mark.asyncio
async def test_paper_inventory_selects_only_id_and_update_time():
    updated = datetime(2026, 7, 13, tzinfo=UTC)
    db = _Session(
        [
            _Result(scalar=1),
            _Result(rows=[SimpleNamespace(id="arxiv:2607.00001", updated_at=updated)]),
        ]
    )
    response = Response()

    page = await sitemap_resources(
        response=response,
        kind="paper",
        limit=100,
        offset=0,
        db=db,  # type: ignore[arg-type]
    )

    assert page.total == 1
    assert page.results[0].id == "arxiv:2607.00001"
    sql = str(db.statements[1])
    assert "papers.id" in sql and "papers.updated_at" in sql
    assert "papers.abstract" not in sql and "materials_extracted" not in sql
    assert response.headers["cache-control"].startswith("public")


@pytest.mark.asyncio
async def test_material_inventory_applies_public_quality_filters():
    db = _Session([_Result(scalar=0), _Result(rows=[])])
    page = await sitemap_resources(
        response=Response(),
        kind="material",
        limit=10_000,
        offset=20_000,
        db=db,  # type: ignore[arg-type]
    )

    assert page.offset == 20_000
    sql = str(db.statements[1])
    assert "materials.needs_review IS false" in sql
    assert "materials.total_papers >" in sql
    assert "provenance_quarantine_nims" in repr(db.statements[1].compile().params)
