"""Actual SQL→0054→verified distribution inventory→scientific observation.

All values, sources, calculation manifests and review declarations here are
synthetic. A fixture grant tests software admission, never human science.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from uuid import uuid4

import pytest
import sqlalchemy as sa

from services import discovery_scientific_cells as cells
from services import research_distribution as distribution
from services import research_freeze as freeze
from services import research_release_manifest as capsule
from services import scientific_result_effects as effects
from tests.rps_distribution_fixtures import distribution_inputs, release_document
from tests.test_priority_public_bundle import reseal_public_release
from tests.test_research_freeze import add, approved, seed, state
from tests.test_research_freeze import db_session as db_session
from tests.test_research_publication import actors
from tests.test_scientific_adjudication_schema import capture, decision_for, item_for, request_for

CANARY = "PRIVATE_SOURCE_CANARY_DO_NOT_DISCLOSE"


async def read_settings(db):
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='10s'"))


async def cell_fixture(db, *, properties=None, computed=True, structure=False, sample=False,
                       reviewed=False, before_freeze=None):
    """Reusable real, registered package; arbitrary caller row dicts are not roots.

    `properties` are native seed specifications, not service input. The returned
    inventory is the unchanged actual distribution registration result.
    """
    await read_settings(db)
    people = await actors(db)
    source = await seed(db, with_children=False)
    await db.execute(sa.text("UPDATE materials SET formula='TEST',formula_normalized='TEST',"
        "family='synthetic',total_papers=1,needs_review=false WHERE id=:id"), {"id": source["material"]})
    await db.execute(sa.text("UPDATE works SET publication_status='active' WHERE id=:id"), {"id": source["work"]})
    await db.execute(sa.text("UPDATE research_events SET event_type=:kind,knowledge_origin='Inferred',"
        "context=CAST(:context AS jsonb) WHERE id=:id"),
        {"kind": "calculation" if computed else "curation", "context": '{"private":"' + CANARY + '"}', "id": source["event"]})
    await db.execute(sa.text("UPDATE material_states SET conditions=CAST(:context AS jsonb) WHERE id=:id"),
        {"context": '{"private":"' + CANARY + '"}', "id": source["state"]})

    async def artifact(kind, document):
        payload = capsule.canonical(document)
        sha = hashlib.sha256(payload).hexdigest()
        source["args"]["artifact_bytes"][sha] = payload
        return await add(db, "evidence_artifacts", kind=kind, schema_version="synthetic/1",
            source="synthetic-cell", record_sha256=sha, bytes_sha256=sha, hash_status="verified",
            access="restricted", metadata={"private": CANARY})

    if computed:
        manifest = await artifact("run_manifest", {"synthetic": True, "execution_verified": False, "private": CANARY})
        run = await add(db, "research_runs", run_kind="dfpt", status="completed", code_version="synthetic/1",
            settings_schema_version="synthetic/1", settings={"private": CANARY},
            input_manifest_id=manifest["id"], output_manifest_id=manifest["id"], record_sha256="2" * 64)
        source["run"] = run["id"]
        await db.execute(sa.text("UPDATE research_events SET producer_run_id=:run,knowledge_origin='Computed' WHERE id=:id"),
            {"run": run["id"], "id": source["event"]})
    if structure:
        coordinates = await artifact("structure", {"synthetic_coordinates": True, "private": CANARY})
        record = await add(db, "structure_records", material_id=source["material"], structure_kind="coordinates",
            artifact_id=coordinates["id"], coordinate_artifact_kind="structure", record_sha256="3" * 64)
        source["structure"] = record["id"]
        await db.execute(sa.text("UPDATE research_events SET structure_id=:structure WHERE id=:id"),
            {"structure": record["id"], "id": source["event"]})
    if sample:
        record = await add(db, "research_samples", material_id=source["material"], work_id=source["work"],
            sample_label=CANARY, source_artifact_id=source["source"])
        source["sample"] = record["id"]
        await db.execute(sa.text("UPDATE material_states SET sample_id=:sample WHERE id=:id"),
            {"sample": record["id"], "id": source["state"]})
    await add(db, "event_evidence", event_id=source["event"], link_type="source", artifact_id=source["source"],
        locator={"line": 3, "start_byte": 7, "end_byte": 20, "private": CANARY})
    specs = properties if properties is not None else [
        {"property_key": key, "relation": "unreported" if key == "superfluid_stiffness" else "exact",
         "value": None if key == "superfluid_stiffness" else -0.125 if key == "phonon_min_frequency" else 0}
        for key in cells.PROPERTY_UNITS]
    source["properties"] = []
    for index, spec in enumerate(specs):
        values = {"event_id": source["event"], "unit": cells.PROPERTY_UNITS[spec["property_key"]],
                  "record_sha256": hashlib.sha256(str(index).encode()).hexdigest(), "raw": {"private": CANARY}, **spec}
        source["properties"].append(await add(db, "event_properties", **values))
    if before_freeze is not None:
        await before_freeze(db, source)
    _, args = await approved(db, source)
    frozen = await freeze.freeze_research_release(db, **args, dry_run=False)
    shared = {"actors": people, "source": source, "capsule": frozen,
              "capsule_bytes": args["artifact_bytes"], "internal_artifacts": {},
              "evidence_source_kind": "calculation" if computed else "curation"}
    release = release_document(source_kind=shared["evidence_source_kind"])
    for item in release["artifacts"]:
        if item["kind"] == "state":
            item["content"].update(pressure_status="not_reported", pressure_gpa=None,
                                   temperature_role="unknown", temperature_k=None)
    for item in release["assessments"]:
        item["assessment"]["target_fit"] = "unresolved"
    release = reseal_public_release(release)
    context = await distribution_inputs(db, release, shared=shared)
    registration = await distribution.register_distribution(db, actor_user_id=people["curator"],
        request_key="synthetic-cell:" + uuid4().hex, **context["arguments"], dry_run=False)
    inventory = registration["inventory"]
    refs = [{"table": "event_properties", "row_id": row["row_id"], "row_sha256": row["row_sha256"]}
            for row in inventory["dependencies"] if row["table"] == "event_properties"]
    arguments = {"inventory": inventory, "property_refs": refs, "material_id": source["material"],
                 "state_id": str(source["state"]), "structure_id": str(source["structure"]) if structure else None}
    result = {"source": source, "frozen": frozen, "actors": people, "inventory": inventory,
              "arguments": arguments, "context": context, "registration": registration}
    if reviewed:
        await review_cell(db, result, scientific=True)
    return result


async def review_cell(db, fixture, *, scientific=False, decision="accept"):
    prop = next(row for row in fixture["source"]["properties"] if row["property_key"] == "phonon_min_frequency")
    subject = await add(db, "scientific_result_subjects", **await capture(db, prop["id"]))
    item = await item_for(db, subject, profile="recorded-sampled-frequency-fidelity/1.0.0", decision=decision)
    items = [item]
    if scientific:
        second = await item_for(db, subject, profile="sampled-phonon-minimum-review/1.0.0")
        second["extraction_decision_id"] = item["decision_id"]
        items.append(second)
    people = fixture["actors"]
    request = await request_for(db, {"reviewer": people["reviewer"], "grant": {"id": people["grants"]["reviewer"]}}, items)
    decisions = [await decision_for(db, request, subject, value, index) for index, value in enumerate(items)]
    await db.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    fixture["decisions"] = decisions
    return decisions


async def test_actual_eight_registry_rows_full_quantity_context_and_safe_sources(db_session):
    fixture = await cell_fixture(db_session, structure=True, sample=True)
    before = await state(db_session)
    result = await cells.build_observations(db_session, **fixture["arguments"])
    assert await state(db_session) == before
    observations = {value["property"]["property_key"]: value for value in result["observations"]}
    assert set(observations) == set(cells.PROPERTY_UNITS)
    assert observations["band_gap"]["quantity"] == {"relation": "exact", "value": 0, "lower": None, "upper": None, "unit": "eV"}
    assert observations["phonon_min_frequency"]["quantity"]["value"] == -0.125
    assert observations["superfluid_stiffness"]["quantity"] == {
        "relation": "unreported", "value": None, "lower": None, "upper": None, "unit": "K"}
    for item in result["observations"]:
        assert item["event"]["knowledge_origin"] == "Computed" and item["event"]["event_type"] == "calculation"
        assert item["state"]["pressure_status"] == "not_reported" and item["state"]["pressure_gpa"] is None
        assert item["state"]["temperature_role"] == "unknown" and item["state"]["temperature_k"] is None
        assert item["sample"]["id"] == str(fixture["source"]["sample"])
        assert item["structure"]["id"] == str(fixture["source"]["structure"])
        assert item["run"]["run_kind"] == "dfpt"
        assert item["sources"][0]["locator"] == {"line": 3, "start_byte": 7, "end_byte": 20}
        assert item["sources"][0]["relation_scope"] == "selected_event"
        assert item["source_occurrences"][0]["relation_scope"] == "event_snapshot_membership"
        assert item["normalization"]["status"] == "not_asserted"
        assert item["scientific_scope_accepted"] is item["ml_training_approved"] is item["public_release_authorized"] is False
    assert CANARY.encode() not in capsule.canonical(result)
    assert result["scientific_pins"] == await effects.resolve_result_statuses(db_session, [ref["row_id"] for ref in fixture["arguments"]["property_refs"]])
    assert set(result["dependency_ids"]) <= {row["dependency_id"] for row in fixture["inventory"]["dependencies"]}


@pytest.mark.parametrize("relation,value,lower,upper", [
    ("exact", 0, None, None), ("interval", None, 0, 2), ("lt", None, None, 2),
    ("le", None, None, 2), ("gt", None, 0, None), ("ge", None, 0, None),
    ("unreported", None, None, None),
])
async def test_native_nonpoint_quantities_never_fabricate_a_scalar(db_session, relation, value, lower, upper):
    fixture = await cell_fixture(db_session, properties=[{"property_key": "band_gap", "relation": relation,
        "value": value, "lower": lower, "upper": upper, "component_key": "spin-up"}])
    result = await cells.build_observations(db_session, **fixture["arguments"])
    item = result["observations"][0]
    assert item["quantity"] == {"relation": relation, "value": value, "lower": lower, "upper": upper, "unit": "eV"}
    assert item["property"]["component_key"] == "spin-up" and item["scientific_scope_accepted"] is False


async def test_current_exact_scientific_review_only_marks_its_own_phonon(db_session):
    fixture = await cell_fixture(db_session, reviewed=True)
    result = await cells.build_observations(db_session, **fixture["arguments"])
    accepted = [value for value in result["observations"] if value["scientific_scope_accepted"]]
    assert [value["property"]["property_key"] for value in accepted] == ["phonon_min_frequency"]
    assert accepted[0]["review"]["scopes"][1]["profile_version"] == "sampled-phonon-minimum-review/1.0.0"
    assert accepted[0]["public_release_authorized"] is accepted[0]["ml_training_approved"] is False


async def test_fidelity_acceptance_never_confers_scientific_acceptance(db_session):
    fixture = await cell_fixture(db_session)
    await review_cell(db_session, fixture)
    result = await cells.build_observations(db_session, **fixture["arguments"])
    assert not any(value["scientific_scope_accepted"] for value in result["observations"])


async def test_exact_negative_review_rejects_entire_construction(db_session):
    fixture = await cell_fixture(db_session)
    await review_cell(db_session, fixture, decision="reject")
    with pytest.raises(cells.DiscoveryScientificCellError, match="review_held"):
        await cells.build_observations(db_session, **fixture["arguments"])


@pytest.mark.parametrize("field", ["material_id", "state_id", "structure_id"])
async def test_identity_is_exact_not_same_formula_or_declared_state(db_session, field):
    fixture = await cell_fixture(db_session)
    args = {**fixture["arguments"], field: "different-material" if field == "material_id" else str(uuid4())}
    with pytest.raises(cells.DiscoveryScientificCellError, match="identity_mismatch"):
        await cells.build_observations(db_session, **args)


@pytest.mark.parametrize("change", ["duplicate", "too_many", "extra", "hash", "boolean_id", "empty"])
async def test_malformed_refs_reject_before_database_access(change):
    refs = [{"table": "event_properties", "row_id": str(uuid4()), "row_sha256": "a" * 64}]
    if change == "duplicate": refs *= 2
    elif change == "too_many": refs *= 101
    elif change == "extra": refs[0]["raw"] = CANARY
    elif change == "hash": refs[0]["row_sha256"] = True
    elif change == "boolean_id": refs[0]["row_id"] = True
    elif change == "empty": refs = []
    with pytest.raises(cells.DiscoveryScientificCellError):
        await cells.build_observations(None, inventory={}, property_refs=refs,
            material_id="synthetic", state_id=str(uuid4()), structure_id=None)


@pytest.mark.parametrize("change", ["missing_forward", "projection", "row_hash", "dependency_id", "ref_hash"])
async def test_no_missing_or_rehashed_substituted_inventory_can_enter(db_session, change):
    fixture = await cell_fixture(db_session)
    args = deepcopy(fixture["arguments"])
    entries = args["inventory"]["dependencies"]
    item = next(row for row in entries if row["table"] == "event_properties")
    if change == "missing_forward": entries[:] = [row for row in entries if row["table"] != "research_runs"]
    elif change == "projection": item["projection"]["value"] = 999
    elif change == "row_hash": item["row_sha256"] = "0" * 64
    elif change == "dependency_id": item["dependency_id"] = "0" * 64
    elif change == "ref_hash": args["property_refs"][0]["row_sha256"] = "0" * 64
    with pytest.raises(cells.DiscoveryScientificCellError):
        await cells.build_observations(db_session, **args)


async def test_unreviewed_global_material_hold_still_rejects(db_session):
    fixture = await cell_fixture(db_session)
    await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"), {"id": fixture["source"]["material"]})
    with pytest.raises(cells.DiscoveryScientificCellError, match="catalogue_held"):
        await cells.build_observations(db_session, **fixture["arguments"])


async def test_caller_mutation_after_first_await_cannot_replace_values(db_session, monkeypatch):
    fixture = await cell_fixture(db_session)
    args = fixture["arguments"]
    original = cells._session
    async def mutate(db):
        await original(db)
        args["property_refs"].clear()
        for row in args["inventory"]["dependencies"]:
            if row["table"] == "event_properties": row["projection"]["value"] = 999
    monkeypatch.setattr(cells, "_session", mutate)
    result = await cells.build_observations(db_session, **args)
    assert len(result["observations"]) == 8
    assert all(value["quantity"]["value"] != 999 for value in result["observations"])


async def test_unreviewed_work_hold_is_not_hidden_by_empty_review_heads(db_session):
    fixture = await cell_fixture(db_session, sample=True)
    await db_session.execute(sa.text("UPDATE works SET publication_status='retracted' WHERE id=:id"),
                             {"id": fixture["source"]["work"]})
    old_statuses = await effects.resolve_result_statuses(db_session,
        [ref["row_id"] for ref in fixture["arguments"]["property_refs"]])
    assert all(scope["effective_status"] == "unreviewed" for value in old_statuses.values() for scope in value["scopes"])
    with pytest.raises(cells.DiscoveryScientificCellError, match="source_held"):
        await cells.build_observations(db_session, **fixture["arguments"])


async def test_parent_material_hold_cannot_be_waived_by_child_visibility(db_session):
    async def parent(db, source):
        identifier = "synthetic-cell-parent:" + uuid4().hex
        await add(db, "materials", id=identifier, formula="TEST", formula_normalized="TEST",
                  needs_review=False, total_papers=1, records=[{"tc_kelvin": 1, "synthetic": True}])
        await db.execute(sa.text("UPDATE materials SET parent_material_id=:parent WHERE id=:id"),
                         {"parent": identifier, "id": source["material"]})
        source["parent"] = identifier
    fixture = await cell_fixture(db_session, before_freeze=parent)
    await db_session.execute(sa.text("UPDATE materials SET needs_review=true WHERE id=:id"),
                             {"id": fixture["source"]["parent"]})
    with pytest.raises(cells.DiscoveryScientificCellError, match="catalogue_held"):
        await cells.build_observations(db_session, **fixture["arguments"])


async def test_revoked_accepted_reviewer_blocks_without_erasing_history(db_session):
    from services.research_publication import revoke_role

    fixture = await cell_fixture(db_session, reviewed=True)
    await db_session.commit()
    await read_settings(db_session)
    await revoke_role(db_session, actor_user_id=fixture["actors"]["admin"],
        grant_id=fixture["actors"]["grants"]["reviewer"], reason_code="synthetic_cell_revoke", dry_run=False)
    with pytest.raises(cells.DiscoveryScientificCellError, match="review_held"):
        await cells.build_observations(db_session, **fixture["arguments"])


async def test_forward_evidence_is_retained_but_never_renamed_direct_support(db_session):
    async def lineage(db, source):
        event = await add(db, "research_events", material_id=source["material"], state_id=source["state"],
            event_type="measurement", knowledge_origin="Observed", record_sha256="8" * 64)
        prop = await add(db, "event_properties", event_id=event["id"], property_key="band_gap", relation="exact",
            value=1, unit="eV", record_sha256="9" * 64)
        await add(db, "event_evidence", event_id=event["id"], link_type="source", artifact_id=source["source"],
            locator={"source_locator": {"line": 8, "start_byte": 20, "end_byte": 40, "private": CANARY}})
        await add(db, "event_evidence", event_id=source["event"], link_type="derives_from", input_event_id=event["id"],
            input_property_id=prop["id"], locator={"private": CANARY})
        source["upstream_event"], source["upstream_property"] = str(event["id"]), str(prop["id"])
    fixture = await cell_fixture(db_session, before_freeze=lineage)
    selected = next(row for row in fixture["source"]["properties"] if row["property_key"] == "phonon_min_frequency")
    args = {**fixture["arguments"], "property_refs": [ref for ref in fixture["arguments"]["property_refs"]
                                                    if ref["row_id"] == str(selected["id"])]}
    result = await cells.build_observations(db_session, **args)
    links = result["observations"][0]["sources"]
    upstream = next(link for link in links if link["owner_event_id"] == fixture["source"]["upstream_event"])
    assert upstream["relation_scope"] == "forward_dependency" and upstream["link_type"] == "source"
    assert upstream["locator"] == {"line": 8, "start_byte": 20, "end_byte": 40}
    derives = next(link for link in links if link["link_type"] == "derives_from")
    assert derives["relation_scope"] == "selected_event" and derives["artifact"] is None
    assert derives["input_property_id"] == fixture["source"]["upstream_property"]
    assert derives["locator"] == {"scope": "locator_not_disclosed"}
    expected = next(row["dependency_id"] for row in fixture["inventory"]["dependencies"]
                    if row["row_id"] == fixture["source"]["upstream_property"])
    assert expected in result["dependency_ids"]
    assert CANARY.encode() not in capsule.canonical(result)


async def test_more_than_twenty_results_share_the_complete_status_inventory(db_session, monkeypatch):
    fixture = await cell_fixture(db_session, properties=[{"property_key": "band_gap", "relation": "exact",
        "value": index, "component_key": "component-" + str(index)} for index in range(21)])
    original = effects.resolve_result_statuses
    batches = []
    async def watched(db, ids):
        batches.append(len(ids))
        return await original(db, ids)
    monkeypatch.setattr(effects, "resolve_result_statuses", watched)
    result = await cells.build_observations(db_session, **fixture["arguments"])
    assert len(result["observations"]) == len(result["scientific_pins"]) == 21
    assert batches == [20, 1]


async def test_shared_subject_budget_refuses_whole_group_without_partial_output(db_session, monkeypatch):
    fixture = await cell_fixture(db_session)
    subject = await cells.capture_result_subject(db_session, fixture["arguments"]["property_refs"][0]["row_id"])
    monkeypatch.setattr(cells, "MAX_BYTES", len(subject.text.encode()) + 10)
    with pytest.raises(cells.DiscoveryScientificCellError, match="byte_limit"):
        await cells.build_observations(db_session, **fixture["arguments"])


@pytest.mark.parametrize("setting", ["SET LOCAL statement_timeout=0", "SET LOCAL TIME ZONE 'Asia/Singapore'"])
async def test_unbounded_or_non_utc_snapshot_refuses(db_session, setting):
    fixture = await cell_fixture(db_session)
    await db_session.execute(sa.text(setting))
    with pytest.raises(cells.DiscoveryScientificCellError):
        await cells.build_observations(db_session, **fixture["arguments"])
