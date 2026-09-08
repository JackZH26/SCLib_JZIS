"""Private import HTTP and real outer transaction boundaries on disposable SQL.

Controlled service doubles below test orchestration, not scientific acceptance.
Separate real-package cases use the production parser/import service fixtures.
"""
from __future__ import annotations

import asyncio
import base64
import importlib
import json
import sys
import threading
from copy import deepcopy
from types import ModuleType
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from models.db import Base
from routers import scientific_program_imports as router
from services import auth_service
from tests.test_research_freeze import add
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_publication import actors

db_session = _serializable_db_session
pytestmark = pytest.mark.asyncio
BASE = "/v1/ml/scientific-program-imports"


def auth(user_id):
    token, _ = auth_service.create_access_token(user_id)
    return {"Authorization": "Bearer " + token}


def body(arguments=None):
    values = deepcopy(arguments or {"manifest": {}, "expected_manifest_sha256": "a" * 64,
        "artifact_bytes": {}, "context": {"version": "scientific-import-context/1.0.0",
            "material_id": "synthetic:existing-material", "expected_material_row_sha256": "b" * 64,
            "force_constants": None}, "force_constants_bytes": None})
    values["artifact_bytes_base64"] = {key: base64.b64encode(value).decode()
        for key, value in values.pop("artifact_bytes").items()}
    sidecar = values.pop("force_constants_bytes")
    values["force_constants_bytes_base64"] = None if sidecar is None else base64.b64encode(sidecar).decode()
    return {**values, "request_key": "synthetic-http:" + uuid4().hex}


def private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers and "location" not in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.fixture
def controlled_service(monkeypatch):
    """Actual SQL markers; only the scientific service implementation is doubled."""
    import services
    name = "services.scientific_pending_import"
    try:
        service = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        service = ModuleType(name)
        monkeypatch.setitem(sys.modules, name, service)
        monkeypatch.setattr(services, "scientific_pending_import", service, raising=False)
    attempt_id, package_id = str(uuid4()), str(uuid4())
    prefix = "synthetic-import-http:" + attempt_id
    calls = []
    cache = Base.metadata.tables["stats_cache"]

    def dto(status, *, replayed=False):
        return {"attempt_id": attempt_id, "package_id": package_id, "request_sha256": "a" * 64,
            "status": status, "outcome_id": None if status == "outcome_unknown" else str(uuid4()),
            "report_sha256": None, "report": None, "actor_grant_id": str(uuid4()), "replayed": replayed,
            "authority": {"scientific_accepted": False, "ml_training_approved": False,
                          "public_release": False, "execution_attested": False}}

    async def value(db, suffix):
        return await db.scalar(sa.select(cache.c.value).where(cache.c.key == prefix + suffix))

    async def insert(db, suffix, value):
        await add(db, "stats_cache", key=prefix + suffix, value=value)

    def prepare_input(**arguments):
        calls.append(("prepare", arguments))
        return arguments

    def compile_input(package):
        calls.append(("compile", package))
        return {"synthetic_prepared": True}

    async def start_import(db, **arguments):
        calls.append(("start", arguments))
        assert await db.scalar(sa.text("SHOW transaction_isolation")) == "serializable"
        terminal = await value(db, ":terminal")
        if terminal is not None:
            return {**terminal, "replayed": True}
        previous = await value(db, ":start")
        if previous is not None:
            return {**previous, "replayed": True}
        result = dto("outcome_unknown")
        await insert(db, ":start", result)
        return result

    async def finish_import(db, **arguments):
        calls.append(("finish", arguments))
        assert await value(db, ":start") is not None
        result = dto("success_pending")
        await insert(db, ":effects", {"synthetic": True})
        await insert(db, ":terminal", result)
        return result

    async def fail_import(db, **arguments):
        calls.append(("fail", arguments))
        terminal = await value(db, ":terminal")
        if terminal is not None:
            return {**terminal, "replayed": True}
        assert await value(db, ":start") is not None
        result = dto("failed")
        result["report"] = {"reason_code": arguments["reason_code"]}
        await insert(db, ":terminal", result)
        return result

    async def preview_import(db, **arguments):
        calls.append(("preview", arguments))
        await insert(db, ":preview", {"synthetic": True})
        return dto("success_pending")

    async def inspect_import(db, **arguments):
        calls.append(("inspect", arguments))
        assert await db.scalar(sa.text("SHOW transaction_read_only")) == "on"
        result = await value(db, ":terminal") or await value(db, ":start")
        if result is None:
            raise ValueError("missing_attempt")
        return result

    async def material_binding(db, **arguments):
        calls.append(("binding", arguments))
        return {"material_id": arguments["material_id"], "material_row_sha256": "b" * 64, "material_formula": "MgB2"}

    for function in (prepare_input, compile_input, start_import, finish_import, fail_import,
                     preview_import, inspect_import, material_binding):
        monkeypatch.setattr(service, function.__name__, function, raising=False)
    return {"service": service, "attempt_id": attempt_id, "calls": calls, "value": value, "prefix": prefix}


@pytest.mark.parametrize("path", ["", "/material-bindings/known", "/" + str(uuid4())])
async def test_all_routes_require_authentication(client, path):
    response = await client.post(BASE, json=body()) if not path else await client.get(BASE + path)
    assert response.status_code == 401
    private(response)


@pytest.mark.parametrize("role", ["admin", "member", "reviewer", "publisher"])
async def test_only_explicit_active_curator_is_admitted_before_upload(client, db_session, monkeypatch, role):
    people = await actors(db_session)
    await db_session.commit()

    async def forbidden(*args, **kwargs):
        pytest.fail("Unauthorized user reached upload")

    monkeypatch.setattr(router, "_body", forbidden)
    for path in ("", "/material-bindings/known", "/" + str(uuid4())):
        response = await client.post(BASE, json=body(), headers=auth(people[role])) if not path else await client.get(
            BASE + path, headers=auth(people[role]))
        assert response.status_code == 403, response.text
        private(response)


@pytest.mark.parametrize("changes", [
    {"actor_user_id": str(uuid4())}, {"actor_grant_id": str(uuid4())}, {"session_version": 0},
    {"dry_run": 0}, {"dry_run": "false"}, {"dry_run": None}, {"dry_run": []},
    {"scientific_accepted": True}, {"ml_training_approved": False},
])
async def test_closed_strict_body_rejects_actor_and_approval_spoofing(client, db_session, changes):
    people = await actors(db_session)
    await db_session.commit()
    response = await client.post(BASE, json={**body(), **changes}, headers=auth(people["curator"]))
    assert response.status_code == 400, response.text
    private(response)


@pytest.mark.parametrize("raw", [b'{"dry_run":true,"dry_run":false}', b'{"secret":NaN}', b'{"secret":1e999}',
    b'{"secret":"\\ud800"}', b'{"secret":"\xff"}', b'[]', b'{"secret":'])
async def test_invalid_json_never_echoes_source(client, db_session, raw):
    people = await actors(db_session)
    await db_session.commit()
    response = await client.post(BASE, content=raw, headers={**auth(people["curator"]), "Content-Type": "application/json"})
    assert response.status_code == 400
    assert "secret" not in response.text
    private(response)


@pytest.mark.parametrize("case", ["header_size", "stream_size", "content_type", "encoding", "artifact_size",
    "package_total", "fc_size", "whitespace", "padding", "noncanonical", "sidecar_missing", "sidecar_extra"])
async def test_upload_and_decoded_limits(client, db_session, controlled_service, monkeypatch, case):
    people = await actors(db_session)
    await db_session.commit()
    request = body()
    headers = {**auth(people["curator"]), "Content-Type": "application/json"}
    expected = 413
    if case == "header_size":
        headers["Content-Length"] = str(router.MAX_REQUEST_BYTES + 1)
    elif case == "stream_size":
        monkeypatch.setattr(router, "MAX_REQUEST_BYTES", 8)
    elif case == "content_type":
        headers["Content-Type"] = "text/plain"
        expected = 415
    elif case == "encoding":
        headers["Content-Encoding"] = "gzip"
        expected = 415
    elif case in {"artifact_size", "package_total"}:
        request["artifact_bytes_base64"] = {"c" * 64: "YWJjZGU="}
        monkeypatch.setattr(router, "MAX_ARTIFACT_BYTES" if case == "artifact_size" else "MAX_PACKAGE_BYTES", 4)
    elif case == "fc_size":
        request["context"]["force_constants"] = {"logical_name": "synthetic.fc", "sha256": "c" * 64, "size_bytes": 5}
        request["force_constants_bytes_base64"] = "YWJjZGU="
        monkeypatch.setattr(router, "MAX_FORCE_CONSTANT_BYTES", 4)
    elif case in {"whitespace", "padding", "noncanonical"}:
        request["artifact_bytes_base64"] = {"c" * 64: {"whitespace": "eA==\n", "padding": "eA=", "noncanonical": "eB=="}[case]}
        expected = 400
    elif case == "sidecar_missing":
        request["context"]["force_constants"] = {"logical_name": "synthetic.fc", "sha256": "c" * 64, "size_bytes": 1}
        expected = 400
    else:
        request["force_constants_bytes_base64"] = "eA=="
        expected = 400

    async def pieces():
        encoded = json.dumps(request).encode()
        yield encoded[:8]
        yield encoded[8:]

    response = await client.post(BASE, content=pieces(), headers=headers)
    assert response.status_code == expected, response.text
    assert controlled_service["calls"] == []
    private(response)


async def test_cookie_writes_require_origin(client, registered_user):
    from config import get_settings
    from services.session_config import build_browser_session_config
    _, token = registered_user
    settings = get_settings()
    cookie = build_browser_session_config(settings.environment, settings.jwt_expiry_hours * 3600).cookie_name
    client.cookies.set(cookie, token)
    response = await client.post(BASE, json=body())
    assert response.status_code == 403
    private(response)


async def test_default_preview_rolls_back_all_service_writes(client, db_session, controlled_service):
    from tests.test_research_freeze import state
    people = await actors(db_session)
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    response = await client.post(BASE, json=body(), headers=auth(people["curator"]))
    assert response.status_code == 200, response.text
    assert response.json()["dry_run"] is True and response.json()["committed"] is False
    assert [name for name, _ in controlled_service["calls"]] == ["prepare", "compile", "preview"]
    assert await state(db_session) == before
    private(response)


async def test_explicit_start_finish_commit_and_exact_replay(client, db_session, controlled_service):
    from tests.test_research_freeze import state
    people = await actors(db_session)
    await db_session.commit()
    request = {**body(), "dry_run": False}
    response = await client.post(BASE, json=request, headers=auth(people["curator"]))
    assert response.status_code == 200, response.text
    assert response.json()["committed"] is True
    assert response.json()["result"]["status"] == "success_pending"
    assert await controlled_service["value"](db_session, ":start") is not None
    assert await controlled_service["value"](db_session, ":effects") is not None
    before = await state(db_session)
    await db_session.rollback()
    response = await client.post(BASE, json=request, headers=auth(people["curator"]))
    assert response.status_code == 200 and response.json()["result"]["replayed"] is True
    assert [name for name, _ in controlled_service["calls"]].count("compile") == 1
    assert await state(db_session) == before
    private(response)


async def test_auth_and_write_connections_are_closed_during_worker(client, db_session, controlled_service, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    engine = router.get_engine()
    active = set()
    sa.event.listen(engine.sync_engine.pool, "checkout", lambda connection, record, proxy: active.add(id(connection)))
    sa.event.listen(engine.sync_engine.pool, "checkin", lambda connection, record: active.discard(id(connection)))
    monkeypatch.setattr(router, "get_engine", lambda: engine)
    service = controlled_service["service"]
    original_prepare, original_compile = service.prepare_input, service.compile_input

    def prepare(**kwargs):
        assert not active
        return original_prepare(**kwargs)

    def compile(package):
        assert not active
        return original_compile(package)

    monkeypatch.setattr(service, "prepare_input", prepare)
    monkeypatch.setattr(service, "compile_input", compile)
    try:
        response = await client.post(BASE, json={**body(), "dry_run": False}, headers=auth(people["curator"]))
        assert response.status_code == 200, response.text
        assert not active
    finally:
        await engine.dispose()


@pytest.mark.parametrize("failure", ["parse", "finish", "serialize", "commit"])
async def test_failure_retains_committed_start_and_independent_failed_terminal(client, db_session, controlled_service, monkeypatch, failure):
    people = await actors(db_session)
    await db_session.commit()
    service = controlled_service["service"]
    original = service.finish_import

    def parse(package):
        raise RuntimeError("PRIVATE-SOURCE-BYTES")

    async def finish(db, **kwargs):
        result = await original(db, **kwargs)
        if failure == "finish":
            raise SQLAlchemyError("PRIVATE-SOURCE-BYTES")
        if failure == "serialize":
            return {"private": object()}
        await db.execute(sa.text("CREATE TEMP TABLE scientific_commit_probe (id integer PRIMARY KEY, "
            "parent_id integer REFERENCES scientific_commit_probe(id) DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP"))
        await db.execute(sa.text("INSERT INTO scientific_commit_probe VALUES (1,2)"))
        return result

    monkeypatch.setattr(service, "compile_input", parse) if failure == "parse" else monkeypatch.setattr(service, "finish_import", finish)
    response = await client.post(BASE, json={**body(), "dry_run": False}, headers=auth(people["curator"]))
    assert response.status_code == 503, response.text
    assert "PRIVATE" not in response.text and "committed" not in response.json()
    assert await controlled_service["value"](db_session, ":start") is not None
    assert await controlled_service["value"](db_session, ":effects") is None
    terminal = await controlled_service["value"](db_session, ":terminal")
    assert terminal["status"] == "failed"
    assert terminal["report"]["reason_code"] == ("parser_failed" if failure == "parse" else "import_failed")
    private(response)


async def test_failed_start_commit_never_starts_parser_or_claims_durability(client, db_session, controlled_service, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    service = controlled_service["service"]
    original = service.start_import

    async def start(db, **kwargs):
        result = await original(db, **kwargs)
        await db.execute(sa.text("CREATE TEMP TABLE scientific_start_probe (id integer PRIMARY KEY, "
            "parent_id integer REFERENCES scientific_start_probe(id) DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP"))
        await db.execute(sa.text("INSERT INTO scientific_start_probe VALUES (1,2)"))
        return result

    monkeypatch.setattr(service, "start_import", start)
    response = await client.post(BASE, json={**body(), "dry_run": False}, headers=auth(people["curator"]))
    assert response.status_code == 503
    assert "compile" not in [name for name, _ in controlled_service["calls"]]
    assert await controlled_service["value"](db_session, ":start") is None
    assert await controlled_service["value"](db_session, ":terminal") is None
    private(response)


async def test_lost_finish_ack_never_overwrites_actual_committed_terminal(client, db_session, controlled_service, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    original = router._write

    async def lost_ack(actor, function, arguments, **kwargs):
        result = await original(actor, function, arguments, **kwargs)
        if function is controlled_service["service"].finish_import:
            raise SQLAlchemyError("simulated missing acknowledgement after real commit")
        return result

    monkeypatch.setattr(router, "_write", lost_ack)
    response = await client.post(BASE, json={**body(), "dry_run": False}, headers=auth(people["curator"]))
    assert response.status_code == 503 and "committed" not in response.json()
    assert (await controlled_service["value"](db_session, ":terminal"))["status"] == "success_pending"
    assert await controlled_service["value"](db_session, ":effects") is not None
    assert "fail" not in [name for name, _ in controlled_service["calls"]]


@pytest.mark.parametrize("change", ["grant", "session", "inactive", "unverified"])
async def test_live_actor_change_after_capture_prevents_start(client, db_session, controlled_service, monkeypatch, change):
    from services.research_publication import revoke_role
    people = await actors(db_session)
    await db_session.commit()
    original = router._body

    async def changed(request):
        value = await original(request)
        if change == "grant":
            await revoke_role(db_session, actor_user_id=people["admin"], grant_id=people["grants"]["curator"],
                              reason_code="synthetic_capture_change", dry_run=False)
        else:
            column, updated = {"session": ("session_version", 1), "inactive": ("is_active", False),
                               "unverified": ("email_verified", False)}[change]
            users = Base.metadata.tables["users"]
            await db_session.execute(users.update().where(users.c.id == people["curator"]).values(**{column: updated}))
        await db_session.commit()
        return value

    monkeypatch.setattr(router, "_body", changed)
    response = await client.post(BASE, json={**body(), "dry_run": False}, headers=auth(people["curator"]))
    assert response.status_code == 403, response.text
    assert "start" not in [name for name, _ in controlled_service["calls"]]
    assert await controlled_service["value"](db_session, ":start") is None
    private(response)


async def test_revocation_during_parse_leaves_unknown_not_authorized_success(client, db_session, controlled_service, monkeypatch):
    from services.research_publication import revoke_role
    people = await actors(db_session)
    await db_session.commit()
    original = router._worker

    async def changed(function, *args, **kwargs):
        result = await original(function, *args, **kwargs)
        if function is controlled_service["service"].compile_input:
            await revoke_role(db_session, actor_user_id=people["admin"], grant_id=people["grants"]["curator"],
                              reason_code="synthetic_parse_change", dry_run=False)
            await db_session.commit()
        return result

    monkeypatch.setattr(router, "_worker", changed)
    response = await client.post(BASE, json={**body(), "dry_run": False}, headers=auth(people["curator"]))
    assert response.status_code == 403
    assert (await controlled_service["value"](db_session, ":start"))["status"] == "outcome_unknown"
    assert await controlled_service["value"](db_session, ":terminal") is None
    assert await controlled_service["value"](db_session, ":effects") is None


@pytest.mark.parametrize("cause", ["cancel", "timeout"])
async def test_parser_capacity_remains_held_until_actual_thread_finishes(monkeypatch, cause):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(router, "_worker_slots", slots)
    monkeypatch.setattr(router, "WORKER_TIMEOUT", 0.1 if cause == "timeout" else 10)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow():
        entered.set()
        try:
            assert release.wait(5)
        finally:
            finished.set()

    task = asyncio.create_task(router._worker(slow))
    try:
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        if cause == "cancel":
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cause == "cancel" else TimeoutError):
            await task
        with pytest.raises(router.HTTPException) as error:
            await router._worker(lambda: None)
        assert error.value.status_code == 503 and not finished.is_set()
    finally:
        release.set()
        for _ in range(200):
            if finished.is_set():
                break
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.01)
        await asyncio.gather(task, return_exceptions=True)
    assert await router._worker(lambda: "ready") == "ready"


async def test_private_inspection_and_material_route_use_fresh_readonly_scope(client, db_session, controlled_service):
    people = await actors(db_session)
    await db_session.commit()
    response = await client.post(BASE, json={**body(), "dry_run": False}, headers=auth(people["curator"]))
    assert response.status_code == 200, response.text
    response = await client.get(BASE + "/" + controlled_service["attempt_id"], headers=auth(people["curator"]))
    assert response.status_code == 200 and response.json()["status"] == "success_pending"
    private(response)
    response = await client.get(BASE + "/material-bindings/synthetic:string-id", headers=auth(people["curator"]))
    assert response.status_code == 200, response.text
    assert response.json() == {"material_id": "synthetic:string-id", "material_row_sha256": "b" * 64,
                              "material_formula": "MgB2"}
    private(response)


async def test_closed_upload_schema_is_in_openapi():
    from main import app
    schema = app.openapi()["paths"][BASE]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["dry_run"]["default"] is True
    assert "actor_user_id" not in schema["properties"]


async def test_real_package_preview_import_retained_bytes_and_idempotent_http_replay(client, db_session):
    import hashlib

    from tests.test_research_freeze import state
    from tests.test_scientific_pending_import import UNTOUCHED_TABLES, seed_import
    fixture = await seed_import(db_session)
    await db_session.commit()
    headers, request = auth(fixture["actors"]["curator"]), body(fixture["args"])
    before = await state(db_session)
    await db_session.rollback()
    preview = await client.post(BASE, json=request, headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["dry_run"] is True and preview.json()["committed"] is False
    assert preview.json()["result"]["status"] == "success_pending"
    assert await state(db_session) == before
    await db_session.rollback()
    response = await client.post(BASE, json={**request, "dry_run": False}, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert response.json()["committed"] is True and result["status"] == "success_pending"
    assert all(flag is False for flag in result["authority"].values())
    after = await state(db_session)
    for name in UNTOUCHED_TABLES:
        assert after[name] == before[name], name
    properties = [row for row in after["event_properties"] if row["id"] == result["row_ids"]["property"]]
    assert len(properties) == 1
    assert properties[0]["raw"]["scientific_review"] == "pending"
    event = next(row for row in after["research_events"] if row["id"] == result["row_ids"]["event"])
    assert event["review_status"] == event["validity_status"] == "pending"
    assert properties[0]["property_key"] == "phonon_min_frequency"
    assert properties[0]["value"] == pytest.approx(-0.0299792458)
    assert properties[0]["unit"] == "THz"
    candidate = result["report"]["preflight"]["parse_result"]["property_candidates"][0]
    assert candidate["source_raw_text"] == "-1.0000" and candidate["source_unit"] == "cm^-1"
    assert result["costs"]["cost_scope"] == "parser_worker_only"
    for name in ("calculation_cpu_seconds", "calculation_wall_seconds", "calculation_monetary_cost"):
        assert result["costs"][name] is None
    from uuid import UUID
    blobs = Base.metadata.tables["scientific_import_blobs"]
    values = (await db_session.execute(sa.select(blobs).where(blobs.c.package_id == UUID(result["package_id"])))).mappings().all()
    retained = {row["bytes_sha256"]: bytes(row["payload"]) for row in values}
    for raw in (fixture["input_bytes"], fixture["frequency_bytes"], fixture["fc_bytes"]):
        assert retained[hashlib.sha256(raw).hexdigest()] == raw
    await db_session.rollback()
    repeated = await client.post(BASE, json={**request, "dry_run": False}, headers=headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["result"] == {**result, "replayed": True}
    assert await state(db_session) == after
    await db_session.rollback()
    inspected = await client.get(BASE + "/" + result["attempt_id"], headers=headers)
    assert inspected.status_code == 200 and inspected.json()["status"] == "success_pending"
    binding = await client.get(BASE + "/material-bindings/" + fixture["material"], headers=headers)
    assert binding.status_code == 200, binding.text
    assert binding.json() == {"material_id": fixture["material"], "material_formula": "AlAs",
        "material_row_sha256": fixture["args"]["context"]["expected_material_row_sha256"]}
    for value in (preview, response, repeated, inspected, binding):
        private(value)


@pytest.mark.parametrize("options", [{"missing_fc": True}, {"bad_fc": True}, {"geometry": "other"}])
async def test_real_incomplete_context_is_durable_quarantine_without_scientific_rows(client, db_session, options):
    from tests.test_research_freeze import state
    from tests.test_scientific_pending_import import SCIENCE_TABLES, UNTOUCHED_TABLES, seed_import
    fixture = await seed_import(db_session, **options)
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    response = await client.post(BASE, json={**body(fixture["args"]), "dry_run": False},
                                 headers=auth(fixture["actors"]["curator"]))
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["status"] == "quarantined" and result["row_ids"] is None
    assert result["report"]["reason_codes"]
    assert all(value is False for value in result["authority"].values())
    after = await state(db_session)
    for name in (*SCIENCE_TABLES, *UNTOUCHED_TABLES):
        assert after[name] == before[name], name
    assert len(after["scientific_import_attempts"]) == len(before["scientific_import_attempts"]) + 1
    assert len(after["scientific_import_outcomes"]) == len(before["scientific_import_outcomes"]) + 1
    private(response)


async def test_real_material_pin_change_during_parse_cannot_create_pending_rows(client, db_session, monkeypatch):
    from services import scientific_pending_import as service
    from tests.test_research_freeze import state
    from tests.test_scientific_pending_import import SCIENCE_TABLES, seed_import
    fixture = await seed_import(db_session)
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    original = router._worker

    async def changed(function, *args, **kwargs):
        result = await original(function, *args, **kwargs)
        if function is service.compile_input:
            materials = Base.metadata.tables["materials"]
            await db_session.execute(materials.update().where(materials.c.id == fixture["material"]).values(formula="MgB2"))
            await db_session.commit()
        return result

    monkeypatch.setattr(router, "_worker", changed)
    response = await client.post(BASE, json={**body(fixture["args"]), "dry_run": False},
                                 headers=auth(fixture["actors"]["curator"]))
    assert response.status_code == 200, response.text
    after = await state(db_session)
    for name in SCIENCE_TABLES:
        assert after[name] == before[name], name
    added = [row for row in after["scientific_import_outcomes"] if row not in before["scientific_import_outcomes"]]
    assert len(added) == 1 and added[0]["outcome"] == "quarantined"
    assert response.json()["result"]["status"] == "quarantined"
    assert "stale_material_binding" in response.json()["result"]["report"]["reason_codes"]
    private(response)


async def test_actual_pending_finish_commit_failure_preserves_only_start_and_failed_receipt(client, db_session, monkeypatch):
    from services import scientific_pending_import as service
    from tests.test_research_freeze import state
    from tests.test_scientific_pending_import import SCIENCE_TABLES, UNTOUCHED_TABLES, seed_import
    fixture = await seed_import(db_session)
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    original = service.finish_import
    returned = []

    async def fail_at_commit(db, **kwargs):
        result = await original(db, **kwargs)
        assert result["status"] == "success_pending"
        returned.append(result)
        await db.execute(sa.text("CREATE TEMP TABLE actual_pending_commit_probe (id integer PRIMARY KEY, "
            "parent_id integer REFERENCES actual_pending_commit_probe(id) DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP"))
        await db.execute(sa.text("INSERT INTO actual_pending_commit_probe VALUES (1,2)"))
        return result

    monkeypatch.setattr(service, "finish_import", fail_at_commit)
    response = await client.post(BASE, json={**body(fixture["args"]), "dry_run": False},
                                 headers=auth(fixture["actors"]["curator"]))
    assert response.status_code == 503 and len(returned) == 1, response.text
    after = await state(db_session)
    for name in (*SCIENCE_TABLES, *UNTOUCHED_TABLES):
        assert after[name] == before[name], name
    starts = [row for row in after["scientific_import_attempts"] if row not in before["scientific_import_attempts"]]
    outcomes = [row for row in after["scientific_import_outcomes"] if row not in before["scientific_import_outcomes"]]
    assert len(starts) == len(outcomes) == 1
    assert starts[0]["id"] == outcomes[0]["attempt_id"] == returned[0]["attempt_id"]
    assert outcomes[0]["outcome"] == "failed" and outcomes[0]["reason_codes"] == ["import_failed"]
    assert outcomes[0]["row_snapshots_json"] is None
    private(response)


@pytest.mark.parametrize("case", ["request_key_conflict", "already_imported", "stale_material"])
@pytest.mark.parametrize("dry_run", [True, False])
async def test_exact_real_conflicts_are_409_and_preserve_every_database_row(client, db_session, case, dry_run):
    from tests.test_research_freeze import state
    from tests.test_scientific_pending_import import seed_import
    fixture = await seed_import(db_session)
    await db_session.commit()
    headers = auth(fixture["actors"]["curator"])
    request = {**body(fixture["args"]), "dry_run": False}
    if case in {"request_key_conflict", "already_imported"}:
        response = await client.post(BASE, json=request, headers=headers)
        assert response.status_code == 200 and response.json()["result"]["status"] == "success_pending", response.text
        if case == "request_key_conflict":
            # Another internally valid package under the SAME key is not an
            # exact replay and must not become a new quarantine/import attempt.
            request["context"]["force_constants"] = None
            request["force_constants_bytes_base64"] = None
        else:
            request["request_key"] = "synthetic-new-key:" + uuid4().hex
    else:
        material = Base.metadata.tables["materials"]
        await db_session.execute(material.update().where(material.c.id == fixture["material"]).values(formula="MgB2"))
        await db_session.commit()
    request["dry_run"] = dry_run
    before = await state(db_session)
    await db_session.rollback()
    response = await client.post(BASE, json=request, headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Scientific import changed; retry"
    assert "committed" not in response.json() and "result" not in response.json()
    assert await state(db_session) == before
    private(response)


async def test_unexpected_error_with_conflict_like_text_remains_unavailable(client, db_session, controlled_service, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()

    def fail(package):
        raise RuntimeError("import_request_key_conflict")

    monkeypatch.setattr(controlled_service["service"], "compile_input", fail)
    response = await client.post(BASE, json={**body(), "dry_run": False}, headers=auth(people["curator"]))
    assert response.status_code == 503
    assert (await controlled_service["value"](db_session, ":terminal"))["status"] == "failed"
    private(response)


async def test_failure_recovery_database_unavailable_retains_only_unknown_start(client, db_session, controlled_service, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    service = controlled_service["service"]

    def parse(package):
        raise RuntimeError("private parse failure")

    async def recovery_unavailable(db, **kwargs):
        raise SQLAlchemyError("private unavailable database")

    monkeypatch.setattr(service, "compile_input", parse)
    monkeypatch.setattr(service, "inspect_import", recovery_unavailable)
    response = await client.post(BASE, json={**body(), "dry_run": False}, headers=auth(people["curator"]))
    assert response.status_code == 503 and "private" not in response.text
    assert (await controlled_service["value"](db_session, ":start"))["status"] == "outcome_unknown"
    assert await controlled_service["value"](db_session, ":terminal") is None
    assert await controlled_service["value"](db_session, ":effects") is None


async def test_http_capacity_bounds_upload_and_reads_without_wait_queue(client, db_session, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(router, "_request_slots", slots)
    assert slots.acquire(blocking=False)
    try:
        for suffix in ("", "/material-bindings/known", "/" + str(uuid4())):
            response = await client.post(BASE, json=body(), headers=auth(people["curator"])) if not suffix else await client.get(
                BASE + suffix, headers=auth(people["curator"]))
            assert response.status_code == 503 and response.headers["retry-after"] == "1"
            private(response)
    finally:
        slots.release()


async def test_cancelled_waiters_cannot_create_unbounded_recovery_jobs(monkeypatch):
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(router, "_recovery_slots", slots)
    monkeypatch.setattr(router, "RECOVERY_TIMEOUT", 5)
    held = asyncio.Event()
    entered, completed = [], []
    previous = set(router._recovery_tasks)

    async def read(actor, function, **kwargs):
        entered.append(kwargs["attempt_id"])
        await held.wait()
        return {"status": "outcome_unknown"}

    async def write(actor, function, arguments, **kwargs):
        completed.append(arguments["attempt_id"])
        return {"status": "failed"}

    monkeypatch.setattr(router, "_read", read)
    monkeypatch.setattr(router, "_write", write)
    actor = router.Actor(uuid4(), uuid4(), 0)
    try:
        for index in range(10):
            task = asyncio.create_task(router._recover(actor, {"attempt_id": str(uuid4())}, "import_cancelled"))
            await asyncio.sleep(0.01)
            if index < 2:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await asyncio.wait_for(task, 0.1)
        assert len(entered) == 2 and len(router._recovery_tasks - previous) == 2
        assert not slots.acquire(blocking=False)
    finally:
        held.set()
        remaining = tuple(router._recovery_tasks - previous)
        await asyncio.gather(*remaining, return_exceptions=True)
        await asyncio.sleep(0)
    assert len(completed) == 2 and router._recovery_tasks == previous
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)
    slots.release()
    slots.release()


async def test_actual_http_cancellation_audits_start_without_late_sql_write(client, db_session, controlled_service, monkeypatch):
    from tests.test_research_freeze import state
    people = await actors(db_session)
    await db_session.commit()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow(package):
        entered.set()
        try:
            assert release.wait(5)
            return {"synthetic_prepared": True}
        finally:
            finished.set()

    monkeypatch.setattr(controlled_service["service"], "compile_input", slow)
    task = asyncio.create_task(client.post(BASE, json={**body(), "dry_run": False}, headers=auth(people["curator"])))
    try:
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # The cancelled ASGI client can return before the shielded recovery
        # transaction. Wait for its bounded completion, not a stale SQL snapshot.
        for _ in range(200):
            if "fail" in [name for name, _ in controlled_service["calls"]] and not router._recovery_tasks:
                break
            await asyncio.sleep(0.01)
        assert await controlled_service["value"](db_session, ":start") is not None
        terminal = await controlled_service["value"](db_session, ":terminal")
        assert terminal is not None, {"calls": [name for name, _ in controlled_service["calls"]],
                                      "pending_recoveries": len(router._recovery_tasks)}
        assert terminal["status"] == "failed" and terminal["report"]["reason_code"] == "import_cancelled"
        assert await controlled_service["value"](db_session, ":effects") is None
        before = await state(db_session)
        await db_session.rollback()
    finally:
        release.set()
        for _ in range(200):
            if finished.is_set():
                break
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.01)
        await asyncio.gather(task, return_exceptions=True)
    assert await state(db_session) == before
