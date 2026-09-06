"""DB-independent legacy Discovery wire contract, shared by pull and API.

Legacy score ranges are deliberately not invented here: scores must be finite
numbers, not numeric strings or booleans. All supported extension fields are
explicit; adding a new producer field requires a reviewed contract change.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[^\s/\\]+$")]
Nonempty = Annotated[str, Field(min_length=1, pattern=r"\S")]
FeedStatus = Literal["ready", "stale", "missing", "invalid"]


class DiscoveryContract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class DiscoveryFilterRule(DiscoveryContract):
    key: Nonempty
    label: Nonempty
    value: str


class DiscoveryCandidate(DiscoveryContract):
    schema_version: Literal["1"] = "1"
    candidate_id: Identifier
    formula: Nonempty
    normalized_formula: str | None = None
    branch: Nonempty
    lane_id: str | None = None
    prototype_family: str | None = None
    candidate_layer: str | None = None
    candidate_quantity_score: float | None = None
    candidate_quality_score: float | None = None
    entry_block_reason: str | None = None
    upgrade_requirements: list[str] = Field(default_factory=list)
    evidence_schema_version: str | None = None
    evidence_quality_score: float | None = None
    literature_verifier_status: str | None = None
    literature_verifier_flags: list[str] = Field(default_factory=list)
    failure_mode_taxonomy: list[str] = Field(default_factory=list)
    synthesis_feasibility_score: float | None = None
    synthesis_feasibility_flags: list[str] = Field(default_factory=list)
    measurement_clarity_score: float | None = None
    correlation_gate_status: str | None = None
    correlation_gate_flags: list[str] = Field(default_factory=list)
    experiment_priority_score: float | None = None
    experiment_readiness: str | None = None
    family_ruleset_id: str | None = None
    validation_recipe_id: str | None = None
    condition_class: str | None = None
    required_condition_vector: list[str] = Field(default_factory=list)
    evidence_level: Nonempty
    checker_status: Nonempty
    public_confidence: Nonempty
    record_role: str | None = None
    claim_level: str | None = None
    next_action: str | None = None
    discovery_score: float | None = None
    mechanism_hypothesis: str | None = None
    risk_tags: list[str] = Field(default_factory=list)
    review_summary: str | None = None
    provenance_summary: str | None = None
    recommended_next_step: str | None = None
    last_reviewed_at_utc: datetime | None = None
    published_at_utc: datetime | None = None
    # Existing, observed upstream extensions: retain rather than silently drop.
    base_discovery_score: float | None = None
    condition_badges: list[str] = Field(default_factory=list)
    display_class: str | None = None
    family_gate_stage: str | None = None
    legacy_candidate_id: str | None = None
    taxonomy_bucket: str | None = None


class DiscoveryResponse(DiscoveryContract):
    schema_version: Literal["1"] = "1"
    page_title: Nonempty
    intro: list[str]
    status: Literal["planned", "active"]
    updated_at_utc: datetime | None = None
    source: str | None = None
    filter_rules: list[DiscoveryFilterRule]
    candidates: list[DiscoveryCandidate]

    @model_validator(mode="after")
    def unique_ids(self) -> DiscoveryResponse:
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate candidate_id")
        if self.status == "active" and not ids:
            raise ValueError("an active feed requires candidates; an empty planned feed must be explicit")
        return self


class DiscoveryCandidateSummary(DiscoveryContract):
    schema_version: Literal["1"] = "1"
    candidate_id: Identifier
    formula: str
    branch: str
    lane_id: str | None = None
    prototype_family: str | None = None
    candidate_layer: str | None = None
    condition_class: str | None = None
    evidence_level: str
    checker_status: str
    public_confidence: str
    evidence_quality_score: float | None = None
    experiment_readiness: str | None = None
    record_role: str | None = None
    claim_level: str | None = None
    next_action: str | None = None
    discovery_score: float | None = None


class DiscoveryVersion(DiscoveryContract):
    data_version: str
    source_status: FeedStatus
    last_successful_at: datetime | None = None
    source_error: Literal["invalid_update", "source_missing"] | None = None


class DiscoveryMetadata(DiscoveryVersion):
    schema_version: Literal["1"] = "1"
    page_title: str
    intro: list[str]
    status: Literal["planned", "active"]
    updated_at_utc: datetime | None = None
    source: str | None = None
    filter_rules: list[DiscoveryFilterRule]
    total_candidates: int
    role_counts: dict[str, int]


class DiscoveryCandidatePage(DiscoveryVersion):
    schema_version: Literal["1"] = "1"
    items: list[DiscoveryCandidateSummary]
    total: int
    offset: int
    limit: int
    has_more: bool
    record_role: str | None = None


class DiscoveryCandidateDetail(DiscoveryCandidate, DiscoveryVersion):
    pass
