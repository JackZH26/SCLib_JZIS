"""Bounded private preparation of exact scientific Discovery publications.

This is an operator API, not a public route or a new scientific approval. The
unchanged distribution transaction boundary owns durable commits and JWT/CSRF
admission. No source path, remote URL, user identity or approval flag is trusted
from the transport.
"""
from __future__ import annotations

import asyncio
import re
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import User, get_engine
from routers.research_distributions import (
    HEADERS,
    AuthenticatedUser,
    Code,
    Identifier,
    Key,
    Operation,
    PrivateRoute,
    Sha,
    _bad,
    _operate,
    _precheck,
    _request_schema,
    _strict_json,
    _uuid,
    enabled,
)
from services import discovery_operator_history as history
from services import discovery_projection_governance as service
from services import discovery_selection_preparation as preparation
from services.discovery_scientific_projection import AUTHORITY, registry_capabilities
from services.research_access import ResearchAccessDenied, require_research_operator
from services.research_distribution_contract import _bounded

MAX_BODY_BYTES = 20 * 1024 * 1024
MAX_BODY_CHUNKS = 65536
MAX_QUERY_BYTES = 1024
MAX_REPORT_BYTES = 8192
MAX_INSPECTION_BYTES = 8 * 1024 * 1024


class ProjectionRoute(PrivateRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            if len(request.scope.get("query_string", b"")) > MAX_QUERY_BYTES:
                raise _bad(413, "Distribution request exceeds limits")
            return await handler(request)
        return guarded


router = APIRouter(prefix="/ml/discovery-projections", tags=["discovery-projection-operators"],
    route_class=ProjectionRoute, dependencies=[Depends(enabled)])


class Registration(Operation):
    distribution_package_id: Identifier
    expected_distribution_record_sha256: Sha
    expected_inventory_sha256: Sha
    public_bundle: dict
    selection: dict
    expected_selection_sha256: Sha
    expected_payload_sha256: Sha | None = None

    @model_validator(mode="after")
    def preview_pin(self):
        if not self.dry_run and self.expected_payload_sha256 is None:
            raise ValueError("preview_payload_required")
        return self


class Right(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dependency_id: Sha
    row_sha256: Sha
    license_code: Literal["CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "permission-on-file"]
    basis_code: Code


class Review(Operation):
    expected_payload_sha256: Sha
    expected_selection_sha256: Sha
    rights: list[Right] = Field(max_length=20000)
    decision: Literal["approve", "reject"]
    representative_selection_approved: bool
    disclosure_approved: bool
    reason_code: Code


class Action(Operation):
    expected_payload_sha256: Sha
    expected_selection_sha256: Sha
    review_id: Identifier
    kind: Literal["publish", "withdraw"]
    reason_code: Code


class SelectionSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    distribution_package_id: Identifier
    public_bundle_json: str = Field(max_length=preparation.MAX_BUNDLE_BYTES)
    expected_public_bundle_text_sha256: Sha


class SelectionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: SelectionSource


class SelectionPreparation(SelectionContext):
    expected_context_sha256: Sha
    request_key: Key
    choices: list[dict] = Field(min_length=1, max_length=25)


def _response(value, *, maximum=MAX_REPORT_BYTES):
    payload = _bounded(value)
    if len(payload) > maximum:
        raise ValueError("discovery_report_limit")
    return Response(payload, media_type="application/json", headers=HEADERS)


def _no_query(request):
    if request.scope.get("query_string", b""):
        raise ValueError("discovery_query_fields")


async def _body(request, model, *, maximum=None):
    maximum = MAX_BODY_BYTES if maximum is None else maximum
    _no_query(request)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise _bad(415, "JSON content required")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise _bad(415, "JSON content required")
    length = request.headers.get("content-length")
    if length is not None and (re.fullmatch(r"[0-9]{1,9}", length) is None or int(length) > maximum):
        raise _bad(413, "Distribution request exceeds limits")
    data, chunks = bytearray(), 0
    async with asyncio.timeout(10):
        async for part in request.stream():
            chunks += 1
            if chunks > MAX_BODY_CHUNKS or len(data) + len(part) > maximum:
                raise _bad(413, "Distribution request exceeds limits")
            data.extend(part)
    return model.model_validate(_strict_json(data), strict=True).model_dump()


async def _read(user, function, **arguments):
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout = '10000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await require_research_operator(db, user.id)
            if await db.scalar(sa.select(User.session_version).where(User.id == user.id)) != user.session_version:
                raise ResearchAccessDenied("session_changed")
            return await function(db, actor_user_id=user.id, **arguments)


async def _execute(user, role, function, arguments):
    async def bounded(db, **values):
        result = await function(db, **values)
        _response({"version": "research-distribution-operation/1.0.0", "dry_run": values["dry_run"],
            "committed": not values["dry_run"], "result": result})
        return result

    try:
        return await _operate(user, role, bounded, arguments)
    except service.DiscoveryGovernanceNotFound:
        raise _bad(404, "Distribution unavailable") from None
    except service.DiscoveryGovernanceConflict:
        raise _bad(409, "Distribution request rejected") from None


@router.get("/capabilities")
async def capabilities(request: Request, user: AuthenticatedUser):
    _no_query(request)

    async def admitted(db, *, actor_user_id):
        return {"version": service.VERSION, "scope": service.SCOPE,
            "registry": registry_capabilities(), "population_scope": "not_queried",
            "max_materials": 25, "max_assessments": 200, "max_properties": 100, **AUTHORITY}

    return _response(await _read(user, admitted))


@router.get("/outcome")
async def outcome(request: Request, user: AuthenticatedUser):
    pairs = list(request.query_params.multi_items())
    if len(pairs) != 3 or {key for key, _ in pairs} != {"operation", "request_key", "expected_request_sha256"}:
        raise ValueError("discovery_query_fields")
    try:
        result = await _read(user, service.inspect_operation, **dict(pairs))
        return _response({"version": "research-distribution-operation/1.0.0", "dry_run": False,
            "committed": True, "result": result})
    except service.DiscoveryGovernanceNotFound:
        raise _bad(404, "Distribution unavailable") from None
    except service.DiscoveryGovernanceConflict:
        raise _bad(409, "Distribution request rejected") from None


@router.get("/selection/access")
async def selection_access(request: Request, user: AuthenticatedUser):
    _no_query(request)
    return _response(await _read(user, preparation.access))


@router.get("/operator/access")
async def operator_access(request: Request, user: AuthenticatedUser):
    _no_query(request)
    return _response(await _read(user, history.operator_access))


@router.get("/{package_id}/governance")
async def governance_header(package_id: str, request: Request, user: AuthenticatedUser):
    _no_query(request)
    try:
        return _response(await _read(user, history.inspect_governance, package_id=_uuid(package_id)), maximum=16384)
    except service.DiscoveryGovernanceNotFound:
        raise _bad(404, "Distribution unavailable") from None


@router.get("/{package_id}/reviews")
async def review_history(package_id: str, request: Request, user: AuthenticatedUser):
    pairs = list(request.query_params.multi_items())
    if len({key for key, _ in pairs}) != len(pairs) or {key for key, _ in pairs} - {"after", "expected_history_sha256"}:
        raise ValueError("discovery_history_query_fields")
    try:
        return _response(await _read(user, history.review_history, package_id=_uuid(package_id), **dict(pairs)), maximum=131072)
    except service.DiscoveryGovernanceNotFound:
        raise _bad(404, "Distribution unavailable") from None
    except service.DiscoveryGovernanceConflict:
        raise _bad(409, "Distribution request rejected") from None


@router.post("/selection/context", openapi_extra=_request_schema(SelectionContext))
async def selection_context(request: Request, user: AuthenticatedUser):
    await _precheck(user, "curator")
    arguments = await _body(request, SelectionContext, maximum=40 * 1024 * 1024)
    return _response(await _read(user, preparation.selection_context, **arguments),
        maximum=2 * preparation.MAX_CONTEXT_BYTES + 1024)


@router.post("/selection/prepare", openapi_extra=_request_schema(SelectionPreparation))
async def selection_prepare(request: Request, user: AuthenticatedUser):
    await _precheck(user, "curator")
    arguments = await _body(request, SelectionPreparation, maximum=40 * 1024 * 1024)
    try:
        return _response(await _read(user, preparation.prepare_selection, **arguments),
            maximum=preparation.MAX_PREPARED_BYTES)
    except service.DiscoveryGovernanceConflict:
        raise _bad(409, "Distribution request rejected") from None


@router.post("/register", openapi_extra=_request_schema(Registration))
async def register(request: Request, user: AuthenticatedUser):
    await _precheck(user, "curator")
    return await _execute(user, "curator", service.register_projection, await _body(request, Registration))


@router.post("/{package_id}/reviews", openapi_extra=_request_schema(Review))
async def review(package_id: str, request: Request, user: AuthenticatedUser):
    await _precheck(user, "reviewer")
    arguments = await _body(request, Review)
    return await _execute(user, "reviewer", service.review_projection, {**arguments, "package_id": _uuid(package_id)})


@router.post("/{package_id}/actions", openapi_extra=_request_schema(Action))
async def action(package_id: str, request: Request, user: AuthenticatedUser):
    await _precheck(user, "publisher")
    arguments = await _body(request, Action)
    return await _execute(user, "publisher", service.projection_action, {**arguments, "package_id": _uuid(package_id)})


@router.get("/{package_id}")
async def inspect(package_id: str, request: Request, user: AuthenticatedUser):
    _no_query(request)
    try:
        return _response(await _read(user, service.inspect_projection, package_id=_uuid(package_id)),
            maximum=MAX_INSPECTION_BYTES)
    except service.DiscoveryGovernanceNotFound:
        raise _bad(404, "Distribution unavailable") from None
    except service.DiscoveryGovernanceConflict:
        raise _bad(409, "Distribution request rejected") from None
