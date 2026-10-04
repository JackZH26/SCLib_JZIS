"""Closed archival-return counterexamples; test proposals are synthetic."""
from uuid import uuid4

import pytest

from services import discovery_feedback_contract as contract


def operation():
    return {"version": contract.REQUEST_VERSION, "request_key": "feedback-test:" + uuid4().hex,
        "operation": "return_evidence", "payload": {
            "design": {"design_id": str(uuid4()), "revision_id": str(uuid4()),
                       "record_sha256": "a" * 64, "next_action_sha256": "b" * 64},
            "evidence": {"kind": "retained_result", "material_id": "mat:comparative-reference", "record_index": 1,
                         "property_id": None, "expected_context_sha256": "c" * 64},
            "findings": "The archival record reports a zero-resistance transition separately from onset.",
            "decision": "redirect", "reason": "Resolve the transition criterion before comparing values.",
            "unknowns": ["Physical sample association is unestablished", "Hc2 derivation method remains unreported"]}}


def link_operation():
    return {"version": contract.REQUEST_VERSION, "request_key": "feedback-link:" + uuid4().hex,
        "operation": "link_follow_up", "payload": {
            "feedback": {"id": str(uuid4()), "record_sha256": "a" * 64},
            "child": {"design_id": str(uuid4()), "revision_id": str(uuid4()), "record_sha256": "b" * 64}}}


def test_snapshot_detaches_research_decision_and_unknowns():
    request = operation()
    captured = contract.snapshot(request)
    request["payload"]["unknowns"].append("Changed after source pinning")
    request["payload"]["decision"] = "continue"
    assert captured["payload"]["decision"] == "redirect"
    assert len(captured["payload"]["unknowns"]) == 2


@pytest.mark.parametrize("change", [
    lambda r: r.update(scientific_acceptance=True),
    lambda r: r["payload"].update(calculation_executed=True),
    lambda r: r["payload"].update(physical_association="same_sample"),
    lambda r: r["payload"]["design"].pop("next_action_sha256"),
    lambda r: r["payload"]["design"].update(record_sha256="unknown"),
    lambda r: r["payload"]["evidence"].update(kind="unanchored"),
    lambda r: r["payload"]["evidence"].update(kind="native_property", property_id=str(uuid4()), record_index=None),
    lambda r: r["payload"]["evidence"].update(record_index=True),
    lambda r: r["payload"]["evidence"].update(record_index=5000),
    lambda r: r["payload"].update(decision="accepted"),
    lambda r: r["payload"].update(reason=""),
    lambda r: r["payload"].update(findings="Source\x00text"),
    lambda r: r["payload"].update(unknowns=["Unresolved"] * 2),
    lambda r: r["payload"].update(unknowns=[str(i) for i in range(17)]),
    lambda r: r.update(request_key="not a key"),
])
def test_no_authority_or_execution_fields_and_closed_actual_decision(change):
    request = operation()
    change(request)
    with pytest.raises(contract.DiscoveryFeedbackError):
        contract.validate(request)


def test_cross_material_evidence_and_no_invented_unknowns_are_allowed():
    request = operation()
    request["payload"]["unknowns"] = []
    assert contract.validate(request) is request
    assert contract.validate(link_operation())["operation"] == "link_follow_up"
    assert all(value is False or key in {"canonical_promotions", "scope"} for key, value in contract.AUTHORITY.items())


@pytest.mark.parametrize("change", [
    lambda r: r["payload"].update(parent={}),
    lambda r: r["payload"]["feedback"].update(id="unknown"),
    lambda r: r["payload"]["child"].update(revision=1),
    lambda r: r["payload"]["child"].update(record_sha256="A" * 64),
])
def test_follow_up_requires_exact_closed_saved_child_pin(change):
    request = link_operation()
    change(request)
    with pytest.raises(contract.DiscoveryFeedbackError):
        contract.validate(request)


def test_total_utf8_byte_bound_is_independent_of_each_field_limit():
    request = operation()
    request["payload"].update(findings="研" * 4000, reason="研" * 2000,
                               unknowns=[str(i) + "研" * 999 for i in range(10)])
    with pytest.raises(contract.DiscoveryFeedbackError, match="byte_bound"):
        contract.validate(request)
