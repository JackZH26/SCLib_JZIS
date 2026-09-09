"""Private saved-output receipts across real HTTP/SQL, using synthetic evidence.

No provider is called and no fixture is scientific gold. The JSON files written
under pytest's private temporary directory are cross-stack test artifacts only.
"""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from models.db import ApiKey, AskHistory, Base, Chunk, Paper, User, get_session_factory
from models.history_receipts import HistoryEvidenceDetail, HistorySaveDisposition
from routers import ask as ask_router
from services import auth_service, rag
from tests.test_scientific_mixed_ask import AMBIENT_MIXED
from tests.test_scientific_mixed_ask import mixed_generation as _mixed_generation

mixed_generation = _mixed_generation
CLARIFY = "What is the Tc of Mg¹¹B2?"
TABLE = Base.metadata.tables["answer_evidence_receipts"]


def headers(registered_user):
    return {"Authorization": "Bearer " + registered_user[1]}


async def count_history(user_id):
    async with get_session_factory()() as db:
        return await db.scalar(sa.select(sa.func.count()).select_from(AskHistory).where(AskHistory.user_id == user_id))


async def saved_clarification(client, registered_user):
    response = await client.post("/v1/ask", headers=headers(registered_user), json={"question": CLARIFY})
    assert response.status_code == 200, response.text
    assert response.json()["history"]["status"] == "saved", response.text
    return response.json()


@pytest.mark.parametrize("kind,question", [
    ("ordinary", "Summarize the synthetic evidence on pairing"),
    ("structured", "What is the Tc of MgB2 at ambient pressure?"),
    ("mixed", AMBIENT_MIXED),
    ("clarification", CLARIFY),
])
async def test_actual_http_saved_output_round_trip(client, registered_user, mixed_generation, monkeypatch, tmp_path, kind, question):
    if kind == "ordinary":
        def excerpts(_question, sources, **kwargs):
            return rag.extractive_fallback(sources, evidence_packing=kwargs["evidence_packing"], tokens_used=None)
        monkeypatch.setattr(rag, "generate_answer", excerpts)
    response = await client.post("/v1/ask", headers=headers(registered_user),
        json={"question": question, "max_sources": 3, "language": "en"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["history"]["status"] == "saved", response.text
    identifier = body["history"]["history_id"]
    detail = await client.get(f"/v1/history/{identifier}", headers=headers(registered_user))
    assert detail.status_code == 200, detail.text
    assert detail.headers["Cache-Control"] == "private, no-store"
    document = detail.json()
    evidence = document["evidence"]
    assert evidence["status"] == "verified", detail.text
    assert evidence["historical_integrity_verified"] is True
    for name in ("scientific_acceptance", "ml_training_approved", "public_release_authorized", "currentness_revalidated"):
        assert evidence[name] is False
    receipt = evidence["receipt"]
    assert receipt["record_sha256"] == body["history"]["receipt_sha256"]
    assert receipt["history_id"] == identifier == document["entry"]["id"]
    assert receipt["response"] == {key: value for key, value in body.items() if key not in {"history", "remaining", "guest_remaining"}}
    assert document["entry"]["answer"] == body["answer"]
    assert document["entry"]["sources"] == body["sources"]
    assert receipt["request"] == {"question": question, "max_sources": 3, "language": "en"}
    assert len(receipt["bindings"]["items"]) == len(body["sources"]) + len(body["scientific_results"])
    assert evidence["binding_scope"] == ("no_selected_evidence" if kind == "clarification" else "generation_members")
    if kind == "ordinary":
        assert body["sources"] and body["tokens_used"] is None
    if kind in {"mixed", "structured"}:
        assert body["scientific_results"][0]["result"]["tc"]["value"] == 39
        assert document["result_current_evidence"]["sources"]
    else:
        assert document["result_current_evidence"] == {}
    if kind == "mixed":
        assert body["sources"] and body["scientific_mixed"]["status"] == "completed"
    listed = await client.get("/v1/history", headers=headers(registered_user))
    assert listed.status_code == 200, listed.text
    row, = listed.json()["results"]
    assert row["receipt"] == {"version": "ask-history-receipt-summary/1.0.0", "status": "recorded",
        "receipt_sha256": receipt["record_sha256"]}
    assert "response_json" not in listed.text and "bindings_json" not in listed.text
    assert mixed_generation["forbidden_calls"] == []
    (tmp_path / f"answer-history-{kind}.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def test_old_history_is_explicitly_unpinned_and_not_retrofitted(client, registered_user, tmp_path):
    async with get_session_factory()() as db:
        row = AskHistory(user_id=registered_user[0].id, question="An old synthetic question", answer="An old saved answer.",
            sources=[], tokens_used=0, latency_ms=2, language="en")
        db.add(row)
        await db.commit()
        identifier = row.id
    response = await client.get(f"/v1/history/{identifier}", headers=headers(registered_user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evidence"]["status"] == "legacy_unpinned" and body["evidence"]["receipt"] is None
    assert body["entry"]["receipt"]["status"] == "legacy_unpinned"
    async with get_session_factory()() as db:
        assert await db.scalar(sa.select(TABLE.c.history_id).where(TABLE.c.history_id == identifier)) is None
        assert (await db.get(AskHistory, identifier)).evidence_receipt_version is None
    (tmp_path / "answer-history-legacy.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


async def test_history_requires_current_owner_session_and_hides_cross_owner_ids(client, registered_user):
    body = await saved_clarification(client, registered_user)
    identifier = body["history"]["history_id"]
    async with get_session_factory()() as db:
        other = User(email=f"other-{uuid4()}@example.test", name="Other synthetic owner", is_active=True)
        db.add(other)
        await db.commit()
        other_token, _ = auth_service.create_access_token(other.id)
    for path in ("/v1/history", f"/v1/history/{identifier}"):
        anonymous = await client.get(path)
        assert anonymous.status_code == 401 and anonymous.headers["Cache-Control"] == "private, no-store"
    cross = await client.get(f"/v1/history/{identifier}", headers={"Authorization": "Bearer " + other_token})
    missing = await client.get(f"/v1/history/{uuid4()}", headers={"Authorization": "Bearer " + other_token})
    assert cross.status_code == missing.status_code == 404
    assert {key: value for key, value in cross.json().items() if key != "request_id"} == {
        key: value for key, value in missing.json().items() if key != "request_id"}
    assert cross.headers["Cache-Control"] == "private, no-store"
    assert (await client.delete(f"/v1/history/{identifier}", headers={"Authorization": "Bearer " + other_token})).status_code == 404
    async with get_session_factory()() as db:
        await db.execute(sa.update(User).where(User.id == registered_user[0].id).values(session_version=1))
        await db.commit()
    assert (await client.get(f"/v1/history/{identifier}", headers=headers(registered_user))).status_code == 401


async def test_api_key_can_save_once_but_cannot_read_private_history(client, registered_user):
    plain, digest, prefix = auth_service.generate_api_key()
    async with get_session_factory()() as db:
        key = ApiKey(user_id=registered_user[0].id, key_hash=digest, key_prefix=prefix, name="Synthetic receipt key")
        db.add(key)
        await db.commit()
        key_id = key.id
    response = await client.post("/v1/ask", headers={"X-API-Key": plain}, json={"question": CLARIFY})
    assert response.status_code == 200, response.text
    assert response.json()["history"]["status"] == "saved", response.text
    path = "/v1/history/" + response.json()["history"]["history_id"]
    assert (await client.get(path, headers={"X-API-Key": plain})).status_code == 401
    assert (await client.get(path, headers=headers(registered_user))).json()["evidence"]["status"] == "verified"
    async with get_session_factory()() as db:
        assert (await db.get(ApiKey, key_id)).total_requests == 1


async def test_guest_does_not_create_history(client):
    response = await client.post("/v1/ask", json={"question": CLARIFY})
    assert response.status_code == 200, response.text
    assert response.json()["history"] == HistorySaveDisposition(reason_code="guest_request").model_dump()


@pytest.mark.parametrize("with_source", [False, True])
async def test_no_generation_empty_or_legacy_lexical_answer_gets_honest_scope(client, registered_user, monkeypatch, with_source):
    from config import get_settings
    from services import index_retrieval, retrieval
    monkeypatch.setattr(get_settings(), "retrieval_logical_index", "empty-history-" + uuid4().hex)
    if with_source:
        identifier = "synthetic:history-" + uuid4().hex
        async with get_session_factory()() as db:
            db.add(Paper(id=identifier, source="arxiv", title="Synthetic legacy source", status="published", authors=[],
                abstract="Synthetic source only."))
            db.add(Chunk(id=identifier + "_chunk", paper_id=identifier, title="Synthetic legacy source", section="Results",
                text="A synthetic passage about pairing. It is not scientifically approved."))
            await db.commit()
    async def lexical(*_args, **_kwargs):
        return [retrieval.LexicalHit(identifier + "_chunk", 1.0)] if with_source else []
    async def no_formula(*_args, **_kwargs):
        return []
    def excerpts(_question, sources, **kwargs):
        return rag.extractive_fallback(sources, evidence_packing=kwargs["evidence_packing"])
    monkeypatch.setattr(retrieval, "lexical_search", lexical)
    monkeypatch.setattr(retrieval, "formula_lexical_search", no_formula)
    monkeypatch.setattr(rag, "generate_answer", excerpts)
    # A mechanism query intentionally excludes legacy-unknown passages. This
    # tests the ordinary lexical path, not that original-evidence gate.
    response = await client.post("/v1/ask", headers=headers(registered_user), json={"question": "Summarize synthetic observations"})
    assert response.status_code == 200, response.text
    assert response.json()["history"]["status"] == "saved", response.text
    async def no_active(*_args, **_kwargs):
        raise AssertionError("Historical reading must not load the active pointer")
    monkeypatch.setattr(index_retrieval, "load_pin", no_active)
    detail = await client.get("/v1/history/" + response.json()["history"]["history_id"], headers=headers(registered_user))
    assert detail.status_code == 200, detail.text
    evidence = detail.json()["evidence"]
    assert evidence["status"] == "verified"
    assert evidence["binding_scope"] == ("legacy_snapshot" if with_source else "no_selected_evidence")
    assert evidence["receipt"]["bindings"]["generation_id"] is None
    assert bool(evidence["receipt"]["response"]["sources"]) is with_source


async def test_browser_cookie_save_and_detail_require_no_local_storage_token(client, registered_user):
    from config import get_settings
    from routers.auth import _browser_session_config, allowed_browser_origins
    client.cookies.set(_browser_session_config().cookie_name, registered_user[1])
    origin = sorted(allowed_browser_origins(get_settings()))[0]
    response = await client.post("/v1/ask", headers={"Origin": origin}, json={"question": CLARIFY})
    assert response.status_code == 200, response.text
    assert response.json()["history"]["status"] == "saved", response.text
    detail = await client.get("/v1/history/" + response.json()["history"]["history_id"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["evidence"]["status"] == "verified"


async def test_failed_receipt_verification_is_explicit_and_returns_no_unchecked_receipt(client, registered_user, monkeypatch):
    body = await saved_clarification(client, registered_user)
    async def reject(*_args):
        raise ValueError("PRIVATE_RECEIPT_FAILURE")
    monkeypatch.setattr(ask_router.answer_evidence, "verify_historical", reject)
    response = await client.get("/v1/history/" + body["history"]["history_id"], headers=headers(registered_user))
    assert response.status_code == 200, response.text
    evidence = response.json()["evidence"]
    assert evidence["status"] == "unavailable" and evidence["receipt"] is None
    assert evidence["historical_integrity_verified"] is False
    assert "PRIVATE_RECEIPT_FAILURE" not in response.text
    assert await count_history(registered_user[0].id) == 1


@pytest.mark.parametrize("failure", ["capture", "storage", "capacity", "revoked"])
async def test_failed_save_keeps_final_answer_without_false_success(client, registered_user, monkeypatch, failure):
    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_DATABASE_DETAIL")
    if failure == "capture":
        monkeypatch.setattr(ask_router, "_capture_inputs", lambda *_args, **_kwargs: None)
    elif failure == "storage":
        monkeypatch.setattr(ask_router.answer_evidence, "receipt_fields", unavailable)
    elif failure == "capacity":
        monkeypatch.setattr(ask_router, "_HISTORY_SLOTS", threading.BoundedSemaphore(0))
    else:
        original = ask_router._history_actor
        async def revoke(request, session, user_id):
            async with get_session_factory()() as db:
                await db.execute(sa.update(User).where(User.id == user_id).values(session_version=1))
                await db.commit()
            return await original(request, session, user_id)
        monkeypatch.setattr(ask_router, "_history_actor", revoke)
    response = await client.post("/v1/ask", headers=headers(registered_user), json={"question": CLARIFY})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scientific_lookup"]["status"] == "clarification_required"
    assert body["history"]["status"] == "not_saved" and body["history"]["history_id"] is None
    expected = {"capture": "capture_unavailable", "storage": "storage_unavailable", "capacity": "storage_unavailable",
        "revoked": "session_no_longer_authorized"}[failure]
    assert body["history"]["reason_code"] == expected
    assert "PRIVATE_DATABASE_DETAIL" not in response.text
    assert await count_history(registered_user[0].id) == 0


@pytest.mark.parametrize("committed", [False, True])
async def test_unconfirmed_commit_returns_original_recovery_id_without_retry(client, registered_user, monkeypatch, committed):
    original = ask_router.AsyncSession.commit
    commits = []
    async def lost_ack(session):
        if session.bind.get_execution_options().get("isolation_level") == "SERIALIZABLE":
            commits.append(True)
            if committed:
                await original(session)
            raise RuntimeError("PRIVATE_COMMIT_ACK")
        return await original(session)
    monkeypatch.setattr(ask_router.AsyncSession, "commit", lost_ack)
    response = await client.post("/v1/ask", headers=headers(registered_user), json={"question": CLARIFY})
    assert response.status_code == 200, response.text
    disposition = response.json()["history"]
    assert disposition["status"] == "unknown" and disposition["reason_code"] == "commit_unconfirmed"
    assert disposition["receipt_sha256"] is None and disposition["history_id"]
    assert commits == [True] and "PRIVATE_COMMIT_ACK" not in response.text
    assert await count_history(registered_user[0].id) == int(committed)
    recovered = await client.get("/v1/history/" + disposition["history_id"], headers=headers(registered_user))
    assert recovered.status_code == (200 if committed else 404)
    if committed:
        assert recovered.json()["evidence"]["status"] == "verified"


async def test_cancelled_save_releases_capacity_and_leaves_no_partial_history(client, registered_user, monkeypatch):
    entered = asyncio.Event()
    async def pause(*_args):
        entered.set()
        await asyncio.Event().wait()
    semaphore = threading.BoundedSemaphore(1)
    monkeypatch.setattr(ask_router, "_HISTORY_SLOTS", semaphore)
    monkeypatch.setattr(ask_router.answer_evidence, "receipt_fields", pause)
    task = asyncio.create_task(client.post("/v1/ask", headers=headers(registered_user), json={"question": CLARIFY}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert semaphore.acquire(blocking=False)
    semaphore.release()
    assert await count_history(registered_user[0].id) == 0


@pytest.mark.parametrize("operation", ["owner_delete", "account_delete", "retention"])
async def test_receipt_follows_parent_privacy_and_retention(client, registered_user, operation):
    body = await saved_clarification(client, registered_user)
    identifier = UUID(body["history"]["history_id"])
    if operation == "owner_delete":
        result = await client.delete(f"/v1/history/{identifier}", headers=headers(registered_user))
        assert result.status_code == 200, result.text
    elif operation == "account_delete":
        result = await client.request("DELETE", "/v1/auth/me", headers=headers(registered_user), json={
            "confirmation": "DELETE", "email": registered_user[0].email, "current_password": "correcthorsebatterystaple"})
        assert result.status_code == 200, result.text
    else:
        # Exercise the same parent bulk-delete used by the 90-day job, with
        # a future cutoff; do not rewrite immutable creation timestamps.
        async with get_session_factory()() as db:
            await db.execute(sa.delete(AskHistory).where(AskHistory.user_id == registered_user[0].id,
                AskHistory.created_at < datetime.now(timezone.utc) + timedelta(days=1)))
            await db.commit()
    async with get_session_factory()() as db:
        assert await db.get(AskHistory, identifier) is None
        assert await db.scalar(sa.select(TABLE.c.history_id).where(TABLE.c.history_id == identifier)) is None


async def test_current_numeric_metadata_is_separate_from_unchanged_saved_receipt(client, registered_user, mixed_generation):
    response = await client.post("/v1/ask", headers=headers(registered_user),
        json={"question": "What is the Tc of MgB2 at ambient pressure?", "max_sources": 3})
    assert response.json()["history"]["status"] == "saved", response.text
    path = "/v1/history/" + response.json()["history"]["history_id"]
    before = (await client.get(path, headers=headers(registered_user))).json()
    async with get_session_factory()() as db:
        await db.execute(sa.update(Paper).where(Paper.id == mixed_generation["meta"].paper_id).values(status="retracted"))
        await db.commit()
    after_response = await client.get(path, headers=headers(registered_user))
    assert after_response.status_code == 200, after_response.text
    after = after_response.json()
    assert before["evidence"]["status"] == after["evidence"]["status"] == "verified"
    assert before["evidence"]["receipt"] == after["evidence"]["receipt"]
    assert after["entry"]["sources"] == []
    assert before["result_current_evidence"] != after["result_current_evidence"]
    assert "retracted" in json.dumps(after["result_current_evidence"])
    assert after["evidence"]["currentness_revalidated"] is False


async def test_export_explicitly_links_separate_owner_receipt_download(client, registered_user):
    body = await saved_clarification(client, registered_user)
    response = await client.get("/v1/auth/me/export", headers=headers(registered_user))
    assert response.status_code == 200, response.text
    document = response.json()
    entry, = document["ask_history"]
    assert entry["evidence_receipt_version"] == "ask-answer-evidence/1.0.0"
    assert entry["evidence_detail_path"] == "/v1/history/" + body["history"]["history_id"]
    assert document["answer_evidence_access"]["inline_receipts_included"] is False
    assert (await client.get(entry["evidence_detail_path"], headers=headers(registered_user))).json()["evidence"]["status"] == "verified"


@pytest.mark.parametrize("which", ["list", "detail"])
async def test_oversized_private_text_is_rejected_before_hydration(client, registered_user, monkeypatch, which):
    body = await saved_clarification(client, registered_user)
    from routers import history as history_router
    monkeypatch.setattr(history_router, "MAX_PAGE_BYTES" if which == "list" else "MAX_DETAIL_BYTES", 1)
    path = "/v1/history" if which == "list" else "/v1/history/" + body["history"]["history_id"]
    response = await client.get(path, headers=headers(registered_user))
    assert response.status_code == 503 and response.headers["Cache-Control"] == "private, no-store"
    assert CLARIFY not in response.text


def test_wire_dispositions_cannot_claim_success_without_confirmed_receipt():
    for value in [dict(status="saved"), dict(status="unknown", history_id=str(uuid4())),
                  dict(status="not_saved", reason_code="commit_unconfirmed"),
                  dict(status="not_requested", receipt_sha256="a" * 64)]:
        with pytest.raises(ValueError):
            HistorySaveDisposition(**value)
    with pytest.raises(ValueError):
        HistoryEvidenceDetail(status="legacy_unpinned", reason_codes=["legacy_receipt_not_recorded"], scientific_acceptance=0)
