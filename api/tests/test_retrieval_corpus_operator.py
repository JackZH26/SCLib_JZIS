"""Owned SQL orchestration and replay, no production attach or host-scale graph."""
from dataclasses import replace
import os
from uuid import UUID,uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

from config import get_settings
from models.db import get_session_factory
from services import retrieval_corpus_operator as operator,retrieval_backend
from tests.test_index_generations import db_session as db_session,staged
from tests.test_research_freeze import state

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Requires fresh owned vector services')]


@pytest_asyncio.fixture(loop_scope='function')
async def source(db_session,monkeypatch):
    generation,_=await staged(db_session,logical_index='owned-operator-'+uuid4().hex)
    database=await db_session.scalar(sa.text('SELECT current_database()'))
    monkeypatch.setattr(operator,'DATABASE',database)
    await db_session.execute(sa.text('CREATE SCHEMA IF NOT EXISTS sclib_pgvector_rehearsal'))
    await db_session.execute(sa.text('CREATE TABLE IF NOT EXISTS sclib_pgvector_rehearsal.source('
        'singleton boolean PRIMARY KEY CHECK(singleton),generation_id uuid NOT NULL,manifest text NOT NULL)'))
    await db_session.execute(sa.text('TRUNCATE sclib_pgvector_rehearsal.source'))
    await db_session.execute(sa.text('INSERT INTO sclib_pgvector_rehearsal.source VALUES(true,:id,:manifest)'),
        {'id':UUID(generation['generation_id']),'manifest':generation['manifest_sha256']})
    await db_session.commit()
    return operator.Request('inspect',generation['generation_id'],generation['manifest_sha256'],1,
        str(uuid4()),'sha256:'+'a'*64,'b'*40,validation_id=str(uuid4()))


async def frozen_v1(db):
    return await db.scalar(sa.text("SELECT jsonb_build_object('generations',"
        "(SELECT jsonb_agg(to_jsonb(g) ORDER BY id) FROM index_generations g),'members',"
        "(SELECT jsonb_agg(to_jsonb(m) ORDER BY generation_id,vector_id) FROM index_generation_members m),'pointer',"
        "(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY logical_index),'[]') FROM index_active_pointer p))"))


async def test_default_preview_does_no_work_for_every_phase(db_session,source):
    before=await state(db_session)
    for phase in operator.PHASES:
        result=await operator.execute(replace(source,phase=phase))
        assert result['status']=='preview_no_work' and result['activation_performed'] is False
    assert await state(db_session)==before


async def test_exact_source_content_projection_resume_and_validation_without_activation(db_session,source):
    before=await frozen_v1(db_session);await db_session.rollback()
    phases=['content','copy-content','seal-content','projection','copy-vectors']
    for phase in phases:
        result=await operator.execute(replace(source,phase=phase,apply=True))
        assert result['status']=='phase_completed' and result['quality_acceptance_created'] is False
    snapshot=await state(db_session);await db_session.rollback()
    for phase in phases:
        await operator.execute(replace(source,phase=phase,apply=True))
    assert await state(db_session)==snapshot
    async with get_session_factory()() as db:
        # Host-scale graph construction is separately budgeted and exercised
        # on the owned full clone. This tiny graph uses the existing64-MiB path.
        await retrieval_backend.build_small_projection_graph(db,build_id=source.build_id,dry_run=False)
        await db.commit()
    for phase in ('seal-projection','validate'):
        result=await operator.execute(replace(source,phase=phase,apply=True))
    assert result['result']['outcome']=='validated' and result['result']['mismatch_count']==0
    await db_session.rollback()
    assert await frozen_v1(db_session)==before
    assert await db_session.scalar(sa.text('SELECT count(*) FROM retrieval_activation_events_v2 WHERE build_id=:id'),
        {'id':UUID(source.build_id)})==0
    assert await db_session.scalar(sa.text('SELECT count(*) FROM retrieval_acceptances_v2 WHERE build_id=:id'),
        {'id':UUID(source.build_id)})==0


@pytest.mark.parametrize('fault',['database','marker','count','production_environment'])
async def test_foreign_or_changed_source_is_refused_before_metadata_writes(db_session,source,monkeypatch,fault):
    if fault=='database':monkeypatch.setattr(operator,'DATABASE','sclib')
    elif fault=='marker':source=replace(source,manifest_sha256='c'*64)
    elif fault=='count':source=replace(source,expected_members=2)
    else:monkeypatch.setattr(get_settings(),'environment','production')
    before=await state(db_session)
    with pytest.raises(operator.CorpusOperatorError):await operator.execute(replace(source,phase='content',apply=True))
    assert await state(db_session)==before


async def test_graph_requires_host_budget_and_changed_artifact_cannot_resume_copy(db_session,source):
    for phase in ['content','copy-content','seal-content','projection']:
        await operator.execute(replace(source,phase=phase,apply=True))
    before=await state(db_session)
    with pytest.raises(operator.CorpusOperatorError,match='host graph budget'):
        await operator.execute(replace(source,phase='graph',apply=True))
    with pytest.raises(operator.CorpusOperatorError,match='artifact binding'):
        await operator.execute(replace(source,phase='copy-vectors',apply=True,image_digest='sha256:'+'c'*64))
    assert await state(db_session)==before
