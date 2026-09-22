"""Real JWT/DB-grant admission on every legacy raw research read surface.

The global test client is intentionally anonymous. Scientific-content suites
opt into a separate real-operator fixture; none of these tests override auth.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from config import get_settings
from models.db import ApiKey, MlDatasetSnapshot, SourceSnapshot, User, get_session_factory
from routers import ml_foundation
from services import auth_service
from services.session_config import build_browser_session_config
from tests.research_access_helpers import research_operator, research_user, revoke_research_grant
from tests.test_ml_claim_visibility import _seed


@pytest_asyncio.fixture
async def raw_research_paths(db_session):
    material, claim, _, work = await _seed(db_session, validity="pending")
    work.identity_metadata = {"private_marker": "PRIVATE-ML07-WORK"}
    source = await db_session.get(SourceSnapshot, claim.source_snapshot_id)
    source.snapshot_metadata = {"private_marker": "PRIVATE-ML07-SOURCE"}
    snapshot = MlDatasetSnapshot(
        id=uuid4(), source_snapshot_id=source.id,
        name="Synthetic private ML07 dataset", version=uuid4().hex,
        status="building", label_policy_version="synthetic/1",
        feature_schema_version="synthetic/1", split_ruleset_version="synthetic/1",
        filters={"private_marker": "PRIVATE-ML07-FILTER"},
        data_card_uri="https://private.example.test/ML07-DATA-CARD",
    )
    db_session.add(snapshot)
    await db_session.commit()
    return (
        f"/v1/claims?material_id={material.id}&include_pending=true&include_retracted=true",
        f"/v1/claims/{claim.id}",
        f"/v1/materials/{material.id}/claims?include_pending=true&include_retracted=true",
        f"/v1/works/{work.id}",
        "/v1/ml/source-snapshots?include_unfrozen=true",
        "/v1/ml/snapshots?include_unfrozen=true",
        f"/v1/ml/snapshots/{snapshot.id}/manifest",
    )


def assert_private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["anonymous", "member", "site_admin", "site_reviewer", "self_declared_role"])
async def test_global_enabled_flag_never_authorizes_raw_research_reads(client, raw_research_paths, identity):
    assert get_settings().ml_foundation_public_enabled is True
    if identity == "anonymous":
        headers = {}
    else:
        changes = {
            "site_admin": {"is_admin": True},
            "site_reviewer": {"is_reviewer": True},
            "self_declared_role": {"profile": {"research_role": "publisher"}, "scopes": ["research:admin"]},
        }.get(identity, {})
        headers = (await research_user(**changes))["headers"]
    for path in raw_research_paths:
        response = await client.get(path, headers=headers)
        assert response.status_code == (401 if identity == "anonymous" else 403), (path, response.text)
        assert "PRIVATE-ML07" not in response.text
        assert "DATA-CARD" not in response.text
        assert_private(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["curator", "reviewer", "publisher"])
async def test_explicit_live_research_role_allows_internal_draft_inspection(client, raw_research_paths, role):
    operator = await research_operator(role=role)
    for path in raw_research_paths:
        response = await client.get(path, headers={**operator["headers"], "If-None-Match": "*"})
        assert response.status_code == 200, (path, response.text)
        assert_private(response)
    manifest = (await client.get(raw_research_paths[-1], headers=operator["headers"])).json()
    assert manifest["status"] == "building"


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["anonymous", "operator"])
async def test_legacy_kill_switch_still_hides_every_raw_route(client, raw_research_paths, identity, monkeypatch):
    headers = (await research_operator())["headers"] if identity == "operator" else {}
    monkeypatch.setenv("ML_FOUNDATION_PUBLIC_ENABLED", "false")
    get_settings.cache_clear()
    try:
        for path in raw_research_paths:
            response = await client.get(path, headers=headers)
            assert response.status_code == 404
            assert response.json()["detail"] == "Not found"
            assert response.json()["error_code"] == "not_found"
            assert_private(response)
    finally:
        monkeypatch.setenv("ML_FOUNDATION_PUBLIC_ENABLED", "true")
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_revoked_role_is_rechecked_before_conditional_and_direct_reads(client, raw_research_paths):
    operator = await research_operator()
    assert (await client.get(raw_research_paths[-1], headers=operator["headers"])).status_code == 200
    await revoke_research_grant(grant_id=operator["grant_id"], revoked_by=operator["grantor_id"])
    for path in raw_research_paths:
        response = await client.get(path, headers={**operator["headers"], "If-None-Match": "*"})
        assert response.status_code == 403
        assert_private(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("change, expected", [({"is_active": False}, 401), ({"email_verified": False}, 403), ({"session_version": 1}, 401)])
async def test_account_authority_is_live_not_embedded_in_role_or_token(client, raw_research_paths, change, expected):
    operator = await research_operator()
    assert (await client.get(raw_research_paths[0], headers=operator["headers"])).status_code == 200
    async with get_session_factory()() as db:
        await db.execute(update(User).where(User.id == operator["id"]).values(**change))
        await db.commit()
    for path in raw_research_paths:
        response = await client.get(path, headers=operator["headers"])
        assert response.status_code == expected, response.text
        assert_private(response)


@pytest.mark.asyncio
async def test_api_key_alone_is_not_a_research_operator_session(client, raw_research_paths):
    operator = await research_operator()
    key = "sclib_test_research_" + uuid4().hex
    async with get_session_factory()() as db:
        db.add(ApiKey(user_id=operator["id"], key_hash=auth_service.hash_api_key(key), key_prefix=key[:12]))
        await db.commit()
    for path in raw_research_paths:
        response = await client.get(path, headers={"X-API-Key": key})
        assert response.status_code == 401
        assert_private(response)


@pytest.mark.asyncio
async def test_invalid_bearer_never_falls_back_to_guest_research_access(client, raw_research_paths):
    for path in raw_research_paths:
        response = await client.get(path, headers={"Authorization": "Bearer invalid.synthetic.token"})
        assert response.status_code == 401
        assert_private(response)


@pytest.mark.asyncio
async def test_browser_session_requires_the_same_live_research_grant(client, raw_research_paths):
    operator = await research_operator()
    settings = get_settings()
    cookie = build_browser_session_config(settings.environment, settings.jwt_expiry_hours * 3600)
    client.cookies.set(cookie.cookie_name, operator["token"])
    assert (await client.get(raw_research_paths[-1])).status_code == 200
    await revoke_research_grant(grant_id=operator["grant_id"], revoked_by=operator["grantor_id"])
    response = await client.get(raw_research_paths[-1])
    assert response.status_code == 403
    assert_private(response)


@pytest.mark.asyncio
async def test_registry_failure_is_closed_and_never_exposes_driver_details(client, raw_research_paths, monkeypatch):
    operator = await research_operator()

    async def unavailable(_db, _user_id):
        raise SQLAlchemyError("PRIVATE-ML07-DATABASE-CREDENTIALS")

    monkeypatch.setattr(ml_foundation, "require_research_operator", unavailable)
    for path in raw_research_paths:
        response = await client.get(path, headers=operator["headers"])
        assert response.status_code == 503
        assert response.json()["detail"] == "Research access registry unavailable"
        assert response.json()["error_code"] == "service_unavailable"
        assert "PRIVATE-ML07" not in response.text
        assert_private(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("path, expected", [
    ("/v1/claims/not-a-uuid", 422),
    ("/v1/works/not-a-uuid", 422),
    ("/v1/ml/snapshots/not-a-uuid/manifest", 422),
    (f"/v1/claims/{uuid4()}", 404),
    (f"/v1/works/{uuid4()}", 404),
    (f"/v1/ml/snapshots/{uuid4()}/manifest", 404),
])
async def test_authenticated_validation_and_missing_errors_never_cache(client, path, expected):
    operator = await research_operator()
    response = await client.get(path, headers=operator["headers"])
    assert response.status_code == expected
    assert_private(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/claims/not-a-uuid", "/v1/works/not-a-uuid", "/v1/ml/snapshots/not-a-uuid/manifest"])
async def test_authentication_precedes_identifier_validation(client, path):
    response = await client.get(path)
    assert response.status_code == 401
    assert_private(response)
