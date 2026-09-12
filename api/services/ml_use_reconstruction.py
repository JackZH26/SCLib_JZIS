"""Bounded, pure reconstruction of exact private ML intake bytes. Never fit.

The recorded client environment is untrusted provenance, not a signature. All
data-derived receipt fields are independently rebuilt by the current server.
"""
from __future__ import annotations

import base64
import hashlib
import platform
import sys
from importlib.resources import files

from models.ml_use_request import INPUTS, prepare_request, sha, validate_request
from services.ml_audited_dataset import canonical, digest, loads
from services.ml_baseline_rehearsal import prepare_audited_baseline_inputs
from services.ml_dataset_builder import AUTHORITY
from services.ml_preparation_receipt import receipt

VERSION = "ml-use-reconstruction/1.0.0"
MAX_ENVELOPE_BYTES = 32 * 1024 * 1024
MAX_DECODED_BYTES = 24 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_ARTIFACTS = 256
FIELDS = {"version", "request", "expected_request_sha256", "expected_requester_grant_id",
          "expected_curator_grant_id", "inputs_base64", "artifacts_base64"}
MODULES = ("models.ml_use_request", "services.ml_use_reconstruction",
           "services.ml_use_reconstruction_worker", "services.ml_preparation_receipt",
           "services.ml_baseline_rehearsal", "services.ml_audited_dataset")


def require(condition):
    if not condition:
        raise ValueError("ml_use_reconstruction_invalid")


def implementation():
    return {"source_sha256": {name: hashlib.sha256(files(name.rsplit(".", 1)[0])
            .joinpath(name.rsplit(".", 1)[1] + ".py").read_bytes()).hexdigest() for name in MODULES},
            "python": sys.version, "implementation": platform.python_implementation(),
            "machine": platform.machine(), "byteorder": sys.byteorder}


def _decode(value, budget):
    require(type(value) is str and len(value) <= 4 * ((MAX_FILE_BYTES + 2) // 3))
    raw = base64.b64decode(value, validate=True)
    require(len(raw) <= MAX_FILE_BYTES and base64.b64encode(raw).decode("ascii") == value)
    budget[0] += len(raw)
    require(budget[0] <= MAX_DECODED_BYTES)
    return raw


def decode_envelope(raw):
    """Canonical wire format avoids accepting a reserialized file as exact bytes."""
    from models.ml_use_request import identifier
    require(type(raw) is bytes and 0 < len(raw) <= MAX_ENVELOPE_BYTES)
    value = loads(raw)
    require(type(value) is dict and set(value) == FIELDS and value["version"] == VERSION)
    request = validate_request(value["request"])
    require(digest(request) == sha(value["expected_request_sha256"]))
    identifier(value["expected_requester_grant_id"])
    identifier(value["expected_curator_grant_id"])
    require(type(value["inputs_base64"]) is dict and set(value["inputs_base64"]) == set(INPUTS))
    encoded = value["artifacts_base64"]
    require(type(encoded) is dict and len(encoded) <= MAX_ARTIFACTS)
    budget, inputs, artifacts = [0], {}, {}
    for name in INPUTS:
        payload = _decode(value["inputs_base64"][name], budget)
        require(hashlib.sha256(payload).hexdigest() == request["input_pins"][name + "_sha256"])
        inputs[name] = loads(payload)
    for pin, text in encoded.items():
        payload = _decode(text, budget)
        require(hashlib.sha256(payload).hexdigest() == sha(pin))
        artifacts[pin] = payload
    return value, inputs, artifacts


def _client_provenance(value):
    # These fields cannot establish where or by whom a client program ran.
    # They are retained only as exact, bounded declarations in the input pin.
    require(type(value) is dict and set(value) == {"source_sha256", "python", "implementation",
            "machine", "byteorder", "verification"})
    require(value["verification"] == "exact_rebuild_in_recorded_runtime")
    require(value["byteorder"] in {"little", "big"})
    require(all(type(value[k]) is str and 0 < len(value[k]) <= 512 for k in
                ("python", "implementation", "machine")))
    sources = value["source_sha256"]
    require(type(sources) is dict and 1 <= len(sources) <= 64)
    for name, pin in sources.items():
        require(type(name) is str and 0 < len(name) <= 256 and name.startswith(("api/", "scripts/"))
                and ".." not in name.split("/") and "\\" not in name and "\x00" not in name)
        sha(pin)
    return value


def reconstruct(raw):
    source = implementation()
    envelope, inputs, artifacts = decode_envelope(raw)
    request = envelope["request"]
    pins = request["input_pins"]
    args = {"artifact_bytes": artifacts}
    for name in ("manifest", "task", "companion", "review_companion", "label_companion", "config"):
        args[name], args["expected_" + name + "_sha256"] = inputs[name], pins[name + "_sha256"]
    prepared = prepare_audited_baseline_inputs(inputs["package"],
        expected_package_sha256=pins["package_sha256"], **args)
    expected = receipt(prepared, inputs["config"], {key: pin for key, pin in pins.items()
                       if key != "preparation_sha256"}, _client_provenance(inputs["preparation"]["implementation"]))
    require(canonical(expected) == canonical(inputs["preparation"]))
    require(expected["diagnostics"]["gate"]["status"] == "pass")
    require(prepare_request(manifest=inputs["manifest"], companion=inputs["companion"], input_pins=pins) == request)
    require(implementation() == source)
    return {"version": VERSION, "request_sha256": digest(request), "envelope_sha256": hashlib.sha256(raw).hexdigest(),
            "input_pins": pins, "prepared_sha256": digest(prepared), "technical_gate": "pass",
            "all_eight_input_bytes_verified": True, "dataset_and_preparation_rebuilt": True,
            "client_runtime_provenance_authenticated": False,
            "client_provenance_status": "self_reported_not_authenticated",
            "capsule_artifact_pins": sorted(artifacts), "server_implementation": source,
            "server_implementation_sha256": digest(source),
            "source_permission_granted": False, "run_authorization_granted": False,
            "request_persisted": False, "training_execution": "disabled", **AUTHORITY}
