"""Gate an exact published SCLib image against its triggering Test artifacts.

GitHub reads and one digest-pinned registry pull are explicit release operations.
The inventory container has no network, mounts, credentials or app entrypoint.
Package-version parity is not OS/ABI equivalence or application execution proof.
"""
from __future__ import annotations

import argparse
import http.client
import io
import json
import os
import platform
import re
import selectors
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

from run_runtime_parity import RUN_LABEL, inventory_command
from runtime_inventory import compare, digest, loads

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "JackZH26/SCLib_JZIS"
API = "https://api.github.com"
WORKFLOW = ".github/workflows/test.yml"
SCHEMA = "sclib-release-runtime-parity/1.0.0"
SCOPE = "python_package_versions_not_os_libraries_or_application_execution"
ARTIFACTS = {"api": ("api-test-runtime-inventory", "migration-test-runtime-inventory"),
             "ingestion": ("ingestion-test-runtime-inventory",)}
ARCHIVE_FILES = frozenset({"test-runtime.json", "image-runtime.json", "parity-report.json"})
MAX_JSON = 2 * 1024 * 1024
MAX_ARCHIVE = 4 * 1024 * 1024
MAX_PAGES = 5
HTTP_SECONDS = 30


class ReleaseRuntimeError(ValueError):
    """Static failure category; never reflect external source/error bodies."""


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ReleaseRuntimeError("invalid_arguments")


def require(condition, code):
    if not condition:
        raise ReleaseRuntimeError(code)


def _positive(value):
    require(type(value) is int and 0 < value < 2**63, "invalid_run_identity")
    return value


def _object(value):
    require(type(value) is dict, "metadata_object_required")
    return value


def artifact_names(project, attempt):
    return tuple(name + "-attempt-" + str(_positive(attempt)) for name in ARTIFACTS[project])


def _hash(value, *, image=False):
    require(type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}" if image else r"[0-9a-f]{64}", value),
            "invalid_digest")
    return value


def _json(payload):
    require(type(payload) is bytes and len(payload) <= MAX_JSON, "metadata_limit")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate_metadata_key")
            result[key] = value
        return result
    return json.loads(payload, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ReleaseRuntimeError("invalid_metadata_number")))


def _time(value):
    require(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z", value),
            "invalid_metadata_time")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _read(path, limit=MAX_JSON):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit,
                "unsafe_local_input")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            payload = handle.read(limit + 1)
        after = os.fstat(fd)
        stable = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        require(len(payload) <= limit and all(getattr(before, key) == getattr(after, key) for key in stable),
                "local_input_changed")
        return payload
    finally:
        os.close(fd)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def _http(url, *, token=None, limit=MAX_JSON, redirect=False):
    """No ambient proxy and no automatic Authorization-bearing redirects."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "SCLib-release-runtime-gate/1"}
    if token is not None:
        require(url.startswith(API + "/repos/" + REPOSITORY + "/") or url == API + "/repos/" + REPOSITORY,
                "credential_origin_refused")
        headers["Authorization"] = "Bearer " + token
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    deadline = time.monotonic() + HTTP_SECONDS
    try:
        response = opener.open(urllib.request.Request(url, headers=headers), timeout=15)
    except urllib.error.HTTPError as exc:
        try:
            require(redirect and exc.code == 302, "github_download_unavailable")
            return exc.headers.get("Location")
        finally:
            exc.close()
    with response:
        require(not redirect and response.status == 200, "unexpected_http_status")
        length = response.headers.get("Content-Length")
        if length is not None:
            require(length.isdigit() and int(length) <= limit, "http_body_limit")
        pieces, size = [], 0
        while True:
            require(time.monotonic() < deadline, "http_total_deadline")
            piece = response.read1(min(65536, limit + 1 - size))
            require(time.monotonic() < deadline, "http_total_deadline")
            if not piece:
                break
            pieces.append(piece)
            size += len(piece)
            require(size <= limit, "http_body_limit")
        payload = b"".join(pieces)
        require(len(payload) <= limit, "http_body_limit")
        return payload


def api_json(path, token):
    require(type(path) is str and (path == "" or path.startswith("/")) and not any(char in path for char in ("#", "\\", "\n")),
            "invalid_api_path")
    return _object(_json(_http(API + "/repos/" + REPOSITORY + path, token=token)))


def download_artifact(artifact_id, token):
    location = _http(API + f"/repos/{REPOSITORY}/actions/artifacts/{_positive(artifact_id)}/zip",
                     token=token, redirect=True)
    require(type(location) is str and len(location) <= 16384, "invalid_archive_redirect")
    parsed = urllib.parse.urlsplit(location)
    require(parsed.scheme == "https" and parsed.username is None and parsed.password is None
            and parsed.port in {None, 443} and not parsed.fragment and parsed.hostname is not None,
            "invalid_archive_redirect")
    # GitHub returns short-lived signed storage URLs. Unknown storage origins
    # require a reviewed update, never forwarding credentials or guessing URLs.
    require(any(parsed.hostname.endswith(suffix) for suffix in
                (".blob.core.windows.net", ".actions.githubusercontent.com", ".githubusercontent.com")),
            "archive_storage_origin_refused")
    return _http(location, limit=MAX_ARCHIVE)  # Deliberately no Authorization.


def command(arguments, *, stdin=None, timeout=120):
    # HOME is host-side Docker login configuration only. It is never forwarded
    # with -e/--env or mounted in the isolated inventory container.
    environment = {"PATH": os.defpath, "LANG": "C.UTF-8"}
    if os.environ.get("HOME"):
        environment["HOME"] = os.environ["HOME"]
    with tempfile.TemporaryFile() as source:
        if stdin is not None:
            source.write(stdin.encode())
            source.seek(0)
        process = subprocess.Popen(arguments, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=ROOT, env=environment)
        deadline, stdout, size = time.monotonic() + timeout, [], 0
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, True)
                selector.register(process.stderr, selectors.EVENT_READ, False)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(arguments, timeout)
                    for key, _ in selector.select(min(remaining, 1)):
                        piece = os.read(key.fileobj.fileno(), 65536)
                        if not piece:
                            selector.unregister(key.fileobj)
                            continue
                        size += len(piece)
                        require(size <= MAX_JSON, "command_output_limit")
                        if key.data:
                            stdout.append(piece)
            result = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            if result:
                raise subprocess.CalledProcessError(result, arguments)
            return b"".join(stdout).decode().strip()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            process.stdout.close()
            process.stderr.close()


def _checkout(project, revision):
    require(project in ARTIFACTS and platform.system() == "Linux" and platform.machine().lower() == "x86_64",
            "release_platform_required")
    require(not any(os.environ.get(key) for key in
        ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")),
        "custom_docker_connection_refused")
    require(command(["git", "rev-parse", "HEAD"]) == revision, "checkout_revision_mismatch")
    paths = [project, "scripts/runtime_inventory.py", "scripts/run_runtime_parity.py",
             "scripts/verify_release_runtime.py", ".github/workflows/release-images.yml", WORKFLOW]
    command(["git", "diff", "--quiet", "HEAD", "--", *paths])
    require(not command(["git", "ls-files", "--others", "--exclude-standard", "--", *paths]),
            "untracked_release_input")
    collector = _read(ROOT / "scripts/runtime_inventory.py")
    expected = {"source_revision": revision, "lock_sha256": digest(_read(ROOT / project / "uv.lock")),
        "pyproject_sha256": digest(_read(ROOT / project / "pyproject.toml")), "collector_sha256": digest(collector),
        "dockerfile_sha256": digest(_read(ROOT / project / "Dockerfile")),
        "gate_sha256": digest(_read(ROOT / "scripts/verify_release_runtime.py")),
        "release_workflow_sha256": digest(_read(ROOT / ".github/workflows/release-images.yml"))}
    return expected, collector


def _run_identity(value, *, run_id, attempt, revision, repository_id, workflow_id):
    require(type(value) is dict and value.get("id") == run_id and type(value.get("id")) is int
        and value.get("run_attempt") == attempt and type(value.get("run_attempt")) is int
        and value.get("head_sha") == revision and value.get("head_branch") == "main"
        and value.get("event") == "push" and value.get("status") == "completed"
        and value.get("conclusion") == "success" and value.get("path") == WORKFLOW
        and value.get("name") == "Test" and type(value.get("workflow_id")) is int
        and value.get("workflow_id") == workflow_id,
        "triggering_test_run_mismatch")
    for key in ("repository", "head_repository"):
        repo = _object(value.get(key))
        require(repo.get("full_name") == REPOSITORY
                and _positive(repo.get("id")) == repository_id, "triggering_repository_mismatch")
    start, end = _time(value.get("run_started_at")), _time(value.get("updated_at"))
    require(start <= end, "invalid_run_window")
    return start, end


def _artifact_identity(item, *, name, run_id, revision, repository_id, start, end):
    require(type(item) is dict and item.get("name") == name and item.get("expired") is False,
            "artifact_unavailable")
    identifier = _positive(item.get("id"))
    checksum = _hash(item.get("digest"), image=True)
    size = item.get("size_in_bytes")
    require(type(size) is int and 0 < size <= MAX_ARCHIVE, "artifact_size_limit")
    witness = _object(item.get("workflow_run"))
    require(_positive(witness.get("id")) == run_id and _positive(witness.get("repository_id")) == repository_id
            and _positive(witness.get("head_repository_id")) == repository_id
            and witness.get("head_sha") == revision and witness.get("head_branch") == "main",
            "artifact_run_mismatch")
    require(start < _time(item.get("created_at")) <= _time(item.get("updated_at")) <= end
            and _time(item.get("expires_at")) > datetime.now(timezone.utc), "artifact_attempt_or_expiry_mismatch")
    return {"id": identifier, "name": name, "digest": checksum, "size_in_bytes": size}


def _archive(payload, metadata):
    require(type(payload) is bytes and len(payload) <= MAX_ARCHIVE and len(payload) == metadata["size_in_bytes"]
            and "sha256:" + digest(payload) == metadata["digest"], "archive_digest_mismatch")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        require(len(members) == len(ARCHIVE_FILES) and {item.filename for item in members} == ARCHIVE_FILES,
                "archive_file_inventory_mismatch")
        require(sum(item.file_size for item in members) <= MAX_ARCHIVE, "archive_expansion_limit")
        result = {}
        for item in members:
            mode = item.external_attr >> 16
            require(not item.is_dir() and not item.flag_bits & 1 and item.file_size <= MAX_JSON
                    and (stat.S_IFMT(mode) in {0, stat.S_IFREG})
                    and item.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}, "unsafe_archive_member")
            with archive.open(item) as handle:
                value = handle.read(MAX_JSON + 1)
            require(len(value) == item.file_size and len(value) <= MAX_JSON, "archive_member_size_mismatch")
            result[item.filename] = value
        return result


def _inventories(files, project, expected):
    tests, candidate = loads(files["test-runtime.json"].decode()), loads(files["image-runtime.json"].decode())
    for value in (tests, candidate):
        require(value["project_name"] == "sclib-" + project and value["system"] == "Linux"
                and value["machine"] == "x86_64", "artifact_project_or_platform_mismatch")
        require(all(value[key] == expected[key] for key in
            ("source_revision", "lock_sha256", "pyproject_sha256", "collector_sha256")), "artifact_input_pin_mismatch")
    require(not compare(candidate, tests), "candidate_inventory_mismatch")
    report = _json(files["parity-report.json"])
    fields = {"schema", "matches", "failures", "project", "image_id", "image_architecture", "scope",
              "source_revision", "lock_sha256", "pyproject_sha256", "collector_sha256", "dockerfile_sha256"}
    require(type(report) is dict and set(report) == fields and report["schema"] == "sclib-runtime-parity/v1"
            and report["matches"] is True and report["failures"] == [] and report["project"] == project
            and report["image_architecture"] == "amd64" and report["scope"] == SCOPE
            and all(report[key] == expected[key] for key in
                ("source_revision", "lock_sha256", "pyproject_sha256", "collector_sha256", "dockerfile_sha256")),
            "candidate_report_mismatch")
    _hash(report["image_id"], image=True)
    return tests


def _cleanup(cidfile, run_id):
    if not cidfile.exists():
        return
    identifier = _read(cidfile, 65).decode().strip()
    require(re.fullmatch(r"[0-9a-f]{64}", identifier), "container_cleanup_identity_mismatch")
    found = command(["docker", "--context", "default", "ps", "-aq", "--no-trunc", "--filter", "id=" + identifier])
    if not found:
        return
    require(found == identifier, "container_cleanup_identity_mismatch")
    details = _json(command(["docker", "--context", "default", "container", "inspect", identifier]).encode())
    require(type(details) is list and len(details) == 1, "container_cleanup_ownership_mismatch")
    detail = _object(details[0])
    require(detail.get("Id") == identifier
            and _object(_object(detail.get("Config")).get("Labels")).get(RUN_LABEL) == run_id,
            "container_cleanup_ownership_mismatch")
    command(["docker", "--context", "default", "container", "rm", "--force", identifier])


def _output(output, files):
    parent = output.parent.resolve(strict=True)
    require(output.parent.absolute() == parent and output.name not in {"", ".", ".."}, "unsafe_output_parent")
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.mkdir(output.name, mode=0o700, dir_fd=parent_fd)  # Existing output is never reused.
        directory = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            for name, data in sorted(files.items()):
                require(re.fullmatch(r"[a-z0-9-]+\.json", name) and type(data) is bytes and len(data) <= MAX_JSON,
                        "output_file_limit")
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
            require(os.stat(output.name, dir_fd=parent_fd, follow_symlinks=False).st_ino == os.fstat(directory).st_ino
                    and output.parent.resolve(strict=True) == parent
                    and os.stat(parent).st_ino == os.fstat(parent_fd).st_ino
                    and os.stat(parent).st_dev == os.fstat(parent_fd).st_dev, "output_directory_changed")
        finally:
            os.close(directory)
    finally:
        os.close(parent_fd)


def check(*, project, image_digest, test_run_id, test_run_attempt, revision, output):
    _hash(image_digest, image=True)
    _positive(test_run_id), _positive(test_run_attempt)
    require(type(revision) is str and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision), "invalid_revision")
    output = Path(output)
    require(output.parent.absolute() == output.parent.resolve(strict=True) and not os.path.lexists(output),
            "unsafe_or_existing_output")
    require(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_EVENT_NAME") == "workflow_run"
            and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
            and os.environ.get("GITHUB_API_URL") == API
            and os.environ.get("GITHUB_SERVER_URL") == "https://github.com", "authenticated_workflow_required")
    token = os.environ.get("GH_TOKEN")
    require(type(token) is str and 0 < len(token) <= 4096 and not any(ord(c) < 33 for c in token), "github_token_required")
    event = _json(_read(Path(os.environ["GITHUB_EVENT_PATH"])))
    event = _object(event)
    event_repo = _object(event.get("repository"))
    require(event.get("action") == "completed" and event_repo.get("full_name") == REPOSITORY, "trigger_event_mismatch")
    expected, collector = _checkout(project, revision)
    names = artifact_names(project, test_run_attempt)
    repository = api_json("", token)
    repository_id = _positive(repository.get("id"))
    require(repository.get("full_name") == REPOSITORY, "repository_metadata_mismatch")
    require(_positive(event_repo.get("id")) == repository_id, "trigger_repository_mismatch")
    workflow = api_json("/actions/workflows/test.yml", token)
    workflow_id = _positive(workflow.get("id"))
    require(workflow.get("path") == WORKFLOW and workflow.get("name") == "Test", "workflow_identity_mismatch")
    identity = dict(run_id=test_run_id, attempt=test_run_attempt, revision=revision,
                    repository_id=repository_id, workflow_id=workflow_id)
    event_window = _run_identity(event.get("workflow_run"), **identity)
    actual_run = api_json(f"/actions/runs/{test_run_id}/attempts/{test_run_attempt}", token)
    start, end = _run_identity(actual_run, **identity)
    # GitHub's event/run and attempt views can update their completion metadata
    # at different times. Identity and attempt start must still agree exactly;
    # artifacts must fit inside BOTH authenticated windows, never their union.
    require(event_window[0] == start, "trigger_attempt_window_mismatch")
    end = min(event_window[1], end)
    found, total, all_ids = {}, None, set()
    for page in range(1, MAX_PAGES + 1):
        listing = api_json(f"/actions/runs/{test_run_id}/artifacts?per_page=100&page={page}", token)
        count, items = listing.get("total_count"), listing.get("artifacts")
        require(type(count) is int and 0 <= count <= MAX_PAGES * 100 and type(items) is list and len(items) <= 100,
                "artifact_listing_limit")
        require(total in {None, count}, "artifact_listing_changed")
        total = count
        for item in items:
            item = _object(item)
            identifier = _positive(item.get("id"))
            require(identifier not in all_ids, "duplicate_artifact_identity")
            all_ids.add(identifier)
            if item.get("name") in names:
                require(item["name"] not in found, "duplicate_named_artifact")
                found[item["name"]] = item
        if len(all_ids) >= total:
            break
        require(len(items) == 100, "incomplete_artifact_listing")
    require(len(all_ids) == total and set(found) == set(names), "required_test_artifacts_missing")
    tests, retained, witnesses = {}, {}, []
    for name in names:
        arguments = dict(name=name, run_id=test_run_id, revision=revision, repository_id=repository_id, start=start, end=end)
        metadata = _artifact_identity(found[name], **arguments)
        current = api_json(f"/actions/artifacts/{metadata['id']}", token)
        require(_artifact_identity(current, **arguments) == metadata, "artifact_metadata_changed")
        files = _archive(download_artifact(metadata["id"], token), metadata)
        tests[name] = _inventories(files, project, expected)
        for filename, data in files.items():
            retained[name + "-" + filename] = data
        witnesses.append({**metadata, "test_inventory_sha256": digest(files["test-runtime.json"]),
                          "archive_files": {key: digest(value) for key, value in sorted(files.items())}})
    endpoint = _json(command(["docker", "--context", "default", "context", "inspect", "default",
                             "--format", "{{json .Endpoints.docker.Host}}"] ).encode())
    require(type(endpoint) is str and endpoint.startswith("unix:///"), "local_docker_required")
    image = f"ghcr.io/jackzh26/sclib-{project}@{image_digest}"
    command(["docker", "--context", "default", "pull", "--platform", "linux/amd64", image], timeout=300)
    details = _json(command(["docker", "--context", "default", "image", "inspect", image]).encode())
    require(type(details) is list and len(details) == 1, "release_image_identity_mismatch")
    detail = _object(details[0])
    image_id = _hash(detail.get("Id"), image=True)
    repo_digests = detail.get("RepoDigests")
    require(type(repo_digests) is list and 1 <= len(repo_digests) <= 100
            and all(type(value) is str and len(value) <= 1024 for value in repo_digests),
            "release_digest_inventory_invalid")
    require(image in repo_digests and detail.get("Os") == "linux"
            and detail.get("Architecture") == "amd64", "release_digest_or_platform_mismatch")
    labels = _object(_object(detail.get("Config")).get("Labels"))
    require(labels.get("org.opencontainers.image.revision") == revision
            and labels.get("org.opencontainers.image.source") == "https://github.com/" + REPOSITORY,
            "release_revision_mismatch")
    with tempfile.TemporaryDirectory(prefix="sclib-final-runtime-") as directory:
        cidfile, run_id = Path(directory) / "container-id", uuid.uuid4().hex
        try:
            runtime_bytes = command(inventory_command(image_id, cidfile, run_id, expected), stdin=collector.decode()).encode()
            runtime = loads(runtime_bytes.decode())
        finally:
            _cleanup(cidfile, run_id)
    failures = {name: compare(runtime, value) for name, value in tests.items()}
    # A safe static code replaces detailed potentially attacker-controlled names.
    matches = not any(failures.values())
    expected_after, collector_after = _checkout(project, revision)
    require(expected_after == expected and collector_after == collector, "checkout_changed_during_capture")
    for metadata in witnesses:
        current = api_json(f"/actions/artifacts/{metadata['id']}", token)
        verified = _artifact_identity(current, name=metadata["name"], run_id=test_run_id, revision=revision,
                                      repository_id=repository_id, start=start, end=end)
        require(all(metadata[key] == value for key, value in verified.items()), "artifact_changed_during_capture")
    report = {"schema": SCHEMA, "matches": matches, "reason_codes": [] if matches else ["runtime_inventory_mismatch"],
        "repository": REPOSITORY, "test_run_id": test_run_id, "test_run_attempt": test_run_attempt,
        "test_workflow_id": workflow_id, "project": project, "image": image, "image_digest": image_digest,
        "image_id": image_id, "platform": "linux/amd64", **expected, "artifacts": witnesses,
        "comparisons": {name: {"matches": not reasons, "mismatch_count": len(reasons)} for name, reasons in failures.items()},
        "runtime_inventory_sha256": digest(runtime_bytes), "scope": SCOPE}
    retained["release-runtime.json"] = runtime_bytes
    retained["release-parity-report.json"] = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
    _output(Path(output), retained)
    return report


def main(argv=None):
    parser = _SafeParser(description=__doc__)
    parser.add_argument("--project", choices=tuple(ARTIFACTS), required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--test-run-id", type=int, required=True)
    parser.add_argument("--test-run-attempt", type=int, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        report = check(**vars(args))
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError, zipfile.BadZipFile,
            RuntimeError, RecursionError, OverflowError, http.client.HTTPException, zlib.error):
        print("Release runtime verification failed.", file=sys.stderr)
        return 1
    print(json.dumps({key: report[key] for key in ("schema", "matches", "project", "image_digest",
                                                 "test_run_id", "test_run_attempt", "reason_codes")}, sort_keys=True))
    return int(not report["matches"])


if __name__ == "__main__":
    raise SystemExit(main())
