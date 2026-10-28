"""A rejected source slice cannot erase the field or the independent good edit."""
from copy import deepcopy
import json
import sqlite3

import pytest

from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.native_revision import configuration, run_one
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.relational_revision import resolve_parent
from ingestion.materials_ner.source_field_local import VERSION, NativeEdits, apply_edits, verify_receipt
from ingestion.materials_ner.source_field_revision import NativeEdits as AtomicEdits, apply_edits as atomic_apply
from test_materials_ner_source_field_revision import fixture
from test_materials_ner_inventory_v2 import SequenceProvider


def prepared(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path)
    graph, _ = resolve_parent(parent, bundle)
    request["fields"].append(dict(request["fields"][0], id="F2", field="/formula_raw", expected_value_sha256=digest(graph.samples[0].formula_raw)))
    response.update(schema_version=VERSION, request_sha256=digest(request))
    response["selections"].append(dict(response["selections"][0], target_id="F2", exact_text="unreported compound"))
    return store, bundle, parent, request, response


@pytest.mark.parametrize("failure", ["missing_text", "ambiguous", "out_of_range", "empty"])
def test_unlocatable_source_preserves_that_field_and_applies_other_source_valid_fields(tmp_path, failure):
    store, bundle, parent, request, response = prepared(tmp_path)
    selection = response["selections"][1]
    if failure == "ambiguous": selection["exact_text"] = "Sample A"
    if failure == "out_of_range": selection.update(exact_text="MgB2", occurrence=99)
    if failure == "empty": selection["exact_text"] = ""
    # The old wire remains atomic and cannot be silently replayed with v2 rules.
    with pytest.raises(ValueError): atomic_apply(parent, bundle, AtomicEdits.model_validate(dict(response, schema_version="materials-source-field-edits/1")), review_request=request)
    config = configuration(parent, mode="source_fields_local", review_request=request)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=parent["receipt"]["bundle_sha256"], config=config, max_attempts=1)
    provider = SequenceProvider([response])
    outcome = run_one(store, job, parent, bundle, mode="source_fields_local", provider_override=provider)
    packet = import_packet(store, job); verify_packet(packet)
    assert provider.calls == 1 and outcome["state"] == "quarantined"
    receipt = packet["receipt"]; sample = receipt["extraction"]["samples"][0]
    original = parent["receipt"]["extraction"]["samples"][0]
    assert sample["form_raw"] == "bulk" and sample["formula_raw"] == original["formula_raw"]
    assert [e for e in sample["evidence"] if e["field"] == "/formula_raw"] == [e for e in original["evidence"] if e["field"] == "/formula_raw"]
    assert receipt["extraction"]["results"] == parent["receipt"]["extraction"]["results"]
    audit = receipt["revision_audit"]
    assert audit["rejected_field_count"] == 1 and audit["invalid_fields_and_evidence_preserved"]
    rejected = audit["field_changes"][1]
    assert rejected["selection_error"] and not rejected["changed"] and rejected["selected_source"] is None
    assert rejected["before"] == rejected["after"]
    assert audit["pending_review_issues"] == request["issues"] and not packet["ml_training_eligible"]
    tampered = deepcopy(receipt); tampered["revision_audit"]["rejected_field_count"] = 0
    with pytest.raises(ValueError): verify_receipt(tampered, bundle, packet["raw_output"])
    db = ProposalDatabase(tmp_path / "private")
    assert db.ingest(packet)["inserted"] and not db.ingest(packet)["inserted"]
    with db.connect() as connection, sqlite3.connect(tmp_path / "restore.sqlite3") as restored:
        connection.backup(restored)
        assert not restored.execute("PRAGMA foreign_key_check").fetchall()
        for row in restored.execute("SELECT payload FROM runs"): verify_packet(json.loads(row[0]))


@pytest.mark.parametrize("failure", ["parent", "stale_value", "coverage", "unknown_source"])
def test_local_rejection_does_not_bypass_global_preconditions(tmp_path, failure):
    _, bundle, parent, request, response = prepared(tmp_path)
    if failure == "parent": response["parent_run_id"] = "0" * 64
    if failure == "stale_value": request["fields"][0]["expected_value_sha256"] = "0" * 64
    if failure == "coverage": response["selections"] = response["selections"][:1]
    if failure == "unknown_source": response["selections"][1]["span_ids"] = ["S999"]
    with pytest.raises(ValueError): apply_edits(parent, bundle, NativeEdits.model_validate(response), review_request=request)
