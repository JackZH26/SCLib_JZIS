"""Real transport tests in fresh owned services; no production admission claim."""
from __future__ import annotations

import math
import os
import time
import asyncio
import json
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

from models.db import get_engine
from services.pgvector_query import (
    PgvectorQueries,
    PgvectorQueryError,
    PgvectorUnavailable,
    ProjectionSpec,
    QueryBudget,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.environ.get("SCLIB_PGVECTOR_RUNTIME_TEST") != "1",
    reason="Requires the owned pgvector test runner",
)]


def vector(angle=0):
    return [math.cos(angle), math.sin(angle)] + [0.0] * 766


@pytest_asyncio.fixture(loop_scope="function")
async def projection():
    engine = get_engine()
    spec = ProjectionSpec(str(uuid4()), str(uuid4()), "a" * 64)
    async with engine.begin() as db:
        await db.execute(sa.text("CREATE SCHEMA IF NOT EXISTS retrieval_projection"))
        await db.execute(sa.text(f"CREATE TABLE {spec.table} (vector_id text PRIMARY KEY,paper_id text,"
                                 "year integer,content_sha256 text,vector_sha256 text,"
                                 "chunk_revision_sha256 text,embedding vector(768))"))
        await db.execute(sa.text(f"INSERT INTO {spec.table} VALUES "
                                 "(:id,:paper,:year,:content,:vector,:revision,CAST(:embedding AS vector(768)))"),
                         [{"id": f"v{i:03}", "paper": f"arxiv:test-{i}",
                           "year": 2026 if i < 12 else 2001, "content": f"{i+1000:064x}",
                           "vector": f"{i+2000:064x}", "revision": f"{i+3000:064x}",
                           "embedding": str(vector(i / 100))} for i in range(192)])
        await db.execute(sa.text(f"CREATE INDEX ON {spec.table} (year)"))
        await db.execute(sa.text(f"CREATE INDEX ON {spec.table} USING hnsw "
                                 "(embedding vector_cosine_ops) WITH (m=16,ef_construction=64)"))
        await db.execute(sa.text(f"ANALYZE {spec.table}"))
    try:
        yield engine, spec
    finally:
        async with engine.begin() as db:
            await db.execute(sa.text(f"DROP TABLE {spec.table}"))


async def test_unfiltered_hnsw_returns_bound_candidates(projection):
    engine, spec = projection
    result = await PgvectorQueries(engine).query(spec, vector(), top_k=20)
    assert result.projection == spec and result.strategy == "hnsw" and result.exhaustive is False
    assert len(result.neighbors) == 20
    assert [item.vector_id for item in result.neighbors] == [f"v{i:03}" for i in range(20)]
    assert result.neighbors[0].distance == pytest.approx(0)
    assert all(item.content_sha256 == f"{int(item.vector_id[1:])+1000:064x}" for item in result.neighbors)


async def test_rare_year_filter_is_exact_and_excludes_source_revisions(projection):
    engine, spec = projection
    result = await PgvectorQueries(engine).query(spec, vector(), top_k=20, year_min=2026,
                                               excluded_revisions=[f"{3001:064x}"])
    assert result.strategy == "exact_filtered" and result.exhaustive
    assert [item.vector_id for item in result.neighbors] == [f"v{i:03}" for i in range(12) if i != 1]
    assert all(item.chunk_revision_sha256 != f"{3001:064x}" for item in result.neighbors)


async def test_large_filtered_cohort_uses_graph_without_cross_year_results(projection):
    engine, spec = projection
    result = await PgvectorQueries(engine, QueryBudget(year_exact_cohort_limit=10)).query(
        spec, vector(), top_k=20, year_max=2001)
    assert result.strategy == "hnsw" and result.exhaustive is False
    assert [item.vector_id for item in result.neighbors] == [f"v{i:03}" for i in range(12, 32)]


async def test_real_empty_filtered_cohort_is_successful_exact_empty(projection):
    engine, spec = projection
    result = await PgvectorQueries(engine).query(spec, vector(), top_k=20, year_min=2027)
    assert result.strategy == "exact_filtered" and result.exhaustive and result.neighbors == ()


async def test_expanded_year_exact_path_scores_all_rows_without_ann_ordering(projection):
    engine,spec=projection
    async with engine.begin() as db:
        await db.execute(sa.text(f"INSERT INTO {spec.table} SELECT 'expanded_'||lpad(n::text,5,'0'),'synthetic-expanded',2026,"
            "repeat('a',64),repeat('b',64),lpad((n+10000)::text,64,'0'),CAST(:vector AS vector(768)) FROM generate_series(1,1200) n"),
            {'vector':str(vector())})
    captured=[]
    def capture(conn,cursor,statement,parameters,context,many):
        if 'ORDER BY (embedding <=>' in statement:captured.append((statement,parameters))
    sa.event.listen(engine.sync_engine,'before_cursor_execute',capture)
    try:result=await PgvectorQueries(engine).query(spec,vector(),top_k=20,year_min=2026)
    finally:sa.event.remove(engine.sync_engine,'before_cursor_execute',capture)
    assert result.exhaustive and result.strategy=='exact_filtered'
    assert [row.vector_id for row in result.neighbors]==[f'expanded_{i:05}' for i in range(1,21)]
    assert len(captured)==1
    async with engine.connect() as db:
        plan=(await db.exec_driver_sql('EXPLAIN (FORMAT JSON) '+captured[0][0],captured[0][1])).scalar_one()
        if isinstance(plan,str):plan=json.loads(plan)
        graph_names=set((await db.execute(sa.text('SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid '
            "JOIN pg_am a ON a.oid=c.relam WHERE i.indrelid=to_regclass(:name) AND a.amname='hnsw'"),{'name':spec.table})).scalars())
    names=[]
    def inspect(node):
        if 'Index Name' in node:names.append(node['Index Name'])
        for child in node.get('Plans',[]):inspect(child)
    inspect(plan[0]['Plan'])
    assert graph_names and not graph_names.intersection(names)


async def test_source_only_exclusions_keep_the_small_exact_count_budget(projection):
    engine,spec=projection
    result=await PgvectorQueries(engine,QueryBudget(exact_cohort_limit=10)).query(spec,vector(),top_k=20,
        excluded_revisions=[f'{3001:064x}'])
    assert result.strategy=='hnsw' and not result.exhaustive
    assert all(row.chunk_revision_sha256!=f'{3001:064x}' for row in result.neighbors)


async def test_equal_distance_ties_follow_canonical_ids_in_exact_and_graph_paths(projection):
    engine, spec = projection
    ids = ['a_0', 'A_0', 'a-0', 'a00', 'Z9']
    async with engine.begin() as db:
        await db.execute(sa.text(f'INSERT INTO {spec.table} VALUES '
            '(:id,:paper,1999,:content,:vector,:revision,CAST(:embedding AS vector(768)))'),
            [{'id': identifier, 'paper': 'synthetic-' + identifier, 'content': 'a' * 64,
              'vector': 'b' * 64, 'revision': f'{9000+i:064x}', 'embedding': str(vector())}
             for i, identifier in enumerate(ids)])
    exact = await PgvectorQueries(engine).query(spec, vector(), top_k=5, year_min=1999, year_max=1999)
    assert [row.vector_id for row in exact.neighbors] == sorted(ids)
    graph = await PgvectorQueries(engine).query(spec, vector(), top_k=6)
    assert [row.vector_id for row in graph.neighbors] == sorted([*ids, 'v000'])


async def test_local_settings_do_not_leak_to_next_transaction(projection):
    from sqlalchemy.ext.asyncio import create_async_engine

    engine, spec = projection
    # The application test engine can use NullPool. Pin one actual owned DB
    # connection so a reset check cannot pass merely by replacing the session.
    dedicated = create_async_engine(engine.url, pool_size=1, max_overflow=0)
    try:
        async with dedicated.connect() as db:
            await db.execute(sa.text("SELECT vector_dims(CAST(:v AS vector(768)))"), {"v": str(vector())})
            original_pid = await db.scalar(sa.text("SELECT pg_backend_pid()"))
            before = {key: await db.scalar(sa.text("SELECT current_setting(:key)"), {"key": key})
                      for key in ("statement_timeout", "work_mem", "transaction_read_only",
                                  "hnsw.iterative_scan", "hnsw.ef_search")}
        await PgvectorQueries(dedicated).query(spec, vector(), top_k=5)
        await PgvectorQueries(dedicated).query_many(spec, [vector(), vector(0.01)], top_k=5)
        async with dedicated.connect() as db:
            assert await db.scalar(sa.text("SELECT pg_backend_pid()")) == original_pid
            after = {key: await db.scalar(sa.text("SELECT current_setting(:key)"), {"key": key}) for key in before}
        assert before == after
    finally:
        await dedicated.dispose()


async def test_locked_projection_times_out_and_connection_recovers(projection):
    engine, spec = projection
    transport = PgvectorQueries(engine, QueryBudget(total_seconds=1.0, statement_ms=500))
    async with engine.begin() as locker:
        await locker.execute(sa.text(f"LOCK TABLE {spec.table} IN ACCESS EXCLUSIVE MODE"))
        started = time.monotonic()
        with pytest.raises(PgvectorUnavailable, match="unavailable"):
            await transport.query(spec, vector(), top_k=5)
        assert time.monotonic() - started < 2.0
    assert len((await transport.query(spec, vector(), top_k=5)).neighbors) == 5


async def test_queue_wait_shares_the_request_deadline_and_releases_permit(projection):
    engine, spec = projection
    transport = PgvectorQueries(engine, QueryBudget(concurrency=1, total_seconds=0.05, statement_ms=20))
    await transport._slots.acquire()
    try:
        with pytest.raises(PgvectorUnavailable):
            await transport.query(spec, vector(), top_k=5)
    finally:
        transport._slots.release()
    assert not transport._slots.locked()


async def test_malformed_stored_bindings_reject_the_whole_batch(projection):
    engine, spec = projection
    async with engine.begin() as db:
        await db.execute(sa.text(f"UPDATE {spec.table} SET content_sha256='invalid' WHERE vector_id='v000'"))
    with pytest.raises(PgvectorQueryError, match="incompatible"):
        await PgvectorQueries(engine).query(spec, vector(), top_k=5)


async def test_twenty_source_vectors_preserve_order_filters_and_exclusions(projection):
    engine, spec = projection
    transport = PgvectorQueries(engine, QueryBudget(concurrency=2))
    batches = await transport.query_many(spec, [vector(i / 100) for i in range(20)],
        top_k=5, year_max=2001, excluded_revisions=[f'{3012:064x}'])
    assert len(batches) == 20 and all(batch.projection == spec for batch in batches)
    assert all(batch.exhaustive and len(batch.neighbors) == 5 for batch in batches)
    assert all('v012' not in {item.vector_id for item in batch.neighbors} for batch in batches)
    assert batches[0].neighbors[0].vector_id == 'v013'
    assert batches[19].neighbors[0].vector_id == 'v019'


async def test_batch_queue_wait_has_one_deadline_and_leaves_no_waiters(projection):
    engine, spec = projection
    transport = PgvectorQueries(engine, QueryBudget(concurrency=1, total_seconds=0.1, statement_ms=50))
    await transport._slots.acquire()
    started = time.monotonic()
    try:
        with pytest.raises(PgvectorUnavailable, match='batch unavailable'):
            await transport.query_many(spec, [vector()] * 20, top_k=5)
        assert time.monotonic() - started < 0.8
    finally:
        transport._slots.release()
    # A cancelled batch must not consume the next request's only SQL permit.
    assert len((await transport.query(spec, vector(), top_k=5)).neighbors) == 5


async def test_locked_batch_cancels_statement_and_recovers_real_connections(projection):
    engine, spec = projection
    transport = PgvectorQueries(engine, QueryBudget(concurrency=2, total_seconds=0.4, statement_ms=300))
    async with engine.begin() as locker:
        await locker.execute(sa.text(f'LOCK TABLE {spec.table} IN ACCESS EXCLUSIVE MODE'))
        started = time.monotonic()
        with pytest.raises(PgvectorUnavailable, match='batch unavailable'):
            await transport.query_many(spec, [vector()] * 20, top_k=5)
        assert time.monotonic() - started < 1.5
    result = await transport.query_many(spec, [vector(), vector(0.01)], top_k=5)
    assert [batch.neighbors[0].vector_id for batch in result] == ['v000', 'v001']


async def test_caller_cancellation_does_not_leave_batch_sql_slots(projection):
    engine, spec = projection
    transport = PgvectorQueries(engine, QueryBudget(concurrency=1))
    await transport._slots.acquire()
    task = asyncio.create_task(transport.query_many(spec, [vector()] * 20, top_k=5))
    await asyncio.sleep(0)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        transport._slots.release()
    assert len((await transport.query(spec, vector(), top_k=5)).neighbors) == 5


@pytest.mark.parametrize('vectors', [[], [vector()] * 21, [vector(), [0.0] * 768]])
async def test_invalid_complete_source_inventory_is_rejected(projection, vectors):
    engine, spec = projection
    with pytest.raises(PgvectorQueryError):
        await PgvectorQueries(engine).query_many(spec, vectors, top_k=5)


async def test_missing_build_fails_without_exposing_sql_or_reusing_another_build(projection):
    engine, existing = projection
    missing = ProjectionSpec(str(uuid4()), existing.content_version_id, existing.manifest_sha256)
    with pytest.raises(PgvectorUnavailable) as error:
        await PgvectorQueries(engine).query(missing, vector(), top_k=5)
    assert missing.table not in str(error.value) and "SELECT" not in str(error.value)
    assert len((await PgvectorQueries(engine).query(existing, vector(), top_k=5)).neighbors) == 5


@pytest.mark.parametrize("values", [[0.0] * 768, [float("nan")] + [1.0] * 767, [1.0] * 767])
async def test_invalid_vectors_cannot_acquire_a_connection(values):
    class NoConnections:
        def connect(self):
            pytest.fail("Invalid query vectors must not acquire a connection")
    with pytest.raises(PgvectorQueryError):
        await PgvectorQueries(NoConnections()).query(
            ProjectionSpec(str(uuid4()), str(uuid4()), "b" * 64), values, top_k=5)


@pytest.mark.parametrize("arguments", [
    {"top_k": True}, {"top_k": 101}, {"top_k": 5, "year_min": 2026, "year_max": 1986},
    {"top_k": 5, "year_min": True}, {"top_k": 5, "excluded_revisions": ["x' OR true --"]},
])
async def test_invalid_requests_are_rejected_before_connection(arguments):
    class NoConnections:
        def connect(self):
            pytest.fail("Invalid requests must not acquire a database connection")
    with pytest.raises(PgvectorQueryError):
        await PgvectorQueries(NoConnections()).query(
            ProjectionSpec(str(uuid4()), str(uuid4()), "b" * 64), vector(), **arguments)


async def test_projection_does_not_accept_sql_object_names():
    with pytest.raises(PgvectorQueryError):
        ProjectionSpec("x; DROP TABLE papers", str(uuid4()), "a" * 64)
    with pytest.raises(PgvectorQueryError):
        ProjectionSpec("AAAAAAAA-aaaa-aaaa-aaaa-aaaaaaaaaaaa", str(uuid4()), "a" * 64)


@pytest.mark.parametrize("budget", [
    {"concurrency": True}, {"concurrency": 9}, {"statement_ms": 6000},
    {"total_seconds": float("inf")}, {"total_seconds": 1.0, "statement_ms": 2000},
    {"candidate_pool": True}, {"candidate_pool": 4097}, {"candidate_pool": 1000},
    {"source_ef_search": True}, {"source_ef_search": 1001},
    {"source_candidate_pool": 256}, {"source_candidate_pool": 4097},
])
async def test_unbounded_resource_settings_are_rejected(budget):
    with pytest.raises(PgvectorQueryError):
        QueryBudget(**budget)


async def test_unfiltered_twenty_source_batch_matches_full_exact_reference(projection):
    engine,spec=projection
    vectors=[vector(i/100) for i in range(20)]
    batches=await PgvectorQueries(engine).query_many(spec,vectors,top_k=5)
    async with engine.connect() as db:
        for query,batch in zip(vectors,batches,strict=True):
            exact=(await db.execute(sa.text(f'SELECT vector_id,embedding <=> CAST(:query AS vector(768)) AS distance FROM {spec.table} ORDER BY (embedding <=> CAST(:query AS vector(768)))+0,vector_id COLLATE "C" LIMIT 5'),{'query':str(query)})).all()
            assert [row.vector_id for row in batch.neighbors]==[row.vector_id for row in exact]
            assert [row.distance for row in batch.neighbors]==pytest.approx([row.distance for row in exact],abs=1e-6)


@pytest.mark.parametrize('source_batch',[False,True])
async def test_independent_engine_shares_global_sql_limit_and_recovers_after_queue_timeout(projection,source_batch):
    from sqlalchemy.ext.asyncio import create_async_engine
    from services.pgvector_query import _SQL_SLOT_KEYS
    engine,spec=projection
    separate=create_async_engine(engine.url,pool_size=4,max_overflow=0)
    transport=PgvectorQueries(separate,QueryBudget(total_seconds=.2,statement_ms=100))
    async def query():
        if source_batch:return await transport.query_many(spec,[vector()],top_k=5)
        return await transport.query(spec,vector(),top_k=5)
    try:
        async with engine.connect() as owner,owner.begin():
            for key in _SQL_SLOT_KEYS:
                await owner.execute(sa.text('SELECT pg_advisory_xact_lock(:key)'),{'key':key})
            began=time.monotonic()
            with pytest.raises(PgvectorUnavailable):await query()
            assert .15<=time.monotonic()-began<1
            assert await owner.scalar(sa.text("SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'"))==4
        assert await query()
        async with separate.connect() as db:
            assert await db.scalar(sa.text("SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'"))==0
    finally:await separate.dispose()
