"""Actual synthetic SQL imports and read-only original-key recovery.

Run only with the owned disposable runner. Synthetic native-format files are
not execution evidence, scientific acceptance, or permission to train models.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from models.db import Base
from routers import scientific_program_imports as router
from services import scientific_import_input as input_service
from services import scientific_pending_import as service
from services.research_publication import grant_role, revoke_role
from services.research_release_manifest import canonical, digest
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_freeze import state
from tests.test_research_publication import actors
from tests.test_scientific_pending_import import seed_import
from tests.test_scientific_program_import_operators import BASE, auth, body, private

db_session = _serializable_db_session
pytestmark = pytest.mark.asyncio


async def snapshot(db):
    result = await state(db)
    await db.rollback()
    return result


def query(request, pin):
    return {"request_key": request["request_key"], "expected_request_sha256": pin}


async def lookup(client, actor, request, pin):
    response = await client.get(BASE + "/outcome", params=query(request, pin), headers=auth(actor))
    private(response)
    return response


async def started(db, fixture, request):
    result = await service.start_import(db, actor_user_id=fixture["actors"]["curator"],
        request_key=request["request_key"], package=fixture["package"], dry_run=False)
    await db.commit()
    return result


async def test_actual_preview_pinned_commit_and_readonly_recovery_fixture(client, db_session, tmp_path):
    fixture = await seed_import(db_session)
    actor = fixture["actors"]["curator"]
    request = body(fixture["args"])
    await db_session.commit()
    before = await snapshot(db_session)
    caps = await client.get(BASE + "/capabilities", headers=auth(actor))
    binding = await client.get(BASE + "/material-bindings/" + fixture["material"], headers=auth(actor))
    preview = await client.post(BASE, json=request, headers=auth(actor))
    for response in (caps, binding, preview):
        assert response.status_code == 200, response.text
        private(response)
    assert await snapshot(db_session) == before
    access = caps.json()
    assert set(access) == {"version", "actor_user_id", "actor_grant_id", "can_read", "can_import",
                           "compiler_sha256", "authority"}
    assert access["compiler_sha256"] == digest(input_service.compiler_inventory())
    assert access["authority"] == input_service.AUTHORITY
    assert len(access["authority"]) == 6 and all(value is False for value in access["authority"].values())
    pin = preview.json()["result"]["request_sha256"]
    assert pin == fixture["package"].package_key
    assert preview.json()["committed"] is False
    absent = await lookup(client, actor, request, pin)
    assert absent.status_code == 404
    assert await snapshot(db_session) == before
    start = await started(db_session, fixture, request)
    before_unknown = await snapshot(db_session)
    unknown = await lookup(client, actor, request, pin)
    assert unknown.status_code == 200, unknown.text
    assert unknown.json() == {**start, "replayed": True}
    assert unknown.json()["status"] == "outcome_unknown"
    assert unknown.json()["report"] is None and unknown.json()["row_ids"] is None
    assert await snapshot(db_session) == before_unknown
    commit_request = {**request, "dry_run": False, "expected_request_sha256": pin}
    committed = await client.post(BASE, json=commit_request, headers=auth(actor))
    assert committed.status_code == 200, committed.text
    assert committed.json()["committed"] is True
    assert committed.json()["result"]["status"] == "success_pending"
    before_recovery = await snapshot(db_session)
    recovered = await lookup(client, actor, request, pin)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json() == {**committed.json()["result"], "replayed": True}
    assert await snapshot(db_session) == before_recovery
    replay = await client.post(BASE, json=commit_request, headers=auth(actor))
    assert replay.status_code == 200, replay.text
    assert replay.json()["result"] == recovered.json()
    assert await snapshot(db_session) == before_recovery
    # Persist exact synthetic HTTP documents, never manually reconstructed pins.
    output = {"capabilities": access, "material_binding": binding.json(), "request": request,
        "preview": preview.json(), "commit_request": commit_request, "committed": committed.json(),
        "outcome_unknown": unknown.json(), "outcome": recovered.json(), "absent": absent.json()}
    path = tmp_path / "scientific-import-recovery-http.json"
    path.write_bytes(canonical(output))
    print("Synthetic HTTP fixture:", path)


@pytest.mark.parametrize("status", ["outcome_unknown", "success_pending", "quarantined", "failed"])
async def test_readonly_service_and_http_observe_exact_historical_status(client, db_session, tmp_path, status):
    fixture = await seed_import(db_session, missing_fc=status == "quarantined")
    request = body(fixture["args"])
    actor = fixture["actors"]["curator"]
    result = await started(db_session, fixture, request)
    if status == "failed":
        result = await service.fail_import(db_session, actor_user_id=actor,
            attempt_id=result["attempt_id"], reason_code="parser_failed")
    elif status != "outcome_unknown":
        result = await service.finish_import(db_session, actor_user_id=actor,
            attempt_id=result["attempt_id"], prepared=service.compile_input(fixture["package"]), dry_run=False)
    await db_session.commit()
    before = await snapshot(db_session)
    await db_session.execute(sa.text("SET TRANSACTION READ ONLY"))
    direct = await service.lookup_import_outcome(db_session, actor_user_id=actor,
        **query(request, fixture["package"].package_key))
    assert await db_session.scalar(sa.text("SHOW transaction_read_only")) == "on"
    await db_session.rollback()
    response = await lookup(client, actor, request, fixture["package"].package_key)
    assert response.status_code == 200, response.text
    assert direct == response.json() == {**result, "replayed": True}
    assert direct["status"] == status
    assert await snapshot(db_session) == before
    (tmp_path / ("scientific-import-" + status + ".json")).write_bytes(canonical({
        "request": request, "outcome": response.json()}))


@pytest.mark.parametrize("case", ["wrong_actor", "wrong_key", "wrong_pin", "absent"])
async def test_actor_key_and_independent_pin_fail_closed_without_writes(client, db_session, case):
    fixture = await seed_import(db_session)
    other = await actors(db_session)
    actor = fixture["actors"]["curator"]
    request = body(fixture["args"])
    pin = fixture["package"].package_key
    if case != "absent":
        await started(db_session, fixture, request)
    await db_session.commit()
    before = await snapshot(db_session)
    if case == "wrong_actor":
        actor = other["curator"]
    if case == "wrong_key":
        request = {**request, "request_key": "unknown-key"}
    if case == "wrong_pin":
        pin = "0" * 64
    response = await lookup(client, actor, request, pin)
    assert response.status_code == (409 if case == "wrong_pin" else 404), response.text
    assert "attempt_id" not in response.text and "request_sha256" not in response.text
    assert await snapshot(db_session) == before


async def test_replaced_grant_recovers_original_receipt_not_latest_attempt(client, db_session):
    fixture = await seed_import(db_session)
    people = fixture["actors"]
    request = body(fixture["args"])
    start = await started(db_session, fixture, request)
    failed = await service.fail_import(db_session, actor_user_id=people["curator"],
        attempt_id=start["attempt_id"], reason_code="import_failed")
    await db_session.commit()
    successor = await started(db_session, fixture, {**request, "request_key": request["request_key"] + ":next"})
    await revoke_role(db_session, actor_user_id=people["admin"], grant_id=people["grants"]["curator"],
                      reason_code="synthetic_revoke", dry_run=False)
    await db_session.commit()
    revoked_before = await snapshot(db_session)
    assert (await lookup(client, people["curator"], request, fixture["package"].package_key)).status_code == 403
    assert await snapshot(db_session) == revoked_before
    replacement = await grant_role(db_session, actor_user_id=people["admin"], user_id=people["curator"],
        role="curator", reason_code="synthetic_replacement", dry_run=False)
    await db_session.commit()
    before = await snapshot(db_session)
    caps = await client.get(BASE + "/capabilities", headers=auth(people["curator"]))
    response = await lookup(client, people["curator"], request, fixture["package"].package_key)
    assert caps.status_code == response.status_code == 200
    assert caps.json()["actor_grant_id"] == replacement["id"]
    assert response.json() == {**failed, "replayed": True}
    assert response.json()["actor_grant_id"] == str(people["grants"]["curator"])
    assert response.json()["attempt_id"] != successor["attempt_id"]
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("role", [None, "admin", "member", "reviewer", "publisher"])
async def test_new_routes_require_current_explicit_curator(client, db_session, role):
    people = await actors(db_session)
    await db_session.commit()
    before = await snapshot(db_session)
    headers = {} if role is None else auth(people[role])
    for suffix in ("/capabilities", "/outcome?request_key=x&expected_request_sha256=" + "0" * 64):
        response = await client.get(BASE + suffix, headers=headers)
        assert response.status_code == (401 if role is None else 403), response.text
        private(response)
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("case", ["session", "inactive", "unverified"])
async def test_current_account_and_session_required_for_recovery(client, db_session, case):
    fixture = await seed_import(db_session)
    actor = fixture["actors"]["curator"]
    request = body(fixture["args"])
    await started(db_session, fixture, request)
    headers = auth(actor)
    users = Base.metadata.tables["users"]
    update = {"session": {"session_version": 1}, "inactive": {"is_active": False},
              "unverified": {"email_verified": False}}[case]
    await db_session.execute(users.update().where(users.c.id == actor).values(**update))
    await db_session.commit()
    before = await snapshot(db_session)
    for suffix in ("/capabilities", "/outcome"):
        response = await client.get(BASE + suffix, headers=headers,
            params=query(request, fixture["package"].package_key) if suffix == "/outcome" else None)
        assert response.status_code in {401, 403}, response.text
        private(response)
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("case", ["wrong_pin", "compiler_drift", "context_drift"])
async def test_preview_pin_checked_before_durable_start_or_compilation(client, db_session, monkeypatch, case):
    fixture = await seed_import(db_session)
    actor = fixture["actors"]["curator"]
    request = body(fixture["args"])
    await db_session.commit()
    preview = await client.post(BASE, json=request, headers=auth(actor))
    assert preview.status_code == 200, preview.text
    request.update(dry_run=False, expected_request_sha256=preview.json()["result"]["request_sha256"])
    if case == "wrong_pin":
        request["expected_request_sha256"] = "0" * 64
    elif case == "compiler_drift":
        changed = {**input_service.compiler_inventory(), "api/services/scientific_pending_import.py": "1" * 64}
        monkeypatch.setattr(input_service, "compiler_inventory", lambda: changed)
    else:
        request["context"]["expected_material_row_sha256"] = "2" * 64
    before = await snapshot(db_session)
    def forbidden(*args, **kwargs):
        pytest.fail("Mismatched independent preview pin reached compilation")
    monkeypatch.setattr(service, "compile_input", forbidden)
    response = await client.post(BASE, json=request, headers=auth(actor))
    assert response.status_code == 409, response.text
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("suffix", [
    "", "?request_key=x", "?request_key=x&expected_request_sha256=secret",
    "?request_key=x&expected_request_sha256=" + "0" * 64 + "&extra=secret",
    "?request_key=x&request_key=y&expected_request_sha256=" + "0" * 64,
    "?request_key=bad%20key&expected_request_sha256=" + "0" * 64,
])
async def test_closed_recovery_query_never_echoes_raw_input(client, db_session, suffix):
    people = await actors(db_session)
    await db_session.commit()
    before = await snapshot(db_session)
    response = await client.get(BASE + "/outcome" + suffix, headers=auth(people["curator"]))
    assert response.status_code == 400, response.text
    assert "secret" not in response.text and "bad key" not in response.text
    private(response)
    assert await snapshot(db_session) == before


async def test_legacy_inspection_still_allows_another_current_curator(client, db_session):
    fixture = await seed_import(db_session)
    other = await actors(db_session)
    request = body(fixture["args"])
    start = await started(db_session, fixture, request)
    before = await snapshot(db_session)
    legacy = await client.get(BASE + "/" + start["attempt_id"], headers=auth(other["curator"]))
    assert legacy.status_code == 200 and legacy.json()["attempt_id"] == start["attempt_id"]
    assert (await lookup(client, other["curator"], request, fixture["package"].package_key)).status_code == 404
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("mutation", ["session", "grant"])
async def test_fresh_read_rechecks_actor_after_authentication(client, db_session, monkeypatch, mutation):
    fixture = await seed_import(db_session)
    people = fixture["actors"]
    request = body(fixture["args"])
    await started(db_session, fixture, request)
    original = router._read
    captured = {}
    async def changed(actor, function, **arguments):
        if mutation == "session":
            users = Base.metadata.tables["users"]
            await db_session.execute(users.update().where(users.c.id == people["curator"]).values(session_version=1))
        else:
            await revoke_role(db_session, actor_user_id=people["admin"], grant_id=people["grants"]["curator"],
                              reason_code="synthetic_after_auth", dry_run=False)
        await db_session.commit()
        captured["state"] = await snapshot(db_session)
        return await original(actor, function, **arguments)
    monkeypatch.setattr(router, "_read", changed)
    response = await lookup(client, people["curator"], request, fixture["package"].package_key)
    assert response.status_code == 403, response.text
    assert await snapshot(db_session) == captured["state"]


async def test_lookup_failure_is_unavailable_not_a_receipt_or_write(client, db_session, monkeypatch):
    fixture = await seed_import(db_session)
    request = body(fixture["args"])
    await started(db_session, fixture, request)
    before = await snapshot(db_session)
    async def unavailable(db, **arguments):
        assert await db.scalar(sa.text("SHOW transaction_read_only")) == "on"
        raise SQLAlchemyError("private-source-and-database-error")
    monkeypatch.setattr(service, "lookup_import_outcome", unavailable)
    response = await lookup(client, fixture["actors"]["curator"], request, fixture["package"].package_key)
    assert response.status_code == 503, response.text
    assert "private-source" not in response.text and "outcome" not in response.json()
    assert await snapshot(db_session) == before


async def test_feature_gate_and_auth_are_checked_before_recovery_input(client, db_session, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    before = await snapshot(db_session)
    response = await client.get(BASE + "/outcome?secret=untrusted")
    assert response.status_code == 401
    settings = router.get_settings().model_copy(update={"ml_foundation_public_enabled": False})
    monkeypatch.setattr(router, "get_settings", lambda: settings)
    for suffix in ("/capabilities", "/outcome?secret=untrusted"):
        response = await client.get(BASE + suffix, headers=auth(people["curator"]))
        assert response.status_code == 404
        assert "secret" not in response.text
        private(response)
    assert await snapshot(db_session) == before


async def test_oversized_raw_query_is_bounded_before_pair_parsing(client, db_session, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    before = await snapshot(db_session)
    # Duplicate pairs must not be materialized before the raw byte-size guard.
    suffix = "/outcome?" + "private=x&" * 110
    original = Request.query_params
    def checked_query(request):
        if len(request.scope.get("query_string", b"")) > router.MAX_OUTCOME_QUERY_BYTES:
            pytest.fail("Oversized recovery query reached parameter parsing")
        return original.fget(request)
    monkeypatch.setattr(Request, "query_params", property(checked_query))
    response = await client.get(BASE + suffix, headers=auth(people["curator"]))
    assert response.status_code == 413, response.text
    private(response)
    assert "private=x" not in response.text
    assert await snapshot(db_session) == before
