"""Configure only the disposable GitHub-hosted runner's local Docker daemon.

The Google cache is optional transport: canonical image references and Docker
Hub fallback remain unchanged. Never run this against application services.
"""
from __future__ import annotations

import json
import os
import platform
import stat
import subprocess
import tempfile
from pathlib import Path

CONFIG = Path("/etc/docker/daemon.json")
MIRROR = "https://mirror.gcr.io"
DOCKER = ["docker", "--context", "default"]
OVERRIDES = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")


def run(command: list[str], *, timeout: int = 20) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True,
                          timeout=timeout).stdout.strip()


def require_runner() -> None:
    expected = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux"}
    if platform.system() != "Linux" or any(os.environ.get(k) != v for k, v in expected.items()):
        raise ValueError("not a disposable GitHub-hosted Linux runner")
    if any(os.environ.get(key) for key in OVERRIDES):
        raise ValueError("custom Docker configuration is not supported")


def local_endpoint() -> str:
    if run(["docker", "context", "show"]) != "default":
        raise ValueError("default context required")
    endpoint = json.loads(run(DOCKER + ["context", "inspect", "default", "--format", "{{json .Endpoints.docker.Host}}"]))
    if endpoint not in ("unix:///var/run/docker.sock", "unix:///run/docker.sock"):
        raise ValueError("local system Docker socket required")
    return endpoint


def require_idle() -> None:
    for status in ("running", "paused", "restarting"):
        if run(DOCKER + ["ps", "--quiet", "--filter", "status=" + status]):
            raise ValueError("refusing to restart Docker with active containers")


def read_config() -> bytes | None:
    if CONFIG.is_symlink():
        raise ValueError("symlink configuration is not supported")
    if not CONFIG.exists():
        return None
    with CONFIG.open("rb") as source:
        value = source.read(1_048_577)
    if len(value) > 1_048_576:
        raise ValueError("configuration is too large")
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate configuration key")
        result[key] = value
    return result


def merged_config(original: bytes | None) -> tuple[dict, bool]:
    document = {} if original is None else json.loads(original, object_pairs_hook=unique_object)
    if not isinstance(document, dict):
        raise ValueError("configuration must be an object")
    mirrors = document.get("registry-mirrors", [])
    if not isinstance(mirrors, list) or any(not isinstance(item, str) for item in mirrors):
        raise ValueError("invalid existing mirrors")
    if MIRROR in mirrors:
        return document, False
    return {**document, "registry-mirrors": [MIRROR, *mirrors]}, True


def configured() -> bool:
    mirrors = json.loads(run(DOCKER + ["info", "--format", "{{json .RegistryConfig.Mirrors}}"]))
    return isinstance(mirrors, list) and any(item in (MIRROR, MIRROR + "/") for item in mirrors)


def configure() -> dict:
    require_runner()
    endpoint = local_endpoint()
    require_idle()
    original = read_config()
    mode = stat.S_IMODE(CONFIG.stat().st_mode) if original is not None else 0o644
    document, changed = merged_config(original)
    if not changed and configured():
        return {"mirror": MIRROR, "endpoint": endpoint, "restarted": False}
    # Only this temporary candidate is validated. The existing file is not
    # replaced until validation and a second idle/context/config check pass.
    with tempfile.TemporaryDirectory(prefix="sclib-ci-docker-") as temporary:
        candidate = Path(temporary) / "daemon.json"
        candidate.write_text(json.dumps(document) + "\n")
        candidate.chmod(0o600)
        run(["sudo", "-n", "dockerd", "--validate", "--config-file", str(candidate)])
        if read_config() != original or local_endpoint() != endpoint:
            raise ValueError("daemon configuration changed during preparation")
        require_idle()
        if changed:
            run(["sudo", "-n", "install", "-m", f"{mode:04o}", str(candidate), str(CONFIG)])
        run(["sudo", "-n", "systemctl", "restart", "docker"], timeout=60)
    if local_endpoint() != endpoint or not configured():
        raise ValueError("mirror activation not verified")
    return {"mirror": MIRROR, "endpoint": endpoint, "restarted": True}


def main() -> int:
    try:
        report = configure()
    except (ValueError, TypeError, OSError, subprocess.SubprocessError):
        # Never print configuration, command output, exception text or environment.
        print("CI Docker mirror setup failed")
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
