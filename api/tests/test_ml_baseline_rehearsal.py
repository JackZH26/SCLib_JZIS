"""Pure synthetic coordinator tests; no dataset authentication or SQL fixture."""

from copy import deepcopy

import pytest

from models import ml_baseline_task as task_model
from services import ml_baseline_numerics as numerics
from services import ml_baseline_rehearsal as service
from services.ml_audited_dataset import digest
from services.ml_composition import FEATURE_NAMES
from services.ml_preprocessing import fit_transform


def small_fixture(*, constant=False, all_missing=False):
    """Explicit one-column numerical seam, not an audited captured package."""
    raw = [[None if all_missing else 0.0 if constant else float(index)] for index in range(5)]
    splits = ["train"] * 3 + ["validation", "test"]
    fitted = fit_transform(raw, splits, ["x"])
    rows = [{"example_id": "synthetic-" + str(index), "group_id": digest(["group", index]),
        "assignment_sha256": digest(["assignment", index, split]), "split": split,
        "family": "train-family" if split == "train" else "unseen-" + split,
        "pressure_state": "not_reported", "pressure_gpa": None,
        "label": {"value": float(1 + 2 * index), "unit": "K", "tc_definition": "onset",
                  "knowledge_origin": "Observed", "value_relation": "exact"},
        "features": values, "missingness": missing}
        for index, (split, values, missing) in enumerate(zip(splits, fitted["transformed"], fitted["missingness"], strict=True))]
    view = {"feature_names": ["x"], "preprocessing": fitted, "rows": rows,
            "cohort_sha256": digest([row["example_id"] for row in rows])}
    configured = {"arm_id": "toy", "view": "C@B", "feature_scope": "view_all", "feature_names": ["x"]}
    config = task_model.make_baseline_task(digest(["explicit-unit-input"]), [configured])
    config["candidates"] = [{"candidate_id": "median", "method": "median_train", "alpha": None},
                             {"candidate_id": "ols", "method": "ols", "alpha": None}]
    conditions = {row["example_id"]: {"pressure_state": row["pressure_state"], "pressure_gpa": row["pressure_gpa"]} for row in rows}
    prepared = {"version": service.PREPARED_VERSION, "input_sha256": config["input_sha256"],
        "config_sha256": digest(config), "scope": "implementation_owned_numerical_fixture",
        "arms": [service._project(view, configured, conditions)], "identity_counts": None,
        "base_coverage": {"synthetic_rows": len(rows), "independent_support_count": None}}
    return prepared, config


def one_arm(report):
    return report["arms"][0]


def test_default_fixed_toy_runs_actual_kernel_and_replays_exactly():
    receipt = service.run_synthetic_rehearsal()
    verified = service.verify_synthetic_rehearsal(receipt, expected_receipt_sha256=digest(receipt))
    assert verified["numerical_replay_verified"] is True
    assert receipt["scope"] == "fixed_implementation_owned_synthetic_rehearsal"
    report = receipt["report"]
    assert report["gate"]["status"] == "pass" and len(report["arms"]) == 4
    assert all(value is False for value in receipt["authority"].values())
    assert all(value is False for value in report["authority"].values())
    assert report["identity_counts"] is None and report["independent_support_count"] is None
    assert report["model_card"]["test_targets_used_for_fit_or_selection"] is False
    assert report["model_card"]["post_selection_refit"] is False
    assert report["model_card"]["uncertainty"] is None
    for arm in report["arms"]:
        assert len(arm["selection"]["candidate_ledger"]) == 5
        assert arm["prediction_execution"]["requested_count"] == len(arm["predictions"])
        assert any(item["candidate_id"] == "ols" and item["status"] == "failed"
                   for item in arm["selection"]["candidate_ledger"])


def test_column_projection_keeps_actual_composition_and_condition_arms_distinct():
    _, _, prepared = service._owned_fixture()
    arms = {arm["arm_id"]: arm for arm in prepared["arms"]}
    composition, conditions = arms["composition_B"], arms["conditions_B"]
    assert composition["feature_names"] == list(FEATURE_NAMES)
    assert conditions["feature_names"] == list(FEATURE_NAMES) + service.CONDITIONS
    assert not set(service.CONDITIONS) & set(composition["selected_feature_names"])
    assert set(service.CONDITIONS) <= set(conditions["selected_feature_names"])
    assert composition["cohort_sha256"] == conditions["cohort_sha256"]
    assert composition["preprocessing"]["source_parameters_sha256"] == conditions["preprocessing"]["source_parameters_sha256"]
    assert set(composition["preprocessing"]) == {"scope", "source_parameters_sha256", "parameters"}
    indices = [conditions["selected_feature_names"].index(name) for name in composition["selected_feature_names"]]
    for left, right in zip(composition["rows"], conditions["rows"], strict=True):
        assert left["example_id"] == right["example_id"]
        assert left["assignment_sha256"] == right["assignment_sha256"]
        assert left["features"] == [right["features"][index] for index in indices]
        assert left["missingness"] == right["missingness"][:len(FEATURE_NAMES)]


def test_composition_scope_cannot_be_used_to_relabel_condition_columns():
    prepared, config = small_fixture()
    arm = deepcopy(config["arms"][0])
    arm["feature_scope"] = "composition"
    with pytest.raises(service.MlBaselineRehearsalError, match="feature_semantics"):
        service._project({"feature_names": ["x"], "preprocessing": None}, arm, {})


def test_test_targets_change_only_test_errors_not_fit_selection_or_predictions():
    prepared, config = small_fixture()
    original = deepcopy(prepared)
    before = service._evaluate_prepared(prepared, config)
    changed = deepcopy(prepared)
    changed["arms"][0]["rows"][-1]["label"]["value"] = 90000.0
    after = service._evaluate_prepared(changed, config)
    left, right = one_arm(before), one_arm(after)
    assert prepared == original
    assert left["selection"] == right["selection"]
    assert left["prediction_execution"] == right["prediction_execution"]
    assert left["metrics"]["by_split"][:2] == right["metrics"]["by_split"][:2]
    assert left["metrics"]["by_split"][2] != right["metrics"]["by_split"][2]
    assert left["preprocessing"] == right["preprocessing"]


def test_test_only_feature_extreme_does_not_enter_fit_and_keeps_failed_row():
    prepared, config = small_fixture()
    baseline = service._evaluate_prepared(prepared, config)
    # The coefficient is in train-standardized coordinates (~1.63), so use
    # a still-finite feature large enough to overflow its actual dot product.
    prepared["arms"][0]["rows"][-1]["features"] = [1.79e308]
    altered = service._evaluate_prepared(prepared, config)
    arm = one_arm(altered)
    assert arm["selection"] == one_arm(baseline)["selection"]
    assert len(arm["predictions"]) == 5
    assert arm["predictions"][-1]["failure_reason"] == "prediction_nonfinite_arithmetic"
    assert arm["metrics"]["summary"]["requested_count"] == 5
    assert arm["metrics"]["summary"]["predicted_count"] == 4


def test_validation_changes_only_selection_and_scores_not_training_models():
    prepared, config = small_fixture()
    before = one_arm(service._evaluate_prepared(prepared, config))
    prepared["arms"][0]["rows"][3]["label"]["value"] = 3.0
    after = one_arm(service._evaluate_prepared(prepared, config))
    assert before["selection"]["selected_candidate_id"] == "ols"
    assert after["selection"]["selected_candidate_id"] == "median"
    assert [item["model"] for item in before["selection"]["candidate_ledger"]] == [item["model"] for item in after["selection"]["candidate_ledger"]]
    assert before["preprocessing"] == after["preprocessing"]


def test_family_fallback_execution_evidence_is_retained_for_unseen_rows():
    prepared, config = small_fixture()
    config["candidates"] = [{"candidate_id": "family", "method": "family_median_train", "alpha": None}]
    prepared["config_sha256"] = digest(config)
    arm = one_arm(service._evaluate_prepared(prepared, config))
    assert [row["fallback_used"] for row in arm["prediction_execution"]["rows"]] == [False] * 3 + [True, True]
    assert arm["selection"]["selected_model"]["global_median"] == 3.0


def test_all_singular_candidates_no_go_retains_full_grid_and_requested_predictions():
    prepared, config = small_fixture(constant=True)
    config["candidates"] = [{"candidate_id": "ols_a", "method": "ols", "alpha": None},
                             {"candidate_id": "ols_b", "method": "ols", "alpha": None}]
    prepared["config_sha256"] = digest(config)
    report = service._evaluate_prepared(prepared, config)
    arm = one_arm(report)
    assert report["gate"]["status"] == "no_go" and report["gate"]["failed_arms"] == ["toy"]
    assert [row["candidate_id"] for row in arm["selection"]["candidate_ledger"]] == ["ols_a", "ols_b"]
    assert all(row["reason_codes"] == ["singular_or_ill_conditioned_system"] for row in arm["selection"]["candidate_ledger"])
    assert arm["prediction_execution"] is None
    assert len(arm["predictions"]) == 5
    assert all(row["failure_reason"] == "no_candidate_selected" for row in arm["predictions"])
    assert arm["metrics"]["summary"]["requested_count"] == 5
    assert arm["metrics"]["summary"]["predicted_count"] == 0


def test_no_retained_training_columns_is_explicit_no_go_without_kernel_call(monkeypatch):
    prepared, config = small_fixture(all_missing=True)
    def forbidden(**_kwargs):
        pytest.fail("empty requested feature arm must not fit an intercept-only substitute")
    monkeypatch.setattr(numerics, "fit_select", forbidden)
    report = service._evaluate_prepared(prepared, config)
    arm = one_arm(report)
    assert report["gate"]["status"] == "no_go"
    assert len(arm["selection"]["candidate_ledger"]) == len(config["candidates"])
    assert all(row["reason_codes"] == ["arm_no_training_features"] for row in arm["selection"]["candidate_ledger"])
    assert all(row["failure_reason"] == "arm_no_training_features" for row in arm["predictions"])
    assert arm["metrics"]["summary"]["failed_count"] == 5


@pytest.mark.parametrize("change", ["unknown_source", "input_pin", "config_pin", "cohort", "duplicate_row",
                                    "target_bool", "computed_truth", "negative_truth", "family_bool", "feature_bool", "missingness_int"])
def test_malformed_prepared_scope_pins_and_records_reject_before_fit(monkeypatch, change):
    prepared, config = small_fixture()
    row = prepared["arms"][0]["rows"][0]
    if change == "unknown_source": prepared["scope"] = "client_approved"
    elif change == "input_pin": prepared["input_sha256"] = "0" * 64
    elif change == "config_pin": prepared["config_sha256"] = "0" * 64
    elif change == "cohort": prepared["arms"][0]["cohort_sha256"] = "0" * 64
    elif change == "duplicate_row": prepared["arms"][0]["rows"].append(deepcopy(row))
    elif change == "target_bool": row["label"]["value"] = True
    elif change == "computed_truth": row["label"]["knowledge_origin"] = "Computed"
    elif change == "negative_truth": row["label"]["value"] = -1
    elif change == "family_bool": row["family"] = True
    elif change == "feature_bool": row["features"][0] = True
    else: row["missingness"][0] = 0
    def forbidden(**_kwargs):
        pytest.fail("malformed preparation reached fitting")
    monkeypatch.setattr(numerics, "fit_select", forbidden)
    with pytest.raises(service.MlBaselineRehearsalError):
        service._evaluate_prepared(prepared, config)


@pytest.mark.parametrize("change", ["family", "label", "assignment", "pressure"])
def test_same_example_binding_cannot_change_across_arms(change):
    prepared, config = small_fixture()
    configured = deepcopy(config["arms"][0])
    configured["arm_id"] = "z_second"
    config["arms"].append(configured)
    arm = deepcopy(prepared["arms"][0])
    arm["arm_id"] = "z_second"
    prepared["arms"].append(arm)
    prepared["config_sha256"] = digest(config)
    row = arm["rows"][0]
    if change == "family": row["family"] = "other"
    elif change == "label": row["label"]["value"] += 1
    elif change == "assignment": row["assignment_sha256"] = "0" * 64
    else: row.update(pressure_state="reported", pressure_gpa=9)
    with pytest.raises(service.MlBaselineRehearsalError, match="shared_binding"):
        service._evaluate_prepared(prepared, config)


@pytest.mark.parametrize("change", ["boolean_policy", "unknown_policy", "extra_authority", "unknown_view", "unknown_scope",
                                    "alpha_bool", "alpha_inf", "duplicate_candidate", "unsorted_candidate", "arm_limit"])
def test_configuration_is_closed_and_strict(change):
    _, config = small_fixture()
    if change == "boolean_policy": config["refit_policy"] = False
    elif change == "unknown_policy": config["selection_rule"] = "test_mae"
    elif change == "extra_authority": config["approved"] = True
    elif change == "unknown_view": config["arms"][0]["view"] = "C@UNKNOWN"
    elif change == "unknown_scope": config["arms"][0]["feature_scope"] = "automatic"
    elif change in {"alpha_bool", "alpha_inf"}:
        config["candidates"] = [{"candidate_id": "ridge", "method": "ridge", "alpha": True if change == "alpha_bool" else float("inf")}]
    elif change == "duplicate_candidate": config["candidates"].append(deepcopy(config["candidates"][0]))
    elif change == "unsorted_candidate": config["candidates"].reverse()
    else: config["arms"] *= task_model.MAX_ARMS + 1
    with pytest.raises(task_model.MlBaselineTaskError):
        task_model.validate_baseline_task(config)


def test_cumulative_cells_are_checked_before_any_candidate_fit(monkeypatch):
    prepared, config = small_fixture()
    monkeypatch.setattr(service, "MAX_TOTAL_CELLS", 1)
    def forbidden(**_kwargs):
        pytest.fail("cumulative cell overrun reached fitting")
    monkeypatch.setattr(numerics, "fit_select", forbidden)
    with pytest.raises(service.MlBaselineRehearsalError, match="total_cell_limit"):
        service._evaluate_prepared(prepared, config)


@pytest.mark.parametrize("change", ["model", "prediction", "selection", "metric", "failure"])
def test_repinned_numerical_report_tampering_fails_full_replay(change):
    prepared, config = small_fixture()
    report = service._evaluate_prepared(prepared, config)
    arm = one_arm(report)
    if change == "model": arm["selection"]["selected_model"]["intercept"] += 1
    elif change == "prediction": arm["predictions"][0]["prediction_k"] += 1
    elif change == "selection": arm["selection"]["selected_candidate_id"] = "median"
    elif change == "metric": arm["metrics"]["summary"]["mae_k"] += 1
    else: arm["selection"]["candidate_ledger"][0]["reason_codes"] = ["forged"]
    with pytest.raises(service.MlBaselineRehearsalError, match="replay_mismatch"):
        service.verify_prepared_rehearsal(report, prepared=prepared, config=config, expected_report_sha256=digest(report))


def test_public_runner_cannot_accept_an_approval_or_supplied_package(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("unimplemented public ML-use gate must reject before all work")
    monkeypatch.setattr(service, "prepare_audited_baseline_inputs", forbidden)
    monkeypatch.setattr(numerics, "fit_select", forbidden)
    with pytest.raises(service.MlBaselineRehearsalError, match="^ml_use_authorization_unavailable$"):
        service.run_baseline_dataset(object(), approved=True, synthetic=True)
    with pytest.raises(TypeError):
        service.run_synthetic_rehearsal(package=object())
