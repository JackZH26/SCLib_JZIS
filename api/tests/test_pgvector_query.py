"""Real transport tests in fresh owned services; no production admission claim."""
from __future__ import annotations

import math
import os
import time
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
    result = await PgvectorQueries(engine, QueryBudget(exact_cohort_limit=10)).query(
        spec, vector(), top_k=20, year_max=2001)
    assert result.strategy == "hnsw" and result.exhaustive is False
    assert [item.vector_id for item in result.neighbors] == [f"v{i:03}" for i in range(12, 32)]


async def test_real_empty_filtered_cohort_is_successful_exact_empty(projection):
    engine, spec = projection
    result = await PgvectorQueries(engine).query(spec, vector(), top_k=20, year_min=2027)
    assert result.strategy == "exact_filtered" and result.exhaustive and result.neighbors == ()


async def test_local_settings_do_not_leak_to_next_transaction(projection):
    engine, spec = projection
    async with engine.connect() as db:
        before = {key: await db.scalar(sa.text("SELECT current_setting(:key)"), {"key": key})
                  for key in ("statement_timeout", "work_mem", "transaction_read_only")}
    await PgvectorQueries(engine).query(spec, vector(), top_k=5)
    async with engine.connect() as db:
        after = {key: await db.scalar(sa.text("SELECT current_setting(:key)"), {"key": key}) for key in before}
    assert before == after


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
])
async def test_unbounded_resource_settings_are_rejected(budget):
    with pytest.raises(PgvectorQueryError):
        QueryBudget(**budget)
