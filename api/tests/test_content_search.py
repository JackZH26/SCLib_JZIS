"""V2 Search with actual owned SQL; public backend dispatch remains gated."""
import os

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import HTTPException

from config import get_settings
from models.db import Paper,get_session_factory
from models.search import SearchRequest
from routers.deps import Identity
from services import content_search as service
from services.content_retrieval import ContentRetriever
from tests.test_content_retrieval import reader as reader
from tests.test_index_generations import db_session as db_session

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned PostgreSQL/vector services')]


@pytest_asyncio.fixture(loop_scope='function')
async def searcher(reader,monkeypatch):
    instance,pin,ids,calls=reader
    monkeypatch.setattr(get_settings(),'retrieval_logical_index',pin.logical_index)
    return instance,pin,ids,calls


def guest():return Identity(user=None,guest_ip='127.0.0.1',guest_remaining=2)


async def test_actual_hybrid_search_preserves_both_origins_scope_and_quota(searcher):
    instance,pin,_,calls=searcher
    result=await service.search(instance,SearchRequest(query='synthetic',top_k=2),guest())
    assert result.total==len(result.results)==2 and result.retrieval_generation.content_id==pin.content_id
    assert result.retrieval_generation.version=='index-read/2.0.0'
    assert result.scientific_lookup.scope=='declared_content_derived_extractions'
    assert result.guest_remaining==result.remaining==2 and len(calls)==1
    assert all(row.title and row.evidence_provenance and row.matched_chunk for row in result.results)


async def test_actual_exact_numeric_results_use_content_bindings_without_embedding(searcher):
    instance,pin,_,calls=searcher
    result=await service.search(instance,SearchRequest(query='What is the Tc of MgB2?',top_k=2),guest())
    assert result.scientific_lookup.status=='completed' and result.total==0 and not result.results
    assert result.scientific_results and all(row.binding.content_id==pin.content_id for row in result.scientific_results)
    assert {row.binding.origin_kind for row in result.scientific_results}=={'legacy_v1','native_v2'}
    assert all(row.binding.version=='scientific-result-binding/2.0.0' for row in result.scientific_results)
    assert calls==[]


async def test_clarification_keeps_actual_content_identity_and_starts_no_provider(searcher):
    instance,pin,_,calls=searcher
    result=await service.search(instance,SearchRequest(query='Tc >'),guest())
    assert result.scientific_lookup.status=='clarification_required'
    assert result.retrieval_generation.build_id==pin.build_id and calls==[]


async def test_governance_is_reloaded_after_hybrid_before_any_excerpt_is_presented(searcher,monkeypatch):
    instance,pin,_,_=searcher;original=ContentRetriever.hybrid;changed=[]
    async def hybrid(self,*args,**kwargs):
        result=await original(self,*args,**kwargs)
        paper_id=next(iter(result.chunks.values())).paper_id;changed.append(paper_id)
        async with get_session_factory()() as db:
            await db.execute(sa.update(Paper).where(Paper.id==paper_id).values(status='retracted'));await db.commit()
        return result
    monkeypatch.setattr(ContentRetriever,'hybrid',hybrid)
    result=await service.search(instance,SearchRequest(query='synthetic',top_k=2),guest())
    assert result.total==1 and all(row.paper_id not in changed for row in result.results)


async def test_year_filter_is_reapplied_to_retained_years(searcher):
    instance,_,_,_=searcher
    result=await service.search(instance,SearchRequest(query='synthetic',top_k=2,filters={'year_min':2020}),guest())
    assert all(type(row.year) is int and row.year>=2020 for row in result.results)
    assert result.retrieval_generation.version=='index-read/2.0.0'


async def test_absent_authority_never_falls_back_to_another_backend(searcher,monkeypatch):
    instance,_,_,calls=searcher
    monkeypatch.setattr(get_settings(),'retrieval_logical_index','absent')
    with pytest.raises(HTTPException) as error:await service.search(instance,SearchRequest(query='synthetic'),guest())
    assert error.value.status_code==503 and calls==[]
