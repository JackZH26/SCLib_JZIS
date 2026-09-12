"""Synthetic ML membership governance on guarded native services, no ML rights."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from config import allowed_browser_origins, get_settings
from models.db import ApiKey, Base, User, get_engine
from models.ml_use_roles_v1 import ROLES, TABLE
from routers import ml_use_governance as router
from services import auth_service
from services import ml_use_access as service
from services.ml_baseline_rehearsal import run_baseline_dataset
from services.research_access import ResearchAccessDenied
from services.research_audit_retention import has_research_audit_references
from services.research_release_manifest import digest
from services.session_config import build_browser_session_config
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state
from tests.test_research_publication import actors

BASE = "/v1/ml/use"


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv("ML_USE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def arguments(people, *, role="requester", action="grant", previous=None, **changes):
    return {"actor_user_id": people["admin"], "user_id": str(people["member"]),
            "role": role, "action": action, "request_key": "synthetic-" + uuid4().hex,
            "reason_code": "synthetic_membership_only", "expected_head_id": None if previous is None else previous["id"],
            "expected_head_sha256": None if previous is None else previous["record_sha256"], **changes}


def body(args, *, preview=None, **changes):
    value = {k: v for k, v in args.items() if k != "actor_user_id"}
    if preview is not None:
        value.update(expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    return {**value, **changes}


def private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "etag" not in response.headers


def no_authority(value):
    assert value["training_execution"] == "disabled"
    for key in ("data_access_granted", "source_permission_granted", "run_authorization_granted", *service.AUTHORITY):
        assert value[key] is False


async def decide(db, args):
    preview = await service.decide_ml_role(db, **args)
    assert preview["decision"] is None and preview["committed"] is False
    result = await service.decide_ml_role(db, **args, dry_run=False,
                                          expected_intent_sha256=preview["intent_sha256"])
    assert result["committed"] is False  # the service never commits its caller
    no_authority(result)
    return result


async def http_decide(client, args):
    preview = await client.post(BASE + "/roles", json=body(args), headers=auth(args["actor_user_id"]))
    assert preview.status_code == 200, preview.text
    assert not preview.json()["committed"] and preview.json()["result"]["decision"] is None
    committed = await client.post(BASE + "/roles", json=body(args, preview=preview.json()["result"]),
                                  headers=auth(args["actor_user_id"]))
    assert committed.status_code == 200 and committed.json()["committed"], committed.text
    private(preview)
    private(committed)
    return preview.json()["result"], committed.json()["result"]


async def test_native_preview_commit_revoke_regrant_and_exact_head_binding(db_session):
    people = await actors(db_session)
    assert not await has_research_audit_references(db_session, people["member"])
    args = arguments(people)
    before = await state(db_session)
    preview = await service.decide_ml_role(db_session, **args)
    assert await state(db_session) == before
    no_authority(preview)
    first = await decide(db_session, args)
    head = first["decision"]
    assert (await service.active_ml_role(db_session, people["member"], role="requester", grant_id=head["id"]))["id"] == UUID(head["id"])
    stable = await state(db_session)
    repeated = await service.decide_ml_role(db_session, **args, dry_run=False,
                                           expected_intent_sha256=first["intent_sha256"])
    assert repeated["replayed"] and repeated["decision"] == head
    assert await state(db_session) == stable
    revoked = await decide(db_session, arguments(people, action="revoke", previous=head))
    with pytest.raises(ResearchAccessDenied):
        await service.active_ml_role(db_session, people["member"], role="requester")
    second = await decide(db_session, arguments(people, previous=revoked["decision"]))
    assert second["decision"]["id"] != head["id"]
    with pytest.raises(ResearchAccessDenied):
        await service.active_ml_role(db_session, people["member"], role="requester", grant_id=head["id"])
    assert (await service.active_ml_role(db_session, people["member"], role="requester"))["id"] == UUID(second["decision"]["id"])
    for user_id in (people["admin"], people["member"]):
        assert await has_research_audit_references(db_session, user_id)


@pytest.mark.parametrize("legacy_role", ["admin", "curator", "reviewer", "publisher", "member"])
async def test_no_legacy_identity_grants_ml_membership(db_session, legacy_role):
    people = await actors(db_session)
    for role in ROLES:
        with pytest.raises(ResearchAccessDenied):
            await service.active_ml_role(db_session, people[legacy_role], role=role)


async def test_authenticated_http_history_recovery_is_not_current_permission(client, db_session):
    people = await actors(db_session)
    await db_session.commit()
    args = arguments(people)
    before = await state(db_session)
    await db_session.rollback()
    response = await client.post(BASE + "/roles", json=body(args), headers=auth(people["admin"]))
    assert response.status_code == 200, response.text
    assert await state(db_session) == before
    await db_session.rollback()
    preview, first = await http_decide(client, args)
    for endpoint, actor in ((BASE + "/access", people["member"]),
                            (BASE + "/roles/users/" + str(people["member"]), people["admin"])):
        result = await client.get(endpoint, headers={**auth(actor), "If-None-Match": "*"})
        assert result.status_code == 200 and result.json()["active_roles"] == ["requester"], result.text
        no_authority(result.json())
        private(result)
    await http_decide(client, arguments(people, action="revoke", previous=first["decision"]))
    current = await client.get(BASE + "/access", headers=auth(people["member"]))
    assert current.status_code == 200 and current.json()["active_roles"] == []
    assert current.json()["heads"][0]["action"] == "revoke"
    stable = await state(db_session)
    await db_session.rollback()
    recovered = await client.get(BASE + "/roles/outcome", headers=auth(people["admin"]), params={
        "request_key": args["request_key"], "expected_intent_sha256": first["intent_sha256"]})
    assert recovered.status_code == 200 and recovered.json()["committed"], recovered.text
    assert recovered.json()["result"]["decision"] == first["decision"]
    replay = await client.post(BASE + "/roles", headers=auth(people["admin"]), json=body(args, preview=preview))
    assert replay.status_code == 200 and replay.json()["result"]["replayed"], replay.text
    assert await state(db_session) == stable
    for result in (current, recovered, replay):
        private(result)
        no_authority(result.json().get("result", result.json()))


@pytest.mark.parametrize("query", ["", "?request_key=private-incomplete", "?expected_intent_sha256=" + "a" * 64])
async def test_incomplete_outcome_query_is_private_bad_request(client, db_session, query):
    people = await actors(db_session)
    await db_session.commit()
    response = await client.get(BASE + "/roles/outcome" + query, headers=auth(people["admin"]))
    assert response.status_code == 400
    assert response.json()["detail"] == "ML role request rejected"
    assert response.json()["error_code"] == "bad_request" and response.json()["request_id"]
    assert set(response.json()) == {"detail", "error_code", "request_id"}
    assert "private-incomplete" not in response.text
    private(response)


@pytest.mark.parametrize("role", [None, "curator", "reviewer", "publisher", "member"])
async def test_admin_admission_before_body_or_other_user_lookup(client, db_session, monkeypatch, role):
    people = await actors(db_session)
    await db_session.commit()

    async def no_body(*_):
        pytest.fail("unadmitted user reached body")
    monkeypatch.setattr(router, "_body", no_body)
    headers = {} if role is None else auth(people[role])
    response = await client.post(BASE + "/roles", content=b"PRIVATE-NOT-JSON", headers={**headers,
        "Content-Length": "90000000", "Content-Type": "application/json"})
    assert response.status_code == (401 if role is None else 403), response.text
    private(response)
    for path in ("/roles/users/not-a-user", "/roles/outcome?request_key=absent&expected_intent_sha256=bad"):
        response = await client.get(BASE + path, headers=headers)
        assert response.status_code == (401 if role is None else 403), response.text
        private(response)


@pytest.mark.parametrize("change", [
    {"actor_user_id": "private"}, {"approved": True}, {"ml_training_approved": True},
    {"source_permission_granted": True}, {"role": "publisher"}, {"action": "train"},
    {"dry_run": "false"}, {"dry_run": False}, {"expected_head_id": str(uuid4())},
    {"expected_head_sha256": "a" * 64}, {"request_key": "a\n"}, {"reason_code": "a\n"},
])
async def test_closed_http_payload_cannot_assign_identity_or_training_authority(client, db_session, change):
    people = await actors(db_session)
    await db_session.commit()
    args = arguments(people)
    response = await client.post(BASE + "/roles", headers=auth(people["admin"]), json=body(args, **change))
    assert response.status_code == 400, response.text
    private(response)
    assert "private" not in response.text.lower()
    assert not (await db_session.execute(sa.select(Base.metadata.tables[TABLE]).where(
        Base.metadata.tables[TABLE].c.user_id == people["member"])) ).first()


@pytest.mark.parametrize("mode", ["intent", "reason", "target", "role", "stale_head"])
async def test_preview_pin_cannot_authorize_modified_or_stale_operation(client, db_session, mode):
    people = await actors(db_session)
    await db_session.commit()
    args = arguments(people)
    response = await client.post(BASE + "/roles", headers=auth(people["admin"]), json=body(args))
    assert response.status_code == 200
    request = body(args, preview=response.json()["result"])
    if mode == "intent":
        request["expected_intent_sha256"] = "0" * 64
    elif mode == "reason":
        request["reason_code"] = "changed_reason"
    elif mode == "target":
        request["user_id"] = str(people["curator"])
    elif mode == "role":
        request["role"] = "run_approver"
    else:
        await http_decide(client, arguments(people))
    denied = await client.post(BASE + "/roles", headers=auth(people["admin"]), json=request)
    assert denied.status_code == 409, denied.text
    private(denied)


@pytest.mark.parametrize("change", [{"is_active": False}, {"email_verified": False}])
async def test_target_account_hold_does_not_erase_history_and_revocation_remains_possible(client, db_session, change):
    people = await actors(db_session)
    await db_session.commit()
    _, first = await http_decide(client, arguments(people))
    await db_session.execute(sa.update(User).where(User.id == people["member"]).values(**change))
    await db_session.commit()
    info = await client.get(BASE + "/roles/users/" + str(people["member"]), headers=auth(people["admin"]))
    assert info.status_code == 200 and info.json()["active_roles"] == []
    assert info.json()["heads"][0]["id"] == first["decision"]["id"]
    await http_decide(client, arguments(people, action="revoke", previous=first["decision"]))
    denied = await client.get(BASE + "/access", headers=auth(people["member"]))
    assert denied.status_code in {401, 403}


async def test_ml_roles_cannot_unlock_raw_research_routes_or_dataset_training(client, db_session):
    people = await actors(db_session)
    await db_session.commit()
    for role in ROLES:
        await http_decide(client, arguments(people, role=role))
    info = await client.get(BASE + "/access", headers=auth(people["member"]))
    assert info.status_code == 200 and info.json()["active_roles"] == list(ROLES)
    no_authority(info.json())
    denied = await client.get("/v1/claims", headers=auth(people["member"]))
    assert denied.status_code == 403
    with pytest.raises(ValueError, match="ml_use_authorization_unavailable"):
        run_baseline_dataset({"roles": list(ROLES), "approved": True})


async def test_kill_switch_is_independent_and_default_disabled(client, db_session, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    monkeypatch.delenv("ML_USE_GOVERNANCE_ENABLED", raising=False)
    get_settings.cache_clear()
    assert get_settings().ml_use_governance_enabled is False
    for path in ("/access", "/roles/users/" + str(people["member"])):
        result = await client.get(BASE + path, headers=auth(people["admin"]))
        assert result.status_code == 404
        private(result)
    result = await client.post(BASE + "/roles", json=body(arguments(people)), headers=auth(people["admin"]))
    assert result.status_code == 404


@pytest.mark.parametrize("change", [{"session_version": 1}, {"is_admin": False},
                                    {"is_active": False}, {"email_verified": False}])
async def test_session_change_during_body_is_rechecked_under_final_fence(client, db_session, monkeypatch, change):
    people = await actors(db_session)
    await db_session.commit()
    original = router._body

    async def changed(request):
        result = await original(request)
        await db_session.execute(sa.update(User).where(User.id == people["admin"]).values(**change))
        await db_session.commit()
        return result
    monkeypatch.setattr(router, "_body", changed)
    result = await client.post(BASE + "/roles", headers=auth(people["admin"]), json=body(arguments(people)))
    assert result.status_code == 403
    private(result)


@pytest.mark.parametrize("raw,content_type,expected", [
    (b'{"role":"requester","role":"rights_reviewer"}', "application/json", 400),
    (b'{"value":NaN}', "application/json", 400),
    (b'[]', "application/json", 400),
    (b'{}', "text/plain", 415),
    (b' ' * 8193, "application/json", 413),
])
async def test_bounded_strict_request_capture_after_admin_admission(client, db_session, raw, content_type, expected):
    people = await actors(db_session)
    await db_session.commit()
    result = await client.post(BASE + "/roles", content=raw,
        headers={**auth(people["admin"]), "Content-Type": content_type})
    assert result.status_code == expected, result.text
    private(result)


async def test_missing_outcome_is_not_success_and_recovery_cannot_cross_actor(client, db_session):
    people = await actors(db_session)
    await db_session.execute(sa.update(User).where(User.id == people["publisher"]).values(is_admin=True))
    await db_session.commit()
    args = arguments(people)
    _, first = await http_decide(client, args)
    query = {"request_key": args["request_key"], "expected_intent_sha256": first["intent_sha256"]}
    response = await client.get(BASE + "/roles/outcome", headers=auth(people["publisher"]), params=query)
    assert response.status_code == 404
    private(response)
    wrong = await client.get(BASE + "/roles/outcome", headers=auth(people["admin"]),
                             params={**query, "expected_intent_sha256": "0" * 64})
    assert wrong.status_code == 409
    assert "committed" not in wrong.json()


async def test_authenticated_self_inspection_never_requires_or_infers_a_role(client, db_session):
    people = await actors(db_session)
    await db_session.commit()
    result = await client.get(BASE + "/access", headers=auth(people["member"]))
    assert result.status_code == 200 and result.json()["active_roles"] == []
    assert result.json()["heads"] == [] and not result.json()["can_administer_roles"]
    no_authority(result.json())
    private(result)


async def test_api_key_does_not_replace_administrator_jwt_session(client, db_session):
    people = await actors(db_session)
    key = "sclib_synthetic_" + uuid4().hex
    await db_session.execute(sa.insert(ApiKey).values(user_id=people["admin"],
        key_hash=auth_service.hash_api_key(key), key_prefix=key[:12]))
    await db_session.commit()
    result = await client.post(BASE + "/roles", headers={"X-API-Key": key}, json=body(arguments(people)))
    assert result.status_code == 401
    private(result)


async def test_cookie_origin_and_invalid_bearer_cannot_bypass_session_boundary(client, db_session):
    people = await actors(db_session)
    await db_session.commit()
    settings = get_settings()
    config = build_browser_session_config(settings.environment, settings.jwt_expiry_hours * 3600)
    token, _ = auth_service.create_access_token(people["admin"])
    client.cookies.set(config.cookie_name, token)
    try:
        info = await client.get(BASE + "/access")
        assert info.status_code == 200
        for headers, expected in (({}, 403), ({"Origin": "https://untrusted.invalid"}, 403),
                                  ({"Origin": allowed_browser_origins(settings)[0]}, 200)):
            result = await client.post(BASE + "/roles", json=body(arguments(people)), headers=headers)
            assert result.status_code == expected, result.text
            private(result)
        invalid = await client.get(BASE + "/access", headers={"Authorization": "Bearer invalid.synthetic"})
        assert invalid.status_code == 401
    finally:
        client.cookies.clear()


async def test_account_erasure_is_held_by_revoked_ml_membership_history(client, db_session):
    people = await actors(db_session)
    assert not await has_research_audit_references(db_session, people["member"])
    await db_session.commit()
    _, first = await http_decide(client, arguments(people))
    await http_decide(client, arguments(people, action="revoke", previous=first["decision"]))
    response = await client.delete("/v1/admin/users/" + str(people["member"]), headers=auth(people["admin"]))
    assert response.status_code == 409, response.text
    assert "immutable research audit history" in response.text
    assert await db_session.scalar(sa.select(User.id).where(User.id == people["member"])) == people["member"]


async def test_unavailable_registry_errors_do_not_disclose_driver_input(client, db_session, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()

    async def fail(*a, **k):
        raise SQLAlchemyError("PRIVATE-DRIVER-CREDENTIAL")
    monkeypatch.setattr(router, "inspect_ml_access", fail)
    result = await client.get(BASE + "/access", headers=auth(people["member"]))
    assert result.status_code == 503 and "PRIVATE" not in result.text
    private(result)


async def test_lost_commit_reply_recovers_same_historical_operation_without_duplicate(client, db_session, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    args = arguments(people)
    preview = await client.post(BASE + "/roles", headers=auth(people["admin"]), json=body(args))
    assert preview.status_code == 200
    operation, close = router.decide_ml_role, AsyncSessionTransaction.__aexit__

    async def marked(db, **kwargs):
        result = await operation(db, **kwargs)
        db.info["synthetic_lost_reply"] = True
        return result

    async def lost(self, *a):
        await close(self, *a)
        if not self.nested and self.session.info.get("synthetic_lost_reply"):
            raise SQLAlchemyError("PRIVATE-LOST-REPLY")

    with monkeypatch.context() as patch:
        patch.setattr(router, "decide_ml_role", marked)
        patch.setattr(AsyncSessionTransaction, "__aexit__", lost)
        response = await client.post(BASE + "/roles", headers=auth(people["admin"]),
                                     json=body(args, preview=preview.json()["result"]))
    assert response.status_code == 503 and response.headers["x-operation-state"] == "unknown", response.text
    assert "PRIVATE" not in response.text
    recovered = await client.get(BASE + "/roles/outcome", headers=auth(people["admin"]), params={
        "request_key": args["request_key"], "expected_intent_sha256": preview.json()["result"]["intent_sha256"]})
    assert recovered.status_code == 200 and recovered.json()["committed"], recovered.text
    relation = Base.metadata.tables[TABLE]
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(relation).where(
        relation.c.user_id == people["member"])) == 1


@pytest.mark.parametrize("mode", ["hash", "role", "version", "admin", "target", "root_revoke", "duplicate_root", "wrong_previous", "same_action"])
async def test_native_insert_guards_cannot_be_bypassed_with_resealed_service_values(db_session, mode):
    people = await actors(db_session)
    first = (await decide(db_session, arguments(people)))["decision"]
    relation = Base.metadata.tables[TABLE]
    value = {k: v for k, v in first.items() if k not in {"created_at", "record_sha256"}}
    value.update(id=str(uuid4()), request_key="other-" + uuid4().hex,
                 supersedes_id=first["id"], action="revoke")
    if mode == "role":
        value["role"] = "reviewer"
    elif mode == "version":
        value["version"] = "future-unapproved"
    elif mode == "admin":
        value["actor_user_id"] = str(people["reviewer"])
    elif mode == "target":
        value["user_id"] = str(people["curator"])
    elif mode == "root_revoke":
        value["supersedes_id"] = None
    elif mode == "duplicate_root":
        value.update(action="grant", supersedes_id=None)
    elif mode == "wrong_previous":
        value["supersedes_id"] = str(uuid4())
    elif mode == "same_action":
        value["action"] = "grant"
    value["record_sha256"] = "0" * 64 if mode == "hash" else digest(value)
    for key in ("id", "user_id", "actor_user_id", "supersedes_id"):
        value[key] = UUID(value[key]) if value[key] is not None else None
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(DBAPIError):
            await db_session.execute(relation.insert().values(**value))
        await savepoint.rollback()
    assert (await service.active_ml_role(db_session, people["member"], role="requester"))["id"] == UUID(first["id"])


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_role_history_is_append_only_even_after_revocation(db_session, operation):
    people = await actors(db_session)
    granted = (await decide(db_session, arguments(people)))["decision"]
    await decide(db_session, arguments(people, action="revoke", previous=granted))
    sql = {"UPDATE": f"UPDATE {TABLE} SET reason_code='changed' WHERE id=:id",
           "DELETE": f"DELETE FROM {TABLE} WHERE id=:id", "TRUNCATE": f"TRUNCATE {TABLE} CASCADE"}[operation]
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(DBAPIError):
            await db_session.execute(sa.text(sql), {"id": UUID(granted["id"])})
        await savepoint.rollback()


async def test_competing_writers_fail_closed_and_cannot_create_two_current_roots(db_session):
    people = await actors(db_session)
    await db_session.commit()
    args = arguments(people)
    preview = await service.decide_ml_role(db_session, **args)
    await db_session.rollback()
    await service.decide_ml_role(db_session, **args, dry_run=False, expected_intent_sha256=preview["intent_sha256"])
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    async with AsyncSession(engine) as rival:
        with pytest.raises(DBAPIError):
            await service.decide_ml_role(rival, **arguments(people))
        await rival.rollback()
        await db_session.commit()
        with pytest.raises(service.MlUseConflict):
            await service.decide_ml_role(rival, **arguments(people))
    assert (await service.active_ml_role(db_session, people["member"], role="requester"))["role"] == "requester"
