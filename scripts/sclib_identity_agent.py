#!/usr/bin/env python3
"""Rotate short-lived, role-scoped OIDC subject tokens for VPS2 workloads."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROLES = {"api", "ingestion", "backup"}
KID_PATTERN = re.compile(r"^[a-f0-9]{32,64}$")
AUDIENCE_PATTERN = re.compile(
    r"^https://iam\.googleapis\.com/projects/[0-9]+/locations/global/"
    r"workloadIdentityPools/sclib-production/providers/vps2-(api|ingestion|backup)$"
)
DEFAULT_OUTPUT_PREFIX = Path("/run/sclib-identity")
DEFAULT_KEY_PREFIX = Path("/etc/sclib/identity-agent")


class IdentityAgentError(ValueError):
    """The identity-agent configuration or signing operation is unsafe."""


@dataclass(frozen=True)
class Workload:
    role: str
    issuer: str
    subject: str
    audience: str
    kid: str
    private_key: Path
    output: Path
    gid: int


@dataclass(frozen=True)
class AgentConfig:
    token_ttl_seconds: int
    interval_seconds: int
    workloads: tuple[Workload, ...]


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _inside(path: Path, prefix: Path, description: str) -> Path:
    if not path.is_absolute():
        raise IdentityAgentError(f"{description} must be an absolute path")
    try:
        path.relative_to(prefix)
    except ValueError as exc:
        raise IdentityAgentError(f"{description} must be under {prefix}") from exc
    return path


def _load_workload(
    value: Any,
    *,
    output_prefix: Path,
    key_prefix: Path,
) -> Workload:
    if not isinstance(value, dict):
        raise IdentityAgentError("each workload must be an object")
    required = {
        "role",
        "issuer",
        "subject",
        "audience",
        "kid",
        "private_key",
        "output",
        "gid",
    }
    if set(value) != required:
        raise IdentityAgentError("workload fields do not match the required schema")
    role = value["role"]
    if role not in ROLES:
        raise IdentityAgentError(f"unsupported workload role: {role}")
    issuer = value["issuer"]
    expected_issuer = f"https://api.jzis.org/sclib-identity/{role}"
    if issuer != expected_issuer or urlparse(issuer).scheme != "https":
        raise IdentityAgentError(f"issuer must be {expected_issuer}")
    subject = value["subject"]
    if subject != f"sclib-{role}-vps2":
        raise IdentityAgentError(f"subject must be sclib-{role}-vps2")
    audience = value["audience"]
    match = AUDIENCE_PATTERN.fullmatch(audience) if isinstance(audience, str) else None
    if not match or match.group(1) != role:
        raise IdentityAgentError("audience must target the matching VPS2 WIF provider")
    kid = value["kid"]
    if not isinstance(kid, str) or not KID_PATTERN.fullmatch(kid):
        raise IdentityAgentError("kid must be a SHA-256 public-key fingerprint")
    private_key = _inside(Path(value["private_key"]), key_prefix, "private key")
    try:
        key_stat = private_key.stat()
    except OSError as exc:
        raise IdentityAgentError(f"cannot read private key metadata: {exc}") from exc
    if not private_key.is_file() or key_stat.st_size == 0:
        raise IdentityAgentError("private key must be a non-empty regular file")
    if key_stat.st_uid != os.geteuid() or key_stat.st_mode & 0o077:
        raise IdentityAgentError("private key must be owned by the agent user with mode 0600")
    output = _inside(Path(value["output"]), output_prefix, "subject-token output")
    gid = value["gid"]
    if not isinstance(gid, int) or gid < 0:
        raise IdentityAgentError("gid must be a non-negative integer")
    return Workload(role, issuer, subject, audience, kid, private_key, output, gid)


def load_config(
    path: Path,
    *,
    output_prefix: Path = DEFAULT_OUTPUT_PREFIX,
    key_prefix: Path = DEFAULT_KEY_PREFIX,
) -> AgentConfig:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityAgentError(f"cannot read identity-agent configuration: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {
        "token_ttl_seconds",
        "interval_seconds",
        "workloads",
    }:
        raise IdentityAgentError("identity-agent configuration has an invalid schema")
    ttl = value["token_ttl_seconds"]
    interval = value["interval_seconds"]
    if not isinstance(ttl, int) or not 120 <= ttl <= 600:
        raise IdentityAgentError("token_ttl_seconds must be between 120 and 600")
    if not isinstance(interval, int) or not 15 <= interval <= ttl - 90:
        raise IdentityAgentError("interval_seconds must refresh at least 90 seconds before expiry")
    raw_workloads = value["workloads"]
    if not isinstance(raw_workloads, list) or len(raw_workloads) != len(ROLES):
        raise IdentityAgentError("exactly three workloads are required")
    workloads = tuple(
        _load_workload(item, output_prefix=output_prefix, key_prefix=key_prefix)
        for item in raw_workloads
    )
    if {item.role for item in workloads} != ROLES:
        raise IdentityAgentError("api, ingestion, and backup roles must each appear once")
    return AgentConfig(ttl, interval, workloads)


def _sign(signing_input: bytes, private_key: Path) -> bytes:
    openssl = shutil.which("openssl")
    if not openssl:
        raise IdentityAgentError("openssl is required for RS256 signing")
    try:
        result = subprocess.run(
            [openssl, "dgst", "-sha256", "-sign", str(private_key)],
            input=signing_input,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode(errors="replace").strip()
        raise IdentityAgentError(f"openssl signing failed: {message}") from exc
    return result.stdout


def issue_token(workload: Workload, ttl_seconds: int, *, now: int | None = None) -> str:
    issued_at = int(time.time()) if now is None else now
    header = {"alg": "RS256", "kid": workload.kid, "typ": "JWT"}
    payload = {
        "iss": workload.issuer,
        "sub": workload.subject,
        "aud": workload.audience,
        "iat": issued_at,
        "nbf": issued_at - 5,
        "exp": issued_at + ttl_seconds,
        "jti": secrets.token_hex(16),
        "sclib_role": workload.role,
    }
    encoded_header = _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    encoded_payload = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    return f"{signing_input.decode()}.{_b64url(_sign(signing_input, workload.private_key))}"


def write_token(workload: Workload, token: str) -> None:
    workload.output.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    if os.geteuid() == 0:
        os.chown(workload.output.parent, 0, workload.gid)
    directory_stat = workload.output.parent.stat()
    if stat.S_IMODE(directory_stat.st_mode) != 0o750:
        raise IdentityAgentError("subject-token directory must have mode 0750")
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{workload.output.name}.",
        dir=workload.output.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o440)
        if os.geteuid() == 0:
            os.fchown(fd, 0, workload.gid)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, workload.output)
    finally:
        temporary.unlink(missing_ok=True)


def rotate_once(config: AgentConfig) -> None:
    now = int(time.time())
    for workload in config.workloads:
        write_token(workload, issue_token(workload, config.token_ttl_seconds, now=now))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("once", "run"))
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("/etc/sclib/identity-agent/config.json"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "once":
            rotate_once(config)
            return 0
        while True:
            rotate_once(config)
            time.sleep(config.interval_seconds)
    except (IdentityAgentError, OSError) as exc:
        print(f"identity agent failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
