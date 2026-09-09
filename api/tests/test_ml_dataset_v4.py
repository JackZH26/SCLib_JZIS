"""V4 compilation from real disposable SQL captures, never scientific approval.

The retained values and review declarations are synthetic. Full compiler tests
use the actual 0054/0064 base plus independently captured review/label documents;
small receipt tests separately exercise the compiler's defensive closed ABI.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from importlib.resources import files
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from models.ml_task_v3 import REVIEW_POLICY
from models.ml_task_v4 import LABEL_CURRENTNESS_POLICY, validate_task_v4
from services.ml_dataset_builder_v2 import _view
from services.ml_dataset_builder_v3 import _implementation as implementation_v3
from services.ml_dataset_builder_v3 import build_task_dataset_v3
from services.ml_dataset_builder_v4 import (
    _check_label_receipt,
    build_task_dataset_v4,
    verify_task_dataset_v4,
)
from services.ml_feature_review_companion import AUTHORITY as REVIEW_AUTHORITY
from services.ml_label_capture import capture_ml_label_companion
from services.ml_label_companion import verify_ml_label_companion
from services.ml_review_capture import EXPORT_SCOPE, capture_ml_review_companion
from services.research_release_manifest import canonical, digest
from tests.test_ml_label_capture import db_session as db_session
from tests.test_ml_label_capture import label_fixture, read_snapshot, write_snapshot
from tests.test_ml_physical_feature_sql import assert_fair_views, write_cli_capsule
from tests.test_research_freeze import add


def compiler_inputs(seeded, *, label=None, review=None, task=None):
    """Plain independent inputs also reusable by the new CLI integration tests."""
    inputs = seeded["inputs"]
    task = deepcopy(task or inputs["task"])
    task.update(
        version="ml-task/4.0.0",
        task_id="observed-tc-current-labels-v4",
        exact_result_review_policy=REVIEW_POLICY,
        label_currentness_policy=LABEL_CURRENTNESS_POLICY,
    )
    validate_task_v4(task)
    review = seeded["review_companion"] if review is None else review
    label = seeded["label_companion"] if label is None else label
    return {
        "manifest": inputs["release"]["manifest"],
        "artifact_bytes": inputs["artifact_bytes"],
        "expected_manifest_sha256": inputs["release"]["manifest_sha256"],
        "companion": inputs["companion"],
        "expected_companion_sha256": digest(inputs["companion"]),
        "review_companion": review,
        "expected_review_companion_sha256": digest(review),
        "label_companion": label,
        "expected_label_companion_sha256": digest(label),
        "task": task,
        "expected_task_sha256": digest(task),
    }


def v3_inputs(arguments):
    inputs = {
        key: value
        for key, value in arguments.items()
        if key not in {"label_companion", "expected_label_companion_sha256"}
    }
    task = deepcopy(inputs["task"])
    del task["label_currentness_policy"]
    task["version"] = "ml-task/3.0.0"
    return {**inputs, "task": task, "expected_task_sha256": digest(task)}


def candidate_for(bundle, seeded, key):
    identifier = str(seeded["fixture"]["candidates"][key]["example"]["id"])
    return next(row for row in bundle["candidates"] if row["example_id"] == identifier)


async def recapture(db, seeded):
    """Refresh both observations in the same read-only snapshot, not old pins."""
    common = {
        key: value
        for key, value in seeded["args"].items()
        if key not in {"export_scope", "review_companion", "expected_review_companion_sha256"}
    }
    review = await capture_ml_review_companion(db, **common, export_scope=EXPORT_SCOPE)
    label = await capture_ml_label_companion(
        db,
        **{
            **seeded["args"],
            "review_companion": review,
            "expected_review_companion_sha256": digest(review),
        },
    )
    return review, label


async def hold_label(db, seeded, key, *, table="materials"):
    candidate = seeded["fixture"]["candidates"][key]
    await write_snapshot(db)
    if table == "materials":
        target, field, value = candidate["material"]["id"], "needs_review", True
    else:
        target, field, value = candidate["paper"]["id"], "status", "retracted"
    model = Base.metadata.tables[table]
    await db.execute(model.update().where(model.c.id == target).values(**{field: value}))
    await read_snapshot(db)
    return await recapture(db, seeded)


def receipt_unit_fixture():
    """Defensive-ABI unit data only; not a valid base or captured observation."""
    index = {
        ("ml_examples", "example-a"): {
            "row_sha256": "1" * 64,
            "data": {"dataset_snapshot_id": "dataset-a", "claim_id": "claim-a"},
        },
        ("ml_examples", "example-b"): {
            "row_sha256": "2" * 64,
            "data": {"dataset_snapshot_id": "dataset-a", "claim_id": "claim-a"},
        },
        ("ml_examples", "other-dataset"): {
            "row_sha256": "3" * 64,
            "data": {"dataset_snapshot_id": "other", "claim_id": "claim-other"},
        },
        ("material_claims", "claim-a"): {"row_sha256": "4" * 64, "data": {}},
        ("material_claims", "claim-other"): {"row_sha256": "5" * 64, "data": {}},
    }
    pin = lambda table, identifier: {
        "table": table,
        "row_id": identifier,
        "row_sha256": index[(table, identifier)]["row_sha256"],
    }
    receipt = {
        "version": "ml-label-companion/1.0.0",
        "observation_semantics": "captured_not_live",
        "base_manifest_sha256": "a" * 64,
        "source_companion_sha256": "b" * 64,
        "review_companion_sha256": "c" * 64,
        "label_companion_sha256": "d" * 64,
        "observation_sha256": "e" * 64,
        "example_pins": {key: pin("ml_examples", key) for key in ("example-a", "example-b")},
        "claim_pins": {"claim-a": pin("material_claims", "claim-a")},
        "claim_holds": {"claim-a": []},
        "authority": dict(REVIEW_AUTHORITY),
    }
    return index, receipt


def check_unit(receipt, index):
    _check_label_receipt(receipt, index, "dataset-a", "a" * 64, "b" * 64, "c" * 64, "d" * 64)


def test_receipt_abi_includes_all_examples_but_deduplicates_shared_claim():
    index, receipt = receipt_unit_fixture()
    check_unit(receipt, index)
    receipt["claim_holds"]["claim-a"] = ["label_current_result_held"]
    check_unit(receipt, index)


@pytest.mark.parametrize(
    "change",
    [
        "extra_field",
        "missing_example",
        "extra_example",
        "missing_claim",
        "extra_claim",
        "missing_hold",
        "extra_hold",
        "wrong_table",
        "wrong_id",
        "wrong_row_hash",
        "observation_bool",
        "base_pin",
        "source_pin",
        "review_pin",
        "label_pin",
        "authority_true",
        "authority_zero",
        "authority_extra",
        "positive_code",
        "duplicate_code",
        "unsorted_codes",
        "code_bool",
        "code_string",
    ],
)
def test_receipt_abi_refuses_omissions_substitution_or_positive_authority(change):
    index, receipt = receipt_unit_fixture()
    if change == "extra_field":
        receipt["current_authority"] = True
    elif change == "missing_example":
        del receipt["example_pins"]["example-b"]
    elif change == "extra_example":
        receipt["example_pins"]["other-dataset"] = deepcopy(receipt["example_pins"]["example-a"])
    elif change == "missing_claim":
        receipt["claim_pins"] = {}
    elif change == "extra_claim":
        receipt["claim_pins"]["claim-other"] = deepcopy(receipt["claim_pins"]["claim-a"])
    elif change == "missing_hold":
        receipt["claim_holds"] = {}
    elif change == "extra_hold":
        receipt["claim_holds"]["claim-other"] = []
    elif change in {"wrong_table", "wrong_id", "wrong_row_hash"}:
        key = {"wrong_table": "table", "wrong_id": "row_id", "wrong_row_hash": "row_sha256"}[change]
        receipt["claim_pins"]["claim-a"][key] = "wrong"
    elif change == "observation_bool":
        receipt["observation_sha256"] = True
    elif change.endswith("_pin"):
        field = {
            "base_pin": "base_manifest_sha256",
            "source_pin": "source_companion_sha256",
            "review_pin": "review_companion_sha256",
            "label_pin": "label_companion_sha256",
        }[change]
        receipt[field] = "0" * 64
    elif change.startswith("authority"):
        receipt["authority"]["scientific_acceptance" if change != "authority_extra" else "new"] = (
            True if change == "authority_true" else 0 if change == "authority_zero" else False
        )
    else:
        receipt["claim_holds"]["claim-a"] = {
            "positive_code": ["scientifically_approved"],
            "duplicate_code": ["label_current_result_held"] * 2,
            "unsorted_codes": ["label_source_identity_changed", "label_current_result_held"],
            "code_bool": [False],
            "code_string": "label_current_result_held",
        }[change]
    with pytest.raises(ValueError):
        check_unit(receipt, index)


@pytest.mark.parametrize("features", [False, True])
async def test_real_no_hold_compilation_preserves_v3_values_and_old_source_pins(
    db_session, features
):
    seeded = await label_fixture(db_session, features=features)
    arguments = compiler_inputs(seeded)
    retained = canonical(
        {key: value for key, value in arguments.items() if key != "artifact_bytes"}
    )
    before = build_task_dataset_v3(**v3_inputs(arguments))
    bundle = build_task_dataset_v4(**arguments)
    assert bundle["version"] == "ml-task-dataset/4.0.0"
    assert bundle["cohorts"] == before["cohorts"]
    for name, view in bundle["views"].items():
        old_view = before["views"][name]
        assert {key: value for key, value in view.items() if key != "rows"} == {
            key: value for key, value in old_view.items() if key != "rows"
        }
        # The assignment checksum includes the independently versioned task.
        # Its scientific values and actual assignments, not that hash, match.
        assert [
            {key: value for key, value in row.items() if key != "assignment_sha256"}
            for row in view["rows"]
        ] == [
            {key: value for key, value in row.items() if key != "assignment_sha256"}
            for row in old_view["rows"]
        ]
    assert bundle["split_report"]["base_assignments"] == before["split_report"]["base_assignments"]
    assert bundle["coverage"] == before["coverage"]
    assert bundle["input_pins"]["label_companion_sha256"] == digest(seeded["label_companion"])
    assert (
        bundle["input_pins"]["label_observation_sha256"]
        == seeded["label_companion"]["observation_sha256"]
    )
    assert bundle["label_observation"]["example_count"] == 5
    assert bundle["label_observation"]["held_claim_count"] == 0
    assert all(flag is False for flag in bundle["authority"].values())
    old_pins = implementation_v3()["source_sha256"]
    assert {name: bundle["compiler"]["source_sha256"][name] for name in old_pins} == old_pins
    new_names = {
        "models.ml_task_v4",
        "services.ml_dataset_builder_v4",
        "services.ml_label_companion",
        "services.ml_label_observation",
    }
    assert set(bundle["compiler"]["source_sha256"]) - set(old_pins) == new_names
    for name in new_names:
        package, module = name.split(".")
        assert (
            bundle["compiler"]["source_sha256"][name]
            == hashlib.sha256(files(package).joinpath(module + ".py").read_bytes()).hexdigest()
        )
    verified = verify_task_dataset_v4(bundle, expected_bundle_sha256=digest(bundle), **arguments)
    assert verified["integrity_verified"] is True
    assert verified["ml_training_approved"] is False
    for field in (
        "review_companion_sha256",
        "review_observation_sha256",
        "label_companion_sha256",
        "label_observation_sha256",
    ):
        assert verified[field] == bundle["input_pins"][field]
    assert bundle == build_task_dataset_v4(**arguments)
    assert retained == canonical(
        {key: value for key, value in arguments.items() if key != "artifact_bytes"}
    )
    assert_fair_views(bundle)


@pytest.mark.parametrize("table", ["materials", "papers"])
async def test_label_hold_without_optional_inputs_excludes_base_and_preserves_old_replay(
    db_session, table
):
    seeded = await label_fixture(db_session)
    original_args = compiler_inputs(seeded)
    before = build_task_dataset_v4(**original_args)
    key = seeded["first"]
    review, label = await hold_label(db_session, seeded, key, table=table)
    after_args = compiler_inputs(seeded, review=review, label=label)
    after = build_task_dataset_v4(**after_args)
    candidate = candidate_for(after, seeded, key)
    assert candidate["status"] == "excluded"
    assert "label_currentness_held" in candidate["reason_codes"]
    assert candidate["captured_label_currentness"]["reason_codes"]
    identifier = candidate["example_id"]
    assert identifier in before["cohorts"]["B"]["example_ids"]
    assert all(identifier not in cohort["example_ids"] for cohort in after["cohorts"].values())
    assert after["coverage"]["cohort_counts"] == {"B": 4, "P": 0, "S": 0, "PS": 0}
    assert after["label_observation"]["held_example_count"] == 1
    assert all(
        not view["rows"] or all(row["example_id"] != identifier for row in view["rows"])
        for view in after["views"].values()
    )
    assert before == build_task_dataset_v4(**original_args)
    assert verify_task_dataset_v4(before, expected_bundle_sha256=digest(before), **original_args)[
        "integrity_verified"
    ]
    assert_fair_views(after)


async def test_held_training_label_refits_all_nested_cohorts_from_raw_data(db_session):
    seeded = await label_fixture(db_session, features=True)
    original_args = compiler_inputs(seeded)
    before = build_task_dataset_v4(**original_args)
    selected = next(row for row in before["rows"] if row["split"] == "train")
    key = next(
        key
        for key, row in seeded["fixture"]["candidates"].items()
        if str(row["example"]["id"]) == selected["example_id"]
    )
    review, label = await hold_label(db_session, seeded, key)
    after = build_task_dataset_v4(**compiler_inputs(seeded, review=review, label=label))
    assert after["coverage"]["cohort_counts"] == {"B": 4, "P": 4, "S": 4, "PS": 4}
    for name, view in after["views"].items():
        assert selected["example_id"] not in {row["example_id"] for row in view["rows"]}
        old_fit = before["views"][name]["preprocessing"]["parameters"]
        new_fit = view["preprocessing"]["parameters"]
        assert old_fit["train_row_count"] == 3 and new_fit["train_row_count"] == 2
        assert old_fit != new_fit
        assert view["cohort_sha256"] != before["views"][name]["cohort_sha256"]
    assert after["split_report"]["cross_artifact_assignment_stability"] == "not_guaranteed"
    assert after["split_report"]["subset_resplitting"] is False
    assert_fair_views(after)
    assert before == build_task_dataset_v4(**original_args)


async def test_test_only_raw_extremes_do_not_change_train_fitted_parameters(db_session):
    seeded = await label_fixture(db_session, features=True)
    bundle = build_task_dataset_v4(**compiler_inputs(seeded))
    # Exercise the unchanged shared view boundary on the actual compiler rows.
    # These deliberately altered raw numbers are not claimed as source evidence.
    view = bundle["views"]["C@B"]
    changed = deepcopy(bundle["rows"])
    selected = next(row for row in changed if row["split"] == "test")
    selected["raw_features"] = [
        1e30 if value is not None else None for value in selected["raw_features"]
    ]
    rebuilt = _view(
        "C@B",
        set(bundle["cohorts"]["B"]["example_ids"]),
        view["feature_names"],
        {},
        changed,
        bundle["task"]["label_task"]["preprocessing"],
    )
    assert rebuilt["preprocessing"]["parameters"] == view["preprocessing"]["parameters"]
    original_train = [row["features"] for row in view["rows"] if row["split"] == "train"]
    assert [row["features"] for row in rebuilt["rows"] if row["split"] == "train"] == original_train


async def test_complete_rebuild_refuses_repinned_dataset_tampering(db_session):
    seeded = await label_fixture(db_session, features=True)
    arguments = compiler_inputs(seeded)
    bundle = build_task_dataset_v4(**arguments)
    for target in ("raw", "fit", "split", "label_audit", "label_pin", "cohort", "authority"):
        changed = deepcopy(bundle)
        if target == "raw":
            changed["views"]["CP@P"]["rows"][0]["raw_features"][-1] = 9999.0
        elif target == "fit":
            changed["views"]["C@B"]["preprocessing"]["parameters"]["statistics"][0]["median"] = (
                9999.0
            )
        elif target == "split":
            changed["rows"][0]["split"] = "invalid"
        elif target == "label_audit":
            changed["candidates"][0]["captured_label_currentness"]["reason_codes"] = [
                "label_current_result_held"
            ]
        elif target == "label_pin":
            changed["input_pins"]["label_observation_sha256"] = "0" * 64
        elif target == "cohort":
            changed["cohorts"]["B"]["example_ids"].pop()
            changed["cohorts"]["B"]["sha256"] = digest(changed["cohorts"]["B"]["example_ids"])
        else:
            changed["authority"]["ml_training_approved"] = True
        with pytest.raises(ValueError, match="recomputation mismatch"):
            verify_task_dataset_v4(changed, expected_bundle_sha256=digest(changed), **arguments)


async def test_empty_current_holds_never_promote_frozen_unknown_pressure_labels(db_session):
    specs = [
        {
            "key": "pending",
            "formula": "MgB2",
            "reviewed": True,
            "pressure": None,
            "pressure_status": "not_reported",
        },
        {"key": "one", "formula": "Pb", "reviewed": True},
        {"key": "two", "formula": "Nb", "reviewed": True},
        {"key": "three", "formula": "Sn", "reviewed": True},
    ]
    seeded = await label_fixture(db_session, specs=specs)
    bundle = build_task_dataset_v4(**compiler_inputs(seeded))
    candidate = candidate_for(bundle, seeded, "pending")
    assert not candidate["captured_label_currentness"]["reason_codes"]
    assert candidate["status"] == "excluded"
    assert candidate["reason_codes"] and "label_currentness_held" not in candidate["reason_codes"]
    assert all(flag is False for flag in bundle["authority"].values())


async def test_excluded_label_bridge_remains_in_complete_group_graph(db_session):
    specs = [
        {"key": "bridge", "formula": "MgB2", "work_group": "left", "reviewed": True},
        {"key": "left", "formula": "FeSe", "work_group": "left", "reviewed": True},
        {"key": "right", "formula": "Nb", "reviewed": True},
        {"key": "train", "formula": "Pb", "reviewed": True},
    ]

    async def bridge(db, fixture):
        candidates = fixture["candidates"]
        await add(
            db,
            "event_evidence",
            event_id=candidates["bridge"]["event"]["id"],
            link_type="context",
            input_event_id=candidates["right"]["event"]["id"],
        )
        materials = Base.metadata.tables["materials"]
        for key, family in (
            ("bridge", "family_a"),
            ("left", "family_a"),
            ("right", "family_b"),
            ("train", "family_train"),
        ):
            await db.execute(
                materials.update()
                .where(materials.c.id == candidates[key]["material"]["id"])
                .values(family=family)
            )

    seeded = await label_fixture(db_session, specs=specs, before_freeze=bridge)
    review, label = await hold_label(db_session, seeded, "bridge")
    task = deepcopy(seeded["inputs"]["task"])
    task["label_task"]["split"].update(
        mode="family_holdout", validation_families=["family_a"], test_families=["family_b"]
    )
    bundle = build_task_dataset_v4(**compiler_inputs(seeded, task=task, review=review, label=label))
    bridge, left, right = [
        candidate_for(bundle, seeded, key) for key in ("bridge", "left", "right")
    ]
    assert "label_currentness_held" in bridge["reason_codes"]
    assert bridge["group_id"] == left["group_id"] == right["group_id"]
    assert bridge["status"] == left["status"] == right["status"] == "excluded"
    assert "family_holdout_component_conflict_or_unknown" in left["reason_codes"]
    assert "family_holdout_component_conflict_or_unknown" in right["reason_codes"]
    assert bundle["gate"]["status"] == "no_go"
    assert not bundle["split_report"]["component_crossings"]


async def test_label_verifier_receipt_matches_full_compiler_root_inventory(db_session):
    seeded = await label_fixture(db_session)
    args = seeded["args"]
    label = seeded["label_companion"]
    receipt = verify_ml_label_companion(
        label,
        **{
            key: args[key]
            for key in (
                "base_manifest",
                "expected_base_manifest_sha256",
                "source_companion",
                "expected_source_companion_sha256",
                "review_companion",
                "expected_review_companion_sha256",
            )
        },
        expected_label_companion_sha256=digest(label),
    )
    bundle = build_task_dataset_v4(**compiler_inputs(seeded))
    assert set(receipt["example_pins"]) == {row["example_id"] for row in bundle["candidates"]}
    assert set(receipt["claim_pins"]) == {row["claim_id"] for row in bundle["candidates"]}
    assert set(receipt["claim_holds"]) == set(receipt["claim_pins"])


async def test_frozen_claim_mutation_is_refused_not_simulated_as_a_live_status_edit(db_session):
    seeded = await label_fixture(db_session)
    claim_id = seeded["fixture"]["candidates"][seeded["first"]]["claim"]["id"]
    await write_snapshot(db_session)
    with pytest.raises(DBAPIError, match="frozen_research_row"):
        async with db_session.begin_nested():
            await db_session.execute(
                sa.text("UPDATE material_claims SET validity_status='disputed' WHERE id=:id"),
                {"id": claim_id},
            )
    await read_snapshot(db_session)
    review, label = await recapture(db_session, seeded)
    assert label == seeded["label_companion"]
    assert review == seeded["review_companion"]


async def test_actual_v4_cli_build_verify_and_repinned_refusal_are_offline(db_session, tmp_path):
    seeded = await label_fixture(db_session, features=True)
    arguments = compiler_inputs(seeded)
    cli_args = write_cli_capsule(tmp_path, {**seeded["inputs"], "task": arguments["task"]})
    for name in ("review", "label"):
        document = seeded[name + "_companion"]
        path = tmp_path.resolve() / (name + ".json")
        path.write_bytes(canonical(document))
        cli_args.extend(
            [
                "--" + name + "-companion",
                str(path),
                "--" + name + "-companion-sha256",
                digest(document),
            ]
        )
    output = tmp_path.resolve() / "compiled-v4.json"
    root = Path(__file__).resolve().parents[2]
    runner = """import runpy,sys
def audit(event,args):
    if event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system','sqlite3.connect'}:
        raise RuntimeError('offline_io_forbidden')
sys.addaudithook(audit)
path=sys.argv.pop(1)
runpy.run_path(path,run_name='__main__')
"""

    def invoke(mode, extra):
        return subprocess.run(
            [
                sys.executable,
                "-c",
                runner,
                str(root / "scripts/ml_current_dataset.py"),
                mode,
                *cli_args,
                *extra,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONHASHSEED": "0",
                "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused",
                "REDIS_URL": "redis://127.0.0.1:1/0",
            },
        )

    built = invoke("build", ["--output", str(output)])
    assert built.returncode == 0, built.stderr
    report = json.loads(built.stdout)
    assert report["output_written"] is True and report["technical_gate"] == "pass"
    assert report["label_observation_sha256"] == seeded["label_companion"]["observation_sha256"]
    assert report["review_observation_sha256"] == seeded["review_companion"]["observation_sha256"]
    assert report["scientific_acceptance"] is False and report["ml_training_approved"] is False
    document = json.loads(output.read_bytes())
    assert document == build_task_dataset_v4(**arguments)
    assert output.stat().st_mode & 0o777 == 0o600
    verified = invoke("verify", ["--bundle", str(output), "--bundle-sha256", digest(document)])
    assert verified.returncode == 0, verified.stderr
    verify_report = json.loads(verified.stdout)
    assert verify_report["integrity_verified"] is True
    for field in (
        "review_companion_sha256",
        "review_observation_sha256",
        "label_companion_sha256",
        "label_observation_sha256",
    ):
        assert verify_report[field] == document["input_pins"][field]
    document["label_observation"]["held_claim_count"] = 1
    output.write_bytes(canonical(document))
    rejected = invoke("verify", ["--bundle", str(output), "--bundle-sha256", digest(document)])
    assert rejected.returncode == 2
    assert json.loads(rejected.stderr) == {"status": "invalid", "output_written": False}


async def test_feature_only_source_hold_does_not_erase_independent_base_labels(db_session):
    seeded = await label_fixture(db_session, features=True)
    before = build_task_dataset_v4(**compiler_inputs(seeded))
    source = seeded["fixture"]["feature_bindings"][(seeded["first"], "band_gap")]["source"]
    await write_snapshot(db_session)
    await db_session.execute(
        sa.text("UPDATE papers SET status='retracted' WHERE id=:id"),
        {"id": source["revision"]["paper_id"]},
    )
    await read_snapshot(db_session)
    review, label = await recapture(db_session, seeded)
    after = build_task_dataset_v4(**compiler_inputs(seeded, review=review, label=label))
    assert after["cohorts"]["B"] == before["cohorts"]["B"]
    assert after["split_report"]["base_assignments"] == before["split_report"]["base_assignments"]
    assert after["views"]["C@B"]["preprocessing"] == before["views"]["C@B"]["preprocessing"]
    assert after["coverage"]["cohort_counts"] == {"B": 5, "P": 4, "S": 4, "PS": 4}
    assert after["label_observation"]["held_claim_count"] == 0
    assert after["review_observation"]["held_input_source_count"] > 0
    assert_fair_views(after)
