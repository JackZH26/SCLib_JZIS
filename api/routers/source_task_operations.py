"""Private, bounded operator workflow for Timeline invalidation only.

No worker, external cache operation or source reinstatement is scheduled here.
All success receipts acknowledge committed historical records, not a currently
rebuilt Timeline or completed cross-system propagation.
"""
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
from models.source_tasks_v1 import ACTION_VERSION
from routers.auth import current_user_from_jwt
from routers.source_impacts import _HEADERS as HEADERS
from routers.source_impacts import enabled
from services import source_task_operations as service
from services.research_access import ResearchAccessDenied, active_grant
from services.research_release_manifest import canonical
from services.source_impact import SourceImpactError, SourceImpactLimitError
from services.source_lifecycle import SourceLifecycleError
from services.source_tasks import SourceTaskError

_slots = threading.BoundedSemaphore(2)
MESSAGES = {
    400: "Invalid or unsupported source task operation",
    401: "Authentication required",
    403: "Current explicit research curator authority required",
    404: "Source task receipt unavailable in the current snapshot",
    409: "Source task evidence, actor, request or attempt head changed; refresh the exact preview",
    413: "Source task operation exceeds the bounded size",
    415: "Source task operations require JSON",
    422: "Invalid source task operation",
    503: "Source task operations temporarily unavailable; a submitted outcome may be unknown",
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


class SourceTaskOperationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            if not _slots.acquire(blocking=False):
                raise _failure(503)
            try:
                async with asyncio.timeout(20):
                    return await handler(request)
            except ResearchAccessDenied:
                raise _failure(403) from None
            except (service.SourceTaskOperationConflict, SourceTaskError,
                    SourceImpactError, SourceImpactLimitError, SourceLifecycleError):
                raise _failure(409) from None
            except (service.SourceTaskOperationUnavailable, TimeoutError):
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


router = APIRouter(prefix="/ml/source-lifecycle/task-operations", tags=["source-task-operations"],
                   route_class=SourceTaskOperationRoute, dependencies=[Depends(enabled)])


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
            # Check before consuming even the first request-body chunk. Services
            # independently recheck exact grants inside their mutation fence.
            await active_grant(db, actor.id, role="curator")
            yield db, actor.id


async def _body(request, *, max_bytes=8192):
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
    return service.loads(bytes(payload), max_bytes=max_bytes)


async def _admitted_body(request, *, max_bytes=8192):
    # Reject unauthorized uploads without consuming them, but do not carry that
    # pre-upload snapshot into the mutation. A session can be revoked while the
    # bounded body is streaming. Replays do not INSERT and cannot rely on the
    # insertion trigger's actor row lock to detect that intervening revocation.
    async with _session(request):
        pass
    return await _body(request, max_bytes=max_bytes)


def _response(value):
    payload = canonical(value)
    if len(payload) > service.MAX_RESPONSE_BYTES:
        raise service.SourceTaskOperationUnavailable("source_task_response_limit")
    return Response(payload, media_type="application/json", headers=HEADERS)


@router.get("/capabilities")
async def capabilities(request: Request):
    async with _session(request) as (db, actor):
        grant = await active_grant(db, actor, role="curator")
        response = _response({
            "version": "source-task-capabilities/1.0.0", "actor_user_id": str(actor),
            "actor_grant_id": str(grant["id"]), "can_read": True, "can_write": True,
            "action_version": ACTION_VERSION, "propagation_complete": False,
            "timeline_rebuilt": False, "scientific_acceptance": False,
            "ml_training_approved": False, "source_reinstatement": False,
            "external_cache_invalidated": False,
        })
    return response


@router.post("/preview")
async def preview(request: Request):
    body = await _admitted_body(request)
    async with _session(request, write=True) as (db, actor):
        value = await service.preview_operation(db, actor_user_id=actor, request=body)
        # Even lock-epoch writes must be a SQL no-op, irrespective of service
        # savepoint implementation details. No provisional receipt escapes.
        await db.rollback()
        response = _response(value)
    return response


@router.post("/commit")
async def commit(request: Request):
    body = service.validate_commit(await _admitted_body(request, max_bytes=service.MAX_COMMIT_BYTES))
    async with _session(request, write=True) as (db, actor):
        value = await service.commit_operation(db, actor_user_id=actor, request=body["request"],
                                               expected_preview_sha256=body["expected_preview_sha256"])
        if value["replayed"]:
            # Replay acknowledges the old durable receipt. Rolling back the
            # entire dedicated transaction also undoes its guard-epoch writes.
            await db.rollback()
        response = _response({**value, "committed": True, "requires_outer_commit": False})
    # The response is returned only AFTER a new outer transaction has committed.
    # A commit/connection failure therefore has an unknown outcome, never a
    # false success and never an automatic write retry under a different key.
    return response


@router.get("/requests/{request_key}")
async def request_receipt(request: Request, request_key: str):
    async with _session(request) as (db, actor):
        value = await service.inspect_by_key(db, actor_user_id=actor, request_key=request_key)
        if value is None:
            raise _failure(404)
        response = _response({**value, "committed": True, "requires_outer_commit": False})
    return response


@router.get("/requests/{request_id}/executions/{execution_key}")
async def execution_receipt(request: Request, request_id: str, execution_key: str):
    async with _session(request) as (db, actor):
        value = await service.inspect_execution(db, actor_user_id=actor, request_id=request_id,
                                               execution_key=execution_key)
        if value is None:
            raise _failure(404)
        response = _response({**value, "committed": True, "requires_outer_commit": False})
    return response
