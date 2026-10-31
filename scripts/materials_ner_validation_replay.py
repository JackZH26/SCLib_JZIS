#!/usr/bin/env python3
"""Revalidate frozen native proposals without replacing receipts or review states.

This is a diagnostic artifact, not an extraction attempt, promotion packet,
independent scientific read or ML qualification. No provider is invoked.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.native_revision import NativeRevision, audit_revision
from ingestion.materials_ner.native_revision_edits import NativeEdits, apply_edits
from ingestion.materials_ner.proposals import import_packet, verify_packet
from ingestion.materials_ner.sources import Bundle, private_write, sha
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction, training_exclusions
from ingestion.materials_ner.wire_v7 import NativeExtraction, validate_coverage
from ingestion.materials_ner.worker import implementation_sources


def diagnose(packet):
    verify_packet(packet)
    receipt = packet["receipt"]
    result = {"run_id": packet["run_id"], "job_id": packet["job_id"],
        "packet_sha256": digest(packet), "work_id": packet["work_id"],
        "bundle_sha256": packet["bundle_hash"], "raw_output_sha256": receipt.get("raw_output_sha256"),
        "historical_worker_state": receipt["state"], "historical_review_states_retained": True,
        "original_validation": receipt.get("validation"),
        "scientific_acceptance": False, "ml_training_eligible": False, "production_writes": False}
    if "extraction" not in receipt:
        return dict(result, replayable=False, reason="No structured extraction in the historical receipt")
    bundle = Bundle.model_validate(packet["bundle"])
    format_ = receipt["config"]["output_format"]
    proof_issues = []
    if format_ in {"materials-native-revision/1", "materials-native-edits/1"}:
        base = receipt["revision_parent"]["raw_output"]
        revision = (apply_edits(base, NativeEdits.model_validate_json(packet["raw_output"]))
                    if format_ == "materials-native-edits/1"
                    else NativeRevision.model_validate_json(packet["raw_output"]))
        compact = revision.revised_graph
        proof_issues = audit_revision(base, revision, bundle)["issues"]
    elif format_ == "materials-ner-shared/3":
        compact = NativeExtraction.model_validate_json(packet["raw_output"])
    elif format_ == "materials-ner-shared/4":
        from ingestion.materials_ner.wire_v8 import RelationalExtraction
        compact = RelationalExtraction.model_validate_json(packet["raw_output"])
    elif format_ == "materials-relational-edits/1":
        from ingestion.materials_ner.relational_revision import verify_receipt
        compact, _ = verify_receipt(receipt, bundle, packet["raw_output"])
        proof_issues = receipt["revision_audit"]["issues"]
    elif format_ == "materials-relational-edits/2":
        from ingestion.materials_ner.relational_review import verify_receipt
        compact, _ = verify_receipt(receipt, bundle, packet["raw_output"])
        proof_issues = receipt["revision_audit"]["issues"]
    elif format_ == "materials-source-field-edits/1":
        from ingestion.materials_ner.source_field_revision import verify_receipt
        compact, _ = verify_receipt(receipt, bundle, packet["raw_output"])
        proof_issues = receipt["revision_audit"]["issues"]
    elif format_ == "materials-source-field-edits/2":
        from ingestion.materials_ner.source_field_local import verify_receipt
        compact, _ = verify_receipt(receipt, bundle, packet["raw_output"])
        proof_issues = receipt["revision_audit"]["issues"]
    else:
        raise ValueError("This diagnostic supports native shared/3, shared/4 and their explicit revisions")
    extraction = compact.expand(bundle)
    if extraction.model_dump() != receipt["extraction"]:
        raise ValueError("Replay must not alter the original extraction")
    coverage = validate_coverage(compact, Inventory.model_validate(receipt["inventory"]), bundle)
    validation = validate_extraction(extraction, bundle)
    validation["issues"].extend(coverage["issues"] + proof_issues)
    validation["valid"] = not validation["issues"]
    key = lambda issue: (issue["code"], issue["path"])
    before = {key(i): i for i in receipt["validation"]["issues"]}
    after = {key(i): i for i in validation["issues"]}
    return dict(result, replayable=True, results=len(extraction.results),
        source_assertions_unchanged=True, current_validation=validation,
        current_inventory_coverage=coverage,
        resolved_issues=[before[k] for k in sorted(before.keys() - after.keys())],
        added_issues=[after[k] for k in sorted(after.keys() - before.keys())],
        historical_issue_counts=dict(Counter(i["code"] for i in receipt["validation"]["issues"])),
        current_issue_counts=dict(Counter(i["code"] for i in validation["issues"])),
        current_training_assessment=training_exclusions(extraction, bundle, validation))


def replay(root, labels, output):
    if output.exists():
        raise ValueError("Use a new replay directory; historical diagnostics are immutable")
    store = Store(root)
    reports, inputs, jobs = [], {}, set()
    for label in labels:
        state_path = root / "runs" / label / "state.json"
        state = json.loads(state_path.read_bytes())
        if state["state"] != "checkpointed": raise ValueError("Only terminal runs may be replayed")
        inputs[str(state_path)] = sha(state_path.read_bytes())
        for job in state["jobs"]:
            if job["id"] in jobs: raise ValueError("Duplicate extraction job")
            jobs.add(job["id"])
            packet = import_packet(store, job["id"])
            reports.append(dict(diagnose(packet), label=label))
    # Capture the actual executable sources, including this diagnostic script.
    sources = implementation_sources()
    sources["scripts/" + Path(__file__).name] = Path(__file__).read_bytes()
    manifest = {name: sha(raw) for name, raw in sources.items()}
    for name, raw in sources.items(): private_write(output / "implementation" / name, raw)
    report = {"schema": "materials-native-validation-replay/1",
        "created_at": datetime.now(timezone.utc).isoformat(), "inputs": inputs,
        "implementation_sha256": digest(manifest), "implementation_files": manifest,
        "runs": reports, "provider_calls": 0, "historical_receipts_modified": False,
        "historical_review_states_modified": False, "scientific_acceptance": False,
        "ml_training_eligible": False, "production_writes": False}
    private_write(output / "report.json", canonical(report).encode())
    return {"path": str(output / "report.json"), "runs": [{"label": r["label"],
        "replayable": r["replayable"], "resolved_issues": r.get("resolved_issues", []),
        "added_issues": r.get("added_issues", []),
        "current_issue_counts": r.get("current_issue_counts", {})} for r in reports]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--labels", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(canonical(replay(args.root, args.labels, args.output)))
