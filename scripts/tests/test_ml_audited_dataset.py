"""Mandatory audited-package file boundaries; compiler doubles prove no science."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
from copy import deepcopy
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("ml_audited_dataset_cli", Path(__file__).resolve().parents[1] / "ml_audited_dataset.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)

INPUTS = ("manifest", "task", "companion", "review_companion", "label_companion")
PIN_NAMES = ("manifest", "manifest-sha256", "companion", "companion-sha256", "review-companion",
             "review-companion-sha256", "label-companion", "label-companion-sha256", "task", "task-sha256")


def write(path, value):
    payload = cli.canonical(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def case(tmp_path, monkeypatch, *, base_gate="pass", audit_gate="pass"):
    from services.ml_dataset_builder import AUTHORITY

    capsule = tmp_path / "capsule"
    capsule.mkdir()
    paths = {name: tmp_path / (name + ".json") for name in INPUTS}
    paths["manifest"] = capsule / "manifest.json"
    gate = "pass" if base_gate == audit_gate == "pass" else "no_go"
    base = {"version": "ml-task-dataset/4.0.0",
            "gate": {"status": base_gate}, "coverage": {"included_count": 3},
            "input_pins": {"review_observation_sha256": "a" * 64, "label_observation_sha256": "b" * 64},
            "authority": dict(AUTHORITY)}
    audit = {"version": "ml-identity-audit/1.0.0", "gate": {"status": audit_gate},
             "independent_support_count": None, "authority": dict(AUTHORITY)}
    package = {
        "version": "ml-identity-audited-dataset/1.0.0",
        "base_dataset": base, "base_dataset_sha256": cli.digest(base),
        "identity_audit": audit, "identity_audit_sha256": cli.digest(audit),
        "audit_policy_version": "captured-typed-identity/1.0.0",
        "gate": {"status": gate, "reason_codes": [] if gate == "pass" else ["synthetic_no_go"]},
        "authority": dict(AUTHORITY),
    }
    arguments = {"mode": "build", "output_path": tmp_path / "output.json"}
    for name in INPUTS:
        arguments[name + "_path"] = paths[name]
        arguments["expected_" + name + "_sha256"] = write(paths[name], {"synthetic_" + name: True})
    calls = []

    def build(**inputs):
        calls.append(deepcopy(inputs))
        return deepcopy(package)

    def verify(value, **inputs):
        assert value == package
        assert inputs.pop("expected_package_sha256") == cli.digest(package)
        build(**inputs)
        return {"version": package["version"], "technical_gate": gate, "integrity_verified": True,
                "package_sha256": cli.digest(package), **package["authority"]}

    monkeypatch.setattr(cli, "build_audited_task_dataset", build)
    monkeypatch.setattr(cli, "verify_audited_task_dataset", verify)
    return arguments, package, calls


def test_all_five_pins_and_mandatory_wrapper_reach_private_no_clobber_output(tmp_path, monkeypatch):
    arguments, package, calls = case(tmp_path, monkeypatch)
    report = cli.run(**arguments)
    assert report["technical_gate"] == report["base_technical_gate"] == report["identity_technical_gate"] == "pass"
    assert report["output_written"] is True and report["independent_support_count"] is None
    assert report["package_sha256"] == cli.digest(package)
    assert report["identity_scope"] == "captured_identity_integrity_not_scientific_independence"
    assert report["label_observation_sha256"] == "b" * 64
    for name in INPUTS:
        assert calls[0][name] == {"synthetic_" + name: True}
        assert calls[0]["expected_" + name + "_sha256"] == arguments["expected_" + name + "_sha256"]
    output = arguments["output_path"]
    assert output.read_bytes() == cli.canonical(package)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600 and output.stat().st_nlink == 1
    with pytest.raises(FileExistsError):
        cli.run(**arguments)
    assert output.read_bytes() == cli.canonical(package)
    assert not list(tmp_path.glob(".ml-audited-*"))


@pytest.mark.parametrize("base,audit", [("pass", "no_go"), ("no_go", "pass"), ("no_go", "no_go")])
def test_either_no_go_prevents_partial_package_output(tmp_path, monkeypatch, base, audit):
    arguments, _, _ = case(tmp_path, monkeypatch, base_gate=base, audit_gate=audit)
    report = cli.run(**arguments)
    assert report["technical_gate"] == "no_go" and report["output_written"] is False
    assert not arguments["output_path"].exists() and not list(tmp_path.glob(".ml-audited-*"))


@pytest.mark.parametrize("base,audit", [("pass", "no_go"), ("no_go", "pass"), ("no_go", "no_go")])
def test_forged_outer_pass_cannot_bypass_either_child_gate(tmp_path, monkeypatch, base, audit):
    arguments, package, _ = case(tmp_path, monkeypatch, base_gate=base, audit_gate=audit)
    package["gate"]["status"] = "pass"
    with pytest.raises(ValueError, match="aggregate gate"):
        cli.run(**arguments)
    assert not arguments["output_path"].exists()


def test_verify_calls_complete_recomputation_without_writing(tmp_path, monkeypatch):
    arguments, package, calls = case(tmp_path, monkeypatch)
    output = arguments.pop("output_path")
    path = tmp_path / "package.json"
    arguments.update(mode="verify", bundle_path=path, expected_bundle_sha256=write(path, package))
    report = cli.run(**arguments)
    assert report["integrity_verified"] is True and report["output_written"] is False
    assert len(calls) == 1 and not output.exists()


@pytest.mark.parametrize("name", INPUTS)
@pytest.mark.parametrize("pin", ["f" * 64, None, False, "invalid"])
def test_every_independent_pin_is_checked_before_build(tmp_path, monkeypatch, name, pin):
    arguments, _, calls = case(tmp_path, monkeypatch)
    arguments["expected_" + name + "_sha256"] = pin
    with pytest.raises((ValueError, TypeError)):
        cli.run(**arguments)
    assert not calls and not arguments["output_path"].exists()


@pytest.mark.parametrize("name", INPUTS)
@pytest.mark.parametrize("change", ["bytes", "inode"])
def test_rechecks_all_input_bytes_and_identities_before_output(tmp_path, monkeypatch, name, change):
    arguments, package, _ = case(tmp_path, monkeypatch)
    def changed(**_inputs):
        path = arguments[name + "_path"]
        if change == "bytes":
            write(path, {"changed": True})
        else:
            replacement = tmp_path / "replacement.json"
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)
        return package
    monkeypatch.setattr(cli, "build_audited_task_dataset", changed)
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not arguments["output_path"].exists()


@pytest.mark.parametrize("moment", ["inside_verify", "during_final_input_recheck"])
def test_package_is_rechecked_after_verification_and_all_input_rechecks(tmp_path, monkeypatch, moment):
    arguments, package, _ = case(tmp_path, monkeypatch)
    arguments.pop("output_path")
    path = tmp_path / "package.json"
    arguments.update(mode="verify", bundle_path=path, expected_bundle_sha256=write(path, package))
    if moment == "inside_verify":
        def changed(*_args, **_kwargs):
            write(path, {"changed": True})
            return {"technical_gate": "pass"}
        monkeypatch.setattr(cli, "verify_audited_task_dataset", changed)
    else:
        original, calls = cli.read_label_companion, []
        def read(*args):
            result = original(*args)
            calls.append(True)
            if len(calls) == 2:
                write(path, {"changed": True})
            return result
        monkeypatch.setattr(cli, "read_label_companion", read)
    with pytest.raises(ValueError):
        cli.run(**arguments)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory", "parent_symlink"])
def test_package_reader_refuses_aliases_and_nonregular_files(tmp_path, kind):
    source, path = tmp_path / "source.json", tmp_path / "alias.json"
    pin = write(source, {"synthetic": True})
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
    with pytest.raises((ValueError, OSError)):
        cli.read_package(path, pin)


@pytest.mark.parametrize("payload", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}',
                                     b'{ "x":1}', b'{}\n', b'\xff', b'[' * 1000 + b']' * 1000])
def test_package_parser_rejects_noncanonical_duplicate_nonfinite_or_deep_json(tmp_path, payload):
    path = tmp_path / "package.json"
    path.write_bytes(payload)
    with pytest.raises((ValueError, RecursionError)):
        cli.read_package(path, hashlib.sha256(payload).hexdigest())


@pytest.mark.parametrize("path", ["relative.json", "https://example.invalid/package.json"])
def test_package_reader_never_fetches_network_or_relative_paths(path):
    with pytest.raises(ValueError):
        cli.read_package(path, "a" * 64)


def test_new_reader_writer_supports_package_above_frozen_eight_mib_limit(tmp_path):
    capsule = tmp_path / "capsule"
    capsule.mkdir()
    path = tmp_path / "large.json"
    value = {"synthetic_private_text": "x" * (9 * 1024 * 1024)}
    cli.write_new_package(path, value, forbidden_directory=capsule)
    assert cli.read_package(path, cli.digest(value))[0] == value
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_oversized_package_refused_before_read_or_json_hydration(tmp_path, monkeypatch):
    path = tmp_path / "package.json"
    with path.open("wb") as handle:
        handle.truncate(cli.MAX_BYTES + 1)
    monkeypatch.setattr(cli.os, "read", lambda *_: pytest.fail("oversized package read"))
    with pytest.raises(ValueError):
        cli.read_package(path, "a" * 64)


def test_package_writer_has_its_own_bound_and_preserves_frozen_limits(tmp_path, monkeypatch):
    from services.research_release_manifest import LIMITS
    original = dict(LIMITS)
    capsule = tmp_path / "capsule"
    capsule.mkdir()
    path = tmp_path / "package.json"
    monkeypatch.setattr(cli, "MAX_BYTES", 32)
    with pytest.raises(ValueError):
        cli.write_new_package(path, {"synthetic": "x" * 33}, forbidden_directory=capsule)
    assert not path.exists() and LIMITS == original


def test_output_cannot_add_to_closed_capsule_directory(tmp_path, monkeypatch):
    arguments, _, _ = case(tmp_path, monkeypatch)
    arguments["output_path"] = arguments["manifest_path"].parent / "output.json"
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not arguments["output_path"].exists()


def test_directory_close_failure_after_publication_reports_unknown_output(tmp_path, monkeypatch):
    arguments, package, _ = case(tmp_path, monkeypatch)
    close_fn, link_fn = cli.os.close, cli.os.link
    published_directories = set()

    def link_and_record(*args, **kwargs):
        link_fn(*args, **kwargs)
        published_directories.add(kwargs["dst_dir_fd"])

    def close_error(fd):
        close_fn(fd)
        if fd in published_directories:
            published_directories.remove(fd)
            raise OSError("synthetic uncertain close response")

    monkeypatch.setattr(cli.os, "link", link_and_record)
    monkeypatch.setattr(cli.os, "close", close_error)
    with pytest.raises(cli.OutputStateUnknown):
        cli.run(**arguments)
    assert arguments["output_path"].read_bytes() == cli.canonical(package)
    assert not list(tmp_path.glob(".ml-audited-*"))


def test_output_parent_replacement_cannot_report_requested_path_written(tmp_path, monkeypatch):
    arguments, package, _ = case(tmp_path, monkeypatch)
    parent, moved = tmp_path / "output-parent", tmp_path / "moved-parent"
    parent.mkdir()
    arguments["output_path"] = parent / "package.json"
    link_fn = cli.os.link

    def moved_parent(*args, **kwargs):
        parent.rename(moved)
        parent.mkdir()
        link_fn(*args, **kwargs)

    monkeypatch.setattr(cli.os, "link", moved_parent)
    with pytest.raises(cli.OutputStateUnknown):
        cli.run(**arguments)
    assert not arguments["output_path"].exists()
    assert (moved / "package.json").read_bytes() == cli.canonical(package)


@pytest.mark.parametrize("replacement", ["same_bytes", "different_bytes", "symlink"])
def test_replaced_temporary_leaf_is_not_deleted_or_claimed_as_owned(tmp_path, monkeypatch, replacement):
    arguments, package, _ = case(tmp_path, monkeypatch)
    link_fn = cli.os.link
    replaced = []

    def replaced_leaf(source, *args, **kwargs):
        temporary = tmp_path / source
        temporary.unlink()
        if replacement == "symlink":
            temporary.symlink_to(arguments["task_path"])
        else:
            temporary.write_bytes(cli.canonical(package) if replacement == "same_bytes" else b"replacement")
        replaced.append(temporary)
        link_fn(source, *args, **kwargs)

    monkeypatch.setattr(cli.os, "link", replaced_leaf)
    with pytest.raises(cli.OutputStateUnknown):
        cli.run(**arguments)
    assert replaced[0].is_symlink() if replacement == "symlink" else replaced[0].is_file()
    assert arguments["task_path"].read_bytes() == cli.canonical({"synthetic_task": True})


@pytest.mark.parametrize("change", ["content", "mode", "extra_link", "same_bytes_new_inode"])
def test_final_output_mutation_never_reports_success_or_deletes_replacement(tmp_path, monkeypatch, change):
    arguments, package, _ = case(tmp_path, monkeypatch)
    link_fn = cli.os.link
    output = arguments["output_path"]

    def altered_output(*args, **kwargs):
        link_fn(*args, **kwargs)
        if change == "content":
            output.write_bytes(b"replacement")
        elif change == "mode":
            output.chmod(0o644)
        elif change == "extra_link":
            link_fn(output, tmp_path / "extra-alias")
        else:
            output.unlink()
            output.write_bytes(cli.canonical(package))
            output.chmod(0o600)

    monkeypatch.setattr(cli.os, "link", altered_output)
    with pytest.raises(cli.OutputStateUnknown):
        cli.run(**arguments)
    assert output.exists()


@pytest.mark.parametrize("failure", ["write", "file_sync", "link", "cleanup", "directory_sync"])
def test_filesystem_failures_preserve_old_inputs_and_distinguish_uncertain_output(tmp_path, monkeypatch, failure):
    arguments, package, _ = case(tmp_path, monkeypatch)
    originals = {name: arguments[name + "_path"].read_bytes() for name in INPUTS}
    write_fn, fsync_fn, link_fn, unlink_fn = cli.os.write, cli.os.fsync, cli.os.link, cli.os.unlink
    def write_error(*_args):
        raise OSError("synthetic write failure")
    def sync_error(fd):
        directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        if (failure == "directory_sync") == directory:
            raise OSError("synthetic sync failure")
        return fsync_fn(fd)
    def link_error(*args, **kwargs):
        link_fn(*args, **kwargs)
        raise OSError("synthetic uncertain link response")
    def unlink_error(*_args, **_kwargs):
        raise OSError("synthetic cleanup failure")
    if failure == "write":
        monkeypatch.setattr(cli.os, "write", write_error)
    elif failure in {"file_sync", "directory_sync"}:
        monkeypatch.setattr(cli.os, "fsync", sync_error)
    elif failure == "link":
        monkeypatch.setattr(cli.os, "link", link_error)
    else:
        monkeypatch.setattr(cli.os, "unlink", unlink_error)
    expected = cli.OutputStateUnknown if failure in {"link", "cleanup", "directory_sync"} else OSError
    with pytest.raises(expected):
        cli.run(**arguments)
    assert {name: arguments[name + "_path"].read_bytes() for name in INPUTS} == originals
    assert arguments["output_path"].exists() == (failure in {"link", "cleanup", "directory_sync"})
    if arguments["output_path"].exists():
        assert arguments["output_path"].read_bytes() == cli.canonical(package)
    # Restore before cleaning only the exact synthetic files created in tmp_path.
    monkeypatch.setattr(cli.os, "write", write_fn)
    monkeypatch.setattr(cli.os, "fsync", fsync_fn)
    monkeypatch.setattr(cli.os, "link", link_fn)
    monkeypatch.setattr(cli.os, "unlink", unlink_fn)
    for path in tmp_path.glob(".ml-audited-*"):
        path.unlink()


@pytest.mark.parametrize("change", [{"mode": "unknown"}, {"output_path": None},
                                    {"bundle_path": "bad"}, {"expected_bundle_sha256": "a" * 64}])
def test_mixed_paths_and_invalid_modes_refused_before_build(tmp_path, monkeypatch, change):
    arguments, _, calls = case(tmp_path, monkeypatch)
    arguments.update(change)
    with pytest.raises(ValueError):
        cli.run(**arguments)
    assert not calls


def test_missing_required_pin_has_static_cli_error(capsys):
    assert cli.main(["build", "--label-companion", "PRIVATE-SOURCE-CREDENTIAL"]) == 2
    result = capsys.readouterr()
    assert result.out == "" and result.err == '{"status":"invalid","output_written":false}\n'


@pytest.mark.parametrize("exception", [ValueError, OSError, TypeError, KeyError, RecursionError])
def test_runtime_errors_do_not_echo_private_inputs(capsys, monkeypatch, exception):
    def fail(**_kwargs):
        raise exception("PRIVATE-SOURCE-CREDENTIAL")
    monkeypatch.setattr(cli, "run", fail)
    argv = ["build"]
    for name in PIN_NAMES:
        argv += ["--" + name, "PRIVATE-SOURCE-CREDENTIAL"]
    assert cli.main(argv) == 2
    result = capsys.readouterr()
    assert result.out == "" and result.err == '{"status":"invalid","output_written":false}\n'


def test_uncertain_output_is_never_reported_as_definitely_unwritten(capsys, monkeypatch):
    def uncertain(**_kwargs):
        raise cli.OutputStateUnknown("PRIVATE-SOURCE-CREDENTIAL")
    monkeypatch.setattr(cli, "run", uncertain)
    argv = ["build"]
    for name in PIN_NAMES:
        argv += ["--" + name, "synthetic"]
    assert cli.main(argv) == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert json.loads(result.err) == {"status": "output_state_unknown", "output_written": None}


@pytest.mark.parametrize("gate,code", [("pass", 0), ("no_go", 3)])
def test_exit_status_is_technical_only(capsys, monkeypatch, gate, code):
    monkeypatch.setattr(cli, "run", lambda **_: {"technical_gate": gate, "scientific_acceptance": False})
    argv = ["build"]
    for name in PIN_NAMES:
        argv += ["--" + name, "synthetic"]
    assert cli.main(argv) == code
    assert '"scientific_acceptance":false' in capsys.readouterr().out
