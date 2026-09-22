#!/usr/bin/env python3
"""Prepare a private ML-use intake declaration after exact baseline replay.

Offline only: no role lookup, source licence, request submission or model fitting.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from models.ml_use_request import INPUTS, PURPOSE, VERSION, prepare_request, sha
from services.ml_dataset_builder import AUTHORITY
from services.research_release_manifest import canonical, digest

from scripts import ml_baseline_preparation as baseline
from scripts.ml_audited_dataset import (
    OutputStateUnknown,
    read_package,
    write_new_package,
)
from scripts.verify_research_release import _capture, strict_json


def run(*, output_path, request_path=None, expected_request_sha256=None, **inputs):
    """Rebuild first, then emit/verify only a closed bounded input-pin declaration."""
    verify = request_path is not None
    if verify != (expected_request_sha256 is not None) or verify == (output_path is not None):
        raise ValueError("exact_request_operation_required")
    expected_names = {name + suffix for name in INPUTS for suffix in ("_path", "_sha256")}
    if set(inputs) != expected_names:
        raise ValueError("exact_request_inputs_required")
    pins = {name + "_sha256": sha(inputs[name + "_sha256"]) for name in INPUTS}
    original_pins = canonical(pins)
    manifest_path = Path(inputs["manifest_path"])
    capsule, signatures = _capture(manifest_path)
    if hashlib.sha256(capsule["manifest.json"]).hexdigest() != pins["manifest_sha256"]:
        raise ValueError("request_manifest_pin_changed")
    manifest = strict_json(capsule["manifest.json"])
    retained = {name: (baseline.READERS.get(name, read_package))(
        inputs[name + "_path"], pins[name + "_sha256"]) for name in INPUTS if name != "manifest"}
    original = {name: (canonical(value), identity) for name, (value, identity) in retained.items()}
    old_request = read_package(request_path, sha(expected_request_sha256)) if verify else None
    own_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    contract_path = ROOT / "api/models/ml_use_request.py"
    contract_hash = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    args = {}
    for name in INPUTS:
        target = "receipt" if name == "preparation" else name
        args[target + "_path"] = inputs[name + "_path"]
        args["expected_" + target + "_sha256"] = pins[name + "_sha256"]
    replay = baseline.run(mode="verify", output_path=None, **args)
    if replay["technical_gate"] != "pass" or replay["preparation_replay_verified"] is not True:
        raise ValueError("request_preparation_no_go")
    request = prepare_request(manifest=manifest, companion=retained["companion"][0], input_pins=pins)
    if verify and canonical(old_request[0]) != canonical(request):
        raise ValueError("request_replay_mismatch")
    if _capture(manifest_path) != (capsule, signatures):
        raise ValueError("request_capsule_changed")
    if canonical(manifest) != capsule["manifest.json"] or canonical(pins) != original_pins:
        raise ValueError("request_captured_inputs_mutated")
    for name in retained:
        reader = baseline.READERS.get(name, read_package)
        value, identity = reader(inputs[name + "_path"], pins[name + "_sha256"])
        if (canonical(value), identity) != original[name] or canonical(retained[name][0]) != original[name][0]:
            raise ValueError("request_input_changed")
    if (hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != own_hash
            or hashlib.sha256(contract_path.read_bytes()).hexdigest() != contract_hash):
        raise ValueError("request_implementation_changed")
    if verify:
        if read_package(request_path, expected_request_sha256) != old_request:
            raise ValueError("request_output_changed")
    else:
        write_new_package(output_path, request, forbidden_directory=manifest_path.parent)
    return {"version": VERSION, "purpose": PURPOSE, "request_sha256": digest(request),
        "output_written": not verify, "request_replay_verified": verify, "baseline_replay_verified_locally": True,
        "request_submitted": False, "training_execution": "disabled", **AUTHORITY}


def main(argv=None):
    parser = baseline._SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("mode", choices=["prepare", "verify"])
    for name in INPUTS:
        flag = name.replace("_", "-")
        parser.add_argument("--" + flag, required=True)
        parser.add_argument("--" + flag + "-sha256", required=True)
    for name in ("output", "request", "request-sha256"):
        parser.add_argument("--" + name)
    try:
        args = vars(parser.parse_args(argv))
        mode = args.pop("mode")
        output, request, pin = (args.pop(key) for key in ("output", "request", "request_sha256"))
        if (mode == "verify") != (request is not None):
            raise ValueError("request_mode_mismatch")
        parameters = {name if name.endswith("_sha256") else name + "_path": value for name, value in args.items()}
        result = run(output_path=output, request_path=request, expected_request_sha256=pin, **parameters)
    except OutputStateUnknown:
        print('{"status":"output_state_unknown","output_written":null}', file=sys.stderr)
        return 2
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError, OverflowError):
        print('{"status":"invalid","output_written":false}', file=sys.stderr)
        return 2
    print(canonical(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
