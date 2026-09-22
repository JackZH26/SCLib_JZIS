"""Small authenticated rights-preparation wire; no arbitrary artifact upload."""
from __future__ import annotations

import asyncio
import re
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, Response
from pydantic import model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import User, get_engine
from routers.research_distributions import (
    HEADERS,
    AuthenticatedUser,
    Code,
    Identifier,
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
from services.research_access import ResearchAccessDenied, active_grant
from services.research_distribution_contract import _bounded
from services.research_distribution_rights import (
    RightsPreparationConflict,
    RightsPreparationNotFound,
    inspect_rights_dependency,
    list_rights_dependencies,
    prepare_distribution_rights,
    rights_preparation_capabilities,
    rights_preparation_outcome,
)

MAX_BODY_BYTES = 8192
MAX_BODY_CHUNKS = 4096
router = APIRouter(prefix="/ml/distributions", tags=["research-distribution-rights"],
                   route_class=PrivateRoute, dependencies=[Depends(enabled)])


class Preparation(Operation):
    decision: Literal["allow", "revoke"]
    license_code: Literal["CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "permission-on-file"]
    basis_code: Code
    reason_code: Code
    expected_package_sha256: Sha
    expected_inventory_sha256: Sha
    expected_dependency_row_sha256: Sha
    expected_head_id: Identifier | None
    expected_head_sha256: Sha | None
    expected_intent_sha256: Sha | None = None

    @model_validator(mode="after")
    def exact_intent(self):
        if (self.expected_head_id is None) != (self.expected_head_sha256 is None):
            raise ValueError("exact_head_required")
        if self.decision == "revoke" and self.expected_head_id is None:
            raise ValueError("revoke_requires_predecessor")
        if not self.dry_run and self.expected_intent_sha256 is None:
            raise ValueError("preview_pin_required")
        return self


async def _small_body(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise _bad(415, "JSON content required")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise _bad(415, "JSON content required")
    length = request.headers.get("content-length")
    if length is not None and (re.fullmatch(r"[0-9]{1,8}", length) is None or int(length) > MAX_BODY_BYTES):
        raise _bad(413, "Distribution request exceeds limits")
    data = bytearray()
    chunks = 0
    async with asyncio.timeout(10):
        async for part in request.stream():
            chunks += 1
            if chunks > MAX_BODY_CHUNKS or len(data) + len(part) > MAX_BODY_BYTES:
                raise _bad(413, "Distribution request exceeds limits")
            data.extend(part)
    return Preparation.model_validate(_strict_json(data), strict=True).model_dump()


async def _read(user, function, **arguments):
    await _precheck(user, "reviewer")
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout = '3000ms'"))
            if await db.scalar(sa.select(User.session_version).where(User.id == user.id)) != user.session_version:
                raise ResearchAccessDenied("session_changed")
            result = await function(db, actor_user_id=user.id, **arguments)
            return Response(_bounded(result), media_type="application/json", headers=HEADERS)


@router.get("/operator/capabilities")
async def capabilities(user: AuthenticatedUser):
    return await _read(user, rights_preparation_capabilities)


@router.get("/{package_id}/rights")
async def dependencies(package_id: str, user: AuthenticatedUser, after: str | None = None,
                       expected_inventory_sha256: str | None = None):
    try:
        return await _read(user, list_rights_dependencies, package_id=_uuid(package_id),
                           after=after, expected_inventory_sha256=expected_inventory_sha256)
    except RightsPreparationConflict:
        raise _bad(409, "Distribution inventory changed") from None


@router.get("/{package_id}/rights/{dependency_id}")
async def inspect(package_id: str, dependency_id: str, user: AuthenticatedUser):
    await _precheck(user, "reviewer")
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout = '3000ms'"))
            await active_grant(db, user.id, role="reviewer")
            if await db.scalar(sa.select(User.session_version).where(User.id == user.id)) != user.session_version:
                raise ResearchAccessDenied("session_changed")
            result = await inspect_rights_dependency(db, actor_user_id=user.id,
                package_id=_uuid(package_id), dependency_id=dependency_id)
            return Response(_bounded(result), media_type="application/json", headers=HEADERS)


@router.post("/{package_id}/rights/{dependency_id}", openapi_extra=_request_schema(Preparation))
async def prepare(package_id: str, dependency_id: str, request: Request, user: AuthenticatedUser):
    await _precheck(user, "reviewer")
    arguments = await _small_body(request)
    try:
        return await _operate(user, "reviewer", prepare_distribution_rights,
                              {**arguments, "package_id": _uuid(package_id), "dependency_id": dependency_id})
    except RightsPreparationConflict:
        raise _bad(409, "Distribution intent changed; inspect again") from None


@router.get("/{package_id}/rights/{dependency_id}/outcome")
async def outcome(package_id: str, dependency_id: str, request_key: str,
                  expected_intent_sha256: str, user: AuthenticatedUser):
    await _precheck(user, "reviewer")
    try:
        async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
            async with db.begin():
                await db.execute(sa.text("SET TRANSACTION READ ONLY"))
                await db.execute(sa.text("SET LOCAL statement_timeout = '3000ms'"))
                if await db.scalar(sa.select(User.session_version).where(User.id == user.id)) != user.session_version:
                    raise ResearchAccessDenied("session_changed")
                result = await rights_preparation_outcome(db, actor_user_id=user.id, package_id=_uuid(package_id),
                    dependency_id=dependency_id, request_key=request_key, expected_intent_sha256=expected_intent_sha256)
                return Response(_bounded({"version": "research-distribution-operation/1.0.0", "dry_run": False,
                    "committed": True, "result": result}), media_type="application/json", headers=HEADERS)
    except RightsPreparationNotFound:
        raise _bad(404, "Distribution outcome not observed") from None
    except RightsPreparationConflict:
        raise _bad(409, "Distribution intent changed") from None
