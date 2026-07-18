#!/usr/bin/env python3
"""Enforce keyless, workload-scoped Google external-account credentials."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

FORBIDDEN_KEYS = {"client_secret", "private_key", "refresh_token"}
AUDIENCE_PATTERN = re.compile(
    r"^//iam\.googleapis\.com/projects/[0-9]+/locations/global/"
    r"workloadIdentityPools/[a-z0-9-]+/providers/[a-z0-9-]+$"
)


class CredentialPolicyError(ValueError):
    """A credential would expose a long-lived or incorrectly scoped identity."""


def _reject_long_lived_credentials(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_KEYS:
                raise CredentialPolicyError(f"forbidden long-lived field at {child_path}")
            if key == "type" and child == "authorized_user":
                raise CredentialPolicyError(f"authorized_user credential at {path}")
            _reject_long_lived_credentials(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_long_lived_credentials(child, f"{path}[{index}]")


def _service_account_from_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "iamcredentials.googleapis.com":
        raise CredentialPolicyError("service-account impersonation must use Google IAM HTTPS")
    match = re.fullmatch(
        r"/v1/projects/-/serviceAccounts/(.+):generateAccessToken",
        parsed.path,
    )
    if not match:
        raise CredentialPolicyError("service-account impersonation URL is malformed")
    return unquote(match.group(1))


def _decode_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parts = token.split(".")
    if len(parts) != 3:
        raise CredentialPolicyError("subject token must be a compact JWT")
    try:
        encoded = []
        for part in parts[:2]:
            padded = part + "=" * (-len(part) % 4)
            encoded.append(json.loads(base64.urlsafe_b64decode(padded)))
    except (ValueError, json.JSONDecodeError) as exc:
        raise CredentialPolicyError("subject token JWT header or payload is invalid") from exc
    header, payload = encoded
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise CredentialPolicyError("subject token JWT header and payload must be objects")
    if (
        header.get("alg") != "RS256"
        or header.get("typ") != "JWT"
        or not isinstance(header.get("kid"), str)
        or not re.fullmatch(r"[a-f0-9]{32,64}", header["kid"])
    ):
        raise CredentialPolicyError("subject token must use a fingerprinted RS256 key")
    return header, payload


def validate_subject_token(
    path: Path,
    allowed_prefix: Path,
    *,
    audience: str,
    expected_role: str,
) -> None:
    try:
        resolved = path.resolve(strict=True)
        prefix = allowed_prefix.resolve(strict=True)
        resolved.relative_to(prefix)
    except (OSError, ValueError) as exc:
        raise CredentialPolicyError(
            "subject token must exist under the dedicated identity runtime directory"
        ) from exc
    if not resolved.is_file() or not 0 < resolved.stat().st_size <= 65_536:
        raise CredentialPolicyError("subject token must be a non-empty regular file <=64 KiB")
    _, payload = _decode_jwt(resolved.read_text().strip())
    now = time.time()
    expires_at = payload.get("exp")
    issued_at = payload.get("iat")
    not_before = payload.get("nbf")
    if not isinstance(expires_at, (int, float)) or expires_at <= now + 60:  # noqa: UP038
        raise CredentialPolicyError("subject token is expired or expires within 60 seconds")
    if not isinstance(issued_at, (int, float)) or not isinstance(  # noqa: UP038
        not_before, (int, float)  # noqa: UP038
    ):
        raise CredentialPolicyError("subject token requires issued-at and not-before claims")
    if issued_at > now + 30 or not_before > now + 30 or expires_at - issued_at > 600:
        raise CredentialPolicyError("subject token timing exceeds the short-lived policy")
    expected_issuer = f"https://api.jzis.org/sclib-identity/{expected_role}"
    expected_subject = f"sclib-{expected_role}-vps2"
    expected_audience = f"https:{audience}"
    if payload.get("iss") != expected_issuer:
        raise CredentialPolicyError("subject token issuer does not match the workload role")
    if payload.get("sub") != expected_subject:
        raise CredentialPolicyError("subject token subject does not match the workload role")
    if payload.get("sclib_role") != expected_role:
        raise CredentialPolicyError("subject token role claim does not match the workload")
    if payload.get("aud") != expected_audience:
        raise CredentialPolicyError("subject token audience does not match the credential")


def validate_external_account(
    credential: Path,
    *,
    expected_service_account: str,
    check_subject_token: bool,
    token_prefix: Path,
) -> dict[str, Any]:
    try:
        payload = json.loads(credential.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CredentialPolicyError(f"cannot read credential configuration: {exc}") from exc
    if not isinstance(payload, dict):
        raise CredentialPolicyError("credential configuration must be a JSON object")
    _reject_long_lived_credentials(payload)
    if payload.get("type") != "external_account":
        raise CredentialPolicyError("production credential type must be external_account")
    audience = payload.get("audience")
    if not isinstance(audience, str) or not AUDIENCE_PATTERN.fullmatch(audience):
        raise CredentialPolicyError("credential audience is not a workload identity provider")
    if payload.get("token_url") != "https://sts.googleapis.com/v1/token":
        raise CredentialPolicyError("credential token_url must use Google STS HTTPS")
    if payload.get("subject_token_type") != "urn:ietf:params:oauth:token-type:jwt":
        raise CredentialPolicyError("credential subject_token_type must be JWT")
    impersonation_url = payload.get("service_account_impersonation_url")
    if not isinstance(impersonation_url, str):
        raise CredentialPolicyError("service-account impersonation URL is required")
    actual_service_account = _service_account_from_url(impersonation_url)
    if actual_service_account != expected_service_account:
        raise CredentialPolicyError(
            f"credential impersonates {actual_service_account}, expected {expected_service_account}"
        )
    role_match = re.fullmatch(
        r"sclib-(api|ingestion|backup)@jzis-sclib\.iam\.gserviceaccount\.com",
        expected_service_account,
    )
    if not role_match:
        raise CredentialPolicyError("expected service account is not a production SCLib workload")
    source = payload.get("credential_source")
    if not isinstance(source, dict) or set(source) - {"file", "format"}:
        raise CredentialPolicyError("credential_source must use only a rotating token file")
    source_file = source.get("file")
    source_format = source.get("format", {"type": "text"})
    if not isinstance(source_file, str) or not Path(source_file).is_absolute():
        raise CredentialPolicyError("credential_source.file must be an absolute path")
    if source_format != {"type": "text"}:
        raise CredentialPolicyError("credential source must contain a text JWT")
    if check_subject_token:
        validate_subject_token(
            Path(source_file),
            token_prefix,
            audience=audience,
            expected_role=role_match.group(1),
        )
    return payload


def _add_policy_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--credential",
        type=Path,
        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        required="GOOGLE_APPLICATION_CREDENTIALS" not in os.environ,
    )
    parser.add_argument(
        "--expected-service-account",
        default=os.environ.get("SCLIB_EXPECTED_GCP_SERVICE_ACCOUNT"),
        required="SCLIB_EXPECTED_GCP_SERVICE_ACCOUNT" not in os.environ,
    )
    parser.add_argument(
        "--token-prefix",
        type=Path,
        default=Path(os.environ.get("SCLIB_IDENTITY_TOKEN_PREFIX", "/var/run/sclib-identity")),
    )
    parser.add_argument("--skip-subject-token-check", action="store_true")


def parse_args(
    argv: Optional[list[str]] = None,  # noqa: UP045 - VPS host Python may be 3.10
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command_name", required=True)
    validate = subcommands.add_parser("validate")
    _add_policy_arguments(validate)
    execute = subcommands.add_parser("exec")
    _add_policy_arguments(execute)
    execute.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:  # noqa: UP045 - host Python 3.10
    args = parse_args(argv)
    try:
        validate_external_account(
            args.credential,
            expected_service_account=args.expected_service_account,
            check_subject_token=not args.skip_subject_token_check,
            token_prefix=args.token_prefix,
        )
    except CredentialPolicyError as exc:
        print(f"credential policy violation: {exc}", file=sys.stderr)
        return 1
    print(f"credential policy passed for {args.expected_service_account}")
    if args.command_name == "exec":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            print("credential exec requires a command", file=sys.stderr)
            return 2
        os.execvp(command[0], command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
