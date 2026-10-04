"""Actual archival evidence associations; never execution or science decisions."""
from __future__ import annotations

import json
import re

from services import discovery_design_contract as designs
from services.research_release_manifest import canonical
from services.source_property_pending import SourcePropertyError

VERSION = "discovery-feedback/1.0.0"
REQUEST_VERSION = "discovery-feedback-operation/1.0.0"
MAX_BYTES = 32768
MAX_PAGE = 8
MAX_FOLLOW_UPS = 8
MAX_PROJECTION_BYTES = 16384
OPERATIONS = ("return_evidence", "link_follow_up")
DECISIONS = ("continue", "stop", "redirect")
AUTHORITY = {"scientific_acceptance": False, "canonical_promotions": 0,
             "ml_training_approved": False, "public_release": False,
             "calculation_executed": False, "experiment_executed": False,
             "physical_association_established": False,
             "scope": "private_owner_evidence_association"}
RETAINED_FIELDS = ("id", "paper_id", "knowledge_origin", "evidence_type", "tc_kelvin", "tc_type", "tc_definition",
    "tc_criterion", "criterion", "measurement", "measurement_method", "method_statement",
    "pressure_gpa", "pressure_status", "pressure_kind", "pressure_conditions", "hc2_tesla",
    "hc2_tesla_unit", "hc2_conditions", "hc2_direction", "field_orientation",
    "magnetic_field_orientation", "scientific_values")
SCIENTIFIC_VALUE_FIELDS = ("raw_value", "input_unit", "raw_unit", "normalized_value", "normalized_unit", "status")


class DiscoveryFeedbackError(SourcePropertyError):
    """Static closed-request failure, without caller or source text."""


def require(ok, code):
    if not ok:
        raise DiscoveryFeedbackError(code)


def closed(value, keys):
    require(type(value) is dict and set(value) == set(keys), "feedback_closed_object_required")


def text(value, maximum):
    require(type(value) is str and 0 < len(value) <= maximum and value == value.strip()
            and not re.search(r"[\x00-\x1f\x7f\ud800-\udfff]", value), "feedback_bounded_text_required")
    return value


def identifier(value):
    try:
        return designs.identifier(value)
    except SourcePropertyError:
        raise DiscoveryFeedbackError("feedback_identifier_required") from None


def checksum(value):
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value), "feedback_checksum_required")
    return value


def design_pin(value):
    closed(value, ("design_id", "revision_id", "record_sha256", "next_action_sha256"))
    identifier(value["design_id"])
    identifier(value["revision_id"])
    checksum(value["record_sha256"])
    checksum(value["next_action_sha256"])


def evidence(value):
    closed(value, ("kind", "material_id", "record_index", "property_id", "expected_context_sha256"))
    require(value["kind"] == "retained_result" and value["property_id"] is None,
            "feedback_retained_evidence_required")
    text(value["material_id"], 100)
    require(type(value["record_index"]) is int and 0 <= value["record_index"] < 5000,
            "feedback_retained_selector_required")
    checksum(value["expected_context_sha256"])


def child_pin(value):
    closed(value, ("design_id", "revision_id", "record_sha256"))
    identifier(value["design_id"])
    identifier(value["revision_id"])
    checksum(value["record_sha256"])


def validate(request):
    closed(request, ("version", "request_key", "operation", "payload"))
    require(request["version"] == REQUEST_VERSION, "feedback_request_version_required")
    require(type(request["request_key"]) is str
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}", request["request_key"]),
            "feedback_request_key_required")
    operation, payload = request["operation"], request["payload"]
    require(operation in OPERATIONS, "feedback_operation_required")
    if operation == "return_evidence":
        closed(payload, ("design", "evidence", "findings", "decision", "reason", "unknowns"))
        design_pin(payload["design"])
        evidence(payload["evidence"])
        text(payload["findings"], 4000)
        require(payload["decision"] in DECISIONS, "feedback_explicit_decision_required")
        text(payload["reason"], 2000)
        require(type(payload["unknowns"]) is list and len(payload["unknowns"]) <= 16,
                "feedback_unknowns_bound")
        for item in payload["unknowns"]:
            text(item, 1000)
        require(len(set(payload["unknowns"])) == len(payload["unknowns"]), "feedback_distinct_unknowns_required")
    else:
        closed(payload, ("feedback", "child"))
        closed(payload["feedback"], ("id", "record_sha256"))
        identifier(payload["feedback"]["id"])
        checksum(payload["feedback"]["record_sha256"])
        child_pin(payload["child"])
    try:
        byte_count = len(canonical(request))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise DiscoveryFeedbackError("feedback_invalid_json") from None
    require(byte_count <= MAX_BYTES, "feedback_operation_byte_bound")
    return request


def snapshot(request):
    validate(request)
    value = json.loads(canonical(request))
    validate(value)
    return value
