"""Default-off private submission, recovery, reinspection and bounded retention."""
from __future__ import annotations

import asyncio
import hashlib
import re

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_engine
from routers import ml_use_preflight as preflight
from routers.ml_use_governance import _precheck, _session_actor
from routers.research_distributions import _request_schema, _strict_json
from services import ml_use_submissions as service
from services.ml_audited_dataset import canonical, digest
from services.ml_use_access import HEADERS
from services.ml_use_currentness import inspect_current_inputs
from services.ml_use_preflight import admission, match


class SubmissionRoute(preflight.PrivateRoute):
    timeout_seconds = 100

    def get_route_handler(self):
        parent = super().get_route_handler()

        async def guarded(request):
            try:
                return await parent(request)
            except HTTPException as exc:
                if exc.status_code == 503 and getattr(request.state, "ml_commit_attempted", False):
                    raise HTTPException(503, "ML submission outcome unknown; recover the exact request",
                                        headers={**HEADERS, "X-Operation-State": "unknown"}) from None
                raise
        return guarded


router = APIRouter(prefix="/ml/use/requests", tags=["ml-use-submissions"], route_class=SubmissionRoute,
                   dependencies=[Depends(preflight.enabled)])


class Lookup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
    expected_intent_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def _headers(request, *, committing):
    def one(name):
        values = request.headers.getlist(name)
        if len(values) != 1:
            raise preflight.rejected(400)
        return values[0]

    proposal = service.intent(request_key=one("Idempotency-Key"),
        envelope_sha256=one("X-SCLib-Envelope-Sha256"), inventory_sha256=one("X-SCLib-Inventory-Sha256"),
        retention_policy=one("X-SCLib-Retention-Policy"))
    if committing:
        match(digest(proposal) == one("X-SCLib-Intent-Sha256"))
    return proposal


def response(value):
    raw = canonical(value)
    if len(raw) > 1100 * 1024:
        raise ValueError("ml_submission_response_limit")
    return Response(raw, media_type="application/json", headers=HEADERS)


async def _read(user, operation, arguments):
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await _session_actor(db, user, admin=True)
            await admission(db, user.id)
            return await operation(db, actor_user_id=user.id, **arguments)


async def _inspect(user, raw, rebuilt, *, lookup=None):
    async def inspect(db, *, actor_user_id):
        if lookup is not None:
            # Expiry/purge/account changes during the worker cannot reopen access.
            match(await service.retained_inputs(db, actor_user_id=actor_user_id, **lookup) == raw)
        return await inspect_current_inputs(db, actor_user_id=actor_user_id, raw=raw, reconstruction=rebuilt)
    return await _read(user, inspect, {})


async def _write(request, user, operation, arguments):
    async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as db:
        async with db.begin():
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await db.execute(sa.text("SELECT public.sclib_research_publication_lock_v1()"))
            await _session_actor(db, user, admin=True, lock=True)
            result = await operation(db, actor_user_id=user.id, **arguments)
            prepared = response({**result, "committed": True})
            if result.get("replayed"):
                await db.rollback()
            else:
                request.state.ml_commit_attempted = True
    return prepared


UPLOAD_SCHEMA = _request_schema(preflight.ReconstructionEnvelope)
UPLOAD_SCHEMA = {**UPLOAD_SCHEMA, "parameters": [
    {"name": name, "in": "header", "required": True, "schema": {"type": "string"}}
    for name in ("Idempotency-Key", "X-SCLib-Envelope-Sha256", "X-SCLib-Inventory-Sha256", "X-SCLib-Retention-Policy")]}


@router.post("/preview", openapi_extra=UPLOAD_SCHEMA)
async def preview(request: Request, user: preflight.AuthenticatedUser):
    await preflight._read(user)
    proposal = _headers(request, committing=False)
    raw, _, rebuilt = await preflight._rebuild_request(request, user)
    observed = await _inspect(user, raw, rebuilt)
    service.validate_observation(raw, observed, proposal, user.id)
    return response({"version": service.VERSION, "intent": proposal, "intent_sha256": digest(proposal),
                     "request_persisted": False, "committed": False, "current_inspection": observed})


@router.post("", openapi_extra={**UPLOAD_SCHEMA, "parameters": [*UPLOAD_SCHEMA["parameters"],
    {"name": "X-SCLib-Intent-Sha256", "in": "header", "required": True, "schema": {"type": "string"}}]})
async def submit(request: Request, user: preflight.AuthenticatedUser):
    await preflight._read(user)
    proposal = _headers(request, committing=True)
    raw = await preflight._reconstruction_body(request)
    match(hashlib.sha256(raw).hexdigest() == proposal["envelope_sha256"])
    lookup = {"request_key": proposal["request_key"], "expected_intent_sha256": digest(proposal)}
    try:
        # Recovery returns historical evidence, even if current sources changed.
        # It never reopens/extends a retained input or reconstructs a stale source.
        prior = await _read(user, service.outcome, lookup)
        return response({**prior, "committed": True})
    except service.SubmissionNotObserved:
        pass
    raw, _, rebuilt = await preflight._rebuild_bytes(user, raw)
    observed = await _inspect(user, raw, rebuilt)
    return await _write(request, user, service.store_submission,
        {"raw": raw, "observation": observed, "submission_intent": proposal, "expected_intent_sha256": digest(proposal)})


async def _lookup_body(request):
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json" or request.headers.get("content-encoding", "identity") != "identity":
        raise preflight.rejected(415)
    length = request.headers.get("content-length")
    if length is not None and (not re.fullmatch(r"[0-9]{1,8}", length) or int(length) > 4096):
        raise preflight.rejected(413)
    raw, count = bytearray(), 0
    async with asyncio.timeout(5):
        async for part in request.stream():
            count += 1
            if count > 4096 or len(raw) + len(part) > 4096:
                raise preflight.rejected(413)
            raw.extend(part)
    return Lookup.model_validate(_strict_json(bytes(raw))).model_dump()


@router.post("/outcome", openapi_extra=_request_schema(Lookup))
async def outcome(request: Request, user: preflight.AuthenticatedUser):
    await preflight._read(user)
    try:
        return response({**await _read(user, service.outcome, await _lookup_body(request)), "committed": True})
    except service.SubmissionNotObserved:
        raise preflight.rejected(404) from None


@router.post("/recheck", openapi_extra=_request_schema(Lookup))
async def recheck(request: Request, user: preflight.AuthenticatedUser):
    await preflight._read(user)
    lookup = await _lookup_body(request)
    try:
        raw = await _read(user, service.retained_inputs, lookup)
        _, _, rebuilt = await preflight._rebuild_bytes(user, raw)
        return response(await _inspect(user, raw, rebuilt, lookup=lookup))
    except service.SubmissionNotObserved:
        raise preflight.rejected(404) from None


@router.post("/purge", openapi_extra=_request_schema(Lookup))
async def purge(request: Request, user: preflight.AuthenticatedUser):
    await preflight._read(user)
    try:
        return await _write(request, user, service.purge_inputs, await _lookup_body(request))
    except service.SubmissionNotObserved:
        raise preflight.rejected(404) from None


@router.post("/purge-expired")
async def purge_expired(request: Request, user: preflight.AuthenticatedUser):
    await _precheck(user)
    # The bounded maintenance operation accepts no caller-selected IDs or bytes.
    async with asyncio.timeout(5):
        count = 0
        async for part in request.stream():
            count += 1
            if part or count > 16:
                raise preflight.rejected(400)
    return await _write(request, user, service.purge_expired, {})
