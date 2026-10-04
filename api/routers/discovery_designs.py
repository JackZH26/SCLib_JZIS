"""Private, proposal-only Discovery designs, independently disabled by default."""
from contextlib import asynccontextmanager

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import get_engine
from routers.source_properties import PrivateRoute, _body, _failure, _response, _session
from services import discovery_designs as service
from services.source_property_pending import _grant
from services.source_property_pending import SourcePropertyConflict


def enabled():
    if not get_settings().discovery_designs_enabled:
        raise _failure(404)


router = APIRouter(prefix="/research/discovery-designs", tags=["discovery-designs"],
                   route_class=PrivateRoute, dependencies=[Depends(enabled)])
FENCE = """SELECT r.epoch,r.xmin::text,s.epoch,s.xmin::text,p.epoch,p.xmin::text
 FROM public.research_integrity_epoch r CROSS JOIN public.source_lifecycle_epoch s
 CROSS JOIN public.research_publication_epoch p WHERE r.id=1 AND s.id=1 AND p.id=1"""


@asynccontextmanager
async def read(request):
    async with _session(request, role="curator") as (db, actor):
        await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
        original = await _grant(db, actor, "curator")
        before = (await db.execute(sa.text(FENCE))).one()
        yield db, actor
        async with AsyncSession(get_engine().execution_options(isolation_level="READ COMMITTED")) as fresh:
            async with fresh.begin():
                await fresh.execute(sa.text("SET TRANSACTION READ ONLY"))
                await fresh.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
                after = (await fresh.execute(sa.text(FENCE))).one()
                current = await _grant(fresh, actor, "curator")
        if tuple(before) != tuple(after) or original != current:
            raise SourcePropertyConflict("discovery_design_read_snapshot_changed")


@router.get("/capabilities")
async def capabilities(request: Request):
    async with read(request) as (db, actor):
        value = await service.capabilities(db, actor_user_id=actor)
    return _response(value)


@router.get("/context")
async def context(request: Request, kind: str = "unanchored", material_id: str | None = None,
                  record_index: int | None = None, property_id: str | None = None):
    async with read(request) as (db, actor):
        value = await service.context(db, actor_user_id=actor, kind=kind, material_id=material_id,
                                      record_index=record_index, property_id=property_id)
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


@router.get("/designs")
async def designs(request: Request, offset: int = 0, limit: int = 8):
    async with read(request) as (db, actor):
        value = await service.designs(db, actor_user_id=actor, offset=offset, limit=limit)
    return _response(value)


@router.get("/designs/{design_id}")
async def design(request: Request, design_id: str):
    async with read(request) as (db, actor):
        value = await service.design_detail(db, actor_user_id=actor, design_id=design_id)
    return _response(value)
