"""Default-off independent ML rights review and fresh owner-scoped coverage."""
from __future__ import annotations

import asyncio
import re
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_engine
from models.ml_use_rights_v1 import VERSION
from routers import ml_use_preflight as preflight
from routers.ml_use_governance import Identifier, Sha, _session_actor
from routers.ml_use_submissions import Lookup, SubmissionRoute, response
from routers.research_distributions import _request_schema, _strict_json
from services import ml_use_rights as service
from services import ml_use_submissions as submissions
from services.ml_use_currentness import inspect_current_inputs
from services.ml_use_preflight import match

router = APIRouter(prefix="/ml/use/rights", tags=["ml-use-rights"], route_class=SubmissionRoute,
                   dependencies=[Depends(preflight.enabled)])


class Inspect(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    submission_id: Identifier
    submission_sha256: Sha
    inventory_sha256: Sha
    after: Sha | None = None


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    submission_id: Identifier
    submission_sha256: Sha
    inventory_sha256: Sha
    resource_id: Sha
    purpose: Literal["private_baseline_evaluation"]
    reviewer_grant_id: Identifier
    curator_grant_id: Identifier
    request_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
    decision: Literal["allow", "deny", "revoke"]
    basis_code: Literal["documented_license", "documented_permission", "documented_institutional_policy", "rights_unresolved", "withdrawn"]
    evidence_sha256: Sha | None
    expires_epoch: int | None = Field(ge=1, lt=2**63)
    supersedes_id: Identifier | None
    supersedes_sha256: Sha | None
    expected_intent_sha256: Sha | None = None
    dry_run: bool = True


async def body(request, schema):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json" or request.headers.get("content-encoding", "identity") != "identity":
        raise preflight.rejected(415)
    length = request.headers.get("content-length")
    if length is not None and (not re.fullmatch(r"[0-9]{1,8}", length) or int(length) > 8192):
        raise preflight.rejected(413)
    raw, count = bytearray(), 0
    async with asyncio.timeout(5):
        async for part in request.stream():
            count += 1
            if count > 4096 or len(raw) + len(part) > 8192:
                raise preflight.rejected(413)
            raw.extend(part)
    return schema.model_validate(_strict_json(bytes(raw))).model_dump()


async def read(user, function=None, args=None, *, reviewer=True):
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await _session_actor(db, user, admin=True)
            actor = await (service.reviewer_admission(db, user.id) if reviewer else preflight.admission(db, user.id))
            try:
                return actor if function is None else await function(db, actor_user_id=user.id, **(args or {}))
            except (service.RightsNotObserved, submissions.SubmissionNotObserved):
                raise preflight.rejected(404) from None


@router.get("/access")
async def access(user: preflight.AuthenticatedUser):
    return response({"version": VERSION, **await read(user), "can_review_rights": True, **service.boundary()})


@router.post("/inspect", openapi_extra=_request_schema(Inspect))
async def inspect(request: Request, user: preflight.AuthenticatedUser):
    await read(user)
    return response(await read(user, service.inspect, await body(request, Inspect)))


@router.post("/decisions", openapi_extra=_request_schema(Decision))
async def decision(request: Request, user: preflight.AuthenticatedUser):
    await read(user)
    args = await body(request, Decision)
    async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as db:
        async with db.begin():
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await db.execute(sa.text("SELECT public.sclib_research_publication_lock_v1()"))
            await _session_actor(db, user, admin=True, lock=True)
            try:
                result = await service.decide(db, actor_user_id=user.id, **args)
            except service.RightsNotObserved:
                raise preflight.rejected(404) from None
            prepared = response({"version": VERSION, "committed": not args["dry_run"], "result": result})
            if args["dry_run"] or result["replayed"]:
                await db.rollback()
            else:
                request.state.ml_commit_attempted = True
    return prepared


@router.post("/outcome", openapi_extra=_request_schema(Lookup))
async def outcome(request: Request, user: preflight.AuthenticatedUser):
    await read(user)
    found = await read(user, service.outcome, await body(request, Lookup))
    return response({"version": VERSION, "committed": True, "result": found})


@router.post("/check", openapi_extra=_request_schema(Lookup))
async def check(request: Request, user: preflight.AuthenticatedUser):
    await read(user, reviewer=False)
    lookup = await body(request, Lookup)
    raw = await read(user, submissions.retained_inputs, lookup, reviewer=False)
    _, _, rebuilt = await preflight._rebuild_bytes(user, raw)

    async def inspect_and_cover(db, *, actor_user_id):
        # No worker outside the authenticated owner's retention boundary. Repeat
        # retention checks after CPU work in the very same source/rights snapshot.
        retained = await submissions.retained_inputs(db, actor_user_id=actor_user_id, **lookup)
        match(retained == raw)
        parent = await submissions._owned(db, actor_user_id, **lookup)
        observed = await inspect_current_inputs(db, actor_user_id=actor_user_id, raw=raw, reconstruction=rebuilt)
        return await service.coverage(db, actor_user_id=actor_user_id, parent=parent, current_inspection=observed)

    return response(await read(user, inspect_and_cover, reviewer=False))
