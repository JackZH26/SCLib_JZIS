"""Canonical Materials read path, enabled locally until the corpus release."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from config import get_settings
from models import get_db
from models.materials_vnext import AdmittedTcPage
from services.materials_vnext_read import admitted_tc_page
from services.materials_dataset_download import (
    DownloadUnavailable, FILES, assert_current, canonical_download_state,
    public_snapshot, read_csv, read_snapshot,
)

router=APIRouter(tags=['materials'])


@router.get('/materials/results',response_model=AdmittedTcPage)
async def material_results(response:Response,db:AsyncSession=Depends(get_db),
    q:str|None=Query(None,max_length=200),
    material_id:str|None=Query(None,min_length=1,max_length=200),
    pressure:Literal['explicit_ambient','nonambient','unknown']|None=None,
    criterion:Literal['onset','midpoint','zero_resistance','diamagnetic_onset','heat_capacity_anomaly','unspecified']|None=None,
    limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0)):
    if not get_settings().materials_vnext_enabled:raise HTTPException(404,'Materials dataset unavailable')
    response.headers['Cache-Control']='no-store'
    return await admitted_tc_page(db,query=q,material_id=material_id,pressure=pressure,criterion=criterion,limit=limit,offset=offset)


async def current_download(db, version=None):
    settings = get_settings()
    if not settings.materials_vnext_enabled:
        raise HTTPException(404, 'Materials dataset unavailable')
    try:
        folder, snapshot = await run_in_threadpool(read_snapshot, settings.materials_dataset_download_root, version)
        assert_current(snapshot, await canonical_download_state(db))
        return folder, snapshot
    except DownloadUnavailable as error:
        raise HTTPException(error.status, str(error), headers={'Cache-Control': 'no-store'}) from error


@router.get('/materials/dataset')
async def material_dataset(response: Response, db: AsyncSession = Depends(get_db)):
    _, snapshot = await current_download(db)
    response.headers['Cache-Control'] = 'no-store'
    return public_snapshot(snapshot)


@router.get('/materials/dataset/{version}/{kind}')
async def material_dataset_file(version: str, kind: Literal['results', 'evidence', 'training'],
    db: AsyncSession = Depends(get_db)):
    folder, snapshot = await current_download(db, version)
    try:
        content = await run_in_threadpool(read_csv, folder, snapshot, kind)
    except DownloadUnavailable as error:
        raise HTTPException(error.status, str(error), headers={'Cache-Control': 'no-store'}) from error
    return Response(content, media_type='text/csv', headers={'Cache-Control': 'no-store',
        'Content-Disposition': f'attachment; filename="{FILES[kind]}"',
        'X-Dataset-Version': snapshot['version']})
