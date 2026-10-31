"""The concrete failed graph is repaired without rewriting untouched entities."""
from copy import deepcopy

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.native_revision import audit_revision, configuration, run_one
from ingestion.materials_ner.native_revision_edits import VERSION, NativeEdits, output_schema, apply_edits, verify_receipt
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from test_materials_ner_native_revision import example, parent_attempt
from test_materials_ner_inventory_v2 import SequenceProvider


def edit_response(revision):
    missing = revision["revised_graph"]["observations"][-1]
    return {"schema_version": VERSION, "work_id": revision["work_id"],
        "base_raw_output_sha256": revision["base_raw_output_sha256"],
        "edits": [{"action": "add", "entity": "result", "value": missing,
                   "reason": revision["notes"][0]["reason"], "span_ids": ["S1"]}],
        "resolved_unextracted_items": [{"item_id": missing["inventory_item_ids"][0],
            "observation_ids": [missing["id"]], "reason": revision["notes"][1]["reason"], "span_ids": ["S1"]}]}


def test_single_add_keeps_all_existing_owners_results_and_context():
    bundle, inventory, bad, response=example(); edits=edit_response(response)
    jsonschema.validate(edits, output_schema(bundle, Inventory.model_validate(inventory), {"raw_output": canonical(bad)}))
    revision=apply_edits(canonical(bad), NativeEdits.model_validate(edits))
    after=revision.revised_graph.model_dump()
    for key in ("samples", "states", "protocols", "context_dispositions", "completion", "limitations"):
        assert after[key] == bad[key]
    assert after["observations"][0] == bad["observations"][0]
    assert len(after["observations"]) == len(bad["observations"])+1
    assert audit_revision(canonical(bad),revision,bundle)["valid"]


@pytest.mark.parametrize("mutation,error", [("delete","validation"), ("wrong_hash","edit_parent_or_work_mismatch"),
    ("overwrite_add","edit_add_target_already_exists"), ("unknown_replace","edit_replace_target_missing_or_ambiguous"),
    ("unbacked_resolution","resolved_exclusion_has_no_explicit_result"), ("duplicate_edit","duplicate_entity_edit")])
def test_model_cannot_drop_declarations_or_resolve_an_exclusion_without_a_result(mutation,error):
    _,_,bad,response=example(); edits=edit_response(response)
    if mutation=="delete": edits["edits"][0]["action"]="delete"
    if mutation=="wrong_hash": edits["base_raw_output_sha256"]="0"*64
    if mutation=="overwrite_add": edits["edits"][0]["value"]=bad["observations"][0]
    if mutation=="unknown_replace": edits["edits"][0]["action"]="replace"
    if mutation=="unbacked_resolution": edits["resolved_unextracted_items"][0]["observation_ids"]=["absent"]
    if mutation=="duplicate_edit": edits["edits"]*=2
    with pytest.raises((ValueError,ValidationError), match=None if error=="validation" else error):
        apply_edits(canonical(bad),NativeEdits.model_validate(edits))


def test_typed_edit_worker_preserves_parent_and_can_be_replayed_and_tamper_checked(tmp_path):
    store,bundle,parent,response=parent_attempt(tmp_path);edits=edit_response(response)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=parent["receipt"]["bundle_sha256"],
        config=configuration(parent,mode="edits"),max_attempts=1)
    provider=SequenceProvider([edits])
    outcome=run_one(store,job,parent,bundle,mode="edits",provider_override=provider)
    assert outcome["state"]=="succeeded" and provider.calls==1
    packet=import_packet(store,job);verify_packet(packet)
    assert packet["receipt"]["revision_parent"]==parent and len(packet["rows"]["results"])==2
    db=ProposalDatabase(tmp_path/"db")
    assert db.ingest(packet)["inserted"] and not db.ingest(packet)["inserted"]
    bad=deepcopy(packet["receipt"]);bad["extraction"]["results"][0]["quantity"]["value"]=999
    with pytest.raises(ValueError,match="revision_extraction_reconstruction_mismatch"):
        verify_receipt(bad,bundle,packet["raw_output"])
    assert not packet["scientific_acceptance"] and not packet["ml_training_eligible"]
