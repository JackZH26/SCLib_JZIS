"""Closed mixed retrieval reporting; catalogue proximity is not an experiment link."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

VERSION = "scientific-mixed-evidence/1.1.0"
LEGACY_VERSION = "scientific-mixed-evidence/1.0.0"
BRIDGE_FIELDS = frozenset({"bridge_revision_id", "bridge_record_sha256", "claim_identity_sha256",
                           "sample_identity_sha256", "source_locator_sha256"})
MixedReason = Literal[
    "numerical_explanation_not_established", "reviewed_result_passage_bridge_missing",
    "no_matching_extraction", "no_original_context", "combined_source_limit",
    "mixed_lookup_unavailable", "mixed_context_unavailable", "mixed_currentness_unavailable",
    "retrieval_generation_changed", "retrieval_source_changed", "retrieval_source_no_longer_eligible",
    "retrieval_grouping_changed", "retrieval_currentness_unavailable", "retrieval_currentness_timeout",
    "evidence_packing_unavailable",
]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class MixedEvidenceAssociation(_Closed):
    parent_result_revision_id: str
    result_source_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_index: int = Field(ge=1, le=20)
    source_vector_id: str = Field(pattern=r"^ig62_[0-9a-f]{32}_[0-9a-f]{64}$")
    source_evidence_revision_id: str
    source_evidence_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalogue_relation: Literal["same_snapshot", "not_same_snapshot"]
    status: Literal["established", "not_established"] = "not_established"
    reason_code: Literal[
        "reviewed_result_passage_bridge_current", "reviewed_result_passage_bridge_missing",
    ] = "reviewed_result_passage_bridge_missing"
    bridge_revision_id: str | None = None
    bridge_record_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    claim_identity_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    sample_identity_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    source_locator_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("parent_result_revision_id", "source_evidence_revision_id", "bridge_revision_id")
    @classmethod
    def canonical_uuid(cls, value):
        if value is None:
            return value
        if str(UUID(value)) != value:
            raise ValueError("A canonical source/result UUID is required")
        return value

    @model_validator(mode="after")
    def coherent_reviewed_link(self):
        pins = (self.bridge_revision_id, self.bridge_record_sha256, self.claim_identity_sha256,
                self.sample_identity_sha256, self.source_locator_sha256)
        established = self.status == "established"
        if established != all(value is not None for value in pins) or (not established and any(value is not None for value in pins)):
            raise ValueError("Reviewed link pins must be complete exactly when the association is established")
        if established != (self.reason_code == "reviewed_result_passage_bridge_current"):
            raise ValueError("Reviewed link status and reason must agree")
        return self


class ScientificMixedEvidence(_Closed):
    version: Literal[
        "scientific-mixed-evidence/1.0.0", "scientific-mixed-evidence/1.1.0",
    ] = VERSION
    status: Literal["not_requested", "completed", "unavailable"] = "not_requested"
    result_count: int = Field(default=0, ge=0, le=20)
    source_count: int = Field(default=0, ge=0, le=20)
    max_selected_inputs: int = Field(default=0, ge=0, le=20)
    associations: list[MixedEvidenceAssociation] = Field(default_factory=list, max_length=100)
    reason_codes: list[MixedReason] = Field(default_factory=list, max_length=8)
    scientific_acceptance: Literal[False] = False
    independent_support_count: None = None

    @model_validator(mode="before")
    @classmethod
    def closed_legacy_associations(cls, value):
        if (isinstance(value, dict) and value.get("version") == LEGACY_VERSION
                and isinstance(value.get("associations"), list)):
            for item in value.get("associations", []):
                if isinstance(item, dict) and BRIDGE_FIELDS.intersection(item):
                    raise ValueError("Legacy associations cannot include reviewed-link fields")
        return value

    @model_serializer(mode="wrap")
    def preserve_wire_version(self, handler):
        value = handler(self)
        if self.version == LEGACY_VERSION:
            for item in value.get("associations", []):
                for field in BRIDGE_FIELDS:
                    item.pop(field, None)
        return value

    @field_validator("scientific_acceptance", mode="before")
    @classmethod
    def no_scientific_authority(cls, value):
        if value is not False:
            raise ValueError("Mixed retrieval never establishes scientific acceptance")
        return value

    @model_validator(mode="after")
    def coherent_inventory(self):
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("Repeated mixed reason codes are ambiguous")
        if self.status == "not_requested":
            if self.result_count or self.source_count or self.max_selected_inputs or self.associations or self.reason_codes:
                raise ValueError("Unrequested mixed retrieval has no measured inventory")
        elif self.status == "unavailable":
            if self.result_count or self.source_count or self.associations or not self.reason_codes:
                raise ValueError("Unavailable mixed retrieval must withdraw all previous inputs")
        else:
            if not 1 <= self.max_selected_inputs <= 20 or self.result_count + self.source_count > self.max_selected_inputs:
                raise ValueError("Mixed result and original inputs share one bounded inventory")
            if len(self.associations) != self.result_count * self.source_count:
                raise ValueError("Every result/original pair needs its unresolved association disposition")
            if "numerical_explanation_not_established" not in self.reason_codes:
                raise ValueError("Unestablished numerical explanation must be disclosed")
            unresolved = not self.associations or any(item.status == "not_established" for item in self.associations)
            if ("reviewed_result_passage_bridge_missing" in self.reason_codes) != unresolved:
                raise ValueError("Missing reviewed bridge disclosure must match the pair inventory")
            if self.version == LEGACY_VERSION and any(item.status != "not_established" for item in self.associations):
                raise ValueError("The legacy mixed contract cannot carry reviewed links")
            if ("no_matching_extraction" in self.reason_codes) != (self.result_count == 0):
                raise ValueError("Missing extraction disclosure must match the inventory")
            if ("no_original_context" in self.reason_codes) != (self.source_count == 0):
                raise ValueError("Missing original-context disclosure must match the inventory")
        return self


def validate_mixed_response(response):
    mixed = response.scientific_mixed
    if mixed.status == "not_requested":
        return response
    query = response.scientific_query
    mixed_query = query is not None and (query.intent == "mixed" or query.intent == "comparison"
        and bool(query.requested_fields or query.constraints or query.evidence_constraints))
    if not mixed_query or query.status != "resolved":
        raise ValueError("Mixed execution requires an explicitly resolved mixed query")
    if (response.answer_mode != "abstention" or response.assessment_scope != "none"
            or response.scientific_support_status != "not_checked" or response.claim_assessments
            or response.tokens_used != 0 or response.input_budget.status != "not_requested"):
        raise ValueError("Unestablished mixed associations cannot carry model synthesis or token claims")
    if mixed.status == "unavailable":
        if response.sources or response.scientific_results or response.scientific_lookup.status != "unavailable":
            raise ValueError("Unavailable mixed responses withdraw both original and numerical inventories")
        return response
    if response.scientific_lookup.status != "completed" or response.retrieval_generation.mode != "generation_snapshot":
        raise ValueError("Completed mixed retrieval requires completed version-pinned numerical lookup")
    rows, sources = response.scientific_results, response.sources
    if len(rows) != mixed.result_count or len(sources) != mixed.source_count:
        raise ValueError("Mixed inventory counts must match the public rows and passages")
    if [source.index for source in sources] != list(range(1, len(sources) + 1)):
        raise ValueError("Original citations have a separate contiguous ordered index")
    by_parent = {row.binding.parent_result_revision_id: row for row in rows}
    by_index = {source.index: source for source in sources}
    if len(by_parent) != len(rows):
        raise ValueError("Repeated parents are not distinct numerical results")
    prefix = "ig62_" + UUID(response.retrieval_generation.generation_id).hex + "_"
    vectors = []
    for source in sources:
        evidence = source.evidence_provenance
        if (evidence.get("chunk_kind") != "original_passage" or evidence.get("permission_status") == "restricted"
                or evidence.get("currentness") == "stale" or source.packing_info is None
                or not source.packing_info.chunk_id.startswith(prefix)):
            raise ValueError("Mixed explanations require individually pinned non-held original candidates")
        vectors.append(source.packing_info.chunk_id)
    if len(set(vectors)) != len(vectors) or set(vectors) & {row.binding.vector_id for row in rows}:
        raise ValueError("Numerical parents and original citations must remain distinct selected inputs")
    seen, snapshots = set(), {}
    for association in mixed.associations:
        key = (association.parent_result_revision_id, association.source_index)
        if key in seen or key[0] not in by_parent or key[1] not in by_index:
            raise ValueError("Mixed association inventory contains unknown or repeated pairs")
        seen.add(key)
        row, source = by_parent[key[0]], by_index[key[1]]
        evidence = source.evidence_provenance
        if (association.source_vector_id != source.packing_info.chunk_id
                or association.source_evidence_revision_id != evidence.get("evidence_revision_id")
                or association.source_evidence_record_sha256 != evidence.get("evidence_record_sha256")
                or association.source_content_sha256 != evidence.get("content_sha256")):
            raise ValueError("Mixed association must retain the original citation's complete evidence binding")
        snapshot = association.result_source_snapshot_sha256
        if key[0] in snapshots and snapshots[key[0]] != snapshot:
            raise ValueError("A numerical parent cannot acquire conflicting catalogue snapshots")
        snapshots[key[0]] = snapshot
        same = row.binding.paper_id == source.paper_id and snapshot == source.packing_info.source_snapshot_sha256
        if (association.catalogue_relation == "same_snapshot") != same:
            raise ValueError("Catalogue proximity must match its declared paper and snapshot, not imply an experiment link")
        if association.status == "established" and not same:
            raise ValueError("Reviewed links require the exact same source paper and snapshot")
    if seen != {(parent, index) for parent in by_parent for index in by_index}:
        raise ValueError("Mixed association inventory is incomplete")
    return response
