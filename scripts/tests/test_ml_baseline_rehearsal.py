"""Fixed-rehearsal command/file boundary; doubles here prove no model science."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
from copy import deepcopy
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("ml_baseline_rehearsal_cli", Path(__file__).resolve().parents[1] / "ml_baseline_rehearsal.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


@pytest.fixture
def double(monkeypatch):
    from services.ml_dataset_builder import AUTHORITY
    report = {"gate": {"status": "pass"}}
    receipt = {"version": "ml-baseline-rehearsal/1.0.0", "scope": "synthetic-command-double-only",
               "fixture_sha256": "a" * 64, "report": report, "report_sha256": cli.digest(report),
               "authority": dict(AUTHORITY)}
    calls = []

    def build():
        calls.append("build_fixed")
        return deepcopy(receipt)

    def verify(value, *, expected_receipt_sha256):
        calls.append("verify_fixed")
        assert value == receipt and expected_receipt_sha256 == cli.digest(receipt)
        return {"technical_gate": receipt["report"]["gate"]["status"], "numerical_replay_verified": True, **AUTHORITY}

    monkeypatch.setattr(cli, "run_synthetic_rehearsal", build)
    monkeypatch.setattr(cli, "verify_synthetic_rehearsal", verify)
    return receipt, calls


def retained(tmp_path, value):
    path = tmp_path / "receipt.json"
    payload = cli.canonical(value)
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


def test_private_no_clobber_output_and_independent_replay_pin(tmp_path, double):
    receipt, calls = double
    output = tmp_path / "rehearsal.json"
    report = cli.run(mode="build", output_path=output)
    assert calls == ["build_fixed"] and report["output_written"] is True
    assert report["receipt_sha256"] == cli.digest(receipt)
    assert output.read_bytes() == cli.canonical(receipt)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600 and output.stat().st_nlink == 1
    checked = cli.run(mode="verify", receipt_path=output, expected_receipt_sha256=cli.digest(receipt))
    assert checked["numerical_replay_verified"] and checked["output_written"] is False
    with pytest.raises(FileExistsError):
        cli.run(mode="build", output_path=output)
    assert output.read_bytes() == cli.canonical(receipt)


@pytest.mark.parametrize("status", ["no_go", "forged_success", True, None])
def test_no_go_or_invalid_gate_never_writes(tmp_path, double, status):
    receipt, _ = double
    receipt["report"]["gate"]["status"] = status
    output = tmp_path / "refused.json"
    if status == "no_go":
        assert cli.run(mode="build", output_path=output)["output_written"] is False
    else:
        with pytest.raises(ValueError):
            cli.run(mode="build", output_path=output)
    assert not output.exists()


@pytest.mark.parametrize("arguments", [
    {"mode": "unknown"}, {"mode": "build"}, {"mode": "verify"},
    {"mode": "build", "output_path": "/unused", "receipt_path": "/unused"},
    {"mode": "build", "output_path": "/unused", "expected_receipt_sha256": "a" * 64},
    {"mode": "verify", "output_path": "/unused", "receipt_path": "/unused"},
])
def test_mixed_paths_refused_before_any_work(double, arguments):
    _, calls = double
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not calls


@pytest.mark.parametrize("flag", ["--dataset", "--manifest", "--config", "--approved", "--synthetic", "--seed", "--model", "--out"])
def test_caller_data_or_approval_flags_cannot_activate_fit(capsys, double, flag):
    _, calls = double
    assert cli.main(["build", flag, "PRIVATE_INPUT"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == '{"status":"invalid","output_written":false}\n'
    assert not calls


@pytest.mark.parametrize("pin", [None, True, "a" * 63, "A" * 64, "0" * 64])
def test_bad_independent_pin_rejected_before_replay(tmp_path, double, pin):
    receipt, calls = double
    path, _ = retained(tmp_path, receipt)
    with pytest.raises(ValueError):
        cli.run(mode="verify", receipt_path=path, expected_receipt_sha256=pin)
    assert not calls


@pytest.mark.parametrize("mutation", ["bytes", "inode", "hardlink", "symlink"])
def test_complete_receipt_reread_after_replay(tmp_path, double, monkeypatch, mutation):
    receipt, _ = double
    path, pin = retained(tmp_path, receipt)
    verify = cli.verify_synthetic_rehearsal

    def change(value, **kwargs):
        result = verify(value, **kwargs)
        if mutation == "bytes":
            path.write_bytes(cli.canonical({**receipt, "tampered": True}))
        elif mutation == "inode":
            replacement = tmp_path / "replacement.json"
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
        elif mutation == "hardlink":
            os.link(path, tmp_path / "alias.json")
        else:
            moved = tmp_path / "moved.json"
            path.rename(moved)
            path.symlink_to(moved)
        return result

    monkeypatch.setattr(cli, "verify_synthetic_rehearsal", change)
    with pytest.raises((ValueError, OSError)):
        cli.run(mode="verify", receipt_path=path, expected_receipt_sha256=pin)


@pytest.mark.parametrize("payload", [b'{"duplicate":0,"duplicate":1}', b'{"n":NaN}', b'{"n":Infinity}', b'{ "space":1}', b'\xff'])
def test_noncanonical_and_invalid_json_refused_before_replay(tmp_path, double, payload):
    _, calls = double
    path = tmp_path / "invalid.json"
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        cli.run(mode="verify", receipt_path=path, expected_receipt_sha256=hashlib.sha256(payload).hexdigest())
    assert not calls


@pytest.mark.parametrize("exception", [ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError, OverflowError])
def test_errors_are_static_and_do_not_echo_private_inputs(capsys, monkeypatch, exception):
    def fail(**_kwargs):
        raise exception("PRIVATE_INPUT")
    monkeypatch.setattr(cli, "run", fail)
    assert cli.main(["build", "--output", "PRIVATE_INPUT"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == '{"status":"invalid","output_written":false}\n'


def test_uncertain_output_preserves_unknown_semantics(capsys, monkeypatch):
    def fail(**_kwargs):
        raise cli.OutputStateUnknown("PRIVATE_INPUT")
    monkeypatch.setattr(cli, "run", fail)
    assert cli.main(["build", "--output", "PRIVATE_INPUT"]) == 2
    result = capsys.readouterr()
    assert result.out == "" and json.loads(result.err) == {"status": "output_state_unknown", "output_written": None}


@pytest.mark.parametrize("status,code", [("pass", 0), ("no_go", 3)])
def test_exit_codes_are_engineering_not_scientific_approval(capsys, monkeypatch, status, code):
    monkeypatch.setattr(cli, "run", lambda **_: {"technical_gate": status, "scientific_acceptance": False})
    assert cli.main(["build", "--output", "unused"]) == code
    assert json.loads(capsys.readouterr().out)["scientific_acceptance"] is False
