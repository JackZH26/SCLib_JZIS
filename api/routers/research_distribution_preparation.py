"""Bounded authenticated descriptor preparation and exact historical recovery."""
from __future__ import annotations

import asyncio
import re

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import User, get_engine
from routers.research_distributions import (
    HEADERS,
    AuthenticatedUser,
    Operation,
    PrivateRoute,
    Sha,
    _bad,
    _decode,
    _operate,
    _precheck,
    _request_schema,
    _strict_json,
    enabled,
)
from services.research_access import ResearchAccessDenied
from services.research_distribution_contract import _bounded
from services.research_distribution_preparation import (
    PreparationConflict,
    PreparationNotFound,
    preparation_capabilities,
    preparation_outcome,
    prepare_distribution,
)

MAX_BODY_BYTES = 48 * 1024 * 1024
MAX_DECODED_BYTES = 32 * 1024 * 1024
MAX_BODY_CHUNKS = 65536
MAX_QUERY_BYTES = 1024
MAX_RESPONSE_BYTES = 8192


class PreparationRoute(PrivateRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            # FastAPI resolves QueryParams even without declared query arguments.
            # Bound its raw input before the framework or dependencies parse it.
            if len(request.scope.get("query_string", b"")) > MAX_QUERY_BYTES:
                raise _bad(413, "Distribution request exceeds limits")
            return await handler(request)
        return guarded


router = APIRouter(prefix="/ml/distributions/preparation", tags=["research-distribution-preparation"],
                   route_class=PreparationRoute, dependencies=[Depends(enabled)])


class Preparation(Operation):
    release: dict
    selections: dict
    public_bundle: dict
    expected_release_sha256: Sha
    expected_selections_sha256: Sha
    expected_public_bundle_sha256: Sha
    artifact_bytes_base64: dict[Sha, str] = Field(max_length=20000)
    capsule_artifact_bytes_base64: dict[Sha, dict[Sha, str]] = Field(default_factory=dict, max_length=8)
    expected_intent_sha256: Sha | None = None

    @model_validator(mode="after")
    def preview_pin(self):
        if not self.dry_run and self.expected_intent_sha256 is None:
            raise ValueError("preview_intent_required")
        return self


def _response(value):
    data = _bounded(value)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("preparation_response_limit")
    return Response(data, media_type="application/json", headers=HEADERS)


async def _body(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise _bad(415, "JSON content required")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise _bad(415, "JSON content required")
    length = request.headers.get("content-length")
    if length is not None and (re.fullmatch(r"[0-9]{1,9}", length) is None or int(length) > MAX_BODY_BYTES):
        raise _bad(413, "Distribution request exceeds limits")
    data, chunks = bytearray(), 0
    async with asyncio.timeout(10):
        async for part in request.stream():
            chunks += 1
            if chunks > MAX_BODY_CHUNKS or len(data) + len(part) > MAX_BODY_BYTES:
                raise _bad(413, "Distribution request exceeds limits")
            data.extend(part)
    body = Preparation.model_validate(_strict_json(data), strict=True).model_dump()
    budget = [0]

    def decode(values):
        if type(values) is not dict or len(values) > 20000:
            raise ValueError("preparation_inventory_limit")
        result = {}
        for key, value in values.items():
            result[key] = _decode(value, budget)
            if budget[0] > MAX_DECODED_BYTES:
                raise _bad(413, "Distribution request exceeds limits")
        return result

    body["artifact_bytes"] = decode(body.pop("artifact_bytes_base64"))
    body["capsule_artifact_bytes"] = {key: decode(values) for key, values in body.pop("capsule_artifact_bytes_base64").items()}
    return body


async def _read(user, function, **arguments):
    await _precheck(user, "curator")
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout = '3000ms'"))
            if await db.scalar(sa.select(User.session_version).where(User.id == user.id)) != user.session_version:
                raise ResearchAccessDenied("session_changed")
            return await function(db, actor_user_id=user.id, **arguments)


@router.get("/capabilities")
async def capabilities(user: AuthenticatedUser):
    return _response(await _read(user, preparation_capabilities))


async def _bounded_prepare(db, **arguments):
    result = await prepare_distribution(db, **arguments)
    _response({"version": "research-distribution-operation/1.0.0", "dry_run": arguments["dry_run"],
        "committed": not arguments["dry_run"], "result": result})
    return result


@router.post("", openapi_extra=_request_schema(Preparation))
async def prepare(request: Request, user: AuthenticatedUser):
    await _precheck(user, "curator")
    arguments = await _body(request)
    try:
        return await _operate(user, "curator", _bounded_prepare, arguments)
    except PreparationConflict:
        raise _bad(409, "Distribution preparation changed") from None


@router.get("/outcome")
async def outcome(request: Request, user: AuthenticatedUser):
    await _precheck(user, "curator")
    pairs = list(request.query_params.multi_items())
    if len(pairs) != 2 or {key for key, _ in pairs} != {"request_key", "expected_intent_sha256"}:
        raise ValueError("preparation_query_fields")
    try:
        result = await _read(user, preparation_outcome, **dict(pairs))
        return _response({"version": "research-distribution-operation/1.0.0", "dry_run": False,
            "committed": True, "result": result})
    except PreparationNotFound:
        raise _bad(404, "Distribution preparation not observed") from None
    except PreparationConflict:
        raise _bad(409, "Distribution preparation changed") from None
