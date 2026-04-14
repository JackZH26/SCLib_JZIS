"""Pydantic schemas for the public Phase-3 routers.

Wire format only — ORM classes live in ``models.db``. Keeping request
and response shapes here means a breaking API change does not require
a database migration, and vice versa.
"""
from __future__ import annotations

from datetime import date
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
    relevance_score: float  # higher = better (1 - cosine distance)
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
    guest_remaining: int | None = None


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
    discovery_year: int | None
    total_papers: int
    status: str


class MaterialDetail(MaterialSummary):
    crystal_structure: str | None
    pairing_symmetry: str | None
    records: list[dict[str, Any]]


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

class StatsResponse(BaseModel):
    total_papers: int
    total_materials: int
    total_chunks: int
    papers_by_year: dict[str, int]
    top_material_families: list[dict[str, Any]]
    last_ingest_at: str | None
    updated_at: str


class TimelinePoint(BaseModel):
    """One dot on the Tc-vs-year Plotly scatter."""

    material: str
    formula_latex: str | None
    family: str | None
    tc_kelvin: float
    year: int
    pressure_gpa: float | None
    paper_id: str | None


class TimelineResponse(BaseModel):
    family: str | None
    points: list[TimelinePoint]
