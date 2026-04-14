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
