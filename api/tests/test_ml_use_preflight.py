"""Synthetic private ML intake on guarded owned SQL; never a training grant."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
import sqlalchemy as sa

from config import get_settings
from models.db import User
from models.ml_use_request import INPUTS, PURPOSE, prepare_request
from routers import ml_use_preflight as router
from services import ml_use_preflight as service
from services.ml_dataset_builder import AUTHORITY
from services.research_release_manifest import digest
from tests.test_ml_use_governance import arguments, decide
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state
from tests.test_research_publication import prepared

BASE = "/v1/ml/use/preflight"


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv("ML_USE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "etag" not in response.headers


async def setup(db, *, permissions=False):
    context = await prepared(db, permissions=permissions)
    people = context["actors"]
    operator = people["curator"]
    await db.execute(sa.update(User).where(User.id == operator).values(is_admin=True))
    membership = await decide(db, arguments(people, user_id=str(operator)))
    manifest = context["release"]["manifest"]
    # Declared non-manifest pins deliberately are not genuine input bytes.
    # The online report must never represent them as reconstructed/approved.
    companion = {"base_release_id": context["release"]["release_id"], "bindings": []}
    pins = {name + "_sha256": digest({"synthetic_declared_pin": name}) for name in INPUTS}
    pins.update(manifest_sha256=digest(manifest), companion_sha256=digest(companion))
    request = prepare_request(manifest=manifest, companion=companion, input_pins=pins)
    body = {"request": request, "expected_request_sha256": digest(request),
            "expected_requester_grant_id": membership["decision"]["id"],
            "expected_curator_grant_id": str(people["grants"]["curator"])}
    return context, body, membership


@pytest.mark.parametrize("permissions", [False, True])
async def test_online_dependency_inventory_does_not_infer_training_from_metadata_rights(client, db_session, permissions):
    context, body, _ = await setup(db_session, permissions=permissions)
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    headers = auth(context["actors"]["curator"])
    access = await client.get(BASE + "/access", headers=headers)
    assert access.status_code == 200, access.text
    result = await client.post(BASE, json=body, headers=headers)
    assert result.status_code == 200, result.text
    report = result.json()
    assert report["version"] == service.VERSION and report["purpose"] == PURPOSE
    assert report["request_sha256"] == digest(body["request"])
    assert report["dependency_count"] == len(report["requirements"]) > 0
    assert report["requirements_sha256"] == digest(report["requirements"])
    frozen = {(r["table"], r["row_id"]) for r in context["release"]["manifest"]["rows"]}
    assert frozen <= {(r["table"], r["row_id"]) for r in report["requirements"]}
    assert report["registered_dependency_inventory_checked"] is True
    assert report["online_private_input_reconstruction_verified"] is False
    assert report["decision"] == "not_authorized" and report["request_persisted"] is False
    for key in (*AUTHORITY, "database_mutated", "source_permission_granted", "run_authorization_granted", "data_access_granted"):
        assert report[key] is False
    assert all(r["permission_granted"] is False and r["purpose_permission_status"] == "not_available"
               for r in report["requirements"])
    assert not any(r["frozen_row_changed"] for r in report["requirements"])
    for word in ("MgB2", "Synthetic reviewer", "source text", "abstract", "password"):
        assert word not in result.text
    private(access)
    private(result)
    assert await state(db_session) == before


@pytest.mark.parametrize("identity", [None, "admin", "member", "reviewer", "publisher"])
async def test_private_admission_before_any_request_body_or_source_lookup(client, db_session, monkeypatch, identity):
    context, _, _ = await setup(db_session)
    await db_session.commit()

    async def no_body(*a, **k):
        pytest.fail("unadmitted input parsing")
    monkeypatch.setattr(router, "_body", no_body)
    headers = {} if identity is None else auth(context["actors"][identity])
    result = await client.post(BASE, content=b"PRIVATE", headers={**headers, "Content-Type": "application/json"})
    assert result.status_code == (401 if identity is None else 403), result.text
    private(result)


@pytest.mark.parametrize("change", [
    {"actor_user_id": "private"}, {"approved": True}, {"expected_request_sha256": "0" * 64},
    {"expected_requester_grant_id": str(uuid4())}, {"expected_curator_grant_id": str(uuid4())},
])
async def test_request_and_current_role_pins_are_independent(client, db_session, change):
    context, body, _ = await setup(db_session)
    await db_session.commit()
    result = await client.post(BASE, json={**body, **change}, headers=auth(context["actors"]["curator"]))
    assert result.status_code in {400, 403, 409}, result.text
    assert "private" not in result.text.lower()
    private(result)


@pytest.mark.parametrize("change", ["dataset", "release", "manifest", "binding", "purpose", "source_list"])
async def test_resealed_request_cannot_retarget_registered_input_inventory(client, db_session, change):
    context, body, _ = await setup(db_session)
    await db_session.commit()
    request = body["request"]
    if change in {"dataset", "release"}:
        request["dataset_id" if change == "dataset" else "base_release_id"] = str(uuid4())
    elif change == "manifest":
        request["input_pins"]["manifest_sha256"] = "0" * 64
    elif change == "binding":
        request["feature_binding_pins"] = [{"id": str(uuid4()), "record_sha256": "a" * 64}]
    elif change == "purpose":
        request["purpose"] = "public_predictions"
    else:
        request["sources"] = []
    body["expected_request_sha256"] = digest(request)
    result = await client.post(BASE, json=body, headers=auth(context["actors"]["curator"]))
    assert result.status_code in {400, 409}, result.text
    private(result)


@pytest.mark.parametrize("change", ["session", "admin", "active", "verified", "requester", "curator"])
async def test_account_and_role_changes_during_body_rechecked(client, db_session, monkeypatch, change):
    from services import research_publication
    context, body, membership = await setup(db_session)
    people = context["actors"]
    await db_session.commit()
    original = router._body

    async def changed(request):
        result = await original(request)
        if change in {"session", "admin", "active", "verified"}:
            values = {"session": {"session_version": 1}, "admin": {"is_admin": False},
                      "active": {"is_active": False}, "verified": {"email_verified": False}}[change]
            await db_session.execute(sa.update(User).where(User.id == people["curator"]).values(**values))
        elif change == "requester":
            await decide(db_session, arguments(people, user_id=str(people["curator"]), action="revoke",
                                               previous=membership["decision"]))
        else:
            await research_publication.revoke_role(db_session, actor_user_id=people["admin"],
                grant_id=people["grants"]["curator"], reason_code="synthetic_revoke", dry_run=False)
        await db_session.commit()
        return result
    monkeypatch.setattr(router, "_body", changed)
    result = await client.post(BASE, json=body, headers=auth(people["curator"]))
    assert result.status_code == 403, result.text
    private(result)


async def test_changed_live_material_is_disclosed_as_hold_not_silently_accepted(client, db_session):
    context, body, _ = await setup(db_session)
    material = context["fixture"]["material"]
    await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"), {"id": material})
    await db_session.commit()
    result = await client.post(BASE, json=body, headers=auth(context["actors"]["curator"]))
    assert result.status_code == 200, result.text
    report = result.json()
    assert "frozen_dependency_changed" in report["blockers"]
    assert "current_catalogue_or_scientific_hold" in report["blockers"]
    assert report["decision"] == "not_authorized"
    assert any(r["table"] == "materials" and r["frozen_row_changed"] for r in report["requirements"])


async def test_service_rejects_non_readonly_or_unbounded_session(db_session):
    context, body, _ = await setup(db_session)
    with pytest.raises(ValueError, match="readonly_snapshot"):
        await service.preflight_ml_use(db_session, actor_user_id=context["actors"]["curator"], **body)


async def test_independent_feature_flag_defaults_off(client, db_session, monkeypatch):
    context, body, _ = await setup(db_session)
    await db_session.commit()
    monkeypatch.delenv("ML_USE_GOVERNANCE_ENABLED")
    get_settings.cache_clear()
    result = await client.post(BASE, json=body, headers=auth(context["actors"]["curator"]))
    assert result.status_code == 404
    private(result)


@pytest.mark.parametrize("raw,kind,status", [(b'[]', "application/json", 400),
    (b'{"request":{},"request":{}}', "application/json", 400), (b'{"request":NaN}', "application/json", 400),
    (b'{}', "text/plain", 415), (b' ' * (router.MAX_BYTES + 2049), "application/json", 413)])
async def test_strict_bounded_request_parsing(client, db_session, raw, kind, status):
    context, _, _ = await setup(db_session)
    await db_session.commit()
    result = await client.post(BASE, content=raw, headers={**auth(context["actors"]["curator"]), "Content-Type": kind})
    assert result.status_code == status, result.text
    private(result)


async def test_runtime_failure_and_capacity_release_remain_private(client, db_session, monkeypatch):
    context, body, _ = await setup(db_session)
    await db_session.commit()

    async def fail(*a, **k):
        raise RuntimeError("PRIVATE-DRIVER-TEXT")
    with monkeypatch.context() as patch:
        patch.setattr(router, "preflight_ml_use", fail)
        result = await client.post(BASE, json=body, headers=auth(context["actors"]["curator"]))
    assert result.status_code == 503 and "PRIVATE" not in result.text
    private(result)
    assert router._slots.acquire(blocking=False) and router._slots.acquire(blocking=False)
    try:
        busy = await client.get(BASE + "/access", headers=auth(context["actors"]["curator"]))
        assert busy.status_code == 503
        private(busy)
    finally:
        router._slots.release()
        router._slots.release()


async def test_request_snapshot_cannot_be_mutated_during_first_await(db_session, monkeypatch):
    context, body, _ = await setup(db_session)
    await db_session.commit()
    await db_session.execute(sa.text("SET TRANSACTION READ ONLY"))
    await db_session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    original = deepcopy(body["request"])
    actual = service.admission

    async def changed(*a, **k):
        body["request"]["purpose"] = "unapproved_mutation"
        return await actual(*a, **k)
    monkeypatch.setattr(service, "admission", changed)
    report = await service.preflight_ml_use(db_session, actor_user_id=context["actors"]["curator"], **body)
    assert report["purpose"] == PURPOSE and report["request_sha256"] == digest(original)
