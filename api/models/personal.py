"""Pydantic wire schemas for per-user private data.

Lives in its own module so the auth-focused ``user.py`` stays small.
Everything here requires JWT auth — no guest access.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Ask history
# ---------------------------------------------------------------------------

class AskHistoryEntry(BaseModel):
    """One row from /history.

    ``sources`` is the JSONB snapshot saved at answer time. It mirrors
    the :class:`AskSource` shape from ``models.search`` but we type it
    as a generic list so the history API doesn't break when AskSource
    grows new fields (older rows wouldn't have them).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    question: str
    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    tokens_used: int | None = None
    latency_ms: int
    language: str | None = None
    created_at: datetime


class AskHistoryListResponse(BaseModel):
    total: int
    results: list[AskHistoryEntry]
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------

BookmarkTargetType = Literal["paper", "material"]


class BookmarkCreate(BaseModel):
    target_type: BookmarkTargetType
    target_id: str = Field(..., min_length=1, max_length=100)


class BookmarkRead(BaseModel):
    """Raw bookmark row as returned by POST and DELETE responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    target_type: BookmarkTargetType
    target_id: str
    created_at: datetime


class BookmarkedPaper(BaseModel):
    """Bookmark entry joined with papers.* for the dashboard list view."""

    id: UUID
    target_id: str
    created_at: datetime
    # Hydrated from papers table
    title: str
    authors: list[str]
    date_submitted: date | None
    material_family: str | None
    status: str
    citation_count: int


class BookmarkedMaterial(BaseModel):
    """Bookmark entry joined with materials.* for the dashboard list view."""

    id: UUID
    target_id: str
    created_at: datetime
    # Hydrated from materials table
    formula: str
    formula_latex: str | None
    family: str | None
    tc_max: float | None
    tc_ambient: float | None
    arxiv_year: int | None


class BookmarkedPapersResponse(BaseModel):
    total: int
    results: list[BookmarkedPaper]


class BookmarkedMaterialsResponse(BaseModel):
    total: int
    results: list[BookmarkedMaterial]


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

FeedbackCategory = Literal["bug", "feature_request", "data_issue", "other"]


class FeedbackCreate(BaseModel):
    """POST /feedback body.

    Feedback requires login (product decision — no anonymous channel).
    The server-side handler appends the submitter's user_id / name /
    email / user-agent / IP before sending to the inbox, so the client
    only needs to provide what the user actually typed.
    """

    category: FeedbackCategory = "other"
    message: str = Field(..., min_length=5, max_length=2000)
    # Optional: if the user wants replies sent somewhere other than
    # their account email (e.g. work address). Purely a hint to the
    # recipient — we do not validate that it is reachable.
    contact_email: str | None = Field(None, max_length=255)
