"""Bounded deterministic numerical primitives, not a real-data execution grant.

Only training and validation data enter fitting/selection. Prediction has no
target argument. No preprocessing, train+validation refit, I/O, uncertainty
estimate or scientific authority is inferred by this standard-library kernel.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from fractions import Fraction

VERSION = "ml-baseline-numerics/1.0.0"
MODEL_VERSION = "ml-baseline-model/1.0.0"
PREDICTION_VERSION = "ml-baseline-predictions/1.0.0"
METHODS = frozenset({"median_train", "family_median_train", "ridge", "ols"})
MAX_ROWS = 512
MAX_FEATURES = 256
MAX_CELLS = 131072
MAX_CANDIDATES = 16
MAX_OPERATIONS = 32_000_000
PREDICTION_FAILURES = frozenset({"prediction_nonfinite_features", "prediction_nonfinite_arithmetic"})
NUMERICAL_POLICY = {
    "version": "float64-normal-equations/1.0.0",
    "ridge_objective": "sum_squared_error_plus_alpha_l2_slopes",
    "intercept": "unpenalized",
    "solver": "centered_normal_equations_partial_pivot",
    "pivot_relative_tolerance": 1e-12,
    "pivot_absolute_tolerance": 1e-14,
    "replay_relative_tolerance": 1e-10,
    "replay_absolute_tolerance": 1e-10,
}
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,119}\Z")
_MODEL_FIELDS = frozenset({"version", "candidate_id", "method", "alpha", "feature_names",
    "training_row_count", "intercept", "coefficients", "global_median", "family_medians"})


class MlBaselineNumericsError(ValueError):
    """Malformed input or resource limit; only static codes are exposed."""


class _NumericalFailure(ArithmeticError):
    pass


def _require(condition, code="baseline_numerical_input_invalid"):
    if not condition:
        raise MlBaselineNumericsError(code)


def _number(value, *, finite=True):
    _require(type(value) in {int, float})
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise MlBaselineNumericsError("baseline_numerical_input_invalid") from None
    _require(not finite or math.isfinite(result))
    return result


def _finite(value):
    if not math.isfinite(value):
        raise _NumericalFailure("nonfinite_arithmetic")
    return value


def _names(value):
    _require(type(value) is list and len(value) <= MAX_FEATURES, "baseline_feature_limit")
    _require(all(type(name) is str and _IDENTIFIER.fullmatch(name) for name in value)
             and len(set(value)) == len(value))
    return list(value)


def _family(value):
    _require(value is None or (type(value) is str and 0 < len(value) <= 120
             and value == value.strip() and not any(ord(char) < 32 or ord(char) == 127 for char in value)))
    if value is not None:
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise MlBaselineNumericsError("baseline_numerical_input_invalid") from None
    return value


def _matrix(value, width):
    _require(type(value) is list and len(value) <= MAX_ROWS
             and len(value) * width <= MAX_CELLS, "baseline_matrix_limit")
    result = []
    for row in value:
        _require(type(row) is list and len(row) == width)
        result.append([_number(number, finite=False) for number in row])
    return result


def _families(value, count):
    _require(type(value) is list and len(value) == count)
    return [_family(family) for family in value]


def _targets(value, count):
    _require(type(value) is list and len(value) == count)
    return [_number(number) for number in value]


def _candidate(value):
    _require(type(value) is dict and set(value) == {"candidate_id", "method", "alpha"})
    _require(type(value["candidate_id"]) is str and _IDENTIFIER.fullmatch(value["candidate_id"]))
    _require(type(value["method"]) is str and value["method"] in METHODS)
    alpha = value["alpha"]
    if value["method"] == "ridge":
        alpha = _number(alpha)
        _require(alpha > 0)
    else:
        _require(alpha is None)
    return {"candidate_id": value["candidate_id"], "method": value["method"], "alpha": alpha}


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else float(
        (Fraction(ordered[middle - 1]) + Fraction(ordered[middle])) / 2)


def _mean(values):
    # Dividing each float first can turn every subnormal summand into zero.
    # This bounded exact accumulation also matches the descriptive metric mean.
    return _finite(float(sum((Fraction(number) for number in values), Fraction()) / len(values)))


def _dot(left, right):
    return _finite(math.fsum(_finite(a * b) for a, b in zip(left, right)))


def _solve(matrix, target):
    """Deterministic partial-pivot elimination; never silently pseudoinvert."""
    width = len(target)
    if not width:
        return []
    augmented = [list(row) + [value] for row, value in zip(matrix, target)]
    scale = max(abs(value) for row in matrix for value in row)
    tolerance = max(NUMERICAL_POLICY["pivot_absolute_tolerance"],
                    NUMERICAL_POLICY["pivot_relative_tolerance"] * scale)
    for column in range(width):
        pivot = max(range(column, width), key=lambda index: abs(augmented[index][column]))
        if abs(augmented[pivot][column]) <= tolerance:
            raise _NumericalFailure("singular_or_ill_conditioned_system")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        for index in range(column + 1, width):
            ratio = _finite(augmented[index][column] / augmented[column][column])
            augmented[index][column] = 0.0
            for following in range(column + 1, width + 1):
                augmented[index][following] = _finite(
                    augmented[index][following] - _finite(ratio * augmented[column][following]))
    coefficients = [0.0] * width
    for index in range(width - 1, -1, -1):
        tail = _dot(augmented[index][index + 1:width], coefficients[index + 1:])
        coefficients[index] = _finite((augmented[index][width] - tail) / augmented[index][index])
    return coefficients


def _fit(candidate, matrix, targets, families, names):
    if not all(math.isfinite(number) for row in matrix for number in row):
        raise _NumericalFailure("nonfinite_training_features")
    model = {"version": MODEL_VERSION, **candidate, "feature_names": list(names),
             "training_row_count": len(matrix), "intercept": None, "coefficients": [],
             "global_median": None, "family_medians": []}
    if candidate["method"] in {"median_train", "family_median_train"}:
        model["global_median"] = _median(targets)
        if candidate["method"] == "family_median_train":
            grouped = {}
            for family, target in zip(families, targets):
                if family is not None:
                    grouped.setdefault(family, []).append(target)
            model["family_medians"] = [{"family": family, "median": _median(values), "count": len(values)}
                                       for family, values in sorted(grouped.items())]
        return model
    width = len(names)
    means = [_mean([row[column] for row in matrix]) for column in range(width)]
    target_mean = _mean(targets)
    centered = [[_finite(value - mean) for value, mean in zip(row, means)] for row in matrix]
    residuals = [_finite(value - target_mean) for value in targets]
    columns = [[row[column] for row in centered] for column in range(width)]
    gram = [[_dot(left, right) for right in columns] for left in columns]
    if candidate["method"] == "ridge":
        for index in range(width):
            gram[index][index] = _finite(gram[index][index] + candidate["alpha"])
    coefficients = _solve(gram, [_dot(column, residuals) for column in columns])
    model.update(coefficients=coefficients, intercept=_finite(target_mean - _dot(means, coefficients)))
    return model


def _model(value):
    _require(type(value) is dict and set(value) == _MODEL_FIELDS and value["version"] == MODEL_VERSION)
    candidate = _candidate({key: value[key] for key in ("candidate_id", "method", "alpha")})
    names = _names(value["feature_names"])
    _require(type(value["training_row_count"]) is int and 1 <= value["training_row_count"] <= MAX_ROWS)
    _require(type(value["coefficients"]) is list and type(value["family_medians"]) is list)
    if candidate["method"] in {"ridge", "ols"}:
        _require(len(value["coefficients"]) == len(names) and value["global_median"] is None
                 and value["family_medians"] == [])
        _number(value["intercept"])
        for coefficient in value["coefficients"]:
            _number(coefficient)
    else:
        _require(value["intercept"] is None and value["coefficients"] == [])
        _number(value["global_median"])
        _require(len(value["family_medians"]) <= value["training_row_count"])
        if candidate["method"] == "median_train":
            _require(value["family_medians"] == [])
        previous, count = None, 0
        for family in value["family_medians"]:
            _require(type(family) is dict and set(family) == {"family", "median", "count"})
            name = _family(family["family"])
            _require(name is not None and (previous is None or previous < name))
            _number(family["median"])
            _require(type(family["count"]) is int and 1 <= family["count"] <= value["training_row_count"])
            previous, count = name, count + family["count"]
        _require(count <= value["training_row_count"])
    return deepcopy(value)


def predict(*, model, matrix, families):
    """Return every requested row; nonfinite arithmetic is a recorded failure."""
    model = _model(model)
    matrix = _matrix(matrix, len(model["feature_names"]))
    families = _families(families, len(matrix))
    family_medians = {row["family"]: row["median"] for row in model["family_medians"]}
    rows = []
    for index, (features, family) in enumerate(zip(matrix, families)):
        reason, value, fallback = None, None, False
        if not all(math.isfinite(number) for number in features):
            reason = "prediction_nonfinite_features"
        else:
            try:
                if model["method"] == "median_train":
                    value = model["global_median"]
                elif model["method"] == "family_median_train":
                    fallback = family not in family_medians
                    value = family_medians.get(family, model["global_median"])
                else:
                    value = _finite(model["intercept"] + _dot(features, model["coefficients"]))
            except (ArithmeticError, ValueError):
                reason, value, fallback = "prediction_nonfinite_arithmetic", None, False
        rows.append({"index": index, "status": "failed" if reason else "predicted", "value": value,
                     "reason_codes": [reason] if reason else [], "fallback_used": fallback})
    return {"version": PREDICTION_VERSION, "requested_count": len(rows),
            "predicted_count": sum(row["status"] == "predicted" for row in rows), "rows": rows}


def fit_select(*, train_matrix, train_targets, train_families, validation_matrix,
               validation_targets, validation_families, feature_names, candidates):
    """Fit every bounded candidate on train; select by complete validation MAE.

    Candidate order is lexical ID order; exact score ties choose the first ID.
    No test data is accepted and the selected model is not refitted. Model
    dictionaries are replayable numerical state, not authenticated receipts.
    """
    names = _names(feature_names)
    train = _matrix(train_matrix, len(names))
    validation = _matrix(validation_matrix, len(names))
    _require(train and len(train) + len(validation) <= MAX_ROWS, "baseline_row_limit")
    targets = _targets(train_targets, len(train))
    validation_targets = _targets(validation_targets, len(validation))
    families = _families(train_families, len(train))
    validation_families = _families(validation_families, len(validation))
    _require(type(candidates) is list and 1 <= len(candidates) <= MAX_CANDIDATES, "baseline_candidate_limit")
    declared = [_candidate(candidate) for candidate in candidates]
    _require(len({candidate["candidate_id"] for candidate in declared}) == len(declared))
    declared.sort(key=lambda candidate: candidate["candidate_id"])
    # Conservative operation estimate covers full normal equations/elimination,
    # every candidate, and validation dot products before any fit is attempted.
    width = len(names)
    per_linear = 4 * len(train) * width * width + 2 * width ** 3 + 4 * len(validation) * width + 8 * len(train) * (width + 1)
    operations = sum(per_linear if candidate["method"] in {"ridge", "ols"}
                     else 8 * (len(train) + len(validation)) for candidate in declared)
    _require(operations <= MAX_OPERATIONS, "baseline_operation_limit")
    ledger = []
    for candidate in declared:
        model = predictions = score = None
        reasons, fit_status = [], "failed"
        try:
            model = _fit(candidate, train, targets, families, names)
            fit_status = "fitted"
            predictions = predict(model=model, matrix=validation, families=validation_families)
            if not validation:
                reasons.append("validation_empty")
            elif predictions["predicted_count"] != len(validation):
                reasons.append("validation_prediction_incomplete")
            else:
                errors = [_finite(abs(row["value"] - target)) for row, target in zip(predictions["rows"], validation_targets)]
                score = _mean(errors)
        except _NumericalFailure as exc:
            reasons.append(str(exc) if fit_status == "failed" else "validation_metric_nonfinite")
        except (ArithmeticError, ValueError):
            reasons.append("nonfinite_fit_arithmetic" if fit_status == "failed" else "validation_metric_nonfinite")
        ledger.append({**candidate, "fit_status": fit_status, "status": "failed" if reasons else "eligible",
            "reason_codes": reasons, "model": model, "validation_predictions": predictions, "validation_mae": score})
    eligible = [row for row in ledger if row["status"] == "eligible"]
    chosen = min(eligible, key=lambda row: (row["validation_mae"], row["candidate_id"])) if eligible else None
    return {"version": VERSION, "selection_rule": "validation_mae_then_candidate_id",
            "numerical_policy": dict(NUMERICAL_POLICY), "candidate_ledger": ledger,
            "selected_candidate_id": chosen["candidate_id"] if chosen else None,
            "selected_model": deepcopy(chosen["model"]) if chosen else None,
            "status": "selected" if chosen else "no_go"}
