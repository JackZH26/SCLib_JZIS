"""Synthetic software fixtures only; no real events, reviews or permissions."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.validate_pilot_review import (
    FIELDS,
    _loads,
    review_hash,
    selection_hash,
    validate,
)

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "docs/pilot"


def selection():
    value = json.loads((PILOT / "selection.template.json").read_text())
    value.update({
        "pilot_id": "SYNTHETIC-TEST-NOT-A-REAL-PILOT", "protocol_status": "approved",
        "protocol_sha256": "a" * 64, "approval_reference": "synthetic-declaration-not-real-approval",
        "selection_status": "frozen", "strata": [{"id": "test", "definition": "Synthetic fixture, not a scientific quota"}],
        "candidates": [{"candidate_id": f"SYNTHETIC-event-{index}", "selection_kind": "actual_source_event", "stratum_id": "test", "family": "synthetic-family", "source_class": "synthetic-format", "source_reference": f"synthetic-source-{index}", "event_locator": "synthetic-event-location", "selection_rationale": "Software fixture only"} for index in range(60)],
        "reviewers": [{"id": "synthetic-human-A", "kind": "human", "roles": ["primary"]}, {"id": "synthetic-human-B", "kind": "human", "roles": ["secondary"]}, {"id": "synthetic-human-C", "kind": "human", "roles": ["arbitration"]}],
        "second_review_candidate_ids": ["SYNTHETIC-event-0", "SYNTHETIC-event-1"], "independence_plan": "Synthetic declaration; no actual humans participated",
        "selected_at": "2026-09-01T00:00:00Z", "frozen_at": "2026-09-02T00:00:00Z",
    })
    value["selection_sha256"] = selection_hash(value)
    return value


def result(index=0):
    return {
        "result_id": f"SYNTHETIC-result-{index}", "decision": "accepted", "decision_reason": "Synthetic asserted decision; not science approval",
        "source": {"paper_id": "synthetic-paper", "revision": "synthetic-revision", "locator": {"table": "synthetic-table"}, "context_reference": "opaque-synthetic-context", "context_sha256": "c" * 64, "access_status": "permitted", "permission_reference": "synthetic-only-not-a-license"},
        "work_id": "synthetic-work", "sample_id": "synthetic-sample", "state_id": f"synthetic-state-{index}", "state_interpretation": "Synthetic interpreted state", "structure_id": None,
        "observation": "positive_tc", "tc": {"relation": "exact", "value": 0.03, "lower": None, "upper": None, "uncertainty": 0.001, "approximate": True, "unit": "K"},
        "tested_temperature_min_k": None, "tc_criterion": "Synthetic onset criterion", "pressure_state": "unknown", "pressure": None, "origin": "Observed", "method": "Synthetic method",
        "fields": {**{field: "reported" for field in FIELDS}, "structure_identity": "not_extracted", "pressure": "ambiguous"},
        "missingness_reasons": {"structure_identity": "No synthetic structure artifact", "pressure": "Unknown synthetic pressure"}, "errors": [],
    }


def review(manifest, index=0, role="primary", primary=None):
    actor = {"primary": "synthetic-human-A", "secondary": "synthetic-human-B", "arbitration": "synthetic-human-C"}[role]
    return {
        "schema_version": "ml08-review/1.0.0", "review_id": f"SYNTHETIC-{role}-{index}-v1", "candidate_id": f"SYNTHETIC-event-{index}", "selection_sha256": manifest["selection_sha256"],
        "reviewer_id": actor, "reviewer_kind": "human", "role": role, "revision": 1, "supersedes_review_id": None,
        "completed_at": "2026-09-03T00:00:00Z", "active_minutes": 5, "active_minutes_by_field": {"tc_value": 2},
        "outcome": "recovered", "outcome_reason": "Synthetic recovery fixture", "independent_assessment": role == "secondary", "requires_second_review": False,
        "compares_review_ids": [primary["review_id"]] if primary else [], "comparison": "agreement" if primary else "not_compared", "disagreement_codes": [], "results": [result(index)],
    }


def report(manifest, reviews, conclusion=None):
    return validate(manifest, reviews, conclusion, manifest["selection_sha256"])


def complete_fixture():
    manifest = selection()
    reviews = [review(manifest, index) for index in range(60)]
    reviews += [review(manifest, index, "secondary", reviews[index]) for index in (0, 1)]
    conclusion = json.loads((PILOT / "conclusion.template.json").read_text())
    conclusion.update({"status": "submitted_for_signoff", "selection_sha256": manifest["selection_sha256"], "review_log_sha256": review_hash(reviews), "reviewer_id": "synthetic-human-C", "completed_at": "2026-09-04T00:00:00Z", "recommendation": "narrow", "rationale": "Synthetic test, never scientific acceptance", "field_actions": [{"field": field, "action": "narrow", "reason": "Synthetic test rationale"} for field in FIELDS], "canary_bundle_reference": "synthetic-unopened-bundle", "canary_bundle_sha256": "d" * 64, "limitations": ["No actual reviewers or scientific data"]})
    return manifest, reviews, conclusion


class PilotReviewTests(unittest.TestCase):
    def test_empty_templates_are_preparation_not_completed_pilot(self):
        manifest = json.loads((PILOT / "selection.template.json").read_text())
        conclusion = json.loads((PILOT / "conclusion.template.json").read_text())
        self.assertFalse((PILOT / "reviews.template.jsonl").read_text().strip())
        value = validate(manifest, [], conclusion)
        self.assertEqual(value["errors"], [])
        self.assertEqual(value["status"], "preparation_draft")
        self.assertEqual(value["counts"]["selected_candidates"], 0)
        self.assertEqual(value["counts"]["primary_reviewed_candidates"], 0)
        self.assertFalse(value["ready_for_review"])
        self.assertFalse(value["ready_for_final_human_signoff"])

    def test_ready_requires_external_anchor_and_exactly_sixty_events(self):
        manifest = selection()
        self.assertFalse(validate(manifest, [])["ready_for_review"])
        self.assertTrue(report(manifest, [])["ready_for_review"])
        self.assertEqual(report(manifest, [])["status"], "selection_ready_not_reviewed")
        manifest["candidates"].pop()
        manifest["selection_sha256"] = selection_hash(manifest)
        self.assertFalse(report(manifest, [])["ready_for_review"])

    def test_selection_replacement_cannot_match_separately_retained_anchor(self):
        manifest = selection()
        original = manifest["selection_sha256"]
        manifest["candidates"][4]["source_reference"] = "another-synthetic-event"
        manifest["selection_sha256"] = selection_hash(manifest)
        self.assertIn("selection: external_anchor_mismatch_no_silent_replacement", validate(manifest, [], expected_selection_sha256=original)["errors"])

    def test_duplicate_event_and_unknown_stratum_are_rejected(self):
        for mutation in (lambda x: x["candidates"][1].update(candidate_id=x["candidates"][0]["candidate_id"]), lambda x: x["candidates"][0].update(stratum_id="undeclared")):
            manifest = selection()
            mutation(manifest)
            manifest["selection_sha256"] = selection_hash(manifest)
            self.assertTrue(report(manifest, [])["errors"])

    def test_unapproved_protocol_and_missing_second_review_plan_stay_not_ready(self):
        for field, value in (("protocol_status", "proposed"), ("approval_reference", None), ("independence_plan", None), ("second_review_candidate_ids", [])):
            with self.subTest(field=field):
                manifest = selection()
                manifest[field] = value
                manifest["selection_sha256"] = selection_hash(manifest)
                self.assertFalse(report(manifest, [])["ready_for_review"])

    def test_reviews_cannot_precede_frozen_selection(self):
        manifest = selection()
        record = review(manifest)
        record["completed_at"] = "2026-09-01T12:00:00Z"
        self.assertTrue(report(manifest, [record])["errors"])

    def test_reviews_cannot_change_cohort_or_omit_timezone(self):
        manifest = selection()
        for field, value in (("candidate_id", "outside-frozen-selection"), ("selection_sha256", "e" * 64), ("completed_at", "2026-09-03T00:00:00")):
            with self.subTest(field=field):
                record = review(manifest)
                record[field] = value
                self.assertTrue(report(manifest, [record])["errors"])

    def test_failure_stays_in_candidate_denominator_without_fake_results(self):
        manifest = selection()
        records = [review(manifest, 0), review(manifest, 1)]
        records[1].update(outcome="inaccessible", results=[])
        value = report(manifest, records)
        self.assertEqual(value["errors"], [])
        self.assertEqual(value["counts"]["selected_candidates"], 60)
        self.assertEqual(value["counts"]["primary_reviewed_candidates"], 2)
        self.assertEqual(value["counts"]["unreviewed_candidates"], 58)
        self.assertEqual(value["event_outcomes"]["inaccessible"], 1)
        self.assertEqual(value["atomic_field_missingness"]["denominator"], 1)
        self.assertEqual(value["candidate_field_recovery"]["tc_value"], {"candidates_with_any_reported_result": 1, "selected_candidate_denominator": 60})
        group = value["time_and_denominators_by_group"]["source_class"]["synthetic-format"]
        self.assertEqual(group["selected_candidates"], 60)
        self.assertEqual(group["event_outcomes"]["inaccessible"], 1)
        self.assertEqual(group["candidates_with_any_reported_field"]["tc_value"], 1)
        records[1]["results"] = [result(1)]
        self.assertTrue(report(manifest, records)["errors"])

    def test_multiple_results_do_not_increase_candidate_denominator(self):
        manifest = selection()
        record = review(manifest)
        record["results"].append(result(1))
        value = report(manifest, [record])
        self.assertEqual(value["counts"]["atomic_results_in_effective_reviews"], 2)
        self.assertEqual(value["counts"]["primary_reviewed_candidates"], 1)
        self.assertEqual(value["reported_identity_counts"]["work_id"], 1)
        self.assertIsNone(value["counts"]["independent_work_count"])

    def test_repeated_result_identity_is_not_counted_as_a_second_atomic_result(self):
        manifest = selection()
        records = [review(manifest, 0), review(manifest, 1)]
        records[1]["results"] = copy.deepcopy(records[0]["results"])
        value = report(manifest, records)
        self.assertEqual(value["counts"]["event_result_associations"], 2)
        self.assertEqual(value["atomic_field_missingness"]["denominator"], 1)
        records[1]["results"][0]["tc"]["value"] = 99
        self.assertTrue(report(manifest, records)["errors"])

    def test_accepted_results_require_source_state_criterion_and_permissions(self):
        mutations = [lambda x: x["source"].update(revision=None), lambda x: x["source"].update(locator={}), lambda x: x.update(state_id=None), lambda x: x.update(tc_criterion=None), lambda x: x.update(method=None), lambda x: x["source"].update(access_status="unknown"), lambda x: x["source"].update(permission_reference=None)]
        for mutation in mutations:
            manifest = selection()
            record = review(manifest)
            mutation(record["results"][0])
            self.assertTrue(report(manifest, [record])["errors"])

    def test_unknown_pressure_is_not_zero_or_invented_ambient(self):
        manifest = selection()
        record = review(manifest)
        record["results"][0]["pressure"] = {**result()["tc"], "value": 0, "unit": "GPa"}
        self.assertTrue(report(manifest, [record])["errors"])

    def test_quantities_preserve_bounds_uncertainty_and_small_values(self):
        manifest = selection()
        record = review(manifest)
        quantity = record["results"][0]["tc"]
        before = copy.deepcopy(quantity)
        self.assertFalse(report(manifest, [record])["errors"])
        self.assertEqual(quantity, before)
        quantity.update(relation="le", value=None, upper=0.03)
        self.assertFalse(report(manifest, [record])["errors"])
        quantity["value"] = 0.03
        self.assertTrue(report(manifest, [record])["errors"])

    def test_negative_requires_observed_test_window_and_never_tc_zero(self):
        manifest = selection()
        record = review(manifest)
        item = record["results"][0]
        item.update(observation="not_detected", tc=None, tested_temperature_min_k=0.03)
        item["fields"]["tc_value"] = "not_applicable"
        item["missingness_reasons"]["tc_value"] = "Explicit non-transition observation, not Tc=0"
        self.assertFalse(report(manifest, [record])["errors"])
        for field, bad in (("tested_temperature_min_k", None), ("origin", "Computed"), ("tc", {**result()["tc"], "value": 0})):
            copy_record = copy.deepcopy(record)
            copy_record["results"][0][field] = bad
            self.assertTrue(report(manifest, [copy_record])["errors"])

    def test_missingness_requires_reason_and_errors_are_not_coverage(self):
        manifest = selection()
        record = review(manifest)
        record["results"][0]["missingness_reasons"] = {}
        self.assertTrue(report(manifest, [record])["errors"])
        record = review(manifest)
        record["results"][0].update(decision="pending", errors=[{"kind": "normalization", "field": "pressure", "code": "synthetic_unit_error"}])
        value = report(manifest, [record])
        self.assertEqual(value["error_counts_separate_from_missingness"], {"normalization": 1})
        self.assertEqual(value["atomic_field_missingness"]["counts"]["pressure"], {"ambiguous": 1})

    def test_secondary_requires_distinct_predeclared_human(self):
        manifest = selection()
        first = review(manifest)
        second = review(manifest, role="secondary", primary=first)
        for field, value in (("reviewer_id", "synthetic-human-A"), ("reviewer_kind", "llm"), ("independent_assessment", False)):
            bad = {**second, field: value}
            self.assertTrue(report(manifest, [first, bad])["errors"])

    def test_append_only_revisions_preserve_time_and_update_statistics(self):
        manifest = selection()
        first = review(manifest)
        newer = copy.deepcopy(first)
        newer.update(review_id="synthetic-primary-v2", revision=2, supersedes_review_id=first["review_id"], active_minutes=2, active_minutes_by_field={})
        newer["results"][0]["tc"]["value"] = 0.05
        value = report(manifest, [first, newer])
        self.assertEqual(value["errors"], [])
        self.assertEqual(value["curation_time"]["recorded_active_minutes_all_revisions"], 7)
        self.assertEqual(value["counts"]["atomic_results_in_effective_reviews"], 1)
        newer["supersedes_review_id"] = None
        self.assertTrue(report(manifest, [first, newer])["errors"])

    def test_unmeasured_time_is_not_imputed_zero_and_field_time_is_disjoint(self):
        manifest = selection()
        record = review(manifest)
        record.update(active_minutes=None, active_minutes_by_field={})
        value = report(manifest, [record])
        self.assertEqual(value["curation_time"]["records_with_timing"], 0)
        self.assertEqual(value["curation_time"]["review_record_denominator"], 1)
        self.assertEqual(value["curation_time_by_field"]["tc_value"]["records_with_timing"], 0)
        record.update(active_minutes=1, active_minutes_by_field={"tc_value": 2})
        self.assertTrue(report(manifest, [record])["errors"])

    def test_sixty_primary_reviews_alone_do_not_complete_pilot(self):
        manifest, records, conclusion = complete_fixture()
        value = report(manifest, records[:60], conclusion)
        self.assertFalse(value["ready_for_final_human_signoff"])
        self.assertIn("secondary_reviews_missing:2", value["final_gaps"])

    def test_complete_synthetic_package_never_grants_scientific_acceptance(self):
        manifest, records, conclusion = complete_fixture()
        value = report(manifest, records, conclusion)
        self.assertEqual(value["errors"], [])
        self.assertTrue(value["ready_for_final_human_signoff"])
        self.assertEqual(value["status"], "final_package_ready_for_human_signoff")
        self.assertFalse(value["scientific_acceptance"])
        self.assertEqual(value["counts"]["atomic_results_in_effective_reviews"], 60)

    def test_disagreement_requires_current_arbitration_and_may_remain_unresolved(self):
        manifest, records, conclusion = complete_fixture()
        records[60].update(comparison="disagreement", disagreement_codes=["synthetic_state_conflict"])
        records[60]["results"][0].update(decision="pending")
        self.assertIn("disagreement_arbitration_missing_or_stale", report(manifest, records, conclusion)["final_gaps"])
        arb = review(manifest, role="arbitration")
        arb.update(comparison="unresolved", disagreement_codes=["synthetic_state_conflict"], compares_review_ids=[records[0]["review_id"], records[60]["review_id"]])
        arb["results"][0]["decision"] = "pending"
        records.append(arb)
        conclusion["review_log_sha256"] = review_hash(records)
        value = report(manifest, records, conclusion)
        self.assertTrue(value["ready_for_final_human_signoff"])
        self.assertEqual(value["atomic_result_decisions"]["pending"], 1)
        arb["results"][0]["decision"] = "accepted"
        self.assertTrue(report(manifest, records, conclusion)["errors"])

    def test_false_agreement_and_stale_comparison_do_not_pass_final_gate(self):
        manifest, records, conclusion = complete_fixture()
        records[60]["results"][0]["tc"]["value"] = 1
        self.assertIn("declared_agreement_has_structured_differences", report(manifest, records, conclusion)["final_gaps"])
        records[60]["results"][0]["tc"]["value"] = 0.03
        newer = copy.deepcopy(records[0])
        newer.update(review_id="synthetic-primary-v2", revision=2, supersedes_review_id=records[0]["review_id"])
        records.append(newer)
        self.assertIn("secondary_comparison_stale", report(manifest, records, conclusion)["final_gaps"])

    def test_conclusion_requires_current_log_hash_and_all_field_recommendations(self):
        manifest, records, conclusion = complete_fixture()
        conclusion["review_log_sha256"] = "e" * 64
        conclusion["field_actions"].pop()
        value = report(manifest, records, conclusion)
        self.assertIn("conclusion_not_bound_to_current_selection_and_log", value["final_gaps"])
        self.assertIn("field_keep_narrow_defer_recommendations_incomplete", value["final_gaps"])

    def test_parser_rejects_duplicate_keys_nonfinite_numbers_and_unknown_private_fields(self):
        for payload in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError):
                _loads(payload)
        manifest = selection()
        manifest["private_secret"] = "DO-NOT-ECHO"
        value = validate(manifest, [])
        self.assertTrue(value["errors"])
        self.assertNotIn("DO-NOT-ECHO", json.dumps(value))

    def test_cli_draft_gate_exit_codes_and_read_only_inputs(self):
        command = [sys.executable, str(ROOT / "scripts/validate_pilot_review.py"), str(PILOT / "selection.template.json"), str(PILOT / "reviews.template.jsonl")]
        before = (PILOT / "selection.template.json").read_bytes()
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout)["status"], "preparation_draft")
        self.assertEqual(subprocess.run([*command, "--require", "ready"], capture_output=True, check=False).returncode, 2)
        self.assertEqual(subprocess.run([*command, "--require", "final"], capture_output=True, check=False).returncode, 2)
        self.assertEqual((PILOT / "selection.template.json").read_bytes(), before)

    def test_cli_rejects_malformed_input_without_echoing_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "bad.json"
            fixture.write_text('{"private":"DO-NOT-ECHO","x":NaN}')
            completed = subprocess.run([sys.executable, str(ROOT / "scripts/validate_pilot_review.py"), str(fixture)], capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 1)
            self.assertNotIn("DO-NOT-ECHO", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
