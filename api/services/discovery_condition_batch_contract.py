"""Closed condition-batch requests and independent local-manifest reconstruction.

This module verifies received data and deterministic bytes. Current owner,
session, parent head, source closure and SQL write authority are checked by the
native service and guarded database functions, not by this pure reconstruction.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from uuid import UUID

from services import discovery_design_contract as design_contract
from services.research_release_manifest import canonical
from services.source_property_pending import SourcePropertyError

VERSION = "discovery-condition-batch/1.0.0"
REQUEST_VERSION = "discovery-condition-batch-operation/1.0.0"
SWEEP_VERSION = "discovery-condition-sweep/1.0.0"
CANDIDATE_VERSION = "discovery-condition-sweep-candidate/1.0.0"
OPERATIONS = ("retain_batch", "propose_candidate_child")
MAX_BYTES = 16384
MAX_PAGE = 8
MAX_OPTIONS = 8
MAX_SCENARIOS = 64
MAX_MANIFEST_BYTES = 4194304
MAX_EXPORT_BYTES = MAX_MANIFEST_BYTES + 128
AUTHORITY = {"scientific_acceptance": False, "canonical_promotions": 0,
             "ml_training_approved": False, "public_release": False,
             "calculation_executed": False, "scope": "private_owner_condition_batch"}

ERROR_CODES = frozenset({
    "condition_batch_closed_object_required", "condition_batch_request_version_required",
    "condition_batch_request_key_required", "condition_batch_operation_required",
    "condition_batch_identifier_required", "condition_batch_checksum_required",
    "condition_batch_revision_required", "condition_batch_axes_invalid",
    "condition_batch_empty_axis", "condition_batch_axis_limit",
    "condition_batch_pressure_invalid", "condition_batch_temperature_invalid",
    "condition_batch_decimal_invalid", "condition_batch_scenario_limit",
    "condition_batch_operation_byte_bound", "condition_batch_invalid_json",
    "condition_batch_parent_invalid", "condition_batch_source_unavailable",
    "condition_batch_actor_invalid", "condition_batch_manifest_limit",
})


class DiscoveryConditionBatchError(SourcePropertyError):
    """Static failure code; never include caller, source or driver text."""


def require(ok, code):
    if not ok:
        raise DiscoveryConditionBatchError(code)


def closed(value, keys):
    require(type(value) is dict and set(value) == set(keys),
            "condition_batch_closed_object_required")


def checksum(value):
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value),
            "condition_batch_checksum_required")
    return value


def identifier(value):
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise DiscoveryConditionBatchError("condition_batch_identifier_required") from None
    require(type(value) is str and str(parsed) == value,
            "condition_batch_identifier_required")
    return value


def parent(value):
    closed(value, ("design_id", "revision_id", "revision", "record_sha256"))
    identifier(value["design_id"])
    identifier(value["revision_id"])
    require(type(value["revision"]) is int and 1 <= value["revision"] <= 1000,
            "condition_batch_revision_required")
    checksum(value["record_sha256"])


def decimal_identity(raw):
    """Exact coefficient/exponent identity, with native float admission only.

    Zero has one identity, but its raw exponent still obeys the deployed Python
    Decimal representation bounds. Binary rounding never merges distinct inputs.
    These are representation limits, not physical pressure/temperature limits.
    """
    require(type(raw) is str and 0 < len(raw) <= 64,
            "condition_batch_decimal_invalid")
    match = re.fullmatch(r"(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?", raw,
                         flags=re.ASCII)
    require(match, "condition_batch_decimal_invalid")
    fractional = match[2] if match[2] is not None else match[3] or ""
    digits = ((match[1] or "") + fractional).lstrip("0")
    exponent = int(match[4] or "0") - len(fractional)
    require(-1999999999999999997 <= exponent <= 999999999999999999,
            "condition_batch_decimal_invalid")
    try:
        admitted = float(raw)
    except (ValueError, OverflowError):
        raise DiscoveryConditionBatchError("condition_batch_decimal_invalid") from None
    require(math.isfinite(admitted) and (not digits or admitted != 0),
            "condition_batch_decimal_invalid")
    if not digits:
        return "0e0"
    coefficient = digits.rstrip("0")
    exponent += len(digits) - len(coefficient)
    return f"{coefficient}e{exponent}"


def normalized_axes(value):
    """Validate the whole input and return sorted first-alias choices plus count."""
    require(type(value) is dict and set(value) == {"pressures", "temperatures_k"}
            and type(value["pressures"]) is list and type(value["temperatures_k"]) is list,
            "condition_batch_axes_invalid")
    pressure_count, temperature_count = len(value["pressures"]), len(value["temperatures_k"])
    require(pressure_count > 0 and temperature_count > 0, "condition_batch_empty_axis")
    require(pressure_count <= MAX_OPTIONS and temperature_count <= MAX_OPTIONS,
            "condition_batch_axis_limit")
    pressures, temperatures = {}, {}
    for pressure in value["pressures"]:
        require(type(pressure) is dict and set(pressure) == {"kind", "raw_gpa"}
                and pressure["kind"] in ("ambient", "specified", "unspecified"),
                "condition_batch_pressure_invalid")
        if pressure["kind"] == "specified":
            key = "specified:" + decimal_identity(pressure["raw_gpa"])
        else:
            require(pressure["raw_gpa"] is None, "condition_batch_pressure_invalid")
            key = pressure["kind"]
        pressures.setdefault(key, {"kind": pressure["kind"], "raw_gpa": pressure["raw_gpa"]})
    for temperature in value["temperatures_k"]:
        require(temperature is None or type(temperature) is str,
                "condition_batch_temperature_invalid")
        key = "unknown" if temperature is None else "specified:" + decimal_identity(temperature)
        temperatures.setdefault(key, temperature)
    unique_count = len(pressures) * len(temperatures)
    require(unique_count <= MAX_SCENARIOS, "condition_batch_scenario_limit")
    count = lambda raw, unique: {"raw_count": raw, "unique_count": unique,
                                 "collapsed_count": raw - unique}
    reasons = []
    if len(pressures) != pressure_count:
        reasons.append("pressure_aliases_collapsed")
    if len(temperatures) != temperature_count:
        reasons.append("temperature_aliases_collapsed")
    result = {"raw_cartesian_count": pressure_count * temperature_count,
              "unique_cartesian_count": unique_count,
              "pressure": count(pressure_count, len(pressures)),
              "temperature": count(temperature_count, len(temperatures)),
              "collapsed_reason_codes": reasons, "max_scenarios": MAX_SCENARIOS}
    return [(key, pressures[key]) for key in sorted(pressures)], [
        (key, temperatures[key]) for key in sorted(temperatures)], result


def _capture(value):
    try:
        return json.loads(canonical(value))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise DiscoveryConditionBatchError("condition_batch_invalid_json") from None


def estimate(axes):
    """Received-data estimate; invalid inputs never produce a partial sweep."""
    return normalized_axes(_capture(axes))[2]


def validate(request):
    closed(request, ("version", "request_key", "operation", "payload"))
    require(request["version"] == REQUEST_VERSION, "condition_batch_request_version_required")
    require(type(request["request_key"]) is str and re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}", request["request_key"]),
        "condition_batch_request_key_required")
    operation, payload = request["operation"], request["payload"]
    require(operation in OPERATIONS, "condition_batch_operation_required")
    if operation == "retain_batch":
        closed(payload, ("parent", "axes", "expected_input_sha256", "expected_manifest_sha256"))
        parent(payload["parent"])
        normalized_axes(payload["axes"])
        checksum(payload["expected_input_sha256"])
        checksum(payload["expected_manifest_sha256"])
    else:
        closed(payload, ("batch", "candidate_sha256"))
        closed(payload["batch"], ("id", "record_sha256", "manifest_sha256"))
        identifier(payload["batch"]["id"])
        checksum(payload["batch"]["record_sha256"])
        checksum(payload["batch"]["manifest_sha256"])
        checksum(payload["candidate_sha256"])
    try:
        encoded = canonical(request)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise DiscoveryConditionBatchError("condition_batch_invalid_json") from None
    require(len(encoded) <= MAX_BYTES, "condition_batch_operation_byte_bound")
    return request


def snapshot(request):
    """Detach and validate before an asynchronous service yields to its caller."""
    validate(request)
    captured = _capture(request)
    validate(captured)
    return captured


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_manifest(parent_row, projection, actor_pins, axes):
    """Reconstruct the unchanged local artifact without retaining source values.

    The caller supplies a native parent and safe projection after authorization.
    Only explicit identity/digest fields are extracted from the native row; raw
    context, receipt, projection values and unrelated row columns cannot egress.
    """
    require(isinstance(parent_row, Mapping) and isinstance(projection, Mapping),
            "condition_batch_parent_invalid")
    try:
        pin = {"design_id": str(parent_row["design_id"]), "revision_id": str(parent_row["id"]),
               "revision": parent_row["revision"], "record_sha256": parent_row["record_sha256"]}
        source_pins = {"baseline": parent_row["baseline"],
                       "context_sha256": parent_row["context_sha256"],
                       "projection_sha256": parent_row["projection_sha256"],
                       **{key: projection[key] for key in ("event_id", "state_id", "producer_run_id")}}
        detached = _capture({"parent": pin, "source_pins": source_pins,
                             "actor": actor_pins, "axes": axes, "design": parent_row["design"]})
    except KeyError:
        raise DiscoveryConditionBatchError("condition_batch_parent_invalid") from None
    pin, source_pins, actor, raw_axes, design = (detached[key] for key in (
        "parent", "source_pins", "actor", "axes", "design"))
    parent(pin)
    try:
        design_contract.baseline(source_pins["baseline"])
        design_contract.design(design)
    except design_contract.DiscoveryDesignError:
        raise DiscoveryConditionBatchError("condition_batch_parent_invalid") from None
    require(source_pins["baseline"]["kind"] != "unanchored", "condition_batch_source_unavailable")
    checksum(source_pins["context_sha256"])
    checksum(source_pins["projection_sha256"])
    require(source_pins["baseline"]["expected_context_sha256"] == source_pins["context_sha256"],
            "condition_batch_parent_invalid")
    for key in ("event_id", "state_id", "producer_run_id"):
        if source_pins[key] is not None:
            identifier(source_pins[key])
    closed(actor, ("actor_user_id", "session_version", "curator_grant_id"))
    identifier(actor["actor_user_id"])
    identifier(actor["curator_grant_id"])
    require(type(actor["session_version"]) is int and 0 <= actor["session_version"] <= 9007199254740991,
            "condition_batch_actor_invalid")
    pressures, temperatures, estimated = normalized_axes(raw_axes)
    input_text = canonical({"version": SWEEP_VERSION, "parent": pin,
                            "source_pins": source_pins, "axes": raw_axes}).decode()
    scenarios = []
    for pressure_identity, pressure in pressures:
        for temperature_identity, temperature in temperatures:
            candidate_sha = _sha(canonical({"version": CANDIDATE_VERSION,
                "parent_record_sha256": pin["record_sha256"], "pressure_identity": pressure_identity,
                "temperature_identity": temperature_identity}).decode())
            conditions = _capture({"pressure": pressure, "temperature_k": temperature})
            proposal = _capture(design)
            proposal["target_conditions"] = _capture(conditions)
            scenarios.append({"candidate_id": "condition-scenario:" + candidate_sha,
                              "candidate_sha256": candidate_sha, "conditions": conditions, "proposal": proposal})
    body = {"version": SWEEP_VERSION, "scope": "local_private_condition_sweep", "actor": actor,
        "parent": pin, "source_pins": source_pins, "input_canonical_json": input_text,
        "input_sha256": _sha(input_text), "estimate": estimated, "scenarios": scenarios,
        "budget_totals": [{"resource": item["resource"], "unit": item["unit"],
            "status": "unknown" if item["status"] == "unknown" else "not_aggregated", "total": None}
            for item in design["next_action"]["budget"]],
        "scientific_acceptance": False, "canonical_promotions": 0, "ml_training_approved": False,
        "public_release": False, "calculation_executed": False, "database_changed": False,
        "batch_saved": False, "atomic_sites_generated": False}
    manifest_bytes = canonical(body)
    require(len(manifest_bytes) <= MAX_MANIFEST_BYTES, "condition_batch_manifest_limit")
    return {**body, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}
