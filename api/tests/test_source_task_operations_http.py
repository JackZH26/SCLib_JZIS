"""Actual private HTTP/SQL workflow; synthetic source data, no background work."""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from config import get_settings
from models.db import Base
from routers import source_task_operations as router
from services import auth_service, research_publication, source_task_operations, source_tasks
from services.research_release_manifest import digest
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_freeze import state
from tests.test_research_publication import actors
from tests.test_source_tasks import prepared

db_session = _serializable_db_session
pytestmark = pytest.mark.asyncio
BASE = "/v1/ml/source-lifecycle/task-operations"
FALSE_FIELDS = (
    "timeline_rebuilt", "propagation_complete", "scientific_acceptance",
    "ml_training_approved", "source_reinstatement", "external_cache_invalidated",
)


def auth(user_id):
    token, _ = auth_service.create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    for field in ("etag", "last-modified", "location"):
        assert field not in response.headers


def safe_receipt(value):
    assert value["committed"] is True and value["requires_outer_commit"] is False
    for field in FALSE_FIELDS:
        assert value["receipt_semantics"][field] is False
    assert value["receipt_semantics"]["currentness"] == "historical_receipt_not_live_projection_state"
    serialized = json.dumps(value)
    for secret in ("inventory_json", "UNEXPOSED", "@example.test", "tc_kelvin", "private_note"):
        assert secret not in serialized


def safe_error(response, status):
    value = response.json()
    assert response.status_code == status
    assert set(value) == {"detail", "error_code", "request_id"}
    assert value["detail"] == router.MESSAGES[status]
    assert value["error_code"] == {400: "bad_request", 409: "conflict", 503: "service_unavailable"}[status]
    assert re.fullmatch(r"[0-9a-f]{32}", value["request_id"])


async def snapshot(db):
    result = await state(db)
    await db.rollback()
    return result


async def fixture(db, **kwargs):
    result = await prepared(db, **kwargs)
    await db.commit()
    result["headers"] = auth(result["actors"]["curator"])
    result["operation"] = {
        "version": "source-task-operation/1.0.0", "operation": "enqueue",
        **{key: str(value) for key, value in result["args"].items() if key != "actor_user_id"},
    }
    return result


def execution(receipt, *, key="synthetic-http-execution", predecessor=None):
    return {
        "version": "source-task-operation/1.0.0", "operation": "execute",
        "request_id": receipt["request"]["id"],
        "expected_request_sha256": receipt["request"]["record_sha256"],
        "execution_key": key,
        "expected_predecessor_id": predecessor["id"] if predecessor else None,
        "expected_predecessor_sha256": predecessor["record_sha256"] if predecessor else None,
    }


async def preview(client, operation, headers):
    response = await client.post(BASE + "/preview", json=operation, headers=headers)
    assert response.status_code == 200, response.text
    private(response)
    value = response.json()
    assert value["database_mutated"] is False and value["can_commit"] is True
    assert value["operation_sha256"] == digest(operation)
    for field in FALSE_FIELDS:
        assert value["receipt_semantics"][field] is False
    return value


async def commit(client, operation, headers, observed=None):
    observed = observed or await preview(client, operation, headers)
    response = await client.post(BASE + "/commit", headers=headers, json={
        "request": operation, "expected_preview_sha256": observed["preview_sha256"],
    })
    assert response.status_code == 200, response.text
    private(response)
    safe_receipt(response.json())
    return response.json()


async def test_actual_workflow_preview_replay_read_and_existing_singleton_effects(client, db_session, tmp_path):
    context = await fixture(db_session)
    headers, operation = context["headers"], context["operation"]
    before = await snapshot(db_session)
    history = await client.get("/v1/ml/source-lifecycle", params={"paper_id": context["source"]}, headers=headers)
    impact = await client.get(f"/v1/ml/source-lifecycle/{operation['event_id']}/impact",
        params={"expected_event_sha256": operation["expected_event_sha256"]}, headers=headers)
    for response in (history, impact):
        assert response.status_code == 200, response.text
        private(response)
    capabilities = await client.get(BASE + "/capabilities", headers=headers)
    assert capabilities.status_code == 200, capabilities.text
    private(capabilities)
    assert capabilities.json()["can_read"] is capabilities.json()["can_write"] is True
    for field in FALSE_FIELDS:
        assert capabilities.json()[field] is False
    enqueue_preview = await preview(client, operation, headers)
    assert enqueue_preview["predicted_status"] == "queued"
    assert await snapshot(db_session) == before
    enqueue = await commit(client, operation, headers, enqueue_preview)
    assert enqueue["replayed"] is False and enqueue["attempt"] is None
    after_enqueue = await snapshot(db_session)
    allowed = {"source_task_requests", "source_task_epoch", "research_integrity_epoch",
               "research_publication_epoch", "source_lifecycle_epoch"}
    assert {name for name in before if before[name] != after_enqueue[name]} <= allowed
    assert len(after_enqueue["source_task_requests"]) == len(before["source_task_requests"]) + 1
    replay = await commit(client, operation, headers, enqueue_preview)
    assert replay["replayed"] is True and replay["request"] == enqueue["request"]
    read = await client.get(BASE + "/requests/" + operation["request_key"], headers=headers)
    assert read.status_code == 200 and read.json() == replay
    private(read)
    assert await snapshot(db_session) == after_enqueue
    queued_history = await client.get("/v1/ml/source-lifecycle/tasks/" + enqueue["request"]["id"], headers=headers)
    assert queued_history.status_code == 200 and queued_history.json()["attempts"] == []
    execute = execution(enqueue)
    execute_preview = await preview(client, execute, headers)
    assert execute_preview["predicted_status"] == "succeeded"
    assert await snapshot(db_session) == after_enqueue
    result = await commit(client, execute, headers, execute_preview)
    assert result["attempt"]["status"] == "succeeded" and result["executed_now"] is True
    after_execute = await snapshot(db_session)
    allowed = {"source_task_attempts", "timeline_projection_state", "source_task_epoch",
               "research_integrity_epoch", "research_publication_epoch", "source_lifecycle_epoch"}
    assert {name for name in after_enqueue if after_enqueue[name] != after_execute[name]} <= allowed
    old_state = after_enqueue["timeline_projection_state"]
    assert after_execute["timeline_projection_state"] == [{**item, "schema_version": 0} for item in old_state]
    replay = await commit(client, execute, headers, execute_preview)
    assert replay["attempt"] == result["attempt"] and replay["executed_now"] is False
    exact = await client.get(f"{BASE}/requests/{execute['request_id']}/executions/{execute['execution_key']}", headers=headers)
    assert exact.status_code == 200 and exact.json() == replay
    private(exact)
    assert await snapshot(db_session) == after_execute
    task_history = await client.get("/v1/ml/source-lifecycle/tasks/" + enqueue["request"]["id"], headers=headers)
    assert task_history.status_code == 200 and task_history.json()["attempts"] == [result["attempt"]]
    # This file contains only synthetic, actual HTTP responses for frontend parity.
    capture = tmp_path / "source-task-operations-http.json"
    data = {"capabilities": capabilities.json(), "source_history": history.json(), "source_impact": impact.json(),
        "source_id": context["source"], "enqueue_request": operation,
        "enqueue_preview": enqueue_preview, "enqueue_receipt": enqueue,
        "recovered_enqueue": read.json(), "queued_task_history": queued_history.json(),
        "execution_request": execute, "execution_preview": execute_preview,
        "execution_receipt": result, "recovered_execution": exact.json(), "task_history": task_history.json()}
    raw = json.dumps(data, sort_keys=True, indent=2) + "\n"
    capture.write_text(raw, encoding="utf-8")
    print(f"SYNTHETIC_HTTP_CAPTURE={capture.resolve()}")
    exported = os.environ.get("SOURCE_TASK_OPERATIONS_HTTP_CAPTURE")
    if exported:
        target = Path(exported)
        assert target.is_absolute() and target.parent.is_dir()
        # Opt-in capture is synthetic only, exclusive, and never overwrites a fixture.
        with target.open("x", encoding="utf-8") as stream:
            stream.write(raw)
        print(f"SYNTHETIC_HTTP_EXPORT={target.resolve()}")


async def test_success_replay_never_invalidates_a_subsequently_rebuilt_timeline(client, db_session):
    context = await fixture(db_session)
    queued = await commit(client, context["operation"], context["headers"])
    request = execution(queued)
    first = await commit(client, request, context["headers"])
    await db_session.execute(sa.text("UPDATE timeline_projection_state SET schema_version=6 WHERE id=1"))
    await db_session.commit()
    before = await snapshot(db_session)
    replay = await commit(client, request, context["headers"])
    assert replay["attempt"] == first["attempt"] and replay["executed_now"] is False
    assert await snapshot(db_session) == before


async def test_missing_timeline_singleton_is_not_created(client, db_session):
    context = await fixture(db_session, with_state=False)
    queued = await commit(client, context["operation"], context["headers"])
    result = await commit(client, execution(queued), context["headers"])
    assert result["attempt"]["status"] == "succeeded"
    assert not (await snapshot(db_session))["timeline_projection_state"]


@pytest.mark.parametrize("role", [None, "admin", "member", "reviewer", "publisher"])
async def test_authority_before_body_and_no_legacy_flags(client, db_session, monkeypatch, role):
    people = await actors(db_session)
    await db_session.commit()
    before = await snapshot(db_session)

    async def forbidden(*args, **kwargs):
        pytest.fail("Unauthorized actor reached request body")

    monkeypatch.setattr(router, "_body", forbidden)
    headers = auth(people[role]) if role else {}
    expected = 401 if role is None else 403
    for suffix in ("/preview", "/commit"):
        response = await client.post(BASE + suffix, content=b"SECRET invalid body", headers=headers)
        assert response.status_code == expected, response.text
        private(response)
    for suffix in ("/capabilities", "/requests/unknown", f"/requests/{uuid4()}/executions/unknown"):
        response = await client.get(BASE + suffix, headers=headers)
        assert response.status_code == expected, response.text
        private(response)
    assert await snapshot(db_session) == before


async def test_feature_gate_hides_every_path_before_auth_or_body(client, monkeypatch):
    monkeypatch.setenv("ML_FOUNDATION_PUBLIC_ENABLED", "false")
    get_settings.cache_clear()
    try:
        for suffix in ("/preview", "/commit"):
            response = await client.post(BASE + suffix, content=b"SECRET")
            assert response.status_code == 404
            private(response)
        for suffix in ("/capabilities", "/requests/a", f"/requests/{uuid4()}/executions/a"):
            response = await client.get(BASE + suffix)
            assert response.status_code == 404
            private(response)
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("payload", [b'[]', b'{"secret":NaN}', b'{"secret":1e999}',
    b'{"secret":1}', b'{"secret":"\\ud800"}', b'{"secret":"\xff"}',
    b'{"secret":', b'{"secret":true,"secret":false}', b'[' * 17 + b']' * 17])
async def test_strict_json_rejects_without_echo_or_mutation(client, db_session, payload):
    people = await actors(db_session)
    await db_session.commit()
    before = await snapshot(db_session)
    response = await client.post(BASE + "/preview", content=payload,
        headers={**auth(people["curator"]), "Content-Type": "application/json"})
    assert response.status_code == 400, response.text
    safe_error(response, 400)
    private(response)
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("mutation", ["actor", "grant", "failure", "hash", "version", "key", "missing", "bool"])
async def test_closed_request_rejects_spoofed_or_invalid_fields(client, db_session, mutation):
    context = await fixture(db_session)
    request = dict(context["operation"])
    if mutation in {"actor", "grant"}:
        request["actor_user_id" if mutation == "actor" else "actor_grant_id"] = str(uuid4())
    elif mutation == "failure":
        request["operation"] = "record_failure"
        request["outcome_code"] = "database_busy"
    elif mutation == "hash":
        request["expected_event_sha256"] = "A" * 64
    elif mutation == "version":
        request["version"] = "source-task-operation/9"
    elif mutation == "key":
        request["request_key"] = "secret/unsafe"
    elif mutation == "missing":
        request.pop("event_id")
    else:
        request["request_key"] = True
    before = await snapshot(db_session)
    response = await client.post(BASE + "/preview", json=request, headers=context["headers"])
    assert response.status_code == 400, response.text
    private(response)
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("transport", ["large", "declared", "stream", "content_type"])
async def test_body_transport_limits(client, db_session, transport):
    people = await actors(db_session)
    await db_session.commit()
    headers = {**auth(people["curator"]), "Content-Type": "application/json"}
    payload = b" " * 8193 if transport in {"large", "stream"} else b"{}"
    if transport == "declared":
        headers["Content-Length"] = "999999999999999999999999"
    if transport == "content_type":
        headers["Content-Type"] = "text/plain"
    if transport == "stream":
        streamed_bytes = payload
        async def chunks():
            yield streamed_bytes[:8000]
            yield streamed_bytes[8000:]
        payload = chunks()
    before = await snapshot(db_session)
    response = await client.post(BASE + "/preview", content=payload, headers=headers)
    assert response.status_code == (415 if transport == "content_type" else 413), response.text
    private(response)
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("change", ["preview", "event", "inventory", "reused_key"])
async def test_exact_conflicts_are_409_and_full_sql_noop(client, db_session, change):
    context = await fixture(db_session)
    operation = dict(context["operation"])
    observed = await preview(client, operation, context["headers"])
    if change == "reused_key":
        await commit(client, operation, context["headers"], observed)
        operation["expected_inventory_sha256"] = "f" * 64
    elif change == "event":
        operation["expected_event_sha256"] = "f" * 64
    elif change == "inventory":
        operation["expected_inventory_sha256"] = "f" * 64
    else:
        observed["preview_sha256"] = "f" * 64
    before = await snapshot(db_session)
    response = await client.post(BASE + "/commit", headers=context["headers"], json={
        "request": operation, "expected_preview_sha256": observed["preview_sha256"]})
    assert response.status_code == 409, response.text
    safe_error(response, 409)
    private(response)
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("change", ["revoke", "session", "inactive", "unverified"])
async def test_revoked_grant_or_session_cannot_replay_or_recover(client, db_session, change):
    context = await fixture(db_session)
    queued = await commit(client, context["operation"], context["headers"])
    await commit(client, execution(queued), context["headers"])
    people = context["actors"]
    if change == "revoke":
        await research_publication.revoke_role(db_session, actor_user_id=people["admin"],
            grant_id=people["grants"]["curator"], reason_code="synthetic_revocation", dry_run=False)
    else:
        values = {"session_version": 1} if change == "session" else {
            "is_active" if change == "inactive" else "email_verified": False}
        users = Base.metadata.tables["users"]
        await db_session.execute(users.update().where(users.c.id == people["curator"]).values(**values))
    await db_session.commit()
    before = await snapshot(db_session)
    expected = 401 if change in {"session", "inactive"} else 403
    response = await client.post(BASE + "/preview", json=context["operation"], headers=context["headers"])
    assert response.status_code == expected, response.text
    private(response)
    for path in (f"/requests/{context['operation']['request_key']}",
                 f"/requests/{queued['request']['id']}/executions/synthetic-http-execution"):
        response = await client.get(BASE + path, headers=context["headers"])
        assert response.status_code == expected, response.text
        private(response)
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("change", ["revoke", "session"])
@pytest.mark.parametrize("history", [None, "enqueue", "execute"])
async def test_actor_change_during_body_is_rejected_at_write_fence(client, db_session, monkeypatch, change, history):
    context = await fixture(db_session)
    operation = context["operation"]
    if history:
        queued = await commit(client, operation, context["headers"])
        if history == "execute":
            operation = execution(queued)
            await commit(client, operation, context["headers"])
    observed = await preview(client, operation, context["headers"])
    original = router._body
    after_change = None

    async def changed(request, **kwargs):
        nonlocal after_change
        value = await original(request, **kwargs)
        people = context["actors"]
        if change == "revoke":
            await research_publication.revoke_role(db_session, actor_user_id=people["admin"],
                grant_id=people["grants"]["curator"], reason_code="synthetic_during_upload", dry_run=False)
        else:
            users = Base.metadata.tables["users"]
            await db_session.execute(users.update().where(users.c.id == people["curator"]).values(session_version=1))
        await db_session.commit()
        after_change = await snapshot(db_session)
        return value

    monkeypatch.setattr(router, "_body", changed)
    response = await client.post(BASE + "/commit", json={"request": operation,
        "expected_preview_sha256": observed["preview_sha256"]}, headers=context["headers"])
    assert response.status_code == (401 if change == "session" else 403), response.text
    private(response)
    assert after_change is not None and await snapshot(db_session) == after_change


async def test_exact_execution_recovery_returns_named_old_attempt_not_latest(client, db_session):
    context = await fixture(db_session)
    queued = await commit(client, context["operation"], context["headers"])
    common = {"actor_user_id": context["actors"]["curator"],
        "request_id": queued["request"]["id"], "expected_request_sha256": queued["request"]["record_sha256"]}
    failed = await source_tasks.record_source_task_failure(db_session, **common, execution_key="first-failure",
        outcome_code="database_busy", dry_run=False)
    await db_session.commit()
    old_attempt = failed["attempt"]
    operation = execution(queued, key="second-success", predecessor=old_attempt)
    latest = await commit(client, operation, context["headers"])
    assert latest["attempt"]["status"] == "succeeded"
    before = await snapshot(db_session)
    response = await client.get(f"{BASE}/requests/{queued['request']['id']}/executions/first-failure", headers=context["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["attempt"] == old_attempt
    assert response.json()["attempt"] != latest["attempt"] and response.json()["executed_now"] is False
    safe_receipt(response.json())
    private(response)
    assert await snapshot(db_session) == before


async def test_second_curator_receipts_are_scoped_to_requester_and_exact_executor(client, db_session):
    context = await fixture(db_session)
    other = await actors(db_session)
    await db_session.commit()
    queued = await commit(client, context["operation"], context["headers"])
    operation = execution(queued)
    result = await commit(client, operation, auth(other["curator"]))
    assert result["actor_user_id"] == str(other["curator"])
    before = await snapshot(db_session)
    wrong_request = await client.get(f"{BASE}/requests/{context['operation']['request_key']}", headers=auth(other["curator"]))
    assert wrong_request.status_code == 404
    wrong_execution = await client.get(f"{BASE}/requests/{queued['request']['id']}/executions/{operation['execution_key']}", headers=context["headers"])
    assert wrong_execution.status_code == 404
    right = await client.get(f"{BASE}/requests/{queued['request']['id']}/executions/{operation['execution_key']}", headers=auth(other["curator"]))
    assert right.status_code == 200 and right.json()["attempt"] == result["attempt"]
    for response in (wrong_request, wrong_execution, right):
        private(response)
    assert await snapshot(db_session) == before


async def test_obsolete_inventory_is_stored_explicitly_without_timeline_invalidation(client, db_session):
    from tests.test_source_impact import material
    context = await fixture(db_session)
    queued = await commit(client, context["operation"], context["headers"])
    await material(db_session, source=context["source"])
    await db_session.commit()
    before = await snapshot(db_session)
    result = await commit(client, execution(queued), context["headers"])
    assert result["attempt"]["status"] == "obsolete"
    assert result["attempt"]["outcome_code"] == "inventory_changed"
    assert result["executed_now"] is False
    assert (await snapshot(db_session))["timeline_projection_state"] == before["timeline_projection_state"]


async def test_stale_attempt_head_cannot_execute_and_mutates_nothing(client, db_session):
    context = await fixture(db_session)
    queued = await commit(client, context["operation"], context["headers"])
    operation = execution(queued)
    observed = await preview(client, operation, context["headers"])
    await source_tasks.record_source_task_failure(db_session, actor_user_id=context["actors"]["curator"],
        request_id=queued["request"]["id"], expected_request_sha256=queued["request"]["record_sha256"],
        execution_key="intervening-failure", outcome_code="database_busy", dry_run=False)
    await db_session.commit()
    before = await snapshot(db_session)
    response = await client.post(BASE + "/commit", json={"request": operation,
        "expected_preview_sha256": observed["preview_sha256"]}, headers=context["headers"])
    assert response.status_code == 409, response.text
    private(response)
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("phase", ["enqueue", "execute"])
async def test_deferred_real_sql_commit_failure_never_returns_success(client, db_session, monkeypatch, phase):
    context = await fixture(db_session)
    operation = context["operation"]
    if phase == "execute":
        operation = execution(await commit(client, operation, context["headers"]))
    observed = await preview(client, operation, context["headers"])
    before = await snapshot(db_session)
    original = source_task_operations.commit_operation
    staged = []

    async def deferred_failure(db, **kwargs):
        value = await original(db, **kwargs)
        staged.append(value)
        await db.execute(sa.text("CREATE TEMP TABLE task_commit_probe (id integer PRIMARY KEY, "
            "parent_id integer REFERENCES task_commit_probe(id) DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP"))
        await db.execute(sa.text("INSERT INTO task_commit_probe VALUES (1,2)"))
        return value

    monkeypatch.setattr(source_task_operations, "commit_operation", deferred_failure)
    response = await client.post(BASE + "/commit", json={"request": operation,
        "expected_preview_sha256": observed["preview_sha256"]}, headers=context["headers"])
    assert response.status_code == 409 and len(staged) == 1, response.text
    safe_error(response, 409)
    private(response)
    assert await snapshot(db_session) == before


async def test_lost_commit_ack_is_unknown_and_original_key_recovers_committed_receipt(client, db_session, monkeypatch):
    context = await fixture(db_session)
    observed = await preview(client, context["operation"], context["headers"])
    original = router._session
    first = True

    @asynccontextmanager
    async def lost_ack(request, **kwargs):
        nonlocal first
        async with original(request, **kwargs) as value:
            yield value
        if request.url.path.endswith("/commit") and kwargs.get("write") is True and first:
            first = False
            raise SQLAlchemyError("SECRET transport lost acknowledgement after actual commit")

    monkeypatch.setattr(router, "_session", lost_ack)
    response = await client.post(BASE + "/commit", json={"request": context["operation"],
        "expected_preview_sha256": observed["preview_sha256"]}, headers=context["headers"])
    assert response.status_code == 503
    safe_error(response, 503)
    private(response)
    after = await snapshot(db_session)
    recovered = await client.get(f"{BASE}/requests/{context['operation']['request_key']}", headers=context["headers"])
    assert recovered.status_code == 200, recovered.text
    safe_receipt(recovered.json())
    replay = await commit(client, context["operation"], context["headers"], observed)
    assert replay == recovered.json() and replay["replayed"] is True
    assert await snapshot(db_session) == after


async def test_two_request_capacity_cancellation_and_rollback_release_slots(client, db_session, monkeypatch):
    context = await fixture(db_session)
    before = await snapshot(db_session)
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(router, "_slots", slots)
    original = router._body
    entered = []
    ready = asyncio.Event()
    release = asyncio.Event()

    async def paused(request, **kwargs):
        entered.append(request)
        if len(entered) == 2:
            ready.set()
        await release.wait()
        return await original(request, **kwargs)

    monkeypatch.setattr(router, "_body", paused)
    requests = [asyncio.create_task(client.post(BASE + "/preview", json=context["operation"],
        headers=context["headers"])) for _ in range(2)]
    try:
        await asyncio.wait_for(ready.wait(), 5)
        rejected = await client.get(BASE + "/capabilities", headers=context["headers"])
        assert rejected.status_code == 503 and len(entered) == 2
        private(rejected)
        for request in requests:
            request.cancel()
        await asyncio.gather(*requests, return_exceptions=True)
    finally:
        release.set()
        await asyncio.gather(*requests, return_exceptions=True)
    monkeypatch.setattr(router, "_body", original)
    healthy = await client.get(BASE + "/capabilities", headers=context["headers"])
    assert healthy.status_code == 200, healthy.text
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)
    slots.release()
    slots.release()
    assert await snapshot(db_session) == before


async def test_concurrent_identical_commits_produce_one_request_and_recoverable_conflict(client, db_session):
    context = await fixture(db_session)
    observed = await preview(client, context["operation"], context["headers"])
    before = await snapshot(db_session)
    body = {"request": context["operation"], "expected_preview_sha256": observed["preview_sha256"]}
    responses = await asyncio.gather(*(client.post(BASE + "/commit", json=body, headers=context["headers"])
                                       for _ in range(2)))
    assert any(response.status_code == 200 for response in responses)
    assert all(response.status_code in {200, 409} for response in responses)
    for response in responses:
        private(response)
    after = await snapshot(db_session)
    assert len(after["source_task_requests"]) == len(before["source_task_requests"]) + 1
    recovered = await client.get(f"{BASE}/requests/{context['operation']['request_key']}", headers=context["headers"])
    assert recovered.status_code == 200
    assert await snapshot(db_session) == after


async def test_whole_request_deadline_cancels_body_without_sql_or_capacity_leak(client, db_session, monkeypatch):
    context = await fixture(db_session)
    before = await snapshot(db_session)
    deadlines = []
    actual_timeout = asyncio.timeout
    cancelled = asyncio.Event()

    def clock(seconds):
        deadline = actual_timeout(seconds)
        deadlines.append((seconds, deadline))
        return deadline

    async def stalled_body(*args, **kwargs):
        # Speed up the genuine outer deadline only once initial auth completed.
        assert deadlines[0][0] == 20
        deadlines[0][1].reschedule(asyncio.get_running_loop().time() + 0.01)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with monkeypatch.context() as patch:
        patch.setattr(router.asyncio, "timeout", clock)
        patch.setattr(router, "_body", stalled_body)
        response = await client.post(BASE + "/preview", json=context["operation"], headers=context["headers"])
    assert cancelled.is_set()
    safe_error(response, 503)
    private(response)
    assert await snapshot(db_session) == before
    assert (await client.get(BASE + "/capabilities", headers=context["headers"])).status_code == 200


async def test_unknown_read_and_invalid_paths_are_private_and_do_not_leak(client, db_session):
    people = await actors(db_session)
    await db_session.commit()
    before = await snapshot(db_session)
    for path, expected in (("/requests/unknown", 404),
        (f"/requests/{uuid4()}/executions/unknown", 404),
        ("/requests/SECRET-invalid-uuid/executions/unknown", 400)):
        response = await client.get(BASE + path, headers=auth(people["curator"]))
        assert response.status_code == expected, response.text
        assert "SECRET" not in response.text
        private(response)
    assert await snapshot(db_session) == before
