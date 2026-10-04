"""Closed private research-design requests; proposals confer no science authority."""
from __future__ import annotations

import json
import math
import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

from services.research_release_manifest import canonical
from services.source_property_pending import SourcePropertyError

VERSION = "discovery-design/1.0.0"
REQUEST_VERSION = "discovery-design-operation/1.0.0"
MAX_BYTES = 65536
MAX_PAGE = 8
MODIFICATIONS = ("doping", "substitution", "vacancy", "strain", "interface", "layer", "twist", "pressure")
PAIRING = ("unresolved", "epc", "correlated", "multiband", "interface")
ACTION_KINDS = ("source_review", "calculation", "experiment")
DECISIONS = ("continue", "stop", "redirect")
RESOURCES = ("cpu_hours", "gpu_hours", "memory", "storage", "human_hours")
AUTHORITY = {"scientific_acceptance": False, "canonical_promotions": 0,
             "ml_training_approved": False, "public_release": False,
             "calculation_executed": False, "scope": "private_owner_research_design"}
NATIVE_UNITS = {"formation_energy_per_atom": "eV/atom", "energy_above_hull": "eV/atom",
    "band_gap": "eV", "dos_at_fermi": "states/eV/formula_unit", "electron_phonon_lambda": "1",
    "omega_log": "K", "phonon_min_frequency": "THz", "superfluid_stiffness": "K"}


class DiscoveryDesignError(SourcePropertyError):
    """Static request failure; never include source or caller text."""


def require(ok, code):
    if not ok:
        raise DiscoveryDesignError(code)


def closed(value, keys):
    require(type(value) is dict and set(value) == set(keys), "design_closed_object_required")


def text(value, maximum, *, empty=False):
    require(type(value) is str and len(value) <= maximum and value == value.strip()
            and (empty or bool(value)) and not re.search(r"[\x00-\x1f\x7f\ud800-\udfff]", value),
            "design_bounded_text_required")
    return value


def checksum(value):
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value), "design_checksum_required")
    return value


def identifier(value):
    try:
        result = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise DiscoveryDesignError("design_identifier_required") from None
    require(type(value) is str and str(result) == value, "design_identifier_required")
    return value


def decimal(value, *, optional=False):
    if optional and value is None:
        return None
    text(value, 80)
    require(re.fullmatch(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value), "design_nonnegative_decimal_required")
    try:
        number = Decimal(value)
        binary = float(number)
    except (InvalidOperation, ValueError, OverflowError):
        raise DiscoveryDesignError("design_finite_decimal_required") from None
    require(number.is_finite() and number >= 0 and math.isfinite(binary)
            and not (number != 0 and binary == 0), "design_finite_decimal_required")
    return number


def baseline(value):
    closed(value, ("kind", "material_id", "record_index", "property_id", "expected_context_sha256"))
    require(value["kind"] in ("unanchored", "retained_result", "native_property"), "design_baseline_kind_required")
    checksum(value["expected_context_sha256"])
    if value["kind"] == "unanchored":
        require(all(value[k] is None for k in ("material_id", "record_index", "property_id")), "design_unanchored_selector_required")
    else:
        text(value["material_id"], 100)
        if value["kind"] == "retained_result":
            require(type(value["record_index"]) is int and 0 <= value["record_index"] < 5000
                    and value["property_id"] is None, "design_retained_selector_required")
        else:
            identifier(value["property_id"])
            require(value["record_index"] is None, "design_native_selector_required")


def predecessor(value):
    closed(value, ("id", "record_sha256"))
    identifier(value["id"])
    checksum(value["record_sha256"])


def parent(value):
    if value is None:
        return
    closed(value, ("design_id", "revision_id", "record_sha256"))
    identifier(value["design_id"])
    identifier(value["revision_id"])
    checksum(value["record_sha256"])


def design(value):
    closed(value, ("host_label", "state_label", "modifications", "target_conditions", "pairing_hypothesis", "hypothesis", "next_action"))
    text(value["host_label"], 500)
    text(value["state_label"], 500)
    text(value["hypothesis"], 4000)
    require(value["pairing_hypothesis"] in PAIRING, "design_pairing_hypothesis_required")
    modifications = value["modifications"]
    require(type(modifications) is list and 1 <= len(modifications) <= 8, "design_modification_bound")
    for item in modifications:
        closed(item, ("kind", "parameters"))
        require(item["kind"] in MODIFICATIONS, "design_modification_kind_required")
        text(item["parameters"], 2000)
    conditions = value["target_conditions"]
    closed(conditions, ("pressure", "temperature_k"))
    pressure = conditions["pressure"]
    closed(pressure, ("kind", "raw_gpa"))
    require(pressure["kind"] in ("unspecified", "ambient", "specified"), "design_pressure_kind_required")
    if pressure["kind"] == "specified":
        decimal(pressure["raw_gpa"])
    else:
        require(pressure["raw_gpa"] is None, "design_pressure_value_scope")
    decimal(conditions["temperature_k"], optional=True)
    action = value["next_action"]
    closed(action, ("kind", "question", "prerequisites", "outcomes", "budget"))
    require(action["kind"] in ACTION_KINDS, "design_action_kind_required")
    text(action["question"], 2000)
    require(type(action["prerequisites"]) is list and 1 <= len(action["prerequisites"]) <= 16, "design_prerequisite_bound")
    for item in action["prerequisites"]:
        text(item, 1000)
    outcomes = action["outcomes"]
    require(type(outcomes) is list and 2 <= len(outcomes) <= 8, "design_observable_outcomes_required")
    for outcome in outcomes:
        closed(outcome, ("observation", "decision"))
        text(outcome["observation"], 1000)
        require(outcome["decision"] in DECISIONS, "design_decision_required")
    require(len({x["observation"].casefold() for x in outcomes}) == len(outcomes)
            and len({x["decision"] for x in outcomes}) >= 2, "design_distinct_observations_decisions_required")
    budget = action["budget"]
    require(type(budget) is list and len(budget) == len(RESOURCES), "design_budget_inventory_required")
    require(all(type(x) is dict and type(x.get("resource")) is str for x in budget), "design_budget_inventory_required")
    require({x["resource"] for x in budget} == set(RESOURCES), "design_budget_inventory_required")
    for item in budget:
        closed(item, ("resource", "status", "raw_upper", "unit"))
        require(item["status"] in ("unknown", "estimated"), "design_budget_status_required")
        text(item["unit"], 40)
        if item["status"] == "unknown":
            require(item["raw_upper"] is None, "design_unknown_budget_not_zero")
        else:
            decimal(item["raw_upper"])
        require(item["unit"] == {"cpu_hours": "core-hour", "gpu_hours": "gpu-hour", "memory": "GiB", "storage": "GiB", "human_hours": "person-hour"}[item["resource"]], "design_budget_unit_required")


def validate(request):
    closed(request, ("version", "request_key", "operation", "payload"))
    require(request["version"] == REQUEST_VERSION, "design_request_version_required")
    require(type(request["request_key"]) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}", request["request_key"]), "design_request_key_required")
    operation, payload = request["operation"], request["payload"]
    require(operation in ("propose", "revise", "withdraw"), "design_operation_required")
    if operation == "withdraw":
        closed(payload, ("design_id", "predecessor", "reason"))
        identifier(payload["design_id"])
        predecessor(payload["predecessor"])
        text(payload["reason"], 2000)
    else:
        closed(payload, ("baseline", "design", "parent") if operation == "propose" else ("baseline", "design", "parent", "design_id", "predecessor"))
        baseline(payload["baseline"])
        design(payload["design"])
        parent(payload["parent"])
        if operation == "revise":
            identifier(payload["design_id"])
            predecessor(payload["predecessor"])
    try:
        require(len(canonical(request)) <= MAX_BYTES, "design_operation_byte_bound")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise DiscoveryDesignError("design_invalid_json") from None
    return request


def snapshot(request):
    """Detach before the first await so caller mutation cannot change a pinned request."""
    validate(request)
    captured = json.loads(canonical(request))
    validate(captured)
    return captured
