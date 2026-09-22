"""Verify one metadata-only public research document against a trusted hash.

Only the named regular file is read. No database, network, external URI, source
capsule, license record or artifact is opened. Passing verifies the bounded
public schema and pinned bytes, not reviewer identity, rights or live access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API_ROOT))

from services.research_public_contract import (
    LIMITS,
    PublicResearchVerificationError,
    verify_public_document,
)
from services.research_release_manifest import (
    ResearchReleaseVerificationError,
    canonical,
)

_HASH = re.compile(r"^[0-9a-f]{64}$")


def _require(condition, message):
    if not condition:
        raise PublicResearchVerificationError(message)


def _strict_json(payload):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise PublicResearchVerificationError("nonfinite JSON number")

    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        canonical(document)
        return document
    except PublicResearchVerificationError:
        raise
    except (ResearchReleaseVerificationError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise PublicResearchVerificationError("invalid or excessive JSON") from exc


def _directory_fd(path):
    _require(path.is_absolute() and ".." not in path.parts, "absolute non-traversing document path required")
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _capture(path):
    _require(path.name == "public-manifest.json", "document must be named public-manifest.json")
    directory = _directory_fd(path.parent)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                     "public document must be a regular file without aliases")
            _require(before.st_size <= LIMITS["file_bytes"], "public document byte limit")
            size, chunks = 0, []
            while True:
                chunk = os.read(descriptor, min(1024 * 1024, LIMITS["file_bytes"] - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                _require(size <= LIMITS["file_bytes"], "public document byte limit")
                chunks.append(chunk)
            after = os.fstat(descriptor)
            _require(_signature(before) == _signature(after) and size == before.st_size,
                     "public document changed during capture")
            return b"".join(chunks), _signature(after)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def verify_public_research_release(*, manifest_path, expected_public_sha256):
    """Capture bounded immutable bytes twice and validate the exact public schema."""
    try:
        _require(type(expected_public_sha256) is str and _HASH.fullmatch(expected_public_sha256),
                 "independently pinned lowercase public SHA-256 required")
        path = Path(manifest_path)
        payload, signature = _capture(path)
        _require(hashlib.sha256(payload).hexdigest() == expected_public_sha256,
                 "pinned public document byte digest mismatch")
        document = _strict_json(payload)
        _require(payload == canonical(document), "public document must use exact canonical JSON bytes")
        result = verify_public_document(document, expected_public_sha256=expected_public_sha256)
        repeated, repeated_signature = _capture(path)
        _require(repeated == payload and repeated_signature == signature,
                 "public document changed during verification")
        return result
    except PublicResearchVerificationError:
        raise
    except (OSError, ResearchReleaseVerificationError, ValueError, TypeError, KeyError,
            AttributeError, RecursionError, OverflowError) as exc:
        raise PublicResearchVerificationError("public document capture or verification failed") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-public-sha256", required=True)
    arguments = parser.parse_args(argv)
    try:
        result = verify_public_research_release(manifest_path=arguments.manifest,
                                                expected_public_sha256=arguments.expected_public_sha256)
    except PublicResearchVerificationError as exc:
        print(json.dumps({"integrity_verified": False, "error": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
