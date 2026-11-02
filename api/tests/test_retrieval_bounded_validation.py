"""Bounded readback with an actual fault in the final retained member."""
import os
from uuid import UUID,uuid4

import pytest
import sqlalchemy as sa

from services import retrieval_backend as backend,retrieval_content as content,index_generations
from tests.test_index_generations import db_session as db_session,staged,resource

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned PostgreSQL/vector services')]


@pytest.mark.parametrize('fault',[None,'last_bytes','last_missing','extra'])
async def test_complete_inventory_and_final_member_are_checked(db_session,fault):
    _,first=await staged(db_session);_,second=await staged(db_session)
    generation=await index_generations.stage_generation(db_session,generation_id=uuid4(),items=first+second,
        resource=resource(),logical_index='bounded-'+uuid4().hex,dry_run=False)
    plan=await content.stage_legacy_content(db_session,generation_id=generation['generation_id'],dry_run=False)
    references=await content.source_reference_page(db_session,content_id=plan['content_id'])
    assert len(references)==2
    await content.append_content_partition(db_session,content_id=plan['content_id'],partition_id=0,
        references=references,dry_run=False)
    await content.seal_content(db_session,content_id=plan['content_id'],dry_run=False)
    build=str(uuid4())
    await backend.stage_build(db_session,build_id=build,content_id=plan['content_id'],
        image_digest='sha256:'+'a'*64,implementation_revision='b'*40,dry_run=False)
    await backend.create_projection(db_session,build_id=build,dry_run=False)
    await backend.copy_partition(db_session,build_id=build,partition_id=0,dry_run=False)
    await backend.build_small_projection_graph(db_session,build_id=build,dry_run=False)
    table='retrieval_projection.b_'+UUID(build).hex
    last=references[-1]['vector_id']
    if fault=='last_bytes':
        await db_session.execute(sa.text(f'UPDATE {table} SET embedding=array_fill(2::real,ARRAY[768])::vector WHERE vector_id=:id'),{'id':last})
    elif fault=='last_missing':await db_session.execute(sa.text(f'DELETE FROM {table} WHERE vector_id=:id'),{'id':last})
    elif fault=='extra':
        await db_session.execute(sa.text(f"INSERT INTO {table} SELECT 'orphan',paper_id,year,content_sha256,vector_sha256,chunk_revision_sha256,embedding FROM {table} LIMIT 1"))
    await backend.seal_projection(db_session,build_id=build,dry_run=False)
    settings=(await db_session.execute(sa.text("SELECT current_setting('work_mem'),current_setting('application_name')"))).one()
    receipt=await backend.validate_projection(db_session,build_id=build,validation_id=str(uuid4()),dry_run=False)
    assert receipt['outcome']==('validated' if fault is None else 'rejected')
    assert receipt['source_member_count']==2 and receipt['content_manifest_intact']
    assert receipt['mismatch_count']==int(fault=='last_bytes')
    assert receipt['missing_count']==int(fault=='last_missing')
    assert receipt['extra_count']==int(fault=='extra')
    assert (await db_session.execute(sa.text("SELECT current_setting('work_mem'),current_setting('application_name')"))).one()==settings
    trigger=await db_session.scalar(sa.text("SELECT tgfoid::regprocedure::text FROM pg_trigger WHERE tgrelid='retrieval_backend_validations_v2'::regclass AND tgname='retrieval_backend_v2_insert'"))
    assert trigger=='sclib_retrieval_backend_bounded_v3()'
