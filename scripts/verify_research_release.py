"""Offline, bounded verifier for an internal research integrity capsule.

Bundle layout is canonical UTF-8 ``manifest.json`` (no trailing newline), plus
the exact declared ``<sha256>.bin`` leaves. An independently pinned manifest
digest is mandatory. No URI is fetched, no DB is read, and a passing result is
not publication permission, reviewer authentication, or ML label approval.
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

from services.research_release_manifest import (
    LIMITS,
    ResearchReleaseVerificationError,
    canonical,
    verify_manifest,
)

_LEAF = re.compile(r"^[0-9a-f]{64}\.bin$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


def _require(condition, message):
    if not condition:
        raise ResearchReleaseVerificationError(message)


def strict_json(payload):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ResearchReleaseVerificationError("nonfinite JSON number")

    try:
        result = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        canonical(result)  # validates depth, node budget, Unicode and 1e999
        return result
    except ResearchReleaseVerificationError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ResearchReleaseVerificationError("invalid or excessive JSON") from exc


def _directory_fd(path):
    _require(path.is_absolute() and ".." not in path.parts, "absolute non-traversing bundle path required")
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


def _inventory(descriptor):
    names = []
    with os.scandir(descriptor) as entries:
        for entry in entries:
            _require(len(names) <= LIMITS["artifacts"], "bundle inventory limit")
            _require(entry.name == "manifest.json" or _LEAF.fullmatch(entry.name), "unsafe or unknown bundle leaf")
            names.append(entry.name)
    _require("manifest.json" in names, "manifest missing")
    return sorted(names)


def _capture(path):
    _require(path.name == "manifest.json", "manifest must be named manifest.json")
    descriptor = _directory_fd(path.parent)
    payloads, signatures, inodes = {}, {}, set()
    total = 0
    try:
        names = _inventory(descriptor)
        for name in names:
            file_descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            try:
                before = os.fstat(file_descriptor)
                _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                         "bundle leaves must be regular files without aliases")
                identity = before.st_dev, before.st_ino
                _require(identity not in inodes, "bundle file identity alias")
                inodes.add(identity)
                _require(before.st_size <= LIMITS["file_bytes"], "bundle leaf byte limit")
                size, chunks = 0, []
                while True:
                    chunk = os.read(file_descriptor, min(1024 * 1024, LIMITS["file_bytes"] - size + 1))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    _require(size <= LIMITS["file_bytes"] and total + size <= LIMITS["combined_bytes"],
                             "bundle byte budget exceeded")
                after = os.fstat(file_descriptor)
                _require(_signature(before) == _signature(after) and size == before.st_size,
                         "bundle leaf changed during capture")
                total += size
                payloads[name] = b"".join(chunks)
                signatures[name] = _signature(after)
            finally:
                os.close(file_descriptor)
        _require(_inventory(descriptor) == names, "bundle inventory changed during capture")
    finally:
        os.close(descriptor)
    return payloads, signatures


def verify_research_release(*, manifest_path, expected_manifest_sha256):
    """Read immutable bounded byte copies, verify, then detect local drift."""
    try:
        _require(type(expected_manifest_sha256) is str and _HASH.fullmatch(expected_manifest_sha256),
                 "independently pinned lowercase SHA-256 required")
        path = Path(manifest_path)
        captured, signatures = _capture(path)
        payload = captured["manifest.json"]
        _require(hashlib.sha256(payload).hexdigest() == expected_manifest_sha256,
                 "pinned manifest byte digest mismatch")
        manifest = strict_json(payload)
        _require(payload == canonical(manifest), "manifest must use exact canonical JSON bytes")
        artifacts = {name[:-4]: value for name, value in captured.items() if name != "manifest.json"}
        result = verify_manifest(manifest, artifact_bytes=artifacts,
                                 expected_manifest_sha256=expected_manifest_sha256)
        # This detects local races, not a hostile kernel or filesystem attack.
        repeated, repeated_signatures = _capture(path)
        _require(repeated == captured and repeated_signatures == signatures,
                 "bundle changed during verification")
        return result
    except ResearchReleaseVerificationError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        raise ResearchReleaseVerificationError("bundle capture or verification failed") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    arguments = parser.parse_args(argv)
    try:
        result = verify_research_release(manifest_path=arguments.manifest,
                                         expected_manifest_sha256=arguments.expected_manifest_sha256)
    except ResearchReleaseVerificationError as exc:
        print(json.dumps({"integrity_verified": False, "error": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
