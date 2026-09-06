"""Deterministic, conservative research-priority policy. Never an SC probability.

This pure evaluator does not establish evidence truth or authorize publication.
The release verifier performs reference/cutoff/review checks; a curator must pin
the verified release hash in server configuration before it can be served.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

POLICY_VERSION = "RPS-v1.2"
ACTION_CONTRACT_VERSION = "rps-action-contract/1"
DIMENSIONS = (
    "stability",
    "electronic",
    "pairing",
    "coherence",
    "geometry",
    "competing_order",
)
PROFILES = {
    "common": (20, 20, 25, 15, 10, 10),
    "epc_hydride": (20, 15, 35, 10, 10, 10),
    "layered_correlated": (20, 20, 20, 15, 15, 10),
    "multiband": (20, 20, 30, 15, 5, 10),
    "flatband": (15, 15, 20, 25, 15, 10),
}
POLICY = {
    "version": POLICY_VERSION,
    "dimensions": DIMENSIONS,
    "profiles_percent": PROFILES,
    "common_fraction": 0.5,
    "pga_weights": [0.5, 0.3, 0.2],
    "offset": 1000,
    "scale": 90,
    "rounding": "nearest_50_half_up",
    "physical_policy": "fixed_denominator_lower_bound",
    "affordability_upper_cost_thresholds": [0.1, 0.25, 0.5, 1],
    "affordability_values": [1, 0.75, 0.5, 0.25],
    "eligibility": "reviewable_action_contract_positive_D_T_ready_prerequisites_complete_resources",
    "action_contract_version": ACTION_CONTRACT_VERSION,
    "critical_block_policy": "confirmed_block_ineligible_unresolved_pending",
}


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


POLICY_HASH = digest(POLICY)
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Nonnegative = Annotated[Number, Field(ge=0)]
Identifier = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Resource = Literal["cpu_core_hours", "gpu_hours", "memory_gib", "storage_gib", "human_hours"]
RESOURCES = ("cpu_core_hours", "gpu_hours", "memory_gib", "storage_gib", "human_hours")
ActionKind = Literal["verification", "calculation", "conversion", "measurement"]
DependencyKind = Literal[
    "structure", "sample", "equipment", "software", "data", "external", "other"
]
Explanation = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Reference(Contract):
    id: Identifier
    sha256: Hash


class Dimension(Contract):
    status: Literal["assessed", "unknown"]
    anchor: Number | None
    lower: Number
    upper: Number
    rule_id: Identifier
    rationale: Annotated[str, Field(min_length=1, max_length=4000)]
    evidence: list[Reference] = Field(default_factory=list, max_length=100)
    missing_reason: str | None = None
    evidence_polarity: Literal["supporting", "opposing", "mixed", "neutral", "unknown"] = "unknown"

    @model_validator(mode="after")
    def validate_range(self) -> Dimension:
        anchors = {0, 25, 50, 75, 100}
        if self.lower not in anchors or self.upper not in anchors:
            raise ValueError("physical bounds must use the five common anchors")
        if self.status == "unknown":
            if (self.anchor, self.lower, self.upper) != (None, 0, 100) or not self.missing_reason:
                raise ValueError("unknown requires null anchor, [0,100], and missing_reason")
            if self.evidence_polarity != "unknown":
                raise ValueError("unknown support must not be labelled adverse or supportive")
        elif (
            self.anchor not in anchors
            or not self.lower <= self.anchor <= self.upper
            or not self.evidence
            or self.missing_reason is not None
        ):
            raise ValueError("assessed dimension requires ordered anchors and evidence")
        return self


class ActionAnchor(Contract):
    anchor: Number
    lower: Number
    upper: Number
    rationale: Annotated[str, Field(min_length=1, max_length=4000)]
    evidence: list[Reference] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_range(self) -> ActionAnchor:
        if any(v not in {0, 0.25, 0.5, 0.75, 1} for v in (self.lower, self.anchor, self.upper)):
            raise ValueError("action anchors must use quarter steps")
        if not self.lower <= self.anchor <= self.upper:
            raise ValueError("action anchor must lie within bounds")
        return self


class Cost(Contract):
    resource: Resource
    lower: Nonnegative
    upper: Nonnegative | None
    basis: Annotated[str, Field(min_length=1, max_length=2000)]
    evidence: list[Reference] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def ordered(self) -> Cost:
        if self.upper is not None and self.lower > self.upper:
            raise ValueError("cost lower exceeds upper")
        return self


class Outcome(Contract):
    observation: Annotated[str, Field(min_length=1, max_length=2000)]
    decision: Annotated[str, Field(min_length=1, max_length=2000)]


class PrerequisiteRule(Contract):
    key: Identifier
    description: Explanation
    dependency_kind: DependencyKind
    critical: bool = Field(strict=True)
    allow_not_applicable: bool = Field(default=False, strict=True)


class ActionTemplate(Contract):
    schema_version: Literal["rps-action-template/1"] = "rps-action-template/1"
    version: Identifier
    title: Explanation
    action_kind: ActionKind
    scope: Explanation
    prerequisites: list[PrerequisiteRule] = Field(max_length=30)
    prerequisite_completeness_rationale: Explanation
    resource_rules: dict[Resource, Literal["required", "optional", "not_applicable"]]

    @model_validator(mode="after")
    def complete(self):
        if set(self.resource_rules) != set(RESOURCES):
            raise ValueError("template must explicitly address all five resource categories")
        if "required" not in self.resource_rules.values():
            raise ValueError("template must identify at least one costed required resource")
        if len({rule.key for rule in self.prerequisites}) != len(self.prerequisites):
            raise ValueError("duplicate template prerequisite")
        return self


class ActionDependency(Contract):
    id: Identifier
    kind: DependencyKind
    status: Literal["available", "pending", "blocked", "unknown"]
    rationale: Explanation
    evidence: list[Reference] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def supported_availability(self):
        if self.status in {"available", "blocked"} and not self.evidence:
            raise ValueError("available/blocked dependency needs traceable evidence")
        return self


class PrerequisiteDeclaration(Contract):
    key: Identifier
    status: Literal["satisfied", "pending", "blocked", "unknown", "not_applicable"]
    rationale: Explanation
    evidence: list[Reference] = Field(default_factory=list, max_length=100)
    dependency_ids: list[Identifier] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def supported_status(self):
        if self.status in {"satisfied", "blocked", "not_applicable"} and not self.evidence:
            raise ValueError("satisfied/blocked/not-applicable prerequisite needs evidence")
        if len(set(self.dependency_ids)) != len(self.dependency_ids):
            raise ValueError("duplicate prerequisite dependency")
        return self


class ResourceDeclaration(Contract):
    resource: Resource
    applicability: Literal["required", "unknown", "not_applicable"]
    rationale: Explanation
    evidence: list[Reference] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def supported_applicability(self):
        if self.applicability != "unknown" and not self.evidence:
            raise ValueError("resource applicability needs reviewable evidence")
        return self


class ActionRequirements(Contract):
    schema_version: Literal["rps-action-contract/1"] = ACTION_CONTRACT_VERSION
    template_ref: Reference
    template_review: Reference
    template: ActionTemplate
    prerequisites: list[PrerequisiteDeclaration] = Field(max_length=30)
    dependencies: list[ActionDependency] = Field(max_length=100)
    resources: list[ResourceDeclaration] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete(self):
        rules = {rule.key: rule for rule in self.template.prerequisites}
        declared = {item.key: item for item in self.prerequisites}
        if len(declared) != len(self.prerequisites) or set(declared) != set(rules):
            raise ValueError("every template prerequisite must be declared exactly once")
        dependencies = {item.id: item for item in self.dependencies}
        if len(dependencies) != len(self.dependencies):
            raise ValueError("duplicate action dependency")
        used = set()
        for key, item in declared.items():
            rule = rules[key]
            if item.status == "not_applicable" and not rule.allow_not_applicable:
                raise ValueError("template does not permit skipping this prerequisite")
            if not set(item.dependency_ids) <= set(dependencies):
                raise ValueError("unresolved prerequisite dependency")
            used.update(item.dependency_ids)
            linked = [dependencies[identifier] for identifier in item.dependency_ids]
            if item.status == "satisfied" and (
                not linked
                or not any(dep.kind == rule.dependency_kind for dep in linked)
                or any(dep.status != "available" for dep in linked)
            ):
                raise ValueError("satisfied prerequisite requires matching available dependencies")
        if used != set(dependencies):
            raise ValueError("orphan dependency is not covered by a prerequisite")
        resources = {item.resource: item for item in self.resources}
        if set(resources) != set(RESOURCES) or len(resources) != len(self.resources):
            raise ValueError("all resource categories must be declared exactly once")
        for key, item in resources.items():
            rule = self.template.resource_rules[key]
            if rule == "required" and item.applicability == "not_applicable":
                raise ValueError("a template-required resource cannot be omitted")
            if rule == "not_applicable" and item.applicability != "not_applicable":
                raise ValueError("resource use is outside the reviewed template scope")
        return self


class Assessment(Contract):
    schema_version: Literal["rps-assessment/1.2"] = "rps-assessment/1.2"
    id: Identifier
    revision: Annotated[int, Field(strict=True, ge=1)]
    material: Reference
    state: Reference
    action: Reference
    profile_assignment: Reference
    formula: Annotated[str, Field(min_length=1, max_length=200)]
    family: Annotated[str, Field(min_length=1, max_length=100)]
    state_summary: Annotated[str, Field(min_length=1, max_length=1000)]
    action_summary: Annotated[str, Field(min_length=1, max_length=1000)]
    role: Literal[
        "new_candidate",
        "conditional_candidate",
        "mechanism_anchor",
        "reference_anchor",
        "benchmark_control",
        "negative_control",
    ]
    target_fit: Literal["matches", "approved_conversion", "mismatch", "unresolved"]
    problem_resolved: bool = Field(strict=True, default=False)
    dimensions: dict[str, Dimension]
    decision_impact: ActionAnchor
    discrimination: ActionAnchor
    readiness: ActionAnchor
    action_requirements: ActionRequirements
    outcomes: list[Outcome] = Field(min_length=2, max_length=10)
    costs: list[Cost] = Field(max_length=5)

    @model_validator(mode="after")
    def complete(self) -> Assessment:
        if set(self.dimensions) != set(DIMENSIONS):
            raise ValueError("exactly six physical dimensions required; explicitly mark unknown")
        if len({c.resource for c in self.costs}) != len(self.costs):
            raise ValueError("duplicate required resource")
        required = {
            item.resource
            for item in self.action_requirements.resources
            if item.applicability == "required"
        }
        if {cost.resource for cost in self.costs} != required:
            raise ValueError(
                "costs must exactly cover declared required resources; unknown is not zero"
            )
        if len({o.decision.strip() for o in self.outcomes}) < 2:
            raise ValueError("action outcomes must change a decision")
        if len({o.observation.strip() for o in self.outcomes}) != len(self.outcomes):
            raise ValueError("action outcomes must be distinct")
        return self


class Campaign(Contract):
    id: Identifier
    version: Identifier
    objective: Annotated[str, Field(min_length=1, max_length=4000)]
    target_pressure_max_gpa: Nonnegative
    budget: dict[Resource, Nonnegative]
    profile_mixes: dict[Identifier, dict[str, Nonnegative]]
    dimension_rules: dict[str, Identifier]
    action_templates: dict[Identifier, Hash]

    @model_validator(mode="after")
    def fixed_mixes(self) -> Campaign:
        if set(self.dimension_rules) != set(DIMENSIONS):
            raise ValueError("campaign must freeze six scoring rubric references")
        if not self.profile_mixes:
            raise ValueError("campaign must fix profile assignments before scoring")
        if not self.action_templates:
            raise ValueError("campaign must pin reviewed action-template digests")
        for mix in self.profile_mixes.values():
            if not mix or not set(mix) <= set(PROFILES):
                raise ValueError("unknown/empty profile")
            if sum(Decimal(str(v)) for v in mix.values()) != 1:
                raise ValueError("profile proportions must sum exactly to 1")
        return self


def effective_weights(campaign: Campaign, assignment_id: str) -> dict[str, Decimal]:
    mix = campaign.profile_mixes[assignment_id]
    return {
        dimension: (
            Decimal(PROFILES["common"][i])
            + sum(
                Decimal(str(fraction)) * PROFILES[profile][i] for profile, fraction in mix.items()
            )
        )
        / 200
        for i, dimension in enumerate(DIMENSIONS)
    }


def _affordability(ratio: Decimal) -> Decimal:
    for threshold, value in ((".1", "1"), (".25", ".75"), (".5", ".5"), ("1", ".25")):
        if ratio <= Decimal(threshold):
            return Decimal(value)
    return Decimal(0)


def round_score(raw: Decimal) -> int:
    return int((raw / 50).quantize(Decimal(1), rounding=ROUND_HALF_UP) * 50)


def action_specification(assessment: Assessment) -> dict:
    """All mutable execution declarations are bound into the reviewed action."""
    return {
        "summary": assessment.action_summary,
        "outcomes": [item.model_dump(mode="json") for item in assessment.outcomes],
        "costs": [item.model_dump(mode="json") for item in assessment.costs],
        "action_requirements": assessment.action_requirements.model_dump(mode="json"),
    }


def dimension_explanation(value: Dimension, weight: Decimal) -> dict:
    if value.status == "unknown":
        return {
            "evidence_polarity": "unknown",
            "reason_codes": ["missing_support"],
            "anchor_contribution": None,
            "uncertainty_discount": None,
            "missing_support_contribution": float(-2250 * weight),
        }
    reasons = [
        {
            "opposing": "adverse_evidence",
            "mixed": "mixed_evidence",
            "supporting": "assessed_support",
            "neutral": "neutral_evidence",
            "unknown": "evidence_polarity_unclassified",
        }[value.evidence_polarity]
    ]
    if value.lower < value.anchor:
        reasons.append("uncertainty_discount")
    return {
        "evidence_polarity": value.evidence_polarity,
        "reason_codes": reasons,
        "anchor_contribution": float(45 * weight * (Decimal(str(value.anchor)) - 50)),
        "uncertainty_discount": float(
            45 * weight * (Decimal(str(value.lower)) - Decimal(str(value.anchor)))
        ),
        "missing_support_contribution": 0.0,
    }


def evaluate(assessment: Assessment, campaign: Campaign) -> dict:
    """Return derived values. A non-null score still requires release approval."""
    weights = effective_weights(campaign, assessment.profile_assignment.id)
    dl = Decimal(str(assessment.decision_impact.lower))
    tl = Decimal(str(assessment.discrimination.lower))
    rl = Decimal(str(assessment.readiness.lower))
    p_lower = sum(weights[k] * Decimal(str(v.lower)) for k, v in assessment.dimensions.items())
    p_upper = sum(weights[k] * Decimal(str(v.upper)) for k, v in assessment.dimensions.items())
    coverage = sum(weights[k] for k, v in assessment.dimensions.items() if v.status == "assessed")
    reasons: list[str] = []
    pending: list[str] = []
    requirements = assessment.action_requirements
    if (
        campaign.action_templates.get(requirements.template_ref.id)
        != requirements.template_ref.sha256
    ):
        reasons.append("action_template_not_registered")
    prerequisite_rules = {rule.key: rule for rule in requirements.template.prerequisites}
    dependencies = {item.id: item for item in requirements.dependencies}
    for prerequisite in requirements.prerequisites:
        if (
            not prerequisite_rules[prerequisite.key].critical
            or prerequisite.status == "not_applicable"
        ):
            continue
        if prerequisite.status == "blocked":
            reasons.append(f"critical_prerequisite_blocked:{prerequisite.key}")
        elif prerequisite.status in {"pending", "unknown"}:
            pending.append(f"critical_prerequisite_{prerequisite.status}:{prerequisite.key}")
        # A vague parent status must not hide a known unavailable required input.
        for identifier in prerequisite.dependency_ids:
            if dependencies[identifier].status == "blocked":
                reason = f"critical_dependency_blocked:{identifier}"
                if reason not in reasons:
                    reasons.append(reason)
    for resource in requirements.resources:
        if resource.applicability == "unknown":
            pending.append(f"resource_applicability_unknown:{resource.resource}")
    if assessment.target_fit == "mismatch":
        reasons.append("target_mismatch")
    elif assessment.target_fit == "unresolved":
        pending.append("target_unresolved")
    if assessment.problem_resolved:
        reasons.append("problem_already_resolved")
    if dl == 0 or tl == 0:
        reasons.append("no_supported_decision_gain")
    if rl == 0:
        reasons.append("action_not_ready")
    elif rl == Decimal(".25"):
        pending.append("readiness_critical_uncertainty")
    ratios_lower, ratios_upper = [], []
    for cost in assessment.costs:
        budget = campaign.budget.get(cost.resource)
        if budget is None or budget == 0:
            reasons.append(f"resource_unavailable:{cost.resource}")
            continue
        ratios_lower.append(Decimal(str(cost.lower)) / Decimal(str(budget)))
        if cost.upper is None:
            pending.append(f"cost_unknown:{cost.resource}")
        else:
            ratio = Decimal(str(cost.upper)) / Decimal(str(budget))
            ratios_upper.append(ratio)
            if ratio > 1:
                reasons.append(f"budget_exceeded:{cost.resource}")
    budget_known = bool(assessment.costs) and len(ratios_upper) == len(assessment.costs)
    b_lower = _affordability(max(ratios_upper)) if budget_known else None
    b_upper = (
        _affordability(max(ratios_lower))
        if assessment.costs and len(ratios_lower) == len(assessment.costs)
        else None
    )
    g_lower = 100 * dl * tl
    g_upper = (
        100
        * Decimal(str(assessment.decision_impact.upper))
        * Decimal(str(assessment.discrimination.upper))
    )
    a_lower = 50 * (b_lower + rl) if b_lower is not None else None
    a_upper = (
        50 * (b_upper + Decimal(str(assessment.readiness.upper))) if b_upper is not None else None
    )
    reference = assessment.role in {"reference_anchor", "benchmark_control", "negative_control"}
    eligibility = (
        "reference_only"
        if reference
        else "ineligible"
        if reasons
        else "pending"
        if pending
        else "eligible"
    )
    raw = (
        1000 + 45 * p_lower + 27 * g_lower + 18 * a_lower
        if eligibility == "eligible" and a_lower is not None
        else None
    )
    upper = (
        1000 + 45 * p_upper + 27 * g_upper + 18 * a_upper
        if raw is not None and a_upper is not None
        else None
    )
    display = round_score(raw) if raw is not None else None
    physical_deltas = {
        k: float(45 * weights[k] * (Decimal(str(v.lower)) - 50))
        for k, v in assessment.dimensions.items()
    }
    explanations = {
        key: dimension_explanation(value, weights[key])
        for key, value in assessment.dimensions.items()
    }
    return {
        "policy_version": POLICY_VERSION,
        "policy_hash": POLICY_HASH,
        "action_contract_version": ACTION_CONTRACT_VERSION,
        "action_requirements_hash": digest(requirements.model_dump(mode="json")),
        "execution_constraint_reasons": reasons + pending,
        "knowledge_origin": "Inferred",
        "run_kind": "priority_assessment",
        "eligibility": eligibility,
        "reason_codes": reasons + pending,
        "rank_group": "mechanism" if assessment.role == "mechanism_anchor" else "discovery",
        "score_raw": float(raw) if raw is not None else None,
        "score_display": display,
        "score_upper": float(upper) if upper is not None else None,
        "p_lower": float(p_lower),
        "p_upper": float(p_upper),
        "g_lower": float(g_lower),
        "g_upper": float(g_upper),
        "a_lower": float(a_lower) if a_lower is not None else None,
        "a_upper": float(a_upper) if a_upper is not None else None,
        "affordability_lower": float(b_lower) if b_lower is not None else None,
        "affordability_upper": float(b_upper) if b_upper is not None else None,
        "assessed_weight": float(coverage),
        "effective_weights": {k: float(v) for k, v in weights.items()},
        "contributions": {
            "baseline": 5500,
            "physical": float(45 * (p_lower - 50)),
            "gain": float(27 * (g_lower - 50)),
            "action": float(18 * (a_lower - 50)) if a_lower is not None else None,
            "dimensions": physical_deltas,
            "dimension_reasons": {
                key: explanation["reason_codes"][0] for key, explanation in explanations.items()
            },
            "dimension_explanations": explanations,
            "rounding": float(Decimal(display) - raw) if raw is not None else None,
        },
    }
