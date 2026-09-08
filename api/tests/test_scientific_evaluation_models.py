"""Synthetic portable representation checks; no real labels or human review."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from models import scientific_evaluation as schema
from models.index_read import IndexReadMetadata
from models.scientific_lookup import ScientificResultBinding
from tests.test_rag_evidence_delivery import descriptor

STAMP = "2026-09-08T00:00:00.000000Z"
GENERATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EVENT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SHA = "a" * 64


def source_payload():
    text = "Synthetic method and result, not a scientific gold label."
    return {"id": "source-1", "paper_id": "synthetic:source", "vector_id": "ig62_" + GENERATION.replace("-", "") + "_" + SHA,
        "vector_sha256": SHA, "source_snapshot_sha256": SHA, "text": text,
        "evidence_provenance": descriptor(body=text, kind="original_passage")}


def case_payload():
    return {"id": "case-1", "query_group_id": "question-family-1", "split": "development", "query": "Synthetic topic?",
        "language": "en", "task": "general", "families": ["synthetic"], "tags": ["not-real-gold"],
        "expected": {"route": "general", "acceptable_modes": ["abstention"], "claims": [
            {"id": "expected-1", "text": "Synthetic assertion", "evidence_alternatives": [["source-1"]]}]}}


def labels_payload():
    return {"condition_match": "undetermined", "numerical_correct": "not_applicable", "unit_correct": "not_applicable",
        "refusal_correct": "undetermined", "answer_claims_complete": True,
        "claims": [{"id": "output-claim-1", "start": 0, "end": 9, "source_ids": ["source-1"],
            "citation_indices": [1], "status": "undetermined", "expected_claim_ids": ["expected-1"]}]}


def output_review_payload():
    return {"id": "output-review-1", "reviewer_id": "synthetic-reviewer-1", "reviewer_kind": "synthetic",
        "observation_sha256": SHA, "submitted_at": STAMP, "rationale": "Synthetic representation fixture only.",
        "labels": labels_payload()}


def observation_payload():
    answer = "Synthetic assertion [1]."
    return {"case_id": "case-1", "case_sha256": SHA, "status": "completed", "retrieved_source_ids": ["source-1"],
        "selected_source_ids": ["source-1"], "answer": answer, "answer_mode": "abstention",
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(), "judgments": [output_review_payload()]}


def package_payload():
    """Structurally valid synthetic fixture; placeholder hashes are NOT verified."""
    return {"purpose": "development_synthetic", "protocol": {"id": "synthetic-protocol", "created_at": STAMP,
        "scope_note": "Synthetic representation-only fixture; no reviewed benchmark.", "k_values": [1, 5, 20]},
        "corpus": {"id": "synthetic-corpus", "generation": {"mode": "generation_snapshot", "generation_id": GENERATION,
            "activation_event_id": EVENT, "manifest_sha256": SHA}, "index_profile": {}, "index_resource": {},
            "sources": [source_payload()]}, "cases": [case_payload()],
        "runs": [{"id": "synthetic-run", "arm": "candidate", "execution": "synthetic", "protocol_sha256": SHA,
            "corpus_sha256": SHA, "dataset_sha256": SHA, "code_revision": "a" * 40, "config": {}, "config_sha256": SHA,
            "lock_sha256": SHA, "prompt_version": "synthetic/1", "policy_versions": {"result": "synthetic/1"},
            "started_at": STAMP, "observations": [observation_payload()]}]}


def case_review_payload():
    return {"id": "case-review-1", "case_id": "case-1", "case_sha256": SHA, "protocol_sha256": SHA,
        "corpus_sha256": SHA, "reviewer_id": "synthetic-reviewer-1", "reviewer_kind": "synthetic",
        "submitted_at": STAMP, "decision": "needs_revision", "rationale": "Synthetic only; no human judgment."}


def rejected(model, value):
    with pytest.raises(ValidationError):
        model.model_validate(value)
    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps(value, allow_nan=True))


def test_package_roundtrip_is_representation_not_authenticated_scientific_review():
    value = schema.ScientificEvaluationPackage.model_validate(package_payload())
    assert schema.ScientificEvaluationPackage.model_validate_json(value.model_dump_json()) == value
    assert value.protocol.target_question_count == 120 and value.protocol.gates == []
    assert value.version == schema.VERSION and value.protocol.metrics_version == schema.METRICS_VERSION
    assert value.corpus.sources[0].root_id is None and value.corpus.sources[0].capture_sha256 is None
    assert value.runs[0].observations[0].cost_usd is None
    assert not hasattr(value, "release_eligible") and not hasattr(value, "reviewer_authority_authenticated")
    with pytest.raises(ValidationError):
        value.purpose = "real_candidate"


@pytest.mark.parametrize("field,value", [("purpose", "scientifically_approved"), ("version", "unknown/1"),
    ("scientific_acceptance", True), ("reviewer_authority_authenticated", True), ("release_eligible", True)])
def test_package_cannot_smuggle_approval_or_unknown_contract(field, value):
    rejected(schema.ScientificEvaluationPackage, {**package_payload(), field: value})


@pytest.mark.parametrize("stamp", ["2026-09-08T00:00:00Z", "2026-09-08T00:00:00.000000+00:00",
    "2026-02-30T00:00:00.000000Z", "0000-01-01T00:00:00.000000Z", "2026-09-08T00:00:60.000000Z",
    "infinity", True, 1788825600])
def test_timestamps_are_exact_finite_utc_text(stamp):
    rejected(schema.EvaluationProtocol, {**package_payload()["protocol"], "created_at": stamp})


def test_datetime_objects_do_not_replace_portable_timestamp_strings():
    with pytest.raises(ValidationError):
        schema.EvaluationProtocol.model_validate({**package_payload()["protocol"], "created_at": datetime.now(UTC)})


@pytest.mark.parametrize("changes", [{"k_values": [1, 1]}, {"k_values": []}, {"k_values": [True]}, {"k_values": [21]},
    {"k_values": ["1"]}, {"target_question_count": 99}, {"target_question_count": 201}, {"target_question_count": True},
    {"scope_note": " "}])
def test_protocol_preserves_explicit_bounded_target_and_cutoffs(changes):
    rejected(schema.EvaluationProtocol, {**package_payload()["protocol"], **changes})


@pytest.mark.parametrize("field,value", [("threshold", True), ("threshold", "0.9"), ("threshold", float("inf")),
    ("threshold", float("nan")), ("min_n", True), ("min_n", 0), ("direction", "greater"), ("metric", "Accuracy %")])
def test_gate_cannot_invent_coerced_nonfinite_or_unbounded_thresholds(field, value):
    rejected(schema.MetricGate, {"metric": "condition_accuracy", "direction": "min", "threshold": 0.9, "min_n": 20, field: value})


@pytest.mark.parametrize("field,value", [("work_id", "not-a-uuid"), ("work_id", GENERATION.upper()),
    ("capture_sha256", "A" * 64), ("source_snapshot_sha256", "a" * 63), ("vector_id", "old-positional-id"),
    ("text", " "), ("text", "\ud800"), ("text", "超" * (512 * 1024 // 3 + 1)), ("text", "x" * (512 * 1024 + 1))],
    ids=lambda value: str(value)[:40])
def test_source_identity_and_original_utf8_resource_bound_are_strict(field, value):
    rejected(schema.CapturedSource, {**source_payload(), field: value})


@pytest.mark.parametrize("change", [{"root_status": "resolved"}, {"scientific_acceptance": True},
    {"scientific_acceptance": 0}, {"support_eligible": True}, {"permission_status": "allowed"}, {"free_text": "Forged"}])
def test_current_descriptor_contract_cannot_be_upgraded_by_eval_artifact(change):
    value = source_payload()
    value["evidence_provenance"].update(change)
    rejected(schema.CapturedSource, value)


def test_legacy_generation_cannot_claim_frozen_corpus_identity():
    rejected(schema.EvaluationCorpus, {**package_payload()["corpus"], "generation": {"mode": "legacy_lexical_only"}})
    forged = IndexReadMetadata.model_construct(mode="generation_snapshot", generation_id=None, activation_event_id=None, manifest_sha256=None)
    with pytest.raises(ValidationError):
        schema.EvaluationCorpus.model_validate({**package_payload()["corpus"], "generation": forged})


def test_complete_corpus_requires_at_least_one_source_and_each_declared_vector_hash():
    rejected(schema.EvaluationCorpus, {**package_payload()["corpus"], "sources": []})
    value = source_payload()
    del value["vector_sha256"]
    rejected(schema.CapturedSource, value)
    rejected(schema.CapturedSource, {**source_payload(), "vector_sha256": "A" * 64})


@pytest.mark.parametrize("field,value", [("query", " "), ("query", "q" * 2001), ("language", "cn"),
    ("task", "scientific_proof"), ("split", "train"), ("families", ["hydride", "hydride"]), ("tags", ["x"] * 33)])
def test_cases_keep_bounded_raw_queries_without_silent_correction(field, value):
    rejected(schema.EvaluationCase, {**case_payload(), field: value})


@pytest.mark.parametrize("bundles", [[], [[]], [["source-1", "source-1"]], [["source-1"], ["source-1"]],
    [["source-1", "source-2"], ["source-2", "source-1"]], [[str(i) for i in range(21)]], [[str(i)] for i in range(21)]])
def test_expected_support_is_nonempty_distinct_or_of_and_bundles(bundles):
    rejected(schema.ExpectedClaim, {"id": "expected-1", "text": "Synthetic", "evidence_alternatives": bundles})


def test_expected_conditions_keep_raw_unresolved_scientific_language():
    text = "Pressure is not reported; do not infer ambient or zero GPa."
    value = schema.ExpectedCondition(field="pressure", raw_expectation=text, source_ids=["source-1"])
    assert value.raw_expectation == text
    rejected(schema.ExpectedCondition, {**value.model_dump(), "source_ids": ["source-1", "source-1"]})


@pytest.mark.parametrize("changes", [{"reviewer_kind": "verified_human"}, {"decision": "approved_truth"},
    {"case_sha256": " "}, {"reviewer_id": " "}, {"rationale": ""}, {"authenticated": True}])
def test_declared_review_is_not_authentication(changes):
    rejected(schema.CaseReview, {**case_review_payload(), **changes})


def test_two_review_resolution_is_explicit_and_does_not_erase_original_judgments():
    original = case_review_payload()
    value = {key: item for key, item in original.items() if key not in {"reviewer_id", "reviewer_kind"}}
    value.update(id="resolution-1", resolver_id="synthetic-resolver", resolver_kind="synthetic", review_ids=["review-1", "review-2"])
    assert schema.CaseResolution.model_validate(value).decision == "needs_revision"
    for refs in (["review-1"], ["review-1", "review-1"], ["review-1", "review-2", "review-3"]):
        rejected(schema.CaseResolution, {**value, "review_ids": refs})
    output = schema.OutputResolution.model_validate({**output_review_payload(), "review_ids": ["output-review-1", "output-review-2"]})
    assert output.reviewer_kind == "synthetic"  # inherited field means the resolver, never inferred authority


@pytest.mark.parametrize("changes", [{"latency_ms": -1}, {"latency_ms": True}, {"cost_usd": "0"},
    {"cost_usd": float("inf")}, {"input_tokens": True}, {"total_tokens": -1}, {"provider_fallback": 0},
    {"retrieved_source_ids": ["source-1"] * 301}, {"selected_source_ids": ["source-1", "source-1"]},
    {"request_sha256": "invalid"}, {"answer_sha256": "A" * 64}, {"answer": "\ud800"},
    {"answer": "超" * (128 * 1024 // 3 + 1)}], ids=lambda value: str(value)[:40])
def test_operational_observations_remain_strict_finite_and_unknown_not_zero(changes):
    rejected(schema.RunObservation, {**observation_payload(), **changes})


@pytest.mark.parametrize("changes", [{"start": True}, {"end": 0}, {"start": 9, "end": 9},
    {"citation_indices": [True]}, {"citation_indices": [0]}, {"citation_indices": [1, 1]},
    {"expected_claim_ids": ["expected-1", "expected-1"]}, {"status": "validated"}])
def test_atomic_output_claim_fields_do_not_coerce_numbers_or_duplicate_coverage(changes):
    rejected(schema.OutputClaimJudgment, {**labels_payload()["claims"][0], **changes})


@pytest.mark.parametrize("field", ["answer_claims_complete", "condition_match", "numerical_correct", "unit_correct", "refusal_correct"])
def test_output_judgment_never_coerces_truthy_scalars(field):
    rejected(schema.OutputLabels, {**labels_payload(), field: 1})


def test_raw_json_objects_remain_json_only_and_finite():
    run = package_payload()["runs"][0]
    for config in ([], {"nested": [float("inf")]}, {"nested": [float("nan")]}):
        rejected(schema.EvaluationRun, {**run, "config": config})
    with pytest.raises(ValidationError):
        schema.EvaluationRun.model_validate({**run, "config": {"set": {1, 2}}})


@pytest.mark.parametrize("field,count", [("cases", 201), ("case_reviews", 401), ("case_resolutions", 201), ("runs", 3)])
def test_top_level_inventory_limits_fail_before_crossreference_scoring(field, count):
    value = package_payload()
    value[field] = [{} for _ in range(count)]
    rejected(schema.ScientificEvaluationPackage, value)


def test_nested_models_are_revalidated_after_unsafe_model_copy():
    value = schema.ScientificEvaluationPackage.model_validate(package_payload())
    forged = value.protocol.model_copy(update={"target_question_count": True})
    with pytest.raises(ValidationError):
        schema.ScientificEvaluationPackage.model_validate({**value.model_dump(), "protocol": forged})
    binding = ScientificResultBinding.model_construct(paper_id=True)
    with pytest.warns(UserWarning, match="Pydantic serializer warnings"):
        with pytest.raises(ValidationError):
            schema.CapturedResult(id="result-1", binding=binding, raw_record={}, input_record_sha256=SHA)


def test_structural_validation_does_not_pretend_to_verify_crossreference_hashes():
    value = copy.deepcopy(package_payload())
    value["cases"][0]["expected"]["claims"][0]["evidence_alternatives"] = [["not-in-corpus"]]
    # The separate pure evaluator rejects this cross-reference. Shape alone
    # must never be presented as a verified run, real human review or gold set.
    result = schema.ScientificEvaluationPackage.model_validate(value)
    assert result.cases[0].expected.claims[0].evidence_alternatives == [["not-in-corpus"]]
