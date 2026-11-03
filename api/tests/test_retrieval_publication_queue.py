"""Actual fenced queue transactions on disposable synthetic SQL only."""
import asyncio,hashlib,os
from uuid import UUID,uuid4
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from models.db import get_session_factory,Chunk
from services import retrieval_publication_queue as service,retrieval_content,retrieval_activation
from services.embedding_receipts import append_embedding_receipt
from services.rag_evidence import register_chunk_evidence
from tests.test_embedding_receipts import completion
from tests.test_index_generations import db_session as db_session
from tests.test_research_freeze import state
from tests.test_retrieval_activation import prepared_build,accepted,activation
from tests.test_retrieval_native import native_inputs

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned PostgreSQL/vector services')]


async def queued(db,tmp_path):
    base=await prepared_build(db)
    arguments,items,chunk=await native_inputs(db,tmp_path)
    result=await service.capture_and_enqueue(db,logical_index=base['logical_index'],input_arguments=arguments,items=items,dry_run=False)
    return base,arguments,items,chunk,result


async def claim(db,result,**values):
    return await service.claim_job(db,job_id=result['job']['job_id'],claim_id=str(uuid4()),worker_id='synthetic-worker',dry_run=False,**values)


async def test_atomic_capture_enqueue_preview_replay_and_outer_rollback(db_session,tmp_path):
    base=await prepared_build(db_session);arguments,items,chunk=await native_inputs(db_session,tmp_path)
    before=await state(db_session)
    dry=await service.capture_and_enqueue(db_session,logical_index=base['logical_index'],input_arguments=arguments,items=items)
    assert dry['committed'] is False and await state(db_session)==before
    result=await service.capture_and_enqueue(db_session,logical_index=base['logical_index'],input_arguments=arguments,items=items,dry_run=False)
    written=await state(db_session)
    assert (await service.capture_and_enqueue(db_session,logical_index=base['logical_index'],input_arguments=arguments,items=items,dry_run=False))==result
    assert await state(db_session)==written
    jobs=await service.pending_jobs(db_session,logical_index=base['logical_index'])
    assert [str(row['id']) for row in jobs]==[result['job']['job_id']]
    await db_session.rollback()
    assert await db_session.scalar(sa.select(Chunk.id).where(Chunk.id==chunk)) is None


async def test_bounded_lease_retry_replay_and_fenced_stale_claim(db_session,tmp_path):
    base,args,items,chunk,result=await queued(db_session,tmp_path)
    first=await claim(db_session,result)
    assert first['currently_usable'] and first['attempt_number']==1
    before=await state(db_session)
    replay=await service.claim_job(db_session,job_id=first['job_id'],claim_id=first['claim_id'],worker_id='synthetic-worker',dry_run=False)
    assert replay==first and await state(db_session)==before
    with pytest.raises(DBAPIError,match='unexpired'):
        await claim(db_session,result)
    assert await service.pending_jobs(db_session,logical_index=base['logical_index'])==[]
    retry=await service.record_result(db_session,claim_id=first['claim_id'],outcome='retry',error_code='build_failed',dry_run=False)
    assert retry['outcome']=='retry'
    second=await claim(db_session,result);assert second['attempt_number']==2
    with pytest.raises(ValueError,match='conflict'):
        await service.record_result(db_session,claim_id=first['claim_id'],outcome='retry',error_code='operator_retry',dry_run=False)
    assert (await service.record_result(db_session,claim_id=first['claim_id'],outcome='retry',error_code='build_failed',dry_run=False))==retry


async def test_published_receipt_requires_actual_active_complete_native_content(db_session,tmp_path):
    base,args,items,chunk,result=await queued(db_session,tmp_path)
    leased=await claim(db_session,result)
    # A genuine synthetic legacy activation still does not publish the native paper.
    initial=await retrieval_activation.activate_backend(db_session,**activation(base,await accepted(db_session,base)),dry_run=False)
    with pytest.raises(DBAPIError,match='actual_active_complete'):
        await service.record_result(db_session,claim_id=leased['claim_id'],outcome='published',activation_event_id=initial['activation_event_id'],dry_run=False)
    plan=await retrieval_content.stage_native_content(db_session,base_content_id=base['content_id'],
        publication_ids=[result['publication']['publication_id']],dry_run=False)
    refs=await retrieval_content.source_reference_page(db_session,content_id=plan['content_id'])
    await retrieval_content.append_content_partition(db_session,content_id=plan['content_id'],partition_id=0,references=refs,dry_run=False)
    await retrieval_content.seal_content(db_session,content_id=plan['content_id'],dry_run=False)
    built=await prepared_build(db_session,content_id=plan['content_id'],logical_index=base['logical_index'])
    event=await retrieval_activation.activate_backend(db_session,**activation(built,await accepted(db_session,built),
        predecessor=initial['activation_event_id'],old=False),dry_run=False)
    finished=await service.record_result(db_session,claim_id=leased['claim_id'],outcome='published',activation_event_id=event['activation_event_id'],dry_run=False)
    assert finished['outcome']=='published' and await service.pending_jobs(db_session,logical_index=base['logical_index'])==[]
    with pytest.raises(DBAPIError,match='terminal'):await claim(db_session,result)


async def test_capture_enqueue_failure_leaves_no_partial_native_or_queue_history(db_session,tmp_path):
    await prepared_build(db_session);arguments,items,_=await native_inputs(db_session,tmp_path)
    before=await state(db_session)
    with pytest.raises(DBAPIError,match='complete_current_sealed'):
        await service.capture_and_enqueue(db_session,logical_index='unregistered-logical',input_arguments=arguments,items=items,dry_run=False)
    assert await state(db_session)==before


async def test_later_same_paper_revision_supersedes_old_work_without_activation(db_session,tmp_path):
    from models.db import Paper
    base,arguments,items,chunk,first=await queued(db_session,tmp_path)
    from services.rag_evidence import CURRENT_FACT_RENDERER_VERSION
    record=dict((await db_session.scalar(sa.select(Chunk.materials_mentioned).where(Chunk.id==chunk)))[0])
    record['tc_kelvin']='<120 K'
    text='Synthetic revised derived quantity Tc < 120 K.'
    await db_session.execute(sa.update(Paper).where(Paper.id==arguments['paper_id']).values(materials_extracted=[record]))
    await db_session.execute(sa.update(Chunk).where(Chunk.id==chunk).values(text=text,materials_mentioned=[record]))
    await register_chunk_evidence(db_session,chunk_id=chunk,candidate={'version':'rag-evidence/1.0.0','chunk_kind':'derived_fact',
        'parent_record':record,'extraction_version':'synthetic-extraction/2','rendering_version':CURRENT_FACT_RENDERER_VERSION},dry_run=False)
    vector,metadata=completion(text)
    receipt=await append_embedding_receipt(db_session,chunk_id=chunk,vector=vector,receipt=metadata,dry_run=False)
    path=tmp_path/'input-v2.json';path.write_text(text)
    revised={**arguments,'relative_path':path.name,'expected_bytes':path.stat().st_size,'provider_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    second=await service.capture_and_enqueue(db_session,logical_index=base['logical_index'],input_arguments=revised,
        items=[{'chunk_id':chunk,'receipt_id':receipt['receipt_id'],'vector':vector}],dry_run=False)
    assert first['job']['job_id']!=second['job']['job_id'] and second['job']['sequence_number']>first['job']['sequence_number']
    leased=await claim(db_session,first)
    finished=await service.record_result(db_session,claim_id=leased['claim_id'],outcome='superseded',successor_job_id=second['job']['job_id'],dry_run=False)
    assert finished['outcome']=='superseded'
    assert [str(row['id']) for row in await service.pending_jobs(db_session,logical_index=base['logical_index'])]==[second['job']['job_id']]
    assert await db_session.scalar(sa.text('SELECT count(*) FROM retrieval_activation_events_v2 WHERE logical_index=:logical'),{'logical':base['logical_index']})==0
    assert await db_session.scalar(sa.text('SELECT count(*) FROM retrieval_publications_v2 WHERE paper_id=:paper'),{'paper':arguments['paper_id']})==2


async def test_repeatable_read_lease_cannot_ignore_a_new_committed_claim(db_session,tmp_path):
    _,_,_,_,result=await queued(db_session,tmp_path);await db_session.commit()
    async with get_session_factory()() as stale:
        await stale.execute(sa.text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        await stale.execute(sa.text('SELECT epoch FROM retrieval_publication_job_fences_v2 WHERE job_id=CAST(:id AS uuid)'),{'id':result['job']['job_id']})
        winner=await claim(db_session,result);await db_session.commit()
        with pytest.raises(DBAPIError) as error:await claim(stale,result)
        assert getattr(error.value.orig,'sqlstate',None)=='40001'
        await stale.rollback()
    assert winner['attempt_number']==1


async def test_expired_claim_can_be_recovered_but_old_worker_cannot_finish(db_session,tmp_path):
    _,_,_,_,result=await queued(db_session,tmp_path)
    old=await claim(db_session,result,lease_seconds=30);await db_session.commit()
    await asyncio.sleep(30.1)
    new=await claim(db_session,result)
    assert new['attempt_number']==2
    with pytest.raises(DBAPIError,match='current_unexpired'):
        await service.record_result(db_session,claim_id=old['claim_id'],outcome='retry',error_code='operator_retry',dry_run=False)


@pytest.mark.parametrize('table,operation',[(t,op) for t in ('retrieval_publication_jobs_v2','retrieval_publication_claims_v2','retrieval_publication_results_v2')
    for op in ('update','delete','truncate')])
async def test_all_queue_history_is_retained(db_session,tmp_path,table,operation):
    _,_,_,_,result=await queued(db_session,tmp_path);leased=await claim(db_session,result)
    await service.record_result(db_session,claim_id=leased['claim_id'],outcome='retry',error_code='operator_retry',dry_run=False)
    sql={'update':'UPDATE '+table+' SET record_sha256=record_sha256','delete':'DELETE FROM '+table,'truncate':'TRUNCATE '+table+' CASCADE'}[operation]
    before=await state(db_session)
    with pytest.raises(DBAPIError,match='append_only'):
        async with db_session.begin_nested():await db_session.execute(sa.text(sql))
    assert await state(db_session)==before


async def test_queue_hash_is_identical_across_session_timezones(db_session,tmp_path):
    _,_,_,_,result=await queued(db_session,tmp_path);leased=await claim(db_session,result)
    for zone in ['UTC','Asia/Shanghai','Pacific/Honolulu']:
        await db_session.execute(sa.text("SELECT set_config('TimeZone',:zone,true)"),{'zone':zone})
        row=await service._existing(db_session,'retrieval_publication_claims_v2',{'id':UUID(leased['claim_id'])})
        assert row['record_sha256']==leased['record_sha256']


async def test_queue_roles_cannot_publish_or_cross_producer_worker_permissions(db_session,tmp_path):
    base,_,_,_,result=await queued(db_session,tmp_path)
    # These existing-source permissions belong to the source writer/build
    # identity. The queue migration grants only its four new relations.
    for role in ['sclib_retrieval_producer','sclib_retrieval_queue_worker']:
        rights=(await db_session.execute(sa.text("SELECT rolsuper,rolcreatedb,rolcreaterole,rolcanlogin FROM pg_roles WHERE rolname=:role"),{'role':role})).one()
        assert not any(rights)
    await db_session.execute(sa.text('SET LOCAL ROLE sclib_retrieval_producer'))
    with pytest.raises(DBAPIError):await claim(db_session,result)
    await db_session.execute(sa.text('RESET ROLE'))
    await db_session.execute(sa.text('SET LOCAL ROLE sclib_retrieval_queue_worker'))
    leased=await claim(db_session,result)
    await service.record_result(db_session,claim_id=leased['claim_id'],outcome='retry',error_code='operator_retry',dry_run=False)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("INSERT INTO retrieval_acceptances_v2(id,build_id,validation_id,evidence,attestation) VALUES(:id,:b,:v,'{}','queue-is-not-a-publisher')"),
                {'id':uuid4(),'b':UUID(base['build_id']),'v':UUID(base['validation_id'])})
    await db_session.execute(sa.text('RESET ROLE'))


async def test_retry_requires_a_closed_nonnull_error_category(db_session,tmp_path):
    _,_,_,_,result=await queued(db_session,tmp_path);leased=await claim(db_session,result)
    for code in [None,'unreviewed_category']:
        before=await state(db_session)
        with pytest.raises(DBAPIError):
            await service.record_result(db_session,claim_id=leased['claim_id'],outcome='retry',error_code=code,dry_run=False)
        assert await state(db_session)==before


async def test_database_ignores_producer_supplied_sequence_order(db_session,tmp_path):
    base,_,_,_,result=await queued(db_session,tmp_path)
    other=await prepared_build(db_session)
    identifier=uuid4()
    await db_session.execute(sa.text('INSERT INTO retrieval_publication_jobs_v2(id,sequence_number,logical_index,publication_id) '
        'OVERRIDING SYSTEM VALUE VALUES(:id,99999999,:logical,:publication)'),
        {'id':identifier,'logical':other['logical_index'],'publication':UUID(result['publication']['publication_id'])})
    row=await service._existing(db_session,'retrieval_publication_jobs_v2',{'id':identifier})
    assert result['job']['sequence_number']<row['sequence_number']<99999999


async def test_pending_claims_skip_another_workers_short_fence_lock(db_session,tmp_path):
    base,_,_,_,first=await queued(db_session,tmp_path)
    second_dir=tmp_path/'second';second_dir.mkdir()
    arguments,items,_=await native_inputs(db_session,second_dir)
    second=await service.capture_and_enqueue(db_session,logical_index=base['logical_index'],input_arguments=arguments,items=items,dry_run=False)
    await db_session.commit()
    async with get_session_factory()() as worker:
        selected=await service.pending_jobs(db_session,logical_index=base['logical_index'],limit=1)
        other=await service.pending_jobs(worker,logical_index=base['logical_index'],limit=1)
        assert [str(row['id']) for row in selected]==[first['job']['job_id']]
        assert [str(row['id']) for row in other]==[second['job']['job_id']]
        await claim(worker,second);await worker.commit()
        await claim(db_session,first);await db_session.commit()
