"""Independent policy admission and shared-slot source/text budget checks."""
import os
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base, get_engine, get_session_factory
from models.retrieval_policy_v4 import POLICY, POLICY_SHA256, SUPPORTED_POLICIES
from services import retrieval_backend as backend, retrieval_activation as activation
from services.content_retrieval import ContentRetriever, ContentRetrievalUnavailable
from services.pgvector_query import PgvectorQueries, QueryBudget
from tests.test_index_generations import db_session as db_session
from tests.test_retrieval_content import legacy_content
from tests.test_retrieval_activation import prepared_build, accepted, activation as activate_args
from tests.test_pgvector_query import projection, vector

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST') != '1',
    reason='Fresh owned pgvector runtime required')]


async def test_distinct_policies_replay_without_relabelling_or_prior_function_rewrite(db_session):
    _, content = await legacy_content(db_session)
    signatures = ['sclib_retrieval_backend_insert_v2', 'sclib_retrieval_policy_build_v3']
    async def functions():
        return [await db_session.scalar(sa.text('SELECT pg_get_functiondef(to_regprocedure(:name))'),
            {'name': 'public.'+name+'()'}) for name in signatures]
    before = await functions(); ids = []
    for number, version in enumerate(('v2', 'v3', 'v4')):
        args = {'build_id': str(uuid4()), 'content_id': content['content_id'], 'image_digest': 'sha256:'+'a'*64,
            'implementation_revision': 'b'*40, 'policy_version': version, 'dry_run': False}
        first = await backend.stage_build(db_session, **args)
        assert await backend.stage_build(db_session, **args) == first
        row = await backend._existing(db_session, 'retrieval_backend_builds_v2', {'id': UUID(first['build_id'])})
        assert (row['policy'], row['policy_artifact_sha256']) == SUPPORTED_POLICIES[number]
        ids.append(first['build_id'])
    with pytest.raises(backend.RetrievalBackendError, match='Immutable backend'):
        await backend.stage_build(db_session, build_id=ids[1], content_id=content['content_id'],
            image_digest='sha256:'+'a'*64, implementation_revision='b'*40, policy_version='v4', dry_run=False)
    assert await functions() == before


@pytest.mark.parametrize('version', ['v2', 'v3'])
async def test_public_reader_rejects_an_actual_prior_policy_build(db_session, version):
    prepared = await prepared_build(db_session, policy_version=version)
    await activation.activate_backend(db_session, **activate_args(prepared, await accepted(db_session, prepared)), dry_run=False)
    await db_session.commit()
    reader = ContentRetriever(get_session_factory(), PgvectorQueries(get_engine()))
    try:
        with pytest.raises(ContentRetrievalUnavailable):
            await reader.pin(logical_index=prepared['logical_index'])
    finally:
        await reader.close(); await get_engine().dispose()


async def test_unregistered_source_budget_cannot_enter_build_authority(db_session):
    _, content = await legacy_content(db_session)
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(DBAPIError, match='supported_runtime_policy'):
            await db_session.execute(Base.metadata.tables['retrieval_backend_builds_v2'].insert().values(
                id=uuid4(), content_id=UUID(content['content_id']), image_digest='sha256:'+'a'*64,
                implementation_revision='b'*40, policy={**POLICY, 'source_ef_search': 64}, policy_artifact_sha256=POLICY_SHA256))
        await savepoint.rollback()


async def test_text_and_complete_source_batch_use_distinct_local_budgets_in_one_pool(projection):
    engine, spec = projection
    observed = []
    def capture(conn, cursor, statement, parameters, context, many):
        if statement.startswith(('WITH candidates AS MATERIALIZED', 'WITH inputs AS MATERIALIZED')):
            values = conn.exec_driver_sql("SELECT current_setting('hnsw.ef_search'),current_setting('statement_timeout')").one()
            observed.append(tuple(values))
    sa.event.listen(engine.sync_engine, 'before_cursor_execute', capture)
    transport = PgvectorQueries(engine)
    try:
        text_result = await transport.query(spec, vector(), top_k=5)
        source_result = await transport.query_many(spec, [vector(), vector(.01)], top_k=5)
    finally:
        sa.event.remove(engine.sync_engine, 'before_cursor_execute', capture)
    assert len(text_result.neighbors) == 5 and all(len(r.neighbors) == 5 for r in source_result)
    assert observed == [('1000','2s'), ('256','2s')]
    assert transport.budget == QueryBudget()
    assert POLICY['source_ef_search'] == transport.budget.source_ef_search
    assert POLICY['source_candidate_pool'] == transport.budget.source_candidate_pool


async def test_year_predicates_keep_bound_values_and_omit_nullable_or_terms(projection):
    engine, spec = projection
    captured = []
    def capture(conn, cursor, statement, parameters, context, many):
        if 'FROM retrieval_projection.' in statement:
            captured.append(statement)
    sa.event.listen(engine.sync_engine, 'before_cursor_execute', capture)
    try:
        result = await PgvectorQueries(engine).query(spec, vector(), top_k=5, year_min=2026)
    finally:
        sa.event.remove(engine.sync_engine, 'before_cursor_execute', capture)
    assert result.exhaustive and len(result.neighbors) == 5
    assert captured and all('IS NULL OR' not in statement and 'ANY(' not in statement for statement in captured)
    assert any('year>=' in statement for statement in captured)
