"""Issue accounting is source-pinned and never substitutes for scientific review."""
from copy import deepcopy
import json
import sqlite3

import pytest

from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.native_revision import configuration, run_one
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.providers import ProviderFailure
from ingestion.materials_ner.relational_revision import resolve_parent
from ingestion.materials_ner.relational_review import (VERSION, NativeEdits, validate_request,
    apply_edits, audit_revision, verify_receipt)
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_relational_revision import parent_attempt


def fixture(tmp_path):
    store, bundle, parent, response = parent_attempt(tmp_path)
    support = response["edits"][0]["value"]
    target = {"entity":"result", "entity_id":support["result_id"]}
    request = {"schema_version":"materials-source-review-request/1", "work_id":bundle.work_id,
        "parent_run_id":parent["run_id"], "bundle_sha256":parent["receipt"]["bundle_sha256"],
        "author_kind":"assistant", "issues":[{"id":"geometry-support",
            "concern":"Check the source-reported relationship between the result and its specimen geometry.",
            "targets":[target], "span_ids":["S1"]}]}
    response.update(schema_version=VERSION, request_sha256=digest(request), dispositions=[{
        "issue_id":"geometry-support", "status":"revised", "reason":"Retain the reported relationship with its source.",
        "span_ids":["S1"], "entities":[target,{"entity":"condition_support","entity_id":support["id"]}]}])
    return store,bundle,parent,request,response


def execute(store,bundle,parent,request,response,provider=None):
    config=configuration(parent,mode="relational_review",review_request=request)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=parent["receipt"]["bundle_sha256"],config=config,max_attempts=1)
    provider=provider or SequenceProvider([response])
    outcome=run_one(store,job,parent,bundle,mode="relational_review",provider_override=provider)
    packet=import_packet(store,job);verify_packet(packet)
    return outcome,packet,provider


def test_one_source_review_call_retains_parent_and_exact_issue_disposition(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path);original=deepcopy(parent)
    outcome,packet,provider=execute(store,bundle,parent,request,response)
    assert outcome["state"]=="succeeded" and provider.calls==1
    assert parent==original and packet["schema"]=="materials-ner-proposals/2"
    receipt=packet["receipt"];proof=receipt["revision_audit"]
    assert receipt["review_request"]==request and proof["request_sha256"]==digest(request)
    assert proof["valid"] and len(proof["dispositions"])==1
    assert proof["dispositions"][0]["source_quotes"] and proof["dispositions"][0]["changed_entities"]
    assert proof["issue_dispositions_are_model_claims"] and not proof["repair_correctness_independently_verified"]
    assert not packet["scientific_acceptance"] and not packet["ml_training_eligible"]
    attempt=store.root/"attempts"/packet["job_id"]/receipt["attempt_id"]
    assert json.loads((attempt/"review-request.json").read_text())==request
    assert "SOURCE_REVIEW_REQUEST" in (attempt/"input.txt").read_text()


@pytest.mark.parametrize("mutation,code",[
    ("missing","source_review_disposition_coverage_invalid"),
    ("duplicate","source_review_disposition_coverage_invalid"),
    ("unknown_issue","source_review_disposition_coverage_invalid"),
    ("wrong_anchor","source_review_disposition_lost_request_target"),
    ("missing_entity","source_review_disposition_target_invalid"),
    ("uncovered_edit","source_review_unaccounted_edit"),
    ("bad_source","source_review_disposition_source_invalid"),
    ("false_revised","source_review_revised_without_change"),
    ("false_unchanged","source_review_unchanged_with_edits"),
])
def test_issue_accounting_is_checked_locally_after_provider_output(tmp_path,mutation,code):
    _,bundle,parent,request,response=fixture(tmp_path)
    if mutation=="missing": response["dispositions"][0]["issue_id"]="another-issue"
    if mutation=="duplicate": response["dispositions"]*=2
    if mutation=="unknown_issue": response["dispositions"][0]["issue_id"]="invented"
    if mutation=="wrong_anchor": response["dispositions"][0]["entities"]=response["dispositions"][0]["entities"][1:]
    if mutation=="missing_entity": response["dispositions"][0]["entities"].append({"entity":"result","entity_id":"absent"})
    if mutation=="uncovered_edit": response["dispositions"][0]["entities"]=response["dispositions"][0]["entities"][:1]
    if mutation=="bad_source": response["dispositions"][0]["span_ids"]=["S999"]
    if mutation=="false_revised": response["edits"]=[];response["dispositions"][0]["entities"]=response["dispositions"][0]["entities"][:1]
    if mutation=="false_unchanged": response["dispositions"][0]["status"]="unchanged_supported"
    revision=apply_edits(parent,bundle,NativeEdits.model_validate(response),review_request=request)
    proof=audit_revision(parent,revision,bundle)
    assert not proof["valid"] and code in {i["code"] for i in proof["issues"]}


@pytest.mark.parametrize("mutation",["parent","work","bundle","target","span","duplicate_issue"])
def test_request_cannot_be_borrowed_from_another_parent_or_source(tmp_path,mutation):
    _,bundle,parent,request,_=fixture(tmp_path)
    if mutation=="parent":request["parent_run_id"]="0"*64
    if mutation=="work":request["work_id"]="arxiv:other"
    if mutation=="bundle":request["bundle_sha256"]="0"*64
    if mutation=="target":request["issues"][0]["targets"][0]["entity_id"]="missing"
    if mutation=="span":request["issues"][0]["span_ids"]=["S999"]
    if mutation=="duplicate_issue":request["issues"]*=2
    with pytest.raises(ValueError):validate_request(request,parent,bundle)


def test_unresolved_review_preserves_exact_graph_without_manufacturing_an_edit(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    response["edits"]=[];response["dispositions"][0].update(status="unresolved",
        reason="The source relation still needs independent inspection.",entities=request["issues"][0]["targets"])
    outcome,packet,provider=execute(store,bundle,parent,request,response)
    assert outcome["state"]=="quarantined" and provider.calls==1
    assert packet["receipt"]["extraction"]==parent["receipt"]["extraction"]
    assert "source_review_issue_unresolved" in {i["code"] for i in packet["receipt"]["validation"]["issues"]}


@pytest.mark.parametrize("mutation",["request","request_hash","disposition","extraction"])
def test_receipt_replay_rejects_changed_request_disposition_or_scientific_values(tmp_path,mutation):
    store,bundle,parent,request,response=fixture(tmp_path)
    _,packet,_=execute(store,bundle,parent,request,response);receipt=deepcopy(packet["receipt"])
    if mutation=="request":receipt["review_request"]["issues"][0]["concern"]="Another request"
    if mutation=="request_hash":receipt["config"]["review_request_sha256"]="0"*64
    if mutation=="disposition":receipt["revision_audit"]["dispositions"][0]["reason"]="Changed interpretation"
    if mutation=="extraction":receipt["extraction"]["results"][0]["quantity"]["value"]=999
    with pytest.raises(ValueError):verify_receipt(receipt,bundle,packet["raw_output"])


def test_chained_review_reconstructs_and_private_backup_restores_both_attempts(tmp_path,monkeypatch):
    store,bundle,parent,request,response=fixture(tmp_path)
    _,first,_=execute(store,bundle,parent,request,response)
    next_parent={k:first[k] for k in ("run_id","receipt","raw_output")}
    graph,_=resolve_parent(next_parent,bundle)
    next_request=deepcopy(request);next_request["parent_run_id"]=first["run_id"]
    second=deepcopy(response);second.update(parent_run_id=first["run_id"],base_graph_sha256=digest(graph.model_dump()),
        request_sha256=digest(next_request),edits=[])
    second["dispositions"][0].update(status="unchanged_supported",entities=next_request["issues"][0]["targets"])
    outcome,second_packet,provider=execute(store,bundle,next_parent,next_request,second)
    assert outcome["state"]=="succeeded" and provider.calls==1
    assert second_packet["receipt"]["extraction"]==first["receipt"]["extraction"]
    from ingestion.materials_ner import relational_revision as base
    original=base.resolve_parent;walked=[]
    def counted(parent,*args,**kwargs):
        walked.append(parent["run_id"])
        return original(parent,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(base,"resolve_parent",counted)
        verify_receipt(second_packet["receipt"],bundle,second_packet["raw_output"])
    assert walked==[first["run_id"],parent["run_id"]]
    db=ProposalDatabase(tmp_path/"private")
    for packet in (first,second_packet):assert db.ingest(packet)["inserted"] and not db.ingest(packet)["inserted"]
    with db.connect() as con,sqlite3.connect(tmp_path/"restored.sqlite3") as restored:
        con.backup(restored);assert not restored.execute("PRAGMA foreign_key_check").fetchall()
        for (payload,) in restored.execute("SELECT payload FROM runs"):verify_packet(json.loads(payload))


def test_provider_failure_is_terminal_without_a_second_call_or_invented_review(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    class Unavailable:
        calls=0
        def extract(self,*args):
            self.calls+=1;raise ProviderFailure("provider_timeout",retryable=True)
    outcome,packet,provider=execute(store,bundle,parent,request,response,Unavailable())
    assert outcome["state"]=="failed" and provider.calls==1 and not packet["receipt"]["retryable"]
    assert packet["rows"]["results"]==[] and "revision_audit" not in packet["receipt"]


@pytest.mark.parametrize("continuation",["drop","rewrite","legacy","resolve"])
def test_unresolved_issue_survives_later_requests_until_explicitly_addressed(tmp_path,continuation):
    store,bundle,parent,request,response=fixture(tmp_path)
    unresolved=deepcopy(response);unresolved["edits"]=[]
    unresolved["dispositions"][0].update(status="unresolved",entities=request["issues"][0]["targets"])
    _,first,_=execute(store,bundle,parent,request,unresolved)
    next_parent={k:first[k] for k in ("run_id","receipt","raw_output")}
    next_request=deepcopy(request);next_request["parent_run_id"]=first["run_id"]
    if continuation=="legacy":
        with pytest.raises(ValueError,match="accounted_revision"):
            configuration(next_parent,mode="relational_edits")
        return
    if continuation=="drop":next_request["issues"][0]["id"]="new-topic"
    if continuation=="rewrite":next_request["issues"][0]["concern"]="An easier replacement problem"
    if continuation in {"drop","rewrite"}:
        with pytest.raises(ValueError,match="drops_or_rewrites_unresolved"):
            validate_request(next_request,next_parent,bundle)
        return
    graph,_=resolve_parent(next_parent,bundle)
    response.update(parent_run_id=first["run_id"],base_graph_sha256=digest(graph.model_dump()),request_sha256=digest(next_request))
    outcome,packet,provider=execute(store,bundle,next_parent,next_request,response)
    assert outcome["state"]=="succeeded" and provider.calls==1
    assert packet["receipt"]["revision_audit"]["dispositions"][0]["status"]=="revised"
    assert not packet["receipt"]["revision_audit"]["repair_correctness_independently_verified"]
