"""Public wire models for the SCLib ML Foundation data layer.

The ORM keeps migration and ingestion details.  These response models expose
only auditable, structured facts; legacy raw JSON and licensed source text are
intentionally not part of the public contract.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.material_visibility import MATERIAL_VISIBILITY_VERSION, sanitize_review_metadata
from services.temporal_provenance import public_locator

_PUBLIC_LOCATOR_STRING_LIMITS = {
    "chunk_id": 200,
    "equation": 100,
    "figure": 100,
    "figure_id": 100,
    "locator_quality": 40,
    "panel": 40,
    "reference": 500,
    "section": 300,
    "section_path": 500,
    "table": 100,
    "table_id": 100,
    "xml_xpath": 500,
}
_PUBLIC_LOCATOR_INTEGER_FIELDS = {
    "char_end",
    "char_start",
    "column",
    "page",
    "page_end",
    "page_start",
    "row",
    "span_end",
    "span_start",
}
_PUBLIC_LOCATOR_HASH_FIELDS = {"artifact_sha256", "excerpt_sha256"}


class SourceSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_version: str
    site_git_sha: str | None = None
    database_watermark: datetime | None = None
    paper_count: int
    material_count: int
    chunk_count: int
    schema_version: str
    manifest_sha256: str | None = None
    license_manifest_sha256: str | None = None
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    frozen_at: datetime | None = None


class WorkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    canonical_title: str | None = None
    canonical_doi: str | None = None
    canonical_arxiv_id: str | None = None
    publication_status: str
    available_at: date | None = None
    available_at_basis: Literal["legacy_work_date_hint_not_result_availability"] = "legacy_work_date_hint_not_result_availability"
    identity_metadata: dict[str, Any] = Field(default_factory=dict)
    paper_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TemporalSourceWitnessResponse(BaseModel):
    """Explicit public allowlist; no review reference, URI, notes or source text."""

    source_revision_id: str
    capture_id: str
    paper_id: str
    work_id: str
    source_version: str
    source_version_public_at: datetime
    captured_at: datetime
    bytes_sha256: str
    representation: str
    locator: dict[str, Any] = Field(default_factory=dict)

    @field_validator("locator", mode="before")
    @classmethod
    def public_coordinates_only(cls, value: Any) -> dict[str, Any]:
        return public_locator(value)


class TemporalProvenanceResponse(BaseModel):
    """Server-derived conservative known-by bound; not first discovery or approval."""

    version: Literal["temporal-provenance/1.0.0"] = "temporal-provenance/1.0.0"
    status: Literal["known_by", "unknown", "uncertain"] = "unknown"
    result_available_at: datetime | None = None
    source_version_public_at: datetime | None = None
    captured_at: datetime | None = None
    availability_basis: Literal["source_version_witness", "unknown", "unresolved_source_evidence"] = "unknown"
    assessment_complete: bool = False
    first_appearance_established: Literal[False] = False
    scientific_acceptance: Literal[False] = False
    llm_pretraining_contamination_assessed: Literal[False] = False
    witnesses: list[TemporalSourceWitnessResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ClaimTemporalFilterResponse(BaseModel):
    version: Literal["claim-temporal-filter/1.0.0"] = "claim-temporal-filter/1.0.0"
    scope: Literal["live_claim_known_by_filter"] = "live_claim_known_by_filter"
    active: bool = False
    cutoff: datetime | None = None
    unknown_policy: Literal["excluded_when_cutoff_active"] = "excluded_when_cutoff_active"
    reproducible_snapshot_established: Literal[False] = False


class MaterialClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    material_id: str
    paper_id: str | None = None
    work_id: uuid.UUID | None = None
    source_snapshot_id: uuid.UUID
    property_type: str
    evidence_role: str
    result_status: str
    value_relation: str
    value_kelvin: float | None = None
    value_lower_kelvin: float | None = None
    value_upper_kelvin: float | None = None
    tc_definition: str
    pressure_state: str
    pressure_gpa: float | None = None
    minimum_temperature_k: float | None = None
    magnetic_field_t: float | None = None
    measurement_method: str | None = None
    sample_form: str | None = None
    structure_phase_raw: str | None = None
    doping_raw: str | None = None
    sample_label: str | None = None
    source_kind: str
    chunk_id: str | None = None
    source_locator: dict[str, Any] = Field(default_factory=dict)
    extraction_confidence: float | None = None
    relation_confidence: float | None = None
    validity_status: str
    source_record_hash: str
    semantic_fingerprint: str | None = None
    duplicate_cluster_id: str | None = None
    available_at: date | None = None
    available_at_basis: Literal["result_known_by_utc_date_or_null"] = "result_known_by_utc_date_or_null"
    legacy_available_at: date | None = None
    temporal_provenance: TemporalProvenanceResponse = Field(default_factory=TemporalProvenanceResponse)
    extractor_version: str
    ingestion_run_id: str | None = None
    created_at: datetime
    updated_at: datetime
    visibility: dict[str, Any] = Field(default_factory=dict)
    claim_visibility: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_locator", mode="before")
    @classmethod
    def remove_source_text_from_public_locator(cls, value: Any) -> dict[str, Any]:
        """Expose reproducible coordinates, never licensed/source excerpts."""
        if not isinstance(value, dict):
            return {}
        visible: dict[str, Any] = {}
        for key, item in value.items():
            if key in _PUBLIC_LOCATOR_STRING_LIMITS:
                if isinstance(item, str):
                    visible[key] = item[: _PUBLIC_LOCATOR_STRING_LIMITS[key]]
            elif key in _PUBLIC_LOCATOR_INTEGER_FIELDS:
                if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
                    visible[key] = item
            elif key in _PUBLIC_LOCATOR_HASH_FIELDS:
                if (
                    isinstance(item, str)
                    and len(item) == 64
                    and all(char in "0123456789abcdefABCDEF" for char in item)
                ):
                    visible[key] = item.lower()
        return visible

    @field_validator("visibility", "claim_visibility", mode="before")
    @classmethod
    def remove_private_review_metadata(cls, value: Any) -> dict[str, Any]:
        return sanitize_review_metadata(value) if isinstance(value, dict) else {}


class MaterialClaimPage(BaseModel):
    items: list[MaterialClaimResponse]
    limit: int
    next_cursor: uuid.UUID | None = None
    has_more: bool = False
    visibility_policy_version: str = MATERIAL_VISIBILITY_VERSION
    view_scope: str = "catalogue"
    scientific_acceptance: bool = False
    temporal_filter: ClaimTemporalFilterResponse = Field(default_factory=ClaimTemporalFilterResponse)


class MlDatasetSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_snapshot_id: uuid.UUID
    name: str
    version: str
    status: str
    label_policy_version: str
    feature_schema_version: str
    split_ruleset_version: str
    manifest_sha256: str | None = None
    row_count: int
    filters: dict[str, Any] = Field(default_factory=dict)
    data_card_uri: str | None = None
    created_at: datetime
    frozen_at: datetime | None = None


class MlDatasetManifestResponse(BaseModel):
    dataset_snapshot_id: uuid.UUID
    source_snapshot_id: uuid.UUID
    name: str
    version: str
    status: str
    manifest_sha256: str | None = None
    row_count: int
    label_policy_version: str
    feature_schema_version: str
    split_ruleset_version: str
    filters: dict[str, Any] = Field(default_factory=dict)
    data_card_uri: str | None = None
    created_at: datetime
    frozen_at: datetime | None = None
