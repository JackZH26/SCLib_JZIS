"""Administrator-only operational status, not scientific or external delivery."""
from __future__ import annotations

import asyncio
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import User, get_engine
from routers.auth import current_user_from_jwt
from services.background_jobs import BackgroundJobError, inspect_background_jobs
from services.research_release_manifest import canonical

router = APIRouter(prefix="/admin/background-jobs", tags=["background jobs"])
_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


async def admin_snapshot(request: Request, authorization: str | None = Header(default=None)):
    try:
        async with asyncio.timeout(10):
            async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
                async with db.begin():
                    await db.execute(sa.text("SET TRANSACTION READ ONLY"))
                    await db.execute(sa.text("SET LOCAL statement_timeout = '5000ms'"))
                    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                    # Reuse the existing JWT/cookie/session-version validator,
                    # but include its DB lookup inside this same bounded snapshot.
                    user = await current_user_from_jwt(request, authorization, db)
                    account = (await db.execute(sa.select(User.is_active, User.is_admin).where(User.id == user.id))).one_or_none()
                    if account is None or not account.is_active or not account.is_admin:
                        raise HTTPException(403, "Administrator access required", headers=_HEADERS)
                    yield db
    except (SQLAlchemyError, TimeoutError):
        raise HTTPException(503, "Background job registry unavailable", headers=_HEADERS) from None


@router.get("")
async def background_job_status(db: Annotated[AsyncSession, Depends(admin_snapshot)]):
    try:
        body = await inspect_background_jobs(db)
        return Response(canonical(body), media_type="application/json", headers=_HEADERS)
    except (BackgroundJobError, SQLAlchemyError):
        raise HTTPException(503, "Background job registry unavailable", headers=_HEADERS) from None
