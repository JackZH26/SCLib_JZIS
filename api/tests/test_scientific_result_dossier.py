"""Actual private SQL snapshots; no science adjudication or release approval."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from models.db import Base
from services import scientific_pending_import as importer
from services import scientific_result_dossier as service
from services.research_access import ResearchAccessDenied
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_freeze import seed as seed_closure
from tests.test_scientific_pending_import import seed_import

db_session = _serializable_db_session


async def prepared(db):
    fixture = await seed_import(db)
    started = await importer.start_import(db, actor_user_id=fixture["actors"]["curator"],
        request_key="synthetic-dossier:" + uuid4().hex, package=fixture["package"], dry_run=False)
    await db.commit()
    finished = await importer.finish_import(db, actor_user_id=fixture["actors"]["curator"],
        attempt_id=started["attempt_id"], prepared=importer.compile_input(fixture["package"]), dry_run=False)
    await db.commit()
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    return fixture, finished["row_ids"]


async def dossier(db, fixture, ids):
    return await service.result_dossier(db, actor_user_id=fixture["actors"]["reviewer"], property_id=ids["property"])


async def test_current_whole_descriptor_is_repeatable_and_read_only(db_session):
    fixture, ids = await prepared(db_session)
    before = await state(db_session)
    result = await dossier(db_session, fixture, ids)
    assert result == await dossier(db_session, fixture, ids)
    assert await state(db_session) == before
    assert result["result"]["value"] == pytest.approx(-0.0299792458)
    assert result["result"]["unit"] == "THz"
    assert result["state"]["pressure_gpa"] is result["state"]["temperature_k"] is None
    assert result["event"]["knowledge_origin"] == "Computed"
    assert result["event"]["review_status"] == "pending"
    assert result["run"]["run_kind"] == "extraction"
    assert result["structure"]["structure_kind"] == "coordinates"
    assert set(result["authority"].values()) == {False}
    assert result["inventory"]["row_count"] > 5
    assert result["inventory"]["artifact_count"] == len(result["sources"])
    assert result["impact"]["complete_for_scope"] is True
    assert "producer_is_extraction_not_native_calculation" in result["warnings"]
    assert "restricted_or_unknown_source_access" in result["warnings"]


async def test_native_driver_uuid_can_identify_a_result(db_session):
    fixture, ids = await prepared(db_session)
    properties = Base.metadata.tables["event_properties"]
    actual_id = await db_session.scalar(sa.select(properties.c.id).where(properties.c.id == UUID(ids["property"])))
    result = await service.result_dossier(db_session, actor_user_id=fixture["actors"]["reviewer"], property_id=actual_id)
    assert result == await dossier(db_session, fixture, ids)


@pytest.mark.parametrize("role,can_read", [("curator", True), ("reviewer", True), ("publisher", False),
                                          ("admin", False), ("member", False)])
async def test_capabilities_are_live_grants_not_legacy_flags(db_session, role, can_read):
    fixture, ids = await prepared(db_session)
    result = await service.capabilities(db_session, actor_user_id=fixture["actors"][role])
    assert result["can_read"] is can_read
    assert result["review_write_available"] is False
    if not can_read:
        with pytest.raises(ResearchAccessDenied):
            await service.result_dossier(db_session, actor_user_id=fixture["actors"][role], property_id=ids["property"])


@pytest.mark.parametrize("table,row_key,field,value", [
    ("event_properties", "property", "raw", {"private_note": "SOURCE_BODY_SENTINEL"}),
    ("research_events", "event", "context", {"private_note": "SOURCE_BODY_SENTINEL"}),
    ("structure_records", "structure", "occupancy_context", {"private_note": "SOURCE_BODY_SENTINEL"}),
    ("research_runs", "run", "settings", {"private_note": "SOURCE_BODY_SENTINEL"}),
    ("material_states", "state", "conditions", {"private_note": "SOURCE_BODY_SENTINEL"}),
])
async def test_private_source_changes_change_pin_without_exposing_contents(db_session, table, row_key, field, value):
    fixture, ids = await prepared(db_session)
    first = await dossier(db_session, fixture, ids)
    relation = Base.metadata.tables[table]
    await db_session.execute(relation.update().where(relation.c.id == UUID(ids[row_key])).values(**{field: value}))
    second = await dossier(db_session, fixture, ids)
    assert second["descriptor_sha256"] != first["descriptor_sha256"]
    assert second["inventory"]["sha256"] != first["inventory"]["sha256"]
    assert "SOURCE_BODY_SENTINEL" not in str(second)


async def test_new_source_edge_changes_full_pin_and_redacts_arbitrary_locator(db_session):
    fixture, ids = await prepared(db_session)
    first = await dossier(db_session, fixture, ids)
    artifact_id = UUID(first["sources"][0]["artifact_id"])
    await add(db_session, "event_evidence", id=uuid4(), event_id=UUID(ids["event"]),
        link_type="source", artifact_id=artifact_id,
        locator={"quote": "DO_NOT_EXPOSE_THIS_SOURCE", "url": "https://private.invalid/secret"})
    second = await dossier(db_session, fixture, ids)
    assert second["descriptor_sha256"] != first["descriptor_sha256"]
    assert second["inventory"]["row_count"] == first["inventory"]["row_count"] + 1
    assert "DO_NOT_EXPOSE_THIS_SOURCE" not in str(second) and "private.invalid" not in str(second)
    assert any({"scope": "locator_not_disclosed"} in source["locators"] for source in second["sources"])


async def test_sibling_result_is_pinned_but_not_displayed_as_selected_result(db_session):
    fixture, ids = await prepared(db_session)
    first = await dossier(db_session, fixture, ids)
    await add(db_session, "event_properties", id=uuid4(), event_id=UUID(ids["event"]),
        property_key="phonon_min_frequency", registry_version="rv2/1", component_key="another-context",
        relation="exact", value=999, unit="THz", uncertainty={}, raw={}, record_sha256="a" * 64)
    second = await dossier(db_session, fixture, ids)
    assert second["inventory"]["row_count"] == first["inventory"]["row_count"] + 1
    assert second["descriptor_sha256"] != first["descriptor_sha256"]
    assert second["result"] == first["result"]
    assert second["authority"]["scientific_accepted"] is False


async def test_keyset_queue_has_explicit_null_total_and_no_scientific_scalar_or_raw_data(db_session):
    fixture, ids = await prepared(db_session)
    for _ in range(2):
        await add(db_session, "event_properties", id=uuid4(), event_id=UUID(ids["event"]),
            property_key="phonon_min_frequency", registry_version="rv2/1", component_key=uuid4().hex,
            relation="exact", value=1, unit="THz", uncertainty={}, raw={}, record_sha256="a" * 64)
    before = await state(db_session)
    actor = fixture["actors"]["reviewer"]
    page = await service.list_results(db_session, actor_user_id=actor, limit=1)
    assert page["has_more"] is True and page["next_cursor"] == page["items"][-1]["property_id"]
    next_page = await service.list_results(db_session, actor_user_id=actor, after=page["next_cursor"], limit=1)
    assert next_page["items"][0]["property_id"] > page["next_cursor"]
    assert page["total_count"] is None and page["count_basis"] == service.COUNT_BASIS
    assert not ({"value", "raw", "context", "metadata"} & set(page["items"][0]))
    assert await state(db_session) == before


@pytest.mark.parametrize("limit", [0, 51, True, 1.5])
async def test_queue_limit_is_strict(db_session, limit):
    fixture, _ = await prepared(db_session)
    with pytest.raises(service.ScientificDossierError, match="scientific_review_page_limit"):
        await service.list_results(db_session, actor_user_id=fixture["actors"]["curator"], limit=limit)


@pytest.mark.parametrize("value", ["unknown", "../private", "A" * 36, "00000000-0000-0000-0000-00000000000A"])
async def test_identifiers_are_canonical_and_fail_without_source_echo(db_session, value):
    fixture, _ = await prepared(db_session)
    with pytest.raises(service.ScientificDossierError) as exc:
        await service.result_dossier(db_session, actor_user_id=fixture["actors"]["curator"], property_id=value)
    assert value not in str(exc.value)


@pytest.mark.parametrize("value,expected", [
    ({"source_locator": {"line": 3, "start_byte": 10, "end_byte": 20, "quote": "secret"}},
     {"line": 3, "start_byte": 10, "end_byte": 20}),
    ({"line": True, "start_byte": 10, "end_byte": 20}, {"scope": "locator_not_disclosed"}),
    ({"line": 3, "start_byte": 20, "end_byte": 10}, {"scope": "locator_not_disclosed"}),
    ({"line": 3, "start_byte": 1, "end_byte": 99999999999999}, {"scope": "locator_not_disclosed"}),
    ({"text": "untrusted instructions"}, {"scope": "locator_not_disclosed"}),
])
def test_source_locator_is_numeric_only(value, expected):
    assert service._locator(value) == expected


async def test_large_inventory_is_rejected_not_a_truncated_complete_dossier(db_session, monkeypatch):
    fixture, ids = await prepared(db_session)
    monkeypatch.setattr(service, "MAX_ROWS", 2)
    before = await state(db_session)
    with pytest.raises(service.ScientificDossierError, match="scientific_dossier_row_limit"):
        await dossier(db_session, fixture, ids)
    assert await state(db_session) == before


async def test_statement_timeout_is_required_without_setting_it_inside_reader(db_session):
    fixture, ids = await prepared(db_session)
    await db_session.execute(sa.text("SET LOCAL statement_timeout=0"))
    with pytest.raises(service.ScientificDossierError, match="bounded_scientific_read_timeout_required"):
        await dossier(db_session, fixture, ids)
    assert await db_session.scalar(sa.text("SELECT setting FROM pg_settings WHERE name='statement_timeout'")) == "0"


async def test_owned_child_quality_checks_are_recursively_captured(db_session):
    fixture = await seed_closure(db_session)
    before = await state(db_session)
    captured = await service._collect(db_session, fixture["children"]["property"])
    assert ("material_claims", str(fixture["claim"])) in captured
    assert ("material_claims", str(fixture["children"]["sibling_claim"])) in captured
    qc_key = "claim_qc", str(fixture["children"]["qc"])
    assert qc_key in captured
    assert await state(db_session) == before
    qc = Base.metadata.tables["claim_qc"]
    await db_session.execute(qc.update().where(qc.c.id == fixture["children"]["qc"])
                             .values(reviewer_notes="PRIVATE_NESTED_QC"))
    changed = await service._collect(db_session, fixture["children"]["property"])
    assert changed[qc_key]["row_sha256"] != captured[qc_key]["row_sha256"]


async def test_source_metadata_is_pinned_without_exposing_private_fields(db_session):
    fixture, ids = await prepared(db_session)
    first = await dossier(db_session, fixture, ids)
    artifacts = Base.metadata.tables["evidence_artifacts"]
    await db_session.execute(artifacts.update().where(artifacts.c.id == UUID(first["sources"][0]["artifact_id"]))
        .values(metadata={"private": "PRIVATE_ARTIFACT_METADATA"}, uri="https://private.invalid/hidden-file"))
    second = await dossier(db_session, fixture, ids)
    assert second["descriptor_sha256"] != first["descriptor_sha256"]
    assert second["sources"] == first["sources"]
    assert "PRIVATE_ARTIFACT_METADATA" not in str(second) and "private.invalid" not in str(second)


async def test_queue_formula_has_native_database_bound_before_hydration(db_session):
    fixture, ids = await prepared(db_session)
    # Other modules intentionally retain committed scientific history. Verify
    # exact result identities, never assume the global queue starts with this
    # fixture. Adjacent UUIDs make this a bounded, deterministic mixed-material
    # regression even when the disposable database already has many results.
    target_id = UUID(ids["property"])
    earlier_id = UUID(int=target_id.int - 1)
    unrelated = await seed_closure(db_session)
    await add(db_session, "event_properties", id=earlier_id, event_id=unrelated["event"],
        property_key="band_gap", component_key="queue-formula-regression", relation="exact",
        value=1, unit="eV", record_sha256="1" * 64)
    materials = Base.metadata.tables["materials"]
    assert materials.c.formula.type.length == 200
    with pytest.raises(sa.exc.DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(materials.update().where(materials.c.id == fixture["material"])
                                     .values(formula="H" * 201))
    result = await service.list_results(db_session, actor_user_id=fixture["actors"]["reviewer"],
        after=str(UUID(int=target_id.int - 2)), limit=2)
    assert [(item["property_id"], item["formula"]) for item in result["items"]] == [
        (str(earlier_id), "MgB2"), (str(target_id), "AlAs"),
    ]


def test_rps_prefix_escapes_sql_underscore():
    from sqlalchemy.dialects import postgresql
    properties, events = (Base.metadata.tables[name] for name in ("event_properties", "research_events"))
    compiled = str(service._supported(properties, events).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "rps/_" in compiled and "ESCAPE '/'" in compiled


async def test_large_shared_snapshot_does_not_expand_unrelated_events(db_session):
    fixture = await seed_closure(db_session)
    property_id = fixture["children"]["property"]
    original = await service._collect(db_session, property_id)
    exact_member = "snapshot_event_memberships", str(fixture["member"])
    assert exact_member in original
    events, members = (Base.metadata.tables[name] for name in ("research_events", "snapshot_event_memberships"))
    unrelated = [uuid4() for _ in range(1001)]
    await db_session.execute(events.insert(), [{"id": event_id, "material_id": fixture["material"],
        "state_id": fixture["state"], "event_type": "measurement", "knowledge_origin": "Observed",
        "record_sha256": "a" * 64} for event_id in unrelated])
    await db_session.execute(members.insert(), [{"snapshot_id": fixture["snapshot"], "event_id": event_id,
        "event_revision": 1, "source_occurrence_key": str(event_id), "locator": {"private_unrelated": True},
        "source_record_sha256": "b" * 64, "result_manifest_sha256": "c" * 64} for event_id in unrelated])
    captured = await service._collect(db_session, property_id)
    assert captured == original
    assert len(captured) < 1000
    assert not any(("research_events", str(event_id)) in captured for event_id in unrelated)
    await db_session.execute(members.update().where(members.c.id == fixture["member"])
                             .values(locator={"table": "changed_exact_occurrence"}))
    changed = await service._collect(db_session, property_id)
    assert changed[exact_member]["row_sha256"] != captured[exact_member]["row_sha256"]
    assert service.closure.owned_relations("source_snapshots") == (("snapshot_event_memberships", "snapshot_id"),)
