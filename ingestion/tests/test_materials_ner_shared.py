"""Shared graph fidelity and isolation; synthetic fixtures are not scientific Gold."""
from copy import deepcopy
import json

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.evidence_patch_shared import build_targets, apply_patch, EvidencePatch, verify_extraction
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.proposals import import_packet, verify_packet, review_rows
from ingestion.materials_ner.repair_selection import assess_repair
from ingestion.materials_ner.sources import save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.wire_v5 import SharedExtraction, output_schema, validate_coverage
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_inventory_v4 import fixture as flat_fixture
from test_materials_ner_inventory_v2 import SequenceProvider


def fixture():
    bundle, inventory, flat = flat_fixture()
    obs = flat["observations"][0]
    raw = {k: deepcopy(v) for k, v in flat.items() if k not in {"schema_version", "observations", "context_dispositions"}}
    raw.update(schema_version="materials-ner-shared/1",
        samples=[dict(obs["sample"], id="sample-A")],
        states=[dict(obs["state"], id="state-A", sample_id="sample-A")],
        protocols=[dict(obs["protocol"], id="protocol-1")],
        observations=[{"id": obs["id"], "sample_id": "sample-A", "state_id": "state-A",
            "protocol_id": "protocol-1", "inventory_item_ids": obs["inventory_item_ids"], "result": obs["result"]}],
        context_dispositions=[])
    for context in flat["context_dispositions"]:
        row = deepcopy(context)
        row["bindings"] = [{"entity": b["entity"], "entity_id": {"sample": "sample-A", "state": "state-A",
            "protocol": "protocol-1", "result": obs["id"]}[b["entity"]], "field": b["field"]} for b in context["bindings"]]
        raw["context_dispositions"].append(row)
    return bundle, inventory, raw


def two_references(raw, inventory):
    """Two explicit synthetic result occurrences; no scientific duplicate decision."""
    other = deepcopy(raw["observations"][0]); other.update(id="O2", inventory_item_ids=["I2"])
    raw["observations"].append(other)
    inventory["items"].append(dict(inventory["items"][0], id="I2"))
    inventory["span_dispositions"][0]["item_ids"].append("I2")


def test_shared_graph_retains_one_entity_with_two_explicit_result_references():
    bundle, inventory, raw = fixture(); two_references(raw, inventory)
    jsonschema.validate(raw, output_schema(bundle))
    wire = SharedExtraction.model_validate(raw); extraction = wire.expand(bundle)
    assert [len(getattr(extraction, k)) for k in ("samples", "states", "protocols", "results")] == [1, 1, 1, 2]
    assert all(r.sample_id == "sample-A" and r.state_id == "state-A" for r in extraction.results)
    assert validate_extraction(extraction, bundle)["valid"]
    assert validate_coverage(wire, Inventory.model_validate(inventory), bundle)["valid"]
    assert len(wire.as_flat().context_dispositions[0].bindings) == 2
    assert len(wire.context_dispositions[0].bindings) == 1


@pytest.mark.parametrize("mutation,match",[("duplicate", "duplicate_or_empty_shared_sample_id"),
    ("dangling_state", "shared_observation_reference_invalid"),
    ("cross_sample", "shared_observation_state_sample_mismatch"),
    ("unused", "unreferenced_shared_entity"), ("context", "shared_context_target_invalid")])
def test_shared_graph_rejects_invalid_ids_cross_sample_states_and_silent_discard(mutation, match):
    _, _, raw = fixture()
    if mutation == "duplicate": raw["samples"] *= 2
    if mutation == "dangling_state": raw["observations"][0]["state_id"] = "missing"
    if mutation in {"cross_sample", "unused"}:
        raw["samples"].append(dict(raw["samples"][0], id="sample-B"))
    if mutation == "cross_sample": raw["observations"][0]["sample_id"] = "sample-B"
    if mutation == "context": raw["context_dispositions"][0]["bindings"][0]["entity_id"] = "missing"
    with pytest.raises(ValidationError, match=match): SharedExtraction.model_validate(raw)


def test_equal_formulas_are_not_automatically_merged_into_one_sample():
    bundle, inventory, raw = fixture(); two_references(raw, inventory)
    raw["samples"].append(dict(raw["samples"][0], id="sample-B"))
    raw["states"].append(dict(raw["states"][0], id="state-B", sample_id="sample-B"))
    raw["observations"][1].update(sample_id="sample-B", state_id="state-B")
    extraction = SharedExtraction.model_validate(raw).expand(bundle)
    assert len(extraction.samples) == len(extraction.states) == 2
    assert extraction.results[0].sample_id != extraction.results[1].sample_id


def test_excluded_context_cannot_claim_a_retained_field():
    bundle, _, raw = fixture()
    raw["context_dispositions"][0].update(resolution="not_applicable", explanation="Out of scope")
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(raw, output_schema(bundle))
    with pytest.raises(ValidationError): SharedExtraction.model_validate(raw)


def test_one_shared_evidence_patch_repairs_both_referencing_results_and_replays(tmp_path):
    bundle, inventory, raw = fixture(); two_references(raw, inventory)
    raw["protocols"][0]["evidence"][0]["fields"].remove("/method")
    wire = SharedExtraction.model_validate(raw); validation = validate_extraction(wire.expand(bundle), bundle)
    targets = build_targets(wire, validation)
    assert len(targets) == 1 and targets[0]["entity_id"] == "protocol-1"
    patch = {"schema_version": "materials-evidence-patch/1", "work_id": bundle.work_id,
        "base_compact_sha256": digest(wire.model_dump()), "decisions": [
            {"target_id": targets[0]["id"], "resolution": "bound", "span_ids": ["S1"], "reason": None}]}
    candidate, proof = apply_patch(wire, EvidencePatch.model_validate(patch), targets, bundle)
    assert proof["scientific_fields_unchanged"]
    checked = validate_extraction(candidate.expand(bundle), bundle)
    assert checked["valid"] and assess_repair(wire, validation, candidate, checked)["admitted"]
    store = Store(tmp_path); bundle_hash, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=configuration(workflow="inventory_v5"))
    provider = SequenceProvider([inventory, raw, patch])
    outcome = run_one(store, job_id=job, provider_override=provider)
    assert outcome["state"] == "succeeded" and provider.calls == 3
    packet = import_packet(store, job); verify_packet(packet)
    assert len(packet["rows"]["samples"]) == 1 and len(packet["rows"]["results"]) == 2
    assert json.loads(packet["raw_output"]) == raw
    assert not packet["scientific_acceptance"] and not packet["ml_training_eligible"]
    altered = deepcopy(packet["receipt"]); altered["extraction"]["states"][0]["label"] = "Changed"
    with pytest.raises(ValueError, match="shared_extraction_reconstruction_mismatch"):
        verify_extraction(altered, bundle, packet["raw_output"])


def test_shared_context_diagnostics_map_to_entity_indices_and_propagate_to_dependents():
    bundle, inventory, raw = fixture(); two_references(raw, inventory)
    raw["protocols"][0]["evidence"][0]["fields"].remove("/method")
    wire = SharedExtraction.model_validate(raw)
    coverage = validate_coverage(wire, Inventory.model_validate(inventory), bundle)
    assert {i["path"] for i in coverage["issues"]} == {"/protocols/0/method"}
    rows = review_rows(wire.expand(bundle), {"issues": coverage["issues"]})
    assert all(r["review_status"] == "quarantined" for r in rows["results"])


def test_unpatched_shared_import_also_checks_raw_to_graph_reconstruction(tmp_path):
    bundle, inventory, raw = fixture()
    store = Store(tmp_path); bundle_hash, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=configuration(workflow="inventory_v5"))
    outcome = run_one(store, job_id=job, provider_override=SequenceProvider([inventory, raw]))
    assert outcome["state"] == "succeeded"
    packet = import_packet(store, job); verify_packet(packet)
    assert not packet["receipt"].get("evidence_patch")
    altered = deepcopy(packet["receipt"]); altered["extraction"]["results"][0]["source_role"] = "cited"
    with pytest.raises(ValueError, match="shared_extraction_reconstruction_mismatch"):
        verify_extraction(altered, bundle, packet["raw_output"])
