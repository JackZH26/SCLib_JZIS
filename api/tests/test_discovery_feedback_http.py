"""Owned authenticated HTTP/SQL evidence flow; no production science attestation."""
import json
import tempfile
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import Base, get_engine
from services import discovery_feedback as service
from services import discovery_feedback_contract as contract
from services.research_release_manifest import canonical
from services.session_config import build_browser_session_config
from tests.research_access_helpers import research_operator, research_user, revoke_research_grant
from tests.test_discovery_design_contract import operation as design_operation
from tests.test_discovery_design_http import private
from tests.test_discovery_feedback import feedback_case, return_request
from tests.test_research_freeze import db_session as db_session

PREFIX = "/v1/research/discovery-feedback"
DESIGNS = "/v1/research/discovery-designs"


@pytest.fixture
def feedback_interface(monkeypatch):
    monkeypatch.setenv("DISCOVERY_FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("DISCOVERY_DESIGNS_ENABLED", "true")
    monkeypatch.setenv("DISCOVERY_CONDITION_BATCHES_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_independent_default_off_explicit_curator_and_live_revocation(client, db_session, monkeypatch):
    monkeypatch.setenv("DISCOVERY_FEEDBACK_ENABLED", "false")
    get_settings.cache_clear()
    response = await client.get(PREFIX + "/capabilities")
    assert response.status_code == 404
    private(response)
    monkeypatch.setenv("DISCOVERY_FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("DISCOVERY_DESIGNS_ENABLED", "false")
    get_settings.cache_clear()
    try:
        actor = await research_operator()
        reviewer, admin = await research_operator(role="reviewer"), await research_user(is_admin=True)
        for headers, expected in (({}, 401), (reviewer["headers"], 403), (admin["headers"], 403), (actor["headers"], 200)):
            response = await client.get(PREFIX + "/capabilities", headers=headers)
            assert response.status_code == expected, response.text
            private(response)
        assert response.json()["operations"] == list(contract.OPERATIONS)
        assert response.json()["baseline_kinds"] == ["retained_result"]
        assert response.json()["action_kinds"] == ["source_review"]
        await revoke_research_grant(grant_id=actor["grant_id"], revoked_by=actor["grantor_id"])
        assert (await client.get(PREFIX + "/capabilities", headers=actor["headers"])).status_code == 403
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_http_return_decision_follow_up_history_original_outcome_and_wire(client, db_session, feedback_interface):
    actor, material, paper, parent, _ = await feedback_case(db_session)
    await db_session.commit()
    cap = await client.get(PREFIX + "/capabilities", headers=actor["headers"])
    assert cap.status_code == 200, cap.text
    params = {"design_id": parent["design_id"], "revision_id": parent["receipt_id"],
              "record_sha256": parent["receipt_sha256"], "material_id": material, "record_index": 1}
    ctx = await client.get(PREFIX + "/context", params=params, headers=actor["headers"])
    assert ctx.status_code == 200, ctx.text
    assert ctx.json()["projection"]["record"]["tc_type"] == "zero_resistance"
    assert ctx.json()["projection"]["record"]["measurement"] == "resistivity"
    assert ctx.json()["projection"]["record"]["hc2_conditions"] == "0 K"
    req = return_request(ctx.json())
    empty = await client.get(PREFIX + "/designs/" + parent["design_id"] + "/returns", headers=actor["headers"])
    assert empty.status_code == 200 and empty.json()["total"] == 0
    preview = await client.post(PREFIX + "/operations/preview", json={"request": req}, headers=actor["headers"])
    assert preview.status_code == 200, preview.text
    assert (await client.get(PREFIX + "/designs/" + parent["design_id"] + "/returns", headers=actor["headers"])).json() == empty.json()
    rejected = await client.post(PREFIX + "/operations/commit", json={"request": req, "expected_preview_sha256": "a" * 64}, headers=actor["headers"])
    assert rejected.status_code == 409
    saved = await client.post(PREFIX + "/operations/commit", json={"request": req,
        "expected_preview_sha256": preview.json()["preview_sha256"]}, headers=actor["headers"])
    assert saved.status_code == 200, saved.text
    out = await client.get(PREFIX + "/operations/outcome", params={"request_key": req["request_key"],
        "expected_request_sha256": saved.json()["request_sha256"]}, headers=actor["headers"])
    assert out.status_code == 200 and out.json()["replayed"]
    baseline = json.loads(parent["receipt_canonical_json"])["baseline"]
    child_req = design_operation(baseline=baseline, parent={key: ctx.json()["design"][key]
                                   for key in ("design_id", "revision_id", "record_sha256")})
    child_preview = await client.post(DESIGNS + "/operations/preview", json={"request": child_req}, headers=actor["headers"])
    assert child_preview.status_code == 200, child_preview.text
    child_saved = await client.post(DESIGNS + "/operations/commit", json={"request": child_req,
        "expected_preview_sha256": child_preview.json()["preview_sha256"]}, headers=actor["headers"])
    assert child_saved.status_code == 200, child_saved.text
    link_req = {"version": contract.REQUEST_VERSION, "request_key": "feedback-http-link:" + saved.json()["receipt_id"],
        "operation": "link_follow_up", "payload": {"feedback": {"id": saved.json()["feedback_id"],
        "record_sha256": saved.json()["feedback_record_sha256"]}, "child": {"design_id": child_saved.json()["design_id"],
        "revision_id": child_saved.json()["receipt_id"], "record_sha256": child_saved.json()["receipt_sha256"]}}}
    link_preview = await client.post(PREFIX + "/operations/preview", json={"request": link_req}, headers=actor["headers"])
    assert link_preview.status_code == 200, link_preview.text
    linked = await client.post(PREFIX + "/operations/commit", json={"request": link_req,
        "expected_preview_sha256": link_preview.json()["preview_sha256"]}, headers=actor["headers"])
    assert linked.status_code == 200, linked.text
    link_outcome = await client.get(PREFIX + "/operations/outcome", params={"request_key": link_req["request_key"],
        "expected_request_sha256": linked.json()["request_sha256"]}, headers=actor["headers"])
    assert link_outcome.status_code == 200 and link_outcome.json()["receipt_sha256"] == linked.json()["receipt_sha256"]
    page = await client.get(PREFIX + "/designs/" + parent["design_id"] + "/returns", headers=actor["headers"])
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 1 and page.json()["entries"][0]["follow_ups"][0]["child"] == link_req["payload"]["child"]
    for response in (cap, ctx, preview, saved, out, link_preview, linked, link_outcome, page):
        private(response)
        assert "DO NOT RETURN SOURCE" not in response.text
        assert "context_json" not in response.text and '"scientific_acceptance":true' not in response.text
    foreign = await research_operator()
    assert (await client.get(PREFIX + "/designs/" + parent["design_id"] + "/returns", headers=foreign["headers"])).status_code == 404
    parent_page = await client.get(DESIGNS + "/designs/" + parent["design_id"], headers=actor["headers"])
    # Finite owned-local native SQL/HTTP bytes for independent client replay;
    # source values are reconstructed retained facts, not production subject IDs.
    wire = {"reconstructed_retained_fixture": True, "no_human_scientific_review": True,
        "capabilities": cap.json(), "context": ctx.json(), "request": req, "preview": preview.json(),
        "commit": saved.json(), "outcome": out.json(), "page": page.json(), "parent": parent_page.json(),
        "child_request": child_req, "child_preview": child_preview.json(), "child_commit": child_saved.json(),
        "link_request": link_req, "link_preview": link_preview.json(), "link_commit": linked.json(), "link_outcome": link_outcome.json()}
    destination = Path(tempfile.mkdtemp(prefix="sclib-discovery-feedback-native-wire-20261004-")) / "wire.json"
    destination.parent.chmod(0o700)
    destination.write_bytes(canonical(wire))
    destination.chmod(0o600)
    print("Owned-local Discovery feedback wire:", destination)


@pytest.mark.asyncio
async def test_closed_body_query_bounds_and_cookie_csrf(client, db_session, feedback_interface):
    actor, _, _, parent, ctx = await feedback_case(db_session)
    await db_session.commit()
    for body in ('{"request":{},"request":{}}', '{"request":{},"experiment_executed":true}'):
        response = await client.post(PREFIX + "/operations/preview", content=body,
                                     headers={**actor["headers"], "content-type": "application/json"})
        assert response.status_code == 400
        private(response)
    assert (await client.get(PREFIX + "/designs/" + parent["design_id"] + "/returns?limit=9", headers=actor["headers"])).status_code == 400
    assert (await client.get(PREFIX + "/capabilities?x=" + "a" * 2050, headers=actor["headers"])).status_code == 413
    settings = get_settings()
    cookie = build_browser_session_config(settings.environment, settings.jwt_expiry_hours * 3600)
    client.cookies.set(cookie.cookie_name, actor["token"])
    try:
        response = await client.post(PREFIX + "/operations/preview", json={"request": return_request(ctx)})
        assert response.status_code == 403
        private(response)
    finally:
        client.cookies.clear()


@pytest.mark.asyncio
async def test_private_read_detects_session_drift_before_egress(client, db_session, feedback_interface, monkeypatch):
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
