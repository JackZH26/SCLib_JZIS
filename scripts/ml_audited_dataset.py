#!/usr/bin/env python3
"""Offline, mandatory identity-audited ML packages; never scientific approval.

Five independently pinned inputs produce an unchanged v4 base and an additional
typed identity/leakage audit. Both technical gates must pass before writing a new
private file. No database, provider, training or publication operation is used.
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
from services.ml_audited_dataset import (
    MAX_BYTES,
    build_audited_task_dataset,
    canonical,
    digest,
    loads,
    verify_audited_task_dataset,
)
from services.research_release_manifest import canonical as capsule_canonical

from scripts.ml_current_dataset import read_label_companion
from scripts.ml_reviewed_dataset import read_review_companion
from scripts.ml_scientific_dataset import read_companion
from scripts.ml_task_dataset import read_json
from scripts.verify_research_release import (
    _capture,
    _directory_fd,
    _signature,
    strict_json,
)


class OutputStateUnknown(ValueError):
    """A filesystem publication/cleanup outcome needs independent inspection."""


def read_package(path, expected):
    """Capture a bounded no-alias package using its version-owned JSON parser."""
    require(type(expected) is str and HASH.fullmatch(expected), "independent package pin required")
    path = Path(path)
    require(path.name.endswith(".json"), "JSON package required")
    directory = _directory_fd(path.parent)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                    and before.st_size <= MAX_BYTES, "package must be bounded regular file without aliases")
            chunks, size = [], 0
            while True:
                chunk = os.read(descriptor, min(1024 * 1024, MAX_BYTES - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                require(size <= MAX_BYTES, "package byte limit")
                chunks.append(chunk)
            after = os.fstat(descriptor)
            require(before.st_size == size and _signature(before) == _signature(after),
                    "package changed during read")
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)
    payload = b"".join(chunks)
    require(hashlib.sha256(payload).hexdigest() == expected, "package file pin mismatch")
    return loads(payload), _signature(after)


def write_new_package(path, value, *, forbidden_directory):
    """No-clobber owner-only output; report uncertain post-link failures honestly."""
    path = Path(path)
    require(path.name.endswith(".json"), "JSON output required")
    payload = canonical(value)
    require(len(payload) <= MAX_BYTES, "package output byte limit")
    directory = _directory_fd(path.parent)
    temporary = ".ml-audited-" + uuid4().hex
    created = linked = False
    descriptor = original = None
    try:
        forbidden = _directory_fd(Path(forbidden_directory))
        try:
            actual_info, forbidden_info = os.fstat(directory), os.fstat(forbidden)
            require((actual_info.st_dev, actual_info.st_ino)
                    != (forbidden_info.st_dev, forbidden_info.st_ino),
                    "output cannot modify closed input capsule inventory")
        finally:
            os.close(forbidden)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        created = True
        # Keep the created inode alive until publication has been checked. A
        # replaced temporary name must not let inode reuse counterfeit ownership.
        original = os.fstat(descriptor)
        os.fchmod(descriptor, 0o600)
        pending = memoryview(payload)
        while pending:
            written = os.write(descriptor, pending)
            require(written > 0, "package output write failed")
            pending = pending[written:]
        os.fsync(descriptor)
        try:
            os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
            linked = True
        except FileExistsError:
            raise
        except OSError:
            # A failed syscall response is not proof that publication had no
            # effect. Do not automatically retry or assert output_written=False.
            raise OutputStateUnknown("output_state_unknown") from None
    finally:
        try:
            if created:
                try:
                    current = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
                    require(original is not None and (current.st_dev, current.st_ino)
                            == (original.st_dev, original.st_ino), "temporary ownership changed")
                    os.unlink(temporary, dir_fd=directory)
                except (OSError, ValueError):
                    # A replacement leaf is not ours to remove, even if it has
                    # identical bytes. Retain it for independent inspection.
                    raise OutputStateUnknown("output_state_unknown") from None
            if linked:
                try:
                    os.fsync(directory)
                    reopened = _directory_fd(path.parent)
                    try:
                        parent = os.fstat(reopened)
                        require((parent.st_dev, parent.st_ino)
                                == (actual_info.st_dev, actual_info.st_ino), "output parent changed")
                    finally:
                        os.close(reopened)
                    _, signature = read_package(path, hashlib.sha256(payload).hexdigest())
                    require(signature[:2] == (original.st_dev, original.st_ino)
                            and stat.S_IMODE(signature[2]) == 0o600, "published output identity changed")
                except (OSError, ValueError):
                    raise OutputStateUnknown("output_state_unknown") from None
        finally:
            try:
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        if linked:
                            raise OutputStateUnknown("output_state_unknown") from None
                        raise
            finally:
                try:
                    os.close(directory)
                except OSError:
                    if linked:
                        raise OutputStateUnknown("output_state_unknown") from None
                    raise


def run(*, mode, manifest_path, expected_manifest_sha256, companion_path, expected_companion_sha256,
        review_companion_path, expected_review_companion_sha256, label_companion_path,
        expected_label_companion_sha256, task_path, expected_task_sha256, output_path=None,
        bundle_path=None, expected_bundle_sha256=None):
    """Stable inputs plus mandatory base/audit gates, not an optional sidecar."""
    require(type(mode) is str and mode in {"build", "verify"}, "unsupported mode")
    require(type(expected_manifest_sha256) is str and HASH.fullmatch(expected_manifest_sha256),
            "capsule pin required")
    if mode == "build":
        require(output_path is not None and bundle_path is None and expected_bundle_sha256 is None,
                "build paths invalid")
    else:
        require(bundle_path is not None and output_path is None, "verify paths invalid")
    path = Path(manifest_path)
    capture, signatures = _capture(path)
    require(hashlib.sha256(capture["manifest.json"]).hexdigest() == expected_manifest_sha256,
            "capsule byte pin mismatch")
    manifest = strict_json(capture["manifest.json"])
    require(capsule_canonical(manifest) == capture["manifest.json"], "canonical capsule required")
    artifacts = {name[:-4]: payload for name, payload in capture.items() if name != "manifest.json"}
    task, task_signature = read_json(task_path, expected_task_sha256)
    companion, companion_signature = read_companion(companion_path, expected_companion_sha256)
    review, review_signature = read_review_companion(review_companion_path, expected_review_companion_sha256)
    label, label_signature = read_label_companion(label_companion_path, expected_label_companion_sha256)
    inputs = {
        "manifest": manifest, "artifact_bytes": artifacts, "expected_manifest_sha256": expected_manifest_sha256,
        "companion": companion, "expected_companion_sha256": expected_companion_sha256,
        "review_companion": review, "expected_review_companion_sha256": expected_review_companion_sha256,
        "label_companion": label, "expected_label_companion_sha256": expected_label_companion_sha256,
        "task": task, "expected_task_sha256": expected_task_sha256,
    }
    if mode == "build":
        package = build_audited_task_dataset(**inputs)
        base, audit = package["base_dataset"], package["identity_audit"]
        states = [package["gate"]["status"], base["gate"]["status"], audit["gate"]["status"]]
        require(all(state in {"pass", "no_go"} for state in states)
                and (states[0] == "pass") == all(state == "pass" for state in states[1:]),
                "mandatory aggregate gate mismatch")
        report = {
            "version": package["version"], "technical_gate": states[0],
            "base_technical_gate": states[1], "identity_technical_gate": states[2],
            "gate_reason_codes": package["gate"]["reason_codes"],
            "package_sha256": digest(package), "base_dataset_sha256": package["base_dataset_sha256"],
            "identity_audit_sha256": package["identity_audit_sha256"],
            "audit_policy_version": package["audit_policy_version"], "coverage": base["coverage"],
            "review_observation_sha256": base["input_pins"]["review_observation_sha256"],
            "label_observation_sha256": base["input_pins"]["label_observation_sha256"],
            "identity_scope": "captured_identity_integrity_not_scientific_independence",
            "independent_support_count": None, **package["authority"],
        }
    else:
        package, package_signature = read_package(bundle_path, expected_bundle_sha256)
        report = verify_audited_task_dataset(package, **inputs, expected_package_sha256=expected_bundle_sha256)
    require(_capture(path) == (capture, signatures), "capsule changed during compilation")
    require(read_json(task_path, expected_task_sha256) == (task, task_signature), "task changed during compilation")
    require(read_companion(companion_path, expected_companion_sha256) == (companion, companion_signature),
            "source companion changed during compilation")
    require(read_review_companion(review_companion_path, expected_review_companion_sha256) == (review, review_signature),
            "review companion changed during compilation")
    require(read_label_companion(label_companion_path, expected_label_companion_sha256) == (label, label_signature),
            "label companion changed during compilation")
    if mode == "verify":
        require(read_package(bundle_path, expected_bundle_sha256) == (package, package_signature),
                "package changed during verification")
    should_write = mode == "build" and package["gate"]["status"] == "pass"
    if should_write:
        write_new_package(output_path, package, forbidden_directory=path.parent)
    report["output_written"] = should_write
    return report


class _SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("invalid arguments")


def main(argv=None):
    parser = _SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("mode", choices=["build", "verify"])
    for field in ("manifest", "manifest-sha256", "companion", "companion-sha256", "review-companion",
                  "review-companion-sha256", "label-companion", "label-companion-sha256", "task", "task-sha256"):
        parser.add_argument("--" + field, required=True)
    for field in ("output", "bundle", "bundle-sha256"):
        parser.add_argument("--" + field)
    try:
        args = parser.parse_args(argv)
        report = run(mode=args.mode, manifest_path=args.manifest, expected_manifest_sha256=args.manifest_sha256,
            companion_path=args.companion, expected_companion_sha256=args.companion_sha256,
            review_companion_path=args.review_companion, expected_review_companion_sha256=args.review_companion_sha256,
            label_companion_path=args.label_companion, expected_label_companion_sha256=args.label_companion_sha256,
            task_path=args.task, expected_task_sha256=args.task_sha256, output_path=args.output,
            bundle_path=args.bundle, expected_bundle_sha256=args.bundle_sha256)
    except OutputStateUnknown:
        print('{"status":"output_state_unknown","output_written":null}', file=sys.stderr)
        return 2
    except (ValueError, OSError, TypeError, KeyError, RecursionError):
        print('{"status":"invalid","output_written":false}', file=sys.stderr)
        return 2
    print(canonical(report).decode())
    return 0 if report["technical_gate"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
