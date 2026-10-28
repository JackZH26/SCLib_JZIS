"""Typed relational revisions preserve source history and never grant acceptance."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sqlite3

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner.contract import canonical,digest
from ingestion.materials_ner.native_revision import configuration,run_one
from ingestion.materials_ner.proposals import import_packet,verify_packet,ProposalDatabase
from ingestion.materials_ner.providers import ProviderFailure, ProviderResult
from ingestion.materials_ner.relational_revision import (NativeEdits,VERSION,MAX_REVISION_DEPTH,
    output_schema,apply_edits,audit_revision,verify_receipt,resolve_parent)
from ingestion.materials_ner.sources import make_blocks,save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.wire_v8 import RelationalExtraction
from ingestion.materials_ner.worker import configuration as original_configuration,run_one as original_run
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_relations import fixture


def parent_attempt(tmp_path,*,missing_scope=False):
    bundle,inventory,good=fixture();bad=deepcopy(good);support=bad["condition_supports"].pop(0)
    if missing_scope:
        bundle.blocks=make_blocks(bundle.documents[0].id,[("target:synthetic:1",bundle.blocks[0].text),
            ("context:synthetic:2","Synthetic source context supplies no extra result.")])
        inventory["processed_block_ids"]=["B1","B2"]
    store=Store(tmp_path);bundle_hash,_=save_bundle(tmp_path,bundle)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=original_configuration(workflow="inventory_v8"))
    assert original_run(store,job_id=job,provider_override=SequenceProvider([inventory,bad]))["state"]=="quarantined"
    packet=import_packet(store,job);verify_packet(packet)
    parent={k:packet[k] for k in ("run_id","receipt","raw_output")}
    graph,_=resolve_parent(parent,bundle)
    response={"schema_version":VERSION,"work_id":bundle.work_id,"parent_run_id":parent["run_id"],
        "base_graph_sha256":digest(graph.model_dump()),"edits":[{"action":"add","entity":"condition_support", "value":support,
            "reason":"Retain the explicitly reported thickness measurement as support for this specimen geometry.","span_ids":["S1"]}],
        "resolved_unextracted_items":[],"document_edit":None}
    return store,bundle,parent,response


def revise(store,bundle,parent,response,provider=None):
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=parent["receipt"]["bundle_sha256"],
        config=configuration(parent,mode="relational_edits",timeout_seconds=300),max_attempts=1)
    provider=provider or SequenceProvider([response])
    outcome=run_one(store,job,parent,bundle,mode="relational_edits",provider_override=provider)
    packet=import_packet(store,job);verify_packet(packet)
    return outcome,packet,provider


def test_one_relation_edit_retains_every_existing_field_and_has_exact_source_audit(tmp_path):
    _,bundle,parent,response=parent_attempt(tmp_path)
    before,inventory=resolve_parent(parent,bundle);immutable=deepcopy(parent)
    jsonschema.validate(response,output_schema(bundle,inventory,parent))
    revision=apply_edits(parent,bundle,NativeEdits.model_validate(response))
    after=revision.revised_graph.model_dump();base=before.model_dump()
    for name in base:
        if name!="condition_supports": assert after[name]==base[name]
    assert after["condition_supports"][0]==base["condition_supports"][0]
    audit=audit_revision(parent,revision,bundle)
    assert audit["valid"] and len(audit["changes"])==1
    assert audit["changes"][0]["source_quotes"] and audit["changes"][0]["operation"]=="added"
    assert audit["reviewer_kind"]=="model" and not audit["scientific_acceptance"]
    assert parent==immutable


@pytest.mark.parametrize("mutation",["delete","parent","graph_hash","duplicate","replace_unknown","add_existing","noop","empty"])
def test_unsupported_or_ambiguous_edits_are_rejected(tmp_path,mutation):
    _,bundle,parent,response=parent_attempt(tmp_path)
    if mutation=="delete": response["edits"][0]["action"]="delete"
    if mutation=="parent": response["parent_run_id"]="0"*64
    if mutation=="graph_hash": response["base_graph_sha256"]="0"*64
    if mutation=="duplicate": response["edits"]*=2
    if mutation=="replace_unknown": response["edits"][0]["action"]="replace"
    if mutation in {"add_existing","noop"}:
        graph,_=resolve_parent(parent,bundle)
        response["edits"][0]["value"]=graph.condition_supports[0].model_dump()
        if mutation=="noop": response["edits"][0]["action"]="replace"
    if mutation=="empty": response["edits"]=[]
    with pytest.raises((ValueError,ValidationError)): apply_edits(parent,bundle,NativeEdits.model_validate(response))


def test_source_bound_document_edit_can_repair_declared_read_scope(tmp_path):
    store,bundle,parent,response=parent_attempt(tmp_path,missing_scope=True)
    base,_=resolve_parent(parent,bundle)
    response["document_edit"]={k:base.model_dump()[k] for k in ("processed_block_ids","unread_block_ids","completion","limitations")}
    response["document_edit"].update(processed_block_ids=["B1","B2"],reason="Explicitly account for the supplied context block after rereading it.",span_ids=["S2"])
    outcome,packet,provider=revise(store,bundle,parent,response)
    assert outcome["state"]=="succeeded" and provider.calls==1
    assert len(packet["receipt"]["extraction"]["processed_block_ids"])==2
    assert {c["entity"] for c in packet["receipt"]["revision_audit"]["changes"]}=={"document","condition_support"}
    assert json.loads(parent["raw_output"])["processed_block_ids"]==["B1"]


def test_worker_private_storage_restore_and_second_revision_preserve_ancestry(tmp_path):
    store,bundle,parent,response=parent_attempt(tmp_path)
    first,packet,provider=revise(store,bundle,parent,response)
    assert first["state"]=="succeeded" and provider.calls==1
    assert packet["schema"]=="materials-ner-proposals/2"
    assert len(packet["rows"]["condition_supports"])==2
    next_parent={k:packet[k] for k in ("run_id","receipt","raw_output")}
    graph,_=resolve_parent(next_parent,bundle)
    changed=deepcopy(graph.samples[0].model_dump());changed["form_raw"]=None
    # Source form ambiguity is retained in a model revision; this is not human adjudication.
    second_response=dict(response,parent_run_id=packet["run_id"],base_graph_sha256=digest(graph.model_dump()),
        edits=[{"action":"replace","entity":"sample","value":changed,"reason":"Leave the form unresolved for review.","span_ids":["S1"]}])
    second,packet2,provider2=revise(store,bundle,next_parent,second_response)
    assert provider2.calls==1 and second["state"] in {"succeeded","quarantined"}
    assert packet2["receipt"]["revision_parent"]["receipt"]["revision_parent"]==parent
    assert len(packet2["receipt"]["extraction"]["condition_supports"])==2
    db=ProposalDatabase(tmp_path/"private")
    for p in (packet,packet2):
        assert db.ingest(p)["inserted"] and not db.ingest(p)["inserted"]
        assert not p["scientific_acceptance"] and not p["ml_training_eligible"]
    with db.connect() as connection, sqlite3.connect(tmp_path/"restore.sqlite") as restored:
        connection.backup(restored)
        assert not restored.execute("PRAGMA foreign_key_check").fetchall()
        assert restored.execute("SELECT count(*) FROM condition_supports").fetchone()[0]==4
        for (payload,) in restored.execute("SELECT payload FROM runs"):verify_packet(json.loads(payload))
    # The frozen-output diagnostic reconstructs the exact selected revision.
    path=Path(__file__).parents[2]/"scripts/materials_ner_validation_replay.py"
    spec=importlib.util.spec_from_file_location("relational_replay",path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    report=module.diagnose(packet2)
    assert report["replayable"] and report["source_assertions_unchanged"]


@pytest.mark.parametrize("mutation,error",[("result","relation_revision_extraction_reconstruction_mismatch"),
    ("audit","relation_revision_audit_reconstruction_mismatch"),("parent","relation_parent_receipt_hash_mismatch"),
    ("inventory","relation_revision_parent_inventory_mismatch")])
def test_reconstruction_rejects_tampered_result_audit_parent_or_inventory(tmp_path,mutation,error):
    store,bundle,parent,response=parent_attempt(tmp_path);_,packet,_=revise(store,bundle,parent,response)
    receipt=deepcopy(packet["receipt"])
    if mutation=="result": receipt["extraction"]["results"][0]["quantity"]["value"]=999
    if mutation=="audit": receipt["revision_audit"]["changes"][0]["reason"]="hidden change"
    if mutation=="parent": receipt["revision_parent"]["receipt"]["state"]="running"
    if mutation=="inventory": receipt["inventory"]["items"]=[]
    with pytest.raises(ValueError,match=error):verify_receipt(receipt,bundle,packet["raw_output"])


def test_invalid_change_source_is_retained_as_a_quarantined_revision(tmp_path):
    store,bundle,parent,response=parent_attempt(tmp_path);response["edits"][0]["span_ids"]=["S999"]
    _,inventory=resolve_parent(parent,bundle)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(response,output_schema(bundle,inventory,parent))
    class UnconstrainedProvider:
        """Exercise local validation when a provider ignores schema constraints."""
        calls=0
        def extract(self,*args):
            self.calls+=1
            return ProviderResult(canonical(response),{"input_tokens":10,"output_tokens":2},"synthetic","gpt-6-luna","1",.01)
    outcome,packet,provider=revise(store,bundle,parent,response,UnconstrainedProvider())
    assert provider.calls==1
    assert outcome["state"]=="quarantined" and len(packet["rows"]["results"])==4
    assert packet["receipt"]["revision_audit"]["issues"]==[{"code":"relation_revision_note_source_invalid","path":"/"}]
    bad=deepcopy(packet["receipt"]);bad["validation"]["issues"]=[]
    with pytest.raises(ValueError,match="relation_revision_audit_issues_omitted"):verify_receipt(bad,bundle,packet["raw_output"])


def test_provider_failure_makes_one_call_and_never_creates_a_repaired_graph(tmp_path):
    store,bundle,parent,_=parent_attempt(tmp_path)
    class Unavailable:
        calls=0
        def extract(self,*args):
            self.calls+=1;raise ProviderFailure("provider_timeout",retryable=True)
    provider=Unavailable();job=store.enqueue(work_id=bundle.work_id,bundle_hash=parent["receipt"]["bundle_sha256"],
        config=configuration(parent,mode="relational_edits"),max_attempts=1)
    outcome=run_one(store,job,parent,bundle,mode="relational_edits",provider_override=provider)
    assert outcome["state"]=="failed" and provider.calls==1
    packet=import_packet(store,job);verify_packet(packet)
    assert packet["rows"]["results"]==[] and not packet["receipt"]["retryable"]
    assert packet["receipt"]["revision_parent"]==parent
    assert run_one(store,job,parent,bundle,mode="relational_edits",provider_override=provider) is None
    assert provider.calls==1


def test_ancestry_limit_is_explicit_and_cannot_turn_a_deep_parent_into_a_new_source(tmp_path):
    _,bundle,parent,_=parent_attempt(tmp_path)
    with pytest.raises(ValueError,match="relation_revision_ancestry_limit"):resolve_parent(parent,bundle,depth=MAX_REVISION_DEPTH+1)
