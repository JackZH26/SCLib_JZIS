#!/usr/bin/env python3
"""Build/replay a private ML08 canary from frozen human-asserted review records.

No network, database, human authentication, scientific approval or training.
Source references are never followed. Only explicitly supplied local files and
hash-named evidence leaves in a closed operator-selected directory are read.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import platform
import re
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from services.ml_audited_dataset import _preparse, canonical, digest

from scripts import validate_pilot_review as pilot
from scripts.ml_audited_dataset import (
    OutputStateUnknown,
    read_package,
    write_new_package,
)
from scripts.verify_research_release import _directory_fd, _signature

VERSION = "ml08-canary/1.0.0"
SCOPE = "private_replayable_human_asserted_pilot_not_scientific_acceptance"
HASH = re.compile(r"[0-9a-f]{64}\Z")
MAX_CONTEXTS = 6000
MAX_CONTEXT_BYTES = 8 * 1024 * 1024
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
AUTHORITY = {"scientific_acceptance": False, "scientific_pilot_accepted": False,
    "human_identity_authenticated": False, "reviewer_independence_authenticated": False,
    "actual_event_existence_verified": False, "source_permissions_verified": False,
    "source_content_scientifically_verified": False, "public_release": False,
    "ml_training_approved": False, "run_authorization_granted": False}
SOURCE_FILES = (
    "scripts/ml_pilot_canary.py", "scripts/validate_pilot_review.py",
    "docs/pilot/ML08_Pilot.schema.json", "scripts/ml_audited_dataset.py",
    "scripts/verify_research_release.py", "api/services/ml_audited_dataset.py",
    "api/services/research_release_manifest.py", "api/services/research_release_spec.py",
)


def require(condition, code="pilot_canary_invalid"):
    if not condition:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def implementation():
    return {"source_sha256": {name: sha((ROOT / name).read_bytes()) for name in SOURCE_FILES},
        "python": sys.version, "implementation": platform.python_implementation(),
        "scope": "selected_disk_sources_and_python_not_loaded_code_or_complete_runtime_attestation"}


def _read_leaf(directory, name, expected, limit):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= limit,
                "pilot_input_not_bounded_unaliased_regular_file")
        chunks, size = [], 0
        while True:
            data = os.read(descriptor, min(1024 * 1024, limit - size + 1))
            if not data:
                break
            size += len(data)
            require(size <= limit, "pilot_input_byte_limit")
            chunks.append(data)
        after = os.fstat(descriptor)
        require(_signature(before) == _signature(after) and size == before.st_size, "pilot_input_changed_during_read")
        raw = b"".join(chunks)
        require(sha(raw) == expected, "pilot_input_pin_mismatch")
        return raw, _signature(after)
    finally:
        os.close(descriptor)


def read_raw(path, expected, limit=pilot.MAX_BYTES):
    require(type(expected) is str and HASH.fullmatch(expected), "independent_pilot_input_pin_required")
    path = Path(path)
    directory = _directory_fd(path.parent)
    try:
        return _read_leaf(directory, path.name, expected, limit)
    finally:
        os.close(directory)


def json_value(raw):
    _preparse(raw)  # Bound depth/token allocation before parsing, including JSONL records.
    value = pilot._loads(raw.decode("utf-8"))
    canonical(value)  # Reject 1e999, lone surrogates and excessive post-parse trees.
    return value


def evidence_hashes(reviews):
    """All declared permitted context in every revision, not just accepted rows.

    Missing/restricted context stays in the ledger but is not opened. These
    declarations are not a live permission check; the operator needs authority.
    """
    hashes = set()
    for review in reviews:
        for result in review["results"]:
            source = result["source"]
            ref, pin = source["context_reference"], source["context_sha256"]
            if ref and pin and source["access_status"] == "permitted":
                hashes.add(pin)
    require(len(hashes) <= MAX_CONTEXTS, "pilot_context_count_limit")
    return sorted(hashes)


def capture_evidence(path, hashes):
    directory = _directory_fd(Path(path))
    try:
        before = _signature(os.fstat(directory))
        names = []
        with os.scandir(directory) as entries:
            for entry in entries:
                require(len(names) < MAX_CONTEXTS, "pilot_context_count_limit")
                names.append(entry.name)
        require(sorted(names) == [pin + ".bin" for pin in hashes], "pilot_evidence_inventory_mismatch")
        records, signatures, total = [], [], 0
        for pin in hashes:
            raw, signature = _read_leaf(directory, pin + ".bin", pin, min(MAX_CONTEXT_BYTES, MAX_EVIDENCE_BYTES - total))
            total += len(raw)
            require(len(raw) > 0 and total <= MAX_EVIDENCE_BYTES, "pilot_context_byte_limit")
            records.append({"sha256": pin, "size_bytes": len(raw)})
            signatures.append(signature)
        require(_signature(os.fstat(directory)) == before, "pilot_evidence_directory_changed")
        reopened = _directory_fd(Path(path))
        try:
            require(_signature(os.fstat(reopened)) == before, "pilot_evidence_directory_replaced")
        finally:
            os.close(reopened)
        return records, signatures, before
    finally:
        os.close(directory)


def event_index(selection, reviews):
    latest = {(row["candidate_id"], row["role"]): row for row in reviews}
    entries = []
    for candidate in selection["candidates"]:
        cid = candidate["candidate_id"]
        primary = latest[cid, "primary"]
        secondary, arbitration = latest.get((cid, "secondary")), latest.get((cid, "arbitration"))
        current = arbitration and secondary and set(arbitration["compares_review_ids"]) == {primary["review_id"], secondary["review_id"]}
        effective = arbitration if current else primary
        entries.append({"candidate_id": cid, "primary_review_id": primary["review_id"],
            "secondary_review_id": None if secondary is None else secondary["review_id"],
            "current_arbitration_review_id": arbitration["review_id"] if current else None,
            "effective_review_id": effective["review_id"], "outcome": effective["outcome"],
            "result_ids": [row["result_id"] for row in effective["results"]]})
    return entries


def compile_canary(selection, reviews, *, selection_sha256, review_log_sha256, input_pins, source, evidence):
    require(pilot.selection_hash(selection) == selection_sha256 and pilot.review_hash(reviews) == review_log_sha256,
            "pilot_logical_anchor_mismatch")
    report = pilot.validate(selection, reviews, expected_selection_sha256=selection_sha256)
    require(not report["errors"] and report["ready_for_review"]
            and report["final_gaps"] == ["conclusion_not_submitted"], "pilot_review_package_incomplete")
    require(selection["protocol_sha256"] == input_pins["protocol_file_sha256"], "pilot_protocol_bytes_mismatch")
    require([item["sha256"] for item in evidence] == evidence_hashes(reviews), "pilot_context_inventory_mismatch")
    return {"version": VERSION, "scope": SCOPE, "input_pins": input_pins,
        "selection_sha256": selection_sha256, "review_log_sha256": review_log_sha256,
        "implementation": source, "selection": selection, "reviews_including_superseded": reviews,
        "event_accounting": event_index(selection, reviews), "accounting": report,
        "accounting_component": "scripts/validate_pilot_review.py_documentary_only",
        "context_integrity_scope": "enclosing_canary_hashes_explicit_local_bytes_not_content_support_or_permission",
        "context_inventory": evidence, "context_bytes_embedded": False,
        "authority": dict(AUTHORITY), "training_execution": "disabled"}


def run(*, mode, selection_path, expected_selection_file_sha256, expected_selection_sha256,
        reviews_path, expected_reviews_file_sha256, expected_review_log_sha256,
        protocol_path, expected_protocol_sha256, evidence_directory,
        output_path=None, bundle_path=None, expected_bundle_sha256=None,
        conclusion_path=None, expected_conclusion_sha256=None):
    require(mode in {"build", "verify"}, "pilot_mode_invalid")
    verify = mode == "verify"
    require((output_path is None and bundle_path is not None and conclusion_path is not None)
            if verify else (output_path is not None and bundle_path is None and expected_bundle_sha256 is None
                            and conclusion_path is None and expected_conclusion_sha256 is None), "pilot_paths_invalid")
    paths = {"selection": selection_path, "reviews": reviews_path, "protocol": protocol_path}
    pins = {"selection": expected_selection_file_sha256, "reviews": expected_reviews_file_sha256,
            "protocol": expected_protocol_sha256}
    if verify:
        paths["conclusion"], pins["conclusion"] = conclusion_path, expected_conclusion_sha256
    all_pins = [*pins.values(), expected_selection_sha256, expected_review_log_sha256]
    if verify:
        all_pins.append(expected_bundle_sha256)
    require(all(type(pin) is str and HASH.fullmatch(pin) for pin in all_pins), "independent_pilot_pins_required")
    source = implementation()
    captured = {key: read_raw(path, pins[key]) for key, path in paths.items()}
    selection = json_value(captured["selection"][0])
    # Keep the canonical ordered log hash distinct from the exact JSONL file hash.
    _preparse(captured["reviews"][0])
    reviews = []
    for line in io.BytesIO(captured["reviews"][0]):
        if line.strip():
            require(len(reviews) < pilot.MAX_REVIEWS, "pilot_review_count_limit")
            reviews.append(json_value(line))
    initial = canonical({"selection": selection, "reviews": reviews})
    # Schema/cross-record checks precede access to any declared context hash.
    report = pilot.validate(selection, reviews, expected_selection_sha256=expected_selection_sha256)
    require(not report["errors"] and report["ready_for_review"]
            and report["final_gaps"] == ["conclusion_not_submitted"], "pilot_review_package_incomplete")
    require(pilot.review_hash(reviews) == expected_review_log_sha256, "pilot_logical_anchor_mismatch")
    require(selection["protocol_sha256"] == expected_protocol_sha256, "pilot_protocol_bytes_mismatch")
    hashes = evidence_hashes(reviews)
    evidence = capture_evidence(evidence_directory, hashes)
    bundle = compile_canary(selection, reviews, selection_sha256=expected_selection_sha256,
        review_log_sha256=expected_review_log_sha256, input_pins={name + "_file_sha256": pins[name]
            for name in ("selection", "reviews", "protocol")}, source=source, evidence=evidence[0])
    old_bundle, conclusion_report = None, None
    if verify:
        old_bundle = read_package(bundle_path, expected_bundle_sha256)
        require(canonical(old_bundle[0]) == canonical(bundle), "pilot_canary_replay_mismatch")
        conclusion = json_value(captured["conclusion"][0])
        conclusion_report = pilot.validate(selection, reviews, conclusion, expected_selection_sha256)
        require(not conclusion_report["errors"] and conclusion_report["ready_for_final_human_signoff"]
                and conclusion["canary_bundle_sha256"] == expected_bundle_sha256, "pilot_conclusion_not_bound_to_canary")
    require(canonical({"selection": selection, "reviews": reviews}) == initial, "pilot_captured_values_mutated")
    for key, path in paths.items():
        require(read_raw(path, pins[key]) == captured[key], "pilot_input_changed")
    require(capture_evidence(evidence_directory, hashes) == evidence, "pilot_evidence_changed")
    require(implementation() == source, "pilot_implementation_changed")
    if verify:
        require(read_package(bundle_path, expected_bundle_sha256) == old_bundle, "pilot_bundle_changed")
    else:
        write_new_package(output_path, bundle, forbidden_directory=evidence_directory)
    # No names, paths, locators, result values, review prose or raw context on stdout.
    return {"version": VERSION, "scope": SCOPE, "mode": mode, "canary_sha256": digest(bundle),
        "selection_sha256": expected_selection_sha256, "review_log_sha256": expected_review_log_sha256,
        "conclusion_file_sha256": expected_conclusion_sha256 if verify else None,
        "output_written": not verify, "canary_replay_verified": verify,
        "conclusion_documentary_gate_verified": conclusion_report is not None,
        "context_file_count": len(hashes), "context_bytes_hashed": sum(row["size_bytes"] for row in evidence[0]),
        "context_bytes_embedded": False, "authority": dict(AUTHORITY), "training_execution": "disabled"}


class SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("pilot_arguments_invalid")


def main(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("mode", choices=["build", "verify"])
    for name in ("selection", "reviews", "protocol", "evidence-directory", "selection-file-sha256",
                 "selection-sha256", "reviews-file-sha256", "review-log-sha256", "protocol-sha256"):
        parser.add_argument("--" + name, required=True)
    for name in ("output", "bundle", "bundle-sha256", "conclusion", "conclusion-sha256"):
        parser.add_argument("--" + name)
    try:
        args = vars(parser.parse_args(argv))
        values = {("expected_" + name if name.endswith("_sha256") else name + "_path"
                   if name in {"selection", "reviews", "protocol", "output", "bundle", "conclusion"} else name): value
                  for name, value in args.items()}
        report = run(**values)
    except OutputStateUnknown:
        print('{"status":"output_state_unknown","output_written":null,"scientific_acceptance":false}', file=sys.stderr)
        return 2
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError, OverflowError):
        print('{"status":"invalid","output_written":false,"scientific_acceptance":false}', file=sys.stderr)
        return 2
    print(canonical(report).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
