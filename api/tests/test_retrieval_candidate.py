"""Owned synthetic candidate reads without acceptance or v2 activation."""
import os
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine

from config import get_settings
from models.db import get_engine,get_session_factory,Paper
from services.scientific_query import interpret_scientific_query
from services import retrieval_candidate as service,retrieval_content,retrieval_members
from services.candidate_runtime import CandidateRetriever
from services.content_retrieval import ContentRetriever,ContentRetrievalUnavailable
from services.content_runtime import selected_reader
from services.pgvector_query import PgvectorQueries
from tests.test_index_generations import db_session as db_session
from tests.test_research_freeze import state
from tests.test_retrieval_activation import prepared_build,accepted,activation
from tests.test_retrieval_content import publication
from services.retrieval_activation import activate_backend

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned PostgreSQL/vector services')]


@pytest_asyncio.fixture
async def candidate(db_session,tmp_path):
    first=await prepared_build(db_session)
    _,_,published=await publication(db_session,tmp_path)
    content=await retrieval_content.stage_native_content(db_session,base_content_id=first['content_id'],
        publication_ids=[published['publication_id']],dry_run=False)
    refs=await retrieval_content.source_reference_page(db_session,content_id=content['content_id'])
    await retrieval_content.append_content_partition(db_session,content_id=content['content_id'],partition_id=0,references=refs,dry_run=False)
    await retrieval_content.seal_content(db_session,content_id=content['content_id'],dry_run=False)
    built=await prepared_build(db_session,content_id=content['content_id'],logical_index=first['logical_index'])
    await db_session.execute(sa.text('CREATE SCHEMA IF NOT EXISTS sclib_pgvector_rehearsal'))
    await db_session.execute(sa.text('CREATE TABLE IF NOT EXISTS sclib_pgvector_rehearsal.source '
        '(singleton boolean PRIMARY KEY CHECK(singleton),generation_id uuid NOT NULL,manifest text NOT NULL)'))
    await db_session.execute(sa.text('DELETE FROM sclib_pgvector_rehearsal.source'))
    await db_session.execute(sa.text('INSERT INTO sclib_pgvector_rehearsal.source VALUES(true,:g,:m)'),
        {'g':first['old']['generation_id'],'m':first['old']['manifest_sha256']})
    database=await db_session.scalar(sa.text('SELECT current_database()'));await db_session.commit()
    engine=create_async_engine(get_engine().url,pool_size=4,max_overflow=0,pool_timeout=.5)
    reader=CandidateRetriever(get_session_factory(),PgvectorQueries(engine),build_id=built['build_id'],
        validation_id=built['validation_id'],expected_database=database)
    pin=await reader.pin(logical_index=first['logical_index']);await reader.prepare(pin)
    try:yield reader,pin,first,built
    finally:
        await reader.close();await engine.dispose()


async def test_same_similarity_and_hybrid_pipeline_without_invented_activation(candidate,db_session,monkeypatch):
    reader,pin,_,_=candidate
    before=await state(db_session)
    ids=await db_session.scalars(sa.text('SELECT vector_id FROM retrieval_content_members_v2 WHERE content_id=CAST(:c AS uuid)'),{'c':pin.content_id})
    chunks=await retrieval_members.hydrate(db_session,pin,list(ids))
    import struct
    vector=struct.unpack('!768f',next(iter(chunks.values())).member['vector_bytes'])
    from services import query_embedding
    monkeypatch.setattr(query_embedding,'embed_query',lambda *args:list(vector))
    await db_session.rollback()
    source=next(iter(chunks.values())).paper_id
    outcome=await reader.similar(pin,source,top_k=10)
    assert len(outcome.results)==1 and outcome.results[0].paper_id!=source
    hybrid=await reader.hybrid(pin,'synthetic',interpret_scientific_query('synthetic'),top_k=2)
    assert set(hybrid.chunks)==set(chunks)
    assert pin.metadata()['scope']=='owned_restore_not_activated'
    assert 'activation_event_id' not in pin.metadata() and not hasattr(pin,'activation_event_id')
    assert all(row.generation_pin==pin.metadata() for row in hybrid.chunks.values())
    assert await db_session.scalar(sa.text('SELECT count(*) FROM retrieval_activation_events_v2 WHERE build_id=CAST(:b AS uuid)'),{'b':pin.build_id})==0
    assert await db_session.scalar(sa.text('SELECT count(*) FROM retrieval_acceptances_v2 WHERE build_id=CAST(:b AS uuid)'),{'b':pin.build_id})==0
    assert await state(db_session)==before


async def test_public_reader_routes_and_history_cannot_treat_candidate_as_activation(candidate,monkeypatch):
    reader,pin,_,_=candidate
    public=ContentRetriever(reader._sessions,reader._transport)
    try:
        with pytest.raises(ContentRetrievalUnavailable):public._pin(pin)
        monkeypatch.setattr(get_settings(),'retrieval_backend','pgvector')
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(content_reader=reader)))
        with pytest.raises(HTTPException) as error:selected_reader(request)
        assert error.value.status_code==503
    finally:await public.close()


async def test_exact_candidate_forgery_physical_guard_marker_and_production_refused(candidate,db_session,monkeypatch):
    _,pin,_,_=candidate
    for forged in (replace(pin,validation_record_sha256='0'*64),replace(pin,build_record_sha256='0'*64),
                   replace(pin,manifest_sha256='0'*64),replace(pin,database_name='another-database')):
        with pytest.raises(service.CandidateUnavailable):await service.current_read_pin(db_session,forged)
    await db_session.execute(sa.text('UPDATE sclib_pgvector_rehearsal.source SET manifest=:m'),{'m':'0'*64})
    with pytest.raises(service.CandidateUnavailable):await service.current_read_pin(db_session,pin)
    await db_session.rollback()
    monkeypatch.setattr(get_settings(),'environment','production')
    with pytest.raises(service.CandidateUnavailable):await service.current_read_pin(db_session,pin)


async def test_actual_v2_activation_ends_candidate_scope(candidate,db_session):
    _,pin,first,built=candidate
    await activate_backend(db_session,**activation(first,await accepted(db_session,first)),dry_run=False)
    await db_session.commit()
    with pytest.raises(service.CandidateUnavailable,match='ended'):await service.current_read_pin(db_session,pin)


async def test_changed_live_rights_are_not_restored_by_candidate(candidate,db_session):
    reader,pin,_,_=candidate
    papers=list((await db_session.scalars(sa.text('SELECT DISTINCT paper_id FROM retrieval_content_members_v2 WHERE content_id=CAST(:c AS uuid)'),{'c':pin.content_id})))
    await db_session.execute(sa.update(Paper).where(Paper.id==papers[1]).values(status='retracted'));await db_session.commit()
    assert (await reader.similar(pin,papers[0])).results==()


async def test_private_http_marks_results_and_has_no_public_or_history_routes(candidate,db_session,monkeypatch):
    import httpx,struct
    from services.candidate_http import create_private_app
    from services import query_embedding
    reader,pin,_,_=candidate
    source=await db_session.scalar(sa.text('SELECT paper_id FROM retrieval_content_members_v2 WHERE content_id=CAST(:c AS uuid) LIMIT 1'),{'c':pin.content_id})
    vector=await db_session.scalar(sa.text('SELECT vector_bytes FROM index_generation_members LIMIT 1'))
    monkeypatch.setattr(query_embedding,'embed_query',lambda *args:list(struct.unpack('!768f',vector)))
    await db_session.rollback()
    app=create_private_app(reader,pin)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://owned-loopback') as client:
        health=await client.get('/health');assert health.status_code==200 and health.json()['ready']
        similar=await client.post('/candidate/similar',json={'paper_id':source})
        assert similar.status_code==200 and len(similar.json()['results'])==1
        assert similar.json()['scope']=='owned_restore_not_activated'
        hybrid=await client.post('/candidate/hybrid',json={'query':'synthetic','top_k':2})
        assert hybrid.status_code==200 and len(hybrid.json()['rankings'])==2
        assert 'activation_event_id' not in hybrid.json()['candidate']
        assert (await client.post('/candidate/hybrid',json={'query':'Tc > 20 K'})).status_code==422
        assert (await client.post('/candidate/similar',json={'paper_id':source,'top_k':True})).status_code==422
        assert (await client.post('/candidate/similar',json={'paper_id':source,'activation_event_id':str(uuid4())})).status_code==422
        for path in ('/v1/search','/v1/ask','/v1/answers','/docs','/openapi.json'):
            assert (await client.get(path)).status_code==404


async def test_frozen_embedding_replay_is_explicit_immutable_and_never_falls_back(candidate,db_session,monkeypatch):
    import struct
    from services import query_embedding
    original,pin,_,_=candidate
    raw=await db_session.scalar(sa.text('SELECT vector_bytes FROM index_generation_members LIMIT 1'))
    vectors={'synthetic':list(struct.unpack('!768f',raw))}
    reader=CandidateRetriever(original._sessions,original._transport,build_id=pin.build_id,validation_id=pin.validation_id,
        expected_database=pin.database_name,replay_vectors=vectors)
    reader._readiness=original._readiness
    vectors.clear()
    monkeypatch.setattr(query_embedding,'embed_query',lambda *args:(_ for _ in ()).throw(AssertionError('No live fallback allowed')))
    try:
        result=await reader.hybrid(pin,'synthetic',interpret_scientific_query('synthetic'),top_k=2)
        assert len(result.chunks)==2 and reader.query_embedding_mode=='frozen_replay_excludes_provider_latency'
        with pytest.raises(ContentRetrievalUnavailable):
            await reader.hybrid(pin,'absent',interpret_scientific_query('absent'),top_k=2)
    finally:await reader.close()


async def test_missing_actual_validation_marker_and_disabled_physical_guard_refused(candidate,db_session):
    _,pin,_,_=candidate
    with pytest.raises(service.CandidateUnavailable):
        await service.load_candidate(db_session,build_id=pin.build_id,validation_id=str(uuid4()),expected_database=pin.database_name)
    await db_session.execute(sa.text('DROP TABLE sclib_pgvector_rehearsal.source'))
    with pytest.raises(service.CandidateUnavailable,match='marker'):await service.current_read_pin(db_session,pin)
    await db_session.rollback()
    await db_session.execute(sa.text('ALTER TABLE '+pin.projection.table+' DISABLE TRIGGER retrieval_projection_write_v2'))
    with pytest.raises(service.CandidateUnavailable,match='physical'):await service.current_read_pin(db_session,pin)
    await db_session.rollback()
