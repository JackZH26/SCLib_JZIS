#!/usr/bin/env python3
"""One bounded Luna reread of a frozen native attempt; never edits the parent."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"ingestion"))
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.native_revision import configuration, run_one, verify_parent
from ingestion.materials_ner.proposals import import_packet, verify_packet
from ingestion.materials_ner.sources import Bundle, private_write, sha, save_bundle
from ingestion.materials_ner.store import Store
from materials_ner_empirical_pilot import export


def run(root, parent_job_id, label, mode="edits", review_request=None):
    destination = root/"runs"/label
    if destination.exists(): raise ValueError("Use a new revision label; terminal attempts are immutable")
    store = Store(root)
    packet = import_packet(store, parent_job_id); verify_packet(packet)
    parent = {k: packet[k] for k in ("run_id", "receipt", "raw_output")}
    bundle = Bundle.model_validate(packet["bundle"])
    if mode == "staged_fields":
        from ingestion.materials_ner.staged_revision import FieldRequest, source_bundle, verify_parent as verify_staged_parent
        parent = packet
        bundle, _ = source_bundle(parent, FieldRequest.model_validate(review_request).source_context)
        verify_staged_parent(parent, bundle)
    elif mode in {"scoped_review", "scoped_fields", "condition_review", "coverage_review", "focused_fields"}:
        from ingestion.materials_ner.scoped_review import verify_parent as verify_scoped_parent
        verify_scoped_parent(parent, bundle)
    elif mode in {"relational_edits", "relational_review", "source_fields", "source_fields_local"}:
        from ingestion.materials_ner.relational_revision import verify_parent as verify_relational_parent
        verify_relational_parent(parent, bundle)
    else:
        verify_parent(parent, bundle)
    if mode in {"relational_review", "source_fields", "source_fields_local", "scoped_review", "scoped_fields", "condition_review", "coverage_review", "focused_fields", "staged_fields"}:
        if mode == "staged_fields":
            from ingestion.materials_ner.staged_revision import validate_request
        elif mode == "focused_fields":
            from ingestion.materials_ner.source_field_focus import validate_request
        elif mode == "coverage_review":
            from ingestion.materials_ner.coverage_revision import validate_request
        elif mode == "condition_review":
            from ingestion.materials_ner.condition_review import validate_request
        elif mode == "scoped_review":
            from ingestion.materials_ner.scoped_review import validate_request
        elif mode == "scoped_fields":
            from ingestion.materials_ner.source_field_scoped import validate_request
        elif mode in {"source_fields", "source_fields_local"}:
            from ingestion.materials_ner.source_field_revision import validate_request
        else:
            from ingestion.materials_ner.relational_review import validate_request
        review_request = validate_request(review_request, parent, bundle).model_dump()
    config = configuration(parent, mode=mode, review_request=review_request,
        timeout_seconds=300, max_input_tokens=60000, max_output_tokens=16000)
    plan = json.loads((root/"plan.json").read_bytes())
    windows = [(p,w) for p in plan["papers"] for w in p["windows"] if w["bundle_sha256"] == packet["bundle_hash"]]
    if len(windows) != 1: raise ValueError("Parent is not one frozen pilot window")
    paper, window = windows[0]
    revision_bundle_hash, _ = save_bundle(root, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=revision_bundle_hash, config=config, max_attempts=1)
    # A reused identical job is inspected, not relaunched automatically.
    existing = next(j for j in store.results() if j["id"] == job)
    if existing["state"] != "queued": raise ValueError("Identical revision already exists; inspect its terminal receipt or live handle")
    state = {"schema": "materials-empirical-run/1", "config": config,
        "plan_sha256": digest(plan), "evaluation_role": "development_regression",
        "evaluation_note": "Model source revision of a disclosed frozen attempt; not independent Gold or a fresh test paper.",
        "parent_run_id": parent["run_id"], "parent_job_id": parent_job_id,
        "started_at": datetime.now(timezone.utc).isoformat(), "state": "running", "jobs": [{
            "id": job, "work_id": bundle.work_id, "bundle_sha256": revision_bundle_hash,
            "split": "development_regression", "target_locator": window["target_locator"]}],
        "scientific_acceptance": False, "production_writes": False}
    private_write(destination/"state.json", canonical(state).encode())
    outcome = run_one(store, job, parent, bundle, mode=mode)
    state.update(state="checkpointed", outcomes=[outcome], stop_reason="single_bounded_source_revision",
                 elapsed_seconds_this_run=outcome["elapsed_seconds"])
    private_write(destination/"state.json", canonical(state).encode())
    export(root, label)
    print(canonical(outcome))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--parent-job", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--mode", choices=["full","edits","relational_edits","relational_review","source_fields","source_fields_local","scoped_review","scoped_fields","condition_review","coverage_review","focused_fields","staged_fields"], default="edits")
    parser.add_argument("--review-request", type=Path)
    args=parser.parse_args()
    if not args.label.replace("-", "").isalnum(): parser.error("label must be alphanumeric with optional hyphens")
    run(args.root, args.parent_job, args.label, args.mode,
        json.loads(args.review_request.read_bytes()) if args.review_request else None)
