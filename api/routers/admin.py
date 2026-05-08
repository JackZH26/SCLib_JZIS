"""/admin/* — site-administration endpoints.

Gated behind ``current_admin_user``; non-admins get 403. Three
groups today:

* **users**: list, ban (deactivate), unban, delete
* **audit reports**: most recent runs of the nightly audit
* **audit queue**: materials currently flagged ``needs_review=TRUE``
  + admin override (``confirm`` keeps the flag, ``override`` clears
  it and records the admin's decision in ``materials.admin_decision``)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.admin import (
    AdminOverview,
    AdminUserListResponse,
    AdminUserSummary,
    AuditOverridePayload,
    AuditQueueItem,
    AuditQueueResponse,
    AuditReportSummary,
)
from models.db import AuditReport, Material, User
from models.user import MessageResponse
from routers.auth import current_user_from_jwt

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def current_admin_user(
    user: User = Depends(current_user_from_jwt),
) -> User:
    """JWT auth + is_admin gate. Returns 403 instead of 401 so the
    user knows they're authenticated but not authorised."""
    if not user.is_admin:
        raise HTTPException(403, "Admin role required")
    return user


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    q: str | None = Query(None, description="Substring match on email or name"),
    role: str | None = Query(None, regex="^(admin|active|inactive)?$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(current_admin_user),
) -> AdminUserListResponse:
    base = select(User)
    count_stmt = select(func.count()).select_from(User)

    def _apply(clause):
        nonlocal base, count_stmt
        base = base.where(clause)
        count_stmt = count_stmt.where(clause)

    if q:
        like = f"%{q.lower()}%"
        _apply(
            (func.lower(User.email).like(like))
            | (func.lower(User.name).like(like))
        )
    if role == "admin":
        _apply(User.is_admin.is_(True))
    elif role == "active":
        _apply(User.is_active.is_(True))
    elif role == "inactive":
        _apply(User.is_active.is_(False))

    base = base.order_by(User.created_at.desc()).limit(limit).offset(offset)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(base)).scalars().all()

    return AdminUserListResponse(
        total=int(total or 0),
        results=[AdminUserSummary.model_validate(u) for u in rows],
        limit=limit,
        offset=offset,
    )


@router.post("/users/{user_id}/ban", response_model=MessageResponse)
async def ban_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(current_admin_user),
) -> MessageResponse:
    """Set is_active=FALSE. Reversible; the user can be unbanned at any time."""
    if user_id == admin.id:
        raise HTTPException(400, "An admin cannot ban themselves")
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if target.is_admin:
        raise HTTPException(400, "Cannot ban another admin; demote first")
    target.is_active = False
    await db.commit()
    log.warning("admin %s banned user %s", admin.email, target.email)
    return MessageResponse(message=f"Banned {target.email}")


@router.post("/users/{user_id}/unban", response_model=MessageResponse)
async def unban_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(current_admin_user),
) -> MessageResponse:
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    target.is_active = True
    await db.commit()
    log.info("admin %s unbanned user %s", admin.email, target.email)
    return MessageResponse(message=f"Unbanned {target.email}")


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(current_admin_user),
) -> MessageResponse:
    """Hard delete + cascading. Requires the user to NOT be an admin
    and NOT be the caller. ``ON DELETE CASCADE`` on api_keys /
    bookmarks / ask_history / email_verifications takes care of the
    children automatically."""
    if user_id == admin.id:
        raise HTTPException(400, "An admin cannot delete themselves")
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if target.is_admin:
        raise HTTPException(
            400, "Cannot delete another admin; demote first via SQL",
        )
    email = target.email
    await db.delete(target)
    await db.commit()
    log.warning("admin %s deleted user %s", admin.email, email)
    return MessageResponse(message=f"Deleted {email}")


# ---------------------------------------------------------------------------
# Audit reports
# ---------------------------------------------------------------------------

@router.get("/audit/reports", response_model=list[AuditReportSummary])
async def list_audit_reports(
    rule: str | None = Query(None, description="Filter to one rule name"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(current_admin_user),
) -> list[AuditReportSummary]:
    """Newest-first list of audit_reports rows. Default returns the
    last ~50 across all rules; pass ``?rule=…`` to drill into one
    rule's history."""
    stmt = select(AuditReport)
    if rule:
        stmt = stmt.where(AuditReport.rule_name == rule)
    stmt = stmt.order_by(AuditReport.started_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [AuditReportSummary.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Audit queue
# ---------------------------------------------------------------------------

@router.get("/audit/queue", response_model=AuditQueueResponse)
async def audit_queue(
    rule: str | None = Query(None, description="Filter to one rule name"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(current_admin_user),
) -> AuditQueueResponse:
    base = select(Material).where(Material.needs_review.is_(True))
    count_stmt = (
        select(func.count())
        .select_from(Material)
        .where(Material.needs_review.is_(True))
    )
    if rule:
        base = base.where(Material.review_reason == rule)
        count_stmt = count_stmt.where(Material.review_reason == rule)

    base = (
        base.order_by(Material.tc_max.desc().nulls_last(), Material.id)
        .limit(limit)
        .offset(offset)
    )
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(base)).scalars().all()

    return AuditQueueResponse(
        total=int(total or 0),
        results=[
            AuditQueueItem(
                id=m.id,
                formula=m.formula,
                family=m.family,
                tc_max=m.tc_max,
                review_reason=m.review_reason,
                total_papers=m.total_papers,
                has_admin_decision=m.admin_decision is not None,
            )
            for m in rows
        ],
        limit=limit,
        offset=offset,
    )


@router.post("/audit/queue/{material_id}/override", response_model=MessageResponse)
async def override_flag(
    material_id: str,
    body: AuditOverridePayload,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(current_admin_user),
) -> MessageResponse:
    """Clear the flag and record the admin's decision. Subsequent
    nightly runs check ``admin_decision->>'rule'`` and skip rows
    whose flag has been overridden — so manual review work persists
    across audits."""
    m = await db.get(Material, material_id)
    if m is None:
        raise HTTPException(404, "Material not found")
    if not m.needs_review:
        raise HTTPException(400, "Material is not currently flagged")
    m.admin_decision = {
        "rule": m.review_reason,
        "reviewer": admin.email,
        "reviewer_id": str(admin.id),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "note": body.note,
        "action": "override",
    }
    m.needs_review = False
    m.review_reason = None
    await db.commit()
    log.info("admin %s overrode flag on material %s: %s",
             admin.email, material_id, body.note)
    return MessageResponse(message=f"Override recorded for {material_id}")


@router.post("/audit/queue/{material_id}/confirm", response_model=MessageResponse)
async def confirm_flag(
    material_id: str,
    body: AuditOverridePayload,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(current_admin_user),
) -> MessageResponse:
    """Keep the flag but record that an admin has reviewed and
    confirmed it (audit trail)."""
    m = await db.get(Material, material_id)
    if m is None:
        raise HTTPException(404, "Material not found")
    m.admin_decision = {
        "rule": m.review_reason,
        "reviewer": admin.email,
        "reviewer_id": str(admin.id),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "note": body.note,
        "action": "confirm",
    }
    await db.commit()
    return MessageResponse(message=f"Confirmation recorded for {material_id}")


# ---------------------------------------------------------------------------
# Overview tile for the admin landing page
# ---------------------------------------------------------------------------

@router.get("/overview", response_model=AdminOverview)
async def admin_overview(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(current_admin_user),
) -> AdminOverview:
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    active_users = (
        await db.execute(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        )
    ).scalar_one()
    admins = (
        await db.execute(
            select(func.count()).select_from(User).where(User.is_admin.is_(True))
        )
    ).scalar_one()

    total_mats = (
        await db.execute(select(func.count()).select_from(Material))
    ).scalar_one()
    flagged_mats = (
        await db.execute(
            select(func.count()).select_from(Material).where(Material.needs_review.is_(True))
        )
    ).scalar_one()

    flagged_by_reason_q = await db.execute(
        select(Material.review_reason, func.count())
        .where(Material.needs_review.is_(True))
        .group_by(Material.review_reason)
    )
    flagged_by_reason = {
        (k or "unknown"): int(v) for k, v in flagged_by_reason_q.all()
    }

    last_audit_q = await db.execute(
        select(AuditReport.started_at, func.sum(AuditReport.rows_flagged))
        .group_by(AuditReport.started_at)
        .order_by(AuditReport.started_at.desc())
        .limit(1)
    )
    row = last_audit_q.first()
    last_started, last_total = (row[0], int(row[1] or 0)) if row else (None, None)

    return AdminOverview(
        total_users=int(total_users or 0),
        active_users=int(active_users or 0),
        admins=int(admins or 0),
        total_materials=int(total_mats or 0),
        flagged_materials=int(flagged_mats or 0),
        flagged_by_reason=flagged_by_reason,
        last_audit_started=last_started,
        last_audit_total_flagged=last_total,
    )
