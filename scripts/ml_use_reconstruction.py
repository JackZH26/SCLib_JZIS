#!/usr/bin/env python3
"""Create a private exact-byte upload envelope; never submit, approve or train."""
from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from models.ml_use_request import INPUTS, identifier
from services.ml_audited_dataset import canonical
from services.ml_use_reconstruction import VERSION, decode_envelope

from scripts import ml_use_request as intake
from scripts.ml_audited_dataset import (
    OutputStateUnknown,
    read_package,
    write_new_package,
)
from scripts.verify_research_release import _capture


def run(*, request_path, expected_request_sha256, requester_grant_id, curator_grant_id, output_path, **inputs):
    identifier(requester_grant_id)
    identifier(curator_grant_id)
    request, request_identity = read_package(request_path, expected_request_sha256)
    manifest_path = Path(inputs["manifest_path"])
    capture, signatures = _capture(manifest_path)
    retained = {name: intake.baseline.READERS.get(name, read_package)(
        inputs[name + "_path"], inputs[name + "_sha256"]) for name in INPUTS if name != "manifest"}
    source = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    replay = intake.run(output_path=None, request_path=request_path,
                        expected_request_sha256=expected_request_sha256, **inputs)
    if replay["request_replay_verified"] is not True:
        raise ValueError("request_replay_required")
    raw_inputs = {"manifest": capture["manifest.json"],
                  **{name: canonical(value) for name, (value, _) in retained.items()}}
    envelope = {"version": VERSION, "request": request, "expected_request_sha256": expected_request_sha256,
        "expected_requester_grant_id": requester_grant_id, "expected_curator_grant_id": curator_grant_id,
        "inputs_base64": {name: base64.b64encode(raw).decode("ascii") for name, raw in raw_inputs.items()},
        "artifacts_base64": {name[:-4]: base64.b64encode(raw).decode("ascii") for name, raw in capture.items()
                             if name != "manifest.json"}}
    raw = canonical(envelope)
    decode_envelope(raw)
    if _capture(manifest_path) != (capture, signatures):
        raise ValueError("capsule_changed")
    for name, retained_value in retained.items():
        if intake.baseline.READERS.get(name, read_package)(inputs[name + "_path"], inputs[name + "_sha256"]) != retained_value:
            raise ValueError("input_changed")
    if read_package(request_path, expected_request_sha256) != (request, request_identity):
        raise ValueError("request_changed")
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != source:
        raise ValueError("implementation_changed")
    write_new_package(output_path, envelope, forbidden_directory=manifest_path.parent)
    return {"version": VERSION, "envelope_sha256": hashlib.sha256(raw).hexdigest(),
            "request_sha256": expected_request_sha256, "output_written": True, "request_submitted": False}


def main(argv=None):
    parser = intake.baseline._SafeParser(description=__doc__, allow_abbrev=False)
    for name in INPUTS:
        flag = name.replace("_", "-")
        parser.add_argument("--" + flag, required=True)
        parser.add_argument("--" + flag + "-sha256", required=True)
    for name in ("request", "request-sha256", "requester-grant-id", "curator-grant-id", "output"):
        parser.add_argument("--" + name, required=True)
    try:
        values = vars(parser.parse_args(argv))
        options = {name: values.pop(name) for name in ("requester_grant_id", "curator_grant_id")}
        options.update(request_path=values.pop("request"), expected_request_sha256=values.pop("request_sha256"),
                       output_path=values.pop("output"))
        result = run(**options, **{name if name.endswith("_sha256") else name + "_path": value
                                  for name, value in values.items()})
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
