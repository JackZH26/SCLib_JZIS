"""Private read-only ML-use intake. No submission, rights grant or execution."""
from __future__ import annotations

import asyncio
import re
import threading
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import User, get_engine
from models.ml_use_request import MAX_BYTES, identifier, sha, validate_request
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
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            if not _slots.acquire(blocking=False):
                raise rejected(503)
            try:
                async with asyncio.timeout(20):
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
