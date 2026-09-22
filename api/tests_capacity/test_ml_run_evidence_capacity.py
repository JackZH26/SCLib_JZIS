"""Actual 32 MiB boundary and concurrent admissions, not a reduced quota double.

Synthetic users/reviews only; every SQL trigger remains enabled. Run separately
through run_disposable_tests so the retained quota history cannot affect ordinary
tests. This is a bounded correctness experiment, not a production load benchmark.
"""
from __future__ import annotations

import asyncio
import hashlib
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, get_engine
from models.ml_run_evidence_v1 import MAX_BYTES, MAX_STORAGE_BYTES, TABLES
from services import ml_run_evidence as evidence
from services import ml_use_runs as runs
from services.ml_audited_dataset import digest
from tests.test_ml_use_runs import fixture, recorded, review_args
from tests.test_ml_use_submissions import db_session as db_session


def decision_ref(record):
    return {"decision_id": record["id"], "decision_sha256": record["record_sha256"]}


def payload(size):
    prefix = "SYNTHETIC quota-only bytes. No human review, science acceptance or execution. "
    return (prefix * (size // len(prefix) + 1))[:size]


def review_values(template, *, previous=None, size=MAX_BYTES):
    value = payload(size)
    return {**template, "request_key": "synthetic-quota-" + uuid4().hex,
        "reason_code": "synthetic_real_quota_boundary", "evidence_text": value,
        "evidence_sha256": hashlib.sha256(value.encode()).hexdigest(),
        "supersedes_id": None if previous is None else previous["id"],
        "supersedes_sha256": None if previous is None else previous["record_sha256"]}


def metadata(values):
    return {k: str(v) if k == "actor_user_id" else v for k, v in values.items() if k != "evidence_text"}


async def retained_bytes(db):
    return await db.scalar(sa.select(sa.func.coalesce(sa.func.sum(sa.func.octet_length(Base.metadata.tables[TABLES[0]].c.payload)), 0)))


async def test_real_32mib_limit_concurrent_last_slot_reclaim_and_atomic_rejection(db_session):
    assert MAX_BYTES == 8192 and MAX_STORAGE_BYTES == 33554432
    assert await retained_bytes(db_session) == 0, "Run capacity tests in their separate owned-service invocation"
    definitions = await db_session.scalar(sa.text("SELECT pg_get_functiondef('public.sclib_ml_run_evidence_insert_v1()'::regprocedure)"))
    assert ">33554432" in definitions  # No patched threshold or bypassed trigger.
    templates = []
    for _ in range(3):
        _, _, _, receipt, actor, args = await fixture(db_session)
        for _ in range(15):  # Respect the real 20 plans/submission and 100 decisions/plan caps.
            plan = (await recorded(db_session, {**args, "request_key": "synthetic-quota-plan-" + uuid4().hex}))["plan"]
            templates.append(review_args(actor, plan, receipt))
        await db_session.commit()
    needed, inserted = MAX_STORAGE_BYTES - MAX_BYTES, 0
    # Real valid approval rows, exact hashes, current independent grants, actual
    # payloads. Calling the low-level insert avoids expensive unrelated preview
    # snapshots, but all production SQL validation/deferred constraints execute.
    for template in templates[:-2]:
        previous = None
        for _ in range(100):
            if not needed:
                break
            size = min(MAX_BYTES, needed)
            values = review_values(template, previous=previous, size=size)
            row = await runs.insert(db_session, metadata(values), "decision")
            await evidence.store(db_session, row, values["evidence_text"].encode())
            previous = runs.dto(row, "decision")
            needed -= size
            inserted += 1
        await db_session.commit()  # Also exercises the real deferred completeness constraint.
        if not needed:
            break
    assert needed == 0 and inserted == 4095
    assert await retained_bytes(db_session) == MAX_STORAGE_BYTES - MAX_BYTES
    await db_session.rollback()

    contenders = [review_values(v) for v in templates[-2:]]
    barrier = asyncio.Barrier(2)
    async def compete(values):
        async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE"), expire_on_commit=False) as db:
            try:
                async with db.begin():
                    await db.execute(sa.text("SET LOCAL statement_timeout='15000ms'"))
                    assert await retained_bytes(db) == MAX_STORAGE_BYTES - MAX_BYTES
                    await asyncio.wait_for(barrier.wait(), timeout=10)
                    result = await runs.decide(db, **values, dry_run=False,
                        expected_intent_sha256=digest(runs.intent(metadata(values), "decision")))
                return {"values": values, "result": result, "sqlstate": None}
            except DBAPIError as exc:
                return {"values": values, "result": None, "sqlstate": exc.orig.sqlstate}
    outcomes = await asyncio.wait_for(asyncio.gather(*(compete(v) for v in contenders)), timeout=40)
    accepted = [v for v in outcomes if v["result"] is not None]
    rejected = [v for v in outcomes if v["result"] is None]
    assert len(accepted) == len(rejected) == 1
    assert rejected[0]["sqlstate"] in {"55P03", "40001", "54000"}
    assert await retained_bytes(db_session) == MAX_STORAGE_BYTES
    winner, loser = accepted[0], rejected[0]
    assert not winner["result"]["run_authorization_granted"] and winner["result"]["training_execution"] == "disabled"
    await db_session.rollback()
    loser_pin = digest(runs.intent(metadata(loser["values"]), "decision"))
    with pytest.raises(DBAPIError) as full:
        await runs.decide(db_session, **loser["values"], dry_run=False, expected_intent_sha256=loser_pin)
    assert full.value.orig.sqlstate == "54000" and "ml_run_evidence_storage_limit" in str(full.value.orig)
    await db_session.rollback()
    decisions = Base.metadata.tables["ml_use_run_decisions"]
    assert not await db_session.scalar(sa.select(sa.exists().where(decisions.c.request_key == loser["values"]["request_key"])))
    assert await retained_bytes(db_session) == MAX_STORAGE_BYTES
    await db_session.rollback()

    target = decision_ref(winner["result"]["decision"])
    purge = await evidence.purge(db_session, actor_user_id=winner["values"]["actor_user_id"], **target)
    assert not purge["replayed"]
    await db_session.commit()
    assert await retained_bytes(db_session) == MAX_STORAGE_BYTES - MAX_BYTES
    await db_session.rollback()
    saved = await runs.decide(db_session, **loser["values"], dry_run=False, expected_intent_sha256=loser_pin)
    await db_session.commit()
    assert saved["decision"]["request_key"] == loser["values"]["request_key"] and await retained_bytes(db_session) == MAX_STORAGE_BYTES
    # Even at capacity, an original-key replay must not restore the winner's
    # explicitly purged bytes or create another approval.
    replay = await runs.decide(db_session, **winner["values"], dry_run=False,
        expected_intent_sha256=winner["result"]["intent_sha256"])
    assert replay["replayed"] and replay["decision"] == winner["result"]["decision"]
    assert await retained_bytes(db_session) == MAX_STORAGE_BYTES
    assert not await db_session.scalar(sa.select(sa.exists().where(Base.metadata.tables[TABLES[0]].c.decision_id == UUID(target["decision_id"]))))
