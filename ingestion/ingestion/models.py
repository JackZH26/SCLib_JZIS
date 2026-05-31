"""Lightweight dataclasses used across pipeline stages.

These are *not* ORM models — database writes go through
ingestion.index.indexer using SQLAlchemy Core statements against the same
schema defined by api/models/db.py. Keeping ingestion decoupled from the
API ORM avoids a circular dependency and keeps ingestion runnable without
api/ on the Python path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class PaperMetadata:
    """Metadata harvested from arXiv OAI-PMH before the full text is fetched."""

    arxiv_id: str                         # "2306.07275"
    title: str
    authors: list[str]
    abstract: str
    date_submitted: date | None
    categories: list[str]
    primary_category: str | None
    doi: str | None = None

    @property
    def paper_id(self) -> str:
        return f"arxiv:{self.arxiv_id}"

    @property
    def yymm(self) -> str:
        """First 4 chars of arxiv_id (e.g. '2306') for GCS sharding."""
        # Both old ("cond-mat/0607123") and new ("2306.07275") arxiv ids
        # have a recognizable 4-digit prefix once the slash is stripped.
        stripped = self.arxiv_id.replace("cond-mat/", "").replace("/", "")
        return stripped[:4]

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly projection for the failure pool (no dataclasses.asdict
        because ``date`` doesn't round-trip through json natively)."""
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "date_submitted": self.date_submitted.isoformat() if self.date_submitted else None,
            "categories": self.categories,
            "primary_category": self.primary_category,
            "doi": self.doi,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaperMetadata":
        ds = data.get("date_submitted")
        return cls(
            arxiv_id=data["arxiv_id"],
            title=data["title"],
            authors=list(data.get("authors", [])),
            abstract=data.get("abstract", ""),
            date_submitted=date.fromisoformat(ds) if ds else None,
            categories=list(data.get("categories", [])),
            primary_category=data.get("primary_category"),
            doi=data.get("doi"),
        )


# ---------------------------------------------------------------------------
# APS (American Physical Society) — TDM ingestion source
# ---------------------------------------------------------------------------

#: APS DOIs are minted as ``10.1103/<JournalToken>.<vol>.<article>`` — the
#: token after ``10.1103/`` and before the first ``.`` reliably identifies
#: the journal, so we derive ``journal`` / ``journal_abbrev`` from the DOI
#: itself rather than guessing at metadata-JSON field names. Maps the DOI
#: token to (full name, short handle stored in papers.journal_abbrev).
APS_JOURNAL_BY_DOI_TOKEN: dict[str, tuple[str, str]] = {
    "PhysRev": ("Physical Review", "PR"),
    "PhysRevLett": ("Physical Review Letters", "PRL"),
    "PhysRevA": ("Physical Review A", "PRA"),
    "PhysRevB": ("Physical Review B", "PRB"),
    "PhysRevC": ("Physical Review C", "PRC"),
    "PhysRevD": ("Physical Review D", "PRD"),
    "PhysRevE": ("Physical Review E", "PRE"),
    "PhysRevX": ("Physical Review X", "PRX"),
    "RevModPhys": ("Reviews of Modern Physics", "RMP"),
    "PhysRevApplied": ("Physical Review Applied", "PRApplied"),
    "PhysRevMaterials": ("Physical Review Materials", "PRMaterials"),
    "PhysRevFluids": ("Physical Review Fluids", "PRFluids"),
    "PhysRevAccelBeams": ("Physical Review Accelerators and Beams", "PRAB"),
    "PhysRevResearch": ("Physical Review Research", "PRResearch"),
    "PhysRevPhysEducRes": ("Physical Review Physics Education Research", "PRPER"),
    "PRXQuantum": ("PRX Quantum", "PRXQuantum"),
    "PRXEnergy": ("PRX Energy", "PRXEnergy"),
    "PRXLife": ("PRX Life", "PRXLife"),
}


def journal_from_doi(doi: str) -> tuple[str | None, str | None]:
    """Return (journal_full, journal_abbrev) inferred from an APS DOI.

    ``10.1103/PhysRevB.108.054515`` → ("Physical Review B", "PRB").
    Returns (None, None) for a non-APS or unrecognised DOI so callers can
    fall back to whatever the metadata JSON provides.
    """
    if not doi:
        return (None, None)
    d = doi.strip().lower()
    # Strip a leading doi.org URL / "doi:" prefix if present.
    for pre in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(pre):
            d = d[len(pre):]
            break
    if not d.startswith("10.1103/"):
        return (None, None)
    suffix = doi.strip().split("10.1103/", 1)[1]
    token = suffix.split(".", 1)[0]
    return APS_JOURNAL_BY_DOI_TOKEN.get(token, (None, None))


@dataclass
class ApsArticleMeta:
    """Authorized metadata for one APS article (from the Harvest API).

    This is the *persistent* slice of an APS paper — title, abstract,
    authors, and bibliographic reference — all within the agreement's
    Appendix A scope. The full text (BagIt) is fetched separately and is
    transient TDM working data, never stored here.

    ``paper_id`` is ``aps:{doi}``, mirroring arXiv's ``arxiv:{id}``.
    ``id_scheme`` is always ``'doi'`` for APS rows.
    """

    doi: str
    title: str
    authors: list[str]
    abstract: str
    journal: str | None = None          # "Physical Review B"
    journal_abbrev: str | None = None   # "PRB"
    volume: str | None = None
    issue: str | None = None
    article_id: str | None = None       # e.g. "054515"
    page: str | None = None
    date_published: date | None = None
    categories: list[str] = field(default_factory=list)

    @property
    def paper_id(self) -> str:
        return f"aps:{self.doi}"

    @property
    def doi_slug(self) -> str:
        """Filesystem- / blob-safe DOI for temp paths and audit rows."""
        return self.doi.replace("/", "_")

    def publication_ref(self) -> dict[str, Any]:
        """JSONB payload for ``papers.publication_ref`` (drops empty keys)."""
        ref = {
            "volume": self.volume,
            "issue": self.issue,
            "article_id": self.article_id,
            "page": self.page,
            "published_date": self.date_published.isoformat()
            if self.date_published else None,
        }
        return {k: v for k, v in ref.items() if v is not None}

    def to_dict(self) -> dict[str, Any]:
        return {
            "doi": self.doi,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "journal": self.journal,
            "journal_abbrev": self.journal_abbrev,
            "volume": self.volume,
            "issue": self.issue,
            "article_id": self.article_id,
            "page": self.page,
            "date_published": self.date_published.isoformat()
            if self.date_published else None,
            "categories": self.categories,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApsArticleMeta":
        dp = data.get("date_published")
        return cls(
            doi=data["doi"],
            title=data.get("title", ""),
            authors=list(data.get("authors", [])),
            abstract=data.get("abstract", ""),
            journal=data.get("journal"),
            journal_abbrev=data.get("journal_abbrev"),
            volume=data.get("volume"),
            issue=data.get("issue"),
            article_id=data.get("article_id"),
            page=data.get("page"),
            date_published=date.fromisoformat(dp) if dp else None,
            categories=list(data.get("categories", [])),
        )


@dataclass
class ParsedPaper:
    """Result of parsing a LaTeX source archive (or PDF fallback)."""

    meta: PaperMetadata
    sections: list["Section"]
    #: Raw plain-text abstract, possibly re-extracted from the LaTeX body
    #: if the OAI-PMH metadata lacked one (rare).
    abstract_override: str | None = None
    has_latex_source: bool = True


@dataclass
class Section:
    name: str                             # "Introduction", "Methods", ...
    text: str                             # detexed body
    has_equation: bool = False
    has_table: bool = False


@dataclass
class Chunk:
    """One vector-search unit. id pattern matches Vertex VS datapoint id."""

    id: str                               # "arxiv:2306.07275_chunk_005"
    paper_id: str
    chunk_index: int
    section: str
    text: str
    token_count: int
    has_equation: bool = False
    has_table: bool = False
    #: filled in after embedding
    embedding: list[float] | None = None
    materials_mentioned: list[dict[str, Any]] = field(default_factory=list)
