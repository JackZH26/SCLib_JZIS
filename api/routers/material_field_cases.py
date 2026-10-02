"""Default-disabled private material field cases; no public enrichment egress."""
from contextlib import asynccontextmanager

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_engine
from routers.source_properties import PrivateRoute, _body, _response, _session, enabled
from services import material_field_cases as service
from services.source_property_pending import SourcePropertyConflict

router = APIRouter(prefix="/research/material-field-cases", tags=["material-field-cases"],
                   route_class=PrivateRoute, dependencies=[Depends(enabled)])
FENCE = """SELECT r.epoch,r.xmin::text,s.epoch,s.xmin::text,p.epoch,p.xmin::text
 FROM public.research_integrity_epoch r CROSS JOIN public.source_lifecycle_epoch s
 CROSS JOIN public.research_publication_epoch p WHERE r.id=1 AND s.id=1 AND p.id=1"""


@asynccontextmanager
async def read(request):
    async with _session(request) as (db, actor):
        _, original_session = await service.reader(db, actor)
        before = (await db.execute(sa.text(FENCE))).one()
        yield db, actor
        # An independent read-committed snapshot detects catalogue, source,
        # expression and grant changes hidden by the stable private read.
        async with AsyncSession(get_engine().execution_options(isolation_level="READ COMMITTED")) as fresh:
            async with fresh.begin():
                await fresh.execute(sa.text("SET TRANSACTION READ ONLY"))
                await fresh.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
                after = (await fresh.execute(sa.text(FENCE))).one()
                try:
                    _, current_session = await service._grant(fresh, actor, "curator")
                except service.ResearchAccessDenied:
                    _, current_session = await service._grant(fresh, actor, "reviewer")
        if tuple(before) != tuple(after) or original_session != current_session:
            raise SourcePropertyConflict("field_case_read_snapshot_changed")


@router.get("/capabilities")
async def capabilities(request: Request, profile: str | None = None):
    async with read(request) as (db, actor):
        value = await service.capabilities(db, actor_user_id=actor, profile=profile)
    return _response(value)


@router.get("/context")
async def context(request: Request, material_id: str, kind: str = "retained_result",
                  record_index: int | None = None, entity_id: str | None = None):
    async with read(request) as (db, actor):
        value = await service.context(db, actor_user_id=actor, material_id=material_id, kind=kind,
                                      record_index=record_index, entity_id=entity_id)
    return _response(value)


@router.post("/operations/preview")
async def preview(request: Request):
    async with _session(request, write=True, role="curator") as (db, actor):
        body = await _body(request, keys={"request"})
        value = await service.operate(db, actor_user_id=actor, request=body["request"], dry_run=True)
    return _response(value)


@router.post("/operations/commit")
async def commit(request: Request):
    async with _session(request, write=True, role="curator") as (db, actor):
        body = await _body(request, keys={"request", "expected_preview_sha256"})
        service.checksum(body["expected_preview_sha256"])
        value = await service.operate(db, actor_user_id=actor, request=body["request"], dry_run=False,
                                      expected_preview_sha256=body["expected_preview_sha256"])
    return _response(value)


@router.get("/operations/outcome")
async def outcome(request: Request, request_key: str, expected_request_sha256: str):
    async with read(request) as (db, actor):
        value = await service.outcome(db, actor_user_id=actor, request_key_value=request_key,
                                      expected_request_sha256=expected_request_sha256)
    return _response(value)


@router.get("/targets")
async def targets(request: Request, offset: int = 0, limit: int = 8, material_id: str | None = None,
                  field_id: str | None = None, profile: str | None = None):
    async with read(request) as (db, actor):
        value = await service.targets(db, actor_user_id=actor, offset=offset, limit=limit,
                                      material_id=material_id, field_id=field_id, profile=profile)
    return _response(value)


@router.get("/targets/{target_id}")
async def target(request: Request, target_id: str, profile: str | None = None):
    async with read(request) as (db, actor):
        value = await service.target_detail(db, actor_user_id=actor, target_id=target_id, profile=profile)
    return _response(value)


@router.get("/materials/{material_id:path}")
async def material(request: Request, material_id: str, offset: int = 0, limit: int = 8, profile: str | None = None):
    async with read(request) as (db, actor):
        value = await service.material_adapter(db, actor_user_id=actor, material_id=material_id, offset=offset, limit=limit, profile=profile)
    return _response(value)
