"""Explicit representatives and quantity projection over synthetic exact pins.

The old public bundle is genuinely verified. Its fixture assessments/reviews
are synthetic policy examples, not a reviewed scientific pilot or ML labels.
All API tests, including pure cases, use the guarded disposable runner.
"""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from models.db import Base
from services import discovery_scientific_projection as service
from services import priority_public_bundle as public
from services.research_priority import digest
from tests.test_priority_public_bundle import (
    disclosure_for,
    public_release_payload,
    reseal_public_release,
)
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as db_session


async def projected_fixture(db, **options):
    """Shared actual package/selection fixture for independent governance tests."""
    from services import research_distribution
    from tests.test_discovery_scientific_cells import cell_fixture

    fixture = await cell_fixture(db, **options)
    bundle = fixture["context"]["bundle"]
    selection = selection_for(bundle, choose="test-1")
    choice = selection["representatives"][0]
    source, inventory = fixture["source"], fixture["inventory"]
    if source.get("structure"):
        row = next(row for row in inventory["dependencies"]
            if row["table"] == "structure_records" and row["row_id"] == str(source["structure"]))
        choice["structure"] = {key: row[key] for key in ("table", "row_id", "row_sha256")}
    for cell in choice["cells"]:
        rows = [row for row in inventory["dependencies"] if row["table"] == "event_properties"
                and row["projection"]["property_key"] == cell["property_key"]]
        cell["result_refs"] = [{key: row[key] for key in ("table", "row_id", "row_sha256")}
                               for row in sorted(rows, key=lambda row: row["row_id"])]
        if any(row["projection"]["relation"] != "unreported" for row in rows):
            cell.update(availability="reported", reason_code="retained_registered_result")
        elif rows:
            cell["reason_code"] = "source_does_not_report_value"
    package = await research_distribution._get(db, "packages", fixture["registration"]["package_id"], header=True)
    arguments = {"distribution_package_id": str(package["id"]),
        "expected_distribution_record_sha256": package["record_sha256"],
        "expected_inventory_sha256": package["inventory_sha256"], "public_bundle": bundle,
        "selection": selection, "expected_selection_sha256": digest(selection)}
    return {**fixture, "package": package, "bundle": bundle, "selection": selection, "arguments": arguments}


def add_assessment(release, identifier, *, new_material=False, lower_score=True):
    """Clone a fully pinned synthetic action; never fabricate real acceptance."""
    entry = deepcopy(release["assessments"][0])
    assessment = entry["assessment"]
    assessment["id"] = identifier
    assessment["action_summary"] = "Synthetic explicitly compared action " + identifier
    if lower_score:
        for dimension in assessment["dimensions"].values():
            dimension.update(anchor=0.0, lower=0.0, upper=0.0)
    originals = {row["id"]: row for row in release["artifacts"]}
    if new_material:
        material = deepcopy(originals[assessment["material"]["id"]])
        material["id"] = "material:" + identifier
        state = deepcopy(originals[assessment["state"]["id"]])
        state["id"] = "state:" + identifier
        state["content"]["material_id"] = material["id"]
        release["artifacts"].extend([material, state])
        assessment["material"]["id"] = material["id"]
        assessment["state"]["id"] = state["id"]
    action = deepcopy(originals[assessment["action"]["id"]])
    action["id"] = "action:" + identifier
    action["content"]["state_id"] = assessment["state"]["id"]
    review = deepcopy(originals[entry["review"]["id"]])
    review["id"] = "review:" + identifier
    assessment["action"]["id"], entry["review"]["id"] = action["id"], review["id"]
    release["artifacts"].extend([action, review])
    release["assessments"].append(entry)


def verified_bundle(*, alternatives=1, second_material=False):
    release = public_release_payload()
    for index in range(alternatives):
        add_assessment(release, "lower-action-" + str(index))
    if second_material:
        add_assessment(release, "second-material", new_material=True)
    return seal_bundle(release)


def seal_bundle(release):
    release = reseal_public_release(release)
    result = public.build_public_bundle(release, disclosure=disclosure_for(release))
    checked = public.verify_public_bundle(result, expected_bundle_sha256=result["bundle_sha256"],
        expected_release_sha256=release["manifest_sha256"])
    assert checked["integrity_verified"] is True and checked["scientific_acceptance"] is False
    return result


def reference(assessment):
    return {"id": assessment["id"], "revision": assessment["revision"], "sha256": digest(assessment)}


def selection_for(bundle, *, choose="lower-action-0"):
    groups = {}
    for entry in bundle["release"]["assessments"]:
        assessment = entry["assessment"]
        groups.setdefault(assessment["material"]["id"], []).append(assessment)
    representatives = []
    for material_id, assessments in sorted(groups.items()):
        picked = next((value for value in assessments if value["id"] == choose), assessments[0])
        representatives.append({"material": deepcopy(picked["material"]), "assessment": reference(picked),
            "structure": None, "rationale": "Explicit synthetic selection, independent of score ranking.",
            "alternatives": [reference(value) for value in sorted(assessments, key=lambda item: item["id"])
                             if value["id"] != picked["id"]],
            "cells": [{"property_key": key, "availability": "unknown", "reason_code": "no_matching_registered_result",
                       "result_refs": [], "evidence_refs": []} for key in sorted(service.REGISTRY)]})
    return {"version": service.SELECTION_VERSION, "release_manifest_sha256": bundle["release"]["manifest_sha256"],
            "public_bundle_sha256": bundle["bundle_sha256"], "representatives": representatives}


def captured(selection):
    return service.capture_selection(selection, digest(selection))


def test_lower_score_explicit_representative_is_kept_with_every_alternate():
    bundle = verified_bundle(alternatives=2)
    selection = captured(selection_for(bundle))
    chosen = service.representative_assessments(bundle, selection)
    scores = {row["id"]: row["result"]["score_display"] for row in bundle["rows"]}
    assert scores["lower-action-0"] < scores["test-1"]
    assert chosen[0]["assessment"]["id"] == "lower-action-0"
    assert [row["id"] for row in chosen[0]["alternate_rows"]] == ["lower-action-1", "test-1"]
    assert chosen[0]["assessment_row"]["result"]["score_display"] == scores["lower-action-0"]


def test_selection_capture_detaches_every_nested_container():
    original = selection_for(verified_bundle())
    result = captured(original)
    expected = deepcopy(result)
    original["representatives"][0]["alternatives"].clear()
    original["representatives"][0]["cells"][0]["evidence_refs"].append({"secret": "not retained"})
    assert result == expected


def test_exact_material_inventory_cannot_omit_or_repeat_a_material():
    bundle = verified_bundle(second_material=True)
    selection = selection_for(bundle)
    assert len(service.representative_assessments(bundle, captured(selection))) == 2
    omitted = deepcopy(selection)
    omitted["representatives"].pop()
    with pytest.raises(ValueError):
        service.representative_assessments(bundle, captured(omitted))
    duplicate = deepcopy(selection)
    duplicate["representatives"].append(deepcopy(duplicate["representatives"][0]))
    with pytest.raises(ValueError):
        captured(duplicate)


def test_release_reordering_needs_fresh_pin_but_never_changes_explicit_choice():
    bundle = verified_bundle(alternatives=2)
    selection = selection_for(bundle)
    release = deepcopy(bundle["release"])
    release["assessments"].reverse()
    release["artifacts"].reverse()
    changed = seal_bundle(release)
    with pytest.raises(ValueError):
        service.representative_assessments(changed, captured(selection))
    selection.update(release_manifest_sha256=changed["release"]["manifest_sha256"], public_bundle_sha256=changed["bundle_sha256"])
    assert service.representative_assessments(changed, captured(selection))[0]["assessment"]["id"] == "lower-action-0"


def test_added_action_requires_complete_alternate_inventory_without_autoselection():
    bundle = verified_bundle()
    selection = selection_for(bundle)
    release = deepcopy(bundle["release"])
    add_assessment(release, "new-alternate", lower_score=False)
    changed = seal_bundle(release)
    selection.update(release_manifest_sha256=changed["release"]["manifest_sha256"], public_bundle_sha256=changed["bundle_sha256"])
    with pytest.raises(ValueError):
        service.representative_assessments(changed, captured(selection))
    added = next(entry["assessment"] for entry in changed["release"]["assessments"] if entry["assessment"]["id"] == "new-alternate")
    selection["representatives"][0]["alternatives"].append(reference(added))
    selection["representatives"][0]["alternatives"].sort(key=lambda item: item["id"])
    assert service.representative_assessments(changed, captured(selection))[0]["assessment"]["id"] == "lower-action-0"


@pytest.mark.parametrize("mutation", ["material_hash", "assessment_id", "revision", "assessment_hash",
    "alternative_missing", "alternative_extra", "alternative_hash", "alternative_order", "foreign_material"])
def test_exact_representative_and_alternative_pins(mutation):
    bundle = verified_bundle(alternatives=2, second_material=True)
    selection = selection_for(bundle)
    choice = selection["representatives"][0]
    if mutation == "material_hash":
        choice["material"]["sha256"] = "0" * 64
    elif mutation == "assessment_id":
        choice["assessment"]["id"] = "missing-assessment"
    elif mutation == "revision":
        choice["assessment"]["revision"] += 1
    elif mutation == "assessment_hash":
        choice["assessment"]["sha256"] = "0" * 64
    elif mutation == "alternative_missing":
        choice["alternatives"].pop()
    elif mutation == "alternative_extra":
        choice["alternatives"].append(deepcopy(choice["assessment"]))
    elif mutation == "alternative_hash":
        choice["alternatives"][0]["sha256"] = "0" * 64
    elif mutation == "alternative_order":
        choice["alternatives"].reverse()
    else:
        choice["assessment"] = deepcopy(selection["representatives"][1]["assessment"])
    with pytest.raises(ValueError):
        service.representative_assessments(bundle, captured(selection))


@pytest.mark.parametrize("mutation", ["top_extra", "choice_extra", "cell_extra", "revision_bool", "revision_zero",
    "revision_float", "material_bool", "hash_upper", "hash_bool", "pin_mismatch", "version", "empty_rationale",
    "oversized_rationale", "missing_cell", "duplicate_cell", "rps_property", "unsorted_cells", "unknown_availability",
    "availability_bool", "invalid_reason", "result_wrong_table", "duplicate_ref", "reference_extra", "structure_wrong_table"])
def test_closed_selection_shapes_and_scalar_types(mutation):
    selection = selection_for(verified_bundle())
    choice, pin = selection["representatives"][0], None
    cell = choice["cells"][0]
    row = {"table": "event_properties", "row_id": str(uuid4()), "row_sha256": "a" * 64}
    if mutation == "top_extra": selection["scientific_acceptance"] = False
    elif mutation == "choice_extra": choice["score"] = 9999
    elif mutation == "cell_extra": cell["value"] = 0
    elif mutation.startswith("revision_"):
        choice["assessment"]["revision"] = {"revision_bool": True, "revision_zero": 0, "revision_float": 1.0}[mutation]
    elif mutation == "material_bool": choice["material"]["id"] = True
    elif mutation == "hash_upper": choice["material"]["sha256"] = "A" * 64
    elif mutation == "hash_bool": choice["assessment"]["sha256"] = False
    elif mutation == "pin_mismatch": pin = "0" * 64
    elif mutation == "version": selection["version"] = "unknown/1"
    elif mutation == "empty_rationale": choice["rationale"] = "   "
    elif mutation == "oversized_rationale": choice["rationale"] = "x" * 2001
    elif mutation == "missing_cell": choice["cells"].pop()
    elif mutation == "duplicate_cell": choice["cells"][1] = deepcopy(cell)
    elif mutation == "rps_property": cell["property_key"] = "rps_score"
    elif mutation == "unsorted_cells": choice["cells"].reverse()
    elif mutation == "unknown_availability": cell["availability"] = "probably_zero"
    elif mutation == "availability_bool": cell["availability"] = False
    elif mutation == "invalid_reason": cell["reason_code"] = "private raw prose"
    elif mutation == "result_wrong_table": cell["result_refs"] = [{**row, "table": "material_claims"}]
    elif mutation == "duplicate_ref": cell["result_refs"] = [row, deepcopy(row)]
    elif mutation == "reference_extra": cell["result_refs"] = [{**row, "value": 0}]
    elif mutation == "structure_wrong_table": choice["structure"] = row
    with pytest.raises(ValueError):
        service.capture_selection(selection, digest(selection) if pin is None else pin)


@pytest.mark.parametrize("availability", ["not_computed", "not_applicable", "conflicted"])
def test_missingness_or_conflict_declarations_require_exact_evidence_references(availability):
    selection = selection_for(verified_bundle())
    cell = selection["representatives"][0]["cells"][0]
    cell["availability"], cell["reason_code"] = availability, "synthetic_explicit_declaration"
    with pytest.raises(ValueError):
        captured(selection)
    cell["evidence_refs"] = [{"table": "evidence_artifacts", "row_id": str(uuid4()), "row_sha256": "a" * 64}]
    # Syntactic capture is not validation that the cited evidence supports it.
    assert captured(selection)["representatives"][0]["cells"][0]["availability"] == availability


def test_all_eight_scientific_registry_keys_remain_separate_from_policy_scores():
    expected = {"formation_energy_per_atom": "eV/atom", "energy_above_hull": "eV/atom", "band_gap": "eV",
        "dos_at_fermi": "states/eV/formula_unit", "electron_phonon_lambda": "1", "omega_log": "K",
        "phonon_min_frequency": "THz", "superfluid_stiffness": "K"}
    capabilities = service.registry_capabilities()
    fields = capabilities["scientific_properties"]
    assert {item["property_key"]: item["unit"] for item in fields} == expected
    assert all(item["populated_observations"] == 0 for item in fields)
    assert all(item["storage_supported"] is True and item["quantity_projection_supported"] is True for item in fields)
    assert {item["property_key"] for item in fields if item["exact_scientific_review_supported"]} == {"phonon_min_frequency"}
    assert capabilities["planned_groups"] == ["geometry", "competing_order"]
    assert not set(expected).intersection(capabilities["rps_fields"]["keys"])
    assert capabilities["rps_fields"]["kind"] == "policy_assessment_not_scientific_ground_truth"
    counts = service.registry_capabilities([{"cells": [{"property_key": key, "observations": [None] * index}
        for index, key in enumerate(sorted(expected))]}])
    assert [row["populated_observations"] for row in counts["scientific_properties"]] == list(range(8))


@pytest.mark.parametrize("field,value", [
    ("material", ""), ("material", "bad id"), ("material", "x" * 121),
    ("assessment", ""), ("assessment", "x/y"), ("assessment", "x" * 121),
    ("result", "not-a-uuid"), ("result", "ABCDEFAB-1234-5678-9123-ABCDEFABCDEF"),
    ("structure", "not-a-uuid"), ("evidence", "not-a-uuid"),
    ("rationale", " " + "x" * 1999 + " "), ("rationale", "hidden\x00text"),
])
def test_ids_are_closed_and_rationale_size_counts_original_text(field, value):
    selection = selection_for(verified_bundle())
    choice = selection["representatives"][0]
    if field in {"material", "assessment"}:
        choice[field]["id"] = value
    elif field == "rationale":
        choice["rationale"] = value
    elif field == "structure":
        choice["structure"] = {"table": "structure_records", "row_id": value, "row_sha256": "a" * 64}
    else:
        choice["cells"][0]["result_refs" if field == "result" else "evidence_refs"] = [
            {"table": "event_properties" if field == "result" else "evidence_artifacts",
             "row_id": value, "row_sha256": "a" * 64}]
    with pytest.raises(ValueError):
        captured(selection)


@pytest.mark.parametrize("field,limit", [("result_refs", 8), ("evidence_refs", 20)])
def test_reference_lists_reject_over_budget_instead_of_clipping(field, limit):
    selection = selection_for(verified_bundle())
    table = "event_properties" if field == "result_refs" else "evidence_artifacts"
    selection["representatives"][0]["cells"][0][field] = [
        {"table": table, "row_id": identifier, "row_sha256": "a" * 64}
        for identifier in sorted(str(uuid4()) for _ in range(limit + 1))]
    with pytest.raises(ValueError):
        captured(selection)


def test_selection_byte_budget_fails_without_partial_capture(monkeypatch):
    selection = selection_for(verified_bundle())
    original = deepcopy(selection)
    monkeypatch.setattr(service, "MAX_SELECTION_BYTES", 64)
    with pytest.raises(ValueError):
        captured(selection)
    assert selection == original


async def test_actual_full_projection_retains_zero_negative_unreported_and_pending_scope(db_session):
    from tests.test_discovery_scientific_cells import CANARY
    fixture = await projected_fixture(db_session, structure=True, sample=True)
    before = await state(db_session)
    result = await service.build_projection(db_session, **fixture["arguments"])
    assert await state(db_session) == before
    payload = result["payload"]
    row = payload["rows"][0]
    cells = {cell["property_key"]: cell for cell in row["cells"]}
    assert set(cells) == set(service.REGISTRY)
    assert cells["band_gap"]["observations"][0]["quantity"]["value"] == 0
    assert cells["phonon_min_frequency"]["observations"][0]["quantity"]["value"] == -0.125
    assert cells["superfluid_stiffness"]["availability"] == "unknown"
    assert cells["superfluid_stiffness"]["reason_code"] == "source_does_not_report_value"
    assert cells["superfluid_stiffness"]["observations"][0]["quantity"]["value"] is None
    assert row["structure"]["row_id"] == str(fixture["source"]["structure"])
    assert row["state"]["row_id"] == str(fixture["source"]["state"])
    assert row["state_context"]["pressure_gpa"] is None
    assert row["assessment"] == fixture["bundle"]["rows"][0]
    assert payload["scientific_acceptance"] is payload["ml_training_approved"] is payload["public_release_authorized"] is False
    assert len(result["scientific_pins"]) == 8
    assert CANARY not in str(payload)


async def test_actual_empty_property_inventory_is_unknown_not_zero_or_not_computed(db_session):
    fixture = await projected_fixture(db_session, properties=[])
    before = await state(db_session)
    result = await service.build_projection(db_session, **fixture["arguments"])
    assert await state(db_session) == before
    assert result["scientific_pins"] == {}
    for cell in result["payload"]["rows"][0]["cells"]:
        assert cell["availability"] == "unknown" and cell["reason_code"] == "no_matching_registered_result"
        assert cell["observations"] == cell["result_refs"] == []
        assert "value" not in cell
    assert all(item["populated_observations"] == 0 for item in result["payload"]["capabilities"]["scientific_properties"])


@pytest.mark.parametrize("status", ["not_computed", "not_applicable"])
async def test_actual_absence_declaration_needs_exact_retained_evidence_but_adds_no_value(db_session, status):
    fixture = await projected_fixture(db_session, properties=[])
    choice = fixture["selection"]["representatives"][0]
    evidence = next(row for row in fixture["inventory"]["dependencies"] if row["table"] == "research_runs")
    cell = next(cell for cell in choice["cells"] if cell["property_key"] == "band_gap")
    cell.update(availability=status, reason_code="synthetic_explicit_declaration",
                evidence_refs=[{key: evidence[key] for key in ("table", "row_id", "row_sha256")}])
    arguments = {**fixture["arguments"], "expected_selection_sha256": digest(fixture["selection"])}
    before = await state(db_session)
    result = await service.build_projection(db_session, **arguments)
    actual = next(cell for cell in result["payload"]["rows"][0]["cells"] if cell["property_key"] == "band_gap")
    assert actual["availability"] == status and actual["observations"] == []
    assert actual["availability_basis"] == "explicit_review_required_declaration"
    assert await state(db_session) == before
    cell["evidence_refs"][0]["row_sha256"] = "0" * 64
    arguments["expected_selection_sha256"] = digest(fixture["selection"])
    with pytest.raises(ValueError):
        await service.build_projection(db_session, **arguments)
    assert await state(db_session) == before


@pytest.mark.parametrize("status", ["unknown", "not_computed", "not_applicable"])
async def test_existing_quantified_result_cannot_be_disguised_as_missing(db_session, status):
    fixture = await projected_fixture(db_session, properties=[{"property_key": "band_gap", "relation": "exact", "value": 0}])
    cell = next(cell for cell in fixture["selection"]["representatives"][0]["cells"] if cell["property_key"] == "band_gap")
    evidence = next(row for row in fixture["inventory"]["dependencies"] if row["table"] == "research_runs")
    cell.update(availability=status, evidence_refs=[{key: evidence[key] for key in ("table", "row_id", "row_sha256")}])
    arguments = {**fixture["arguments"], "expected_selection_sha256": digest(fixture["selection"])}
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.build_projection(db_session, **arguments)
    assert await state(db_session) == before


@pytest.mark.parametrize("change", ["omitted_result", "result_hash", "structure_none", "structure_pin", "inventory_pin", "package_pin"])
async def test_actual_exact_root_state_structure_and_inventory_cannot_be_substituted(db_session, change):
    fixture = await projected_fixture(db_session, structure=True,
        properties=[{"property_key": "band_gap", "relation": "exact", "value": 0}])
    arguments = deepcopy(fixture["arguments"])
    choice = arguments["selection"]["representatives"][0]
    cell = next(cell for cell in choice["cells"] if cell["property_key"] == "band_gap")
    if change == "omitted_result":
        cell.update(availability="unknown", reason_code="no_matching_registered_result", result_refs=[])
    elif change == "result_hash": cell["result_refs"][0]["row_sha256"] = "0" * 64
    elif change == "structure_none": choice["structure"] = None
    elif change == "structure_pin": choice["structure"]["row_sha256"] = "0" * 64
    elif change == "inventory_pin": arguments["expected_inventory_sha256"] = "0" * 64
    elif change == "package_pin": arguments["expected_distribution_record_sha256"] = "0" * 64
    arguments["expected_selection_sha256"] = digest(arguments["selection"])
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.build_projection(db_session, **arguments)
    assert await state(db_session) == before


async def test_large_source_quantity_is_not_clipped_or_converted_to_a_priority_score(db_session):
    fixture = await projected_fixture(db_session, properties=[{"property_key": "band_gap", "relation": "exact", "value": 1e20}])
    result = await service.build_projection(db_session, **fixture["arguments"])
    row = result["payload"]["rows"][0]
    cell = next(cell for cell in row["cells"] if cell["property_key"] == "band_gap")
    assert cell["observations"][0]["quantity"]["value"] == 1e20
    assert cell["observations"][0]["normalization"]["status"] == "not_asserted"
    assert row["assessment"] == fixture["bundle"]["rows"][0]
    assert "rps_score" not in cell and "score" not in cell


async def test_conflicting_same_component_results_are_retained_without_averaging(db_session):
    async def add_conflict(db, source):
        event = await add(db, "research_events", material_id=source["material"], state_id=source["state"],
            event_type="curation", knowledge_origin="Inferred", record_sha256=digest({"synthetic_second_event": True}))
        prop = await add(db, "event_properties", event_id=event["id"], property_key="band_gap", relation="exact",
            value=2.0, unit="eV", component_key="bulk", record_sha256=digest({"synthetic_second_value": 2.0}))
        await add(db, "event_evidence", event_id=event["id"], link_type="source", artifact_id=source["source"], locator={"line": 4})
        await add(db, "snapshot_event_memberships", snapshot_id=source["snapshot"], event_id=event["id"], event_revision=1,
            source_occurrence_key="synthetic-conflicting-result", locator={"line": 4},
            source_record_sha256=prop["record_sha256"], result_manifest_sha256=prop["record_sha256"])
    fixture = await projected_fixture(db_session, computed=False, before_freeze=add_conflict,
        properties=[{"property_key": "band_gap", "relation": "exact", "value": 0.0}])
    cell = next(cell for cell in fixture["selection"]["representatives"][0]["cells"] if cell["property_key"] == "band_gap")
    evidence = next(row for row in fixture["inventory"]["dependencies"] if row["table"] == "event_evidence")
    cell.update(availability="conflicted", reason_code="synthetic_conflicting_observations",
        evidence_refs=[{key: evidence[key] for key in ("table", "row_id", "row_sha256")}])
    arguments = {**fixture["arguments"], "expected_selection_sha256": digest(fixture["selection"])}
    before = await state(db_session)
    result = await service.build_projection(db_session, **arguments)
    actual = next(cell for cell in result["payload"]["rows"][0]["cells"] if cell["property_key"] == "band_gap")
    assert actual["availability"] == "conflicted"
    assert sorted(item["quantity"]["value"] for item in actual["observations"]) == [0.0, 2.0]
    assert "value" not in actual and len(actual["result_refs"]) == 2
    assert await state(db_session) == before


async def test_different_components_do_not_become_a_conflict_or_a_single_value(db_session):
    fixture = await projected_fixture(db_session, properties=[
        {"property_key": "band_gap", "component_key": "spin-up", "relation": "exact", "value": 0.0},
        {"property_key": "band_gap", "component_key": "spin-down", "relation": "exact", "value": 2.0}])
    cell = next(cell for cell in fixture["selection"]["representatives"][0]["cells"] if cell["property_key"] == "band_gap")
    result = await service.build_projection(db_session, **fixture["arguments"])
    actual = next(cell for cell in result["payload"]["rows"][0]["cells"] if cell["property_key"] == "band_gap")
    assert {item["property"]["component_key"] for item in actual["observations"]} == {"spin-up", "spin-down"}
    evidence = next(row for row in fixture["inventory"]["dependencies"] if row["table"] == "event_evidence")
    cell.update(availability="conflicted", evidence_refs=[{key: evidence[key] for key in ("table", "row_id", "row_sha256")}])
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.build_projection(db_session, **{**fixture["arguments"], "expected_selection_sha256": digest(fixture["selection"])})
    assert await state(db_session) == before


async def test_only_exact_scientific_reviewed_property_is_marked_accepted(db_session):
    fixture = await projected_fixture(db_session, reviewed=True)
    result = await service.build_projection(db_session, **fixture["arguments"])
    accepted = [item["property"]["property_key"] for cell in result["payload"]["rows"][0]["cells"]
                for item in cell["observations"] if item["scientific_scope_accepted"]]
    assert accepted == ["phonon_min_frequency"]
    assert all(result["payload"][flag] is False for flag in service.AUTHORITY)


async def test_source_hold_after_registration_withholds_whole_projection_without_writes(db_session):
    from tests.test_discovery_scientific_cells import read_settings
    fixture = await projected_fixture(db_session)
    await db_session.commit()
    papers = Base.metadata.tables["papers"]
    await db_session.execute(papers.update().where(papers.c.id == fixture["source"]["paper"]).values(status="retracted"))
    await db_session.commit()
    await read_settings(db_session)
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.build_projection(db_session, **fixture["arguments"])
    assert await state(db_session) == before


async def test_two_rps_descriptors_cannot_duplicate_one_actual_material_in_projection(db_session):
    from services import research_distribution as distribution
    from tests.rps_distribution_fixtures import distribution_inputs

    fixture = await projected_fixture(db_session, properties=[])
    release = deepcopy(fixture["context"]["release"])
    release["id"] = "synthetic-alias-" + uuid4().hex
    add_assessment(release, "alias-action", new_material=True)
    release = reseal_public_release(release)
    context = await distribution_inputs(db_session, release, shared=fixture["context"]["shared"])
    registered = await distribution.register_distribution(db_session, actor_user_id=fixture["actors"]["curator"],
        request_key=uuid4().hex, **context["arguments"], dry_run=False)
    material_bindings = [item for item in registered["inventory"]["artifact_bindings"] if item["artifact_kind"] == "material"]
    assert len(material_bindings) == 2
    assert len({item["artifact_id"] for item in material_bindings}) == 2
    assert {item["identity"]["row_id"] for item in material_bindings} == {fixture["source"]["material"]}
    package = await distribution._get(db_session, "packages", registered["package_id"], header=True)
    selection = selection_for(context["bundle"])
    assert len(service.representative_assessments(context["bundle"], captured(selection))) == 2
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.build_projection(db_session, distribution_package_id=str(package["id"]),
            expected_distribution_record_sha256=package["record_sha256"], expected_inventory_sha256=package["inventory_sha256"],
            public_bundle=context["bundle"], selection=selection, expected_selection_sha256=digest(selection))
    assert await state(db_session) == before


async def test_retained_source_for_another_exact_state_cannot_declare_selected_absence(db_session):
    from services.research_release_manifest import canonical

    async def another_state(db, source):
        document = {"synthetic_declaration": "Not computed in a different state; no real scientific assertion."}
        payload, sha = canonical(document), digest(document)
        artifact = await add(db, "evidence_artifacts", kind="literature_locator", schema_version="synthetic/1",
            source="synthetic-unrelated-state", bytes_sha256=sha, record_sha256=sha, hash_status="verified", access="restricted")
        source["args"]["artifact_bytes"][sha] = payload
        source["unrelated_artifact"] = artifact["id"]
        state_row = await add(db, "material_states", material_id=source["material"], resolution="source_scoped",
            condition_schema_version="synthetic/1", pressure_status="not_reported", temperature_role="unknown",
            context_sha256=digest({"other_state": True}), source_artifact_id=artifact["id"])
        event = await add(db, "research_events", material_id=source["material"], state_id=state_row["id"],
            event_type="curation", knowledge_origin="Inferred", record_sha256=sha)
        await add(db, "event_evidence", event_id=event["id"], link_type="source", artifact_id=artifact["id"], locator={"line": 8})
        await add(db, "snapshot_event_memberships", snapshot_id=source["snapshot"], event_id=event["id"], event_revision=1,
            source_occurrence_key="synthetic-other-state", locator={"line": 8}, source_record_sha256=sha, result_manifest_sha256=sha)

    fixture = await projected_fixture(db_session, properties=[], before_freeze=another_state)
    dependency = next(row for row in fixture["inventory"]["dependencies"]
        if row["table"] == "evidence_artifacts" and row["row_id"] == str(fixture["source"]["unrelated_artifact"]))
    await service.build_projection(db_session, **fixture["arguments"])
    before = await state(db_session)
    for status in ("not_computed", "not_applicable"):
        selection = deepcopy(fixture["selection"])
        cell = next(item for item in selection["representatives"][0]["cells"] if item["property_key"] == "band_gap")
        cell.update(availability=status, reason_code="synthetic_other_state_declaration",
            evidence_refs=[{key: dependency[key] for key in ("table", "row_id", "row_sha256")}])
        with pytest.raises(ValueError):
            await service.build_projection(db_session, **{**fixture["arguments"], "selection": selection,
                "expected_selection_sha256": digest(selection)})
        assert await state(db_session) == before
