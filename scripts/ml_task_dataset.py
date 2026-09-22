#!/usr/bin/env python3
"""Bounded offline build/verify for restricted task datasets, never publication.

Use the matching repository revision and locked API interpreter. Input digests
must arrive independently, not be trusted merely because this tool prints them.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from models.ml_task import HASH, require
from services.ml_dataset_builder import build_task_dataset, verify_task_dataset
from services.research_release_manifest import LIMITS, canonical, digest

from scripts.verify_research_release import (
    _capture,
    _directory_fd,
    _signature,
    strict_json,
)


def read_json(path, expected):
    require(type(expected) is str and HASH.fullmatch(expected), "independent JSON pin required")
    path = Path(path)
    require(path.name.endswith(".json"), "JSON file required")
    directory = _directory_fd(path.parent)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= LIMITS["file_bytes"],
                    "JSON must be a bounded regular file without aliases")
            chunks, size = [], 0
            while True:
                chunk = os.read(descriptor, min(1024 * 1024, LIMITS["file_bytes"] - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                require(size <= LIMITS["file_bytes"], "JSON byte limit")
                chunks.append(chunk)
            after = os.fstat(descriptor)
            require(_signature(before) == _signature(after) and before.st_size == size, "JSON changed during read")
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)
    payload = b"".join(chunks)
    require(hashlib.sha256(payload).hexdigest() == expected, "JSON byte pin mismatch")
    value = strict_json(payload)
    require(payload == canonical(value), "exact canonical JSON required")
    return value, _signature(after)


def write_new_json(path, value, *, forbidden_directory=None):
    """Atomically link an owner-only new file; never replace an existing path."""
    path = Path(path)
    require(path.name.endswith(".json"), "JSON output required")
    payload = canonical(value)
    require(len(payload) <= LIMITS["file_bytes"], "output byte limit")
    directory = _directory_fd(path.parent)
    temporary = ".ml-task-" + uuid4().hex
    created = False
    try:
        if forbidden_directory is not None:
            forbidden_fd = _directory_fd(Path(forbidden_directory))
            try:
                current, forbidden = os.fstat(directory), os.fstat(forbidden_fd)
                require((current.st_dev, current.st_ino) != (forbidden.st_dev, forbidden.st_ino),
                        "output cannot modify closed input capsule inventory")
            finally:
                os.close(forbidden_fd)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        created = True
        try:
            pending = memoryview(payload)
            while pending:
                size = os.write(descriptor, pending)
                require(size > 0, "output write failed")
                pending = pending[size:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    finally:
        if created:
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)


def run(*, mode, manifest_path, expected_manifest_sha256, task_path, expected_task_sha256,
        output_path=None, bundle_path=None, expected_bundle_sha256=None):
    require(type(mode) is str and mode in {"build", "verify"}, "unsupported mode")
    require(type(expected_manifest_sha256) is str and HASH.fullmatch(expected_manifest_sha256), "capsule pin required")
    path = Path(manifest_path)
    capture, signatures = _capture(path)
    require(hashlib.sha256(capture["manifest.json"]).hexdigest() == expected_manifest_sha256, "capsule byte pin mismatch")
    manifest = strict_json(capture["manifest.json"])
    require(capture["manifest.json"] == canonical(manifest), "canonical capsule required")
    artifacts = {name[:-4]: payload for name, payload in capture.items() if name != "manifest.json"}
    task, task_signature = read_json(task_path, expected_task_sha256)
    arguments = dict(manifest=manifest, artifact_bytes=artifacts, expected_manifest_sha256=expected_manifest_sha256,
                     task=task, expected_task_sha256=expected_task_sha256)
    if mode == "build":
        require(output_path is not None and bundle_path is None and expected_bundle_sha256 is None, "build paths invalid")
        bundle = build_task_dataset(**arguments)
        report = {"version": bundle["version"], "technical_gate": bundle["gate"]["status"],
                  "gate_reason_codes": bundle["gate"]["reason_codes"], "coverage": bundle["coverage"],
                  "bundle_sha256": digest(bundle), **bundle["authority"]}
    else:
        require(bundle_path is not None and output_path is None, "verify paths invalid")
        bundle, bundle_signature = read_json(bundle_path, expected_bundle_sha256)
        report = verify_task_dataset(bundle, **arguments, expected_bundle_sha256=expected_bundle_sha256)
        require(read_json(bundle_path, expected_bundle_sha256) == (bundle, bundle_signature), "bundle changed during verification")
    require(_capture(path) == (capture, signatures), "capsule changed during compilation")
    require(read_json(task_path, expected_task_sha256) == (task, task_signature), "task changed during compilation")
    if mode == "build" and bundle["gate"]["status"] == "pass":
        write_new_json(output_path, bundle, forbidden_directory=path.parent)
    report["output_written"] = mode == "build" and bundle["gate"]["status"] == "pass"
    return report


class _SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("invalid arguments")


def main(argv=None):
    parser = _SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("mode", choices=["build", "verify"])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--task-sha256", required=True)
    parser.add_argument("--output")
    parser.add_argument("--bundle")
    parser.add_argument("--bundle-sha256")
    try:
        args = parser.parse_args(argv)
        report = run(mode=args.mode, manifest_path=args.manifest, expected_manifest_sha256=args.manifest_sha256,
            task_path=args.task, expected_task_sha256=args.task_sha256, output_path=args.output,
            bundle_path=args.bundle, expected_bundle_sha256=args.bundle_sha256)
    except (ValueError, OSError):
        # Do not echo source content, filesystem paths, or uncaught provider text.
        print('{"status":"invalid","output_written":false}', file=sys.stderr)
        return 2
    print(canonical(report).decode())
    return 0 if report["technical_gate"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
