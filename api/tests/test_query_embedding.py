"""Embedding transport needs no Matching Engine deployment; no real RPCs."""
from copy import deepcopy
from types import SimpleNamespace
import asyncio
import threading

import pytest

from models.index_generations_v1 import PROFILE
from services import query_embedding as service


@pytest.fixture
def provider(monkeypatch):
    calls=[]
    reply={'embeddings':[{'values':[1.0]+[0.0]*767,'statistics':{'truncated':False,'token_count':2}}]}
    def call(**kwargs):calls.append(kwargs);return reply
    monkeypatch.setattr(service,'get_settings',lambda:SimpleNamespace(embedding_model='text-embedding-005',
        embedding_output_dimensionality=768))
    monkeypatch.setattr(service,'embedding_client',lambda:SimpleNamespace(models=SimpleNamespace(embed_content=call)))
    return calls,reply


def test_independent_query_task_model_vector_and_no_truncation(provider):
    calls,_=provider
    assert service.embed_query(PROFILE,'MgB₂ superconductivity')==[1.0]+[0.0]*767
    assert len(calls)==1 and calls[0]['contents']==['MgB₂ superconductivity']
    assert calls[0]['model']=='text-embedding-005'
    config=calls[0]['config']
    assert config.task_type=='RETRIEVAL_QUERY' and config.output_dimensionality==768
    assert config.auto_truncate is False and config.http_options.timeout==5000
    assert config.http_options.retry_options.attempts==1


@pytest.mark.parametrize('query',['','x'*9000,None,True])
def test_invalid_local_query_is_refused_before_client(provider,query):
    with pytest.raises(service.QueryEmbeddingUnavailable):service.embed_query(PROFILE,query)
    assert provider[0]==[]


@pytest.mark.parametrize('field,value',[('model','text-embedding-004'),('document_task','RETRIEVAL_QUERY'),
    ('query_task','RETRIEVAL_DOCUMENT'),('output_dimensionality',768.0),('extra','unexpected')])
def test_incompatible_profile_is_refused_before_client(provider,field,value):
    profile={**PROFILE,field:value}
    with pytest.raises(service.QueryEmbeddingUnavailable):service.embed_query(profile,'synthetic')
    assert provider[0]==[]


@pytest.mark.parametrize('fault',['truncated','missing_stats','dimension','nonfinite','zero'])
def test_incomplete_or_malformed_provider_vector_is_not_accepted(provider,fault):
    _,reply=provider;row=reply['embeddings'][0]
    if fault=='truncated':row['statistics']['truncated']=True
    elif fault=='missing_stats':row.pop('statistics')
    elif fault=='dimension':row['values']=[1.0]
    elif fault=='nonfinite':row['values'][0]=float('nan')
    else:row['values']=[0.0]*768
    with pytest.raises(service.QueryEmbeddingUnavailable):service.embed_query(PROFILE,'synthetic')


@pytest.mark.parametrize('timeout',[True,0,-1,6,float('inf')])
def test_timeout_is_a_bounded_sdk_budget(provider,timeout):
    with pytest.raises(service.QueryEmbeddingUnavailable):service.embed_query(PROFILE,'synthetic',timeout_seconds=timeout)
    assert provider[0]==[]


def test_provider_error_is_sanitized(provider,monkeypatch):
    def client():raise RuntimeError('PRIVATE QUERY AND CREDENTIALS')
    monkeypatch.setattr(service,'embedding_client',client)
    with pytest.raises(service.QueryEmbeddingUnavailable) as error:service.embed_query(deepcopy(PROFILE),'private input')
    assert 'PRIVATE' not in str(error.value) and error.value.__cause__ is None


@pytest.mark.asyncio
async def test_cancelled_caller_does_not_release_actual_running_worker_capacity():
    workers=service.QueryEmbeddingWorkers(workers=1)
    started=threading.Event();release=threading.Event();later=threading.Event()
    def first():
        started.set()
        assert release.wait(2)
        return 'first'
    first_task=asyncio.create_task(workers.run(first))
    assert await asyncio.to_thread(started.wait,1)
    first_task.cancel()
    with pytest.raises(asyncio.CancelledError):await first_task
    second=asyncio.create_task(workers.run(lambda:later.set() or 'second'))
    try:
        await asyncio.sleep(.03)
        assert not later.is_set()
        release.set()
        assert await asyncio.wait_for(second,1)=='second'
    finally:
        release.set()
        await workers.close()


def test_uncached_client_remains_alive_during_model_call(provider,monkeypatch):
    state={'closed':False,'called':False}
    class Models:
        def embed_content(self,**kwargs):
            assert not state['closed'], 'SDK owner was collected before its request'
            state['called']=True
            return provider[1]
    class Client:
        def __init__(self):self.models=Models()
        def __del__(self):state['closed']=True
    monkeypatch.setattr(service,'embedding_client',Client)
    assert service.embed_query(PROFILE,'niobium superconductivity')==[1.0]+[0.0]*767
    assert state['called'] and state['closed']
