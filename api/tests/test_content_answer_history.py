"""Actual immutable SQL history, independent of current ANN and parsers."""
import json,os
from copy import deepcopy
from uuid import UUID,uuid4

import pytest
import sqlalchemy as sa

from models.db import Base,Paper
from models.answer_evidence import canonical
from models.content_answer_storage_v2 import TABLE,VERSION
from services import content_answer_evidence as capture,content_answer_history as history
from tests.test_content_answer_evidence import captured
from tests.test_content_scientific_lookup import content as content
from tests.test_index_generations import db_session as db_session

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned PostgreSQL/vector services')]


async def begin(db,readonly=False):
    await db.rollback()
    await db.execute(sa.text('SET TRANSACTION ISOLATION LEVEL '+('REPEATABLE READ READ ONLY' if readonly else 'SERIALIZABLE')))
    await db.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))


async def store(db,prepared,owner=None,change_fields=None):
    await begin(db);identifier=uuid4()
    if owner is None:
        owner=uuid4()
        await db.execute(Base.metadata.tables['users'].insert().values(id=owner,email=str(owner)+'@example.test',
            name='Synthetic content receipt owner',is_active=True,email_verified=True))
    fields=await history.receipt_fields(db,prepared)
    if change_fields:fields=change_fields(fields)
    request,response=prepared.document['request'],prepared.document['response']
    await db.execute(Base.metadata.tables['ask_history'].insert().values(id=identifier,user_id=owner,
        question=request['question'],answer=response['answer'],sources=response['sources'],tokens_used=response['tokens_used'],
        latency_ms=response['query_time_ms'],language=request['language'],content_evidence_receipt_version=VERSION))
    await db.execute(Base.metadata.tables[TABLE].insert().values(history_id=identifier,**fields))
    await db.commit();await begin(db,True)
    return dict((await db.execute(sa.select(Base.metadata.tables[TABLE]).where(
        Base.metadata.tables[TABLE].c.history_id==identifier))).mappings().one())


async def prepared(db,content):
    selected,response,_,_=await captured(db,content)
    return capture.finish_capture(selected,response)


async def test_real_native_legacy_receipt_replays_without_active_index_provider_or_new_parser(db_session,content,monkeypatch):
    saved=await store(db_session,await prepared(db_session,content))
    def forbidden(*args,**kwargs):raise AssertionError('History must use retained rows and saved bytes only')
    from services import retrieval_activation,scientific_query,index_vector_adapter
    monkeypatch.setattr(retrieval_activation,'load_active_backend',forbidden)
    monkeypatch.setattr(scientific_query,'interpret_scientific_query',forbidden)
    monkeypatch.setattr(index_vector_adapter,'query',forbidden)
    result=await history.verify_historical(db_session,saved)
    assert {item['origin_kind'] for item in result['bindings']['items']}=={'legacy_v1','native_v2'}
    assert result['response']==json.loads(saved['response_json']) and result['version']==VERSION
    assert all(item['parent_result_revision_id'] for item in result['bindings']['items'])


async def test_recalculated_caller_hash_cannot_replace_persisted_bytes(db_session,content):
    saved=await store(db_session,await prepared(db_session,content))
    changed=deepcopy(saved);body=json.loads(changed['response_json']);body['answer']='Changed saved answer'
    changed['response_json']=canonical(body).decode()
    from services.answer_evidence import _hash
    changed['response_sha256']=_hash(changed['response_json'])
    with pytest.raises(ValueError):await history.verify_historical(db_session,changed)
    assert (await history.verify_historical(db_session,saved))['response']['answer']!='Changed saved answer'


@pytest.mark.parametrize('mutation',['update','delete','truncate','parent_update'])
async def test_saved_receipt_and_parent_are_immutable_but_owner_deletion_cascades(db_session,content,mutation):
    saved=await store(db_session,await prepared(db_session,content));await begin(db_session)
    statements={'update':f"UPDATE {TABLE} SET response_json='{{}}' WHERE history_id=:id",
        'delete':f'DELETE FROM {TABLE} WHERE history_id=:id','truncate':f'TRUNCATE {TABLE}',
        'parent_update':'UPDATE ask_history SET answer=answer WHERE id=:id'}
    with pytest.raises(sa.exc.DBAPIError):await db_session.execute(sa.text(statements[mutation]),{'id':saved['history_id']})
    await db_session.rollback()
    await db_session.execute(sa.text('DELETE FROM ask_history WHERE id=:id'),{'id':saved['history_id']});await db_session.commit()
    assert await db_session.scalar(sa.text(f'SELECT count(*) FROM {TABLE} WHERE history_id=:id'),{'id':saved['history_id']})==0


async def test_no_retrofit_and_deferred_complete_receipt_required(db_session,registered_user):
    owner,_=registered_user
    table=Base.metadata.tables['ask_history'];identifier=uuid4()
    await db_session.execute(table.insert().values(id=identifier,user_id=owner.id,question='Old unpinned question',
        answer='Old unpinned answer',sources=[],latency_ms=1,language='en'));await db_session.commit()
    with pytest.raises(sa.exc.DBAPIError):
        await db_session.execute(table.update().where(table.c.id==identifier).values(content_evidence_receipt_version=VERSION))
    await db_session.rollback()
    new=uuid4();await db_session.execute(table.insert().values(id=new,user_id=owner.id,question='New content question',
        answer='New content answer',sources=[],latency_ms=1,language='en',content_evidence_receipt_version=VERSION))
    with pytest.raises(sa.exc.DBAPIError):await db_session.commit()
    await db_session.rollback()
    assert await db_session.scalar(sa.select(table.c.content_evidence_receipt_version).where(table.c.id==identifier)) is None
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(table).where(table.c.id==new))==0


async def test_owner_http_history_list_detail_and_delete_preserve_explicit_v2(client,db_session,content,registered_user,tmp_path):
    user,token=registered_user
    saved=await store(db_session,await prepared(db_session,content),owner=user.id)
    await db_session.rollback()
    headers={'Authorization':'Bearer '+token};identifier=str(saved['history_id'])
    listing=await client.get('/v1/history',headers=headers)
    assert listing.status_code==200 and listing.headers['cache-control']=='private, no-store'
    entry=next(row for row in listing.json()['results'] if row['id']==identifier)
    assert entry['receipt']['status']=='recorded' and entry['receipt']['receipt_sha256']==saved['record_sha256']
    response=await client.get('/v1/history/'+identifier,headers=headers)
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    body=response.json();evidence=body['evidence']
    assert evidence['status']=='verified' and evidence['binding_scope']=='content_members'
    assert evidence['receipt']['version']==VERSION and evidence['currentness_revalidated'] is False
    assert evidence['scientific_acceptance'] is False and evidence['historical_integrity_verified'] is True
    assert body['entry']['answer']==evidence['receipt']['response']['answer']
    (tmp_path/'content-history-http.json').write_text(json.dumps(body,ensure_ascii=False,indent=2)+'\n')
    assert (await client.get('/v1/history/'+identifier)).status_code==401
    assert (await client.delete('/v1/history/'+identifier,headers=headers)).status_code==200
    assert (await client.get('/v1/history/'+identifier,headers=headers)).status_code==404


async def test_transactional_answer_writer_stores_v2_and_reports_real_commit(client,db_session,content,registered_user):
    from starlette.requests import Request
    from routers.ask import _persist_history
    user,token=registered_user;selected,response,_,request_body=await captured(db_session,content)
    request=Request({'type':'http','headers':[(b'authorization',('Bearer '+token).encode())],
        'client':('127.0.0.1',12345),'state':{}})
    saved=await _persist_history(db_session,request,user.id,request_body,response,selected)
    assert saved.history.status=='saved' and saved.history.receipt_sha256
    detail=await client.get('/v1/history/'+saved.history.history_id,headers={'Authorization':'Bearer '+token})
    assert detail.status_code==200 and detail.json()['evidence']['receipt']['version']==VERSION
    assert detail.json()['evidence']['receipt']['record_sha256']==saved.history.receipt_sha256


@pytest.mark.parametrize('content',[{'original':True}],indirect=True)
@pytest.mark.parametrize('origin',['legacy_v1','native_v2'])
async def test_original_citation_receipt_retains_frozen_attribution_and_exact_parent_scope(db_session,content,origin):
    from models.search import AskSource,AskRequest,AskResponse
    from models.evidence_packing import PackingCandidate
    from models.index_read import retrieval_read_metadata
    from models.scientific_lookup import ScientificLookupStatus
    from services import evidence_packing,retrieval_members,answer_evidence as old,index_retrieval
    from tests.test_retrieval_currentness_v2 import selected
    pin,_,_=content;pins,chunks=await selected(db_session,pin)
    chunk=next(row for row in chunks if row.member['origin_kind']==origin)
    selection=next(row for row in pins if row.chunk_id==chunk.id)
    evidence=(await retrieval_members.resolve_evidence(db_session,pin,[chunk]))[chunk.id]
    candidate=PackingCandidate(chunk_id=chunk.id,paper_id=chunk.paper_id,
        source_snapshot_sha256=chunk.member['source_snapshot_sha256'],content_sha256=chunk.member['content_sha256'],
        accepted_work_id=None,chunk_kind=evidence['chunk_kind'],role_hint='results')
    plan=evidence_packing.pack_evidence([candidate],cost=lambda ids:100+100*len(ids),byte_budget=4096,max_chunks=1)
    paper=index_retrieval.attribution(chunk)
    source=AskSource(index=1,paper_id=chunk.paper_id,arxiv_id=paper.arxiv_id,title=paper.title,
        authors_short=old.authors_short(paper.authors or []),year=paper.date_submitted.year if paper.date_submitted else None,
        section=chunk.section,snippet=old._snippet(chunk.text),evidence_provenance=evidence,packing_info=plan.selected[0])
    request=AskRequest(question='Explain the synthetic source',max_sources=1)
    response=AskResponse(answer='Synthetic context [1].',sources=[source],tokens_used=None,query_time_ms=1,
        evidence_packing=evidence_packing.public_summary(plan),retrieval_generation=retrieval_read_metadata(pin),
        scientific_lookup=ScientificLookupStatus(scope='declared_content_derived_extractions'))
    selected=capture.capture_inputs(request=request,backend_pin=pin,sources=(source,),chunks=(chunk,),selection_pins=(selection,))
    stored=await store(db_session,capture.finish_capture(selected,response));result=await history.verify_historical(db_session,stored)
    assert result['response']['sources'][0]['title']==paper.title
    assert result['bindings']['items'][0]['origin_kind']==origin
    assert result['bindings']['items'][0]['parent_result_revision_id'] is None


@pytest.mark.parametrize('fault',['reference','origin','extra','omitted','selected_pin'])
async def test_sql_writer_rejects_rehashed_forged_bindings(db_session,content,fault):
    def change(fields):
        from services.answer_evidence import _hash
        value=json.loads(fields['bindings_json']);item=value['items'][0]
        if fault=='reference':item['content_member_record_sha256']='0'*64
        elif fault=='origin':item['origin_record_sha256']='0'*64
        elif fault=='extra':item['invented_generation_id']=str(uuid4())
        elif fault=='omitted':value['items'].pop()
        else:item['selection_content_pin_sha256']='0'*64
        fields['bindings_json']=canonical(value).decode();fields['bindings_sha256']=_hash(fields['bindings_json'])
        return fields
    with pytest.raises(sa.exc.DBAPIError,match='content_answer'):
        await store(db_session,await prepared(db_session,content),change_fields=change)
    await db_session.rollback()
    assert await db_session.scalar(sa.text(f'SELECT count(*) FROM {TABLE} WHERE content_id=:id'),
        {'id':UUID(content[0].content_id)})==0
