"""Owned native SQL/HTTP tests; all reviewers and documents are synthetic."""
from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSessionTransaction

from models.db import Base, User
from models.ml_run_evidence_v1 import TABLES
from services import ml_run_evidence as evidence
from services import ml_use_runs as runs
from services.ml_use_preflight import MlUsePreflightConflict
from services.research_audit_retention import (
    has_research_audit_references,
    is_research_audit_reference_violation,
)
from tests.test_ml_label_capture import read_snapshot, write_snapshot
from tests.test_ml_use_governance import arguments, decide
from tests.test_ml_use_preflight import enabled as enabled
from tests.test_ml_use_runs import (
    BASE,
    approver,
    fixture,
    plan_ref,
    recorded,
    review_args,
    successor,
)
from tests.test_ml_use_submissions import db_session as db_session
from tests.test_research_audit_retention import private_rows, snapshot
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import add, state

TEXT = "SYNTHETIC review only.\nBudget: 60 CPU seconds; not execution authority.\nΔTc / 数据 / 🧪 <script>never_execute()</script>\n"


def ref(record):
    return {"decision_id": record["id"], "decision_sha256": record["record_sha256"]}


async def setup(db):
    seeded, compiled, _, receipt, actor, args = await fixture(db)
    plan = (await recorded(db, args))["plan"]
    review = {**review_args(actor, plan, receipt), "evidence_text": TEXT,
              "evidence_sha256": hashlib.sha256(TEXT.encode()).hexdigest()}
    return seeded, compiled, receipt, actor, plan, review


@pytest.mark.parametrize("value", [None, "", " \t\n\r", "\u0085\u00a0\u2003", "x\x00y", "\ud800", "é" * 4097],
                         ids=["none", "empty", "whitespace", "unicode_space", "nul", "surrogate", "utf8_limit"])
def test_text_rejects_invalid_input(value):
    with pytest.raises(ValueError, match="ml_use_reconstruction_invalid"):
        evidence.text_bytes(value, "a" * 64)


def test_text_exact_byte_limit_no_normalization_or_hash_alias():
    raw = ("é" * 4096).encode()
    assert evidence.text_bytes(raw.decode(), hashlib.sha256(raw).hexdigest()) == raw
    with pytest.raises(MlUsePreflightConflict):
        evidence.text_bytes(TEXT, hashlib.sha256(TEXT.strip().encode()).hexdigest())


async def test_atomic_preview_read_purge_no_resurrection_or_implicit_authority(db_session):
    _, _, _, actor, plan, review = await setup(db_session)
    before = await state(db_session)
    await runs.decide(db_session, **review)
    assert await state(db_session) == before
    with pytest.raises(ValueError, match="ml_use_reconstruction_invalid"):
        await runs.decide(db_session, **{**review, "evidence_text": None})
    approval = await recorded(db_session, review, "decision")
    target = ref(approval["decision"])
    await read_snapshot(db_session)
    document = await evidence.read(db_session, actor_user_id=actor["actor_user_id"], **target)
    assert document["text"] == TEXT and document["size_bytes"] == len(TEXT.encode())
    assert document["decision"] == approval["decision"] and document["content_sha256"] == review["evidence_sha256"]
    assert document["training_execution"] == "disabled" and not document["scientific_acceptance"]
    await write_snapshot(db_session)
    purged = await evidence.purge(db_session, actor_user_id=actor["actor_user_id"], **target)
    assert not purged["replayed"] and purged["evidence_state"] == "purged"
    await db_session.commit()
    stable = await state(db_session)
    assert (await evidence.purge(db_session, actor_user_id=actor["actor_user_id"], **target))["replayed"]
    replay = await runs.decide(db_session, **review, dry_run=False, expected_intent_sha256=approval["intent_sha256"])
    assert replay["replayed"] and replay["decision"] == approval["decision"]
    assert await state(db_session) == stable
    await read_snapshot(db_session)
    with pytest.raises(runs.RunNotObserved):
        await evidence.read(db_session, actor_user_id=actor["actor_user_id"], **target)
    inspected = await runs.inspect(db_session, actor_user_id=actor["actor_user_id"], **plan_ref(plan))
    assert inspected["recorded_approval_status"] == "evidence_unavailable"
    await write_snapshot(db_session)
    renewed = await recorded(db_session, successor(review, approval["decision"]), "decision")
    assert renewed["decision"]["id"] != target["decision_id"]


async def test_http_exact_author_roles_session_and_bounded_purge_inputs(client, db_session, monkeypatch):
    seeded, compiled, _, actor, _, review = await setup(db_session)
    other = await approver(db_session, seeded["people"])
    await db_session.commit()
    body = {k: v for k, v in review.items() if k != "actor_user_id"}
    for value in ("", "\t\n", "é" * 4097, "x\x00y"):
        invalid = await client.post(BASE + "/decisions", json={**body, "evidence_text": value,
            "evidence_sha256": hashlib.sha256(value.encode()).hexdigest()}, headers=auth(actor["actor_user_id"]))
        assert invalid.status_code == 400
        if value:
            assert value not in invalid.text
    accepted_text = "é" * 4096
    boundary = await client.post(BASE + "/decisions", json={**body, "evidence_text": accepted_text,
        "evidence_sha256": hashlib.sha256(accepted_text.encode()).hexdigest()}, headers=auth(actor["actor_user_id"]))
    assert boundary.status_code == 200 and boundary.json()["result"]["decision"] is None, boundary.text
    excessive = await client.post(BASE + "/decisions", content=b" " * 16385,
        headers={**auth(actor["actor_user_id"]), "Content-Type": "application/json"})
    assert excessive.status_code == 413
    approval = await recorded(db_session, review, "decision")
    target = ref(approval["decision"])
    await db_session.commit()
    for identity in (None, compiled["actor_user_id"], other["actor_user_id"]):
        for action in ("read", "purge"):
            result = await client.post(BASE + "/evidence/" + action, json=target, headers={} if identity is None else auth(identity))
            assert result.status_code in {401, 403, 404}, result.text
            assert TEXT not in result.text and result.headers["cache-control"] == "private, no-store"
    own = auth(actor["actor_user_id"])
    result = await client.post(BASE + "/evidence/read", json=target, headers=own)
    assert result.status_code == 200, result.text
    assert result.json()["text"] == TEXT and result.json()["decision"] == approval["decision"]
    assert result.headers["cache-control"] == "private, no-store"
    bad = await client.post(BASE + "/evidence/read", json={**target, "decision_sha256": "f" * 64}, headers=own)
    assert bad.status_code == 409 and TEXT not in bad.text
    roles = Base.metadata.tables["ml_use_role_decisions"]
    prior = (await db_session.execute(sa.select(roles).where(roles.c.id == UUID(actor["approver_grant_id"])))).mappings().one()
    await decide(db_session, arguments(seeded["people"], user_id=str(actor["actor_user_id"]), role="run_approver", action="revoke",
        expected_head_id=actor["approver_grant_id"], expected_head_sha256=prior["record_sha256"]))
    await db_session.commit()
    denied = await client.post(BASE + "/evidence/read", json=target, headers=own)
    assert denied.status_code == 403
    original, close = evidence.purge, AsyncSessionTransaction.__aexit__
    async def mark(db, **kw):
        result = await original(db, **kw)
        db.info["synthetic_purge_lost_reply"] = True
        return result
    async def lost(self, *kw):
        await close(self, *kw)
        if not self.nested and self.session.info.get("synthetic_purge_lost_reply"):
            raise SQLAlchemyError("PRIVATE LOST PURGE REPLY")
    with monkeypatch.context() as patch:
        patch.setattr(evidence, "purge", mark)
        patch.setattr(AsyncSessionTransaction, "__aexit__", lost)
        purged = await client.post(BASE + "/evidence/purge", json=target, headers=own)
    assert purged.status_code == 503 and purged.headers["x-operation-state"] == "unknown", purged.text
    assert "PRIVATE" not in purged.text
    repeated = await client.post(BASE + "/evidence/purge", json=target, headers=own)
    assert repeated.status_code == 200 and repeated.json()["result"]["replayed"]
    malformed = await client.post(BASE + "/evidence/purge-expired", json={"limit": 99999}, headers=own)
    assert malformed.status_code == 400
    empty = await client.post(BASE + "/evidence/purge-expired", json={}, headers=own)
    assert empty.status_code == 200 and empty.json()["result"]["purged_count"] == 0
    await db_session.execute(sa.update(User).where(User.id == actor["actor_user_id"]).values(session_version=1))
    await db_session.commit()
    stale = await client.post(BASE + "/evidence/purge", json=target, headers=own)
    assert stale.status_code == 401


async def test_direct_sql_requires_text_and_guards_mutation_purge_history(db_session):
    _, _, _, actor, _, review = await setup(db_session)
    values = {key: str(value) if key == "actor_user_id" else value for key, value in review.items() if key != "evidence_text"}
    with pytest.raises(DBAPIError, match="ml_run_approval_document_required"):
        async with db_session.begin_nested():
            await runs.insert(db_session, values, "decision")
            await db_session.execute(sa.text("SET CONSTRAINTS mu75_complete IMMEDIATE"))
    for payload in (b"\t\n", "\u0085\u2003".encode(), b"x\x00y", b"\xff"):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                row = await runs.insert(db_session, {**values, "evidence_sha256": hashlib.sha256(payload).hexdigest()}, "decision")
                await db_session.execute(Base.metadata.tables[TABLES[0]].insert().values(decision_id=row["id"], payload=payload))
                await db_session.execute(sa.text("SET CONSTRAINTS mu75_complete IMMEDIATE"))
    approval = await recorded(db_session, review, "decision")
    await db_session.commit()
    for statement in (f"UPDATE {TABLES[0]} SET payload=decode('61','hex')", f"DELETE FROM {TABLES[0]}", f"TRUNCATE {TABLES[0]}"):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(sa.text(statement))
    purges = Base.metadata.tables[TABLES[1]]
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(purges.insert().values(decision_id=UUID(approval["decision"]["id"]),
                actor_user_id=actor["actor_user_id"], reason="retention_expired"))
    await evidence.purge(db_session, actor_user_id=actor["actor_user_id"], **ref(approval["decision"]))
    await db_session.commit()
    for statement in (f"UPDATE {TABLES[1]} SET reason='retention_expired'", f"DELETE FROM {TABLES[1]}", f"TRUNCATE {TABLES[1]}"):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(sa.text(statement))
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(Base.metadata.tables[TABLES[0]].insert().values(decision_id=UUID(approval["decision"]["id"]), payload=TEXT.encode()))


async def test_expired_text_cannot_be_read_and_cleanup_is_bounded_with_audit_hold(client, db_session):
    seeded, _, receipt, actor, _, review = await setup(db_session)
    head, decision_ids = None, []
    for _ in range(21):
        approval = await recorded(db_session, review if head is None else successor(review, head), "decision")
        head = approval["decision"]
        decision_ids.append(UUID(head["id"]))
    await db_session.commit()
    assert (await evidence.purge_expired(db_session, actor_user_id=seeded["people"]["admin"]))["purged_count"] == 0
    # Controlled aging in this owned disposable DB only; normal writers cannot mutate retention.
    await db_session.execute(sa.text("ALTER TABLE ml_use_submissions DISABLE TRIGGER mu72_immutable"))
    await db_session.execute(sa.text("UPDATE ml_use_submissions SET created_at=created_at-interval '8 days', "
        "expires_at=expires_at-interval '8 days' WHERE id=:id"), {"id": UUID(receipt["submission_id"])})
    await db_session.execute(sa.text("ALTER TABLE ml_use_submissions ENABLE TRIGGER mu72_immutable"))
    await read_snapshot(db_session)
    with pytest.raises(runs.RunNotObserved):
        await evidence.read(db_session, actor_user_id=actor["actor_user_id"], **ref(head))
    await write_snapshot(db_session)
    # This administrator has no other research role/audit reference. The new
    # purge row alone must protect the account, not some earlier fixture grant.
    janitor = uuid4()
    await add(db_session, "users", id=janitor, email=f"purge-{janitor}@example.test", name="Synthetic purge-only administrator",
              is_active=True, email_verified=True, is_admin=True)
    assert not await has_research_audit_references(db_session, janitor)
    first = await evidence.purge_expired(db_session, actor_user_id=janitor)
    assert first["purged_count"] == 20 and first["more_may_remain"]
    await db_session.commit()
    second = await evidence.purge_expired(db_session, actor_user_id=janitor)
    assert second["purged_count"] == 1 and not second["more_may_remain"]
    await db_session.commit()
    assert await has_research_audit_references(db_session, janitor)
    with pytest.raises(IntegrityError) as caught:
        async with db_session.begin_nested():
            await db_session.execute(sa.delete(User).where(User.id == janitor))
    assert is_research_audit_reference_violation(caught.value)
    await db_session.rollback()
    await private_rows(janitor)
    before = await snapshot(janitor)
    deleted = await client.delete(f"/v1/admin/users/{janitor}", headers=auth(seeded["people"]["admin"]))
    assert deleted.status_code == 409 and deleted.json()["error_code"] == "conflict", deleted.text
    assert "set-cookie" not in deleted.headers and await snapshot(janitor) == before
    for name, expected in ((TABLES[0], 0), (TABLES[1], 21)):
        relation = Base.metadata.tables[name]
        assert await db_session.scalar(sa.select(sa.func.count()).select_from(relation).where(relation.c.decision_id.in_(decision_ids))) == expected
