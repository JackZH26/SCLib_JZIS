"""Nested elapsed boundaries with real owned SQL and controlled scheduling.

The normal API conftest/disposable runner still owns PostgreSQL and Redis.
No model or database safety gate is substituted by these clock controls.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

from models.db import Material, Paper, PaperWorkMap, Work, get_session_factory
from services import material_list_timing as timing
from services import material_visibility_adapter as adapter
from services import source_lifecycle as lifecycle


@pytest_asyncio.fixture(loop_scope="function")
async def scope_rows():
    async with get_session_factory()() as db_session:
        suffix = uuid4().hex
        paper = Paper(id=f"timing:{suffix}", source="arxiv", status="published",
                      title="Synthetic timing fixture", authors=[], abstract="Synthetic only")
        work = Work(canonical_title="Synthetic timing Work", publication_status="active")
        db_session.add_all([paper, work])
        await db_session.flush()
        db_session.add(PaperWorkMap(paper_id=paper.id, work_id=work.id,
                                   match_method="manual", review_status="accepted"))
        record = {"paper_id": paper.id, "tc_kelvin": 30, "knowledge_origin": "Observed",
                  "measurement": "resistivity", "pressure_condition": "ambient pressure"}
        parent = Material(id=f"mat:{suffix}:parent", formula="Nb", formula_normalized=f"{suffix}:parent",
                          status="active_research", needs_review=False, total_papers=1,
                          records=[deepcopy(record)])
        child = Material(id=f"mat:{suffix}:child", formula="Nb", formula_normalized=f"{suffix}:child",
                         parent_material_id=parent.id, status="active_research", needs_review=False,
                         total_papers=1, records=[deepcopy(record)])
        db_session.add_all([parent, child])
        await db_session.commit()
        yield db_session, paper, parent, child


def observed_clock(monkeypatch):
    clock, observations = [0.], []
    monkeypatch.setattr(timing, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(timing, "MATERIAL_LIST_STAGE_DURATION", SimpleNamespace(
        labels=lambda stage: SimpleNamespace(observe=lambda duration: observations.append((stage, duration)))))
    return clock, observations


def full_views(views):
    return [{"id": v.id, "visibility": v.visibility, "statuses": v.source_statuses,
             "current_records": v.current_records()} for v in views]


@pytest.mark.asyncio
async def test_native_nested_totals_exclude_result_materialization_and_preserve_full_views(
    scope_rows, monkeypatch,
):
    db_session, _, parent, child = scope_rows
    before = deepcopy([parent.records, child.records])
    baseline = full_views(await adapter.prepare_material_views(db_session, [child]))
    clock, observations = observed_clock(monkeypatch)
    execute, policy = AsyncSession.execute, adapter.scoped_material_visibility
    calls = []

    class Materialized:
        def __init__(self, result):
            self.result = result

        def scalars(self):
            self.result = self.result.scalars()
            return self

        def mappings(self):
            self.result = self.result.mappings()
            return self

        def all(self):
            clock[0] += 2  # Deliberately outside the execute-await subtotal.
            return self.result.all()

    async def controlled_execute(self, statement, *args, **kwargs):
        calls.append("lifecycle" if isinstance(statement, TextClause) else "select")
        clock[0] += 3
        return Materialized(await execute(self, statement, *args, **kwargs))

    def controlled_policy(*args, **kwargs):
        result = policy(*args, **kwargs)
        clock[0] += 7
        return result

    monkeypatch.setattr(AsyncSession, "execute", controlled_execute)
    monkeypatch.setattr(adapter, "scoped_material_visibility", controlled_policy)
    with timing.material_list_request() as collected:
        with timing.material_list_stage("scope"):
            actual = full_views(await adapter.prepare_material_views(db_session, [child]))
    assert actual == baseline and [parent.records, child.records] == before
    assert calls == ["select", "lifecycle", "select", "lifecycle"]
    assert collected.seconds == pytest.approx({
        "parent_execute_elapsed": 3, "lifecycle_execute_elapsed": 9,
        "lifecycle_resolver_elapsed": 15, "scope_policy_elapsed": 14, "scope": 34,
    })
    assert sum(v for k, v in collected.seconds.items() if k != "scope") > collected.seconds["scope"]
    assert len(observations) == 7 and timing._current.get() is None


@pytest.mark.asyncio
async def test_shared_non_list_resolver_and_adapter_emit_no_list_observations(scope_rows, monkeypatch):
    db_session, paper, _, child = scope_rows
    _, observations = observed_clock(monkeypatch)

    def forbidden_clock():
        raise AssertionError("A shared non-list caller must not start a list timer")

    monkeypatch.setattr(timing, "perf_counter", forbidden_clock)
    assert (await lifecycle.resolve_paper_lifecycle(db_session, [paper.id]))[paper.id] == "published"
    assert len(await adapter.prepare_material_views(db_session, [child])) == 1
    assert not observations and timing._current.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ("parent", "lifecycle"))
@pytest.mark.parametrize("outcome", ("cancel", "error"))
async def test_await_failure_records_elapsed_preserves_error_and_releases_request(
    scope_rows, monkeypatch, phase, outcome,
):
    db_session, _, _, child = scope_rows
    clock, _ = observed_clock(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    execute = AsyncSession.execute
    failure = RuntimeError("Synthetic execute failure")
    collected, owners = [], []

    async def blocked(self, statement, *args, **kwargs):
        is_parent = not isinstance(statement, TextClause) and statement.column_descriptions[0]["entity"] is Material
        if (phase == "parent" and is_parent) or (phase == "lifecycle" and isinstance(statement, TextClause)):
            entered.set()
            await release.wait()
            raise failure
        return await execute(self, statement, *args, **kwargs)

    async def request():
        memo = adapter.LifecycleReadMemo(db_session)
        owners.append(memo)
        try:
            with timing.material_list_request() as current:
                collected.append(current)
                with timing.material_list_stage("scope"):
                    await adapter.prepare_material_views(db_session, [child], lifecycle_memo=memo)
        finally:
            memo.close()
            assert timing._current.get() is None

    monkeypatch.setattr(AsyncSession, "execute", blocked)
    task = asyncio.create_task(request())
    await asyncio.wait_for(entered.wait(), 2)
    clock[0] = 5
    if outcome == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        release.set()
        with pytest.raises(RuntimeError) as raised:
            await task
        assert raised.value is failure
    stage = "parent_execute_elapsed" if phase == "parent" else "lifecycle_execute_elapsed"
    assert collected[0].seconds[stage] == 5 and collected[0].seconds["scope"] == 5
    if phase == "lifecycle":
        assert collected[0].seconds["lifecycle_resolver_elapsed"] == 5
    assert "scope_policy_elapsed" not in collected[0].seconds
    assert owners[0]._session is None and not owners[0]._entries
    with timing.material_list_request() as fresh:
        assert not fresh.seconds
    assert timing._current.get() is None


@pytest.mark.asyncio
async def test_overlapping_native_resolvers_keep_request_subtotals_separate(scope_rows, monkeypatch):
    _, paper, _, _ = scope_rows
    clock, _ = observed_clock(monkeypatch)
    entered = {name: asyncio.Event() for name in ("A", "B")}
    release = {name: asyncio.Event() for name in entered}
    seen, results = set(), {}
    execute = AsyncSession.execute

    async def controlled(self, statement, *args, **kwargs):
        name = asyncio.current_task().get_name()
        if isinstance(statement, TextClause) and name not in seen:
            seen.add(name)
            entered[name].set()
            await release[name].wait()
        return await execute(self, statement, *args, **kwargs)

    async def request(name):
        async with get_session_factory()() as session:
            with timing.material_list_request() as current:
                result = await lifecycle.resolve_paper_lifecycle(session, [paper.id])
                results[name] = current, result
            assert timing._current.get() is None

    monkeypatch.setattr(AsyncSession, "execute", controlled)
    first = asyncio.create_task(request("A"), name="A")
    await asyncio.wait_for(entered["A"].wait(), 2)
    clock[0] = 1
    second = asyncio.create_task(request("B"), name="B")
    await asyncio.wait_for(entered["B"].wait(), 2)
    clock[0] = 3
    release["A"].set()
    await asyncio.wait_for(first, 2)
    clock[0] = 7
    release["B"].set()
    await asyncio.wait_for(second, 2)
    assert results["A"][1] == results["B"][1] == {paper.id: "published"}
    assert results["A"][0].seconds == {"lifecycle_resolver_elapsed": 3, "lifecycle_execute_elapsed": 3}
    assert results["B"][0].seconds == {"lifecycle_resolver_elapsed": 6, "lifecycle_execute_elapsed": 6}
    assert timing._current.get() is None
