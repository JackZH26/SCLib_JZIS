"""Synthetic contract tests only; these templates/reviews are not scientific approvals."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from services.priority_releases import PriorityRelease
from services.research_priority import RESOURCES, Assessment, Campaign, digest, evaluate
from tests.test_research_priority import (
    assessment,
    campaign,
    rehash,
    release_payload,
    template_artifact,
)


def pin_synthetic_template(a, c):
    """Pure evaluator fixture, not approval of a scientific action template."""
    item = template_artifact()
    item["content"] = a["action_requirements"]["template"]
    item["sha256"] = digest({k: v for k, v in item.items() if k != "sha256"})
    a["action_requirements"]["template_ref"]["sha256"] = item["sha256"]
    c["action_templates"][item["id"]] = item["sha256"]


@pytest.mark.parametrize(
    "kind,dependency", [("calculation", "structure"), ("measurement", "sample")]
)
def test_dfpt_without_structure_and_measurement_without_sample_cannot_rank(kind, dependency):
    a, c = assessment().model_dump(mode="json"), campaign().model_dump(mode="json")
    requirements = a["action_requirements"]
    requirements["template"]["action_kind"] = kind
    requirements["template"]["prerequisites"][0].update(key=dependency, dependency_kind=dependency)
    requirements["prerequisites"][0].update(key=dependency, status="unknown")
    requirements["dependencies"][0].update(kind=dependency, status="unknown")
    pin_synthetic_template(a, c)
    result = evaluate(Assessment.model_validate(a), Campaign.model_validate(c))
    assert result["eligibility"] == "pending"
    assert result["score_display"] is None
    assert f"critical_prerequisite_unknown:{dependency}" in result["reason_codes"]


def test_separately_scoped_verification_uses_own_prerequisites():
    a, c = assessment().model_dump(mode="json"), campaign().model_dump(mode="json")
    a["action_summary"] = "Synthetic structure-verification task, not DFPT execution"
    requirements = a["action_requirements"]
    requirements["template"].update(
        action_kind="verification",
        scope="Verify whether usable input data exist; no DFPT execution",
    )
    requirements["template"]["prerequisites"][0].update(key="source_data", dependency_kind="data")
    requirements["prerequisites"][0]["key"] = "source_data"
    requirements["dependencies"][0]["kind"] = "data"
    pin_synthetic_template(a, c)
    assert (
        evaluate(Assessment.model_validate(a), Campaign.model_validate(c))["eligibility"]
        == "eligible"
    )


@pytest.mark.parametrize("status", ["unknown", "pending", "blocked"])
@pytest.mark.parametrize("readiness", [0.25, 0.75])
def test_unresolved_critical_input_never_receives_executable_score(status, readiness):
    a = assessment().model_dump(mode="json")
    a["action_requirements"]["prerequisites"][0]["status"] = status
    a["action_requirements"]["dependencies"][0]["status"] = status
    a["readiness"].update(anchor=readiness, lower=readiness, upper=readiness)
    result = evaluate(Assessment.model_validate(a), campaign())
    assert result["eligibility"] == ("ineligible" if status == "blocked" else "pending")
    assert result["score_display"] is None
    assert f"critical_prerequisite_{status}:structure" in result["execution_constraint_reasons"]


@pytest.mark.parametrize("dependency_kind", ["equipment", "sample", "external", "structure"])
@pytest.mark.parametrize("parent_status", ["blocked", "pending", "unknown"])
def test_known_unavailable_critical_dependency_is_ineligible_despite_high_scores(
    dependency_kind, parent_status
):
    a, c = assessment().model_dump(mode="json"), campaign().model_dump(mode="json")
    requirements = a["action_requirements"]
    requirements["template"]["prerequisites"][0]["dependency_kind"] = dependency_kind
    requirements["prerequisites"][0]["status"] = parent_status
    requirements["dependencies"][0].update(kind=dependency_kind, status="blocked")
    for dimension in a["dimensions"].values():
        dimension.update(anchor=100, lower=100, upper=100)
    for key in ("decision_impact", "discrimination", "readiness"):
        a[key].update(anchor=1, lower=1, upper=1)
    pin_synthetic_template(a, c)
    result = evaluate(Assessment.model_validate(a), Campaign.model_validate(c))
    assert result["eligibility"] == "ineligible"
    assert result["score_raw"] is None and result["score_display"] is None
    assert "critical_dependency_blocked:structure-input" in result["execution_constraint_reasons"]


@pytest.mark.parametrize("declaration", ["dependencies", "prerequisites"])
def test_confirmed_block_needs_evidence_not_an_unknown_assertion(declaration):
    a = assessment().model_dump(mode="json")
    a["action_requirements"]["prerequisites"][0]["status"] = "unknown"
    a["action_requirements"][declaration][0].update(status="blocked", evidence=[])
    with pytest.raises(ValidationError, match="needs.*evidence"):
        Assessment.model_validate(a)


@pytest.mark.parametrize("exemption", ["noncritical", "not_applicable"])
def test_only_required_critical_dependencies_are_hard_execution_gates(exemption):
    a, c = assessment().model_dump(mode="json"), campaign().model_dump(mode="json")
    requirements = a["action_requirements"]
    rule = requirements["template"]["prerequisites"][0]
    requirements["dependencies"][0]["status"] = "blocked"
    if exemption == "noncritical":
        rule["critical"] = False
        requirements["prerequisites"][0]["status"] = "blocked"
    else:
        rule["allow_not_applicable"] = True
        requirements["prerequisites"][0]["status"] = "not_applicable"
    pin_synthetic_template(a, c)
    result = evaluate(Assessment.model_validate(a), Campaign.model_validate(c))
    assert result["eligibility"] == "eligible"
    assert not any("blocked" in reason for reason in result["execution_constraint_reasons"])


def test_quarter_readiness_retains_critical_uncertainty_gate():
    a = assessment().model_dump(mode="json")
    a["readiness"].update(anchor=0.25, lower=0.25, upper=0.25)
    result = evaluate(Assessment.model_validate(a), campaign())
    assert result["eligibility"] == "pending"
    assert "readiness_critical_uncertainty" in result["reason_codes"]


@pytest.mark.parametrize("resource", RESOURCES)
def test_all_five_resource_categories_must_be_declared(resource):
    a = assessment().model_dump(mode="json")
    a["action_requirements"]["resources"] = [
        r for r in a["action_requirements"]["resources"] if r["resource"] != resource
    ]
    with pytest.raises(ValidationError):
        Assessment.model_validate(a)


def test_unknown_resource_is_pending_not_zero_or_free():
    a = assessment().model_dump(mode="json")
    a["action_requirements"]["resources"][0].update(applicability="unknown", evidence=[])
    a["costs"] = []
    result = evaluate(Assessment.model_validate(a), campaign())
    assert result["eligibility"] == "pending"
    assert result["a_lower"] is None and result["affordability_lower"] is None
    assert result["score_display"] is None


@pytest.mark.parametrize("resource", ["memory_gib", "human_hours"])
def test_additional_required_resource_must_be_costed_and_budgeted(resource):
    a, c = assessment().model_dump(mode="json"), campaign().model_dump(mode="json")
    requirements = a["action_requirements"]
    requirements["template"]["resource_rules"][resource] = "required"
    declaration = next(item for item in requirements["resources"] if item["resource"] == resource)
    declaration["applicability"] = "required"
    pin_synthetic_template(a, c)
    with pytest.raises(ValidationError, match="costs must exactly cover"):
        Assessment.model_validate(a)
    cost = deepcopy(a["costs"][0])
    cost.update(resource=resource, lower=1, upper=2)
    a["costs"].append(cost)
    result = evaluate(Assessment.model_validate(a), Campaign.model_validate(c))
    assert result["eligibility"] == "ineligible"
    assert f"resource_unavailable:{resource}" in result["reason_codes"]


@pytest.mark.parametrize(
    "mutation",
    [
        "omit_cost",
        "required_na",
        "na_no_evidence",
        "blank_rationale",
        "duplicate_resource",
        "missing_prerequisite",
        "duplicate_prerequisite",
        "duplicate_dependency",
        "orphan_dependency",
        "unresolved_dependency",
        "wrong_dependency_kind",
        "unavailable_satisfied_dependency",
    ],
)
def test_incomplete_or_inconsistent_action_contract_rejected(mutation):
    a = assessment().model_dump(mode="json")
    requirements = a["action_requirements"]
    if mutation == "omit_cost":
        a["costs"] = []
    elif mutation == "required_na":
        requirements["resources"][0]["applicability"] = "not_applicable"
        a["costs"] = []
    elif mutation == "na_no_evidence":
        requirements["resources"][1]["evidence"] = []
    elif mutation == "blank_rationale":
        requirements["resources"][1]["rationale"] = "  "
    elif mutation == "duplicate_resource":
        requirements["resources"][1] = deepcopy(requirements["resources"][0])
    elif mutation == "missing_prerequisite":
        requirements["prerequisites"] = []
    elif mutation == "duplicate_prerequisite":
        requirements["prerequisites"] *= 2
    elif mutation == "duplicate_dependency":
        requirements["dependencies"] *= 2
    elif mutation == "orphan_dependency":
        dependency = deepcopy(requirements["dependencies"][0])
        dependency["id"] = "unused"
        requirements["dependencies"].append(dependency)
    elif mutation == "unresolved_dependency":
        requirements["prerequisites"][0]["dependency_ids"] = ["missing"]
    elif mutation == "wrong_dependency_kind":
        requirements["dependencies"][0]["kind"] = "sample"
    else:
        requirements["dependencies"][0]["status"] = "blocked"
    with pytest.raises(ValidationError):
        Assessment.model_validate(a)


def test_unregistered_template_never_ranked():
    c = campaign().model_dump(mode="json")
    c["action_templates"]["template:test"] = "b" * 64
    result = evaluate(assessment(), Campaign.model_validate(c))
    assert result["eligibility"] == "ineligible"
    assert "action_template_not_registered" in result["reason_codes"]


@pytest.mark.parametrize("mutation", ["prerequisite", "dependency", "resource", "template_version"])
def test_execution_declarations_are_bound_into_action_review(mutation):
    payload = release_payload()
    a = payload["assessments"][0]["assessment"]
    requirements = a["action_requirements"]
    if mutation == "prerequisite":
        requirements["prerequisites"][0]["status"] = "pending"
    elif mutation == "dependency":
        requirements["dependencies"][0]["rationale"] = "Changed input revision"
    elif mutation == "resource":
        requirements["resources"][1]["rationale"] = "Changed applicability basis"
    else:
        requirements["template"]["version"] = "synthetic-2"
    # Rehashing an untrusted manifest cannot refresh either scientific review.
    with pytest.raises(ValidationError, match="changed after review|inline action template"):
        PriorityRelease.model_validate(rehash(payload))


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "version",
        "future",
        "after_action",
        "before_template",
        "reviewer",
        "unresolved_evidence",
    ],
)
def test_template_review_is_required_versioned_and_traceable(mutation):
    payload = release_payload()
    item = next(item for item in payload["artifacts"] if item["kind"] == "template_review")
    if mutation == "missing":
        payload["artifacts"].remove(item)
    else:
        if mutation == "version":
            item["content"]["template_version"] = "wrong-version"
        elif mutation == "future":
            item["available_at"] = "2026-09-05T12:00:00Z"
        elif mutation == "after_action":
            item["available_at"] = "2026-09-01T12:00:00Z"
        elif mutation == "before_template":
            item["available_at"] = "2026-08-31T12:00:00Z"
        elif mutation == "reviewer":
            item["content"]["reviewer_id"] = " "
        else:
            item["content"]["evidence"][0]["id"] = "missing-source"
        item["sha256"] = digest({k: v for k, v in item.items() if k != "sha256"})
        payload["assessments"][0]["assessment"]["action_requirements"]["template_review"][
            "sha256"
        ] = item["sha256"]
    with pytest.raises(ValidationError):
        PriorityRelease.model_validate(rehash(payload))


def test_old_bundle_is_fail_closed_not_implicitly_approved():
    payload = release_payload()
    del payload["assessments"][0]["assessment"]["action_requirements"]
    with pytest.raises(ValidationError):
        PriorityRelease.model_validate(rehash(payload))


def test_refreshing_action_hash_without_a_new_assessment_review_fails():
    payload = release_payload()
    a = payload["assessments"][0]["assessment"]
    a["action_requirements"]["prerequisites"][0]["status"] = "pending"
    action = next(item for item in payload["artifacts"] if item["kind"] == "action")
    from services.research_priority import action_specification

    action["content"]["action_requirements_hash"] = digest(a["action_requirements"])
    action["content"]["assessment_action_hash"] = digest(
        action_specification(Assessment.model_validate(a))
    )
    action["sha256"] = digest({k: v for k, v in action.items() if k != "sha256"})
    a["action"]["sha256"] = action["sha256"]
    with pytest.raises(ValidationError, match="missing/broken assessment review"):
        PriorityRelease.model_validate(rehash(payload))


@pytest.mark.parametrize(
    "polarity,reason",
    [
        ("supporting", "assessed_support"),
        ("opposing", "adverse_evidence"),
        ("mixed", "mixed_evidence"),
        ("neutral", "neutral_evidence"),
        ("unknown", "evidence_polarity_unclassified"),
    ],
)
def test_low_conservative_bound_is_not_automatically_adverse(polarity, reason):
    a = assessment().model_dump(mode="json")
    a["dimensions"]["stability"].update(anchor=75, lower=25, upper=100, evidence_polarity=polarity)
    result = evaluate(Assessment.model_validate(a), campaign())
    explanation = result["contributions"]["dimension_explanations"]["stability"]
    assert explanation["reason_codes"] == [reason, "uncertainty_discount"]
    assert explanation["anchor_contribution"] == 225
    assert explanation["uncertainty_discount"] == -450
    assert (
        explanation["anchor_contribution"] + explanation["uncertainty_discount"]
        == result["contributions"]["dimensions"]["stability"]
    )


def test_unknown_support_cannot_be_declared_adverse():
    a = assessment().model_dump(mode="json")
    a["dimensions"]["stability"].update(
        status="unknown",
        anchor=None,
        lower=0,
        upper=100,
        missing_reason="Missing",
        evidence=[],
        evidence_polarity="opposing",
    )
    with pytest.raises(ValidationError):
        Assessment.model_validate(a)


def test_physical_zero_is_not_execution_veto_and_negative_control_not_negative_outcome():
    a = assessment().model_dump(mode="json")
    a["dimensions"]["stability"].update(anchor=0, lower=0, upper=0, evidence_polarity="opposing")
    result = evaluate(Assessment.model_validate(a), campaign())
    assert result["eligibility"] == "eligible"
    assert result["score_display"] is not None
    a["role"] = "negative_control"
    assert evaluate(Assessment.model_validate(a), campaign())["eligibility"] == "reference_only"


@pytest.mark.parametrize("role", ["reference_anchor", "benchmark_control", "negative_control"])
def test_all_reference_roles_remain_unranked(role):
    a = assessment().model_dump(mode="json")
    a["role"] = role
    result = evaluate(Assessment.model_validate(a), campaign())
    assert result["eligibility"] == "reference_only" and result["score_display"] is None


@pytest.mark.parametrize(
    "target,eligibility", [("mismatch", "ineligible"), ("unresolved", "pending")]
)
def test_target_gates_cannot_be_offset_by_complete_prerequisites(target, eligibility):
    a = assessment().model_dump(mode="json")
    a["target_fit"] = target
    result = evaluate(Assessment.model_validate(a), campaign())
    assert result["eligibility"] == eligibility and result["score_display"] is None
