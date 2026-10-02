"""Private v2 primary-fragment intake; the existing disabled flag governs both."""

from fastapi import APIRouter, Depends, Request

from routers.source_properties import PrivateRoute, _body, _response, _session, enabled
from services import source_expression_intake_v2 as service

router = APIRouter(
    prefix="/research/source-expressions",
    tags=["pending-source-expressions"],
    route_class=PrivateRoute,
    dependencies=[Depends(enabled)],
)


@router.get("/capabilities")
async def capabilities(request: Request):
    async with _session(request) as (db, actor):
        return _response(await service.capabilities(db, actor_user_id=actor))


@router.post("/imports/preview")
async def preview(request: Request):
    async with _session(request, write=True, role="curator") as (db, actor):
        body = await _body(request, keys={"request_key", "package"})
        value = await service.import_package(
            db,
            actor_user_id=actor,
            request_key_value=body["request_key"],
            package=body["package"],
            dry_run=True,
        )
    return _response(value)


@router.post("/imports/commit")
async def commit(request: Request):
    async with _session(request, write=True, role="curator") as (db, actor):
        body = await _body(request, keys={"request_key", "package", "expected_preview_sha256"})
        service.checksum(body["expected_preview_sha256"])
        value = await service.import_package(
            db,
            actor_user_id=actor,
            request_key_value=body["request_key"],
            package=body["package"],
            dry_run=False,
            expected_preview_sha256=body["expected_preview_sha256"],
        )
    return _response(value)


@router.get("/imports/outcome")
async def outcome(request: Request, request_key: str, expected_request_sha256: str):
    async with _session(request, role="curator") as (db, actor):
        return _response(
            await service.outcome(
                db,
                actor_user_id=actor,
                request_key_value=request_key,
                expected_request_sha256=expected_request_sha256,
            )
        )


@router.get("/captures")
async def captures(
    request: Request, offset: int = 0, limit: int = 25, currentness: str | None = None
):
    async with _session(request) as (db, actor):
        return _response(
            await service.captures(
                db, actor_user_id=actor, offset=offset, limit=limit, currentness=currentness
            )
        )


@router.get("/captures/{capture_id}")
async def capture(request: Request, capture_id: str):
    async with _session(request) as (db, actor):
        return _response(await service.capture(db, actor_user_id=actor, capture_id=capture_id))


@router.get("/expressions")
async def expressions(
    request: Request,
    offset: int = 0,
    limit: int = 8,
    source_id: str | None = None,
    field_id: str | None = None,
    currentness: str | None = None,
):
    async with _session(request) as (db, actor):
        return _response(
            await service.expressions(
                db,
                actor_user_id=actor,
                offset=offset,
                limit=limit,
                source_id=source_id,
                field_id=field_id,
                currentness=currentness,
            )
        )


@router.get("/expressions/{revision_id}")
async def expression(request: Request, revision_id: str):
    async with _session(request) as (db, actor):
        return _response(await service.expression(db, actor_user_id=actor, revision_id=revision_id))
