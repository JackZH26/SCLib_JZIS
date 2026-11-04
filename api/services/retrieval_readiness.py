"""Explicit startup cache preparation for a sealed active v2 projection.

This is operational readiness, not a claim that cache pages cannot be evicted,
source permission, retrieval quality or scientific acceptance. No DDL/grant or
automatic cold-request warmup is performed. A privileged operator must install
pg_prewarm separately before this read-only component can prepare a projection.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa

from services.retrieval_activation import RetrievalPinV2
from services.retrieval_candidate import is_read_pin,current_read_pin


class ProjectionNotReady(ValueError):pass


@dataclass(frozen=True,slots=True)
class ProjectionWitness:
    pin: RetrievalPinV2
    postmaster_started_at: str
    table_oid: int
    graph_oid: int
    primary_key_oid: int
    table_filenode: int
    graph_filenode: int
    primary_key_filenode: int
    table_bytes: int
    graph_bytes: int
    primary_key_bytes: int
    shared_buffer_bytes: int
    block_size: int
    member_count: int


async def physical_witness(db,pin):
    """Measure the physical identity after the caller verifies its active or historical seal."""
    row=(await db.execute(sa.text("""
      SELECT pg_postmaster_start_time() AS started,t.oid AS table_oid,g.oid AS graph_oid,k.oid AS primary_key_oid,
        pg_relation_filenode(t.oid) AS table_filenode,pg_relation_filenode(g.oid) AS graph_filenode,
        pg_relation_filenode(k.oid) AS primary_key_filenode,pg_relation_size(t.oid) AS table_bytes,
        pg_relation_size(g.oid) AS graph_bytes,pg_relation_size(k.oid) AS primary_key_bytes,
        pg_size_bytes(current_setting('shared_buffers')) AS shared_buffer_bytes,
        current_setting('block_size')::integer AS block_size,b.expected_member_count AS member_count
      FROM pg_class t JOIN pg_index gi ON gi.indrelid=t.oid
      JOIN pg_class g ON g.oid=gi.indexrelid JOIN pg_am am ON am.oid=g.relam AND am.amname='hnsw'
      JOIN pg_index ki ON ki.indrelid=t.oid AND ki.indisprimary JOIN pg_class k ON k.oid=ki.indexrelid
      JOIN retrieval_backend_builds_v2 b ON b.id=:build
      WHERE t.oid=to_regclass(:table) AND gi.indisvalid AND gi.indisready
    """),{'table':pin.projection.table,'build':UUID(pin.build_id)})).mappings().one()
    values={key:int(value) for key,value in row.items() if key!='started'}
    if any(value<=0 for value in values.values()):raise ProjectionNotReady('Nonempty exact physical projection required')
    return ProjectionWitness(pin,row['started'].isoformat(),**values)


class ProjectionReadiness:
    def __init__(self,session_factory):
        self._sessions=session_factory
        self._lock=asyncio.Lock()
        self._prepared=None

    async def _witness(self,db,pin):
        if not is_read_pin(pin):raise ProjectionNotReady('An exact internal v2 pin is required')
        await current_read_pin(db,pin)
        return await physical_witness(db,pin)

    async def _read(self,operation,*,warming=False):
        async with self._sessions() as db:
            await db.execute(sa.text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            await db.execute(sa.text("SET LOCAL statement_timeout='120s'" if warming else
                "SET LOCAL statement_timeout='2000ms'"))
            await db.execute(sa.text("SET LOCAL lock_timeout='250ms'"))
            return await operation(db)

    def prepared_witness(self,pin):
        witness=self._prepared
        if witness is None or witness.pin!=pin:
            raise ProjectionNotReady('Prepared projection changed')
        return witness

    async def ready(self,pin):
        prepared=self._prepared
        if prepared is None or not is_read_pin(pin) or prepared.pin!=pin:return False
        try:
            async with asyncio.timeout(3):
                observed=await self._read(lambda db:self._witness(db,pin))
                return self._prepared is prepared and observed==prepared
        except Exception:return False

    async def prepare(self,pin):
        """Explicit startup/operator stage, never called inside a query.

        Read heap/key sequentially into OS cache, then load the HNSW graph into
        shared buffers. Reserve at least 20% of buffers for other database work.
        Confirm a NEW authority/boot/physical snapshot after warming; an ABA
        activation, restart or physical rewrite cannot inherit prior readiness.
        """
        async with asyncio.timeout(180),self._lock:
            self._prepared=None
            started=time.monotonic()
            async def warm(db):
                before=await self._witness(db,pin)
                # The measured retained corpus's TOAST/backup working set also
                # competes for buffers. Fitting the graph alone allowed a 6-GiB
                # profile that lost all graph pages and failed 24/240 queries.
                # Larger-than-smoke builds require the measured 16-GiB floor;
                # this still does not replace exact-build performance gates.
                if before.member_count>1000 and before.shared_buffer_bytes<16*1024**3:
                    raise ProjectionNotReady('Corpus preparation requires the measured 16-GiB shared-buffer floor')
                if before.graph_bytes*5>before.shared_buffer_bytes*4:
                    raise ProjectionNotReady('The sealed graph exceeds its reserved shared-buffer budget')
                if not await db.scalar(sa.text("SELECT to_regprocedure('public.pg_prewarm(regclass,text,text,bigint,bigint)') IS NOT NULL")):
                    raise ProjectionNotReady('Operator-installed pg_prewarm is required')
                phases=[]
                for oid,size,mode in [(before.table_oid,before.table_bytes,'read'),
                                      (before.primary_key_oid,before.primary_key_bytes,'read'),
                                      (before.graph_oid,before.graph_bytes,'buffer')]:
                    blocks=await db.scalar(sa.text('SELECT public.pg_prewarm(CAST(CAST(:oid AS oid) AS regclass),:mode)'),
                        {'oid':oid,'mode':mode})
                    if blocks*before.block_size!=size:raise ProjectionNotReady('Complete relation prewarm was not observed')
                    phases.append({'relation_oid':oid,'mode':mode,'blocks':blocks})
                return before,phases
            before,phases=await self._read(warm,warming=True)
            after=await self._read(lambda db:self._witness(db,pin))
            if after!=before:raise ProjectionNotReady('Authority, server boot or physical projection changed during preparation')
            self._prepared=after
            return {'version':'projection-readiness/1.0.0','build_id':pin.build_id,
                'content_id':pin.content_id,**({'activation_event_id':pin.activation_event_id}
                    if type(pin) is RetrievalPinV2 else {'engineering_candidate':pin.metadata()}),
                'postmaster_started_at':after.postmaster_started_at,'phases':phases,
                'shared_buffer_bytes':after.shared_buffer_bytes,'graph_bytes':after.graph_bytes,
                'seconds':time.monotonic()-started,'query_warmups':0,
                'permissions_or_scientific_acceptance':False,'future_cache_residency_guaranteed':False}
