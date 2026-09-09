#!/usr/bin/env python3
"""Offline build/verify of separately pinned review-aware v3 datasets.

Use the locked API interpreter. Every input SHA-256 is an independently supplied
canonical whole-file pin. A captured negative-only review observation is not a
current authorization, authenticated reviewer identity, or permission to train,
publish, or redistribute source material. No network or DB connection is made.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from models.ml_task import HASH, require
from services.ml_dataset_builder_v3 import build_task_dataset_v3, verify_task_dataset_v3
from services.ml_feature_review_companion import MAX_BYTES as MAX_REVIEW_BYTES
from services.research_release_manifest import canonical, digest

from scripts.ml_scientific_dataset import read_companion
from scripts.ml_task_dataset import read_json, write_new_json
from scripts.verify_research_release import (
    _capture,
    _directory_fd,
    _signature,
    strict_json,
)


def read_review_companion(path, expected):
    """Bounded 16 MiB observation capture without widening frozen v1 readers."""
    require(
        type(expected) is str and HASH.fullmatch(expected),
        "independent review file pin required",
    )
    path = Path(path)
    require(path.name.endswith(".json"), "JSON review companion required")
    directory = _directory_fd(path.parent)
    try:
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        try:
            before = os.fstat(descriptor)
            require(
                stat.S_ISREG(before.st_mode)
                and before.st_nlink == 1
                and before.st_size <= MAX_REVIEW_BYTES,
                "review companion must be bounded regular file without aliases",
            )
            chunks, size = [], 0
            while True:
                chunk = os.read(
                    descriptor, min(1024 * 1024, MAX_REVIEW_BYTES - size + 1)
                )
                if not chunk:
                    break
                size += len(chunk)
                require(size <= MAX_REVIEW_BYTES, "review companion byte limit")
                chunks.append(chunk)
            after = os.fstat(descriptor)
            require(
                before.st_size == size and _signature(before) == _signature(after),
                "review companion changed during read",
            )
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)
    payload = b"".join(chunks)
    require(
        hashlib.sha256(payload).hexdigest() == expected,
        "review companion file pin mismatch",
    )
    value = strict_json(payload)
    require(canonical(value) == payload, "canonical review companion required")
    return value, _signature(after)


def run(
    *,
    mode,
    manifest_path,
    expected_manifest_sha256,
    companion_path,
    expected_companion_sha256,
    review_companion_path,
    expected_review_companion_sha256,
    task_path,
    expected_task_sha256,
    output_path=None,
    bundle_path=None,
    expected_bundle_sha256=None,
):
    """Recapture every pinned input before returning or publishing a new file."""
    require(type(mode) is str and mode in {"build", "verify"}, "unsupported mode")
    require(
        type(expected_manifest_sha256) is str
        and HASH.fullmatch(expected_manifest_sha256),
        "capsule pin required",
    )
    if mode == "build":
        require(
            output_path is not None
            and bundle_path is None
            and expected_bundle_sha256 is None,
            "build paths invalid",
        )
    else:
        require(bundle_path is not None and output_path is None, "verify paths invalid")
    path = Path(manifest_path)
    capture, signatures = _capture(path)
    require(
        hashlib.sha256(capture["manifest.json"]).hexdigest()
        == expected_manifest_sha256,
        "capsule byte pin mismatch",
    )
    manifest = strict_json(capture["manifest.json"])
    require(
        canonical(manifest) == capture["manifest.json"], "canonical capsule required"
    )
    artifacts = {
        name[:-4]: payload
        for name, payload in capture.items()
        if name != "manifest.json"
    }
    task, task_signature = read_json(task_path, expected_task_sha256)
    companion, companion_signature = read_companion(
        companion_path, expected_companion_sha256
    )
    review, review_signature = read_review_companion(
        review_companion_path, expected_review_companion_sha256
    )
    inputs = {
        "manifest": manifest,
        "artifact_bytes": artifacts,
        "expected_manifest_sha256": expected_manifest_sha256,
        "companion": companion,
        "expected_companion_sha256": expected_companion_sha256,
        "review_companion": review,
        "expected_review_companion_sha256": expected_review_companion_sha256,
        "task": task,
        "expected_task_sha256": expected_task_sha256,
    }
    if mode == "build":
        bundle = build_task_dataset_v3(**inputs)
        report = {
            "version": bundle["version"],
            "technical_gate": bundle["gate"]["status"],
            "gate_reason_codes": bundle["gate"]["reason_codes"],
            "no_go_views": bundle["gate"]["no_go_views"],
            "coverage": bundle["coverage"],
            "bundle_sha256": digest(bundle),
            "review_observation_sha256": bundle["input_pins"][
                "review_observation_sha256"
            ],
            "review_scope": "captured_observation_not_current_authorization",
            **bundle["authority"],
        }
    else:
        bundle, bundle_signature = read_json(bundle_path, expected_bundle_sha256)
        report = verify_task_dataset_v3(
            bundle, **inputs, expected_bundle_sha256=expected_bundle_sha256
        )
        require(
            read_json(bundle_path, expected_bundle_sha256)
            == (bundle, bundle_signature),
            "bundle changed during verification",
        )
    require(
        _capture(path) == (capture, signatures), "capsule changed during compilation"
    )
    require(
        read_json(task_path, expected_task_sha256) == (task, task_signature),
        "task changed during compilation",
    )
    require(
        read_companion(companion_path, expected_companion_sha256)
        == (companion, companion_signature),
        "source companion changed during compilation",
    )
    require(
        read_review_companion(review_companion_path, expected_review_companion_sha256)
        == (review, review_signature),
        "review companion changed during compilation",
    )
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
    for field in (
        "manifest",
        "manifest-sha256",
        "companion",
        "companion-sha256",
        "review-companion",
        "review-companion-sha256",
        "task",
        "task-sha256",
    ):
        parser.add_argument("--" + field, required=True)
    for field in ("output", "bundle", "bundle-sha256"):
        parser.add_argument("--" + field)
    try:
        args = parser.parse_args(argv)
        report = run(
            mode=args.mode,
            manifest_path=args.manifest,
            expected_manifest_sha256=args.manifest_sha256,
            companion_path=args.companion,
            expected_companion_sha256=args.companion_sha256,
            review_companion_path=args.review_companion,
            expected_review_companion_sha256=args.review_companion_sha256,
            task_path=args.task,
            expected_task_sha256=args.task_sha256,
            output_path=args.output,
            bundle_path=args.bundle,
            expected_bundle_sha256=args.bundle_sha256,
        )
    except (ValueError, OSError, TypeError, RecursionError):
        print('{"status":"invalid","output_written":false}', file=sys.stderr)
        return 2
    print(canonical(report).decode())
    return 0 if report["technical_gate"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
