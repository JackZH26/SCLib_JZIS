"""Private reviewer workflow for exact result/original-passage links."""
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
from services import scientific_result_passage as service
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical

_slots = threading.BoundedSemaphore(4)
_MESSAGES = {
    400: "Invalid or unsupported reviewed result-passage request",
    401: "Authentication required",
    403: "Current research reviewer authority required for this action",
    404: "Reviewed result-passage receipt unavailable",
    409: "Review evidence, actor, request or link head changed; refresh the exact preview",
    413: "Reviewed result-passage request exceeds the bounded size",
    415: "Reviewed result-passage request requires JSON",
    422: "Invalid reviewed result-passage request",
    503: "Reviewed result-passage workflow temporarily unavailable; a submitted outcome may be unknown",
}


def _failure(status):
    return HTTPException(status, _MESSAGES.get(status, _MESSAGES[400]), headers=HEADERS)


class ResultPassageRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            if not _slots.acquire(blocking=False):
                raise _failure(503)
            try:
                async with asyncio.timeout(20):
                    return await handler(request)
            except service.ResultPassageConflict:
                raise _failure(409) from None
            except ResearchAccessDenied:
                raise _failure(403) from None
            except service.ResultPassageUnavailable:
                raise _failure(503) from None
            except SQLAlchemyError as exc:
                original = getattr(exc, "orig", exc)
                state = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
                raise _failure(403 if state == "42501" else 409 if state in {
                    "40001", "40P01", "55P03", "23505", "23514", "23503",
                } else 503) from None
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


router = APIRouter(prefix="/ml/scientific-review/result-passage-links",
                   tags=["scientific-result-passage"], route_class=ResultPassageRoute,
                   dependencies=[Depends(enabled)])


@asynccontextmanager
async def _session(request, *, write=False):
    isolation = "SERIALIZABLE" if write else "REPEATABLE READ"
    async with AsyncSession(get_engine().execution_options(isolation_level=isolation)) as db:
        async with db.begin():
            if not write:
                await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            actor = await current_user_from_jwt(request=request,
                authorization=request.headers.get("authorization"), db=db)
            yield db, actor.id


async def _body(request):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise _failure(415)
    length = request.headers.get("content-length")
    if length is not None and (not length.isdigit() or len(length) > 10 or int(length) > service.MAX_BYTES):
        raise _failure(413)
    value = bytearray()
    async for piece in request.stream():
        if len(value) + len(piece) > service.MAX_BYTES:
            raise _failure(413)
        value.extend(piece)
    return service.loads(bytes(value))


def _response(value):
    payload = canonical(value)
    if len(payload) > service.MAX_RESPONSE_BYTES:
        raise service.ResultPassageUnavailable("Reviewed link response exceeds its byte limit")
    return Response(payload, media_type="application/json", headers=HEADERS)


@router.post("/context")
async def context(request: Request):
    async with _session(request) as (db, actor):
        await service._reader(db, actor)
        body = await _body(request)
        if type(body) is not dict or set(body) != {"parent_result_revision_id", "source_evidence_revision_id"}:
            raise ValueError("A closed exact-pair context request is required")
        value = await service.action_context(db, actor_user_id=actor, **body)
    return _response(value)


@router.post("/preview")
async def preview(request: Request):
    async with _session(request, write=True) as (db, actor):
        await service._reviewer(db, actor)
        value = await service.review(db, actor_user_id=actor, request=await _body(request), dry_run=True)
    return _response(value)


@router.post("/commit")
async def commit(request: Request):
    async with _session(request, write=True) as (db, actor):
        await service._reviewer(db, actor)
        body = await _body(request)
        if type(body) is not dict or set(body) != {"request", "expected_preview_sha256"}:
            raise ValueError("A closed exact-pair commit request is required")
        value = await service.review(db, actor_user_id=actor, request=body["request"],
            expected_preview_sha256=body["expected_preview_sha256"], dry_run=False)
    return _response({**value, "committed": True})


@router.get("/requests/{request_key}")
async def receipt(request: Request, request_key: str):
    async with _session(request) as (db, actor):
        value = await service.inspect_request(db, actor_user_id=actor, request_key=request_key)
        if value is None:
            raise _failure(404)
    return _response(value)
