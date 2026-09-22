"""Offline filesystem adversaries; synthetic capsules are not scientific approval.

The one pass-gate stub tests output-path admission only, not ML compilation.
Actual successful compilation is covered by the guarded SQL integration suite.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from models.ml_task import default_task
from services.ml_dataset_builder import build_task_dataset
from services.research_release_manifest import canonical, digest

from scripts import ml_task_dataset as cli
from scripts.tests.test_research_release_verifier import fixture, write_bundle


@pytest.fixture
def inputs(tmp_path):
    directory = tmp_path.resolve()
    manifest, artifacts = fixture()
    task = default_task()
    manifest_path = write_bundle(directory, manifest, artifacts)
    task_path = directory / "task.json"
    task_path.write_bytes(canonical(task))
    return {
        "mode": "build", "manifest_path": manifest_path,
        "expected_manifest_sha256": digest(manifest), "task_path": task_path,
        "expected_task_sha256": digest(task), "output_path": directory / "dataset.json",
    }, manifest, artifacts, task


def _replace_same_bytes(path):
    temporary = path.with_name(path.name + ".replacement")
    temporary.write_bytes(path.read_bytes())
    os.replace(temporary, path)


@pytest.mark.parametrize("target", ["task", "manifest", "artifact"])
def test_same_bytes_new_inode_after_compilation_is_refused(inputs, monkeypatch, target):
    args, _, _, _ = inputs
    original = cli.build_task_dataset

    def compile_then_replace(**kwargs):
        bundle = original(**kwargs)
        path = args["task_path"] if target == "task" else args["manifest_path"]
        if target == "artifact":
            path = next(path.parent.glob("*.bin"))
        _replace_same_bytes(path)
        return bundle

    monkeypatch.setattr(cli, "build_task_dataset", compile_then_replace)
    with pytest.raises(ValueError, match="changed during compilation"):
        cli.run(**args)
    assert not args["output_path"].exists()


def test_inventory_added_after_compilation_is_refused(inputs, monkeypatch):
    args, _, _, _ = inputs
    original = cli.build_task_dataset

    def compile_then_add(**kwargs):
        bundle = original(**kwargs)
        (args["manifest_path"].parent / "undeclared.json").write_bytes(b"{}")
        return bundle

    monkeypatch.setattr(cli, "build_task_dataset", compile_then_add)
    with pytest.raises(ValueError, match="unsafe or unknown"):
        cli.run(**args)
    assert not args["output_path"].exists()


def test_verified_bundle_replacement_is_refused_even_with_identical_bytes(inputs, monkeypatch):
    args, manifest, artifacts, task = inputs
    bundle = build_task_dataset(manifest, artifact_bytes=artifacts,
        expected_manifest_sha256=digest(manifest), task=task, expected_task_sha256=digest(task))
    bundle_path = args.pop("output_path")
    # A no-go report may be retained by this test, but the build CLI never publishes it.
    bundle_path.write_bytes(canonical(bundle))
    args.update(mode="verify", bundle_path=bundle_path, expected_bundle_sha256=digest(bundle))
    original = cli.verify_task_dataset

    def verify_then_replace(*values, **kwargs):
        report = original(*values, **kwargs)
        _replace_same_bytes(bundle_path)
        return report

    monkeypatch.setattr(cli, "verify_task_dataset", verify_then_replace)
    with pytest.raises(ValueError, match="bundle changed during verification"):
        cli.run(**args)


def test_in_place_mutation_during_read_is_not_hidden_by_original_payload(tmp_path, monkeypatch):
    path = tmp_path.resolve() / "input.json"
    document = {"synthetic": "before"}
    path.write_bytes(canonical(document))
    identity = path.stat().st_ino
    original_read = os.read
    changed = False

    def read_then_mutate(descriptor, amount):
        nonlocal changed
        payload = original_read(descriptor, amount)
        if payload and not changed and os.fstat(descriptor).st_ino == identity:
            changed = True
            path.write_bytes(canonical({"synthetic": "after!"}))
        return payload

    monkeypatch.setattr(cli.os, "read", read_then_mutate)
    with pytest.raises(ValueError, match="changed during read"):
        cli.read_json(path, digest(document))
    assert changed


@pytest.mark.parametrize("failure", ["zero_write", "write_error", "fsync_error"])
def test_partial_output_failure_leaves_no_published_or_temporary_file(tmp_path, monkeypatch, failure):
    directory = tmp_path.resolve()
    path = directory / "output.json"
    if failure == "zero_write":
        monkeypatch.setattr(cli.os, "write", lambda *_: 0)
    else:
        def fail(*_args):
            raise OSError("synthetic disk failure")
        monkeypatch.setattr(cli.os, "write" if failure == "write_error" else "fsync", fail)
    with pytest.raises((OSError, ValueError)):
        cli.write_new_json(path, {"synthetic": True})
    assert list(directory.iterdir()) == []


def test_competing_output_creator_wins_without_overwrite(tmp_path, monkeypatch):
    directory = tmp_path.resolve()
    output = directory / "output.json"
    competing_bytes = b"synthetic competing writer"
    original_link = os.link

    def create_then_link(source, target, **kwargs):
        assert target == output.name
        output.write_bytes(competing_bytes)
        return original_link(source, target, **kwargs)

    monkeypatch.setattr(cli.os, "link", create_then_link)
    with pytest.raises(FileExistsError):
        cli.write_new_json(output, {"synthetic": True})
    assert output.read_bytes() == competing_bytes
    assert [path.name for path in directory.iterdir()] == [output.name]


def test_no_go_never_touches_existing_output_or_enters_writer(inputs, monkeypatch):
    args, _, _, _ = inputs
    original_bytes = b"synthetic existing artifact"
    args["output_path"].write_bytes(original_bytes)

    def forbidden_write(*_args):
        raise AssertionError("no-go entered publishing code")

    monkeypatch.setattr(cli, "write_new_json", forbidden_write)
    report = cli.run(**args)
    assert report["technical_gate"] == "no_go" and report["output_written"] is False
    assert args["output_path"].read_bytes() == original_bytes


@pytest.mark.parametrize("malformation", ["missing_field", "nested_extra", "bool_number"])
def test_resealed_invalid_task_cannot_bypass_contract(inputs, malformation):
    args, _, _, task = inputs
    if malformation == "missing_field":
        del task["measurement_window"]
    elif malformation == "nested_extra":
        task["pressure"]["unreviewed_ambient_default"] = True
    else:
        task["label_window_k"]["maximum"] = True
    args["task_path"].write_bytes(canonical(task))
    args["expected_task_sha256"] = digest(task)
    with pytest.raises(ValueError):
        cli.run(**args)
    assert not args["output_path"].exists()


def test_output_inside_exact_input_capsule_is_refused(inputs, monkeypatch):
    args, _, _, _ = inputs
    args["output_path"] = args["manifest_path"].parent / "dataset.json"
    before = {path.name: path.read_bytes() for path in args["manifest_path"].parent.iterdir()}
    # Deliberately bypass compilation only to isolate the output filesystem admission gate.
    monkeypatch.setattr(cli, "build_task_dataset", lambda **_: {
        "version": "synthetic-io-test/1", "gate": {"status": "pass", "reason_codes": []},
        "coverage": {}, "authority": {"public_release": False, "scientific_acceptance": False},
    })
    with pytest.raises(ValueError):
        cli.run(**args)
    assert {path.name: path.read_bytes() for path in args["manifest_path"].parent.iterdir()} == before


@pytest.mark.parametrize("argv", [
    ["PRIVATE-INVALID-MODE-CANARY"],
    ["build", "--manifest", "/private/canary/manifest.json", "--manifest-sha256", "0" * 64,
     "--task", "/private/canary/task.json", "--task-sha256", "0" * 64,
     "--unrecognized-private-option", "PRIVATE-ARGUMENT-CANARY"],
])
def test_argument_errors_are_sanitized_without_echoing_inputs(argv, capsys):
    assert cli.main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == '{"status":"invalid","output_written":false}\n'
