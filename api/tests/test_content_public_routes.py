"""Actual ASGI routes select one prepared backend, never config-only identity."""
import os

import pytest
import pytest_asyncio
import sqlalchemy as sa

from config import get_settings
from models.db import get_engine,get_session_factory
from services import content_runtime,retrieval_members,index_vector_adapter
from services.content_retrieval import ContentRetriever
from tests.test_content_ask import ask_reader as ask_reader
from tests.test_content_retrieval import reader as reader
from tests.test_index_generations import db_session as db_session
from tests.test_schema_lifecycle import schema_engine as schema_engine

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned PostgreSQL/vector services')]


@pytest_asyncio.fixture(loop_scope='function')
async def public_reader(ask_reader,monkeypatch):
    from main import app
    reader,pin,ids,calls=ask_reader
    monkeypatch.setattr(get_settings(),'retrieval_backend','pgvector')
    monkeypatch.setitem(app.state._state,'content_reader',reader)
    def forbidden(*args,**kwargs):raise AssertionError('Public v2 routes cannot use Google ANN')
    monkeypatch.setattr(index_vector_adapter,'query',forbidden)
    monkeypatch.setattr(index_vector_adapter,'query_members',forbidden)
    return reader,pin,ids,calls


async def test_real_search_ask_similar_and_history_share_the_actual_v2_identity(public_reader,client,db_session,registered_user):
    reader,pin,ids,calls=public_reader;user,token=registered_user
    headers={'Authorization':'Bearer '+token}
    members=await retrieval_members.load_members(db_session,pin,ids);await db_session.rollback()
    response=await client.post('/v1/search',headers=headers,json={'query':'synthetic','top_k':2})
    assert response.status_code==200,response.text
    assert len(response.json()['results'])==2
    response=await client.get('/v1/similar/'+members[0]['paper_id'],headers=headers)
    assert response.status_code==200,response.text
    assert len(response.json()['results'])==1
    assert response.json()['retrieval_generation']['activation_event_id']==pin.activation_event_id
    response=await client.post('/v1/ask',headers=headers,json={'question':'What is the Tc of MgB2?'})
    assert response.status_code==200,response.text
    body=response.json()
    assert body['retrieval_generation']['content_id']==pin.content_id
    assert body['history']['status']=='saved' and body['scientific_results']
    saved=await client.get('/v1/history/'+body['history']['history_id'],headers=headers)
    assert saved.status_code==200 and saved.json()['evidence']['receipt']['version']=='ask-answer-evidence/2.0.0'
    assert len(calls)==1


async def test_readiness_rechecks_actual_boot_and_projection_without_warming_on_request(public_reader,client):
    reader,_,_,_=public_reader
    ready=await client.get('/readyz')
    assert ready.status_code==200 and ready.json()['dependencies']['retrieval']['status']=='ok'
    reader._readiness._prepared=None
    ready=await client.get('/readyz')
    assert ready.status_code==503 and ready.json()['dependencies']['retrieval']['status']=='error'
    assert reader._readiness._prepared is None
    assert (await client.get('/v1/health')).status_code==200


async def test_pgvector_mode_without_initialized_reader_cannot_fall_back(public_reader,client,monkeypatch):
    from main import app
    monkeypatch.setitem(app.state._state,'content_reader',None)
    for path,body in [('/v1/search',{'query':'synthetic'}),('/v1/ask',{'question':'synthetic'})]:
        response=await client.post(path,json=body)
        assert response.status_code==503


async def test_managed_runtime_owns_reserved_pool_and_keeps_metadata_engine_open(ask_reader,monkeypatch):
    _,pin,_,_=ask_reader;source=get_engine()
    original=type(source).dispose;closed=[]
    async def dispose(self,*args,**kwargs):
        closed.append(self);await original(self,*args,**kwargs)
    monkeypatch.setattr(type(source),'dispose',dispose)
    async with content_runtime.managed_reader(source_engine=source,session_factory=get_session_factory()) as reader:
        assert reader._transport.engine is not source and reader._transport.engine.pool.size()==4
        assert await reader.pin(logical_index=pin.logical_index)==pin
        assert await reader._readiness.ready(pin)
    assert source not in closed and len(closed)==1


async def test_failed_startup_closes_owned_reader_without_admitting_requests(ask_reader,monkeypatch):
    monkeypatch.setattr(get_settings(),'retrieval_logical_index','missing')
    original=ContentRetriever.close;closed=[]
    async def close(self):closed.append(self);await original(self)
    monkeypatch.setattr(ContentRetriever,'close',close)
    with pytest.raises(ValueError):
        async with content_runtime.managed_reader():raise AssertionError('Absent authority cannot admit runtime')
    assert len(closed)==1


async def test_application_lifespan_prepares_before_background_start_and_clears_on_shutdown(ask_reader,schema_engine,monkeypatch):
    from contextlib import asynccontextmanager
    import main
    monkeypatch.setattr(get_settings(),'retrieval_backend','pgvector')
    seen=[]
    @asynccontextmanager
    async def background(app):
        assert type(app.state.content_reader) is ContentRetriever
        pin=await app.state.content_reader.pin(logical_index=get_settings().retrieval_logical_index)
        assert await app.state.content_reader._readiness.ready(pin)
        seen.append('start')
        try:yield
        finally:seen.append('stop')
    monkeypatch.setattr(main,'_application_lifespan',background)
    async with main.lifespan(main.app):assert seen==['start']
    assert seen==['start','stop'] and main.app.state.content_reader is None


async def test_google_lifespan_preserves_existing_path_without_creating_ann_pool(ask_reader,monkeypatch):
    from contextlib import asynccontextmanager
    import main
    monkeypatch.setattr(get_settings(),'retrieval_backend','google')
    def forbidden(*args,**kwargs):raise AssertionError('Google mode must retain its existing startup path')
    @asynccontextmanager
    async def background(app):
        assert app.state.content_reader is None
        yield
    monkeypatch.setattr(content_runtime,'managed_reader',forbidden)
    monkeypatch.setattr(main,'_application_lifespan',background)
    async with main.lifespan(main.app):assert main.app.state.content_reader is None
