"""Closed source-scoped metadata review; original Tc observations stay intact."""
from __future__ import annotations

import json

from services.research_release_manifest import canonical
from services.source_property_pending import checksum, identifier, request_key, require

VERSION = "material-field-review/1.0.0"
PROFILE = "retained-tc-field-fidelity/1.0.0"
FIELDS = ("tc_criterion", "measurement_method", "pressure_gpa")
CHECKS = ("source_identity_and_fragment", "field_value_and_unit_boundary",
          "retained_result_window_and_sample_scope", "semantic_missingness_and_conflicts")
AUTHORITY = {"scientific_acceptance": False, "canonical_promotions": 0,
             "ml_training_approved": False, "public_release_authorized": False,
             "sample_identity_established": False, "phase_identity_established": False}
MAX_BYTES = 32768
MAX_RESPONSE_BYTES = 2 * 1024 * 1024 - 4096
SUBJECT_KEYS = ("target_id", "target_sha256", "field_id", "association", "expression",
                "tc_expression", "source_identity", "component")
ITEM_KEYS = (*SUBJECT_KEYS, "expected_subject_sha256", "expected_candidate_sha256",
             "expected_missingness_sha256", "expected_tuple_sha256", "decision", "checks",
             "source_inspection_attested", "rationale", "predecessor", "resolves_decision_id")


def closed(value, keys):
    require(type(value) is dict and set(value) == set(keys), "field_review_closed_object_required")


def pin(value, *, nullable=False, projection=False):
    if nullable and value is None:
        return
    closed(value, ("id", "record_sha256", "projection_sha256") if projection else ("id", "record_sha256"))
    require(type(value["id"]) is str, "field_review_identifier_required")
    identifier(value["id"])
    checksum(value["record_sha256"])
    if projection:
        checksum(value["projection_sha256"])


def subject(value):
    closed(value, SUBJECT_KEYS)
    require(type(value["target_id"]) is str, "field_review_identifier_required")
    identifier(value["target_id"])
    checksum(value["target_sha256"])
    require(type(value["field_id"]) is str and value["field_id"] in FIELDS, "field_review_field_required")
    pin(value["association"], nullable=True)
    pin(value["expression"], projection=True)
    pin(value["tc_expression"], nullable=True, projection=True)
    closed(value["source_identity"], ("paper_id", "work_id"))
    paper = value["source_identity"]["paper_id"]
    require(type(paper) is str and 1 <= len(paper) <= 100 and paper == paper.strip()
            and all(ord(c) >= 32 for c in paper), "field_review_paper_required")
    if value["source_identity"]["work_id"] is not None:
        identifier(value["source_identity"]["work_id"])
    c = value["component"]
    closed(c, ("kind", "index", "field_id", "role"))
    expected = {"tc_criterion": "criterion_statement", "measurement_method": "method_statement",
                "pressure_gpa": "pressure_gpa"}[value["field_id"]]
    require(c["field_id"] == expected, "field_review_component_field_required")
    require(c["kind"] == "condition" and type(c["index"]) is int and 0 <= c["index"] <= 7
            and c["role"] == "reported_result_condition"
            or c["kind"] == "value" and value["field_id"] == "measurement_method"
            and c["index"] is None and c["role"] is None, "field_review_component_required")
    require(value["tc_expression"] is None if c["kind"] == "condition"
            else value["tc_expression"] is not None, "field_review_tc_companion_scope_required")


def validate(value):
    closed(value, ("version", "profile_version", "request_key", "items"))
    require(value["version"] == VERSION and value["profile_version"] == PROFILE, "field_review_profile_required")
    request_key(value["request_key"])
    require(type(value["items"]) is list and 1 <= len(value["items"]) <= 8, "field_review_item_bound")
    seen = set()
    for item in value["items"]:
        closed(item, ITEM_KEYS)
        subject({k: item[k] for k in SUBJECT_KEYS})
        key = item["target_id"], item["field_id"]
        require(key not in seen, "field_review_duplicate_target")
        seen.add(key)
        for key in ("expected_subject_sha256", "expected_candidate_sha256",
                    "expected_missingness_sha256", "expected_tuple_sha256"):
            checksum(item[key])
        require(type(item["decision"]) is str and item["decision"] in {"accept", "reject", "request_clarification"},
                "field_review_decision_required")
        closed(item["checks"], CHECKS)
        require(all(type(x) is str and x in {"satisfied", "unresolved", "not_applicable"}
                    for x in item["checks"].values()), "field_review_checks_required")
        require(type(item["source_inspection_attested"]) is bool, "field_review_attestation_required")
        rationale = item["rationale"]
        require(type(rationale) is str and 20 <= len(rationale.strip()) <= len(rationale) <= 1000
                and all(c in "\n\t" or ord(c) >= 32 and not 127 <= ord(c) < 160 for c in rationale),
                "field_review_rationale_bound")
        pin(item["predecessor"], nullable=True)
        if item["resolves_decision_id"] is not None:
            require(item["predecessor"] is not None and item["resolves_decision_id"] == item["predecessor"]["id"],
                    "field_review_resolution_head_required")
        if item["decision"] == "accept":
            require(item["source_inspection_attested"] and all(x == "satisfied" for x in item["checks"].values()),
                    "field_review_acceptance_checks_required")
    text = canonical(value)
    require(len(text) <= MAX_BYTES, "field_review_request_bound")
    return json.loads(text)
