"""Synthetic policy tests; generated records are not scientific validation."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from ingestion.materials_ner import reviewed_reader as rr
from materials_ner_production90 import digest, qualify
from materials_ner_tc_sampling import retained
import materials_ner_tc_quality_windows as windows

PLAN = {
    "created_at": "2026-10-27T01:00:00+00:00", "first_execution_batch": 45,
    "target_eligible_records": 50, "maximum_small_batch_eligible_records": 50,
}

def descriptor(number, size, **extra):
    return dict(number=number, eligible=size, extraction_created_at="2026-10-27T02:00:00+00:00",
                method="census_of_retained_records", **extra)

def numbers(groups):
    return [[m["number"] for m in g] for g in groups]

def pin(tmp_path, name, data):
    path = tmp_path / name
    rr.put(path, data)
    return rr.reference(path)

def preparation_job(tmp_path, name, created_at):
    coverage = pin(tmp_path, f"coverage-{name}.json", {"work_id": name, "created_at": created_at})
    request = pin(tmp_path, f"request-{name}.json",
                  {"schema": "materials-core-tc-input/1", "coverage": coverage})
    return {"work_id": name, "input": request}

def test_real_batch_manifest_shape_uses_all_hash_bound_preparation_times(tmp_path):
    jobs = [preparation_job(tmp_path, "first", "2026-10-27T02:00:00+00:00"),
            preparation_job(tmp_path, "second", "2026-10-27T03:00:00+00:00")]
    manifest = {"schema": "production90-batch/2", "only_new_papers": True, "jobs": jobs}
    assert "created_at" not in manifest
    assert windows.preparation_time(manifest, {}, PLAN) == "2026-10-27T02:00:00+00:00"
    jobs.append(preparation_job(tmp_path, "historical", "2026-10-27T00:00:00+00:00"))
    with pytest.raises(ValueError, match="historical_batch"):
        windows.preparation_time(manifest, {}, PLAN)

def test_preparation_timestamp_cannot_use_changed_coverage(tmp_path):
    job = preparation_job(tmp_path, "paper", "2026-10-27T02:00:00+00:00")
    coverage = windows.read_pin(job["input"])["coverage"]
    Path(coverage["path"]).write_text('{"created_at":"2026-10-27T03:00:00+00:00"}')
    with pytest.raises(ValueError, match="input_changed"):
        windows.preparation_time({"jobs": [job]}, {}, PLAN)

def test_empty_batch_completion_does_not_invent_an_extraction_timestamp():
    receipt = {"state": "no_eligible_candidates", "finished_at": "2026-10-27T02:00:00+00:00"}
    assert windows.preparation_time({"jobs": []}, receipt, PLAN) == receipt["finished_at"]
    receipt["state"] = "admission_processed"
    with pytest.raises(ValueError, match="without_jobs"):
        windows.preparation_time({"jobs": []}, receipt, PLAN)

def member(tmp_path, number, count, incorrect=0, indeterminate=0):
    work, run, projection_hash = f"arxiv:synthetic-{number}", f"run-{number}", f"projection-{number}"
    quote = "Synthetic policy fixture, not a scientific source."
    evidence = {
        "original_source": pin(tmp_path, f"source-{number}.json", {"blocks": [{"id": "b", "text": quote}]}),
        "block_id": "b", "start_char": 0, "end_char": len(quote), "quote": quote,
    }
    population = [
        dict(work_id=work, result_id=f"r{i}", run_id=run, projection_sha256=projection_hash,
             status="eligible_for_source_audit", holds=[]) for i in range(count)
    ]
    projection = {"projection_sha256": projection_hash, "records": population}
    entry = {
        "packet": pin(tmp_path, f"packet-{number}.json", {"run_id": run}),
        "projection": pin(tmp_path, f"projection-{number}.json", projection),
    }
    selected = [{k: r[k] for k in windows.KEY} for r in population]
    selection = {"source_entries": [entry], "records": selected, "eligible_results": count}
    decisions = []
    for i, row in enumerate(selected):
        verdict = "incorrect" if i < incorrect else "indeterminate" if i < incorrect + indeterminate else "correct"
        decisions.append({**row, "verdict": verdict, "rationale": "Synthetic policy fixture only.",
                          "source_evidence": [evidence], "review_completed": verdict != "indeterminate"})
    audit = {"records": decisions}
    original_quality = {"correct": count - incorrect - indeterminate, "incorrect": incorrect,
                        "indeterminate": indeterminate, "sample_size": count,
                        "qualified": (count - incorrect - indeterminate) / count >= 0.9}
    return {
        **descriptor(number, count), "selection": selection, "audit": audit,
        "selection_pin": pin(tmp_path, f"selection-{number}.json", selection),
        "audit_pin": pin(tmp_path, f"audit-{number}.json", audit),
        "receipt": pin(tmp_path, f"batch-{number}.json", {"quality": original_quality}),
        "original_quality": original_quality,
    }, projection

@pytest.fixture
def read_fixture_projection(monkeypatch):
    # Exercise aggregate membership and real quote/hash qualification without
    # pretending these synthetic fixtures are validated extraction packets.
    monkeypatch.setattr(windows, "checked_projection",
                        lambda entry: (windows.read_pin(entry["packet"]), windows.read_pin(entry["projection"])))

def test_boundaries_ignore_verdicts_and_keep_entire_boundary_batch():
    batches = [descriptor(45, 5, verdict="incorrect"), descriptor(46, 30, verdict="correct"),
               descriptor(47, 20, verdict="indeterminate"), descriptor(48, 4, verdict="correct")]
    groups, pending, skipped = windows.partition(batches, PLAN)
    changed = deepcopy(batches)
    for row in changed:
        row["verdict"] = "correct"
    other, other_pending, _ = windows.partition(changed, PLAN)
    assert numbers(groups) == numbers(other) == [[45, 46, 47]]
    assert sum(m["eligible"] for m in groups[0]) == 55
    assert [m["number"] for m in pending] == [m["number"] for m in other_pending] == [48]
    assert skipped == []

@pytest.mark.parametrize("bad, message", [
    ([descriptor(45, 5), descriptor(47, 45)], "gap_or_reordering"),
    ([{**descriptor(45, 50), "extraction_created_at": "2026-10-27T00:59:59+00:00"}], "historical_batch"),
    ([{**descriptor(45, 50), "method": "paper_stratified_without_replacement"}], "requires_census"),
])
def test_no_historical_pooling_skipped_gap_or_reclassified_small_sample(bad, message):
    with pytest.raises(ValueError, match=message):
        windows.partition(bad, PLAN)

def test_empty_and_large_batches_do_not_select_members_by_quality():
    batches = [descriptor(45, 5), descriptor(46, 0), descriptor(47, 51), descriptor(48, 45)]
    groups, pending, skipped = windows.partition(batches, PLAN)
    assert numbers(groups) == [[45, 48]] and pending == []
    assert skipped == [{"batch": 46, "reason": "no_eligible_candidates"},
                       {"batch": 47, "reason": "existing_large_batch_sampling_route"}]

def test_ninety_percent_window_keeps_failed_history_and_excludes_known_bad(tmp_path, read_fixture_projection):
    first, p1 = member(tmp_path, 45, 5, incorrect=1)
    second, p2 = member(tmp_path, 46, 45, indeterminate=4)
    members = [first, second]
    before = deepcopy(members)
    selection, audit = windows.aggregate_payloads({"sha256": "registered-before-extraction"},
        PLAN, members, 1, "2026-10-27T03:00:00+00:00")
    report = qualify(selection, audit)
    assert report["sample_size"] == 50
    assert (report["correct"], report["incorrect"], report["indeterminate"]) == (45, 1, 4)
    assert report["observed_precision"] == 0.9 and report["qualified"]
    assert report["wilson_95"][0] < 0.9
    assert members == before and first["original_quality"]["qualified"] is False
    assert audit["aggregation"]["original_reviews"][0]["original_quality"] == first["original_quality"]
    assert len(retained(p1, selection, audit)) == 4
    assert len(retained(p2, selection, audit)) == 41
    assert sorted(digest(r) for r in audit["records"]) == sorted(
        digest(r) for m in members for r in m["audit"]["records"])
    assert audit["aggregation"]["new_model_calls"] == 0

def test_full_census_can_cross_fifty_without_dropping_bad_records(tmp_path, read_fixture_projection):
    first, _ = member(tmp_path, 45, 30, incorrect=3)
    second, _ = member(tmp_path, 46, 30, incorrect=3)
    selection, audit = windows.aggregate_payloads({"sha256": "prospective"}, PLAN, [first, second], 1,
                                                 "2026-10-27T03:00:00+00:00")
    assert selection["method"] == "census_of_retained_records"
    assert len(selection["records"]) == 60
    assert qualify(selection, audit)["observed_precision"] == 0.9

def test_partial_window_and_changed_original_verdict_cannot_materialize(tmp_path, read_fixture_projection):
    first, _ = member(tmp_path, 45, 5, incorrect=1)
    with pytest.raises(ValueError, match="incomplete_window"):
        windows.aggregate_payloads({"sha256": "prospective"}, PLAN, [first], 1,
                                   "2026-10-27T03:00:00+00:00")
    first["audit"]["records"][0]["verdict"] = "correct"
    with pytest.raises(ValueError, match="original_review_payload_changed"):
        windows.aggregate_payloads({"sha256": "prospective"}, PLAN, [first], 1,
                                   "2026-10-27T03:00:00+00:00")

def test_changed_source_bytes_still_fail_the_existing_quality_gate(tmp_path, read_fixture_projection):
    first, _ = member(tmp_path, 45, 50)
    selection, audit = windows.aggregate_payloads({"sha256": "prospective"}, PLAN, [first], 1,
                                                 "2026-10-27T03:00:00+00:00")
    source = Path(audit["records"][0]["source_evidence"][0]["original_source"]["path"])
    source.write_text("changed original bytes")
    with pytest.raises(ValueError, match="input_changed"):
        qualify(selection, audit)
