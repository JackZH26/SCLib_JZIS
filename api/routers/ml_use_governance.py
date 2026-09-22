"""Opt-in authenticated ML role administration, with no data or training grant."""
from __future__ import annotations

import asyncio
import re
import threading
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import User, get_engine
from models.ml_use_roles_v1 import VERSION
from routers.auth import current_user_from_jwt
from routers.research_distributions import _request_schema, _strict_json, _uuid
from services.ml_use_access import (
    HEADERS,
    MlUseConflict,
    MlUseOutcomeNotObserved,
    decide_ml_role,
    inspect_ml_access,
    ml_role_outcome,
)
from services.research_access import ResearchAccessDenied, active_user, require_research_admin
from services.research_release_manifest import canonical

MAX_BODY_BYTES = 8192
REQUEST_TIMEOUT = 15
_slots = threading.BoundedSemaphore(2)
AuthenticatedUser = Annotated[User, Depends(current_user_from_jwt)]
Identifier = Annotated[str, BeforeValidator(_uuid)]
Sha = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class RoleDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    user_id: Identifier
    role: Literal["requester", "rights_reviewer", "run_approver"]
    action: Literal["grant", "revoke"]
    request_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,159}$")
    expected_head_id: Identifier | None
    expected_head_sha256: Sha | None
    expected_intent_sha256: Sha | None = None
    dry_run: bool = True

    @model_validator(mode="after")
    def exact_binding(self):
        if (self.expected_head_id is None) != (self.expected_head_sha256 is None):
            raise ValueError("exact_head_required")
        if self.action == "revoke" and self.expected_head_id is None:
            raise ValueError("revoke_predecessor_required")
        if not self.dry_run and self.expected_intent_sha256 is None:
            raise ValueError("preview_pin_required")
        return self


def _bad(status, *, uncertain=False):
    messages = {400: "ML role request rejected", 401: "Authentication required",
                403: "ML role administration access denied", 404: "ML role record unavailable",
                409: "ML role intent or predecessor changed", 413: "ML role request exceeds limits",
                415: "JSON content required", 503: "ML role registry unavailable"}
    return HTTPException(status, messages[status], headers={**HEADERS,
                         **({"X-Operation-State": "unknown"} if uncertain else {})})


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            if not _slots.acquire(blocking=False):
                raise _bad(503)
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    return await handler(request)
            except ResearchAccessDenied:
                raise _bad(403) from None
            except MlUseConflict:
                raise _bad(409) from None
            except MlUseOutcomeNotObserved:
                raise _bad(404) from None
            except HTTPException as exc:
                status = 400 if exc.status_code == 422 else exc.status_code
                raise _bad(status if status in {400, 401, 403, 404, 409, 413, 415, 503} else 503,
                           uncertain=exc.headers is not None and exc.headers.get("X-Operation-State") == "unknown") from None
            except (RequestValidationError, ValueError, TypeError, OverflowError, RecursionError):
                raise _bad(400) from None
            except (SQLAlchemyError, TimeoutError):
                raise _bad(503, uncertain=request.method == "POST") from None
            except Exception:
                raise _bad(503, uncertain=request.method == "POST") from None
            finally:
                _slots.release()

        return guarded


def enabled():
    if not get_settings().ml_use_governance_enabled:
        raise _bad(404)


router = APIRouter(prefix="/ml/use", tags=["ml-use-governance"], route_class=PrivateRoute,
                   dependencies=[Depends(enabled)])


async def _session_actor(db, user, *, admin=False, lock=False):
    query = sa.select(User.session_version).where(User.id == user.id)
    if lock:
        query = query.with_for_update(read=True)
    if await db.scalar(query) != user.session_version:
        raise ResearchAccessDenied("session_changed")
    await (require_research_admin(db, user.id) if admin else active_user(db, user.id))


async def _read(user, function, arguments, *, admin=False):
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout='3000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await _session_actor(db, user, admin=admin)
            result = await function(db, actor_user_id=user.id, **arguments)
            payload = canonical(result)
            if len(payload) > 32768:
                raise ValueError("ml_role_report_budget")
    return Response(payload, media_type="application/json", headers=HEADERS)


async def _precheck(user):
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout='3000ms'"))
            await _session_actor(db, user, admin=True)


async def _body(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise _bad(415)
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise _bad(415)
    length = request.headers.get("content-length")
    if length is not None and (re.fullmatch(r"[0-9]{1,8}", length) is None or int(length) > MAX_BODY_BYTES):
        raise _bad(413)
    raw, chunks = bytearray(), 0
    async with asyncio.timeout(5):
        async for part in request.stream():
            chunks += 1
            if chunks > 4096 or len(raw) + len(part) > MAX_BODY_BYTES:
                raise _bad(413)
            raw.extend(part)
    return RoleDecision.model_validate(_strict_json(bytes(raw))).model_dump()


async def _operate(user, arguments):
    async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as db:
        async with db.begin():
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await db.execute(sa.text("SELECT public.sclib_research_publication_lock_v1()"))
            await _session_actor(db, user, admin=True, lock=True)
            result = await decide_ml_role(db, actor_user_id=user.id, **arguments)
            payload = canonical({"version": VERSION, "dry_run": arguments["dry_run"],
                                 "committed": not arguments["dry_run"], "result": result})
            if len(payload) > 32768:
                raise ValueError("ml_role_report_budget")
            if arguments["dry_run"] or result["replayed"]:
                await db.rollback()
    return Response(payload, media_type="application/json", headers=HEADERS)


@router.get("/access")
async def access(user: AuthenticatedUser):
    return await _read(user, inspect_ml_access, {})


@router.get("/roles/users/{user_id}")
async def subject(user_id: str, user: AuthenticatedUser):
    # Administrator admission precedes target lookup, including malformed IDs.
    await _precheck(user)
    return await _read(user, inspect_ml_access, {"user_id": _uuid(user_id)}, admin=True)


@router.post("/roles", openapi_extra=_request_schema(RoleDecision))
async def decision(request: Request, user: AuthenticatedUser):
    await _precheck(user)
    arguments = await _body(request)
    return await _operate(user, arguments)


@router.get("/roles/outcome")
async def outcome(request_key: str, expected_intent_sha256: str, user: AuthenticatedUser):
    async def recover(db, **arguments):
        result = await ml_role_outcome(db, **arguments)
        return {"version": VERSION, "dry_run": False, "committed": True, "result": result}

    return await _read(user, recover, {"request_key": request_key,
                                     "expected_intent_sha256": expected_intent_sha256}, admin=True)
