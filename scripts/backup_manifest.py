#!/usr/bin/env python3
"""Create and verify the integrity manifest paired with a PostgreSQL dump."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 1
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """The manifest is malformed or does not match its backup artifact."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_manifest(
    dump: Path,
    *,
    postgres_version: str,
    git_sha: str,
    created_at: Optional[str] = None,  # noqa: UP045 - VPS host Python may be 3.10
) -> dict[str, Any]:
    if not dump.is_file() or dump.stat().st_size == 0:
        raise ManifestError("backup dump must be a non-empty regular file")
    if not re.fullmatch(r"[0-9a-f]{40}", git_sha):
        raise ManifestError("git_sha must be a full 40-character commit SHA")
    return {
        "schema_version": SCHEMA_VERSION,
        # datetime.UTC is unavailable on the supported Ubuntu 22.04 host Python.
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        "source": {
            "database": "sclib",
            "postgres_version": postgres_version.strip(),
            "git_sha": git_sha,
        },
        "artifact": {
            "filename": dump.name,
            "format": "postgres-custom",
            "bytes": dump.stat().st_size,
            "sha256": file_sha256(dump),
        },
    }


def verify_manifest(dump: Path, manifest: Path) -> dict[str, Any]:
    try:
        payload = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read backup manifest: {exc}") from exc
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError("unsupported backup manifest schema")
    artifact = payload.get("artifact")
    source = payload.get("source")
    if not isinstance(artifact, dict) or not isinstance(source, dict):
        raise ManifestError("manifest source/artifact sections are required")
    expected_sha = artifact.get("sha256")
    if not isinstance(expected_sha, str) or not SHA256_PATTERN.fullmatch(expected_sha):
        raise ManifestError("manifest sha256 is invalid")
    if artifact.get("format") != "postgres-custom":
        raise ManifestError("manifest artifact format is not postgres-custom")
    if artifact.get("filename") != dump.name:
        raise ManifestError("manifest filename does not match dump")
    if artifact.get("bytes") != dump.stat().st_size:
        raise ManifestError("manifest byte count does not match dump")
    if file_sha256(dump) != expected_sha:
        raise ManifestError("manifest checksum does not match dump")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    create = subcommands.add_parser("create")
    create.add_argument("--dump", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--postgres-version", required=True)
    create.add_argument("--git-sha", required=True)
    verify = subcommands.add_parser("verify")
    verify.add_argument("--dump", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "create":
            payload = create_manifest(
                args.dump,
                postgres_version=args.postgres_version,
                git_sha=args.git_sha,
            )
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            os.replace(temporary, args.output)
            print(payload["artifact"]["sha256"])
        else:
            payload = verify_manifest(args.dump, args.manifest)
            print(payload["artifact"]["sha256"])
    except (ManifestError, OSError) as exc:
        print(f"backup manifest error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
