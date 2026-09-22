"""Private rights HTTP boundaries, not synthetic legal or publication approval.

These tests keep the actual guarded PostgreSQL/auth/transaction boundary. Small
service spies isolate transport admission from the separate real-package tests.
"""
from __future__ import annotations

import asyncio
import json
import threading
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from models.db import Base
from routers import research_distribution_rights as rights
from routers import research_distributions as operators
from services.research_access import ResearchAccessDenied
from tests.test_research_distribution_operators import auth, private
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_publication import actors

db_session = _serializable_db_session
pytestmark = pytest.mark.asyncio
BASE = "/v1/ml/distributions"
PRIVATE = "PRIVATE_RIGHTS_WIRE_SOURCE_PASSWORD_PATH"


def body():
    return {
        "request_key": "synthetic-rights-wire:" + uuid4().hex,
        "decision": "allow", "license_code": "permission-on-file",
        "basis_code": "synthetic_declared_basis", "reason_code": "synthetic_wire_only",
        "expected_package_sha256": "a" * 64, "expected_inventory_sha256": "b" * 64,
        "expected_dependency_row_sha256": "c" * 64,
        "expected_head_id": None, "expected_head_sha256": None,
    }


def target():
    return BASE + "/" + str(uuid4()) + "/rights/" + "d" * 64


@pytest_asyncio.fixture
async def wire_people(db_session):
    people = await actors(db_session)
    await db_session.commit()
    return people


@pytest.fixture
def boundary_spy(monkeypatch):
    calls = []

    async def prepare(db, **arguments):
        assert await db.scalar(sa.text("SHOW transaction_isolation")) == "serializable"
        calls.append(deepcopy(arguments))
        return {"synthetic_transport_only": True, "dry_run": arguments["dry_run"],
                "committed": False, "replayed": False}

    monkeypatch.setattr(rights, "prepare_distribution_rights", prepare)
    return calls


async def test_closed_preparation_has_no_default_decision_or_license_and_safe_preview_default():
    schema = rights.Preparation.model_json_schema()
    assert schema["additionalProperties"] is False
    assert {"decision", "license_code", "expected_head_id", "expected_head_sha256"} <= set(schema["required"])
    assert schema["properties"]["dry_run"]["default"] is True
    assert "default" not in schema["properties"]["decision"]
    assert "default" not in schema["properties"]["license_code"]
    parsed = rights.Preparation.model_validate(body(), strict=True).model_dump()
    assert parsed["dry_run"] is True and parsed["expected_intent_sha256"] is None
    assert "actor_user_id" not in parsed and "rights_bytes_base64" not in parsed


@pytest.mark.parametrize("change", [
    {"dry_run": 0}, {"dry_run": 1}, {"dry_run": "false"}, {"dry_run": None},
    {"decision": "approve"}, {"decision": True}, {"license_code": ""},
    {"license_code": "unknown"}, {"license_code": "MIT"},
    {"basis_code": "some prose"}, {"reason_code": "Mixed_Case"},
    {"request_key": "../private"}, {"request_key": "x" * 161},
    {"expected_package_sha256": "A" * 64}, {"expected_inventory_sha256": True},
    {"expected_dependency_row_sha256": "a" * 63},
    {"expected_head_id": str(uuid4())}, {"expected_head_sha256": "a" * 64},
    {"decision": "revoke"}, {"dry_run": False},
    {"actor_user_id": str(uuid4())}, {"actor_grant_id": str(uuid4())},
    {"source_text": PRIVATE}, {"metadata": {}}, {"rights_bytes_base64": "eA=="},
    {"scientific_acceptance": True}, {"ml_training_approved": True},
])
async def test_closed_preparation_refuses_coercion_extra_authority_and_unpinned_intent(change):
    with pytest.raises(ValidationError):
        rights.Preparation.model_validate({**body(), **change}, strict=True)


@pytest.mark.parametrize("field", ["decision", "license_code", "expected_package_sha256",
                                      "expected_inventory_sha256", "expected_dependency_row_sha256",
                                      "expected_head_id", "expected_head_sha256"])
async def test_required_exact_input_is_never_silently_defaulted(field):
    value = body()
    del value[field]
    with pytest.raises(ValidationError):
        rights.Preparation.model_validate(value, strict=True)


@pytest.mark.parametrize("license_code", ["CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "permission-on-file"])
async def test_supported_explicit_license_and_exact_revoke_shape(license_code):
    value = {**body(), "license_code": license_code, "decision": "revoke", "dry_run": False,
             "expected_head_id": str(uuid4()), "expected_head_sha256": "e" * 64,
             "expected_intent_sha256": "f" * 64}
    assert rights.Preparation.model_validate(value, strict=True).model_dump() == value


@pytest.mark.parametrize("caller", ["anonymous", "member", "admin", "curator", "publisher"])
async def test_auth_and_explicit_reviewer_precede_any_body_read(client, wire_people, monkeypatch, caller):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("unadmitted caller reached the rights body reader")

    monkeypatch.setattr(rights, "_small_body", forbidden)
    headers = {} if caller == "anonymous" else auth(wire_people[caller])
    headers.update({"Content-Type": "application/json", "Content-Length": str(rights.MAX_BODY_BYTES + 1)})
    response = await client.post(target(), headers=headers, content=PRIVATE.encode())
    assert response.status_code == (401 if caller == "anonymous" else 403)
    assert PRIVATE not in response.text
    private(response)


@pytest.mark.parametrize("raw", [
    b'{"request_key":"PRIVATE","request_key":"OTHER"}', b'{"PRIVATE":NaN}',
    b'{"PRIVATE":Infinity}', b'{"PRIVATE":-Infinity}', b'{"PRIVATE":1e999}',
    b'{"PRIVATE":"\\ud800"}', b'{"PRIVATE":"\xff"}', b'[]', b'null', b'{"PRIVATE":',
])
async def test_malformed_json_is_private_and_never_calls_service(client, wire_people, boundary_spy, raw):
    response = await client.post(target(), content=raw, headers={**auth(wire_people["reviewer"]),
                                                               "Content-Type": "application/json"})
    assert response.status_code == 400, response.text
    assert "PRIVATE" not in response.text and not boundary_spy
    private(response)


@pytest.mark.parametrize("headers,status", [
    ({"Content-Type": "text/plain"}, 415), ({"Content-Encoding": "gzip"}, 415),
    ({"Content-Length": "8193"}, 413), ({"Content-Length": "-1"}, 413),
    ({"Content-Length": "1e3"}, 413), ({"Content-Length": "9" * 9}, 413),
])
async def test_header_refusal_precedes_stream_consumption(headers, status):
    async def stream():
        pytest.fail("invalid headers consumed source bytes")
        yield b""  # pragma: no cover

    request = SimpleNamespace(headers={"content-type": "application/json",
        **{key.lower(): value for key, value in headers.items()}}, stream=stream)
    with pytest.raises(HTTPException) as caught:
        await rights._small_body(request)
    assert caught.value.status_code == status


@pytest.mark.parametrize("extra", [0, 1])
async def test_actual_8k_stream_boundary_without_content_length(client, wire_people, boundary_spy, extra):
    encoded = json.dumps(body()).encode()
    payload = encoded + b" " * (8192 - len(encoded) + extra)

    async def stream():
        yield payload[:4000]
        yield payload[4000:]

    response = await client.post(target(), content=stream(), headers={**auth(wire_people["reviewer"]),
                                                                    "Content-Type": "application/json"})
    assert response.status_code == (413 if extra else 200), response.text
    assert len(boundary_spy) == (0 if extra else 1)
    if not extra:
        assert response.json()["committed"] is False
        assert boundary_spy[0]["actor_user_id"] == wire_people["reviewer"]
    private(response)


async def test_stream_fragment_limit_counts_empty_chunks_before_parsing(monkeypatch):
    # Empty transport fragments consume CPU even when the byte budget is intact.
    # This direct stream test is needed because ASGI may discard empty frames.
    assert 1 <= rights.MAX_BODY_CHUNKS <= 4096
    reads = 0

    async def stream():
        nonlocal reads
        for _ in range(rights.MAX_BODY_CHUNKS + 1):
            reads += 1
            yield b""
        pytest.fail("fragment budget allowed further stream traversal")

    def forbidden(_payload):
        pytest.fail("fragment-limit failure reached JSON parsing")

    monkeypatch.setattr(rights, "_strict_json", forbidden)
    request = SimpleNamespace(headers={"content-type": "application/json"}, stream=stream)
    with pytest.raises(HTTPException) as caught:
        await rights._small_body(request)
    assert caught.value.status_code == 413 and reads == rights.MAX_BODY_CHUNKS + 1


@pytest.mark.parametrize("change", ["role_revoked", "inactive", "email_unverified", "session_revoked"])
async def test_late_identity_change_after_stream_refuses_before_service(
        client, db_session, wire_people, boundary_spy, monkeypatch, change):
    from services.research_publication import revoke_role

    original = rights._small_body

    async def changed(request):
        value = await original(request)
        if change == "role_revoked":
            await revoke_role(db_session, actor_user_id=wire_people["admin"],
                grant_id=wire_people["grants"]["reviewer"], reason_code="synthetic_late_wire_hold", dry_run=False)
        else:
            field, scalar = {"inactive": ("is_active", False), "email_unverified": ("email_verified", False),
                             "session_revoked": ("session_version", 1)}[change]
            users = Base.metadata.tables["users"]
            await db_session.execute(sa.update(users).where(users.c.id == wire_people["reviewer"]).values(**{field: scalar}))
        await db_session.commit()
        return value

    monkeypatch.setattr(rights, "_small_body", changed)
    response = await client.post(target(), json=body(), headers=auth(wire_people["reviewer"]))
    assert response.status_code == 403, response.text
    assert not boundary_spy
    private(response)


@pytest.mark.parametrize("failure,status", [
    (SQLAlchemyError(PRIVATE), 503), (TimeoutError(PRIVATE), 503),
    (ResearchAccessDenied(PRIVATE), 403), (ValueError(PRIVATE), 400),
    (TypeError(PRIVATE), 400), (RuntimeError(PRIVATE), 503),
    (rights.RightsPreparationConflict(PRIVATE), 409),
])
async def test_private_errors_release_capacity_and_do_not_echo_diagnostics(
        client, wire_people, monkeypatch, failure, status):
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(operators, "_request_slots", slots)

    async def failed(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(rights, "prepare_distribution_rights", failed)
    response = await client.post(target(), json=body(), headers=auth(wire_people["reviewer"]))
    assert response.status_code == status, response.text
    assert PRIVATE not in response.text and "committed" not in response.json()
    private(response)
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)
    slots.release()
    slots.release()


async def test_capacity_is_shared_for_preview_inspection_and_get_outcome_and_cancel_releases(
        client, wire_people, monkeypatch, boundary_spy):
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(operators, "_request_slots", slots)
    entered, release = asyncio.Event(), asyncio.Event()
    readers = []
    original = rights._small_body

    async def held(request):
        value = await original(request)
        readers.append(True)
        if len(readers) == 2:
            entered.set()
        await release.wait()
        return value

    monkeypatch.setattr(rights, "_small_body", held)
    headers = auth(wire_people["reviewer"])
    path = target()
    pending = [asyncio.create_task(client.post(path, headers=headers, json=body())) for _ in range(2)]
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        calls = [client.post(path, headers=headers, json=body()), client.get(path, headers=headers),
                 client.get(path + "/outcome", headers=headers,
                    params={"request_key": "synthetic_original", "expected_intent_sha256": "a" * 64})]
        for call in calls:
            response = await asyncio.wait_for(call, timeout=1)
            assert response.status_code == 503 and response.headers["retry-after"] == "1"
            private(response)
        assert len(readers) == 2 and not boundary_spy
        pending[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending[0]
        assert slots.acquire(blocking=False) and not slots.acquire(blocking=False)
        slots.release()
        release.set()
        response = await pending[1]
        assert response.status_code == 200 and response.json()["committed"] is False
    finally:
        release.set()
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    assert len(boundary_spy) == 1
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)
    slots.release()
    slots.release()


async def test_streaming_body_schema_is_documented_without_framework_body_hydration():
    from main import app

    schema = app.openapi()["paths"][BASE + "/{package_id}/rights/{dependency_id}"]["post"][
        "requestBody"]["content"]["application/json"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["dry_run"]["default"] is True
    assert {"decision", "license_code", "expected_package_sha256", "expected_dependency_row_sha256"} <= set(schema["required"])
    assert not ({"actor_user_id", "artifact", "uri", "rights_bytes_base64"} & set(schema["properties"]))


def read_path(kind, path):
    if kind == "capabilities":
        return BASE + "/operator/capabilities", {}
    if kind == "dependencies":
        return path.rsplit("/", 1)[0], {"after": "e" * 64, "expected_inventory_sha256": "f" * 64}
    if kind == "outcome":
        return path + "/outcome", {"request_key": "synthetic:original/+@key", "expected_intent_sha256": "f" * 64}
    return path, {}


READ_FUNCTIONS = {"capabilities": "rights_preparation_capabilities", "dependencies": "list_rights_dependencies",
                  "inspect": "inspect_rights_dependency", "outcome": "rights_preparation_outcome"}


@pytest.mark.parametrize("kind", list(READ_FUNCTIONS))
async def test_read_routes_require_auth_before_service_and_never_return_private_input(client, monkeypatch, kind):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("anonymous read reached a private service")

    monkeypatch.setattr(rights, READ_FUNCTIONS[kind], forbidden)
    path, params = read_path(kind, target())
    response = await client.get(path, params=params)
    assert response.status_code == 401
    private(response)


async def test_actual_capability_is_exact_current_reviewer_not_a_publication_grant(client, wire_people):
    response = await client.get(BASE + "/operator/capabilities", headers=auth(wire_people["reviewer"]))
    assert response.status_code == 200, response.text
    assert response.json() == {"version": "rps-rights-preparation/1.0.0", "scope": "rps_structured_bundle",
        "actor_user_id": str(wire_people["reviewer"]), "actor_grant_id": str(wire_people["grants"]["reviewer"]),
        "can_read": True, "can_prepare": True, "scientific_acceptance": False,
        "ml_training_approved": False, "current_authorization_checked": False}
    private(response)


@pytest.mark.parametrize("kind", list(READ_FUNCTIONS))
async def test_read_routes_use_fresh_readonly_snapshot_and_preserve_exact_selectors(
        client, wire_people, monkeypatch, kind):
    observed = []

    async def inspect(db, **arguments):
        assert await db.scalar(sa.text("SHOW transaction_isolation")) == "repeatable read"
        assert await db.scalar(sa.text("SHOW transaction_read_only")) == "on"
        assert await db.scalar(sa.text("SHOW statement_timeout")) == "3s"
        observed.append(arguments)
        return {"synthetic_transport_only": True}

    monkeypatch.setattr(rights, READ_FUNCTIONS[kind], inspect)
    path, params = read_path(kind, target())
    response = await client.get(path, params=params, headers=auth(wire_people["reviewer"]))
    assert response.status_code == 200, response.text
    assert len(observed) == 1 and observed[0]["actor_user_id"] == wire_people["reviewer"]
    for field, value in params.items():
        assert observed[0][field] == value
    private(response)


@pytest.mark.parametrize("kind", list(READ_FUNCTIONS))
async def test_read_route_rechecks_session_after_precheck_before_private_service(
        client, db_session, wire_people, monkeypatch, kind):
    original = rights._precheck

    async def stale(user, role):
        await original(user, role)
        users = Base.metadata.tables["users"]
        await db_session.execute(sa.update(users).where(users.c.id == wire_people["reviewer"]).values(session_version=1))
        await db_session.commit()

    async def forbidden(*_args, **_kwargs):
        pytest.fail("late session change reached a private read service")

    monkeypatch.setattr(rights, "_precheck", stale)
    monkeypatch.setattr(rights, READ_FUNCTIONS[kind], forbidden)
    path, params = read_path(kind, target())
    response = await client.get(path, params=params, headers=auth(wire_people["reviewer"]))
    assert response.status_code == 403, response.text
    private(response)


@pytest.mark.parametrize("failure,status", [(rights.RightsPreparationNotFound(PRIVATE), 404),
                                            (rights.RightsPreparationConflict(PRIVATE), 409)])
async def test_get_outcome_missing_and_conflicting_are_not_success(client, wire_people, monkeypatch, failure, status):
    async def unavailable(*_args, **_kwargs):
        raise failure

    async def forbidden(*_args, **_kwargs):
        pytest.fail("read-only recovery attempted preparation")

    monkeypatch.setattr(rights, "rights_preparation_outcome", unavailable)
    monkeypatch.setattr(rights, "prepare_distribution_rights", forbidden)
    path, params = read_path("outcome", target())
    response = await client.get(path, params=params, headers=auth(wire_people["reviewer"]))
    assert response.status_code == status and "committed" not in response.json()
    assert PRIVATE not in response.text
    private(response)
