"""Private, bounded uploads: durable starts, pure parsing, atomic pending rows.

No path or URL in a request is fetched. A committed audit receipt never means
that a calculation was executed, a scientific result approved, or ML admitted.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import threading
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import User, get_engine
from routers.auth import current_user_from_jwt
from routers.research_distributions import _strict_json
from services.research_access import ResearchAccessDenied, active_grant
from services.research_release_manifest import canonical
from services.scientific_import_input import ScientificImportError

HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
MAX_REQUEST_BYTES = 24 * 1024 * 1024
MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_FORCE_CONSTANT_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
REQUEST_TIMEOUT = 45
BODY_TIMEOUT = 10
WORKER_TIMEOUT = 15
RECOVERY_TIMEOUT = 5
_request_slots = threading.BoundedSemaphore(2)
_worker_slots = threading.BoundedSemaphore(2)
_recovery_slots = threading.BoundedSemaphore(2)
_recovery_tasks: set[asyncio.Task] = set()
_CONFLICT_CODES = frozenset({"import_request_key_conflict", "successful_import_package_already_exists",
                           "stale_material_binding"})

Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$")]


class ForceConstants(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    logical_name: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    sha256: Sha
    size_bytes: int = Field(ge=1, le=MAX_FORCE_CONSTANT_BYTES)

    @model_validator(mode="after")
    def safe_name(self):
        if ".." in self.logical_name:
            raise ValueError("unsafe_logical_name")
        return self


class ImportContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["scientific-import-context/1.0.0"]
    material_id: str = Field(min_length=1, max_length=100)
    expected_material_row_sha256: Sha
    force_constants: ForceConstants | None


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_key: Key
    dry_run: bool = True
    manifest: dict
    expected_manifest_sha256: Sha
    artifact_bytes_base64: dict[Sha, str] = Field(max_length=16)
    context: ImportContext
    force_constants_bytes_base64: str | None = None

    @model_validator(mode="after")
    def paired_sidecar(self):
        if (self.context.force_constants is None) != (self.force_constants_bytes_base64 is None):
            raise ValueError("force_constant_bytes_and_pin_must_be_paired")
        return self


@dataclass(frozen=True, slots=True)
class Actor:
    id: UUID
    grant_id: UUID
    session_version: int


def _bad(status, detail):
    return HTTPException(status, detail, headers=HEADERS)


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            if not _request_slots.acquire(blocking=False):
                raise HTTPException(503, "Scientific import capacity unavailable; retry",
                    headers={**HEADERS, "Retry-After": "1"})
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    return await handler(request)
            except ResearchAccessDenied:
                raise _bad(403, "Research curator access required") from None
            except HTTPException as exc:
                details = {400: "Scientific import request rejected", 401: "Authentication required",
                    403: "Research curator access required", 404: "Scientific import unavailable",
                    409: "Scientific import changed; retry", 413: "Scientific import request exceeds limits",
                    415: "JSON content required", 422: "Scientific import request rejected",
                    503: "Scientific import unavailable"}
                headers = {**HEADERS, **({"Retry-After": "1"} if exc.status_code == 503 else {})}
                raise HTTPException(exc.status_code, details.get(exc.status_code, "Scientific import request rejected"),
                                    headers=headers) from None
            except (SQLAlchemyError, TimeoutError):
                raise _bad(503, "Scientific import unavailable") from None
            except ScientificImportError as exc:
                if str(exc) in _CONFLICT_CODES:
                    raise _bad(409, "Scientific import changed; retry") from None
                raise _bad(400, "Scientific import request rejected") from None
            except (ValidationError, ValueError, TypeError, OverflowError, RecursionError):
                raise _bad(400, "Scientific import request rejected") from None
            except Exception:
                raise _bad(503, "Scientific import unavailable") from None
            finally:
                _request_slots.release()

        return guarded


def _enabled():
    if not get_settings().ml_foundation_public_enabled:
        raise _bad(404, "Scientific import unavailable")


router = APIRouter(prefix="/ml/scientific-program-imports", tags=["scientific-program-import-operators"],
                   route_class=PrivateRoute, dependencies=[Depends(_enabled)])


async def _authenticate(request: Request):
    """Reuse session/Origin verification but close its SQL scope before upload."""
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout = '3000ms'"))
            user = await current_user_from_jwt(request=request, authorization=request.headers.get("authorization"), db=db)
            grant = await active_grant(db, user.id, role="curator")
            actor = Actor(user.id, grant["id"], user.session_version)
    return actor


AuthenticatedActor = Annotated[Actor, Depends(_authenticate)]


async def _live_actor(db, actor):
    await active_grant(db, actor.id, role="curator", grant_id=actor.grant_id)
    version = await db.scalar(sa.select(User.session_version).where(User.id == actor.id))
    if version != actor.session_version:
        raise ResearchAccessDenied("session_changed")


async def _body(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise _bad(415, "JSON content required")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise _bad(415, "JSON content required")
    length = request.headers.get("content-length")
    if length is not None and (re.fullmatch(r"[0-9]{1,12}", length) is None or int(length) > MAX_REQUEST_BYTES):
        raise _bad(413, "Scientific import request exceeds limits")
    data = bytearray()
    async with asyncio.timeout(BODY_TIMEOUT):
        async for piece in request.stream():
            if len(data) + len(piece) > MAX_REQUEST_BYTES:
                raise _bad(413, "Scientific import request exceeds limits")
            data.extend(piece)
    return ImportRequest.model_validate(_strict_json(data), strict=True).model_dump()


def _decode(value, limit):
    if type(value) is not str or len(value) > 4 * ((limit + 2) // 3):
        raise _bad(413, "Scientific import request exceeds limits")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("invalid_base64") from None
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("noncanonical_base64")
    if len(decoded) > limit:
        raise _bad(413, "Scientific import request exceeds limits")
    return decoded


def _decode_inputs(body):
    artifacts, size = {}, 0
    for key, value in body.pop("artifact_bytes_base64").items():
        decoded = _decode(value, MAX_ARTIFACT_BYTES)
        size += len(decoded)
        if size > MAX_PACKAGE_BYTES:
            raise _bad(413, "Scientific import request exceeds limits")
        artifacts[key] = decoded
    encoded = body.pop("force_constants_bytes_base64")
    sidecar = None if encoded is None else _decode(encoded, MAX_FORCE_CONSTANT_BYTES)
    body["artifact_bytes"], body["force_constants_bytes"] = artifacts, sidecar
    return body


async def _worker(function, *args, **kwargs):
    """A cancelled HTTP waiter cannot release an unfinished parser's permit."""
    if not _worker_slots.acquire(blocking=False):
        raise _bad(503, "Scientific import capacity unavailable")

    def run():
        try:
            return function(*args, **kwargs)
        finally:
            _worker_slots.release()

    try:
        future = asyncio.get_running_loop().run_in_executor(None, run)
    except BaseException:
        _worker_slots.release()
        raise
    future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    async with asyncio.timeout(WORKER_TIMEOUT):
        return await asyncio.shield(future)


def _bounded(value):
    payload = canonical(value)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("scientific_import_response_limit")
    return payload


def _operation(result, *, dry_run):
    return {"version": "scientific-import-operation/1.0.0", "dry_run": dry_run,
            "committed": not dry_run, "result": result}


async def _write(actor, function, arguments, *, rollback=False, observed=None):
    """Only this boundary owns commits; services retain their savepoint contract."""
    async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as db:
        async with db.begin():
            await db.execute(sa.text("SET LOCAL statement_timeout = '10000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await db.execute(sa.text("SELECT public.sclib_scientific_import_lock_v1()"))
            await _live_actor(db, actor)
            result = await function(db, actor_user_id=actor.id, **arguments)
            # No durable mutation whose JSON response cannot be built. Retain
            # only the bounded ID privately for ambiguous commit recovery.
            encoded = _bounded(_operation(result, dry_run=rollback))
            result = json.loads(encoded)["result"]
            if observed is not None and type(result.get("attempt_id")) is str:
                observed["attempt_id"] = result["attempt_id"]
            if rollback or result.get("replayed") is True:
                await db.rollback()
    return result


async def _read(actor, function, **arguments):
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout = '3000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await _live_actor(db, actor)
            result = await function(db, actor_user_id=actor.id, **arguments)
            payload = _bounded(result)
    return json.loads(payload)


async def _recover(actor, observed, reason_code):
    """Best-effort negative audit; never turn an unknown commit into success.

    A database outage or revoked session may leave the durable start unresolved.
    That is explicitly outcome_unknown and requires a fresh authorized recovery.
    """
    attempt_id = observed.get("attempt_id")
    if attempt_id is None:
        return
    from services.scientific_pending_import import fail_import, inspect_import

    # Repeated cancellation can release the HTTP gate while an earlier shielded
    # recovery is still running. Recovery has its own no-queue budget; exhaustion
    # leaves the durable start unknown, never a fabricated negative receipt.
    if not _recovery_slots.acquire(blocking=False):
        return

    async def settle():
        try:
            async with asyncio.timeout(RECOVERY_TIMEOUT):
                current = await _read(actor, inspect_import, attempt_id=attempt_id)
                if current.get("status") == "outcome_unknown":
                    await _write(actor, fail_import, {"attempt_id": attempt_id, "reason_code": reason_code})
        except Exception:
            # Nothing is inferred when independent recovery cannot commit.
            return

    try:
        task = asyncio.create_task(settle())
    except BaseException:
        _recovery_slots.release()
        raise
    _recovery_tasks.add(task)

    def completed(done):
        _recovery_tasks.discard(done)
        _recovery_slots.release()
        if not done.cancelled():
            done.exception()

    task.add_done_callback(completed)
    await asyncio.shield(task)


def _identifier(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError("canonical_uuid_required")
    return value


@router.post("", openapi_extra={"requestBody": {"required": True, "content": {"application/json": {
    "schema": ImportRequest.model_json_schema()}}}})
async def submit(request: Request, actor: AuthenticatedActor):
    from services import scientific_pending_import as service
    body = _decode_inputs(await _body(request))
    request_key, dry_run = body.pop("request_key"), body.pop("dry_run")
    package = await _worker(service.prepare_input, **body)
    if dry_run:
        prepared = await _worker(service.compile_input, package)
        result = await _write(actor, service.preview_import,
            {"request_key": request_key, "prepared": prepared}, rollback=True)
    else:
        observed, phase = {}, "start"
        try:
            result = await _write(actor, service.start_import,
                {"request_key": request_key, "package": package, "dry_run": False}, observed=observed)
            if result.get("status") == "outcome_unknown":
                phase = "parse"
                prepared = await _worker(service.compile_input, package)
                phase = "finish"
                result = await _write(actor, service.finish_import,
                    {"attempt_id": result["attempt_id"], "prepared": prepared, "dry_run": False})
        except asyncio.CancelledError:
            await _recover(actor, observed, "import_cancelled")
            raise
        except Exception as exc:
            reason = "import_timeout" if isinstance(exc, TimeoutError) else (
                "parser_failed" if phase == "parse" else "import_failed")
            await _recover(actor, observed, reason)
            # Even if fresh inspection finds an already durable terminal after
            # an ambiguous acknowledgement, this failed HTTP call claims none.
            if isinstance(exc, ScientificImportError) and str(exc) in _CONFLICT_CODES:
                raise _bad(409, "Scientific import changed; retry") from None
            if not isinstance(exc, (ResearchAccessDenied, HTTPException)):
                raise _bad(503, "Scientific import unavailable") from None
            raise
    return Response(_bounded(_operation(result, dry_run=dry_run)), media_type="application/json", headers=HEADERS)


@router.get("/material-bindings/{material_id}")
async def material_binding(material_id: str, actor: AuthenticatedActor):
    from services.scientific_pending_import import material_binding as binding
    if not 0 < len(material_id) <= 100:
        raise ValueError("invalid_material_id")
    return Response(_bounded(await _read(actor, binding, material_id=material_id)),
                    media_type="application/json", headers=HEADERS)


@router.get("/{attempt_id}")
async def inspect(attempt_id: str, actor: AuthenticatedActor):
    from services.scientific_pending_import import inspect_import
    return Response(_bounded(await _read(actor, inspect_import, attempt_id=_identifier(attempt_id))),
                    media_type="application/json", headers=HEADERS)
