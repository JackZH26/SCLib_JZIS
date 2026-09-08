"""Offline evaluator integration on self-consistent synthetic captured objects."""
from __future__ import annotations

from copy import deepcopy

import pytest

from models.scientific_evaluation import ScientificEvaluationPackage
from services import scientific_evaluation as evaluator
from services.rag_evidence_contract import input_record_sha256
from tests.scientific_evaluation_fixtures import (
    RESOLUTION_AT,
    make_package,
    make_source,
    reseal,
    uid,
)


def rejected(value, code):
    with pytest.raises(evaluator.ScientificEvaluationError, match="^" + code + "$"):
        evaluator.validate_package(value)


def first_output(value, arm=0):
    return value["runs"][arm]["observations"][0]


def revise_claims(observation, **changes):
    for review in observation["judgments"]:
        review["labels"]["claims"][0].update(changes)


def test_self_consistent_complete_synthetic_package_never_becomes_real_gold_or_release():
    value = make_package()
    assert make_package() == value
    audit = evaluator.validate_package(value)
    assert audit["status"] == "structurally_consistent"
    assert audit["integrity_scope"] == "declared_portable_objects_only"
    assert audit["counts"]["cases"] == 3 and audit["counts"]["sources"] == 4 and audit["counts"]["results"] == 1
    assert audit["declared_case_decisions"] == {"accept": 3}
    assert audit["split_audit"]["declared_component_count"] == 2
    for key in ("scientific_acceptance", "release_authorized", "reviewer_authority_authenticated", "source_roots_authenticated",
                "catalogue_bindings_authenticated", "execution_authenticated", "preregistration_authenticated", "ann_replay_available"):
        assert audit[key] is False
    assert "synthetic_development_only" in audit["release_blockers"] and "target_coverage_not_met" in audit["release_blockers"]
    assert evaluator.validate_package(ScientificEvaluationPackage.model_validate(value)) == audit
    paired = evaluator.compare_package(value)
    assert paired["comparison"]["paired"]["baseline_run_id"] == "run-baseline"
    assert paired["comparison"]["paired"]["candidate_run_id"] == "run-candidate"
    assert paired["comparison"]["arms"]["run-candidate"]["splits"]["all"]["operations"]["cost_usd"]["complete_total"] is None


def test_unexecuted_protocol_is_valid_inventory_but_cannot_be_compared():
    value = make_package(runs=False)
    assert evaluator.validate_package(value)["counts"]["runs"] == 0
    with pytest.raises(evaluator.ScientificEvaluationError, match="paired_runs_required"):
        evaluator.compare_package(value)


@pytest.mark.parametrize("field", ["text", "vector_sha256", "vector_id", "manifest", "profile", "resource"])
def test_captured_generation_and_source_bytes_are_checked_not_only_declared_counts(field):
    value = make_package()
    source = value["corpus"]["sources"][0]
    if field == "text":
        source["text"] += " Tampered scientific context."
        code = "source_content_mismatch"
    elif field == "vector_sha256":
        source[field] = "f" * 64
        code = "incomplete_generation_manifest"
    elif field == "vector_id":
        source[field] = "ig62_" + uid("other-generation").replace("-", "") + "_" + "f" * 64
        code = "source_generation_mismatch"
    elif field == "manifest":
        value["corpus"]["generation"]["manifest_sha256"] = "f" * 64
        code = "incomplete_generation_manifest"
    elif field == "profile":
        value["corpus"]["index_profile"]["model"] = "invented-model"
        code = "unsupported_index_profile"
    else:
        value["corpus"]["index_resource"]["feature_norm"] = "UNIT_L2_NORM"
        code = "unsupported_index_resource"
    rejected(value, code)


def test_declared_manifest_cannot_omit_one_untampered_source():
    value = make_package()
    value["corpus"]["sources"].pop()
    rejected(value, "incomplete_generation_manifest")


@pytest.mark.parametrize("kind", ["paper", "work", "root", "capture_hash", "capture_id", "query_group", "query", "full_text"])
def test_related_question_components_cannot_cross_development_and_heldout(kind):
    value = make_package(runs=False)
    first, last = value["corpus"]["sources"][0], value["corpus"]["sources"][-1]
    if kind == "paper":
        last["paper_id"], last["work_id"] = first["paper_id"], first["work_id"]
    elif kind == "work":
        last["work_id"] = first["work_id"]
    elif kind == "root":
        last["root_id"] = first["root_id"]
    elif kind == "capture_hash":
        last["capture_sha256"] = first["capture_sha256"]
    elif kind == "capture_id":
        last["capture_sha256"] = first["capture_sha256"] = None
        last["evidence_provenance"]["source_capture_id"] = first["evidence_provenance"]["source_capture_id"]
    elif kind == "query_group":
        value["cases"][-1]["query_group_id"] = value["cases"][0]["query_group_id"]
    elif kind == "query":
        value["cases"][-1]["query"] = "  " + value["cases"][0]["query"] + "\n"
    else:
        last["text"] = first["text"]
        last["evidence_provenance"]["content_sha256"] = first["evidence_provenance"]["content_sha256"]
    rejected(reseal(value), "split_component_overlap")


@pytest.mark.parametrize("two_bridges", [False, True])
def test_unreferenced_corpus_sources_connect_split_graph_transitively(two_bridges):
    value = make_package(runs=False)
    first, last = value["corpus"]["sources"][0], value["corpus"]["sources"][-1]
    bridge = make_source("bridge-c", "c")
    bridge["work_id"] = first["work_id"]
    if two_bridges:
        other = make_source("bridge-d", "d")
        bridge["root_id"] = other["root_id"] = "synthetic-bridge-root"
        other["work_id"] = last["work_id"]
        value["corpus"]["sources"].append(other)
    else:
        bridge["root_id"] = last["root_id"]
    value["corpus"]["sources"].append(bridge)
    rejected(reseal(value), "split_component_overlap")


def test_missing_root_stays_explicitly_unresolved_not_inferred_from_work():
    value = make_package(runs=False)
    for source in value["corpus"]["sources"]:
        source["root_id"] = None
    audit = evaluator.validate_package(reseal(value))
    assert audit["split_audit"]["cases_with_missing_root_links"] == 3
    assert audit["source_roots_authenticated"] is False


def test_repeated_parent_rendering_and_forged_root_labels_do_not_create_new_evidence():
    value = make_package(runs=False)
    source = deepcopy(value["corpus"]["sources"][2])
    source.update(id="alias-derived", paper_id="synthetic:alias", work_id=uid("alias-work"), root_id="synthetic-other-root",
                  capture_sha256=None, vector_id="ig62_" + uid("generation").replace("-", "") + "_" + "e" * 64)
    source["evidence_provenance"].update(evidence_revision_id=uid("alias-evidence"), source_capture_id=None,
        content_sha256=evaluator.text_digest("Synthetic differently rendered same parent."))
    source["text"] = "Synthetic differently rendered same parent."
    value["corpus"]["sources"].append(source)
    value["cases"][-1]["expected"]["conditions"] = [{"field": "other", "raw_expectation": "Same declared extraction parent", "source_ids": [source["id"]]}]
    rejected(reseal(value), "split_component_overlap")


@pytest.mark.parametrize("change", ["raw_bytes", "rehash_raw", "parent_id", "binding_content", "binding_paper"])
def test_derived_result_is_bound_to_its_entire_actual_raw_parent(change):
    value = make_package()
    result = value["corpus"]["results"][0]
    if change in {"raw_bytes", "rehash_raw"}:
        result["raw_record"]["tc_kelvin"] = "99 K"
        if change == "rehash_raw":
            result["input_record_sha256"] = input_record_sha256(result["raw_record"])
        code = "raw_record_mismatch" if change == "raw_bytes" else "raw_parent_identity_mismatch"
    elif change == "parent_id":
        result["binding"]["parent_result_revision_id"] = uid("not-actual-parent")
        code = "result_evidence_mismatch"
    elif change == "binding_content":
        result["binding"]["content_sha256"] = "f" * 64
        code = "result_evidence_mismatch"
    else:
        result["binding"]["paper_id"] = "synthetic:other"
        code = "result_source_mismatch"
    rejected(reseal(value), code)


def test_derived_fact_cannot_be_expected_original_support():
    value = make_package()
    value["cases"][0]["expected"]["claims"][0]["evidence_alternatives"] = [["a-derived"]]
    rejected(reseal(value), "derived_extraction_is_not_original_support")


def test_support_judgment_must_include_an_entire_expected_complementary_bundle():
    value = make_package()
    observation = first_output(value)
    observation["answer"] = "Synthetic incomplete method-only evidence [1]."
    revise_claims(observation, end=len(observation["answer"]), citation_indices=[1], source_ids=["a-methods"])
    rejected(reseal(value), "incomplete_judged_support_bundle")


@pytest.mark.parametrize("change", ["derived", "restricted", "stale"])
def test_positive_output_support_cannot_cite_derived_restricted_or_stale_text(change):
    value = make_package()
    if change == "derived":
        observation = first_output(value)
        observation["selected_source_ids"] = observation["retrieved_source_ids"] = ["a-derived"]
        observation["answer"] = "Synthetic derived assertion [1]."
        revise_claims(observation, end=len(observation["answer"]), source_ids=["a-derived"], citation_indices=[1], expected_claim_ids=[])
    else:
        value["corpus"]["sources"][0]["evidence_provenance"]["permission_status" if change == "restricted" else "currentness"] = change
    rejected(reseal(value), "nonoriginal_positive_support")


def test_disagreement_is_not_silently_accepted_and_distinct_resolution_is_bound():
    value = make_package()
    value["case_reviews"][1]["decision"] = "reject"
    value = reseal(value)
    audit = evaluator.validate_package(value)
    assert audit["declared_case_decisions"] == {"accept": 2, "disputed": 1}
    first, second = value["case_reviews"][:2]
    resolution = {key: first[key] for key in ("case_id", "case_sha256", "protocol_sha256", "corpus_sha256")}
    resolution.update(id="case-resolution", review_ids=[first["id"], second["id"]], resolver_id="synthetic-resolver", resolver_kind="synthetic",
        submitted_at=RESOLUTION_AT, decision="accept", rationale="Synthetic conflict resolution fixture only.")
    value["case_resolutions"] = [resolution]
    assert evaluator.validate_package(reseal(value))["declared_case_decisions"] == {"accept": 3}
    value["case_resolutions"][0]["resolver_id"] = first["reviewer_id"]
    rejected(reseal(value), "resolver_not_distinct")


@pytest.mark.parametrize("change", ["same_reviewer", "wrong_context", "unreviewed", "output_disagrees"])
def test_review_inventory_preserves_independent_declared_judgments_and_exact_context(change):
    value = make_package()
    if change == "same_reviewer":
        value["case_reviews"][1]["reviewer_id"] = value["case_reviews"][0]["reviewer_id"]
        rejected(value, "nonindependent_reviewer_alias")
    elif change == "wrong_context":
        value["case_reviews"][0]["corpus_sha256"] = "f" * 64
        rejected(value, "review_context_mismatch")
    elif change == "unreviewed":
        value["case_reviews"].pop(0)
        assert evaluator.validate_package(value)["declared_case_decisions"] == {"accept": 2, "unreviewed": 1}
    else:
        first_output(value)["judgments"][1]["labels"]["condition_match"] = "incorrect"
        package, _, _, labels = evaluator._validate(reseal(value))
        assert labels[package.runs[0].id][package.cases[0].id] is None


def test_output_resolution_preserves_prior_judgments_and_exact_observation_hash():
    value = make_package()
    observation = first_output(value)
    observation["judgments"][1]["labels"]["condition_match"] = "incorrect"
    resolution = deepcopy(observation["judgments"][0])
    resolution.update(id="output-resolution", reviewer_id="synthetic-output-resolver", submitted_at=RESOLUTION_AT,
                      review_ids=[item["id"] for item in observation["judgments"]])
    observation["resolution"] = resolution
    value = reseal(value)
    assert evaluator._validate(value)[3]["run-baseline"]["case-methods"].condition_match == "correct"
    first_output(value)["resolution"]["observation_sha256"] = "f" * 64
    rejected(value, "output_review_binding_mismatch")


@pytest.mark.parametrize("change", ["missing_case", "missing_arm", "wrong_dataset", "mutated_answer"])
def test_two_arms_cannot_compare_intersections_or_reuse_stale_output_judgments(change):
    value = make_package()
    if change == "missing_case":
        value["runs"][0]["observations"].pop()
        rejected(value, "incomplete_run_inventory")
    elif change == "missing_arm":
        value["runs"].pop()
        with pytest.raises(evaluator.ScientificEvaluationError, match="paired_runs_required"):
            evaluator.compare_package(value)
    elif change == "wrong_dataset":
        value["runs"][1]["dataset_sha256"] = "f" * 64
        rejected(value, "run_frozen_objects_mismatch")
    else:
        first_output(value)["answer"] += " Unreviewed content."
        rejected(value, "answer_content_mismatch")


@pytest.mark.parametrize("fault", ["omit_citation", "out_of_range", "grouped", "leading_zero", "citation_only", "overlap", "outside_answer"])
def test_output_claim_spans_and_citation_inventory_must_be_complete(fault):
    value = make_package()
    observation = first_output(value)
    if fault == "omit_citation":
        revise_claims(observation, citation_indices=[1], source_ids=["a-methods"])
        code = "judgment_citation_inventory_mismatch"
    elif fault in {"out_of_range", "grouped", "leading_zero"}:
        observation["answer"] = "Synthetic assertion " + {"out_of_range": "[999].", "grouped": "[1,2].", "leading_zero": "[01]."}[fault]
        revise_claims(observation, end=len(observation["answer"]), citation_indices=[], source_ids=[], status="undetermined")
        code = "malformed_judged_citation"
    elif fault == "citation_only":
        observation["answer"] = "[1]"
        revise_claims(observation, end=3, citation_indices=[1], source_ids=["a-methods"], expected_claim_ids=[])
        code = "citation_only_claim_span"
    elif fault == "overlap":
        for review in observation["judgments"]:
            review["labels"]["claims"].append({**review["labels"]["claims"][0], "id": "overlapping-claim"})
        code = "overlapping_output_claims"
    else:
        revise_claims(observation, end=len(observation["answer"]) + 1)
        code = "invalid_claim_span"
    rejected(reseal(value), code)
