"""Owner-private evidence returns, independently disabled by default."""
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, Response

from config import get_settings
from routers.discovery_designs import read
from routers.source_properties import HEADERS, PrivateRoute, _body, _failure, _session
from services import discovery_feedback as service
from services.research_release_manifest import canonical

# Eight bounded returns repeat canonical proofs and escaped researcher notes.
# This interface owns its transport ceiling; other private readers retain theirs.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def _response(value):
    payload = canonical(value)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise _failure(503)
    return Response(payload, media_type="application/json", headers=HEADERS)


def enabled():
    if not get_settings().discovery_feedback_enabled:
        raise _failure(404)


router = APIRouter(prefix="/research/discovery-feedback", tags=["discovery-feedback"],
                   route_class=PrivateRoute, dependencies=[Depends(enabled)])


@router.get("/capabilities")
async def capabilities(request: Request):
    async with read(request) as (db, actor):
        value = await service.capabilities(db, actor_user_id=actor)
    return _response(value)


@router.get("/context")
async def context(request: Request, design_id: str, revision_id: str, record_sha256: str,
                  material_id: str, record_index: int):
    async with read(request) as (db, actor):
        value = await service.context(db, actor_user_id=actor, design_id=design_id, revision_id=revision_id,
                                      record_sha256=record_sha256, material_id=material_id, record_index=record_index)
    return _response(value)


@router.post("/operations/preview")
async def preview(request: Request):
    async with _session(request, write=True, role="curator") as (db, actor):
        await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
        body = await _body(request, keys={"request"})
        value = await service.operate(db, actor_user_id=actor, request=body["request"], dry_run=True)
    return _response(value)


@router.post("/operations/commit")
async def commit(request: Request):
    async with _session(request, write=True, role="curator") as (db, actor):
        await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
        body = await _body(request, keys={"request", "expected_preview_sha256"})
        value = await service.operate(db, actor_user_id=actor, request=body["request"], dry_run=False,
                                      expected_preview_sha256=body["expected_preview_sha256"])
    return _response(value)


@router.get("/operations/outcome")
async def outcome(request: Request, request_key: str, expected_request_sha256: str):
    async with read(request) as (db, actor):
        value = await service.outcome(db, actor_user_id=actor, request_key_value=request_key,
                                      expected_request_sha256=expected_request_sha256)
    return _response(value)


@router.get("/designs/{design_id}/returns")
async def returns(request: Request, design_id: str, offset: int = 0, limit: int = 8):
    async with read(request) as (db, actor):
        value = await service.returns(db, actor_user_id=actor, design_id=design_id, offset=offset, limit=limit)
    return _response(value)
