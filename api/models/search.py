"""Pydantic schemas for the public Phase-3 routers.

Wire format only — ORM classes live in ``models.db``. Keeping request
and response shapes here means a breaking API change does not require
a database migration, and vice versa.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.evidence_packing import EvidencePackingSelection, EvidencePackingSummary
from models.history_receipts import HistorySaveDisposition
from models.index_read import IndexReadMetadata
from models.rag_input_budget import RagInputBudgetReport
from models.scientific_lookup import (
    LinkedScientificResult,
    ScientificLookupStatus,
    validate_scientific_response,
)
from models.scientific_mixed import ScientificMixedEvidence, validate_mixed_response
from models.scientific_query import ScientificQueryInterpretation
from services.claim_support import SUPPORT_POLICY_VERSION
from services.material_property_projection import project_material_properties
from services.material_semantics import MATERIAL_SEMANTICS_VERSION
from services.material_visibility_adapter import MaterialReadContext
from services.pressure_semantics import annotate_pressure_records, classify_pressure
from services.result_semantics import (
    CLASSIFIER_VERSION,
    annotate_records,
    classification_summary,
    evidence_summary,
)
from services.scientific_filters import FILTER_POLICY_VERSION
from services.structure_disclosure import redact_structure_payloads

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class SearchFilters(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    year_min: int | None = Field(None, ge=1900, le=2100)
    year_max: int | None = Field(None, ge=1900, le=2100)
    material_family: list[str] | None = None
    tc_min: float | None = Field(None, ge=0)
    pressure_max: float | None = Field(None, ge=0)
    pressure_min: float | None = Field(None, ge=0)
    ambient_only: bool = False
    include_unknown_pressure: bool = False
    knowledge_origin: list[Literal["Observed", "Computed", "Inferred", "AI-Proposed", "Unknown"]] | None = None
    source_role: Literal["primary", "cited"] | None = None
    experimental_only: bool = False
    exclude_retracted: bool = True

    @model_validator(mode="after")
    def consistent_bounds(self):
        if self.pressure_min is not None and self.pressure_max is not None and self.pressure_min > self.pressure_max:
            raise ValueError("pressure_min cannot exceed pressure_max")
        return self


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000)
    top_k: int = Field(20, ge=1, le=100)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    sort: Literal["relevance", "date", "tc"] = "relevance"

    @field_validator("query")
    @classmethod
    def nonblank_query(cls, value):
        if not value.strip():
            raise ValueError("Query must contain non-whitespace text")
        return value  # preserve original notation and whitespace spans


class SearchMatch(BaseModel):
    """One hit in a search response."""

    source_visibility: dict[str, Any] = Field(default_factory=dict)
    occurrence_visibility_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_provenance")
    @classmethod
    def validate_evidence(cls, value):
        from services.rag_evidence_contract import validate_evidence_descriptor
        return validate_evidence_descriptor(value) if value else {}

    @field_validator("materials")
    @classmethod
    def classify_materials(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return redact_structure_payloads(annotate_pressure_records(annotate_records(value)))

    paper_id: str
    arxiv_id: str | None
    title: str
    authors: list[str]
    year: int | None
    date_submitted: date | None
    relevance_score: float  # higher = better (normalized hybrid rerank score)
    matched_chunk: str
    matched_section: str | None
    materials: list[dict[str, Any]]
    citation_count: int
    material_family: str | None
    has_equation: bool
    has_table: bool
    matching_results: list[dict[str, Any]] = Field(default_factory=list)
    filter_policy_version: str = FILTER_POLICY_VERSION


class SearchResponse(BaseModel):
    retrieval_generation: IndexReadMetadata = Field(default_factory=IndexReadMetadata)
    scientific_query: ScientificQueryInterpretation | None = None
    scientific_lookup: ScientificLookupStatus = Field(default_factory=ScientificLookupStatus)
    scientific_results: list[LinkedScientificResult] = Field(default_factory=list, max_length=20)
    total: int
    results: list[SearchMatch]
    query_time_ms: int
    guest_remaining: int | None = None
    remaining: int | None = None

    @model_validator(mode="after")
    def scientific_response_coherent(self):
        return validate_scientific_response(self)


# ---------------------------------------------------------------------------
# Ask (RAG)
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    max_sources: int = Field(10, ge=1, le=20)
    language: Literal["auto", "en", "zh"] = "auto"

    @field_validator("question")
    @classmethod
    def nonblank_question(cls, value):
        if not value.strip():
            raise ValueError("Question must contain non-whitespace text")
        return value


class AskSource(BaseModel):
    """One citation surfaced in the RAG answer."""

    index: int  # 1-based, matches [1] [2] in markdown
    paper_id: str
    arxiv_id: str | None
    title: str
    authors_short: str
    year: int | None
    section: str | None
    snippet: str
    material_evidence: list[dict[str, Any]] = Field(default_factory=list)
    source_visibility: dict[str, Any] = Field(default_factory=dict)
    evidence_provenance: dict[str, Any] = Field(default_factory=dict)
    packing_info: EvidencePackingSelection | None = None

    @field_validator("evidence_provenance")
    @classmethod
    def validate_evidence(cls, value):
        from services.rag_evidence_contract import validate_evidence_descriptor
        return validate_evidence_descriptor(value) if value else {}

SupportStatus = Literal["supported", "contradicted", "undetermined", "not_checked"]


class ClaimSupportEvidence(BaseModel):
    source_index: int = Field(ge=1)
    paper_id: str
    excerpt: str


class ClaimSupportAssessment(BaseModel):
    claim_id: str
    text: str
    cited_indices: list[int] = Field(default_factory=list)
    status: SupportStatus
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[ClaimSupportEvidence] = Field(default_factory=list)
    quantities: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)


class AskResponse(BaseModel):
    history: HistorySaveDisposition = Field(default_factory=HistorySaveDisposition)
    scientific_mixed: ScientificMixedEvidence = Field(default_factory=ScientificMixedEvidence)
    evidence_packing: EvidencePackingSummary = Field(default_factory=EvidencePackingSummary)
    input_budget: RagInputBudgetReport = Field(default_factory=RagInputBudgetReport)
    retrieval_generation: IndexReadMetadata = Field(default_factory=IndexReadMetadata)
    scientific_query: ScientificQueryInterpretation | None = None
    scientific_lookup: ScientificLookupStatus = Field(default_factory=ScientificLookupStatus)
    scientific_results: list[LinkedScientificResult] = Field(default_factory=list, max_length=20)
    answer: str  # markdown with [1][2] citations
    sources: list[AskSource]
    tokens_used: int | None
    query_time_ms: int
    citation_valid: bool = Field(False, deprecated=True, description="Legacy citation/lexical heuristic; not scientific support or acceptance.")
    citation_warnings: list[str] = Field(default_factory=list)
    support_policy_version: str = SUPPORT_POLICY_VERSION
    citation_indices_valid: bool = False
    lexical_support_checked: bool = False
    scientific_support_status: SupportStatus = "not_checked"
    claim_assessments: list[ClaimSupportAssessment] = Field(default_factory=list)
    support_warnings: list[str] = Field(default_factory=list)
    support_coverage: dict[str, Any] = Field(default_factory=dict)
    answer_mode: Literal["synthesis", "limited_synthesis", "extractive_fallback", "abstention"] = "abstention"
    assessment_scope: Literal["generated_draft", "none"] = "none"
    guest_remaining: int | None = None
    remaining: int | None = None

    @model_validator(mode="after")
    def scientific_response_coherent(self):
        validate_scientific_response(self)
        validate_mixed_response(self)
        packing = self.evidence_packing
        if packing.status != "packed":
            if any(source.packing_info is not None for source in self.sources):
                raise ValueError("Only a completed packing plan can publish citation grouping")
            if packing.status in {"empty", "base_budget_exceeded", "withheld", "unavailable"} and self.sources:
                raise ValueError("An empty or withheld plan cannot retain sources")
            return self
        from models.evidence_packing import EvidencePackingPlan
        # Reuse the exact private-plan cross-validation (including ordered
        # roles, source/work limits) without disclosing excluded identifiers.
        selected = [source.packing_info for source in self.sources]
        if any(item is None for item in selected) or len(self.sources) != packing.selected_count:
            raise ValueError("Every selected citation needs its exact packing metadata")
        if any(source.index != item.position for source, item in zip(self.sources, selected, strict=True)):
            raise ValueError("Citation indices must preserve packing positions")
        EvidencePackingPlan(status="packed", selected=selected, excluded=[],
            candidate_count=packing.selected_count, selected_count=packing.selected_count,
            source_group_count=packing.source_group_count, diversity_group_count=packing.diversity_group_count,
            payload_bytes=packing.payload_bytes, byte_budget=packing.byte_budget, max_chunks=packing.max_chunks,
            max_per_source=packing.max_per_source, max_per_work=packing.max_per_work)
        identities = {}
        from services.evidence_packing import packing_group_ids
        for source, item in zip(self.sources, selected, strict=True):
            identity = (source.paper_id, item.source_snapshot_sha256)
            if item.source_group_id in identities and identities[item.source_group_id] != identity:
                raise ValueError("One source group cannot mix papers or snapshots")
            identities[item.source_group_id] = identity
            expected_groups = packing_group_ids({"chunk_id": item.chunk_id, "paper_id": source.paper_id,
                "source_snapshot_sha256": item.source_snapshot_sha256, "content_sha256": "0" * 64,
                "chunk_kind": "legacy_unknown", "role_hint": item.role_hint})
            if item.source_group_id != expected_groups["source_group_id"]:
                raise ValueError("Source grouping must bind its actual paper and retained catalogue snapshot")
            if item.group_basis != "accepted_work_mapping" and item.diversity_group_id != expected_groups["diversity_group_id"]:
                raise ValueError("Unmapped diversity must retain its exact source group")
            if item.selection_reason == "complementary_role" and source.evidence_provenance.get("chunk_kind") != "original_passage":
                raise ValueError("A derived or unknown chunk is not a complementary original passage")
        if (self.input_budget.payload_bytes is not None and self.input_budget.payload_bytes != packing.payload_bytes
                or self.input_budget.status == "counted" and self.input_budget.byte_limit != packing.byte_budget):
            raise ValueError("Input preflight and selected complete payload disagree")
        return self


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

class MaterialSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    visibility: dict[str, Any] = Field(default_factory=dict)
    needs_review: bool = True
    review_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def add_result_origin_summary(cls, value: Any) -> Any:
        records = value.get("records") if isinstance(value, dict) else getattr(value, "records", None)
        if isinstance(value, MaterialReadContext):
            records = value.current_records()
        records = [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []
        payload = project_material_properties(value, cls.model_fields, compact="records" not in cls.model_fields)
        summary = classification_summary(records)
        selected_tc = payload["property_evidence"]["properties"].get("tc_max", {}).get("selected")
        payload.update(
            result_classification_version=summary["classifier_version"],
            result_origin_counts=summary["origin_counts"],
            classification_conflicts=summary["conflicted_records"],
            tc_max_origin=selected_tc["origin"].get("knowledge_origin", "Unknown") if selected_tc else "Unknown",
            dominant_evidence=evidence_summary(records),
        )
        return payload

    result_classification_version: str = CLASSIFIER_VERSION
    result_origin_counts: dict[str, int] = Field(default_factory=dict)
    classification_conflicts: int = 0
    tc_max_origin: str = "Unknown"
    matching_results: list[dict[str, Any]] = Field(default_factory=list)
    filter_policy_version: str = FILTER_POLICY_VERSION

    material_semantics: dict[str, Any] = Field(default_factory=dict)
    structure_evidence: dict[str, Any] = Field(default_factory=dict)
    classification_filter_policy_version: str = MATERIAL_SEMANTICS_VERSION
    classification_filter_scope: str = "material_reported_summary_not_joint_state"
    property_evidence: dict[str, Any] = Field(default_factory=dict)
    anomaly_review: dict[str, Any] = Field(default_factory=dict)

    id: str
    formula: str
    formula_latex: str | None
    family: str | None
    subfamily: str | None
    tc_max: float | None
    tc_max_conditions: str | None
    tc_ambient: float | None
    dominant_evidence: str | None = None
    tc_max_experimental: float | None = None
    tc_max_theoretical: float | None = None
    arxiv_year: int | None
    total_papers: int
    status: str
    # v2 — fields the list/table view surfaces directly
    pairing_symmetry: str | None = None
    structure_phase: str | None = None
    ambient_sc: bool | None = None
    is_unconventional: bool | None = None
    has_competing_order: bool | None = None
    # Credibility
    best_credibility_tier: str | None = None
    # P2 — parent-variant
    parent_material_id: str | None = None
    variant_count: int = 0


class VariantSummary(BaseModel):
    """Compact representation of a doping/oxygen variant for the detail page."""
    model_config = ConfigDict(from_attributes=True)
    visibility: dict[str, Any] = Field(default_factory=dict)
    needs_review: bool = True
    review_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def check_ambient_summary(cls, value: Any) -> Any:
        return project_material_properties(value, cls.model_fields, compact=True)

    id: str
    formula: str
    tc_max: float | None = None
    tc_ambient: float | None = None
    total_papers: int = 0
    doping_level: float | None = None
    pressure_type: str | None = None

    property_evidence: dict[str, Any] = Field(default_factory=dict)
    material_semantics: dict[str, Any] = Field(default_factory=dict)
    structure_evidence: dict[str, Any] = Field(default_factory=dict)
    anomaly_review: dict[str, Any] = Field(default_factory=dict)


class PhaseDiagramPoint(BaseModel):
    """One dot on the Tc-vs-doping phase diagram."""
    material_id: str | None = None
    visibility: dict[str, Any] = Field(default_factory=dict)
    formula: str
    tc_kelvin: float
    doping_level: float | None = None
    pressure_gpa: float | None = None
    pressure_semantics: dict[str, Any] = Field(default_factory=dict)
    paper_id: str | None = None
    year: int | None = None


class HydrideTcParameterRecord(BaseModel):
    """Independent hydride enrichment row shown on material detail pages."""
    model_config = ConfigDict(from_attributes=True)
    visibility: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def pressure_metadata(cls, value: Any) -> Any:
        payload = dict(value) if isinstance(value, dict) else {
            name: getattr(value, name) for name in cls.model_fields if hasattr(value, name)
        }
        payload["pressure_semantics"] = classify_pressure(payload).to_dict()
        return payload

    id: int
    material_id: str | None = None
    formula: str
    formula_normalized: str
    paper_id: str
    source: str
    doi: str | None = None
    arxiv_id: str | None = None
    year: int | None = None
    tc_kelvin: float | None = None
    pressure_gpa: float | None = None
    pressure_semantics: dict[str, Any] = Field(default_factory=dict)
    lambda_eph: float | None = None
    mu_star: float | None = None
    omega_log_k: float | None = None
    omega_log_source_value: float | None = None
    omega_log_source_unit: str | None = None
    method: str | None = None
    evidence_type: str | None = None
    confidence: float | None = None
    source_section: str | None = None
    validation_flags: list[Any] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    prompt_version: str
    created_at: datetime
    updated_at: datetime


class MaterialDetail(MaterialSummary):
    crystal_structure: str | None
    records: list[dict[str, Any]]
    raw_archive: dict[str, Any] = Field(default_factory=dict)

    @field_validator("records")
    @classmethod
    def classify_records(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return redact_structure_payloads(annotate_pressure_records(annotate_records(value)))
    # ML Foundation v1 composition enrichment. ``None`` means the legacy row
    # has not yet been processed; ambiguous formulas retain an explicit state
    # instead of fabricated fixed-composition values.
    composition_status: str | None = None
    composition_data: dict[str, Any] | None = None
    composition_enriched_at: datetime | None = None
    # v2 structural
    space_group: str | None = None
    lattice_params: dict[str, Any] | None = None
    # v2 SC parameters
    gap_structure: str | None = None
    hc2_tesla: float | None = None
    hc2_conditions: str | None = None
    lambda_eph: float | None = None
    omega_log_k: float | None = None
    rho_s_mev: float | None = None
    # v2 competing orders
    t_cdw_k: float | None = None
    t_sdw_k: float | None = None
    t_afm_k: float | None = None
    rho_exponent: float | None = None
    competing_order: str | None = None
    # v2 samples + pressure
    pressure_type: str | None = None
    sample_form: str | None = None
    substrate: str | None = None
    doping_type: str | None = None
    doping_level: float | None = None
    # v2 misc flags
    disputed: bool | None = None
    retracted: bool | None = None
    # P2: Interface decomposition
    formula_substrate: str | None = None
    formula_overlayer: str | None = None
    layer_thickness_nm: float | None = None
    # P2: Variants — populated only when this material has children
    variants: list[VariantSummary] = []
    # Phase B — Materials Project linkage. mp_id stays NULL when the
    # formula has no MP match (NIMS oxynitrides, non-stoich cuprates,
    # etc.). mp_alternate_ids is the full polymorph list sorted by
    # energy_above_hull (lowest first); alternate_ids[0] == mp_id when
    # there is a match. The frontend renders a "View on MP" button only
    # when mp_id is set.
    mp_id: str | None = None
    mp_alternate_ids: list[str] = []
    mp_synced_at: datetime | None = None


class MaterialListResponse(BaseModel):
    total: int
    results: list[MaterialSummary]
    limit: int
    offset: int
    sort_basis: Literal["current_projected_catalogue", "legacy_catalogue"] = "current_projected_catalogue"
    scientific_display_policy: Literal["atomic_property_evidence"] = "atomic_property_evidence"


# ---------------------------------------------------------------------------
# Papers
# ---------------------------------------------------------------------------

class PaperSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    arxiv_id: str | None
    doi: str | None
    title: str
    authors: list[str]
    date_submitted: date | None
    material_family: str | None
    status: str
    citation_count: int
    chunk_count: int
    credibility_tier: str | None = None
    paper_type: str | None = None
    journal: str | None = None


class PaperDetail(PaperSummary):
    source_visibility: dict[str, Any] = Field(default_factory=dict)
    occurrence_visibility_summary: dict[str, Any] = Field(default_factory=dict)
    abstract: str
    categories: list[str] | None
    materials_extracted: list[dict[str, Any]]
    quality_flags: list[Any]
    indexed_at: Any  # datetime — serialized by pydantic

    @field_validator("materials_extracted")
    @classmethod
    def classify_materials(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return redact_structure_payloads(annotate_pressure_records(annotate_records(value)))


class SitemapResource(BaseModel):
    """Minimal public resource identity used to generate XML sitemaps."""

    kind: Literal["paper", "material"]
    id: str
    updated_at: datetime


class SitemapResourcePage(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[SitemapResource]


class SimilarPaper(BaseModel):
    paper_id: str
    arxiv_id: str | None
    title: str
    authors: list[str]
    year: int | None
    similarity: float  # 1 - avg cosine distance


class SimilarResponse(BaseModel):
    retrieval_generation: IndexReadMetadata = Field(default_factory=IndexReadMetadata)
    source_paper_id: str
    results: list[SimilarPaper]


# ---------------------------------------------------------------------------
# Stats / Timeline (public)
# ---------------------------------------------------------------------------

class StatsPipelineStage(BaseModel):
    status: Literal["complete", "failed", "unknown"] = "unknown"
    exit_code: int | None = Field(None, ge=0, le=255)


class StatsDataPipeline(BaseModel):
    status: Literal["complete", "partial", "failed", "unknown"] = "unknown"
    last_run_at: str | None = None
    stages: dict[str, StatsPipelineStage] = Field(default_factory=dict)


class StatsRefreshRequest(BaseModel):
    data_pipeline: StatsDataPipeline | None = None


class StatsResponse(BaseModel):
    total_papers: int
    total_materials: int
    total_chunks: int
    papers_by_year: dict[str, int]
    papers_by_year_arxiv: dict[str, int] = Field(default_factory=dict)
    papers_by_year_aps: dict[str, int] = Field(default_factory=dict)
    top_material_families: list[dict[str, Any]]
    last_ingest_at: str | None
    # Explicit cache-computation timestamp. ``updated_at`` remains as a
    # backward-compatible alias for older clients.
    stats_refreshed_at: str | None = None
    updated_at: str
    # Calver string ("v2026.04.30") derived from last_ingest_at — gives
    # users a stable, human-readable handle for "which data snapshot is
    # this answer based on", mirroring Materials Project's
    # `database_version`. None when the DB has never been ingested.
    dataset_version: str | None = None
    data_pipeline: StatsDataPipeline = Field(default_factory=StatsDataPipeline)


class TimelinePoint(BaseModel):
    """One provenance-bearing reported result, not a display cluster."""

    point_id: str | None = None
    result_metadata: dict[str, Any] = Field(default_factory=dict)
    material_id: str | None = None
    visibility: dict[str, Any] = Field(default_factory=dict)

    material: str
    formula_latex: str | None
    family: str | None
    tc_kelvin: float
    year: int
    pressure_gpa: float | None
    pressure_semantics: dict[str, Any] = Field(default_factory=dict)
    paper_id: str | None
    # Legacy compatibility flag only: False does NOT establish an observation.
    # New consumers must use the explicit origin/status fields below.
    is_theoretical: bool = False
    knowledge_origin: str = "Unknown"
    classification_status: str = "unknown"
    source_role: str = "unknown"
    classifier_version: str = CLASSIFIER_VERSION


class TimelineCoverage(BaseModel):
    """Summary counts so the frontend can surface 'N points from M
    materials, years X–Y' without recomputing from the points list.

    ``year_range`` is the inclusive [min, max] of points that survived
    filtering; ``total_materials`` is the distinct material count.
    """

    total_points: int
    total_materials: int
    year_min: int | None
    year_max: int | None
    # Number of points included in this response. This can be lower than
    # ``total_points`` when a caller requests deterministic downsampling.
    returned_points: int
    # Number of points available after optional deterministic downsampling and
    # before offset/limit pagination.
    available_points: int | None = None


class TimelineResponse(BaseModel):
    timeline_policy_version: str = "reported-tc-timeline/2.0.0"
    sampling: dict[str, Any] = Field(default_factory=dict)
    record_summary: dict[str, Any] = Field(default_factory=dict)
    visibility_policy_version: str | None = None
    anomaly_policy_version: str | None = None
    schema_version: Literal["1"] = "1"
    data_version: str = "timeline-v1-unknown"
    data_updated_at: datetime | None = None
    family: str | None
    points: list[TimelinePoint]
    coverage: TimelineCoverage | None = None
    offset: int = 0
    limit: int | None = None
    has_more: bool = False


# ---------------------------------------------------------------------------
# Discovery (reviewed SC SuperLoop feed)
# ---------------------------------------------------------------------------

# Re-export the DB-independent contract so pull validation and public routes
# use exactly the same models without the pull process importing ORM/settings.
from services.discovery_contract import (  # noqa: E402,F401
    DiscoveryCandidate,
    DiscoveryCandidateDetail,
    DiscoveryCandidatePage,
    DiscoveryCandidateSummary,
    DiscoveryFilterRule,
    DiscoveryMetadata,
    DiscoveryResponse,
)
