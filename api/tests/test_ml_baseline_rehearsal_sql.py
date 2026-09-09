"""Synthetic SQL capture-to-numerical-rehearsal integration, not ML permission.

The private evaluator is a numerical test seam, not a training authorization
boundary. Public entry points must reject supplied datasets before any fitting;
only their implementation-owned fixed toy may be evaluated by the public CLI.
All SQL below runs on capability-owned disposable services through the guarded
runner. Existing fixture cleanup tracks only the Materials created by this test.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from models.db import Base
from models.ml_task_v2 import selector_for
from services.ml_audited_dataset import build_audited_task_dataset
from services.ml_audited_dataset import digest as package_digest
from services.ml_dataset_builder_v4 import build_task_dataset_v4
from services.research_release_manifest import canonical, digest
from tests.test_ml_dataset_v4 import compiler_inputs
from tests.test_ml_label_capture import db_session as db_session
from tests.test_ml_label_capture import label_fixture
from tests.test_ml_physical_feature_sql import computed_property
from tests.test_ml_task_dataset_sql import eligible_specs
from tests.test_research_freeze import state


def prepare(fixture, *, views=None, config=None):
    from services import ml_baseline_rehearsal as service

    package = fixture["package"]
    config = service.draft_task_for_package(package, views=views) if config is None else config
    prepared = service.prepare_audited_baseline_inputs(
        package, expected_package_sha256=package_digest(package), config=config,
        expected_config_sha256=digest(config), **fixture["arguments"],
    )
    return prepared, config


async def baseline_fixture(db, *, features=False, test_target_delta=0.0, target_derived=False,
                           feature_budget="composition"):
    """Build genuine five-input captures with fixed 3/1/1 synthetic partitions.

    Family assignments are written before freezing, so random database IDs do
    not change which declared synthetic observations are held out. A target
    perturbation creates a new fixture; no frozen Claim or QC row is rewritten.
    This helper is test-only and supplies no authorization to public runners.
    """
    specs = eligible_specs()
    specs[-1]["tc"] += test_target_delta
    chain = []

    async def configure(db, fixture):
        materials = Base.metadata.tables["materials"]
        for key, candidate in fixture["candidates"].items():
            family = {"four": "fixture-validation", "five": "fixture-test"}.get(key, "fixture-train")
            await db.execute(materials.update().where(materials.c.id == candidate["material"]["id"]).values(family=family))
        if target_derived:
            assert features
            candidate = fixture["candidates"]["one"]
            dependency = {"table": "material_claims", "row_id": candidate["claim"]["id"], "event_id": candidate["event"]["id"]}
            for name in ("electron_phonon_lambda", "dos_at_fermi"):
                item = await computed_property(
                    db, fixture, "one", name, structure=fixture["structures"]["one"],
                    protocol=fixture["protocols"][name], settings=fixture["settings"][name],
                    reference_artifacts=fixture["reference_artifacts"], value=1.5,
                    dependencies=[dependency],
                    feature_key="renamed-normal-state-descriptor" if name == "dos_at_fermi" else name,
                )
                fixture["physics"]["one"][name] = item
                fixture["task"]["physical_features"].append(selector_for(fixture["protocols"][name]))
                chain.append(item)
                dependency = {"table": "event_properties", "row_id": item["property"]["id"], "event_id": item["event"]["id"]}
            fixture["task"]["physical_features"].sort(key=lambda item: item["feature_key"])

    seeded = await label_fixture(db, features=features, specs=specs, before_freeze=configure)
    task = deepcopy(seeded["inputs"]["task"])
    task["label_task"]["feature_budget"] = feature_budget
    task["label_task"]["split"].update(
        mode="family_holdout", validation_families=["fixture-validation"], test_families=["fixture-test"],
    )
    arguments = compiler_inputs(seeded, task=task)
    before = await state(db)
    original = build_task_dataset_v4(**arguments)
    package = build_audited_task_dataset(**arguments)
    assert before == await state(db)
    assert canonical(package["base_dataset"]) == canonical(original)
    assert package["base_dataset_sha256"] == digest(original)
    assert package["gate"]["status"] == "pass"
    assert all(value is False for value in package["authority"].values())
    keys = {str(item["example"]["id"]): key for key, item in seeded["fixture"]["candidates"].items()}
    assert {keys[row["example_id"]]: row["split"] for row in original["rows"]} == {
        "one": "train", "two": "train", "three": "train", "four": "validation", "five": "test",
    }
    return {"seeded": seeded, "arguments": arguments, "package": package,
            "original": original, "keys": keys, "chain": chain}


@pytest.mark.parametrize("features", [False, True])
async def test_native_fixture_retains_five_pins_fixed_partitions_and_old_v4_bytes(db_session, features, monkeypatch):
    from services import ml_baseline_numerics as numerics
    from services import ml_baseline_rehearsal as service

    fixture = await baseline_fixture(db_session, features=features)
    arguments, package = fixture["arguments"], fixture["package"]
    before = await state(db_session)
    original_package = canonical(package)

    def no_fit(*args, **kwargs):
        raise AssertionError("read-only preparation attempted a model fit")

    with monkeypatch.context() as patch:
        patch.setattr(numerics, "fit_select", no_fit)
        if hasattr(service, "fit_select"):
            patch.setattr(service, "fit_select", no_fit)
        prepared, config = prepare(fixture)
        assert prepare(fixture) == (prepared, config)
    assert before == await state(db_session)
    assert canonical(package) == original_package
    assert len(prepared["arms"]) == (9 if features else 1)
    for arm in prepared["arms"]:
        assert len(arm["rows"]) == 5
        assert {row["split"] for row in arm["rows"]} == {"train", "validation", "test"}
        assert arm["preprocessing"]["parameters"]["train_row_count"] == 3
    # This is deliberately a private numerical test seam on synthetic values.
    # A verified package does not make the public dataset runner available.
    report = service._evaluate_prepared(prepared, config)
    assert report["gate"]["status"] == "pass"
    assert report == service._evaluate_prepared(prepared, config)
    service.verify_prepared_rehearsal(report, prepared=prepared, config=config,
                                      expected_report_sha256=digest(report))
    assert all(value is False for value in report["authority"].values())
    for arm in report["arms"]:
        assert len(arm["selection"]["candidate_ledger"]) == len(config["candidates"])
        assert arm["selection"]["selected_model"]["training_row_count"] == 3
        assert len(arm["predictions"]) == 5
        family = next(row for row in arm["selection"]["candidate_ledger"] if row["method"] == "family_median_train")
        assert [item["family"] for item in family["model"]["family_medians"]] == ["fixture-train"]
        assert family["validation_predictions"]["rows"][0]["fallback_used"] is True
        ols = next(row for row in arm["selection"]["candidate_ledger"] if row["method"] == "ols")
        assert ols["fit_status"] == "failed" and "singular_or_ill_conditioned_system" in ols["reason_codes"]
    if not features:
        def alter_model(value):
            model = value["arms"][0]["selection"]["selected_model"]
            if model["coefficients"]:
                model["coefficients"][0] += 1.0
            else:
                model["global_median"] += 1.0

        changes = [
            alter_model,
            lambda value: value["arms"][0]["predictions"][0].update(prediction_k=-123.0),
            lambda value: value["arms"][0]["selection"]["candidate_ledger"].pop(),
            lambda value: value["arms"][0]["selection"].update(selected_candidate_id="forged_selection"),
            lambda value: value["arms"][0]["metrics"]["summary"].update(mae_k=0.0),
            lambda value: value["arms"][0]["metrics"]["summary"].update(requested_count=4),
            lambda value: value["authority"].update(ml_training_approved=True),
        ]
        for change in changes:
            tampered = deepcopy(report)
            change(tampered)
            with pytest.raises(ValueError):
                service.verify_prepared_rehearsal(tampered, prepared=prepared, config=config,
                                                  expected_report_sha256=digest(tampered))
        singular_config = deepcopy(config)
        singular_config["candidates"] = [item for item in config["candidates"] if item["method"] == "ols"]
        singular, singular_config = prepare(fixture, config=singular_config)
        failed = service._evaluate_prepared(singular, singular_config)
        assert failed["gate"]["status"] == "no_go"
        assert failed["arms"][0]["selection"]["selected_model"] is None
        summary = failed["arms"][0]["metrics"]["summary"]
        assert summary["requested_count"] == summary["failed_count"] == 5
        assert summary["predicted_count"] == 0 and summary["mae_k"] is None
        assert all(row["prediction_k"] is None and row["failure_reason"] == "no_candidate_selected"
                   for row in failed["arms"][0]["predictions"])
    assert before == await state(db_session)
    assert canonical(build_task_dataset_v4(**arguments)) == canonical(fixture["original"])
    assert build_audited_task_dataset(**arguments) == package
    assert len(package["base_dataset"]["views"]) == (9 if features else 1)
    assert len({arguments[name] for name in (
        "expected_manifest_sha256", "expected_companion_sha256", "expected_review_companion_sha256",
        "expected_label_companion_sha256", "expected_task_sha256",
    )}) == 5


async def test_public_real_package_entry_refuses_before_parse_prepare_or_fit(db_session, monkeypatch):
    from services import ml_baseline_rehearsal as service

    fixture = await baseline_fixture(db_session)
    before = await state(db_session)

    def no_work(*args, **kwargs):
        raise AssertionError("an unsupported public dataset reached preparation or fitting")

    monkeypatch.setattr(service, "prepare_audited_baseline_inputs", no_work)
    monkeypatch.setattr(service, "_evaluate_prepared", no_work)
    for extra in ({}, {"synthetic": True}, {"approved": True, "ml_training_approved": True}):
        with pytest.raises(ValueError, match="^ml_use_authorization_unavailable$"):
            service.run_baseline_dataset(fixture["package"], **extra)
    with pytest.raises(TypeError):
        service.run_synthetic_rehearsal(package=fixture["package"])
    assert before == await state(db_session)


async def test_prepare_rejects_resealed_audit_and_independent_pin_changes_without_fitting(db_session, monkeypatch):
    from services import ml_baseline_numerics as numerics
    from services import ml_baseline_rehearsal as service

    fixture = await baseline_fixture(db_session)
    config = service.draft_task_for_package(fixture["package"])
    before = await state(db_session)

    def no_fit(*args, **kwargs):
        raise AssertionError("tampered input reached fitting")

    monkeypatch.setattr(numerics, "fit_select", no_fit)
    for key in (
        "expected_manifest_sha256", "expected_companion_sha256", "expected_review_companion_sha256",
        "expected_label_companion_sha256", "expected_task_sha256",
    ):
        with pytest.raises(ValueError):
            service.prepare_audited_baseline_inputs(
                fixture["package"], expected_package_sha256=package_digest(fixture["package"]),
                config=config, expected_config_sha256=digest(config),
                **{**fixture["arguments"], key: "0" * 64},
            )
    changed = deepcopy(fixture["package"])
    changed["identity_audit"]["counts"][0]["rows"] += 1
    changed["identity_audit_sha256"] = package_digest(changed["identity_audit"])
    repinned = service.draft_task_for_package(changed)
    with pytest.raises(ValueError):
        service.prepare_audited_baseline_inputs(
            changed, expected_package_sha256=package_digest(changed), config=repinned,
            expected_config_sha256=digest(repinned), **fixture["arguments"],
        )
    assert before == await state(db_session)


async def test_actual_test_target_perturbation_never_changes_fit_selection_or_prediction(db_session):
    from services import ml_baseline_rehearsal as service

    original = await baseline_fixture(db_session, features=True)
    first, first_config = prepare(original)
    first_report = service._evaluate_prepared(first, first_config)
    # A fresh synthetic SQL graph is required: 0054 forbids rewriting frozen Tc.
    await db_session.rollback()
    changed = await baseline_fixture(db_session, features=True, test_target_delta=100.0)
    second, second_config = prepare(changed)
    second_report = service._evaluate_prepared(second, second_config)
    assert first_config["input_sha256"] != second_config["input_sha256"]
    for left, right in zip(first["arms"], second["arms"]):
        assert left["preprocessing"]["parameters"] == right["preprocessing"]["parameters"]
        assert left["selected_feature_names"] == right["selected_feature_names"]
    for left, right in zip(first_report["arms"], second_report["arms"]):
        assert left["selection"] == right["selection"]
        left_predictions = {original["keys"][row["example_id"]]: row["prediction_k"] for row in left["predictions"]}
        right_predictions = {changed["keys"][row["example_id"]]: row["prediction_k"] for row in right["predictions"]}
        assert left_predictions == right_predictions
        left_scores = {row["split"]: row["summary"] for row in left["metrics"]["by_split"]}
        right_scores = {row["split"]: row["summary"] for row in right["metrics"]["by_split"]}
        assert left_scores["train"] == right_scores["train"]
        assert left_scores["validation"] == right_scores["validation"]
        assert left_scores["test"]["mae_k"] != right_scores["test"]["mae_k"]
        assert left_scores["test"]["requested_count"] == right_scores["test"]["requested_count"] == 1


async def test_target_derived_renamed_input_is_absent_from_prepared_model_columns(db_session):
    from services import ml_baseline_rehearsal as service

    fixture = await baseline_fixture(db_session, features=True, target_derived=True)
    prepared, config = prepare(fixture, views=["C@B"])
    admissions = fixture["original"]["dependency_manifest"]["feature_admission"]
    for item in fixture["chain"]:
        admission = next(row for row in admissions if row["input_id"] == str(item["input"]["id"]))
        assert admission["status"] == "excluded" and "target_dependency" in admission["reason_codes"]
    forbidden = {"electron_phonon_lambda", "dos_at_fermi", "renamed-normal-state-descriptor"}
    assert not forbidden.intersection(prepared["arms"][0]["feature_names"])
    report = service._evaluate_prepared(prepared, config)
    assert report["gate"]["status"] == "pass"
    assert not forbidden.intersection(report["arms"][0]["selection"]["selected_model"]["feature_names"])


async def test_condition_columns_cannot_be_relabelled_as_composition_only(db_session):
    fixture = await baseline_fixture(db_session, feature_budget="composition_conditions")
    prepared, config = prepare(fixture)
    conditions = {"reported_pressure_gpa", "reported_magnetic_field_t"}
    assert any(conditions.issubset(arm["feature_names"]) for arm in prepared["arms"])
    changed = deepcopy(config)
    arm = next(arm for arm in changed["arms"] if conditions.issubset(arm["feature_names"]))
    arm["feature_scope"] = "composition"
    with pytest.raises(ValueError):
        prepare(fixture, config=changed)
    assert fixture["package"]["base_dataset"]["task"]["label_task"]["feature_budget"] == "composition_conditions"


async def test_real_verifier_postcheck_mutation_refuses_without_fit_or_caller_mutation(db_session, monkeypatch):
    from services import ml_baseline_numerics as numerics
    from services import ml_baseline_rehearsal as service

    fixture = await baseline_fixture(db_session)
    config = service.draft_task_for_package(fixture["package"])
    original_verify = service.verify_audited_task_dataset
    original_package = canonical(fixture["package"])
    original_manifest = canonical(fixture["arguments"]["manifest"])
    original_config = canonical(config)
    before = await state(db_session)

    def no_fit(*args, **kwargs):
        raise AssertionError("a post-verification mutation reached numerical fitting")

    for change in ("view_features", "manifest_pressure"):
        verified = []

        def verify_then_mutate(package, **arguments):
            result = original_verify(package, **arguments)
            assert result["integrity_verified"] is True and result["technical_gate"] == "pass"
            assert package is not fixture["package"]
            assert arguments["manifest"] is not fixture["arguments"]["manifest"]
            verified.append(change)
            if change == "view_features":
                package["base_dataset"]["views"]["C@B"]["rows"][0]["features"][0] += 1.0
            else:
                claim = next(row for row in arguments["manifest"]["rows"] if row["table"] == "material_claims")
                claim["data"]["pressure_gpa"] = 0.5
            return result

        with monkeypatch.context() as patch:
            patch.setattr(service, "verify_audited_task_dataset", verify_then_mutate)
            patch.setattr(numerics, "fit_select", no_fit)
            with pytest.raises(service.MlBaselineRehearsalError, match="^ml_baseline_independent_pin_mismatch$"):
                prepare(fixture, config=config)
        assert verified == [change]
        assert canonical(fixture["package"]) == original_package
        assert canonical(fixture["arguments"]["manifest"]) == original_manifest
        assert canonical(config) == original_config
    assert before == await state(db_session)


def invoke_fixed_cli(arguments):
    root = Path(__file__).resolve().parents[2]
    runner = """import runpy,sys
def audit(event,args):
    if event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system','sqlite3.connect'}:
        raise RuntimeError('offline_io_forbidden')
sys.addaudithook(audit)
path=sys.argv.pop(1)
runpy.run_path(path,run_name='__main__')
"""
    return subprocess.run(
        [sys.executable, "-c", runner, str(root / "scripts/ml_baseline_rehearsal.py"), *arguments],
        cwd=root, capture_output=True, text=True, timeout=60, check=False,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0",
             "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused",
             "REDIS_URL": "redis://127.0.0.1:1/0"},
    )


def test_fixed_cli_real_subprocess_is_offline_immutable_and_replays_before_trusting_hash(tmp_path):
    """Only the implementation-owned toy is fitted; no SQL package is supplied."""
    output = tmp_path.resolve() / "synthetic-baseline.json"
    built = invoke_fixed_cli(["build", "--output", str(output)])
    assert built.returncode == 0, built.stderr
    summary = json.loads(built.stdout)
    assert summary["technical_gate"] == "pass" and summary["output_written"] is True
    raw = output.read_bytes()
    receipt = json.loads(raw)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert receipt["scope"] == "fixed_implementation_owned_synthetic_rehearsal"
    assert all(value is False for value in receipt["authority"].values())
    assert receipt["report"]["model_card"]["test_targets_used_for_fit_or_selection"] is False
    assert summary["receipt_sha256"] == package_digest(receipt)
    verified = invoke_fixed_cli(["verify", "--receipt", str(output), "--receipt-sha256", package_digest(receipt)])
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["numerical_replay_verified"] is True
    repeated = invoke_fixed_cli(["build", "--output", str(output)])
    assert repeated.returncode == 2 and not repeated.stdout and output.read_bytes() == raw
    tampered = deepcopy(receipt)
    tampered["report"]["arms"][0]["predictions"][0]["prediction_k"] += 1.0
    tampered["report_sha256"] = digest(tampered["report"])
    changed = tmp_path.resolve() / "repinned-prediction.json"
    changed.write_bytes(canonical(tampered))
    denied = invoke_fixed_cli(["verify", "--receipt", str(changed), "--receipt-sha256", package_digest(tampered)])
    assert denied.returncode == 2 and not denied.stdout
    assert json.loads(denied.stderr) == {"status": "invalid", "output_written": False}
    arbitrary = tmp_path.resolve() / "must-not-exist.json"
    for flags in (["--dataset", str(output)], ["--synthetic", "true"], ["--approved", "true"]):
        denied = invoke_fixed_cli(["build", "--output", str(arbitrary), *flags])
        assert denied.returncode == 2 and not denied.stdout and not arbitrary.exists()
        assert json.loads(denied.stderr) == {"status": "invalid", "output_written": False}
