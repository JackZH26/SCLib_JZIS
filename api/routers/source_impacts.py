"""Operator-only point-in-time lifecycle and dependency inspections.

These GET routes do not enqueue refresh, persist receipts or clear source holds.
Authentication and live grant checks remain separate from manifest checksums.
"""
from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import User, get_engine
from routers.auth import current_user_from_jwt
from services.research_access import ResearchAccessDenied, require_research_operator
from services.research_release_manifest import canonical
from services.source_lifecycle import SourceLifecycleError, inspect_source_lifecycle

_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def enabled():
    if not get_settings().ml_foundation_public_enabled:
        raise HTTPException(404, "Not found", headers=_HEADERS)


async def impact_read_session():
    try:
        async with asyncio.timeout(10):
            async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as session:
                async with session.begin():
                    await session.execute(sa.text("SET TRANSACTION READ ONLY"))
                    await session.execute(sa.text("SET LOCAL statement_timeout = '5000ms'"))
                    await session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                    yield session
    except (SQLAlchemyError, TimeoutError):
        raise HTTPException(503, "Source impact registry unavailable", headers=_HEADERS) from None


async def operator_snapshot(
    user: Annotated[User, Depends(current_user_from_jwt)],
    db: Annotated[AsyncSession, Depends(impact_read_session)],
):
    # Recheck the explicit grant and account within the same snapshot as the
    # inventory. A valid JWT or legacy administrator flag alone is insufficient.
    try:
        await require_research_operator(db, user.id)
    except ResearchAccessDenied:
        raise HTTPException(403, "Research operator access required", headers=_HEADERS) from None
    except SQLAlchemyError:
        raise HTTPException(503, "Research access registry unavailable", headers=_HEADERS) from None
    return db


router = APIRouter(prefix="/ml/source-lifecycle", tags=["source-impact"], dependencies=[Depends(enabled)])
OperatorSnapshot = Annotated[AsyncSession, Depends(operator_snapshot)]


@router.get("")
async def source_history(
    db: OperatorSnapshot,
    paper_id: str | None = Query(None, min_length=1, max_length=100),
    work_id: UUID | None = None,
    limit: int = Query(25, ge=1, le=100),
    before_revision: int | None = Query(None, ge=1, le=2_147_483_647),
):
    if (paper_id is None) == (work_id is None):
        raise HTTPException(422, "Select exactly one Paper or Work", headers=_HEADERS)
    try:
        body = await inspect_source_lifecycle(db, paper_id=paper_id, work_id=work_id,
                                             limit=limit, before_revision=before_revision)
        return Response(canonical(body), media_type="application/json", headers=_HEADERS)
    except SourceLifecycleError:
        raise HTTPException(404, "Source lifecycle unavailable", headers=_HEADERS) from None
    except SQLAlchemyError:
        raise HTTPException(503, "Source impact registry unavailable", headers=_HEADERS) from None


@router.get("/{event_id}/impact")
async def source_impact(
    event_id: UUID,
    db: OperatorSnapshot,
    expected_event_sha256: str = Query(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
):
    from services.source_impact import (
        SourceImpactError,
        SourceImpactLimitError,
        inspect_source_impact,
    )

    try:
        body = await inspect_source_impact(db, event_id=event_id, expected_event_sha256=expected_event_sha256)
        return Response(canonical(body), media_type="application/json", headers=_HEADERS)
    except SourceImpactLimitError:
        raise HTTPException(409, {"code": "impact_inventory_incomplete",
            "message": "The source impact inventory exceeds its declared safe scope or limits.",
            "complete_for_declared_scope": False, "refresh_execution": "not_scheduled"}, headers=_HEADERS) from None
    except (SourceImpactError, SourceLifecycleError):
        raise HTTPException(409, "Source impact unavailable or source revision changed", headers=_HEADERS) from None
    except SQLAlchemyError:
        raise HTTPException(503, "Source impact registry unavailable", headers=_HEADERS) from None
