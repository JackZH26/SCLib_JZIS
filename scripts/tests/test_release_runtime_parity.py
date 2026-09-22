"""Offline final-release gate orchestration; no Docker, GitHub or registry I/O."""
from __future__ import annotations

import http.client
import io
import json
import os
import stat
import subprocess
import sys
import zipfile
import zlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_release_runtime as gate
from runtime_inventory import SCHEMA, digest


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for name, value in files.items():
            handle.writestr(name, value)
    return output.getvalue()


@pytest.fixture
def context(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    for project in ("api", "ingestion"):
        (root / project).mkdir()
        for name in ("uv.lock", "pyproject.toml", "Dockerfile"):
            (root / project / name).write_text("synthetic " + project + name)
    (root / "scripts").mkdir()
    for name in ("runtime_inventory.py", "verify_release_runtime.py"):
        (root / "scripts" / name).write_text("# synthetic trusted checkout " + name)
    (root / ".github/workflows").mkdir(parents=True)
    (root / ".github/workflows/release-images.yml").write_text("synthetic workflow")
    data = SimpleNamespace(root=root, project="api", revision="a" * 40, run_id=123, attempt=2,
        repo_id=456, workflow_id=789, image_digest="sha256:" + "b" * 64, image_id="sha256:" + "c" * 64,
        commands=[], api_calls=[], archives={}, files={}, metadata={}, runtime=None, extra_artifacts=[],
        endpoint="unix:///var/run/docker.sock", output=root / "output", fail_operation=None, clean=False)
    repo = {"id": data.repo_id, "full_name": gate.REPOSITORY}
    data.run = {"id": data.run_id, "run_attempt": data.attempt, "head_sha": data.revision,
        "head_branch": "main", "event": "push", "status": "completed", "conclusion": "success",
        "path": gate.WORKFLOW, "name": "Test", "workflow_id": data.workflow_id,
        "repository": dict(repo), "head_repository": dict(repo),
        "run_started_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:10:00Z"}
    data.event = {"action": "completed", "repository": repo, "workflow_run": deepcopy(data.run)}
    data.event_path = root / "event.json"
    data.event_path.write_bytes(encoded(data.event))
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_run",
        "GITHUB_REPOSITORY": gate.REPOSITORY, "GITHUB_API_URL": gate.API,
        "GITHUB_SERVER_URL": "https://github.com", "GH_TOKEN": "synthetic-secret-token",
        "GITHUB_EVENT_PATH": str(data.event_path)}.items():
        monkeypatch.setenv(key, value)
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(gate, "ROOT", root)
    monkeypatch.setattr(gate.platform, "system", lambda: "Linux")
    monkeypatch.setattr(gate.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr("socket.socket", Mock(side_effect=AssertionError("No network allowed")))

    def configure(project):
        data.project = project
        expected = {"source_revision": data.revision,
            "lock_sha256": digest((root / project / "uv.lock").read_bytes()),
            "pyproject_sha256": digest((root / project / "pyproject.toml").read_bytes()),
            "collector_sha256": digest((root / "scripts/runtime_inventory.py").read_bytes()),
            "dockerfile_sha256": digest((root / project / "Dockerfile").read_bytes())}
        data.runtime = {"schema": SCHEMA, "python_minor": "3.11", "python_version": "3.11.14",
            "implementation": "CPython", "system": "Linux", "machine": "x86_64",
            "project_name": "sclib-" + project, "project_version": "0.1.0",
            "packages": {"sclib-" + project: "0.1.0", "sqlalchemy": "2.0.49"},
            **{key: value for key, value in expected.items() if key != "dockerfile_sha256"}}
        data.details = [{"Id": data.image_id, "RepoDigests": [f"ghcr.io/jackzh26/sclib-{project}@{data.image_digest}"],
            "Os": "linux", "Architecture": "amd64", "Config": {"Labels": {
                "org.opencontainers.image.revision": data.revision,
                "org.opencontainers.image.source": "https://github.com/" + gate.REPOSITORY}}}]
        data.metadata.clear()
        data.files.clear()
        for index, name in enumerate(gate.artifact_names(project, data.attempt), 1):
            tests = deepcopy(data.runtime)
            tests["packages"].update(pytest="9.0.2", pluggy="1.6.0")
            report = {"schema": "sclib-runtime-parity/v1", "matches": True, "failures": [],
                "project": project, "image_id": "sha256:" + "d" * 64, "image_architecture": "amd64",
                "scope": gate.SCOPE, **expected}
            data.files[name] = {"test-runtime.json": encoded(tests), "image-runtime.json": encoded(data.runtime),
                                "parity-report.json": encoded(report)}
            data.metadata[name] = {"id": index, "name": name, "expired": False,
                "created_at": "2026-01-01T00:05:00Z", "updated_at": "2026-01-01T00:05:01Z",
                "expires_at": "2035-01-01T00:00:00Z", "workflow_run": {"id": data.run_id,
                    "repository_id": data.repo_id, "head_repository_id": data.repo_id,
                    "head_sha": data.revision, "head_branch": "main"}}
            reseal(name)

    def reseal(name):
        raw = archive(data.files[name])
        item = data.metadata[name]
        data.archives[item["id"]] = raw
        item.update(digest="sha256:" + digest(raw), size_in_bytes=len(raw))

    def api(path, token):
        assert token == "synthetic-secret-token"
        data.api_calls.append(path)
        if path == "":
            return {"id": data.repo_id, "full_name": gate.REPOSITORY}
        if path == "/actions/workflows/test.yml":
            return {"id": data.workflow_id, "path": gate.WORKFLOW, "name": "Test"}
        if path == f"/actions/runs/{data.run_id}/attempts/{data.attempt}":
            return deepcopy(data.run)
        if path.startswith(f"/actions/runs/{data.run_id}/artifacts?"):
            page = int(path.rsplit("=", 1)[1])
            items = [*data.extra_artifacts, *data.metadata.values()]
            return {"total_count": len(items), "artifacts": deepcopy(items[(page - 1) * 100:page * 100])}
        if path.startswith("/actions/artifacts/"):
            identifier = int(path.rsplit("/", 1)[1])
            return deepcopy(next(item for item in data.metadata.values() if item["id"] == identifier))
        raise AssertionError("Unexpected API path")

    def command(arguments, *, stdin=None, timeout=120):
        data.commands.append((arguments, stdin, timeout))
        if data.fail_operation and data.fail_operation in arguments:
            raise subprocess.CalledProcessError(1, arguments, stderr="private error")
        if arguments[:2] == ["git", "rev-parse"]:
            return data.revision
        if arguments[0] == "git":
            return ""
        if arguments[3:5] == ["context", "inspect"]:
            return json.dumps(data.endpoint)
        if arguments[3] == "pull":
            return "synthetic pinned pull"
        if arguments[3:5] == ["image", "inspect"]:
            return json.dumps(data.details)
        if arguments[3] == "run":
            return json.dumps(data.runtime)
        raise AssertionError("Unexpected command")

    data.configure, data.reseal, data.api, data.command = configure, reseal, api, command
    data.arguments = lambda: dict(project=data.project, image_digest=data.image_digest, test_run_id=data.run_id,
        test_run_attempt=data.attempt, revision=data.revision, output=data.output)
    monkeypatch.setattr(gate, "api_json", api)
    monkeypatch.setattr(gate, "download_artifact", lambda identifier, token: data.archives[identifier])
    monkeypatch.setattr(gate, "command", command)
    configure("api")
    return data


@pytest.mark.parametrize("project,count", [("api", 2), ("ingestion", 1)])
def test_exact_final_digest_is_actually_compared_with_every_required_test_inventory(context, project, count):
    context.configure(project)
    report = gate.check(**context.arguments())
    assert report["matches"] is True
    assert len(report["artifacts"]) == len(report["comparisons"]) == count
    assert set(report["comparisons"]) == set(gate.artifact_names(project, 2))
    assert report["image_digest"] == context.image_digest and report["image_id"] == context.image_id
    assert report["test_run_id"] == 123 and report["test_run_attempt"] == 2
    assert report["scope"] == gate.SCOPE
    assert json.loads((context.output / "release-parity-report.json").read_text()) == report
    assert context.output.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in context.output.iterdir())
    capture, stdin, _ = next(item for item in context.commands if item[0][3:4] == ["run"])
    assert context.image_id in capture and context.image_digest not in capture
    assert stdin == (context.root / "scripts/runtime_inventory.py").read_text()
    for key, value in (("--network", "none"), ("--pull", "never"), ("--cap-drop", "ALL"),
        ("--security-opt", "no-new-privileges"), ("--entrypoint", "/opt/venv/bin/python"), ("--user", "1001:1001")):
        assert capture[capture.index(key) + 1] == value
    for present in ("--read-only", "--no-healthcheck", "-I", "-B"):
        assert present in capture
    assert not any(word in capture for word in ("--env", "-e", "--env-file", "-v", "--mount", "--privileged"))
    pulls = [cmd for cmd, _, _ in context.commands if cmd[3:4] == ["pull"]]
    assert pulls == [["docker", "--context", "default", "pull", "--platform", "linux/amd64", report["image"]]]


def test_same_revision_and_lock_do_not_hide_changed_final_package(context):
    context.runtime["packages"]["sqlalchemy"] = "9.9"
    report = gate.check(**context.arguments())
    assert report["matches"] is False and report["reason_codes"] == ["runtime_inventory_mismatch"]
    assert all(value["matches"] is False for value in report["comparisons"].values())


def test_api_migration_runtime_is_independently_required(context):
    name = gate.artifact_names("api", 2)[1]
    for filename in ("test-runtime.json", "image-runtime.json"):
        value = json.loads(context.files[name][filename])
        value["packages"]["sqlalchemy"] = "2.0.48"
        context.files[name][filename] = encoded(value)
    context.reseal(name)
    report = gate.check(**context.arguments())
    assert report["matches"] is False
    assert report["comparisons"][gate.artifact_names("api", 2)[0]]["matches"] is True
    assert report["comparisons"][name]["matches"] is False


@pytest.mark.parametrize("field,value", [("run_attempt", 1), ("id", 999), ("head_sha", "f" * 40),
    ("path", ".github/workflows/other.yml"), ("name", "Other"), ("event", "pull_request"),
    ("head_branch", "feature"), ("status", "in_progress"), ("conclusion", "failure"),
    ("repository", None), ("head_repository", {"full_name": "outsider/repo", "id": 456})])
def test_wrong_actual_run_or_attempt_fails_before_docker(context, field, value):
    context.run[field] = value
    with pytest.raises((gate.ReleaseRuntimeError, TypeError)):
        gate.check(**context.arguments())
    assert not any(cmd[0] == "docker" for cmd, _, _ in context.commands)


@pytest.mark.parametrize("field,value", [("expired", True), ("digest", "sha256:" + "0" * 64),
    ("created_at", "2025-12-31T23:59:00Z"), ("created_at", "2026-01-01T00:00:00Z"),
    ("updated_at", "2026-01-01T00:10:01Z"), ("expires_at", "2025-01-01T00:00:00Z"),
    ("workflow_run", None), ("size_in_bytes", True), ("size_in_bytes", gate.MAX_ARCHIVE + 1)])
def test_artifact_digest_attempt_window_expiry_and_types_fail_closed(context, field, value):
    next(iter(context.metadata.values()))[field] = value
    with pytest.raises(gate.ReleaseRuntimeError):
        gate.check(**context.arguments())
    assert not any(cmd[0] == "docker" for cmd, _, _ in context.commands)


def test_missing_duplicate_or_previous_attempt_artifact_names_are_not_fallbacks(context):
    name = gate.artifact_names("api", 2)[1]
    context.metadata.pop(name)
    with pytest.raises(gate.ReleaseRuntimeError):
        gate.check(**context.arguments())
    context.configure("api")
    duplicate = deepcopy(context.metadata[name])
    duplicate["id"] = 99
    context.extra_artifacts = [duplicate]
    with pytest.raises(gate.ReleaseRuntimeError):
        gate.check(**context.arguments())
    context.extra_artifacts = []
    context.metadata[name]["name"] = name.replace("attempt-2", "attempt-1")
    with pytest.raises(gate.ReleaseRuntimeError):
        gate.check(**context.arguments())


def test_artifacts_are_paginated_with_bounded_exact_run_paths(context):
    context.extra_artifacts = [{"id": index + 1000, "name": "irrelevant-" + str(index)} for index in range(100)]
    assert gate.check(**context.arguments())["matches"] is True
    assert "/actions/runs/123/artifacts?per_page=100&page=2" in context.api_calls
    assert not any("latest" in path or "/runs?" in path for path in context.api_calls)


@pytest.mark.parametrize("field,value", [("lock_sha256", "f" * 64), ("collector_sha256", "f" * 64),
    ("pyproject_sha256", "f" * 64), ("source_revision", "f" * 40), ("machine", "aarch64"),
    ("project_name", "sclib-ingestion")])
def test_resealed_test_inventory_with_wrong_input_or_project_pin_is_refused(context, field, value):
    name = gate.artifact_names("api", 2)[0]
    payload = json.loads(context.files[name]["test-runtime.json"])
    payload[field] = value
    context.files[name]["test-runtime.json"] = encoded(payload)
    context.reseal(name)
    with pytest.raises(ValueError):
        gate.check(**context.arguments())
    assert not any(cmd[0] == "docker" for cmd, _, _ in context.commands)


@pytest.mark.parametrize("mutation", ["digest", "platform", "revision", "source", "image_id", "null_config", "null_detail",
    "digest_string", "digest_dict", "digest_null", "digest_nonstring", "digest_unbounded"])
def test_final_image_requires_registry_digest_local_id_platform_and_revision(context, mutation):
    row = context.details[0]
    if mutation == "digest": row["RepoDigests"] = []
    if mutation == "platform": row["Architecture"] = "arm64"
    if mutation == "revision": row["Config"]["Labels"]["org.opencontainers.image.revision"] = "f" * 40
    if mutation == "source": row["Config"]["Labels"]["org.opencontainers.image.source"] = "https://other.invalid/repo"
    if mutation == "image_id": row["Id"] = "latest"
    if mutation == "null_config": row["Config"] = None
    if mutation == "null_detail": context.details = [None]
    if mutation == "digest_string": row["RepoDigests"] = row["RepoDigests"][0]
    if mutation == "digest_dict": row["RepoDigests"] = {row["RepoDigests"][0]: True}
    if mutation == "digest_null": row["RepoDigests"] = None
    if mutation == "digest_nonstring": row["RepoDigests"].append(None)
    if mutation == "digest_unbounded": row["RepoDigests"] *= 101
    with pytest.raises(gate.ReleaseRuntimeError):
        gate.check(**context.arguments())
    assert not any(cmd[3:4] == ["run"] for cmd, _, _ in context.commands)


@pytest.mark.parametrize("name", ["../test-runtime.json", "/tmp/evil", "nested/file", "extra.py"])
def test_archive_closed_inventory_rejects_paths_and_executable_extras(context, name):
    selected = gate.artifact_names("api", 2)[0]
    context.files[selected][name] = b"raise Exception('must never execute')"
    context.reseal(selected)
    with pytest.raises(gate.ReleaseRuntimeError):
        gate.check(**context.arguments())


def test_zip_symlink_duplicate_and_expansion_are_rejected(context, monkeypatch):
    selected = gate.artifact_names("api", 2)[0]
    info = zipfile.ZipInfo("test-runtime.json")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as handle:
        handle.writestr(info, b"target")
        for name in ("image-runtime.json", "parity-report.json"):
            handle.writestr(name, b"{}")
    metadata = {"digest": "sha256:" + digest(raw.getvalue()), "size_in_bytes": len(raw.getvalue())}
    with pytest.raises(gate.ReleaseRuntimeError):
        gate._archive(raw.getvalue(), metadata)
    monkeypatch.setattr(gate, "MAX_JSON", 5)
    with pytest.raises(gate.ReleaseRuntimeError):
        gate._archive(context.archives[1], context.metadata[selected])


@pytest.mark.parametrize("key,value", [("GITHUB_ACTIONS", "false"), ("GITHUB_REPOSITORY", "other/repo"),
    ("GITHUB_API_URL", "https://private.invalid"), ("GITHUB_EVENT_NAME", "push"), ("GH_TOKEN", ""),
    ("DOCKER_HOST", "tcp://private:2376")])
def test_untrusted_execution_environment_fails_before_external_operations(context, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(gate.ReleaseRuntimeError):
        gate.check(**context.arguments())
    assert not context.api_calls
    assert not any(cmd[0] == "docker" for cmd, _, _ in context.commands)


def test_existing_and_symlink_output_are_refused_before_external_operations(context):
    context.output.mkdir()
    sentinel = context.output / "retained"
    sentinel.write_text("preserve")
    with pytest.raises(gate.ReleaseRuntimeError):
        gate.check(**context.arguments())
    assert sentinel.read_text() == "preserve" and not context.api_calls
    context.output = context.root / "symlink"
    context.output.symlink_to(sentinel)
    with pytest.raises(gate.ReleaseRuntimeError):
        gate.check(**context.arguments())


def test_local_input_atime_changes_do_not_change_content_identity(context, monkeypatch):
    original = os.fstat
    count = 0
    def observed(fd):
        nonlocal count
        value = original(fd)
        count += 1
        fields = {key: getattr(value, key) for key in ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")}
        return SimpleNamespace(**fields, st_atime=count)
    monkeypatch.setattr(gate.os, "fstat", observed)
    assert gate._read(context.event_path) == context.event_path.read_bytes()


def test_credential_bearing_redirect_is_not_reused_for_signed_storage(monkeypatch):
    calls = []
    def http(url, **kwargs):
        calls.append((url, kwargs))
        return "https://synthetic.blob.core.windows.net/archive?sig=private" if kwargs.get("redirect") else b"zip"
    monkeypatch.setattr(gate, "_http", http)
    assert gate.download_artifact(12, "SECRET") == b"zip"
    assert calls[0][1]["token"] == "SECRET"
    assert "token" not in calls[1][1]
    assert gate._NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid") is None


@pytest.mark.parametrize("location", ["http://storage.invalid/x", "https://localhost/x",
    "https://user:password@synthetic.blob.core.windows.net/x", "https://synthetic.blob.core.windows.net:444/x",
    "https://blob.core.windows.net.attacker.invalid/x", "https://synthetic.blob.core.windows.net/x#bad"])
def test_off_origin_or_ambiguous_archive_redirect_is_refused(monkeypatch, location):
    request = Mock(return_value=location)
    monkeypatch.setattr(gate, "_http", request)
    with pytest.raises(gate.ReleaseRuntimeError):
        gate.download_artifact(12, "SECRET")
    assert request.call_count == 1


def test_http_total_deadline_cannot_be_extended_by_slow_trickle(monkeypatch):
    class Response:
        status, headers = 200, {}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read1(self, size): return b"x"
    monkeypatch.setattr(gate.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=lambda *a, **kw: Response()))
    monkeypatch.setattr(gate.time, "monotonic", Mock(side_effect=[0, 1, 2, 29, 31]))
    with pytest.raises(gate.ReleaseRuntimeError, match="http_total_deadline"):
        gate._http("https://synthetic.blob.core.windows.net/fixture")


def test_command_strips_credentials_and_bounds_real_subprocess_output(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setenv("GH_TOKEN", "PRIVATE_GITHUB_CREDENTIAL")
    monkeypatch.setenv("DATABASE_URL", "PRIVATE_DATABASE")
    result = gate.command([sys.executable, "-I", "-c", "import os; print(sorted(os.environ))"])
    assert "GH_TOKEN" not in result and "DATABASE_URL" not in result
    monkeypatch.setattr(gate, "MAX_JSON", 1024)
    with pytest.raises(gate.ReleaseRuntimeError, match="command_output_limit"):
        gate.command([sys.executable, "-I", "-c", "import sys; sys.stderr.write('x'*100000)"])
    with pytest.raises(subprocess.TimeoutExpired):
        gate.command([sys.executable, "-I", "-c", "import time; time.sleep(2)"], timeout=0.05)


def test_main_errors_are_sanitized_without_raw_input_or_credentials(context, monkeypatch, capsys):
    monkeypatch.setattr(gate, "check", Mock(side_effect=gate.ReleaseRuntimeError("SECRET source/credential/path")))
    assert gate.main(["--project", "api", "--image-digest", context.image_digest, "--test-run-id", "123",
        "--test-run-attempt", "2", "--revision", context.revision, "--output", str(context.output)]) == 1
    output = capsys.readouterr()
    assert output.err == "Release runtime verification failed.\n" and output.out == ""


@pytest.mark.parametrize("error", [http.client.BadStatusLine("PRIVATE_REMOTE_STATUS"),
    http.client.IncompleteRead(b"PRIVATE_REMOTE_BODY", 100), zlib.error("PRIVATE_DEFLATE_ERROR")])
def test_http_and_compression_failures_cannot_escape_sanitized_cli(context, monkeypatch, capsys, error):
    monkeypatch.setattr(gate, "check", Mock(side_effect=error))
    assert gate.main(["--project", "api", "--image-digest", context.image_digest, "--test-run-id", "123",
        "--test-run-attempt", "2", "--revision", context.revision, "--output", str(context.output)]) == 1
    captured = capsys.readouterr()
    assert captured.err == "Release runtime verification failed.\n" and captured.out == ""


@pytest.mark.parametrize("arguments", [["--test-run-id", "PRIVATE_ARGUMENT"], ["--unknown=PRIVATE_ARGUMENT"],
    ["--project", "PRIVATE_PROJECT"], []])
def test_cli_argument_validation_never_echoes_supplied_values(arguments, capsys):
    assert gate.main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.err == "Release runtime verification failed.\n" and captured.out == ""


def test_cli_help_remains_available(capsys):
    with pytest.raises(SystemExit) as exc:
        gate.main(["--help"])
    assert exc.value.code == 0
    assert "--test-run-attempt" in capsys.readouterr().out


@pytest.mark.parametrize("payload", [b"null", b"[]", b"3", b'{"id":1,"id":2}', b'{"id":NaN}'])
def test_authenticated_metadata_requires_strict_json_object(monkeypatch, payload):
    monkeypatch.setattr(gate, "_http", lambda *a, **kw: payload)
    with pytest.raises(gate.ReleaseRuntimeError):
        gate.api_json("/actions/workflows/test.yml", "synthetic")


@pytest.mark.parametrize("field", ["st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"])
def test_local_input_identity_or_content_changes_are_refused(context, monkeypatch, field):
    original, calls = os.fstat, 0
    def observed(fd):
        nonlocal calls
        value = original(fd)
        calls += 1
        fields = {key: getattr(value, key) for key in ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")}
        if calls == 2:
            fields[field] += 1
        return SimpleNamespace(**fields)
    monkeypatch.setattr(gate.os, "fstat", observed)
    with pytest.raises(gate.ReleaseRuntimeError, match="local_input_changed"):
        gate._read(context.event_path)


@pytest.mark.parametrize("target", ["artifact", "collector"])
def test_input_changes_during_final_capture_prevent_successful_receipt(context, monkeypatch, target):
    def command(arguments, **kwargs):
        output = context.command(arguments, **kwargs)
        if arguments[3:4] == ["run"]:
            if target == "artifact":
                next(iter(context.metadata.values()))["digest"] = "sha256:" + "0" * 64
            else:
                (context.root / "scripts/runtime_inventory.py").write_text("# changed collector")
        return output
    monkeypatch.setattr(gate, "command", command)
    with pytest.raises(gate.ReleaseRuntimeError):
        gate.check(**context.arguments())
    assert not context.output.exists()


def test_actual_archive_size_must_match_authenticated_metadata(context):
    first = next(iter(context.metadata.values()))
    first["size_in_bytes"] += 1
    with pytest.raises(gate.ReleaseRuntimeError, match="archive_digest_mismatch"):
        gate.check(**context.arguments())


@pytest.mark.parametrize("owned", [True, False])
def test_cleanup_never_removes_unowned_container(tmp_path, monkeypatch, owned):
    identifier = "d" * 64
    cidfile = tmp_path / "cid"
    cidfile.write_text(identifier)
    commands = []
    def command(arguments, **kwargs):
        commands.append(arguments)
        if "ps" in arguments:
            return identifier
        if "inspect" in arguments:
            return json.dumps([{"Id": identifier, "Config": {"Labels": {gate.RUN_LABEL: "owner" if owned else "other"}}}])
        return ""
    monkeypatch.setattr(gate, "command", command)
    if owned:
        gate._cleanup(cidfile, "owner")
    else:
        with pytest.raises(gate.ReleaseRuntimeError, match="container_cleanup_ownership_mismatch"):
            gate._cleanup(cidfile, "owner")
    removals = [cmd for cmd in commands if "rm" in cmd]
    assert removals == ([["docker", "--context", "default", "container", "rm", "--force", identifier]] if owned else [])


def test_release_gate_precedes_release_signing_attestation_and_deployment_artifacts():
    workflow = (ROOT / ".github/workflows/release-images.yml").read_text()
    position = workflow.index("python scripts/verify_release_runtime.py")
    assert workflow.index("name: Build and publish once") < position
    for later in ("name: Sign immutable digest", "name: Attach GitHub build provenance", "name: Record deployment digest"):
        assert position < workflow.index(later)
    # Build-origin attestations may already exist; they do not claim parity.
    assert "provenance: mode=max" in workflow and "sbom: true" in workflow
    assert "--image-digest \"$RELEASE_DIGEST\"" in workflow
    assert "TEST_RUN_ID: ${{ github.event.workflow_run.id }}" in workflow
    assert "TEST_RUN_ATTEMPT: ${{ github.event.workflow_run.run_attempt }}" in workflow
    assert workflow.count("github.event.workflow_run.head_repository.full_name == github.repository") == 2
    tests = (ROOT / ".github/workflows/test.yml").read_text()
    for component in ("api", "migration", "ingestion"):
        assert f"name: {component}-test-runtime-inventory-attempt-${{{{ github.run_attempt }}}}" in tests
    assert "pnpm install --frozen-lockfile" in tests
