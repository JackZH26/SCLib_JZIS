"""Offline file-gate adversaries; no database or remote evaluator is invoked."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_scientific_evaluation.py"
SPEC = importlib.util.spec_from_file_location("scientific_evaluation_cli", SCRIPT)
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)

CANARY = "PRIVATE-SOURCE-postgresql-secret-DO-NOT-PRINT"
REPORT = {"status": "validated", "release_eligible": False, "scientific_acceptance": False}


@pytest.fixture
def artifact(tmp_path):
    # macOS temporary roots may themselves be symlinked. Tests deliberately
    # choose the real absolute root, not a resolve() inside the production gate.
    path = tmp_path.resolve() / "package.json"
    path.write_bytes(b'{"fixture":"synthetic offline input"}')
    return path


def arguments(path, *, command="validate", payload=None, digest=None):
    if digest is None:
        digest = hashlib.sha256(path.read_bytes() if payload is None else payload).hexdigest()
    return [command, str(path), "--sha256", digest]


def output(capsys):
    captured = capsys.readouterr()
    assert captured.err == ""
    assert CANARY not in captured.out
    assert "Traceback" not in captured.out
    return json.loads(captured.out)


@pytest.fixture
def service(monkeypatch):
    calls = []

    def evaluate(command, document):
        calls.append((command, document))
        return REPORT.copy()

    monkeypatch.setattr(cli, "_evaluate", evaluate)
    return calls


@pytest.mark.parametrize("command", ["validate", "compare"])
def test_wellformed_diagnostic_is_exit_zero_even_when_release_is_false(artifact, service, capsys, command):
    before = artifact.stat()
    payload = artifact.read_bytes()
    assert cli.main(arguments(artifact, command=command)) == 0
    assert output(capsys) == REPORT
    assert service == [(command, {"fixture": "synthetic offline input"})]
    assert artifact.read_bytes() == payload
    assert artifact.stat().st_ino == before.st_ino
    assert set(artifact.parent.iterdir()) == {artifact}


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_is_fixed_json_without_any_artifact_or_service(flag, monkeypatch, capsys, service):
    monkeypatch.setattr(cli.os, "open", lambda *args, **kwargs: pytest.fail("help opened a file"))
    assert cli.main([flag]) == 0
    report = output(capsys)
    assert report["status"] == "usage" and report["offline"] is True and report["read_only"] is True
    assert report["commands"] == ["validate", "compare"]
    assert "Independently supplied" in report["sha256_requirement"]
    assert not service


@pytest.mark.parametrize("args", [[], ["validate"], ["validate", CANARY],
    ["delete", CANARY, "--sha256", "a" * 64], ["validate", CANARY, "--sh", "a" * 64],
    ["validate", CANARY, "--sha256", "a" * 64, "--unknown", CANARY]])
def test_invalid_invocation_is_json_only_and_never_echoes_raw_arguments(args, capsys, service):
    assert cli.main(args) == 2
    assert output(capsys) == {"status": "rejected", "reason_code": "invalid_arguments"}
    assert not service


@pytest.mark.parametrize("digest", ["", "A" * 64, "a" * 63, "a" * 65, CANARY, "g" * 64])
def test_external_sha_is_required_and_strict_lowercase_hex(artifact, digest, capsys, service):
    assert cli.main(arguments(artifact, digest=digest)) == 2
    assert output(capsys)["reason_code"] == "invalid_expected_sha256"
    assert not service


def test_wrong_raw_sha_fails_before_json_or_service(artifact, capsys, service, monkeypatch):
    def forbidden(_payload):
        pytest.fail("JSON parser was reached before independent hash verification")
    monkeypatch.setattr(cli, "_strict_json", forbidden)
    assert cli.main(arguments(artifact, digest="0" * 64)) == 2
    assert output(capsys)["reason_code"] == "artifact_sha256_mismatch"
    assert not service


def test_external_digest_binds_raw_whitespace_not_a_reconstructed_json_object(artifact, capsys, service):
    raw = b'{\n  "fixture": "synthetic offline input"\n}\n'
    artifact.write_bytes(raw)
    canonical = json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")).encode()
    assert raw != canonical
    assert cli.main(arguments(artifact, digest=hashlib.sha256(canonical).hexdigest())) == 2
    assert output(capsys)["reason_code"] == "artifact_sha256_mismatch"
    assert not service
    assert cli.main(arguments(artifact)) == 0
    assert output(capsys) == REPORT


@pytest.mark.parametrize("path", ["relative.json", "https://private.invalid/" + CANARY,
    "file:///private/" + CANARY, "/tmp/../" + CANARY, "//host/" + CANARY, "/tmp/\x00secret"])
def test_uri_relative_traversal_or_invalid_path_is_never_opened(path, capsys, service, monkeypatch):
    monkeypatch.setattr(cli.os, "open", lambda *args, **kwargs: pytest.fail("invalid path opened"))
    assert cli.main(["validate", path, "--sha256", "0" * 64]) == 2
    assert output(capsys)["reason_code"] == "invalid_artifact_path"
    assert not service


@pytest.mark.parametrize("payload,code", [
    (b'{"a":1,"a":2}', "duplicate_json_keys"),
    (b'{"a":1,"\\u0061":2}', "duplicate_json_keys"),
    (b'{"outer":{"a":1,"a":2}}', "duplicate_json_keys"),
    (b'{"a":NaN}', "nonfinite_json"), (b'{"a":Infinity}', "nonfinite_json"),
    (b'{"a":-Infinity}', "nonfinite_json"), (b'{"a":1e999}', "nonfinite_json"),
    (b'{"a":-1e999}', "nonfinite_json"), (b'{"a":"\\ud800"}', "invalid_json"),
    (b'{"\\udfff":1}', "invalid_json"), (b'{"a":"\xff"}', "invalid_json"),
    (b'\xef\xbb\xbf{}', "invalid_json"), (b'[]', "invalid_json"), (b'null', "invalid_json"),
    (b'1', "invalid_json"), (b'{"a":1} {"b":2}', "invalid_json"),
    (b'{"a":', "invalid_json"), (b'{"a":01}', "invalid_json"),
])
def test_strict_json_rejections_precede_application_models(artifact, payload, code, capsys, service):
    artifact.write_bytes(payload)
    assert cli.main(arguments(artifact)) == 2
    assert output(capsys)["reason_code"] == code
    assert not service


def test_depth_is_bounded_before_tree_allocation(artifact, service, monkeypatch, capsys):
    artifact.write_bytes(b'{"v":' + b'[' * 32 + b'0' + b']' * 32 + b'}')
    monkeypatch.setattr(cli.json, "loads", lambda *args, **kwargs: pytest.fail("deep JSON reached tree allocator"))
    assert cli.main(arguments(artifact)) == 2
    raw = capsys.readouterr()
    assert '"reason_code": "json_resource_limit"' in raw.out and raw.err == ""
    assert not service


def test_node_budget_counts_keys_containers_and_values_before_parsing(artifact, service, monkeypatch, capsys):
    monkeypatch.setattr(cli, "MAX_JSON_NODES", 5)
    artifact.write_bytes(b'{"a":[0,1]}')  # object, key, list, two values
    assert cli.main(arguments(artifact)) == 0
    assert output(capsys) == REPORT
    service.clear()
    artifact.write_bytes(b'{"a":[0,1,2]}')
    assert cli.main(arguments(artifact)) == 2
    assert output(capsys)["reason_code"] == "json_resource_limit"
    assert not service


def test_nested_json_at_exact_depth_and_escaped_brackets_remains_valid(artifact, service, capsys):
    artifact.write_bytes(b'{"v":' + b'[' * 31 + b'"escaped \\\" [{ : \\u4e2d"' + b']' * 31 + b'}')
    assert cli.main(arguments(artifact)) == 0
    assert output(capsys) == REPORT
    assert len(service) == 1


def test_raw_byte_limit_applies_before_read_or_service(artifact, service, monkeypatch, capsys):
    monkeypatch.setattr(cli, "MAX_INPUT_BYTES", 32)
    artifact.write_bytes(b'{"v":"' + b'x' * 25 + b'"}')  # 33 bytes
    assert cli.main(arguments(artifact)) == 2
    assert output(capsys)["reason_code"] == "artifact_size_limit"
    assert not service


@pytest.mark.parametrize("kind", ["target_symlink", "ancestor_symlink", "hardlink", "directory", "fifo", "missing"])
def test_only_nofollow_single_link_regular_files_are_admitted(artifact, kind, service, capsys):
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    target = artifact
    if kind == "target_symlink":
        target = artifact.parent / "alias.json"
        target.symlink_to(artifact)
    elif kind == "ancestor_symlink":
        nested = artifact.parent / "nested"
        nested.mkdir()
        target = nested / "package.json"
        target.write_bytes(artifact.read_bytes())
        alias = artifact.parent / "alias"
        alias.symlink_to(nested, target_is_directory=True)
        target = alias / target.name
    elif kind == "hardlink":
        os.link(artifact, artifact.parent / "alias.json")
    elif kind == "directory":
        target = artifact.parent
    elif kind == "fifo":
        target = artifact.parent / "pipe.json"
        os.mkfifo(target)
    else:
        target = artifact.parent / CANARY
    assert cli.main(arguments(target, digest=digest)) == 2
    assert output(capsys)["reason_code"] in {"artifact_unavailable", "artifact_not_regular"}
    assert not service


def test_device_input_is_not_opened_or_treated_as_an_empty_package(service, monkeypatch, capsys):
    original = cli.os.open
    def open_directory_only(path, flags, **kwargs):
        assert flags & os.O_DIRECTORY, "Non-regular target was opened"
        return original(path, flags, **kwargs)
    monkeypatch.setattr(cli.os, "open", open_directory_only)
    assert cli.main(["validate", "/dev/null", "--sha256", "0" * 64]) == 2
    assert output(capsys)["reason_code"] == "artifact_not_regular"
    assert not service


@pytest.mark.parametrize("change", ["bytes", "same_bytes_rewrite", "replace_inode", "ancestor_swap", "unlink", "add_alias"])
def test_post_evaluation_recapture_withholds_report_after_any_observed_artifact_drift(
    artifact, change, monkeypatch, capsys,
):
    original = artifact.read_bytes()
    args = arguments(artifact)

    def evaluate(_command, _document):
        if change == "bytes":
            artifact.write_bytes(original.replace(b"synthetic", b"different"))
        elif change == "same_bytes_rewrite":
            artifact.write_bytes(original)
        elif change == "replace_inode":
            replacement = artifact.with_name("replacement.json")
            replacement.write_bytes(original)
            replacement.replace(artifact)
        elif change == "ancestor_swap":
            old_parent = artifact.parent.with_name(artifact.parent.name + "-retained")
            artifact.parent.rename(old_parent)
            artifact.parent.mkdir()
            artifact.write_bytes(original)
        elif change == "unlink":
            artifact.unlink()
        else:
            os.link(artifact, artifact.with_name("alias.json"))
        return REPORT.copy()

    monkeypatch.setattr(cli, "_evaluate", evaluate)
    assert cli.main(args) == 2
    assert output(capsys)["reason_code"] in {"artifact_changed", "artifact_unavailable", "artifact_not_regular"}


def test_mutation_during_first_read_is_rejected_before_service(artifact, service, monkeypatch, capsys):
    original_read = cli.os.read
    original = artifact.read_bytes()
    args = arguments(artifact)
    changed = False

    def changing_read(descriptor, size):
        nonlocal changed
        value = original_read(descriptor, size)
        if value and not changed:
            artifact.write_bytes(original)
            changed = True
        return value

    monkeypatch.setattr(cli.os, "read", changing_read)
    assert cli.main(args) == 2
    assert output(capsys)["reason_code"] == "artifact_changed"
    assert not service


@pytest.mark.parametrize("exception", [ValueError(CANARY), RuntimeError(CANARY),
    cli.EvaluationCLIRejection(CANARY), KeyboardInterrupt(CANARY)])
def test_unexpected_failure_is_static_json_without_exception_or_input_leaks(artifact, monkeypatch, capsys, exception):
    def fail(*_args):
        raise exception
    monkeypatch.setattr(cli, "_evaluate", fail)
    assert cli.main(arguments(artifact)) == 2
    assert output(capsys)["reason_code"] == "evaluation_unavailable"


def test_actual_process_rejects_bad_input_without_api_import_or_created_files(artifact):
    artifact.write_bytes(b'{"private":"' + CANARY.encode() + b'","a":NaN}')
    before = set(artifact.parent.iterdir())
    process = subprocess.run([sys.executable, str(SCRIPT), *arguments(artifact)], capture_output=True,
                             text=True, timeout=10, check=False)
    assert process.returncode == 2
    assert process.stderr == ""
    assert json.loads(process.stdout) == {"status": "rejected", "reason_code": "nonfinite_json"}
    assert CANARY not in process.stdout
    assert set(artifact.parent.iterdir()) == before


@pytest.mark.parametrize("command", ["validate", "compare"])
def test_lazy_service_dispatch_uses_only_the_selected_pure_entrypoint(artifact, command, monkeypatch, capsys):
    calls = []
    def validate(document):
        calls.append(("validate", document))
        return REPORT.copy()
    def compare(document):
        calls.append(("compare", document))
        return REPORT.copy()
    monkeypatch.setitem(sys.modules, "services.scientific_evaluation", SimpleNamespace(
        validate_package=validate, compare_package=compare))
    monkeypatch.setattr(sys, "path", sys.path.copy())
    assert cli.main(arguments(artifact, command=command)) == 0
    assert output(capsys) == REPORT
    assert calls == [(command, {"fixture": "synthetic offline input"})]


def test_real_dispatch_sanitizes_core_rejection_without_its_raw_exception(artifact, monkeypatch, capsys):
    def invalid(_document):
        raise ValueError(CANARY)
    monkeypatch.setitem(sys.modules, "services.scientific_evaluation", SimpleNamespace(
        validate_package=invalid, compare_package=invalid))
    monkeypatch.setattr(sys, "path", sys.path.copy())
    assert cli.main(arguments(artifact)) == 2
    assert output(capsys)["reason_code"] == "evaluation_rejected"


@pytest.mark.parametrize("report", [None, [], {"value": float("nan")}, {"value": object()}])
def test_non_json_or_nonfinite_service_report_is_withheld(artifact, report, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_evaluate", lambda *_args: report)
    assert cli.main(arguments(artifact)) == 2
    assert output(capsys)["reason_code"] == "report_invalid"


def _actual_package(monkeypatch, *, runs=True):
    """Use the actual semantic fixture, not a model-only placeholder digest."""
    monkeypatch.setattr(sys, "path", [str(ROOT / "api"), *sys.path])
    from tests.scientific_evaluation_fixtures import make_package
    return make_package(runs=runs)


@pytest.mark.parametrize("command", ["validate", "compare"])
def test_actual_evaluator_process_is_read_only_offline_and_keeps_authority_false(artifact, monkeypatch, command):
    package = _actual_package(monkeypatch)
    artifact.write_bytes(json.dumps(package, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))
    original = artifact.read_bytes()
    before = set(artifact.parent.iterdir())
    # The entire actual service/model import and dispatch runs behind these
    # process audit hooks, not just a stubbed pure function in the pytest host.
    bootstrap = """
import sys
sys.dont_write_bytecode = True
import os, runpy
def offline_readonly(event, args):
    if event.startswith('socket.') or event == 'sqlite3.connect':
        raise RuntimeError('Forbidden service access')
    if event == 'open':
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            raise RuntimeError('Forbidden filesystem write')
sys.addaudithook(offline_readonly)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    process = subprocess.run([sys.executable, "-c", bootstrap, str(SCRIPT), *arguments(artifact, command=command)],
        capture_output=True, text=True, timeout=20, check=False)
    assert process.returncode == 0, process.stdout + process.stderr
    assert process.stderr == ""
    report = json.loads(process.stdout)
    assert report["status"] == "structurally_consistent"
    assert report["scientific_acceptance"] is False and report["release_authorized"] is False
    assert report["reviewer_authority_authenticated"] is False
    assert report["execution_authenticated"] is False
    assert "synthetic_development_only" in report["release_blockers"]
    assert ("comparison" in report) is (command == "compare")
    for source in package["corpus"]["sources"]:
        assert source["text"] not in process.stdout
    for case in package["cases"]:
        assert case["query"] not in process.stdout
    for run in package["runs"]:
        for observation in run["observations"]:
            if observation["answer"]:
                assert observation["answer"] not in process.stdout
    assert artifact.read_bytes() == original
    assert set(artifact.parent.iterdir()) == before


def test_actual_compare_refuses_missing_paired_runs_with_static_exit_two(artifact, monkeypatch, capsys):
    package = _actual_package(monkeypatch, runs=False)
    artifact.write_bytes(json.dumps(package, allow_nan=False).encode())
    assert cli.main(arguments(artifact, command="validate")) == 0
    assert output(capsys)["release_authorized"] is False
    assert cli.main(arguments(artifact, command="compare")) == 2
    assert output(capsys) == {"status": "rejected", "reason_code": "evaluation_rejected"}


def test_linux_ci_explicitly_runs_the_offline_cli_suite_with_the_locked_api_runtime():
    workflow = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "uv sync --locked --extra dev --python 3.11" in workflow
    assert "- name: Verify scientific evaluation offline CLI (no services)\n        run: .venv/bin/python -m pytest -q ../scripts/tests/test_scientific_evaluation_cli.py" in workflow
    assert workflow.index("Verify scientific evaluation offline CLI") < workflow.index("Prepare ephemeral service images")
    # This new pure/offline gate does not replace or bypass API DB guards.
    assert ".venv/bin/python ../scripts/run_disposable_tests.py --backend docker --suite api -- -q" in workflow
