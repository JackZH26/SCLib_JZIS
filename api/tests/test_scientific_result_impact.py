"""Actual typed reverse references; all sources/reviews are synthetic fixtures."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, Paper, get_engine
from services import research_freeze
from services import scientific_result_impact as service
from services.research_release_manifest import canonical
from tests.rps_distribution_fixtures import publish_distribution, release_document
from tests.test_research_freeze import add, approved, seed, state
from tests.test_research_freeze import db_session as db_session
from tests.test_research_publication import actors, proposed


def ids(report, table):
    return {item["row_id"] for item in report["items"] if item["table"] == table}


def relations(report, table, identifier):
    return {item["relation"] for item in report["items"]
            if item["table"] == table and item["row_id"] == str(identifier)}


async def inspect(db, fixture):
    await db.execute(sa.text("SET LOCAL statement_timeout='5s'"))
    return await service.inspect_result_impact(db, property_id=fixture["children"]["property"], event_id=fixture["event"])


async def input_row(db, fixture, *, input_kind="event_context", property_id=None):
    return await add(db, "ml_example_inputs", example_id=fixture["example"], input_kind=input_kind,
        input_property_id=property_id, input_event_id=fixture["event"], feature_key=uuid4().hex,
        matching_policy_version="synthetic-impact/1", record_sha256="a" * 64,
        context={"private_canary": "NOT_RETURNED_INPUT_CONTEXT"})


async def test_exact_references_are_complete_deterministic_and_read_only(db_session):
    fixture = await seed(db_session)
    await db_session.execute(sa.text("SET LOCAL statement_timeout='5s'"))
    before = await state(db_session)
    settings_before = (await db_session.execute(sa.text("SELECT current_setting('TimeZone'),current_setting('statement_timeout')"))).one()
    statements = []
    engine = db_session.get_bind()
    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement)
    sa.event.listen(engine, "before_cursor_execute", observe)
    try:
        report = await service.inspect_result_impact(db_session, property_id=fixture["children"]["property"], event_id=fixture["event"])
    finally:
        sa.event.remove(engine, "before_cursor_execute", observe)
    assert set(report) == {"version", "scope", "unsupported_scopes", "complete_for_scope", "counts", "items"}
    assert report["version"] == service.VERSION and report["complete_for_scope"] is True
    assert set(report["counts"]) == {*service.TABLES, "total_nodes", "total_relations"}
    assert ids(report, "ml_example_inputs") == {str(fixture["children"]["input"])}
    assert relations(report, "ml_example_inputs", fixture["children"]["input"]) == {
        "input_property_reference", "input_event_reference"}
    assert ids(report, "ml_examples") == {str(fixture["example"])}
    assert ids(report, "ml_dataset_snapshots") == {str(fixture["args"]["dataset_id"])}
    assert ids(report, "snapshot_event_memberships") == {str(fixture["member"])}
    assert ids(report, "source_snapshots") == {str(fixture["snapshot"])}
    assert not ids(report, "event_evidence")  # Original source artifact is not a reverse derives_from edge.
    for table in service.TABLES:
        assert report["counts"][table] == len(ids(report, table))
    assert report["counts"]["total_nodes"] == sum(report["counts"][name] for name in service.TABLES)
    assert report["counts"]["total_relations"] == len(report["items"])
    assert all(set(item) == {"table", "row_id", "relation", "via_table", "via_id"} for item in report["items"])
    assert len(canonical(report)) <= service.MAX_BYTES
    assert await inspect(db_session, fixture) == report
    assert await state(db_session) == before
    assert (await db_session.execute(sa.text("SELECT current_setting('TimeZone'),current_setting('statement_timeout')"))).one() == settings_before
    for statement in statements:
        assert statement.lstrip().upper().startswith(("SELECT", "SHOW"))
        for forbidden in (".raw", ".row_data", ".manifest", ".projection_json", ".label_data", ".context", "SELECT *"):
            assert forbidden not in statement


async def test_event_context_and_sibling_property_are_not_target_property_causality(db_session):
    fixture = await seed(db_session)
    context = await input_row(db_session, fixture)
    sibling = await add(db_session, "event_properties", event_id=fixture["event"], property_key="band_gap",
                        component_key="synthetic-sibling", relation="exact", value=1.1, unit="eV", record_sha256="b" * 64)
    other = await input_row(db_session, fixture, input_kind="property", property_id=sibling["id"])
    unrelated = await seed(db_session)  # Same formula does not create a link.
    report = await inspect(db_session, fixture)
    assert relations(report, "ml_example_inputs", context["id"]) == {"input_event_reference"}
    assert relations(report, "ml_example_inputs", other["id"]) == {"input_event_reference"}
    assert str(unrelated["children"]["input"]) not in ids(report, "ml_example_inputs")
    assert "property_specific_causality_of_event_context_or_sibling_results" in report["unsupported_scopes"]
    assert b"NOT_RETURNED_INPUT_CONTEXT" not in canonical(report)


async def test_derivation_is_one_hop_only_and_support_is_not_causality(db_session):
    fixture = await seed(db_session)
    output = await add(db_session, "research_events", material_id=fixture["material"], state_id=fixture["state"],
                       event_type="curation", knowledge_origin="Inferred", record_sha256="b" * 64)
    edge = await add(db_session, "event_evidence", event_id=output["id"], link_type="derives_from",
        input_event_id=fixture["event"], input_property_id=fixture["children"]["property"])
    prop = await add(db_session, "event_properties", event_id=output["id"], property_key="band_gap",
        relation="exact", value=0.5, unit="eV", record_sha256="c" * 64)
    grandchild = await add(db_session, "research_events", material_id=fixture["material"], state_id=fixture["state"],
                          event_type="curation", knowledge_origin="Inferred", record_sha256="d" * 64)
    second = await add(db_session, "event_evidence", event_id=grandchild["id"], link_type="derives_from",
                      input_event_id=output["id"], input_property_id=prop["id"])
    supported = await add(db_session, "event_evidence", event_id=grandchild["id"], link_type="supports",
                         input_event_id=fixture["event"])
    report = await inspect(db_session, fixture)
    assert ids(report, "event_evidence") == {str(edge["id"])}
    assert relations(report, "event_evidence", edge["id"]) == {"derives_from_input_event", "derives_from_input_property"}
    assert ids(report, "research_events") == {str(fixture["event"]), str(output["id"])}
    assert str(second["id"]) not in ids(report, "event_evidence")
    assert str(supported["id"]) not in ids(report, "event_evidence")
    assert "transitive_event_and_feature_dependencies" in report["unsupported_scopes"]


async def test_real_frozen_pins_and_metadata_proposal_not_publication_authority(db_session):
    context = await proposed(db_session)
    fixture = context["fixture"]
    before = await state(db_session)
    report = await inspect(db_session, fixture)
    assert ids(report, "research_releases") == {context["release"]["release_id"]}
    assert ids(report, "research_publication_proposals") == {context["proposal"]["id"]}
    assert report["counts"]["research_release_pins"] >= 6
    assert all(item["relation"] == "historical_exact_row_pin"
               for item in report["items"] if item["table"] == "research_release_pins")
    assert await state(db_session) == before
    assert not {"manifest", "payload", "scientific_acceptance", "public_release"} & set(report)


async def distribution_context(db):
    people, source = await actors(db), await seed(db)
    await db.execute(sa.text("UPDATE materials SET formula='TEST',formula_normalized='TEST',family='synthetic',"
                            "total_papers=1,needs_review=false WHERE id=:id"), {"id": source["material"]})
    await db.execute(sa.text("UPDATE works SET publication_status='active' WHERE id=:id"), {"id": source["work"]})
    await db.execute(sa.text("UPDATE material_states SET pressure_status='explicit_ambient',pressure_gpa=0 WHERE id=:id"),
                     {"id": source["state"]})
    await db.execute(sa.text("UPDATE research_events SET event_type='curation',knowledge_origin='Inferred' WHERE id=:id"),
                     {"id": source["event"]})
    _, args = await approved(db, source)
    frozen = await research_freeze.freeze_research_release(db, **args, dry_run=False)
    shared = {"actors": people, "source": source, "capsule": frozen, "capsule_bytes": args["artifact_bytes"],
              "internal_artifacts": {}, "evidence_source_kind": "curation"}
    return await publish_distribution(db, release_document(), shared=shared, publish=False, permissions=False)


async def test_distribution_exact_dependency_and_capsule_fks_not_release_name_guessing(db_session):
    context = await distribution_context(db_session)
    fixture = context["shared"]["source"]
    before = await state(db_session)
    report = await inspect(db_session, fixture)
    package_id = str(context["package"]["id"])
    assert ids(report, "research_distribution_packages") == {package_id}
    assert ids(report, "research_distribution_dependencies")
    assert any(item["relation"] == "historical_exact_row_dependency" and item["via_table"] == "event_properties"
               and item["via_id"] == str(fixture["children"]["property"]) for item in report["items"])
    assert any(item["relation"] == "historical_capsule_reference" for item in report["items"])
    assert not context["permissions"] and "review" not in context
    assert await state(db_session) == before
    assert b"bindings_sha256" not in canonical(report) and b"TEST" not in canonical(report)


@pytest.mark.parametrize("kind", ["missing_property", "missing_event", "mismatched_event", "string_noncanonical", "boolean"])
async def test_target_pair_identity_is_verified(db_session, kind):
    fixture = await seed(db_session)
    await db_session.execute(sa.text("SET LOCAL statement_timeout='5s'"))
    args = {"property_id": fixture["children"]["property"], "event_id": fixture["event"]}
    if kind == "missing_property": args["property_id"] = uuid4()
    elif kind == "missing_event": args["event_id"] = uuid4()
    elif kind == "mismatched_event": args["event_id"] = (await seed(db_session))["event"]
    elif kind == "string_noncanonical": args["property_id"] = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
    else: args["event_id"] = True
    with pytest.raises(service.ScientificResultImpactError, match="invalid_identity|target_mismatch_or_missing"):
        await service.inspect_result_impact(db_session, **args)


@pytest.mark.parametrize("timeout", [0, 10001])
async def test_unbounded_or_overlong_query_deadline_is_refused(db_session, timeout):
    await db_session.execute(sa.text("SELECT set_config('statement_timeout', :value, true)"), {"value": str(timeout)})
    with pytest.raises(service.ScientificResultImpactError, match="statement_deadline_required"):
        await service.inspect_result_impact(db_session, property_id=uuid4(), event_id=uuid4())


async def test_read_committed_is_not_a_complete_consistent_inventory():
    async with AsyncSession(get_engine().execution_options(isolation_level="READ COMMITTED")) as db:
        with pytest.raises(service.ScientificResultImpactError, match="stable_snapshot_required"):
            await service.inspect_result_impact(db, property_id=uuid4(), event_id=uuid4())


async def test_orm_pending_objects_are_not_implicitly_flushed(db_session):
    pending = Paper(id="impact-unflushed:" + uuid4().hex, title="NO_IMPLICIT_WRITE", abstract="private", source="arxiv")
    db_session.add(pending)
    with pytest.raises(service.ScientificResultImpactError, match="clean_session_required"):
        await service.inspect_result_impact(db_session, property_id=uuid4(), event_id=uuid4())
    assert pending in db_session.new


@pytest.mark.parametrize("limit", ["MAX_QUERY_ROWS", "MAX_NODES", "MAX_RELATIONS", "MAX_BYTES"])
async def test_any_limit_fails_closed_without_returning_a_partial_complete_inventory(db_session, monkeypatch, limit):
    fixture = await seed(db_session)
    await input_row(db_session, fixture)
    monkeypatch.setattr(service, limit, 1)
    before = await state(db_session)
    with pytest.raises(service.ScientificResultImpactLimitError):
        await inspect(db_session, fixture)
    assert await state(db_session) == before


async def test_exact_final_envelope_not_only_item_bytes_obeys_limit(db_session, monkeypatch):
    fixture = await seed(db_session)
    report = await inspect(db_session, fixture)
    monkeypatch.setattr(service, "MAX_BYTES", len(canonical(report)) - 1)
    with pytest.raises(service.ScientificResultImpactLimitError, match="byte_limit"):
        await inspect(db_session, fixture)


async def test_snapshot_is_stable_and_later_references_require_a_new_transaction(db_session):
    fixture = await seed(db_session)
    await db_session.commit()
    before = await inspect(db_session, fixture)
    async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as writer:
        added = await input_row(writer, fixture)
        await writer.commit()
    assert await inspect(db_session, fixture) == before
    await db_session.rollback()
    fresh = await inspect(db_session, fixture)
    assert str(added["id"]) in ids(fresh, "ml_example_inputs")


async def test_no_hidden_commit_of_callers_own_rows(db_session):
    fixture = await seed(db_session)
    await inspect(db_session, fixture)
    await db_session.rollback()
    props = Base.metadata.tables["event_properties"]
    assert await db_session.scalar(sa.select(props.c.id).where(props.c.id == fixture["children"]["property"])) is None


async def test_actual_1001_matching_inputs_are_refused_without_truncation(db_session):
    fixture = await seed(db_session)
    table = Base.metadata.tables["ml_example_inputs"]
    await db_session.execute(table.insert(), [{"example_id": fixture["example"], "input_kind": "event_context",
        "input_event_id": fixture["event"], "feature_key": "bounded:" + str(index),
        "matching_policy_version": "synthetic-impact/1", "record_sha256": "e" * 64} for index in range(1000)])
    assert service.MAX_QUERY_ROWS == 1000
    with pytest.raises(service.ScientificResultImpactLimitError, match="query_limit"):
        await inspect(db_session, fixture)


async def test_overall_deadline_is_sanitized_and_returns_no_partial_body(db_session, monkeypatch):
    fixture = await seed(db_session)
    async def stalled(*args):
        await asyncio.sleep(60)
    monkeypatch.setattr(service, "_collect", stalled)
    monkeypatch.setattr(service, "MAX_SECONDS", 0.02)
    await db_session.execute(sa.text("SET LOCAL statement_timeout='10ms'"))
    with pytest.raises(service.ScientificResultImpactError, match="database_unavailable"):
        await service.inspect_result_impact(db_session, property_id=fixture["children"]["property"], event_id=fixture["event"])
