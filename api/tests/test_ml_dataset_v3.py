"""Pure v3 policy/propagation checks, not review authenticity or training proof.

Actual SQL capture and full compiler integration use the separate capture
fixtures. This file cannot manufacture a verified companion for the builder.
"""

from copy import deepcopy

import pytest

from models.ml_task_v2 import default_task_v2
from models.ml_task_v3 import REVIEW_POLICY, default_task_v3, validate_task_v3
from services.ml_dataset_builder_v3 import (
    MAX_HELD_REFERENCES,
    _account_review_holds,
    _check_review_receipt,
    _review_gate,
)


def ref(identifier):
    return ("event_properties", identifier)


def receipt(properties=("a", "b", "c"), inputs=("ia", "ib", "ic")):
    return {
        "version": "ml-feature-review-companion/1.0.0",
        "observation_semantics": "captured_not_live",
        "property_holds": {identifier: [] for identifier in properties},
        "input_source_holds": {identifier: [] for identifier in inputs},
        "property_pins": {
            identifier: {"table": "event_properties", "row_id": identifier, "row_sha256": "1" * 64}
            for identifier in properties
        },
        "input_pins": {
            identifier: {"table": "ml_example_inputs", "row_id": identifier, "row_sha256": "2" * 64}
            for identifier in inputs
        },
        "base_manifest_sha256": "3" * 64,
        "source_companion_sha256": "4" * 64,
        "review_companion_sha256": "5" * 64,
        "observation_sha256": "6" * 64,
        "authority": {
            "scientific_acceptance": False,
            "ml_training_approved": False,
            "public_release_authorized": False,
            "reviewer_authority_authenticated": False,
            "database_observation_authenticated": False,
            "live_source_rights_checked": False,
        },
    }


def index_for(value):
    return {
        (pin["table"], pin["row_id"]): {"row_sha256": pin["row_sha256"]}
        for key in ("property_pins", "input_pins")
        for pin in value[key].values()
    }


def test_v3_is_explicit_detached_policy_over_unchanged_v2_fields():
    old = default_task_v2()
    task = default_task_v3()
    value = validate_task_v3(task)
    assert value == task and value is not task and value["label_task"] is not task["label_task"]
    assert (
        value["version"] == "ml-task/3.0.0" and value["exact_result_review_policy"] == REVIEW_POLICY
    )
    assert {
        key: item
        for key, item in value.items()
        if key not in {"version", "task_id", "exact_result_review_policy"}
    } == {key: item for key, item in old.items() if key not in {"version", "task_id"}}
    value["label_task"]["task_id"] = "changed-detached-result"
    assert task["label_task"] == old["label_task"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "ml-task/2.0.0"),
        ("version", True),
        ("exact_result_review_policy", True),
        ("exact_result_review_policy", "accepted_only"),
        ("exact_result_review_policy", "negative_only/2.0.0"),
        ("task_id", "invalid id"),
        ("physical_features", {}),
        ("physical_features", [{"feature_key": "Tc"}]),
        ("structure_features", ["density_g_cm3"]),
        ("state_policy", "formula_match"),
        ("cohort_policy", "resplit_after_review"),
        ("information_regime", "post_outcome"),
        ("missingness", "global_impute"),
        ("label_task", {"scientific_acceptance": True}),
    ],
)
def test_v3_rejects_policy_and_inherited_science_weakening(field, value):
    task = default_task_v3()
    task[field] = value
    with pytest.raises(ValueError):
        validate_task_v3(task)


@pytest.mark.parametrize("value", [None, [], True, {}, {"version": "ml-task/3.0.0"}])
def test_v3_requires_complete_closed_task(value):
    with pytest.raises(ValueError):
        validate_task_v3(value)


def test_v3_refuses_extra_authority_field():
    task = default_task_v3()
    task["ml_training_approved"] = True
    with pytest.raises(ValueError):
        validate_task_v3(task)


def test_unreviewed_and_captured_accepted_without_holds_do_not_add_positive_authority():
    value = receipt()
    before = deepcopy(value)
    result = _review_gate(ref("a"), "ia", {ref("a"): set()}, {}, value)
    assert result == {"reason_codes": [], "held_properties": [], "held_source_inputs": []}
    assert value == before


def test_property_hold_is_exact_not_shared_material_event_run_or_review_batch():
    value = receipt()
    value["property_holds"]["a"] = ["exact_result_rejected"]
    dependencies = {ref("a"): set(), ref("b"): set()}
    held = _review_gate(ref("a"), "ia", dependencies, {}, value)
    sibling = _review_gate(ref("b"), "ib", dependencies, {}, value)
    assert "exact_result_review_held" in held["reason_codes"]
    assert held["held_properties"][0]["ref"] == list(ref("a"))
    assert sibling["reason_codes"] == []


def test_property_hold_propagates_through_full_explicit_ancestry():
    value = receipt()
    value["property_holds"]["a"] = ["exact_result_clarification_required"]
    result = _review_gate(ref("c"), "ic", {ref("c"): {ref("b")}, ref("b"): {ref("a")}}, {}, value)
    assert "dependency_exact_result_review_held" in result["reason_codes"]
    assert result["held_properties"] == [
        {
            "ref": list(ref("a")),
            "direct": False,
            "reason_codes": ["exact_result_clarification_required"],
            "row_sha256": "1" * 64,
        }
    ]


def test_twenty_first_property_cannot_escape_ancestry_review():
    names = [f"p{index}" for index in range(21)]
    value = receipt(properties=names, inputs=("input",))
    value["property_holds"][names[-1]] = ["scientific_subject_changed"]
    dependencies = {ref(left): {ref(right)} for left, right in zip(names, names[1:], strict=False)}
    result = _review_gate(ref(names[0]), "input", dependencies, {}, value)
    assert result["held_properties"][0]["ref"] == list(ref(names[-1]))


def test_source_hold_on_same_property_direct_input_a_does_not_exclude_b():
    value = receipt()
    value["input_source_holds"]["ia"] = ["feature_source_held"]
    sources = {ref("a"): ["ia", "ib"]}
    assert (
        "feature_source_review_held"
        in _review_gate(ref("a"), "ia", {}, sources, value)["reason_codes"]
    )
    assert _review_gate(ref("a"), "ib", {}, sources, value)["reason_codes"] == []


def test_ancestor_without_source_choice_edge_requires_all_declared_bindings_unheld():
    value = receipt()
    value["input_source_holds"]["ia"] = ["feature_source_held"]
    result = _review_gate(ref("c"), "ic", {ref("c"): {ref("a")}}, {ref("a"): ["ia", "ib"]}, value)
    assert "dependency_feature_source_held" in result["reason_codes"]
    assert result["held_source_inputs"] == [
        {
            "input_id": "ia",
            "ref": list(ref("a")),
            "direct": False,
            "reason_codes": ["feature_source_held"],
            "row_sha256": "2" * 64,
        }
    ]


def test_coordinate_source_ancestor_hold_reaches_dependent_property_not_siblings():
    value = receipt()
    value["input_source_holds"]["ia"] = ["feature_source_held"]
    structure = ("structure_records", "structure")
    result = _review_gate(ref("b"), "ib", {ref("b"): {structure}}, {structure: ["ia"]}, value)
    assert "dependency_feature_source_held" in result["reason_codes"]
    assert _review_gate(ref("c"), "ic", {}, {structure: ["ia"]}, value)["reason_codes"] == []


def test_cycle_walk_is_bounded_without_making_any_temporal_completeness_claim():
    value = receipt()
    value["property_holds"]["b"] = ["scientific_source_held"]
    dependencies = {ref("a"): {ref("b")}, ref("b"): {ref("a")}}
    result = _review_gate(ref("a"), "ia", dependencies, {}, value)
    assert len(result["held_properties"]) == 1
    assert "eligible" not in result and "dependency_complete" not in result


def test_repeated_shared_ancestor_audit_hits_total_bound_without_truncation():
    value = receipt()
    value["property_holds"]["a"] = ["exact_result_rejected"]
    shared = _review_gate(ref("b"), "ib", {ref("b"): {ref("a")}}, {}, value)
    count = 0
    for _ in range(MAX_HELD_REFERENCES):
        count = _account_review_holds(count, shared)
    assert count == MAX_HELD_REFERENCES and len(shared["held_properties"]) == 1
    with pytest.raises(ValueError, match="review_feature_audit_reference_limit"):
        _account_review_holds(count, shared)
    assert len(shared["held_properties"]) == 1


@pytest.mark.parametrize("missing", ["direct_input", "ancestor_property", "ancestor_input"])
def test_missing_mandatory_observation_refuses_not_silently_unreviewed(missing):
    value = receipt()
    if missing == "direct_input":
        del value["input_source_holds"]["ia"]
    if missing == "ancestor_property":
        del value["property_holds"]["b"]
    if missing == "ancestor_input":
        del value["input_source_holds"]["ib"]
    with pytest.raises(ValueError):
        _review_gate(ref("a"), "ia", {ref("a"): {ref("b")}}, {ref("b"): ["ib"]}, value)


def test_exact_receipt_pins_are_checked_again_at_compiler_boundary():
    value = receipt()
    _check_review_receipt(value, index_for(value), "3" * 64, "4" * 64, "5" * 64)


@pytest.mark.parametrize(
    "change",
    [
        "base",
        "source",
        "review",
        "observation",
        "authority",
        "empty_authority",
        "zero_authority",
        "version",
        "semantics",
        "missing_input",
        "extra_input",
        "pin_table",
        "pin_hash",
        "pin_row",
        "pin_extra",
        "missing_hold",
        "bool_code",
        "duplicate_codes",
    ],
)
def test_compiler_refuses_inconsistent_normalized_receipt(change):
    value = receipt()
    index = index_for(value)
    if change in {"base", "source", "review"}:
        key = {
            "base": "base_manifest_sha256",
            "source": "source_companion_sha256",
            "review": "review_companion_sha256",
        }[change]
        value[key] = "9" * 64
    if change == "observation":
        value["observation_sha256"] = True
    if change == "authority":
        value["authority"]["ml_training_approved"] = True
    if change == "empty_authority":
        value["authority"] = {}
    if change == "zero_authority":
        value["authority"]["ml_training_approved"] = 0
    if change == "version":
        value["version"] = "ml-feature-review-companion/2.0.0"
    if change == "semantics":
        value["observation_semantics"] = "current_authenticated"
    if change == "missing_input":
        del value["input_pins"]["ia"]
        del value["input_source_holds"]["ia"]
    if change == "extra_input":
        value["input_pins"]["extra"] = value["input_pins"]["ia"]
        value["input_source_holds"]["extra"] = []
    if change == "pin_table":
        value["property_pins"]["a"]["table"] = "material_claims"
    if change == "pin_hash":
        value["property_pins"]["a"]["row_sha256"] = "9" * 64
    if change == "pin_row":
        value["property_pins"]["a"]["row_id"] = "b"
    if change == "pin_extra":
        value["property_pins"]["a"]["accepted"] = True
    if change == "missing_hold":
        del value["property_holds"]["a"]
    if change == "bool_code":
        value["property_holds"]["a"] = [True]
    if change == "duplicate_codes":
        value["property_holds"]["a"] = ["held", "held"]
    with pytest.raises(ValueError):
        _check_review_receipt(value, index, "3" * 64, "4" * 64, "5" * 64)
