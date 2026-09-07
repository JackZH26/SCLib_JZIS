"""Read-only declared-scope relationship manifests on disposable PostgreSQL."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, Paper, get_engine
from services import source_impact as service
from services.research_release_manifest import canonical, digest
from services.source_lifecycle import inspect_source_lifecycle
from tests.test_research_freeze import add, seed, state
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_publication import proposed

db_session = _serializable_db_session


async def paper(db, *, status="published"):
    identifier = "impact-paper:" + uuid4().hex
    await add(db, "papers", id=identifier, source="arxiv", title="UNEXPOSED_TITLE",
              authors=[], abstract="UNEXPOSED_ABSTRACT", status=status)
    return identifier


async def material(db, *, source=None, parent=None, records=None):
    identifier = "impact-material:" + uuid4().hex
    await add(db, "materials", id=identifier, formula="SAME_FORMULA", formula_normalized="SAME_FORMULA",
        parent_material_id=parent, records=records if records is not None else (
            [{"paper_id": source, "tc_kelvin": 1234.567, "private_note": "UNEXPOSED_RECORD"}] if source else []))
    return identifier


async def observation(db, *, kind="paper", identifier=None):
    if identifier is None:
        if kind == "paper":
            identifier = await paper(db, status="corrected")
        else:
            identifier = (await add(db, "works", canonical_title="UNEXPOSED_WORK", publication_status="corrected"))["id"]
    else:
        name, field = ("papers", "status") if kind == "paper" else ("works", "publication_status")
        table = Base.metadata.tables[name]
        await db.execute(table.update().where(table.c.id == identifier).values(**{field: "corrected"}))
    head = (await inspect_source_lifecycle(db, **{f"{kind}_id": identifier}))["head"]
    return identifier, {"event_id": head["id"], "expected_event_sha256": head["record_sha256"]}


def identifiers(report, table):
    return {node["row_id"] for node in report["nodes"] if node["table"] == table}


def relations(report, table, row_id):
    return next(node["relations"] for node in report["nodes"]
                if node["table"] == table and node["row_id"] == str(row_id))


async def test_zero_point_and_descendant_candidates_without_formula_inference(db_session):
    source, args = await observation(db_session)
    root = await material(db_session, source=source)
    child = await material(db_session, parent=root)
    grandchild = await material(db_session, parent=child)
    unrelated = await material(db_session)
    before = await state(db_session)
    report = await service.inspect_source_impact(db_session, **args)
    assert set(report["timeline_candidate_material_ids"]) == {root, child, grandchild}
    assert identifiers(report, "materials") == {root, child, grandchild}
    assert unrelated not in identifiers(report, "materials")
    assert identifiers(report, "timeline_projection_points") == set()
    assert relations(report, "materials", child) == [
        {"kind": "inherited_parent_governance", "via_table": "materials", "via_id": root}]
    assert await state(db_session) == before


async def test_work_only_accepted_maps_and_explicit_claims(db_session):
    fixture = await seed(db_session, with_children=False)
    work, args = await observation(db_session, kind="work", identifier=fixture["work"])
    accepted, pending, rejected = [await paper(db_session) for _ in range(3)]
    for source, status in ((accepted, "accepted"), (pending, "pending"), (rejected, "rejected")):
        await add(db_session, "paper_work_map", paper_id=source, work_id=work,
                  match_method="manual", review_status=status)
    target = await material(db_session, source=accepted)
    report = await service.inspect_source_impact(db_session, **args)
    assert identifiers(report, "papers") == {accepted}
    assert identifiers(report, "paper_work_map") == {accepted}
    assert str(fixture["claim"]) in identifiers(report, "material_claims")
    assert str(fixture["example"]) in identifiers(report, "ml_examples")
    assert identifiers(report, "materials") == {target, fixture["material"]}
    assert report["timeline_candidate_material_ids"] == [target]
    assert relations(report, "materials", fixture["material"])[0]["kind"] == "claim_material_context"


async def test_paper_does_not_expand_same_work_siblings(db_session):
    source, args = await observation(db_session)
    sibling = await paper(db_session)
    work = (await add(db_session, "works", canonical_title="same work"))["id"]
    for identifier in (source, sibling):
        await add(db_session, "paper_work_map", paper_id=identifier, work_id=work,
                  match_method="manual", review_status="accepted")
    sibling_material = await material(db_session, source=sibling)
    report = await service.inspect_source_impact(db_session, **args)
    assert identifiers(report, "papers") == {source}
    assert not identifiers(report, "works")
    assert sibling_material not in identifiers(report, "materials")


async def test_direct_chunk_hydride_and_inactive_timeline_references(db_session):
    source, args = await observation(db_session)
    target = await material(db_session, source=source)
    chunk_id = "impact-chunk:" + uuid4().hex
    await add(db_session, "chunks", id=chunk_id, paper_id=source, text="UNEXPOSED_CHUNK")
    hydride = await add(db_session, "hydride_tc_parameters", record_key=uuid4().hex,
        material_id=target, formula="UNEXPOSED_HYDRIDE", formula_normalized="H3S", paper_id=source,
        source="arxiv", tc_kelvin=9999, prompt_version="synthetic")
    point_id = uuid4().hex * 2
    await add(db_session, "timeline_projection_points", id=point_id, material_id=target,
        paper_id=source, year=2020, tc_kelvin=123.456, source_updated_at=datetime.now(UTC), active=False)
    report = await service.inspect_source_impact(db_session, **args)
    assert identifiers(report, "chunks") == {chunk_id}
    assert identifiers(report, "hydride_tc_parameters") == {str(hydride["id"])}
    assert identifiers(report, "timeline_projection_points") == {point_id}
    assert {item["kind"] for item in relations(report, "timeline_projection_points", point_id)} == {
        "existing_timeline_material", "existing_timeline_source"}
    payload = canonical(report)
    for hidden in (b"UNEXPOSED", b"1234.567", b"123.456", b"9999", b"SAME_FORMULA"):
        assert hidden not in payload


async def test_ml_label_claim_material_and_dataset_membership(db_session):
    fixture = await seed(db_session, with_children=False)
    source, args = await observation(db_session, identifier=fixture["paper"])
    table = Base.metadata.tables["materials"]
    await db_session.execute(table.update().where(table.c.id == fixture["material"]).values(records=[{"paper_id": source}]))
    report = await service.inspect_source_impact(db_session, **args)
    assert identifiers(report, "material_claims") == {str(fixture["claim"])}
    assert identifiers(report, "ml_examples") == {str(fixture["example"])}
    assert identifiers(report, "ml_dataset_snapshots") == {str(fixture["args"]["dataset_id"])}
    assert {item["kind"] for item in relations(report, "ml_examples", fixture["example"])} == {
        "example_label_claim", "example_material_governance"}
    assert "transitive_research_event_and_ml_feature_dependencies" in report["unsupported_scopes"]


async def test_digest_deterministic_and_not_a_scientific_row_hash(db_session):
    source, args = await observation(db_session)
    target = await material(db_session, source=source)
    first = await service.inspect_source_impact(db_session, **args)
    second = await service.inspect_source_impact(db_session, **args)
    assert first["inventory_sha256"] == second["inventory_sha256"]
    body = {key: value for key, value in first.items() if key not in {"inventory_sha256", "observation"}}
    assert first["inventory_sha256"] == digest(body)
    table = Base.metadata.tables["materials"]
    await db_session.execute(table.update().where(table.c.id == target).values(
        records=[{"paper_id": source, "tc_kelvin": 111}, {"paper_id": source, "tc_kelvin": 222}]))
    duplicate = await service.inspect_source_impact(db_session, **args)
    assert duplicate["inventory_sha256"] == first["inventory_sha256"]
    child = await material(db_session, parent=target)
    changed = await service.inspect_source_impact(db_session, **args)
    assert changed["event"] == first["event"]
    assert changed["inventory_sha256"] != first["inventory_sha256"]
    assert child in identifiers(changed, "materials")


async def test_same_nodes_changed_parent_edges_change_digest(db_session):
    source, args = await observation(db_session)
    left, right = [await material(db_session, source=source) for _ in range(2)]
    child = await material(db_session, parent=left)
    first = await service.inspect_source_impact(db_session, **args)
    table = Base.metadata.tables["materials"]
    await db_session.execute(table.update().where(table.c.id == child).values(parent_material_id=right))
    second = await service.inspect_source_impact(db_session, **args)
    assert identifiers(first, "materials") == identifiers(second, "materials")
    assert first["inventory_sha256"] != second["inventory_sha256"]


async def test_accepted_mapping_change_is_observed_without_new_source_event(db_session):
    work, args = await observation(db_session, kind="work")
    source = await paper(db_session)
    mapping = Base.metadata.tables["paper_work_map"]
    await add(db_session, "paper_work_map", paper_id=source, work_id=work,
        match_method="manual", review_status="pending")
    before = await service.inspect_source_impact(db_session, **args)
    await db_session.execute(mapping.update().where(mapping.c.paper_id == source).values(review_status="accepted"))
    after = await service.inspect_source_impact(db_session, **args)
    assert before["event"] == after["event"]
    assert before["inventory_sha256"] != after["inventory_sha256"]
    assert identifiers(after, "papers") == {source}


async def test_frozen_pin_and_publication_references_never_modify_history(db_session):
    context = await proposed(db_session)
    _, args = await observation(db_session, identifier=context["fixture"]["paper"])
    before = await state(db_session)
    report = await service.inspect_source_impact(db_session, **args)
    assert identifiers(report, "research_releases") == {context["release"]["release_id"]}
    assert identifiers(report, "research_publication_proposals") == {context["proposal"]["id"]}
    assert await state(db_session) == before
    assert all(action["status"] == "not_scheduled" for action in report["next_actions"])
    assert report["complete_for_declared_scope"] is True
    assert tuple(report["supported_scopes"]) == service.SUPPORTED_SCOPES
    assert tuple(report["unsupported_scopes"]) == service.UNSUPPORTED_SCOPES
    for field in ("propagation_complete", "scientific_acceptance", "ml_training_approved", "source_reinstatement"):
        assert report[field] is False
    assert report["observation"]["persisted"] is report["observation"]["refresh_scheduled"] is False


@pytest.mark.parametrize("mutation", ["stale", "hash", "missing"])
async def test_current_exact_event_required(db_session, mutation):
    source, args = await observation(db_session)
    if mutation == "stale":
        await db_session.execute(sa.text("UPDATE papers SET status='published' WHERE id=:id"), {"id": source})
    elif mutation == "hash":
        args["expected_event_sha256"] = "0" * 64
    else:
        args["event_id"] = str(uuid4())
    with pytest.raises(service.SourceImpactError):
        await service.inspect_source_impact(db_session, **args)


async def test_cycle_cannot_be_reported_as_complete(db_session):
    source, args = await observation(db_session)
    root = await material(db_session, source=source)
    child = await material(db_session, parent=root)
    table = Base.metadata.tables["materials"]
    await db_session.execute(table.update().where(table.c.id == root).values(parent_material_id=child))
    with pytest.raises(service.SourceImpactError, match="cycle"):
        await service.inspect_source_impact(db_session, **args)


async def test_depth_bound_cannot_be_reported_as_complete(db_session, monkeypatch):
    source, args = await observation(db_session)
    parent = await material(db_session, source=source)
    for _ in range(3):
        parent = await material(db_session, parent=parent)
    monkeypatch.setattr(service, "MAX_PARENT_DEPTH", 2)
    with pytest.raises(service.SourceImpactLimitError, match="depth"):
        await service.inspect_source_impact(db_session, **args)


async def test_overlapping_record_roots_do_not_relax_ancestry_depth(db_session, monkeypatch):
    source, args = await observation(db_session)
    parent = None
    for _ in range(4):
        parent = await material(db_session, source=source, parent=parent)
    monkeypatch.setattr(service, "MAX_PARENT_DEPTH", 2)
    with pytest.raises(service.SourceImpactLimitError, match="depth"):
        await service.inspect_source_impact(db_session, **args)


async def test_final_envelope_included_in_byte_limit(db_session, monkeypatch):
    _, args = await observation(db_session)
    report = await service.inspect_source_impact(db_session, **args)
    body = {key: value for key, value in report.items() if key not in {"inventory_sha256", "observation"}}
    # The body fits but the actual response envelope, including observation
    # metadata and digest, does not. The result must fail, never truncate.
    monkeypatch.setattr(service, "MAX_DESCRIPTOR_BYTES", len(canonical(body)) + 50)
    with pytest.raises(service.SourceImpactLimitError, match="document byte"):
        await service.inspect_source_impact(db_session, **args)


@pytest.mark.parametrize("limit", ["MAX_NODES", "MAX_RELATIONS", "MAX_DESCRIPTOR_BYTES"])
async def test_inventory_resource_caps_fail_explicitly(db_session, monkeypatch, limit):
    source, args = await observation(db_session)
    for _ in range(3):
        await material(db_session, source=source)
    monkeypatch.setattr(service, limit, 2 if limit != "MAX_DESCRIPTOR_BYTES" else 100)
    with pytest.raises(service.SourceImpactLimitError):
        await service.inspect_source_impact(db_session, **args)


async def test_work_mapping_limit_before_unbounded_inventory(db_session, monkeypatch):
    work, args = await observation(db_session, kind="work")
    for _ in range(3):
        await add(db_session, "paper_work_map", paper_id=await paper(db_session), work_id=work,
            match_method="manual", review_status="accepted")
    monkeypatch.setattr(service, "MAX_PAPERS", 2)
    with pytest.raises(service.SourceImpactLimitError, match="row limit"):
        await service.inspect_source_impact(db_session, **args)


@pytest.mark.parametrize("records", [{"paper_id": "placeholder"}, ["placeholder"], [{"nested": {"paper_id": "placeholder"}}]])
async def test_json_source_identity_requires_exact_top_level_typed_record(db_session, records):
    source, args = await observation(db_session)
    # Deliberately malformed/irrelevant extraction shapes do not create edges.
    import json

    records = json.loads(json.dumps(records).replace("placeholder", source))
    unrelated = await material(db_session, records=records)
    report = await service.inspect_source_impact(db_session, **args)
    assert unrelated not in identifiers(report, "materials")


async def test_read_committed_is_rejected_before_event_lookup(db_session):
    _, args = await observation(db_session)
    engine = get_engine().execution_options(isolation_level="READ COMMITTED")
    try:
        async with AsyncSession(engine) as ordinary:
            with pytest.raises(service.SourceImpactError, match="REPEATABLE READ"):
                await service.inspect_source_impact(ordinary, **args)
    finally:
        await engine.dispose()


async def test_pending_orm_writes_are_rejected_without_autoflush(db_session):
    _, args = await observation(db_session)
    pending = Paper(id="unflushed:" + uuid4().hex, source="arxiv", title="pending",
                    authors=[], abstract="pending", status="published")
    db_session.add(pending)
    with pytest.raises(service.SourceImpactError, match="dedicated clean"):
        await service.inspect_source_impact(db_session, **args)
    assert pending in db_session.new
    db_session.expunge(pending)
