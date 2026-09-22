"""Actual public HTTP admission over synthetic two-scope reviewed SQL data.

Fixtures create explicit test-only grants, not scientific or licensing evidence.
Every test uses the guarded native/disposable runner; no source files/providers.
"""
from __future__ import annotations

import asyncio
import threading
from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

from config import get_settings
from routers import discovery_scientific as routes
from services import discovery_projection_governance as governance
from tests.test_discovery_projection_governance import reviewed_publication
from tests.test_discovery_scientific_cells import CANARY, read_settings
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state
from tests.test_scientific_adjudication_schema import decision_for, item_for, request_for

URL = "/v1/discovery/scientific"


@pytest_asyncio.fixture(loop_scope="function")
async def published(db_session, monkeypatch):
    context = await reviewed_publication(db_session)
    await db_session.commit()
    await read_settings(db_session)
    settings = get_settings()
    bundle = context["fixture"]["bundle"]
    monkeypatch.setattr(settings, "discovery_scientific_public_enabled", True)
    monkeypatch.setattr(settings, "discovery_scientific_approved_projections", {
        context["registered"]["package_id"]: context["registered"]["payload_sha256"]})
    monkeypatch.setattr(settings, "discovery_rps_public_enabled", True)
    monkeypatch.setattr(settings, "discovery_rps_approved_releases", {
        bundle["release"]["id"]: bundle["release"]["manifest_sha256"]})
    monkeypatch.setattr(settings, "discovery_rps_approved_public_bundles", {
        bundle["release"]["id"]: bundle["bundle_sha256"]})
    try:
        yield context
    finally:
        # Committed fixture history is retained; keep its synthetic material out
        # of unrelated catalogue tests which share this disposable schema.
        await db_session.rollback()
        await read_settings(db_session)
        await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"),
            {"id": context["fixture"]["source"]["material"]})
        await db_session.commit()


def path(context):
    return URL + "/" + context["registered"]["package_id"]


def safe(response):
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "etag" not in response.headers and "last-modified" not in response.headers
    for value in (CANARY, "Traceback", "postgresql", "password", "/Users/"):
        assert value not in response.text


async def test_default_off_and_unapproved_ids_never_open_database(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "discovery_scientific_public_enabled", False)
    def forbidden():
        pytest.fail("disabled public surface opened database")
    monkeypatch.setattr(routes, "get_engine", forbidden)
    for url in (URL, URL + "/" + str(uuid4())):
        response = await client.get(url)
        assert response.status_code == 404
        safe(response)
    monkeypatch.setattr(settings, "discovery_scientific_public_enabled", True)
    monkeypatch.setattr(settings, "discovery_rps_public_enabled", True)
    monkeypatch.setattr(settings, "discovery_scientific_approved_projections", {})
    response = await client.get(URL + "/" + str(uuid4()))
    assert response.status_code == 404
    safe(response)


async def test_actual_two_fresh_readonly_snapshots_and_no_database_changes(client, published, db_session, monkeypatch):
    observed = []
    original = governance.admitted_projection
    async def inspect(db, identifier):
        row = (await db.execute(sa.text("SELECT current_setting('transaction_isolation'),"
            "current_setting('transaction_read_only'),current_setting('TimeZone'),"
            "current_setting('statement_timeout'),txid_current_snapshot()::text"))).one()
        observed.append((db, tuple(row)))
        return await original(db, identifier)
    monkeypatch.setattr(governance, "admitted_projection", inspect)
    before = await state(db_session)
    await db_session.commit()
    response = await client.get(path(published), headers={"If-None-Match": "*", "If-Modified-Since": "Wed, 01 Jan 2099 00:00:00 GMT"})
    assert response.status_code == 200, response.text
    safe(response)
    assert len(observed) == 2 and observed[0][0] is not observed[1][0]
    assert all(row[:4] == ("repeatable read", "on", "UTC", "5s") for _, row in observed)
    value = response.json()
    assert value["payload_sha256"] == published["registered"]["payload_sha256"]
    assert value["payload"]["rows"][0]["cells"]
    observations = [item for cell in value["payload"]["rows"][0]["cells"] for item in cell["observations"]]
    assert len(observations) == 1 and observations[0]["scientific_scope_accepted"] is True
    assert value["scientific_acceptance"] is value["ml_training_approved"] is False
    await read_settings(db_session)
    assert await state(db_session) == before


async def test_catalog_only_explicit_approved_ids_and_no_failed_private_ids(client, published):
    private = str(uuid4())
    get_settings().discovery_scientific_approved_projections[private] = "1" * 64
    response = await client.get(URL)
    assert response.status_code == 200, response.text
    safe(response)
    body = response.json()
    assert set(body) == {"version", "status", "items", "unavailable_count", "scientific_acceptance", "ml_training_approved"}
    assert body["status"] == "degraded" and body["unavailable_count"] == 1
    assert [row["package_id"] for row in body["items"]] == [published["registered"]["package_id"]]
    assert private not in response.text


@pytest.mark.parametrize("setting", ["discovery_scientific_public_enabled", "discovery_rps_public_enabled"])
async def test_either_switch_blocks_previously_published_payload(client, published, setting):
    setattr(get_settings(), setting, False)
    response = await client.get(path(published), headers={"If-None-Match": "*"})
    assert response.status_code == 404
    safe(response)


@pytest.mark.parametrize("which", ["projection", "release", "bundle"])
async def test_each_independent_config_pin_is_required(client, published, which):
    settings = get_settings()
    field = {"projection": "discovery_scientific_approved_projections", "release": "discovery_rps_approved_releases",
             "bundle": "discovery_rps_approved_public_bundles"}[which]
    mapping = getattr(settings, field)
    mapping[next(iter(mapping))] = "0" * 64
    response = await client.get(path(published))
    assert response.status_code == 404
    safe(response)
    catalog = await client.get(URL)
    assert catalog.status_code == 200 and catalog.json()["status"] == "unavailable"
    assert catalog.json()["items"] == [] and published["registered"]["package_id"] not in catalog.text
    safe(catalog)


@pytest.mark.parametrize("invalid", ["NOT-A-UUID", "00000000-0000-0000-0000-00000000000A", "1" * 1000])
async def test_canonical_uuid_only_with_static_errors(client, invalid):
    response = await client.get(URL + "/" + invalid)
    assert response.status_code == 400
    assert invalid not in response.text
    safe(response)


@pytest.mark.parametrize("mode", ["query", "body", "post"])
async def test_no_free_query_or_body_inputs_or_write_methods(client, published, mode):
    response = (await client.get(path(published) + "?selection=" + CANARY) if mode == "query" else
        await client.request("GET" if mode == "body" else "POST", path(published), content=CANARY))
    assert response.status_code == (405 if mode == "post" else 400)
    safe(response)


@pytest.mark.parametrize("stage", [1, 2])
async def test_hot_config_change_between_passes_returns_no_payload(client, published, monkeypatch, stage):
    original = routes._observe
    calls = 0
    async def change(*args, **kwargs):
        nonlocal calls
        result = await original(*args, **kwargs)
        calls += 1
        if calls == stage:
            get_settings().discovery_scientific_approved_projections.clear()
        return result
    monkeypatch.setattr(routes, "_observe", change)
    response = await client.get(path(published))
    assert response.status_code == 409
    safe(response)
    assert "payload" not in response.json() and calls == stage


@pytest.mark.parametrize("change", ["withdraw", "reviewer", "source", "scientific_head"])
async def test_new_snapshot_catches_hot_database_governance_changes(client, published, db_session, monkeypatch, change):
    original = routes._observe
    calls = 0
    async def change_after_read(*args, **kwargs):
        nonlocal calls
        result = await original(*args, **kwargs)
        calls += 1
        if calls == 1:
            await read_settings(db_session)
            if change == "withdraw":
                await governance.projection_action(db_session, **{**published["action_arguments"],
                    "request_key": uuid4().hex, "kind": "withdraw"}, dry_run=False)
            elif change == "reviewer":
                await db_session.execute(sa.text("UPDATE users SET is_active=false WHERE id=:id"),
                    {"id": published["fixture"]["actors"]["reviewer"]})
            elif change == "source":
                await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"),
                    {"id": published["fixture"]["source"]["material"]})
            else:
                current = published["fixture"]
                prop = current["source"]["properties"][0]
                subject = (await db_session.execute(sa.text("SELECT * FROM scientific_result_subjects WHERE property_id=:id"),
                    {"id": prop["id"]})).mappings().one()
                item = await item_for(db_session, subject, profile="recorded-sampled-frequency-fidelity/1.0.0",
                    decision="reject", predecessor=current["decisions"][0]["id"])
                people = current["actors"]
                request = await request_for(db_session, {"reviewer": people["reviewer"],
                    "grant": {"id": people["grants"]["reviewer"]}}, [item])
                await decision_for(db_session, request, subject, item)
                await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
            await db_session.commit()
        return result
    monkeypatch.setattr(routes, "_observe", change_after_read)
    response = await client.get(path(published), headers={"If-None-Match": "*"})
    assert response.status_code in {409, 503}, response.text
    assert calls == 1  # second observation fails before returning a receipt
    safe(response)
    assert "payload" not in response.json()


@pytest.mark.parametrize("error", [ValueError, RuntimeError])
async def test_rebuild_exception_is_static_and_does_not_leak_private_source(client, published, monkeypatch, error):
    async def failed(*args, **kwargs):
        raise error(CANARY + " postgresql://secret:password@private")
    monkeypatch.setattr(governance, "admitted_projection", failed)
    response = await client.get(path(published))
    assert response.status_code == 503
    safe(response)
    catalog = await client.get(URL)
    assert catalog.status_code == (200 if error is ValueError else 503)
    if error is ValueError:
        assert catalog.json()["status"] == "unavailable"
    assert published["registered"]["package_id"] not in catalog.text
    safe(catalog)


async def test_capacity_is_nonblocking_and_releases_its_own_permit(client, published, monkeypatch):
    slots = threading.BoundedSemaphore(2)
    assert slots.acquire(False) and slots.acquire(False)
    monkeypatch.setattr(routes, "_slots", slots)
    response = await client.get(path(published))
    assert response.status_code == 503 and response.headers["retry-after"] == "1"
    safe(response)
    slots.release()
    response = await client.get(path(published))
    assert response.status_code == 200, response.text
    assert slots.acquire(False)
    slots.release()
    slots.release()


async def test_cancellation_closes_snapshot_and_releases_permit(client, published, monkeypatch):
    started = asyncio.Event()
    slots = threading.BoundedSemaphore(2)
    async def wait(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(routes, "_slots", slots)
    monkeypatch.setattr(governance, "admitted_projection", wait)
    pending = asyncio.create_task(client.get(path(published)))
    await asyncio.wait_for(started.wait(), timeout=5)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert slots.acquire(False) and slots.acquire(False)
    slots.release()
    slots.release()


@pytest.mark.parametrize("bad", [True, {"bad": "0" * 64}, {str(uuid4()): True}])
async def test_bad_approval_configuration_is_static_before_database(client, monkeypatch, bad):
    settings = get_settings()
    # Assignment bypass intentionally exercises defensive runtime validation.
    monkeypatch.setattr(settings, "discovery_scientific_approved_projections", bad)
    response = await client.get(URL)
    assert response.status_code == 503
    safe(response)


async def test_catalog_shared_byte_budget_never_silently_truncates(client, published, monkeypatch):
    monkeypatch.setattr(routes, "MAX_OBSERVATION_BYTES", 1)
    response = await client.get(URL)
    assert response.status_code == 503
    safe(response)


async def test_mutated_rebuild_receipt_does_not_serve_a_valid_old_hash(client, published, monkeypatch):
    original = governance.admitted_projection
    async def mutate(*args, **kwargs):
        value = deepcopy(await original(*args, **kwargs))
        value["payload"]["rows"].clear()
        return value
    monkeypatch.setattr(governance, "admitted_projection", mutate)
    response = await client.get(path(published))
    assert response.status_code == 503
    safe(response)


async def test_raw_oversized_query_refused_before_fastapi_query_parsing(client, monkeypatch):
    from starlette.requests import Request

    def forbidden(_):
        pytest.fail("oversized query reached parsed-query access")
    monkeypatch.setattr(Request, "query_params", property(forbidden))
    response = await client.get(URL + "?private=" + CANARY * 50)
    assert response.status_code == 400
    safe(response)


async def test_overlarge_approval_map_refuses_before_database(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "discovery_scientific_approved_projections", {
        str(uuid4()): "0" * 64 for _ in range(26)})
    response = await client.get(URL)
    assert response.status_code == 503
    safe(response)
