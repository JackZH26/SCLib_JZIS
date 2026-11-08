"""Closed bindings for qualified extraction lookup, never scientific approval."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class LinkedScientificResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    result: ScientificQueryResult
    binding: ScientificResultBinding


class ScientificLookupStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    status: Literal["not_requested", "completed", "unavailable", "clarification_required"] = "not_requested"
    reason_codes: list[str] = Field(default_factory=list, max_length=8)
    returned_count: int = Field(default=0, ge=0, le=20)
    has_more: bool = False
    scope: Literal["declared_generation_derived_extractions"] = "declared_generation_derived_extractions"
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
    if status.status == "completed" and pin.mode != "generation_snapshot":
        raise ValueError("Completed scientific lookup requires a pinned generation")
    if len({row.binding.parent_result_revision_id for row in rows}) != len(rows):
        raise ValueError("Repeated extraction parents are not distinct results")
    for row in rows:
        if any(getattr(row.binding, field) != getattr(pin, field) for field in
               ("generation_id", "activation_event_id", "manifest_sha256")):
            raise ValueError("Scientific result belongs to a different read generation")
        if not row.binding.vector_id.startswith("ig62_" + UUID(pin.generation_id).hex + "_"):
            raise ValueError("Scientific vector identity belongs to another generation")
    return response
