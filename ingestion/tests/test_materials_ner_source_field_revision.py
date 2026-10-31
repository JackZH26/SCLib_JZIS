"""Source copying cannot rewrite numeric semantics or launder scientific review."""
from copy import deepcopy
import json
import sqlite3

import jsonschema
import pytest

from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.native_revision import configuration, run_one
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.providers import ProviderFailure
from ingestion.materials_ner.relational_revision import resolve_parent
from ingestion.materials_ner.relational_review import pending_review_issues
from ingestion.materials_ner.source_field_revision import (VERSION, NativeEdits, Selection,
    validate_request, output_schema, apply_edits, audit_revision, verify_receipt, _select)
from ingestion.materials_ner.sources import save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import configuration as worker_configuration, run_one as worker_run
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_relations import fixture as source_fixture


def fixture(tmp_path, *, unknown_method=False, nested_raw=False):
    bundle, inventory, raw = source_fixture()
    raw["samples"][0]["form_raw"] = "invented bulky form"
    if nested_raw:
        raw["observations"][0]["result"]["quantity_name_raw"] = "paraphrased transition"
        raw["observations"][0]["definition"]["criterion_raw"] = "paraphrased onset"
    if unknown_method:
        raw["protocols"][0]["method"] = None
        raw["protocols"][0]["method_class"] = "unspecified"
    store = Store(tmp_path); bundle_hash, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=worker_configuration(workflow="inventory_v8"))
    worker_run(store, job_id=job, provider_override=SequenceProvider([inventory, raw]))
    packet = import_packet(store, job); verify_packet(packet)
    parent = {k: packet[k] for k in ("run_id", "receipt", "raw_output")}
    graph, _ = resolve_parent(parent, bundle)
    request = {"schema_version": "materials-source-field-request/1", "work_id": bundle.work_id,
        "parent_run_id": parent["run_id"], "bundle_sha256": bundle_hash, "author_kind": "assistant",
        "issues": [{"id": "source-fidelity", "concern": "Read the declared sample form and retain uncertain method ownership.",
                    "targets": [{"entity": "sample", "entity_id": graph.samples[0].id},
                                {"entity": "procedure", "entity_id": graph.protocols[0].id}], "span_ids": ["S1"]}],
        "fields": [{"id": "F1", "issue_id": "source-fidelity", "entity": "sample", "entity_id": graph.samples[0].id,
                    "field": "/form_raw", "expected_value_sha256": digest("invented bulky form"),
                    "kind": "raw_literal", "allow_absent": False}]}
    response = {"schema_version": VERSION, "work_id": bundle.work_id, "parent_run_id": parent["run_id"],
        "base_graph_sha256": digest(graph.model_dump()), "request_sha256": digest(request),
        "selections": [{"target_id": "F1", "action": "copy", "span_ids": ["S1"], "exact_text": "bulk",
                        "occurrence": None, "reason": "Copy the reported sample form."}]}
    return store, bundle, parent, request, response


def execute(store, bundle, parent, request, response, provider=None):
    config = configuration(parent, mode="source_fields", review_request=request)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=parent["receipt"]["bundle_sha256"], config=config, max_attempts=1)
    provider = provider or SequenceProvider([response])
    result = run_one(store, job, parent, bundle, mode="source_fields", provider_override=provider)
    packet = import_packet(store, job); verify_packet(packet)
    return result, packet, provider


def test_source_slice_only_changes_declared_raw_field_and_its_binding(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path)
    before = deepcopy(parent); graph, inventory = resolve_parent(parent, bundle)
    jsonschema.validate(response, output_schema(bundle, inventory, parent, review_request=request))
    outcome, packet, provider = execute(store, bundle, parent, request, response)
    assert outcome["state"] == "quarantined" and provider.calls == 1
    assert parent == before and packet["schema"] == "materials-ner-proposals/2"
    revised, _ = resolve_parent({k:packet[k] for k in ("run_id", "receipt", "raw_output")}, bundle)
    after = revised.model_dump(); original = graph.model_dump()
    assert after["samples"][0]["form_raw"] == "bulk"
    after["samples"][0]["form_raw"] = original["samples"][0]["form_raw"]
    after["samples"][0]["evidence"] = original["samples"][0]["evidence"]
    assert after == original
    receipt = packet["receipt"]; selected = receipt["revision_audit"]["field_changes"][0]["selected_source"]
    assert bundle.blocks[0].text[selected["start_char"]:selected["end_char"]] == "bulk"
    assert receipt["revision_audit"]["pending_review_issues"] == request["issues"]
    assert not packet["scientific_acceptance"] and not packet["ml_training_eligible"]
    assert not receipt["revision_audit"]["repair_correctness_independently_verified"]
    db = ProposalDatabase(tmp_path / "private")
    assert db.ingest(packet)["inserted"] and not db.ingest(packet)["inserted"]
    with db.connect() as connection, sqlite3.connect(tmp_path / "restored.sqlite3") as restored:
        connection.backup(restored)
        assert not restored.execute("PRAGMA foreign_key_check").fetchall()
        for row in restored.execute("SELECT payload FROM runs"): verify_packet(json.loads(row[0]))


@pytest.mark.parametrize("mutation", ["number", "owner", "criterion", "evidence", "stale", "duplicate", "missing_issue", "mandatory_absence"])
def test_request_cannot_enable_undeclared_scientific_or_arbitrary_edits(tmp_path, mutation):
    _, bundle, parent, request, _ = fixture(tmp_path)
    target = request["fields"][0]
    if mutation in {"number", "owner", "criterion"}:
        graph, _ = resolve_parent(parent, bundle); result = graph.observations[0]
        target.update(entity="result", entity_id=result.id)
        request["issues"][0]["targets"].append({"entity":"result", "entity_id":result.id})
        pointer, value = {"number": ("/result/quantity/value", result.result.quantity.value),
                          "owner": ("/sample_id", result.sample_id), "criterion": ("/definition/criterion", result.definition.criterion)}[mutation]
        target.update(field=pointer, expected_value_sha256=digest(value))
    if mutation == "evidence": target["field"] = "/evidence/0/fields/0"
    if mutation == "stale": target["expected_value_sha256"] = "0" * 64
    if mutation == "duplicate": request["fields"] *= 2
    if mutation == "missing_issue": target["issue_id"] = "unrequested"
    if mutation == "mandatory_absence": target.update(field="/formula_raw", expected_value_sha256=digest("MgB2"), allow_absent=True)
    with pytest.raises(ValueError): validate_request(request, parent, bundle)


@pytest.mark.parametrize("mutation", ["wrong_source", "paraphrase", "case", "missing", "extra", "parent", "hash", "graph", "absent", "text_on_unresolved"])
def test_provider_output_cannot_invent_source_or_skip_field_preconditions(tmp_path, mutation):
    _, bundle, parent, request, response = fixture(tmp_path)
    selection = response["selections"][0]
    if mutation == "wrong_source": selection["span_ids"] = ["S999"]
    if mutation == "paraphrase": selection["exact_text"] = "bulk specimen"
    if mutation == "case": selection["exact_text"] = "BULK"
    if mutation == "missing": response["selections"] = []
    if mutation == "extra": response["selections"].append(dict(selection, target_id="unrequested"))
    if mutation == "parent": response["parent_run_id"] = "0" * 64
    if mutation == "hash": response["request_sha256"] = "0" * 64
    if mutation == "graph": response["base_graph_sha256"] = "0" * 64
    if mutation == "absent": selection.update(action="absent", exact_text=None)
    if mutation == "text_on_unresolved": selection["action"] = "unresolved"
    with pytest.raises(ValueError): apply_edits(parent, bundle, NativeEdits.model_validate(response), review_request=request)


def test_source_copy_preserves_original_whitespace_and_requires_repeated_occurrence():
    catalog = {"spans": {"S1": {"block_id":"B1", "text":"alpha\n beta; alpha beta", "start_char":10, "end_char":32}}}
    selection = Selection(target_id="F", action="copy", span_ids=["S1"], exact_text="alpha beta", occurrence=None, reason="Read source.")
    with pytest.raises(ValueError, match="occurrence_required"): _select(selection, catalog)
    selected, _ = _select(selection.model_copy(update={"occurrence":0}), catalog)
    assert selected["text"] == "alpha\n beta" and selected["start_char"] == 10
    with pytest.raises(ValueError, match="out_of_range"): _select(selection.model_copy(update={"occurrence":2}), catalog)


def test_optional_absence_and_null_binding_do_not_change_other_assertions(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path, unknown_method=True)
    graph, _ = resolve_parent(parent, bundle)
    request["fields"][0]["allow_absent"] = True
    request["fields"].append({"id":"F2", "issue_id":"source-fidelity", "entity":"procedure",
        "entity_id":graph.protocols[0].id, "field":"/method", "expected_value_sha256":digest(None), "kind":"null_evidence", "allow_absent":False})
    response["request_sha256"] = digest(request)
    response["selections"][0].update(action="absent", exact_text=None)
    response["selections"].append(dict(response["selections"][0], target_id="F2", action="drop_null_binding"))
    _, packet, _ = execute(store, bundle, parent, request, response)
    extraction = packet["receipt"]["extraction"]
    assert extraction["samples"][0]["form_raw"] is None
    assert extraction["protocols"][0]["method"] is None
    assert all(e["field"] != "/method" for e in extraction["protocols"][0]["evidence"])
    assert extraction["results"] == parent["receipt"]["extraction"]["results"]


def test_unresolved_selections_preserve_graph_and_cannot_hide_pending_issues(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path)
    response["selections"][0].update(action="unresolved", exact_text=None)
    _, packet, _ = execute(store, bundle, parent, request, response)
    assert packet["receipt"]["extraction"] == parent["receipt"]["extraction"]
    next_parent = {k:packet[k] for k in ("run_id","receipt","raw_output")}
    assert pending_review_issues(next_parent) == request["issues"]
    with pytest.raises(ValueError, match="accounted_revision"): configuration(next_parent, mode="relational_edits")
    next_request = deepcopy(request); next_request["parent_run_id"] = packet["run_id"]
    next_request["issues"][0]["concern"] = "An easier issue"
    with pytest.raises(ValueError, match="drops_or_rewrites_unresolved"): validate_request(next_request, next_parent, bundle)


@pytest.mark.parametrize("mutation", ["number", "audit", "hold", "request"])
def test_receipt_replay_checks_graph_field_audit_request_and_remaining_review(tmp_path, mutation):
    store, bundle, parent, request, response = fixture(tmp_path)
    _, packet, _ = execute(store, bundle, parent, request, response)
    receipt = deepcopy(packet["receipt"])
    if mutation == "number": receipt["extraction"]["results"][0]["quantity"]["value"] = 999
    if mutation == "audit": receipt["revision_audit"]["field_changes"][0]["selected_source"]["start_char"] += 1
    if mutation == "hold": receipt["validation"]["issues"] = []
    if mutation == "request": receipt["review_request"]["fields"][0]["allow_absent"] = True
    with pytest.raises(ValueError): verify_receipt(receipt, bundle, packet["raw_output"])


def test_audit_detects_unrequested_mutation_after_copying(tmp_path):
    _, bundle, parent, request, response = fixture(tmp_path)
    revision = apply_edits(parent, bundle, NativeEdits.model_validate(response), review_request=request)
    revision.revised_graph.observations[0].result.quantity.value = 999
    with pytest.raises(ValueError, match="undeclared_change"): audit_revision(parent, revision, bundle)


def test_provider_failure_retained_without_retry_or_repaired_rows(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path)
    class Unavailable:
        calls = 0
        def extract(self, *args):
            self.calls += 1
            raise ProviderFailure("provider_timeout", retryable=True)
    outcome, packet, provider = execute(store, bundle, parent, request, response, Unavailable())
    assert provider.calls == 1 and outcome["state"] == "failed"
    assert packet["rows"]["results"] == [] and not packet["receipt"]["retryable"]


def test_nested_result_and_definition_sources_keep_separate_evidence_namespaces(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path, nested_raw=True)
    graph, _ = resolve_parent(parent, bundle); observation = graph.observations[0]
    request["issues"][0]["targets"].append({"entity":"result", "entity_id":observation.id})
    for number, (path, old) in enumerate([
            ("/result/quantity_name_raw", observation.result.quantity_name_raw),
            ("/definition/criterion_raw", observation.definition.criterion_raw)], 2):
        request["fields"].append({"id":f"F{number}", "issue_id":"source-fidelity", "entity":"result",
            "entity_id":observation.id, "field":path, "expected_value_sha256":digest(old),
            "kind":"raw_literal", "allow_absent":False})
        response["selections"].append(dict(response["selections"][0], target_id=f"F{number}", exact_text="onset"))
    response["request_sha256"] = digest(request)
    _, packet, _ = execute(store, bundle, parent, request, response)
    result = packet["receipt"]["extraction"]["results"][0]
    assert result["quantity"] == parent["receipt"]["extraction"]["results"][0]["quantity"]
    assert result["definition"]["criterion"] == observation.definition.criterion
    assert result["quantity_name_raw"] == result["definition"]["criterion_raw"] == "onset"
    fields = {row["field"] for row in result["evidence"]}
    assert "/quantity_name_raw" in fields and "/definition/criterion_raw" in fields
    assert not any(field.startswith("/result/") for field in fields)


def test_chained_field_revision_keeps_review_issues_and_reconstructs_exact_parent(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path)
    _, first, _ = execute(store, bundle, parent, request, response)
    next_parent = {k:first[k] for k in ("run_id","receipt","raw_output")}
    graph, _ = resolve_parent(next_parent, bundle)
    next_request = deepcopy(request); next_request["parent_run_id"] = first["run_id"]
    next_request["fields"][0]["expected_value_sha256"] = digest("bulk")
    next_response = deepcopy(response)
    next_response.update(parent_run_id=first["run_id"], base_graph_sha256=digest(graph.model_dump()), request_sha256=digest(next_request))
    next_response["selections"][0].update(action="unresolved", exact_text=None)
    _, second, provider = execute(store, bundle, next_parent, next_request, next_response)
    assert provider.calls == 1
    assert second["receipt"]["extraction"] == first["receipt"]["extraction"]
    assert pending_review_issues({k:second[k] for k in ("run_id","receipt","raw_output")}) == request["issues"]


def test_invalid_target_request_fails_before_provider_but_retains_empty_attempt(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path)
    request["fields"][0]["expected_value_sha256"] = "0" * 64
    outcome, packet, provider = execute(store, bundle, parent, request, response)
    assert provider.calls == 0 and outcome["state"] == "quarantined"
    assert packet["rows"]["results"] == [] and "extraction" not in packet["receipt"]
    assert packet["receipt"]["review_request"] == request
    assert packet["receipt"]["revision_error_detail"] == "source_field_stale_value"
