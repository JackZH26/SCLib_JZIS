"""Fenced request memo integration on newly owned PostgreSQL/Redis only."""
from __future__ import annotations

import inspect
from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, text

import routers.materials as routes
from models.db import Material, Paper, PaperWorkMap, Work, get_session_factory
from services import material_visibility_adapter as adapter
from services.source_lifecycle_status import lifecycle_revision


@pytest_asyncio.fixture(loop_scope="function")
async def inventory():
    family = f"memo_{uuid4().hex[:12]}"
    async with get_session_factory()() as session:
        papers = [Paper(id=f"{family}:{label}", source="arxiv", status="published",
                        title="Synthetic request memo fixture", authors=[], abstract="Synthetic only")
                  for label in ("active", "held")]
        works = [Work(canonical_title="Synthetic memo Work", publication_status="active") for _ in papers]
        session.add_all(papers + works)
        await session.flush()
        links = [PaperWorkMap(paper_id=paper.id, work_id=work.id,
                             match_method="manual", review_status="accepted")
                 for paper, work in zip(papers, works, strict=True)]
        session.add_all(links)
        records = [{"paper_id": identity, "formula": "Nb", "family": family,
                    "tc_kelvin": tc, "knowledge_origin": "Observed", "measurement": "resistivity",
                    "pressure_gpa": 0, "pressure_condition": "ambient pressure", "year": 2025}
                   for identity, tc in [(papers[0].id, 30), (papers[1].id, 90), (family + ":missing", 80)]]
        rows = [Material(id=f"mat:{family}:{index:03}", formula="Nb", formula_normalized=f"{family}:{index}",
                         family=family, records=deepcopy(records), status="active_research", needs_review=False,
                         tc_max=90, tc_max_experimental=90, tc_ambient=90, total_papers=3)
                for index in range(256)]
        session.add_all(rows)
        await session.commit()
        works[1].publication_status = "retracted"
        await session.commit()
        try:
            yield session, family, papers, works, links
        finally:
            await session.rollback()
            await session.execute(delete(Material).where(Material.family == family))
            await session.commit()


@pytest.fixture(autouse=True)
def fresh_caches(monkeypatch):
    monkeypatch.setattr(routes, "_material_pages", routes._MaterialPageCache())
    monkeypatch.setattr(routes, "_material_rankings", routes._MaterialPageCache())


def counted_resolver(monkeypatch):
    calls = []
    original = adapter.resolve_paper_lifecycle

    async def resolve(session, identifiers):
        result = await original(session, identifiers)
        calls.append((list(identifiers), deepcopy(result)))
        return result

    monkeypatch.setattr(adapter, "resolve_paper_lifecycle", resolve)
    return calls


@pytest.mark.asyncio
async def test_shared_sources_resolve_once_with_real_work_hold_and_byte_parity(client, inventory, monkeypatch):
    _, family, papers, _, _ = inventory
    calls = counted_resolver(monkeypatch)
    memos = []
    factory = routes.LifecycleReadMemo

    def capture(session):
        memo = factory(session)
        memos.append(memo)
        return memo

    monkeypatch.setattr(routes, "LifecycleReadMemo", capture)
    response = await client.get("/v1/materials", params={"family": family, "limit": 2})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 256
    assert [row["tc_max"] for row in response.json()["results"]] == [30, 30]
    assert len(calls) == 1 and len(calls[0][0]) == 3
    assert lifecycle_revision(calls[0][1][papers[1].id]) is not None
    assert calls[0][1][papers[1].id]["status"] == "published"
    assert family + ":missing" not in calls[0][1]
    assert len(memos) == 1 and not memos[0]._entries and memos[0]._session is None
    # Same fenced route and complete projector, with only memoization disabled.
    calls.clear()
    monkeypatch.setattr(routes, "_material_pages", routes._MaterialPageCache())
    monkeypatch.setattr(routes, "_material_rankings", routes._MaterialPageCache())
    monkeypatch.setattr(routes, "LifecycleReadMemo", lambda session: None)
    baseline = await client.get("/v1/materials", params={"family": family, "limit": 2})
    assert baseline.content == response.content
    assert len(calls) == 2 and calls[0] == calls[1]


def resolved_arguments(session, family):
    arguments = {}
    for key, parameter in inspect.signature(routes.list_materials).parameters.items():
        if key == "db":
            arguments[key] = session
        elif key in {"identity", "request"}:
            arguments[key] = None
        else:
            arguments[key] = getattr(parameter.default, "default", parameter.default)
    return {**arguments, "family": family, "limit": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("private_mode", ("write_transaction", "repeatable_read"))
async def test_noncacheable_scan_never_constructs_a_memo(inventory, monkeypatch, private_mode):
    session, family, _, _, _ = inventory
    calls = counted_resolver(monkeypatch)

    def forbidden(session):
        raise AssertionError("Noncacheable transaction must not create memo")

    monkeypatch.setattr(routes, "LifecycleReadMemo", forbidden)
    await session.execute(text("SELECT pg_current_xact_id()" if private_mode == "write_transaction"
                               else "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    assert await routes._material_page_revision(session) is None
    result = await routes.list_materials(**resolved_arguments(session, family))
    assert result.total == 256 and len(result.results) == 2
    assert len(calls) == 2 and calls[0] == calls[1]
    assert not routes._material_pages.entries and not routes._material_rankings.entries


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ("paper_hold", "work_hold", "accepted_map"))
async def test_between_batch_source_change_rejects_memo_and_all_cache_publication(client, inventory, monkeypatch, change):
    writer, family, papers, works, links = inventory
    if change == "accepted_map":
        links[0].review_status = "pending"
        works[0].publication_status = "retracted"
        await writer.commit()
    calls = counted_resolver(monkeypatch)
    original = routes.prepare_material_views
    batches = 0
    memos = []

    async def interleaved(session, materials, **kwargs):
        nonlocal batches
        views = await original(session, materials, **kwargs)
        batches += 1
        memos.append(kwargs.get("lifecycle_memo"))
        if batches == 1:
            if change == "paper_hold":
                papers[0].status = "retracted"
            elif change == "work_hold":
                works[0].publication_status = "retracted"
            else:
                links[0].review_status = "accepted"
            await writer.commit()
        return views

    monkeypatch.setattr(routes, "prepare_material_views", interleaved)
    response = await client.get("/v1/materials", params={"family": family, "limit": 2})
    assert response.status_code == 503 and response.headers["retry-after"] == "1"
    assert "no-store" in response.headers["cache-control"]
    assert batches == 2 and memos[0] is memos[1] and memos[0] is not None
    assert not memos[0]._entries and memos[0]._session is None
    assert len(calls) == 1, "Second batch exercised an old memo entry, so the fence must reject it"
    assert not routes._material_pages.entries and not routes._material_rankings.entries
    retry = await client.get("/v1/materials", params={"family": family, "limit": 2})
    assert retry.status_code == 200 and retry.json()["total"] == 0
