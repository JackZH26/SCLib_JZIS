"""Fail-closed, standard-library-only gate for destructive SCLib tests.

This prevents accidental use of inherited configuration, not a malicious local
user who can edit the tests. No DB/Redis modules are imported by this module.
Only run_disposable_tests.py creates the private, short-lived capability file.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

LABEL = "org.jzis.sclib.disposable-test-run"
SCHEMA = "sclib-disposable-tests/v1"


class UnsafeTestEnvironment(RuntimeError):
    """Messages must contain only reason codes, never supplied DSNs/secrets."""


def refuse(reason: str) -> None:
    raise UnsafeTestEnvironment(
        f"Unsafe test environment [{reason}]. Use scripts/run_disposable_tests.py; "
        "no database or Redis connection is permitted."
    ) from None


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def process_identity(pid: int) -> tuple[int, str]:
    """Read process identity without opening a service connection."""
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "ppid=", "-o", "command="],
            capture_output=True, text=True, timeout=5, check=True,
        )
        parent, command = result.stdout.strip().split(maxsplit=1)
        return int(parent), command
    except (OSError, ValueError, subprocess.SubprocessError):
        refuse("service-process-unavailable")


def docker_json(arguments: list[str]) -> Any:
    """Only the local default Docker context is allowed; capture errors privately."""
    binary = shutil.which("docker")
    if binary is None:
        refuse("docker-unavailable")
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("DOCKER_")}
    try:
        endpoint = subprocess.run(
            [binary, "--context", "default", "context", "inspect", "default",
             "--format", "{{json .Endpoints.docker.Host}}"],
            env=clean_env, capture_output=True, text=True, timeout=10, check=True,
        )
        if not str(json.loads(endpoint.stdout)).startswith("unix://"):
            refuse("docker-not-local")
        result = subprocess.run(
            [binary, "--context", "default", *arguments], env=clean_env,
            capture_output=True, text=True, timeout=10, check=True,
        )
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        refuse("docker-identity-unavailable")


def assert_service_runtime(manifest: Mapping[str, Any], service: str) -> None:
    """Bind approved host ports to processes/containers created by this runner."""
    entry = manifest[service]
    runtime = entry["runtime"]
    if manifest["backend"] == "native":
        ppid, command = process_identity(runtime["pid"])
        if ppid != manifest["runner_pid"]:
            refuse("service-owner-mismatch")
        executable = runtime["executable"]
        if not command.startswith(executable + " "):
            refuse("service-executable-mismatch")
        if service == "postgres":
            if f"-D {manifest['root']}/postgres " not in command:
                refuse("postgres-directory-mismatch")
            if f"-p {entry['port']}" not in command:
                refuse("postgres-port-mismatch")
        elif f"127.0.0.1:{entry['port']}" not in command:
            refuse("redis-port-mismatch")
    elif manifest["backend"] == "docker":
        container_id = runtime["container_id"]
        if not re.fullmatch(r"[a-f0-9]{64}", container_id):
            refuse("container-id-invalid")
        rows = docker_json(["inspect", container_id])
        if not isinstance(rows, list) or len(rows) != 1:
            refuse("container-identity-invalid")
        item = rows[0]
        if (item.get("Id") != container_id or not item.get("State", {}).get("Running")
                or item.get("Config", {}).get("Labels", {}).get(LABEL) != manifest["run_id"]):
            refuse("container-owner-mismatch")
        internal = "5432/tcp" if service == "postgres" else "6379/tcp"
        bindings = item.get("NetworkSettings", {}).get("Ports", {}).get(internal)
        if bindings != [{"HostIp": "127.0.0.1", "HostPort": str(entry["port"])}]:
            refuse("container-port-mismatch")
    else:
        refuse("backend-invalid")


@dataclass(frozen=True)
class TestCapability:
    manifest: dict[str, Any]
    database_url: str = field(repr=False)
    redis_url: str = field(repr=False)

    @property
    def run_id(self) -> str:
        return self.manifest["run_id"]


def _private_file(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or path.name != "capability.json":
        refuse("sentinel-path-invalid")
    try:
        parent = path.parent.lstat()
        info = path.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode)
                or not path.parent.name.startswith("sclib-tests-")
                or stat.S_IMODE(parent.st_mode) != 0o700
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid() or parent.st_uid != os.getuid()
                or info.st_size > 65_536):
            refuse("sentinel-not-private")
        # O_NOFOLLOW closes the last-component symlink race after lstat.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            opened = os.fstat(handle.fileno())
            if opened.st_ino != info.st_ino or opened.st_dev != info.st_dev:
                refuse("sentinel-replaced")
            value = json.load(handle)
        if not isinstance(value, dict):
            refuse("sentinel-invalid")
        return value
    except (OSError, ValueError):
        refuse("sentinel-unreadable")


def _check_dsn(value: str, service: str, entry: Mapping[str, Any], run_id: str) -> None:
    """Exact random capability + strict grammar; no query/host override allowed."""
    __tracebackhide__ = True
    try:
        parsed = urlsplit(value)
        scheme = {"postgresql", "postgresql+asyncpg", "postgresql+psycopg2"}
        if service == "redis":
            scheme = {"redis"}
        expected_name = "test_" + run_id[:16]
        expected_path = "/" + expected_name if service == "postgres" else "/0"
        if (parsed.scheme not in scheme or parsed.hostname != "127.0.0.1"
                or parsed.port != entry["port"] or not 1024 <= parsed.port <= 65535
                or parsed.port in {5432, 6379} or parsed.username != expected_name
                or parsed.path != expected_path or parsed.query or parsed.fragment
                or not re.fullmatch(r"[a-f0-9]{48}", parsed.password or "")
                or digest(value) != entry["dsn_sha256"]):
            refuse(f"{service}-target-unapproved")
    except (TypeError, KeyError, ValueError):
        refuse(f"{service}-target-invalid")


def validate_test_environment(
    environment: Mapping[str, str] | None = None, *,
    database_url: str | None = None, redis_url: str | None = None,
) -> TestCapability:
    """Validate both services before ANY application/client import or connection."""
    __tracebackhide__ = True
    env = os.environ if environment is None else environment
    if env.get("ENVIRONMENT") != "test":
        refuse("environment-not-test")
    run_id = env.get("SCLIB_TEST_RUN_ID", "")
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        refuse("run-id-missing-or-invalid")
    manifest = _private_file(Path(env.get("SCLIB_TEST_CAPABILITY", "")))
    try:
        now = time.time()
        if (manifest["schema"] != SCHEMA or manifest["run_id"] != run_id
                or manifest["root"] != str(Path(env["SCLIB_TEST_CAPABILITY"]).parent)
                or not isinstance(manifest["runner_pid"], int) or manifest["runner_pid"] <= 1):
            refuse("sentinel-identity-invalid")
        # Keep the original inclusive wall-clock interval and maximum lifetime.
        # Static, value-free reasons distinguish a clock/expiry refusal from an
        # identity mismatch without disclosing a capability, DSN or credential.
        if not manifest["created_at"] <= now <= manifest["expires_at"]:
            if now < manifest["created_at"]:
                refuse("sentinel-not-yet-valid")
            if now > manifest["expires_at"]:
                refuse("sentinel-expired")
            refuse("sentinel-lifetime-invalid")
        if manifest["expires_at"] - manifest["created_at"] > 7200:
            refuse("sentinel-lifetime-too-long")
        os.kill(manifest["runner_pid"], 0)
        db_url = env.get("DATABASE_URL", "")
        redis = env.get("REDIS_URL", "")
        _check_dsn(db_url, "postgres", manifest["postgres"], run_id)
        _check_dsn(redis, "redis", manifest["redis"], run_id)
        # Cached Settings must not evade the environment-level checks.
        if database_url is not None and database_url != db_url:
            refuse("postgres-settings-changed")
        if redis_url is not None and redis_url != redis:
            refuse("redis-settings-changed")
        if not re.fullmatch(r"[a-f0-9]{40}", manifest["redis"]["server_run_id"]):
            refuse("redis-marker-invalid")
        for service in ("postgres", "redis"):
            assert_service_runtime(manifest, service)
    except (KeyError, TypeError, ValueError, OSError):
        refuse("sentinel-invalid-or-expired")
    return TestCapability(manifest, db_url, redis)


def verify_postgres_identity(connection: Any, capability: TestCapability) -> None:
    """Second barrier, after an approved connection and before any destructive SQL."""
    from sqlalchemy import text

    row = connection.execute(text(
        "SELECT current_database(), current_user, r.rolsuper, r.rolcreatedb, "
        "r.rolcreaterole, r.rolreplication, r.rolbypassrls "
        "FROM pg_roles r WHERE r.rolname = current_user"
    )).one()
    name = "test_" + capability.run_id[:16]
    if tuple(row[:2]) != (name, name) or any(row[2:]):
        refuse("postgres-role-not-isolated")
    marker = connection.execute(text(
        "SELECT run_id FROM sclib_test_guard.run_identity WHERE expires_at > now()"
    )).scalars().all()
    if marker != [capability.run_id]:
        refuse("postgres-marker-mismatch")


async def verify_redis_identity(client: Any, capability: TestCapability) -> None:
    info = await client.info("server")
    if info.get("run_id") != capability.manifest["redis"]["server_run_id"]:
        refuse("redis-marker-mismatch")
