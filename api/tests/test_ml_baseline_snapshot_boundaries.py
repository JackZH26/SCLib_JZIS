"""Synthetic snapshot/TOCTOU regressions, not scientific admission evidence.

The preparation verifier double isolates ownership and post-verification pin
checks. Real SQL/capsule verification canaries are in the native integration
module; the fitting/replay boundary tests here use the actual tiny toy kernel.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from importlib.resources import files

import pytest

from services import ml_baseline_numerics as numerics
from services import ml_baseline_rehearsal as service
from services.ml_audited_dataset import canonical, digest
from tests.test_ml_baseline_rehearsal import small_fixture


def preparation_double():
    """Only the projection seam's fields: explicitly NOT a valid capsule."""
    prepared, config = small_fixture()
    arm = prepared["arms"][0]
    rows = [
        dict(deepcopy(row), claim_id=f"synthetic-claim-{index}")
        for index, row in enumerate(arm["rows"])
    ]
    view = {
        "feature_names": list(arm["feature_names"]),
        "rows": rows,
        "preprocessing": {"parameters": deepcopy(arm["preprocessing"]["parameters"])},
        "cohort_sha256": arm["cohort_sha256"],
    }
    package = {
        "version": "synthetic-projection-unit-double-not-an-audited-package",
        "gate": {"status": "pass"},
        "base_dataset": {
            "rows": deepcopy(rows),
            "views": {"C@B": view},
            "coverage": {"rows": len(rows)},
        },
        "identity_audit": {"counts": []},
    }
    manifest = {
        "version": "synthetic-projection-unit-double-not-a-capsule",
        "rows": [
            {
                "table": "material_claims",
                "row_id": row["claim_id"],
                "data": {
                    "pressure_state": row["pressure_state"],
                    "pressure_gpa": row["pressure_gpa"],
                },
            }
            for row in rows
        ],
    }
    config["input_sha256"] = digest(package)
    return (
        package,
        config,
        {
            "manifest": manifest,
            "expected_manifest_sha256": digest(manifest),
        },
    )


def prepare(package, config, arguments):
    return service.prepare_audited_baseline_inputs(
        package,
        expected_package_sha256=digest(package),
        config=config,
        expected_config_sha256=digest(config),
        **arguments,
    )


@pytest.mark.parametrize("field", ["features", "label", "identity_counts", "manifest_pressure"])
def test_mutating_passed_verified_snapshot_cannot_return_old_pin_new_values(monkeypatch, field):
    package, config, arguments = preparation_double()
    originals = deepcopy((package, config, arguments))
    checked = []

    def verify(passed, *, expected_package_sha256, **inputs):
        assert digest(passed) == expected_package_sha256
        assert digest(inputs["manifest"]) == inputs["expected_manifest_sha256"]
        assert passed is not package
        assert inputs["manifest"] is not arguments["manifest"]
        checked.append(True)
        row = passed["base_dataset"]["views"]["C@B"]["rows"][0]
        if field == "features":
            row["features"][0] += 10.0
        elif field == "label":
            row["label"]["value"] += 10.0
        elif field == "identity_counts":
            passed["identity_audit"]["counts"].append({"synthetic": "substituted"})
        else:
            inputs["manifest"]["rows"][0]["data"].update(
                pressure_state="reported", pressure_gpa=10.0
            )

    monkeypatch.setattr(service, "verify_audited_task_dataset", verify)
    with pytest.raises(service.MlBaselineRehearsalError, match="independent_pin_mismatch"):
        prepare(package, config, arguments)
    assert checked == [True]
    assert (package, config, arguments) == originals


@pytest.mark.parametrize("field", ["package", "manifest", "configuration"])
def test_caller_mutation_after_capture_does_not_change_detached_preparation(monkeypatch, field):
    package, config, arguments = preparation_double()
    initial_package, initial_config, initial_arguments = deepcopy((package, config, arguments))

    def verify(passed, *, expected_package_sha256, **inputs):
        assert canonical(passed) == canonical(initial_package)
        assert canonical(inputs["manifest"]) == canonical(initial_arguments["manifest"])
        if field == "package":
            package["base_dataset"]["views"]["C@B"]["rows"][0]["features"][0] += 10.0
        elif field == "manifest":
            arguments["manifest"]["rows"][0]["data"].update(
                pressure_state="reported", pressure_gpa=10.0
            )
        else:
            config["candidates"].clear()

    monkeypatch.setattr(service, "verify_audited_task_dataset", verify)
    result = prepare(package, config, arguments)
    assert result["input_sha256"] == digest(initial_package)
    assert result["config_sha256"] == digest(initial_config)
    actual = result["arms"][0]["rows"][0]
    expected = initial_package["base_dataset"]["views"]["C@B"]["rows"][0]
    assert actual["features"] == expected["features"]
    assert actual["pressure_state"] == "not_reported"
    assert actual["pressure_gpa"] is None
    service._validate_prepared(result, initial_config)


def test_configuration_projection_mutation_is_rechecked(monkeypatch):
    package, config, arguments = preparation_double()
    monkeypatch.setattr(service, "verify_audited_task_dataset", lambda *args, **kwargs: None)
    project = service._project

    def changed(view, arm, conditions):
        result = project(view, arm, conditions)
        arm["arm_id"] = "mutated"
        return result

    monkeypatch.setattr(service, "_project", changed)
    with pytest.raises(service.MlBaselineRehearsalError, match="independent_pin_mismatch"):
        prepare(package, config, arguments)


@pytest.mark.parametrize("field", ["candidates", "selection_rule", "task_id"])
def test_config_changed_during_actual_fit_cannot_be_reported_as_original(monkeypatch, field):
    prepared, config = small_fixture()
    fit = numerics.fit_select
    calls = []

    def changed(**kwargs):
        result = fit(**kwargs)
        calls.append(result["selected_candidate_id"])
        if field == "candidates":
            config["candidates"].pop()
        elif field == "selection_rule":
            config["selection_rule"] = "test_mae"
        else:
            config["task_id"] = "substituted_after_fit"
        return result

    monkeypatch.setattr(numerics, "fit_select", changed)
    with pytest.raises(service.MlBaselineRehearsalError, match="configuration_mutated"):
        service._evaluate_prepared(prepared, config)
    assert calls == ["ols"]


def test_two_arms_cannot_silently_use_different_candidate_grids(monkeypatch):
    prepared, config = small_fixture()
    second = deepcopy(config["arms"][0])
    second["arm_id"] = "z_second"
    config["arms"].append(second)
    prepared["arms"].append(dict(deepcopy(prepared["arms"][0]), arm_id="z_second"))
    prepared["config_sha256"] = digest(config)
    fit, grid_sizes = numerics.fit_select, []

    def changed(**kwargs):
        grid_sizes.append(len(kwargs["candidates"]))
        result = fit(**kwargs)
        if len(grid_sizes) == 1:
            config["candidates"].pop()
        return result

    monkeypatch.setattr(numerics, "fit_select", changed)
    with pytest.raises(service.MlBaselineRehearsalError, match="configuration_mutated"):
        service._evaluate_prepared(prepared, config)
    assert grid_sizes == [2, 1]


@pytest.mark.parametrize("field", ["gate", "authority", "prediction"])
def test_prepared_verifier_refuses_supplied_report_mutation_during_replay(monkeypatch, field):
    prepared, config = small_fixture()
    report = service._evaluate_prepared(prepared, config)
    original, expected = deepcopy(report), digest(report)

    def replay(*args, **kwargs):
        if field == "gate":
            report["gate"]["status"] = "no_go"
        elif field == "authority":
            report["authority"]["ml_training_approved"] = True
        else:
            report["arms"][0]["predictions"][0]["prediction_k"] += 1.0
        return deepcopy(original)

    monkeypatch.setattr(service, "_evaluate_prepared", replay)
    with pytest.raises(service.MlBaselineRehearsalError, match="replay_mismatch"):
        service.verify_prepared_rehearsal(
            report, prepared=prepared, config=config, expected_report_sha256=expected
        )


@pytest.mark.parametrize("field", ["gate", "authority", "implementation"])
def test_fixed_receipt_verifier_refuses_input_mutation_during_replay(monkeypatch, field):
    receipt = service.run_synthetic_rehearsal()
    original, expected = deepcopy(receipt), digest(receipt)

    def replay():
        if field == "gate":
            receipt["report"]["gate"]["status"] = "no_go"
        elif field == "authority":
            receipt["authority"]["public_release"] = True
        else:
            receipt["implementation"]["python"] = "substituted runtime"
        return deepcopy(original)

    monkeypatch.setattr(service, "run_synthetic_rehearsal", replay)
    with pytest.raises(service.MlBaselineRehearsalError, match="replay_mismatch"):
        service.verify_synthetic_rehearsal(receipt, expected_receipt_sha256=expected)


@pytest.mark.parametrize(
    "field", ["source_sha256", "api_lock_sha256", "python", "numerical_policy"]
)
def test_runtime_and_implementation_change_during_fixed_run_refuses_receipt(monkeypatch, field):
    initial = service._implementation()
    changed = deepcopy(initial)
    if field == "source_sha256":
        changed[field]["services.ml_dataset_builder"] = "0" * 64
    elif field == "numerical_policy":
        changed[field]["pivot_absolute_tolerance"] = 0.0
    else:
        changed[field] = "0" * 64
    observations = iter([initial, changed])
    monkeypatch.setattr(service, "_implementation", lambda: next(observations))
    with pytest.raises(service.MlBaselineRehearsalError, match="implementation_changed"):
        service.run_synthetic_rehearsal()


def test_actual_source_inventory_binds_authority_and_canonical_dependencies():
    implementation = service._implementation()
    for name in ("services.ml_dataset_builder", "services.research_release_manifest"):
        package, module = name.rsplit(".", 1)
        expected = hashlib.sha256(files(package).joinpath(module + ".py").read_bytes()).hexdigest()
        assert implementation["source_sha256"][name] == expected
    assert implementation["api_lock_sha256"]
    assert implementation["verification"] == "exact_replay_in_identical_recorded_runtime"
