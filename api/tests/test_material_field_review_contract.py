"""Finite request boundaries, never synthetic scientific acceptance."""
from copy import deepcopy
from uuid import uuid4

import pytest

from services import material_field_review_contract as contract
from services.source_property_pending import SourcePropertyError


def valid():
    item = {"target_id": str(uuid4()), "target_sha256": "a"*64, "field_id": "tc_criterion",
        "association": None, "expression": {"id": str(uuid4()), "record_sha256": "b"*64, "projection_sha256": "c"*64},
        "tc_expression": None, "source_identity": {"paper_id": "arxiv:synthetic", "work_id": None},
        "component": {"kind": "condition", "index": 0, "field_id": "criterion_statement", "role": "reported_result_condition"},
        "expected_subject_sha256": "d"*64, "expected_candidate_sha256": "e"*64,
        "expected_missingness_sha256": "f"*64, "expected_tuple_sha256": "1"*64,
        "decision": "accept", "checks": {k: "satisfied" for k in contract.CHECKS}, "source_inspection_attested": True,
        "rationale": "Synthetic source-scoped fidelity fixture only.", "predecessor": None, "resolves_decision_id": None}
    return {"version": contract.VERSION, "profile_version": contract.PROFILE, "request_key": "synthetic-review:1", "items": [item]}


def test_closed_request_detaches_and_keeps_lexical_metadata():
    value = valid()
    detached = contract.validate(value)
    assert detached == value and detached is not value and detached["items"][0] is not value["items"][0]


@pytest.mark.parametrize("key,value", [("decision", None), ("decision", "scientific_approval"),
    ("source_inspection_attested", 1), ("source_inspection_attested", False),
    ("expected_subject_sha256", "x"*64), ("expected_candidate_sha256", "A"*64),
    ("field_id", "lambda_eph"), ("rationale", "short"), ("rationale", "x"*1001)])
def test_invalid_acceptance_or_field_is_refused(key, value):
    request = valid()
    request["items"][0][key] = value
    with pytest.raises(SourcePropertyError):
        contract.validate(request)


@pytest.mark.parametrize("key,value", [("kind", "study_extent"), ("index", True), ("index", 0.0), ("index", 8),
    ("role", "study_extent"), ("role", None), ("field_id", "pressure_gpa")])
def test_component_index_role_and_field_are_exact(key, value):
    request = valid()
    request["items"][0]["component"][key] = value
    with pytest.raises(SourcePropertyError):
        contract.validate(request)


def test_bounds_and_duplicate_targets_are_not_silently_trimmed():
    for change in (lambda r: r.update(extra=True), lambda r: r.update(items=[]),
                   lambda r: r["items"].append(deepcopy(r["items"][0])),
                   lambda r: r["items"][0]["checks"].update(extra="satisfied"),
                   lambda r: r["items"][0]["expression"].update(extra=True)):
        request = valid()
        change(request)
        with pytest.raises(SourcePropertyError):
            contract.validate(request)


def test_unresolved_checks_can_request_clarification_but_cannot_accept():
    request = valid()
    request["items"][0]["checks"][contract.CHECKS[0]] = "unresolved"
    with pytest.raises(SourcePropertyError):
        contract.validate(request)
    request["items"][0]["decision"] = "request_clarification"
    request["items"][0]["source_inspection_attested"] = False
    assert contract.validate(request) == request


def test_tc_companion_is_only_for_standalone_method():
    req = valid()
    req["items"][0]["tc_expression"] = deepcopy(req["items"][0]["expression"])
    with pytest.raises(SourcePropertyError, match="companion_scope"):
        contract.validate(req)
    item = req["items"][0]
    item.update(field_id="measurement_method", component={"kind": "value", "index": None,
        "field_id": "method_statement", "role": None})
    assert contract.validate(req) == req
    item["tc_expression"] = None
    with pytest.raises(SourcePropertyError, match="companion_scope"):
        contract.validate(req)
