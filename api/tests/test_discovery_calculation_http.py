"""Authenticated local HTTP -> original bytes -> SQL -> native reconstruction."""
import asyncio
import hashlib
import json
import tempfile
import threading
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import Base, get_engine
from routers import discovery_calculations as route
from services import discovery_calculation_contract as contract
from services import discovery_calculations as service
from services.research_release_manifest import canonical, digest
from services.session_config import build_browser_session_config
from tests.research_access_helpers import research_operator, research_user, revoke_research_grant
from tests.test_discovery_calculations import case, saved, wire
from tests.test_discovery_design_http import private
from tests.test_discovery_designs import save
from tests.test_research_freeze import db_session as db_session

PREFIX = "/v1/research/discovery-calculations"


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("DISCOVERY_CALCULATIONS_ENABLED", "true")
    monkeypatch.setenv("DISCOVERY_DESIGNS_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_default_off_curator_only_revocation_and_auth_before_body(client, monkeypatch):
    monkeypatch.setenv("DISCOVERY_CALCULATIONS_ENABLED", "false")
    get_settings.cache_clear()
    r = await client.get(PREFIX + "/capabilities")
    assert r.status_code == 404
    private(r)
    monkeypatch.setenv("DISCOVERY_CALCULATIONS_ENABLED", "true")
    get_settings.cache_clear()
    try:
        actor = await research_operator()
        reviewer, admin = await research_operator(role="reviewer"), await research_user(is_admin=True)
        for headers, expected in (({}, 401), (reviewer["headers"], 403), (admin["headers"], 403), (actor["headers"], 200)):
            r = await client.get(PREFIX + "/capabilities", headers=headers)
            assert r.status_code == expected, r.text
            private(r)
        assert r.json()["action_kinds"] == ["calculation"]
        consumed = False
        async def forbidden_body(req):
            nonlocal consumed
            consumed = True
            raise AssertionError("Unauthenticated body was consumed")
        monkeypatch.setattr(route, "body_bytes", forbidden_body)
        r = await client.post(PREFIX + "/operations/preview", content=b"not json")
        assert r.status_code == 401 and not consumed
        await revoke_research_grant(grant_id=actor["grant_id"], revoked_by=actor["grantor_id"])
        assert (await client.get(PREFIX + "/capabilities", headers=actor["headers"])).status_code == 403
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_http_private_save_recover_report_and_exact_original_download(client, db_session, enabled):
    actor, parent, req, files, _, _ = await case(db_session)
    await db_session.commit()
    ctx = await client.get(PREFIX + "/designs/" + parent["design_id"] + "/context", headers=actor["headers"])
    assert ctx.status_code == 200 and ctx.json()["design"] == req["design"]
    body = wire(req, files)
    preview = await client.post(PREFIX + "/operations/preview", json=body, headers=actor["headers"])
    assert preview.status_code == 200, preview.text
    assert preview.json()["dry_run"] and not preview.json()["private_ledger_written"]
    assert (await client.get(PREFIX + "/designs/" + parent["design_id"] + "/returns", headers=actor["headers"])).json()["total"] == 0
    body["expected_preview_sha256"] = preview.json()["preview_sha256"]
    commit = await client.post(PREFIX + "/operations/commit", json=body, headers=actor["headers"])
    assert commit.status_code == 200, commit.text
    assert commit.json()["receipt_sha256"] == preview.json()["receipt_sha256"]
    private(commit)
    rid = commit.json()["receipt_id"]
    out = await client.get(PREFIX + "/operations/outcome", params={"request_key": req["request_key"],
        "expected_request_sha256": digest(req)}, headers=actor["headers"])
    assert out.status_code == 200 and out.json()["receipt_sha256"] == commit.json()["receipt_sha256"]
    detail = await client.get(PREFIX + "/returns/" + rid, headers=actor["headers"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["report"]["status"] == "scf_reported_converged"
    assert detail.json()["report"]["observations"]["total_energy"]["value"] == -31.19334546679567
    assert not detail.json()["candidate_source_association_verified"]
    assert hashlib.sha256(detail.json()["report_canonical_json"].encode()).hexdigest() == commit.json()["report_sha256"]
    assert json.loads(detail.json()["report_canonical_json"]) == detail.json()["report"]
    for i, raw in enumerate(files):
        r = await client.get(PREFIX + f"/returns/{rid}/files/{i}", headers=actor["headers"])
        assert r.status_code == 200 and r.content == raw
        assert r.headers["x-content-sha256"] == req["files"][i]["sha256"]
        private(r)
    other = await research_operator()
    for path in (f"/returns/{rid}", f"/returns/{rid}/files/0", f"/designs/{parent['design_id']}/returns"):
        r = await client.get(PREFIX + path, headers=other["headers"])
        assert r.status_code == 404
        assert "-31.193" not in r.text
    replay = await client.post(PREFIX + "/operations/commit", json=body, headers=actor["headers"])
    assert replay.status_code == 200 and replay.json()["replayed"]
    cap = await client.get(PREFIX + "/capabilities", headers=actor["headers"])
    design_cap = await client.get("/v1/research/discovery-designs/capabilities", headers=actor["headers"])
    parent_detail = await client.get("/v1/research/discovery-designs/designs/" + parent["design_id"], headers=actor["headers"])
    page = await client.get(PREFIX + "/designs/" + parent["design_id"] + "/returns", headers=actor["headers"])
    for response in (cap, design_cap, parent_detail, page):
        assert response.status_code == 200, response.text
        private(response)
    capture = {"synthetic_actors_and_upf_headers": True, "no_authenticated_execution": True,
        "design_capabilities": design_cap.json(), "parent": parent_detail.json(), "capabilities": cap.json(),
        "context": ctx.json(), "upload": wire(req, files), "preview": preview.json(), "commit": commit.json(),
        "outcome": out.json(), "detail": detail.json(), "page": page.json()}
    await save(db_session, actor, {"version": "discovery-design-operation/1.0.0", "request_key": "withdraw-native-capture:" + uuid4().hex,
        "operation": "withdraw", "payload": {"design_id": parent["design_id"], "predecessor": {"id": parent["receipt_id"],
        "record_sha256": parent["receipt_sha256"]}, "reason": "Synthetic plan withdrawn after original-byte replay"}})
    await db_session.commit()
    held = await client.get(PREFIX + "/returns/" + rid, headers=actor["headers"])
    assert held.status_code == 200 and not held.json()["eligibility"]["eligible"]
    assert held.json()["report"] is None and held.json()["report_canonical_json"] is None
    capture["held_detail"] = held.json()
    destination = Path(tempfile.mkdtemp(prefix="sclib-calculation-native-wire-20261005-")) / "wire.json"
    destination.parent.chmod(0o700)
    destination.write_bytes(canonical(capture))
    destination.chmod(0o600)
    print("Owned-local calculation wire:", destination)



@pytest.mark.asyncio
async def test_closed_payload_limits_cookie_csrf_and_noncanonical_bytes(client, db_session, enabled, monkeypatch):
    actor, _, req, files, _, _ = await case(db_session)
    await db_session.commit()
    for bad in ('{"request":{},"request":{}}', '{"report":{"accepted":true}}'):
        r = await client.post(PREFIX + "/operations/preview", content=bad, headers={**actor["headers"], "content-type": "application/json"})
        assert r.status_code == 400
        private(r)
    body = wire(req, files)
    body["files_base64"][0] += "\n"
    assert (await client.post(PREFIX + "/operations/preview", json=body, headers=actor["headers"])).status_code == 400
    assert (await client.get(PREFIX + "/capabilities?x=" + "x" * 2050, headers=actor["headers"])).status_code == 413
    monkeypatch.setattr(route, "MAX_BODY_BYTES", 100)
    assert (await client.post(PREFIX + "/operations/preview", json=wire(req, files), headers=actor["headers"])).status_code == 413
    cookie = build_browser_session_config(get_settings().environment, get_settings().jwt_expiry_hours * 3600)
    client.cookies.set(cookie.cookie_name, actor["token"])
    try:
        assert (await client.post(PREFIX + "/operations/preview", json={})).status_code == 403
    finally:
        client.cookies.clear()


@pytest.mark.asyncio
async def test_upload_revalidates_session_after_parsing_and_before_any_insert(client, db_session, enabled, monkeypatch):
    actor, parent, req, files, _, _ = await case(db_session)
    await db_session.commit()
    original = route.worker
    async def drift(fn, *args):
        result = await original(fn, *args)
        async with AsyncSession(get_engine().execution_options(isolation_level="READ COMMITTED")) as db:
            async with db.begin():
                users = Base.metadata.tables["users"]
                await db.execute(users.update().where(users.c.id == actor["id"]).values(session_version=users.c.session_version + 1))
        return result
    monkeypatch.setattr(route, "worker", drift)
    r = await client.post(PREFIX + "/operations/preview", json=wire(req, files), headers=actor["headers"])
    assert r.status_code in (401, 403, 409), r.text
    assert "receipt_id" not in r.text
    private(r)


@pytest.mark.asyncio
async def test_native_parser_rejects_forged_output_even_with_matching_file_hashes(client, db_session, enabled):
    import hashlib
    actor, _, req, files, _, _ = await case(db_session)
    await db_session.commit()
    i = next(i for i, item in enumerate(req["files"]) if item["role"] == "xml")
    files[i] = files[i].replace(b"-3.119334546679567E+001", b"-9.119334546679567E+001")
    req["files"][i].update(size_bytes=len(files[i]), sha256=hashlib.sha256(files[i]).hexdigest())
    r = await client.post(PREFIX + "/operations/preview", json=wire(req, files), headers=actor["headers"])
    assert r.status_code == 400 and "9.119" not in r.text


@pytest.mark.asyncio
async def test_worker_retains_capacity_until_cancelled_call_actually_finishes():
    started, release = threading.Event(), threading.Event()
    def blocked():
        started.set()
        release.wait(5)
        return "finished"
    task = asyncio.create_task(route.worker(blocked))
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(.01)
        assert started.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(route.HTTPException) as exc:
            await route.worker(lambda: "must not run")
        assert exc.value.status_code == 503
    finally:
        release.set()
        if route._tasks:
            await asyncio.gather(*list(route._tasks), return_exceptions=True)
        await asyncio.sleep(0)
    assert await route.worker(lambda: "recovered") == "recovered"


@pytest.mark.asyncio
async def test_saved_false_report_digest_never_serves_values_or_files(client, db_session, enabled):
    actor, _, req, files, _, _ = await case(db_session)
    prepared = contract.prepare(req, files)
    forged = json.loads(prepared.report_json)
    forged["observations"]["total_energy"]["value"] = 300
    # Deliberately model a forged, re-signed DB digest. HTTP never accepts a
    # Prepared object or uploaded report; every public read must reparse files.
    prepared = replace(prepared, report_json=json.dumps(forged))
    preview = await service.operate(db_session, actor_user_id=actor["id"], prepared=prepared)
    result = await service.operate(db_session, actor_user_id=actor["id"], prepared=prepared, dry_run=False,
                                   expected_preview_sha256=preview["preview_sha256"])
    await db_session.commit()
    for suffix in ("", "/files/0"):
        r = await client.get(PREFIX + "/returns/" + result["receipt_id"] + suffix, headers=actor["headers"])
        assert r.status_code == 503 and "observations" not in r.text and "&CONTROL" not in r.text
        private(r)


@pytest.mark.asyncio
async def test_design_withdrawn_during_native_replay_is_withheld_before_response(client, db_session, enabled, monkeypatch):
    actor, parent, req, files, _, _ = await case(db_session)
    result = await saved(db_session, actor, req, files)
    await db_session.commit()
    original = route.worker
    async def withdraw_after_parse(fn, *args):
        parsed = await original(fn, *args)
        async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as db:
            async with db.begin():
                await save(db, actor, {"version": "discovery-design-operation/1.0.0", "request_key": "withdraw-read:" + uuid4().hex,
                    "operation": "withdraw", "payload": {"design_id": parent["design_id"],
                        "predecessor": {"id": parent["receipt_id"], "record_sha256": parent["receipt_sha256"]},
                        "reason": "Withdraw while the native-file reading is in progress"}})
        return parsed
    monkeypatch.setattr(route, "worker", withdraw_after_parse)
    r = await client.get(PREFIX + "/returns/" + result["receipt_id"], headers=actor["headers"])
    assert r.status_code == 409 and "-31.193" not in r.text
    monkeypatch.setattr(route, "worker", original)
    hidden = await client.get(PREFIX + "/returns/" + result["receipt_id"], headers=actor["headers"])
    assert hidden.status_code == 200 and hidden.json()["report"] is None
    assert not hidden.json()["eligibility"]["eligible"]
    assert (await client.get(PREFIX + "/returns/" + result["receipt_id"] + "/files/0", headers=actor["headers"])).status_code == 409
