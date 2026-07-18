#!/usr/bin/env python3
"""Export the public half of an RSA signing key as a Google WIF JWKS."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def build_jwks(private_key: Path) -> tuple[str, dict[str, object]]:
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError("openssl is required")
    public_der = subprocess.run(
        [openssl, "pkey", "-in", str(private_key), "-pubout", "-outform", "DER"],
        capture_output=True,
        check=True,
    ).stdout
    modulus_output = subprocess.run(
        [openssl, "rsa", "-in", str(private_key), "-noout", "-modulus"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    prefix = "Modulus="
    if not modulus_output.startswith(prefix):
        raise RuntimeError("openssl did not return an RSA modulus")
    modulus = bytes.fromhex(modulus_output[len(prefix) :]).lstrip(b"\x00")
    kid = hashlib.sha256(public_der).hexdigest()
    jwks: dict[str, object] = {
        "keys": [
            {
                "alg": "RS256",
                "e": "AQAB",
                "kid": kid,
                "kty": "RSA",
                "n": _b64url(modulus),
                "use": "sig",
            }
        ]
    }
    return kid, jwks


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    kid, jwks = build_jwks(args.private_key)
    args.output.write_text(json.dumps(jwks, indent=2, sort_keys=True) + "\n")
    args.output.chmod(0o644)
    print(kid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
