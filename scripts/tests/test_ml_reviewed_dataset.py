"""Offline file/CLI gates; service doubles are not evidence of science admission."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
from copy import deepcopy
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ml_reviewed_dataset_cli",
    Path(__file__).resolve().parents[1] / "ml_reviewed_dataset.py",
)
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


def write(path, value):
    payload = cli.canonical(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def case(tmp_path, monkeypatch, *, gate="pass"):
    capsule = tmp_path / "capsule"
    capsule.mkdir()
    manifest = capsule / "manifest.json"
    task, companion, review = [
        tmp_path / name for name in ("task.json", "source.json", "review.json")
    ]
    values = [
        {"synthetic_manifest": True},
        {"synthetic_task": True},
        {"synthetic_source": True},
        {"synthetic_review": True},
    ]
    hashes = [
        write(path, value)
        for path, value in zip((manifest, task, companion, review), values)
    ]
    bundle = {
        "version": "ml-task-dataset/3.0.0",
        "gate": {
            "status": gate,
            "reason_codes": []
            if gate == "pass"
            else ["required_comparison_view_no_go"],
            "no_go_views": [] if gate == "pass" else ["CP@P"],
        },
        "coverage": {"included_count": 3},
        "input_pins": {"review_observation_sha256": "a" * 64},
        "authority": {"scientific_acceptance": False, "ml_training_approved": False},
    }
    calls = []

    def build(**arguments):
        calls.append(deepcopy(arguments))
        return deepcopy(bundle)

    def verify(value, **arguments):
        assert value == bundle
        assert arguments.pop("expected_bundle_sha256") == cli.digest(bundle)
        build(**arguments)
        return {
            "version": bundle["version"],
            "technical_gate": gate,
            "integrity_verified": True,
            **bundle["authority"],
        }

    monkeypatch.setattr(cli, "build_task_dataset_v3", build)
    monkeypatch.setattr(cli, "verify_task_dataset_v3", verify)
    return (
        {
            "mode": "build",
            "manifest_path": manifest,
            "expected_manifest_sha256": hashes[0],
            "task_path": task,
            "expected_task_sha256": hashes[1],
            "companion_path": companion,
            "expected_companion_sha256": hashes[2],
            "review_companion_path": review,
            "expected_review_companion_sha256": hashes[3],
            "output_path": tmp_path / "result.json",
        },
        bundle,
        calls,
    )


def test_every_independent_document_reaches_v3_and_new_private_output(
    tmp_path, monkeypatch
):
    arguments, bundle, calls = case(tmp_path, monkeypatch)
    report = cli.run(**arguments)
    assert (
        report["output_written"] is True
        and report["review_scope"] == "captured_observation_not_current_authorization"
    )
    assert calls[0]["review_companion"] == {"synthetic_review": True}
    assert (
        calls[0]["expected_review_companion_sha256"]
        == arguments["expected_review_companion_sha256"]
    )
    output = arguments["output_path"]
    assert output.read_bytes() == cli.canonical(bundle)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600 and output.stat().st_nlink == 1
    with pytest.raises(FileExistsError):
        cli.run(**arguments)
    assert output.read_bytes() == cli.canonical(bundle)
    assert not list(tmp_path.glob(".ml-task-*"))


def test_verify_calls_full_v3_recomputation_and_writes_nothing(tmp_path, monkeypatch):
    arguments, bundle, calls = case(tmp_path, monkeypatch)
    output = arguments.pop("output_path")
    bundle_path = tmp_path / "bundle.json"
    arguments.update(
        mode="verify",
        bundle_path=bundle_path,
        expected_bundle_sha256=write(bundle_path, bundle),
    )
    report = cli.run(**arguments)
    assert report["integrity_verified"] is True and report["output_written"] is False
    assert len(calls) == 1 and not output.exists()


def test_no_go_never_publishes_output(tmp_path, monkeypatch):
    arguments, _, _ = case(tmp_path, monkeypatch, gate="no_go")
    report = cli.run(**arguments)
    assert report["technical_gate"] == "no_go" and report["output_written"] is False
    assert not arguments["output_path"].exists()


@pytest.mark.parametrize(
    "field",
    [
        "expected_manifest_sha256",
        "expected_companion_sha256",
        "expected_review_companion_sha256",
        "expected_task_sha256",
    ],
)
def test_each_wrong_whole_file_pin_rejects_before_compiler(
    tmp_path, monkeypatch, field
):
    arguments, _, calls = case(tmp_path, monkeypatch)
    arguments[field] = "f" * 64
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not calls and not arguments["output_path"].exists()


@pytest.mark.parametrize(
    "field", ["manifest_path", "companion_path", "review_companion_path", "task_path"]
)
@pytest.mark.parametrize("change", ["bytes", "inode"])
def test_changes_during_build_rejected_before_output(
    tmp_path, monkeypatch, field, change
):
    arguments, bundle, _ = case(tmp_path, monkeypatch)

    def build(**_arguments):
        path = arguments[field]
        if change == "bytes":
            write(path, {"changed": True})
        else:
            replacement = tmp_path / "replacement.json"
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)
        return bundle

    monkeypatch.setattr(cli, "build_task_dataset_v3", build)
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not arguments["output_path"].exists()


def test_compiled_bundle_change_during_verify_rejected(tmp_path, monkeypatch):
    arguments, bundle, _ = case(tmp_path, monkeypatch)
    arguments.pop("output_path")
    path = tmp_path / "bundle.json"
    arguments.update(
        mode="verify", bundle_path=path, expected_bundle_sha256=write(path, bundle)
    )

    def verify(*_args, **_kwargs):
        write(path, {"tampered": True})
        return {"technical_gate": "pass"}

    monkeypatch.setattr(cli, "verify_task_dataset_v3", verify)
    with pytest.raises(ValueError):
        cli.run(**arguments)


@pytest.mark.parametrize(
    "kind", ["symlink", "hardlink", "fifo", "directory", "parent_symlink"]
)
def test_review_document_alias_or_nonregular_rejected(tmp_path, monkeypatch, kind):
    arguments, _, calls = case(tmp_path, monkeypatch)
    source = arguments["review_companion_path"]
    path = tmp_path / "aliased.json"
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
    arguments["review_companion_path"] = path
    with pytest.raises((ValueError, OSError)):
        cli.run(**arguments)
    assert not calls


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
        b'{"a":1e999}',
        b'{ "a":1}',
        b"{}\n",
        b"\xff",
        b"[" * 1000 + b"]" * 1000,
    ],
)
def test_review_strict_json_canonical_and_depth_gate(tmp_path, monkeypatch, payload):
    arguments, _, calls = case(tmp_path, monkeypatch)
    arguments["review_companion_path"].write_bytes(payload)
    arguments["expected_review_companion_sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises((ValueError, RecursionError)):
        cli.run(**arguments)
    assert not calls


@pytest.mark.parametrize(
    "path", ["relative.json", "https://example.invalid/review.json"]
)
def test_review_no_relative_or_network_paths(tmp_path, monkeypatch, path):
    arguments, _, calls = case(tmp_path, monkeypatch)
    arguments["review_companion_path"] = path
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not calls


def test_review_observation_larger_than_old_reader_but_within_new_bound(tmp_path):
    path = tmp_path / "review.json"
    value = {"synthetic_private_text": "x" * (8 * 1024 * 1024)}
    expected = write(path, value)
    assert cli.read_review_companion(path, expected)[0] == value


def test_review_observation_over_limit_rejected_before_read(tmp_path, monkeypatch):
    path = tmp_path / "review.json"
    with path.open("wb") as handle:
        handle.truncate(cli.MAX_REVIEW_BYTES + 1)
    monkeypatch.setattr(
        cli.os, "read", lambda *_: pytest.fail("oversized bytes were read")
    )
    with pytest.raises(ValueError):
        cli.read_review_companion(path, "f" * 64)


def test_output_cannot_change_closed_capsule_inventory(tmp_path, monkeypatch):
    arguments, _, _ = case(tmp_path, monkeypatch)
    arguments["output_path"] = arguments["manifest_path"].parent / "output.json"
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not arguments["output_path"].exists()


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "unknown"},
        {"bundle_path": "bad"},
        {"expected_bundle_sha256": "f" * 64},
        {"output_path": None},
    ],
)
def test_invalid_mode_or_mixed_paths_rejected(tmp_path, monkeypatch, change):
    arguments, _, calls = case(tmp_path, monkeypatch)
    arguments.update(change)
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not calls


def test_cli_missing_pins_static_error_does_not_echo_private_input(capsys):
    assert cli.main(["build", "--manifest", "PRIVATE-SOURCE-CREDENTIAL"]) == 2
    captured = capsys.readouterr()
    assert (
        captured.out == ""
        and captured.err == '{"status":"invalid","output_written":false}\n'
    )


@pytest.mark.parametrize("exception", [ValueError, OSError, TypeError, RecursionError])
def test_cli_runtime_error_is_sanitized(capsys, monkeypatch, exception):
    def fail(**_kwargs):
        raise exception("PRIVATE-SOURCE-CREDENTIAL")

    monkeypatch.setattr(cli, "run", fail)
    arguments = ["build"]
    for name in (
        "manifest",
        "manifest-sha256",
        "companion",
        "companion-sha256",
        "review-companion",
        "review-companion-sha256",
        "task",
        "task-sha256",
    ):
        arguments += ["--" + name, "PRIVATE-SOURCE-CREDENTIAL"]
    assert cli.main(arguments) == 2
    captured = capsys.readouterr()
    assert (
        captured.out == ""
        and captured.err == '{"status":"invalid","output_written":false}\n'
    )


@pytest.mark.parametrize("gate,expected", [("pass", 0), ("no_go", 3)])
def test_cli_technical_exit_code_is_not_scientific_authority(
    capsys, monkeypatch, gate, expected
):
    monkeypatch.setattr(
        cli, "run", lambda **_: {"technical_gate": gate, "scientific_acceptance": False}
    )
    arguments = ["build"]
    for name in (
        "manifest",
        "manifest-sha256",
        "companion",
        "companion-sha256",
        "review-companion",
        "review-companion-sha256",
        "task",
        "task-sha256",
    ):
        arguments += ["--" + name, "synthetic"]
    assert cli.main(arguments) == expected
    assert '"scientific_acceptance":false' in capsys.readouterr().out
