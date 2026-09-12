"""Preparation CLI/file invariants. Compiler doubles are not scientific evidence."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
from copy import deepcopy
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("ml_baseline_preparation_cli", Path(__file__).resolve().parents[1] / "ml_baseline_preparation.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)
INPUTS = ("manifest", "task", "companion", "review_companion", "label_companion", "package", "config")


def write(path, value):
    path.write_bytes(cli.canonical(value))
    return cli.digest(value)


@pytest.fixture
def case(tmp_path, monkeypatch):
    from services.ml_baseline_rehearsal import _owned_fixture

    _, config, prepared = _owned_fixture()
    package = {"synthetic_command_double": True}
    config["input_sha256"] = prepared["input_sha256"] = cli.digest(package)
    prepared["config_sha256"] = cli.digest(config)
    prepared["scope"] = "read_only_verified_audited_package_not_fit_authorization"
    capsule = tmp_path / "capsule"
    capsule.mkdir()
    values = {name: {"synthetic_" + name: True} for name in INPUTS}
    values.update(package=package, config=config)
    paths = {name: tmp_path / (name + ".json") for name in INPUTS}
    paths["manifest"] = capsule / "manifest.json"
    arguments = {"mode": "prepare", "output_path": tmp_path / "prepared.json"}
    for name in INPUTS:
        arguments[name + "_path"] = paths[name]
        arguments["expected_" + name + "_sha256"] = write(paths[name], values[name])
    calls = []

    def verify(value, **inputs):
        calls.append("verify")
        assert value == package and inputs["expected_package_sha256"] == cli.digest(package)
        for name in ("manifest", "task", "companion", "review_companion", "label_companion"):
            assert inputs[name] == values[name]
            assert inputs["expected_" + name + "_sha256"] == cli.digest(values[name])
        return {"technical_gate": "pass", "integrity_verified": True}

    def prepare(value, **inputs):
        assert inputs.pop("config") == config and inputs.pop("expected_config_sha256") == cli.digest(config)
        verify(value, **inputs)
        calls.append("prepare")
        return deepcopy(prepared)

    def draft(value, *, views):
        assert value == package and views in (None, ["C@B"])
        calls.append("draft")
        return deepcopy(config)

    monkeypatch.setattr(cli, "verify_audited_task_dataset", verify)
    monkeypatch.setattr(cli, "prepare_audited_baseline_inputs", prepare)
    monkeypatch.setattr(cli, "draft_task_for_package", draft)
    return arguments, values, prepared, calls


def verification(arguments, receipt):
    return {**arguments, "mode": "verify", "output_path": None,
            "receipt_path": arguments["output_path"], "expected_receipt_sha256": cli.digest(receipt)}


def test_private_preparation_and_exact_replay_without_training(case):
    args, values, prepared, calls = case
    report = cli.run(**args)
    assert calls == ["verify", "prepare"]
    receipt = json.loads(args["output_path"].read_bytes())
    assert receipt["prepared"] == prepared and receipt["config"] == values["config"]
    assert receipt["prepared_sha256"] == cli.digest(prepared)
    assert receipt["scope"] == cli.SCOPE and receipt["training_execution"] == "disabled"
    assert all(value is False for value in receipt["authority"].values())
    assert report["output_written"] and report["technical_gate"] == "pass"
    assert report["independent_support_count"] is None
    assert "diagnostics" not in report and "prepared" not in report
    assert stat.S_IMODE(args["output_path"].stat().st_mode) == 0o600
    assert args["output_path"].stat().st_nlink == 1
    result = cli.run(**verification(args, receipt))
    assert result["preparation_replay_verified"] and not result["output_written"]
    with pytest.raises(FileExistsError):
        cli.run(**args)
    assert json.loads(args["output_path"].read_bytes()) == receipt


def test_draft_always_verifies_before_selecting_inventory(case):
    args, values, _, calls = case
    draft = {**args, "mode": "draft", "config_path": None, "expected_config_sha256": None,
             "views": ["C@B"]}
    report = cli.run(**draft)
    assert calls == ["verify", "draft"]
    assert report["draft_requires_independent_review_and_pin"]
    assert json.loads(args["output_path"].read_bytes()) == values["config"]


def test_no_go_package_cannot_create_draft(case, monkeypatch):
    args, _, _, calls = case
    monkeypatch.setattr(cli, "verify_audited_task_dataset", lambda *a, **k: {"technical_gate": "no_go"})
    report = cli.run(**{**args, "mode": "draft", "config_path": None, "expected_config_sha256": None})
    assert not calls and not report["output_written"] and report["config_sha256"] is None
    assert report["technical_gate"] == "no_go" and not args["output_path"].exists()


@pytest.mark.parametrize("name", INPUTS)
@pytest.mark.parametrize("pin", [None, True, "A" * 64, "0" * 64])
def test_every_independent_pin_required_before_preparation(case, name, pin):
    args, _, _, calls = case
    with pytest.raises((ValueError, OSError)):
        cli.run(**{**args, "expected_" + name + "_sha256": pin})
    assert not calls and not args["output_path"].exists()


@pytest.mark.parametrize("name", INPUTS)
@pytest.mark.parametrize("change", ["bytes", "inode"])
def test_all_input_bytes_and_identities_reread_before_output(case, monkeypatch, name, change):
    args, _, _, _ = case
    prepare = cli.prepare_audited_baseline_inputs

    def changed(*a, **k):
        result = prepare(*a, **k)
        path = args[name + "_path"]
        if change == "bytes":
            path.write_bytes(b"{}")
        else:
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
        return result

    monkeypatch.setattr(cli, "prepare_audited_baseline_inputs", changed)
    with pytest.raises((ValueError, OSError)):
        cli.run(**args)
    assert not args["output_path"].exists()


@pytest.mark.parametrize("name", ["package", "config", "manifest", "task", "artifact_bytes"])
def test_callee_mutation_cannot_redefine_original_snapshot(case, monkeypatch, name):
    args, _, _, _ = case
    prepare = cli.prepare_audited_baseline_inputs

    def changed(package, **inputs):
        result = prepare(package, **inputs)
        (package if name == "package" else inputs[name])["tampered"] = True
        return result

    monkeypatch.setattr(cli, "prepare_audited_baseline_inputs", changed)
    with pytest.raises(ValueError):
        cli.run(**args)
    assert not args["output_path"].exists()


@pytest.mark.parametrize("field", ["prepared", "diagnostics", "authority", "training_blockers", "implementation"])
def test_resealing_receipt_cannot_forge_preparation(case, field):
    args, _, _, _ = case
    cli.run(**args)
    receipt = json.loads(args["output_path"].read_bytes())
    if field == "training_blockers":
        receipt[field] = []
    elif field == "prepared":
        receipt[field]["arms"][0]["rows"][0]["features"][0] += 1
        receipt["prepared_sha256"] = cli.digest(receipt[field])
    else:
        receipt[field]["forged"] = True
    write(args["output_path"], receipt)
    with pytest.raises(ValueError, match="replay mismatch"):
        cli.run(**verification(args, receipt))


def test_receipt_changed_during_final_input_check_is_refused(case, monkeypatch):
    args, _, _, _ = case
    cli.run(**args)
    receipt = json.loads(args["output_path"].read_bytes())
    read = cli.READERS["label_companion"]
    count = 0

    def changed(*a):
        nonlocal count
        result = read(*a)
        count += 1
        if count == 2:
            args["output_path"].write_bytes(b"{}")
        return result

    monkeypatch.setitem(cli.READERS, "label_companion", changed)
    with pytest.raises(ValueError):
        cli.run(**verification(args, receipt))


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory", "parent_symlink"])
def test_config_aliases_nonregular_files_and_parent_aliases_refused(case, kind, tmp_path):
    args, _, _, calls = case
    path = args["config_path"]
    alias = tmp_path / "alias.json"
    if kind == "symlink":
        alias.symlink_to(path)
    elif kind == "hardlink":
        os.link(path, alias)
    elif kind == "fifo":
        os.mkfifo(alias)
    elif kind == "directory":
        alias.mkdir()
    else:
        directory = tmp_path / "alias"
        directory.symlink_to(tmp_path, target_is_directory=True)
        alias = directory / path.name
    with pytest.raises((ValueError, OSError)):
        cli.run(**{**args, "config_path": alias})
    assert not calls


def test_output_cannot_modify_capsule_or_replace_configuration(case):
    args, _, _, _ = case
    for output in (args["manifest_path"].parent / "output.json", args["config_path"]):
        with pytest.raises((ValueError, OSError)):
            cli.run(**{**args, "output_path": output})
    assert not args["output_path"].exists()


def test_implementation_changed_during_preparation_cannot_write(case, monkeypatch):
    args, _, _, _ = case
    source = cli.implementation()
    count = 0

    def changed():
        nonlocal count
        count += 1
        return source if count == 1 else {**source, "python": "changed"}

    monkeypatch.setattr(cli, "implementation", changed)
    with pytest.raises(ValueError, match="implementation changed"):
        cli.run(**args)
    assert not args["output_path"].exists()


@pytest.mark.parametrize("payload", [b'{"a":0,"a":1}', b'{"a":NaN}', b'{"a":1e999}', b'{ "a":0}', b'\xff'])
def test_pinned_noncanonical_or_invalid_json_is_not_admitted(case, payload):
    args, _, _, calls = case
    args["config_path"].write_bytes(payload)
    with pytest.raises(ValueError):
        cli.run(**{**args, "expected_config_sha256": cli.hashlib.sha256(payload).hexdigest()})
    assert not calls and not args["output_path"].exists()


@pytest.mark.parametrize("change", [
    {"mode": "train"}, {"output_path": None}, {"views": ["C@B"]},
    {"receipt_path": "/unused.json"}, {"expected_receipt_sha256": "a" * 64},
    {"mode": "verify"}, {"config_path": None}, {"mode": "draft"},
])
def test_mixed_modes_or_paths_fail_before_scientific_work(case, change):
    args, _, _, calls = case
    with pytest.raises(ValueError):
        cli.run(**{**args, **change})
    assert not calls


@pytest.mark.parametrize("reason", ["no_features", "no_train", "no_validation", "no_test"])
def test_inoperable_arm_reports_no_go_and_never_writes(case, reason):
    args, _, prepared, _ = case
    arm = prepared["arms"][0]
    if reason == "no_features":
        arm["selected_feature_names"] = []
    else:
        arm["rows"] = [r for r in arm["rows"] if r["split"] != reason[3:]]
    result = cli.run(**args)
    assert result["technical_gate"] == "no_go" and len(result["arm_failures"]) == 1
    assert not result["output_written"] and not args["output_path"].exists()


def test_coverage_is_raw_missingness_not_imputed_value_or_independence(case):
    _, _, prepared, _ = case
    report = cli.diagnostics(prepared)
    arm = next(a for a in report["arms"] if a["arm_id"] == "conditions_B")
    field = next(f for f in arm["features"] if f["name"] == "reported_magnetic_field_t")
    assert [r["missing_count"] for r in field["by_split"]] == [1, 1, 1]
    assert [r["row_count"] for r in field["by_split"]] == [6, 3, 3]
    assert report["independent_support_count"] is None
    pair = next(p for p in report["population_comparisons"]
                if p["left_arm_id"] == "conditions_B" and p["right_arm_id"] == "structure_S")
    assert pair["population_relation"] == "right_subset"
    assert pair["common_row_count"] == 9 and pair["left_only_row_count"] == 3
    assert cli.diagnostics(prepared) == report
    for arm in prepared["arms"]:
        for row in arm["rows"]:
            row["label"] = {"unreadable_target": object()}
    assert cli.diagnostics(prepared) == report


@pytest.mark.parametrize("left,right,relation", [
    ([0, 1], [0, 1], "identical"), ([0], [0, 1], "left_subset"),
    ([0, 1], [0], "right_subset"), ([0, 1], [1, 2], "overlapping"),
    ([0], [1], "disjoint"),
])
def test_population_relationships_never_collapse_nested_or_different_cases(case, left, right, relation):
    _, _, prepared, _ = case
    arms = prepared["arms"][:2]
    original_left, original_right = deepcopy(arms[0]["rows"]), deepcopy(arms[1]["rows"])
    arms[0]["rows"], arms[1]["rows"] = [original_left[i] for i in left], [original_right[i] for i in right]
    prepared["arms"] = arms
    result = cli.diagnostics(prepared)
    comparison = result["population_comparisons"][0]
    assert comparison["population_relation"] == relation
    assert comparison["common_row_count"] == len(set(left) & set(right))
    assert comparison["left_only_row_count"] == len(set(left) - set(right))
    assert comparison["right_only_row_count"] == len(set(right) - set(left))


def test_captured_component_counts_do_not_double_count_same_group_rows(case):
    _, _, prepared, _ = case
    arm = prepared["arms"][0]
    arm["rows"][1]["group_id"] = arm["rows"][0]["group_id"]
    result = cli.diagnostics(prepared)["arms"][0]
    assert result["by_split"][0]["row_count"] == 6
    assert result["by_split"][0]["captured_component_count"] == 5


@pytest.mark.parametrize("flag", ["--approved", "--synthetic", "--train", "--grant", "--out"])
def test_no_flag_opens_training_or_echoes_private_inputs(capsys, flag):
    assert cli.main([*argv(), flag, "PRIVATE_VALUE"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == '{"status":"invalid","output_written":false}\n'


def argv(mode="prepare"):
    result = [mode]
    for name in INPUTS:
        result.extend(["--" + name.replace("_", "-"), "PRIVATE_VALUE",
                       "--" + name.replace("_", "-") + "-sha256", "a" * 64])
    return result + ["--output", "PRIVATE_VALUE"]


@pytest.mark.parametrize("exception", [ValueError, TypeError, OSError, KeyError, AttributeError, RecursionError, OverflowError])
def test_errors_never_echo_scientific_data_or_paths(capsys, monkeypatch, exception):
    def fail(**_):
        raise exception("PRIVATE_VALUE")
    monkeypatch.setattr(cli, "run", fail)
    assert cli.main(argv()) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == '{"status":"invalid","output_written":false}\n'


def test_uncertain_output_is_not_reported_as_absent(capsys, monkeypatch):
    def fail(**_):
        raise cli.OutputStateUnknown("PRIVATE_VALUE")
    monkeypatch.setattr(cli, "run", fail)
    assert cli.main(argv()) == 2
    captured = capsys.readouterr()
    assert not captured.out and json.loads(captured.err) == {"status": "output_state_unknown", "output_written": None}


@pytest.mark.parametrize("gate,exit_code", [("pass", 0), ("no_go", 3)])
def test_main_argument_mapping_and_engineering_exit_codes(capsys, monkeypatch, gate, exit_code):
    def run(**args):
        assert args["config_path"] == args["package_path"] == "PRIVATE_VALUE"
        assert args["expected_manifest_sha256"] == args["expected_config_sha256"] == "a" * 64
        return {"technical_gate": gate, "training_execution": "disabled"}
    monkeypatch.setattr(cli, "run", run)
    assert cli.main(argv()) == exit_code
    assert json.loads(capsys.readouterr().out)["training_execution"] == "disabled"
