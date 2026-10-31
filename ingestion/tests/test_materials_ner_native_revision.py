"""Source revision retains originals, binds edits and never grants acceptance."""
from copy import deepcopy
import json

import jsonschema
import pytest

from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.native_revision import (NativeRevision, VERSION, output_schema,
    audit_revision, graph_diagnostics, verify_receipt, configuration, run_one)
from ingestion.materials_ner.proposals import ProposalDatabase, import_packet, verify_packet
from ingestion.materials_ner.providers import ProviderFailure
from ingestion.materials_ner.sources import save_bundle, sha
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import configuration as original_config, run_one as original_run
from test_materials_ner_native import fixture
from test_materials_ner_inventory_v2 import SequenceProvider


def example():
    bundle, inventory, good = fixture()
    bad = deepcopy(good); absent = bad["observations"].pop()
    item_id = absent["inventory_item_ids"][0]
    bad["unextracted_items"] = [{"item_id": item_id, "reason": "not_a_result", "explanation": "Mistakenly excluded."}]
    bad["context_dispositions"][0]["bindings"].append({"entity": "result", "entity_id": absent["id"], "field": "/quantity"})
    good["context_dispositions"] = deepcopy(bad["context_dispositions"])
    response = {"schema_version": VERSION, "work_id": bundle.work_id,
        "base_raw_output_sha256": sha(canonical(bad).encode()), "revised_graph": good,
        "notes": [{"entity": "result", "entity_id": absent["id"], "reason": "The source explicitly gives this separate zero-resistance result.", "span_ids": ["S1"]},
                  {"entity": "unextracted_item", "entity_id": item_id, "reason": "The excluded result is now explicitly retained.", "span_ids": ["S1"]}]}
    return bundle, inventory, bad, response


def parent_attempt(tmp_path):
    bundle, inventory, bad, response = example()
    store = Store(tmp_path); bundle_hash,_ = save_bundle(tmp_path,bundle)
    job = store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=original_config(workflow="inventory_v7"))
    result = original_run(store,job_id=job,provider_override=SequenceProvider([inventory,bad]))
    assert result["state"] == "quarantined" and result["error_code"] == "output_schema_invalid"
    packet=import_packet(store,job);verify_packet(packet)
    parent={k:packet[k] for k in ("run_id","receipt","raw_output")}
    return store,bundle,parent,response


def test_missing_result_is_added_with_exact_change_and_source_accounting():
    bundle,inventory,bad,response=example()
    from ingestion.materials_ner.inventory import Inventory
    jsonschema.validate(response,output_schema(bundle,Inventory.model_validate(inventory)))
    assert graph_diagnostics(bad)[0]["code"] == "context_target_missing"
    proof=audit_revision(canonical(bad),NativeRevision.model_validate(response),bundle)
    assert proof["valid"] and len(proof["changes"])==2
    assert {c["operation"] for c in proof["changes"]}=={"added","removed"}
    assert all(c["source_quotes"] for c in proof["changes"])
    assert not proof["independent_review"] and not proof["scientific_acceptance"]


@pytest.mark.parametrize("mutation,code",[("missing_note","revision_note_coverage_mismatch"),
    ("extra_note","revision_note_coverage_mismatch"),("duplicate_note","revision_duplicate_note"),
    ("unknown_span","revision_note_source_invalid")])
def test_unaccounted_or_unlocated_changes_remain_quarantined(mutation,code):
    bundle,_,bad,response=example()
    if mutation=="missing_note":response["notes"].pop()
    if mutation=="extra_note":response["notes"].append(dict(response["notes"][0],entity="sample",entity_id="unused"))
    if mutation=="duplicate_note":response["notes"].append(response["notes"][0])
    if mutation=="unknown_span":response["notes"][0]["span_ids"]=["S999"]
    report=audit_revision(canonical(bad),NativeRevision.model_validate(response),bundle)
    assert not report["valid"] and code in {i["code"] for i in report["issues"]}


def test_removing_an_existing_result_does_not_make_a_revision_admissible():
    bundle,_,bad,response=example()
    removed=response["revised_graph"]["observations"].pop(0)
    response["notes"].append({"entity":"result","entity_id":removed["id"],"reason":"Attempted deletion to hide a failure.","span_ids":["S1"]})
    proof=audit_revision(canonical(bad),NativeRevision.model_validate(response),bundle)
    assert "revision_declaration_removed" in {i["code"] for i in proof["issues"]}


def test_revision_attempt_import_and_restore_keep_parent_and_original_graph(tmp_path):
    store,bundle,parent,response=parent_attempt(tmp_path)
    before=deepcopy(parent);config=configuration(parent,timeout_seconds=300)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=parent["receipt"]["bundle_sha256"],config=config,max_attempts=1)
    provider=SequenceProvider([response]);outcome=run_one(store,job,parent,bundle,provider_override=provider)
    assert provider.calls==1 and outcome["state"]=="succeeded"
    assert parent==before
    packet=import_packet(store,job);verify_packet(packet)
    assert len(packet["rows"]["results"])==2 and packet["receipt"]["revision_parent"]==before
    database=ProposalDatabase(tmp_path/"proposals")
    assert database.ingest(packet)["inserted"] and not database.ingest(packet)["inserted"]
    assert not packet["scientific_acceptance"] and not packet["ml_training_eligible"]
    changed=deepcopy(packet["receipt"]);changed["extraction"]["results"][0]["quantity"]["value"]=999
    with pytest.raises(ValueError,match="revision_extraction_reconstruction_mismatch"):
        verify_receipt(changed,bundle,packet["raw_output"])
    changed=deepcopy(packet["receipt"]);changed["revision_audit"]["changes"][0]["reason"]="Hidden edit."
    with pytest.raises(ValueError,match="revision_audit_reconstruction_mismatch"):
        verify_receipt(changed,bundle,packet["raw_output"])
    changed=deepcopy(packet["receipt"]);changed["revision_parent"]["raw_output"]="{}"
    with pytest.raises(ValueError,match="revision_parent_receipt_hash_mismatch"):
        verify_receipt(changed,bundle,packet["raw_output"])


def test_valid_graph_without_edit_accounting_stays_review_only(tmp_path):
    store,bundle,parent,response=parent_attempt(tmp_path);response["notes"]=[]
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=parent["receipt"]["bundle_sha256"],config=configuration(parent),max_attempts=1)
    outcome=run_one(store,job,parent,bundle,provider_override=SequenceProvider([response]))
    assert outcome["state"]=="quarantined"
    packet=import_packet(store,job);verify_packet(packet)
    assert len(packet["rows"]["results"])==2
    assert all(r["review_status"]=="quarantined" for r in packet["rows"]["results"])
    changed=deepcopy(packet["receipt"]);changed["validation"]["issues"]=[]
    with pytest.raises(ValueError,match="revision_audit_issues_omitted"):
        verify_receipt(changed,bundle,packet["raw_output"])


def test_provider_failure_retains_parent_without_relaunch_or_synthetic_result(tmp_path):
    store,bundle,parent,_=parent_attempt(tmp_path)
    class Unavailable:
        calls=0
        def extract(self,*args):
            self.calls+=1
            raise ProviderFailure("provider_timeout",retryable=True)
    provider=Unavailable()
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=parent["receipt"]["bundle_sha256"],config=configuration(parent),max_attempts=1)
    outcome=run_one(store,job,parent,bundle,provider_override=provider)
    assert outcome["state"]=="failed" and provider.calls==1
    packet=import_packet(store,job);verify_packet(packet)
    assert packet["receipt"]["revision_parent"]==parent and packet["rows"]["results"]==[]
    assert not packet["receipt"]["retryable"]
    assert run_one(store,job,parent,bundle,provider_override=provider) is None
    assert provider.calls==1


def test_duplicate_parent_entity_ids_cannot_be_silently_collapsed():
    bundle,_,bad,response=example()
    bad["samples"].append(deepcopy(bad["samples"][0]))
    response["base_raw_output_sha256"]=sha(canonical(bad).encode())
    with pytest.raises(ValueError,match="revision_parent_duplicate_identifier"):
        audit_revision(canonical(bad),NativeRevision.model_validate(response),bundle)
