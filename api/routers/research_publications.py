"""Publication-only metadata reads; raw research routes remain operator-only."""
from __future__ import annotations

import asyncio
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import get_engine
from services.research_access import ResearchAccessDenied
from services.research_freeze import ResearchFreezeError
from services.research_public_contract import PublicResearchVerificationError
from services.research_publication import (
    PublicationUnavailable,
    admitted_publication,
    public_inventory,
)
from services.research_release_manifest import ResearchReleaseVerificationError, canonical


def enabled():
    if not get_settings().ml_foundation_public_enabled:
        raise HTTPException(404, "Not found", headers={"Cache-Control": "private, no-store"})


async def publication_read_session():
    # A dedicated snapshot avoids mixing authentication/quota queries and
    # READ COMMITTED governance snapshots. Request scope, no cross-request cache.
    try:
        async with asyncio.timeout(10):
            async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as session:
                async with session.begin():
                    await session.execute(sa.text("SET TRANSACTION READ ONLY"))
                    await session.execute(sa.text("SET LOCAL statement_timeout = '5000ms'"))
                    yield session
    except (SQLAlchemyError, TimeoutError):
        raise HTTPException(503, "Publication registry unavailable", headers=_HEADERS) from None


router = APIRouter(prefix="/ml/releases", tags=["research-publications"], dependencies=[Depends(enabled)])
_UNAVAILABLE = (PublicationUnavailable, ResearchAccessDenied, ResearchFreezeError, PublicResearchVerificationError,
                ResearchReleaseVerificationError)
_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


@router.get("")
async def list_publications(db=Depends(publication_read_session)):
    try:
        body = await public_inventory(db)
        return Response(canonical(body), media_type="application/json", headers=_HEADERS)
    except _UNAVAILABLE:
        raise HTTPException(503, "Publication inventory unavailable", headers=_HEADERS) from None
    except SQLAlchemyError:
        raise HTTPException(503, "Publication registry unavailable", headers=_HEADERS) from None


@router.get("/{publication_id}")
@router.get("/{publication_id}/manifest")
@router.get("/{publication_id}/download")
async def public_publication(publication_id: UUID, db=Depends(publication_read_session)):
    try:
        proposal = await admitted_publication(db, publication_id)
        # Exact canonical bytes are shared by detail/manifest/download; no
        # internal URI redirect or second, weaker download admission exists.
        return Response(canonical(proposal["public_payload"]), media_type="application/json",
                        headers={**_HEADERS, "X-Public-Manifest-SHA256": proposal["payload_sha256"]})
    except _UNAVAILABLE:
        raise HTTPException(404, "Publication unavailable", headers=_HEADERS) from None
    except SQLAlchemyError:
        raise HTTPException(503, "Publication registry unavailable", headers=_HEADERS) from None
