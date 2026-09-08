"""Actual private HTTP reads of synthetic native-byte pending scientific results.

No source is scientifically adjudicated or published by this fixture. Complete
SQL snapshots include immutable ledgers, guard epochs, and unrelated tables.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from config import get_settings
from routers import scientific_review as router
from services import auth_service, research_publication
from services import scientific_pending_import as imports
from services import scientific_result_impact as impact
from services.research_release_manifest import digest
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_publication import actors
from tests.test_scientific_pending_import import seed_import

db_session = _serializable_db_session
pytestmark = pytest.mark.asyncio
BASE = "/v1/ml/scientific-review"
UNKNOWN_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
PATHS = ("/capabilities", "/results", "/results/" + UNKNOWN_ID)
PRIVATE_CANARY = "PRIVATE_NATIVE_SCIENTIFIC_SOURCE_DO_NOT_DISCLOSE"


def auth(user_id):
    token, _ = auth_service.create_access_token(user_id)
    return {"Authorization": "Bearer " + token}


def private(response, *, guarded=True):
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers
    assert "last-modified" not in response.headers
    if guarded:
        assert response.headers["x-content-type-options"] == "nosniff"


async def snapshot(db):
    value = await state(db)
    await db.rollback()
    return value


async def pending_result(db):
    fixture = await seed_import(db)
    # This is a real retained native-source comment, not a response-only canary.
    args = deepcopy(fixture["args"])
    old = fixture["input_bytes"]
    raw = b"! " + PRIVATE_CANARY.encode() + b"\n" + old
    old_hash, new_hash = hashlib.sha256(old).hexdigest(), hashlib.sha256(raw).hexdigest()
    args["artifact_bytes"].pop(old_hash)
    args["artifact_bytes"][new_hash] = raw
    for entry in args["manifest"]["files"]:
        if entry["role"] == "input":
            entry.update(sha256=new_hash, size_bytes=len(raw))
    args["expected_manifest_sha256"] = digest(args["manifest"])
    package = imports.prepare_input(**args)
    started = await imports.start_import(db, actor_user_id=fixture["actors"]["curator"],
        request_key="synthetic-read-only-review:" + uuid4().hex, package=package, dry_run=False)
    await db.commit()
    finished = await imports.finish_import(db, actor_user_id=fixture["actors"]["curator"],
        attempt_id=started["attempt_id"], prepared=imports.compile_input(package), dry_run=False)
    await db.commit()
    assert finished["status"] == "success_pending"
    return {**fixture, "started": started, "finished": finished,
            "property_id": finished["row_ids"]["property"], "input_hash": new_hash}


@pytest.mark.parametrize("path", PATHS)
async def test_every_get_requires_authentication(client, path):
    response = await client.get(BASE + path)
    assert response.status_code == 401
    private(response)


@pytest.mark.parametrize("role,expected_roles,can_read", [
    ("member", [], False), ("admin", [], False), ("publisher", ["publisher"], False),
    ("curator", ["curator"], True), ("reviewer", ["reviewer"], True),
])
async def test_capabilities_require_real_roles_not_legacy_flags(client, db_session, role, expected_roles, can_read):
    people = await actors(db_session)
    if role in {"member", "admin"}:
        await db_session.execute(sa.text("UPDATE users SET is_reviewer=true WHERE id=:id"), {"id": people[role]})
    await db_session.commit()
    response = await client.get(BASE + "/capabilities", headers=auth(people[role]))
    assert response.status_code == 200, response.text
    assert response.json() == {"version": "scientific-review-capabilities/1.0.0",
        "roles": expected_roles, "can_read": can_read, "review_write_available": False}
    private(response)


@pytest.mark.parametrize("role", ["member", "admin", "publisher"])
async def test_unprivileged_users_cannot_list_or_probe_result_ids(client, db_session, role):
    people = await actors(db_session)
    await db_session.execute(sa.text("UPDATE users SET is_reviewer=true WHERE id=:id"), {"id": people[role]})
    await db_session.commit()
    before = await snapshot(db_session)
    for path in PATHS[1:]:
        response = await client.get(BASE + path, headers=auth(people[role]))
        assert response.status_code == 403, response.text
        private(response)
        assert "property_id" not in response.text
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("role", ["curator", "reviewer"])
async def test_grant_revocation_is_observed_on_next_request_without_cached_admission(client, db_session, role):
    people = await actors(db_session)
    await db_session.commit()
    headers = auth(people[role])
    initial = await client.get(BASE + "/results", headers=headers)
    assert initial.status_code == 200, initial.text
    await research_publication.revoke_role(db_session, actor_user_id=people["admin"],
        grant_id=people["grants"][role], reason_code="synthetic_review_access_withdrawn", dry_run=False)
    await db_session.commit()
    before = await snapshot(db_session)
    capabilities = await client.get(BASE + "/capabilities", headers={**headers, "If-None-Match": '"old"'})
    assert capabilities.json()["roles"] == []
    assert capabilities.json()["can_read"] is False
    for path in PATHS[1:]:
        response = await client.get(BASE + path, headers={**headers, "If-None-Match": '"old"'})
        assert response.status_code == 403
        private(response)
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("field,value,status", [
    ("is_active", False, 401), ("email_verified", False, 403), ("session_version", 1, 401),
])
async def test_live_user_and_session_flags_are_rechecked(client, db_session, field, value, status):
    people = await actors(db_session)
    await db_session.commit()
    headers = auth(people["curator"])
    assert (await client.get(BASE + "/capabilities", headers=headers)).status_code == 200
    await db_session.execute(sa.text(f"UPDATE users SET {field}=:value WHERE id=:id"),
                             {"value": value, "id": people["curator"]})
    await db_session.commit()
    before = await snapshot(db_session)
    for path in PATHS:
        response = await client.get(BASE + path, headers=headers)
        assert response.status_code == status, response.text
        private(response)
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("path", PATHS)
async def test_feature_gate_hides_all_reads(client, monkeypatch, path):
    monkeypatch.setattr(get_settings(), "ml_foundation_public_enabled", False)
    response = await client.get(BASE + path)
    assert response.status_code == 404
    private(response)


@pytest.mark.parametrize("path", PATHS)
async def test_no_mutation_endpoint_exists(client, db_session, path):
    before = await snapshot(db_session)
    response = await client.post(BASE + path, json={"approved": True, "scientific_accepted": True})
    assert response.status_code == 405
    private(response, guarded=False)
    assert await snapshot(db_session) == before


async def test_real_pending_result_discloses_only_closed_typed_evidence_without_writes(client, db_session, tmp_path):
    fixture = await pending_result(db_session)
    property_id = fixture["property_id"]
    before = await snapshot(db_session)
    # Verify the privacy canary really exists in retained SQL bytes.
    raw = await db_session.scalar(sa.text("SELECT payload FROM scientific_import_blobs WHERE package_id=:package "
        "AND bytes_sha256=:sha"), {"package": UUID(fixture["started"]["package_id"]), "sha": fixture["input_hash"]})
    assert PRIVATE_CANARY.encode() in bytes(raw)
    await db_session.rollback()
    headers = auth(fixture["actors"]["reviewer"])
    response = await client.get(BASE + "/results/" + property_id, headers=headers)
    assert response.status_code == 200, response.text
    private(response)
    value = response.json()
    assert set(value) == {"version", "descriptor_sha256", "target", "material", "result", "event", "state",
                          "structure", "run", "sources", "inventory", "warnings", "impact", "authority"}
    assert value["target"] == {"property_id": property_id, "event_id": fixture["finished"]["row_ids"]["event"],
                               "event_revision": 1}
    assert value["material"] == {"id": fixture["material"], "formula": "AlAs"}
    assert value["result"]["property_key"] == "phonon_min_frequency"
    assert value["result"]["value"] == pytest.approx(-0.0299792458)
    assert value["result"]["unit"] == "THz"
    assert value["result"]["lower"] is None and value["result"]["upper"] is None
    assert value["event"]["review_status"] == value["event"]["validity_status"] == "pending"
    assert value["event"]["event_type"] == "extraction"
    assert value["event"]["knowledge_origin"] == "Computed"
    assert value["state"]["pressure_status"] == "not_reported"
    assert value["state"]["pressure_gpa"] is None
    assert value["state"]["temperature_k"] is None
    assert value["run"]["run_kind"] == "extraction"
    assert value["structure"]["structure_kind"] == "coordinates"
    assert value["authority"] == {"scientific_accepted": False, "ml_training_approved": False,
        "public_release": False, "review_write_available": False}
    assert {"source_text_not_disclosed", "pressure_not_reported", "temperature_not_reported",
        "producer_is_extraction_not_native_calculation", "restricted_or_unknown_source_access",
        "parent_event_review_does_not_adjudicate_selected_property"} <= set(value["warnings"])
    assert value["sources"]
    locators = []
    for source in value["sources"]:
        assert set(source) == {"artifact_id", "kind", "access", "hash_status", "bytes_sha256",
                               "evidence_link_ids", "locators"}
        assert source["access"] == "restricted"
        assert source["hash_status"] == "verified"
        assert len(source["locators"]) == len(source["evidence_link_ids"])
        for locator in source["locators"]:
            assert set(locator) in ({"scope"}, {"line", "start_byte", "end_byte"})
            if "line" in locator:
                assert 0 <= locator["start_byte"] <= locator["end_byte"]
                locators.append(locator)
    assert locators  # Byte identities are private metadata, not source-text delivery.
    assert value["inventory"]["artifact_count"] == len(value["sources"])
    assert value["impact"]["complete_for_scope"] is True
    assert value["impact"]["counts"]["event_properties"] == 1
    assert "scientific_validity_refresh_completion_or_current_distribution_authorization" in value["impact"]["unsupported_scopes"]
    for forbidden in (PRIVATE_CANARY, '"raw"', '"context"', '"metadata"', '"payload"', '"source_url"',
                      '"manifest"', '"password_hash"', '"source_raw_text"'):
        assert forbidden not in response.text
    second = await client.get(BASE + "/results/" + property_id, headers={**headers, "If-None-Match": '"old"'})
    assert second.status_code == 200 and second.json() == value
    capabilities = await client.get(BASE + "/capabilities", headers=headers)
    predecessor = str(UUID(int=UUID(property_id).int - 1))
    queue = await client.get(BASE + "/results", params={"after": predecessor, "limit": 1}, headers=headers)
    assert capabilities.status_code == queue.status_code == 200
    assert queue.json()["items"][0]["property_id"] == property_id
    assert await snapshot(db_session) == before
    # Entirely synthetic wire capture for optional independent frontend parity.
    output = tmp_path / "scientific-review-http.json"
    output.write_text(json.dumps({"capabilities": capabilities.json(), "queue": queue.json(), "dossier": value}, indent=2) + "\n")
    print("Synthetic scientific review HTTP fixture:", output)


async def test_queue_uses_exact_keyset_and_never_counts_parent_review_as_result_approval(client, db_session):
    fixture = await pending_result(db_session)
    before = await snapshot(db_session)
    property_id = fixture["property_id"]
    # No UUID is between this predecessor and the real property, regardless of
    # other committed fixtures elsewhere in the complete API suite.
    predecessor = str(UUID(int=UUID(property_id).int - 1))
    response = await client.get(BASE + "/results", params={"after": predecessor, "limit": 1},
                                headers=auth(fixture["actors"]["curator"]))
    assert response.status_code == 200, response.text
    value = response.json()
    assert set(value) == {"version", "items", "next_cursor", "has_more", "total_count", "count_basis"}
    assert len(value["items"]) == 1
    item = value["items"][0]
    assert set(item) == {"property_id", "event_id", "event_revision", "material_id", "formula", "property_key",
                         "unit", "knowledge_origin", "review_status", "validity_status"}
    assert item["property_id"] == property_id
    assert item["review_status"] == item["validity_status"] == "pending"
    assert value["total_count"] is None
    assert "not a reviewed-result total" in value["count_basis"]
    assert value["next_cursor"] == (property_id if value["has_more"] else None)
    empty = await client.get(BASE + "/results", params={"after": UNKNOWN_ID, "limit": 50},
                             headers=auth(fixture["actors"]["curator"]))
    assert empty.status_code == 200, empty.text
    assert empty.json()["items"] == []
    assert empty.json()["has_more"] is False and empty.json()["next_cursor"] is None
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("query,status", [
    ({"limit": 0}, 422), ({"limit": 51}, 422), ({"limit": "nope"}, 422),
    ({"after": "not-a-uuid"}, 400), ({"after": UNKNOWN_ID.upper()}, 400),
    ({"after": "x" * 37}, 422),
])
async def test_invalid_paging_is_bounded_and_does_not_mutate(client, db_session, query, status):
    people = await actors(db_session)
    await db_session.commit()
    before = await snapshot(db_session)
    response = await client.get(BASE + "/results", params=query, headers=auth(people["reviewer"]))
    assert response.status_code == status, response.text
    private(response, guarded=status != 422)
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("identifier", ["not-a-uuid", UNKNOWN_ID, UNKNOWN_ID.upper()])
async def test_missing_and_malformed_targets_are_safe_private_failures(client, db_session, identifier):
    people = await actors(db_session)
    await db_session.commit()
    before = await snapshot(db_session)
    response = await client.get(BASE + "/results/" + identifier, headers=auth(people["reviewer"]))
    assert response.status_code in {400, 404}, response.text
    private(response)
    assert "scientific_dossier_reference_unavailable" not in response.text
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("property_key,unit", [("tc", "K"), ("tc_kelvin", "K"), ("rps_score", "point")])
async def test_tc_registry_boundary_and_priority_route_exclusion(client, db_session, property_key, unit):
    fixture = await pending_result(db_session)
    target = uuid4()
    values = dict(id=target, event_id=UUID(fixture["finished"]["row_ids"]["event"]),
        property_key=property_key, registry_version="rv2/1", component_key="synthetic-unsupported",
        relation="exact", value=39, unit=unit, uncertainty={}, raw={}, record_sha256="a" * 64)
    if property_key in {"tc", "tc_kelvin"}:
        # Tc belongs only to material_claims. Do not weaken the frozen registry
        # to manufacture a supposedly canonical Tc event_property for a test.
        with pytest.raises(DBAPIError, match="ck_rv2_property_registry"):
            async with db_session.begin_nested():
                await add(db_session, "event_properties", **values)
    else:
        run_id, event_id = uuid4(), uuid4()
        await add(db_session, "research_runs", id=run_id, run_kind="priority_assessment", status="completed",
            settings_schema_version="synthetic/1", record_sha256="b" * 64)
        await add(db_session, "research_events", id=event_id, material_id=fixture["material"],
            state_id=UUID(fixture["finished"]["row_ids"]["state"]), producer_run_id=run_id,
            event_type="priority_assessment", assessment_run_kind="priority_assessment",
            knowledge_origin="Inferred", record_sha256="c" * 64)
        values.update(event_id=event_id, assessment_event_type="priority_assessment", value=5500)
        await add(db_session, "event_properties", **values)
    await db_session.commit()
    before = await snapshot(db_session)
    headers = auth(fixture["actors"]["curator"])
    detail = await client.get(BASE + "/results/" + str(target), headers=headers)
    assert detail.status_code == 400, detail.text
    private(detail)
    page = await client.get(BASE + "/results", params={"after": str(UUID(int=target.int - 1)), "limit": 1}, headers=headers)
    assert page.status_code == 200, page.text
    assert all(item["property_id"] != str(target) for item in page.json()["items"])
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("failure", [SQLAlchemyError, TimeoutError])
async def test_actual_dossier_impact_database_failures_are_503_without_partial_evidence(client, db_session, monkeypatch, failure):
    fixture = await pending_result(db_session)
    before = await snapshot(db_session)
    visited = []

    async def unavailable(db, statement):
        visited.append(True)
        raise failure(PRIVATE_CANARY)

    monkeypatch.setattr(impact, "_rows", unavailable)
    response = await client.get(BASE + "/results/" + fixture["property_id"], headers=auth(fixture["actors"]["reviewer"]))
    assert visited  # Auth, current SQL closure, and dossier preparation were real.
    assert response.status_code == 503, response.text
    private(response)
    assert "sources" not in response.json() and "result" not in response.json()
    assert PRIVATE_CANARY not in response.text
    assert await snapshot(db_session) == before


async def test_actual_read_transaction_is_read_only_bounded_utc_and_repeatable(client, db_session, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    original = router.dossier.capabilities
    observed = []

    async def spy(db, **kwargs):
        observed.append(tuple([await db.scalar(sa.text(command)) for command in (
            "SHOW transaction_isolation", "SHOW transaction_read_only", "SHOW TimeZone", "SHOW statement_timeout")]))
        return await original(db, **kwargs)

    monkeypatch.setattr(router.dossier, "capabilities", spy)
    response = await client.get(BASE + "/capabilities", headers=auth(people["curator"]))
    assert response.status_code == 200, response.text
    assert observed == [("repeatable read", "on", "UTC", "5s")]


async def test_read_only_sql_fence_blocks_accidental_service_write_and_preserves_all_rows(client, db_session, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    before = await snapshot(db_session)

    async def broken(db, **kwargs):
        await db.execute(sa.text("INSERT INTO stats_cache(key,value) VALUES (:key, '{}'::jsonb)"),
                         {"key": "forbidden-review-read:" + uuid4().hex})
        pytest.fail("PostgreSQL admitted a write in the review read-only transaction")

    monkeypatch.setattr(router.dossier, "capabilities", broken)
    response = await client.get(BASE + "/capabilities", headers=auth(people["curator"]))
    assert response.status_code == 503, response.text
    private(response)
    assert "INSERT" not in response.text and "stats_cache" not in response.text
    assert await snapshot(db_session) == before


@pytest.mark.parametrize("failure,status", [(SQLAlchemyError, 503), (TimeoutError, 503),
    (RuntimeError, 503), (ValueError, 400), (TypeError, 400), (OverflowError, 400), (RecursionError, 400)])
async def test_errors_are_sanitized_and_release_capacity(client, db_session, monkeypatch, failure, status):
    people = await actors(db_session)
    await db_session.commit()
    original = router.dossier.capabilities

    async def broken(*args, **kwargs):
        raise failure(PRIVATE_CANARY)

    monkeypatch.setattr(router.dossier, "capabilities", broken)
    response = await client.get(BASE + "/capabilities", headers=auth(people["curator"]))
    assert response.status_code == status
    assert PRIVATE_CANARY not in response.text
    private(response)
    monkeypatch.setattr(router.dossier, "capabilities", original)
    assert (await client.get(BASE + "/capabilities", headers=auth(people["curator"]))).status_code == 200


async def test_complete_response_byte_cap_returns_no_partial_document(client, db_session, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    monkeypatch.setattr(router.dossier, "MAX_RESPONSE_BYTES", 1)
    response = await client.get(BASE + "/capabilities", headers=auth(people["curator"]))
    assert response.status_code == 400
    assert "roles" not in response.json() and "can_read" not in response.json()
    private(response)


async def test_whole_request_deadline_cancels_reader_and_releases_capacity(client, db_session, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    original, actual_timeout = router.dossier.capabilities, asyncio.timeout
    deadline_arguments, deadlines = [], []
    cancelled = asyncio.Event()

    def short_timeout(seconds):
        deadline_arguments.append(seconds)
        deadline = actual_timeout(seconds)
        deadlines.append(deadline)
        return deadline

    async def slow(*args, **kwargs):
        # Accelerate only after authentication and SQL setup have completed,
        # so machine load cannot expire the timer before this witness exists.
        deadlines[0].reschedule(asyncio.get_running_loop().time() + 0.01)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with monkeypatch.context() as patch:
        patch.setattr(router.asyncio, "timeout", short_timeout)
        patch.setattr(router.dossier, "capabilities", slow)
        response = await client.get(BASE + "/capabilities", headers=auth(people["curator"]))
    assert deadline_arguments == [10]
    assert cancelled.is_set()
    assert response.status_code == 503
    private(response)
    assert router.dossier.capabilities is original
    assert (await client.get(BASE + "/capabilities", headers=auth(people["curator"]))).status_code == 200


async def test_four_request_slots_remain_held_until_reads_finish(client, db_session, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    original = router.dossier.capabilities
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0
    slots = threading.BoundedSemaphore(4)
    monkeypatch.setattr(router, "_slots", slots)

    async def held(db, **kwargs):
        nonlocal count
        count += 1
        if count == 4:
            entered.set()
        await release.wait()
        return await original(db, **kwargs)

    monkeypatch.setattr(router.dossier, "capabilities", held)
    requests = [asyncio.create_task(client.get(BASE + "/capabilities", headers=auth(people["curator"]))) for _ in range(4)]
    try:
        await asyncio.wait_for(entered.wait(), 3)
        denied = await client.get(BASE + "/capabilities", headers=auth(people["curator"]))
        assert denied.status_code == 503
        private(denied)
        assert count == 4
    finally:
        release.set()
        responses = await asyncio.gather(*requests)
    assert all(response.status_code == 200 for response in responses)
    assert (await client.get(BASE + "/capabilities", headers=auth(people["curator"]))).status_code == 200


async def test_cancelled_read_releases_request_slot_and_sql_session(client, db_session, monkeypatch):
    people = await actors(db_session)
    await db_session.commit()
    before = await snapshot(db_session)
    original = router.dossier.capabilities
    entered = asyncio.Event()
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(router, "_slots", slots)

    async def held(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(router.dossier, "capabilities", held)
    request = asyncio.create_task(client.get(BASE + "/capabilities", headers=auth(people["curator"])))
    await asyncio.wait_for(entered.wait(), 3)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    monkeypatch.setattr(router.dossier, "capabilities", original)
    response = await client.get(BASE + "/capabilities", headers=auth(people["curator"]))
    assert response.status_code == 200, response.text
    assert await snapshot(db_session) == before
