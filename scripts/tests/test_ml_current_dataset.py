"""Offline v4 file/task boundary tests; CLI doubles do not establish science."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
from copy import deepcopy
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("ml_current_dataset_cli", Path(__file__).resolve().parents[1] / "ml_current_dataset.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)

INPUTS = ("manifest", "task", "companion", "review_companion", "label_companion")
PIN_NAMES = ("manifest", "manifest-sha256", "companion", "companion-sha256", "review-companion",
             "review-companion-sha256", "label-companion", "label-companion-sha256", "task", "task-sha256")


def write(path, value):
    payload = cli.canonical(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def case(tmp_path, monkeypatch, *, gate="pass"):
    capsule = tmp_path / "capsule"
    capsule.mkdir()
    paths = {name: tmp_path / (name + ".json") for name in INPUTS}
    paths["manifest"] = capsule / "manifest.json"
    values = {name: {"synthetic_" + name: True} for name in INPUTS}
    bundle = {
        "version": "ml-task-dataset/4.0.0",
        "gate": {"status": gate, "reason_codes": [] if gate == "pass" else ["required_comparison_view_no_go"],
                 "no_go_views": [] if gate == "pass" else ["C@B"]},
        "coverage": {"included_count": 3},
        "input_pins": {"review_observation_sha256": "a" * 64, "label_observation_sha256": "b" * 64},
        "authority": {"scientific_acceptance": False, "ml_training_approved": False},
    }
    arguments = {"mode": "build", "output_path": tmp_path / "result.json"}
    for name in INPUTS:
        arguments[name + "_path"] = paths[name]
        arguments["expected_" + name + "_sha256"] = write(paths[name], values[name])
    calls = []

    def build(**inputs):
        calls.append(deepcopy(inputs))
        return deepcopy(bundle)

    def verify(value, **inputs):
        assert value == bundle
        assert inputs.pop("expected_bundle_sha256") == cli.digest(bundle)
        build(**inputs)
        return {"version": bundle["version"], "technical_gate": gate, "integrity_verified": True,
                **bundle["authority"]}

    monkeypatch.setattr(cli, "build_task_dataset_v4", build)
    monkeypatch.setattr(cli, "verify_task_dataset_v4", verify)
    return arguments, bundle, calls


def test_five_independently_pinned_inputs_reach_v4_and_private_atomic_output(tmp_path, monkeypatch):
    arguments, bundle, calls = case(tmp_path, monkeypatch)
    report = cli.run(**arguments)
    assert report["output_written"] is True
    assert report["label_currentness_scope"] == "captured_negative_only_not_live_authorization"
    assert report["label_observation_sha256"] == "b" * 64
    for name in INPUTS:
        assert calls[0][name] == {"synthetic_" + name: True}
        assert calls[0]["expected_" + name + "_sha256"] == arguments["expected_" + name + "_sha256"]
    output = arguments["output_path"]
    assert output.read_bytes() == cli.canonical(bundle)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600 and output.stat().st_nlink == 1
    with pytest.raises(FileExistsError):
        cli.run(**arguments)
    assert output.read_bytes() == cli.canonical(bundle) and not list(tmp_path.glob(".ml-task-*"))


def test_verify_invokes_full_v4_recomputation_without_output(tmp_path, monkeypatch):
    arguments, bundle, calls = case(tmp_path, monkeypatch)
    output = arguments.pop("output_path")
    path = tmp_path / "bundle.json"
    arguments.update(mode="verify", bundle_path=path, expected_bundle_sha256=write(path, bundle))
    report = cli.run(**arguments)
    assert report["integrity_verified"] is True and report["output_written"] is False
    assert len(calls) == 1 and not output.exists()


def test_no_go_does_not_publish_partial_label_filtered_output(tmp_path, monkeypatch):
    arguments, _, _ = case(tmp_path, monkeypatch, gate="no_go")
    report = cli.run(**arguments)
    assert report["technical_gate"] == "no_go" and report["output_written"] is False
    assert not arguments["output_path"].exists()


@pytest.mark.parametrize("name", INPUTS)
@pytest.mark.parametrize("pin", ["f" * 64, None, False, "bad"])
def test_each_independent_pin_is_required_before_compiler(tmp_path, monkeypatch, name, pin):
    arguments, _, calls = case(tmp_path, monkeypatch)
    arguments["expected_" + name + "_sha256"] = pin
    with pytest.raises((ValueError, TypeError)):
        cli.run(**arguments)
    assert not calls and not arguments["output_path"].exists()


@pytest.mark.parametrize("name", INPUTS)
@pytest.mark.parametrize("change", ["bytes", "inode"])
def test_all_inputs_rechecked_after_compilation_before_publish(tmp_path, monkeypatch, name, change):
    arguments, bundle, _ = case(tmp_path, monkeypatch)

    def build(**_inputs):
        path = arguments[name + "_path"]
        if change == "bytes":
            write(path, {"changed": True})
        else:
            replacement = tmp_path / "replacement.json"
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)
        return bundle

    monkeypatch.setattr(cli, "build_task_dataset_v4", build)
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not arguments["output_path"].exists()


def test_verify_rechecks_bundle_identity_and_bytes(tmp_path, monkeypatch):
    arguments, bundle, _ = case(tmp_path, monkeypatch)
    arguments.pop("output_path")
    path = tmp_path / "bundle.json"
    arguments.update(mode="verify", bundle_path=path, expected_bundle_sha256=write(path, bundle))

    def verify(*_args, **_kwargs):
        write(path, {"tampered": True})
        return {"technical_gate": "pass"}

    monkeypatch.setattr(cli, "verify_task_dataset_v4", verify)
    with pytest.raises(ValueError):
        cli.run(**arguments)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory", "parent_symlink"])
def test_label_companion_aliases_and_nonregular_files_fail_closed(tmp_path, monkeypatch, kind):
    arguments, _, calls = case(tmp_path, monkeypatch)
    source, path = arguments["label_companion_path"], tmp_path / "alias.json"
    if kind == "symlink":
        path.symlink_to(source)
    elif kind == "hardlink":
        os.link(source, path)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        parent = tmp_path / "alias"
        parent.symlink_to(tmp_path, target_is_directory=True)
        path = parent / source.name
    arguments["label_companion_path"] = path
    with pytest.raises((ValueError, OSError)):
        cli.run(**arguments)
    assert not calls


@pytest.mark.parametrize("payload", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}',
                                     b'{ "x":1}', b'{}\n', b'\xff', b'[' * 1000 + b']' * 1000])
def test_label_canonical_json_and_depth_bounds(tmp_path, monkeypatch, payload):
    arguments, _, calls = case(tmp_path, monkeypatch)
    arguments["label_companion_path"].write_bytes(payload)
    arguments["expected_label_companion_sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises((ValueError, RecursionError)):
        cli.run(**arguments)
    assert not calls


@pytest.mark.parametrize("path", ["relative.json", "https://example.invalid/label.json"])
def test_label_reader_never_fetches_network_or_relative_paths(tmp_path, monkeypatch, path):
    arguments, _, calls = case(tmp_path, monkeypatch)
    arguments["label_companion_path"] = path
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not calls


def test_label_reader_supports_bounded_private_observations_above_old_json_limit(tmp_path):
    path = tmp_path / "label.json"
    value = {"private_synthetic_text": "x" * (8 * 1024 * 1024)}
    assert cli.read_label_companion(path, write(path, value))[0] == value


def test_oversized_label_refused_before_hydration(tmp_path, monkeypatch):
    path = tmp_path / "label.json"
    with path.open("wb") as handle:
        handle.truncate(cli.MAX_LABEL_BYTES + 1)
    monkeypatch.setattr(cli.os, "read", lambda *_: pytest.fail("oversized bytes were read"))
    with pytest.raises(ValueError):
        cli.read_label_companion(path, "a" * 64)


def test_output_cannot_modify_closed_capsule_inventory(tmp_path, monkeypatch):
    arguments, _, _ = case(tmp_path, monkeypatch)
    arguments["output_path"] = arguments["manifest_path"].parent / "output.json"
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not arguments["output_path"].exists()


@pytest.mark.parametrize("change", [{"mode": "unknown"}, {"output_path": None},
                                    {"bundle_path": "bad"}, {"expected_bundle_sha256": "a" * 64}])
def test_invalid_modes_and_mixed_output_paths_reject(tmp_path, monkeypatch, change):
    arguments, _, calls = case(tmp_path, monkeypatch)
    arguments.update(change)
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not calls


def test_missing_label_pin_is_static_cli_error(capsys):
    assert cli.main(["build", "--label-companion", "PRIVATE-SOURCE-CREDENTIAL"]) == 2
    result = capsys.readouterr()
    assert result.out == "" and result.err == '{"status":"invalid","output_written":false}\n'


@pytest.mark.parametrize("exception", [ValueError, OSError, TypeError, RecursionError])
def test_runtime_errors_do_not_echo_private_inputs(capsys, monkeypatch, exception):
    def fail(**_kwargs):
        raise exception("PRIVATE-SOURCE-CREDENTIAL")
    monkeypatch.setattr(cli, "run", fail)
    arguments = ["build"]
    for name in PIN_NAMES:
        arguments += ["--" + name, "PRIVATE-SOURCE-CREDENTIAL"]
    assert cli.main(arguments) == 2
    result = capsys.readouterr()
    assert result.out == "" and result.err == '{"status":"invalid","output_written":false}\n'


@pytest.mark.parametrize("gate,code", [("pass", 0), ("no_go", 3)])
def test_cli_exit_code_is_technical_not_scientific_authority(capsys, monkeypatch, gate, code):
    monkeypatch.setattr(cli, "run", lambda **_: {"technical_gate": gate, "scientific_acceptance": False})
    arguments = ["build"]
    for name in PIN_NAMES:
        arguments += ["--" + name, "synthetic"]
    assert cli.main(arguments) == code
    assert '"scientific_acceptance":false' in capsys.readouterr().out


def test_v4_task_preserves_closed_v3_contract_and_detaches():
    from models.ml_task_v3 import default_task_v3, validate_task_v3
    from models.ml_task_v4 import default_task_v4, validate_task_v4
    old = default_task_v3()
    task = default_task_v4()
    result = validate_task_v4(task)
    assert result == task and result is not task and result["label_task"] is not task["label_task"]
    projected = {key: value for key, value in task.items() if key != "label_currentness_policy"}
    projected["version"] = old["version"]
    assert validate_task_v3(projected) == projected
    assert default_task_v3() == old


@pytest.mark.parametrize("field,value", [("version", "ml-task/3.0.0"), ("version", False),
    ("label_currentness_policy", "live"), ("label_currentness_policy", True), ("extra", 1),
    ("exact_result_review_policy", "positive_approval")])
def test_v4_task_does_not_relax_unknown_or_older_contracts(field, value):
    from models.ml_task_v4 import default_task_v4, validate_task_v4
    task = default_task_v4()
    task[field] = value
    with pytest.raises(ValueError):
        validate_task_v4(task)


@pytest.mark.parametrize("field", ["label_currentness_policy", "label_task", "exact_result_review_policy"])
def test_v4_task_missing_required_policies_reject(field):
    from models.ml_task_v4 import default_task_v4, validate_task_v4
    task = default_task_v4()
    del task[field]
    with pytest.raises(ValueError):
        validate_task_v4(task)
