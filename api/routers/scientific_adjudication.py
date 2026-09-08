"""Authenticated exact-result adjudication, separate from the v1 read dossier."""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_engine
from routers.auth import current_user_from_jwt
from routers.scientific_review import HEADERS, enabled
from services import scientific_adjudication as service
from services import scientific_adjudication_contract as contract
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical
from services.scientific_result_effects import ScientificResultStatusUnavailable
from services.scientific_result_subject import ScientificSubjectUnavailable

_slots = threading.BoundedSemaphore(4)
MESSAGES = {
    400: "Invalid or unsupported scientific adjudication request",
    401: "Authentication required",
    403: "Current research reviewer authority required for this action",
    404: "Scientific adjudication or request receipt unavailable",
    409: "Review evidence, actor, request or decision head conflicts; refresh the exact preview",
    413: "Scientific adjudication request exceeds the bounded size",
    415: "Scientific adjudication requires JSON",
    422: "Invalid scientific adjudication request",
    503: "Scientific adjudication temporarily unavailable; a submitted decision outcome may be unknown",
}


def _failure(status):
    return HTTPException(status, MESSAGES.get(status, MESSAGES[400]), headers=HEADERS)


def _sql_status(exc):
    original = getattr(exc, "orig", exc)
    state = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if state == "42501":
        return 403
    if state in {"40001", "40P01", "55P03", "23505", "23514", "23503"}:
        return 409
    return 503


class AdjudicationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request):
            if not _slots.acquire(blocking=False):
                raise _failure(503)
            try:
                async with asyncio.timeout(20):
                    return await handler(request)
            except contract.ScientificAdjudicationConflict:
                raise _failure(409) from None
            except ResearchAccessDenied:
                raise _failure(403) from None
            except (contract.ScientificAdjudicationUnavailable, ScientificSubjectUnavailable,
                    ScientificResultStatusUnavailable, TimeoutError):
                raise _failure(503) from None
            except SQLAlchemyError as exc:
                raise _failure(_sql_status(exc)) from None
            except RequestValidationError:
                raise _failure(422) from None
            except HTTPException as exc:
                raise _failure(exc.status_code) from None
            except (ValueError, TypeError, OverflowError, RecursionError):
                raise _failure(400) from None
            except Exception:
                raise _failure(503) from None
            finally:
                _slots.release()
        return guarded


router = APIRouter(prefix="/ml/scientific-review/adjudication", tags=["scientific-adjudication"],
                   route_class=AdjudicationRoute, dependencies=[Depends(enabled)])


@asynccontextmanager
async def _session(request, *, write=False):
    isolation = "SERIALIZABLE" if write else "REPEATABLE READ"
    async with AsyncSession(get_engine().execution_options(isolation_level=isolation)) as db:
        async with db.begin():
            if not write:
                await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            actor = await current_user_from_jwt(request=request, authorization=request.headers.get("authorization"), db=db)
            yield db, actor.id


async def _body(request, *, max_bytes=contract.MAX_BYTES):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise _failure(415)
    length = request.headers.get("content-length")
    if length is not None and (not length.isdigit() or len(length) > 10 or int(length) > max_bytes):
        raise _failure(413)
    payload = bytearray()
    async for piece in request.stream():
        if len(payload) + len(piece) > max_bytes:
            raise _failure(413)
        payload.extend(piece)
    return contract.loads(bytes(payload), max_bytes=max_bytes)


def _response(value):
    payload = canonical(value)
    if len(payload) > contract.MAX_RESPONSE_BYTES:
        raise contract.ScientificAdjudicationUnavailable("adjudication_response_limit")
    return Response(payload, media_type="application/json", headers=HEADERS)


@router.post("/context")
async def context(request: Request):
    async with _session(request) as (db, actor):
        # Reject unprivileged slow streams before reading their bodies. The
        # service still rechecks authority with its exact snapshot/lock checks.
        await service._reader(db, actor)
        body = await _body(request)
        contract.require(type(body) is dict and set(body) == {"property_ids"}, "closed_adjudication_context_required")
        value = await service.action_context(db, actor_user_id=actor, property_ids=body["property_ids"])
    return _response(value)


@router.post("/preview")
async def preview(request: Request):
    # Real SQL rehearsal uses a write-capable transaction, but its savepoint
    # always rolls back, including every guard epoch and deferred row.
    async with _session(request, write=True) as (db, actor):
        await service._reviewer(db, actor)
        value = await service.adjudicate(db, actor_user_id=actor, request=await _body(request), dry_run=True)
    return _response(value)


@router.post("/commit")
async def commit(request: Request):
    async with _session(request, write=True) as (db, actor):
        await service._reviewer(db, actor)
        body = await _body(request, max_bytes=contract.MAX_COMMIT_BYTES)
        contract.require(type(body) is dict and set(body) == {"request", "expected_preview_sha256"},
                         "closed_adjudication_commit_required")
        value = await service.adjudicate(db, actor_user_id=actor, request=body["request"],
            expected_preview_sha256=body["expected_preview_sha256"], dry_run=False)
    # Do not emit committed=true before the actual outer commit succeeds.
    return _response({**value, "committed": True})


@router.get("/requests/{request_key}")
async def receipt(request: Request, request_key: str):
    async with _session(request) as (db, actor):
        value = await service.inspect_request(db, actor_user_id=actor, request_key=request_key)
        if value is None:
            raise _failure(404)
    return _response({**value, "committed": True})
