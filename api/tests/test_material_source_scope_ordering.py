"""Current public ordering over real SQL source scopes; disposable API only."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from models.db import Material, Paper, get_session_factory
from models.search import MaterialListResponse


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        try:
            yield session
        finally:
            await session.rollback()
            identifiers = session.info.get("scope_order_materials", [])
            if identifiers:
                await session.execute(delete(Material).where(Material.id.in_(identifiers)))
                await session.commit()


async def material_row(session, *, family, label, tc, old_tc, source_count,
                       old_count=None, scoped=False, year=2025):
    """Synthetic raw source records; a real lifecycle update holds one source."""
    papers, records = [], []
    for index in range(source_count + int(scoped)):
        paper = Paper(id=f"{family}:{label}:paper:{index}", source="arxiv", status="published",
                      title="Synthetic current-ordering fixture", authors=[],
                      abstract="Synthetic test data, not scientific evidence.")
        session.add(paper)
        papers.append(paper)
        records.append({"paper_id": paper.id, "formula": "Nb", "family": family,
                        "tc_kelvin": 120 if scoped and index == 0 else tc,
                        "pressure_gpa": 0, "pressure_condition": "ambient pressure", "knowledge_origin": "Observed",
                        "measurement": "resistivity", "year": 2025})
    row = Material(id=f"mat:{family}:{label}", formula="Nb", formula_normalized=f"{family}:{label}",
                   family=family, records=deepcopy(records), status="active_research", needs_review=False,
                   tc_max=old_tc, tc_max_experimental=old_tc, tc_max_theoretical=None,
                   tc_ambient=old_tc, total_papers=source_count if old_count is None else old_count,
                   arxiv_year=year)
    session.add(row)
    session.info.setdefault("scope_order_materials", []).append(row.id)
    await session.commit()
    if scoped:
        papers[0].status = "retracted"
        await session.commit()
    return row


async def ordered_fixture(session):
    family = f"scope_order_{uuid4().hex[:12]}"
    rows = {}
    for label, tc, old_tc, count, old_count, scoped, year in (
        ("a", 30, 120, 2, 99, True, 2030),
        ("b", 60, 20, 3, 1, True, 2020),
        ("c", 60, 90, 3, 8, True, 2026),
        ("d", 20, None, 4, 4, False, 2025),
        ("e", 10, 10, 1, 1, False, 2020),
    ):
        rows[label] = await material_row(session, family=family, label=label, tc=tc,
            old_tc=old_tc, source_count=count, old_count=old_count, scoped=scoped, year=year)
    return family, rows


@pytest.mark.asyncio
@pytest.mark.parametrize("sort,labels,values", (
    ("tc_max", "bcaed", [60, 60, 30, 10, None]),
    ("tc_ambient", "bcaed", [60, 60, 30, 10, None]),
    ("arxiv_year", "deabc", [2025, 2020, None, None, None]),
    ("total_papers", "dbcae", [4, 3, 3, 2, 1]),
))
async def test_current_values_order_before_pagination_with_nulls_and_id_ties(client, db_session, sort, labels, values):
    family, rows = await ordered_fixture(db_session)
    expected = [rows[label].id for label in labels]
    original = {key: (row.tc_max, row.tc_ambient, row.total_papers, row.arxiv_year,
                      deepcopy(row.records), row.updated_at) for key, row in rows.items()}
    for offset, limit in ((0, 1), (1, 2), (3, 2), (5, 2), (0, 5)):
        response = await client.get("/v1/materials", params={"family": family, "sort": sort,
                                    "offset": offset, "limit": limit})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["sort_basis"] == "current_projected_catalogue"
        assert body["total"] == 5 and body["offset"] == offset and body["limit"] == limit
        assert [item["id"] for item in body["results"]] == expected[offset:offset + limit]
        assert [item[sort] for item in body["results"]] == values[offset:offset + limit]
        assert all(item["visibility"]["scientific_acceptance"] is False for item in body["results"])
    for key, row in rows.items():
        await db_session.refresh(row)
        assert (row.tc_max, row.tc_ambient, row.total_papers, row.arxiv_year,
                row.records, row.updated_at) == original[key]


@pytest.mark.asyncio
async def test_held_120_does_not_outrank_current_60_at_limit_one(client, db_session):
    family = f"scope_rank_{uuid4().hex[:12]}"
    held = await material_row(db_session, family=family, label="a", tc=30, old_tc=120,
                              source_count=1, scoped=True)
    current = await material_row(db_session, family=family, label="b", tc=60, old_tc=60,
                                 source_count=1)
    response = await client.get("/v1/materials", params={"family": family, "limit": 1})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
    assert [(item["id"], item["tc_max"]) for item in response.json()["results"]] == [(current.id, 60)]
    second = await client.get("/v1/materials", params={"family": family, "offset": 1, "limit": 1})
    assert second.status_code == 200, second.text
    assert [(item["id"], item["tc_max"]) for item in second.json()["results"]] == [(held.id, 30)]


@pytest.mark.asyncio
async def test_zero_legacy_count_is_not_a_scoped_skeleton_but_v1_zero_stays_opt_in(client, db_session):
    family = f"scope_zero_{uuid4().hex[:12]}"
    scoped = await material_row(db_session, family=family, label="scoped", tc=30, old_tc=120,
                                source_count=2, old_count=0, scoped=True)
    legacy = await material_row(db_session, family=family, label="legacy", tc=50, old_tc=50,
                                source_count=1, old_count=0)
    for extra in ({}, {"min_papers": 2}):
        response = await client.get("/v1/materials", params={"family": family, **extra})
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1
        assert [(item["id"], item["total_papers"]) for item in response.json()["results"]] == [(scoped.id, 2)]
    too_many = await client.get("/v1/materials", params={"family": family, "min_papers": 3})
    assert too_many.status_code == 200 and too_many.json()["total"] == 0
    archive = await client.get("/v1/materials", params={"family": family, "include_skeletons": True})
    assert archive.status_code == 200, archive.text
    assert archive.json()["total"] == 2
    counts = {item["id"]: item["total_papers"] for item in archive.json()["results"]}
    assert counts == {scoped.id: 2, legacy.id: 0}


@pytest.mark.asyncio
async def test_heap_retains_only_the_requested_window_and_keeps_same_record_filters(client, db_session, monkeypatch):
    import routers.materials as material_router

    family, rows = await ordered_fixture(db_session)
    heap_lengths = []
    actual_heap = material_router.heapq

    def push(heap, value):
        actual_heap.heappush(heap, value)
        heap_lengths.append(len(heap))

    def replace(heap, value):
        actual_heap.heapreplace(heap, value)
        heap_lengths.append(len(heap))

    monkeypatch.setattr(material_router, "heapq", SimpleNamespace(heappush=push, heapreplace=replace))
    response = await client.get("/v1/materials", params={"family": family, "sort": "tc_max", "offset": 1, "limit": 1})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 5 and response.json()["results"][0]["id"] == rows["c"].id
    assert heap_lengths and max(heap_lengths) == 2
    # Ranking is not a reason to re-admit a held source into scientific matches.
    excluded = await client.get("/v1/materials", params={"family": family, "tc_min": 100})
    assert excluded.status_code == 200 and excluded.json()["total"] == 0


def test_sort_basis_defaults_current_while_accepting_explicit_historical_responses():
    fields = {"total": 0, "results": [], "limit": 1, "offset": 0}
    assert MaterialListResponse(**fields).sort_basis == "current_projected_catalogue"
    assert MaterialListResponse(**fields, sort_basis="legacy_catalogue").sort_basis == "legacy_catalogue"
