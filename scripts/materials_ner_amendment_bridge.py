"""Explicit local append-only amendment import; no provider or canonical writes."""
import asyncio
import json
import os
from pathlib import Path
import sys

R=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(R/'api'),str(R/'ingestion'),str(R/'scripts')]
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from ingestion.materials_ner.review_amendments import verify, review_mapping
from materials_ner_db_bridge_v2 import _apply_projected_packet
from models import materials_ner_amendments_v1 as schema
from services.materials_proposal_storage import canonical, projected_rows
from services.materials_proposal_amendments import storage_hash


async def apply(connection, parent, amendment):
    verify(amendment,parent)
    # verify rebuilds the amendment and verifies its complete parent receipt.
    return await _apply_prepared(connection, parent, amendment, projected_rows(parent), review_mapping(amendment))


async def _apply_prepared(connection, parent, amendment, rows, mapping):
    """Internal SQL phase for detached, verified input; never accepts raw CLI data."""
    await _apply_projected_packet(connection, parent, rows)
    h=storage_hash(amendment,mapping)
    args=dict(i=amendment['amendment_id'],r=parent['run_id'],p=parent['packet_hash'],
              a=canonical(amendment),m=canonical(mapping),h=h)
    inserted=(await connection.execute(text("""INSERT INTO materials_ner_v1.amendments
      (id,parent_run_id,parent_packet_hash,payload,mapping,storage_hash)
      VALUES(:i,:r,:p,CAST(:a AS jsonb),CAST(:m AS jsonb),:h)
      ON CONFLICT(id) DO NOTHING RETURNING id"""),args)).scalar_one_or_none() is not None
    row=(await connection.execute(text("""SELECT parent_run_id,parent_packet_hash,payload,mapping,storage_hash
      FROM materials_ner_v1.amendments WHERE id=:i"""),args)).mappings().one()
    if dict(row)!=dict(parent_run_id=parent['run_id'],parent_packet_hash=parent['packet_hash'],
                       payload=amendment,mapping=mapping,storage_hash=h):
        raise ValueError('amendment_storage_readback_mismatch')
    return dict(inserted=inserted,amendment_id=amendment['amendment_id'],storage_hash=h,
                readback_verified=True,selected_results=len(amendment['reviews']),
                scientific_acceptance=False,ml_training_eligible=False,canonical_writes=False)


async def process(request, database_url=None):
    if request.get('action') not in {'initialize','ingest'}: raise ValueError('unsupported_amendment_action')
    prepared = None
    if request['action'] == 'ingest':
        # Detach and replay before opening a database connection. A failed
        # source amendment cannot create even a partial parent import.
        parent, amendment = json.loads(canonical([request['parent'],request['amendment']]))
        verify(amendment,parent)
        prepared = (parent,amendment,projected_rows(parent),review_mapping(amendment))
    engine=create_async_engine(make_url(database_url or os.environ['DATABASE_URL']).set(drivername='postgresql+asyncpg'))
    try:
        async with engine.begin() as c:
            await c.execute(text("SET LOCAL statement_timeout='45s'"))
            await c.execute(text("SET LOCAL lock_timeout='10s'"))
            await c.execute(text('SELECT pg_advisory_xact_lock(924601)'))
            if request['action']=='initialize':
                await c.run_sync(schema.upgrade)
                result=dict(initialized=True,version=schema.VERSION,canonical_writes=False)
            else:
                fingerprint=(await c.execute(text('SELECT fingerprint FROM materials_ner_v1.schema_version WHERE version=:v'),
                                             dict(v=schema.VERSION))).scalar_one_or_none()
                if fingerprint!=schema.FINGERPRINT: raise ValueError('amendment_schema_not_initialized')
                result=await _apply_prepared(c,*prepared)
        return result
    finally: await engine.dispose()


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(16*1024**2+1)
        if len(raw)>16*1024**2: raise ValueError('amendment_request_too_large')
        print(canonical(asyncio.run(process(json.loads(raw)))))
    except Exception as e:
        print(canonical(dict(ok=False,error_class=type(e).__name__)))
        sys.exit(1)
