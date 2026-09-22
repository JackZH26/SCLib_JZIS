"""Pure, explicitly synthetic arithmetic units; not a scientific benchmark."""

from copy import deepcopy
from inspect import signature

import pytest

from services import ml_baseline_numerics as kernel


def candidate(method, identifier=None, alpha=None):
    return {"candidate_id": identifier or method, "method": method,
            "alpha": alpha if method == "ridge" else None}


def arguments():
    return {"train_matrix": [[0.0], [1.0], [2.0]], "train_targets": [1.0, 3.0, 5.0],
            "train_families": ["A", "A", "B"], "validation_matrix": [[3.0]],
            "validation_targets": [7.0], "validation_families": ["new-family"],
            "feature_names": ["x"], "candidates": [candidate("ols")]}


def test_toy_ols_exact_coefficients_and_unpenalized_intercept():
    result = kernel.fit_select(**arguments())
    assert result["status"] == "selected"
    model = result["selected_model"]
    assert model["coefficients"] == [2.0]
    assert model["intercept"] == 1.0
    assert model["training_row_count"] == 3
    assert result["candidate_ledger"][0]["validation_mae"] == 0.0
    assert kernel.predict(model=model, matrix=[[4.0]], families=[None])["rows"][0]["value"] == 9.0


def test_ridge_has_sum_sse_objective_not_mean_sse_or_penalized_intercept():
    args = arguments()
    args["candidates"] = [candidate("ridge", alpha=2.0)]
    result = kernel.fit_select(**args)
    model = result["selected_model"]
    # Centered sum(x²)=2, sum(x*y)=4: slope=4/(2+2)=1.
    assert model["coefficients"] == [1.0] and model["intercept"] == 2.0
    assert result["candidate_ledger"][0]["validation_mae"] == 2.0
    assert result["numerical_policy"]["ridge_objective"] == "sum_squared_error_plus_alpha_l2_slopes"


def test_multiple_predictors_recover_full_rank_known_coefficients():
    args = arguments()
    args.update(train_matrix=[[0, 0], [1, 0], [0, 1], [1, 1]], train_targets=[4, 6, 7, 9],
                train_families=[None] * 4, validation_matrix=[[2, 3]], validation_targets=[17],
                feature_names=["x", "y"])
    model = kernel.fit_select(**args)["selected_model"]
    assert model["coefficients"] == [2.0, 3.0] and model["intercept"] == 4.0


@pytest.mark.parametrize("targets,expected", [([1, 3, 100], 3.0), ([1e308, 1e308], 1e308),
                                                ([5e-324, 5e-324], 5e-324)])
def test_training_median_has_no_midpoint_overflow_or_constant_underflow(targets, expected):
    args = arguments()
    args.update(train_matrix=[[0]] * len(targets), train_targets=targets, train_families=[None] * len(targets),
                validation_matrix=[[0]], validation_targets=[expected], candidates=[candidate("median_train")])
    assert kernel.fit_select(**args)["selected_model"]["global_median"] == expected


def test_family_medians_and_unknown_family_use_only_global_training_fallback():
    args = arguments()
    args.update(train_targets=[10, 30, 100], candidates=[candidate("family_median_train")])
    model = kernel.fit_select(**args)["selected_model"]
    assert model["global_median"] == 30.0
    assert model["family_medians"] == [{"family": "A", "median": 20.0, "count": 2},
                                        {"family": "B", "median": 100.0, "count": 1}]
    predictions = kernel.predict(model=model, matrix=[[1], [2], [3], [4]], families=["A", "B", "unseen", None])
    assert [row["value"] for row in predictions["rows"]] == [20.0, 100.0, 30.0, 30.0]
    assert [row["fallback_used"] for row in predictions["rows"]] == [False, False, True, True]
    assert all(row["reason_codes"] == [] for row in predictions["rows"])


def test_validation_can_change_selection_but_not_any_fitted_candidate():
    args = arguments()
    args["candidates"] = [candidate("median_train"), candidate("ridge", alpha=2)]
    args["validation_targets"] = [5]
    before = kernel.fit_select(**args)
    args["validation_targets"] = [3]
    after = kernel.fit_select(**args)
    assert before["selected_candidate_id"] == "ridge"
    assert after["selected_candidate_id"] == "median_train"
    assert [row["model"] for row in before["candidate_ledger"]] == [row["model"] for row in after["candidate_ledger"]]
    assert all(row["model"]["training_row_count"] == 3 for row in after["candidate_ledger"])


def test_candidates_are_deterministically_sorted_and_exact_ties_use_id():
    args = arguments()
    args["candidates"] = [candidate("median_train", "z"), candidate("median_train", "a")]
    result = kernel.fit_select(**args)
    args["candidates"].reverse()
    assert kernel.fit_select(**args) == result
    assert [row["candidate_id"] for row in result["candidate_ledger"]] == ["a", "z"]
    assert result["selected_candidate_id"] == "a"


def test_fit_select_and_prediction_have_no_held_out_target_parameter_or_refit():
    assert not any("test" in name for name in signature(kernel.fit_select).parameters)
    assert not any("target" in name for name in signature(kernel.predict).parameters)
    with pytest.raises(TypeError):
        kernel.fit_select(**arguments(), test_targets=[999999])
    model = kernel.fit_select(**arguments())["selected_model"]
    retained = deepcopy(model)
    predictions = kernel.predict(model=model, matrix=[[1e308], [4]], families=[None, None])
    assert predictions["rows"][0]["status"] == "failed"
    assert predictions["rows"][1]["value"] == 9.0
    assert model == retained


def test_no_input_mutation_and_selected_model_is_detached_from_ledger():
    args = arguments()
    original = deepcopy(args)
    result = kernel.fit_select(**args)
    assert args == original
    result["selected_model"]["coefficients"][0] = 123
    assert result["candidate_ledger"][0]["model"]["coefficients"] == [2.0]


def test_ols_singular_candidate_retained_alongside_eligible_ridge():
    args = arguments()
    args.update(train_matrix=[[0, 0], [1, 1], [2, 2]], validation_matrix=[[3, 3]], feature_names=["x", "y"],
                candidates=[candidate("ridge", alpha=1), candidate("ols")])
    result = kernel.fit_select(**args)
    failed, fitted = result["candidate_ledger"]
    assert failed["candidate_id"] == "ols" and failed["model"] is None
    assert failed["reason_codes"] == ["singular_or_ill_conditioned_system"]
    assert fitted["status"] == "eligible" and result["selected_candidate_id"] == "ridge"


@pytest.mark.parametrize("kind", ["singular", "nonfinite_training", "nonfinite_arithmetic"])
def test_all_failed_candidates_are_no_go_without_invented_fallback(kind):
    args = arguments()
    if kind == "singular":
        args["train_matrix"] = [[1], [1], [1]]
    elif kind == "nonfinite_training":
        args["train_matrix"][0][0] = float("nan")
    else:
        args["train_matrix"] = [[-1e308], [0], [1e308]]
    result = kernel.fit_select(**args)
    assert result["status"] == "no_go" and result["selected_model"] is None
    assert result["selected_candidate_id"] is None and len(result["candidate_ledger"]) == 1
    assert result["candidate_ledger"][0]["status"] == "failed"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_prediction_row_does_not_drop_or_change_other_denominators(bad):
    model = kernel.fit_select(**arguments())["selected_model"]
    result = kernel.predict(model=model, matrix=[[bad], [4], [1e308]], families=[None] * 3)
    assert result["requested_count"] == 3 and result["predicted_count"] == 1
    assert [row["index"] for row in result["rows"]] == [0, 1, 2]
    assert result["rows"][0]["reason_codes"] == ["prediction_nonfinite_features"]
    assert result["rows"][2]["reason_codes"] == ["prediction_nonfinite_arithmetic"]
    assert result["rows"][0]["value"] is None and result["rows"][2]["value"] is None


def test_incomplete_validation_is_not_scored_on_surviving_subset():
    args = arguments()
    args.update(validation_matrix=[[3], [float("inf")]], validation_targets=[7, 8], validation_families=[None, None])
    result = kernel.fit_select(**args)
    ledger = result["candidate_ledger"][0]
    assert ledger["fit_status"] == "fitted" and ledger["validation_mae"] is None
    assert ledger["validation_predictions"]["requested_count"] == 2
    assert ledger["validation_predictions"]["predicted_count"] == 1
    assert ledger["reason_codes"] == ["validation_prediction_incomplete"]
    assert result["status"] == "no_go"


def test_empty_validation_and_overflowed_errors_remain_failed_ledger_entries():
    args = arguments()
    args.update(validation_matrix=[], validation_targets=[], validation_families=[])
    result = kernel.fit_select(**args)
    assert result["candidate_ledger"][0]["reason_codes"] == ["validation_empty"]
    args.update(train_targets=[1e308] * 3, validation_matrix=[[0]], validation_targets=[-1e308],
                validation_families=[None], candidates=[candidate("median_train")])
    result = kernel.fit_select(**args)
    assert result["candidate_ledger"][0]["reason_codes"] == ["validation_metric_nonfinite"]
    assert result["status"] == "no_go"


@pytest.mark.parametrize("change", ["method", "alpha_bool", "alpha_zero", "alpha_nan", "alpha_extra",
                                    "extra", "id", "duplicate", "feature_name", "duplicate_feature",
                                    "feature_bool", "target_bool", "target_nan", "family_bool", "shape"])
def test_invalid_closed_types_enums_and_bools_reject_atomically(change):
    args = arguments()
    if change.startswith("alpha_"):
        args["candidates"] = [candidate("ridge", alpha={"alpha_bool": True, "alpha_zero": 0,
            "alpha_nan": float("nan"), "alpha_extra": 1}[change])]
        if change == "alpha_extra": args["candidates"][0]["method"] = "ols"
    elif change == "method": args["candidates"][0]["method"] = "automatic_best"
    elif change == "extra": args["candidates"][0]["approved"] = True
    elif change == "id": args["candidates"][0]["candidate_id"] = "bad id"
    elif change == "duplicate": args["candidates"] *= 2
    elif change == "feature_name": args["feature_names"] = [True]
    elif change == "duplicate_feature": args["feature_names"] = ["x", "x"]
    elif change == "feature_bool": args["train_matrix"][0][0] = True
    elif change == "target_bool": args["train_targets"][0] = True
    elif change == "target_nan": args["validation_targets"][0] = float("nan")
    elif change == "family_bool": args["train_families"][0] = True
    else: args["validation_matrix"][0].append(1)
    with pytest.raises(kernel.MlBaselineNumericsError):
        kernel.fit_select(**args)


@pytest.mark.parametrize("change", ["version", "method", "intercept_bool", "coefficient_shape", "extra", "count_bool"])
def test_forged_model_shape_rejected_before_prediction(change):
    model = kernel.fit_select(**arguments())["selected_model"]
    if change == "version": model["version"] = "other"
    elif change == "method": model["method"] = "neural"
    elif change == "intercept_bool": model["intercept"] = True
    elif change == "coefficient_shape": model["coefficients"] = []
    elif change == "extra": model["training_approved"] = True
    else: model["training_row_count"] = True
    with pytest.raises(kernel.MlBaselineNumericsError):
        kernel.predict(model=model, matrix=[[1]], families=[None])


@pytest.mark.parametrize("limit", ["rows", "features", "grid", "operations"])
def test_resource_limits_reject_before_any_fit(monkeypatch, limit):
    args = arguments()
    if limit == "rows":
        args.update(train_matrix=[[0]] * kernel.MAX_ROWS, train_targets=[1] * kernel.MAX_ROWS, train_families=[None] * kernel.MAX_ROWS)
    elif limit == "features": args["feature_names"] = ["f" + str(index) for index in range(kernel.MAX_FEATURES + 1)]
    elif limit == "grid": args["candidates"] = [candidate("ols", "c" + str(index)) for index in range(kernel.MAX_CANDIDATES + 1)]
    else: monkeypatch.setattr(kernel, "MAX_OPERATIONS", 0)
    def forbidden(*_args):
        pytest.fail("fit must not start after failed resource preflight")
    monkeypatch.setattr(kernel, "_fit", forbidden)
    with pytest.raises(kernel.MlBaselineNumericsError):
        kernel.fit_select(**args)


def test_declared_256_column_bound_supports_statistical_methods():
    args = arguments()
    args.update(feature_names=["x" + str(index) for index in range(256)], train_matrix=[[0] * 256] * 3,
                validation_matrix=[[0] * 256], candidates=[candidate("median_train")])
    assert kernel.fit_select(**args)["status"] == "selected"


def test_intercept_only_linear_model_is_explicit_and_finite():
    args = arguments()
    args.update(train_matrix=[[], [], []], validation_matrix=[[]], feature_names=[])
    model = kernel.fit_select(**args)["selected_model"]
    assert model["coefficients"] == [] and model["intercept"] == 3.0


def test_validation_mae_preserves_repeated_subnormal_nonzero_errors():
    args = arguments()
    args.update(train_targets=[0, 0, 0], validation_matrix=[[0], [0], [0]],
                validation_targets=[5e-324] * 3, validation_families=[None] * 3,
                candidates=[candidate("median_train")])
    selection = kernel.fit_select(**args)
    assert selection["candidate_ledger"][0]["validation_mae"] == 5e-324


def test_constant_subnormal_target_mean_does_not_become_zero():
    args = arguments()
    args.update(train_matrix=[[], [], []], validation_matrix=[[]], feature_names=[],
                train_targets=[5e-324] * 3, validation_targets=[5e-324])
    selection = kernel.fit_select(**args)
    assert selection["selected_model"]["intercept"] == 5e-324
    assert selection["candidate_ledger"][0]["validation_mae"] == 0.0
