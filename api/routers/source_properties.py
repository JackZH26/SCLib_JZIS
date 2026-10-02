"""Private pending source-expression ledger, independently disabled by default."""
from __future__ import annotations

import asyncio
import base64
import binascii
import re
import threading
from contextlib import asynccontextmanager

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import get_engine
from routers.auth import current_user_from_jwt
from routers.research_distributions import _strict_json
from services import source_property_pending as service
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical
from services.source_property_contract import SourcePropertyContractError

HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
MAX_BODY_BYTES = 1536 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_slots = threading.BoundedSemaphore(4)
MESSAGES = {400: "Unsupported or invalid pending source-property request", 401: "Authentication required",
    403: "Current explicit research role required", 404: "Pending source-property interface or receipt unavailable",
    409: "Source-property request, authority or exact preview conflicts; refresh",
    413: "Pending source-property request exceeds limits", 415: "Uncompressed JSON required",
    422: "Invalid pending source-property request", 503: "Pending source-property temporarily unavailable; submission outcome may be unknown"}


def _failure(status):
    return HTTPException(status, MESSAGES.get(status, MESSAGES[400]), headers=HEADERS)


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            if not _slots.acquire(blocking=False):
                raise _failure(503)
            try:
                async with asyncio.timeout(20):
                    if len(request.scope.get("query_string", b"")) > 2048:
                        raise _failure(413)
                    return await handler(request)
            except service.SourcePropertyConflict:
                raise _failure(409) from None
            except service.SourcePropertyNotFound:
                raise _failure(404) from None
            except ResearchAccessDenied:
                raise _failure(403) from None
            except HTTPException as exc:
                raise _failure(exc.status_code) from None
            except RequestValidationError:
                raise _failure(422) from None
            except SQLAlchemyError as exc:
                orig = getattr(exc, "orig", exc)
                state = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
                status = 403 if state == "42501" else 409 if state in {"40001", "40P01", "55P03", "23505", "23514", "23503"} else 503
                raise _failure(status) from None
            except TimeoutError:
                raise _failure(503) from None
            except (SourcePropertyContractError, service.SourcePropertyError, ValueError, TypeError, OverflowError, RecursionError):
                raise _failure(400) from None
            except Exception:
                raise _failure(503) from None
            finally:
                _slots.release()

        return guarded


def enabled():
    if not get_settings().source_property_pending_enabled:
        raise _failure(404)


router = APIRouter(prefix="/research/source-properties", tags=["pending-source-properties"],
                   route_class=PrivateRoute, dependencies=[Depends(enabled)])


@asynccontextmanager
async def _session(request, *, write=False, role=None):
    async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE" if write else "REPEATABLE READ")) as db:
        async with db.begin():
            if not write:
                await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            actor = await current_user_from_jwt(request=request, authorization=request.headers.get("authorization"), db=db)
            if role is None:
                await service.reader(db, actor.id)
            else:
                await service._grant(db, actor.id, role, session_version=actor.session_version)
            yield db, actor.id


async def _body(request, *, keys):
    if (request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
            or request.headers.get("content-encoding", "identity").lower() != "identity"):
        raise _failure(415)
    length = request.headers.get("content-length")
    if length is not None and (not re.fullmatch(r"[0-9]{1,10}", length) or int(length) > MAX_BODY_BYTES):
        raise _failure(413)
    data = bytearray()
    async with asyncio.timeout(8):
        async for piece in request.stream():
            if len(data) + len(piece) > MAX_BODY_BYTES:
                raise _failure(413)
            data.extend(piece)
    value = _strict_json(data)
    service.require(set(value) == keys, "closed_request_required")
    return value


def _source_bytes(encoded):
    if type(encoded) is not str or len(encoded) > 4 * ((1048576 + 2) // 3):
        raise _failure(413)
    try:
        value = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise service.SourcePropertyError("invalid_base64") from None
    service.require(base64.b64encode(value).decode("ascii") == encoded, "canonical_base64_required")
    return value


def _response(value, *, download=False):
    payload = canonical(value)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise _failure(503)
    headers = {**HEADERS, **({"Content-Disposition": 'attachment; filename="pending-source-observation.json"'} if download else {})}
    return Response(payload, media_type="application/json", headers=headers)


@router.get("/capabilities")
async def capabilities(request: Request):
    async with _session(request) as (db, actor):
        return _response(await service.capabilities(db, actor_user_id=actor))


@router.post("/imports/preview")
async def import_preview(request: Request):
    async with _session(request, write=True, role="curator") as (db, actor):
        body = await _body(request, keys={"request_key", "source_bytes_base64"})
        value = await service.import_snapshot(db, actor_user_id=actor, request_key_value=body["request_key"],
                                             source_bytes=_source_bytes(body["source_bytes_base64"]), dry_run=True)
    return _response(value)


@router.post("/imports/commit")
async def import_commit(request: Request):
    async with _session(request, write=True, role="curator") as (db, actor):
        body = await _body(request, keys={"request_key", "source_bytes_base64", "expected_preview_sha256"})
        service.checksum(body["expected_preview_sha256"])
        value = await service.import_snapshot(db, actor_user_id=actor, request_key_value=body["request_key"],
            source_bytes=_source_bytes(body["source_bytes_base64"]), dry_run=False,
            expected_preview_sha256=body["expected_preview_sha256"])
    return _response(value)


@router.get("/imports/outcome")
async def import_outcome(request: Request, request_key: str, expected_request_sha256: str):
    async with _session(request, role="curator") as (db, actor):
        return _response(await service.lookup_import(db, actor_user_id=actor, request_key_value=request_key,
                                                    expected_request_sha256=expected_request_sha256))


@router.get("/observations")
async def observations(request: Request, offset: int = 0, limit: int = 25, field_id: str | None = None,
                       source_role: str | None = None, profile: str | None = None):
    async with _session(request) as (db, actor):
        return _response(await service.observations(db, actor_user_id=actor, offset=offset, limit=limit,
                                                   field_id=field_id, source_role=source_role, profile=profile))


@router.get("/observations/{observation_id}/download")
async def download(request: Request, observation_id: str):
    async with _session(request) as (db, actor):
        return _response(await service.observation(db, actor_user_id=actor, observation_id=observation_id), download=True)


@router.get("/observations/{observation_id}")
async def observation(request: Request, observation_id: str):
    async with _session(request) as (db, actor):
        return _response(await service.observation(db, actor_user_id=actor, observation_id=observation_id))


@router.post("/reviews/preview")
async def review_preview(request: Request):
    async with _session(request, write=True, role="reviewer") as (db, actor):
        body = await _body(request, keys={"request"})
        value = await service.append_review(db, actor_user_id=actor, request=body["request"], dry_run=True)
    return _response(value)


@router.post("/reviews/commit")
async def review_commit(request: Request):
    async with _session(request, write=True, role="reviewer") as (db, actor):
        body = await _body(request, keys={"request", "expected_preview_sha256"})
        service.checksum(body["expected_preview_sha256"])
        value = await service.append_review(db, actor_user_id=actor, request=body["request"], dry_run=False,
                                           expected_preview_sha256=body["expected_preview_sha256"])
    return _response(value)


@router.get("/reviews/outcome")
async def review_outcome(request: Request, request_key: str, expected_request_sha256: str):
    async with _session(request, role="reviewer") as (db, actor):
        return _response(await service.lookup_review(db, actor_user_id=actor, request_key_value=request_key,
                                                    expected_request_sha256=expected_request_sha256))
