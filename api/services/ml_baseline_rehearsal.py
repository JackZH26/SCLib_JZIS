"""Private numerical engineering rehearsal; no general real-dataset fit path.

Preparation re-verifies an audited package but cannot authorize model training.
Only the no-argument implementation-owned synthetic rehearsal is executable by
the public service/CLI. The private numerical seam is for owned test fixtures,
not an authentication boundary, scientific review or real-data authorization.
"""
from __future__ import annotations

import itertools
import json
import math
import platform
import sys
from copy import deepcopy
from importlib.resources import files
from pathlib import Path

from models.ml_baseline_task import HASH, make_baseline_task, validate_baseline_task
from services import ml_baseline_metrics as metrics
from services import ml_baseline_numerics as numerics
from services.ml_audited_dataset import canonical, digest, verify_audited_task_dataset
from services.ml_composition import FEATURE_NAMES, composition_features
from services.ml_dataset_builder import AUTHORITY
from services.ml_preprocessing import fit_transform
from services.research_release_manifest import canonical as capsule_canonical

VERSION = "ml-baseline-rehearsal/1.0.0"
PREPARED_VERSION = "ml-baseline-prepared-views/1.0.0"
FIXTURE_VERSION = "ml09-owned-numerical-fixture/1.0.0"
CONDITIONS = ["reported_pressure_gpa", "reported_magnetic_field_t"]
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_TOTAL_CELLS = 120_000
_RECORD_FIELDS = ("example_id", "group_id", "assignment_sha256", "split", "family",
                  "pressure_state", "pressure_gpa", "label")
_ARM_FIELDS = {"arm_id", "view", "feature_scope", "feature_names", "selected_feature_names",
               "preprocessing", "cohort_sha256", "rows"}
_ROW_FIELDS = {*_RECORD_FIELDS, "features", "missingness"}
_SOURCE_MODULES = (
    "models.ml_baseline_task", "services.ml_baseline_rehearsal", "services.ml_baseline_numerics",
    "services.ml_baseline_metrics", "services.ml_preprocessing", "services.ml_composition",
    "services.ml_audited_dataset", "services.ml_identity_audit", "services.ml_dataset_builder",
    "services.research_release_manifest",
    "services._composition.formula_enrichment", "services._composition.formula_validator",
)


class MlBaselineRehearsalError(ValueError):
    """Static error without scientific input values, IDs or paths."""


def _require(condition, code="ml_baseline_rehearsal_invalid"):
    if not condition:
        raise MlBaselineRehearsalError(code)


def _bounded(value):
    raw = canonical(value)
    _require(len(raw) <= MAX_REPORT_BYTES, "ml_baseline_rehearsal_byte_limit")
    return raw


def _pin(value, expected):
    _require(type(expected) is str and HASH.fullmatch(expected) and digest(value) == expected,
             "ml_baseline_independent_pin_mismatch")


def run_baseline_dataset(*_args, **_kwargs):
    """Real ML-use admission is not implemented; reject before reading or fitting."""
    raise MlBaselineRehearsalError("ml_use_authorization_unavailable")


def draft_task_for_package(package, *, views=None):
    """Read-only draft of explicit columns, not approval or held-out selection."""
    try:
        inventory = package["base_dataset"]["views"]
        selected = sorted(inventory) if views is None else views
        _require(type(selected) is list and selected == sorted(set(selected)) and selected)
        arms = []
        for name in selected:
            _require(name in inventory)
            arms.append({"arm_id": "view_" + name.replace("@", "_"), "view": name,
                         "feature_scope": "view_all", "feature_names": list(inventory[name]["feature_names"])})
        if "C@B" in selected and all(name in inventory["C@B"]["feature_names"] for name in CONDITIONS):
            arms.append({"arm_id": "composition_only_B", "view": "C@B", "feature_scope": "composition",
                         "feature_names": list(FEATURE_NAMES)})
        return make_baseline_task(digest(package), sorted(arms, key=lambda arm: arm["arm_id"]))
    except MlBaselineRehearsalError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise MlBaselineRehearsalError("ml_baseline_draft_invalid") from None


def _project(view, arm, conditions):
    """Column-only projection of independently fitted verified preprocessing."""
    names = view["feature_names"]
    desired = arm["feature_names"]
    expected = (list(FEATURE_NAMES) if arm["feature_scope"] == "composition" else
                list(FEATURE_NAMES) + CONDITIONS if arm["feature_scope"] == "composition_conditions" else names)
    _require(desired == expected and all(name in names for name in desired), "ml_baseline_feature_semantics_mismatch")
    _require(view["preprocessing"] is not None, "ml_baseline_preprocessing_unavailable")
    original = view["preprocessing"]["parameters"]
    indices = [index for index, name in enumerate(original["selected_feature_names"]) if name in desired]
    selected = [original["selected_feature_names"][index] for index in indices]
    raw_indices = [names.index(name) for name in desired]
    statistics = [{**item, "index": desired.index(item["name"])} for item in original["statistics"] if item["name"] in desired]
    projection = {
        "scope": "column_projection_of_verified_train_fitted_view",
        "source_parameters_sha256": digest(original),
        "parameters": {"config": original["config"], "feature_names": desired,
            "selected_indices": [desired.index(name) for name in selected], "selected_feature_names": selected,
            "statistics": statistics, "train_row_count": original["train_row_count"],
            "dropped_features": [{**item, "index": desired.index(item["name"])} for item in original["dropped_features"]
                                 if item["name"] in desired]},
    }
    rows = []
    for source in view["rows"]:
        row = {key: deepcopy(source[key]) for key in _RECORD_FIELDS if key not in {"pressure_state", "pressure_gpa"}}
        row.update(conditions[source["example_id"]])
        row["features"] = [source["features"][index] for index in indices]
        row["missingness"] = [source["missingness"][index] for index in raw_indices]
        rows.append(row)
    return {**deepcopy(arm), "selected_feature_names": selected, "preprocessing": projection,
            "cohort_sha256": view["cohort_sha256"], "rows": sorted(rows, key=lambda row: row["example_id"])}


def prepare_audited_baseline_inputs(package, *, expected_package_sha256, config, expected_config_sha256, **inputs):
    """Recompute dataset and prepare views only; never invoke a model fit."""
    try:
        validate_baseline_task(config)
        _pin(config, expected_config_sha256)
        config = json.loads(canonical(config))
        _require(config["input_sha256"] == expected_package_sha256, "ml_baseline_dataset_config_mismatch")
        # Project only detached package/label-row snapshots, not caller-owned
        # mappings that can change after their verification boundary. Other
        # independently pinned inputs are consumed by the unchanged verifier.
        _pin(package, expected_package_sha256)
        package = json.loads(canonical(package))
        inputs = dict(inputs)
        manifest_bytes = capsule_canonical(inputs["manifest"])
        _require(len(manifest_bytes) <= 8 * 1024 * 1024, "ml_baseline_manifest_budget")
        inputs["manifest"] = json.loads(manifest_bytes)
        verify_audited_task_dataset(package, expected_package_sha256=expected_package_sha256, **inputs)
        _require(package["gate"]["status"] == "pass", "ml_baseline_dataset_technical_no_go")
        base = package["base_dataset"]
        index = {(row["table"], row["row_id"]): row["data"] for row in inputs["manifest"]["rows"]}
        conditions = {row["example_id"]: {key: index[("material_claims", row["claim_id"])][key]
                      for key in ("pressure_state", "pressure_gpa")} for row in base["rows"]}
        arms = [_project(base["views"][arm["view"]], arm, conditions) for arm in config["arms"]]
        result = {"version": PREPARED_VERSION, "input_sha256": expected_package_sha256,
            "config_sha256": expected_config_sha256, "scope": "read_only_verified_audited_package_not_fit_authorization",
            "arms": arms, "identity_counts": deepcopy(package["identity_audit"]["counts"]),
            "base_coverage": deepcopy(base["coverage"])}
        _pin(package, expected_package_sha256)
        _pin(inputs["manifest"], inputs["expected_manifest_sha256"])
        _pin(config, expected_config_sha256)
        _validate_prepared(result, config)
        return json.loads(_bounded(result))
    except MlBaselineRehearsalError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise MlBaselineRehearsalError("ml_baseline_preparation_failed") from None


def _record(row, prediction=None, failure="no_candidate_selected"):
    return {**{key: deepcopy(row[key]) for key in _RECORD_FIELDS},
            "prediction_k": prediction, "failure_reason": failure}


def _validate_prepared(prepared, config):
    """Structural numerical checks, not a claim of authenticated source bytes."""
    validate_baseline_task(config)
    _bounded(prepared)
    _require(type(prepared) is dict and set(prepared) == {
        "version", "input_sha256", "config_sha256", "scope", "arms", "identity_counts", "base_coverage"})
    _require(prepared["version"] == PREPARED_VERSION and prepared["input_sha256"] == config["input_sha256"]
             and prepared["config_sha256"] == digest(config))
    _require(prepared["scope"] in {"read_only_verified_audited_package_not_fit_authorization", "implementation_owned_numerical_fixture"})
    _require(type(prepared["arms"]) is list and len(prepared["arms"]) == len(config["arms"]))
    cells, shared, group_splits = 0, {}, {}
    for arm, configured in zip(prepared["arms"], config["arms"], strict=True):
        _require(type(arm) is dict and set(arm) == _ARM_FIELDS
                 and all(arm[key] == configured[key] for key in configured))
        names = arm["selected_feature_names"]
        _require(type(names) is list and names == [name for name in arm["feature_names"] if name in names])
        rows = arm["rows"]
        _require(type(rows) is list and 0 < len(rows) <= 100)
        _require([row["example_id"] for row in rows] == sorted({row["example_id"] for row in rows}))
        _require(arm["cohort_sha256"] == digest([row["example_id"] for row in rows]), "ml_baseline_cohort_mismatch")
        _require(all(type(row) is dict and set(row) == _ROW_FIELDS for row in rows))
        metrics.validate_prediction_records([_record(row) for row in rows])
        for row in rows:
            _require(type(row["features"]) is list and len(row["features"]) == len(names)
                     and all(type(value) in {int, float} and math.isfinite(value) for value in row["features"]))
            _require(type(row["missingness"]) is list and len(row["missingness"]) == len(arm["feature_names"])
                     and all(type(value) is bool for value in row["missingness"]))
            cells += len(row["features"]) + len(row["missingness"])
            binding = _record(row)
            _require(shared.setdefault(row["example_id"], binding) == binding, "ml_baseline_shared_binding_mismatch")
            _require(group_splits.setdefault(row["group_id"], row["split"]) == row["split"], "ml_baseline_component_crossing")
    _require(cells <= MAX_TOTAL_CELLS, "ml_baseline_total_cell_limit")


def _evaluate_prepared(prepared, config):
    """Private owned-test numerical seam, NOT a real-data authorization service."""
    try:
        _validate_prepared(prepared, config)
        before = digest(prepared)
        config_before = digest(config)
        results = []
        for arm in prepared["arms"]:
            rows = arm["rows"]
            train = [row for row in rows if row["split"] == "train"]
            validation = [row for row in rows if row["split"] == "validation"]
            # No test rows or test targets cross this fit/select call boundary.
            if not arm["selected_feature_names"]:
                selection = {"version": numerics.VERSION, "selection_rule": config["selection_rule"],
                    "numerical_policy": deepcopy(numerics.NUMERICAL_POLICY),
                    "candidate_ledger": [{**deepcopy(item), "fit_status": "failed", "status": "failed",
                        "reason_codes": ["arm_no_training_features"], "model": None,
                        "validation_predictions": None, "validation_mae": None} for item in config["candidates"]],
                    "selected_candidate_id": None, "selected_model": None, "status": "no_go"}
            else:
                selection = numerics.fit_select(
                    train_matrix=[row["features"] for row in train], train_targets=[row["label"]["value"] for row in train],
                    train_families=[row["family"] for row in train],
                    validation_matrix=[row["features"] for row in validation], validation_targets=[row["label"]["value"] for row in validation],
                    validation_families=[row["family"] for row in validation],
                    feature_names=arm["selected_feature_names"], candidates=config["candidates"])
            model = selection["selected_model"]
            predicted = None
            if model is None:
                failure = "arm_no_training_features" if not arm["selected_feature_names"] else "no_candidate_selected"
                records = [_record(row, failure=failure) for row in rows]
            else:
                predicted = numerics.predict(model=model, matrix=[row["features"] for row in rows],
                                              families=[row["family"] for row in rows])
                _require(predicted["requested_count"] == len(rows) and len(predicted["rows"]) == len(rows))
                records = [_record(row, item["value"], item["reason_codes"][0] if item["reason_codes"] else None)
                           for row, item in zip(rows, predicted["rows"], strict=True)]
            missing = {partition: {"rows": sum(row["split"] == partition for row in rows),
                "missing_counts": [sum(row["missingness"][index] for row in rows if row["split"] == partition)
                                   for index in range(len(arm["feature_names"]))]}
                       for partition in ("train", "validation", "test")}
            results.append({key: deepcopy(arm[key]) for key in (
                "arm_id", "view", "feature_scope", "feature_names", "selected_feature_names", "preprocessing", "cohort_sha256")})
            results[-1].update(selection=selection, prediction_execution=predicted, predictions=records,
                               metrics=metrics.score_predictions(records), missingness=missing)
        comparisons = [{"left_arm": left["arm_id"], "right_arm": right["arm_id"],
                        "report": metrics.compare_prediction_arms(left["predictions"], right["predictions"])}
                       for left, right in itertools.combinations(results, 2)]
        failed = [arm["arm_id"] for arm in results if arm["selection"]["status"] != "selected"]
        _require(before == digest(prepared), "ml_baseline_prepared_mutated")
        _require(config_before == digest(config), "ml_baseline_configuration_mutated")
        result = {"version": VERSION,
            "input_pins": {"input_sha256": prepared["input_sha256"], "config_sha256": digest(config), "prepared_sha256": before},
            "configuration": deepcopy(config), "arms": results, "comparisons": comparisons,
            "identity_counts": deepcopy(prepared["identity_counts"]), "base_coverage": deepcopy(prepared["base_coverage"]),
            "gate": {"status": "no_go" if failed else "pass", "failed_arms": failed,
                     "reason_codes": ["no_eligible_candidate_in_required_arm"] if failed else []},
            "authority": dict(AUTHORITY), "independent_support_count": None,
            "model_card": {"scope": "numerical_engineering_rehearsal_not_scientific_evaluation",
                "input_integrity": "numerical_seam_does_not_authenticate_or_authorize_supplied_data",
                "selection": config["selection_rule"], "test_targets_used_for_fit_or_selection": False,
                "post_selection_refit": False, "predictions_clipped": False, "log_metrics": False,
                "uncertainty": None, "recommendation": "no_scientific_continue_narrow_stop_conclusion",
                "limitations": ["exact_positive_observed_tc_only", "independent_experimental_units_unknown",
                    "synthetic_results_not_superconductor_accuracy", "no_general_real_dataset_execution",
                    "nested_subset_improvement_not_causal_feature_value"]}}
        return json.loads(_bounded(result))
    except MlBaselineRehearsalError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise MlBaselineRehearsalError("ml_baseline_numerical_rehearsal_failed") from None


def verify_prepared_rehearsal(report, *, prepared, config, expected_report_sha256):
    """Repeat a test seam; this receipt is NOT real-data or release admission."""
    _pin(report, expected_report_sha256)
    captured = _bounded(report)
    rebuilt = _evaluate_prepared(prepared, config)
    _require(captured == _bounded(rebuilt) and captured == _bounded(report), "ml_baseline_replay_mismatch")
    return {"version": VERSION, "report_sha256": expected_report_sha256,
            "numerical_replay_verified": True, "technical_gate": rebuilt["gate"]["status"], **AUTHORITY}


def _owned_fixture():
    """Fixed numerical values invented for engineering tests, not source records."""
    formulas = ["MgB2", "Nb", "Ta", "Al", "Pb", "Sn", "LaH10", "H3S", "FeSe", "NbN", "YB6", "CaC6"]
    rows = []
    for index, formula in enumerate(formulas):
        split = "train" if index < 6 else "validation" if index < 9 else "test"
        identifier = f"owned-toy-{index:02d}"
        descriptor = composition_features({"formula": formula, "formula_normalized": formula,
                                           "records": [], "status": "active"})
        _require(descriptor["status"] == "computed", "ml_baseline_owned_fixture_invalid")
        rows.append({"example_id": identifier, "group_id": digest([FIXTURE_VERSION, identifier]),
            "assignment_sha256": digest([FIXTURE_VERSION, identifier, split]), "split": split,
            "family": "toy-family-" + str(index % 3), "pressure_state": "reported", "pressure_gpa": float(index),
            "label": {"value": float(8 + 3 * index + index % 2), "unit": "K", "tc_definition": "zero_resistance",
                      "knowledge_origin": "Observed", "value_relation": "exact"},
            "raw_features": descriptor["values"] + [float(index), None if index in {2, 8, 11} else float(index % 2)],
            "structure_features": [float(10 + index), float(2 + index / 10)]})
    definition = {"version": FIXTURE_VERSION, "disclosure": "invented_values_not_measured_materials", "rows": rows}
    source_pin = digest(definition)
    base_names = list(FEATURE_NAMES) + CONDITIONS
    specifications = [("C@B", rows, base_names), ("C@S", [row for index, row in enumerate(rows) if index not in {1, 7, 11}], base_names),
                      ("CS@S", [row for index, row in enumerate(rows) if index not in {1, 7, 11}], base_names + ["volume_per_atom_a3", "density_g_cm3"])]
    views = {}
    conditions = {row["example_id"]: {key: row[key] for key in ("pressure_state", "pressure_gpa")} for row in rows}
    for name, selected, names in specifications:
        raw = [row["raw_features"] + (row["structure_features"] if name == "CS@S" else []) for row in selected]
        fitted = fit_transform(raw, [row["split"] for row in selected], names)
        views[name] = {"feature_names": names, "preprocessing": fitted,
            "cohort_sha256": digest(sorted(row["example_id"] for row in selected)),
            "rows": [{**{key: deepcopy(row[key]) for key in _RECORD_FIELDS}, "features": values, "missingness": missing}
                     for row, values, missing in zip(selected, fitted["transformed"], fitted["missingness"], strict=True)]}
    configured = [{"arm_id": "composition_B", "view": "C@B", "feature_scope": "composition", "feature_names": list(FEATURE_NAMES)},
                  {"arm_id": "conditions_B", "view": "C@B", "feature_scope": "composition_conditions", "feature_names": base_names},
                  {"arm_id": "conditions_S", "view": "C@S", "feature_scope": "view_all", "feature_names": base_names},
                  {"arm_id": "structure_S", "view": "CS@S", "feature_scope": "view_all", "feature_names": specifications[-1][2]}]
    config = make_baseline_task(source_pin, configured)
    prepared = {"version": PREPARED_VERSION, "input_sha256": source_pin, "config_sha256": digest(config),
        "scope": "implementation_owned_numerical_fixture", "arms": [_project(views[arm["view"]], arm, conditions) for arm in configured],
        "identity_counts": None, "base_coverage": {"synthetic_rows": len(rows), "independent_support_count": None}}
    return definition, config, prepared


def _implementation():
    import hashlib
    mapping = {}
    for name in _SOURCE_MODULES:
        package, module = name.rsplit(".", 1)
        data = files(package).joinpath(module + ".py").read_bytes()
        _require(0 < len(data) <= 1024 * 1024, "ml_baseline_source_budget")
        mapping[name] = hashlib.sha256(data).hexdigest()
    lock = Path(__file__).resolve().parents[1] / "uv.lock"
    data = lock.read_bytes()
    _require(0 < len(data) <= 4 * 1024 * 1024, "ml_baseline_lock_budget")
    return {"source_sha256": mapping, "api_lock_sha256": hashlib.sha256(data).hexdigest(),
            "python": sys.version, "implementation": platform.python_implementation(),
            "machine": platform.machine(), "byteorder": sys.byteorder,
            "numerical_policy": deepcopy(numerics.NUMERICAL_POLICY),
            "verification": "exact_replay_in_identical_recorded_runtime"}


def run_synthetic_rehearsal():
    """The only public fit entry point: no user dataset/config/approval arguments."""
    implementation = _implementation()
    definition, config, prepared = _owned_fixture()
    report = _evaluate_prepared(prepared, config)
    _require(implementation == _implementation(), "ml_baseline_implementation_changed")
    result = {"version": VERSION, "scope": "fixed_implementation_owned_synthetic_rehearsal",
        "fixture_version": FIXTURE_VERSION, "fixture_sha256": digest(definition),
        "implementation": implementation, "implementation_sha256": digest(implementation),
        "report": report, "report_sha256": digest(report), "authority": dict(AUTHORITY)}
    return json.loads(_bounded(result))


def verify_synthetic_rehearsal(receipt, *, expected_receipt_sha256):
    _pin(receipt, expected_receipt_sha256)
    captured = _bounded(receipt)
    rebuilt = run_synthetic_rehearsal()
    _require(captured == _bounded(rebuilt) and captured == _bounded(receipt), "ml_baseline_replay_mismatch")
    return {"version": VERSION, "receipt_sha256": expected_receipt_sha256,
            "numerical_replay_verified": True, "technical_gate": rebuilt["report"]["gate"]["status"], **AUTHORITY}
