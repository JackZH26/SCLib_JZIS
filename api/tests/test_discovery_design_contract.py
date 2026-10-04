"""Meaningful request counterexamples; all research content is synthetic."""
from copy import deepcopy
from uuid import uuid4

import pytest

from services import discovery_design_contract as contract


def design():
    units = {"cpu_hours": "core-hour", "gpu_hours": "gpu-hour", "memory": "GiB", "storage": "GiB", "human_hours": "person-hour"}
    return {"host_label": "Synthetic MgB2 host hypothesis", "state_label": "Proposed substituted state",
        "modifications": [{"kind": "substitution", "parameters": "Specify a synthetic site and occupancy for source review"}],
        "target_conditions": {"pressure": {"kind": "unspecified", "raw_gpa": None}, "temperature_k": None},
        "pairing_hypothesis": "unresolved", "hypothesis": "Synthetic proposal only: source review may constrain the site model.",
        "next_action": {"kind": "source_review", "question": "Does the inspected source specify the substituted site and composition?",
            "prerequisites": ["Inspect source and supplement with a page locator"],
            "outcomes": [{"observation": "Source supplies an explicit site and composition", "decision": "continue"},
                         {"observation": "Source supplies no resolved site assignment", "decision": "redirect"}],
            "budget": [{"resource": resource, "status": "unknown", "raw_upper": None, "unit": unit} for resource, unit in units.items()]}}


def operation(kind="propose", *, baseline=None, parent=None):
    payload = {"baseline": baseline or {"kind": "unanchored", "material_id": None, "record_index": None,
        "property_id": None, "expected_context_sha256": "0" * 64}, "design": design(), "parent": parent}
    return {"version": contract.REQUEST_VERSION, "request_key": "design-test:" + uuid4().hex,
            "operation": kind, "payload": payload}


def test_snapshot_detaches_entire_hypothesis_before_async_use():
    request = operation()
    captured = contract.snapshot(request)
    request["payload"]["design"]["modifications"][0]["parameters"] = "Changed after request pinning"
    assert captured["payload"]["design"] != request["payload"]["design"]
    assert captured["payload"]["baseline"] == request["payload"]["baseline"]


@pytest.mark.parametrize("change", [
    lambda r: r.update(scientific_acceptance=True),
    lambda r: r["payload"].update(predicted_tc=300),
    lambda r: r["payload"]["design"].update(stability="approved"),
    lambda r: r["payload"]["baseline"].update(sample_context={"parent": "MgB2"}),
    lambda r: r["payload"]["design"]["next_action"].update(outcomes=[{"observation": "Works", "decision": "continue"}]),
    lambda r: r["payload"]["design"]["next_action"]["outcomes"][1].update(observation="Source supplies an explicit site and composition"),
    lambda r: r["payload"]["design"]["next_action"]["outcomes"][1].update(decision="continue"),
    lambda r: r["payload"]["design"]["next_action"]["budget"][0].update(raw_upper="0"),
    lambda r: r["payload"]["design"]["next_action"].update(budget=[]),
    lambda r: r["payload"]["design"]["next_action"]["budget"][0].update(resource=[]),
    lambda r: r["payload"]["design"]["target_conditions"]["pressure"].update(kind="specified", raw_gpa="1e-999"),
    lambda r: r["payload"]["design"]["target_conditions"].update(temperature_k="NaN"),
    lambda r: r["payload"]["design"]["target_conditions"].update(temperature_k="1e999"),
    lambda r: r["payload"]["design"]["target_conditions"].update(temperature_k="٣٠٠"),
    lambda r: r["payload"]["design"]["target_conditions"]["pressure"].update(kind="ambient", raw_gpa="0"),
    lambda r: r["payload"]["design"].update(modifications=[{"kind": "doping", "parameters": "Synthetic"}] * 9),
    lambda r: r["payload"]["design"].update(host_label="private\x00text"),
])
def test_closed_semantic_counterexamples(change):
    request = operation()
    change(request)
    with pytest.raises(contract.DiscoveryDesignError):
        contract.validate(request)


def test_true_zero_and_unknown_cost_are_distinct_and_pressure_not_inferred():
    request = operation()
    request["payload"]["design"]["target_conditions"] = {"pressure": {"kind": "specified", "raw_gpa": "0"}, "temperature_k": "0"}
    request["payload"]["design"]["next_action"]["budget"][0].update(status="estimated", raw_upper="0")
    contract.validate(request)
    budget = request["payload"]["design"]["next_action"]["budget"]
    assert budget[0]["raw_upper"] == "0" and budget[1]["raw_upper"] is None
    assert request["payload"]["baseline"]["kind"] == "unanchored"


def test_parent_requires_revision_identity_and_exact_digest():
    request = operation(parent={"design_id": str(uuid4()), "revision_id": str(uuid4()), "record_sha256": "a" * 64})
    contract.validate(request)
    changed = deepcopy(request)
    changed["payload"]["parent"]["record_sha256"] = "unknown"
    with pytest.raises(contract.DiscoveryDesignError):
        contract.validate(changed)
