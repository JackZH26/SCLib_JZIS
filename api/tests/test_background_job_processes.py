"""Independent Python-process races and crash recovery on disposable SQL.

No schema fixture transaction is shared with the workers: their running claim
and the final audit effect must be independently visible to this process.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from test_safety import validate_test_environment

from models.db import AuditReport, Base, get_engine

WORKER = Path(__file__).with_name("background_job_process_worker.py")


@pytest_asyncio.fixture(loop_scope="function")
async def process_engine():
    engine = get_engine()
    try:
        yield engine
    finally:
        await engine.dispose()


async def fixture_identity(engine):
    token = uuid4().hex
    # Monotonic exact past cycles: never overtake a newer success by selecting
    # a random older date, and never depend on a daily schedule boundary.
    table = Base.metadata.tables["background_job_cycles"]
    async with engine.connect() as connection:
        latest = (await connection.execute(sa.select(sa.func.max(table.c.scheduled_for)).where(
            table.c.job_name == "nightly_audit"))).scalar_one()
    due = latest + timedelta(seconds=1) if latest else datetime(2000, 1, 1, tzinfo=UTC)
    assert due.microsecond == 0
    # The controlled replay still obeys the service's whole-second schedule
    # grid and <= database-now check. A prior exact-current fixture can require
    # at most a short wait before the next second becomes due.
    for _ in range(60):
        async with engine.connect() as connection:
            now = (await connection.execute(sa.select(sa.func.clock_timestamp()))).scalar_one()
        if due <= now:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("The independent process fixture would require a future cycle")
    return "en03-process-" + token, due


@asynccontextmanager
async def worker(rule_name, due, *, hold=False):
    # This environment was created by the EN01 runner, not copied from .env.
    # Both parent and child validate its existing one-run capability.
    validate_test_environment()
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(WORKER), "--rule-name", rule_name,
        "--scheduled-for", due.isoformat(), "--mode", "hold" if hold else "commit",
        cwd=WORKER.parents[1], env=dict(os.environ),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        yield process
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await asyncio.wait_for(process.communicate(), timeout=10)


async def next_message(process):
    line = await asyncio.wait_for(process.stdout.readline(), timeout=15)
    assert line, f"Synthetic background worker exited without a response (code={process.returncode})"
    message = json.loads(line)
    assert message.get("event") != "worker_error", message
    return message


async def result(process):
    message = await next_message(process)
    if message.get("event") == "effect_ready":
        message = await next_message(process)
    assert message.get("event") == "result", message
    assert await asyncio.wait_for(process.wait(), timeout=10) == 0
    return message["result"]


async def reports(engine, rule_name):
    async with engine.connect() as connection:
        return (await connection.execute(sa.select(AuditReport.__table__).where(
            AuditReport.rule_name == rule_name))).mappings().all()


async def cycle(engine, identifier):
    table = Base.metadata.tables["background_job_cycles"]
    async with engine.connect() as connection:
        rows = await connection.execute(sa.select(table).where(table.c.id == UUID(str(identifier))))
        return rows.mappings().one()


@pytest.mark.asyncio
async def test_two_processes_produce_one_effective_audit_set_for_same_cycle(process_engine):
    rule_name, due = await fixture_identity(process_engine)
    async with worker(rule_name, due, hold=True) as first:
        ready = await next_message(first)
        assert ready["event"] == "effect_ready"
        assert ready["process_id"] == first.pid
        assert (await cycle(process_engine, ready["cycle_id"]))["status"] == "running"
        assert await reports(process_engine, rule_name) == []
        async with worker(rule_name, due) as contender:
            assert contender.pid != first.pid
            blocked = await result(contender)
        assert blocked["status"] == "busy"
        assert await reports(process_engine, rule_name) == []
        first.stdin.write(b"continue\n")
        await first.stdin.drain()
        completed = await result(first)
    assert completed["status"] == "succeeded"
    assert str(completed["cycle_id"]) == ready["cycle_id"]
    rows = await reports(process_engine, rule_name)
    assert len(rows) == 1 and rows[0]["sample_ids"] == [ready["cycle_id"]]
    async with worker(rule_name, due) as replay:
        repeated = await result(replay)
    assert repeated["status"] == "already_succeeded"
    assert str(repeated["cycle_id"]) == ready["cycle_id"]
    assert await reports(process_engine, rule_name) == rows
    assert (await cycle(process_engine, ready["cycle_id"]))["attempts"] == 1


@pytest.mark.asyncio
async def test_killed_process_rolls_back_effect_and_new_process_recovers_cycle(process_engine):
    rule_name, due = await fixture_identity(process_engine)
    async with worker(rule_name, due, hold=True) as crashed:
        ready = await next_message(crashed)
        assert ready["event"] == "effect_ready"
        assert await reports(process_engine, rule_name) == []
        claimed = await cycle(process_engine, ready["cycle_id"])
        assert claimed["status"] == "running" and claimed["attempts"] == 1
        crashed.kill()
        assert await asyncio.wait_for(crashed.wait(), timeout=10) != 0
    assert await reports(process_engine, rule_name) == []
    # Closing a killed process releases its DB session. Allow only bounded
    # lock-release latency; a busy response itself never executes the handler.
    recovered = None
    for _ in range(20):
        async with worker(rule_name, due) as successor:
            recovered = await result(successor)
        if recovered["status"] != "busy":
            break
        await asyncio.sleep(0.05)
    assert recovered["status"] == "succeeded"
    assert recovered["recovered"] is True
    assert str(recovered["cycle_id"]) == ready["cycle_id"]
    rows = await reports(process_engine, rule_name)
    assert len(rows) == 1 and rows[0]["sample_ids"] == [ready["cycle_id"]]
    finished = await cycle(process_engine, ready["cycle_id"])
    assert finished["status"] == "succeeded" and finished["attempts"] == 2
    assert finished["owner_id"] != claimed["owner_id"]
