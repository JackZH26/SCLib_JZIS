"""Default-off exact run contracts and independent conditional review."""
from __future__ import annotations

from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_engine
from models.ml_run_evidence_v1 import MAX_BYTES as EVIDENCE_BYTES
from models.ml_run_evidence_v1 import VERSION as EVIDENCE_VERSION
from models.ml_use_runs_v1 import VERSION
from routers import ml_use_preflight as preflight
from routers.ml_use_governance import Identifier, Sha, _precheck, _session_actor
from routers.ml_use_rights import body
from routers.ml_use_submissions import Lookup, SubmissionRoute, response
from routers.research_distributions import _request_schema
from services import ml_run_evidence as evidence
from services import ml_use_runs as service
from services.ml_use_currentness import inspect_current_inputs
from services.ml_use_preflight import match

router = APIRouter(prefix="/ml/use/runs", tags=["ml-use-runs"], route_class=SubmissionRoute,
                   dependencies=[Depends(preflight.enabled)])


class SubmissionRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    submission_id: Identifier
    submission_sha256: Sha
    inventory_sha256: Sha


class PlanRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan_id: Identifier
    plan_sha256: Sha


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision_id: Identifier
    decision_sha256: Sha


class Plan(SubmissionRef):
    requester_grant_id: Identifier
    curator_grant_id: Identifier
    request_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
    prepared_sha256: Sha
    task_sha256: Sha
    config_sha256: Sha
    package_sha256: Sha
    implementation_sha256: Sha
    runtime_sha256: Sha
    cpu_seconds: int = Field(ge=1, le=1800)
    wall_seconds: int = Field(ge=1, le=1800)
    memory_mib: int = Field(ge=128, le=4096)
    expected_intent_sha256: Sha | None = None
    dry_run: bool = True


class Decision(PlanRef):
    approver_grant_id: Identifier
    curator_grant_id: Identifier
    request_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
    decision: Literal["approve", "deny", "revoke"]
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,159}$")
    evidence_sha256: Sha | None
    evidence_text: str | None = Field(default=None, max_length=EVIDENCE_BYTES)
    expires_epoch: int | None = Field(ge=1, lt=2**63)
    supersedes_id: Identifier | None
    supersedes_sha256: Sha | None
    expected_intent_sha256: Sha | None = None
    dry_run: bool = True


NOT_OBSERVED = (service.RunNotObserved, service.rights.RightsNotObserved, service.submissions.SubmissionNotObserved)


async def read(user, function=None, args=None, *, approver=False):
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await _session_actor(db, user, admin=True)
            actor = await (service.approver_admission(db, user.id) if approver else preflight.admission(db, user.id))
            try:
                return actor if function is None else await function(db, actor_user_id=user.id, **(args or {}))
            except NOT_OBSERVED:
                raise preflight.rejected(404) from None


async def write(request, user, function, args, *, version=VERSION):
    async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as db:
        async with db.begin():
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await db.execute(sa.text("SELECT public.sclib_research_publication_lock_v1()"))
            await _session_actor(db, user, admin=True, lock=True)
            try:
                result = await function(db, actor_user_id=user.id, **args)
            except NOT_OBSERVED:
                raise preflight.rejected(404) from None
            prepared = response({"version": version, "committed": not args["dry_run"], "result": result})
            if args["dry_run"] or result["replayed"]:
                await db.rollback()
            else:
                request.state.ml_commit_attempted = True
    return prepared


@router.get("/requester-access")
async def requester_access(user: preflight.AuthenticatedUser):
    return response({"version": VERSION, **await read(user), "can_request_plan": True, **service.boundary()})


@router.get("/approver-access")
async def approver_access(user: preflight.AuthenticatedUser):
    return response({"version": VERSION, **await read(user, approver=True), "can_review_plan": True, **service.boundary()})


@router.post("/context", openapi_extra=_request_schema(SubmissionRef))
async def context(request: Request, user: preflight.AuthenticatedUser):
    await read(user)
    return response(await read(user, service.context, await body(request, SubmissionRef)))


@router.post("/plans", openapi_extra=_request_schema(Plan))
async def plan(request: Request, user: preflight.AuthenticatedUser):
    await read(user)
    return await write(request, user, service.propose, await body(request, Plan))


@router.post("/inspect", openapi_extra=_request_schema(PlanRef))
async def inspect(request: Request, user: preflight.AuthenticatedUser):
    await read(user, approver=True)
    return response(await read(user, service.inspect, await body(request, PlanRef), approver=True))


@router.post("/decisions", openapi_extra=_request_schema(Decision))
async def decision(request: Request, user: preflight.AuthenticatedUser):
    await read(user, approver=True)
    return await write(request, user, service.decide, await body(request, Decision, max_bytes=16384))


@router.post("/evidence/read", openapi_extra=_request_schema(EvidenceRef))
async def read_evidence(request: Request, user: preflight.AuthenticatedUser):
    await read(user, approver=True)
    return response(await read(user, evidence.read, await body(request, EvidenceRef), approver=True))


@router.post("/evidence/purge", openapi_extra=_request_schema(EvidenceRef))
async def purge_evidence(request: Request, user: preflight.AuthenticatedUser):
    # Withdrawal must remain possible after the original review roles are revoked.
    await _precheck(user)
    return await write(request, user, evidence.purge, {**await body(request, EvidenceRef), "dry_run": False},
                       version=EVIDENCE_VERSION)


@router.post("/evidence/purge-expired")
async def purge_expired_evidence(request: Request, user: preflight.AuthenticatedUser):
    await _precheck(user)
    # Reuse the bounded parser but permit only an explicit empty object.
    class Empty(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
    await body(request, Empty)
    return await write(request, user, evidence.purge_expired, {"dry_run": False}, version=EVIDENCE_VERSION)


@router.post("/plans/outcome", openapi_extra=_request_schema(Lookup))
async def plan_outcome(request: Request, user: preflight.AuthenticatedUser):
    await read(user)
    found = await read(user, service.outcome, {**await body(request, Lookup), "kind": "plan"})
    return response({"version": VERSION, "committed": True, "result": found})


@router.post("/decisions/outcome", openapi_extra=_request_schema(Lookup))
async def decision_outcome(request: Request, user: preflight.AuthenticatedUser):
    await read(user, approver=True)
    found = await read(user, service.outcome, {**await body(request, Lookup), "kind": "decision"}, approver=True)
    return response({"version": VERSION, "committed": True, "result": found})


@router.post("/check", openapi_extra=_request_schema(PlanRef))
async def check(request: Request, user: preflight.AuthenticatedUser):
    await read(user)
    query = await body(request, PlanRef)
    raw = await read(user, service.retained_inputs, query)
    _, _, rebuilt = await preflight._rebuild_bytes(user, raw)

    async def inspect_readiness(db, *, actor_user_id):
        # Recheck the owner's same retained bytes after CPU work, then join the
        # full audit, rights and exact approval heads in the same fresh snapshot.
        match(await service.retained_inputs(db, actor_user_id=actor_user_id, **query) == raw)
        observed = await inspect_current_inputs(db, actor_user_id=actor_user_id, raw=raw, reconstruction=rebuilt)
        return await service.readiness(db, actor_user_id=actor_user_id, current_inspection=observed, **query)

    return response(await read(user, inspect_readiness))
