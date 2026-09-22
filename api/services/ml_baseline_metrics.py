"""Descriptive Kelvin errors for exact positive Observed Tc predictions.

This pure helper does not authenticate labels, authorize fitting, infer source
rights, or establish independent experiments. The coordinator must first verify
the pinned dataset. Failed predictions remain in every requested denominator;
finite negative predictions are neither clipped nor interpreted as observations.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from fractions import Fraction

VERSION = "ml-baseline-metrics/1.0.0"
PRESSURE_STRATA_VERSION = "reported-pressure-strata/1.0.0"
MAX_RECORDS = 100
MAX_REPORT_BYTES = 2 * 1024 * 1024
PARTITIONS = ("train", "validation", "test")
FAILURE_REASONS = frozenset(
    {
        "prediction_nonfinite_features",
        "prediction_nonfinite_arithmetic",
        "no_candidate_selected",
        "arm_no_training_features",
    }
)
AUTHORITY = {
    "scientific_acceptance": False,
    "public_release": False,
    "ml_training_approved": False,
    "reviewer_authority_authenticated": False,
    "live_source_rights_checked": False,
    "external_dependency_completeness_proven": False,
}
UNCERTAINTY_REASONS = ["independent_experimental_units_not_established", "descriptive_metrics_only"]
PRESSURE_STRATA = (
    "explicit_ambient",
    "reported_zero",
    "reported_0_to_10_gpa",
    "reported_10_to_100_gpa",
    "reported_ge_100_gpa",
    "not_reported",
    "ambiguous",
)
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+@/-]{0,199}\Z")
_RECORD_FIELDS = {
    "example_id",
    "group_id",
    "assignment_sha256",
    "split",
    "family",
    "pressure_state",
    "pressure_gpa",
    "label",
    "prediction_k",
    "failure_reason",
}
_LABEL_FIELDS = {"value", "unit", "tc_definition", "knowledge_origin", "value_relation"}
_BINDING_FIELDS = tuple(sorted(_RECORD_FIELDS - {"prediction_k", "failure_reason"}))


class MlBaselineMetricsError(ValueError):
    """Static bounded error; private identities/labels are never echoed."""


def _require(condition, code="ml_baseline_metrics_invalid"):
    if not condition:
        raise MlBaselineMetricsError(code)


def _canonical(value):
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    _require(len(raw) <= MAX_REPORT_BYTES, "ml_baseline_metrics_byte_limit")
    return raw


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _number(value):
    return type(value) in {int, float} and math.isfinite(value)


def _records(records):
    _require(
        type(records) is list and len(records) <= MAX_RECORDS, "ml_baseline_metrics_record_limit"
    )
    identifiers, group_splits = set(), {}
    for row in records:
        _require(
            type(row) is dict and len(row) == len(_RECORD_FIELDS) and set(row) == _RECORD_FIELDS
        )
        identifier = row["example_id"]
        _require(
            type(identifier) is str and _ID.fullmatch(identifier) and identifier not in identifiers,
            "ml_baseline_metrics_identity_invalid",
        )
        identifiers.add(identifier)
        for key in ("group_id", "assignment_sha256"):
            _require(
                type(row[key]) is str and _HASH.fullmatch(row[key]),
                "ml_baseline_metrics_identity_invalid",
            )
        _require(type(row["split"]) is str and row["split"] in PARTITIONS)
        _require(
            group_splits.setdefault(row["group_id"], row["split"]) == row["split"],
            "ml_baseline_metrics_partition_crossing",
        )
        family = row["family"]
        _require(
            family is None
            or type(family) is str
            and 0 < len(family) <= 50
            and family.strip() == family
            and not any(ord(char) < 32 or ord(char) == 127 for char in family)
        )
        label = row["label"]
        _require(
            type(label) is dict
            and len(label) == len(_LABEL_FIELDS)
            and set(label) == _LABEL_FIELDS
            and label["unit"] == "K"
            and type(label["unit"]) is str
            and label["knowledge_origin"] == "Observed"
            and type(label["knowledge_origin"]) is str
            and label["value_relation"] == "exact"
            and type(label["value_relation"]) is str
            and type(label["tc_definition"]) is str
            and label["tc_definition"]
            in {"onset", "zero_resistance", "midpoint", "diamagnetic", "heat_capacity"}
            and _number(label["value"])
            and label["value"] > 0,
            "ml_baseline_metrics_unsupported_truth",
        )
        state, pressure = row["pressure_state"], row["pressure_gpa"]
        _require(
            type(state) is str
            and state in {"explicit_ambient", "reported", "not_reported", "ambiguous"}
            and (pressure is None or _number(pressure) and pressure >= 0),
            "ml_baseline_metrics_pressure_invalid",
        )
        _require(
            (state == "explicit_ambient" and pressure == 0)
            or (state == "reported" and pressure is not None)
            or (state == "not_reported" and pressure is None)
            or state == "ambiguous",
            "ml_baseline_metrics_pressure_invalid",
        )
        prediction, failure = row["prediction_k"], row["failure_reason"]
        _require(
            (prediction is not None and _number(prediction) and failure is None)
            or (prediction is None and type(failure) is str and failure in FAILURE_REASONS),
            "ml_baseline_metrics_prediction_invalid",
        )
    _criterion(records)
    return json.loads(_canonical(sorted(records, key=lambda row: row["example_id"])))


def _criterion(rows):
    criteria = {row["label"]["tc_definition"] for row in rows}
    _require(len(criteria) <= 1, "ml_baseline_metrics_mixed_tc_criteria")
    return next(iter(criteria)) if criteria else None


def validate_prediction_records(records):
    """Detach closed records, preserving original values rather than normalizing."""
    try:
        return _records(records)
    except MlBaselineMetricsError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError, RecursionError):
        raise MlBaselineMetricsError("ml_baseline_metrics_invalid") from None


def _pressure_stratum(row):
    state, value = row["pressure_state"], row["pressure_gpa"]
    if state != "reported":
        return state
    if value == 0:
        return "reported_zero"
    if value < 10:
        return "reported_0_to_10_gpa"
    if value < 100:
        return "reported_10_to_100_gpa"
    return "reported_ge_100_gpa"


def _finite_fraction(value):
    result = float(value)
    _require(math.isfinite(result), "ml_baseline_metrics_nonfinite_arithmetic")
    return result


def _errors(rows):
    # Exact rational differences/sums avoid order dependence, overflow of a
    # finite mean, and underflow from dividing each subnormal summand first.
    errors = sorted(
        abs(Fraction(row["prediction_k"]) - Fraction(row["label"]["value"]))
        for row in rows
        if row["prediction_k"] is not None
    )
    if not errors:
        return None, None
    count, middle = len(errors), len(errors) // 2
    median = errors[middle] if count % 2 else (errors[middle - 1] + errors[middle]) / 2
    return _finite_fraction(sum(errors, Fraction()) / count), _finite_fraction(median)


def _summary(rows):
    predicted = [row for row in rows if row["prediction_k"] is not None]
    failed = [row for row in rows if row["prediction_k"] is None]
    mae, median = _errors(rows)
    return {
        "requested_count": len(rows),
        "predicted_count": len(predicted),
        "failed_count": len(failed),
        "prediction_coverage": len(predicted) / len(rows) if rows else None,
        "metric_status": "scored"
        if predicted
        else "no_predictions"
        if rows
        else "no_requested_rows",
        "mae_k": mae,
        "median_absolute_error_k": median,
        "declared_component_count": len({row["group_id"] for row in rows}),
        "successful_component_count": len({row["group_id"] for row in predicted}),
        "failure_reason_counts": dict(
            sorted(Counter(row["failure_reason"] for row in failed).items())
        ),
        "failed_example_ids": [row["example_id"] for row in failed],
    }


def _limitations():
    return {
        "uncertainty": None,
        "uncertainty_reason_codes": list(UNCERTAINTY_REASONS),
        "independent_support_count": None,
        "authority": dict(AUTHORITY),
        "group_interpretation": "captured_leakage_components_not_independent_experiments",
    }


def score_predictions(records):
    """Full requested denominators plus descriptive split/stratum/group scores."""
    try:
        rows = _records(records)
        splits = []
        for split in PARTITIONS:
            selected = [row for row in rows if row["split"] == split]
            families = sorted(
                {row["family"] for row in selected},
                key=lambda value: (value is not None, value or ""),
            )
            splits.append(
                {
                    "split": split,
                    "summary": _summary(selected),
                    "by_family": [
                        {
                            "family": family,
                            "summary": _summary(
                                [row for row in selected if row["family"] == family]
                            ),
                        }
                        for family in families
                    ],
                    "by_pressure": [
                        {
                            "stratum": stratum,
                            "summary": _summary(
                                [row for row in selected if _pressure_stratum(row) == stratum]
                            ),
                        }
                        for stratum in PRESSURE_STRATA
                    ],
                    "by_component": [
                        {
                            "group_id": identifier,
                            "summary": _summary(
                                [row for row in selected if row["group_id"] == identifier]
                            ),
                        }
                        for identifier in sorted({row["group_id"] for row in selected})
                    ],
                }
            )
        report = {
            "version": VERSION,
            "records_sha256": _digest(rows),
            "metric_unit": "K",
            "tc_definition": _criterion(rows),
            "truth_policy": "exact_positive_observed_tc_only",
            "prediction_policy": "finite_unclipped_kelvin",
            "pressure_strata_version": PRESSURE_STRATA_VERSION,
            "pressure_basis": "supplied_pressure_state_and_value_no_imputation",
            "pressure_intervals_gpa": {
                "reported_0_to_10_gpa": "0 < P < 10",
                "reported_10_to_100_gpa": "10 <= P < 100",
                "reported_ge_100_gpa": "P >= 100",
            },
            "summary": _summary(rows),
            "by_split": splits,
            **_limitations(),
        }
        return json.loads(_canonical(report))
    except MlBaselineMetricsError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        UnicodeError,
        RecursionError,
        ArithmeticError,
    ):
        raise MlBaselineMetricsError("ml_baseline_metrics_invalid") from None


def compare_prediction_arms(left, right, *, split="test"):
    """Compare exact shared bindings; label nested/intersection metrics honestly.

    The common-success metric never replaces the complete requested inventories
    and explicit exclusions. A nested/cohort intersection is descriptive, not
    evidence for the causal value of a feature or independent significance.
    """
    try:
        _require(type(split) is str and split in PARTITIONS, "ml_baseline_comparison_split_invalid")
        left_rows, right_rows = _records(left), _records(right)
        criterion = _criterion(left_rows + right_rows)
        group_splits = {}
        for row in left_rows + right_rows:
            _require(
                group_splits.setdefault(row["group_id"], row["split"]) == row["split"],
                "ml_baseline_comparison_partition_mismatch",
            )
        all_left = {row["example_id"]: row for row in left_rows}
        all_right = {row["example_id"]: row for row in right_rows}
        for identifier in sorted(all_left.keys() & all_right.keys()):
            first, second = all_left[identifier], all_right[identifier]
            _require(
                _canonical({key: first[key] for key in _BINDING_FIELDS})
                == _canonical({key: second[key] for key in _BINDING_FIELDS}),
                "ml_baseline_comparison_binding_mismatch",
            )
        left_selected = {key: row for key, row in all_left.items() if row["split"] == split}
        right_selected = {key: row for key, row in all_right.items() if row["split"] == split}
        left_ids, right_ids = set(left_selected), set(right_selected)
        common = left_ids & right_ids
        relation = (
            "same_rows"
            if left_ids == right_ids
            else "left_nested_subset"
            if left_ids < right_ids
            else "right_nested_subset"
            if right_ids < left_ids
            else "overlap_not_nested"
            if common
            else "disjoint"
        )
        successful = sorted(
            identifier
            for identifier in common
            if left_selected[identifier]["prediction_k"] is not None
            and right_selected[identifier]["prediction_k"] is not None
        )
        paired_left = [left_selected[key] for key in successful]
        paired_right = [right_selected[key] for key in successful]
        left_mae, left_median = _errors(paired_left)
        right_mae, right_median = _errors(paired_right)
        paired = (
            None
            if not successful
            else {
                "successful_common_count": len(successful),
                "left_mae_k": left_mae,
                "right_mae_k": right_mae,
                "left_median_absolute_error_k": left_median,
                "right_median_absolute_error_k": right_median,
                "mae_delta_right_minus_left_k": _finite_fraction(
                    Fraction(right_mae) - Fraction(left_mae)
                ),
                "median_absolute_error_delta_right_minus_left_k": _finite_fraction(
                    Fraction(right_median) - Fraction(left_median)
                ),
            }
        )
        report = {
            "version": VERSION,
            "comparison_scope": "common_successful_rows_descriptive_not_causal",
            "split": split,
            "relationship": relation,
            "metric_unit": "K",
            "tc_definition": criterion,
            "left_records_sha256": _digest(left_rows),
            "right_records_sha256": _digest(right_rows),
            "left_summary": _summary(list(left_selected.values())),
            "right_summary": _summary(list(right_selected.values())),
            "common_requested_count": len(common),
            "common_requested_example_ids": sorted(common),
            "left_only_example_ids": sorted(left_ids - right_ids),
            "right_only_example_ids": sorted(right_ids - left_ids),
            "successful_common_example_ids": successful,
            "common_prediction_failures": [
                {
                    "example_id": key,
                    "left_failure_reason": left_selected[key]["failure_reason"],
                    "right_failure_reason": right_selected[key]["failure_reason"],
                }
                for key in sorted(common - set(successful))
            ],
            "paired_metrics": paired,
            "significance": None,
            "causal_feature_effect_established": False,
            **_limitations(),
        }
        return json.loads(_canonical(report))
    except MlBaselineMetricsError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        UnicodeError,
        RecursionError,
        ArithmeticError,
    ):
        raise MlBaselineMetricsError("ml_baseline_comparison_invalid") from None


__all__ = [
    "VERSION",
    "PRESSURE_STRATA_VERSION",
    "MAX_RECORDS",
    "MAX_REPORT_BYTES",
    "FAILURE_REASONS",
    "MlBaselineMetricsError",
    "validate_prediction_records",
    "score_predictions",
    "compare_prediction_arms",
]
