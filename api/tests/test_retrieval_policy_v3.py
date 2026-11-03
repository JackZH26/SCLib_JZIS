"""Policy identities remain immutable; legacy control records stay readable."""
import os
from uuid import UUID,uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base,get_engine,get_session_factory
from models.retrieval_policy_v3 import POLICY,POLICY_SHA256,SUPPORTED_POLICIES
from services import retrieval_backend as backend,retrieval_activation as activation
from services.content_retrieval import ContentRetriever,ContentRetrievalUnavailable
from services.pgvector_query import PgvectorQueries,QueryBudget,PgvectorQueryError
from tests.test_index_generations import db_session as db_session
from tests.test_retrieval_content import legacy_content
from tests.test_retrieval_activation import prepared_build,accepted,activation as activate_args

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',
    reason='Fresh owned vector runtime required')]


async def test_old_and_new_builds_replay_without_relabelling_or_changing_old_function(db_session):
    _,content=await legacy_content(db_session)
    old_function=await db_session.scalar(sa.text("SELECT pg_get_functiondef('public.sclib_retrieval_backend_insert_v2()'::regprocedure)"))
    ids=[]
    for version in ('v2','v3'):
        args={'build_id':str(uuid4()),'content_id':content['content_id'],'image_digest':'sha256:'+'a'*64,
            'implementation_revision':'b'*40,'policy_version':version,'dry_run':False}
        first=await backend.stage_build(db_session,**args);assert await backend.stage_build(db_session,**args)==first
        ids.append(first['build_id'])
        expected,digest=SUPPORTED_POLICIES[0 if version=='v2' else 1]
        row=await backend._existing(db_session,'retrieval_backend_builds_v2',{'id':UUID(first['build_id'])})
        assert row['policy']==expected and row['policy_artifact_sha256']==digest
    with pytest.raises(backend.RetrievalBackendError,match='Immutable backend'):
        await backend.stage_build(db_session,build_id=ids[0],content_id=content['content_id'],image_digest='sha256:'+'a'*64,
            implementation_revision='b'*40,policy_version='v3',dry_run=False)
    assert await db_session.scalar(sa.text("SELECT pg_get_functiondef('public.sclib_retrieval_backend_insert_v2()'::regprocedure)"))==old_function


async def test_database_rejects_unregistered_policy_even_with_builder_insert_rights(db_session):
    _,content=await legacy_content(db_session)
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(DBAPIError,match='supported_runtime_policy'):
            await db_session.execute(Base.metadata.tables['retrieval_backend_builds_v2'].insert().values(id=uuid4(),
                content_id=UUID(content['content_id']),image_digest='sha256:'+'a'*64,implementation_revision='b'*40,
                policy={**POLICY,'year_exact_cohort_limit':200001},policy_artifact_sha256=POLICY_SHA256))
        await savepoint.rollback()


async def test_v3_public_runtime_rejects_an_actual_legacy_policy_authority(db_session):
    prepared=await prepared_build(db_session,policy_version='v2')
    await activation.activate_backend(db_session,**activate_args(prepared,await accepted(db_session,prepared)),dry_run=False)
    await db_session.commit()
    legacy=await activation.load_active_backend(db_session,logical_index=prepared['logical_index'])
    assert legacy.policy_artifact_sha256==SUPPORTED_POLICIES[0][1]
    engine=get_engine();reader=ContentRetriever(get_session_factory(),PgvectorQueries(engine))
    try:
        with pytest.raises(ContentRetrievalUnavailable):await reader.pin(logical_index=prepared['logical_index'])
    finally:await reader.close();await engine.dispose()


@pytest.mark.parametrize('limit',[True,0,200001])
async def test_year_exact_limit_cannot_exceed_the_frozen_safety_ceiling(limit):
    with pytest.raises(PgvectorQueryError):QueryBudget(year_exact_cohort_limit=limit)
