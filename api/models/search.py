"""Pydantic schemas for the public Phase-3 routers.

Wire format only — ORM classes live in ``models.db``. Keeping request
and response shapes here means a breaking API change does not require
a database migration, and vice versa.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class SearchFilters(BaseModel):
    year_min: int | None = Field(None, ge=1900, le=2100)
    year_max: int | None = Field(None, ge=1900, le=2100)
    material_family: list[str] | None = None
    tc_min: float | None = Field(None, ge=0)
    pressure_max: float | None = Field(None, ge=0)
    exclude_retracted: bool = True


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000)
    top_k: int = Field(20, ge=1, le=100)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    sort: Literal["relevance", "date", "tc"] = "relevance"


class SearchMatch(BaseModel):
    """One hit in a search response."""

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


class SearchResponse(BaseModel):
    total: int
    results: list[SearchMatch]
    query_time_ms: int
    guest_remaining: int | None = None
    remaining: int | None = None


# ---------------------------------------------------------------------------
# Ask (RAG)
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    max_sources: int = Field(10, ge=1, le=20)
    language: Literal["auto", "en", "zh"] = "auto"


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


class AskResponse(BaseModel):
    answer: str  # markdown with [1][2] citations
    sources: list[AskSource]
    tokens_used: int | None
    query_time_ms: int
    citation_valid: bool = True
    citation_warnings: list[str] = Field(default_factory=list)
    guest_remaining: int | None = None
    remaining: int | None = None


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

class MaterialSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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

    id: str
    formula: str
    tc_max: float | None = None
    tc_ambient: float | None = None
    total_papers: int = 0
    doping_level: float | None = None
    pressure_type: str | None = None


class PhaseDiagramPoint(BaseModel):
    """One dot on the Tc-vs-doping phase diagram."""
    formula: str
    tc_kelvin: float
    doping_level: float | None = None
    pressure_gpa: float | None = None
    paper_id: str | None = None
    year: int | None = None


class HydrideTcParameterRecord(BaseModel):
    """Independent hydride enrichment row shown on material detail pages."""
    model_config = ConfigDict(from_attributes=True)

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
    abstract: str
    categories: list[str] | None
    materials_extracted: list[dict[str, Any]]
    quality_flags: list[Any]
    indexed_at: Any  # datetime — serialized by pydantic


class SimilarPaper(BaseModel):
    paper_id: str
    arxiv_id: str | None
    title: str
    authors: list[str]
    year: int | None
    similarity: float  # 1 - avg cosine distance


class SimilarResponse(BaseModel):
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
    """One dot on the Tc-vs-year Plotly scatter."""

    material: str
    formula_latex: str | None
    family: str | None
    tc_kelvin: float
    year: int
    pressure_gpa: float | None
    paper_id: str | None
    # True iff the underlying record is a calculation rather than an
    # experimental measurement. The frontend renders these as hollow
    # rings so users can distinguish DFT predictions (e.g. P/Cl-doped
    # H₃S at 200 K) from confirmed lab measurements. Defaults False
    # so any caller that doesn't set it gets the safer "experimental"
    # styling rather than mis-marking real data as theory.
    is_theoretical: bool = False


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

class DiscoveryFilterRule(BaseModel):
    key: str
    label: str
    value: str


class DiscoveryCandidate(BaseModel):
    schema_version: Literal["1"] = "1"
    candidate_id: str
    formula: str
    normalized_formula: str | None = None
    branch: str
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
    evidence_level: str
    checker_status: str
    public_confidence: str
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


class DiscoveryResponse(BaseModel):
    schema_version: Literal["1"] = "1"
    page_title: str
    intro: list[str]
    status: Literal["planned", "active"] = "planned"
    updated_at_utc: datetime | None = None
    source: str | None = None
    filter_rules: list[DiscoveryFilterRule]
    candidates: list[DiscoveryCandidate]


class DiscoveryCandidateSummary(BaseModel):
    """Fields required to render one collapsed discovery result.

    The full dossier remains available from the candidate detail endpoint, so
    list pages do not repeatedly transfer long evidence and provenance arrays.
    """

    schema_version: Literal["1"] = "1"
    candidate_id: str
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


class DiscoveryMetadata(BaseModel):
    schema_version: Literal["1"] = "1"
    page_title: str
    intro: list[str]
    status: Literal["planned", "active"] = "planned"
    updated_at_utc: datetime | None = None
    source: str | None = None
    filter_rules: list[DiscoveryFilterRule]
    total_candidates: int
    role_counts: dict[str, int]


class DiscoveryCandidatePage(BaseModel):
    schema_version: Literal["1"] = "1"
    items: list[DiscoveryCandidateSummary]
    total: int
    offset: int
    limit: int
    has_more: bool
    record_role: str | None = None
