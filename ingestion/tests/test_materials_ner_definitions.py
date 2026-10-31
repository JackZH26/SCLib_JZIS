"""Result definition ownership and replay; synthetic engineering cases, not Gold."""
from copy import deepcopy

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.evidence_patch_defined import build_targets, apply_patch, EvidencePatch, verify_extraction
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.proposals import import_packet, verify_packet, review_rows
from ingestion.materials_ner.repair_selection import assess_repair
from ingestion.materials_ner.sources import save_bundle, make_blocks
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.wire_v6 import DefinedExtraction, output_schema, validate_coverage
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_shared import fixture as shared_fixture, two_references
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_pipeline import quantity


def fixture():
    bundle, inventory, raw = shared_fixture()
    raw["schema_version"] = "materials-ner-shared/2"
    procedure = raw["protocols"][0]
    definition = {k: procedure.pop(k) for k in ("criterion", "criterion_raw")}
    definition.update(parameters=[], evidence=[])
    raw["observations"][0]["definition"] = definition
    return bundle, inventory, raw


def two_criteria():
    bundle, inventory, raw = fixture()
    text = ("SYNTHETIC FIXTURE. Sample A was nominal MgB2 in bulk form. Our own "
            "four-probe resistivity measurement found an onset at 39 K and zero resistance at 37 K.")
    bundle.blocks = make_blocks(bundle.documents[0].id, [("synthetic:1", text)])
    observation = raw["observations"][0]
    observation["result"].update(quantity_kind="tc", quantity=quantity(39, "K", "39 K"), qualifiers=[])
    observation["result"]["evidence"][0]["fields"] = ["/quantity_kind", "/quantity", "/sample_id",
        "/state_id", "/protocol_id", "/origin", "/source_role"]
    observation["definition"].update(criterion="onset", criterion_raw="onset",
        evidence=[{"span_ids": ["S1"], "fields": ["/criterion", "/criterion_raw"]}])
    inventory["items"][0].update(value_raw="39 K", quantity_name_raw="superconducting onset")
    two_references(raw, inventory)
    raw["observations"][1]["result"]["quantity"] = quantity(37, "K", "37 K")
    raw["observations"][1]["definition"].update(criterion="zero_resistance", criterion_raw="zero resistance")
    inventory["items"][1].update(value_raw="37 K", quantity_name_raw="zero resistance")
    return bundle, inventory, raw


def test_distinct_result_criteria_survive_one_shared_procedure_without_extra_measurement_claim():
    bundle, inventory, raw = two_criteria()
    jsonschema.validate(raw, output_schema(bundle))
    wire = DefinedExtraction.model_validate(raw)
    expanded = wire.expand(bundle)
    assert len(wire.protocols) == 1 and len(expanded.protocols) == 2
    assert [p.criterion for p in expanded.protocols] == ["onset", "zero_resistance"]
    assert [r.quantity.value for r in expanded.results] == [39, 37]
    assert len(expanded.samples) == len(expanded.states) == 1
    assert validate_extraction(expanded, bundle)["valid"]
    assert validate_coverage(wire, Inventory.model_validate(inventory), bundle)["valid"]
    assert wire.model_dump() == raw


@pytest.mark.parametrize("mutation", ["invented_id", "omitted", "extra"])
def test_generation_schema_binds_dispositions_to_actual_inventory_context_ids(mutation):
    bundle, inventory, raw = fixture()
    schema = output_schema(bundle, Inventory.model_validate(inventory))
    jsonschema.validate(raw, schema)
    if mutation == "invented_id": raw["context_dispositions"][0]["context_id"] = "descriptive_replacement"
    if mutation == "omitted": raw["context_dispositions"] = []
    if mutation == "extra": raw["context_dispositions"] *= 2
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(raw, schema)


def test_empty_source_context_inventory_is_a_valid_empty_disposition_contract():
    bundle, inventory, raw = fixture()
    inventory["context_assertions"] = []; raw["context_dispositions"] = []
    schema = output_schema(bundle, Inventory.model_validate(inventory))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(raw, schema)
    assert validate_coverage(DefinedExtraction.model_validate(raw), Inventory.model_validate(inventory), bundle)["valid"]


@pytest.mark.parametrize("mutation", ["criterion_in_procedure", "missing_definition", "threshold_in_procedure"])
def test_wire_rejects_ambiguous_or_missing_definition_ownership(mutation):
    bundle, _, raw = fixture()
    if mutation == "criterion_in_procedure": raw["protocols"][0]["criterion"] = "onset"
    if mutation == "missing_definition": raw["observations"][0].pop("definition")
    if mutation == "threshold_in_procedure":
        raw["protocols"][0]["parameters"] = [{"kind": "resistance_fraction", "name_raw": "90%",
            "quantity": quantity(90, "%", "90%") }]
    with pytest.raises(ValidationError): DefinedExtraction.model_validate(raw)
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(raw, output_schema(bundle))


@pytest.mark.parametrize("mutation", ["procedure_criterion", "definition_method", "parameter_overflow", "context"])
def test_pointers_cannot_gain_a_different_owner_during_legacy_adaptation(mutation):
    _, _, raw = two_criteria()
    if mutation == "procedure_criterion": raw["protocols"][0]["evidence"][0]["fields"].append("/criterion")
    if mutation == "definition_method": raw["observations"][0]["definition"]["evidence"][0]["fields"].append("/method")
    if mutation == "parameter_overflow": raw["protocols"][0]["evidence"][0]["fields"].append("/parameters/0")
    if mutation == "context": raw["context_dispositions"][0]["bindings"][0]["field"] = "/criterion"
    with pytest.raises(ValidationError, match="definition_ownership_invalid"): DefinedExtraction.model_validate(raw)


def test_definition_evidence_patch_cannot_spread_one_criterion_to_another_result(tmp_path):
    bundle, inventory, raw = two_criteria()
    raw["observations"][0]["definition"]["evidence"][0]["fields"].remove("/criterion")
    wire = DefinedExtraction.model_validate(raw)
    validation = validate_extraction(wire.expand(bundle), bundle)
    targets = build_targets(wire, validation)
    assert len(targets) == 1 and targets[0]["entity"] == "definition"
    assert targets[0]["entity_id"] == raw["observations"][0]["id"]
    patch = {"schema_version": "materials-evidence-patch/1", "work_id": bundle.work_id,
        "base_compact_sha256": digest(wire.model_dump()), "decisions": [
            {"target_id": targets[0]["id"], "resolution": "bound", "span_ids": ["S1"], "reason": None}]}
    candidate, proof = apply_patch(wire, EvidencePatch.model_validate(patch), targets, bundle)
    assert proof["scientific_fields_unchanged"] and candidate.scientific_payload() == wire.scientific_payload()
    assert candidate.observations[1].model_dump() == wire.observations[1].model_dump()
    checked = validate_extraction(candidate.expand(bundle), bundle)
    assert checked["valid"] and assess_repair(wire, validation, candidate, checked)["admitted"]
    store = Store(tmp_path); bundle_hash, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=configuration(workflow="inventory_v6"))
    provider = SequenceProvider([inventory, raw, patch])
    outcome = run_one(store, job_id=job, provider_override=provider)
    assert outcome["state"] == "succeeded" and provider.calls == 3
    packet = import_packet(store, job); verify_packet(packet)
    assert packet["receipt"]["definition_projection"]["observations"][0]["procedure_id"] == raw["protocols"][0]["id"]
    assert len(packet["rows"]["protocols"]) == 2 and len(packet["rows"]["samples"]) == 1
    altered = deepcopy(packet["receipt"]); altered["extraction"]["protocols"][0]["criterion"] = "midpoint"
    with pytest.raises(ValueError, match="shared_extraction_reconstruction_mismatch"):
        verify_extraction(altered, bundle, packet["raw_output"])
    altered = deepcopy(packet["receipt"])
    altered["definition_projection"]["observations"][0]["procedure_id"] = "different-procedure"
    with pytest.raises(ValueError, match="result_definition_projection_manifest_mismatch"):
        verify_extraction(altered, bundle, packet["raw_output"])
    assert not packet["scientific_acceptance"] and not packet["ml_training_eligible"]


def test_common_method_patch_is_deduplicated_and_applies_to_both_explicit_variants():
    bundle, _, raw = two_criteria()
    raw["protocols"][0]["evidence"][0]["fields"].remove("/method")
    wire = DefinedExtraction.model_validate(raw)
    report = validate_extraction(wire.expand(bundle), bundle)
    targets = build_targets(wire, report)
    assert len(targets) == 1 and targets[0]["entity"] == "protocol"
    rows = review_rows(wire.expand(bundle), report)
    assert all(r["review_status"] == "quarantined" for r in rows["results"])
    patch = {"schema_version": "materials-evidence-patch/1", "work_id": bundle.work_id,
        "base_compact_sha256": digest(wire.model_dump()), "decisions": [
            {"target_id": targets[0]["id"], "resolution": "bound", "span_ids": ["S1"], "reason": None}]}
    candidate, _ = apply_patch(wire, EvidencePatch.model_validate(patch), targets, bundle)
    assert validate_extraction(candidate.expand(bundle), bundle)["valid"]
    assert [o.definition for o in wire.observations] == [o.definition for o in candidate.observations]


def test_parameter_offsets_and_context_targets_preserve_shared_and_result_specific_evidence():
    bundle, inventory, raw = two_criteria()
    body = raw["protocols"][0]
    body["parameters"] = [{"kind": "frequency", "name_raw": "frequency", "quantity": quantity(13, "Hz", "13 Hz")}]
    body["evidence"][0]["fields"].append("/parameters/0")
    definition = raw["observations"][0]["definition"]
    definition.update(criterion="resistance_fraction", criterion_raw="90%",
        parameters=[{"kind": "resistance_fraction", "name_raw": "normal-state resistance", "quantity": quantity(90, "%", "90%")}])
    definition["evidence"][0]["fields"].append("/parameters/0")
    inventory["context_assertions"].append({"id": "C2", "kind": "protocol", "description": "90% normal-state resistance definition", "span_ids": ["S1"]})
    raw["context_dispositions"].append({"context_id": "C2", "resolution": "carried", "explanation": None,
        "bindings": [{"entity": "definition", "entity_id": raw["observations"][0]["id"], "field": "/parameters/0"}]})
    wire = DefinedExtraction.model_validate(raw)
    adapted = wire.as_shared_v1()
    assert [p.kind for p in adapted.protocols[0].parameters] == ["frequency", "resistance_fraction"]
    assert [p.kind for p in adapted.protocols[1].parameters] == ["frequency"]
    assert adapted.context_dispositions[1].bindings[0].field == "/parameters/1"
    assert wire.source_protocol_field(adapted.protocols[0].id, "/parameters/1/quantity") == (
        "definition", raw["observations"][0]["id"], "/parameters/0/quantity")
    assert wire.source_protocol_field(adapted.protocols[0].id, "/parameters/0") == ("protocol", body["id"], "/parameters/0")
    # This test checks reference ownership only; its synthetic added parameters
    # intentionally lack source support and must not pass scientific validation.
    assert not validate_extraction(wire.expand(bundle), bundle)["valid"]


def test_definition_coverage_failure_quarantines_only_its_own_result():
    bundle, inventory, raw = two_criteria()
    first = raw["observations"][0]
    inventory["context_assertions"].append({"id": "C2", "kind": "protocol", "description": "Onset definition", "span_ids": ["S1"]})
    raw["context_dispositions"].append({"context_id": "C2", "resolution": "carried", "explanation": None,
        "bindings": [{"entity": "definition", "entity_id": first["id"], "field": "/criterion"}]})
    first["definition"]["evidence"][0]["fields"].remove("/criterion")
    wire = DefinedExtraction.model_validate(raw)
    report = validate_coverage(wire, Inventory.model_validate(inventory), bundle)
    assert {i["path"] for i in report["issues"]} == {"/protocols/0/criterion"}
    rows = review_rows(wire.expand(bundle), {"issues": report["issues"]})
    assert [r["review_status"] for r in rows["results"]] == ["quarantined", "pending_review"]


def test_unpatched_result_definition_packet_reconstructs_and_rejects_mutated_origin(tmp_path):
    bundle, inventory, raw = fixture()
    store = Store(tmp_path); bundle_hash, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=configuration(workflow="inventory_v6"))
    outcome = run_one(store, job_id=job, provider_override=SequenceProvider([inventory, raw]))
    assert outcome["state"] == "succeeded"
    packet = import_packet(store, job); verify_packet(packet)
    altered = deepcopy(packet["receipt"]); altered["extraction"]["results"][0]["origin"] = "computed"
    with pytest.raises(ValueError, match="shared_extraction_reconstruction_mismatch"):
        verify_extraction(altered, bundle, packet["raw_output"])
