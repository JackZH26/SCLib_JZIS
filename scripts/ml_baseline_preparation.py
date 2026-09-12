#!/usr/bin/env python3
"""Prepare/replay private baseline inputs from audited datasets; never fit a model.

Drafts and preparations require the original five pinned inputs, including the
closed capsule inventory. Offline checks authenticate neither people nor rights.
The existing real-data training entry point remains disabled.
"""
from __future__ import annotations

import argparse
import hashlib
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from models.ml_baseline_task import validate_baseline_task
from models.ml_task import HASH, require
from services.ml_audited_dataset import canonical, digest, verify_audited_task_dataset
from services.ml_baseline_rehearsal import (
    draft_task_for_package,
    prepare_audited_baseline_inputs,
)
from services.ml_dataset_builder import AUTHORITY
from services.ml_preparation_receipt import SCOPE, TRAINING_BLOCKERS, VERSION
from services.ml_preparation_receipt import diagnostics as diagnostics
from services.ml_preparation_receipt import receipt as _receipt
from services.research_release_manifest import canonical as capsule_canonical

from scripts.ml_audited_dataset import (
    OutputStateUnknown,
    read_package,
    write_new_package,
)
from scripts.ml_current_dataset import read_label_companion
from scripts.ml_reviewed_dataset import read_review_companion
from scripts.ml_scientific_dataset import read_companion
from scripts.ml_task_dataset import read_json
from scripts.verify_research_release import _capture, strict_json

READERS = {
    "task": read_json,
    "companion": read_companion,
    "review_companion": read_review_companion,
    "label_companion": read_label_companion,
    "package": read_package,
    "config": read_json,
    "receipt": read_package,
}
IMPLEMENTATION_FILES = (
    "scripts/ml_baseline_preparation.py",
    "scripts/ml_audited_dataset.py",
    "scripts/ml_current_dataset.py",
    "scripts/ml_reviewed_dataset.py",
    "scripts/ml_scientific_dataset.py",
    "scripts/ml_task_dataset.py",
    "scripts/verify_research_release.py",
    "api/models/ml_baseline_task.py",
    "api/services/ml_baseline_rehearsal.py",
    "api/services/ml_preparation_receipt.py",
    "api/services/ml_audited_dataset.py",
    "api/services/ml_preprocessing.py",
    "api/uv.lock",
)


def implementation():
    """This wrapper's exact code/runtime; the package pins its own compilers."""
    return {
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in IMPLEMENTATION_FILES},
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "byteorder": sys.byteorder,
        "verification": "exact_rebuild_in_recorded_runtime",
    }




def run(*, mode, manifest_path, expected_manifest_sha256, task_path, expected_task_sha256,
        companion_path, expected_companion_sha256, review_companion_path, expected_review_companion_sha256,
        label_companion_path, expected_label_companion_sha256, package_path, expected_package_sha256,
        config_path=None, expected_config_sha256=None, output_path=None, receipt_path=None,
        expected_receipt_sha256=None, views=None):
    """Draft a configuration, prepare a private file, or rebuild a pinned receipt."""
    require(type(mode) is str and mode in {"draft", "prepare", "verify"}, "invalid preparation mode")
    if mode == "draft":
        require(config_path is None and expected_config_sha256 is None and output_path is not None
                and receipt_path is None and expected_receipt_sha256 is None, "invalid draft paths")
    else:
        require(config_path is not None and expected_config_sha256 is not None and views is None,
                "independently pinned configuration required")
        require((output_path is not None and receipt_path is None and expected_receipt_sha256 is None)
                if mode == "prepare" else
                (output_path is None and receipt_path is not None and expected_receipt_sha256 is not None),
                "invalid preparation paths")
    if views is not None:
        require(type(views) is list and views and all(type(v) is str for v in views)
                and views == sorted(set(views)), "explicit sorted unique views required")
    paths = {"task": task_path, "companion": companion_path, "review_companion": review_companion_path,
             "label_companion": label_companion_path, "package": package_path}
    pins = {"manifest": expected_manifest_sha256, "task": expected_task_sha256,
            "companion": expected_companion_sha256, "review_companion": expected_review_companion_sha256,
            "label_companion": expected_label_companion_sha256, "package": expected_package_sha256}
    if mode != "draft":
        paths["config"], pins["config"] = config_path, expected_config_sha256
    if mode == "verify":
        paths["receipt"], pins["receipt"] = receipt_path, expected_receipt_sha256
    # Validate every independent pin before opening any of the scientific files.
    require(all(type(pin) is str and HASH.fullmatch(pin) for pin in pins.values()), "independent pins required")
    source = implementation()
    path = Path(manifest_path)
    capture, signatures = _capture(path)
    require(hashlib.sha256(capture["manifest.json"]).hexdigest() == expected_manifest_sha256,
            "capsule file pin mismatch")
    manifest = strict_json(capture["manifest.json"])
    require(capsule_canonical(manifest) == capture["manifest.json"], "canonical capsule required")
    retained = {name: READERS[name](location, pins[name]) for name, location in paths.items()}
    # Keep independent canonical snapshots for postchecks; a callee mutating its
    # supplied mapping must not redefine the bytes compared with a final reread.
    original = {name: (canonical(value), signature) for name, (value, signature) in retained.items()}
    values = {name: item[0] for name, item in retained.items()}
    inputs = {"manifest": manifest,
              "artifact_bytes": {name[:-4]: raw for name, raw in capture.items() if name != "manifest.json"},
              "expected_manifest_sha256": expected_manifest_sha256}
    for name in ("task", "companion", "review_companion", "label_companion"):
        inputs[name], inputs["expected_" + name + "_sha256"] = values[name], pins[name]
    package = values["package"]
    if mode == "draft":
        verified = verify_audited_task_dataset(package, expected_package_sha256=expected_package_sha256, **inputs)
        gate = verified["technical_gate"]
        require(gate in {"pass", "no_go"}, "invalid audited gate")
        config = draft_task_for_package(package, views=views) if gate == "pass" else None
        if config is not None:
            validate_baseline_task(config)
        output = config
        report = {"version": VERSION, "scope": SCOPE, "mode": mode, "technical_gate": gate,
                  "package_sha256": expected_package_sha256,
                  "config_sha256": None if config is None else digest(config),
                  "draft_requires_independent_review_and_pin": True}
    else:
        config = values["config"]
        validate_baseline_task(config)
        prepared = prepare_audited_baseline_inputs(
            package, expected_package_sha256=expected_package_sha256, config=config,
            expected_config_sha256=expected_config_sha256, **inputs)
        output = _receipt(prepared, config, {name + "_sha256": pin for name, pin in pins.items()
                                            if name != "receipt"}, source)
        gate = output["diagnostics"]["gate"]["status"]
        if mode == "verify":
            require(canonical(values["receipt"]) == canonical(output), "preparation replay mismatch")
        report = {"version": VERSION, "scope": SCOPE, "mode": mode, "technical_gate": gate,
                  "package_sha256": expected_package_sha256, "config_sha256": expected_config_sha256,
                  "receipt_sha256": digest(output), "prepared_sha256": digest(prepared),
                  "preparation_replay_verified": mode == "verify",
                  "arm_count": len(prepared["arms"]),
                  "arm_failures": output["diagnostics"]["gate"]["arm_failures"]}
    require(_capture(path) == (capture, signatures), "capsule changed during preparation")
    require(capsule_canonical(manifest) == capture["manifest.json"], "captured manifest mutated")
    require(inputs["artifact_bytes"] == {name[:-4]: raw for name, raw in capture.items()
                                        if name != "manifest.json"}, "captured artifacts mutated")
    for name, location in paths.items():
        value, signature = READERS[name](location, pins[name])
        require((canonical(value), signature) == original[name]
                and canonical(values[name]) == original[name][0], "input changed during preparation")
    require(implementation() == source, "implementation changed during preparation")
    should_write = mode != "verify" and gate == "pass"
    if should_write:
        write_new_package(output_path, output, forbidden_directory=path.parent)
    return {**report, "output_written": should_write, "training_execution": "disabled",
            "training_blockers": list(TRAINING_BLOCKERS), "independent_support_count": None, **AUTHORITY}


class _SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("invalid preparation arguments")


def main(argv=None):
    parser = _SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("mode", choices=["draft", "prepare", "verify"])
    for field in ("manifest", "task", "companion", "review-companion", "label-companion", "package"):
        parser.add_argument("--" + field, required=True)
        parser.add_argument("--" + field + "-sha256", required=True)
    for field in ("config", "config-sha256", "output", "receipt", "receipt-sha256"):
        parser.add_argument("--" + field)
    parser.add_argument("--view", action="append", dest="views")
    try:
        args = vars(parser.parse_args(argv))
        arguments = {"mode": args.pop("mode"), "views": args.pop("views")}
        for name, value in args.items():
            arguments[("expected_" + name) if name.endswith("_sha256") else (name + "_path")] = value
        report = run(**arguments)
    except OutputStateUnknown:
        print('{"status":"output_state_unknown","output_written":null}', file=sys.stderr)
        return 2
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError, OverflowError):
        print('{"status":"invalid","output_written":false}', file=sys.stderr)
        return 2
    print(canonical(report).decode())
    return 0 if report["technical_gate"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
