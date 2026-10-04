"""Actual private HTTP + PostgreSQL boundaries; scientific content is synthetic."""
import json
from pathlib import Path
import tempfile

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import Base, get_engine
from services import discovery_designs as service
from services.research_release_manifest import canonical
from services.session_config import build_browser_session_config
from tests.research_access_helpers import research_operator, research_user, revoke_research_grant
from tests.test_discovery_design_contract import operation
from tests.test_research_freeze import db_session, seed

PREFIX = "/v1/research/discovery-designs"


@pytest.fixture
def design_interface(monkeypatch):
    monkeypatch.setenv("DISCOVERY_DESIGNS_ENABLED", "true")
    monkeypatch.setenv("SOURCE_PROPERTY_PENDING_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_default_disabled_and_explicit_curator_only_http(client, db_session, monkeypatch):
    response = await client.get(PREFIX + "/capabilities")
    assert response.status_code == 404
    private(response)
    monkeypatch.setenv("DISCOVERY_DESIGNS_ENABLED", "true")
    get_settings.cache_clear()
    try:
        actor, reviewer, admin = await research_operator(), await research_operator(role="reviewer"), await research_user(is_admin=True)
        for headers, status in (({}, 401), (reviewer["headers"], 403), (admin["headers"], 403), (actor["headers"], 200)):
            response = await client.get(PREFIX + "/capabilities", headers=headers)
            assert response.status_code == status, response.text
            private(response)
        await revoke_research_grant(grant_id=actor["grant_id"], revoked_by=actor["grantor_id"])
        assert (await client.get(PREFIX + "/capabilities", headers=actor["headers"])).status_code == 403
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_actual_http_preview_commit_outcome_history_and_native_source_wire(client, db_session, design_interface):
    actor = await research_operator()
    native = await seed(db_session)
    await db_session.commit()
    cap = await client.get(PREFIX + "/capabilities", headers=actor["headers"])
    assert cap.status_code == 200, cap.text
    ctx = await client.get(PREFIX + "/context", params={"kind": "native_property", "material_id": native["material"], "property_id": str(native["children"]["property"])}, headers=actor["headers"])
    assert ctx.status_code == 200, ctx.text
    assert ctx.json()["projection"]["values"][0]["value"] == 0
    req = operation(baseline=ctx.json()["baseline"])
    before = await client.get(PREFIX + "/designs", headers=actor["headers"])
    preview = await client.post(PREFIX + "/operations/preview", json={"request": req}, headers=actor["headers"])
    assert preview.status_code == 200, preview.text
    assert (await client.get(PREFIX + "/designs", headers=actor["headers"])).json() == before.json()
    rejected = await client.post(PREFIX + "/operations/commit", json={"request": req, "expected_preview_sha256": "a" * 64}, headers=actor["headers"])
    assert rejected.status_code == 409
    saved = await client.post(PREFIX + "/operations/commit", json={"request": req, "expected_preview_sha256": preview.json()["preview_sha256"]}, headers=actor["headers"])
    assert saved.status_code == 200, saved.text
    outcome = await client.get(PREFIX + "/operations/outcome", params={"request_key": req["request_key"], "expected_request_sha256": saved.json()["request_sha256"]}, headers=actor["headers"])
    assert outcome.status_code == 200 and outcome.json()["replayed"]
    page = await client.get(PREFIX + "/designs", headers=actor["headers"])
    detail = await client.get(PREFIX + "/designs/" + saved.json()["design_id"], headers=actor["headers"])
    assert page.status_code == detail.status_code == 200
    for response in (cap, ctx, preview, saved, outcome, page, detail):
        private(response)
        assert "context_json" not in response.text and "literature_locator" not in response.text
    wire = {"synthetic_native_fixture": True, "capabilities": cap.json(), "context": ctx.json(), "request": req, "preview": preview.json(), "commit": saved.json(), "outcome": outcome.json(), "page": page.json(), "detail": detail.json()}
    # A finite source-free synthetic SQL/HTTP fixture for independent TS replay.
    destination = Path(tempfile.mkdtemp(prefix="sclib-discovery-designs-native-wire-20261004-")) / "wire.json"
    destination.write_bytes(canonical(wire))
    destination.chmod(0o600)
    print("Synthetic native Discovery wire:", destination)
    other = await research_operator()
    assert (await client.get(PREFIX + "/designs/" + saved.json()["design_id"], headers=other["headers"])).status_code == 404


@pytest.mark.asyncio
async def test_closed_body_duplicate_keys_query_bounds_and_cookie_csrf(client, db_session, design_interface):
    actor = await research_operator()
    assert (await client.get(PREFIX + "/designs?limit=9", headers=actor["headers"])).status_code == 400
    assert (await client.get(PREFIX + "/capabilities?x=" + "a" * 2050, headers=actor["headers"])).status_code == 413
    for body in ('{"request":{},"request":{}}', '{"request":{},"scientific_acceptance":true}'):
        response = await client.post(PREFIX + "/operations/preview", content=body, headers={**actor["headers"], "content-type": "application/json"})
        assert response.status_code == 400
        private(response)
    settings = get_settings()
    cookie = build_browser_session_config(settings.environment, settings.jwt_expiry_hours * 3600)
    client.cookies.set(cookie.cookie_name, actor["token"])
    try:
        response = await client.post(PREFIX + "/operations/preview", json={"request": operation()})
        assert response.status_code == 403
        response = await client.post(PREFIX + "/operations/preview", json={"request": operation()}, headers={"Origin": "https://untrusted.example"})
        assert response.status_code == 403
        private(response)
    finally:
        client.cookies.clear()


@pytest.mark.asyncio
async def test_private_read_detects_session_drift_before_egress(client, db_session, design_interface, monkeypatch):
    actor = await research_operator()
    original = service.capabilities

    async def drift(db, *, actor_user_id):
        result = await original(db, actor_user_id=actor_user_id)
        async with AsyncSession(get_engine().execution_options(isolation_level="READ COMMITTED")) as fresh:
            async with fresh.begin():
                users = Base.metadata.tables["users"]
                await fresh.execute(users.update().where(users.c.id == actor["id"]).values(session_version=users.c.session_version + 1))
        return result

    monkeypatch.setattr(service, "capabilities", drift)
    response = await client.get(PREFIX + "/capabilities", headers=actor["headers"])
    assert response.status_code == 409, response.text
    private(response)
    assert "actor_user_id" not in response.text
