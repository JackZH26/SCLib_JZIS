"""Closed bindings for qualified extraction lookup, never scientific approval."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.scientific_query_result import ScientificQueryResult


class ScientificResultBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    paper_id: str = Field(min_length=1, max_length=100)
    vector_id: str = Field(pattern=r"^ig62_[0-9a-f]{32}_[0-9a-f]{64}$")
    generation_id: str
    activation_event_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_revision_id: str
    evidence_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_result_revision_id: str
    parent_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    association_scope: Literal["derived_extraction_not_original_support"] = "derived_extraction_not_original_support"

    @field_validator("generation_id", "activation_event_id", "evidence_revision_id", "parent_result_revision_id")
    @classmethod
    def canonical_id(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("A canonical evidence UUID is required")
        return value


class ContentScientificResultBinding(BaseModel):
    """Structural content/origin binding, never database or science authority."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    version: Literal["scientific-result-binding/2.0.0"]
    paper_id: str = Field(min_length=1, max_length=100)
    vector_id: str = Field(pattern=r"^(ig62_[0-9a-f]{32}_|rv2_)[0-9a-f]{64}$")
    content_id: str
    build_id: str
    activation_event_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_member_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin_kind: Literal["legacy_v1", "native_v2"]
    origin_generation_id: str | None
    native_revision_id: str | None
    origin_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    vector_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_revision_id: str
    evidence_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_result_revision_id: str
    parent_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    association_scope: Literal["derived_extraction_not_original_support"]

    @field_validator("content_id", "build_id", "activation_event_id", "origin_generation_id",
                     "native_revision_id", "evidence_revision_id", "parent_result_revision_id")
    @classmethod
    def canonical_id(cls, value):
        if value is not None and str(UUID(value)) != value:
            raise ValueError("A canonical content/origin/evidence UUID is required")
        return value

    @model_validator(mode="after")
    def exact_origin(self):
        if self.origin_kind == "legacy_v1":
            if self.origin_generation_id is None or self.native_revision_id is not None:
                raise ValueError("A retained legacy origin requires its real generation")
            expected = "ig62_" + UUID(self.origin_generation_id).hex + "_" + self.chunk_revision_sha256
        else:
            if self.native_revision_id is None or self.origin_generation_id is not None:
                raise ValueError("A native origin cannot acquire a provider generation")
            expected = "rv2_" + self.chunk_revision_sha256
        if self.vector_id != expected:
            raise ValueError("Scientific vector does not match its declared origin revision")
        return self


class LinkedScientificResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    result: ScientificQueryResult
    binding: ScientificResultBinding | ContentScientificResultBinding


class ScientificLookupStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    status: Literal["not_requested", "completed", "unavailable", "clarification_required"] = "not_requested"
    reason_codes: list[str] = Field(default_factory=list, max_length=8)
    returned_count: int = Field(default=0, ge=0, le=20)
    has_more: bool = False
    scope: Literal["declared_generation_derived_extractions", "declared_content_derived_extractions"] = "declared_generation_derived_extractions"
    scientific_acceptance: Literal[False] = False

    @field_validator("scientific_acceptance", mode="before")
    @classmethod
    def no_scientific_authority(cls, value):
        if value is not False:
            raise ValueError("Scientific acceptance must be the boolean false")
        return value

    @field_validator("reason_codes")
    @classmethod
    def closed_reasons(cls, values):
        import re
        if len(set(values)) != len(values) or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", value) for value in values):
            raise ValueError("Bounded unique reason codes are required")
        return values


def validate_scientific_response(response):
    """Reject contradictory public execution/binding envelopes before display."""
    status, rows, interpretation = response.scientific_lookup, response.scientific_results, response.scientific_query
    if status.returned_count != len(rows):
        raise ValueError("Scientific lookup result count mismatch")
    if status.status != "completed" and (rows or status.has_more):
        raise ValueError("Incomplete scientific lookup cannot publish results")
    if status.status in {"completed", "unavailable"} and (interpretation is None or interpretation.status != "resolved"):
        raise ValueError("Scientific lookup requires a resolved interpretation")
    if status.status == "clarification_required" and (interpretation is None or interpretation.status != "clarification_required"):
        raise ValueError("Clarification must preserve unresolved query clauses")
    if status.has_more and not rows:
        raise ValueError("Scientific lookup cannot hide its entire first page")
    pin = response.retrieval_generation
    content = pin.mode == "content_snapshot"
    if status.status == "completed":
        if pin.mode not in {"generation_snapshot", "content_snapshot"}:
            raise ValueError("Completed scientific lookup requires a pinned generation")
        expected_scope = "declared_content_derived_extractions" if content else "declared_generation_derived_extractions"
        if status.scope != expected_scope:
            raise ValueError("Scientific lookup scope does not match its read identity")
    if len({row.binding.parent_result_revision_id for row in rows}) != len(rows):
        raise ValueError("Repeated extraction parents are not distinct results")
    for row in rows:
        if content:
            if type(row.binding) is not ContentScientificResultBinding or any(
                    getattr(row.binding, field) != getattr(pin, field) for field in
                    ("content_id", "build_id", "activation_event_id", "manifest_sha256", "policy_artifact_sha256")):
                raise ValueError("Scientific result belongs to a different content/backend read")
            continue
        if type(row.binding) is not ScientificResultBinding:
            raise ValueError("Scientific result belongs to a different read generation")
        if any(getattr(row.binding, field) != getattr(pin, field) for field in
               ("generation_id", "activation_event_id", "manifest_sha256")):
            raise ValueError("Scientific result belongs to a different read generation")
        if not row.binding.vector_id.startswith("ig62_" + UUID(pin.generation_id).hex + "_"):
            raise ValueError("Scientific vector identity belongs to another generation")
    return response
