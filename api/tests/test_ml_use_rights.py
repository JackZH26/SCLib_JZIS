"""Native rights ledger tests with explicit intake compiler doubles.

No real permissions or data are used. The separate real-worker request pipeline
exercises the new owner coverage endpoint without replacing reconstruction.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSessionTransaction

from config import get_settings
from models.db import Base, User
from models.ml_use_rights_v1 import INTENT_FIELDS, INTENT_VERSION, TABLE
from routers import ml_use_rights as router
from services import ml_use_currentness, ml_use_submissions
from services import ml_use_rights as service
from services.ml_audited_dataset import digest
from services.ml_use_preflight import MlUsePreflightConflict
from services.research_access import ResearchAccessDenied
from services.research_publication import grant_role
from tests.test_ml_label_capture import read_snapshot, write_snapshot
from tests.test_ml_use_governance import arguments, decide
from tests.test_ml_use_preflight import enabled as enabled
from tests.test_ml_use_submissions import db_session as db_session
from tests.test_ml_use_submissions import lookup, stored
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import add, state

BASE = "/v1/ml/use/rights"


async def reviewer(db, people):
    uid = uuid4()
    await add(db, "users", id=uid, email=f"rights-{uid}@example.test", name="Synthetic independent rights reviewer",
              is_active=True, email_verified=True, is_admin=True)
    curator = await grant_role(db, actor_user_id=people["admin"], user_id=uid, role="curator",
                              reason_code="synthetic_rights_review", dry_run=False)
    role = await decide(db, arguments(people, role="rights_reviewer", user_id=str(uid)))
    return {"actor_user_id": uid, "reviewer_grant_id": role["decision"]["id"], "curator_grant_id": curator["id"]}


async def fixture(db):
    seeded, compiled, values, receipt = await stored(db)
    actor = await reviewer(db, seeded["people"])
    await db.commit()
    parent = await service.submission(db, receipt["submission_id"], receipt["record_sha256"])
    inventory = service.resources(parent)
    args = {**actor, "submission_id": receipt["submission_id"], "submission_sha256": receipt["record_sha256"],
        "inventory_sha256": parent["inventory_sha256"], "resource_id": next(iter(inventory)),
        "request_key": "synthetic-rights-" + uuid4().hex, "decision": "allow", "basis_code": "documented_permission",
        "evidence_sha256": digest({"synthetic_not_a_real_licence": True}),
        "expires_epoch": int(parent["expires_at"].timestamp()) - 1,
        "supersedes_id": None, "supersedes_sha256": None}
    return seeded, compiled, values, receipt, parent, args


async def recorded(db, args):
    preview = await service.decide(db, **args)
    assert preview["decision"] is None
    return await service.decide(db, **args, dry_run=False, expected_intent_sha256=preview["intent_sha256"])


def successor(args, head, **changes):
    return {**args, "request_key": "synthetic-rights-" + uuid4().hex,
            "supersedes_id": head["id"], "supersedes_sha256": head["record_sha256"], **changes}


def inspect_args(args):
    return {key: args[key] for key in ("submission_id", "submission_sha256", "inventory_sha256")}


async def test_full_inventory_coverage_preserves_source_hold_revoke_replay_and_no_training_authority(db_session):
    _, compiled, values, receipt, parent, args = await fixture(db_session)
    before = await state(db_session)
    preview = await service.decide(db_session, **args)
    assert await state(db_session) == before
    first = await recorded(db_session, args)
    await db_session.commit()
    stable = await state(db_session)
    replay = await service.decide(db_session, **args, dry_run=False, expected_intent_sha256=preview["intent_sha256"])
    assert replay["replayed"] and replay["decision"] == first["decision"] and await state(db_session) == stable
    inventory = service.resources(parent)
    assert {value["kind"] for value in inventory.values()} == {"row", "artifact"}
    for resource_id in inventory:
        if resource_id != args["resource_id"]:
            await recorded(db_session, {**args, "resource_id": resource_id, "request_key": "synthetic-rights-" + uuid4().hex})
    await read_snapshot(db_session)
    observed = await ml_use_currentness.inspect_current_inputs(db_session, **compiled)
    checked = await service.coverage(db_session, actor_user_id=compiled["actor_user_id"], parent=parent, current_inspection=observed)
    assert checked["recorded_permissions_complete"], checked["status_counts"]
    # The shared ML fixture intentionally retains unapproved legacy catalogue
    # data (including a 7777 K canary). Complete rights cannot waive that gate.
    assert observed["catalogue_and_scientific_gate"] != "no_hold_observed" or any(
        item["frozen_row_changed"] for item in observed["requirements"])
    assert not checked["source_permission_granted"] and not checked["current_source_validity_passed"]
    assert checked["live_source_rights_checked"] and checked["status_counts"]["allow_recorded"] == len(inventory)
    assert not checked["run_authorization_granted"] and not checked["ml_training_approved"] and not checked["public_release"]
    await write_snapshot(db_session)
    revoked = await recorded(db_session, successor(args, first["decision"], decision="revoke", basis_code="withdrawn", expires_epoch=None))
    await read_snapshot(db_session)
    current = await ml_use_currentness.inspect_current_inputs(db_session, **compiled)
    held = await service.coverage(db_session, actor_user_id=compiled["actor_user_id"], parent=parent, current_inspection=current)
    assert not held["source_permission_granted"] and held["status_counts"]["revoked"] == 1
    historical = await service.outcome(db_session, actor_user_id=args["actor_user_id"], request_key=args["request_key"],
                                      expected_intent_sha256=first["intent_sha256"])
    assert historical["decision"] == first["decision"] and not historical["source_permission_granted"]
    await write_snapshot(db_session)
    restored = await recorded(db_session, successor(args, revoked["decision"]))
    assert restored["decision"]["id"] != first["decision"]["id"]
    await ml_use_submissions.purge_inputs(db_session, actor_user_id=compiled["actor_user_id"], **lookup(values))
    await read_snapshot(db_session)
    with pytest.raises(MlUsePreflightConflict):
        await service.coverage(db_session, actor_user_id=compiled["actor_user_id"], parent=parent, current_inspection=current)
    await write_snapshot(db_session)
    withdrawn = await recorded(db_session, successor(args, restored["decision"], decision="revoke", basis_code="withdrawn", expires_epoch=None))
    assert withdrawn["decision"]["decision"] == "revoke"  # purge cannot block rights withdrawal


async def test_exact_pins_independence_and_closed_use_scope(db_session):
    seeded, compiled, _, _, _, args = await fixture(db_session)
    self_role = await decide(db_session, arguments(seeded["people"], role="rights_reviewer", user_id=str(compiled["actor_user_id"])))
    before = await state(db_session)
    cases = [
        {"resource_id": "a" * 64}, {"submission_sha256": "a" * 64}, {"inventory_sha256": "a" * 64},
        {"purpose": "public_rps_metadata"}, {"evidence_sha256": None}, {"basis_code": "rights_unresolved"},
        {"expires_epoch": 1}, {"expires_epoch": args["expires_epoch"] + 86400}, {"expires_epoch": True},
        {"reviewer_grant_id": str(uuid4())}, {"curator_grant_id": str(uuid4())},
        {"decision": "revoke", "expires_epoch": None, "basis_code": "withdrawn"},
        {"actor_user_id": compiled["actor_user_id"], "reviewer_grant_id": self_role["decision"]["id"],
         "curator_grant_id": str(seeded["people"]["grants"]["curator"])},
    ]
    for changes in cases:
        with pytest.raises((ValueError, ResearchAccessDenied)):
            await service.decide(db_session, **{**args, **changes})
        assert await state(db_session) == before, changes
    first = await recorded(db_session, args)
    stable = await state(db_session)
    for changes in ({"request_key": "new-root"}, {"evidence_sha256": "b" * 64}, {"expires_epoch": args["expires_epoch"] - 1}):
        with pytest.raises(MlUsePreflightConflict):
            await service.decide(db_session, **{**args, **changes}, dry_run=False, expected_intent_sha256=first["intent_sha256"])
        assert await state(db_session) == stable


async def test_direct_sql_guards_reject_resealed_forgery_and_immutable_history(db_session):
    _, compiled, _, _, parent, args = await fixture(db_session)
    first = await recorded(db_session, args)
    relation = Base.metadata.tables[TABLE]
    original = dict((await db_session.execute(sa.select(relation).where(relation.c.id == UUID(first["decision"]["id"])))).mappings().one())
    before = await state(db_session)
    for mode in ("resource", "submission", "scope", "actor", "grant", "expired", "late", "root", "predecessor", "missing_evidence"):
        row = {**original, "id": uuid4(), "request_key": "synthetic-sql-" + uuid4().hex}
        row.update(supersedes_id=original["id"], supersedes_sha256=original["record_sha256"])
        if mode == "resource":
            row["resource_id"] = "f" * 64
        elif mode == "submission":
            row["submission_sha256"] = "f" * 64
        elif mode == "scope":
            row["purpose"] = "public_rps_metadata"
        elif mode == "actor":
            row["actor_user_id"] = compiled["actor_user_id"]
        elif mode == "grant":
            row["reviewer_grant_id"] = parent["requester_grant_id"]
        elif mode == "expired":
            row["expires_epoch"] = 1
        elif mode == "late":
            row["expires_epoch"] += 86400
        elif mode == "root":
            row.update(supersedes_id=None, supersedes_sha256=None)
        elif mode == "predecessor":
            row["supersedes_sha256"] = "f" * 64
        else:
            row["evidence_sha256"] = None
        values = service.body(row)
        row["intent_sha256"] = digest({"version": INTENT_VERSION, **{key: values[key] for key in INTENT_FIELDS}})
        row["record_sha256"] = digest(service.body(row))
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(relation.insert().values(**row))
        assert await state(db_session) == before, mode
    for query in ("UPDATE ml_use_rights_decisions SET decision='deny'", "DELETE FROM ml_use_rights_decisions", "TRUNCATE ml_use_rights_decisions CASCADE"):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(sa.text(query))
        assert await state(db_session) == before


async def test_expiry_and_reviewer_membership_changes_hold_coverage(db_session):
    _, compiled, _, _, parent, args = await fixture(db_session)
    denied = await recorded(db_session, {**args, "decision": "deny", "basis_code": "rights_unresolved",
                                        "expires_epoch": None, "evidence_sha256": None})
    assert denied["decision"]["decision"] == "deny"
    # Real short-lived synthetic permission; no trigger bypass or clock mutation.
    now = await db_session.scalar(sa.select(sa.func.extract("epoch", sa.func.clock_timestamp())))
    first = await recorded(db_session, successor(args, denied["decision"], expires_epoch=int(now) + 3))
    await db_session.commit()
    await asyncio.sleep(3.1)
    await read_snapshot(db_session)
    observed = await ml_use_currentness.inspect_current_inputs(db_session, **compiled)
    checked = await service.coverage(db_session, actor_user_id=compiled["actor_user_id"], parent=parent, current_inspection=observed)
    assert checked["status_counts"]["expired"] == 1 and not checked["source_permission_granted"]
    await write_snapshot(db_session)
    await recorded(db_session, successor(args, first["decision"]))
    await db_session.execute(sa.update(User).where(User.id == args["actor_user_id"]).values(is_active=False))
    await read_snapshot(db_session)
    observed = await ml_use_currentness.inspect_current_inputs(db_session, **compiled)
    checked = await service.coverage(db_session, actor_user_id=compiled["actor_user_id"], parent=parent, current_inspection=observed)
    assert checked["status_counts"]["reviewer_unavailable"] == 1 and not checked["source_permission_granted"]


@pytest.mark.parametrize("endpoint", ["/inspect", "/decisions", "/outcome", "/check"])
async def test_anonymous_before_private_body(client, monkeypatch, endpoint):
    async def forbidden(*_a):
        pytest.fail("private body consumed before admission")
    monkeypatch.setattr(router, "body", forbidden)
    response = await client.post(BASE + endpoint, content=b"PRIVATE")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "private, no-store"


async def test_http_preview_history_unknown_commit_closed_body_and_live_owner_check(client, db_session, monkeypatch):
    _, compiled, values, _, parent, args = await fixture(db_session)
    await db_session.commit()
    request = {key: value for key, value in args.items() if key != "actor_user_id"}
    request["purpose"] = "private_baseline_evaluation"
    actor_headers = auth(args["actor_user_id"])
    inspected = await client.post(BASE + "/inspect", json=inspect_args(args), headers=actor_headers)
    assert inspected.status_code == 200 and inspected.json()["resource_count"] == len(service.resources(parent)), inspected.text
    assert len(inspected.json()["resources"]) <= 25
    private = await client.post(BASE + "/decisions", json={**request, "actor_user_id": str(compiled["actor_user_id"])}, headers=actor_headers)
    assert private.status_code == 400 and str(compiled["actor_user_id"]) not in private.text
    preview = await client.post(BASE + "/decisions", json=request, headers=actor_headers)
    assert preview.status_code == 200 and not preview.json()["committed"], preview.text
    request.update(dry_run=False, expected_intent_sha256=preview.json()["result"]["intent_sha256"])
    close = AsyncSessionTransaction.__aexit__
    operation = service.decide
    async def marked(db, **kw):
        result = await operation(db, **kw)
        db.info["synthetic_lost_rights_reply"] = True
        return result
    async def lost(self, *kw):
        await close(self, *kw)
        if not self.nested and self.session.info.get("synthetic_lost_rights_reply"):
            raise SQLAlchemyError("PRIVATE LOST RIGHTS REPLY")
    with monkeypatch.context() as patch:
        patch.setattr(service, "decide", marked)
        patch.setattr(AsyncSessionTransaction, "__aexit__", lost)
        failed = await client.post(BASE + "/decisions", json=request, headers=actor_headers)
    assert failed.status_code == 503 and failed.headers["x-operation-state"] == "unknown", failed.text
    assert "PRIVATE" not in failed.text
    recovery = {key: request[key] for key in ("request_key", "expected_intent_sha256")}
    recovered = await client.post(BASE + "/outcome", json=recovery, headers=actor_headers)
    assert recovered.status_code == 200 and recovered.json()["committed"], recovered.text
    replay = await client.post(BASE + "/decisions", json=request, headers=actor_headers)
    assert replay.status_code == 200 and replay.json()["result"]["replayed"], replay.text
    assert replay.json()["result"]["decision"] == recovered.json()["result"]["decision"]
    # Real SQL reinspection, but this test's compiler proof is explicitly doubled.
    async def rebuilt(_user, raw):
        return raw, {}, compiled["reconstruction"]
    monkeypatch.setattr(router.preflight, "_rebuild_bytes", rebuilt)
    checked = await client.post(BASE + "/check", json=lookup(values), headers=auth(compiled["actor_user_id"]))
    assert checked.status_code == 200 and checked.json()["status_counts"]["allow_recorded"] == 1, checked.text
    assert not checked.json()["source_permission_granted"]
    other = await client.post(BASE + "/outcome", json=recovery, headers=auth(compiled["actor_user_id"]))
    assert other.status_code == 403  # requester is not an independent rights reviewer


async def test_nonadmitted_roles_never_read_body_and_disabled_registry_is_private(client, db_session, monkeypatch):
    seeded, _, _, _, _, _ = await fixture(db_session)
    await db_session.commit()
    async def forbidden(*_a):
        pytest.fail("body was consumed before independent rights admission")
    monkeypatch.setattr(router, "body", forbidden)
    for role in ("admin", "curator", "reviewer", "publisher", "member"):
        for endpoint in ("/inspect", "/decisions", "/outcome"):
            response = await client.post(BASE + endpoint, content=b"PRIVATE", headers=auth(seeded["people"][role]))
            assert response.status_code == 403, (role, endpoint, response.text)
            assert response.headers["cache-control"] == "private, no-store"
    monkeypatch.setenv("ML_USE_GOVERNANCE_ENABLED", "false")
    get_settings.cache_clear()
    response = await client.post(BASE + "/decisions", content=b"PRIVATE")
    assert response.status_code == 404 and response.headers["cache-control"] == "private, no-store"


async def test_concurrent_commit_has_one_exact_recoverable_decision(client, db_session):
    _, _, _, _, _, args = await fixture(db_session)
    await db_session.commit()
    request = {key: value for key, value in args.items() if key != "actor_user_id"}
    request["purpose"] = "private_baseline_evaluation"
    headers = auth(args["actor_user_id"])
    preview = await client.post(BASE + "/decisions", json=request, headers=headers)
    assert preview.status_code == 200, preview.text
    request.update(dry_run=False, expected_intent_sha256=preview.json()["result"]["intent_sha256"])
    results = await asyncio.gather(*(client.post(BASE + "/decisions", json=request, headers=headers) for _ in range(2)))
    assert all(result.status_code in {200, 503} for result in results) and any(result.status_code == 200 for result in results)
    recovered = await client.post(BASE + "/outcome", json={key: request[key] for key in ("request_key", "expected_intent_sha256")}, headers=headers)
    assert recovered.status_code == 200 and recovered.json()["committed"], recovered.text
    rows = [row for row in (await state(db_session))[TABLE] if row["actor_user_id"] == str(args["actor_user_id"])]
    assert len(rows) == 1 and rows[0]["id"] == recovered.json()["result"]["decision"]["id"]


@pytest.mark.parametrize("case,permitted", [("all_gates", True), ("unreviewed", False), ("denied", False),
    ("revoked", False), ("expired", False), ("reviewer_unavailable", False), ("source_hold", False), ("frozen_drift", False)])
async def test_coverage_conjunction_truth_table_with_explicit_gate_doubles(monkeypatch, case, permitted):
    """Logical combination only, NOT genuine source/role/legal verification.

    Native cases above check real ledger/currentness denial; this isolated table
    also verifies the positive Boolean branch without manufacturing an accepted
    scientific dataset or changing the deliberately held integration fixture.
    """
    uid, resource_id = str(uuid4()), "a" * 64
    parent = {"id": uuid4(), "actor_user_id": uid, "requester_grant_id": uuid4(), "curator_grant_id": uuid4(),
        "record_sha256": "b" * 64, "inventory_sha256": "c" * 64, "request_sha256": "d" * 64,
        "envelope_sha256": "e" * 64, "expires_at": datetime.fromtimestamp(200, UTC)}
    head = {"id": uuid4(), "record_sha256": "f" * 64, "decision": "allow", "reviewer_current": True, "expires_epoch": 200}
    if case in {"denied", "revoked"}:
        head["decision"] = {"denied": "deny", "revoked": "revoke"}[case]
    if case == "expired":
        head["expires_epoch"] = 100
    if case == "reviewer_unavailable":
        head["reviewer_current"] = False
    monkeypatch.setattr(service, "_read_session", AsyncMock())
    monkeypatch.setattr(service, "admission", AsyncMock())
    monkeypatch.setattr(service, "resources", lambda _parent: {resource_id: {}})
    monkeypatch.setattr(service, "heads", AsyncMock(return_value={} if case == "unreviewed" else {resource_id: head}))
    observed = {"dependency_inventory_sha256": parent["inventory_sha256"], "request_sha256": parent["request_sha256"],
        "reconstruction": {"envelope_sha256": parent["envelope_sha256"]}, "companion_observations_rechecked_online": True,
        "online_private_input_reconstruction_verified": True,
        "catalogue_and_scientific_gate": "held_or_unavailable" if case == "source_hold" else "no_hold_observed",
        "requirements": [{"frozen_row_changed": case == "frozen_drift"}]}
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[100, True]))
    result = await service.coverage(db, actor_user_id=uid, parent=parent, current_inspection=observed)
    assert result["source_permission_granted"] is permitted
    assert result["recorded_permissions_complete"] is (case in {"all_gates", "source_hold", "frozen_drift"})
    assert result["training_execution"] == "disabled"
    assert not result["run_authorization_granted"] and not result["ml_training_approved"] and not result["public_release"]
    assert not result["external_dependency_completeness_proven"] and not result["legal_evidence_independently_verified"]
