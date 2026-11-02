"""Actual v2 Ask orchestration on fresh owned SQL, no live model calls."""
import os

import pytest
import pytest_asyncio
from starlette.requests import Request

from config import get_settings
from models.search import AskRequest
from models.rag_input_budget import RagInputBudgetReport
from routers.deps import Identity
from routers.ask import _ask
from services import rag
from tests.test_content_retrieval import reader as reader
from tests.test_content_scientific_lookup import content as content
from tests.test_index_generations import db_session as db_session

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned PostgreSQL/vector services')]


@pytest_asyncio.fixture(loop_scope='function')
async def ask_reader(reader,monkeypatch):
    instance,pin,ids,calls=reader
    monkeypatch.setattr(get_settings(),'retrieval_logical_index',pin.logical_index)
    return instance,pin,ids,calls


def request(token=None):
    return Request({'type':'http','headers':[(b'authorization',('Bearer '+token).encode())] if token else [],
        'client':('127.0.0.1',12345),'state':{}})


def guest():return Identity(user=None,guest_ip='127.0.0.1',guest_remaining=2)


async def test_v2_clarification_and_numeric_lookup_use_no_embedding_or_generation(ask_reader,db_session,monkeypatch):
    instance,pin,_,calls=ask_reader
    def forbidden(*args,**kwargs):raise AssertionError('No provider generation for numeric or unresolved queries')
    monkeypatch.setattr(rag,'generate_answer',forbidden)
    response=await _ask(AskRequest(question='Tc >'),request(),guest(),db_session,reader=instance)
    assert response.scientific_lookup.status=='clarification_required' and response.retrieval_generation.build_id==pin.build_id
    response=await _ask(AskRequest(question='What is the Tc of MgB2?'),request(),guest(),db_session,reader=instance)
    assert response.scientific_lookup.status=='completed' and response.scientific_results
    assert {row.binding.origin_kind for row in response.scientific_results}=={'legacy_v1','native_v2'}
    assert response.retrieval_generation.version=='index-read/2.0.0' and response.tokens_used==0 and calls==[]


async def test_authenticated_numeric_ask_commits_v2_history_and_actual_owner_replay(ask_reader,client,db_session,registered_user):
    instance,_,_,_=ask_reader;user,token=registered_user
    identity=Identity(user=user,guest_ip=None,guest_remaining=None,user_remaining=42)
    response=await _ask(AskRequest(question='What is the Tc of MgB2?'),request(token),identity,db_session,reader=instance)
    assert response.history.status=='saved' and response.remaining==42
    stored=await client.get('/v1/history/'+response.history.history_id,headers={'Authorization':'Bearer '+token})
    assert stored.status_code==200 and stored.json()['evidence']['receipt']['version']=='ask-answer-evidence/2.0.0'
    assert stored.json()['evidence']['receipt']['response']['scientific_results']==[
        row.model_dump(mode='json') for row in response.scientific_results]


async def test_v2_context_reuses_actual_packing_fallback_and_final_currentness(ask_reader,db_session,monkeypatch):
    instance,pin,_,calls=ask_reader;generation=[]
    def generated(question,sources,**kwargs):
        generation.append(len(sources))
        return rag.extractive_fallback(sources,evidence_packing=kwargs['evidence_packing'],
            input_budget=RagInputBudgetReport(status='unavailable',generation_started=False,
                byte_limit=get_settings().gemini_input_byte_limit),tokens_used=None)
    monkeypatch.setattr(rag,'generate_answer',generated)
    response=await _ask(AskRequest(question='synthetic',max_sources=2),request(),guest(),db_session,reader=instance)
    assert response.retrieval_generation.content_id==pin.content_id and response.scientific_lookup.scope=='declared_content_derived_extractions'
    assert response.sources and generation==[len(response.sources)] and len(calls)==1
    assert all(row.evidence_provenance for row in response.sources)


async def test_v2_mixed_query_withholds_causal_synthesis_and_keeps_v2_report(ask_reader,db_session,monkeypatch):
    instance,pin,_,_=ask_reader
    def forbidden(*args,**kwargs):raise AssertionError('Mixed scientific retrieval cannot synthesize a causal explanation')
    monkeypatch.setattr(rag,'generate_answer',forbidden)
    response=await _ask(AskRequest(question='What is Tc of MgB2 at ambient pressure and why?'),request(),guest(),db_session,reader=instance)
    assert response.retrieval_generation.content_id==pin.content_id
    assert response.scientific_mixed.version=='scientific-mixed-evidence/2.0.0'
    assert response.scientific_mixed.status=='completed' and response.tokens_used==0
    assert response.answer_mode=='abstention' and response.scientific_mixed.scientific_acceptance is False


@pytest.mark.parametrize('content',[{'original':True,'distinct':True}],indirect=True)
async def test_native_and_legacy_originals_remain_context_without_inventing_numeric_parents(content,db_session,monkeypatch):
    import struct
    from services import content_retrieval,retrieval_members
    from services.content_runtime import managed_reader
    pin,ids,_=content
    members=await retrieval_members.load_members(db_session,pin,ids)
    assert {row['origin_kind'] for row in members}=={'legacy_v1','native_v2'}
    vector=list(struct.unpack('!768f',members[0]['vector_bytes']))
    await db_session.rollback()
    monkeypatch.setattr(get_settings(),'retrieval_logical_index',pin.logical_index)
    monkeypatch.setattr(content_retrieval.query_embedding,'embed_query',lambda *args:list(vector))
    def forbidden(*args,**kwargs):raise AssertionError('Original context cannot invent a numerical explanation')
    monkeypatch.setattr(rag,'generate_answer',forbidden)
    async with managed_reader() as instance:
        response=await _ask(AskRequest(question='What is Tc of MgB2 at ambient pressure and why?'),
            request(),guest(),db_session,reader=instance)
    assert response.scientific_results==[] and len(response.sources)==2
    assert response.scientific_mixed.version=='scientific-mixed-evidence/2.0.0'
    assert response.scientific_mixed.result_count==0 and response.scientific_mixed.source_count==2
    assert response.scientific_mixed.associations==[] and response.tokens_used==0
    assert {source.packing_info.chunk_id for source in response.sources}==set(ids)
    assert all(source.evidence_provenance['chunk_kind']=='original_passage' for source in response.sources)
