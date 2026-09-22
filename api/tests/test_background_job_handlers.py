"""Scheduled effects share the coordinator transaction, never a hidden commit."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import main
from models.background_jobs_v1 import JOB_LOCK_KEYS
from models.db import AuditReport, Base, Material, get_engine
from services import audit_runner, stats_refresh
from services.audit_rules import AuditRule
from tests.test_research_freeze import add
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_stats_consistency import _FakeDb, _payload

db_session = _serializable_db_session


async def test_stats_deferred_commit_defers_metrics(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(stats_refresh, "compute_stats", AsyncMock(return_value=_payload()))
    metrics = Mock()
    monkeypatch.setattr(stats_refresh, "update_dataset_metrics", metrics)
    result = await stats_refresh.refresh_dashboard_cache(db, commit=False)
    assert db.committed is False and len(db.executed) == 1
    metrics.assert_not_called()
    stats_refresh.publish_dashboard_metrics(result)
    metrics.assert_called_once()


async def test_manual_stats_refresh_locks_before_its_first_input_read(monkeypatch):
    db = _FakeDb()

    async def compute(session):
        assert len(session.executed) == 1
        assert "pg_advisory_xact_lock" in str(session.executed[0])
        return _payload()

    monkeypatch.setattr(stats_refresh, "compute_stats", compute)
    await stats_refresh.refresh_dashboard_cache(db)
    assert db.committed is True


@pytest.mark.parametrize("call,name,interval,offset", [
    (lambda: main._periodic_stats_refresh(900), "stats_refresh", 900, 0),
    (lambda: main._periodic_timeline_projection(900), "timeline_projection", 900, 0),
    (lambda: main._periodic_formula_audit(3600), "formula_audit", 3600, 0),
    (lambda: main._nightly_data_audit(20), "nightly_audit", 86400, 72000),
    (lambda: main._periodic_ask_history_prune(86400, 90), "ask_history_prune", 86400, 0),
])
async def test_all_lifespan_writers_use_coordinated_cycles(monkeypatch, call, name, interval, offset):
    coordinator_loop = AsyncMock()
    monkeypatch.setattr(main, "_run_periodic_job", coordinator_loop)
    await call()
    args, kwargs = coordinator_loop.call_args
    assert args[0:2] == (name, interval)
    assert callable(args[2]) and kwargs.get("offset_seconds", 0) == offset
    assert kwargs["config"]["policy_version"]
    if name == "ask_history_prune":
        assert kwargs["config"]["retention_days"] == 90


async def test_prune_cutoff_comes_from_cycle_not_recovery_wall_clock(monkeypatch):
    scheduled = datetime(2026, 7, 1, tzinfo=UTC)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(rowcount=3)))

    async def invoke(_name, _interval, handler, **kwargs):
        result = await handler(db, scheduled, uuid4())
        assert result == {"deleted": 3, "cutoff": (scheduled - timedelta(days=90)).isoformat(), "retention_days": 90}
        statement = db.execute.call_args.args[0]
        assert list(statement.compile().params.values()) == [scheduled - timedelta(days=90)]

    monkeypatch.setattr(main, "_run_periodic_job", invoke)
    await main._periodic_ask_history_prune(86400, 90)


async def test_timeline_recovery_does_not_backdate_projection(monkeypatch):
    stamp = datetime.now(UTC)
    refresh = AsyncMock(return_value=SimpleNamespace(full_rebuild=True, materials_processed=2,
        active_materials=2, active_points=3, refreshed_at=stamp))
    monkeypatch.setattr(main, "refresh_timeline_projection", refresh)
    db = object()
    result = await main._timeline_projection_cycle(db, datetime(2000, 1, 1, tzinfo=UTC), uuid4())
    refresh.assert_awaited_once_with(db)
    assert result["refreshed_at"] == stamp.isoformat()


async def test_atomic_audit_failure_rolls_back_all_prior_rules_and_reports(db_session, monkeypatch):
    token = uuid4().hex
    identifier = "background-audit:" + token
    await add(db_session, "materials", id=identifier, formula="X", formula_normalized="X", records=[], needs_review=False)
    await db_session.commit()
    rules = [AuditRule(name="synthetic-good-" + token, severity="critical", description="Synthetic", predicate="FALSE"),
             AuditRule(name="synthetic-bad-" + token, severity="critical", description="Synthetic", predicate="FALSE")]
    monkeypatch.setattr(audit_runner, "RULES", rules)

    async def outcome(db, rule):
        if rule is rules[1]:
            raise RuntimeError("synthetic second-rule failure")
        await db.execute(sa.update(Material).where(Material.id == identifier).values(needs_review=True))
        return {"flagged": 1, "sample_ids": [identifier]}

    monkeypatch.setattr(audit_runner, "_run_rule", outcome)
    with pytest.raises(RuntimeError, match="did not complete"):
        await audit_runner.run_audit(db_session, commit=False, scheduled_for=datetime.now(UTC), cycle_id=uuid4())
    await db_session.rollback()
    assert await db_session.scalar(sa.select(Material.needs_review).where(Material.id == identifier)) is False
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(AuditReport).where(
        AuditReport.rule_name.in_([rule.name for rule in rules]))) == 0


async def test_audit_cycle_delta_uses_prior_successful_scheduled_cycle_not_interleaved_manual_report(db_session, monkeypatch):
    name = "scheduled-metric:" + uuid4().hex
    stamp = datetime(2026, 9, 1, 20, tzinfo=UTC)
    cycle = uuid4()
    rule = AuditRule(name=name, severity="critical", description="Synthetic", predicate="FALSE")
    monkeypatch.setattr(audit_runner, "RULES", [rule])
    monkeypatch.setattr(audit_runner, "_run_rule", AsyncMock(return_value={"flagged": 8, "sample_ids": []}))
    await db_session.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": JOB_LOCK_KEYS["nightly_audit"]})
    previous_time = stamp - timedelta(days=2)
    prior = await add(db_session, "background_job_cycles", job_name="nightly_audit",
        scheduled_for=previous_time, schedule_sha256="a" * 64, status="running", owner_id=uuid4(),
        backend_pid=await db_session.scalar(sa.text("SELECT pg_backend_pid()")), attempts=1, started_at=previous_time)
    table = Base.metadata.tables["background_job_cycles"]
    await db_session.execute(table.update().where(table.c.id == prior["id"]).values(
        status="succeeded", completed_at=previous_time, duration_ms=0))
    for offset, count in [(-2, 7), (-1, 99), (0, 90), (1, 100)]:
        marker = [{"kind": "background_cycle", "version": "background-cycle/1.0.0", "cycle_id": str(prior["id"]),
                   "scheduled_for": previous_time.isoformat()}] if offset == -2 else []
        db_session.add(AuditReport(rule_name=name, severity="critical", started_at=stamp + timedelta(days=offset),
            completed_at=stamp, rows_flagged=count, sample_ids=[], suggested_fixes=audit_runner._metric_marker(rule) + marker))
    await db_session.commit()
    result = await audit_runner.run_audit(db_session, commit=False, scheduled_for=stamp, cycle_id=cycle)
    assert result == {name: 8}
    report = (await db_session.execute(sa.select(AuditReport).where(
        AuditReport.rule_name == name, AuditReport.rows_flagged == 8))).scalar_one()
    assert report.delta_vs_previous == 1 and report.started_at == stamp
    assert report.suggested_fixes[1] == {"kind": "background_cycle", "version": "background-cycle/1.0.0",
        "cycle_id": str(cycle), "scheduled_for": stamp.isoformat()}
    await db_session.rollback()
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(AuditReport).where(
        AuditReport.rule_name == name, AuditReport.rows_flagged == 8)) == 0


@pytest.mark.parametrize("job_name", ["stats_refresh", "nightly_audit"])
async def test_manual_writer_waits_for_scheduled_owner_before_reading_inputs(monkeypatch, job_name):
    engine = get_engine()
    entered = asyncio.Event()
    ready = asyncio.Event()
    if job_name == "stats_refresh":
        async def compute(_db):
            entered.set()
            return _payload()
        monkeypatch.setattr(stats_refresh, "compute_stats", compute)
    else:
        name = "manual-lock:" + uuid4().hex
        monkeypatch.setattr(audit_runner, "RULES", [AuditRule(name=name, severity="critical", description="Synthetic", predicate="FALSE")])

        async def outcome(_db, _rule):
            entered.set()
            return {"flagged": 0, "sample_ids": []}
        monkeypatch.setattr(audit_runner, "_run_rule", outcome)

    async def manual():
        async with AsyncSession(engine) as db:
            ready.set()
            if job_name == "stats_refresh":
                return await stats_refresh.refresh_dashboard_cache(db)
            return await audit_runner.run_audit(db)

    task = None
    try:
        async with engine.connect() as owner:
            await owner.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": JOB_LOCK_KEYS[job_name]})
            task = asyncio.create_task(manual())
            await asyncio.wait_for(ready.wait(), timeout=5)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(entered.wait(), timeout=0.1)
            await owner.commit()
            await asyncio.wait_for(task, timeout=5)
            assert entered.is_set()
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


async def test_formula_handler_never_commits_and_preserves_existing_reason(db_session):
    identifier = "background-formula:" + uuid4().hex
    await add(db_session, "materials", id=identifier, formula="graphene", formula_normalized="graphene",
              records=[], needs_review=False, review_reason="retained_reason")
    await db_session.commit()
    result = await main._formula_audit_cycle(db_session, datetime.now(UTC), uuid4())
    assert result["flagged"] >= 1 and result["rule_count"] == 4
    row = (await db_session.execute(sa.select(Material).where(Material.id == identifier))).scalar_one()
    assert row.needs_review is True and row.review_reason == "retained_reason"
    await db_session.rollback()
    assert await db_session.scalar(sa.select(Material.needs_review).where(Material.id == identifier)) is False


@pytest.mark.parametrize("statuses,post_calls", [
    (["busy", "retry_wait", "already_succeeded", "failed"], 0),
    (["succeeded", "already_succeeded"], 1),
])
async def test_loop_post_commit_only_for_new_durable_success_and_polls_retries(monkeypatch, statuses, post_calls):
    from services import background_jobs

    coordinator = AsyncMock(side_effect=[{"status": item, "cycle_id": "synthetic", "result": {}} for item in statuses])
    monkeypatch.setattr(background_jobs, "run_background_cycle", coordinator)
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == len(statuses):
            raise asyncio.CancelledError

    monkeypatch.setattr(main.asyncio, "sleep", sleep)
    post = AsyncMock()
    handler = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await main._run_periodic_job("nightly_audit", 86400, handler, offset_seconds=72000,
            config={"synthetic": True}, after_commit=post)
    assert sleeps == [30] * len(statuses)
    assert post.await_count == post_calls
    assert coordinator.await_count == len(statuses)
    assert coordinator.call_args.kwargs["handler"] is handler
