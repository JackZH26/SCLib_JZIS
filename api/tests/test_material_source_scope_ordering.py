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


@pytest.mark.asyncio
async def test_only_returned_page_rows_build_complete_public_evidence_envelopes(client, db_session, monkeypatch):
    import routers.materials as material_router

    family, rows = await ordered_fixture(db_session)
    original = material_router.MaterialSummary.model_validate
    hydrated = []

    def validate(value, *args, **kwargs):
        hydrated.append(value.id)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(material_router.MaterialSummary, "model_validate", staticmethod(validate))
    response = await client.get("/v1/materials", params={
        "family": family, "sort": "tc_max", "offset": 1, "limit": 1,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 5 and body["results"][0]["id"] == rows["c"].id
    assert body["results"][0]["tc_max"] == 60
    assert body["results"][0]["property_evidence"]["evidence_scope"] == "selected_only"
    assert hydrated == [rows["c"].id]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", (
    "raw_records", "display_field", "material_hold", "paper_hold", "parent_hold",
    "work_hold", "accepted_work_map", "insert_material", "delete_material",
))
async def test_cached_pages_follow_actual_committed_catalogue_dependencies(client, db_session, monkeypatch, change):
    import routers.materials as routes
    from models.db import PaperWorkMap, Work
    from sqlalchemy import text

    monkeypatch.setattr(routes, "_material_pages", routes._MaterialPageCache())
    family = f"cache_{uuid4().hex[:12]}"
    row = await material_row(db_session, family=family, label="subject", tc=30, old_tc=30, source_count=1)
    parent = await material_row(db_session, family=family + "_parent", label="parent", tc=20, old_tc=20, source_count=1)
    row.parent_material_id = parent.id
    paper_id = row.records[0]["paper_id"]
    work = Work(canonical_title="Synthetic page-cache invalidation fixture", publication_status="active")
    db_session.add(work)
    await db_session.flush()
    link = PaperWorkMap(paper_id=paper_id, work_id=work.id, match_method="manual",
                        review_status="pending" if change == "accepted_work_map" else "accepted")
    db_session.add(link)
    if change == "accepted_work_map":
        work.publication_status = "retracted"
    await db_session.commit()
    calls = []
    original = routes._current_sort_value

    def counted(*args):
        calls.append(args[0].id)
        return original(*args)

    monkeypatch.setattr(routes, "_current_sort_value", counted)
    params = {"family": family, "limit": 3}
    first = await client.get("/v1/materials", params=params)
    assert first.status_code == 200 and first.json()["total"] == 1
    assert calls == [row.id]
    calls.clear()
    warm = await client.get("/v1/materials", params=params)
    assert warm.status_code == 200 and warm.json() == first.json()
    assert calls == [], "An unchanged transaction revision should reuse the exact page"
    if change == "raw_records":
        row.records = [{**row.records[0], "tc_kelvin": 12}]
    elif change == "display_field":
        # A direct SQL update need not change updated_at. The statement trigger
        # must still invalidate, so timestamps alone are not cache authority.
        await db_session.execute(text("UPDATE materials SET formula='Nb synthetic revision' WHERE id=:id"), {"id": row.id})
    elif change == "material_hold":
        row.needs_review = True
    elif change == "paper_hold":
        await db_session.execute(text("UPDATE papers SET status='retracted' WHERE id=:id"), {"id": paper_id})
    elif change == "parent_hold":
        parent.needs_review = True
    elif change == "work_hold":
        work.publication_status = "retracted"
    elif change == "accepted_work_map":
        link.review_status = "accepted"
    elif change == "insert_material":
        await material_row(db_session, family=family, label="added", tc=60, old_tc=60, source_count=1)
    elif change == "delete_material":
        await db_session.delete(row)
    await db_session.commit()
    changed = await client.get("/v1/materials", params=params)
    assert changed.status_code == 200, changed.text
    assert changed.json() != first.json()
    # Compare the complete cached-path result to a fresh unpopulated cache.
    monkeypatch.setattr(routes, "_material_pages", routes._MaterialPageCache())
    monkeypatch.setattr(routes, "_material_rankings", routes._MaterialPageCache())
    uncached = await client.get("/v1/materials", params=params)
    assert uncached.status_code == 200 and uncached.json() == changed.json()


@pytest.mark.asyncio
async def test_page_cache_does_not_publish_a_read_spanning_source_change(client, db_session, monkeypatch):
    import routers.materials as routes
    from sqlalchemy import text

    monkeypatch.setattr(routes, "_material_pages", routes._MaterialPageCache())
    family = f"cache_race_{uuid4().hex[:12]}"
    row = await material_row(db_session, family=family, label="subject", tc=30, old_tc=30, source_count=1)
    original = routes.prepare_material_views
    changed = False

    async def interleaved(*args, **kwargs):
        nonlocal changed
        result = await original(*args, **kwargs)
        if not changed:
            changed = True
            await db_session.execute(text("UPDATE papers SET status='retracted' WHERE id=:id"),
                                     {"id": row.records[0]["paper_id"]})
            await db_session.commit()
        return result

    monkeypatch.setattr(routes, "prepare_material_views", interleaved)
    response = await client.get("/v1/materials", params={"family": family})
    assert response.status_code == 503 and response.headers["retry-after"] == "1"
    assert "no-store" in response.headers["cache-control"]
    assert not routes._material_pages.entries
    retry = await client.get("/v1/materials", params={"family": family})
    assert retry.status_code == 200 and retry.json()["total"] == 0


@pytest.mark.asyncio
async def test_page_cache_rejects_private_transactions_and_old_snapshot_isolation(db_session):
    from routers.materials import _material_page_revision
    from sqlalchemy import text

    assert await _material_page_revision(db_session) is not None
    await db_session.execute(text("SELECT pg_current_xact_id()"))
    assert await _material_page_revision(db_session) is None
    await db_session.rollback()
    await db_session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    assert await _material_page_revision(db_session) is None
    await db_session.rollback()
    assert await _material_page_revision(db_session) is not None


@pytest.mark.asyncio
async def test_cached_page_key_includes_filters_pagination_and_policy_year(client, db_session, monkeypatch):
    import routers.materials as routes
    from datetime import datetime as actual_datetime

    monkeypatch.setattr(routes, "_material_pages", routes._MaterialPageCache())
    family, _ = await ordered_fixture(db_session)
    variants = ({}, {"offset": 1}, {"limit": 1}, {"sort": "total_papers"},
                {"tc_min": 40}, {"include_pending": True}, {"min_papers": 3})
    for extra in variants:
        params = {"family": family, **extra}
        cold = await client.get("/v1/materials", params=params)
        warm = await client.get("/v1/materials", params=params)
        assert cold.status_code == warm.status_code == 200 and cold.json() == warm.json()
    assert len(routes._material_pages.entries) == len(variants)
    year = actual_datetime.now(routes.UTC).year + 1
    monkeypatch.setattr(routes, "datetime", SimpleNamespace(now=lambda tz: actual_datetime(year, 1, 1, tzinfo=tz)))
    assert (await client.get("/v1/materials", params={"family": family})).status_code == 200
    assert len(routes._material_pages.entries) == len(variants) + 1


def test_page_cache_limits_serialized_bytes_and_entry_count():
    from routers.materials import _MaterialPageCache

    cache = _MaterialPageCache(max_bytes=12, max_entries=2)
    cache.put((1, b"a"), b"1234")
    cache.put((2, b"b"), b"5678")
    assert cache.size == 10
    assert cache.get((1, b"a")) == b"1234"
    cache.put((3, b"c"), b"abcd")
    assert cache.get((2, b"b")) is None and cache.size == 10
    cache.put((1, b"a"), b"xyz")
    assert cache.size == 9
    cache.put((4, b"oversize"), b"payload too large")
    assert len(cache.entries) == 2 and cache.size == 9


@pytest.mark.asyncio
@pytest.mark.parametrize("sort", ("tc_max", "tc_ambient", "total_papers", "arxiv_year"))
async def test_new_pages_reuse_ranking_and_hydrate_only_the_page(client, db_session, monkeypatch, sort):
    import routers.materials as routes

    family, _ = await ordered_fixture(db_session)
    params = {"family": family, "sort": sort}
    calls, hydrated = [], []
    original_sort, original_prepare = routes._current_sort_value, routes.prepare_material_views

    def counted(material, field):
        calls.append(material.id)
        return original_sort(material, field)

    async def prepared(db, materials):
        hydrated.extend(row.id for row in materials)
        return await original_prepare(db, materials)

    monkeypatch.setattr(routes, "_current_sort_value", counted)
    monkeypatch.setattr(routes, "prepare_material_views", prepared)
    first = await client.get("/v1/materials", params={**params, "limit": 1})
    assert first.status_code == 200 and len(calls) == len(hydrated) == 5
    calls.clear()
    hydrated.clear()
    page = await client.get("/v1/materials", params={**params, "offset": 1, "limit": 2})
    assert page.status_code == 200 and page.json()["total"] == 5
    assert not calls and set(hydrated) == {row["id"] for row in page.json()["results"]}
    assert len(hydrated) == 2
    assert page.headers["cache-control"] == "private, no-store"
    assert page.headers["x-materials-cache"] == "MISS"
    repeat = await client.get("/v1/materials", params={**params, "offset": 1, "limit": 2})
    assert repeat.content == page.content and repeat.headers["x-materials-cache"] == "HIT"
    assert len(hydrated) == 2
    # The full raw scan must produce exactly the same response bytes, including
    # matched records, source governance, null sorting and tied-ID order.
    monkeypatch.setattr(routes, "_material_pages", routes._MaterialPageCache())
    monkeypatch.setattr(routes, "_material_rankings", routes._MaterialPageCache())
    reference = await client.get("/v1/materials", params={**params, "offset": 1, "limit": 2})
    assert reference.content == page.content
    assert len(calls) == 5


@pytest.mark.asyncio
async def test_ranking_does_not_reuse_matches_for_different_filters(client, db_session):
    family, rows = await ordered_fixture(db_session)
    cases = (
        ({}, "bcaed"), ({"tc_min": 40}, "bc"),
        ({"min_papers": 4}, "d"), ({"pressure_min": 1}, ""),
        ({"knowledge_origin": "Computed"}, ""),
        ({"has_competing_order": True}, ""), ({"only_aps": True}, ""),
    )
    for extra, labels in cases:
        first = await client.get("/v1/materials", params={"family": family, "limit": 1, **extra})
        second = await client.get("/v1/materials", params={"family": family, "offset": 1, "limit": 4, **extra})
        assert first.status_code == second.status_code == 200
        assert first.json()["total"] == second.json()["total"] == len(labels)
        assert [row["id"] for row in first.json()["results"] + second.json()["results"]] == [rows[label].id for label in labels]


@pytest.mark.asyncio
async def test_concurrent_cold_pages_share_one_scan(client, db_session, monkeypatch):
    import asyncio
    import routers.materials as routes

    family, rows = await ordered_fixture(db_session)
    calls = []
    original = routes._current_sort_value

    def counted(material, field):
        calls.append(material.id)
        return original(material, field)

    monkeypatch.setattr(routes, "_current_sort_value", counted)
    responses = await asyncio.gather(*(client.get("/v1/materials", params={
        "family": family, "limit": 1, "offset": offset,
    }) for offset in (0, 1, 2)))
    assert all(response.status_code == 200 for response in responses)
    assert [response.json()["results"][0]["id"] for response in responses] == [rows[key].id for key in "bca"]
    assert len(calls) == 5
    assert not routes._material_build_locks


@pytest.mark.asyncio
async def test_ranking_hit_rejects_a_source_change_during_page_hydration(client, db_session, monkeypatch):
    import routers.materials as routes
    from sqlalchemy import text

    family, rows = await ordered_fixture(db_session)
    first = await client.get("/v1/materials", params={"family": family, "limit": 1})
    assert first.status_code == 200
    original = routes.prepare_material_views
    changed = False

    async def interleaved(*args, **kwargs):
        nonlocal changed
        result = await original(*args, **kwargs)
        if not changed:
            changed = True
            await db_session.execute(text("UPDATE materials SET needs_review=true WHERE id=:id"), {"id": rows["c"].id})
            await db_session.commit()
        return result

    monkeypatch.setattr(routes, "prepare_material_views", interleaved)
    params = {"family": family, "offset": 1, "limit": 1}
    raced = await client.get("/v1/materials", params=params)
    assert raced.status_code == 503 and raced.headers["retry-after"] == "1"
    retry = await client.get("/v1/materials", params=params)
    assert retry.status_code == 200 and retry.json()["total"] == 4
    assert retry.json()["results"][0]["id"] == rows["a"].id


@pytest.mark.asyncio
async def test_unselected_material_update_invalidates_order_for_unvisited_pages(client, db_session):
    family, rows = await ordered_fixture(db_session)
    first = await client.get("/v1/materials", params={"family": family, "limit": 1})
    assert first.status_code == 200 and first.json()["results"][0]["id"] == rows["b"].id
    # Use the current source-scoped values: changing a legacy raw record alone
    # can legitimately disagree with its frozen legacy summary selection.
    rows["a"].records = [record if index == 0 else {**record, "tc_kelvin": 70}
                         for index, record in enumerate(rows["a"].records)]
    await db_session.commit()
    next_page = await client.get("/v1/materials", params={"family": family, "limit": 1, "offset": 1})
    assert next_page.status_code == 200 and next_page.json()["results"][0]["id"] == rows["b"].id
    current_first = await client.get("/v1/materials", params={"family": family, "limit": 1})
    assert current_first.status_code == 200 and current_first.json()["results"][0]["id"] == rows["a"].id


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", ("_MAX_RANKED_MATERIALS", "_MAX_RANKING_BYTES"))
async def test_oversized_ranking_falls_back_to_bounded_page_scan(client, db_session, monkeypatch, budget):
    import routers.materials as routes

    monkeypatch.setattr(routes, "_material_rankings", routes._MaterialPageCache())
    monkeypatch.setattr(routes, budget, 2)
    family, rows = await ordered_fixture(db_session)
    for offset, label in enumerate("bc"):
        result = await client.get("/v1/materials", params={"family": family, "offset": offset, "limit": 1})
        assert result.status_code == 200 and result.json()["total"] == 5
        assert result.json()["results"][0]["id"] == rows[label].id
    assert not routes._material_rankings.entries
