"""Native scientific ownership, auxiliary uses and immutable private imports."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sqlite3

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner.contract import digest, parse_extraction
from ingestion.materials_ner.evidence_patch_native import build_targets, apply_patch, EvidencePatch, verify_extraction
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.proposals import import_packet, verify_packet, review_rows, ProposalDatabase
from ingestion.materials_ner.repair_selection import assess_repair
from ingestion.materials_ner.sources import make_blocks, save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction, training_exclusions
from ingestion.materials_ner.wire_v7 import NativeExtraction, output_schema, validate_coverage
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_definitions import two_criteria
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_pipeline import quantity


def fixture():
    bundle, inventory, raw = two_criteria()
    raw["schema_version"] = "materials-ner-shared/3"
    for procedure in raw["protocols"]: procedure["context_uses"] = []
    return bundle, inventory, raw


def auxiliary(bundle, raw, *, linked=True):
    bundle.blocks = make_blocks(bundle.documents[0].id, [("synthetic:1", bundle.blocks[0].text +
        " X-ray reflectivity measured Sample A thickness as 8 nm.")])
    state = raw["states"][0]
    state["conditions"] = [{"kind": "thickness", "role": "measurement", "quantity": quantity(8, "nm", "8 nm"),
        "orientation_raw": None, "basis_raw": "X-ray reflectivity", "window_position": None}]
    state["evidence"][0]["fields"].append("/conditions/0")
    procedure = {"id": "xrr", "method": "X-ray reflectivity", "method_class": "other",
        "observable": "specimen thickness", "details_raw": None, "parameters": [],
        "context_uses": [{"state_id": state["id"], "condition_index": 0}] if linked else [],
        "evidence": [{"span_ids": ["S1"], "fields": ["/method", "/method_class"] + (["/context_uses/0"] if linked else [])}]}
    raw["protocols"].append(procedure)
    return procedure


def checked(wire, inventory, bundle):
    result = validate_extraction(wire.expand(bundle), bundle)
    result["issues"].extend(validate_coverage(wire, Inventory.model_validate(inventory), bundle)["issues"])
    result["valid"] = not result["issues"]
    return result


def test_native_results_own_definitions_and_all_procedure_ids_survive_without_variants():
    bundle, inventory, raw = fixture(); auxiliary(bundle, raw)
    jsonschema.validate(raw, output_schema(bundle, Inventory.model_validate(inventory)))
    wire = NativeExtraction.model_validate(raw); extraction = wire.expand(bundle)
    assert extraction.schema_version == "materials-ner/5"
    assert len(extraction.protocols) == len(raw["protocols"]) == 2
    assert all("criterion" not in p.model_dump() for p in extraction.protocols)
    assert [r.definition.criterion for r in extraction.results] == ["onset", "zero_resistance"]
    assert extraction.results[0].protocol_id == extraction.results[1].protocol_id == raw["protocols"][0]["id"]
    assert extraction.protocols[1].context_uses[0].state_id == raw["states"][0]["id"]
    assert parse_extraction(extraction.model_dump()).model_dump() == extraction.model_dump()
    assert checked(wire, inventory, bundle)["valid"]
    assert any(e.field == "/definition/criterion" for e in extraction.results[0].evidence)
    assert wire.model_dump() == raw


@pytest.mark.parametrize("mutation", ["missing_state", "missing_condition", "negative_index", "duplicate_use", "cross_sample"])
def test_native_context_and_result_references_have_real_source_scoped_owners(mutation):
    bundle, _, raw = fixture(); procedure = auxiliary(bundle, raw)
    if mutation == "missing_state": procedure["context_uses"][0]["state_id"] = "unknown"
    if mutation == "missing_condition": procedure["context_uses"][0]["condition_index"] = 2
    if mutation == "negative_index": procedure["context_uses"][0]["condition_index"] = -1
    if mutation == "duplicate_use": procedure["context_uses"] *= 2
    if mutation == "cross_sample": raw["observations"][0]["sample_id"] = "different"
    with pytest.raises(ValidationError): NativeExtraction.model_validate(raw).expand(bundle)


def test_unassigned_auxiliary_is_retained_and_flagged_without_fabricating_an_observation(tmp_path):
    bundle, inventory, raw = fixture(); auxiliary(bundle, raw, linked=False)
    wire = NativeExtraction.model_validate(raw); extraction = wire.expand(bundle)
    report = checked(wire, inventory, bundle)
    assert [(i["code"],i["path"]) for i in report["issues"]] == [
        ("unassigned_procedure_scope_requires_review", "/protocols/1/context_uses")]
    rows = review_rows(extraction, report)
    assert len(rows["protocols"]) == 2 and len(rows["results"]) == 2
    assert rows["protocols"][1]["review_status"] == "quarantined"
    assert all(r["review_status"] == "pending_review" for r in rows["results"])
    store = Store(tmp_path); bundle_hash, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=configuration(workflow="inventory_v7"))
    outcome = run_one(store, job_id=job, provider_override=SequenceProvider([inventory, raw]))
    assert outcome["state"] == "quarantined"
    packet = import_packet(store, job); verify_packet(packet)
    database = ProposalDatabase(tmp_path/"private")
    assert database.ingest(packet)["inserted"] and not database.ingest(packet)["inserted"]
    assert database.summary()["tables"]["protocols"] == 2
    assert not packet["scientific_acceptance"] and not packet["ml_training_eligible"]


def test_method_evidence_failure_propagates_through_condition_use_to_referencing_results():
    bundle, inventory, raw = fixture(); procedure = auxiliary(bundle, raw)
    procedure["evidence"][0]["fields"].remove("/method")
    wire = NativeExtraction.model_validate(raw)
    rows = review_rows(wire.expand(bundle), checked(wire, inventory, bundle))
    assert "condition_method_has_validation_issues" in rows["states"][0]["issues"]
    assert all(r["review_status"] == "quarantined" for r in rows["results"])
    # No other source state is manufactured to attach the method.
    assert len(rows["states"]) == 1


def test_unreferenced_sample_and_state_are_retained_with_explicit_scope_findings():
    bundle, inventory, raw = fixture()
    raw["samples"].append(dict(raw["samples"][0],id="unassigned-sample"))
    raw["states"].append(dict(raw["states"][0],id="unassigned-state",sample_id="unassigned-sample"))
    wire = NativeExtraction.model_validate(raw); extraction = wire.expand(bundle)
    report = checked(wire,inventory,bundle)
    assert {i["code"] for i in report["issues"]} == {
        "unassigned_sample_scope_requires_review","unassigned_state_scope_requires_review"}
    assert len(extraction.samples) == len(extraction.states) == 2


def threshold_fixture():
    bundle, inventory, raw = fixture()
    bundle.blocks = make_blocks(bundle.documents[0].id, [("synthetic:1", bundle.blocks[0].text +
        " The definitions are 90% and 50% of normal-state resistance, respectively.")])
    for observation, value in zip(raw["observations"], [90, 50]):
        observation["definition"].update(criterion="resistance_fraction", criterion_raw=f"{value}%",
            parameters=[{"kind": "resistance_fraction", "name_raw": "normal-state resistance",
                         "quantity": quantity(value, "%", f"{value}%")}])
    raw["protocols"][0]["evidence"][0]["fields"].append("/parameters/0")
    return bundle, inventory, raw


def test_invalid_procedure_pointer_never_becomes_a_valid_result_threshold_binding(tmp_path):
    bundle, inventory, raw = threshold_fixture()
    wire = NativeExtraction.model_validate(raw); report = checked(wire, inventory, bundle)
    assert {i["path"] for i in report["issues"]} == {
        "/protocols/0/parameters/0", "/results/0/definition/parameters/0", "/results/1/definition/parameters/0",
        "/results/0/definition/parameters/0/quantity", "/results/1/definition/parameters/0/quantity"}
    targets = build_targets(wire, report)
    assert len(targets) == 3
    assert {t["entity"] for t in targets} == {"protocol", "definition"}
    assert next(t for t in targets if t["entity"] == "protocol")["permitted_action"] == "remove_invalid_pointer"
    patch = {"schema_version": "materials-evidence-patch/1", "work_id": bundle.work_id,
        "base_compact_sha256": digest(wire.model_dump()), "decisions": [
            {"target_id": t["id"], "resolution": "bound" if t["field_present"] else "remove_invalid_pointer",
             "span_ids": ["S1"] if t["field_present"] else [], "reason": None if t["field_present"] else "The shared procedure has no such parameter."}
            for t in targets]}
    candidate, proof = apply_patch(wire, EvidencePatch.model_validate(patch), targets, bundle)
    assert proof["scientific_fields_unchanged"] and candidate.scientific_payload() == wire.scientific_payload()
    checked_after = checked(candidate, inventory, bundle)
    assert checked_after["valid"] and assess_repair(wire, report, candidate, checked_after)["admitted"]
    assert candidate.protocols[0].parameters == []
    assert [o.definition.parameters[0].quantity.value for o in candidate.observations] == [90, 50]
    store = Store(tmp_path); bundle_hash, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=configuration(workflow="inventory_v7"))
    provider = SequenceProvider([inventory, raw, patch])
    outcome = run_one(store, job_id=job, provider_override=provider)
    assert outcome["state"] == "succeeded" and provider.calls == 3
    packet = import_packet(store, job); verify_packet(packet)
    assert len(packet["rows"]["protocols"]) == 1
    assert packet["receipt"]["extraction"]["results"][0]["definition"]["criterion"] == "resistance_fraction"
    changed = deepcopy(packet["receipt"])
    changed["extraction"]["results"][0]["definition"]["parameters"][0]["quantity"]["value"] = 50
    with pytest.raises(ValueError, match="shared_extraction_reconstruction_mismatch"):
        verify_extraction(changed, bundle, packet["raw_output"])
    assert all(not r["eligible"] for r in training_exclusions(candidate.expand(bundle),bundle,checked_after)["results"])


def test_context_definition_issues_use_native_result_paths_and_remain_result_scoped():
    bundle, inventory, raw = fixture()
    obs = raw["observations"][0]
    obs["definition"]["evidence"][0]["fields"].remove("/criterion")
    inventory["context_assertions"].append({"id": "C2", "kind": "protocol", "description": "Onset criterion", "span_ids": ["S1"]})
    raw["context_dispositions"].append({"context_id": "C2", "resolution": "carried", "explanation": None,
        "bindings": [{"entity": "definition", "entity_id": obs["id"], "field": "/criterion"}]})
    wire = NativeExtraction.model_validate(raw)
    report = validate_coverage(wire, Inventory.model_validate(inventory), bundle)
    assert {i["path"] for i in report["issues"]} == {"/results/0/definition/criterion"}
    assert [r["review_status"] for r in review_rows(wire.expand(bundle), report)["results"]] == ["quarantined", "pending_review"]


def load_script(name):
    path = Path(__file__).resolve().parents[2]/"scripts"/(name+".py")
    spec = importlib.util.spec_from_file_location(name+"_native_test", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def review_fixture(extraction):
    maps = {k:{e.id:e.model_dump() for e in getattr(extraction,k)} for k in ("samples","states","protocols")}
    return [{"row_id": "synthetic:"+r.id, "job_id": "synthetic", "work_id": extraction.work_id,
        "bundle_sha256": "a"*64, "receipt_sha256": "b"*64, "technical_review_status": "pending_review",
        "sample": maps["samples"][r.sample_id], "state": maps["states"][r.state_id],
        "protocol": maps["protocols"][r.protocol_id], "result": r.model_dump(),
        "scientific_acceptance":False,"ml_training_eligible":False} for r in extraction.results]


def test_review_database_displays_distinct_result_criteria_with_one_procedure(tmp_path):
    bundle, _, raw = fixture()
    rows = review_fixture(NativeExtraction.model_validate(raw).expand(bundle))
    module = load_script("materials_ner_pilot_quality")
    result = module.build_database(tmp_path/"review.sqlite3", rows, {})
    assert result["meaningful_value_and_evidence_round_trip"]
    with sqlite3.connect(tmp_path/"review.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM protocols").fetchone()[0] == 1
        assert db.execute("SELECT value,criterion FROM materials_review ORDER BY value DESC").fetchall() == [
            (39.0,"onset"),(37.0,"zero_resistance")]


def test_canary_checks_native_threshold_evidence_at_result_owner_only():
    bundle, _, raw = threshold_fixture()
    extraction = NativeExtraction.model_validate(raw).expand(bundle)
    row = review_fixture(extraction)[0]
    checker = load_script("materials_ner_canary_gate")
    reference = {"criterion":"resistance_fraction","parameters":[{"kind":"resistance_fraction","unit":"%","value":90}]}
    check = checker.checks(row, reference)
    assert check["criterion"] and check["resistance_fraction"] and not check["resistance_fraction_evidence"]
    # A source binding incorrectly attached to the common procedure cannot
    # satisfy the evidence requirement of the result's own definition.
    row["result"]["evidence"].append(dict(row["result"]["evidence"][0],field="/definition/parameters/0"))
    assert checker.checks(row, reference)["resistance_fraction_evidence"]
