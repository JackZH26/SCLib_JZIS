"""Security-policy tests for keyless Google workload credentials."""

from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path

from scripts.validate_gcp_credentials import (
    CredentialPolicyError,
    parse_args,
    validate_external_account,
)

SERVICE_ACCOUNT = "sclib-api@jzis-sclib.iam.gserviceaccount.com"


def _jwt(payload: dict[str, object]) -> str:
    def encode(value: dict[str, object]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return (
        f"{encode({'alg': 'RS256', 'kid': 'a' * 64, 'typ': 'JWT'})}."
        f"{encode(payload)}.test-signature"
    )


class CredentialPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.token_dir = self.root / "api"
        self.token_dir.mkdir()
        self.token = self.token_dir / "subject.jwt"
        self.token.write_text(
            _jwt(
                {
                    "iss": "https://api.jzis.org/sclib-identity/api",
                    "sub": "sclib-api-vps2",
                    "aud": (
                        "https://iam.googleapis.com/projects/123456789/locations/global/"
                        "workloadIdentityPools/sclib-production/providers/vps2-api"
                    ),
                    "iat": int(time.time()),
                    "nbf": int(time.time()) - 5,
                    "exp": int(time.time()) + 600,
                    "sclib_role": "api",
                }
            )
        )
        self.credential = self.root / "external-account.json"

    def _payload(self) -> dict[str, object]:
        return {
            "type": "external_account",
            "audience": (
                "//iam.googleapis.com/projects/123456789/locations/global/"
                "workloadIdentityPools/sclib-production/providers/vps2-api"
            ),
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "token_url": "https://sts.googleapis.com/v1/token",
            "service_account_impersonation_url": (
                "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
                f"{SERVICE_ACCOUNT}:generateAccessToken"
            ),
            "credential_source": {
                "file": str(self.token),
                "format": {"type": "text"},
            },
        }

    def _validate(self, payload: dict[str, object]) -> dict[str, object]:
        self.credential.write_text(json.dumps(payload))
        return validate_external_account(
            self.credential,
            expected_service_account=SERVICE_ACCOUNT,
            check_subject_token=True,
            token_prefix=self.root,
        )

    def test_valid_rotating_external_account_is_accepted(self) -> None:
        self.assertEqual(self._validate(self._payload())["type"], "external_account")

    def test_nested_authorized_user_refresh_token_is_rejected(self) -> None:
        payload = self._payload()
        payload["source_credentials"] = {
            "type": "authorized_user",
            "refresh_token": "never-allowed",
        }
        with self.assertRaisesRegex(CredentialPolicyError, "authorized_user|refresh_token"):
            self._validate(payload)

    def test_wrong_service_account_is_rejected(self) -> None:
        payload = self._payload()
        payload["service_account_impersonation_url"] = (
            "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
            "sclib-ingestion@jzis-sclib.iam.gserviceaccount.com:generateAccessToken"
        )
        with self.assertRaisesRegex(CredentialPolicyError, "expected"):
            self._validate(payload)

    def test_expired_subject_token_is_rejected(self) -> None:
        self.token.write_text(
            _jwt(
                {
                    "iss": "https://api.jzis.org/sclib-identity/api",
                    "sub": "sclib-api-vps2",
                    "aud": (
                        "https://iam.googleapis.com/projects/123456789/locations/global/"
                        "workloadIdentityPools/sclib-production/providers/vps2-api"
                    ),
                    "iat": int(time.time()) - 700,
                    "nbf": int(time.time()) - 705,
                    "exp": int(time.time()) - 1,
                    "sclib_role": "api",
                }
            )
        )
        with self.assertRaisesRegex(CredentialPolicyError, "expired"):
            self._validate(self._payload())

    def test_executable_or_url_credential_source_is_rejected(self) -> None:
        payload = self._payload()
        payload["credential_source"] = {"executable": {"command": "curl attacker"}}
        with self.assertRaisesRegex(CredentialPolicyError, "rotating token file"):
            self._validate(payload)

    def test_exec_wrapper_preserves_container_command(self) -> None:
        args = parse_args(
            [
                "exec",
                "--credential",
                str(self.credential),
                "--expected-service-account",
                SERVICE_ACCOUNT,
                "--",
                "/app/entrypoint.sh",
                "uvicorn",
            ]
        )
        self.assertEqual(args.command, ["--", "/app/entrypoint.sh", "uvicorn"])

    def test_production_compose_separates_every_workload_identity(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        compose = (repository / "docker-compose.prod.yml").read_text()
        deploy = (repository / ".github" / "workflows" / "deploy.yml").read_text()
        backup = (repository / "scripts" / "backup_postgres.sh").read_text()
        for role in ("api", "ingestion", "backup"):
            self.assertIn(f"{role}-external-account.json", compose + deploy + backup)
            self.assertIn(f"sclib-{role}@jzis-sclib.iam.gserviceaccount.com", compose + deploy + backup)
        self.assertNotIn("application_default_credentials", compose)
        self.assertNotIn("gcp-sa.json", compose)
        self.assertIn("validate_gcp_credentials.py", deploy)
        self.assertIn("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", backup)
