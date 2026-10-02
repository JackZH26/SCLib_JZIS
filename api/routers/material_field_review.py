"""Default-off reviewer metadata API; no public enrichment egress."""
import asyncio

from fastapi import APIRouter, Depends, Request

from routers.material_field_cases import read
from routers.research_distributions import _strict_json
from routers.source_properties import PrivateRoute, _failure, _response, _session, enabled
from services import material_field_review as service

router = APIRouter(prefix="/research/material-field-review", tags=["material-field-review"],
                   route_class=PrivateRoute, dependencies=[Depends(enabled)])


async def body(request, keys):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json" or request.headers.get("content-encoding", "identity").lower() != "identity":
        raise _failure(415)
    data = bytearray()
    async with asyncio.timeout(8):
        async for chunk in request.stream():
            if len(data)+len(chunk) > service.contract.MAX_BYTES+256:
                raise _failure(413)
            data.extend(chunk)
    value = _strict_json(data)
    service.contract.closed(value, keys)
    return value


@router.get("/capabilities")
async def capabilities(request: Request):
    async with read(request) as (db, actor):
        value = await service.capabilities(db, actor_user_id=actor)
    return _response(value)


@router.get("/context")
async def context(request: Request, target_id: str, field_id: str, expression_revision_id: str,
                  component_index: int = 0, component_kind: str = "condition", association_id: str | None = None,
                  tc_expression_revision_id: str | None = None):
    async with read(request) as (db, actor):
        value = await service.context(db, actor_user_id=actor, target_id=target_id, field_id=field_id,
            expression_revision_id=expression_revision_id, component_index=component_index, component_kind=component_kind,
            association_id=association_id, tc_expression_revision_id=tc_expression_revision_id)
    return _response(value)


@router.post("/operations/preview")
async def preview(request: Request):
    async with _session(request, write=True, role="reviewer") as (db, actor):
        value = await body(request, {"request"})
        result = await service.operate(db, actor_user_id=actor, request=value["request"])
    return _response(result)


@router.post("/operations/commit")
async def commit(request: Request):
    async with _session(request, write=True, role="reviewer") as (db, actor):
        value = await body(request, {"request", "expected_preview_sha256"})
        service.checksum(value["expected_preview_sha256"])
        result = await service.operate(db, actor_user_id=actor, request=value["request"], dry_run=False,
                                       expected_preview_sha256=value["expected_preview_sha256"])
    return _response(result)


@router.get("/operations/outcome")
async def outcome(request: Request, request_key: str, expected_request_sha256: str):
    async with read(request) as (db, actor):
        value = await service.outcome(db, actor_user_id=actor, request_key_value=request_key,
                                     expected_request_sha256=expected_request_sha256)
    return _response(value)


@router.get("/targets/{target_id}/history")
async def history(request: Request, target_id: str, field_id: str | None = None, offset: int = 0, limit: int = 8):
    async with read(request) as (db, actor):
        value = await service.history(db, actor_user_id=actor, target_id=target_id, field_id=field_id, offset=offset, limit=limit)
    return _response(value)


@router.get("/targets/{target_id}/effective")
async def effective(request: Request, target_id: str, field_id: str):
    async with read(request) as (db, actor):
        value = await service.effective(db, actor_user_id=actor, target_id=target_id, field_id=field_id)
    return _response(value)
