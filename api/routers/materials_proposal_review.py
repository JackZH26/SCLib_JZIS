"""Default-disabled authenticated proposal reader and lossless JSON pages."""
import asyncio
from contextlib import asynccontextmanager
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import get_engine
from routers.auth import current_user_from_jwt
from services import materials_proposal_review as service
from services import materials_proposal_export as export_service
from services import materials_proposal_amendments as amendment_service
from services.materials_proposal_storage import canonical
from services.research_access import ResearchAccessDenied

HEADERS = {"Cache-Control":"private, no-store", "X-Content-Type-Options":"nosniff"}
_slots = threading.BoundedSemaphore(4)
MESSAGES = {400:"Invalid proposal review request",401:"Authentication required",403:"Current curator or reviewer access required",
    404:"Proposal review unavailable",409:"Proposal integrity or access changed; refresh",422:"Invalid proposal review query",
    503:"Proposal review temporarily unavailable"}
def failure(status):return HTTPException(status, MESSAGES.get(status,MESSAGES[400]), headers=HEADERS)


class PrivateReadRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request):
            if not _slots.acquire(blocking=False):raise failure(503)
            try:
                async with asyncio.timeout(15):
                    if len(request.scope.get("query_string", b""))>2048:raise failure(422)
                    return await handler(request)
            except ResearchAccessDenied:raise failure(403) from None
            except service.ProposalUnavailable:raise failure(404) from None
            except service.ProposalIntegrityError:raise failure(409) from None
            except RequestValidationError:raise failure(422) from None
            except HTTPException as error:raise failure(error.status_code) from None
            except (SQLAlchemyError, TimeoutError):raise failure(503) from None
            except (ValueError, TypeError, KeyError, OverflowError, RecursionError):raise failure(400) from None
            except Exception:raise failure(503) from None
            finally:_slots.release()
        return guarded


def enabled():
    if not get_settings().materials_ner_review_enabled:raise failure(404)


router = APIRouter(prefix="/research/materials-ner", tags=["materials-proposal-review"],
    route_class=PrivateReadRoute, dependencies=[Depends(enabled)])


@asynccontextmanager
async def read(request):
    authorization=request.headers.get("authorization")
    async def identity(db):
        actor=await current_user_from_jwt(request=request,authorization=authorization,db=db)
        grant=await service.admit(db,actor.id)
        return actor.id,actor.session_version,grant
    async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
        async with db.begin():
            await db.execute(text("SET TRANSACTION READ ONLY"))
            await db.execute(text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            before=await identity(db)
            yield db,before[0]
            # A fresh transaction must see the same live identity/grant before egress.
            async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as fresh:
                async with fresh.begin():
                    await fresh.execute(text("SET TRANSACTION READ ONLY"))
                    await fresh.execute(text("SET LOCAL statement_timeout='5000ms'"))
                    await fresh.execute(text("SET LOCAL TIME ZONE 'UTC'"))
                    if await identity(fresh)!=before:raise service.ProposalIntegrityError("proposal_read_authority_changed")


def response(value):
    payload=canonical(value).encode()
    if len(payload)>service.MAX_RESPONSE_BYTES:raise failure(503)
    return Response(payload,media_type="application/json",headers=HEADERS)


@router.get("/capabilities")
async def capabilities(request:Request):
    async with read(request) as (db,actor):value=await service.capabilities(db,actor)
    return response(value)


@router.get("/runs")
async def runs(request:Request,work_id:str|None=Query(None,max_length=100),after:str|None=Query(None,max_length=64),
               limit:int=Query(10,ge=1,le=25)):
    async with read(request) as (db,actor):value=await service.runs(db,actor,work_id=work_id,after=after,limit=limit)
    return response(value)


@router.get("/runs/{run_id}")
async def detail(request:Request,run_id:str,after:str|None=Query(None,max_length=200),limit:int=Query(10,ge=1,le=25)):
    async with read(request) as (db,actor):value=await service.run_detail(db,actor,run_id,after=after,limit=limit)
    return response(value)


@router.get("/runs/{run_id}/evidence")
async def evidence(request:Request,run_id:str,result_id:str=Query(...,min_length=1,max_length=200),
                   after:int=Query(-1,ge=-1,le=20000),limit:int=Query(40,ge=1,le=100)):
    async with read(request) as (db,actor):value=await service.evidence_page(db,actor,run_id,result_id=result_id,after=after,limit=limit)
    return response(value)


@router.get("/runs/{run_id}/export")
async def export_manifest(request:Request,run_id:str):
    async with read(request) as (db,actor):descriptor,_=await export_service.run_export(db,actor,run_id)
    return response(descriptor)


@router.get("/runs/{run_id}/export/package")
async def export_package(request:Request,run_id:str,expected_sha256:str=Query(...,pattern="^[0-9a-f]{64}$")):
    async with read(request) as (db,actor):
        descriptor,payload=await export_service.run_export(db,actor,run_id)
        service.require(descriptor["sha256"]==expected_sha256,"proposal_export_snapshot_changed")
    return Response(payload,media_type="application/zip",headers={**HEADERS,
        "Content-Disposition":f'attachment; filename="{descriptor["filename"]}"'})


@router.get("/runs/{run_id}/amendments")
async def amendments(request:Request,run_id:str):
    async with read(request) as (db,actor):
        value=await amendment_service.list_for_run(db,actor,run_id)
    return response(value)


@router.get("/runs/{run_id}/amendments/{amendment_id}")
async def amendment(request:Request,run_id:str,amendment_id:str):
    async with read(request) as (db,actor):
        value=await amendment_service.detail(db,actor,run_id,amendment_id)
    return response(value)


@router.get("/runs/{run_id}/amendments/{amendment_id}/export")
async def amendment_export(request:Request,run_id:str,amendment_id:str):
    async with read(request) as (db,actor):
        value=await amendment_service.detail(db,actor,run_id,amendment_id)
        csv_raw,contract=amendment_service.export(value['amendment'],value['mapping'])
    return response(dict(amendment_id=amendment_id,storage_hash=value['storage_hash'],
                         csv=csv_raw.decode('utf-8'),csv_contract=contract,authority=service.AUTHORITY))


@router.get("/runs/{run_id}/amendments/{amendment_id}/canonical-targets")
async def amendment_targets(request:Request,run_id:str,amendment_id:str,
                            result_id:str=Query(...,min_length=1,max_length=200)):
    async with read(request) as (db,actor):
        value=await amendment_service.canonical_targets(db,actor,run_id,amendment_id,result_id)
    return response(value)
