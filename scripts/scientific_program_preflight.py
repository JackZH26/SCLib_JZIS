#!/usr/bin/env python3
"""Inspect a pinned scientific-program package offline; never run its code.

An exact manifest.json plus declared <sha256>.bin files form a private capsule.
The optional output is a new owner-only audit report, not an approved result or
database write. Context/rights/version declarations never become verified facts.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT))

from services.research_release_manifest import canonical, digest
from services.scientific_program_import import (
    HASH,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_MANIFEST_BYTES,
    MAX_PACKAGE_BYTES,
    build_preflight,
    require,
)

from scripts.verify_research_release import _directory_fd, _signature, strict_json

_LEAF = re.compile(r"^[0-9a-f]{64}\.bin$")


def _inventory(directory):
    names = []
    with os.scandir(directory) as entries:
        for entry in entries:
            require(len(names) < MAX_FILES + 1, "package_inventory_limit")
            require(entry.name == "manifest.json" or _LEAF.fullmatch(entry.name), "package_unknown_leaf")
            names.append(entry.name)
    require("manifest.json" in names, "package_manifest_missing")
    return sorted(names)


def capture_package(path):
    path = Path(path)
    require(path.name == "manifest.json", "package_manifest_name_required")
    directory = _directory_fd(path.parent)
    captured, signatures, identities, total = {}, {}, set(), 0
    try:
        inventory = _inventory(directory)
        for name in inventory:
            limit = MAX_MANIFEST_BYTES if name == "manifest.json" else MAX_FILE_BYTES
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                before = os.fstat(descriptor)
                require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                        "package_regular_unaliased_files_required")
                require((before.st_dev, before.st_ino) not in identities, "package_file_identity_alias")
                identities.add((before.st_dev, before.st_ino))
                require(before.st_size <= limit and total + before.st_size <= MAX_PACKAGE_BYTES,
                        "package_byte_limit")
                chunks, size = [], 0
                while True:
                    chunk = os.read(descriptor, min(65536, limit - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    require(size <= limit and total + size <= MAX_PACKAGE_BYTES, "package_byte_limit")
                    chunks.append(chunk)
                after = os.fstat(descriptor)
                require(_signature(before) == _signature(after) and before.st_size == size,
                        "package_file_changed_during_capture")
                captured[name] = b"".join(chunks)
                signatures[name] = _signature(after)
                total += size
            finally:
                os.close(descriptor)
        require(_inventory(directory) == inventory, "package_inventory_changed")
    finally:
        os.close(directory)
    return captured, signatures


def write_new_report(path, report, *, forbidden_identity):
    """Same-directory exclusive publish; failed writes cannot replace user files."""
    path = Path(path)
    require(path.name.endswith(".json"), "json_report_required")
    data = canonical(report)
    require(len(data) <= MAX_PACKAGE_BYTES, "preflight_report_byte_limit")
    directory = _directory_fd(path.parent)
    temporary, created = ".scientific-preflight-" + uuid4().hex, False
    try:
        current = os.fstat(directory)
        # The caller retains the original source directory FD until publication.
        # Reopening its old pathname here would allow rename-and-replace races
        # to publish a report into the captured capsule at a different path.
        require((current.st_dev, current.st_ino) != forbidden_identity,
                "report_cannot_modify_input_capsule")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        created = True
        try:
            remaining = memoryview(data)
            while remaining:
                written = os.write(descriptor, remaining)
                require(written > 0, "report_write_failed")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    finally:
        if created:
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)


def run(*, manifest_path, expected_manifest_sha256, output_path=None):
    require(type(expected_manifest_sha256) is str and HASH.fullmatch(expected_manifest_sha256),
            "independent_package_pin_required")
    path = Path(manifest_path)
    source = _directory_fd(path.parent)
    try:
        source_stat = os.fstat(source)
        source_identity = source_stat.st_dev, source_stat.st_ino
        captured, signatures = capture_package(path)
        payload = captured["manifest.json"]
        require(hashlib.sha256(payload).hexdigest() == expected_manifest_sha256, "package_manifest_pin_mismatch")
        manifest = strict_json(payload)
        require(canonical(manifest) == payload, "canonical_package_manifest_required")
        report = build_preflight(manifest, expected_manifest_sha256=expected_manifest_sha256,
            artifact_bytes={name[:-4]: value for name, value in captured.items() if name != "manifest.json"})
        require(capture_package(path) == (captured, signatures), "package_changed_during_preflight")
        current = _directory_fd(path.parent)
        try:
            info = os.fstat(current)
            require((info.st_dev, info.st_ino) == source_identity, "package_directory_changed")
        finally:
            os.close(current)
        if output_path is not None:
            write_new_report(output_path, report, forbidden_identity=source_identity)
        return report
    finally:
        os.close(source)


class _SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("invalid_arguments")


def main(argv=None):
    parser = _SafeParser(description=__doc__, allow_abbrev=False)
    for field in ("manifest", "manifest-sha256"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--output")
    try:
        args = parser.parse_args(argv)
        report = run(manifest_path=args.manifest, expected_manifest_sha256=args.manifest_sha256,
                     output_path=args.output)
    except (ValueError, OSError, TypeError, OverflowError, RecursionError):
        print('{"status":"invalid","output_written":false}', file=sys.stderr)
        return 2
    print(canonical({"status": report["status"], "report_sha256": digest(report),
                     "output_written": args.output is not None, "authority": report["authority"]}).decode())
    return 0 if report["status"] == "parsed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
