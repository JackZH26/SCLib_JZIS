"""Redundant indexing may be derived; scientific source assertions may not."""
from copy import deepcopy
import json

import pytest

from ingestion.materials_ner.inventory import Inventory, validate_inventory
from ingestion.materials_ner.inventory_links import assertions, project_links, verify_inventory_projection
from ingestion.materials_ner.proposals import import_packet, verify_packet
from ingestion.materials_ner.sources import make_blocks, save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_inventory_v4 import fixture


def paired_inventory():
    bundle, raw, _ = fixture()
    bundle.blocks = make_blocks(bundle.documents[0].id, [
        ("target:synthetic:1", "SYNTHETIC Sample A has Tc 3.2 K."),
        ("target:synthetic:2", "SYNTHETIC Sample B has Tc 5.4 K.")])
    raw.update(processed_block_ids=["B1", "B2"], context_assertions=[])
    raw["items"] = [
        {"id": "I1", "sample_raw": "Sample A", "quantity_name_raw": "Tc",
         "value_raw": "3.2 K", "source_span_ids": ["S1"], "context_span_ids": []},
        {"id": "I2", "sample_raw": "Sample B", "quantity_name_raw": "Tc",
         "value_raw": "5.4 K", "source_span_ids": ["S2"], "context_span_ids": []}]
    raw["span_dispositions"] = [
        {"span_id": "S1", "role": "result_assertions", "item_ids": ["I2"], "reason": None},
        {"span_id": "S2", "role": "result_assertions", "item_ids": ["I1"], "reason": None}]
    return bundle, raw


def test_reverse_index_is_derived_without_moving_values_subjects_or_source_links():
    bundle, raw = paired_inventory()
    source = Inventory.model_validate(raw)
    projected, proof = project_links(source, bundle)
    assert proof["action"] == "projected" and len(proof["edits"]) == 2
    assert assertions(source) == assertions(projected)
    assert source.model_dump() == raw  # Caller-owned original is immutable.
    assert [d.item_ids for d in projected.span_dispositions] == [["I1"], ["I2"]]
    assert validate_inventory(projected, bundle)["valid"]
    again, second = project_links(projected, bundle)
    assert again == projected and second["action"] == "unchanged"


@pytest.mark.parametrize("mutation", ["missing_value", "unknown_source", "context",
                                      "unread", "duplicate_item", "missing_span"])
def test_projection_refuses_primary_source_or_coverage_errors(mutation):
    bundle, raw = paired_inventory()
    if mutation == "missing_value": raw["items"][0]["value_raw"] = "9.9 K"
    if mutation == "unknown_source": raw["items"][0]["source_span_ids"] = ["S999"]
    if mutation == "context":
        raw["span_dispositions"][0].update(role="context_only", item_ids=[], reason="Claimed context")
    if mutation == "unread": raw["span_dispositions"][0]["role"] = "unread"
    if mutation == "duplicate_item": raw["items"][1]["id"] = "I1"
    if mutation == "missing_span": raw["span_dispositions"].pop()
    source = Inventory.model_validate(raw)
    selected, proof = project_links(source, bundle)
    assert selected == source and proof["action"] == "rejected" and proof["blockers"]
    assert proof["edits"] == [] and not proof["scientific_acceptance"]


def test_projection_never_treats_a_fallible_subject_label_as_scientifically_verified():
    bundle, raw = paired_inventory()
    raw["items"][0]["sample_raw"] = "Incorrect subject requiring source review"
    source = Inventory.model_validate(raw)
    selected, proof = project_links(source, bundle)
    assert selected.items[0].sample_raw == source.items[0].sample_raw
    assert assertions(selected) == assertions(source) and not proof["scientific_acceptance"]


def test_v4_worker_projects_reverse_lists_and_import_replays_the_original_response(tmp_path):
    bundle, inventory, raw = fixture()
    inventory["span_dispositions"][0]["item_ids"] = ["MistypedReverseID"]
    store = Store(tmp_path)
    bundle_hash, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash,
                        config=configuration(workflow="inventory_v4"))
    provider = SequenceProvider([inventory, raw])
    outcome = run_one(store, job_id=job, provider_override=provider)
    assert outcome["state"] == "succeeded" and provider.calls == 2
    packet = import_packet(store, job)
    verify_packet(packet)
    read = packet["receipt"]["inventory_reads"][0]
    assert json.loads(read["raw_output"]) == inventory
    assert read["link_projection"]["action"] == "projected"
    assert not packet["scientific_acceptance"] and not packet["ml_training_eligible"]
    for mutation, code in (("raw", "raw_hash"), ("proof", "proof"), ("selected", "selection")):
        altered = deepcopy(packet["receipt"])
        if mutation == "raw": altered["inventory_reads"][0]["raw_output"] += " "
        if mutation == "proof": altered["inventory_reads"][0]["link_projection"]["edits"] = []
        if mutation == "selected": altered["inventory"]["items"][0]["sample_raw"] = "Changed subject"
        with pytest.raises(ValueError, match="inventory_projection_" + code):
            verify_inventory_projection(altered, bundle)
