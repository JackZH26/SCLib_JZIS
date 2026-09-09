"""Private preparation HTTP on capability-owned synthetic PostgreSQL only.

Actual source/capsule fixtures do not preseed the descriptor artifacts this
entrypoint must create. Fault injections wrap actual service/outer transaction
work; they are not fabricated permission or scientific-approval receipts.
"""
from __future__ import annotations

import asyncio
import base64
import json
import threading
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from models.db import Base
from routers import research_distribution_preparation as router
from routers import research_distributions as operators
from services import research_publication as publication
from tests.test_research_distribution_operators import auth, private
from tests.test_research_distribution_preparation import preparation_fixture
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state
from tests.test_research_publication import actors

BASE = "/v1/ml/distributions/preparation"
PRIVATE = "PRIVATE_PREPARATION_SOURCE_PASSWORD_PATH"


def request_body(arguments=None):
    """Encode transport bytes only, without rewriting any source/selection pin."""
    value = deepcopy(arguments or {"release": {}, "selections": {}, "public_bundle": {},
        "expected_release_sha256": "a" * 64, "expected_selections_sha256": "b" * 64,
        "expected_public_bundle_sha256": "c" * 64, "artifact_bytes": {}, "capsule_artifact_bytes": {}})
    value["artifact_bytes_base64"] = {sha: base64.b64encode(payload).decode("ascii")
        for sha, payload in value.pop("artifact_bytes").items()}
    value["capsule_artifact_bytes_base64"] = {manifest: {
        sha: base64.b64encode(payload).decode("ascii") for sha, payload in sources.items()}
        for manifest, sources in value.pop("capsule_artifact_bytes").items()}
    value["request_key"] = "synthetic-preparation-http:" + uuid4().hex
    return value


def commit_body(body, preview):
    return {**deepcopy(body), "dry_run": False, "expected_intent_sha256": preview["result"]["intent_sha256"]}


def outcome_query(body, preview):
    return {"request_key": body["request_key"], "expected_intent_sha256": preview["result"]["intent_sha256"]}


@pytest_asyncio.fixture
async def wire_people(db_session):
    people = await actors(db_session)
    await db_session.commit()
    return people


async def prepared(client, db_session):
    context = await preparation_fixture(db_session)
    assert context["shared"]["internal_artifacts"] == {}
    body = request_body(context["arguments"])
    await db_session.commit()
    response = await client.post(BASE, json=body, headers=auth(context["shared"]["actors"]["curator"]))
    assert response.status_code == 200, response.text
    assert response.json()["committed"] is False
    return context, body, response.json()


async def test_actual_preview_commit_and_exact_get_replay_have_bounded_private_wire(client, db_session, tmp_path):
    context = await preparation_fixture(db_session)
    body = request_body(context["arguments"])
    people = context["shared"]["actors"]
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    capabilities = await client.get(BASE + "/capabilities", headers=auth(people["curator"]))
    assert capabilities.status_code == 200, capabilities.text
    cap = capabilities.json()
    assert cap["actor_user_id"] == str(people["curator"])
    assert cap["actor_grant_id"] == str(people["grants"]["curator"])
    assert cap["can_read"] is cap["can_prepare"] is True
    assert cap["scientific_acceptance"] is cap["ml_training_approved"] is cap["current_authorization_checked"] is False
    preview = await client.post(BASE, json=body, headers=auth(people["curator"]))
    assert preview.status_code == 200, preview.text
    rehearsal = preview.json()
    assert rehearsal["dry_run"] is True and rehearsal["committed"] is False
    assert rehearsal["result"]["package"] is None
    assert set(rehearsal["result"]) == {"version", "dry_run", "committed", "replayed", "intent", "intent_sha256",
        "descriptor_count", "source_dependency_count", "package", "scientific_acceptance", "ml_training_approved", "current_authorization_checked"}
    assert before == await state(db_session)
    await db_session.rollback()
    absent = await client.get(BASE + "/outcome", params=outcome_query(body, rehearsal), headers=auth(people["curator"]))
    assert absent.status_code == 404 and "committed" not in absent.json()
    committed = await client.post(BASE, json=commit_body(body, rehearsal), headers=auth(people["curator"]))
    assert committed.status_code == 200, committed.text
    durable = committed.json()
    assert durable["committed"] is True and durable["dry_run"] is False
    assert durable["result"]["committed"] is False  # Inner savepoint is not the durable boundary.
    assert durable["result"]["intent_sha256"] == rehearsal["result"]["intent_sha256"]
    assert set(durable["result"]["package"]) == {"id", "record_sha256", "bindings_sha256", "inventory_sha256", "dependency_count"}
    after = await state(db_session)
    assert len(after["evidence_artifacts"]) == len(before["evidence_artifacts"]) + rehearsal["result"]["descriptor_count"]
    assert len(after["research_distribution_packages"]) == len(before["research_distribution_packages"]) + 1
    for table in ("research_distribution_permissions", "research_distribution_reviews", "research_distribution_actions"):
        assert before[table] == after[table]
    await db_session.rollback()
    outcome = await client.get(BASE + "/outcome", params=outcome_query(body, rehearsal), headers=auth(people["curator"]))
    assert outcome.status_code == 200, outcome.text
    assert outcome.json()["committed"] is True and outcome.json()["result"]["replayed"] is True
    assert outcome.json()["result"]["package"] == durable["result"]["package"]
    replay = await client.post(BASE, json=commit_body(body, rehearsal), headers=auth(people["curator"]))
    assert replay.status_code == 200 and replay.json()["result"]["replayed"] is True, replay.text
    assert after == await state(db_session)  # Includes all governance lock epochs.
    for response in (capabilities, preview, absent, committed, outcome, replay):
        private(response)
        assert response.headers["x-content-type-options"] == "nosniff"
    fixture = {"capabilities": cap, "request": body, "preview": rehearsal, "commit_request": commit_body(body, rehearsal),
        "committed": durable, "outcome": outcome.json(), "absent": absent.json()}
    (tmp_path / "distribution-preparation-http.json").write_text(json.dumps(fixture, ensure_ascii=False, sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize("role", [None, "member", "admin", "reviewer", "publisher"])
async def test_current_curator_admission_precedes_any_body_read(client, wire_people, monkeypatch, role):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("unadmitted caller reached preparation body")

    monkeypatch.setattr(router, "_body", forbidden)
    headers = {} if role is None else auth(wire_people[role])
    for endpoint in (BASE + "/capabilities", BASE + "/outcome?request_key=missing&expected_intent_sha256=" + "a" * 64,
                     BASE + "/outcome?bad=PRIVATE"):
        response = await client.get(endpoint, headers=headers)
        assert response.status_code == (401 if role is None else 403), response.text
        private(response)
    response = await client.post(BASE, content=PRIVATE.encode(), headers={**headers,
        "Content-Type": "application/json", "Content-Length": "999999999"})
    assert response.status_code == (401 if role is None else 403), response.text
    assert PRIVATE not in response.text
    private(response)


@pytest.mark.parametrize("change", [
    {"actor_user_id": "private-actor"}, {"actor_grant_id": "private-grant"},
    {"path": "/private/source"}, {"url": "https://private.invalid/source"},
    {"rights": {"approved": True}}, {"scientific_acceptance": True}, {"ml_training_approved": True},
    {"dry_run": 0}, {"dry_run": "false"}, {"dry_run": None}, {"dry_run": False},
    {"expected_release_sha256": "A" * 64}, {"expected_selections_sha256": True},
    {"expected_public_bundle_sha256": "bad"}, {"request_key": "x" * 161},
])
async def test_closed_wire_refuses_coercion_identity_authority_and_unpinned_commit(client, wire_people, change):
    response = await client.post(BASE, json={**request_body(), **change}, headers=auth(wire_people["curator"]))
    assert response.status_code == 400, response.text
    assert "private" not in response.text.lower() and "committed" not in response.json()
    private(response)


@pytest.mark.parametrize("raw", [b'{"request_key":"PRIVATE","request_key":"OTHER"}', b'{"PRIVATE":NaN}',
    b'{"PRIVATE":Infinity}', b'{"PRIVATE":1e999}', b'{"PRIVATE":"\\ud800"}', b'{"PRIVATE":"\xff"}', b'[]', b'null'])
async def test_invalid_json_is_rejected_without_service_or_source_echo(client, wire_people, monkeypatch, raw):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("malformed JSON reached preparation")

    monkeypatch.setattr(router, "prepare_distribution", forbidden)
    response = await client.post(BASE, content=raw, headers={**auth(wire_people["curator"]), "Content-Type": "application/json"})
    assert response.status_code == 400 and "PRIVATE" not in response.text, response.text
    private(response)


@pytest.mark.parametrize("headers,expected", [({"Content-Type": "text/plain"}, 415), ({"Content-Encoding": "gzip"}, 415),
    ({"Content-Length": "-1"}, 413), ({"Content-Length": "1e4"}, 413), ({"Content-Length": "999999999"}, 413)])
async def test_invalid_transport_headers_do_not_consume_large_source_body(client, wire_people, headers, expected):
    async def source():
        pytest.fail("header rejection consumed private source")
        yield b""  # pragma: no cover

    response = await client.post(BASE, content=source(), headers={**auth(wire_people["curator"]),
        "Content-Type": "application/json", **headers})
    assert response.status_code == expected, response.text
    private(response)


@pytest.mark.parametrize("change", ["role_revoked", "session_revoked", "inactive", "unverified"])
async def test_identity_change_during_real_upload_is_checked_again_before_any_descriptor_write(client, db_session, change):
    context = await preparation_fixture(db_session)
    people, body = context["shared"]["actors"], request_body(context["arguments"])
    await db_session.commit()
    preview = await client.post(BASE, json=body, headers=auth(people["curator"]))
    assert preview.status_code == 200, preview.text
    body = commit_body(body, preview.json())
    expected = []

    async def source():
        payload = json.dumps(body).encode()
        yield payload[:20]
        if change == "role_revoked":
            await publication.revoke_role(db_session, actor_user_id=people["admin"],
                grant_id=people["grants"]["curator"], reason_code="synthetic_midupload", dry_run=False)
        else:
            column, value = {"session_revoked": ("session_version", 1), "inactive": ("is_active", False),
                             "unverified": ("email_verified", False)}[change]
            users = Base.metadata.tables["users"]
            await db_session.execute(sa.update(users).where(users.c.id == people["curator"]).values(**{column: value}))
        await db_session.commit()
        expected.append(await state(db_session))
        await db_session.rollback()
        yield payload[20:]

    response = await client.post(BASE, content=source(), headers={**auth(people["curator"]), "Content-Type": "application/json"})
    assert response.status_code == 403, response.text
    assert len(expected) == 1 and expected[0] == await state(db_session)
    private(response)


@pytest.mark.parametrize("failure", ["serialize", "oversized", "outer_commit", "lost_ack"])
async def test_failure_and_ack_loss_recover_only_actual_durable_atomic_registration(client, db_session, monkeypatch, failure):
    context, body, preview = await prepared(client, db_session)
    headers = auth(context["shared"]["actors"]["curator"])
    before = await state(db_session)
    await db_session.rollback()
    completed = []
    with monkeypatch.context() as patch:
        if failure == "lost_ack":
            operate = router._operate

            async def lost(*args, **kwargs):
                await operate(*args, **kwargs)
                completed.append(True)
                raise SQLAlchemyError(PRIVATE)

            patch.setattr(router, "_operate", lost)
        else:
            prepare = router.prepare_distribution

            async def fail(db, **kwargs):
                result = await prepare(db, **kwargs)
                completed.append(True)
                if failure == "serialize":
                    return {**result, "unserializable": object()}
                if failure == "oversized":
                    return {**result, "oversized": "x" * (router.MAX_RESPONSE_BYTES + 1)}
                await db.execute(sa.text("CREATE TEMP TABLE preparation_commit_probe (id int PRIMARY KEY, "
                    "parent int REFERENCES preparation_commit_probe(id) DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP"))
                await db.execute(sa.text("INSERT INTO preparation_commit_probe VALUES (1,2)"))
                return result

            patch.setattr(router, "prepare_distribution", fail)
        response = await client.post(BASE, json=commit_body(body, preview), headers=headers)
    assert completed == [True]
    assert response.status_code == (400 if failure in {"serialize", "oversized"} else 503), response.text
    assert PRIVATE not in response.text and "committed" not in response.json()
    after = await state(db_session)
    if failure == "lost_ack":
        assert len(after["research_distribution_packages"]) == len(before["research_distribution_packages"]) + 1
        assert len(after["evidence_artifacts"]) == len(before["evidence_artifacts"]) + preview["result"]["descriptor_count"]
    else:
        assert after == before
    await db_session.rollback()
    outcome = await client.get(BASE + "/outcome", params=outcome_query(body, preview), headers=headers)
    assert outcome.status_code == (200 if failure == "lost_ack" else 404), outcome.text
    assert after == await state(db_session)
    private(response)
    private(outcome)


async def test_cancellation_after_actual_descriptor_work_rolls_back_every_row(client, db_session, monkeypatch):
    context, body, preview = await prepared(client, db_session)
    headers = auth(context["shared"]["actors"]["curator"])
    before = await state(db_session)
    await db_session.rollback()
    prepare = router.prepare_distribution
    reached, release = asyncio.Event(), asyncio.Event()

    async def cancelled(db, **arguments):
        result = await prepare(db, **arguments)
        assert result["package"] is not None
        reached.set()
        await release.wait()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(router, "prepare_distribution", cancelled)
        request = asyncio.create_task(client.post(BASE, json=commit_body(body, preview), headers=headers))
        try:
            await asyncio.wait_for(reached.wait(), timeout=10)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
        finally:
            if not request.done():
                request.cancel()
            await asyncio.gather(request, return_exceptions=True)
    assert reached.is_set() and before == await state(db_session)
    await db_session.rollback()
    response = await client.get(BASE + "/outcome", params=outcome_query(body, preview), headers=headers)
    assert response.status_code == 404
    private(response)


async def test_historical_get_is_original_actor_key_pin_scoped_and_survives_regrant(client, db_session):
    context, body, preview = await prepared(client, db_session)
    people = context["shared"]["actors"]
    committed = await client.post(BASE, json=commit_body(body, preview), headers=auth(people["curator"]))
    assert committed.status_code == 200, committed.text
    original = committed.json()["result"]
    await publication.revoke_role(db_session, actor_user_id=people["admin"], grant_id=people["grants"]["curator"],
        reason_code="synthetic_regrant", dry_run=False)
    await publication.grant_role(db_session, actor_user_id=people["admin"], user_id=people["curator"], role="curator",
        reason_code="synthetic_regrant", dry_run=False)
    await publication.grant_role(db_session, actor_user_id=people["admin"], user_id=people["member"], role="curator",
        reason_code="synthetic_other_actor", dry_run=False)
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    query = outcome_query(body, preview)
    outcome = await client.get(BASE + "/outcome", params=query, headers=auth(people["curator"]))
    assert outcome.status_code == 200, outcome.text
    result = outcome.json()["result"]
    assert result["package"] == original["package"] and result["intent"] == original["intent"]
    assert result["replayed"] is True and result["current_authorization_checked"] is False
    for actor, params, code in ((people["member"], query, 404),
        (people["curator"], {**query, "expected_intent_sha256": "0" * 64}, 409),
        (people["curator"], {**query, "request_key": "original-not-observed"}, 404)):
        response = await client.get(BASE + "/outcome", params=params, headers=auth(actor))
        assert response.status_code == code and "committed" not in response.json(), response.text
        private(response)
    assert before == await state(db_session)


@pytest.mark.parametrize("query,expected", [
    ("request_key=x&expected_intent_sha256=" + "a" * 64 + "&extra=PRIVATE", 400),
    ("request_key=x&request_key=y&expected_intent_sha256=" + "a" * 64, 400),
    ("request_key=x&expected_intent_sha256=" + "a" * 64 + "&expected_intent_sha256=" + "b" * 64, 400),
    ("request_key=" + "x" * 1025, 413),
])
async def test_get_query_is_bounded_and_closed_before_private_lookup(client, wire_people, query, expected):
    response = await client.get(BASE + "/outcome?" + query, headers=auth(wire_people["curator"]))
    assert response.status_code == expected and "PRIVATE" not in response.text, response.text
    private(response)


@pytest.mark.parametrize("encoded", ["eA==\n", "eB==", "eA=", "秘密"])
async def test_noncanonical_base64_is_not_accepted_as_retained_source_bytes(client, wire_people, encoded):
    body = request_body()
    body["artifact_bytes_base64"] = {"a" * 64: encoded}
    response = await client.post(BASE, json=body, headers=auth(wire_people["curator"]))
    assert response.status_code == 400 and encoded not in response.text, response.text
    private(response)


async def test_live_and_capsule_sources_share_one_decoded_byte_budget(client, wire_people, monkeypatch):
    body = request_body()
    body["artifact_bytes_base64"] = {"a" * 64: base64.b64encode(b"ab").decode()}
    body["capsule_artifact_bytes_base64"] = {"b" * 64: {"c" * 64: base64.b64encode(b"cd").decode()}}
    monkeypatch.setattr(router, "MAX_DECODED_BYTES", 3)

    async def forbidden(*_args, **_kwargs):
        pytest.fail("shared decoded byte overflow reached preparation")

    monkeypatch.setattr(router, "prepare_distribution", forbidden)
    response = await client.post(BASE, json=body, headers=auth(wire_people["curator"]))
    assert response.status_code == 413, response.text
    private(response)


async def test_body_stream_budget_is_checked_before_json_hydration(client, wire_people, monkeypatch):
    payload = json.dumps(request_body()).encode()
    monkeypatch.setattr(router, "MAX_BODY_BYTES", len(payload) - 1)

    def forbidden(*_args):
        pytest.fail("byte overflow reached JSON hydration")

    monkeypatch.setattr(router, "_strict_json", forbidden)

    async def source():
        yield payload[:10]
        yield payload[10:]

    response = await client.post(BASE, content=source(), headers={**auth(wire_people["curator"]), "Content-Type": "application/json"})
    assert response.status_code == 413, response.text
    private(response)


async def test_body_fragment_count_bounds_empty_fragment_cpu(monkeypatch):
    monkeypatch.setattr(router, "MAX_BODY_CHUNKS", 3)
    seen = []

    async def source():
        for _ in range(4):
            seen.append(True)
            yield b""
        pytest.fail("fragment guard allowed unbounded traversal")

    request = SimpleNamespace(headers={"content-type": "application/json"}, stream=source)
    with pytest.raises(HTTPException) as caught:
        await router._body(request)
    assert caught.value.status_code == 413 and len(seen) == 4


@pytest.mark.parametrize("path", ["/capabilities", "/outcome?request_key=x&expected_intent_sha256=" + "a" * 64])
async def test_get_rechecks_session_in_fresh_snapshot_after_initial_precheck(client, db_session, wire_people, monkeypatch, path):
    precheck = router._precheck

    async def changed(user, role):
        await precheck(user, role)
        users = Base.metadata.tables["users"]
        await db_session.execute(sa.update(users).where(users.c.id == wire_people["curator"]).values(session_version=1))
        await db_session.commit()

    monkeypatch.setattr(router, "_precheck", changed)
    response = await client.get(BASE + path, headers=auth(wire_people["curator"]))
    assert response.status_code == 403, response.text
    private(response)


async def test_slots_cover_upload_and_recovery_and_release_on_cancel(client, wire_people, monkeypatch):
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(operators, "_request_slots", slots)
    entered, release = asyncio.Event(), asyncio.Event()
    readers = []
    original = router._body

    async def held(request):
        value = await original(request)
        readers.append(True)
        if len(readers) == 2:
            entered.set()
        await release.wait()
        return value

    monkeypatch.setattr(router, "_body", held)
    headers = auth(wire_people["curator"])
    pending = [asyncio.create_task(client.post(BASE, headers=headers, json=request_body())) for _ in range(2)]
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        calls = [client.post(BASE, headers=headers, json=request_body()), client.get(BASE + "/capabilities", headers=headers),
            client.get(BASE + "/outcome?request_key=x&expected_intent_sha256=" + "a" * 64, headers=headers)]
        for call in calls:
            response = await asyncio.wait_for(call, timeout=1)
            assert response.status_code == 503 and response.headers["retry-after"] == "1", response.text
            private(response)
        pending[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending[0]
        assert slots.acquire(blocking=False) and not slots.acquire(blocking=False)
        slots.release()
        release.set()
        response = await pending[1]
        assert response.status_code == 409  # Deliberately mismatched selection pin, not exhausted capacity.
    finally:
        release.set()
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)
    slots.release()
    slots.release()


async def test_static_prefix_and_streaming_openapi_do_not_route_to_old_package_uuid_handler():
    from main import app
    paths = app.openapi()["paths"]
    assert BASE + "/capabilities" in paths and BASE + "/outcome" in paths
    schema = paths[BASE]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["dry_run"]["default"] is True
    assert {"release", "selections", "public_bundle", "expected_release_sha256", "expected_selections_sha256",
            "expected_public_bundle_sha256", "artifact_bytes_base64"} <= set(schema["required"])
    assert not {"actor_user_id", "actor_grant_id", "permissions", "path", "url"} & set(schema["properties"])
