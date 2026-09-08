"""Private, authenticated distribution operations with explicit outer commits.

Bodies contain bytes, never paths to fetch. Account identity comes only from
the existing JWT/browser-session dependency. Service savepoints are not durable
receipts until this router has successfully committed its dedicated transaction.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import math
import re
import threading
from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import User, get_engine
from routers.auth import current_user_from_jwt
from services.research_access import ResearchAccessDenied, active_grant, require_research_operator
from services.research_distribution import DistributionRegistryUnavailable
from services.research_distribution_contract import _bounded

HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
MAX_REQUEST_BYTES = 96 * 1024 * 1024
MAX_DECODED_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 48
MAX_JSON_NODES = 500_000
REQUEST_TIMEOUT = 30
BODY_TIMEOUT = 10
REQUEST_CAPACITY = 2
_request_slots = threading.BoundedSemaphore(REQUEST_CAPACITY)


def _uuid(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError("canonical_uuid_required")
    return value


Identifier = Annotated[str, BeforeValidator(_uuid)]
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,159}$")]
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$")]


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_key: Key
    dry_run: bool = True


class Registration(Operation):
    release: dict
    bindings: dict
    public_bundle: dict
    expected_release_sha256: Sha
    expected_bindings_sha256: Sha
    expected_public_bundle_sha256: Sha
    artifact_bytes_base64: dict[Sha, str] = Field(max_length=20_000)
    capsule_artifact_bytes_base64: dict[Sha, dict[Sha, str]] = Field(default_factory=dict, max_length=8)


class Permission(Operation):
    dependency_id: Sha
    decision: Literal["allow", "revoke"]
    license_code: Literal["CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "permission-on-file"]
    basis_code: Code
    reason_code: Code
    rights_artifact_id: Identifier | None = None
    expected_rights_row_sha256: Sha | None = None
    rights_bytes_base64: str | None = None
    supersedes_id: Identifier | None = None

    @model_validator(mode="after")
    def decision_inputs(self):
        if self.decision == "allow" and any(value is None for value in (
            self.rights_artifact_id, self.expected_rights_row_sha256, self.rights_bytes_base64)):
            raise ValueError("allow_requires_exact_rights")
        if self.decision == "revoke" and self.supersedes_id is None:
            raise ValueError("revoke_requires_predecessor")
        return self


class Review(Operation):
    expected_inventory_sha256: Sha
    disclosure_approved: bool
    reason_code: Code


class Action(Operation):
    expected_inventory_sha256: Sha
    review_id: Identifier
    kind: Literal["publish", "withdraw"]
    reason_code: Code


def _bad(status, detail):
    return HTTPException(status, detail, headers=HEADERS)


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            if not _request_slots.acquire(blocking=False):
                raise HTTPException(503, "Distribution capacity unavailable; retry",
                                    headers={**HEADERS, "Retry-After": "1"})
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    return await handler(request)
            except ResearchAccessDenied:
                raise _bad(403, "Research operator access required") from None
            except (SQLAlchemyError, TimeoutError, DistributionRegistryUnavailable):
                raise _bad(503, "Distribution registry unavailable") from None
            except (ValidationError, ValueError, TypeError, OverflowError, RecursionError):
                raise _bad(400, "Distribution request rejected") from None
            except HTTPException as exc:
                # No input-derived Pydantic locations or service exception
                # strings are disclosed by this private bulk-upload boundary.
                details = {400: "Distribution request rejected", 401: "Authentication required",
                           403: "Research operator access required", 404: "Distribution unavailable",
                           413: "Distribution request exceeds limits", 415: "JSON content required",
                           422: "Distribution request rejected", 503: "Distribution registry unavailable"}
                raise _bad(exc.status_code, details.get(exc.status_code, "Distribution request rejected")) from None
            except Exception:
                # Unexpected provider/driver/parser errors must not echo source
                # bodies, local paths or credentials. Cancellation propagates.
                raise _bad(503, "Distribution registry unavailable") from None
            finally:
                # This guard spans authentication, upload, decode, dedicated
                # SQL work and response serialization. There is no wait queue.
                _request_slots.release()

        return guarded


def enabled():
    if not get_settings().ml_foundation_public_enabled:
        raise _bad(404, "Distribution unavailable")


router = APIRouter(prefix="/ml/distributions", tags=["research-distribution-operators"],
                   route_class=PrivateRoute, dependencies=[Depends(enabled)])
AuthenticatedUser = Annotated[User, Depends(current_user_from_jwt)]


async def _precheck(user, role):
    """Cheap admission before allocating the large upload; never final authority.

    The snapshot and connection close before streaming. A role/account/session
    change during upload is independently checked under the later write fence.
    """
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout = '3000ms'"))
            await active_grant(db, user.id, role=role)
            version = await db.scalar(sa.select(User.session_version).where(User.id == user.id))
            if version != user.session_version:
                raise ResearchAccessDenied("session_changed")


def _preflight(text):
    depth = nodes = 0
    quoted = escaped = primitive = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char.isspace() or char in ",:":
            primitive = False
            continue
        if char in "}]":
            depth -= 1
            primitive = False
            if depth < 0:
                raise ValueError("invalid_json")
            continue
        if char == '"':
            nodes += 1
            quoted, primitive = True, False
        elif char in "{[":
            depth += 1
            nodes += 1
            primitive = False
        elif not primitive:
            nodes += 1
            primitive = True
        if depth > MAX_JSON_DEPTH or nodes > MAX_JSON_NODES:
            raise _bad(413, "Distribution request exceeds limits")
    if quoted or depth != 0:
        raise ValueError("invalid_json")


def _strict_json(payload):
    text = payload.decode("utf-8", errors="strict")
    _preflight(text)

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def number(raw):
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("nonfinite_json")
        return value

    def constant(_raw):
        raise ValueError("nonfinite_json")

    value = json.loads(text, object_pairs_hook=pairs, parse_float=number, parse_constant=constant)
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict:
            pending.extend(item)
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
        elif type(item) is str:
            item.encode("utf-8", errors="strict")
    if type(value) is not dict:
        raise ValueError("json_object_required")
    return value


async def _body(request, model):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise _bad(415, "JSON content required")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise _bad(415, "JSON content required")
    length = request.headers.get("content-length")
    if length is not None and (re.fullmatch(r"[0-9]{1,12}", length) is None or int(length) > MAX_REQUEST_BYTES):
        raise _bad(413, "Distribution request exceeds limits")
    data = bytearray()
    async with asyncio.timeout(BODY_TIMEOUT):
        async for piece in request.stream():
            if len(data) + len(piece) > MAX_REQUEST_BYTES:
                raise _bad(413, "Distribution request exceeds limits")
            data.extend(piece)
    return model.model_validate(_strict_json(data), strict=True).model_dump()


def _decode(value, budget):
    if type(value) is not str or len(value) > 4 * ((MAX_ARTIFACT_BYTES + 2) // 3):
        raise _bad(413, "Distribution request exceeds limits")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("invalid_base64") from None
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("noncanonical_base64")
    budget[0] += len(decoded)
    if len(decoded) > MAX_ARTIFACT_BYTES or budget[0] > MAX_DECODED_BYTES:
        raise _bad(413, "Distribution request exceeds limits")
    return decoded


def _decode_inputs(body):
    budget = [0]
    if "artifact_bytes_base64" in body:
        body["artifact_bytes"] = {key: _decode(value, budget)
            for key, value in body.pop("artifact_bytes_base64").items()}
        body["capsule_artifact_bytes"] = {manifest: {key: _decode(value, budget)
            for key, value in values.items()} for manifest, values in body.pop("capsule_artifact_bytes_base64").items()}
    if "rights_bytes_base64" in body:
        encoded = body.pop("rights_bytes_base64")
        body["rights_bytes"] = None if encoded is None else _decode(encoded, budget)
    return body


async def _operate(user, role, function, arguments):
    dry_run = arguments["dry_run"]
    async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as db:
        async with db.begin():
            await db.execute(sa.text("SET LOCAL statement_timeout = '10000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            # Establish the same ordered governance fence before any role or
            # material read. Service checks remain independent of this boundary.
            await db.execute(sa.text("SELECT public.sclib_research_distribution_lock_v1()"))
            await active_grant(db, user.id, role=role)
            version = await db.scalar(sa.select(User.session_version).where(User.id == user.id))
            if version != user.session_version:
                raise ResearchAccessDenied("session_changed")
            body = await function(db, actor_user_id=user.id, **arguments)
            # Serialize before the commit so a malformed/oversized report never
            # commits a mutation for which no successful response can be built.
            payload = _bounded({"version": "research-distribution-operation/1.0.0",
                "dry_run": dry_run, "committed": not dry_run, "result": body})
            if len(payload) > MAX_DECODED_BYTES:
                raise ValueError("report_limit")
            if dry_run or body.get("replayed") is True:
                # An exact replay returns an already durable record. Even the
                # outer admission-lock epoch must remain a no-op on that path.
                await db.rollback()
        # Exiting begin() above completes the real outer commit. A connection
        # loss here is a sanitized failure, not an invented success receipt.
    return Response(payload, media_type="application/json", headers=HEADERS)


def _request_schema(model):
    # Document the real closed wire without letting FastAPI eagerly parse an
    # unbounded body before our authenticated streaming boundary runs.
    return {"requestBody": {"required": True, "content": {"application/json": {
        "schema": model.model_json_schema()}}}}


@router.post("/register", openapi_extra=_request_schema(Registration))
async def register(request: Request, user: AuthenticatedUser):
    from services.research_distribution import register_distribution
    await _precheck(user, "curator")
    arguments = _decode_inputs(await _body(request, Registration))
    return await _operate(user, "curator", register_distribution, arguments)


@router.post("/{package_id}/permissions", openapi_extra=_request_schema(Permission))
async def permission(package_id: str, request: Request, user: AuthenticatedUser):
    from services.research_distribution import decide_distribution_permission
    await _precheck(user, "reviewer")
    arguments = _decode_inputs(await _body(request, Permission))
    return await _operate(user, "reviewer", decide_distribution_permission,
                          {**arguments, "package_id": _uuid(package_id)})


@router.post("/{package_id}/reviews", openapi_extra=_request_schema(Review))
async def review(package_id: str, request: Request, user: AuthenticatedUser):
    from services.research_distribution import review_distribution
    await _precheck(user, "reviewer")
    arguments = await _body(request, Review)
    return await _operate(user, "reviewer", review_distribution, {**arguments, "package_id": _uuid(package_id)})


@router.post("/{package_id}/actions", openapi_extra=_request_schema(Action))
async def action(package_id: str, request: Request, user: AuthenticatedUser):
    from services.research_distribution import distribution_action
    await _precheck(user, "publisher")
    arguments = await _body(request, Action)
    return await _operate(user, "publisher", distribution_action, {**arguments, "package_id": _uuid(package_id)})


@router.get("/{package_id}")
async def inspect(package_id: str, user: AuthenticatedUser):
    from services.research_distribution import inspect_distribution
    identifier = _uuid(package_id)
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout = '10000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await require_research_operator(db, user.id)
            version = await db.scalar(sa.select(User.session_version).where(User.id == user.id))
            if version != user.session_version:
                raise ResearchAccessDenied("session_changed")
            payload = _bounded(await inspect_distribution(db, package_id=identifier))
            if len(payload) > MAX_DECODED_BYTES:
                raise ValueError("report_limit")
    return Response(payload, media_type="application/json", headers=HEADERS)
