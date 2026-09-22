"""Native private retention tests; SQL audit fixtures use explicit worker doubles.

The genuine compiler/upload/worker path is independently extended in the request
pipeline test. Fixture-only clock aging below is not an allowed production write.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSessionTransaction

from models.db import Base, User
from models.ml_use_submissions_v1 import RETENTION_POLICY, TABLES
from routers import ml_use_submissions as router
from services import ml_use_currentness
from services import ml_use_submissions as service
from services.ml_audited_dataset import canonical, digest, loads
from services.ml_use_preflight import MlUsePreflightConflict
from services.research_audit_retention import has_research_audit_references
from tests.test_ml_label_capture import read_snapshot, write_snapshot
from tests.test_ml_use_currentness import db_session as db_session
from tests.test_ml_use_currentness import setup
from tests.test_ml_use_preflight import enabled as enabled
from tests.test_ml_use_preflight import private
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import state

BASE = "/v1/ml/use/requests"


async def prepared(db):
    seeded, args = await setup(db)
    observed = await ml_use_currentness.inspect_current_inputs(db, **args)
    proposal = service.intent(request_key="synthetic-intake-" + uuid4().hex,
        envelope_sha256=hashlib.sha256(args["raw"]).hexdigest(),
        inventory_sha256=observed["dependency_inventory_sha256"], retention_policy=RETENTION_POLICY)
    values = {"actor_user_id": args["actor_user_id"], "raw": args["raw"], "observation": observed,
              "submission_intent": proposal, "expected_intent_sha256": digest(proposal)}
    await write_snapshot(db)
    return seeded, args, values


def lookup(values):
    return {"request_key": values["submission_intent"]["request_key"],
            "expected_intent_sha256": values["expected_intent_sha256"]}


def headers(values):
    proposal = values["submission_intent"]
    return {**auth(values["actor_user_id"]), "Content-Type": "application/json",
        "Idempotency-Key": proposal["request_key"], "X-SCLib-Envelope-Sha256": proposal["envelope_sha256"],
        "X-SCLib-Inventory-Sha256": proposal["inventory_sha256"], "X-SCLib-Retention-Policy": RETENTION_POLICY,
        "X-SCLib-Intent-Sha256": digest(proposal)}


async def stored(db):
    seeded, args, values = await prepared(db)
    result = await service.store_submission(db, **values)
    await db.commit()
    return seeded, args, values, result


async def test_native_atomic_retention_exact_noop_recovery_purge_and_no_authority(db_session):
    seeded, args, values = await prepared(db_session)
    before = await state(db_session)
    first = await service.store_submission(db_session, **values)
    identifier = UUID(first["submission_id"])
    await db_session.commit()
    after = await state(db_session)
    assert {key for key in before if before[key] != after[key]} == {TABLES[0], TABLES[1], "research_publication_epoch"}
    assert first["stored_observation"] == values["observation"] and first["request_persisted"]
    assert first["input_state"] == "retained" and not first["currentness_checked_now"]
    assert await has_research_audit_references(db_session, values["actor_user_id"])
    replay = await service.store_submission(db_session, **values)
    assert replay["replayed"] and replay["record_sha256"] == first["record_sha256"]
    assert await state(db_session) == after
    await read_snapshot(db_session)
    assert await service.retained_inputs(db_session, actor_user_id=args["actor_user_id"], **lookup(values)) == args["raw"]
    observed = await service.outcome(db_session, actor_user_id=args["actor_user_id"], **lookup(values))
    assert observed == replay
    for key in ("source_permission_granted", "ml_training_approved", "run_authorization_granted", "currentness_checked_now"):
        assert observed[key] is False
    await write_snapshot(db_session)
    purged = await service.purge_inputs(db_session, actor_user_id=args["actor_user_id"], **lookup(values))
    assert purged["input_state"] == "purged" and purged["record_sha256"] == first["record_sha256"]
    await db_session.commit()
    final = await state(db_session)
    assert all(row["submission_id"] != str(identifier) for row in final[TABLES[1]])
    assert final[TABLES[0]] == after[TABLES[0]]
    assert any(row["submission_id"] == str(identifier) for row in final[TABLES[2]])
    await service.purge_inputs(db_session, actor_user_id=args["actor_user_id"], **lookup(values))
    assert await state(db_session) == final
    await read_snapshot(db_session)
    with pytest.raises(service.SubmissionNotObserved):
        await service.retained_inputs(db_session, actor_user_id=args["actor_user_id"], **lookup(values))


@pytest.mark.parametrize("change", ["inventory", "upload", "policy", "intent", "authority", "actor"])
async def test_resealed_or_retargeted_declarations_do_not_store(db_session, change):
    _, _, values = await prepared(db_session)
    before = await state(db_session)
    altered = deepcopy(values)
    if change == "inventory":
        altered["submission_intent"]["inventory_sha256"] = "a" * 64
        altered["expected_intent_sha256"] = digest(altered["submission_intent"])
    elif change == "upload":
        altered["raw"] += b"\n"
    elif change == "policy":
        altered["submission_intent"]["retention_policy"] = "forever"
    elif change == "intent":
        altered["expected_intent_sha256"] = "b" * 64
    elif change == "authority":
        altered["observation"]["ml_training_approved"] = True
    else:
        altered["actor_user_id"] = uuid4()
    with pytest.raises((ValueError, MlUsePreflightConflict)):
        await service.store_submission(db_session, **altered)
    assert await state(db_session) == before


@pytest.mark.parametrize("query", [
    "UPDATE ml_use_submissions SET request_key='changed'", "DELETE FROM ml_use_submissions", "TRUNCATE ml_use_submissions CASCADE",
    "UPDATE ml_use_private_inputs SET payload=decode('00','hex')", "DELETE FROM ml_use_private_inputs", "TRUNCATE ml_use_private_inputs",
])
async def test_database_immutability_and_purge_receipt_guards(db_session, query):
    await stored(db_session)
    before = await state(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(query))
    assert await state(db_session) == before


async def test_service_rollback_never_leaves_metadata_without_payload(db_session):
    _, _, values = await prepared(db_session)
    before = await state(db_session)
    await service.store_submission(db_session, **values)
    await db_session.rollback()
    assert await state(db_session) == before


async def test_native_complete_input_and_resealed_scope_guards(db_session):
    _, args, values, receipt = await stored(db_session)
    relation = Base.metadata.tables[TABLES[0]]
    original = dict((await db_session.execute(sa.select(relation).where(relation.c.id == UUID(receipt["submission_id"])))).mappings().one())
    before = await state(db_session)
    for mode in ("orphan", "intent_scope", "training", "run_permission", "public", "foreign_grant"):
        row = deepcopy(original)
        body = loads(row["record_json"].encode())
        body.update(id=str(uuid4()), request_key="schema-" + mode)
        proposal = {**values["submission_intent"], "request_key": body["request_key"]}
        observed = loads(row["observation_json"].encode())
        if mode == "intent_scope":
            proposal["retention_policy"] = "forever"
        elif mode in {"training", "run_permission", "public"}:
            observed[{"training": "ml_training_approved", "run_permission": "run_authorization_granted", "public": "public_release"}[mode]] = True
        elif mode == "foreign_grant":
            body["requester_grant_id"] = str(uuid4())
        body.update(intent_sha256=digest(proposal), observation_sha256=digest(observed))
        row.update({key: UUID(value) if key in {"id", "actor_user_id", "requester_grant_id", "curator_grant_id"}
                    else value for key, value in body.items()})
        row.update(intent_json=canonical(proposal).decode(), observation_json=canonical(observed).decode(),
                   record_json=canonical(body).decode(), record_sha256=digest(body))
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(relation.insert().values(**row))
                await db_session.execute(sa.text("SET CONSTRAINTS mu72_complete IMMEDIATE"))
        assert await state(db_session) == before, mode
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(Base.metadata.tables[TABLES[2]].insert().values(
                submission_id=UUID(receipt["submission_id"]), actor_user_id=args["actor_user_id"], reason="retention_expired"))
    assert await state(db_session) == before


async def test_expiry_denies_before_loading_bytes_and_sweeper_retains_audit(db_session):
    _, args, values, first = await stored(db_session)
    # Disposable-only controlled clock aging, explicitly bypassing UPDATE guard.
    # Normal runtime writers cannot update this immutable receipt or renew it.
    await db_session.execute(sa.text("ALTER TABLE ml_use_submissions DISABLE TRIGGER mu72_immutable"))
    await db_session.execute(sa.text("UPDATE ml_use_submissions SET created_at=created_at-interval '8 days', "
        "expires_at=expires_at-interval '8 days' WHERE id=:id"), {"id": UUID(first["submission_id"])})
    await db_session.execute(sa.text("ALTER TABLE ml_use_submissions ENABLE TRIGGER mu72_immutable"))
    await read_snapshot(db_session)
    with pytest.raises(service.SubmissionNotObserved):
        await service.retained_inputs(db_session, actor_user_id=args["actor_user_id"], **lookup(values))
    observed = await service.outcome(db_session, actor_user_id=args["actor_user_id"], **lookup(values))
    assert observed["input_state"] == "expired" and observed["record_sha256"] == first["record_sha256"]
    await write_snapshot(db_session)
    cleanup = await service.purge_expired(db_session, actor_user_id=args["actor_user_id"])
    assert cleanup["purged_count"] == 1
    await db_session.commit()
    assert (await service.purge_expired(db_session, actor_user_id=args["actor_user_id"]))["purged_count"] == 0


@pytest.mark.parametrize("path", ["", "/preview", "/outcome", "/recheck", "/purge"])
async def test_anonymous_requests_never_read_body(client, monkeypatch, path):
    async def forbidden(*_a, **_k):
        pytest.fail("read private bytes without admission")
    monkeypatch.setattr(router.preflight, "_reconstruction_body", forbidden)
    monkeypatch.setattr(router, "_lookup_body", forbidden)
    result = await client.post(BASE + path, content=b"PRIVATE", headers={"Content-Type": "application/json"})
    assert result.status_code == 401
    private(result)


async def test_owner_acl_current_admission_and_lost_commit_recovery(client, db_session, monkeypatch):
    seeded, args, values = await prepared(db_session)
    await db_session.commit()
    # Isolated transport failure test uses the explicit fixture worker double.
    async def rebuilt(_user, raw):
        return raw, {}, args["reconstruction"]
    async def inspect(_user, _raw, _rebuilt):
        return values["observation"]
    monkeypatch.setattr(router.preflight, "_rebuild_bytes", rebuilt)
    monkeypatch.setattr(router, "_inspect", inspect)
    operation, close = service.store_submission, AsyncSessionTransaction.__aexit__
    async def mark(db, **kw):
        result = await operation(db, **kw)
        db.info["synthetic_lost_reply"] = True
        return result
    async def lost(self, *kw):
        await close(self, *kw)
        if not self.nested and self.session.info.get("synthetic_lost_reply"):
            raise SQLAlchemyError("PRIVATE LOST REPLY")
    with monkeypatch.context() as patch:
        patch.setattr(service, "store_submission", mark)
        patch.setattr(AsyncSessionTransaction, "__aexit__", lost)
        response = await client.post(BASE, content=args["raw"], headers=headers(values))
    assert response.status_code == 503 and response.headers["x-operation-state"] == "unknown", response.text
    assert "PRIVATE" not in response.text
    recovered = await client.post(BASE + "/outcome", json=lookup(values), headers=auth(args["actor_user_id"]))
    assert recovered.status_code == 200 and recovered.json()["committed"], recovered.text
    repeated = await client.post(BASE, content=args["raw"], headers=headers(values))
    assert repeated.status_code == 200 and repeated.json()["replayed"]
    assert repeated.json()["record_sha256"] == recovered.json()["record_sha256"]
    # A different fully admitted account still cannot inspect this owner's row.
    from tests.test_ml_use_governance import arguments, decide
    people = seeded["people"]
    await decide(db_session, arguments(people, user_id=str(people["admin"])))
    await db_session.commit()
    foreign = await client.post(BASE + "/outcome", json=lookup(values), headers=auth(people["admin"]))
    assert foreign.status_code == 404, foreign.text
    await db_session.execute(sa.update(User).where(User.id == args["actor_user_id"]).values(session_version=1))
    await db_session.commit()
    denied = await client.post(BASE + "/outcome", json=lookup(values), headers=auth(args["actor_user_id"]))
    assert denied.status_code == 401
    assert sum(row["actor_user_id"] == str(args["actor_user_id"]) for row in (await state(db_session))[TABLES[0]]) == 1
