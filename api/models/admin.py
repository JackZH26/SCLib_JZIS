"""Pydantic wire schemas for /admin endpoints.

Lives alongside ``models/user.py`` and ``models/personal.py`` —
shape only; persistence stays in ``models/db.py``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Users management
# ---------------------------------------------------------------------------

class AdminUserSummary(BaseModel):
    """Compact user record for the admin user-list table.

    Includes the operational columns (email_verified, is_active,
    is_admin, created_at, last_login) so admins don't need to drill
    into a detail page for routine triage.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    institution: str | None = None
    country: str | None = None
    research_area: str | None = None
    is_active: bool
    is_admin: bool
    is_reviewer: bool = False
    email_verified: bool
    auth_provider: str
    created_at: datetime
    last_login: datetime | None = None


class AdminUserListResponse(BaseModel):
    total: int
    results: list[AdminUserSummary]
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Audit queue
# ---------------------------------------------------------------------------

class AuditReportSummary(BaseModel):
    """One nightly audit_reports row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    started_at: datetime
    completed_at: datetime
    rule_name: str
    severity: str
    rows_flagged: int
    delta_vs_previous: int | None = None
    sample_ids: list[str] = Field(default_factory=list)


class AuditQueueItem(BaseModel):
    """One flagged material in the admin review queue."""

    id: str
    formula: str
    family: str | None = None
    tc_max: float | None = None
    review_reason: str | None = None
    total_papers: int = 0
    has_admin_decision: bool = False


class AuditQueueResponse(BaseModel):
    total: int
    results: list[AuditQueueItem]
    limit: int
    offset: int


class AuditOverridePayload(BaseModel):
    """Body for POST /admin/audit/queue/{id}/override."""

    note: str = Field(..., min_length=1, max_length=500)


# ---------------------------------------------------------------------------
# Site-wide stats for the admin landing
# ---------------------------------------------------------------------------

class AdminOverview(BaseModel):
    total_users: int
    active_users: int
    admins: int
    total_materials: int
    flagged_materials: int
    flagged_by_reason: dict[str, int]
    last_audit_started: datetime | None = None
    last_audit_total_flagged: int | None = None
