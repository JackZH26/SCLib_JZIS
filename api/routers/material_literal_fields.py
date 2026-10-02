"""Opt-in private prepare; source text never travels through public enrichment."""
from fastapi import APIRouter, Depends, Request

from routers.material_field_cases import read
from routers.source_properties import PrivateRoute, _body, _response, enabled
from services import material_literal_field_prepare as service

router = APIRouter(prefix="/research/material-literal-fields", tags=["material-literal-fields"],
                   route_class=PrivateRoute, dependencies=[Depends(enabled)])


@router.get("/capabilities")
async def capabilities(request: Request):
    async with read(request) as (db, actor):
        caps = await service.cases.capabilities(db, actor_user_id=actor, profile=service.PROFILE)
    return _response({"version": service.VERSION, "profile": service.PROFILE,
                      "prepare_request_keys": sorted(service.REQUEST_KEYS), "field_cases": caps,
                      "scope": "private_pending_prepare", **service.case_contract.AUTHORITY})


@router.post("/prepare")
async def prepare(request: Request):
    async with read(request) as (db, actor):
        body = await _body(request, keys=service.REQUEST_KEYS)
        result = await service.prepare(db, actor_user_id=actor, request=body)
    return _response(result)
