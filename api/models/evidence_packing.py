"""Closed operational retrieval plans; grouping never proves independence."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RoleHint = Literal["methods", "results", "table", "other"]
GroupBasis = Literal["accepted_work_mapping", "source_snapshot", "legacy_paper"]
ExclusionReason = Literal[
    "payload_budget", "base_payload_budget", "chunk_limit", "source_limit", "work_limit",
    "duplicate_content", "role_already_represented", "not_complementary_original",
]
SummaryReason = Literal[
    "packing_not_requested", "no_admitted_candidates", "base_payload_budget_exceeded", "payload_budget_excluded",
    "selection_limits_applied", "duplicate_content_removed", "complementarity_not_established",
    "packing_unavailable", "selected_context_withheld",
]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class PackingCandidate(_Closed):
    """Private, already-admitted identities supplied by a trusted DB resolver.

    No permission/approval status is accepted from an untrusted request body.
    Accepted Work IDs are diversity hints, not independent scientific roots.
    """
    chunk_id: str = Field(min_length=1, max_length=200)
    paper_id: str = Field(min_length=1, max_length=100)
    source_snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    accepted_work_id: str | None = None
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_kind: Literal["original_passage", "abstract", "derived_fact", "legacy_unknown"]
    role_hint: RoleHint = "other"

    @field_validator("chunk_id", "paper_id")
    @classmethod
    def bounded_identifier(cls, value):
        if not value.strip() or any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("A bounded nonblank identifier is required")
        return value

    @field_validator("accepted_work_id")
    @classmethod
    def canonical_work(cls, value):
        if value is not None and str(UUID(value)) != value:
            raise ValueError("Accepted Work diversity requires its canonical UUID")
        return value


class EvidencePackingSelection(_Closed):
    version: Literal["evidence-pack-item/1.0.0"] = "evidence-pack-item/1.0.0"
    position: int = Field(ge=1, le=20)
    chunk_id: str = Field(min_length=1, max_length=200)
    source_group_id: str = Field(pattern=r"^src:[0-9a-f]{64}$")
    source_snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    diversity_group_id: str = Field(pattern=r"^div:[0-9a-f]{64}$")
    source_group_basis: Literal["source_snapshot", "legacy_paper"]
    group_basis: GroupBasis
    role_hint: RoleHint
    selection_reason: Literal["source_diversity", "source_coverage", "complementary_role"]
    scientific_acceptance: Literal[False] = False

    @field_validator("scientific_acceptance", mode="before")
    @classmethod
    def no_acceptance(cls, value):
        if value is not False:
            raise ValueError("A packing decision never grants scientific acceptance")
        return value

    @model_validator(mode="after")
    def consistent_basis(self):
        if (self.source_group_basis == "source_snapshot") != (self.source_snapshot_sha256 is not None):
            raise ValueError("Source grouping must disclose whether an exact snapshot was bound")
        if self.group_basis != "accepted_work_mapping" and self.group_basis != self.source_group_basis:
            raise ValueError("Unmapped diversity must retain its exact source grouping basis")
        if self.source_group_basis == "legacy_paper" and self.selection_reason == "complementary_role":
            raise ValueError("Unresolved legacy source snapshots cannot be complemented")
        if self.selection_reason == "complementary_role" and self.role_hint == "other":
            raise ValueError("Only explicit retrieval role hints provide complementarity")
        return self


class EvidencePackingExclusion(_Closed):
    chunk_id: str = Field(min_length=1, max_length=200)
    reason_code: ExclusionReason


class EvidencePackingPlan(_Closed):
    version: Literal["evidence-packing/1.0.0"] = "evidence-packing/1.0.0"
    status: Literal["packed", "empty", "base_budget_exceeded"]
    selected: list[EvidencePackingSelection] = Field(default_factory=list, max_length=20)
    excluded: list[EvidencePackingExclusion] = Field(default_factory=list, max_length=300)
    candidate_count: int = Field(ge=0, le=300)
    selected_count: int = Field(ge=0, le=20)
    source_group_count: int = Field(ge=0, le=20)
    diversity_group_count: int = Field(ge=0, le=20)
    payload_bytes: int = Field(ge=0, le=64 * 1024 * 1024)
    byte_budget: int = Field(ge=1, le=16 * 1024 * 1024)
    byte_count_method: Literal["utf8-full-payload/1"] = "utf8-full-payload/1"
    max_chunks: int = Field(ge=1, le=20)
    max_per_source: int = Field(ge=1, le=3)
    max_per_work: int = Field(ge=1, le=3)
    independent_support_count: None = None
    independence_status: Literal["independence_not_established"] = "independence_not_established"
    scientific_acceptance: Literal[False] = False

    @field_validator("scientific_acceptance", mode="before")
    @classmethod
    def no_acceptance(cls, value):
        if value is not False:
            raise ValueError("Grouping is not scientific acceptance")
        return value

    @model_validator(mode="after")
    def coherent_plan(self):
        identifiers = [item.chunk_id for item in [*self.selected, *self.excluded]]
        if len(set(identifiers)) != len(identifiers) or len(identifiers) != self.candidate_count:
            raise ValueError("Every admitted candidate must have exactly one packing disposition")
        if self.selected_count != len(self.selected) or self.selected_count > self.max_chunks:
            raise ValueError("Packing selection count mismatch")
        if [item.position for item in self.selected] != list(range(1, self.selected_count + 1)):
            raise ValueError("Citation positions must be contiguous and ordered")
        if (self.source_group_count != len({item.source_group_id for item in self.selected})
                or self.diversity_group_count != len({item.diversity_group_id for item in self.selected})):
            raise ValueError("Operational grouping count mismatch")
        seen_sources, seen_diversity, roles = set(), set(), {}
        for item in self.selected:
            expected = ("source_diversity" if item.diversity_group_id not in seen_diversity else
                        "source_coverage" if item.source_group_id not in seen_sources else "complementary_role")
            if item.selection_reason != expected:
                raise ValueError("Packing selection reason must match its ordered grouping")
            if item.selection_reason == "complementary_role" and item.role_hint in roles.get(item.source_group_id, set()):
                raise ValueError("A repeated role is not complementary source coverage")
            source_members = [row for row in self.selected if row.source_group_id == item.source_group_id]
            if len(source_members) > (1 if item.source_group_basis == "legacy_paper" else self.max_per_source):
                raise ValueError("Source group packing limit exceeded")
            if len({(row.source_group_basis, row.diversity_group_id, row.group_basis) for row in source_members}) != 1:
                raise ValueError("One exact source group cannot have conflicting diversity bindings")
            if len({row.source_snapshot_sha256 for row in source_members}) != 1:
                raise ValueError("One exact source group cannot mix source snapshots")
            if item.group_basis == "accepted_work_mapping" and sum(
                    row.diversity_group_id == item.diversity_group_id for row in self.selected) > self.max_per_work:
                raise ValueError("Accepted Work diversity limit exceeded")
            seen_sources.add(item.source_group_id)
            seen_diversity.add(item.diversity_group_id)
            roles.setdefault(item.source_group_id, set()).add(item.role_hint)
        if self.status == "packed":
            valid = bool(self.selected) and self.payload_bytes <= self.byte_budget
        elif self.status == "empty":
            valid = not self.selected and self.payload_bytes <= self.byte_budget
        else:
            valid = not self.selected and self.payload_bytes > self.byte_budget
        if not valid:
            raise ValueError("Packing state and complete-payload byte accounting disagree")
        return self


class EvidencePackingSummary(_Closed):
    """Public accounting only: no withheld candidate IDs or raw Work UUIDs."""
    version: Literal["evidence-packing/1.0.0"] = "evidence-packing/1.0.0"
    status: Literal["not_requested", "packed", "empty", "base_budget_exceeded", "withheld", "unavailable"] = "not_requested"
    candidate_count: int = Field(default=0, ge=0, le=300)
    selected_count: int = Field(default=0, ge=0, le=20)
    source_group_count: int = Field(default=0, ge=0, le=20)
    diversity_group_count: int = Field(default=0, ge=0, le=20)
    payload_bytes: int | None = Field(default=None, ge=0, le=64 * 1024 * 1024)
    byte_budget: int | None = Field(default=None, ge=1, le=16 * 1024 * 1024)
    byte_count_method: Literal["utf8-full-payload/1"] = "utf8-full-payload/1"
    max_chunks: int = Field(default=20, ge=1, le=20)
    max_per_source: int = Field(default=3, ge=1, le=3)
    max_per_work: int = Field(default=3, ge=1, le=3)
    reason_counts: dict[ExclusionReason, int] = Field(default_factory=dict)
    reason_codes: list[SummaryReason] = Field(default_factory=list, max_length=9)
    independent_support_count: None = None
    independence_status: Literal["independence_not_established"] = "independence_not_established"
    scientific_acceptance: Literal[False] = False

    @field_validator("scientific_acceptance", mode="before")
    @classmethod
    def no_acceptance(cls, value):
        if value is not False:
            raise ValueError("Grouping is not scientific acceptance")
        return value

    @field_validator("reason_counts")
    @classmethod
    def positive_counts(cls, value):
        if any(type(count) is not int or not 1 <= count <= 300 for count in value.values()):
            raise ValueError("Packing exclusion counts must be bounded positive integers")
        return value

    @model_validator(mode="after")
    def coherent_summary(self):
        if (not 0 <= self.diversity_group_count <= self.source_group_count <= self.selected_count <= self.candidate_count
                or self.selected_count > self.max_chunks or len(set(self.reason_codes)) != len(self.reason_codes)):
            raise ValueError("Inconsistent public packing counts")
        if self.status in {"not_requested", "withheld", "unavailable"}:
            if self.selected_count or self.source_group_count or self.diversity_group_count or self.payload_bytes is not None or self.reason_counts:
                raise ValueError("Unavailable or withheld plans cannot disclose a previous selected context")
            if self.status == "not_requested" and (self.candidate_count or self.byte_budget is not None):
                raise ValueError("Unrequested packing has no measured inventory or budget")
        else:
            if self.payload_bytes is None or self.byte_budget is None:
                raise ValueError("A completed plan needs exact complete-payload accounting")
            if sum(self.reason_counts.values()) != self.candidate_count - self.selected_count:
                raise ValueError("Public exclusion counts must account for the complete inventory")
            if self.status == "base_budget_exceeded":
                valid = self.selected_count == 0 and self.payload_bytes > self.byte_budget
            else:
                valid = self.payload_bytes <= self.byte_budget and (self.selected_count > 0) == (self.status == "packed")
            if not valid:
                raise ValueError("Public packing state disagrees with its byte budget")
        return self
