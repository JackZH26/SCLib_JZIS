"""Build a local CI release image and inspect packages without starting its app.

No registry push, Compose, service connection, mounted files or credentials.
Builds need ordinary public dependency downloads; inventory containers have no
network, writable filesystem or Linux capabilities. Linux/local Docker only.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from runtime_inventory import compare, digest, loads

ROOT = Path(__file__).resolve().parents[1]
RUN_LABEL = "org.jzis.sclib.runtime-parity.run"


def run(command: list[str], *, stdin: str | None = None, timeout: int = 120) -> str:
    # No inherited DB/cloud/provider settings are forwarded, even to Docker.
    return subprocess.run(
        command, input=stdin, text=True, check=True, capture_output=True,
        cwd=ROOT, timeout=timeout, env={"PATH": os.defpath, "LANG": "C.UTF-8"},
    ).stdout.strip()


def provenance(project: str, tests: dict) -> dict:
    if project not in {"api", "ingestion"} or platform.system() != "Linux":
        raise ValueError("parity requires an explicit project and Linux runner")
    if any(os.environ.get(name) for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")):
        raise ValueError("custom Docker connection settings are not supported")
    revision = run(["git", "rev-parse", "HEAD"])
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision):
        raise ValueError("invalid checkout revision")
    paths = [project, "scripts/runtime_inventory.py", "scripts/run_runtime_parity.py"]
    run(["git", "diff", "--quiet", "HEAD", "--", *paths])
    if run(["git", "ls-files", "--others", "--exclude-standard", "--", *paths]):
        raise ValueError("untracked build inputs are not revision-bound")
    result = {
        "source_revision": revision,
        "lock_sha256": digest((ROOT / project / "uv.lock").read_bytes()),
        "pyproject_sha256": digest((ROOT / project / "pyproject.toml").read_bytes()),
        "collector_sha256": digest((ROOT / "scripts/runtime_inventory.py").read_bytes()),
        "dockerfile_sha256": digest((ROOT / project / "Dockerfile").read_bytes()),
    }
    if any(tests.get(key) != value for key, value in result.items() if key != "dockerfile_sha256"):
        raise ValueError("test inventory does not match checked-out inputs")
    if (tests["project_name"] != f"sclib-{project}" or tests["system"] != "Linux"
            or tests["machine"] != "x86_64"):
        raise ValueError("test inventory has the wrong project or platform")
    endpoint = json.loads(run(["docker", "--context", "default", "context", "inspect", "default",
                              "--format", "{{json .Endpoints.docker.Host}}"] ))
    if not isinstance(endpoint, str) or not endpoint.startswith("unix:///"):
        raise ValueError("only the local default Unix Docker daemon is supported")
    return result


def inventory_command(image_id: str, cidfile: Path, run_id: str, expected: dict) -> list[str]:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("inventory requires an immutable local image ID")
    return [
        "docker", "--context", "default", "run", "--rm", "--pull", "never",
        "--network", "none", "--read-only", "--no-healthcheck", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "32", "--memory", "256m",
        "--user", "1001:1001", "--label", f"{RUN_LABEL}={run_id}",
        "--cidfile", str(cidfile), "--entrypoint", "/opt/venv/bin/python", "-i", image_id,
        "-I", "-B", "-", "--lock", "/app/uv.lock", "--pyproject", "/app/pyproject.toml",
        "--revision", expected["source_revision"], "--collector-sha256", expected["collector_sha256"],
    ]


def clean_owned_container(cidfile: Path, run_id: str) -> None:
    if not cidfile.exists():
        return
    container_id = cidfile.read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", container_id):
        raise ValueError("invalid inventory container identity; no cleanup attempted")
    # Normal --rm completion already deleted it. Inspect only this exact ID;
    # interrupted Docker CLI calls must not leave a live inventory container.
    result = json.loads(run(["docker", "--context", "default", "ps", "-aq", "--no-trunc",
                             "--filter", f"id={container_id}", "--format", "{{json .ID}}"] ) or "null")
    if result is None:
        return
    if result != container_id:
        raise ValueError("container cleanup identity mismatch")
    details = json.loads(run(["docker", "--context", "default", "container", "inspect", container_id]))
    if len(details) != 1 or details[0].get("Id") != container_id or details[0].get("Config", {}).get("Labels", {}).get(RUN_LABEL) != run_id:
        raise ValueError("container cleanup ownership mismatch")
    run(["docker", "--context", "default", "container", "rm", "--force", container_id])


def check(project: str, tests_path: Path, output: Path) -> dict:
    tests = loads(tests_path.read_text())
    expected = provenance(project, tests)
    output.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    labels = {"org.opencontainers.image.revision": expected["source_revision"],
              "org.jzis.sclib.runtime-parity.project": project,
              **{f"org.jzis.sclib.runtime-parity.{key}": value for key, value in expected.items() if key != "source_revision"}}
    with tempfile.TemporaryDirectory(prefix="sclib-runtime-parity-") as temporary:
        iidfile, cidfile = Path(temporary) / "image-id", Path(temporary) / "container-id"
        # Match release-images.yml's current explicit deployment platform.
        command = ["docker", "--context", "default", "build", "--pull",
                   "--platform", "linux/amd64", "--iidfile", str(iidfile)]
        for key, value in sorted(labels.items()):
            command.extend(["--label", f"{key}={value}"])
        if project == "api":
            command.extend(["--build-arg", f"GIT_SHA={expected['source_revision'][:7]}"])
        command.extend(["--file", str(ROOT / project / "Dockerfile"), str(ROOT / project)])
        run(command, timeout=1200)
        image_id = iidfile.read_text().strip()
        capture_command = inventory_command(image_id, cidfile, run_id, expected)
        details = json.loads(run(["docker", "--context", "default", "image", "inspect", image_id]))
        if (len(details) != 1 or details[0].get("Id") != image_id
                or details[0].get("Os") != "linux" or details[0].get("Architecture") != "amd64"):
            raise ValueError("built image identity/platform mismatch")
        if any(details[0].get("Config", {}).get("Labels", {}).get(key) != value for key, value in labels.items()):
            raise ValueError("built image provenance mismatch")
        try:
            # Exactly the same collector bytes as test capture; stdin avoids
            # mounting any checkout, secret, Docker socket or credential file.
            runtime = loads(run(capture_command, stdin=(ROOT / "scripts/runtime_inventory.py").read_text()))
        finally:
            clean_owned_container(cidfile, run_id)
        failures = compare(runtime, tests)
        report = {"schema": "sclib-runtime-parity/v1", "matches": not failures,
                  "failures": failures, "project": project, "image_id": image_id,
                  "image_architecture": details[0].get("Architecture"), **expected,
                  "scope": "python_package_versions_not_os_libraries_or_application_execution"}
        (output / "image-runtime.json").write_text(json.dumps(runtime, sort_keys=True, indent=2) + "\n")
        (output / "parity-report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, choices=("api", "ingestion"))
    parser.add_argument("--tests", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = check(args.project, args.tests, args.output)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        # No raw subprocess output, environment, DSNs or Docker config is logged.
        print("Runtime parity failed: build, capture or provenance validation failed.")
        return 1
    print(json.dumps(report, sort_keys=True))
    return int(not report["matches"])


if __name__ == "__main__":
    raise SystemExit(main())
