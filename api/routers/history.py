"""GET/DELETE /history — per-user Ask history.

Rows are written by ``routers.ask`` on every successful authenticated
/ask call. A periodic task in ``main.py`` prunes rows older than 90
days (product decision — see project memory file).

Both endpoints use the JWT auth path (``current_user_from_jwt``). Ask
history is dashboard-UI data, not something external API-key clients
need to read, so we don't expose it on the X-API-Key path.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import AskHistory, User
from models.personal import AskHistoryEntry, AskHistoryListResponse
from models.user import MessageResponse
from routers.auth import current_user_from_jwt

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=AskHistoryListResponse)
async def list_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
) -> AskHistoryListResponse:
    """List the current user's Ask history, newest first.

    Paginated because power users can accumulate hundreds of entries
    within the 90-day window. Frontend default page size is 50.
    """
    # total first so the dashboard can render the "N questions" counter
    # without pulling all rows
    total_q = await db.execute(
        select(func.count()).select_from(AskHistory)
        .where(AskHistory.user_id == user.id)
    )
    total = int(total_q.scalar_one() or 0)

    q = await db.execute(
        select(AskHistory)
        .where(AskHistory.user_id == user.id)
        .order_by(AskHistory.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = q.scalars().all()
    return AskHistoryListResponse(
        total=total,
        results=[AskHistoryEntry.model_validate(r) for r in rows],
        limit=limit,
        offset=offset,
    )


@router.delete("/{entry_id}", response_model=MessageResponse)
async def delete_history_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
) -> MessageResponse:
    """Delete one history entry owned by the current user.

    Cross-user deletes 404 (not 403) so an attacker can't confirm whether
    a specific UUID exists.
    """
    row = await db.get(AskHistory, entry_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "History entry not found")
    await db.delete(row)
    await db.commit()
    return MessageResponse(message="Deleted")
