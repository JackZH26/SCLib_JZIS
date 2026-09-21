"""Actual reviewed result/original-passage links on disposable PostgreSQL."""
from __future__ import annotations

from copy import deepcopy
import asyncio
import json
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, get_engine
from services import auth_service
from services import scientific_result_passage as service
from services.research_access import ResearchAccessDenied
from tests.test_research_publication import actors
from tests.test_scientific_mixed_ask import AMBIENT_MIXED
from tests.test_scientific_mixed_ask import mixed_generation as _mixed_generation

mixed_generation = _mixed_generation


async def _pair(client):
    response = await client.post("/v1/ask", json={"question": AMBIENT_MIXED, "max_sources": 3})
    assert response.status_code == 200, response.text
    payload = response.json()
    return (payload["scientific_results"][0]["binding"]["parent_result_revision_id"],
            payload["sources"][0]["evidence_provenance"]["evidence_revision_id"])


async def _serial():
    db = AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE"), expire_on_commit=False)
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    return db


async def _establish(client):
    parent_id, evidence_id = await _pair(client)
    db = await _serial()
    try:
        people = await actors(db)
        context = await service.action_context(db, actor_user_id=people["reviewer"],
            parent_result_revision_id=parent_id, source_evidence_revision_id=evidence_id)
        request = service.request_from_context(context, request_key="synthetic-link:" + uuid4().hex,
            action="establish")
        before = await db.scalar(sa.text("SELECT count(*) FROM scientific_result_passage_links"))
        preview = await service.review(db, actor_user_id=people["reviewer"], request=request)
        assert await db.scalar(sa.text("SELECT count(*) FROM scientific_result_passage_links")) == before
        receipt = await service.review(db, actor_user_id=people["reviewer"], request=request,
            expected_preview_sha256=preview["preview_sha256"], dry_run=False)
        await db.commit()
    finally:
        await db.close()
    return people, context, request, preview, receipt


async def test_reviewed_link_preview_commit_replay_and_mixed_consumption(client, mixed_generation):
    people, context, request, preview, receipt = await _establish(client)
    assert context["can_review"] is True and context["current_head"] is None
    assert preview["database_mutated"] is False and preview["can_commit"] is True
    assert receipt["action"] == "establish" and receipt["committed"] is False
    assert receipt["scientific_acceptance"] is False and receipt["causal_explanation_established"] is False

    db = await _serial()
    try:
        replay = await service.review(db, actor_user_id=people["reviewer"], request=request,
            expected_preview_sha256=preview["preview_sha256"], dry_run=False)
        assert replay["replayed"] is True and replay["bridge_record_sha256"] == receipt["bridge_record_sha256"]
        resolved = await service.resolve_current_links(db, [
            (receipt["parent_result_revision_id"], receipt["source_evidence_revision_id"]),
        ])
        assert resolved, "the committed current reviewed link must resolve in a stable snapshot"
    finally:
        await db.close()

    response = await client.post("/v1/ask", json={"question": AMBIENT_MIXED, "max_sources": 3})
    assert response.status_code == 200, response.text
    payload = response.json()
    established = [item for item in payload["scientific_mixed"]["associations"] if item["status"] == "established"]
    assert len(established) == 1, {
        "expected": (receipt["parent_result_revision_id"], receipt["source_evidence_revision_id"]),
        "actual": [(item["parent_result_revision_id"], item["source_evidence_revision_id"], item["status"])
                   for item in payload["scientific_mixed"]["associations"]],
    }
    assert established[0]["bridge_revision_id"] == receipt["bridge_revision_id"]
    assert established[0]["bridge_record_sha256"] == receipt["bridge_record_sha256"]
    assert established[0]["reason_code"] == "reviewed_result_passage_bridge_current"
    assert payload["answer_mode"] == "abstention" and payload["tokens_used"] == 0
    assert payload["scientific_mixed"]["scientific_acceptance"] is False
    assert "reviewed link" in payload["answer"] and "causal explanation is not established" in payload["answer"]


async def test_withdrawal_removes_positive_consumption_without_erasing_history(client, mixed_generation):
    people, _, _, _, establish = await _establish(client)
    db = await _serial()
    try:
        context = await service.action_context(db, actor_user_id=people["reviewer"],
            parent_result_revision_id=establish["parent_result_revision_id"],
            source_evidence_revision_id=establish["source_evidence_revision_id"])
        assert context["current_head"]["action"] == "establish"
        request = service.request_from_context(context, request_key="synthetic-withdraw:" + uuid4().hex,
            action="withdraw")
        preview = await service.review(db, actor_user_id=people["reviewer"], request=request)
        withdrawn = await service.review(db, actor_user_id=people["reviewer"], request=request,
            expected_preview_sha256=preview["preview_sha256"], dry_run=False)
        await db.commit()
    finally:
        await db.close()
    assert withdrawn["action"] == "withdraw"

    response = await client.post("/v1/ask", json={"question": AMBIENT_MIXED, "max_sources": 3})
    assert response.status_code == 200, response.text
    mixed = response.json()["scientific_mixed"]
    assert all(item["status"] == "not_established" for item in mixed["associations"])
    assert "reviewed_result_passage_bridge_missing" in mixed["reason_codes"]

    db = await _serial()
    try:
        links = Base.metadata.tables["scientific_result_passage_links"]
        rows = (await db.execute(sa.select(links).where(
            links.c.parent_result_revision_id == UUID(establish["parent_result_revision_id"]),
            links.c.source_evidence_revision_id == UUID(establish["source_evidence_revision_id"]),
        ).order_by(links.c.created_at))).mappings().all()
        assert [row["action"] for row in rows] == ["establish", "withdraw"]
        with pytest.raises(DBAPIError):
            await db.execute(sa.update(links).where(links.c.id == rows[0]["id"]).values(action="withdraw"))
        await db.rollback()
    finally:
        await db.close()


async def test_only_current_reviewer_can_write_and_exact_hash_changes_conflict(client, mixed_generation):
    parent_id, evidence_id = await _pair(client)
    db = await _serial()
    try:
        people = await actors(db)
        context = await service.action_context(db, actor_user_id=people["reviewer"],
            parent_result_revision_id=parent_id, source_evidence_revision_id=evidence_id)
        request = service.request_from_context(context, request_key="synthetic-invalid:" + uuid4().hex,
            action="establish")
        with pytest.raises(ResearchAccessDenied):
            await service.review(db, actor_user_id=people["member"], request=request)
        changed = deepcopy(request)
        changed["expected_source_content_sha256"] = "0" * 64
        with pytest.raises(service.ResultPassageConflict):
            await service.review(db, actor_user_id=people["reviewer"], request=changed)
    finally:
        await db.close()


async def test_private_http_context_and_receipt_require_current_reviewer(client, mixed_generation):
    people, context, request, _, receipt = await _establish(client)
    reviewer_token, _ = auth_service.create_access_token(people["reviewer"])
    member_token, _ = auth_service.create_access_token(people["member"])
    body = {"parent_result_revision_id": context["parent_result_revision_id"],
            "source_evidence_revision_id": context["source_evidence_revision_id"]}
    response = await client.post("/v1/ml/scientific-review/result-passage-links/context", json=body,
        headers={"Authorization": f"Bearer {reviewer_token}"})
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    assert response.json()["current_head"]["bridge_revision_id"] == receipt["bridge_revision_id"]
    denied = await client.post("/v1/ml/scientific-review/result-passage-links/preview", json=request,
        headers={"Authorization": f"Bearer {member_token}"})
    assert denied.status_code == 403
    found = await client.get(f"/v1/ml/scientific-review/result-passage-links/requests/{request['request_key']}",
        headers={"Authorization": f"Bearer {reviewer_token}"})
    assert found.status_code == 200 and found.json()["bridge_revision_id"] == receipt["bridge_revision_id"]


@pytest.mark.parametrize("change", ["revoke", "disable_user", "unverify_user", "replace_passage", "source_changed"])
async def test_live_changes_remove_positive_links_but_preserve_receipts(client, mixed_generation, change):
    from services import research_publication

    people, context, request, _, receipt = await _establish(client)
    db = await _serial()
    try:
        if change == "revoke":
            await research_publication.revoke_role(db, actor_user_id=people["admin"],
                grant_id=people["grants"]["reviewer"], reason_code="synthetic_revocation", dry_run=False)
        elif change in {"disable_user", "unverify_user"}:
            users = Base.metadata.tables["users"]
            await db.execute(users.update().where(users.c.id == people["reviewer"]).values(
                **{"is_active" if change == "disable_user" else "email_verified": False}))
        elif change == "replace_passage":
            await db.execute(sa.text("UPDATE chunks SET text='Synthetic changed passage' WHERE id=(SELECT chunk_key FROM rag_evidence_revisions WHERE id=:id)"),
                {"id": UUID(context["source_evidence_revision_id"])})
        else:
            await db.execute(sa.text("UPDATE papers SET title='Synthetic corrected source' WHERE id=:id"), {"id": context["paper_id"]})
        await db.commit()
    finally:
        await db.close()
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        await db.execute(sa.text("SET TRANSACTION READ ONLY"))
        assert await service.resolve_current_links(db, [(context["parent_result_revision_id"], context["source_evidence_revision_id"])]) == {}
        links = Base.metadata.tables["scientific_result_passage_links"]
        retained = (await db.execute(sa.select(links).where(links.c.id == UUID(receipt["bridge_revision_id"])))).mappings().one()
        assert retained["record_sha256"] == receipt["bridge_record_sha256"]


async def test_http_preview_commit_replay_and_conflicting_request_are_atomic(client, mixed_generation):
    parent_id, evidence_id = await _pair(client)
    db = await _serial()
    try:
        people = await actors(db)
        await db.commit()
    finally:
        await db.close()
    token, _ = auth_service.create_access_token(people["reviewer"])
    headers = {"Authorization": f"Bearer {token}"}
    root = "/v1/ml/scientific-review/result-passage-links"
    response = await client.post(root + "/context", json={"parent_result_revision_id": parent_id,
        "source_evidence_revision_id": evidence_id}, headers=headers)
    assert response.status_code == 200, response.text
    request = service.request_from_context(response.json(), request_key="synthetic-http:" + uuid4().hex, action="establish")
    preview = await client.post(root + "/preview", json=request, headers=headers)
    assert preview.status_code == 200, preview.text
    absent = await client.get(root + "/requests/" + request["request_key"], headers=headers)
    assert absent.status_code == 404
    body = {"request": request, "expected_preview_sha256": "0" * 64}
    assert (await client.post(root + "/commit", json=body, headers=headers)).status_code == 409
    body["expected_preview_sha256"] = preview.json()["preview_sha256"]
    for replayed in (False, True):
        committed = await client.post(root + "/commit", json=body, headers=headers)
        assert committed.status_code == 200, committed.text
        assert committed.json()["committed"] is True and committed.json()["replayed"] is replayed
        assert committed.headers["cache-control"] == "private, no-store"
    changed = deepcopy(request)
    changed["expected_claim_identity_sha256"] = "0" * 64
    assert (await client.post(root + "/preview", json=changed, headers=headers)).status_code == 409
    duplicate = json.dumps(request)[:-1] + ',"action":"withdraw"}'
    invalid = await client.post(root + "/preview", content=duplicate,
        headers={**headers, "Content-Type": "application/json"})
    assert invalid.status_code == 400
    assert (await client.post(root + "/preview", content=b"x" * (service.MAX_BYTES + 1),
        headers={**headers, "Content-Type": "application/json"})).status_code == 413


async def test_stale_source_can_be_withdrawn_but_cannot_be_reestablished(client, mixed_generation):
    people, context, _, _, _ = await _establish(client)
    db = await _serial()
    try:
        original_title = await db.scalar(sa.text("SELECT title FROM papers WHERE id=:id"),
            {"id": context["paper_id"]})
        await db.execute(sa.text("UPDATE papers SET title='Synthetic changed source' WHERE id=:id"),
            {"id": context["paper_id"]})
        await db.commit()
    finally:
        await db.close()
    db = await _serial()
    try:
        stale = await service.action_context(db, actor_user_id=people["reviewer"],
            parent_result_revision_id=context["parent_result_revision_id"],
            source_evidence_revision_id=context["source_evidence_revision_id"])
        assert stale["can_withdraw"] and not stale["can_establish"]
        request = service.request_from_context(stale, request_key="synthetic-stale-withdraw:" + uuid4().hex, action="withdraw")
        changed = {**request, "expected_source_content_sha256": "0" * 64}
        with pytest.raises(service.ResultPassageConflict):
            await service.review(db, actor_user_id=people["reviewer"], request=changed)
        preview = await service.review(db, actor_user_id=people["reviewer"], request=request)
        withdrawn = await service.review(db, actor_user_id=people["reviewer"], request=request,
            expected_preview_sha256=preview["preview_sha256"], dry_run=False)
        assert withdrawn["action"] == "withdraw"
        fresh = await service.action_context(db, actor_user_id=people["reviewer"],
            parent_result_revision_id=context["parent_result_revision_id"],
            source_evidence_revision_id=context["source_evidence_revision_id"])
        assert not fresh["can_establish"] and not fresh["can_withdraw"]
        request = service.request_from_context(fresh, request_key="synthetic-stale-reestablish:" + uuid4().hex, action="establish")
        with pytest.raises(service.ResultPassageConflict):
            await service.review(db, actor_user_id=people["reviewer"], request=request)
        assert (await service.inspect_request(db, actor_user_id=people["reviewer"],
            request_key=withdrawn["request_key"]))["action"] == "withdraw"
        links = Base.metadata.tables["scientific_result_passage_links"]
        row = dict((await db.execute(sa.select(links).where(
            links.c.id == UUID(withdrawn["bridge_revision_id"])))).mappings().one())
        row.update(id=uuid4(), action="establish", reason_code="reviewed_exact_claim_sample_passage",
            request_key="synthetic-stale-direct:" + uuid4().hex,
            predecessor_id=row["id"], predecessor_sha256=row["record_sha256"])
        with pytest.raises(DBAPIError) as denied:
            async with db.begin_nested():
                await db.execute(links.insert().values(**row))
        assert getattr(denied.value.orig, "sqlstate", None) == "23514"
        assert "result_passage_current_inputs_required" in str(denied.value.orig)
        await db.execute(sa.text("UPDATE papers SET title=:title WHERE id=:id"),
            {"id": context["paper_id"], "title": original_title})
        assert await service.resolve_current_links(db, [(context["parent_result_revision_id"],
            context["source_evidence_revision_id"])]) == {}
        await db.commit()
    finally:
        await db.close()


async def test_competing_previews_cannot_fork_a_reviewed_pair(client, mixed_generation):
    parent_id, evidence_id = await _pair(client)
    db = await _serial()
    try:
        people = await actors(db)
        context = await service.action_context(db, actor_user_id=people["reviewer"],
            parent_result_revision_id=parent_id, source_evidence_revision_id=evidence_id)
        requests = [service.request_from_context(context, request_key="synthetic-race:" + uuid4().hex,
            action="establish") for _ in range(2)]
        previews = [await service.review(db, actor_user_id=people["reviewer"], request=request) for request in requests]
        await db.commit()
    finally:
        await db.close()

    async def commit_one(request, preview):
        session = await _serial()
        try:
            receipt = await service.review(session, actor_user_id=people["reviewer"], request=request,
                expected_preview_sha256=preview["preview_sha256"], dry_run=False)
            await session.commit()
            return receipt
        except (DBAPIError, service.ResultPassageConflict) as exc:
            await session.rollback()
            if isinstance(exc, DBAPIError):
                assert getattr(exc.orig, "sqlstate", None) in {"40001", "23514", "55P03"}
            return None
        finally:
            await session.close()

    results = await asyncio.gather(*(commit_one(request, preview) for request, preview in zip(requests, previews)))
    assert sum(value is not None for value in results) == 1
    async with AsyncSession(get_engine()) as session:
        links = Base.metadata.tables["scientific_result_passage_links"]
        assert await session.scalar(sa.select(sa.func.count()).select_from(links).where(
            links.c.parent_result_revision_id == UUID(parent_id), links.c.source_evidence_revision_id == UUID(evidence_id))) == 1
