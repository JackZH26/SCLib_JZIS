"""Actual navigation/publication SQL in fresh owned vector services only."""
import os
from uuid import UUID,uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base,Chunk,Paper
from models.index_generations_v1 import PROFILE
from models.retrieval_navigation_v2 import TABLE
from services import retrieval_navigation as service
from services import retrieval_members, retrieval_content, retrieval_native, retrieval_activation
from services.index_generations import activate_generation
from services.index_corpus import stage_partition,validate_corpus
from services.scientific_query import match_source_formulas
from tests.test_index_generations import db_session as db_session
from tests.test_retrieval_members import active_content
from tests.test_retrieval_native import native_inputs
from tests.test_retrieval_activation import prepared_build,accepted
from tests.test_research_freeze import state

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned vector runner')]


@pytest.fixture
def english_sources(monkeypatch):
    from tests import test_embedding_receipts as receipts,test_retained_legacy as retained
    from tests.test_rag_evidence import seed
    async def english_seed(db,**kwargs):
        return await seed(db,text='MgB₂ superconductivity reported in a synthetic retained fixture. Tc < 100 K.')
    monkeypatch.setattr(receipts,'seed',english_seed)
    monkeypatch.setattr(retained,'seed',english_seed)


async def test_native_and_small_legacy_keywords_formulas_and_unknown_years(db_session,tmp_path,english_sources):
    pin,ids,_=await active_content(db_session,tmp_path)
    hits=await service.lexical_search(db_session,pin,'superconductivity',limit=30)
    assert {hit.chunk_id for hit in hits}==set(ids)
    formula=await service.formula_search(db_session,pin,{'MgB2'},limit=30)
    assert [hit.chunk_id for hit in formula]==sorted(ids) and all(hit.score==1 for hit in formula)
    assert await service.lexical_search(db_session,pin,'absentwordxyz',limit=30)==[]
    assert await service.formula_search(db_session,pin,{'NbN'},limit=30)==[]
    # Unknown years do not become reported dates or silently pass a year filter.
    assert await service.lexical_search(db_session,pin,'superconductivity',limit=30,year_min=2000)==[]
    assert await service.formula_search(db_session,pin,{'MgB2'},limit=30,year_max=2026)==[]
    before=await retrieval_members.load_text_bindings(db_session,pin,ids)
    rows=await retrieval_members.load_members(db_session,pin,ids)
    await db_session.execute(sa.delete(Chunk).where(Chunk.id.in_([row['chunk_key'] for row in rows])))
    assert await retrieval_members.load_text_bindings(db_session,pin,ids)==before
    assert {hit.chunk_id for hit in await service.lexical_search(db_session,pin,'superconductivity',limit=30)}==set(ids)
    assert [hit.chunk_id for hit in await service.formula_search(db_session,pin,{'MgB2'},limit=30)]==sorted(ids)


async def test_native_navigation_replay_and_read_helpers_do_not_change_state_or_settings(db_session,tmp_path,english_sources):
    pin,ids,_=await active_content(db_session,tmp_path)
    rows=await retrieval_members.load_members(db_session,pin,ids)
    native=next(row for row in rows if row['origin_kind']=='native_v2')
    await db_session.execute(sa.text("SET LOCAL bytea_output='escape'"))
    before=await state(db_session)
    a=await service.ensure_native_navigation(db_session,native_revision_id=native['native_revision_id'],dry_run=False)
    b=await service.ensure_native_navigation(db_session,native_revision_id=native['native_revision_id'],dry_run=False)
    assert a==b and await state(db_session)==before
    assert await db_session.scalar(sa.text('SHOW bytea_output'))=='escape'
    assert await retrieval_members.load_text_bindings(db_session,pin,ids)
    assert await db_session.scalar(sa.text('SHOW bytea_output'))=='escape'


async def test_publication_cannot_seal_missing_navigation_or_a_preview(db_session,tmp_path,english_sources):
    args,items,_=await native_inputs(db_session,tmp_path)
    receipt=await retrieval_native.append_input_receipt(db_session,**args,dry_run=False)
    revisions=await retrieval_native.append_native_revisions(db_session,input_receipt_id=receipt['input_receipt_id'],items=items,dry_run=False)
    revision=UUID(revisions['revisions'][0]['revision_id']);pub=uuid4()
    await db_session.execute(Base.metadata.tables['retrieval_publications_v2'].insert().values(
        id=pub,paper_id=args['paper_id'],expected_member_count=1,profile=PROFILE))
    await db_session.execute(Base.metadata.tables['retrieval_publication_members_v2'].insert().values(
        publication_id=pub,native_revision_id=revision))
    for preview in (False,True):
        if preview:await service.ensure_native_navigation(db_session,native_revision_id=revision)
        async with db_session.begin_nested() as savepoint:
            with pytest.raises(DBAPIError,match='complete_native_navigation'):
                await db_session.execute(Base.metadata.tables['retrieval_publication_seals_v2'].insert().values(publication_id=pub))
            await savepoint.rollback()
    await service.ensure_native_navigation(db_session,native_revision_id=revision,dry_run=False)
    await db_session.execute(Base.metadata.tables['retrieval_publication_seals_v2'].insert().values(publication_id=pub))


@pytest.mark.parametrize('operation',['UPDATE','DELETE','TRUNCATE'])
async def test_navigation_is_immutable(db_session,tmp_path,operation):
    await active_content(db_session,tmp_path)
    statement=f"UPDATE {TABLE} SET terms=ARRAY['Nb']" if operation=='UPDATE' else f'{operation} '+('FROM ' if operation=='DELETE' else '')+TABLE
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(DBAPIError,match='navigation_immutable'):await db_session.execute(sa.text(statement))
        await savepoint.rollback()


async def test_live_retraction_filter_and_stale_content_pin(db_session,tmp_path,english_sources):
    pin,ids,_=await active_content(db_session,tmp_path)
    rows=await retrieval_members.load_members(db_session,pin,ids)
    native=next(row for row in rows if row['origin_kind']=='native_v2')
    await db_session.execute(sa.update(Paper).where(Paper.id==native['paper_id']).values(status='retracted'))
    assert native['vector_id'] not in {hit.chunk_id for hit in await service.lexical_search(db_session,pin,'superconductivity',limit=30)}
    assert native['vector_id'] in {hit.chunk_id for hit in await service.lexical_search(db_session,pin,'superconductivity',limit=30,exclude_retracted=False)}
    from tests.test_retrieval_activation import activation
    later=await prepared_build(db_session,content_id=pin.content_id,logical_index=pin.logical_index)
    await retrieval_activation.activate_backend(db_session,**activation(later,await accepted(db_session,later),
        predecessor=pin.activation_event_id,old=False),dry_run=False)
    with pytest.raises(ValueError):await service.lexical_search(db_session,pin,'superconductivity',limit=30)
    with pytest.raises(ValueError):await service.formula_search(db_session,pin,{'MgB2'},limit=30)


async def test_corpus_navigation_joins_the_actual_content_before_ranking(db_session,tmp_path,english_sources):
    from datetime import datetime,timezone
    from tests.test_index_corpus import setup_corpus,observe
    from services import index_corpus
    source,plans,items=await setup_corpus(db_session)
    start=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ');observations=[]
    for number,page in enumerate(items,1):
        await stage_partition(db_session,generation_id=source['generation_id'],partition_id=number,items=page)
        observations.append((await observe(db_session,source,number))['id'])
    validated=await validate_corpus(db_session,generation_id=source['generation_id'],observation_ids=observations,started_at=start)
    old=await activate_generation(db_session,generation_id=source['generation_id'],validation_id=validated['validation_id'],
        expected_event_id=None,idempotency_key=uuid4().hex,dry_run=False)
    content=await retrieval_content.stage_legacy_content(db_session,generation_id=source['generation_id'],dry_run=False)
    refs=await retrieval_content.source_reference_page(db_session,content_id=content['content_id'])
    await retrieval_content.append_content_partition(db_session,content_id=content['content_id'],partition_id=0,references=refs,dry_run=False)
    await retrieval_content.seal_content(db_session,content_id=content['content_id'],dry_run=False)
    build=await prepared_build(db_session,content_id=content['content_id'],logical_index='sclib-main')
    await retrieval_activation.activate_backend(db_session,event_id=str(uuid4()),build_id=build['build_id'],
        validation_id=build['validation_id'],acceptance_id=await accepted(db_session,build),expected_event_id=None,
        idempotency_key=uuid4().hex,expected_v1={key:old[key] for key in ('generation_id','activation_event_id','manifest_sha256')},dry_run=False)
    pin=await retrieval_activation.load_active_backend(db_session)
    found=await service.formula_search(db_session,pin,{'MgB2'},limit=30)
    assert {hit.chunk_id for hit in found}=={ref['vector_id'] for ref in refs}
    assert {hit.chunk_id for hit in await service.lexical_search(db_session,pin,'superconductivity',limit=30)}=={ref['vector_id'] for ref in refs}
    from tests.test_retrieval_content import publication
    from tests.test_retrieval_activation import activation
    _,_,pub=await publication(db_session,tmp_path)
    later=await retrieval_content.stage_native_content(db_session,base_content_id=pin.content_id,
        publication_ids=[pub['publication_id']],dry_run=False)
    refs=await retrieval_content.source_reference_page(db_session,content_id=later['content_id'])
    await retrieval_content.append_content_partition(db_session,content_id=later['content_id'],partition_id=0,references=refs,dry_run=False)
    await retrieval_content.seal_content(db_session,content_id=later['content_id'],dry_run=False)
    build=await prepared_build(db_session,content_id=later['content_id'],logical_index=pin.logical_index)
    await retrieval_activation.activate_backend(db_session,**activation(build,await accepted(db_session,build),
        predecessor=pin.activation_event_id,old=False),dry_run=False)
    current=await retrieval_activation.load_active_backend(db_session)
    assert len(refs)==3
    assert {hit.chunk_id for hit in await service.formula_search(db_session,current,{'MgB2'},limit=30)}=={ref['vector_id'] for ref in refs}
    assert {hit.chunk_id for hit in await service.lexical_search(db_session,current,'superconductivity',limit=30)}=={ref['vector_id'] for ref in refs}
    assert [hit.chunk_id for hit in await service.formula_search(db_session,current,{'MgB2'},limit=1)]==[min(ref['vector_id'] for ref in refs)]


async def test_untrusted_query_syntax_is_data_and_does_not_mutate_sources(db_session,tmp_path,english_sources):
    pin,_,_=await active_content(db_session,tmp_path)
    before=await state(db_session)
    assert await service.lexical_search(db_session,pin,"'; DROP TABLE papers; -- unmatchedxyz",limit=30)==[]
    assert await state(db_session)==before


async def test_old_validation_does_not_bypass_missing_navigation_at_activation(db_session,tmp_path,english_sources):
    from tests.test_retrieval_content import publication
    from tests.test_retrieval_activation import activation
    from services import retrieval_backend
    pin,_,_=await active_content(db_session)
    _,_,pub=await publication(db_session,tmp_path)
    later=await retrieval_content.stage_native_content(db_session,base_content_id=pin.content_id,
        publication_ids=[pub['publication_id']],dry_run=False)
    refs=await retrieval_content.source_reference_page(db_session,content_id=later['content_id'])
    await retrieval_content.append_content_partition(db_session,content_id=later['content_id'],partition_id=0,references=refs,dry_run=False)
    await retrieval_content.seal_content(db_session,content_id=later['content_id'],dry_run=False)
    build=await prepared_build(db_session,content_id=later['content_id'],logical_index=pin.logical_index)
    acceptance=await accepted(db_session,build)
    revision=next(row['native_revision_id'] for row in refs if row['origin_kind']=='native_v2')
    digest=await db_session.scalar(sa.text(f'SELECT record_sha256 FROM {TABLE} WHERE native_revision_id=:id'),{'id':UUID(str(revision))})
    # Simulate an inactive derived-index rebuild. Only this fresh owned table's
    # trigger is changed; immutable original input/evidence rows stay intact.
    await db_session.execute(sa.text(f'ALTER TABLE {TABLE} DISABLE TRIGGER nav_v2_immutable'))
    await db_session.execute(sa.text(f'DELETE FROM {TABLE} WHERE native_revision_id=:id'),{'id':UUID(str(revision))})
    await db_session.execute(sa.text(f'ALTER TABLE {TABLE} ENABLE TRIGGER nav_v2_immutable'))
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(DBAPIError,match='complete_native_navigation'):
            await retrieval_backend.validate_projection(db_session,build_id=build['build_id'],validation_id=str(uuid4()),dry_run=False)
        await savepoint.rollback()
    args=activation(build,acceptance,predecessor=pin.activation_event_id,old=False)
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(DBAPIError,match='complete_native_navigation'):
            await retrieval_activation.activate_backend(db_session,**args,dry_run=False)
        await savepoint.rollback()
    assert await retrieval_activation.load_active_backend(db_session,logical_index=pin.logical_index)==pin
    rebuilt=await service.ensure_native_navigation(db_session,native_revision_id=revision,dry_run=False)
    assert rebuilt['record_sha256']==digest
    await retrieval_activation.activate_backend(db_session,**args,dry_run=False)
