"""Closed reviewer-authored requests, never inferred scientific authority.

Only these sampled-frequency propositions are implemented in v1. Request prose
is private audit content: it cannot choose an actor, invoke tools, broaden a
profile, grant source rights or alter an original observation.
"""
from __future__ import annotations

import json
import math
import re
from uuid import UUID

from services.research_release_manifest import canonical, digest

VERSION = "scientific-result-adjudication/1.0.0"
CONTEXT_VERSION = "scientific-adjudication-context/1.0.0"
PREVIEW_VERSION = "scientific-adjudication-preview/1.0.0"
RECEIPT_VERSION = "scientific-adjudication-receipt/1.0.0"
MAX_ITEMS = 20
MAX_BYTES = 128 * 1024
# The closed commit envelope adds 105 canonical bytes to a maximum-size
# request. It is independently bounded; the inner request stays at 128 KiB.
MAX_COMMIT_BYTES = MAX_BYTES + 256
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SCOPES = ("extraction_fidelity", "scientific_result")
CHECKS = ("source_match", "quantity_and_units", "state_association", "method_and_scope")
CHECK_STATES = frozenset({"satisfied", "not_applicable", "unresolved"})
LIMITATIONS = (
    "conditions_remain_as_reported",
    "no_automatic_ml_or_publication_authority",
    "not_a_full_zone_stability_assessment",
    "review_does_not_establish_upstream_execution",
    "scope_is_sampled_q_points_only",
)
PROFILES = {
    "native-sampled-frequency-extraction/1.0.0": (
        "extraction_fidelity", "retained_native_sampled_frequency_minimum"),
    "recorded-sampled-frequency-fidelity/1.0.0": (
        "extraction_fidelity", "recorded_sampled_frequency_minimum"),
    "sampled-phonon-minimum-review/1.0.0": (
        "scientific_result", "sampled_frequency_minimum_only"),
}
REASONS = {
    "accept": frozenset({"evidence_and_scope_match"}),
    "reject": frozenset({"source_mismatch", "quantity_or_unit_mismatch", "state_association_mismatch",
                         "method_or_scope_mismatch", "scientific_concern"}),
    "request_clarification": frozenset({"insufficient_evidence", "unresolved_state", "unresolved_method",
                                        "conflicting_evidence"}),
}
ITEM_KEYS = frozenset({
    "decision_id", "subject_id", "property_id", "scope", "profile_version",
    "expected_subject_sha256", "expected_previous_decision_id", "expected_impact_sha256",
    "decision", "reason_code", "rationale", "proposition", "limitations", "checks", "evidence_refs",
    "source_inspection_attested", "resolves_decision_id", "extraction_decision_id",
})
AUTHORITY = {"ml_training_approved": False, "public_release_authorized": False}


class ScientificAdjudicationError(ValueError):
    """Static failure code; do not reflect supplied source or rationale text."""


class ScientificAdjudicationConflict(ScientificAdjudicationError):
    """An exact preview, request identity or decision head no longer matches."""


class ScientificAdjudicationUnavailable(ScientificAdjudicationError):
    """Bounded evidence could not be checked, not a no-decisions result."""


def require(condition, code):
    if not condition:
        raise ScientificAdjudicationError(code)


def identifier(value, *, nullable=False):
    if value is None and nullable:
        return None
    require(type(value) is str, "adjudication_identifier_required")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ScientificAdjudicationError("adjudication_identifier_required") from None
    require(str(parsed) == value, "adjudication_canonical_identifier_required")
    return value


def checksum(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "adjudication_hash_required")
    return value


def request_key(value):
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:+@-]{0,159}", value),
            "adjudication_request_key_required")
    return value


def _object(value, keys):
    require(type(value) is dict and set(value) == set(keys), "closed_adjudication_object_required")


def _item(item):
    _object(item, ITEM_KEYS)
    for name in ("decision_id", "subject_id", "property_id"):
        identifier(item[name])
    for name in ("expected_previous_decision_id", "resolves_decision_id", "extraction_decision_id"):
        identifier(item[name], nullable=True)
    for name in ("expected_subject_sha256", "expected_impact_sha256"):
        checksum(item[name])
    profile = item["profile_version"]
    require(type(profile) is str and profile in PROFILES, "unsupported_adjudication_profile")
    require((item["scope"], item["proposition"]) == PROFILES[profile], "adjudication_profile_scope_mismatch")
    require(item["limitations"] == list(LIMITATIONS), "adjudication_explicit_scope_limitations_required")
    decision, reason = item["decision"], item["reason_code"]
    require(type(decision) is str and decision in REASONS and type(reason) is str and reason in REASONS[decision],
            "adjudication_reason_decision_mismatch")
    rationale = item["rationale"]
    require(type(rationale) is str and 20 <= len(rationale.strip()) <= len(rationale) <= 2000
            and all(char in "\n\t" or ord(char) >= 32 and not 127 <= ord(char) < 160 for char in rationale),
            "bounded_adjudication_rationale_required")
    _object(item["checks"], CHECKS)
    require(all(type(value) is str and value in CHECK_STATES for value in item["checks"].values()),
            "adjudication_check_state_required")
    require(type(item["source_inspection_attested"]) is bool, "explicit_source_inspection_attestation_required")
    refs = item["evidence_refs"]
    require(type(refs) is list and len(refs) <= 50, "adjudication_evidence_inventory_limit")
    ids = []
    for reference in refs:
        _object(reference, ("artifact_id", "bytes_sha256"))
        ids.append(identifier(reference["artifact_id"]))
        checksum(reference["bytes_sha256"])
    require(ids == sorted(set(ids)), "ordered_unique_adjudication_evidence_required")
    if decision == "accept":
        require(item["source_inspection_attested"] and bool(refs)
                and all(value == "satisfied" for value in item["checks"].values()),
                "adjudication_acceptance_checks_required")
    if item["scope"] == "scientific_result" and decision == "accept":
        require(item["extraction_decision_id"] is not None, "exact_fidelity_dependency_required")
    else:
        require(item["extraction_decision_id"] is None, "unexpected_fidelity_dependency")
    if item["resolves_decision_id"] is not None:
        require(item["resolves_decision_id"] == item["expected_previous_decision_id"],
                "adjudication_resolution_head_mismatch")


def validate_request(value):
    """Bound and detach the full caller request before the first async boundary."""
    try:
        _object(value, ("version", "request_key", "items"))
        require(value["version"] == VERSION, "unsupported_adjudication_request_version")
        request_key(value["request_key"])
        items = value["items"]
        require(type(items) is list and 1 <= len(items) <= MAX_ITEMS, "adjudication_item_limit")
        targets, decisions, references = set(), {}, 0
        for index, item in enumerate(items):
            _item(item)
            target = item["property_id"], item["scope"]
            require(target not in targets and item["decision_id"] not in decisions, "duplicate_adjudication_target")
            targets.add(target)
            decisions[item["decision_id"]] = index
            references += len(item["evidence_refs"])
        require(references <= 200, "combined_adjudication_evidence_limit")
        for index, item in enumerate(items):
            dependency_index = decisions.get(item["extraction_decision_id"])
            if dependency_index is not None:
                dependency = items[dependency_index]
                require(dependency_index < index and dependency["scope"] == "extraction_fidelity"
                        and dependency["decision"] == "accept" and dependency["property_id"] == item["property_id"]
                        and dependency["subject_id"] == item["subject_id"]
                        and dependency["expected_subject_sha256"] == item["expected_subject_sha256"],
                        "ordered_exact_fidelity_dependency_required")
        payload = canonical(value)
        require(len(payload) <= MAX_BYTES, "adjudication_request_byte_limit")
        return json.loads(payload)
    except (TypeError, KeyError, RecursionError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ScientificAdjudicationError):
            raise
        raise ScientificAdjudicationError("invalid_adjudication_request") from None


def loads(payload, *, max_bytes=MAX_BYTES):
    """Reject ambiguous duplicate/nonfinite JSON before profile validation."""
    require(type(max_bytes) is int and max_bytes in {MAX_BYTES, MAX_COMMIT_BYTES}, "adjudication_body_limit_required")
    require(type(payload) is bytes and 0 < len(payload) <= max_bytes, "adjudication_request_byte_limit")
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_adjudication_json_key")
            result[key] = value
        return result
    def finite_float(value):
        number = float(value)
        require(math.isfinite(number), "nonfinite_adjudication_json")
        return number
    try:
        return json.loads(payload, object_pairs_hook=pairs, parse_float=finite_float,
                          parse_constant=lambda _: (_ for _ in ()).throw(ScientificAdjudicationError("nonfinite_adjudication_json")))
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ScientificAdjudicationError):
            raise
        raise ScientificAdjudicationError("invalid_adjudication_json") from None


def preview_binding(request, actor_user_id, actor_grant_id):
    """Actor- and body-bound identity; successful SQL rehearsal supplies validity."""
    return digest({"version": PREVIEW_VERSION, "request_sha256": digest(request),
                   "actor_user_id": str(actor_user_id), "actor_grant_id": str(actor_grant_id)})
