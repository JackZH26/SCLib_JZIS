"""Private read-only scientific evidence workbench; no adjudication endpoint."""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import get_engine
from routers.auth import current_user_from_jwt
from services import scientific_result_dossier as dossier
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical
from services.scientific_result_impact import ScientificResultImpactUnavailable

HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
_slots = threading.BoundedSemaphore(4)


class PrivateReadRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request):
            if not _slots.acquire(blocking=False):
                raise HTTPException(503, "Scientific review temporarily unavailable", headers=HEADERS)
            try:
                async with asyncio.timeout(10):
                    return await handler(request)
            except ResearchAccessDenied:
                raise HTTPException(403, "Current research curator or reviewer access required", headers=HEADERS) from None
            except RequestValidationError:
                raise HTTPException(422, "Invalid scientific review query", headers=HEADERS) from None
            except HTTPException as exc:
                raise HTTPException(exc.status_code, {401: "Authentication required", 403: "Research access required",
                    404: "Scientific review unavailable", 422: "Invalid scientific review query"}.get(
                        exc.status_code, "Scientific review request rejected"), headers=HEADERS) from None
            except (SQLAlchemyError, TimeoutError, ScientificResultImpactUnavailable):
                raise HTTPException(503, "Scientific review temporarily unavailable", headers=HEADERS) from None
            except (ValueError, TypeError, OverflowError, RecursionError):
                raise HTTPException(400, "Scientific evidence snapshot unavailable or unsupported", headers=HEADERS) from None
            except Exception:
                raise HTTPException(503, "Scientific review temporarily unavailable", headers=HEADERS) from None
            finally:
                _slots.release()
        return guarded


def enabled():
    if not get_settings().ml_foundation_public_enabled:
        raise HTTPException(404, "Scientific review unavailable", headers=HEADERS)


router = APIRouter(prefix="/ml/scientific-review", tags=["scientific-review-readers"],
                   route_class=PrivateReadRoute, dependencies=[Depends(enabled)])


@asynccontextmanager
async def read(request):
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout = '5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            actor = await current_user_from_jwt(request=request, authorization=request.headers.get("authorization"), db=db)
            yield db, actor.id


def response(body):
    payload = canonical(body)
    if len(payload) > dossier.MAX_RESPONSE_BYTES:
        raise ValueError("scientific_review_response_limit")
    return Response(payload, media_type="application/json", headers=HEADERS)


@router.get("/capabilities")
async def capabilities(request: Request):
    async with read(request) as (db, actor):
        return response(await dossier.capabilities(db, actor_user_id=actor))


@router.get("/results")
async def results(request: Request, after: str | None = Query(None, max_length=36),
                  limit: int = Query(25, ge=1, le=50)):
    async with read(request) as (db, actor):
        return response(await dossier.list_results(db, actor_user_id=actor, after=after, limit=limit))


@router.get("/results/{property_id}")
async def detail(request: Request, property_id: str):
    async with read(request) as (db, actor):
        return response(await dossier.result_dossier(db, actor_user_id=actor, property_id=property_id))
