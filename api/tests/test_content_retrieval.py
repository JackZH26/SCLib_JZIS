"""Actual v2 hybrid reads over fresh owned pgvector; never production RPCs."""
import asyncio
import os
import struct
from dataclasses import replace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine,AsyncSession

from models.db import get_engine,get_session_factory
from services import content_retrieval as service,index_vector_adapter,retrieval_members,retrieval_navigation
from services.pgvector_query import PgvectorQueries,QueryBudget
from services.scientific_query import interpret_scientific_query
from tests.test_index_generations import db_session as db_session
from tests.test_retrieval_members import active_content
from tests.test_retrieval_activation import prepared_build,accepted,activation
from services import retrieval_activation

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned vector runner')]


@pytest_asyncio.fixture(loop_scope='function')
async def reader(db_session,tmp_path,monkeypatch):
    pin,ids,_=await active_content(db_session,tmp_path)
    members=await retrieval_members.load_members(db_session,pin,ids)
    vector=list(struct.unpack('!768f',members[0]['vector_bytes']))
    await db_session.commit()
    calls=[]
    def embed(profile,query):calls.append((profile,query));return list(vector)
    def forbidden(*args,**kwargs):raise AssertionError('Matching Engine must not be invoked')
    monkeypatch.setattr(service.query_embedding,'embed_query',embed)
    monkeypatch.setattr(index_vector_adapter,'_transport',forbidden)
    engine=create_async_engine(get_engine().url,pool_size=4,max_overflow=0,pool_timeout=.5)
    instance=service.ContentRetriever(get_session_factory(),PgvectorQueries(engine))
    try:yield instance,pin,ids,calls
    finally:
        await instance.close()
        await engine.dispose()


async def test_database_pin_and_actual_hybrid_bind_native_legacy_and_same_identity(reader):
    instance,pin,ids,calls=reader
    assert await instance.pin(logical_index=pin.logical_index)==pin
    result=await instance.hybrid(pin,'synthetic',interpret_scientific_query('synthetic'),top_k=2)
    assert result.pin==pin and set(result.chunks)==set(ids)
    assert {row.chunk_id for row in result.rankings}==set(ids)
    assert all(row.vector_score is not None and 'vector' in row.retrieval_modes for row in result.rankings)
    assert all(chunk.generation_pin==pin.metadata() for chunk in result.chunks.values())
    assert len(calls)==1 and calls[0][1]=='synthetic'
    assert {chunk.member['origin_kind'] for chunk in result.chunks.values()}=={'native_v2','legacy_v1'}


async def test_missing_or_forged_authority_does_not_start_embedding(reader):
    instance,pin,_,calls=reader
    with pytest.raises(service.ContentRetrievalUnavailable):await instance.pin(logical_index='absent-'+uuid4().hex)
    for forged in (pin.metadata(),replace(pin,activation_event_id=str(uuid4()))):
        with pytest.raises(service.ContentRetrievalUnavailable):
            await instance.hybrid(forged,'synthetic',interpret_scientific_query('synthetic'),top_k=2)
    assert calls==[]


@pytest.mark.parametrize('fault',['unresolved','different_query','bad_count','mapping'])
async def test_closed_request_before_any_embedding(reader,fault):
    instance,pin,_,calls=reader
    query='synthetic';interpretation=interpret_scientific_query(query);top_k=2
    if fault=='unresolved':interpretation=interpret_scientific_query('Tc >')
    elif fault=='different_query':interpretation=interpret_scientific_query('another query')
    elif fault=='mapping':interpretation=interpretation.model_dump()
    else:top_k=True
    with pytest.raises(service.ContentRetrievalUnavailable):await instance.hybrid(pin,query,interpretation,top_k=top_k)
    assert calls==[]


async def test_semantic_failure_cannot_be_published_as_partial_lexical_success(reader,monkeypatch):
    instance,pin,_,_=reader
    def failed(*args,**kwargs):raise RuntimeError('secret provider request')
    monkeypatch.setattr(service.query_embedding,'embed_query',failed)
    with pytest.raises(service.ContentRetrievalUnavailable) as error:
        await instance.hybrid(pin,'synthetic',interpret_scientific_query('synthetic'),top_k=2)
    assert 'secret' not in str(error.value)


async def test_navigation_failure_cancels_and_awaits_embedding_task(reader,monkeypatch):
    instance,pin,_,_=reader;started=asyncio.Event();ended=asyncio.Event()
    async def waiting(*args,**kwargs):
        started.set()
        try:await asyncio.Future()
        finally:ended.set()
    async def failed(*args,**kwargs):await started.wait();raise RuntimeError('SQL failed')
    monkeypatch.setattr(instance,'_semantic',waiting)
    monkeypatch.setattr(retrieval_navigation,'lexical_search',failed)
    with pytest.raises(service.ContentRetrievalUnavailable):
        await instance.hybrid(pin,'synthetic',interpret_scientific_query('synthetic'),top_k=2)
    assert ended.is_set()


async def test_caller_cancellation_cleans_up_sibling_task(reader,monkeypatch):
    instance,pin,_,_=reader;started=asyncio.Event();ended=asyncio.Event()
    async def waiting(*args,**kwargs):
        started.set()
        try:await asyncio.Future()
        finally:ended.set()
    monkeypatch.setattr(instance,'_semantic',waiting)
    task=asyncio.create_task(instance.hybrid(pin,'synthetic',interpret_scientific_query('synthetic'),top_k=2))
    await asyncio.wait_for(started.wait(),3);task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert ended.is_set()


async def test_activation_during_embedding_discards_every_old_candidate(reader,db_session,monkeypatch):
    instance,pin,_,_=reader
    later=await prepared_build(db_session,content_id=pin.content_id,logical_index=pin.logical_index)
    approval=await accepted(db_session,later);await db_session.commit()
    semantic=instance._semantic
    async def switched(*args,**kwargs):
        async with AsyncSession(get_engine()) as writer:
            await retrieval_activation.activate_backend(writer,**activation(later,approval,
                predecessor=pin.activation_event_id,old=False),dry_run=False)
            await writer.commit()
        return await semantic(*args,**kwargs)
    monkeypatch.setattr(instance,'_semantic',switched)
    with pytest.raises(service.ContentRetrievalUnavailable):
        await instance.hybrid(pin,'synthetic',interpret_scientific_query('synthetic'),top_k=2)


async def test_mutated_transport_policy_cannot_masquerade_as_sealed_policy(reader):
    instance,pin,_,calls=reader
    instance._transport.budget=QueryBudget(ef_search=400)
    with pytest.raises(service.ContentRetrievalUnavailable):
        await instance.hybrid(pin,'synthetic',interpret_scientific_query('synthetic'),top_k=2)
    assert calls==[]
