"""Request timing isolation and real SQL cache paths on owned services only."""
from __future__ import annotations

import asyncio
import inspect
import re
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

import routers.materials as routes
from models.db import Material, Paper, get_session_factory
from models.search import MaterialListResponse
from services import material_list_timing as timing


def parsed_header(response):
    parts = response.headers["server-timing"].split(", ")
    assert len(parts) <= len(timing.STAGES) + 1
    path = re.fullmatch(r'materials_path;desc="([a-z_]+)"', parts[0]).group(1)
    assert path in timing.PATHS
    stages = {}
    for part in parts[1:]:
        match = re.fullmatch(r"([a-z_]+);dur=(\d+\.\d{3})", part)
        assert match is not None, part
        name, value = match.groups()
        assert name in timing.STAGES and name not in stages
        stages[name] = float(value)
    assert "total" in stages
    # Stage totals are disjoint except for `total`; allow rounding to 0.001 ms.
    assert sum(value for name, value in stages.items() if name != "total") <= stages["total"] + .02
    return path, stages


@pytest.fixture(autouse=True)
def fresh_caches(monkeypatch):
    monkeypatch.setattr(routes, "_material_pages", routes._MaterialPageCache())
    monkeypatch.setattr(routes, "_material_rankings", routes._MaterialPageCache())
    assert timing._current.get() is None


@pytest_asyncio.fixture(loop_scope="function")
async def inventory():
    family = "timing_" + uuid4().hex[:12]
    async with get_session_factory()() as session:
        source = Paper(id=family + ":source", source="arxiv", status="published",
                       title="Synthetic timing fixture", authors=[], abstract="Synthetic only")
        session.add(source)
        session.add_all([
            Material(id=f"mat:{family}:{index}", formula="Nb", formula_normalized=f"{family}:{index}",
                     family=family, status="active_research", needs_review=False, total_papers=1,
                     tc_max=30 + index, tc_max_experimental=30 + index,
                     records=[{"paper_id": source.id, "tc_kelvin": 30 + index, "family": family,
                               "knowledge_origin": "Observed", "measurement": "resistivity",
                               "pressure_gpa": 0, "pressure_condition": "ambient pressure"}])
            for index in range(4)
        ])
        await session.commit()
        try:
            yield family, session, source
        finally:
            await session.rollback()
            await session.execute(delete(Material).where(Material.family == family))
            await session.commit()


@pytest.mark.asyncio
async def test_real_scan_page_hit_ranking_and_lifecycle_invalidation(client, inventory):
    family, writer, source = inventory
    params = {"family": family, "sort": "total_papers", "limit": 2}
    cold = await client.get("/v1/materials", params=params)
    assert cold.status_code == 200, cold.text
    path, stages = parsed_header(cold)
    assert path == "scan" and cold.headers["x-materials-cache"] == "MISS"
    assert {"revision", "lock_wait", "scan_fetch", "scope", "selection", "scan_close",
            "projection", "ranking_publish", "serialization"} <= stages.keys()
    warm = await client.get("/v1/materials", params=params)
    assert warm.content == cold.content
    assert parsed_header(warm)[0] == "page_hit"
    assert set(parsed_header(warm)[1]) == {"revision", "total"}
    assert warm.headers["x-materials-cache"] == "HIT"
    assert warm.headers["server-timing"] != cold.headers["server-timing"]
    adjacent = await client.get("/v1/materials", params={**params, "offset": 2})
    assert adjacent.status_code == 200 and adjacent.json()["total"] == 4
    path, stages = parsed_header(adjacent)
    assert path == "ranking" and "ranking_page" in stages and "scan_fetch" not in stages
    assert adjacent.headers["x-materials-cache"] == "MISS"
    assert set(row["id"] for row in adjacent.json()["results"]).isdisjoint(
        row["id"] for row in cold.json()["results"])
    source.status = "retracted"
    await writer.commit()
    held = await client.get("/v1/materials", params=params)
    assert held.status_code == 200 and held.json()["total"] == 0
    assert parsed_header(held)[0] == "scan", "Timing must not hide a stale lifecycle cache replay"
    assert not cold.json()["results"][0]["visibility"]["scientific_acceptance"]


@pytest.mark.asyncio
async def test_refusal_does_not_replay_warm_timing_or_body(client, inventory):
    family, _, _ = inventory
    good = await client.get("/v1/materials", params={"family": family, "limit": 2})
    assert good.status_code == 200
    refused = await client.get("/v1/materials", params=[("family", family), ("q", "Nb"), ("q", "MgB2")])
    assert refused.status_code == 422
    assert "server-timing" not in refused.headers and "x-materials-cache" not in refused.headers
    assert timing._current.get() is None


@pytest.mark.asyncio
async def test_revision_conflict_keeps_refusal_and_releases_context(client, inventory, monkeypatch):
    family, writer, source = inventory
    original = routes.prepare_material_views

    async def interleave(session, rows, **kwargs):
        views = await original(session, rows, **kwargs)
        source.status = "retracted"
        await writer.commit()
        return views

    monkeypatch.setattr(routes, "prepare_material_views", interleave)
    refused = await client.get("/v1/materials", params={"family": family, "limit": 2})
    assert refused.status_code == 503 and refused.headers["retry-after"] == "1"
    assert "no-store" in refused.headers["cache-control"]
    assert "server-timing" not in refused.headers
    assert not routes._material_pages.entries and not routes._material_rankings.entries
    assert timing._current.get() is None


@pytest.mark.asyncio
async def test_cancelled_real_scan_closes_sql_stream_and_memo(inventory, monkeypatch):
    family, session, _ = inventory
    streams, memos = [], []
    original_stream, original_views = AsyncSession.stream_scalars, routes.prepare_material_views

    async def capture_stream(self, *args, **kwargs):
        stream = await original_stream(self, *args, **kwargs)
        streams.append(stream)
        return stream

    async def cancel_scan(self, rows, **kwargs):
        memos.append(kwargs["lifecycle_memo"])
        await original_views(self, rows, **kwargs)
        raise asyncio.CancelledError()

    monkeypatch.setattr(AsyncSession, "stream_scalars", capture_stream)
    monkeypatch.setattr(routes, "prepare_material_views", cancel_scan)
    arguments = {}
    for name, parameter in inspect.signature(routes.list_materials).parameters.items():
        arguments[name] = (session if name == "db" else None if name in {"identity", "request"}
                           else getattr(parameter.default, "default", parameter.default))
    with pytest.raises(asyncio.CancelledError):
        await routes.list_materials(**{**arguments, "family": family, "limit": 2})
    assert len(streams) == 1 and streams[0].closed
    assert len(memos) == 1 and memos[0]._session is None and not memos[0]._entries
    assert not routes._material_pages.entries and not routes._material_rankings.entries
    assert timing._current.get() is None


def synthetic_builder(monkeypatch):
    """Control scheduling rather than asserting a machine-dependent latency."""
    entered, release, waiter = asyncio.Event(), asyncio.Event(), asyncio.Event()
    builds = []

    class ObservedLock(asyncio.Lock):
        async def acquire(self):
            if self.locked():
                waiter.set()
            return await super().acquire()

    class Locks(dict):
        def setdefault(self, key, default):
            if key not in self:
                self[key] = ObservedLock()
            return self[key]

    monkeypatch.setattr(routes, "_material_build_locks", Locks())

    async def revision(db, *, year):
        return ("synthetic-fixed-revision", year)

    monkeypatch.setattr(routes, "catalogue_revision", revision)

    @routes._cache_material_pages
    async def build(db, q=None, request=None, identity=None, limit=2, offset=0):
        builds.append(offset)
        timing.material_list_path("scan")
        with timing.material_list_stage("scope"):
            entered.set()
            await release.wait()
        return MaterialListResponse(total=0, results=[], limit=limit, offset=offset)

    return build, entered, release, waiter, builds


@pytest.mark.asyncio
async def test_waited_hit_reports_only_its_own_work(monkeypatch):
    build, entered, release, waiter, builds = synthetic_builder(monkeypatch)
    first = asyncio.create_task(build(db=object()))
    await asyncio.wait_for(entered.wait(), 2)
    second = asyncio.create_task(build(db=object()))
    await asyncio.wait_for(waiter.wait(), 2)
    release.set()
    cold, waited = await asyncio.gather(first, second)
    assert builds == [0] and cold.body == waited.body
    assert parsed_header(cold)[0] == "scan"
    path, stages = parsed_header(waited)
    assert path == "waited_hit" and "lock_wait" in stages and "scope" not in stages
    assert waited.headers["x-materials-cache"] == "HIT"
    assert timing._current.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", ("builder", "waiter"))
async def test_cancelled_request_releases_lock_and_timing(monkeypatch, cancel):
    build, entered, release, waiter, builds = synthetic_builder(monkeypatch)
    first = asyncio.create_task(build(db=object()))
    await asyncio.wait_for(entered.wait(), 2)
    second = asyncio.create_task(build(db=object()))
    await asyncio.wait_for(waiter.wait(), 2)
    cancelled, survivor = (first, second) if cancel == "builder" else (second, first)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    release.set()
    successful = await asyncio.wait_for(survivor, 2)
    assert parsed_header(successful)[0] == "scan"
    assert builds == ([0, 0] if cancel == "builder" else [0])
    fresh = await build(db=object())
    assert parsed_header(fresh)[0] == "page_hit"
    assert set(parsed_header(fresh)[1]) == {"revision", "total"}
    assert all(not lock.locked() for lock in routes._material_build_locks.values())
    assert timing._current.get() is None


def test_batch_times_accumulate_and_labels_cannot_use_source_data(monkeypatch):
    clock = iter([0., .1, .3, .4, .7, .9])
    monkeypatch.setattr(timing, "perf_counter", lambda: next(clock))
    with timing.material_list_request() as collected:
        with timing.material_list_stage("total"):
            with timing.material_list_stage("scope"):
                pass
            with timing.material_list_stage("scope"):
                pass
        assert collected.seconds["scope"] == pytest.approx(.5)
        assert collected.seconds["total"] == pytest.approx(.9)
        with pytest.raises(ValueError):
            timing.material_list_stage("paper:user-input").__enter__()
        with pytest.raises(ValueError):
            timing.material_list_path("query:user-input")
    assert timing._current.get() is None
