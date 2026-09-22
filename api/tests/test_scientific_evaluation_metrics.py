"""Offline metric arithmetic fixtures, not reviewed scientific benchmarks."""
from __future__ import annotations

import copy
import json

import pytest

from models.scientific_evaluation import OutputLabels, ScientificEvaluationPackage
from services.scientific_evaluation_metrics import compute_metrics
from tests.test_scientific_evaluation_models import labels_payload, package_payload, source_payload


def fixture(n=1):
    payload = package_payload()
    payload["protocol"]["k_values"] = [1, 2, 5]
    payload["corpus"]["sources"] = []
    for index in range(1, 7):
        source = source_payload()
        source.update(id=f"source-{index}", root_id=f"root-{index}")
        payload["corpus"]["sources"].append(source)
    case = payload["cases"][0]
    observation = payload["runs"][0]["observations"][0]
    payload["cases"] = []
    observations = []
    for index in range(1, n + 1):
        payload["cases"].append({**copy.deepcopy(case), "id": f"case-{index}", "query_group_id": f"group-{index}",
                                 "split": "held_out" if index % 2 else "development"})
        observations.append({**copy.deepcopy(observation), "case_id": f"case-{index}", "judgments": []})
    run = payload["runs"][0]
    payload["runs"] = [{**copy.deepcopy(run), "id": arm, "arm": arm, "observations": copy.deepcopy(observations)}
                       for arm in ("baseline", "candidate")]
    decisions = {case["id"]: "accept" for case in payload["cases"]}
    labels = {arm: {case["id"]: labels_payload() for case in payload["cases"]} for arm in ("baseline", "candidate")}
    return payload, decisions, labels


def score(payload, decisions, labels):
    package = ScientificEvaluationPackage.model_validate(payload)
    checked = {run: {case: OutputLabels.model_validate(label) if label is not None else None
                     for case, label in cases.items()} for run, cases in labels.items()}
    return compute_metrics(package, case_decisions=decisions, output_labels=checked)


def summary(report, arm="candidate", split="all"):
    return report["arms"][arm]["splits"][split]


def metric(report, name, arm="candidate", split="all"):
    return summary(report, arm, split)["metrics"][name]


def test_empty_evaluation_is_null_not_a_perfect_benchmark():
    report = score(*fixture(0))
    assert report["coverage"]["planned_cases"] == 0
    for split in ("all", "held_out", "development"):
        values = summary(report, split=split)
        assert values["planned_cases"] == 0
        assert all(item["value"] is None and item["denominator"] == 0 for item in values["metrics"].values())
        assert values["operations"]["cost_usd"]["complete_total"] is None
    assert report["version"] == "scientific-eval-metrics/1.0.0"
    for flag in ("scientific_acceptance", "reviewer_authority_authenticated", "source_roots_authenticated", "independent_support_established"):
        assert report[flag] is False


@pytest.mark.parametrize("status", ["unavailable", "not_run"])
def test_unavailable_retrieval_is_missing_not_zero_recall(status):
    payload, decisions, labels = fixture(2)
    for run in payload["runs"]:
        for observation in run["observations"]:
            observation.update(status=status, retrieved_source_ids=[], selected_source_ids=[], answer="")
    report = score(payload, decisions, labels)
    value = metric(report, "evidence_bundle_completion_at_1")
    assert (value["denominator"], value["missing"], value["value"]) == (0, 2, None)
    assert report["paired"]["metrics"]["evidence_bundle_completion_at_1"]["unscored"] == 2


def test_completed_empty_retrieval_counts_actual_misses():
    payload, decisions, labels = fixture()
    payload["runs"][1]["observations"][0]["retrieved_source_ids"] = []
    report = score(payload, decisions, labels)
    for name in ("evidence_bundle_completion_at_1", "declared_root_recall_at_1"):
        value = metric(report, name)
        assert (value["numerator"], value["denominator"], value["missing"], value["value"]) == (0, 1, 0, 0)
        assert report["paired"]["metrics"][name]["regressed"] == 1


def test_support_alternatives_are_or_of_complete_and_bundles():
    payload, decisions, labels = fixture()
    payload["cases"][0]["expected"]["claims"][0]["evidence_alternatives"] = [["source-1", "source-2"], ["source-3"]]
    payload["runs"][0]["observations"][0]["retrieved_source_ids"] = ["source-1", "source-2"]
    payload["runs"][1]["observations"][0]["retrieved_source_ids"] = ["source-3"]
    report = score(payload, decisions, labels)
    assert metric(report, "evidence_bundle_completion_at_1", "baseline")["value"] == 0
    assert metric(report, "evidence_bundle_completion_at_2", "baseline")["value"] == 1
    assert metric(report, "evidence_bundle_completion_at_1")["value"] == 1
    assert metric(report, "declared_root_recall_at_1")["value"] == 1 / 3
    assert report["paired"]["metrics"]["evidence_bundle_completion_at_1"]["improved"] == 1


def test_declared_root_micro_recall_deduplicates_repeat_root_not_work_id():
    payload, decisions, labels = fixture(2)
    for source in payload["corpus"]["sources"]:
        source["work_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    payload["corpus"]["sources"][1]["root_id"] = "root-1"
    payload["cases"][0]["expected"]["claims"][0]["evidence_alternatives"] = [["source-1", "source-2"]]
    payload["cases"][1]["expected"]["claims"][0]["evidence_alternatives"] = [["source-3", "source-4"]]
    payload["runs"][1]["observations"][1]["retrieved_source_ids"] = ["source-3"]
    report = score(payload, decisions, labels)
    value = metric(report, "declared_root_recall_at_1")
    assert (value["numerator"], value["denominator"], value["value"]) == (2, 3, 2 / 3)
    assert value["denominator_unit"] == "declared_relevant_root"


def test_one_unknown_support_root_makes_whole_case_root_inventory_missing():
    payload, decisions, labels = fixture()
    payload["corpus"]["sources"][1].update(root_id=None, work_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    payload["cases"][0]["expected"]["claims"][0]["evidence_alternatives"] = [["source-1"], ["source-2"]]
    report = score(payload, decisions, labels)
    roots = metric(report, "declared_root_recall_at_1")
    assert (roots["denominator"], roots["missing"], roots["value"]) == (0, 1, None)
    assert roots["missing_unit"] == "case"
    assert metric(report, "evidence_bundle_completion_at_1")["value"] == 1


@pytest.mark.parametrize("name", ["condition_match", "numerical_correct", "unit_correct", "refusal_correct"])
def test_correctness_retains_undetermined_denominator_and_missing_review(name):
    payload, decisions, labels = fixture(5)
    for index, status in enumerate(("correct", "incorrect", "undetermined", "not_applicable"), 1):
        labels["candidate"][f"case-{index}"][name] = status
    labels["candidate"]["case-5"] = None
    value = metric(score(payload, decisions, labels), name)
    assert (value["numerator"], value["denominator"], value["undetermined"], value["not_applicable"], value["missing"]) == (1, 3, 1, 1, 1)
    assert value["value"] == 1 / 3


@pytest.mark.parametrize("decision", ["reject", "needs_revision", "unreviewed", "disputed"])
def test_nonaccepted_case_cannot_supply_gold_but_citation_syntax_is_observable(decision):
    payload, decisions, labels = fixture()
    decisions["case-1"] = decision
    report = score(payload, decisions, labels)
    assert summary(report)["accepted_cases"] == 0
    assert metric(report, "evidence_bundle_completion_at_1")["missing"] == 1
    assert metric(report, "claim_support_precision")["missing"] == 1
    assert metric(report, "mechanical_citation_precision")["value"] == 1


def test_support_precision_and_expected_coverage_preserve_undetermined_and_deduplicate():
    payload, decisions, labels = fixture()
    claim = payload["cases"][0]["expected"]["claims"][0]
    payload["cases"][0]["expected"]["claims"] = [{**copy.deepcopy(claim), "id": f"expected-{index}"} for index in range(1, 4)]
    judgment = labels["candidate"]["case-1"]["claims"][0]
    labels["candidate"]["case-1"]["claims"] = [
        {**judgment, "id": "j1", "status": "supported", "expected_claim_ids": ["expected-1", "expected-2"]},
        {**judgment, "id": "j2", "status": "contradicted", "expected_claim_ids": ["expected-2"]},
        {**judgment, "id": "j3", "status": "undetermined", "expected_claim_ids": ["expected-2", "expected-3"]},
    ]
    report = score(payload, decisions, labels)
    precision = metric(report, "claim_support_precision")
    coverage = metric(report, "expected_claim_coverage")
    assert (precision["numerator"], precision["denominator"], precision["undetermined"], precision["value"]) == (1, 3, 1, 1 / 3)
    assert (coverage["numerator"], coverage["denominator"], coverage["undetermined"], coverage["value"]) == (2, 3, 1, 2 / 3)
    # Three claims are still one scored case, never three independent samples.
    assert precision["scored_cases"] == coverage["scored_cases"] == 1
    assert metric(report, "evidence_bundle_completion_at_1")["scored_cases"] == 1


def test_scored_case_count_is_not_root_claim_or_citation_denominator():
    payload, decisions, labels = fixture(2)
    payload["cases"][0]["expected"]["claims"][0]["evidence_alternatives"] = [["source-1", "source-2", "source-3"]]
    payload["runs"][1]["observations"][0]["answer"] = "[1] [1] [1] [1]"
    payload["runs"][1]["observations"][1].update(status="unavailable", answer="", answer_mode="unavailable")
    report = score(payload, decisions, labels)
    assert metric(report, "declared_root_recall_at_1")["denominator"] == 3
    assert metric(report, "mechanical_citation_precision")["denominator"] == 4
    assert metric(report, "declared_root_recall_at_1")["scored_cases"] == 1
    assert metric(report, "mechanical_citation_precision")["scored_cases"] == 1


def test_selective_claim_inventory_does_not_raise_precision_or_coverage():
    payload, decisions, labels = fixture()
    labels["candidate"]["case-1"].update(answer_claims_complete=False, condition_match="correct")
    labels["candidate"]["case-1"]["claims"][0]["status"] = "supported"
    report = score(payload, decisions, labels)
    assert metric(report, "condition_match")["value"] == 1
    for name in ("claim_support_precision", "expected_claim_coverage"):
        assert metric(report, name)["value"] is None and metric(report, name)["missing"] == 1


def test_empty_expected_and_complete_empty_answer_claims_are_not_applicable():
    payload, decisions, labels = fixture()
    payload["cases"][0]["expected"]["claims"] = []
    labels["candidate"]["case-1"]["claims"] = []
    report = score(payload, decisions, labels)
    for name in ("evidence_bundle_completion_at_1", "declared_root_recall_at_1", "claim_support_precision", "expected_claim_coverage"):
        assert metric(report, name)["not_applicable"] == 1 and metric(report, name)["value"] is None


def test_mechanical_citations_count_actual_occurrences_and_reject_grouped_or_noncanonical_indices():
    payload, decisions, labels = fixture()
    payload["runs"][1]["observations"][0].update(selected_source_ids=["source-1", "source-2"],
        answer="[1] [1] [2] [9] [01] [0] [1,2] [١] [" + "9" * 5000 + "]")
    report = score(payload, decisions, labels)
    value = metric(report, "mechanical_citation_precision")
    assert (value["numerator"], value["denominator"], value["value"]) == (3, 9, 1 / 3)
    assert summary(report)["unsupported_grouped_citation_count"] == 1


def test_mechanical_metric_does_not_invoke_lexical_entailment_checker():
    payload, decisions, labels = fixture()
    payload["runs"][1]["observations"][0]["answer"] = "A fabricated unrelated claim [1]."
    labels["candidate"]["case-1"]["claims"][0]["status"] = "contradicted"
    report = score(payload, decisions, labels)
    assert metric(report, "mechanical_citation_precision")["value"] == 1
    assert metric(report, "claim_support_precision")["value"] == 0


def test_operational_nearest_rank_and_known_partial_totals_are_not_imputed():
    payload, decisions, labels = fixture(21)
    for index, observation in enumerate(payload["runs"][1]["observations"][:20], 1):
        observation.update(latency_ms=float(index), input_tokens=0, total_tokens=index, cost_usd=0.0, provider_fallback=index % 2 == 0)
    operations = summary(score(payload, decisions, labels))["operations"]
    assert operations["latency_ms"] == {"observed_count": 20, "missing_count": 1, "p95_nearest_rank": 19}
    assert operations["input_tokens"] == {"known_total": 0, "observed_count": 20, "missing_count": 1, "complete_total": None}
    assert operations["total_tokens"]["known_total"] == 210
    assert operations["provider_fallback"]["value"] == 0.5
    assert operations["provider_fallback"]["missing"] == 1
    assert operations["cost_usd"]["known_total"] == 0 and operations["cost_usd"]["complete_total"] is None
    assert operations["cost_per_supported_answer_usd"] is None
    assert operations["measurement_scope"] == "synthetic_not_production"


def test_all_unknown_usage_and_cost_stay_null():
    operations = summary(score(*fixture()))["operations"]
    for name in ("input_tokens", "total_tokens", "cost_usd"):
        assert operations[name] == {"known_total": None, "observed_count": 0, "missing_count": 1, "complete_total": None}
    assert operations["provider_fallback"]["value"] is None
    assert operations["latency_ms"]["p95_nearest_rank"] is None


def test_cost_per_supported_answer_requires_all_costs_and_complete_resolved_claim_reviews():
    payload, decisions, labels = fixture(2)
    for index, observation in enumerate(payload["runs"][1]["observations"], 1):
        observation["cost_usd"] = 0.2 * index
        labels["candidate"][f"case-{index}"]["claims"][0]["status"] = "supported"
    operations = summary(score(payload, decisions, labels))["operations"]
    assert operations["cost_per_supported_answer_usd"] == pytest.approx(0.3)
    assert operations["supported_answer_count"] == 2
    labels["candidate"]["case-2"]["claims"][0]["status"] = "undetermined"
    operations = summary(score(payload, decisions, labels))["operations"]
    assert operations["cost_per_supported_answer_usd"] is None
    assert operations["support_adjudication_complete"] is False


def test_case_splits_quota_coverage_and_paired_outcomes_keep_every_planned_case():
    payload, decisions, labels = fixture(4)
    payload["protocol"]["strata"] = [{"dimension": "family", "key": "synthetic", "min_n": 4},
                                      {"dimension": "tag", "key": "missing-stratum", "min_n": 1}]
    payload["cases"][0]["families"].append("second-family")
    labels["baseline"]["case-1"]["condition_match"] = "incorrect"
    labels["candidate"]["case-1"]["condition_match"] = "correct"
    labels["baseline"]["case-2"]["condition_match"] = "correct"
    labels["candidate"]["case-2"]["condition_match"] = "incorrect"
    labels["candidate"]["case-4"] = None
    decisions["case-4"] = "unreviewed"
    report = score(payload, decisions, labels)
    assert report["paired"]["metrics"]["condition_match"] == {"improved": 1, "regressed": 1, "tied": 1, "unscored": 1, "planned_pairs": 4}
    assert len(report["paired"]["cases"]) == 4
    assert summary(report, split="held_out")["planned_cases"] == 2
    assert summary(report, split="development")["planned_cases"] == 2
    quota = report["coverage"]["quotas"][0]
    assert (quota["planned_cases"], quota["accepted_cases"], quota["held_out_accepted_cases"], quota["declared_quota_met"]) == (4, 3, 2, False)
    assert report["coverage"]["quotas"][1]["planned_cases"] == 0
    assert report["coverage"]["multi_label_strata_may_overlap"] is True
    assert summary(report)["strata"]["family"]["second-family"]["planned_cases"] == 1


@pytest.mark.parametrize("fault", ["missing_observation", "duplicate_observation", "missing_review", "missing_decision", "unknown_decision", "same_arm", "missing_run_labels"])
def test_direct_metrics_call_never_silently_intersects_incomplete_inventories(fault):
    payload, decisions, labels = fixture(2)
    if fault == "missing_observation":
        payload["runs"][1]["observations"].pop()
    elif fault == "duplicate_observation":
        payload["runs"][1]["observations"][1] = copy.deepcopy(payload["runs"][1]["observations"][0])
    elif fault == "missing_review":
        labels["candidate"].pop("case-1")
    elif fault == "missing_decision":
        decisions.pop("case-1")
    elif fault == "unknown_decision":
        decisions["case-1"] = "scientifically_approved"
    elif fault == "same_arm":
        payload["runs"][0]["arm"] = "candidate"
    else:
        labels.pop("candidate")
    with pytest.raises(ValueError):
        score(payload, decisions, labels)


def test_finite_individual_costs_cannot_overflow_into_invalid_json_total():
    payload, decisions, labels = fixture(2)
    for observation in payload["runs"][1]["observations"]:
        observation["cost_usd"] = 1e308
    with pytest.raises(ValueError, match="finite"):
        score(payload, decisions, labels)


def test_metrics_leave_original_frozen_objects_unchanged_and_emit_no_question_answer_or_prose():
    payload, decisions, labels = fixture()
    original = copy.deepcopy((payload, decisions, labels))
    report = score(payload, decisions, labels)
    assert (payload, decisions, labels) == original
    rendered = json.dumps(report, allow_nan=False)
    assert payload["cases"][0]["query"] not in rendered
    assert payload["runs"][0]["observations"][0]["answer"] not in rendered
    assert "reviewed_gold_pass" not in rendered
