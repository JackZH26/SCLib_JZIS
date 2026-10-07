"""One authorized release's package parity, without claiming API regression.

The control workflow copies this helper before checking out the frozen payload.
Only payload modules are imported. Registry/Docker reads happen only in main.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import selectors
import stat
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT / "scripts"))
from run_runtime_parity import RUN_LABEL, inventory_command
from runtime_inventory import compare, digest, loads

PAYLOAD = "bcf2d8549348646ca0908a6ee8144fec59ab3ce7"
REPOSITORY = "JackZH26/SCLib_JZIS"
WORKFLOW_REF = REPOSITORY + "/.github/workflows/release-images.yml@refs/heads/main"
SCOPE = "python_package_versions_not_os_libraries_or_application_execution"
LIMIT = 2 * 1024 * 1024


class RuntimeGateError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise RuntimeGateError(code)


def read(path, limit=LIMIT):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and 0 < before.st_size <= limit, "input_file_shape")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            body = handle.read(limit + 1)
        after = os.fstat(fd)
        fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        require(len(body) == before.st_size and all(getattr(before, k) == getattr(after, k) for k in fields),
                "input_file_changed")
        return body
    finally:
        os.close(fd)


def decode(body):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    return json.loads(body, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(RuntimeGateError("nonfinite_json")))


def save(root, name, body):
    require(name in {"started.json", "locked-runtime.json", "release-runtime.json",
                     "release-parity-report.json", "first-failure.json"}, "output_name")
    require(len(body) <= LIMIT, "output_limit")
    fd = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def command(arguments, *, stdin=None, timeout=120):
    environment = {"PATH": os.defpath, "LANG": "C.UTF-8"}
    # Host-side registry authentication only; never passed or mounted in inventory.
    if os.environ.get("HOME"):
        environment["HOME"] = os.environ["HOME"]
    with tempfile.TemporaryFile() as source:
        if stdin is not None:
            source.write(stdin.encode())
            source.seek(0)
        process = subprocess.Popen(arguments, stdin=source, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=ROOT, env=environment)
        deadline, pieces, size = time.monotonic() + timeout, [], 0
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, True)
                selector.register(process.stderr, selectors.EVENT_READ, False)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    require(remaining > 0, "command_timeout")
                    for key, _ in selector.select(min(remaining, 1)):
                        piece = os.read(key.fileobj.fileno(), 65536)
                        if not piece:
                            selector.unregister(key.fileobj)
                            continue
                        size += len(piece)
                        require(size <= LIMIT, "command_output_limit")
                        if key.data:
                            pieces.append(piece)
            require(process.wait(timeout=max(.01, deadline - time.monotonic())) == 0, "command_failed")
            return b"".join(pieces).decode().strip()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            process.stdout.close()
            process.stderr.close()


def dispatch_identity():
    required = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": REPOSITORY,
                "GITHUB_API_URL": "https://api.github.com", "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_WORKFLOW_REF": WORKFLOW_REF, "GITHUB_RUN_ATTEMPT": "1"}
    require(all(os.environ.get(k) == v for k, v in required.items()), "one_time_dispatch_identity")
    control = os.environ.get("GITHUB_SHA", "")
    run = os.environ.get("GITHUB_RUN_ID", "")
    require(re.fullmatch(r"[0-9a-f]{40}", control) and re.fullmatch(r"[1-9][0-9]*", run), "control_identity")
    event = decode(read(Path(os.environ["GITHUB_EVENT_PATH"])))
    repo = event.get("repository", {})
    require(repo.get("full_name") == REPOSITORY and repo.get("id") == 1210057429,
            "dispatch_repository")
    return {"control_revision": control, "control_run_id": int(run), "control_run_attempt": 1,
            "workflow_ref": WORKFLOW_REF, "event": "workflow_dispatch", "ref": "refs/heads/main"}


def checkout(project):
    require(project in {"api", "ingestion"} and platform.system() == "Linux"
            and platform.machine().lower() == "x86_64", "payload_platform")
    require(not any(os.environ.get(k) for k in
            ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")),
            "custom_docker_connection")
    require(command(["git", "rev-parse", "HEAD"]) == PAYLOAD, "payload_revision")
    paths = [project, "scripts/runtime_inventory.py", "scripts/run_runtime_parity.py"]
    command(["git", "diff", "--quiet", "HEAD", "--", *paths])
    require(not command(["git", "ls-files", "--others", "--exclude-standard", "--", *paths]), "untracked_payload_input")
    collector = read(ROOT / "scripts/runtime_inventory.py")
    expected = {"source_revision": PAYLOAD, "lock_sha256": digest(read(ROOT / project / "uv.lock")),
                "pyproject_sha256": digest(read(ROOT / project / "pyproject.toml")),
                "collector_sha256": digest(collector), "dockerfile_sha256": digest(read(ROOT / project / "Dockerfile")),
                "parity_source_sha256": digest(read(ROOT / "scripts/run_runtime_parity.py"))}
    return expected, collector


def validate_locked(value, project, expected):
    require(value["project_name"] == "sclib-" + project and value["system"] == "Linux"
            and value["machine"] == "x86_64" and value["python_minor"] == "3.11", "locked_inventory_platform")
    require(all(value[k] == expected[k] for k in
            ("source_revision", "lock_sha256", "pyproject_sha256", "collector_sha256")), "locked_inventory_input_pin")


def validate_image(detail, image, revision):
    require(detail.get("Os") == "linux" and detail.get("Architecture") == "amd64"
            and image in detail.get("RepoDigests", []), "registry_digest_platform")
    identifier = detail.get("Id", "")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", identifier), "image_id")
    labels = detail.get("Config", {}).get("Labels") or {}
    require(labels.get("org.opencontainers.image.revision") == revision
            and labels.get("org.opencontainers.image.source") == "https://github.com/" + REPOSITORY,
            "OCI_source_revision")
    return identifier


def cleanup(cidfile, owned):
    if not cidfile.exists():
        return
    identifier = read(cidfile, 65).decode().strip()
    require(re.fullmatch(r"[0-9a-f]{64}", identifier), "cleanup_id")
    found = command(["docker", "--context", "default", "ps", "-aq", "--no-trunc", "--filter", "id=" + identifier])
    if not found:
        return
    require(found == identifier, "cleanup_id")
    values = decode(command(["docker", "--context", "default", "container", "inspect", identifier]))
    require(type(values) is list and len(values) == 1 and values[0].get("Id") == identifier
            and (values[0].get("Config", {}).get("Labels") or {}).get(RUN_LABEL) == owned, "cleanup_ownership")
    command(["docker", "--context", "default", "container", "rm", "--force", identifier])


def check(*, project, image_digest, locked_inventory, output):
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest), "digest_shape")
    identity = dispatch_identity()
    root = Path(output).absolute()
    require(root.parent == root.parent.resolve(strict=True) and not os.path.lexists(root), "fresh_output")
    root.mkdir(mode=0o700, exist_ok=False)
    try:
        save(root, "started.json", encoded({**identity, "payload_revision": PAYLOAD,
            "at_utc": datetime.now(timezone.utc).isoformat(), "scope": SCOPE, "automatic_retry": False}))
        expected, collector = checkout(project)
        locked_body = read(locked_inventory)
        locked = loads(locked_body.decode())
        validate_locked(locked, project, expected)
        save(root, "locked-runtime.json", locked_body)
        endpoint = decode(command(["docker", "--context", "default", "context", "inspect", "default",
                                   "--format", "{{json .Endpoints.docker.Host}}"] ))
        require(type(endpoint) is str and endpoint.startswith("unix:///"), "local_docker")
        image = f"ghcr.io/jackzh26/sclib-{project}@{image_digest}"
        command(["docker", "--context", "default", "pull", "--platform", "linux/amd64", image], timeout=300)
        details = decode(command(["docker", "--context", "default", "image", "inspect", image]))
        require(type(details) is list and len(details) == 1, "image_inventory")
        image_id = validate_image(details[0], image, PAYLOAD)
        with tempfile.TemporaryDirectory(prefix="sclib-one-time-runtime-") as directory:
            cidfile, owned = Path(directory) / "container-id", uuid.uuid4().hex
            try:
                runtime_body = command(inventory_command(image_id, cidfile, owned, expected), stdin=collector.decode()).encode()
                runtime = loads(runtime_body.decode())
            finally:
                cleanup(cidfile, owned)
        failures = compare(runtime, locked)
        expected_after, collector_after = checkout(project)
        require(expected_after == expected and collector_after == collector
                and read(locked_inventory) == locked_body, "inputs_changed")
        report = {"schema": "sclib-one-time-release-runtime-parity/1.0.0", **identity, **expected,
                  "helper_sha256": digest(read(Path(__file__))), "project": project, "image": image,
                  "image_digest": image_digest, "image_id": image_id, "platform": "linux/amd64",
                  "locked_inventory_sha256": digest(locked_body), "runtime_inventory_sha256": digest(runtime_body),
                  "matches": not failures, "reason_codes": [] if not failures else ["runtime_inventory_mismatch"],
                  "mismatch_count": len(failures), "scope": SCOPE,
                  "inventory_source": "fresh_uv_locked_dev_venv_not_Test_artifacts",
                  "api_regression": "pending_waived_for_this_one_release_not_verified_here",
                  "claims_Test_success": False, "claims_application_execution": False,
                  "Security_scan_signing_provenance_and_Deploy_gates": "separate_workflow_requirements_not_verified_here"}
        save(root, "release-runtime.json", runtime_body)
        save(root, "release-parity-report.json", encoded(report))
        return report
    except Exception as error:
        code = str(error) if isinstance(error, RuntimeGateError) else type(error).__name__
        save(root, "first-failure.json", encoded({"status": "failed", "code": code,
             "payload_revision": PAYLOAD, "automatic_retry": False, "claims_Test_success": False}))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", choices=("api", "ingestion"), required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--locked-inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = check(**vars(args))
    except Exception:
        print("One-time package runtime verification failed.", file=sys.stderr)
        return 1
    print(json.dumps({k: report[k] for k in ("schema", "project", "source_revision", "image_digest", "matches", "scope")}))
    return int(not report["matches"])


if __name__ == "__main__":
    raise SystemExit(main())
