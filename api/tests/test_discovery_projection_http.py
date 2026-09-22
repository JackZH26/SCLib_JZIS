"""Private Discovery HTTP on actual, capability-owned synthetic PostgreSQL.

These fixtures exercise retained bytes and real operator ledgers. They are not
a reviewed scientific pilot, production publication or training authorization.
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
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from models.db import Base
from routers import discovery_projections as router
from routers import research_distributions as operators
from services import research_publication as publication
from tests.test_discovery_projection_governance import reviewed_publication
from tests.test_discovery_scientific_cells import CANARY
from tests.test_discovery_scientific_projection import projected_fixture
from tests.test_research_distribution_operators import auth, private
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state
from tests.test_research_publication import actors

BASE = "/v1/ml/discovery-projections"
SECRET = "PRIVATE_DISCOVERY_PASSWORD_PATH_SOURCE"


def body(arguments=None):
    value = deepcopy(arguments or {
        "distribution_package_id": str(uuid4()), "expected_distribution_record_sha256": "a" * 64,
        "expected_inventory_sha256": "b" * 64, "public_bundle": {}, "selection": {},
        "expected_selection_sha256": "c" * 64})
    value.pop("actor_user_id", None)
    value.pop("package_id", None)
    value.setdefault("request_key", "synthetic-discovery-http:" + uuid4().hex)
    return value


def commit_body(request, preview):
    return {**deepcopy(request), "dry_run": False, "expected_payload_sha256": preview["result"]["payload_sha256"]}


def query(request, receipt, operation="register"):
    return {"operation": operation, "request_key": request["request_key"],
        "expected_request_sha256": receipt["result"]["request_sha256"]}


def protected(response):
    private(response)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert SECRET not in response.text and CANARY not in response.text


@pytest_asyncio.fixture(loop_scope="function")
async def people(db_session):
    result = await actors(db_session)
    await db_session.commit()
    return result


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def isolate_owned_materials(db_session):
    """After assertions, hold only this test's committed synthetic materials.

    This disposable-test isolation prevents a successful synthetic publisher
    fixture from entering later global listings. Immutable ledgers are retained;
    it is neither production behavior nor part of any operation receipt.
    """
    owned = set()
    db_session.info["discovery_http_owned_materials"] = owned
    yield
    await db_session.rollback()
    if owned:
        materials = Base.metadata.tables["materials"]
        changed = (await db_session.execute(sa.update(materials).where(materials.c.id.in_(sorted(owned)))
            .values(needs_review=True).returning(materials.c.id))).scalars().all()
        assert set(changed) <= owned
        await db_session.commit()


def track_material(db, fixture):
    db.info["discovery_http_owned_materials"].add(fixture["source"]["material"])


async def previewed(client, db):
    fixture = await projected_fixture(db, properties=[{"property_key": "band_gap", "relation": "exact", "value": 0}])
    track_material(db, fixture)
    request = body(fixture["arguments"])
    await db.commit()
    response = await client.post(BASE + "/register", json=request, headers=auth(fixture["actors"]["curator"]))
    assert response.status_code == 200, response.text
    return fixture, request, response.json()


async def test_actual_registration_preview_commit_inspection_and_exact_recovery(client, db_session, tmp_path):
    fixture = await projected_fixture(db_session, structure=True, sample=True)
    track_material(db_session, fixture)
    request, people = body(fixture["arguments"]), fixture["actors"]
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    capabilities = await client.get(BASE + "/capabilities", headers=auth(people["curator"]))
    assert capabilities.status_code == 200, capabilities.text
    capability = capabilities.json()
    assert set(capability) == {"version", "scope", "registry", "population_scope", "max_materials",
        "max_assessments", "max_properties", "scientific_acceptance", "ml_training_approved", "public_release_authorized"}
    assert capability["population_scope"] == "not_queried"
    assert capability["scientific_acceptance"] is capability["ml_training_approved"] is capability["public_release_authorized"] is False
    preview = await client.post(BASE + "/register", json=request, headers=auth(people["curator"]))
    assert preview.status_code == 200, preview.text
    rehearsal = preview.json()
    assert rehearsal["version"] == "research-distribution-operation/1.0.0"
    assert rehearsal["dry_run"] is True and rehearsal["committed"] is False
    assert before == await state(db_session)
    await db_session.rollback()
    absent = await client.get(BASE + "/outcome", params=query(request, rehearsal), headers=auth(people["curator"]))
    assert absent.status_code == 404 and "committed" not in absent.json()
    committed = await client.post(BASE + "/register", json=commit_body(request, rehearsal), headers=auth(people["curator"]))
    assert committed.status_code == 200, committed.text
    receipt = committed.json()
    assert receipt["committed"] is True and receipt["dry_run"] is False
    assert receipt["result"]["committed"] is False  # Inner savepoint is not the durable boundary.
    assert receipt["result"]["payload_sha256"] == rehearsal["result"]["payload_sha256"]
    assert set(receipt["result"]) == {"version", "operation", "id", "package_id", "record_sha256",
        "payload_sha256", "selection_sha256", "request_sha256", "dry_run", "committed", "replayed",
        "scientific_acceptance", "ml_training_approved", "current_authorization_checked"}
    after = await state(db_session)
    assert len(after["discovery_projection_packages"]) == len(before["discovery_projection_packages"]) + 1
    for table in ("discovery_projection_reviews", "discovery_projection_actions", "research_distribution_permissions",
                  "research_distribution_reviews", "research_distribution_actions", "event_properties", "material_claims", "materials"):
        assert before[table] == after[table]
    await db_session.rollback()
    inspection = await client.get(BASE + "/" + receipt["result"]["package_id"], headers=auth(people["reviewer"]))
    assert inspection.status_code == 200, inspection.text
    assert inspection.json()["payload_sha256"] == receipt["result"]["payload_sha256"]
    assert len(inspection.json()["payload"]["rows"][0]["cells"]) == 8
    assert len(inspection.json()["rights_targets"]) == len(fixture["inventory"]["dependencies"])
    recovered = await client.get(BASE + "/outcome", params=query(request, rehearsal), headers=auth(people["curator"]))
    replay = await client.post(BASE + "/register", json=commit_body(request, rehearsal), headers=auth(people["curator"]))
    for response in (recovered, replay):
        assert response.status_code == 200, response.text
        assert response.json()["result"]["id"] == receipt["result"]["id"]
        assert response.json()["result"]["replayed"] is True
    assert after == await state(db_session)  # Includes every governance epoch.
    for response in (capabilities, preview, absent, committed, inspection, recovered, replay):
        protected(response)
        assert len(response.content) <= (router.MAX_INSPECTION_BYTES if response is inspection else router.MAX_REPORT_BYTES)
    (tmp_path / "discovery-projection-http.json").write_text(json.dumps({"capabilities": capability,
        "request": request, "preview": rehearsal, "commit_request": commit_body(request, rehearsal),
        "committed": receipt, "inspection": inspection.json(), "outcome": recovered.json()}, sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize("role", [None, "admin", "member", "curator", "reviewer", "publisher"])
async def test_actual_capabilities_require_explicit_operator_not_legacy_flags(client, people, role):
    response = await client.get(BASE + "/capabilities", headers={} if role is None else auth(people[role]))
    assert response.status_code == (401 if role is None else 403 if role in {"admin", "member"} else 200), response.text
    protected(response)


@pytest.mark.parametrize("path,allowed", [("register", "curator"), ("reviews", "reviewer"), ("actions", "publisher")])
async def test_specific_role_is_checked_before_source_body_read(client, people, monkeypatch, path, allowed):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("unadmitted caller reached source body")

    monkeypatch.setattr(router, "_body", forbidden)
    endpoint = BASE + "/register" if path == "register" else BASE + "/" + str(uuid4()) + "/" + path
    for role in (None, "admin", "member", "curator", "reviewer", "publisher"):
        if role == allowed:
            continue
        response = await client.post(endpoint, content=SECRET, headers={
            **({} if role is None else auth(people[role])), "Content-Type": "application/json", "Content-Length": "999999999"})
        assert response.status_code == (401 if role is None else 403), response.text
        protected(response)


@pytest.mark.parametrize("change", [{"actor_user_id": "secret"}, {"actor_grant_id": "secret"},
    {"scientific_acceptance": True}, {"rights": []}, {"path": SECRET}, {"dry_run": 0}, {"dry_run": "false"},
    {"dry_run": False}, {"expected_payload_sha256": True}, {"expected_selection_sha256": "A" * 64},
    {"request_key": "x" * 161}, {"distribution_package_id": "not-a-uuid"}])
async def test_closed_registration_and_preview_pin_required_before_service(client, people, monkeypatch, change):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("invalid transport reached registration")

    monkeypatch.setattr(router.service, "register_projection", forbidden)
    response = await client.post(BASE + "/register", json={**body(), **change}, headers=auth(people["curator"]))
    assert response.status_code == 400, response.text
    assert "committed" not in response.json()
    protected(response)


@pytest.mark.parametrize("raw", [b'{"key":1,"key":2}', b'{"private":NaN}', b'{"private":Infinity}',
    b'{"private":1e999}', b'{"private":"\\ud800"}', b'{"private":"\xff"}', b'[]', b'null'])
async def test_malformed_json_has_static_errors_no_service(client, people, monkeypatch, raw):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("malformed JSON reached registration")

    monkeypatch.setattr(router.service, "register_projection", forbidden)
    response = await client.post(BASE + "/register", content=raw, headers={**auth(people["curator"]), "Content-Type": "application/json"})
    assert response.status_code == 400 and response.json()["detail"] == "Distribution request rejected", response.text
    assert set(response.json()) == {"detail", "error_code", "request_id"}
    assert response.json()["error_code"] == "bad_request"
    protected(response)


@pytest.mark.parametrize("headers,expected", [({"Content-Type": "text/plain"}, 415),
    ({"Content-Encoding": "gzip"}, 415), ({"Content-Length": "-1"}, 413),
    ({"Content-Length": "1e8"}, 413), ({"Content-Length": "999999999"}, 413)])
async def test_transport_header_rejection_never_consumes_body(client, people, headers, expected):
    async def source():
        pytest.fail("invalid headers consumed body")
        yield b""  # pragma: no cover

    response = await client.post(BASE + "/register", content=source(), headers={**auth(people["curator"]),
        "Content-Type": "application/json", **headers})
    assert response.status_code == expected, response.text
    protected(response)


@pytest.mark.parametrize("kind", ["bytes", "chunks"])
async def test_actual_stream_budget_rejects_before_service(client, people, monkeypatch, kind):
    monkeypatch.setattr(router, "MAX_BODY_BYTES" if kind == "bytes" else "MAX_BODY_CHUNKS", 4)

    async def source():
        for _ in range(6):
            yield b"xx" if kind == "bytes" else b" "

    response = await client.post(BASE + "/register", content=source(), headers={**auth(people["curator"]), "Content-Type": "application/json"})
    assert response.status_code == 413, response.text
    protected(response)


@pytest.mark.parametrize("suffix", ["/capabilities?unknown=secret", "/outcome?operation=register",
    "/outcome?operation=register&operation=review&request_key=key&expected_request_sha256=" + "a" * 64,
    "/" + str(uuid4()) + "?unknown=secret"])
async def test_query_fields_are_closed(client, people, suffix):
    response = await client.get(BASE + suffix, headers=auth(people["curator"]))
    assert response.status_code == 400, response.text
    protected(response)


async def test_raw_query_limit_precedes_even_query_decoding(client, people, monkeypatch):
    original = Request.query_params

    def guarded(request):
        if request.scope["path"].startswith(BASE):
            pytest.fail("oversized query decoded")
        return original.__get__(request, Request)

    monkeypatch.setattr(Request, "query_params", property(guarded))
    response = await client.get(BASE + "/outcome?" + "a" * 1025, headers=auth(people["curator"]))
    assert response.status_code == 413, response.text
    protected(response)


async def test_disabled_feature_is_private_and_does_not_reach_body(client, people, monkeypatch):
    monkeypatch.setattr(operators, "get_settings", lambda: SimpleNamespace(ml_foundation_public_enabled=False))
    for method, endpoint in (("get", "/capabilities"), ("post", "/register"), ("get", "/outcome")):
        response = await getattr(client, method)(BASE + endpoint, headers=auth(people["curator"]))
        assert response.status_code == 404, response.text
        protected(response)


@pytest.mark.parametrize("change", ["payload", "selection", "inventory", "package", "request_key"])
async def test_stale_pins_or_conflicting_key_do_not_write(client, db_session, change):
    fixture, request, preview = await previewed(client, db_session)
    headers = auth(fixture["actors"]["curator"])
    commit = commit_body(request, preview)
    if change == "request_key":
        first = await client.post(BASE + "/register", json=commit, headers=headers)
        assert first.status_code == 200, first.text
        commit["selection"]["representatives"][0]["rationale"] += " changed"
        from services.research_priority import digest
        commit["expected_selection_sha256"] = digest(commit["selection"])
    else:
        field = {"payload": "expected_payload_sha256", "selection": "expected_selection_sha256",
                 "inventory": "expected_inventory_sha256", "package": "expected_distribution_record_sha256"}[change]
        commit[field] = "0" * 64
    before = await state(db_session)
    await db_session.rollback()
    response = await client.post(BASE + "/register", json=commit, headers=headers)
    assert response.status_code == (409 if change in {"payload", "request_key"} else 400), response.text
    assert before == await state(db_session)
    protected(response)


@pytest.mark.parametrize("mode", ["new", "replay"])
@pytest.mark.parametrize("change", ["session", "grant"])
async def test_current_identity_rechecked_after_body_for_new_work_and_replay(client, db_session, mode, change):
    fixture, request, preview = await previewed(client, db_session)
    people, commit = fixture["actors"], commit_body(request, preview)
    headers = auth(people["curator"])
    if mode == "replay":
        response = await client.post(BASE + "/register", json=commit, headers=headers)
        assert response.status_code == 200, response.text
    expected = []

    async def source():
        raw = json.dumps(commit).encode()
        yield raw[:20]
        if change == "session":
            users = Base.metadata.tables["users"]
            await db_session.execute(sa.update(users).where(users.c.id == people["curator"]).values(session_version=1))
        else:
            await publication.revoke_role(db_session, actor_user_id=people["admin"], grant_id=people["grants"]["curator"],
                reason_code="synthetic_midupload", dry_run=False)
        await db_session.commit()
        expected.append(await state(db_session))
        await db_session.rollback()
        yield raw[20:]

    response = await client.post(BASE + "/register", content=source(), headers={**headers, "Content-Type": "application/json"})
    assert response.status_code == 403, response.text
    assert len(expected) == 1 and expected[0] == await state(db_session)
    protected(response)


async def test_historical_get_is_actor_key_pin_exact_and_survives_source_drift_and_regrant(client, db_session):
    fixture, request, preview = await previewed(client, db_session)
    people, headers = fixture["actors"], auth(fixture["actors"]["curator"])
    response = await client.post(BASE + "/register", json=commit_body(request, preview), headers=headers)
    assert response.status_code == 200, response.text
    receipt = response.json()
    await publication.grant_role(db_session, actor_user_id=people["admin"], user_id=people["member"],
        role="curator", reason_code="synthetic_other_curator", dry_run=False)
    await publication.revoke_role(db_session, actor_user_id=people["admin"], grant_id=people["grants"]["curator"],
        reason_code="synthetic_replacement", dry_run=False)
    await publication.grant_role(db_session, actor_user_id=people["admin"], user_id=people["curator"],
        role="curator", reason_code="synthetic_replacement", dry_run=False)
    await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"), {"id": fixture["source"]["material"]})
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    original = query(request, preview)
    for params, actor, status in ((original, people["curator"], 200), (original, people["member"], 404),
        ({**original, "request_key": "absent"}, people["curator"], 404),
        ({**original, "expected_request_sha256": "0" * 64}, people["curator"], 409)):
        result = await client.get(BASE + "/outcome", params=params, headers=auth(actor))
        assert result.status_code == status, result.text
        if status == 200:
            assert result.json()["result"]["id"] == receipt["result"]["id"]
            assert result.json()["result"]["replayed"] is True
        else:
            assert "committed" not in result.json()
        protected(result)
    replay = await client.post(BASE + "/register", json=commit_body(request, preview), headers=headers)
    assert replay.status_code == 409, replay.text
    assert before == await state(db_session)


@pytest.mark.parametrize("failure", ["serialize", "oversized", "outer_commit", "lost_ack"])
async def test_response_failure_and_lost_ack_do_not_invent_durable_success(client, db_session, monkeypatch, failure):
    fixture, request, preview = await previewed(client, db_session)
    headers = auth(fixture["actors"]["curator"])
    before = await state(db_session)
    await db_session.rollback()
    completed = []
    with monkeypatch.context() as patch:
        if failure == "lost_ack":
            operate = router._operate

            async def lost(*args, **kwargs):
                await operate(*args, **kwargs)
                completed.append(True)
                raise SQLAlchemyError(SECRET)

            patch.setattr(router, "_operate", lost)
        else:
            register = router.service.register_projection

            async def fault(db, **kwargs):
                result = await register(db, **kwargs)
                completed.append(True)
                if failure == "serialize":
                    return {**result, "bad": object()}
                if failure == "oversized":
                    return {**result, "bad": "x" * (router.MAX_REPORT_BYTES + 1)}
                await db.execute(sa.text("CREATE TEMP TABLE discovery_commit_probe (id int PRIMARY KEY, "
                    "parent int REFERENCES discovery_commit_probe(id) DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP"))
                await db.execute(sa.text("INSERT INTO discovery_commit_probe VALUES(1,2)"))
                return result

            patch.setattr(router.service, "register_projection", fault)
        response = await client.post(BASE + "/register", json=commit_body(request, preview), headers=headers)
    assert completed == [True]
    assert response.status_code == (400 if failure in {"serialize", "oversized"} else 503), response.text
    assert "committed" not in response.json()
    protected(response)
    after = await state(db_session)
    if failure == "lost_ack":
        assert len(after["discovery_projection_packages"]) == len(before["discovery_projection_packages"]) + 1
    else:
        assert after == before
    await db_session.rollback()
    outcome = await client.get(BASE + "/outcome", params=query(request, preview), headers=headers)
    assert outcome.status_code == (200 if failure == "lost_ack" else 404), outcome.text
    if failure == "lost_ack":
        assert outcome.json()["committed"] is True and outcome.json()["result"]["replayed"] is True
    assert after == await state(db_session)


async def test_actual_review_and_publisher_roundtrip_preserves_false_authority(client, db_session, tmp_path):
    context = await reviewed_publication(db_session, publish=False)
    track_material(db_session, context["fixture"])
    people, registered = context["fixture"]["actors"], context["registered"]
    review = body(context["review_arguments"])
    review["request_key"] = uuid4().hex
    action = body(context["action_arguments"])
    package_id = registered["package_id"]
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    preview = await client.post(BASE + "/" + package_id + "/reviews", json=review, headers=auth(people["reviewer"]))
    assert preview.status_code == 200, preview.text
    assert preview.json()["committed"] is False and before == await state(db_session)
    await db_session.rollback()
    reviewed = await client.post(BASE + "/" + package_id + "/reviews", json={**review, "dry_run": False}, headers=auth(people["reviewer"]))
    assert reviewed.status_code == 200, reviewed.text
    action["review_id"] = reviewed.json()["result"]["id"]
    before_publish = await state(db_session)
    await db_session.rollback()
    publish_preview = await client.post(BASE + "/" + package_id + "/actions", json=action, headers=auth(people["publisher"]))
    assert publish_preview.status_code == 200, publish_preview.text
    assert before_publish == await state(db_session)
    await db_session.rollback()
    published = await client.post(BASE + "/" + package_id + "/actions", json={**action, "dry_run": False}, headers=auth(people["publisher"]))
    assert published.status_code == 200, published.text
    after = await state(db_session)
    await db_session.rollback()
    for request, receipt, role, operation in ((review, reviewed.json(), "reviewer", "review"),
                                            (action, published.json(), "publisher", "publish")):
        outcome = await client.get(BASE + "/outcome", params=query(request, receipt, operation), headers=auth(people[role]))
        assert outcome.status_code == 200 and outcome.json()["result"]["id"] == receipt["result"]["id"], outcome.text
        assert receipt["result"]["scientific_acceptance"] is receipt["result"]["ml_training_approved"] is False
        protected(outcome)
    assert after == await state(db_session)
    for response in (preview, reviewed, publish_preview, published):
        protected(response)
    (tmp_path / "discovery-projection-publication-http.json").write_text(json.dumps({"review_request": review,
        "review_preview": preview.json(), "reviewed": reviewed.json(), "action_request": action,
        "action_preview": publish_preview.json(), "published": published.json()}, sort_keys=True), encoding="utf-8")


async def test_nonblocking_capacity_cancellation_and_timeout_release_slots(client, people, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(operators, "_request_slots", slots)
    entered, release = asyncio.Event(), asyncio.Event()

    async def source():
        entered.set()
        await release.wait()
        yield b"{}"

    request = asyncio.create_task(client.post(BASE + "/register", content=source(),
        headers={**auth(people["curator"]), "Content-Type": "application/json"}))
    await asyncio.wait_for(entered.wait(), 3)
    second = await client.get(BASE + "/capabilities", headers=auth(people["curator"]))
    assert second.status_code == 503
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert slots.acquire(blocking=False)
    slots.release()
    monkeypatch.setattr(operators, "REQUEST_TIMEOUT", 0.05)
    response = await client.post(BASE + "/register", content=source(),
        headers={**auth(people["curator"]), "Content-Type": "application/json"})
    assert response.status_code == 503, response.text
    assert slots.acquire(blocking=False)
    slots.release()
    protected(response)
