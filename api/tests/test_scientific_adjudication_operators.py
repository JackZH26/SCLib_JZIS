"""Actual private HTTP decisions over synthetic retained native evidence only."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from config import get_settings
from models.db import Base
from routers import scientific_adjudication as router
from services import research_publication
from services import scientific_adjudication_contract as contract
from services.research_release_manifest import canonical
from tests.test_research_freeze import add
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_scientific_adjudication import request_for
from tests.test_scientific_review_operators import (
    PRIVATE_CANARY,
    auth,
    pending_result,
    private,
    snapshot,
)

db_session = _serializable_db_session
pytestmark = pytest.mark.asyncio
BASE = "/v1/ml/scientific-review/adjudication"
POSTS = ("/context", "/preview", "/commit")


async def context_for(client, db, role="reviewer"):
    fixture = await pending_result(db)
    response = await client.post(BASE + "/context", json={"property_ids": [fixture["property_id"]]},
                                 headers=auth(fixture["actors"][role]))
    assert response.status_code == 200, response.text
    return fixture, response.json(), auth(fixture["actors"][role])


async def preview_for(client, request, headers):
    response = await client.post(BASE + "/preview", json=request, headers=headers)
    assert response.status_code == 200, response.text
    private(response)
    return response.json()


@pytest.mark.parametrize("path", POSTS + ("/requests/synthetic-request",))
async def test_authentication_and_feature_gate_precede_action(client, monkeypatch, path):
    method = client.get if path.startswith("/requests/") else client.post
    response = await method(BASE + path)
    assert response.status_code == 401
    private(response)
    monkeypatch.setattr(get_settings(), "ml_foundation_public_enabled", False)
    response = await method(BASE + path)
    assert response.status_code == 404
    private(response)


@pytest.mark.parametrize("role", ["curator", "publisher", "member", "admin"])
async def test_only_explicit_current_reviewer_can_rehearse_or_commit(client, db_session, role):
    fixture, context, _ = await context_for(client, db_session)
    request = request_for(context)
    headers = auth(fixture["actors"][role])
    before = await snapshot(db_session)
    for path, body in (("/preview", request), ("/commit", {"request": request, "expected_preview_sha256": "0" * 64})):
        response = await client.post(BASE + path, json=body, headers=headers)
        assert response.status_code == 403, response.text
        private(response)
    assert await snapshot(db_session) == before
    response = await client.post(BASE + "/context", json={"property_ids": [fixture["property_id"]]}, headers=headers)
    assert response.status_code == (200 if role == "curator" else 403)
    if role == "curator":
        assert response.json()["can_review"] is False and response.json()["actor_grant_id"] is None


async def test_real_http_preview_commit_receipt_and_exact_context_are_private(client, db_session, tmp_path):
    fixture, context, headers = await context_for(client, db_session)
    target = context["targets"][0]
    assert target["dossier"]["target"]["property_id"] == fixture["property_id"]
    assert target["dossier"]["target"]["event_revision"] == target["event_revision"]
    assert target["dossier"]["impact"] == target["impact"]
    assert target["status"]["subject_sha256"] == target["subject_sha256"]
    before = await snapshot(db_session)
    request = request_for(context)
    request["items"][0]["rationale"] = "Synthetic private reviewer rationale: not a real scientific assessment."
    preview = await preview_for(client, request, headers)
    assert await snapshot(db_session) == before
    assert preview["database_mutated"] is False
    response = await client.post(BASE + "/commit", headers=headers,
        json={"request": request, "expected_preview_sha256": preview["preview_sha256"]})
    assert response.status_code == 200, response.text
    private(response)
    receipt = response.json()
    assert receipt["committed"] is True and receipt["replayed"] is False
    after = await snapshot(db_session)
    assert len(after["scientific_result_decisions"]) == len(before["scientific_result_decisions"]) + 1
    recovered = await client.get(BASE + "/requests/" + request["request_key"], headers=headers)
    assert recovered.status_code == 200, recovered.text
    private(recovered)
    assert recovered.json() == {**receipt, "replayed": True}
    replay = await client.post(BASE + "/commit", headers=headers,
        json={"request": request, "expected_preview_sha256": preview["preview_sha256"]})
    assert replay.status_code == 200 and replay.json() == recovered.json()
    assert await snapshot(db_session) == after
    for payload in (context, preview, receipt):
        text = json.dumps(payload)
        assert PRIVATE_CANARY not in text
        assert "Synthetic private reviewer rationale" not in text
        for forbidden in ('"source_url"', '"source_raw_text"', '"password_hash"', '"payload"'):
            assert forbidden not in text
    # Entirely synthetic actual HTTP wire capture, no tokens, source bytes, or
    # real human scientific decisions. Test output is retained for frontend QA.
    capture = {"context": context, "request": request, "preview": preview, "receipt": receipt}
    output = tmp_path / "scientific-adjudication-http.json"
    output.write_text(json.dumps(capture, indent=2) + "\n")
    print("Synthetic scientific adjudication HTTP fixture:", output)


async def test_revoked_authority_is_checked_again_at_commit(client, db_session):
    fixture, context, headers = await context_for(client, db_session)
    request = request_for(context)
    preview = await preview_for(client, request, headers)
    await research_publication.revoke_role(db_session, actor_user_id=fixture["actors"]["admin"],
        grant_id=fixture["actors"]["grants"]["reviewer"], reason_code="synthetic_adjudication_access_withdrawn", dry_run=False)
    await db_session.commit()
    before = await snapshot(db_session)
    response = await client.post(BASE + "/commit", headers=headers,
        json={"request": request, "expected_preview_sha256": preview["preview_sha256"]})
    assert response.status_code == 403, response.text
    private(response)
    assert await snapshot(db_session) == before


async def test_source_edit_after_preview_refuses_every_decision(client, db_session):
    fixture, context, headers = await context_for(client, db_session)
    request = request_for(context)
    preview = await preview_for(client, request, headers)
    await db_session.execute(sa.text("UPDATE materials SET formula='AlAs2' WHERE id=:id"), {"id": fixture["material"]})
    await db_session.commit()
    before = await snapshot(db_session)
    response = await client.post(BASE + "/commit", headers=headers,
        json={"request": request, "expected_preview_sha256": preview["preview_sha256"]})
    assert response.status_code == 409, response.text
    private(response)
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("lost_after_commit", [False, True])
async def test_outer_commit_failure_never_emits_success_and_unknown_is_read_only_recoverable(
    client, db_session, monkeypatch, lost_after_commit
):
    _, context, headers = await context_for(client, db_session)
    request = request_for(context)
    preview = await preview_for(client, request, headers)
    before = await snapshot(db_session)
    original = router._session

    @asynccontextmanager
    async def failing_session(http_request, *, write=False):
        async with original(http_request, write=write) as session:
            yield session
            if not lost_after_commit:
                raise SQLAlchemyError("PRIVATE_COMMIT_FAILURE " + PRIVATE_CANARY)
        if lost_after_commit:
            raise SQLAlchemyError("PRIVATE_RESPONSE_LOST " + PRIVATE_CANARY)

    monkeypatch.setattr(router, "_session", failing_session)
    response = await client.post(BASE + "/commit", headers=headers,
        json={"request": request, "expected_preview_sha256": preview["preview_sha256"]})
    assert response.status_code == 503, response.text
    assert "committed" not in response.text and PRIVATE_CANARY not in response.text
    private(response)
    monkeypatch.setattr(router, "_session", original)
    recovered = await client.get(BASE + "/requests/" + request["request_key"], headers=headers)
    assert recovered.status_code == (200 if lost_after_commit else 404), recovered.text
    after = await snapshot(db_session)
    if lost_after_commit:
        assert recovered.json()["committed"] is True and recovered.json()["replayed"] is True
        assert len(after["scientific_result_decisions"]) == len(before["scientific_result_decisions"]) + 1
    else:
        assert after == before
    assert await snapshot(db_session) == after  # Recovery performs no write.


@pytest.mark.parametrize("raw,status,content_type", [
    ('{"property_ids":[],"property_ids":[]}', 400, "application/json"),
    ('{"property_ids":[NaN]}', 400, "application/json"),
    ('{"property_ids":[1e999]}', 400, "application/json"),
    ('{"property_ids":[],"actor_user_id":"forged"}', 400, "application/json"),
    ('{"property_ids":[]}', 400, "application/json"),
    (' ' * (contract.MAX_BYTES + 1), 413, "application/json"),
    ('{}', 415, "text/plain"),
], ids=[
    "duplicate-property-ids", "nan", "infinite-number", "forged-actor",
    "empty-property-ids", "oversized-body", "unsupported-content-type",
])
async def test_closed_bounded_json_has_no_side_effects(client, db_session, raw, status, content_type):
    _, _, headers = await context_for(client, db_session)
    before = await snapshot(db_session)
    response = await client.post(BASE + "/context", content=raw,
        headers={**headers, "Content-Type": content_type})
    assert response.status_code == status, response.text
    private(response)
    assert await snapshot(db_session) == before


async def test_actor_scoped_request_lookup_does_not_disclose_another_reviewers_receipt(client, db_session):
    first, context, headers = await context_for(client, db_session)
    second, _, other_headers = await context_for(client, db_session)
    assert first["actors"]["reviewer"] != second["actors"]["reviewer"]
    request = request_for(context)
    preview = await preview_for(client, request, headers)
    response = await client.post(BASE + "/commit", headers=headers,
        json={"request": request, "expected_preview_sha256": preview["preview_sha256"]})
    assert response.status_code == 200, response.text
    before = await snapshot(db_session)
    missing = await client.get(BASE + "/requests/" + request["request_key"], headers=other_headers)
    assert missing.status_code == 404
    private(missing)
    assert await snapshot(db_session) == before


async def test_explicit_two_target_batch_is_atomic_and_preserves_order(client, db_session):
    first, _, headers = await context_for(client, db_session)
    second = await pending_result(db_session)
    response = await client.post(BASE + "/context", headers=headers,
        json={"property_ids": [second["property_id"], first["property_id"]]})
    assert response.status_code == 200, response.text
    context = response.json()
    request = request_for(context, decision="request_clarification")
    preview = await preview_for(client, request, headers)
    before = await snapshot(db_session)
    invalid = deepcopy(request)
    invalid["items"][1]["expected_previous_decision_id"] = str(uuid4())
    bad = await client.post(BASE + "/preview", headers=headers, json=invalid)
    assert bad.status_code == 409, bad.text
    assert await snapshot(db_session) == before
    response = await client.post(BASE + "/commit", headers=headers,
        json={"request": request, "expected_preview_sha256": preview["preview_sha256"]})
    assert response.status_code == 200, response.text
    assert [item["property_id"] for item in response.json()["items"]] == [second["property_id"], first["property_id"]]
    assert len((await snapshot(db_session))["scientific_result_decisions"]) == len(before["scientific_result_decisions"]) + 2


async def test_status_backend_failure_is_unavailable_not_invalid_request(client, db_session, monkeypatch):
    from services import scientific_result_effects as effects
    fixture, _, headers = await context_for(client, db_session)
    before = await snapshot(db_session)

    async def unavailable(*args, **kwargs):
        raise effects.ScientificResultStatusUnavailable(PRIVATE_CANARY)

    monkeypatch.setattr(effects, "resolve_result_status", unavailable)
    response = await client.post(BASE + "/context", headers=headers, json={"property_ids": [fixture["property_id"]]})
    assert response.status_code == 503, response.text
    assert PRIVATE_CANARY not in response.text
    private(response)
    assert await snapshot(db_session) == before


async def test_audited_reviewer_identity_survives_revocation_and_account_deletion_attempt(client, db_session):
    from services.research_audit_retention import RETENTION_MESSAGE
    fixture, context, headers = await context_for(client, db_session)
    request = request_for(context, decision="reject")
    preview = await preview_for(client, request, headers)
    response = await client.post(BASE + "/commit", headers=headers,
        json={"request": request, "expected_preview_sha256": preview["preview_sha256"]})
    assert response.status_code == 200, response.text
    await research_publication.revoke_role(db_session, actor_user_id=fixture["actors"]["admin"],
        grant_id=fixture["actors"]["grants"]["reviewer"], reason_code="synthetic_audit_retention_check", dry_run=False)
    await db_session.commit()
    before = await snapshot(db_session)
    response = await client.delete("/v1/admin/users/" + str(fixture["actors"]["reviewer"]),
                                   headers=auth(fixture["actors"]["admin"]))
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == RETENTION_MESSAGE
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("role,path", [("member", path) for path in POSTS] +
                         [("curator", "/preview"), ("curator", "/commit")])
async def test_unprivileged_stream_is_rejected_before_body_consumption(client, db_session, role, path):
    fixture, _, _ = await context_for(client, db_session)
    consumed = False

    async def body():
        nonlocal consumed
        consumed = True
        yield b'{"items":[]}'

    before = await snapshot(db_session)
    response = await client.post(BASE + path, content=body(),
        headers={**auth(fixture["actors"][role]), "Content-Type": "application/json"})
    assert response.status_code == 403, response.text
    assert consumed is False
    private(response)
    assert await snapshot(db_session) == before


async def test_maximum_inner_request_previews_and_commits_with_bounded_envelope(client, db_session):
    """Twenty synthetic component rows, not twenty independent scientific sources."""
    fixture, _, headers = await context_for(client, db_session)
    table = Base.metadata.tables["event_properties"]
    original = dict((await db_session.execute(sa.select(table).where(
        table.c.id == sa.cast(fixture["property_id"], sa.Uuid())))).mappings().one())
    fields = {key: value for key, value in original.items() if key not in {"id", "created_at"}}
    ids = [uuid4() for _ in range(20)]
    for index, identifier in enumerate(ids):
        await add(db_session, "event_properties", **{**fields, "id": identifier,
            "component_key": f"synthetic-request-boundary-{index}", "record_sha256": "a" * 64})
    await db_session.commit()
    context = await client.post(BASE + "/context", headers=headers, json={"property_ids": list(map(str, ids))})
    assert context.status_code == 200, context.text
    request = request_for(context.json(), decision="request_clarification")
    remaining = contract.MAX_BYTES - len(canonical(request))
    for item in request["items"]:
        count = min(2000 - len(item["rationale"]), remaining // 3)
        item["rationale"] += "测" * count
        remaining -= 3 * count
        if remaining <= 2:
            count = min(2000 - len(item["rationale"]), remaining)
            item["rationale"] += "x" * count
            remaining -= count
    assert remaining == 0 and len(canonical(request)) == contract.MAX_BYTES
    preview_response = await client.post(BASE + "/preview", content=canonical(request),
        headers={**headers, "Content-Type": "application/json"})
    assert preview_response.status_code == 200, preview_response.text
    envelope = {"request": request, "expected_preview_sha256": preview_response.json()["preview_sha256"]}
    raw = canonical(envelope)
    assert contract.MAX_BYTES < len(raw) <= contract.MAX_COMMIT_BYTES
    before = await snapshot(db_session)
    invalid = deepcopy(envelope)
    invalid["request"]["items"][-1]["rationale"] += "x"
    assert len(canonical(invalid)) <= contract.MAX_COMMIT_BYTES
    rejected = await client.post(BASE + "/commit", content=canonical(invalid),
        headers={**headers, "Content-Type": "application/json"})
    assert rejected.status_code == 400, rejected.text  # Inner limit still applies.
    assert await snapshot(db_session) == before
    response = await client.post(BASE + "/commit", content=raw,
        headers={**headers, "Content-Type": "application/json"})
    assert response.status_code == 200, response.text
    assert response.json()["committed"] is True and len(response.json()["items"]) == 20
    assert len((await snapshot(db_session))["scientific_result_decisions"]) == len(before["scientific_result_decisions"]) + 20
