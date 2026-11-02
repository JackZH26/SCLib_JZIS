"""Real owned SQL preparation and physical identity checks, no production DDL."""
from contextlib import asynccontextmanager
from dataclasses import replace
import os
import asyncio

import pytest
import sqlalchemy as sa

from models.db import get_session_factory
from services import retrieval_activation,content_retrieval
from services.retrieval_readiness import ProjectionReadiness,ProjectionNotReady
from services.pgvector_query import PgvectorQueries
from services.scientific_query import interpret_scientific_query
from tests.test_index_generations import db_session as db_session
from tests.test_retrieval_members import active_content
from tests.test_retrieval_activation import accepted,activation,prepared_build
from tests.test_research_freeze import state

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned vector/prewarm runner')]


async def setup(db):
    pin,_,_=await active_content(db)
    await db.commit()
    return pin,ProjectionReadiness(get_session_factory())


async def test_explicit_read_only_preparation_then_fresh_readiness(db_session):
    pin,ready=await setup(db_session)
    before=await state(db_session)
    assert not await ready.ready(pin)
    receipt=await ready.prepare(pin)
    assert [phase['mode'] for phase in receipt['phases']]==['read','read','buffer']
    assert receipt['query_warmups']==0 and receipt['future_cache_residency_guaranteed'] is False
    assert receipt['permissions_or_scientific_acceptance'] is False
    assert receipt['build_id']==pin.build_id and receipt['postmaster_started_at']
    assert await ready.ready(pin) and await state(db_session)==before


async def test_unprepared_hybrid_cannot_schedule_provider_or_ANN(db_session,monkeypatch):
    from models.db import get_engine
    pin,_=await setup(db_session)
    reader=content_retrieval.ContentRetriever(get_session_factory(),PgvectorQueries(get_engine()))
    def forbidden(*args,**kwargs):raise AssertionError('Provider must not start before readiness')
    monkeypatch.setattr(content_retrieval.query_embedding,'embed_query',forbidden)
    try:
        with pytest.raises(content_retrieval.ContentRetrievalUnavailable):
            await reader.hybrid(pin,'synthetic',interpret_scientific_query('synthetic'),top_k=2)
    finally:await reader.close()


async def test_aba_activation_cannot_reuse_prepared_same_build(db_session):
    pin,ready=await setup(db_session);await ready.prepare(pin)
    later=await prepared_build(db_session,content_id=pin.content_id,logical_index=pin.logical_index)
    event=await retrieval_activation.activate_backend(db_session,**activation(later,await accepted(db_session,later),
        predecessor=pin.activation_event_id,old=False),dry_run=False)
    # Recover the initial active build's exact validation reference.
    first=(await db_session.execute(sa.text('SELECT build_id,validation_id FROM retrieval_activation_events_v2 WHERE id=:id'),
        {'id':__import__('uuid').UUID(pin.activation_event_id)})).mappings().one()
    first={**first,'build_id':str(first['build_id']),'validation_id':str(first['validation_id'])}
    args=activation(first,await accepted(db_session,first),predecessor=event['activation_event_id'],old=False)
    await retrieval_activation.activate_backend(db_session,**(args|{'action':'rollback'}),dry_run=False)
    current=await retrieval_activation.load_active_backend(db_session,logical_index=pin.logical_index)
    await db_session.commit()
    assert current.build_id==pin.build_id and current.activation_event_id!=pin.activation_event_id
    assert not await ready.ready(pin) and not await ready.ready(current)
    await ready.prepare(current);assert await ready.ready(current)


async def test_physical_graph_rewrite_invalidates_old_cache_witness(db_session):
    pin,ready=await setup(db_session);await ready.prepare(pin)
    before=await state(db_session)
    await db_session.execute(sa.text('REINDEX INDEX retrieval_projection.hnsw_b_'+pin.build_id.replace('-','')))
    await db_session.commit()
    assert await state(db_session)==before
    assert not await ready.ready(pin)
    await ready.prepare(pin);assert await ready.ready(pin)


async def test_changed_server_boot_and_missing_probe_fail_closed(db_session,monkeypatch):
    pin,ready=await setup(db_session);await ready.prepare(pin)
    witness=ready._witness
    async def rebooted(db,pin):return replace(await witness(db,pin),postmaster_started_at='different synthetic boot')
    monkeypatch.setattr(ready,'_witness',rebooted)
    assert not await ready.ready(pin)
    async def failed(db,pin):raise RuntimeError('database unavailable')
    monkeypatch.setattr(ready,'_witness',failed)
    assert not await ready.ready(pin)


async def test_insufficient_buffer_budget_refuses_preparation(db_session,monkeypatch):
    pin,ready=await setup(db_session)
    witness=ready._witness
    async def too_small(db,pin):
        row=await witness(db,pin)
        return replace(row,shared_buffer_bytes=row.graph_bytes)
    monkeypatch.setattr(ready,'_witness',too_small)
    with pytest.raises(ProjectionNotReady,match='reserved shared-buffer budget'):await ready.prepare(pin)
    assert not await ready.ready(pin)


async def test_read_only_reader_can_prepare_without_DDL_or_superuser(db_session):
    pin,_=await setup(db_session)
    await db_session.execute(sa.text('GRANT SELECT ON ALL TABLES IN SCHEMA public TO sclib_retrieval_reader'))
    await db_session.execute(sa.text('GRANT USAGE ON SCHEMA retrieval_projection TO sclib_retrieval_reader'))
    await db_session.execute(sa.text('GRANT SELECT ON ALL TABLES IN SCHEMA retrieval_projection TO sclib_retrieval_reader'))
    await db_session.commit();before=await state(db_session)
    @asynccontextmanager
    async def sessions():
        async with get_session_factory()() as db:
            await db.execute(sa.text('SET LOCAL ROLE sclib_retrieval_reader'))
            yield db
    ready=ProjectionReadiness(sessions)
    await ready.prepare(pin)
    assert await ready.ready(pin) and await state(db_session)==before


async def test_activation_during_warming_cannot_mark_stale_projection_ready(db_session,monkeypatch):
    pin,ready=await setup(db_session)
    later=await prepared_build(db_session,content_id=pin.content_id,logical_index=pin.logical_index)
    approval=await accepted(db_session,later);await db_session.commit()
    read=ready._read
    async def switched(operation,*,warming=False):
        result=await read(operation,warming=warming)
        if warming:
            async with get_session_factory()() as writer:
                await retrieval_activation.activate_backend(writer,**activation(later,approval,
                    predecessor=pin.activation_event_id,old=False),dry_run=False)
                await writer.commit()
        return result
    monkeypatch.setattr(ready,'_read',switched)
    with pytest.raises(ValueError):await ready.prepare(pin)
    assert not await ready.ready(pin)


async def test_inflight_ready_probe_cannot_undo_a_failed_new_preparation(db_session,monkeypatch):
    pin,ready=await setup(db_session);await ready.prepare(pin)
    witness=ready._witness;read=ready._read;started=asyncio.Event();release=asyncio.Event()
    async def held(db,pin):
        observed=await witness(db,pin)
        started.set();await release.wait()
        return observed
    async def failed(operation,*,warming=False):
        if warming:raise RuntimeError('Preparation failed before warming')
        return await read(operation,warming=warming)
    monkeypatch.setattr(ready,'_witness',held)
    monkeypatch.setattr(ready,'_read',failed)
    probe=asyncio.create_task(ready.ready(pin));await started.wait()
    with pytest.raises(RuntimeError):await ready.prepare(pin)
    release.set()
    assert await probe is False
