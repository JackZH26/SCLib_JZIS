#!/usr/bin/env python3
"""Build/replay a private ML08 canary from frozen human-asserted review records.

No network, database, human authentication, scientific approval or training.
Source references are never followed. Only explicitly supplied local files and
hash-named evidence leaves in a closed operator-selected directory are read.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from services import ml_pilot_accounting as pilot
from services.ml_pilot_canary import (  # noqa: F401 -- CLI compatibility exports
    AUTHORITY,
    HASH,
    MAX_CONTEXT_BYTES,
    MAX_CONTEXTS,
    MAX_EVIDENCE_BYTES,
    SCOPE,
    SOURCE_FILES,
    VERSION,
    canonical,
    compile_canary,
    digest,
    event_index,
    evidence_hashes,
    implementation,
    require,
    sha,
)
from services.ml_pilot_documents import _preparse, json_value, review_records

from scripts.ml_audited_dataset import (
    OutputStateUnknown,
    read_package,
    write_new_package,
)
from scripts.verify_research_release import _directory_fd, _signature


def _read_leaf(directory, name, expected, limit):
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
    )
    try:
        before = os.fstat(descriptor)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and 0 < before.st_size <= limit,
            "pilot_input_not_bounded_unaliased_regular_file",
        )
        chunks, size = [], 0
        while True:
            data = os.read(descriptor, min(1024 * 1024, limit - size + 1))
            if not data:
                break
            size += len(data)
            require(size <= limit, "pilot_input_byte_limit")
            chunks.append(data)
        after = os.fstat(descriptor)
        require(
            _signature(before) == _signature(after) and size == before.st_size,
            "pilot_input_changed_during_read",
        )
        raw = b"".join(chunks)
        require(sha(raw) == expected, "pilot_input_pin_mismatch")
        return raw, _signature(after)
    finally:
        os.close(descriptor)


def read_raw(path, expected, limit=pilot.MAX_BYTES):
    require(
        type(expected) is str and HASH.fullmatch(expected),
        "independent_pilot_input_pin_required",
    )
    path = Path(path)
    directory = _directory_fd(path.parent)
    try:
        return _read_leaf(directory, path.name, expected, limit)
    finally:
        os.close(directory)


def capture_evidence(path, hashes):
    directory = _directory_fd(Path(path))
    try:
        before = _signature(os.fstat(directory))
        names = []
        with os.scandir(directory) as entries:
            for entry in entries:
                require(len(names) < MAX_CONTEXTS, "pilot_context_count_limit")
                names.append(entry.name)
        require(
            sorted(names) == [pin + ".bin" for pin in hashes],
            "pilot_evidence_inventory_mismatch",
        )
        records, signatures, total = [], [], 0
        for pin in hashes:
            raw, signature = _read_leaf(
                directory,
                pin + ".bin",
                pin,
                min(MAX_CONTEXT_BYTES, MAX_EVIDENCE_BYTES - total),
            )
            total += len(raw)
            require(
                len(raw) > 0 and total <= MAX_EVIDENCE_BYTES, "pilot_context_byte_limit"
            )
            records.append({"sha256": pin, "size_bytes": len(raw)})
            signatures.append(signature)
        require(
            _signature(os.fstat(directory)) == before,
            "pilot_evidence_directory_changed",
        )
        reopened = _directory_fd(Path(path))
        try:
            require(
                _signature(os.fstat(reopened)) == before,
                "pilot_evidence_directory_replaced",
            )
        finally:
            os.close(reopened)
        return records, signatures, before
    finally:
        os.close(directory)


def run(
    *,
    mode,
    selection_path,
    expected_selection_file_sha256,
    expected_selection_sha256,
    reviews_path,
    expected_reviews_file_sha256,
    expected_review_log_sha256,
    protocol_path,
    expected_protocol_sha256,
    evidence_directory,
    output_path=None,
    bundle_path=None,
    expected_bundle_sha256=None,
    conclusion_path=None,
    expected_conclusion_sha256=None,
):
    require(mode in {"build", "verify"}, "pilot_mode_invalid")
    verify = mode == "verify"
    require(
        (
            output_path is None
            and bundle_path is not None
            and conclusion_path is not None
        )
        if verify
        else (
            output_path is not None
            and bundle_path is None
            and expected_bundle_sha256 is None
            and conclusion_path is None
            and expected_conclusion_sha256 is None
        ),
        "pilot_paths_invalid",
    )
    paths = {
        "selection": selection_path,
        "reviews": reviews_path,
        "protocol": protocol_path,
    }
    pins = {
        "selection": expected_selection_file_sha256,
        "reviews": expected_reviews_file_sha256,
        "protocol": expected_protocol_sha256,
    }
    if verify:
        paths["conclusion"], pins["conclusion"] = (
            conclusion_path,
            expected_conclusion_sha256,
        )
    all_pins = [*pins.values(), expected_selection_sha256, expected_review_log_sha256]
    if verify:
        all_pins.append(expected_bundle_sha256)
    require(
        all(type(pin) is str and HASH.fullmatch(pin) for pin in all_pins),
        "independent_pilot_pins_required",
    )
    source = implementation()
    captured = {key: read_raw(path, pins[key]) for key, path in paths.items()}
    selection = json_value(captured["selection"][0])
    # Keep the canonical ordered log hash distinct from the exact JSONL file hash.
    _preparse(captured["reviews"][0])
    reviews = review_records(captured["reviews"][0])
    initial = canonical({"selection": selection, "reviews": reviews})
    # Schema/cross-record checks precede access to any declared context hash.
    report = pilot.validate(
        selection, reviews, expected_selection_sha256=expected_selection_sha256
    )
    require(
        not report["errors"]
        and report["ready_for_review"]
        and report["final_gaps"] == ["conclusion_not_submitted"],
        "pilot_review_package_incomplete",
    )
    require(
        pilot.review_hash(reviews) == expected_review_log_sha256,
        "pilot_logical_anchor_mismatch",
    )
    require(
        selection["protocol_sha256"] == expected_protocol_sha256,
        "pilot_protocol_bytes_mismatch",
    )
    hashes = evidence_hashes(reviews)
    evidence = capture_evidence(evidence_directory, hashes)
    bundle = compile_canary(
        selection,
        reviews,
        selection_sha256=expected_selection_sha256,
        review_log_sha256=expected_review_log_sha256,
        input_pins={
            name + "_file_sha256": pins[name]
            for name in ("selection", "reviews", "protocol")
        },
        source=source,
        evidence=evidence[0],
    )
    old_bundle, conclusion_report = None, None
    if verify:
        old_bundle = read_package(bundle_path, expected_bundle_sha256)
        require(
            canonical(old_bundle[0]) == canonical(bundle),
            "pilot_canary_replay_mismatch",
        )
        conclusion = json_value(captured["conclusion"][0])
        conclusion_report = pilot.validate(
            selection, reviews, conclusion, expected_selection_sha256
        )
        require(
            not conclusion_report["errors"]
            and conclusion_report["ready_for_final_human_signoff"]
            and conclusion["canary_bundle_sha256"] == expected_bundle_sha256,
            "pilot_conclusion_not_bound_to_canary",
        )
    require(
        canonical({"selection": selection, "reviews": reviews}) == initial,
        "pilot_captured_values_mutated",
    )
    for key, path in paths.items():
        require(read_raw(path, pins[key]) == captured[key], "pilot_input_changed")
    require(
        capture_evidence(evidence_directory, hashes) == evidence,
        "pilot_evidence_changed",
    )
    require(implementation() == source, "pilot_implementation_changed")
    if verify:
        require(
            read_package(bundle_path, expected_bundle_sha256) == old_bundle,
            "pilot_bundle_changed",
        )
    else:
        write_new_package(output_path, bundle, forbidden_directory=evidence_directory)
    # No names, paths, locators, result values, review prose or raw context on stdout.
    return {
        "version": VERSION,
        "scope": SCOPE,
        "mode": mode,
        "canary_sha256": digest(bundle),
        "selection_sha256": expected_selection_sha256,
        "review_log_sha256": expected_review_log_sha256,
        "conclusion_file_sha256": expected_conclusion_sha256 if verify else None,
        "output_written": not verify,
        "canary_replay_verified": verify,
        "conclusion_documentary_gate_verified": conclusion_report is not None,
        "context_file_count": len(hashes),
        "context_bytes_hashed": sum(row["size_bytes"] for row in evidence[0]),
        "context_bytes_embedded": False,
        "authority": dict(AUTHORITY),
        "training_execution": "disabled",
    }


class SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("pilot_arguments_invalid")


def main(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("mode", choices=["build", "verify"])
    for name in (
        "selection",
        "reviews",
        "protocol",
        "evidence-directory",
        "selection-file-sha256",
        "selection-sha256",
        "reviews-file-sha256",
        "review-log-sha256",
        "protocol-sha256",
    ):
        parser.add_argument("--" + name, required=True)
    for name in (
        "output",
        "bundle",
        "bundle-sha256",
        "conclusion",
        "conclusion-sha256",
    ):
        parser.add_argument("--" + name)
    try:
        args = vars(parser.parse_args(argv))
        values = {
            (
                "expected_" + name
                if name.endswith("_sha256")
                else name + "_path"
                if name
                in {
                    "selection",
                    "reviews",
                    "protocol",
                    "output",
                    "bundle",
                    "conclusion",
                }
                else name
            ): value
            for name, value in args.items()
        }
        report = run(**values)
    except OutputStateUnknown:
        print(
            '{"status":"output_state_unknown","output_written":null,"scientific_acceptance":false}',
            file=sys.stderr,
        )
        return 2
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OSError,
        RecursionError,
        OverflowError,
    ):
        print(
            '{"status":"invalid","output_written":false,"scientific_acceptance":false}',
            file=sys.stderr,
        )
        return 2
    print(canonical(report).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
