"""Materialize prospectively registered quality windows without model or database writes.

The existing extraction pipeline keeps running. Future small execution batches
are grouped using candidate counts only; their original source-review decisions
are copied unchanged. Only complete, prospectively defined windows can qualify.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
from uuid import uuid4

from ingestion.materials_ner import reviewed_reader as rr
from materials_ner_production90 import POLICY, digest, read_pin
from materials_ner_tc_intake import KEY, checked_projection, quality

SCHEMA = "materials-prospective-quality-windows/1"
TERMINAL = {"admission_processed", "scientific_batch_held", "no_eligible_candidates"}

def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone_required")
    return result

def require(condition, code):
    if not condition:
        raise ValueError(code)

def preparation_time(manifest, receipt, plan):
    """The production batch has no timestamp; use its hash-bound job inputs."""
    prepared = []
    for job in manifest["jobs"]:
        request = read_pin(job["input"])
        require(request["schema"] == "materials-core-tc-input/1", "unexpected_extraction_input")
        coverage = read_pin(request["coverage"])
        require(coverage["work_id"] == job["work_id"], "preparation_work_identity_changed")
        created = coverage["created_at"]
        require(timestamp(created) > timestamp(plan["created_at"]), "historical_batch_not_allowed")
        prepared.append(created)
    if prepared:
        return min(prepared, key=timestamp)
    require(receipt["state"] == "no_eligible_candidates", "nonempty_result_without_jobs")
    require(timestamp(receipt["finished_at"]) > timestamp(plan["created_at"]),
            "historical_batch_not_allowed")
    return receipt["finished_at"]

def partition(batches, plan):
    """No review verdict or qualification result participates in membership."""
    windows, pending, skipped = [], [], []
    count = 0
    expected = plan["first_execution_batch"]
    for batch in batches:
        require(batch["number"] == expected, "execution_batch_gap_or_reordering")
        expected += 1
        require(timestamp(batch["extraction_created_at"]) > timestamp(plan["created_at"]),
                "historical_batch_not_allowed")
        size = batch["eligible"]
        require(isinstance(size, int) and size >= 0, "invalid_candidate_count")
        if size == 0:
            skipped.append({"batch": batch["number"], "reason": "no_eligible_candidates"})
            continue
        if size > plan["maximum_small_batch_eligible_records"]:
            skipped.append({"batch": batch["number"], "reason": "existing_large_batch_sampling_route"})
            continue
        require(batch["method"] == "census_of_retained_records", "small_batch_requires_census")
        pending.append(batch)
        count += size
        if count >= plan["target_eligible_records"]:
            windows.append(pending)
            pending, count = [], 0
    return windows, pending, skipped

def load_batch(campaign, receipt_path, number, plan):
    receipt = json.loads(receipt_path.read_bytes())
    require(receipt["batch"] == f"batch-{number:03d}", "execution_batch_identity_changed")
    require(receipt["state"] in TERMINAL, "execution_batch_not_terminal")
    for pin in receipt["completion_evidence"]:
        rr.checked(pin)
    directory = campaign / receipt["batch"]
    manifest_path = directory / "BATCH.json"
    manifest = json.loads(manifest_path.read_bytes())
    require(manifest["only_new_papers"], "recovery_batch_not_allowed_in_prospective_window")
    created_at = preparation_time(manifest, receipt, plan)
    descriptor = {
        "number": number, "extraction_created_at": created_at,
        "preparation_timestamp_source": "hash_bound_job_coverage" if manifest["jobs"] else "empty_batch_completion",
        "receipt": rr.reference(receipt_path), "manifest": rr.reference(manifest_path),
        "state": receipt["state"], "eligible": 0, "method": None,
    }
    if receipt["state"] == "no_eligible_candidates":
        require(receipt["quality"] is None, "empty_batch_has_quality_result")
        return descriptor
    selection_path = directory / "FROZEN_SAMPLE.json"
    audit_path = directory / "luna-audit/SOURCE_AUDIT.json"
    selection = json.loads(selection_path.read_bytes())
    audit = json.loads(audit_path.read_bytes())
    require(timestamp(selection["created_at"]) > timestamp(plan["created_at"]),
            "historical_selection_not_allowed")
    require(audit["reviewer_kind"] == "model" and audit["reviewer_model"] == "gpt-6-luna",
            "unexpected_source_reviewer")
    require(not audit["candidate_verdicts_in_model_input"] and not audit["independent_expert_review"],
            "source_review_scope_changed")
    require(quality(selection, audit) == receipt["quality"], "original_quality_report_changed")
    descriptor.update(
        eligible=selection["eligible_results"], method=selection["method"],
        selection_pin=rr.reference(selection_path), audit_pin=rr.reference(audit_path),
        selection=selection, audit=audit, original_quality=receipt["quality"],
    )
    if 0 < descriptor["eligible"] <= plan["maximum_small_batch_eligible_records"]:
        require(len(selection["records"]) == descriptor["eligible"] == len(audit["records"]),
                "incomplete_original_census")
    return descriptor

def aggregate_payloads(plan_pin, plan, members, ordinal, created_at):
    """Preserve every original verdict, including unavailable/indeterminate rows."""
    entries, population, decisions, origins = [], [], [], []
    seen_runs, seen_records = set(), set()
    for member in members:
        selection, audit = member["selection"], member["audit"]
        require(timestamp(member["extraction_created_at"]) > timestamp(plan["created_at"]),
                "historical_batch_not_allowed")
        require(read_pin(member["selection_pin"]) == selection
                and read_pin(member["audit_pin"]) == audit,
                "original_review_payload_changed")
        require(read_pin(member["receipt"])["quality"] == member["original_quality"],
                "original_quality_report_changed")
        for entry in selection["source_entries"]:
            packet, projection = checked_projection(entry)
            eligible = [r for r in projection["records"] if r["status"] == "eligible_for_source_audit"]
            if not eligible:
                continue
            require(packet["run_id"] not in seen_runs, "duplicate_source_run_in_window")
            seen_runs.add(packet["run_id"])
            entries.append(deepcopy(entry))
            for row in projection["records"]:
                value = {k: row[k] for k in ("work_id", "result_id", "run_id", "status", "holds")}
                value["projection_sha256"] = projection["projection_sha256"]
                key = tuple(value[k] for k in KEY)
                require(key not in seen_records, "duplicate_record_in_window")
                seen_records.add(key)
                population.append(value)
        decisions.extend(deepcopy(audit["records"]))
        origins.append({
            "execution_batch": member["number"], "batch_result": member["receipt"],
            "selection": member["selection_pin"], "source_audit": member["audit_pin"],
            "original_quality": deepcopy(member["original_quality"]),
        })
    eligible = [r for r in population if r["status"] == "eligible_for_source_audit"]
    require(len(eligible) == sum(m["eligible"] for m in members), "window_population_changed")
    require(len(eligible) >= plan["target_eligible_records"], "incomplete_window")
    seed = f"prospective-quality-window:{plan_pin['sha256']}:{ordinal}"
    selected = sorted(eligible, key=lambda row: digest([seed, *[row[k] for k in KEY]]))
    selection = {
        "schema": "materials-native-tc-sample/1", "policy": POLICY,
        "seed": seed, "method": "census_of_retained_records", "created_at": created_at,
        "source_entries": entries, "population": population, "population_sha256": digest(population),
        "input_results": len(population), "eligible_results": len(eligible),
        "held_results": len(population) - len(eligible),
        "records": [{k: row[k] for k in KEY} for row in selected],
        "independent_gold": False, "prior_source_exposure": True,
        "source_exposure_note": (
            "Window membership was registered before these extractions. Original source "
            "reviews existed when this aggregate was materialized; no verdict selects "
            "membership or the boundary. This is not an independent gold benchmark."
        ),
        "prospective_window": {
            "registration": plan_pin, "ordinal": ordinal,
            "execution_batches": [m["number"] for m in members],
            "registration_predates_all_included_extractions": True,
        },
    }
    selection["selection_sha256"] = digest(selection)
    original_decision_hashes = sorted(digest(r) for m in members for r in m["audit"]["records"])
    require(sorted(digest(r) for r in decisions) == original_decision_hashes,
            "original_review_decisions_changed")
    audit = {
        "schema": "materials-source-audit/1",
        "selection_sha256": selection["selection_sha256"],
        "reviewer_kind": "model", "reviewer_model": "gpt-6-luna", "reviewer_reasoning": "high",
        "reviewer_identity": "Original separate Luna source-check invocations; deterministic prospective-window aggregation.",
        "independent_expert_review": False, "created_at": created_at,
        "candidate_verdicts_in_model_input": False,
        "records": sorted(decisions, key=lambda row: tuple(row[k] for k in KEY)),
        "aggregation": {
            "schema": SCHEMA, "registration": plan_pin, "original_reviews": origins,
            "original_model_verdicts_and_rationales_unchanged": True,
            "new_model_calls": 0, "not_a_new_model_review": True,
        },
    }
    require({tuple(r[k] for k in KEY) for r in decisions}
            == {tuple(r[k] for k in KEY) for r in selected}, "window_audit_membership_changed")
    return selection, audit

def atomic_status(path, value):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".pending")
    rr.put(temporary, value)
    temporary.replace(path)

def build(plan_path, implementation_path=None):
    plan_path = Path(plan_path).resolve()
    plan_pin = rr.reference(plan_path)
    plan = read_pin(plan_pin)
    require(plan["schema"] == SCHEMA and plan["admission_policy"] == POLICY,
            "unexpected_window_policy")
    require(plan["threshold"] == 0.9 and plan["target_eligible_records"] == 50
            and plan["maximum_small_batch_eligible_records"] == 50, "window_rule_changed")
    pipeline = read_pin(plan["pipeline"])
    campaign = Path(plan["campaign"])
    pipeline_dir = Path(plan["pipeline_directory"])
    root = plan_path.parent
    implementation = Path(implementation_path).resolve() if implementation_path else root / "IMPLEMENTATION.json"
    require(implementation.exists(), "verified_implementation_required")
    impl = json.loads(implementation.read_bytes())
    require(impl["plan"] == plan_pin, "registered_plan_changed")
    require(impl["assembler"] == rr.reference(Path(__file__)), "assembler_changed")
    rr.checked(impl["assembler"])
    with (root / "ASSEMBLY.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        descriptors = []
        number = plan["first_execution_batch"]
        while True:
            index = number - pipeline["batch_start"]
            require(index >= 0, "window_before_pipeline")
            path = pipeline_dir / f"BATCH_{index:03d}.json"
            if not path.exists():
                break
            descriptors.append(load_batch(campaign, path, number, plan))
            number += 1
        windows, pending, skipped = partition(descriptors, plan)
        completed = []
        for ordinal, members in enumerate(windows, 1):
            directory = root / f"window-{ordinal:03d}"
            previous_selection = directory / "FROZEN_SAMPLE.json"
            created_at = (json.loads(previous_selection.read_bytes())["created_at"]
                          if previous_selection.exists() else datetime.now(timezone.utc).isoformat())
            selection, audit = aggregate_payloads(plan_pin, plan, members, ordinal, created_at)
            report = quality(selection, audit)
            directory.mkdir(exist_ok=True)
            rr.put(previous_selection, selection)
            rr.put(directory / "SOURCE_AUDIT.json", audit)
            rr.put(directory / "QUALITY_REPORT.json", report)
            manifest = {
                "schema": "materials-prospective-quality-window-result/1",
                "created_at": created_at, "registration": plan_pin, "ordinal": ordinal,
                "state": "qualified_for_existing_admission" if report["qualified"] else "held",
                "execution_batches": [m["number"] for m in members],
                "original_batch_results": [m["receipt"] for m in members],
                "eligible_records": selection["eligible_results"],
                "selection": rr.reference(previous_selection),
                "source_audit": rr.reference(directory / "SOURCE_AUDIT.json"),
                "quality_report": rr.reference(directory / "QUALITY_REPORT.json"),
                "original_model_decisions_unchanged": True, "new_model_calls": 0,
                "database_writes_performed": False, "assembler": rr.reference(Path(__file__)),
            }
            rr.put(directory / "MANIFEST.json", manifest)
            completed.append({"manifest": rr.reference(directory / "MANIFEST.json"),
                              "state": manifest["state"], "eligible_records": selection["eligible_results"],
                              "quality": report})
        status = {
            "schema": "materials-prospective-quality-window-status/1",
            "at": datetime.now(timezone.utc).isoformat(), "registration": plan_pin,
            "next_execution_batch_without_terminal_receipt": number,
            "completed_windows": completed,
            "pending_window": {"execution_batches": [m["number"] for m in pending],
                               "eligible_records": sum(m["eligible"] for m in pending)},
            "batches_on_existing_route": skipped, "new_model_calls": 0,
            "database_writes_performed": False, "assembler": rr.reference(Path(__file__)),
            "implementation": rr.reference(implementation),
        }
        atomic_status(root / "STATUS.json", status)
        return status

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--implementation", type=Path,
                        help="Explicit verified implementation revision; original receipts remain unchanged.")
    args = parser.parse_args()
    result = build(args.plan, args.implementation)
    print(json.dumps({k: result[k] for k in (
        "next_execution_batch_without_terminal_receipt", "completed_windows",
        "pending_window", "new_model_calls", "database_writes_performed")}))
