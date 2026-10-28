#!/usr/bin/env python3
"""Immutable assistant diagnostic review and frozen-output validator replay."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
from ingestion.materials_ner.contract import parse_extraction, canonical, digest
from ingestion.materials_ner.proposals import review_rows
from ingestion.materials_ner.sources import load_bundle, private_write, sha
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.worker import configuration


def frozen_write(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    if path.exists():
        raise ValueError(f"immutable artifact already exists: {path.name}")
    private_write(path, raw)


def review(root):
    rows_path = root / "runs/baseline/observations.jsonl"
    rows = [json.loads(x) for x in rows_path.read_text().splitlines()]
    annotations = {}

    def note(row, decision, fields, reason, source_location):
        annotations.setdefault(row["row_id"], []).append({
            "decision": decision, "reviewer_type": "assistant_source_read",
            "scope": "specified_fields_only", "checked_fields": fields, "reason": reason,
            "source_location": source_location, "source_bundle_sha256": row["bundle_sha256"],
            "scientific_acceptance": False, "independent_human_gold": False})

    for row in rows:
        aid, r, pr = row["work_id"], row["result"], row["protocol"]
        value, kind = r["quantity"]["value"], r["quantity_kind"]
        if aid == "arxiv:2508.05010" and kind == "tc":
            note(row, "partial_support", ["sample.formula_raw", "result.quantity.value", "protocol.method"],
                 "The per-alloy value and measurement method agree with the original paper. Composition basis, full conditions and complete paper coverage are not adjudicated.",
                 row["target_locator"])
        if aid == "arxiv:2410.02104" and kind == "tc" and row["job_id"].startswith("a9381c9d"):
            note(row, "partial_support", ["sample.formula_raw", "result.quantity.value", "protocol.method", "result.origin"],
                 "Version 2 Table I was visually inspected. Twelve values belong to four compounds and three calculation protocols; they are computed Tc values, not repeated measurements.",
                 "v2 PDF page 4, Table I")
        if aid == "arxiv:2301.01120" and kind == "tc" and value == 4.6:
            note(row, "reject_field", ["protocol.criterion"],
                 "The source describes resistivity reaching zero at 4.6 K; the proposal labels onset. An exact quote does not validate this criterion assignment.",
                 "v1 PDF page 7, first paragraph")
        if aid == "arxiv:2504.00662" and kind == "tc":
            if value == .3:
                note(row, "reject_field", ["result.quantity_kind", "protocol.criterion"],
                     "Figure 3a describes a spectrum measured in the superconducting state at 0.3 K, not a transition at 0.3 K. This technically passing result must not become a Tc label.",
                     "v1 HTML Figure 3 caption")
            elif value == 3.25:
                note(row, "reject_field", ["result.quantity.value", "result.quantity.relation", "protocol.criterion"],
                     "The source reports suppression of gap-like peaks over 3-3.5 K. The proposal invented the 3.25 K midpoint and lost the gap-feature meaning.",
                     "v1 HTML tunneling-spectroscopy discussion after Figure 2")
            elif value == 2.5:
                note(row, "reject_field", ["result.quantity_kind", "result.origin", "sample.target_kind"],
                     "This is a BCS/proximity interpretation of a degraded surface component. It is not an unqualified bulk transition or a first-principles prediction.",
                     "v1 HTML tunneling-spectroscopy discussion after Figure 2")
            elif value == 4.95:
                note(row, "reject_field", ["result.origin"],
                     "The source obtains bulk Tc from a fit to heat-capacity data. Its provenance is model-derived from experiment, not a theoretical computed prediction.",
                     "v1 HTML heat-capacity discussion after Figure 5")
        if aid == "arxiv:2012.05654" and kind == "non_detection":
            note(row, "reject_field", ["result.quantity_kind", "result.interpretation_raw"],
                 "The cited passage reports spontaneous internal fields in the superconducting state. Zero-field muon mode does not establish absent superconductivity.",
                 "v1 PDF page 2, zero-field muon discussion")
        if aid == "arxiv:2604.07807" and kind == "tc":
            if (row["sample"]["label"] or "").lower().endswith("b"):
                note(row, "source_conflict_requires_review", ["sample.formula_raw", "sample.identity_resolution"],
                     "The source paragraph contains La2PrNiO7, while the title and surrounding text use La2PrNi2O7. Preserve conflicting composition assertions; do not silently correct or accept an exact composition.",
                     "v1 PDF page 2, structural-characterization paragraph; title and Figure 1")
            if value in {15.5, 19.5}:
                note(row, "needs_structured_qualifier", ["protocol.criterion", "result.component_raw"],
                     "The source explicitly calls this a secondary transition onset. Onset is a criterion; secondary is a separate transition stage. Both must survive export.",
                     "v1 PDF page 2, electrical-transport paragraph; Figure 2")

    frozen_write(root / "assistant_review.json", {
        "schema": "materials-assistant-field-review/1", "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline_observations_sha256": sha(rows_path.read_bytes()), "reviewer_type": "assistant",
        "independent_human_gold": False, "scientific_acceptance": False,
        "annotations": annotations})
    original = json.loads((root / "reference_anchors.json").read_bytes())
    corrected = json.loads(canonical(original))
    corrections = []
    for anchor in corrected["anchors"]:
        if anchor["work_id"] == "arxiv:2604.07807" and anchor["value"] in {15.5, 19.5}:
            corrections.append({"anchor_id": anchor["id"], "field": "criterion", "old": anchor["criterion"],
                                "new": "onset", "transition_stage": "secondary",
                                "reason": "Source explicitly labels a secondary transition onset; criterion and stage are independent.",
                                "source_location": "2604.07807v1 PDF page 2 / Figure 2"})
            anchor.update(criterion="onset", transition_stage="secondary")
    corrected.update(schema="materials-pilot-anchors/2", supersedes_sha256=digest(original), corrections=corrections)
    frozen_write(root / "reference_anchors_v2.json", corrected)
    print(canonical({"reviewed_rows":len(annotations), "decisions":dict(Counter(
        a["decision"] for aa in annotations.values() for a in aa)), "reference_corrections":len(corrections)}))


def replay(root, label, source_label="baseline"):
    baseline = json.loads((root / "runs" / source_label / "state.json").read_bytes())
    config = configuration(model="gpt-6-luna", max_input_tokens=60000, timeout_seconds=300)
    jobs, changes = [], []
    old_counts, new_counts, old_issues, new_issues = Counter(), Counter(), Counter(), Counter()
    directory = root / "replays" / label
    if directory.exists():
        raise ValueError("replay label already exists")
    for job in baseline["jobs"]:
        receipts = list((root / "attempts" / job["id"]).glob("*/receipt.json"))
        if len(receipts) != 1:
            raise ValueError("baseline attempt selection must be unambiguous")
        source_raw = receipts[0].read_bytes()
        receipt = json.loads(source_raw)
        if "extraction" not in receipt:
            jobs.append({"job_id":job["id"], "state":"no_expanded_extraction", "receipt_sha256":sha(source_raw)})
            continue
        bundle = load_bundle(root / "bundles" / (job["bundle_sha256"] + ".json"))
        extraction = parse_extraction(receipt["extraction"])
        new = validate_extraction(extraction, bundle)
        old = receipt["validation"]
        old_rows = review_rows(extraction, old)["results"]
        new_rows = review_rows(extraction, new)["results"]
        old_counts.update(r["review_status"] for r in old_rows)
        new_counts.update(r["review_status"] for r in new_rows)
        old_issues.update(i["code"] for i in old["issues"])
        new_issues.update(i["code"] for i in new["issues"])
        for before, after in zip(old_rows, new_rows):
            if before["review_status"] != after["review_status"] or before["issues"] != after["issues"]:
                changes.append({"row_id":job["id"]+":"+before["local_id"],
                                "old_status":before["review_status"], "new_status":after["review_status"],
                                "old_issues":before["issues"], "new_issues":after["issues"]})
        frozen_write(directory / (job["id"] + ".json"), {
            "baseline_receipt_sha256":sha(source_raw), "config":config, "validation":new,
            "extraction_sha256":digest(receipt["extraction"]), "model_called":False})
        jobs.append({"job_id":job["id"], "old_valid":old["valid"], "new_valid":new["valid"],
                     "baseline_receipt_sha256":sha(source_raw)})
    summary={"schema":"materials-frozen-output-replay/1", "config":config, "model_called":False,
             "source_run_label":source_label,
             "jobs":jobs, "old_review_counts":dict(old_counts), "new_review_counts":dict(new_counts),
             "old_issues":dict(old_issues), "new_issues":dict(new_issues), "changes":changes,
             "scientific_acceptance":False,"ml_training_eligible":False}
    frozen_write(directory / "report.json", summary)
    print(canonical({k:summary[k] for k in ("model_called","old_review_counts","new_review_counts","new_issues")}))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["freeze-review","replay"])
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--label",default="registry-1-3-0")
    parser.add_argument("--source-label",default="baseline")
    args=parser.parse_args()
    if not args.label.replace("-", "").isalnum(): parser.error("invalid label")
    review(args.root) if args.action=="freeze-review" else replay(args.root,args.label,args.source_label)
