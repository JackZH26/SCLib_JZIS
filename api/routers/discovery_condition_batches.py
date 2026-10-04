"""Private condition batches with separate bounded raw manifest export."""
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, Response

from config import get_settings
from routers.discovery_designs import read
from routers.source_properties import HEADERS, PrivateRoute, _body, _failure, _response, _session
from services import discovery_condition_batches as service


def enabled():
    if not get_settings().discovery_condition_batches_enabled:
        raise _failure(404)


router = APIRouter(prefix="/research/discovery-condition-batches", tags=["discovery-condition-batches"],
                   route_class=PrivateRoute, dependencies=[Depends(enabled)])


@router.get("/capabilities")
async def capabilities(request: Request):
    async with read(request) as (db, actor):
        value = await service.capabilities(db, actor_user_id=actor)
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


@router.get("/batches")
async def batches(request: Request, offset: int = 0, limit: int = 8):
    async with read(request) as (db, actor):
        value = await service.batches(db, actor_user_id=actor, offset=offset, limit=limit)
    return _response(value)


@router.get("/batches/{batch_id}")
async def batch(request: Request, batch_id: str, offset: int = 0, limit: int = 8):
    async with read(request) as (db, actor):
        value = await service.batch_detail(db, actor_user_id=actor, batch_id=batch_id, offset=offset, limit=limit)
    return _response(value)


@router.get("/batches/{batch_id}/manifest")
async def manifest(request: Request, batch_id: str):
    async with read(request) as (db, actor):
        value = await service.export_manifest(db, actor_user_id=actor, batch_id=batch_id)
    return Response(content=value, media_type="application/json", headers=HEADERS)
