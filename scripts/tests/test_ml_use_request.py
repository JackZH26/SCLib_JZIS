"""Intake file/contract boundaries. Rebuild doubles are not scientific evidence."""
from __future__ import annotations

import json
import os
import stat
from copy import deepcopy
from uuid import uuid4

import pytest

from scripts import ml_use_request as cli


@pytest.fixture
def case(tmp_path, monkeypatch):
    capsule = tmp_path / "capsule"
    capsule.mkdir()
    values = {name: {"synthetic_private": name} for name in cli.INPUTS}
    values["manifest"] = {"dataset_id": str(uuid4())}
    values["companion"] = {"base_release_id": str(uuid4()), "bindings": [
        {"id": str(uuid4()), "record_sha256": "a" * 64}]}
    args = {"output_path": tmp_path / "request.json"}
    for name, value in values.items():
        location = (capsule if name == "manifest" else tmp_path) / (name + ".json")
        location.write_bytes(cli.canonical(value))
        args[name + "_path"] = location
        args[name + "_sha256"] = cli.digest(value)
    calls = []

    def replay(**kwargs):
        calls.append(kwargs)
        assert kwargs["mode"] == "verify" and kwargs["output_path"] is None
        for name in cli.INPUTS:
            key = "receipt" if name == "preparation" else name
            assert kwargs[key + "_path"] == args[name + "_path"]
            assert kwargs["expected_" + key + "_sha256"] == args[name + "_sha256"]
        return {"technical_gate": "pass", "preparation_replay_verified": True}
    monkeypatch.setattr(cli.baseline, "run", replay)
    return args, values, calls


def test_private_request_and_exact_replay_carry_only_pins(case):
    args, values, calls = case
    result = cli.run(**args)
    assert len(calls) == 1 and result["baseline_replay_verified_locally"]
    request = json.loads(args["output_path"].read_bytes())
    assert request["version"] == cli.VERSION and request["purpose"] == cli.PURPOSE
    assert request["dataset_id"] == values["manifest"]["dataset_id"]
    assert request["feature_binding_pins"] == values["companion"]["bindings"]
    assert "synthetic_private" not in args["output_path"].read_text()
    assert stat.S_IMODE(args["output_path"].stat().st_mode) == 0o600
    assert result["request_submitted"] is False and result["training_execution"] == "disabled"
    assert all(result[key] is False for key in cli.AUTHORITY)
    checked = cli.run(**{**args, "output_path": None, "request_path": args["output_path"],
                         "expected_request_sha256": cli.digest(request)})
    assert checked["request_replay_verified"] and not checked["output_written"]
    assert len(calls) == 2
    with pytest.raises(FileExistsError):
        cli.run(**args)
    assert json.loads(args["output_path"].read_bytes()) == request


@pytest.mark.parametrize("name", cli.INPUTS)
@pytest.mark.parametrize("pin", [None, True, "A" * 64, "0" * 64])
def test_all_eight_independent_pins_required_before_replay(case, name, pin):
    args, _, calls = case
    with pytest.raises(ValueError):
        cli.run(**{**args, name + "_sha256": pin})
    assert not calls and not args["output_path"].exists()


@pytest.mark.parametrize("name", cli.INPUTS)
@pytest.mark.parametrize("change", ["bytes", "inode"])
def test_inputs_cannot_change_during_baseline_replay(case, monkeypatch, name, change):
    args, _, _ = case
    replay = cli.baseline.run

    def changed(**kwargs):
        result = replay(**kwargs)
        path = args[name + "_path"]
        if change == "bytes":
            path.write_bytes(b"{}")
        else:
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
        return result
    monkeypatch.setattr(cli.baseline, "run", changed)
    with pytest.raises((ValueError, OSError)):
        cli.run(**args)
    assert not args["output_path"].exists()


@pytest.mark.parametrize("mode", ["no_go", "not_verified", "exception"])
def test_failed_baseline_replay_never_writes_request(case, monkeypatch, mode):
    args, _, _ = case

    def failed(**_):
        if mode == "exception":
            raise ValueError("PRIVATE-INPUT")
        return {"technical_gate": "no_go" if mode == "no_go" else "pass", "preparation_replay_verified": False}
    monkeypatch.setattr(cli.baseline, "run", failed)
    with pytest.raises(ValueError):
        cli.run(**args)
    assert not args["output_path"].exists()


@pytest.mark.parametrize("field", ["manifest", "input_pins"])
def test_in_memory_mutation_cannot_redefine_pin_comparison(case, monkeypatch, field):
    args, _, _ = case
    original = cli.prepare_request

    def mutated(**kwargs):
        request = original(**kwargs)
        kwargs[field]["tampered"] = True
        return request
    monkeypatch.setattr(cli, "prepare_request", mutated)
    with pytest.raises(ValueError):
        cli.run(**args)
    assert not args["output_path"].exists()


@pytest.mark.parametrize("field", ["purpose", "dataset_id", "base_release_id", "feature_binding_pins", "input_pins"])
def test_resealed_request_cannot_replace_independent_rebuild(case, field):
    args, _, _ = case
    cli.run(**args)
    request = json.loads(args["output_path"].read_bytes())
    request[field] = "changed" if field not in {"feature_binding_pins", "input_pins"} else []
    args["output_path"].write_bytes(cli.canonical(request))
    with pytest.raises(ValueError):
        cli.run(**{**args, "output_path": None, "request_path": args["output_path"],
                   "expected_request_sha256": cli.digest(request)})


@pytest.mark.parametrize("change", ["extra", "purpose", "missing_pin", "bad_uuid", "duplicate", "unsorted", "too_many", "newline"])
def test_request_contract_is_closed_bounded_and_never_accepts_source_overrides(case, change):
    from models.ml_use_request import validate_request
    args, _, _ = case
    cli.run(**args)
    request = json.loads(args["output_path"].read_bytes())
    if change == "extra":
        request["source_permissions"] = {"approved": True}
    elif change == "purpose":
        request["purpose"] = "training_and_public_release"
    elif change == "missing_pin":
        del request["input_pins"]["label_companion_sha256"]
    elif change == "bad_uuid":
        request["dataset_id"] = "private-path"
    elif change == "duplicate":
        request["feature_binding_pins"] *= 2
    elif change == "unsorted":
        request["feature_binding_pins"] = sorted([request["feature_binding_pins"][0],
            {"id": str(uuid4()), "record_sha256": "b" * 64}], key=lambda r: r["id"], reverse=True)
    elif change == "too_many":
        request["feature_binding_pins"] *= 501
    else:
        request["input_pins"]["task_sha256"] += "\n"
    with pytest.raises(ValueError):
        validate_request(request)


def test_parser_does_not_echo_private_values_or_enable_arbitrary_modes(capsys):
    assert cli.main(["--approved", "private-location"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and json.loads(captured.err) == {"status": "invalid", "output_written": False}


def test_request_file_changed_during_verification_is_not_accepted(case, monkeypatch):
    args, _, _ = case
    cli.run(**args)
    request = json.loads(args["output_path"].read_bytes())
    replay = cli.baseline.run

    def changed(**kwargs):
        result = replay(**kwargs)
        substitute = args["output_path"].with_suffix(".new")
        substitute.write_bytes(args["output_path"].read_bytes())
        substitute.replace(args["output_path"])
        return result
    monkeypatch.setattr(cli.baseline, "run", changed)
    with pytest.raises(ValueError):
        cli.run(**{**args, "output_path": None, "request_path": args["output_path"],
                   "expected_request_sha256": cli.digest(request)})


def test_validation_captures_caller_containers(case):
    from models.ml_use_request import validate_request
    args, _, _ = case
    cli.run(**args)
    request = json.loads(args["output_path"].read_bytes())
    before = deepcopy(request)
    copied = validate_request(request)
    request["input_pins"]["task_sha256"] = "0" * 64
    assert copied == before


@pytest.mark.parametrize("name", cli.INPUTS)
@pytest.mark.parametrize("alias", ["hardlink", "symlink"])
def test_no_aliased_input_is_accepted(case, name, alias):
    args, _, calls = case
    original = args[name + "_path"]
    link = original.with_name("alias-" + original.name)
    if alias == "hardlink":
        os.link(original, link)
    else:
        link.symlink_to(original)
        args[name + "_path"] = link
    with pytest.raises((ValueError, OSError)):
        cli.run(**args)
    assert not calls and not args["output_path"].exists()
