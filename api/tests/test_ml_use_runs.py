"""Actual native run-contract SQL/HTTP with explicitly doubled intake compiler.

Synthetic accounts and data only. No execution, real rights or scientific pilot
are manufactured; the separate request pipeline covers genuine reconstruction.
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSessionTransaction

from config import get_settings
from models.db import Base, User
from models.ml_use_runs_v1 import PLAN_FIELDS, TABLES
from routers import ml_use_runs as router
from services import ml_use_currentness, ml_use_submissions
from services import ml_use_runs as service
from services.ml_audited_dataset import digest
from services.ml_use_preflight import MlUsePreflightConflict
from services.research_access import ResearchAccessDenied
from services.research_publication import grant_role
from tests.test_ml_label_capture import read_snapshot, write_snapshot
from tests.test_ml_use_governance import arguments, decide
from tests.test_ml_use_preflight import enabled as enabled
from tests.test_ml_use_submissions import db_session as db_session
from tests.test_ml_use_submissions import lookup, prepared
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import add, state

BASE = "/v1/ml/use/runs"


async def approver(db, people):
    uid = uuid4()
    await add(db, "users", id=uid, email=f"run-{uid}@example.test", name="Synthetic independent run approver",
              is_active=True, email_verified=True, is_admin=True)
    curator = await grant_role(db, actor_user_id=people["admin"], user_id=uid, role="curator",
                              reason_code="synthetic_run_review", dry_run=False)
    role = await decide(db, arguments(people, role="run_approver", user_id=str(uid)))
    return {"actor_user_id": uid, "approver_grant_id": role["decision"]["id"], "curator_grant_id": curator["id"]}


async def fixture(db):
    seeded, compiled, values = await prepared(db)
    # This fixture remains an explicit compiler double. The real worker test
    # supplies a genuinely rebuilt prepared hash; do not relax the service when
    # an older synthetic fixture omits it.
    pin = digest({"synthetic_prepared_not_a_real_dataset": True})
    compiled["reconstruction"]["prepared_sha256"] = pin
    values["observation"]["reconstruction"]["prepared_sha256"] = pin
    receipt = await ml_use_submissions.store_submission(db, **values)
    actor = await approver(db, seeded["people"])
    await read_snapshot(db)
    context = await service.context(db, actor_user_id=compiled["actor_user_id"], submission_id=receipt["submission_id"],
        submission_sha256=receipt["record_sha256"], inventory_sha256=values["observation"]["dependency_inventory_sha256"])
    args = {key: context[key] for key in PLAN_FIELDS if key not in {"request_key", "cpu_seconds", "wall_seconds", "memory_mib"}}
    args.update(request_key="synthetic-run-plan-" + uuid4().hex, cpu_seconds=60, wall_seconds=120, memory_mib=512)
    await write_snapshot(db)
    return seeded, compiled, values, receipt, actor, args


async def recorded(db, args, kind="plan"):
    operation = service.propose if kind == "plan" else service.decide
    preview = await operation(db, **args)
    assert preview[kind] is None and not preview["run_authorization_granted"]
    return await operation(db, **args, dry_run=False, expected_intent_sha256=preview["intent_sha256"])


def review_args(actor, plan, receipt):
    from datetime import datetime
    return {**actor, **plan_ref(plan), "request_key": "synthetic-run-review-" + uuid4().hex,
        "decision": "approve", "reason_code": "synthetic_conditional_budget_review",
        "evidence_sha256": digest({"synthetic_not_real_approval": True}),
        "expires_epoch": int(datetime.fromisoformat(receipt["input_access_expires_at"]).timestamp()) - 1,
        "supersedes_id": None, "supersedes_sha256": None}


def plan_ref(plan):
    return {"plan_id": plan["id"], "plan_sha256": plan["record_sha256"]}


def successor(args, record, **changes):
    return {**args, "request_key": "synthetic-run-review-" + uuid4().hex,
            "supersedes_id": record["id"], "supersedes_sha256": record["record_sha256"], **changes}


async def test_native_exact_plan_preview_replay_independent_approval_and_held_readiness(db_session):
    _, compiled, values, receipt, actor, args = await fixture(db_session)
    before = await state(db_session)
    await service.propose(db_session, **args)
    assert await state(db_session) == before
    first = await recorded(db_session, args)
    stable = await state(db_session)
    replay = await service.propose(db_session, **args, dry_run=False, expected_intent_sha256=first["intent_sha256"])
    assert replay["plan"] == first["plan"] and replay["replayed"] and await state(db_session) == stable
    review = review_args(actor, first["plan"], receipt)
    approval = await recorded(db_session, review, "decision")
    await read_snapshot(db_session)
    found = await service.inspect(db_session, actor_user_id=actor["actor_user_id"], **plan_ref(first["plan"]))
    assert found["head"] == approval["decision"] and found["recorded_approval_status"] == "conditional_approval_recorded"
    assert not found["run_authorization_granted"]
    raw = await service.retained_inputs(db_session, actor_user_id=compiled["actor_user_id"], **plan_ref(first["plan"]))
    assert raw == compiled["raw"]
    current = await ml_use_currentness.inspect_current_inputs(db_session, **compiled)
    ready = await service.readiness(db_session, actor_user_id=compiled["actor_user_id"],
        current_inspection=current, **plan_ref(first["plan"]))
    assert ready["conditional_run_approval_current"] and all(ready["fingerprints_match"].values())
    assert not ready["ready_for_execution"] and not ready["run_authorization_granted"]
    assert not ready["source_permission_granted"] and not ready["ml_training_approved"]
    assert ready["source_coverage"]["status_counts"]["unreviewed"] > 0
    assert "current_source_permissions_or_validity_incomplete" in ready["blockers"]
    assert "guarded_execution_consumer_unavailable" in ready["blockers"]
    await write_snapshot(db_session)
    revoked = await recorded(db_session, successor(review, approval["decision"], decision="revoke", expires_epoch=None), "decision")
    await read_snapshot(db_session)
    historical = await service.outcome(db_session, actor_user_id=actor["actor_user_id"], request_key=review["request_key"],
        expected_intent_sha256=approval["intent_sha256"], kind="decision")
    assert historical["decision"] == approval["decision"] and not historical["conditional_run_approval_current"]
    held = await service.readiness(db_session, actor_user_id=compiled["actor_user_id"],
        current_inspection=current, **plan_ref(first["plan"]))
    assert held["approval_status"] == "revoked" and not held["conditional_run_approval_current"]
    await write_snapshot(db_session)
    await ml_use_submissions.purge_inputs(db_session, actor_user_id=compiled["actor_user_id"], **lookup(values))
    denied = await recorded(db_session, successor(review, revoked["decision"], decision="deny", expires_epoch=None), "decision")
    replay_after_purge = await service.propose(db_session, **args, dry_run=False, expected_intent_sha256=first["intent_sha256"])
    assert replay_after_purge["replayed"] and replay_after_purge["plan"] == first["plan"]
    assert not replay_after_purge["run_authorization_granted"]
    assert denied["decision"]["decision"] == "deny"
    with pytest.raises(MlUsePreflightConflict):
        await recorded(db_session, successor(review, denied["decision"]), "decision")


async def test_exact_budget_host_pins_owner_and_approval_validation(db_session, monkeypatch):
    seeded, compiled, _, receipt, actor, args = await fixture(db_session)
    before = await state(db_session)
    for change in ({"cpu_seconds": True}, {"cpu_seconds": 121}, {"wall_seconds": 1801}, {"memory_mib": 127},
        {"memory_mib": 4097}, {"runtime_sha256": "a" * 64}, {"implementation_sha256": "a" * 64},
        {"package_sha256": "a" * 64}, {"prepared_sha256": "a" * 64}, {"inventory_sha256": "a" * 64},
        {"requester_grant_id": str(uuid4())}, {"actor_user_id": actor["actor_user_id"]}, {"command": "forbidden"}):
        with pytest.raises((ValueError, ResearchAccessDenied)):
            await service.propose(db_session, **{**args, **change})
        assert await state(db_session) == before, change
    first = await recorded(db_session, args)
    self_role = await decide(db_session, arguments(seeded["people"], role="run_approver", user_id=str(compiled["actor_user_id"])))
    review = review_args(actor, first["plan"], receipt)
    stable = await state(db_session)
    for change in ({"expires_epoch": None}, {"expires_epoch": True}, {"expires_epoch": 1},
        {"expires_epoch": review["expires_epoch"] + 86400}, {"evidence_sha256": None}, {"plan_sha256": "b" * 64},
        {"approver_grant_id": str(uuid4())}, {"supersedes_id": str(uuid4())}, {"decision": "revoke", "expires_epoch": None},
        {"actor_user_id": compiled["actor_user_id"], "approver_grant_id": self_role["decision"]["id"], "curator_grant_id": args["curator_grant_id"]}):
        with pytest.raises((ValueError, ResearchAccessDenied)):
            await service.decide(db_session, **{**review, **change})
        assert await state(db_session) == stable, change
    await recorded(db_session, review, "decision")
    await read_snapshot(db_session)
    current = await ml_use_currentness.inspect_current_inputs(db_session, **compiled)
    original = service.fingerprints
    monkeypatch.setattr(service, "fingerprints", lambda: {**original(), "runtime_sha256": "f" * 64})
    ready = await service.readiness(db_session, actor_user_id=compiled["actor_user_id"], current_inspection=current, **plan_ref(first["plan"]))
    assert ready["conditional_run_approval_current"] and not ready["fingerprints_match"]["runtime"]
    assert "runtime_fingerprint_changed" in ready["blockers"] and not ready["ready_for_execution"]


async def test_direct_sql_null_expiry_resealed_forgery_and_immutable_history(db_session):
    _, compiled, _, receipt, actor, args = await fixture(db_session)
    first = await recorded(db_session, args)
    approval = await recorded(db_session, review_args(actor, first["plan"], receipt), "decision")
    before = await state(db_session)
    for kind, name, record in (("plan", TABLES[0], first["plan"]), ("decision", TABLES[1], approval["decision"])):
        relation = Base.metadata.tables[name]
        original = dict((await db_session.execute(sa.select(relation).where(relation.c.id == UUID(record["id"])))).mappings().one())
        changes = [{"prepared_sha256": "e" * 64}, {"cpu_seconds": 2000}, {"memory_mib": 1}, {"runner_profile": "arbitrary"},
                   {"implementation_json": "{}"}] if kind == "plan" else [
                   {"expires_epoch": None}, {"expires_epoch": 1}, {"expires_epoch": review_args(actor, first["plan"], receipt)["expires_epoch"] + 86400},
                   {"evidence_sha256": None}, {"plan_sha256": "f" * 64}, {"actor_user_id": compiled["actor_user_id"]},
                   {"supersedes_id": None, "supersedes_sha256": None}, {"supersedes_sha256": "f" * 64}]
        for change in changes:
            row = {**original, "id": uuid4(), "request_key": "synthetic-direct-" + uuid4().hex}
            if kind == "decision":
                row.update(supersedes_id=original["id"], supersedes_sha256=original["record_sha256"])
            row.update(change)
            row["intent_sha256"] = digest(service.intent(row, kind))
            row["record_sha256"] = digest(service.body(row))
            with pytest.raises(DBAPIError):
                async with db_session.begin_nested():
                    await db_session.execute(relation.insert().values(**row))
            assert await state(db_session) == before, change
        for query in (f"UPDATE {name} SET request_key='tampered'", f"DELETE FROM {name}", f"TRUNCATE {name} CASCADE"):
            with pytest.raises(DBAPIError):
                async with db_session.begin_nested():
                    await db_session.execute(sa.text(query))
            assert await state(db_session) == before


async def test_approval_expiry_role_withdrawal_owner_purge_and_historical_regrant_recovery(db_session):
    seeded, compiled, values, receipt, actor, args = await fixture(db_session)
    first = await recorded(db_session, args)
    review = review_args(actor, first["plan"], receipt)
    now = await db_session.scalar(sa.select(sa.func.extract("epoch", sa.func.clock_timestamp())))
    approval = await recorded(db_session, {**review, "expires_epoch": int(now) + 3}, "decision")
    await db_session.commit()
    await asyncio.sleep(3.1)
    await read_snapshot(db_session)
    inspected = await service.inspect(db_session, actor_user_id=actor["actor_user_id"], **plan_ref(first["plan"]))
    assert inspected["recorded_approval_status"] == "expired"
    await write_snapshot(db_session)
    renewed_args = successor(review, approval["decision"])
    renewed = await recorded(db_session, renewed_args, "decision")
    await db_session.execute(sa.update(User).where(User.id == actor["actor_user_id"]).values(is_active=False))
    await read_snapshot(db_session)
    current = await ml_use_currentness.inspect_current_inputs(db_session, **compiled)
    held = await service.readiness(db_session, actor_user_id=compiled["actor_user_id"], current_inspection=current, **plan_ref(first["plan"]))
    assert held["approval_status"] == "approver_unavailable"
    await write_snapshot(db_session)
    await db_session.execute(sa.update(User).where(User.id == actor["actor_user_id"]).values(is_active=True))
    revoke = arguments(seeded["people"], user_id=str(actor["actor_user_id"]), role="run_approver", action="revoke",
        expected_head_id=actor["approver_grant_id"])
    # Role administration requires the exact previous record hash as well.
    roles = Base.metadata.tables["ml_use_role_decisions"]
    prior = (await db_session.execute(sa.select(roles).where(roles.c.id == UUID(actor["approver_grant_id"])))).mappings().one()
    revoke["expected_head_sha256"] = prior["record_sha256"]
    revoked_role = await decide(db_session, revoke)
    granted_role = await decide(db_session, arguments(seeded["people"], user_id=str(actor["actor_user_id"]), role="run_approver",
        expected_head_id=revoked_role["decision"]["id"], expected_head_sha256=revoked_role["decision"]["record_sha256"]))
    await read_snapshot(db_session)
    recovered = await service.outcome(db_session, actor_user_id=actor["actor_user_id"], request_key=renewed_args["request_key"],
        expected_intent_sha256=renewed["intent_sha256"], kind="decision")
    assert recovered["decision"] == renewed["decision"] and not recovered["conditional_run_approval_current"]
    held = await service.readiness(db_session, actor_user_id=compiled["actor_user_id"], current_inspection=current, **plan_ref(first["plan"]))
    assert held["approval_status"] == "approver_unavailable"  # regrant cannot revive an old approval
    await write_snapshot(db_session)
    await ml_use_submissions.purge_inputs(db_session, actor_user_id=compiled["actor_user_id"], **lookup(values))
    await db_session.execute(sa.update(User).where(User.id == compiled["actor_user_id"]).values(is_active=False))
    withdrawn = await recorded(db_session, successor(review, renewed["decision"], decision="revoke", expires_epoch=None,
        approver_grant_id=granted_role["decision"]["id"]), "decision")
    assert withdrawn["decision"]["decision"] == "revoke"


@pytest.mark.parametrize("endpoint", ["/context", "/plans", "/inspect", "/decisions", "/plans/outcome", "/decisions/outcome", "/check"])
async def test_anonymous_before_body(client, monkeypatch, endpoint):
    async def forbidden(*_args):
        pytest.fail("private body consumed before admission")
    monkeypatch.setattr(router, "body", forbidden)
    response = await client.post(BASE + endpoint, content=b"PRIVATE")
    assert response.status_code == 401 and response.headers["cache-control"] == "private, no-store"


async def test_http_commit_recovery_closed_body_concurrency_and_owner_recheck(client, db_session, monkeypatch):
    seeded, compiled, values, receipt, actor, args = await fixture(db_session)
    await db_session.commit()
    request = {key: value for key, value in args.items() if key != "actor_user_id"}
    headers = auth(compiled["actor_user_id"])
    invalid = await client.post(BASE + "/plans", json={**request, "runtime_json": "PRIVATE"}, headers=headers)
    assert invalid.status_code == 400 and "PRIVATE" not in invalid.text
    preview = await client.post(BASE + "/plans", json=request, headers=headers)
    assert preview.status_code == 200, preview.text
    request.update(dry_run=False, expected_intent_sha256=preview.json()["result"]["intent_sha256"])
    replies = await asyncio.gather(*(client.post(BASE + "/plans", json=request, headers=headers) for _ in range(2)))
    assert any(r.status_code == 200 for r in replies) and all(r.status_code in {200, 503} for r in replies)
    recovered = await client.post(BASE + "/plans/outcome", json={key: request[key] for key in ("request_key", "expected_intent_sha256")}, headers=headers)
    assert recovered.status_code == 200, recovered.text
    plan = recovered.json()["result"]["plan"]
    review = review_args(actor, plan, receipt)
    review.pop("actor_user_id")
    review_headers = auth(actor["actor_user_id"])
    preview = await client.post(BASE + "/decisions", json=review, headers=review_headers)
    assert preview.status_code == 200, preview.text
    review.update(dry_run=False, expected_intent_sha256=preview.json()["result"]["intent_sha256"])
    close, operation = AsyncSessionTransaction.__aexit__, service.decide
    async def marked(db, **kw):
        result = await operation(db, **kw)
        db.info["synthetic_lost_run_reply"] = True
        return result
    async def lost(self, *kw):
        await close(self, *kw)
        if not self.nested and self.session.info.get("synthetic_lost_run_reply"):
            raise SQLAlchemyError("PRIVATE lost reply")
    with monkeypatch.context() as patch:
        patch.setattr(service, "decide", marked)
        patch.setattr(AsyncSessionTransaction, "__aexit__", lost)
        failed = await client.post(BASE + "/decisions", json=review, headers=review_headers)
    assert failed.status_code == 503 and failed.headers["x-operation-state"] == "unknown" and "PRIVATE" not in failed.text
    recovered = await client.post(BASE + "/decisions/outcome", json={key: review[key] for key in ("request_key", "expected_intent_sha256")}, headers=review_headers)
    assert recovered.status_code == 200 and recovered.json()["result"]["replayed"], recovered.text
    replay = await client.post(BASE + "/decisions", json=review, headers=review_headers)
    assert replay.status_code == 200 and replay.json()["result"]["decision"] == recovered.json()["result"]["decision"]
    async def rebuilt(_user, raw):
        return raw, {}, compiled["reconstruction"]
    monkeypatch.setattr(router.preflight, "_rebuild_bytes", rebuilt)
    checked = await client.post(BASE + "/check", json=plan_ref(plan), headers=headers)
    assert checked.status_code == 200 and checked.json()["conditional_run_approval_current"], checked.text
    assert not checked.json()["ready_for_execution"] and not checked.json()["source_permission_granted"]
    foreign = await client.post(BASE + "/check", json=plan_ref(plan), headers=review_headers)
    assert foreign.status_code == 403
    # Even another admitted requester cannot reconstruct the owner's inputs.
    await decide(db_session, arguments(seeded["people"], user_id=str(actor["actor_user_id"]), role="requester"))
    await db_session.commit()
    async def no_foreign_worker(*_args):
        pytest.fail("foreign owner inputs reached the worker")
    monkeypatch.setattr(router.preflight, "_rebuild_bytes", no_foreign_worker)
    foreign = await client.post(BASE + "/check", json=plan_ref(plan), headers=review_headers)
    assert foreign.status_code == 403
    async def purged_during_worker(_user, raw):
        response = await client.post("/v1/ml/use/requests/purge", json=lookup(values), headers=headers)
        assert response.status_code == 200, response.text
        return raw, {}, compiled["reconstruction"]
    monkeypatch.setattr(router.preflight, "_rebuild_bytes", purged_during_worker)
    purged = await client.post(BASE + "/check", json=plan_ref(plan), headers=headers)
    assert purged.status_code == 404, purged.text


async def test_nonadmitted_and_disabled_do_not_consume_body(client, db_session, monkeypatch):
    seeded, _, _, _, _, _ = await fixture(db_session)
    await db_session.commit()
    async def forbidden(*_args):
        pytest.fail("nonadmitted body consumed")
    monkeypatch.setattr(router, "body", forbidden)
    for role in ("admin", "reviewer", "publisher", "member"):
        for endpoint in ("/plans", "/decisions", "/inspect", "/check"):
            response = await client.post(BASE + endpoint, content=b"PRIVATE", headers=auth(seeded["people"][role]))
            assert response.status_code == 403, response.text
    monkeypatch.setenv("ML_USE_GOVERNANCE_ENABLED", "false")
    get_settings.cache_clear()
    response = await client.post(BASE + "/plans", content=b"PRIVATE")
    assert response.status_code == 404 and response.headers["cache-control"] == "private, no-store"
