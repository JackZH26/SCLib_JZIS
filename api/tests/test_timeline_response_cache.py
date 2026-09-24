"""Real epoch invalidation and single-flight Timeline response regression tests."""
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text

from routers import timeline as routes
from services.catalogue_cache import BoundedResponseCache
from tests.test_material_source_scope_ordering import material_row


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(routes, "_timeline_pages", BoundedResponseCache())
    monkeypatch.setattr(routes, "_timeline_build_lock", asyncio.Lock())


@pytest.mark.parametrize("change", ["record", "hold", "paper", "parent", "work", "map", "display", "insert", "delete"])
async def test_cache_rechecks_committed_dependencies_before_etag(client, db_session, monkeypatch, change):
    from models.db import PaperWorkMap, Work
    family = "timeline_cache_" + uuid4().hex[:12]
    row = await material_row(db_session, family=family, label="subject", tc=30, old_tc=30, source_count=1)
    parent = await material_row(db_session, family=family + "_p", label="parent", tc=20, old_tc=20, source_count=1)
    row.parent_material_id = parent.id
    work = Work(canonical_title="Synthetic timeline cache test", publication_status="active")
    db_session.add(work)
    await db_session.flush()
    link = PaperWorkMap(paper_id=row.records[0]["paper_id"], work_id=work.id,
        match_method="manual", review_status="pending" if change == "map" else "accepted")
    db_session.add(link)
    if change == "map":
        work.publication_status = "retracted"
    await db_session.commit()
    params = {"family": family, "max_points": 2000, "compact": True}
    first = await client.get("/v1/timeline", params=params)
    assert first.status_code == 200 and len(first.json()["points"]) == 1
    assert first.headers["x-timeline-cache"] == "MISS"
    warm = await client.get("/v1/timeline", params=params)
    assert warm.json() == first.json() and warm.headers["x-timeline-cache"] == "HIT"
    if change == "record":
        row.records = [{**row.records[0], "tc_kelvin": 12}]
    elif change == "hold":
        row.needs_review = True
    elif change == "paper":
        await db_session.execute(text("UPDATE papers SET status='retracted' WHERE id=:id"), {"id": row.records[0]["paper_id"]})
    elif change == "parent":
        parent.needs_review = True
    elif change == "work":
        work.publication_status = "retracted"
    elif change == "map":
        link.review_status = "accepted"
    elif change == "display":
        await db_session.execute(text("UPDATE materials SET formula='Nb changed' WHERE id=:id"), {"id": row.id})
    elif change == "insert":
        await material_row(db_session, family=family, label="new", tc=10, old_tc=10, source_count=1)
    elif change == "delete":
        await db_session.delete(row)
    await db_session.commit()
    changed = await client.get("/v1/timeline", params=params, headers={"If-None-Match": first.headers["etag"]})
    assert changed.status_code == 200 and changed.json() != first.json()
    assert changed.headers["x-timeline-cache"] == "MISS"
    monkeypatch.setattr(routes, "_timeline_pages", BoundedResponseCache())
    fresh = await client.get("/v1/timeline", params=params)
    assert fresh.json() == changed.json()


async def test_mutation_during_build_is_not_cached(client, db_session, monkeypatch):
    family = "timeline_race_" + uuid4().hex[:12]
    row = await material_row(db_session, family=family, label="subject", tc=30, old_tc=30, source_count=1)
    original = routes._build_timeline_fallback
    async def mutate(**kwargs):
        result = await original(**kwargs)
        await db_session.execute(text("UPDATE papers SET status='retracted' WHERE id=:id"), {"id": row.records[0]["paper_id"]})
        await db_session.commit()
        return result
    monkeypatch.setattr(routes, "_build_timeline_fallback", mutate)
    response = await client.get("/v1/timeline", params={"family": family})
    assert response.status_code == 503 and response.headers["retry-after"] == "1"
    assert not routes._timeline_pages.entries


async def test_simultaneous_cold_reads_share_one_build(client, db_session, monkeypatch):
    family = "timeline_coalesce_" + uuid4().hex[:12]
    await material_row(db_session, family=family, label="subject", tc=30, old_tc=30, source_count=1)
    original = routes._build_timeline_fallback
    calls = []
    async def slow(**kwargs):
        calls.append(True)
        await asyncio.sleep(0.05)
        return await original(**kwargs)
    monkeypatch.setattr(routes, "_build_timeline_fallback", slow)
    responses = await asyncio.gather(*(client.get("/v1/timeline", params={"family": family}) for _ in range(3)))
    assert all(response.status_code == 200 for response in responses)
    assert len(calls) == 1 and all(response.json() == responses[0].json() for response in responses)
