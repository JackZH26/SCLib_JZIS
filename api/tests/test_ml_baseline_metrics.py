"""Synthetic numerical/accounting tests, never a scientific benchmark."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from decimal import Decimal

import pytest

from services import ml_baseline_metrics as metrics


def record(
    index=1,
    *,
    truth=39.0,
    prediction=40.0,
    failure=None,
    split="test",
    family="synthetic",
    pressure_state="explicit_ambient",
    pressure_gpa=0.0,
    group=None,
):
    return {
        "example_id": f"synthetic-example-{index}",
        "group_id": group or hashlib.sha256(f"group:{index}".encode()).hexdigest(),
        "assignment_sha256": hashlib.sha256(f"assignment:{index}:{split}".encode()).hexdigest(),
        "split": split,
        "family": family,
        "pressure_state": pressure_state,
        "pressure_gpa": pressure_gpa,
        "label": {
            "value": truth,
            "unit": "K",
            "tc_definition": "zero_resistance",
            "knowledge_origin": "Observed",
            "value_relation": "exact",
        },
        "prediction_k": prediction,
        "failure_reason": failure,
    }


def split_summary(report, name="test"):
    return next(item for item in report["by_split"] if item["split"] == name)


def test_full_requested_denominator_and_unclipped_negative_predictions():
    rows = [
        record(1, truth=2, prediction=-2),
        record(2, truth=3, prediction=4),
        record(3, prediction=None, failure="prediction_nonfinite_features"),
    ]
    report = metrics.score_predictions(rows)
    summary = report["summary"]
    assert summary == {
        "requested_count": 3,
        "predicted_count": 2,
        "failed_count": 1,
        "prediction_coverage": 2 / 3,
        "metric_status": "scored",
        "mae_k": 2.5,
        "median_absolute_error_k": 2.5,
        "declared_component_count": 3,
        "successful_component_count": 2,
        "failure_reason_counts": {"prediction_nonfinite_features": 1},
        "failed_example_ids": ["synthetic-example-3"],
    }
    assert report["metric_unit"] == "K"
    assert report["tc_definition"] == "zero_resistance"
    assert report["prediction_policy"] == "finite_unclipped_kelvin"
    assert rows[0]["prediction_k"] == -2
    assert report["uncertainty"] is None
    assert report["independent_support_count"] is None
    assert set(report["authority"]) == set(metrics.AUTHORITY)
    assert all(value is False for value in report["authority"].values())


@pytest.mark.parametrize(
    "errors,expected_mae,expected_median",
    [
        ([1], 1.0, 1.0),
        ([4, 1, 2], 7 / 3, 2),
        ([4, 1, 2, 9], 4.0, 3.0),
        ([0, 0, 0], 0.0, 0.0),
        ([1e308] * 3, 1e308, 1e308),
    ],
)
def test_exact_deterministic_mean_median_without_sum_overflow(
    errors, expected_mae, expected_median
):
    rows = [
        record(index, truth=max(value, 1), prediction=0 if value else 1)
        for index, value in enumerate(errors)
    ]
    report = metrics.score_predictions(rows)
    assert report["summary"]["mae_k"] == expected_mae
    assert report["summary"]["median_absolute_error_k"] == expected_median
    assert metrics.score_predictions(list(reversed(rows))) == report


def test_subnormal_errors_not_lost_by_dividing_each_summand():
    rows = [record(index, truth=5e-324, prediction=0.0) for index in range(3)]
    report = metrics.score_predictions(rows)
    assert report["summary"]["mae_k"] == 5e-324
    assert report["summary"]["median_absolute_error_k"] == 5e-324


@pytest.mark.parametrize(
    "rows,status,coverage",
    [
        ([], "no_requested_rows", None),
        ([record(prediction=None, failure="no_candidate_selected")], "no_predictions", 0.0),
    ],
)
def test_no_metric_is_not_a_zero_error_claim(rows, status, coverage):
    report = metrics.score_predictions(rows)
    assert report["summary"]["metric_status"] == status
    assert report["summary"]["mae_k"] is None
    assert report["summary"]["median_absolute_error_k"] is None
    assert report["summary"]["prediction_coverage"] == coverage
    assert report["tc_definition"] == ("zero_resistance" if rows else None)
    for item in report["by_split"]:
        assert (
            sum(row["summary"]["requested_count"] for row in item["by_pressure"])
            == item["summary"]["requested_count"]
        )


def test_split_family_pressure_and_component_denominators_remain_complete():
    group = "a" * 64
    rows = [
        record(1, split="train", family=None),
        record(2, split="validation", family="unknown"),
        record(3, group=group, pressure_state="not_reported", pressure_gpa=None),
        record(
            4,
            group=group,
            pressure_state="ambiguous",
            pressure_gpa=0,
            prediction=None,
            failure="arm_no_training_features",
        ),
    ]
    report = metrics.score_predictions(rows)
    assert [item["summary"]["requested_count"] for item in report["by_split"]] == [1, 1, 2]
    assert split_summary(report, "train")["by_family"][0]["family"] is None
    assert split_summary(report, "validation")["by_family"][0]["family"] == "unknown"
    selected = split_summary(report)
    assert selected["summary"]["declared_component_count"] == 1
    assert selected["by_component"] == [{"group_id": group, "summary": selected["summary"]}]
    strata = {row["stratum"]: row["summary"] for row in selected["by_pressure"]}
    assert strata["not_reported"]["requested_count"] == 1
    assert strata["ambiguous"]["failed_count"] == 1
    assert strata["explicit_ambient"]["requested_count"] == 0
    for selected in report["by_split"]:
        for dimension in ("by_family", "by_pressure", "by_component"):
            assert (
                sum(row["summary"]["requested_count"] for row in selected[dimension])
                == selected["summary"]["requested_count"]
            )
            assert (
                sum(row["summary"]["failed_count"] for row in selected[dimension])
                == selected["summary"]["failed_count"]
            )


@pytest.mark.parametrize(
    "state,value,stratum",
    [
        ("explicit_ambient", 0, "explicit_ambient"),
        ("reported", 0, "reported_zero"),
        ("reported", 5e-324, "reported_0_to_10_gpa"),
        ("reported", 9.999, "reported_0_to_10_gpa"),
        ("reported", 10, "reported_10_to_100_gpa"),
        ("reported", 99.99, "reported_10_to_100_gpa"),
        ("reported", 100, "reported_ge_100_gpa"),
        ("reported", 1e308, "reported_ge_100_gpa"),
        ("not_reported", None, "not_reported"),
        ("ambiguous", None, "ambiguous"),
        ("ambiguous", 0, "ambiguous"),
        ("ambiguous", 100, "ambiguous"),
    ],
)
def test_pressure_exact_boundaries_preserve_unknown_and_source_state(state, value, stratum):
    report = metrics.score_predictions([record(pressure_state=state, pressure_gpa=value)])
    nonempty = [
        item["stratum"]
        for item in split_summary(report)["by_pressure"]
        if item["summary"]["requested_count"]
    ]
    assert nonempty == [stratum]
    assert report["pressure_strata_version"] == metrics.PRESSURE_STRATA_VERSION
    assert report["pressure_basis"] == "supplied_pressure_state_and_value_no_imputation"


def test_input_and_returned_documents_are_detached_with_exact_input_hash():
    rows = [record(2), record(1, family="硼化物")]
    before = deepcopy(rows)
    detached = metrics.validate_prediction_records(rows)
    report = metrics.score_predictions(rows)
    payload = json.dumps(
        detached, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()
    assert report["records_sha256"] == hashlib.sha256(payload).hexdigest()
    detached[0]["label"]["value"] = 999
    report["authority"]["scientific_acceptance"] = True
    assert rows == before
    assert metrics.AUTHORITY["scientific_acceptance"] is False
    assert metrics.score_predictions(rows)["authority"]["scientific_acceptance"] is False


@pytest.mark.parametrize("failure", sorted(metrics.FAILURE_REASONS))
def test_all_controlled_failures_remain_in_denominator(failure):
    summary = metrics.score_predictions([record(prediction=None, failure=failure)])["summary"]
    assert summary["requested_count"] == summary["failed_count"] == 1
    assert summary["prediction_coverage"] == 0
    assert summary["failure_reason_counts"] == {failure: 1}


def replace(row, key, value):
    if key.startswith("label."):
        row["label"][key.split(".")[1]] = value
    else:
        row[key] = value
    return row


@pytest.mark.parametrize(
    "key,value",
    [
        ("label.value", 0),
        ("label.value", -1),
        ("label.value", True),
        ("label.value", None),
        ("label.value", float("inf")),
        ("label.value", float("nan")),
        ("label.value", Decimal("39")),
        ("label.value", 10**1000),
        ("label.unit", "C"),
        ("label.unit", "mK"),
        ("label.knowledge_origin", "Computed"),
        ("label.value_relation", "less_than"),
        ("label.value_relation", "not_detected"),
        ("label.tc_definition", "unknown"),
        ("prediction_k", True),
        ("prediction_k", float("inf")),
        ("prediction_k", float("nan")),
        ("prediction_k", Decimal("40")),
        ("prediction_k", "40"),
        ("prediction_k", None),
        ("failure_reason", "prediction_nonfinite_features"),
        ("failure_reason", "secret raw failure"),
        ("pressure_state", "unknown"),
        ("pressure_gpa", -1),
        ("pressure_gpa", False),
        ("pressure_gpa", float("inf")),
        ("pressure_gpa", None),
        ("family", ""),
        ("family", " x"),
        ("family", "x\nsecret"),
        ("family", "a" * 51),
        ("family", True),
        ("family", "\ud800"),
        ("split", "holdout"),
        ("split", True),
        ("example_id", ""),
        ("example_id", "x" * 201),
        ("example_id", "/private/x"),
        ("group_id", "a" * 63),
        ("group_id", "A" * 64),
        ("assignment_sha256", None),
        ("new_field", True),
        ("label.new_field", True),
    ],
)
def test_closed_strict_finite_supported_record_boundary(key, value):
    row = replace(record(), key, value)
    for function in (metrics.validate_prediction_records, metrics.score_predictions):
        with pytest.raises(metrics.MlBaselineMetricsError):
            function([row])


@pytest.mark.parametrize(
    "state,value", [("explicit_ambient", 1), ("reported", None), ("not_reported", 0)]
)
def test_pressure_state_value_mismatch_cannot_be_reinterpreted(state, value):
    with pytest.raises(metrics.MlBaselineMetricsError, match="pressure_invalid"):
        metrics.score_predictions([record(pressure_state=state, pressure_gpa=value)])


def test_duplicate_missing_subclass_and_limit_refused():
    class Hidden(dict):
        pass

    missing = record()
    del missing["failure_reason"]
    for rows in (
        [record(), record()],
        [missing],
        [Hidden(record())],
        tuple([record()]),
        [record(index) for index in range(metrics.MAX_RECORDS + 1)],
    ):
        with pytest.raises(metrics.MlBaselineMetricsError):
            metrics.score_predictions(rows)


def test_declared_group_cannot_cross_partitions():
    with pytest.raises(metrics.MlBaselineMetricsError, match="partition_crossing"):
        metrics.score_predictions(
            [record(1, group="a" * 64, split="train"), record(2, group="a" * 64)]
        )


def test_unrepresentable_finite_error_refuses_complete_report():
    with pytest.raises(metrics.MlBaselineMetricsError):
        metrics.score_predictions([record(truth=1e308, prediction=-1e308)])


def test_report_byte_budget_is_fail_closed(monkeypatch):
    monkeypatch.setattr(metrics, "MAX_REPORT_BYTES", 1000)
    with pytest.raises(metrics.MlBaselineMetricsError, match="byte_limit"):
        metrics.score_predictions([record()])


def test_maximum_record_inventory_has_no_truncation():
    rows = [record(index, family=f"family-{index}") for index in range(metrics.MAX_RECORDS)]
    report = metrics.score_predictions(rows)
    assert report["summary"]["requested_count"] == metrics.MAX_RECORDS
    assert len(split_summary(report)["by_component"]) == metrics.MAX_RECORDS
    assert len(split_summary(report)["by_family"]) == metrics.MAX_RECORDS
    assert len(json.dumps(report).encode()) < metrics.MAX_REPORT_BYTES


def test_same_rows_pairing_and_failure_intersection_are_explicit():
    left = [
        record(1, truth=10, prediction=12),
        record(2, prediction=None, failure="prediction_nonfinite_features"),
        record(3, truth=10, prediction=11),
    ]
    right = deepcopy(left)
    right[0]["prediction_k"] = 9
    right[1].update(prediction_k=40, failure_reason=None)
    right[2].update(prediction_k=None, failure_reason="prediction_nonfinite_arithmetic")
    report = metrics.compare_prediction_arms(left, right)
    assert report["relationship"] == "same_rows"
    assert report["common_requested_count"] == 3
    assert (
        report["left_summary"]["requested_count"] == report["right_summary"]["requested_count"] == 3
    )
    assert report["successful_common_example_ids"] == ["synthetic-example-1"]
    assert report["common_prediction_failures"] == [
        {
            "example_id": "synthetic-example-2",
            "left_failure_reason": "prediction_nonfinite_features",
            "right_failure_reason": None,
        },
        {
            "example_id": "synthetic-example-3",
            "left_failure_reason": None,
            "right_failure_reason": "prediction_nonfinite_arithmetic",
        },
    ]
    assert report["paired_metrics"] == {
        "successful_common_count": 1,
        "left_mae_k": 2.0,
        "right_mae_k": 1.0,
        "left_median_absolute_error_k": 2.0,
        "right_median_absolute_error_k": 1.0,
        "mae_delta_right_minus_left_k": -1.0,
        "median_absolute_error_delta_right_minus_left_k": -1.0,
    }
    assert report["comparison_scope"] == "common_successful_rows_descriptive_not_causal"
    assert report["significance"] is None
    assert report["causal_feature_effect_established"] is False
    assert report["independent_support_count"] is None
    assert all(value is False for value in report["authority"].values())


@pytest.mark.parametrize(
    "left_ids,right_ids,relationship",
    [
        ([1, 2], [1, 2], "same_rows"),
        ([1], [1, 2], "left_nested_subset"),
        ([1, 2], [1], "right_nested_subset"),
        ([1, 2], [2, 3], "overlap_not_nested"),
        ([1], [2], "disjoint"),
        ([], [], "same_rows"),
        ([], [1], "left_nested_subset"),
    ],
)
def test_nested_and_nonpaired_cohorts_not_mislabeled_as_full_paired(
    left_ids, right_ids, relationship
):
    report = metrics.compare_prediction_arms(
        [record(index) for index in left_ids], [record(index) for index in right_ids]
    )
    assert report["relationship"] == relationship
    assert report["common_requested_example_ids"] == [
        f"synthetic-example-{index}" for index in sorted(set(left_ids) & set(right_ids))
    ]
    assert report["left_only_example_ids"] == [
        f"synthetic-example-{index}" for index in sorted(set(left_ids) - set(right_ids))
    ]
    assert report["right_only_example_ids"] == [
        f"synthetic-example-{index}" for index in sorted(set(right_ids) - set(left_ids))
    ]
    assert report["causal_feature_effect_established"] is False
    if not set(left_ids) & set(right_ids):
        assert report["paired_metrics"] is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("group_id", "0" * 64),
        ("assignment_sha256", "0" * 64),
        ("label.value", 40),
        ("label.value", 39),
        ("family", "other"),
        ("pressure_state", "reported"),
    ],
)
def test_cross_arm_changed_binding_or_task_assignment_is_not_paired(key, value):
    left = [record()]
    right = [replace(deepcopy(left[0]), key, value)]
    with pytest.raises(metrics.MlBaselineMetricsError, match="binding_mismatch"):
        metrics.compare_prediction_arms(left, right)


@pytest.mark.parametrize("method", ["score", "validate", "compare"])
def test_distinct_tc_criteria_never_silently_pooled(method):
    first, second = record(1), record(2)
    second["label"]["tc_definition"] = "onset"
    with pytest.raises(metrics.MlBaselineMetricsError, match="mixed_tc_criteria"):
        if method == "score":
            metrics.score_predictions([first, second])
        elif method == "validate":
            metrics.validate_prediction_records([first, second])
        else:
            # Even disjoint IDs cannot make different estimands comparable.
            metrics.compare_prediction_arms([first], [second])


def test_empty_arm_does_not_erase_other_arms_explicit_criterion():
    report = metrics.compare_prediction_arms([], [record()])
    assert report["tc_definition"] == "zero_resistance"
    assert metrics.compare_prediction_arms([], [])["tc_definition"] is None


def test_cross_arm_partition_mismatch_even_without_shared_example_ids():
    left = [record(1, split="train", group="a" * 64)]
    right = [record(2, split="test", group="a" * 64)]
    with pytest.raises(metrics.MlBaselineMetricsError, match="partition_mismatch"):
        metrics.compare_prediction_arms(left, right)


def test_comparator_validates_shared_non_test_bindings_too():
    left = [record(1, split="train"), record(2)]
    right = deepcopy(left)
    right[0]["assignment_sha256"] = "0" * 64
    with pytest.raises(metrics.MlBaselineMetricsError, match="binding_mismatch"):
        metrics.compare_prediction_arms(left, right)


def test_no_joint_predictions_is_not_a_zero_difference():
    left = [record(prediction=None, failure="no_candidate_selected")]
    right = [record()]
    report = metrics.compare_prediction_arms(left, right)
    assert report["paired_metrics"] is None
    assert report["successful_common_example_ids"] == []
    assert report["common_requested_count"] == 1
    assert report["left_summary"]["prediction_coverage"] == 0
    assert report["right_summary"]["prediction_coverage"] == 1


def test_split_scoped_comparison_is_deterministic_and_preserves_whole_record_pins():
    rows = [record(3), record(1, split="train"), record(2, split="validation")]
    before = deepcopy(rows)
    report = metrics.compare_prediction_arms(rows, deepcopy(rows), split="validation")
    assert report["common_requested_example_ids"] == ["synthetic-example-2"]
    assert report["left_records_sha256"] == metrics.score_predictions(rows)["records_sha256"]
    assert metrics.compare_prediction_arms(list(reversed(rows)), rows, split="validation") == report
    report["common_requested_example_ids"].clear()
    assert rows == before


@pytest.mark.parametrize("split", ["all", "holdout", True, None, 1])
def test_unknown_comparison_partition_rejects(split):
    with pytest.raises(metrics.MlBaselineMetricsError, match="split_invalid"):
        metrics.compare_prediction_arms([record()], [record()], split=split)


def test_errors_never_echo_private_values():
    row = record(family="secret source\nprivate token=abc")
    for function in (
        metrics.score_predictions,
        lambda rows: metrics.compare_prediction_arms(rows, rows),
    ):
        with pytest.raises(metrics.MlBaselineMetricsError) as caught:
            function([row])
        assert "secret" not in str(caught.value)
        assert "private" not in str(caught.value)
