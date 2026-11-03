"""Real role/COPY/seal/readback in fresh owned vector services only."""
from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base, get_engine
from models.retrieval_backend_v2 import TABLE_ORDER
from services import retrieval_backend as service
from services.pgvector_query import ProjectionSpec
from tests.test_index_generations import db_session as db_session
from tests.test_research_freeze import state
from tests.test_retrieval_content import legacy_content

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.environ.get("SCLIB_PGVECTOR_RUNTIME_TEST") != "1", reason="Requires fresh owned vector runner")]


async def prepared_backend(db, *, graph=True, sealed=True):
    _, content = await legacy_content(db)
    # These are explicit synthetic artifact declarations, not signature proof.
    values = dict(build_id=str(uuid4()), content_id=content["content_id"],
                  image_digest="sha256:" + "a" * 64, implementation_revision="b" * 40)
    build = await service.stage_build(db, **values, dry_run=False)
    await service.create_projection(db, build_id=values["build_id"], dry_run=False)
    await service.copy_partition(db, build_id=values["build_id"], partition_id=0, dry_run=False)
    if graph:
        await service.build_small_projection_graph(db, build_id=values["build_id"], dry_run=False)
    if sealed:
        await service.seal_projection(db, build_id=values["build_id"], dry_run=False)
    stored = (await db.execute(sa.select(Base.metadata.tables[TABLE_ORDER[0]]).where(
        Base.metadata.tables[TABLE_ORDER[0]].c.id == UUID(values["build_id"])))).mappings().one()
    spec = ProjectionSpec(values["build_id"], content["content_id"], stored["content_manifest_sha256"])
    return values, build, spec


async def test_build_preview_replay_and_nonprivileged_actual_runtime(db_session):
    _, content = await legacy_content(db_session)
    values = dict(build_id=str(uuid4()), content_id=content["content_id"],
                  image_digest="sha256:" + "a" * 64, implementation_revision="b" * 40)
    before = await state(db_session)
    await service.stage_build(db_session, **values)
    assert await state(db_session) == before
    result = await service.stage_build(db_session, **values, dry_run=False)
    after = await state(db_session)
    assert await service.stage_build(db_session, **values, dry_run=False) == result
    assert await state(db_session) == after
    role = (await db_session.execute(sa.text("SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user"))).one()
    assert tuple(role) == (False, False, False)
    assert not result["committed"] and not result["active_pointer_changed"]
    changed = {**values, "image_digest": "sha256:" + "c" * 64}
    with pytest.raises(service.RetrievalBackendError, match="identity conflict"):
        await service.stage_build(db_session, **changed, dry_run=False)
    assert await state(db_session) == after


async def test_copy_preview_full_bit_readback_and_exact_resume(db_session):
    _, content = await legacy_content(db_session)
    identifier = str(uuid4())
    await service.stage_build(db_session, build_id=identifier, content_id=content["content_id"],
        image_digest="sha256:" + "a" * 64, implementation_revision="b" * 40, dry_run=False)
    before = await state(db_session)
    await service.create_projection(db_session, build_id=identifier)
    assert await state(db_session) == before
    assert await db_session.scalar(sa.text("SELECT to_regclass(:table) IS NULL"),
                                   {"table": "retrieval_projection.b_" + UUID(identifier).hex})
    await service.create_projection(db_session, build_id=identifier, dry_run=False)
    before = await state(db_session)
    await service.copy_partition(db_session, build_id=identifier, partition_id=0)
    assert await state(db_session) == before
    table = "retrieval_projection.b_" + UUID(identifier).hex
    assert await db_session.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 0
    await service.copy_partition(db_session, build_id=identifier, partition_id=0, dry_run=False)
    actual = await db_session.scalar(sa.text(f"SELECT bool_and(substring(vector_send(p.embedding) FROM 5)=m.vector_bytes) "
        f"FROM {table} p JOIN index_generation_members m ON m.vector_id=p.vector_id"))
    assert actual is True
    physical = (await db_session.execute(sa.text(f"SELECT pg_column_size(embedding),"
        f"octet_length(vector_send(embedding))+4 FROM {table}"))).one()
    # EXTENDED compresses this repetitive synthetic vector. Inspect the actual
    # stored datum and the unchanged binary readback, not just column metadata.
    assert tuple(physical) == (3080, 3080)
    assert await db_session.scalar(sa.text("SELECT attstorage::text FROM pg_attribute "
        "WHERE attrelid=to_regclass(:name) AND attname='embedding'"), {'name': table}) == 'p'
    assert await db_session.scalar(sa.text("SELECT bool_and(attstorage::text='p') FROM pg_attribute "
        "WHERE attrelid=to_regclass(:name) AND attnum>0 AND NOT attisdropped"), {'name': table}) is True
    assert await db_session.scalar(sa.text("SELECT CASE WHEN reltoastrelid=0 THEN 0 "
        "ELSE pg_relation_size(reltoastrelid) END FROM pg_class WHERE oid=to_regclass(:name)"), {'name': table}) == 0
    after = await state(db_session)
    replay = await service.copy_partition(db_session, build_id=identifier, partition_id=0, dry_run=False)
    assert replay["replayed"] and await state(db_session) == after


async def test_sealed_projection_validates_actual_complete_inventory(db_session):
    values, _, _ = await prepared_backend(db_session)
    before = await state(db_session)
    identifier = str(uuid4())
    preview = await service.validate_projection(db_session, build_id=values["build_id"], validation_id=identifier)
    assert preview["outcome"] == "validated" and await state(db_session) == before
    receipt = await service.validate_projection(db_session, build_id=values["build_id"], validation_id=identifier, dry_run=False)
    assert receipt["source_member_count"] == receipt["projection_member_count"] == 1
    assert receipt["missing_count"] == receipt["extra_count"] == receipt["mismatch_count"] == 0
    assert receipt["content_manifest_intact"] is True and not receipt["active_pointer_changed"]
    after = await state(db_session)
    assert await service.validate_projection(db_session, build_id=values["build_id"], validation_id=identifier, dry_run=False) == receipt
    assert await state(db_session) == after


@pytest.mark.parametrize('year',[None,2024])
async def test_initial_binary_copy_preserves_actual_nullable_filtering_year(db_session,monkeypatch,year):
    from datetime import date
    from models.db import Chunk,Paper
    from tests import test_embedding_receipts
    seed=test_embedding_receipts.seed
    async def dated(db):
        chunk,candidate=await seed(db)
        paper=await db.scalar(sa.select(Chunk.paper_id).where(Chunk.id==chunk))
        await db.execute(sa.update(Chunk).where(Chunk.id==chunk).values(year=year))
        await db.execute(sa.update(Paper).where(Paper.id==paper).values(date_submitted=date(year,1,1) if year else None))
        return chunk,candidate
    monkeypatch.setattr(test_embedding_receipts,'seed',dated)
    values,_,spec=await prepared_backend(db_session)
    assert await db_session.scalar(sa.text(f'SELECT year FROM {spec.table}'))==year
    receipt=await service.validate_projection(db_session,build_id=values['build_id'],validation_id=str(uuid4()),dry_run=False)
    assert receipt['mismatch_count']==receipt['missing_count']==receipt['extra_count']==0


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE", "INSERT"])
async def test_seal_blocks_all_statements_before_any_row_changes(db_session, operation):
    values, _, spec = await prepared_backend(db_session)
    before = await state(db_session)
    statements = {"UPDATE": f"UPDATE {spec.table} SET paper_id=paper_id WHERE false",
                  "DELETE": f"DELETE FROM {spec.table}", "TRUNCATE": f"TRUNCATE {spec.table}",
                  "INSERT": f"INSERT INTO {spec.table} SELECT * FROM {spec.table} WHERE false"}
    with pytest.raises(DBAPIError, match="projection_sealed"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(statements[operation]))
    assert await state(db_session) == before
    with pytest.raises(service.RetrievalBackendError, match="sealed"):
        await service.copy_partition(db_session, build_id=values["build_id"], partition_id=0, dry_run=False)
    assert await state(db_session) == before


async def test_reader_cannot_write_even_if_update_was_accidentally_granted(db_session):
    _, _, spec = await prepared_backend(db_session, sealed=False)
    await db_session.execute(sa.text("GRANT USAGE ON SCHEMA retrieval_projection TO sclib_retrieval_reader"))
    await db_session.execute(sa.text(f"GRANT UPDATE,SELECT ON {spec.table} TO sclib_retrieval_reader"))
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="separate_builder_role"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("SET LOCAL ROLE sclib_retrieval_reader"))
            await db_session.execute(sa.text(f"UPDATE {spec.table} SET paper_id='unauthorized'"))
    assert await state(db_session) == before


@pytest.mark.parametrize("bad", ["hash", "year", "bytes", "missing", "extra"])
async def test_full_validation_refuses_bad_projection_not_just_matching_count(db_session, bad):
    values, _, spec = await prepared_backend(db_session, sealed=False)
    if bad == "hash":
        await db_session.execute(sa.text(f"UPDATE {spec.table} SET content_sha256=:hash"), {"hash": "e" * 64})
    elif bad == "year":
        await db_session.execute(sa.text(f"UPDATE {spec.table} SET year=1870"))
    elif bad == "bytes":
        await db_session.execute(sa.text(f"UPDATE {spec.table} SET embedding=array_fill(1::real,ARRAY[768])::vector"))
    elif bad == "missing":
        await db_session.execute(sa.text(f"DELETE FROM {spec.table}"))
    else:
        await db_session.execute(sa.text(f"INSERT INTO {spec.table} SELECT 'orphan',paper_id,year,content_sha256,"
            f"vector_sha256,chunk_revision_sha256,embedding FROM {spec.table} LIMIT 1"))
    await service.seal_projection(db_session, build_id=values["build_id"], dry_run=False)
    receipt = await service.validate_projection(db_session, build_id=values["build_id"], validation_id=str(uuid4()), dry_run=False)
    assert receipt["outcome"] == "rejected"


async def test_missing_or_wrong_graph_cannot_be_sealed(db_session):
    values, _, spec = await prepared_backend(db_session, graph=False, sealed=False)
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="valid_cosine_graph"):
        await service.seal_projection(db_session, build_id=values["build_id"], dry_run=False)
    assert await state(db_session) == before
    await db_session.execute(sa.text(f"CREATE INDEX hnsw_b_{UUID(values['build_id']).hex} ON {spec.table} "
        "USING hnsw(embedding vector_cosine_ops) WITH(m=16,ef_construction=64)"))
    with pytest.raises(DBAPIError, match="valid_cosine_graph"):
        await service.seal_projection(db_session, build_id=values["build_id"], dry_run=False)


async def test_caller_cannot_declare_a_bad_projection_valid(db_session):
    values, _, spec = await prepared_backend(db_session, sealed=False)
    await db_session.execute(sa.text(f"UPDATE {spec.table} SET content_sha256=:hash"), {"hash": "f" * 64})
    await service.seal_projection(db_session, build_id=values["build_id"], dry_run=False)
    identifier = uuid4()
    await db_session.execute(Base.metadata.tables[TABLE_ORDER[3]].insert().values(
        id=identifier, build_id=UUID(values["build_id"]), table_oid=0, index_oid=0,
        source_member_count=1, projection_member_count=1, missing_count=0, extra_count=0,
        mismatch_count=0, content_manifest_intact=True, outcome="validated"))
    row = (await db_session.execute(sa.select(Base.metadata.tables[TABLE_ORDER[3]]).where(
        Base.metadata.tables[TABLE_ORDER[3]].c.id == identifier))).mappings().one()
    assert row["outcome"] == "rejected" and row["mismatch_count"] == 1
    assert row["table_oid"] > 0 and row["index_oid"] > 0


async def test_old_repeatable_read_writer_cannot_miss_a_new_seal(db_session):
    values, _, spec = await prepared_backend(db_session, sealed=False)
    await db_session.commit()
    engine = get_engine()
    try:
        async with engine.connect() as writer:
            await writer.execution_options(isolation_level="REPEATABLE READ")
            await writer.begin()
            assert await writer.scalar(sa.text("SHOW transaction_isolation")) == "repeatable read"
            await writer.scalar(sa.text("SELECT epoch FROM retrieval_backend_fences_v2 WHERE build_id=:id"),
                                {"id": UUID(values["build_id"])})
            await service.seal_projection(db_session, build_id=values["build_id"], dry_run=False)
            await db_session.commit()
            with pytest.raises(DBAPIError) as error:
                await writer.execute(sa.text(f"UPDATE {spec.table} SET paper_id='stale-writer'"))
            assert getattr(error.value.orig, "sqlstate", None) == "40001"
            await writer.rollback()
    finally:
        await engine.dispose()
        # The committed immutable ledger remains. Remove only this test's
        # physical projection before the fresh cluster is destroyed.
        await db_session.execute(sa.text(f"DROP TABLE {spec.table}"))
        await db_session.commit()


async def test_binary_import_and_validation_ignore_session_bytea_format(db_session):
    _, content = await legacy_content(db_session)
    identifier = str(uuid4())
    await service.stage_build(db_session, build_id=identifier, content_id=content["content_id"],
        image_digest="sha256:" + "a" * 64, implementation_revision="b" * 40, dry_run=False)
    await service.create_projection(db_session, build_id=identifier, dry_run=False)
    await db_session.execute(sa.text("SET LOCAL bytea_output='escape'"))
    await service.copy_partition(db_session, build_id=identifier, partition_id=0, dry_run=False)
    assert await db_session.scalar(sa.text("SHOW bytea_output")) == "escape"
    await service.build_small_projection_graph(db_session, build_id=identifier, dry_run=False)
    await service.seal_projection(db_session, build_id=identifier, dry_run=False)
    result = await service.validate_projection(db_session, build_id=identifier, validation_id=str(uuid4()), dry_run=False)
    assert result["outcome"] == "validated" and result["mismatch_count"] == 0
    assert await db_session.scalar(sa.text("SHOW bytea_output")) == "escape"


@pytest.mark.parametrize("table", [TABLE_ORDER[0], TABLE_ORDER[2], TABLE_ORDER[3]])
async def test_build_seal_and_validation_history_remain_append_only(db_session, table):
    values, _, _ = await prepared_backend(db_session)
    await service.validate_projection(db_session, build_id=values["build_id"], validation_id=str(uuid4()), dry_run=False)
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(f"DELETE FROM {table}"))
    assert await state(db_session) == before
