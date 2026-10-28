"""Closed claim review requests. Model output cannot confer reviewer authority.

Non-detection has a fidelity profile only. Its detection target/window and
task-specific negative-label contract are not implemented by this increment.
"""
from __future__ import annotations

import json

from services import scientific_adjudication_contract as legacy
from services.research_release_manifest import canonical, digest

VERSION = "materials-result-adjudication/2.0.0"
CONTEXT_VERSION = "materials-adjudication-context/2.0.0"
PREVIEW_VERSION = "materials-adjudication-preview/2.0.0"
RECEIPT_VERSION = "materials-adjudication-receipt/2.0.0"
MAX_ITEMS, MAX_BYTES = legacy.MAX_ITEMS, legacy.MAX_BYTES
MAX_RESPONSE_BYTES, MAX_COMMIT_BYTES = legacy.MAX_RESPONSE_BYTES, legacy.MAX_COMMIT_BYTES
SCOPES, REASONS, AUTHORITY = legacy.SCOPES, legacy.REASONS, legacy.AUTHORITY
require, identifier, checksum, request_key = legacy.require, legacy.identifier, legacy.checksum, legacy.request_key
CHECKS = (*legacy.CHECKS, "criterion_and_transition", "source_version_and_location", "result_origin")
LIMITATIONS = (
    "conditions_and_missing_information_remain_as_reported",
    "no_automatic_ml_or_publication_authority",
    "no_imputed_mean_zero_or_ambient_pressure",
    "non_detection_is_not_a_qualified_negative_label",
    "review_does_not_establish_independent_experimental_replication",
)
PROFILES = {
    "reported-tc-fidelity/1.0.0": ("extraction_fidelity", "reported_tc_assertion"),
    "reported-non-detection-fidelity/1.0.0": ("extraction_fidelity", "reported_non_detection_assertion"),
    "experimental-tc-review/1.0.0": ("scientific_result", "paper_supported_experimental_tc"),
}
ITEM_KEYS = (legacy.ITEM_KEYS - {"property_id"}) | {"result_kind", "result_id"}
EVIDENCE_KEYS = ("occurrence_id", "source_revision_id", "capture_id", "bytes_sha256")


def _item(item):
    legacy._object(item, ITEM_KEYS)
    require(item["result_kind"] == "claim", "unsupported_materials_adjudication_target")
    for name in ("decision_id", "subject_id", "result_id"):
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
            and all(c in "\n\t" or ord(c) >= 32 and not 127 <= ord(c) < 160 for c in rationale),
            "bounded_adjudication_rationale_required")
    legacy._object(item["checks"], CHECKS)
    require(all(type(v) is str and v in legacy.CHECK_STATES for v in item["checks"].values()),
            "adjudication_check_state_required")
    require(type(item["source_inspection_attested"]) is bool, "explicit_source_inspection_attestation_required")
    refs = item["evidence_refs"]
    require(type(refs) is list and len(refs) <= 50, "adjudication_evidence_inventory_limit")
    ids = []
    for ref in refs:
        legacy._object(ref, EVIDENCE_KEYS)
        for name in EVIDENCE_KEYS[:-1]: identifier(ref[name])
        checksum(ref["bytes_sha256"])
        ids.append(ref["occurrence_id"])
    require(ids == sorted(set(ids)), "ordered_unique_adjudication_evidence_required")
    if decision == "accept":
        require(item["source_inspection_attested"] and bool(refs)
                and all(v == "satisfied" for v in item["checks"].values()), "adjudication_acceptance_checks_required")
    require((item["extraction_decision_id"] is not None) == (item["scope"] == "scientific_result" and decision == "accept"),
            "exact_fidelity_dependency_required")
    if item["resolves_decision_id"] is not None:
        require(item["resolves_decision_id"] == item["expected_previous_decision_id"], "adjudication_resolution_head_mismatch")


def validate_request(value):
    try:
        legacy._object(value, ("version", "request_key", "items"))
        require(value["version"] == VERSION, "unsupported_adjudication_request_version")
        request_key(value["request_key"])
        items = value["items"]
        require(type(items) is list and 1 <= len(items) <= MAX_ITEMS, "adjudication_item_limit")
        targets, decisions, refs = set(), {}, 0
        for index, item in enumerate(items):
            _item(item)
            target = item["result_kind"], item["result_id"], item["scope"]
            require(target not in targets and item["decision_id"] not in decisions, "duplicate_adjudication_target")
            targets.add(target); decisions[item["decision_id"]] = index; refs += len(item["evidence_refs"])
        require(refs <= 200, "combined_adjudication_evidence_limit")
        # Scientific acceptance needs a different authenticated account from
        # the fidelity reviewer; both cannot be accepted in one actor's request.
        for item in items:
            require(item["extraction_decision_id"] not in decisions, "independent_fidelity_reviewer_required")
        payload = canonical(value)
        require(len(payload) <= MAX_BYTES, "adjudication_request_byte_limit")
        return json.loads(payload)
    except (TypeError, KeyError, RecursionError, UnicodeError, ValueError) as exc:
        if isinstance(exc, legacy.ScientificAdjudicationError): raise
        raise legacy.ScientificAdjudicationError("invalid_adjudication_request") from None


def preview_binding(request, actor_user_id, actor_grant_id):
    return digest({"version": PREVIEW_VERSION, "request_sha256": digest(request),
                   "actor_user_id": str(actor_user_id), "actor_grant_id": str(actor_grant_id)})
