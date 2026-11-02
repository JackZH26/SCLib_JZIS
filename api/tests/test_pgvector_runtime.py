"""Actual pgvector runtime checks, exclusively through the owned test runner.

These prove extension/runtime behavior, not corpus parity or production recall.
The ordinary non-vector suite skips them; the pgvector CI job must execute them.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import struct

import pytest
import pytest_asyncio
import sqlalchemy as sa
from migration_source_expressions import public_objects
from pgvector_wire import MAGIC, projection_copy
from sqlalchemy.exc import DBAPIError

from models.db import get_session_factory

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.environ.get("SCLIB_PGVECTOR_RUNTIME_TEST") != "1",
    reason="Requires run_disposable_tests.py --pgvector with a verified owned database",
)]


@pytest_asyncio.fixture(loop_scope="function")
async def runtime_db():
    async with get_session_factory()() as db:
        yield db


async def test_extension_preserves_original_float32_network_bytes(runtime_db):
    db = runtime_db
    assert await db.scalar(sa.text("SELECT extversion FROM pg_extension WHERE extname='vector'")) == "0.8.7"
    # Include subnormals and values which ordinary decimal rounding would alter.
    values = [struct.unpack("!f", struct.pack("!I", bits))[0]
              for bits in (0x3F800001, 0xBF000001, 0x00000001, 0x00800001)]
    values += [0.0] * (768 - len(values))
    raw = struct.pack("!768f", *values)
    vector = "[" + ",".join(repr(value) for value in values) + "]"
    result = await db.scalar(sa.text("SELECT vector_send(CAST(:v AS vector(768)))"), {"v": vector})
    assert bytes(result)[:4] == struct.pack("!hh", 768, 0)
    assert bytes(result)[4:] == raw
    assert hashlib.sha256(bytes(result)[4:]).digest() == hashlib.sha256(raw).digest()


async def test_rehearsal_binary_copy_roundtrips_through_real_pgvector(runtime_db):
    db = runtime_db
    raw = struct.pack("!768f", 1.0000001192092896, -0.5000000596046448, *([0.0] * 766))
    row = [b"ig62_runtime", b"arxiv:runtime", b"a" * 64,
           hashlib.sha256(raw).hexdigest().encode(), b"b" * 64, raw, b"\x01"]
    source = MAGIC + b"\0" * 8 + struct.pack("!h", len(row))
    source += b"".join(struct.pack("!i", len(value)) + value for value in row) + struct.pack("!h", -1)
    payload, _ = projection_copy(source)
    await db.execute(sa.text("CREATE TEMP TABLE runtime_wire (vector_id text,paper_id text,"
                            "content_sha256 text,vector_sha256 text,chunk_revision_sha256 text,embedding vector(768))"))
    connection = await db.connection()
    driver = (await connection.get_raw_connection()).driver_connection
    await driver.copy_to_table("runtime_wire", source=io.BytesIO(payload), format="binary")
    observed = await db.scalar(sa.text("SELECT substring(vector_send(embedding) FROM 5) FROM runtime_wire"))
    assert bytes(observed) == raw


async def test_schema_inventory_preserves_vector_aggregates(runtime_db):
    functions, _ = await runtime_db.run_sync(lambda session: public_objects(session.connection()))
    aggregate = json.loads(functions["avg(vector)"])
    assert aggregate["prokind"] == "a"
    assert aggregate["aggregate"]["aggtransfn"]
    assert "CREATE OR REPLACE FUNCTION" in functions["vector_send(vector)"]


async def test_cosine_distance_and_filtered_hnsw_use_the_same_vector_space(runtime_db):
    db = runtime_db
    await db.execute(sa.text("CREATE TEMP TABLE runtime_vectors (id integer, group_id integer, embedding vector(3))"))
    points = [(i, i % 3, [math.cos(i / 100), math.sin(i / 100), 0.1]) for i in range(90)]
    await db.execute(sa.text("INSERT INTO runtime_vectors VALUES (:id,:group_id,CAST(:v AS vector(3)))"),
                     [{"id": i, "group_id": group, "v": str(vector)} for i, group, vector in points])
    await db.execute(sa.text("CREATE INDEX runtime_hnsw ON runtime_vectors USING hnsw "
                             "(embedding vector_cosine_ops) WITH (m=16,ef_construction=64)"))
    query = {"v": "[1,0,0.1]"}
    exact_sql = sa.text("SELECT id,embedding <=> CAST(:v AS vector(3)) AS distance FROM runtime_vectors "
                       "WHERE group_id=1 ORDER BY embedding <=> CAST(:v AS vector(3)) LIMIT 10")
    await db.execute(sa.text("SET LOCAL enable_indexscan=off"))
    exact = (await db.execute(exact_sql, query)).all()
    await db.execute(sa.text("SET LOCAL enable_indexscan=on"))
    await db.execute(sa.text("SET LOCAL enable_seqscan=off"))
    await db.execute(sa.text("SET LOCAL hnsw.ef_search=100"))
    await db.execute(sa.text("SET LOCAL hnsw.iterative_scan='strict_order'"))
    plan = " ".join((await db.execute(sa.text("EXPLAIN SELECT id FROM runtime_vectors WHERE group_id=1 "
        "ORDER BY embedding <=> CAST(:v AS vector(3)) LIMIT 10"), query)).scalars())
    assert "runtime_hnsw" in plan
    approximate = (await db.execute(exact_sql, query)).all()
    assert [row.id for row in approximate] == [row.id for row in exact]
    assert [row.distance for row in approximate] == pytest.approx([row.distance for row in exact])
    assert all(0 <= row.distance <= 2 for row in approximate)


@pytest.mark.parametrize("value", ["[NaN,0,1]", "[Infinity,0,1]", "[1,2]"])
async def test_nonfinite_or_wrong_dimension_input_is_rejected_by_postgres(runtime_db, value):
    with pytest.raises(DBAPIError):
        async with runtime_db.begin_nested():
            await runtime_db.execute(sa.text("SELECT CAST(:v AS vector(3))"), {"v": value})
    assert await runtime_db.scalar(sa.text("SELECT 1")) == 1
