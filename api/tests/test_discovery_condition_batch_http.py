"""Actual owned HTTP/SQL condition batches; scientific fixtures are synthetic."""
import json
from pathlib import Path
import tempfile

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import Base, get_engine
from services import discovery_condition_batch_contract as contract
from services import discovery_condition_batches as service
from services.research_release_manifest import canonical
from services.session_config import build_browser_session_config
from tests.research_access_helpers import research_operator, research_user, revoke_research_grant
from tests.test_discovery_condition_batch_sql import AXES
from tests.test_discovery_condition_batches import retain_request, child_request
from tests.test_discovery_design_contract import operation
from tests.test_discovery_design_http import private
from tests.test_research_freeze import db_session, seed

PREFIX = "/v1/research/discovery-condition-batches"
DESIGNS = "/v1/research/discovery-designs"


@pytest.fixture
def batch_interface(monkeypatch):
    monkeypatch.setenv("DISCOVERY_CONDITION_BATCHES_ENABLED", "true")
    monkeypatch.setenv("DISCOVERY_DESIGNS_ENABLED", "true")
    monkeypatch.setenv("SOURCE_PROPERTY_PENDING_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def http_parent(client, db, actor):
    fixture = await seed(db)
    await db.commit()
    ctx = await client.get(DESIGNS + "/context", params={"kind": "native_property", "material_id": fixture["material"],
        "property_id": str(fixture["children"]["property"])}, headers=actor["headers"])
    assert ctx.status_code == 200, ctx.text
    req = operation(baseline=ctx.json()["baseline"])
    preview = await client.post(DESIGNS + "/operations/preview", json={"request": req}, headers=actor["headers"])
    assert preview.status_code == 200, preview.text
    saved = await client.post(DESIGNS + "/operations/commit", json={"request": req,
        "expected_preview_sha256": preview.json()["preview_sha256"]}, headers=actor["headers"])
    assert saved.status_code == 200, saved.text
    cap = await client.get(DESIGNS + "/capabilities", headers=actor["headers"])
    page = await client.get(DESIGNS + "/designs", headers=actor["headers"])
    entry = page.json()["entries"][0]
    row = json.loads(saved.json()["receipt_canonical_json"])
    row.update(record_sha256=entry["record_sha256"], projection=entry["projection"])
    return row, {"capabilities": cap.json(), "context": ctx.json(), "request": req,
                 "preview": preview.json(), "commit": saved.json(), "page": page.json()}


@pytest.mark.asyncio
async def test_independent_default_off_curator_only_and_current_revocation(client, db_session, monkeypatch):
    monkeypatch.setenv("DISCOVERY_CONDITION_BATCHES_ENABLED", "false")
    get_settings.cache_clear()
    response = await client.get(PREFIX + "/capabilities")
    assert response.status_code == 404
    private(response)
    monkeypatch.setenv("DISCOVERY_CONDITION_BATCHES_ENABLED", "true")
    monkeypatch.setenv("DISCOVERY_DESIGNS_ENABLED", "false")
    get_settings.cache_clear()
    try:
        actor = await research_operator()
        reviewer, admin = await research_operator(role="reviewer"), await research_user(is_admin=True)
        for headers, expected in (({}, 401), (reviewer["headers"], 403), (admin["headers"], 403), (actor["headers"], 200)):
            response = await client.get(PREFIX + "/capabilities", headers=headers)
            assert response.status_code == expected, response.text
            private(response)
        assert response.json()["can_write"] and response.json()["operations"] == list(contract.OPERATIONS)
        await revoke_research_grant(grant_id=actor["grant_id"], revoked_by=actor["grantor_id"])
        assert (await client.get(PREFIX + "/batches", headers=actor["headers"])).status_code == 403
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_native_http_batch_child_preview_atomic_commit_original_export_and_wire(client, db_session, batch_interface):
    actor = await research_operator()
    parent, parent_wire = await http_parent(client, db_session, actor)
    cap = await client.get(PREFIX + "/capabilities", headers=actor["headers"])
    assert cap.status_code == 200, cap.text
    actor_pins = {key: cap.json()[key] for key in ("actor_user_id", "session_version", "curator_grant_id")}
    manifest = contract.build_manifest(parent, parent["projection"], actor_pins, AXES)
    req = retain_request(parent, manifest)
    before = await client.get(PREFIX + "/batches", headers=actor["headers"])
    preview = await client.post(PREFIX + "/operations/preview", json={"request": req}, headers=actor["headers"])
    assert preview.status_code == 200, preview.text
    assert (await client.get(PREFIX + "/batches", headers=actor["headers"])).json() == before.json()
    rejected = await client.post(PREFIX + "/operations/commit", json={"request": req,
        "expected_preview_sha256": "f"*64}, headers=actor["headers"])
    assert rejected.status_code == 409, rejected.text
    saved = await client.post(PREFIX + "/operations/commit", json={"request": req,
        "expected_preview_sha256": preview.json()["preview_sha256"]}, headers=actor["headers"])
    assert saved.status_code == 200, saved.text
    batch_id = saved.json()["batch_id"]
    outcome = await client.get(PREFIX + "/operations/outcome", params={"request_key": req["request_key"],
        "expected_request_sha256": saved.json()["request_sha256"]}, headers=actor["headers"])
    page = await client.get(PREFIX + "/batches", headers=actor["headers"])
    detail = await client.get(PREFIX + "/batches/"+batch_id, headers=actor["headers"])
    exported = await client.get(PREFIX + "/batches/"+batch_id+"/manifest", headers=actor["headers"])
    assert outcome.status_code == page.status_code == detail.status_code == exported.status_code == 200
    assert exported.content == canonical(manifest)
    assert exported.json()["batch_saved"] is False
    child_req = child_request(saved.json(), manifest["scenarios"][0])
    before_designs = await client.get(DESIGNS + "/designs", headers=actor["headers"])
    child_preview = await client.post(PREFIX + "/operations/preview", json={"request": child_req}, headers=actor["headers"])
    assert child_preview.status_code == 200, child_preview.text
    assert (await client.get(DESIGNS + "/designs", headers=actor["headers"])).json() == before_designs.json()
    assert (await client.get(PREFIX + "/batches/"+batch_id, headers=actor["headers"])).json() == detail.json()
    child_commit = await client.post(PREFIX + "/operations/commit", json={"request": child_req,
        "expected_preview_sha256": child_preview.json()["preview_sha256"]}, headers=actor["headers"])
    assert child_commit.status_code == 200, child_commit.text
    child_outcome = await client.get(PREFIX + "/operations/outcome", params={"request_key": child_req["request_key"],
        "expected_request_sha256": child_commit.json()["request_sha256"]}, headers=actor["headers"])
    linked_detail = await client.get(PREFIX + "/batches/"+batch_id, headers=actor["headers"])
    assert linked_detail.json()["scenarios"][0]["child"]["revision_id"] == child_commit.json()["child"]["receipt_id"]
    for response in (cap, preview, saved, outcome, page, detail, exported, child_preview, child_commit, child_outcome, linked_detail):
        private(response)
        assert "context_json" not in response.text and "literature_locator" not in response.text and '"values"' not in response.text
    other = await research_operator()
    for suffix in ("", "/manifest"):
        response = await client.get(PREFIX+"/batches/"+batch_id+suffix, headers=other["headers"])
        assert response.status_code == 404
        private(response)
    assert (await client.get(PREFIX + "/batches/"+batch_id+"?offset=8", headers=actor["headers"])).json()["scenarios"]
    wire = {"synthetic_native_fixture": True, "parent": parent_wire,
        "capabilities": cap.json(), "request": req, "manifest_canonical_json": exported.text,
        "preview": preview.json(), "commit": saved.json(), "outcome": outcome.json(),
        "page": page.json(), "detail": detail.json(), "child_request": child_req,
        "child_preview": child_preview.json(), "child_commit": child_commit.json(),
        "child_outcome": child_outcome.json(), "linked_detail": linked_detail.json()}
    destination = Path(tempfile.mkdtemp(prefix="sclib-condition-batch-native-wire-20261004-")) / "wire.json"
    destination.write_bytes(canonical(wire)); destination.chmod(0o600)
    print("Synthetic native condition batch wire:", destination)


@pytest.mark.asyncio
async def test_closed_bodies_query_bounds_and_browser_csrf(client, db_session, batch_interface):
    actor = await research_operator()
    for suffix in ("/batches?limit=9", "/batches?offset=1001", "/batches?limit=0"):
        response = await client.get(PREFIX + suffix, headers=actor["headers"])
        assert response.status_code == 400
        private(response)
    assert (await client.get(PREFIX + "/capabilities?x="+"a"*2050, headers=actor["headers"])).status_code == 413
    for body in ('{"request":{},"request":{}}', '{"request":{},"scientific_acceptance":true}'):
        response = await client.post(PREFIX + "/operations/preview", content=body,
            headers={**actor["headers"], "content-type": "application/json"})
        assert response.status_code == 400
        private(response)
    settings = get_settings()
    cookie = build_browser_session_config(settings.environment, settings.jwt_expiry_hours * 3600)
    client.cookies.set(cookie.cookie_name, actor["token"])
    try:
        response = await client.post(PREFIX + "/operations/preview", json={"request": {}})
        assert response.status_code == 403
        response = await client.post(PREFIX + "/operations/preview", json={"request": {}}, headers={"Origin": "https://untrusted.example"})
        assert response.status_code == 403
        private(response)
    finally:
        client.cookies.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["session", "research_integrity_epoch", "source_lifecycle_epoch", "research_publication_epoch"])
async def test_read_fresh_actor_and_each_epoch_fence_before_egress(client, db_session, batch_interface, monkeypatch, drift):
    actor = await research_operator()
    original = service.capabilities
    async def changed(db, *, actor_user_id):
        result = await original(db, actor_user_id=actor_user_id)
        async with AsyncSession(get_engine().execution_options(isolation_level="READ COMMITTED")) as fresh:
            async with fresh.begin():
                if drift == "session":
                    users = Base.metadata.tables["users"]
                    await fresh.execute(users.update().where(users.c.id == actor["id"]).values(session_version=users.c.session_version+1))
                else:
                    epoch = Base.metadata.tables[drift]
                    await fresh.execute(epoch.update().where(epoch.c.id == 1).values(epoch=epoch.c.epoch+1))
        return result
    monkeypatch.setattr(service, "capabilities", changed)
    response = await client.get(PREFIX + "/capabilities", headers=actor["headers"])
    assert response.status_code == 409, response.text
    private(response)
    assert "actor_user_id" not in response.text
