"""Tests for the root-only rotating OIDC identity agent."""

from __future__ import annotations

import base64
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.export_identity_jwks import build_jwks
from scripts.sclib_identity_agent import (
    IdentityAgentError,
    issue_token,
    load_config,
    rotate_once,
)


def _decode(value: str) -> dict[str, object]:
    padded = value + "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


class IdentityAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.keys = self.root / "keys"
        self.tokens = self.root / "tokens"
        self.keys.mkdir()
        self.tokens.mkdir()
        self.config_path = self.root / "config.json"
        self.workloads = []
        for role in ("api", "ingestion", "backup"):
            key = self.keys / f"{role}.key"
            subprocess.run(
                [
                    "openssl",
                    "genpkey",
                    "-algorithm",
                    "RSA",
                    "-pkeyopt",
                    "rsa_keygen_bits:2048",
                    "-out",
                    str(key),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            key.chmod(0o600)
            kid, _ = build_jwks(key)
            self.workloads.append(
                {
                    "role": role,
                    "issuer": f"https://api.jzis.org/sclib-identity/{role}",
                    "subject": f"sclib-{role}-vps2",
                    "audience": (
                        "https://iam.googleapis.com/projects/123456789/locations/global/"
                        f"workloadIdentityPools/sclib-production/providers/vps2-{role}"
                    ),
                    "kid": kid,
                    "private_key": str(key),
                    "output": str(self.tokens / role / "subject.jwt"),
                    "gid": os.getgid(),
                }
            )
        self._write_config()

    def _write_config(self, **overrides: object) -> None:
        value = {
            "token_ttl_seconds": 300,
            "interval_seconds": 60,
            "workloads": self.workloads,
        }
        value.update(overrides)
        self.config_path.write_text(json.dumps(value))

    def _load(self):  # type annotation would expose a private implementation detail
        return load_config(
            self.config_path,
            output_prefix=self.tokens,
            key_prefix=self.keys,
        )

    def test_rotates_three_role_scoped_tokens_atomically(self) -> None:
        config = self._load()
        rotate_once(config)
        for workload in config.workloads:
            token = workload.output.read_text().strip()
            header_encoded, payload_encoded, signature_encoded = token.split(".")
            header = _decode(header_encoded)
            payload = _decode(payload_encoded)
            self.assertEqual(header["alg"], "RS256")
            self.assertEqual(header["kid"], workload.kid)
            self.assertEqual(payload["sub"], f"sclib-{workload.role}-vps2")
            self.assertEqual(payload["sclib_role"], workload.role)
            self.assertEqual(payload["aud"], workload.audience)
            self.assertEqual(payload["exp"] - payload["iat"], 300)
            self.assertEqual(stat.S_IMODE(workload.output.stat().st_mode), 0o440)

            public_key = self.root / f"{workload.role}.pub"
            subprocess.run(
                ["openssl", "pkey", "-in", str(workload.private_key), "-pubout", "-out", str(public_key)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            signature = self.root / f"{workload.role}.sig"
            signature.write_bytes(
                base64.urlsafe_b64decode(signature_encoded + "=" * (-len(signature_encoded) % 4))
            )
            verified = subprocess.run(
                [
                    "openssl",
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(public_key),
                    "-signature",
                    str(signature),
                ],
                input=f"{header_encoded}.{payload_encoded}".encode(),
                capture_output=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr.decode())

    def test_rejects_overlong_token_lifetime(self) -> None:
        self._write_config(token_ttl_seconds=3600)
        with self.assertRaisesRegex(IdentityAgentError, "between 120 and 600"):
            self._load()

    def test_rejects_group_readable_private_key(self) -> None:
        Path(self.workloads[0]["private_key"]).chmod(0o640)
        with self.assertRaisesRegex(IdentityAgentError, "mode 0600"):
            self._load()

    def test_rejects_role_provider_mismatch(self) -> None:
        self.workloads[0]["audience"] = self.workloads[0]["audience"].replace(
            "vps2-api", "vps2-backup"
        )
        self._write_config()
        with self.assertRaisesRegex(IdentityAgentError, "matching VPS2 WIF provider"):
            self._load()

    def test_issue_token_does_not_contain_private_material(self) -> None:
        workload = self._load().workloads[0]
        token = issue_token(workload, 300, now=1_800_000_000)
        self.assertNotIn("PRIVATE", token)
        self.assertEqual(_decode(token.split(".")[1])["exp"], 1_800_000_300)
