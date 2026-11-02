"""Actual native/legacy parent lookup; synthetic cases are not scientific gold."""
from copy import copy,deepcopy
from dataclasses import replace
import os
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import sqlalchemy as sa

from models.db import Chunk,Paper,get_session_factory
from models.index_read import retrieval_read_metadata
from models.search import SearchResponse
from models.scientific_lookup import ContentScientificResultBinding
from services import content_scientific_lookup as service,retrieval_members,retrieval_currentness,index_vector_adapter
from services.scientific_filters import ResultFilters
from services.scientific_query import interpret_scientific_query
from tests.test_index_generations import db_session as db_session
from tests.test_retrieval_members import active_content
from tests.test_research_freeze import state
from tests.test_scientific_query_http import record

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned vector services')]


@pytest_asyncio.fixture(loop_scope='function')
async def content(db_session,tmp_path,monkeypatch,request):
    from tests import test_embedding_receipts
    from tests.test_rag_evidence import seed
    options=getattr(request,'param',{})
    value=record(tc=options.get('tc','39 K'),pressure=options.get('pressure','ambient'),raw_extraction={
        'tc_kelvin':options.get('tc','39 K'),'source_context':'Synthetic full private context',
        'custom_payload':{'preserve':['all','raw','fields']}})
    async def selected_seed(db):
        identifier,candidate=await seed(db,record=value,text='Synthetic MgB2 superconductivity exact retained fixture. Tc 39 K.')
        if options.get('original'):
            candidate={'version':'rag-evidence/1.0.0','chunk_kind':'original_passage',
                'rendering_version':'sclib-section-chunker/2.0.0'}
        if options.get('extra'):
            await db.execute(sa.update(Chunk).where(Chunk.id==identifier).values(materials_mentioned=[value,options['extra']]))
        return identifier,candidate
    def forbidden(*args,**kwargs):raise AssertionError('Scientific lookup must not call a provider')
    monkeypatch.setattr(test_embedding_receipts,'seed',selected_seed)
    monkeypatch.setattr(index_vector_adapter,'query',forbidden)
    if options.get('original'):
        from tests import test_retrieval_content
        native_inputs=test_retrieval_content.native_inputs
        async def complete_synthetic_text(db,folder):
            import hashlib
            arguments,items,chunk=await native_inputs(db,folder)
            text=await db.scalar(sa.select(Chunk.text).where(Chunk.id==chunk))
            # One complete tiny synthetic input, never a claimed publisher file.
            path=folder/'complete-synthetic-text.txt';path.write_text(text)
            arguments.update(relative_path=path.name,source_scope='full_text',media_type='text/plain',
                expected_bytes=path.stat().st_size,provider_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            return arguments,items,chunk
        monkeypatch.setattr(test_retrieval_content,'native_inputs',complete_synthetic_text)
    pin,ids,_=await active_content(db_session,tmp_path)
    await db_session.commit()
    return pin,ids,value


def numerical():return interpret_scientific_query('What is the Tc of MgB2?')


async def test_exact_native_and_legacy_results_keep_origin_and_raw_parent(db_session,content):
    pin,ids,value=content
    before=await state(db_session)
    inputs=(await service.prepare_content_scientific_lookup(db_session,pin,numerical())).consume()
    assert len(inputs.parents)==len(inputs.outcome.results)==2
    assert {row.binding.origin_kind for row in inputs.outcome.results}=={'native_v2','legacy_v1'}
    for parent,result in zip(inputs.parents,inputs.outcome.results,strict=True):
        binding=result.binding
        assert type(binding) is ContentScientificResultBinding and binding.content_id==pin.content_id
        assert binding.build_id==pin.build_id and binding.activation_event_id==pin.activation_event_id
        assert binding.association_scope=='derived_extraction_not_original_support'
        assert parent.raw_record==value and parent.member['snapshot_json']['materials_mentioned'][parent.record_index]==value
        assert parent.selection_pin.has_evidence_pin and parent.selection_pin.grouping_sha256
        assert 'vector_bytes' not in parent.member and binding.parent_result_sha256
        assert result.result.tc.value==39
    response=SearchResponse(total=0,results=[],query_time_ms=1,retrieval_generation=retrieval_read_metadata(pin),
        scientific_query=numerical(),scientific_lookup=inputs.outcome.status,scientific_results=inputs.outcome.results)
    assert response.scientific_lookup.scope==service.SCOPE and response.scientific_lookup.scientific_acceptance is False
    assert await state(db_session)==before


async def test_preparation_keeps_caller_transaction_and_does_not_fresh_check(db_session,content,monkeypatch):
    pin,_,_=content
    await db_session.execute(sa.text('SELECT 1'));transaction=db_session.get_transaction()
    forbidden=AsyncMock(side_effect=AssertionError('Caller owns preparation transaction'))
    with monkeypatch.context() as patch:
        patch.setattr(db_session,'commit',forbidden);patch.setattr(db_session,'rollback',forbidden)
        patch.setattr(retrieval_currentness,'check_selected_sources',forbidden)
        inputs=(await service.prepare_content_scientific_lookup(db_session,pin,numerical())).consume()
    assert len(inputs.parents)==2 and db_session.get_transaction() is transaction
    forbidden.assert_not_called()


async def test_handle_is_one_shot_and_all_nested_outputs_are_detached(db_session,content):
    pin,_,value=content
    prepared=await service.prepare_content_scientific_lookup(db_session,pin,numerical())
    prepared.outcome.results.clear();prepared.parents[0].raw_record['raw_extraction']['custom_payload']['preserve'].clear()
    for copier in (copy,deepcopy):
        with pytest.raises(TypeError,match='single-consumption'):copier(prepared)
    inputs=prepared.consume()
    assert len(inputs.outcome.results)==2 and inputs.parents[0].raw_record==value
    inputs.parents[0].member['snapshot_json']['materials_mentioned'].clear()
    assert inputs.parents[0].raw_record==value and inputs.backend_pin==pin
    for method in (prepared.consume,lambda:prepared.parents,lambda:prepared.outcome):
        with pytest.raises(ValueError,match='already been consumed'):method()


@pytest.mark.parametrize('fault',['drop','raw','event','selection','origin'])
async def test_inconsistent_input_inventory_is_refused(db_session,content,fault):
    pin,_,_=content
    inputs=(await service.prepare_content_scientific_lookup(db_session,pin,numerical())).consume()
    parents=list(inputs.parents)
    if fault=='drop':parents.pop()
    elif fault=='raw':parents[0]=replace(parents[0],_raw_record_json='{"formula":"Nb"}')
    elif fault=='selection':parents[0]=replace(parents[0],selection_pin=replace(parents[0].selection_pin,generation_pin_sha256='0'*64))
    elif fault=='origin':
        member=parents[0].member;member['origin_record_sha256']='0'*64
        parents[0]=replace(parents[0],_member_json=service._json(member))
    else:
        from uuid import uuid4
        with pytest.raises(ValueError,match='binding mismatch'):
            replace(inputs,backend_pin=replace(pin,activation_event_id=str(uuid4())))
        return
    with pytest.raises(ValueError,match='one-to-one|binding mismatch'):replace(inputs,parents=tuple(parents))


async def test_completed_lookup_freshly_checks_retained_inputs_after_mutable_deletion(db_session,content):
    pin,ids,_=content
    chunks=await retrieval_members.hydrate(db_session,pin,ids)
    await db_session.execute(sa.delete(Chunk).where(Chunk.id.in_([row.member['chunk_key'] for row in chunks.values()])))
    await db_session.commit()
    outcome=await service.lookup_content_scientific_results(db_session,pin,numerical())
    assert outcome.status.status=='completed' and len(outcome.results)==2


async def test_hold_after_preparation_withholds_every_result(db_session,content,monkeypatch):
    pin,ids,_=content
    chunks=await retrieval_members.hydrate(db_session,pin,ids)
    selected_paper=chunks[ids[0]].paper_id
    await db_session.rollback()
    prepare=service.prepare_content_scientific_lookup
    async def held(*args,**kwargs):
        result=await prepare(*args,**kwargs)
        async with get_session_factory()() as writer:
            await writer.execute(sa.update(Paper).where(Paper.id==selected_paper).values(status='corrected'))
            await writer.commit()
        return result
    monkeypatch.setattr(service,'prepare_content_scientific_lookup',held)
    outcome=await service.lookup_content_scientific_results(db_session,pin,numerical())
    assert outcome.status.status=='unavailable' and outcome.results==[]


@pytest.mark.parametrize('content',[{'original':True}],indirect=True)
async def test_original_passages_cannot_invent_extraction_parents(db_session,content):
    pin,_,_=content
    outcome=await service.lookup_content_scientific_results(db_session,pin,numerical())
    assert outcome.status.status=='completed' and outcome.results==[]
    assert outcome.status.reason_codes==['declared_content_no_extraction_parents']


async def test_ui_keywords_pagination_and_unknown_years_remain_real_conditions(db_session,content):
    pin,_,_=content
    filters=ResultFilters(tc_min=30)
    first=(await service.prepare_content_scientific_lookup(db_session,pin,interpret_scientific_query('synthetic'),
        filters=filters,limit=1)).consume().outcome
    assert len(first.results)==1 and first.status.has_more
    absent=(await service.prepare_content_scientific_lookup(db_session,pin,interpret_scientific_query('unmatchedwordxyz'),
        filters=filters)).consume().outcome
    assert absent.results==[] and not absent.status.has_more
    unknown=(await service.prepare_content_scientific_lookup(db_session,pin,numerical(),year_min=1986)).consume().outcome
    assert unknown.results==[]


@pytest.mark.parametrize('content',[{'pressure':'50 GPa','extra':record(formula='Nb',pressure='ambient')}],indirect=True)
async def test_one_record_cannot_borrow_another_record_ambient_pressure(db_session,content):
    pin,_,_=content
    outcome=(await service.prepare_content_scientific_lookup(db_session,pin,numerical(),filters=ResultFilters(ambient_only=True))).consume().outcome
    assert outcome.results==[]


@pytest.mark.parametrize('content',[{'tc':'< 100 K'}],indirect=True)
async def test_censored_upper_bound_cannot_satisfy_positive_minimum(db_session,content):
    pin,_,_=content
    outcome=(await service.prepare_content_scientific_lookup(db_session,pin,numerical(),filters=ResultFilters(tc_min=50))).consume().outcome
    assert outcome.results==[]


async def test_stale_or_public_mapping_pin_and_oversized_records_fail_closed(db_session,content,monkeypatch):
    pin,_,_=content
    with pytest.raises(ValueError):await service.prepare_content_scientific_lookup(db_session,pin.metadata(),numerical())
    monkeypatch.setattr(service,'MAX_RECORDS',1)
    with pytest.raises(ValueError,match='Complete scientific record inventory'):
        await service.prepare_content_scientific_lookup(db_session,pin,numerical())
