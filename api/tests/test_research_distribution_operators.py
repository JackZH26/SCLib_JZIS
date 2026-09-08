"""Private operator HTTP boundary on guarded disposable PostgreSQL only."""
from __future__ import annotations

import asyncio
import base64
import json
import threading
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from models.db import Base
from routers import research_distributions as router
from services import auth_service
from tests.test_research_freeze import add
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_publication import actors

db_session = _serializable_db_session
pytestmark = pytest.mark.asyncio
BASE = "/v1/ml/distributions"


@pytest_asyncio.fixture
async def operator_user(registered_user, db_session):
    """Wire-validation callers have real grants; ordinary accounts do not."""
    from services.research_publication import grant_role
    user, token = registered_user
    people = await actors(db_session)
    for role in ("curator", "reviewer", "publisher"):
        await grant_role(db_session, actor_user_id=people["admin"], user_id=user.id,
                         role=role, reason_code="synthetic_wire_validation", dry_run=False)
    await db_session.commit()
    return user, token


def auth(identifier):
    token, _ = auth_service.create_access_token(identifier)
    return {"Authorization": "Bearer " + token}


def private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers
    assert "location" not in response.headers


def registration_body(arguments=None):
    arguments = deepcopy(arguments or {"release": {}, "bindings": {}, "public_bundle": {},
        "expected_release_sha256": "a" * 64, "expected_bindings_sha256": "b" * 64,
        "expected_public_bundle_sha256": "c" * 64, "artifact_bytes": {}, "capsule_artifact_bytes": {}})
    arguments["artifact_bytes_base64"] = {key: base64.b64encode(value).decode("ascii")
        for key, value in arguments.pop("artifact_bytes").items()}
    arguments["capsule_artifact_bytes_base64"] = {sha: {key: base64.b64encode(value).decode("ascii")
        for key, value in values.items()} for sha, values in arguments.pop("capsule_artifact_bytes").items()}
    return {**arguments, "request_key": "synthetic-http:" + uuid4().hex}


def operation(path):
    common = {"request_key": "synthetic-http:" + uuid4().hex}
    if path == "register":
        return registration_body()
    if path == "permissions":
        return {**common, "dependency_id": "a" * 64, "decision": "allow",
            "license_code": "permission-on-file", "basis_code": "synthetic_basis",
            "reason_code": "synthetic_reason", "rights_artifact_id": str(uuid4()),
            "expected_rights_row_sha256": "b" * 64, "rights_bytes_base64": "eA=="}
    if path == "reviews":
        return {**common, "expected_inventory_sha256": "a" * 64,
            "disclosure_approved": True, "reason_code": "synthetic_review"}
    return {**common, "expected_inventory_sha256": "a" * 64, "review_id": str(uuid4()),
        "kind": "publish", "reason_code": "synthetic_publish"}


def path_for(kind, identifier=None):
    return BASE + "/register" if kind == "register" else BASE + "/" + str(identifier or uuid4()) + "/" + kind


@pytest.mark.parametrize("kind", ["register", "permissions", "reviews", "actions", "inspect"])
async def test_all_operator_routes_require_authentication(client, kind):
    response = await client.get(BASE + "/" + str(uuid4())) if kind == "inspect" else await client.post(
        path_for(kind), json=operation(kind))
    assert response.status_code == 401
    private(response)


@pytest.mark.parametrize("role", ["admin", "member"])
async def test_legacy_flags_are_not_distribution_grants(client, db_session, role):
    people = await actors(db_session)
    await db_session.commit()
    for kind in ("register", "permissions", "reviews", "actions"):
        response = await client.post(path_for(kind), headers=auth(people[role]), json=operation(kind))
        assert response.status_code == 403, response.text
        private(response)
    response = await client.get(BASE + "/" + str(uuid4()), headers=auth(people[role]))
    assert response.status_code == 403
    private(response)


@pytest.mark.parametrize("kind,wrong_role", [("register", "reviewer"), ("permissions", "curator"),
    ("reviews", "publisher"), ("actions", "reviewer")])
async def test_exact_live_role_required(client, db_session, kind, wrong_role):
    people = await actors(db_session)
    await db_session.commit()
    response = await client.post(path_for(kind), headers=auth(people[wrong_role]), json=operation(kind))
    assert response.status_code == 403, response.text
    private(response)


@pytest.mark.parametrize("kind", ["register", "permissions", "reviews", "actions"])
async def test_request_cannot_select_its_actor(client, operator_user, kind):
    _, token = operator_user
    body = {**operation(kind), "actor_user_id": str(uuid4())}
    response = await client.post(path_for(kind), headers={"Authorization": "Bearer " + token}, json=body)
    assert response.status_code == 400
    assert "actor_user_id" not in response.text
    private(response)


@pytest.mark.parametrize("value", [0, 1, "false", None, []])
async def test_dry_run_never_coerces_false(client, operator_user, value):
    _, token = operator_user
    response = await client.post(BASE + "/register", headers={"Authorization": "Bearer " + token},
        json={**registration_body(), "dry_run": value})
    assert response.status_code == 400
    private(response)


@pytest.mark.parametrize("raw", [b'{"dry_run":true,"dry_run":false}', b'{"secret":NaN}',
    b'{"secret":Infinity}', b'{"secret":1e999}', b'{"secret":"\\ud800"}', b'{"secret":"\xff"}',
    b'[]', b'{"secret":'])
async def test_strict_json_rejects_without_echo(client, operator_user, raw):
    _, token = operator_user
    response = await client.post(BASE + "/register", headers={"Authorization": "Bearer " + token,
        "Content-Type": "application/json"}, content=raw)
    assert response.status_code == 400, response.text
    assert "secret" not in response.text
    private(response)


@pytest.mark.parametrize("change", ["header_size", "stream_size", "depth", "nodes", "encoded_size", "decoded_size",
    "base64_whitespace", "base64_noncanonical", "base64_unicode", "base64_padding", "content_type", "compression"])
async def test_stream_and_decoded_resource_bounds(client, operator_user, monkeypatch, change):
    _, token = operator_user
    body, headers = registration_body(), {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    expected = 413
    if change == "header_size":
        headers["Content-Length"] = str(router.MAX_REQUEST_BYTES + 1)
    elif change == "stream_size":
        monkeypatch.setattr(router, "MAX_REQUEST_BYTES", 10)
    elif change == "depth":
        monkeypatch.setattr(router, "MAX_JSON_DEPTH", 1)
    elif change == "nodes":
        monkeypatch.setattr(router, "MAX_JSON_NODES", 2)
    elif change in {"encoded_size", "decoded_size"}:
        body["artifact_bytes_base64"] = {"a" * 64: base64.b64encode(b"abcde").decode()}
        monkeypatch.setattr(router, "MAX_ARTIFACT_BYTES" if change == "encoded_size" else "MAX_DECODED_BYTES", 1)
    elif change.startswith("base64_"):
        body["artifact_bytes_base64"] = {"a" * 64: {"base64_whitespace": "eA==\n", "base64_noncanonical": "eB==",
            "base64_unicode": "秘密", "base64_padding": "eA="}[change]}
        expected = 400
    elif change == "content_type":
        headers["Content-Type"] = "text/plain"
        expected = 415
    else:
        headers["Content-Encoding"] = "gzip"
        expected = 415

    async def chunks():
        value = json.dumps(body).encode()
        yield value[:10]
        yield value[10:]

    response = await client.post(BASE + "/register", headers=headers, content=chunks())
    assert response.status_code == expected, response.text
    private(response)


async def test_cookie_write_requires_allowlisted_origin(client, registered_user):
    from config import get_settings
    from services.session_config import build_browser_session_config
    _, token = registered_user
    settings = get_settings()
    cookie = build_browser_session_config(settings.environment, settings.jwt_expiry_hours * 3600).cookie_name
    client.cookies.set(cookie, token)
    for headers in ({}, {"Origin": "https://untrusted.invalid"}):
        response = await client.post(BASE + "/register", json=registration_body(), headers=headers)
        assert response.status_code == 403
        private(response)


async def test_default_preview_and_explicit_commit_use_real_outer_transaction(client, db_session, monkeypatch):
    from services import research_distribution as service
    people = await actors(db_session)
    await db_session.commit()
    marker = "distribution-http:" + uuid4().hex
    seen = []

    async def append(db, **kwargs):
        seen.append(kwargs)
        assert await db.scalar(sa.text("SHOW transaction_isolation")) == "serializable"
        await add(db, "stats_cache", key=marker, value={"synthetic": True})
        return {"id": str(uuid4()), "committed": False, "dry_run": kwargs["dry_run"]}

    monkeypatch.setattr(service, "register_distribution", append)
    body = registration_body()
    preview = await client.post(BASE + "/register", json=body, headers=auth(people["curator"]))
    assert preview.status_code == 200, preview.text
    assert preview.json()["committed"] is False and preview.json()["dry_run"] is True
    assert seen[-1]["actor_user_id"] == people["curator"]
    assert seen[-1]["dry_run"] is True
    assert await db_session.scalar(sa.text("SELECT count(*) FROM stats_cache WHERE key=:key"), {"key": marker}) == 0
    await db_session.rollback()
    committed = await client.post(BASE + "/register", json={**body, "dry_run": False}, headers=auth(people["curator"]))
    assert committed.status_code == 200, committed.text
    assert committed.json()["committed"] is True
    assert committed.json()["result"]["committed"] is False  # savepoint report is not rewritten
    assert await db_session.scalar(sa.text("SELECT count(*) FROM stats_cache WHERE key=:key"), {"key": marker}) == 1
    private(preview)
    private(committed)


@pytest.mark.parametrize("failure", ["service", "timeout", "serialize", "commit"])
async def test_failure_never_reports_success_or_leaks_and_rolls_back(client, db_session, monkeypatch, failure):
    from services import research_distribution as service
    people = await actors(db_session)
    await db_session.commit()
    marker = "distribution-failure:" + uuid4().hex
    deferred_returned = []

    async def fail(db, **kwargs):
        await add(db, "stats_cache", key=marker, value={"synthetic": True})
        if failure == "service":
            raise SQLAlchemyError("PRIVATE-SOURCE-BODY-DSN")
        if failure == "timeout":
            raise TimeoutError("PRIVATE-SOURCE-BODY-DSN")
        if failure == "serialize":
            return {"secret": object()}
        # Test-only connection-local table: the real deferred FK raises after
        # this handler returns, when the router commits its outer transaction.
        await db.execute(sa.text("CREATE TEMP TABLE distribution_commit_probe "
            "(id integer PRIMARY KEY, parent_id integer REFERENCES distribution_commit_probe(id) "
            "DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP"))
        await db.execute(sa.text("INSERT INTO distribution_commit_probe VALUES(1,2)"))
        deferred_returned.append(True)
        return {"committed": False}

    monkeypatch.setattr(service, "register_distribution", fail)
    response = await client.post(BASE + "/register", json={**registration_body(), "dry_run": False},
        headers=auth(people["curator"]))
    assert response.status_code in {400, 503}
    assert "PRIVATE" not in response.text and "committed" not in response.json()
    if failure == "commit":
        assert deferred_returned == [True] and response.status_code == 503
    assert await db_session.scalar(sa.text("SELECT count(*) FROM stats_cache WHERE key=:key"), {"key": marker}) == 0
    private(response)


async def test_streaming_operator_schemas_are_discoverable_without_accepting_actor_payload():
    from main import app
    paths = app.openapi()["paths"]
    for suffix in ("/register", "/{package_id}/permissions", "/{package_id}/reviews", "/{package_id}/actions"):
        schema = paths[BASE + suffix]["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["dry_run"]["default"] is True
        assert "actor_user_id" not in schema["properties"]


@pytest.mark.parametrize("change", ["role_revoked", "email_unverified", "inactive", "session_revoked"])
async def test_live_identity_checked_again_after_body_capture(client, db_session, monkeypatch, change):
    from services import research_publication
    people = await actors(db_session)
    await db_session.commit()
    original = router._body

    async def capture(request, model):
        body = await original(request, model)
        if change == "role_revoked":
            await research_publication.revoke_role(db_session, actor_user_id=people["admin"],
                grant_id=people["grants"]["curator"], reason_code="synthetic_late_revocation", dry_run=False)
        else:
            column, value = {"email_unverified": ("email_verified", False), "inactive": ("is_active", False),
                             "session_revoked": ("session_version", 1)}[change]
            await db_session.execute(sa.update(Base.metadata.tables["users"]).where(
                Base.metadata.tables["users"].c.id == people["curator"]).values(**{column: value}))
        await db_session.commit()
        return body

    monkeypatch.setattr(router, "_body", capture)
    response = await client.post(BASE + "/register", json=registration_body(), headers=auth(people["curator"]))
    assert response.status_code == 403, response.text
    private(response)


async def test_actual_registration_preview_commit_and_private_inspection(client, db_session):
    from tests.rps_distribution_fixtures import distribution_inputs, release_document
    from tests.test_research_freeze import state
    context = await distribution_inputs(db_session, release_document())
    await db_session.commit()
    body = registration_body(context["arguments"])
    people = context["shared"]["actors"]
    preview = await client.post(BASE + "/register", json=body, headers=auth(people["curator"]))
    assert preview.status_code == 200, preview.text
    assert preview.json()["committed"] is False
    expected = preview.json()["result"]
    assert expected["inventory"]["scientific_acceptance"] is False
    assert await db_session.scalar(sa.text("SELECT count(*) FROM research_distribution_packages WHERE release_id=:id"),
        {"id": context["release"]["id"]}) == 0
    await db_session.rollback()
    response = await client.post(BASE + "/register", json={**body, "dry_run": False}, headers=auth(people["curator"]))
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert response.json()["committed"] is True
    assert result["inventory_sha256"] == expected["inventory_sha256"]
    before_replay = await state(db_session)
    await db_session.rollback()
    replay = await client.post(BASE + "/register", json={**body, "dry_run": False}, headers=auth(people["curator"]))
    assert replay.status_code == 200 and replay.json()["result"]["replayed"] is True, replay.text
    assert replay.json()["committed"] is True
    assert await state(db_session) == before_replay
    await db_session.rollback()
    inspection = await client.get(BASE + "/" + result["package_id"], headers=auth(people["reviewer"]))
    assert inspection.status_code == 200, inspection.text
    assert "inventory" in inspection.json()
    assert inspection.json()["inventory"]["scientific_acceptance"] is False
    private(response)
    private(inspection)


async def test_full_actual_operator_http_workflow_and_revoke_without_obsolete_bytes(client, db_session):
    import hashlib

    from services import research_distribution as service
    from services.research_distribution_contract import ResearchDistributionError
    from services.research_priority import canonical_json, digest
    from tests.rps_distribution_fixtures import distribution_inputs, release_document
    from tests.test_research_freeze import state
    from tests.test_research_release_schema import capture

    context = await distribution_inputs(db_session, release_document())
    people = context["shared"]["actors"]
    await db_session.commit()
    response = await client.post(BASE + "/register", json={**registration_body(context["arguments"]), "dry_run": False},
                                 headers=auth(people["curator"]))
    assert response.status_code == 200, response.text
    registration = response.json()["result"]
    package_id = registration["package_id"]
    await db_session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    package = await service._get(db_session, "packages", package_id)
    requests = []
    for dependency in registration["inventory"]["dependencies"]:
        document = service.rights_review_payload(package, dependency, "permission-on-file", "synthetic_http_disclosure")
        encoded = canonical_json(document).encode()
        sha = hashlib.sha256(encoded).hexdigest()
        artifact = await add(db_session, "evidence_artifacts", kind="review", schema_version=service.RIGHTS_VERSION,
            source="synthetic-http-rights", record_sha256=sha, bytes_sha256=sha, hash_status="verified", access="restricted",
            metadata={"distribution_rights": document})
        actual = await capture(db_session, "evidence_artifacts", artifact["id"])
        requests.append({"request_key": "http-permission:" + uuid4().hex, "dependency_id": dependency["dependency_id"],
            "decision": "allow", "license_code": "permission-on-file", "basis_code": "synthetic_http_disclosure",
            "reason_code": "synthetic_http_permission", "rights_artifact_id": str(artifact["id"]),
            "expected_rights_row_sha256": digest(actual), "rights_bytes_base64": base64.b64encode(encoded).decode()})
    await db_session.commit()
    preview = await client.post(path_for("permissions", package_id), json=requests[0], headers=auth(people["reviewer"]))
    assert preview.status_code == 200 and preview.json()["committed"] is False, preview.text
    assert await db_session.scalar(sa.text("SELECT count(*) FROM research_distribution_permissions WHERE package_id=:id"),
                                   {"id": UUID(package_id)}) == 0
    await db_session.rollback()
    receipts = []
    for body in requests:
        response = await client.post(path_for("permissions", package_id), json={**body, "dry_run": False},
                                     headers=auth(people["reviewer"]))
        assert response.status_code == 200, response.text
        receipts.append(response.json()["result"])
    review = {"request_key": "http-review:" + uuid4().hex, "expected_inventory_sha256": registration["inventory_sha256"],
        "disclosure_approved": True, "reason_code": "synthetic_http_review"}
    for preview_only in (True, False):
        response = await client.post(path_for("reviews", package_id), json={**review, "dry_run": preview_only},
                                     headers=auth(people["reviewer"]))
        assert response.status_code == 200 and response.json()["committed"] is not preview_only, response.text
    review_id = response.json()["result"]["id"]
    action = {"request_key": "http-publish:" + uuid4().hex, "expected_inventory_sha256": registration["inventory_sha256"],
        "review_id": review_id, "kind": "publish", "reason_code": "synthetic_http_publish"}
    for preview_only in (True, False):
        response = await client.post(path_for("actions", package_id), json={**action, "dry_run": preview_only},
                                     headers=auth(people["publisher"]))
        assert response.status_code == 200 and response.json()["committed"] is not preview_only, response.text
    await db_session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    admitted = await service.admitted_distribution(db_session, package_id)
    assert admitted["package_id"] == package_id
    before_replay = await state(db_session)
    await db_session.rollback()
    for kind, body, role in (("permissions", requests[0], "reviewer"), ("reviews", review, "reviewer"),
                             ("actions", action, "publisher")):
        response = await client.post(path_for(kind, package_id), json={**body, "dry_run": False}, headers=auth(people[role]))
        assert response.status_code == 200 and response.json()["result"]["replayed"] is True, response.text
    assert await state(db_session) == before_replay
    await db_session.rollback()
    # An exact retained predecessor is sufficient to revoke. Old source bytes
    # need not remain obtainable merely to stop public disclosure.
    first = requests[0]
    revoke = {key: first[key] for key in ("dependency_id", "license_code", "basis_code")}
    revoke.update(request_key="http-revoke:" + uuid4().hex, decision="revoke", supersedes_id=receipts[0]["id"],
                  reason_code="synthetic_http_revocation", dry_run=False)
    response = await client.post(path_for("permissions", package_id), json=revoke, headers=auth(people["reviewer"]))
    assert response.status_code == 200 and response.json()["committed"] is True, response.text
    await db_session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    with pytest.raises(ResearchDistributionError):
        await service.admitted_distribution(db_session, package_id)
    await db_session.rollback()
    response = await client.post(path_for("actions", package_id), json={**action, "request_key": "http-withdraw:" + uuid4().hex,
        "kind": "withdraw", "reason_code": "synthetic_http_withdrawal", "dry_run": False}, headers=auth(people["publisher"]))
    assert response.status_code == 200 and response.json()["committed"] is True, response.text
    private(response)


async def test_cancelled_operation_does_not_commit(db_session):
    people = await actors(db_session)
    await db_session.commit()
    # Retain only authenticated values; do not use an expired ORM attribute in
    # a different connection after the test session rollback.
    from types import SimpleNamespace
    actor = SimpleNamespace(id=people["curator"], session_version=0)
    marker = "cancelled-distribution:" + uuid4().hex

    async def cancelled(db, **_kwargs):
        await add(db, "stats_cache", key=marker, value={"synthetic": True})
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await router._operate(actor, "curator", cancelled, {"dry_run": False})
    assert await db_session.scalar(sa.text("SELECT count(*) FROM stats_cache WHERE key=:key"), {"key": marker}) == 0


@pytest.mark.parametrize("kind", ["register", "permissions", "reviews", "actions"])
async def test_ungranted_account_rejected_before_upload_or_decode(client, registered_user, monkeypatch, kind):
    _, token = registered_user

    async def forbidden_read(*_args, **_kwargs):
        pytest.fail("ungranted caller reached body reader")

    def forbidden_decode(*_args, **_kwargs):
        pytest.fail("ungranted caller reached byte decoder")

    monkeypatch.setattr(router, "_body", forbidden_read)
    monkeypatch.setattr(router, "_decode_inputs", forbidden_decode)
    response = await client.post(path_for(kind), headers={"Authorization": "Bearer " + token,
        "Content-Length": str(router.MAX_REQUEST_BYTES + 1), "Content-Type": "application/json"}, content=b"INVALID")
    assert response.status_code == 403, response.text
    private(response)


async def test_per_process_capacity_covers_upload_get_and_releases_after_cancellation(client, operator_user, monkeypatch):
    _, token = operator_user
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(router, "_request_slots", slots)
    reached = asyncio.Event()
    release = asyncio.Event()
    original = router._body
    entered = []

    async def held_body(request, model):
        value = await original(request, model)
        entered.append(True)
        if len(entered) == 2:
            reached.set()
        await release.wait()
        return value

    monkeypatch.setattr(router, "_body", held_body)
    headers = {"Authorization": "Bearer " + token}
    tasks = [asyncio.create_task(client.post(BASE + "/register", json=registration_body(), headers=headers)) for _ in range(2)]
    try:
        await asyncio.wait_for(reached.wait(), timeout=5)
        # Every public operator path shares the same gate, including inventory
        # reads; rejection is immediate and does not add a queued waiter.
        for kind in ("register", "permissions", "reviews", "actions", "inspect"):
            request = client.get(BASE + "/" + str(uuid4()), headers=headers) if kind == "inspect" else client.post(
                path_for(kind), json=operation(kind), headers=headers)
            response = await asyncio.wait_for(request, timeout=1)
            assert response.status_code == 503 and response.headers["retry-after"] == "1", response.text
            assert response.json()["detail"] == "Distribution capacity unavailable; retry"
            private(response)
        assert len(entered) == 2
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        response = await client.get(BASE + "/" + str(uuid4()), headers=headers)
        assert response.status_code == 400, response.text  # missing package, not exhausted capacity
        release.set()
        response = await tasks[1]
        assert response.status_code == 400  # deliberately invalid synthetic release
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert slots.acquire(blocking=False)
    assert slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)
    slots.release()
    slots.release()


@pytest.mark.parametrize("failure", ["sql", "timeout", "validation"])
async def test_capacity_returns_on_precheck_failure_without_body_read(client, operator_user, monkeypatch, failure):
    _, token = operator_user
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(router, "_request_slots", slots)

    async def fail(*_args):
        raise {"sql": SQLAlchemyError, "timeout": TimeoutError, "validation": ValueError}[failure]("PRIVATE-UPLOAD-ERROR")

    async def body(*_args):
        pytest.fail("failed precheck reached upload")

    monkeypatch.setattr(router, "_precheck", fail)
    monkeypatch.setattr(router, "_body", body)
    for _ in range(3):
        response = await client.post(BASE + "/register", json=registration_body(), headers={"Authorization": "Bearer " + token})
        assert response.status_code == (400 if failure == "validation" else 503)
        assert "PRIVATE" not in response.text and "capacity" not in response.text
        private(response)
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)
    slots.release()
    slots.release()
