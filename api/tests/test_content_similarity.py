"""Real bounded v2 Similar over disposable SQL; fixtures are not quality gold."""
import os
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

from models.db import Chunk,Paper,get_engine,get_session_factory
from sqlalchemy.ext.asyncio import create_async_engine
from services import content_similarity as service,retrieval_members,index_retrieval
from services.pgvector_query import PgvectorQueries
from tests.test_content_retrieval import reader as reader
from tests.test_index_generations import db_session as db_session

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned PostgreSQL/vector services')]


async def papers(db,pin,ids):
    rows=await retrieval_members.hydrate(db,pin,ids)
    result=[(chunk.paper_id,index_retrieval.attribution(chunk).title) for chunk in rows.values()]
    await db.rollback()
    return result


async def test_real_native_legacy_similarity_keeps_frozen_bibliography_and_uses_no_provider(reader,db_session):
    instance,pin,ids,embedding_calls=reader
    sources=await papers(db_session,pin,ids)
    assert len({paper for paper,_ in sources})==2
    await db_session.execute(sa.update(Paper).where(Paper.id==sources[1][0]).values(title='Changed live title'))
    await db_session.commit()
    outcome=await instance.similar(pin,sources[0][0],top_k=50)
    assert outcome.pin==pin and outcome.source_paper_id==sources[0][0]
    assert [(row.paper_id,row.title) for row in outcome.results]==[sources[1]]
    assert 0<=outcome.results[0].similarity<=1 and embedding_calls==[]


@pytest.mark.parametrize('field,value',[('paper_id',''),('paper_id',None),('top_k',True),('top_k',0),('top_k',51)])
async def test_closed_request_is_checked_before_ann(reader,monkeypatch,field,value):
    instance,pin,_,_=reader
    spy=AsyncMock(side_effect=AssertionError('Invalid Similar input must not execute ANN'))
    monkeypatch.setattr(PgvectorQueries,'query_many',spy)
    args={'paper_id':'source','top_k':10};args[field]=value
    with pytest.raises(service.ContentSimilarityUnavailable):await instance.similar(pin,**args)
    spy.assert_not_awaited()


async def test_current_retracted_target_is_omitted_and_retracted_source_starts_no_ann(reader,db_session,monkeypatch):
    instance,pin,ids,_=reader;sources=await papers(db_session,pin,ids)
    await db_session.execute(sa.update(Paper).where(Paper.id==sources[1][0]).values(status='retracted'));await db_session.commit()
    assert (await instance.similar(pin,sources[0][0])).results==()
    await db_session.execute(sa.update(Paper).where(Paper.id==sources[0][0]).values(status='retracted'));await db_session.commit()
    spy=AsyncMock(side_effect=AssertionError('No eligible source must start no ANN'))
    monkeypatch.setattr(PgvectorQueries,'query_many',spy)
    assert (await instance.similar(pin,sources[0][0])).results==()
    spy.assert_not_awaited()


async def test_governance_change_after_selection_is_caught_in_new_snapshot(reader,db_session,monkeypatch):
    instance,pin,ids,_=reader;sources=await papers(db_session,pin,ids)
    original=service.capture;calls=0
    async def changed(db,backend,chunks):
        nonlocal calls
        selected=await original(db,backend,chunks);calls+=1
        if calls==2:
            async with get_session_factory()() as fresh:
                await fresh.execute(sa.update(Paper).where(Paper.id==sources[1][0]).values(status='retracted'))
                await fresh.commit()
        return selected
    monkeypatch.setattr(service,'capture',changed)
    with pytest.raises(service.ContentSimilarityUnavailable):await instance.similar(pin,sources[0][0])
    assert calls==2


@pytest.mark.parametrize('fault',['nan','duplicate','wrong_hash','missing_batch','unknown_id'])
async def test_bad_ann_inventory_cannot_become_partial_similarity(reader,db_session,monkeypatch,fault):
    instance,pin,ids,_=reader;sources=await papers(db_session,pin,ids);original=PgvectorQueries.query_many
    async def broken(self,*args,**kwargs):
        result=await original(self,*args,**kwargs)
        if fault=='missing_batch':return ()
        batch=result[0];hit=batch.neighbors[0]
        if fault=='nan':hit=replace(hit,distance=float('nan'))
        elif fault=='wrong_hash':hit=replace(hit,content_sha256='0'*64)
        elif fault=='unknown_id':hit=replace(hit,vector_id='rv2_'+'0'*64)
        neighbors=(hit,hit) if fault=='duplicate' else (hit,)
        return (replace(batch,neighbors=neighbors),)
    monkeypatch.setattr(PgvectorQueries,'query_many',broken)
    with pytest.raises(service.ContentSimilarityUnavailable):await instance.similar(pin,sources[0][0])


async def test_explicit_preparation_cannot_be_skipped(reader,db_session):
    instance,pin,ids,_=reader;sources=await papers(db_session,pin,ids)
    instance._readiness._prepared=None
    with pytest.raises(service.ContentSimilarityUnavailable):await instance.similar(pin,sources[0][0])


@pytest_asyncio.fixture(loop_scope='function')
async def many_sources(db_session,tmp_path,monkeypatch):
    from tests import test_retrieval_activation,test_embedding_receipts
    from tests.test_index_generations import resource
    from tests.test_retrieval_members import active_content
    from services import embedding_receipts,index_generations,query_embedding
    from services.content_retrieval import ContentRetriever
    original_seed=test_embedding_receipts.seed;source_paper=None;seed_count=0
    async def shared_seed(db):
        nonlocal source_paper,seed_count
        chunk,candidate=await original_seed(db)
        paper=await db.scalar(sa.select(Chunk.paper_id).where(Chunk.id==chunk))
        if source_paper is None:source_paper=paper
        elif seed_count<20:
            # Reassign only the new synthetic row before its evidence/receipt
            # is created. Retained input rows are never edited.
            await db.execute(sa.update(Chunk).where(Chunk.id==chunk).values(paper_id=source_paper))
        seed_count+=1
        return chunk,candidate
    monkeypatch.setattr(test_embedding_receipts,'seed',shared_seed)
    async def staged(db,**kwargs):
        items=[]
        for _ in range(44):
            chunk,vector,receipt,_=await test_embedding_receipts.prepared(db)
            completed=await embedding_receipts.append_embedding_receipt(db,chunk_id=chunk,vector=vector,receipt=receipt,dry_run=False)
            items.append({'chunk_id':chunk,'receipt_id':completed['receipt_id'],'vector':vector,'parser_version':'synthetic/1'})
        generation=await index_generations.stage_generation(db,generation_id=uuid4(),items=items,resource=resource(),
            logical_index=kwargs['logical_index'],dry_run=False)
        return generation,items
    monkeypatch.setattr(test_retrieval_activation,'staged',staged)
    pin,ids,_=await active_content(db_session,tmp_path);await db_session.commit()
    def forbidden(*args,**kwargs):raise AssertionError('Similar must use stored document vectors, no embedding RPC')
    monkeypatch.setattr(query_embedding,'embed_query',forbidden)
    engine=create_async_engine(get_engine().url,pool_size=4,max_overflow=0,pool_timeout=.5)
    instance=ContentRetriever(get_session_factory(),PgvectorQueries(engine));await instance.prepare(pin)
    try:yield instance,pin,source_paper
    finally:await instance.close();await engine.dispose()


async def test_twenty_real_source_vectors_share_one_batch_and_all_winners_get_fresh_checks(many_sources,monkeypatch):
    instance,pin,source=many_sources
    original=PgvectorQueries.query_many;query_calls=[];captures=[];checks=[]
    async def query(self,projection,vectors,**kwargs):
        query_calls.append((len(vectors),kwargs['top_k'],len(kwargs['excluded_revisions'])))
        return await original(self,projection,vectors,**kwargs)
    capture=service.capture
    async def selected(db,backend,chunks):
        captures.append(len(chunks));return await capture(db,backend,chunks)
    current=service.retrieval_currentness._check_snapshot
    async def checked(db,pins,resolver,**kwargs):
        checks.extend(value.chunk_id for value in pins)
        return await current(db,pins,resolver,**kwargs)
    monkeypatch.setattr(PgvectorQueries,'query_many',query)
    monkeypatch.setattr(service,'capture',selected)
    monkeypatch.setattr(service.retrieval_currentness,'_check_snapshot',checked)
    outcome=await instance.similar(pin,source,top_k=50)
    assert query_calls==[(20,50,20)]
    assert captures==[20,20,5] and len(outcome.results)==25
    assert len(checks)==len(set(checks))==45 and all(row.paper_id!=source for row in outcome.results)


async def test_oversized_complete_target_cohort_uses_bounded_pages_without_changing_results(many_sources,monkeypatch):
    instance,pin,source=many_sources
    expected=await instance.similar(pin,source,top_k=50)
    async with get_session_factory()() as db:
        rows=(await db.execute(sa.text(
            "SELECT reference->>'paper_id',octet_length(reference::text)+octet_length(origin::text)+length(vector_hex)/2 AS bytes "
            "FROM ("+retrieval_members._source_sql().replace('m.vector_id IN :ids','true')+") sizes"),
            {'content':pin.content_id})).all()
    source_bytes=sum(size for paper,size in rows if paper==source)
    target_sizes=sorted((size for paper,size in rows if paper!=source),reverse=True)
    limit=max(source_bytes,sum(target_sizes[:20]))
    assert sum(target_sizes)>limit
    monkeypatch.setattr(retrieval_members,'MAX_BYTES',limit)
    observed=[];original=retrieval_members.hydrate
    async def bounded(db,backend,identifiers):
        try:return await original(db,backend,identifiers)
        except retrieval_members.RetrievalMemberBudgetExceeded:
            observed.append(len(identifiers));raise
    monkeypatch.setattr(retrieval_members,'hydrate',bounded)
    assert await instance.similar(pin,source,top_k=50)==expected
    assert observed==[25]
