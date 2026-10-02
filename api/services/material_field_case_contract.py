"""Closed pending field-case operations; no scientific interpretation."""
from __future__ import annotations

from services.research_release_manifest import canonical
from services.source_property_pending import checksum, identifier, request_key, require

VERSION = "material-field-case/1.0.0"
REQUEST_VERSION = "material-field-case-operation/1.0.0"
MAX_BYTES = 32768
MAX_PAGE = 8
AUTHORITY = {"scientific_acceptance": False, "canonical_promotions": 0,
             "selected_result_association": "unestablished", "sample_identity_established": False,
             "phase_identity_established": False, "public_content_release": False,
             "ml_training_approved": False}
FIELDS = ("tc_kelvin", "pressure_gpa", "tc_criterion", "measurement_method", "sample_form",
          "space_group", "crystal_structure", "lattice_a", "lattice_b", "lattice_c",
          "measurement_temperature_k", "atomic_sites", "site_occupancies", "composition_identity",
          "pairing_symmetry", "gap_structure", "is_unconventional", "competing_order",
          "hc2_tesla", "lambda_london_nm", "xi_gl_nm", "lambda_eph", "omega_log_k", "mu_star")
OUTCOMES = ("pending_expression_available", "source_unavailable", "not_found_in_checked_scope",
            "requires_interpretation", "association_unresolved", "current_source_held", "target_changed",
            "external_reference_available", "needs_new_calculation_or_experiment")
REASONS = (*OUTCOMES, "bounded_scope_only", "source_identity_unresolved", "source_identity_proposed",
           "publication_currentness_unverified", "publication_rights_unverified", "expression_superseded",
           "target_fingerprint_changed", "material_not_currently_eligible", "source_lifecycle_held",
           "native_source_binding_unavailable", "unit_requires_review", "value_requires_review",
           "different_source_window", "different_model", "sample_state_unestablished", "no_expression_available")


def closed(value, keys):
    require(type(value) is dict and set(value) == set(keys), "field_case_closed_object_required")


def bounded_text(value, maximum=160):
    require(type(value) is str and 0 < len(value) <= maximum and value == value.strip()
            and not any(ord(c) < 32 for c in value), "field_case_bounded_text_required")
    return value


def predecessor(value):
    if value is not None:
        closed(value, ("id", "record_sha256"))
        identifier(value["id"])
        checksum(value["record_sha256"])


def selector(value):
    closed(value, ("kind", "material_id", "record_index", "entity_id", "expected_context_sha256"))
    require(type(value["kind"]) is str and value["kind"] in {"retained_result", "tc_claim", "event_property"}, "field_case_target_kind")
    bounded_text(value["material_id"], 100)
    checksum(value["expected_context_sha256"])
    if value["kind"] == "retained_result":
        require(type(value["record_index"]) is int and 0 <= value["record_index"] < 5000
                and value["entity_id"] is None, "field_case_record_selector")
    else:
        require(value["record_index"] is None, "field_case_native_selector")
        identifier(value["entity_id"])


def validate(request):
    closed(request, ("version", "request_key", "operation", "payload"))
    require(request["version"] == REQUEST_VERSION, "field_case_request_version")
    request_key(request["request_key"])
    op, p = request["operation"], request["payload"]
    require(type(op) is str and op in {"target", "association", "attempt"}, "field_case_operation")
    if op == "target":
        closed(p, ("field_id", "target"))
        require(p["field_id"] in FIELDS, "field_case_field_registry")
        selector(p["target"])
    else:
        closed(p, (("target_id", "target_sha256", "expression_revision_id", "expression_record_sha256",
                    "source_identity", "action", "predecessor") if op == "association" else
                   ("target_id", "target_sha256", "outcome", "reason_codes", "checked_scope", "expression_pins", "predecessor")))
        identifier(p["target_id"])
        checksum(p["target_sha256"])
        predecessor(p["predecessor"])
        if op == "association":
            identifier(p["expression_revision_id"])
            checksum(p["expression_record_sha256"])
            require(type(p["action"]) is str and p["action"] in {"propose", "withdraw"}, "field_case_association_action")
            closed(p["source_identity"], ("paper_id", "work_id"))
            if p["source_identity"]["paper_id"] is not None:
                bounded_text(p["source_identity"]["paper_id"], 100)
            if p["source_identity"]["work_id"] is not None:
                identifier(p["source_identity"]["work_id"])
            require(p["action"] != "withdraw" or p["predecessor"] is not None, "field_case_withdraw_predecessor")
        else:
            require(p["outcome"] in OUTCOMES, "field_case_outcome_registry")
            require(type(p["reason_codes"]) is list and 1 <= len(p["reason_codes"]) <= 16
                    and all(type(v) is str and v in REASONS for v in p["reason_codes"])
                    and len(set(p["reason_codes"])) == len(p["reason_codes"]), "field_case_reason_registry")
            scope = p["checked_scope"]
            closed(scope, ("source_ids", "fulltext_checked", "supplement_checked", "scope_label"))
            require(type(scope["source_ids"]) is list and len(scope["source_ids"]) <= 8
                    and all(type(v) is str for v in scope["source_ids"])
                    and len(set(scope["source_ids"])) == len(scope["source_ids"]), "field_case_source_scope_bound")
            for v in scope["source_ids"]:
                bounded_text(v)
            bounded_text(scope["scope_label"], 500)
            require(type(scope["fulltext_checked"]) is bool and type(scope["supplement_checked"]) is bool,
                    "field_case_declared_check_required")
            require(scope["source_ids"] or not scope["fulltext_checked"] and not scope["supplement_checked"],
                    "field_case_empty_scope_not_inspected")
            require(type(p["expression_pins"]) is list and len(p["expression_pins"]) <= 8,
                    "field_case_expression_pin_bound")
            ids = []
            for pin in p["expression_pins"]:
                closed(pin, ("revision_id", "record_sha256"))
                ids.append(str(identifier(pin["revision_id"])))
                checksum(pin["record_sha256"])
            require(len(set(ids)) == len(ids), "field_case_duplicate_expression_pin")
            require(p["outcome"] != "pending_expression_available" or ids, "field_case_expression_required")
    require(len(canonical(request)) <= MAX_BYTES, "field_case_operation_bound")
    return request
