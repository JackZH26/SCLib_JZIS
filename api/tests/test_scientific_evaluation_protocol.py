"""Declared gates and retained input checks, not scientific release acceptance."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from services import rag
from services import scientific_evaluation as evaluator
from services.rag_input_budget import build_request
from tests.scientific_evaluation_fixtures import MODEL, make_package, reseal


def with_gate(**changes):
    value = make_package()
    value["protocol"]["gates"] = [{"metric": "condition_match", "direction": "min",
        "threshold": 1.0, "min_n": 1, **changes}]
    return reseal(value)


def test_declared_gate_uses_candidate_held_out_not_pooled_development_or_authority():
    value = with_gate()
    for run in value["runs"]:
        for observation in run["observations"][:2]:
            for review in observation["judgments"]:
                review["labels"]["condition_match"] = "incorrect"
    audit = evaluator.compare_package(reseal(value))
    check = audit["declared_threshold_checks"]
    assert check["arm"] == "candidate" and check["split"] == "held_out"
    assert check["checks"][0]["value"] == 1 and check["checks"][0]["scored_cases"] == 1
    assert check["checks"][0]["declared_threshold_met"] is True
    assert check["preregistration_authenticated"] is False
    assert audit["release_authorized"] is audit["scientific_acceptance"] is False
    assert "execution_receipts_unverified" in audit["release_blockers"]


@pytest.mark.parametrize("direction,threshold,expected", [("min", 0.8, True), ("max", 0.8, False), ("max", 1.0, True)])
def test_ratio_threshold_direction_and_exact_boundary(direction, threshold, expected):
    audit = evaluator.compare_package(with_gate(direction=direction, threshold=threshold))
    assert audit["declared_threshold_checks"]["checks"][0]["declared_threshold_met"] is expected


@pytest.mark.parametrize("mutation", ["min_n", "missing_review", "disputed_review", "undetermined", "not_applicable"])
def test_gate_retains_unmeasured_and_uncertain_cases(mutation):
    value = with_gate(min_n=2 if mutation == "min_n" else 1)
    observation = value["runs"][1]["observations"][-1]
    if mutation == "missing_review":
        observation["judgments"].pop()
    elif mutation == "disputed_review":
        observation["judgments"][0]["labels"]["condition_match"] = "incorrect"
    elif mutation in {"undetermined", "not_applicable"}:
        for review in observation["judgments"]:
            review["labels"]["condition_match"] = mutation
    check = evaluator.compare_package(reseal(value))["declared_threshold_checks"]["checks"][0]
    assert check["declared_threshold_met"] is (False if mutation == "undetermined" else None)
    assert check["missing_cases"] == int(mutation in {"missing_review", "disputed_review"})


def test_multi_claims_do_not_inflate_gate_case_count():
    value = with_gate(metric="evidence_bundle_completion_at_3", min_n=2)
    last_case = value["cases"][-1]
    claim = last_case["expected"]["claims"][0]
    last_case["expected"]["claims"].extend([{**deepcopy(claim), "id": "additional-1"},
                                           {**deepcopy(claim), "id": "additional-2"}])
    audit = evaluator.compare_package(reseal(value))
    metric = audit["comparison"]["arms"]["run-candidate"]["splits"]["held_out"]["metrics"]["evidence_bundle_completion_at_3"]
    assert metric["denominator"] == 3 and metric["scored_cases"] == 1
    assert audit["declared_threshold_checks"]["checks"][0]["declared_threshold_met"] is None


@pytest.mark.parametrize("change,code", [({"metric": "invented_accuracy"}, "unsupported_metric_gate"),
    ({"metric": "declared_root_recall_at_2"}, "unsupported_metric_gate"),
    ({"threshold": -0.1}, "ratio_gate_out_of_range"), ({"threshold": 1.1}, "ratio_gate_out_of_range")])
def test_unsupported_or_out_of_range_gates_rejected(change, code):
    with pytest.raises(evaluator.ScientificEvaluationError, match="^" + code + "$"):
        evaluator.validate_package(with_gate(**change))


@pytest.mark.parametrize("mutation,code", [("duplicate", "duplicate_metric_gate"),
    ("contradictory", "contradictory_metric_gates"), ("stratum", "duplicate_stratum_requirement")])
def test_ambiguous_preregistered_inventories_fail_closed(mutation, code):
    value = with_gate()
    if mutation == "stratum":
        value["protocol"]["strata"].append(deepcopy(value["protocol"]["strata"][0]))
    else:
        gate = deepcopy(value["protocol"]["gates"][0])
        if mutation == "contradictory":
            gate.update(direction="max", threshold=0.5)
        value["protocol"]["gates"].append(gate)
    with pytest.raises(evaluator.ScientificEvaluationError, match="^" + code + "$"):
        evaluator.validate_package(reseal(value))


def test_missing_thresholds_and_accepted_stratum_shortfall_remain_release_blockers():
    value = make_package()
    value["protocol"]["strata"][0]["min_n"] = 2
    audit = evaluator.compare_package(reseal(value))
    assert audit["declared_threshold_checks"]["checks"] == []
    assert "release_thresholds_not_declared" in audit["release_blockers"]
    assert "held_out_declared_thresholds_unmet_or_unmeasured" in audit["release_blockers"]
    assert "declared_stratum_coverage_unmet" in audit["release_blockers"]


@pytest.mark.parametrize("mutation,code", [("purpose", "run_purpose_mismatch"),
    ("execution", "run_purpose_mismatch"), ("case_reviewer", "review_purpose_mismatch"),
    ("output_reviewer", "review_purpose_mismatch"), ("mode", "completed_mode_unavailable")])
def test_synthetic_known_mixing_and_completed_unavailable_state_are_rejected(mutation, code):
    value = make_package()
    if mutation == "purpose":
        value["purpose"] = "real_candidate"
    elif mutation == "execution":
        value["runs"][0]["execution"] = "captured"
    elif mutation == "case_reviewer":
        value["case_reviews"][0]["reviewer_kind"] = "declared_human"
    elif mutation == "output_reviewer":
        value["runs"][0]["observations"][0]["judgments"][0]["reviewer_kind"] = "declared_human"
    else:
        value["runs"][0]["observations"][0]["answer_mode"] = "unavailable"
    with pytest.raises(evaluator.ScientificEvaluationError, match="^" + code + "$"):
        evaluator.validate_package(reseal(value))


def test_changing_all_declarations_consistently_does_not_authenticate_real_review():
    value = make_package()
    value["purpose"] = "real_candidate"
    for review in value["case_reviews"]:
        review["reviewer_kind"] = "declared_human"
    for run in value["runs"]:
        run["execution"] = "captured"
        for observation in run["observations"]:
            for review in observation["judgments"]:
                review["reviewer_kind"] = "declared_human"
    audit = evaluator.compare_package(reseal(value))
    assert audit["reviewer_authority_authenticated"] is audit["execution_authenticated"] is False
    assert audit["scientific_acceptance"] is audit["release_authorized"] is False


def with_request():
    value = make_package()
    case, observation = value["cases"][0], value["runs"][0]["observations"][0]
    sources = {source["id"]: source for source in value["corpus"]["sources"]}
    entries = [rag.RagSourceInput(index=index, paper_id=sources[identifier]["paper_id"], title="Synthetic fixture",
        authors_short="Synthetic fixture", year=None, section=None, text=sources[identifier]["text"],
        evidence_provenance=sources[identifier]["evidence_provenance"])
        for index, identifier in enumerate(observation["selected_source_ids"], 1)]
    frozen = build_request(model=MODEL, contents=rag.build_user_prompt(case["query"], entries), system_instruction="Synthetic test only.")
    observation["request_payload"] = json.loads(frozen._payload_json)
    observation["request_sha256"] = frozen.request_sha256
    return reseal(value)


@pytest.mark.parametrize("mutation,code", [("digest", "request_digest_mismatch"),
    ("profile", "unsupported_request_profile"), ("index", "request_citation_order_mismatch"),
    ("boolean_index", "request_citation_order_mismatch"), ("source_inventory", "request_source_inventory_mismatch"),
    ("descriptor", "request_evidence_mismatch"), ("duplicate_key", "duplicate_json_key")])
def test_complete_retained_request_is_checked_after_independently_rehashing_mutated_payload(mutation, code):
    value = with_request()
    observation = value["runs"][0]["observations"][0]
    body = observation["request_payload"]
    if mutation == "digest":
        observation["request_sha256"] = "0" * 64
        for review in observation["judgments"]:
            review["observation_sha256"] = evaluator.observation_digest(observation)
    elif mutation == "profile":
        body["profile"] = "unknown/1"
        value = reseal(value)
    else:
        prompt = body["contents"][0]["parts"][0]["text"]
        prefix, remainder = prompt.split("\n", 1)
        source_json, suffix = remainder.split("\n</untrusted_sources_json>", 1)
        entries = json.loads(source_json)
        if mutation == "index":
            entries[0]["index"] = 2
        elif mutation == "boolean_index":
            entries[0]["index"] = True
        elif mutation == "source_inventory":
            entries.pop()
        elif mutation == "descriptor":
            entries[0]["evidence_provenance"]["currentness"] = "stale"
        source_json = json.dumps(entries, ensure_ascii=False)
        if mutation == "duplicate_key":
            source_json = source_json.replace('"index": 1', '"index": 1, "index": 1', 1)
        body["contents"][0]["parts"][0]["text"] = prefix + "\n" + source_json + "\n</untrusted_sources_json>" + suffix
        value = reseal(value)
    with pytest.raises(evaluator.ScientificEvaluationError, match="^" + code + "$"):
        evaluator.validate_package(value)


def test_digest_only_capture_remains_valid_but_full_request_is_not_reconstructed():
    value = with_request()
    value["runs"][0]["observations"][0]["request_payload"] = None
    audit = evaluator.validate_package(reseal(value))
    assert audit["counts"]["retained_request_payloads"] == 0
    assert audit["ann_replay_available"] is audit["execution_authenticated"] is False


@pytest.mark.parametrize("mutation", ["unsupported_model", "empty_system", "empty_contents", "boolean_output_tokens", "oversized"])
def test_input_builder_errors_stay_within_static_evaluation_rejection(mutation):
    value = with_request()
    body = value["runs"][0]["observations"][0]["request_payload"]
    if mutation == "unsupported_model":
        body["model"] = "https://untrusted.invalid/model"
    elif mutation == "empty_system":
        body["system_instruction"]["parts"][0]["text"] = ""
    elif mutation == "boolean_output_tokens":
        body["generation_config"]["max_output_tokens"] = True
    else:
        body["contents"][0]["parts"][0]["text"] = "" if mutation == "empty_contents" else "x" * (1024 * 1024 + 1)
    with pytest.raises(evaluator.ScientificEvaluationError, match="^invalid_retained_request$"):
        evaluator.validate_package(reseal(value))
