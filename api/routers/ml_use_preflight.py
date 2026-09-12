"""Private read-only ML-use intake. No submission, rights grant or execution."""
from __future__ import annotations

import asyncio
import re
import threading
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import User, get_engine
from models.ml_use_request import INPUTS, MAX_BYTES, identifier, sha, validate_request
from routers.auth import current_user_from_jwt
from routers.research_distributions import _request_schema, _strict_json
from services.ml_dataset_builder import AUTHORITY
from services.ml_use_access import HEADERS
from services.ml_use_preflight import (
    VERSION,
    MlUsePreflightConflict,
    admission,
    preflight_ml_use,
)
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical

_slots = threading.BoundedSemaphore(2)
AuthenticatedUser = Annotated[User, Depends(current_user_from_jwt)]


def rejected(status):
    messages = {400: "ML use request rejected", 401: "Authentication required", 403: "ML use inspection access denied",
                404: "ML use inspection unavailable", 409: "ML use request or registration changed",
                413: "ML use request exceeds limits", 415: "JSON content required", 503: "ML use inspection unavailable"}
    return HTTPException(status, messages[status], headers=HEADERS)


class PrivateRoute(APIRoute):
    timeout_seconds = 20

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            if not _slots.acquire(blocking=False):
                raise rejected(503)
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    return await handler(request)
            except ResearchAccessDenied:
                raise rejected(403) from None
            except MlUsePreflightConflict:
                raise rejected(409) from None
            except HTTPException as exc:
                raise rejected(exc.status_code if exc.status_code in {400, 401, 403, 404, 409, 413, 415, 503} else 503) from None
            except (RequestValidationError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
                raise rejected(400) from None
            except (SQLAlchemyError, TimeoutError):
                raise rejected(503) from None
            except Exception:
                raise rejected(503) from None
            finally:
                _slots.release()

        return guarded


def enabled():
    if not get_settings().ml_use_governance_enabled:
        raise rejected(404)


router = APIRouter(prefix="/ml/use/preflight", tags=["ml-use-preflight"], route_class=PrivateRoute,
                   dependencies=[Depends(enabled)])


class PreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request: dict
    expected_request_sha256: str
    expected_requester_grant_id: str
    expected_curator_grant_id: str

    @model_validator(mode="after")
    def exact_pins(self):
        self.request = validate_request(self.request)
        sha(self.expected_request_sha256)
        identifier(self.expected_requester_grant_id)
        identifier(self.expected_curator_grant_id)
        return self


async def _read(user, args=None):
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            if await db.scalar(sa.select(User.session_version).where(User.id == user.id)) != user.session_version:
                raise ResearchAccessDenied("session_changed")
            if args is None:
                result = {"version": VERSION, "admission": await admission(db, user.id),
                          "scope": "private_ml_use_intake_inspection_only", "training_execution": "disabled",
                          "data_access_granted": False, "source_permission_granted": False, "run_authorization_granted": False,
                          **AUTHORITY}
            else:
                result = await preflight_ml_use(db, actor_user_id=user.id, **args)
            return canonical(result)


async def _body(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise rejected(415)
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise rejected(415)
    length = request.headers.get("content-length")
    if length is not None and (re.fullmatch(r"[0-9]{1,8}", length) is None or int(length) > MAX_BYTES + 2048):
        raise rejected(413)
    raw, chunks = bytearray(), 0
    async with asyncio.timeout(5):
        async for part in request.stream():
            chunks += 1
            if chunks > 4096 or len(raw) + len(part) > MAX_BYTES + 2048:
                raise rejected(413)
            raw.extend(part)
    return PreflightRequest.model_validate(_strict_json(bytes(raw))).model_dump()


@router.get("/access")
async def access(user: AuthenticatedUser):
    return Response(await _read(user), media_type="application/json", headers=HEADERS)


@router.post("", openapi_extra=_request_schema(PreflightRequest))
async def inspect(request: Request, user: AuthenticatedUser):
    await _read(user)  # strong admission before processing a private declaration
    args = await _body(request)
    # Recheck session/account and exact memberships after body receipt in the
    # same read-only snapshot as the complete source/dependency observation.
    return Response(await _read(user, args), media_type="application/json", headers=HEADERS)


class ReconstructionRoute(PrivateRoute):
    timeout_seconds = 60


reconstruction_router = APIRouter(route_class=ReconstructionRoute)


class ReconstructionEnvelope(PreflightRequest):
    version: Literal["ml-use-reconstruction/1.0.0"]
    inputs_base64: dict[str, str] = Field(min_length=8, max_length=8, json_schema_extra={
        "properties": {name: {"type": "string", "contentEncoding": "base64"} for name in INPUTS},
        "required": list(INPUTS), "additionalProperties": False})
    artifacts_base64: dict[str, str] = Field(max_length=256)


async def _reconstruction_body(request):
    from services.ml_use_reconstruction import MAX_ENVELOPE_BYTES
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise rejected(415)
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise rejected(415)
    length = request.headers.get("content-length")
    if length is not None and (re.fullmatch(r"[0-9]{1,8}", length) is None or int(length) > MAX_ENVELOPE_BYTES):
        raise rejected(413)
    raw, chunks = bytearray(), 0
    async with asyncio.timeout(10):
        async for part in request.stream():
            chunks += 1
            if chunks > 4096 or len(raw) + len(part) > MAX_ENVELOPE_BYTES:
                raise rejected(413)
            raw.extend(part)
    return bytes(raw)


async def _rebuild_request(request, user):
    import hashlib

    from services.ml_audited_dataset import loads
    from services.ml_use_reconstruction import FIELDS, require
    from services.ml_use_reconstruction import VERSION as RECONSTRUCTION_VERSION
    from services.ml_use_reconstruction_worker import reconstruct_in_worker

    await _read(user)  # No private bytes or worker before current admission.
    raw = await _reconstruction_body(request)
    envelope = loads(raw)
    require(type(envelope) is dict and set(envelope) == FIELDS and envelope["version"] == RECONSTRUCTION_VERSION)
    args = PreflightRequest.model_validate({key: envelope[key] for key in PreflightRequest.model_fields}).model_dump()
    # Avoid spending reconstruction resources on stale roles or unregistered data.
    await _read(user, args)
    rebuilt = await reconstruct_in_worker(raw)
    require(rebuilt["request_sha256"] == args["expected_request_sha256"]
            and rebuilt["envelope_sha256"] == hashlib.sha256(raw).hexdigest()
            and rebuilt["all_eight_input_bytes_verified"] is True
            and rebuilt["dataset_and_preparation_rebuilt"] is True)
    return raw, args, rebuilt


@reconstruction_router.post("/reconstruct", openapi_extra=_request_schema(ReconstructionEnvelope))
async def reconstruct(request: Request, user: AuthenticatedUser):
    from services.ml_audited_dataset import loads
    from services.ml_use_preflight import MAX_RESPONSE_BYTES
    from services.ml_use_reconstruction import VERSION as RECONSTRUCTION_VERSION
    from services.ml_use_reconstruction import require

    _, args, rebuilt = await _rebuild_request(request, user)
    # A fresh SQL snapshot observes logout, role revocation or source changes
    # committed while the CPU worker was running. It grants no lasting lease.
    result = loads(await _read(user, args))
    result.update(version=RECONSTRUCTION_VERSION, online_private_input_reconstruction_verified=True,
                  reconstruction=rebuilt, companion_observations_rechecked_online=False)
    result["blockers"] = sorted((set(result["blockers"]) - {"private_input_bytes_not_rebuilt_online"})
                                | {"companion_observations_not_rechecked_online"})
    output = canonical(result)
    require(len(output) <= MAX_RESPONSE_BYTES)
    return Response(output, media_type="application/json", headers=HEADERS)


router.include_router(reconstruction_router)


class CurrentReconstructionRoute(PrivateRoute):
    timeout_seconds = 90


currentness_router = APIRouter(route_class=CurrentReconstructionRoute)


@currentness_router.post("/reconstruct/current", openapi_extra=_request_schema(ReconstructionEnvelope))
async def current_reconstruction(request: Request, user: AuthenticatedUser):
    from services.ml_use_currentness import inspect_current_inputs

    raw, args, rebuilt = await _rebuild_request(request, user)
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            if await db.scalar(sa.select(User.session_version).where(User.id == user.id)) != user.session_version:
                raise ResearchAccessDenied("session_changed")
            await admission(db, user.id, requester_grant_id=args["expected_requester_grant_id"],
                            curator_grant_id=args["expected_curator_grant_id"])
            result = await inspect_current_inputs(db, actor_user_id=user.id, raw=raw, reconstruction=rebuilt)
    return Response(canonical(result), media_type="application/json", headers=HEADERS)


router.include_router(currentness_router)
