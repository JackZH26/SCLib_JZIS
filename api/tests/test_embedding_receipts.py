"""0061 document response observations on guarded synthetic PostgreSQL."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base, Chunk, get_session_factory
from services import embedding_receipts as receipt_service
from services.embedding_contract import (
    DIMENSION,
    LOCAL_DOCUMENT_COUNT_METHOD,
    LOCAL_DOCUMENT_INPUT_LIMIT,
    LOCAL_DOCUMENT_REQUEST_LIMIT,
    MODEL,
    validate_embedding_response,
)
from services.embedding_receipts import TABLE_NAME, EmbeddingReceiptError, append_embedding_receipt
from services.rag_evidence import register_chunk_evidence
from tests.test_rag_evidence import chunk_row, seed
from tests.test_research_freeze import state


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


def completion(text):
    import tiktoken

    count = len(tiktoken.get_encoding("cl100k_base").encode(text, disallowed_special=()))
    response = {"embeddings": [{"values": [0.25] * DIMENSION,
                                "statistics": {"truncated": False, "token_count": 17.0}}]}
    return validate_embedding_response([text], response, model=MODEL, dimension=DIMENSION,
        task_type="RETRIEVAL_DOCUMENT", local_counts=[count], local_count_method=LOCAL_DOCUMENT_COUNT_METHOD,
        local_input_limit=LOCAL_DOCUMENT_INPUT_LIMIT, local_request_limit=LOCAL_DOCUMENT_REQUEST_LIMIT)[0]


async def prepared(db):
    chunk, candidate = await seed(db)
    evidence = await register_chunk_evidence(db, chunk_id=chunk, candidate=candidate, dry_run=False)
    row = await chunk_row(db, chunk)
    vector, receipt = completion(row.text)
    return chunk, vector, receipt, evidence


async def read_receipt(db, identifier):
    table = Base.metadata.tables[TABLE_NAME]
    return dict((await db.execute(sa.select(table).where(table.c.id == UUID(identifier)))).mappings().one())


def test_builder_is_byte_identical_across_independent_deployments():
    root = Path(__file__).resolve().parents[2]
    assert (root / "api/services/embedding_receipt_contract.py").read_bytes() == (
        root / "ingestion/ingestion/embedding_receipt_contract.py").read_bytes()


def test_receipt_has_no_chunk_fk_vector_or_source_text_columns():
    table = Base.metadata.tables[TABLE_NAME]
    assert all(fk.column.table.name != "chunks" for fk in table.foreign_keys)
    assert not {"text", "vector", "embedding", "source_quote", "scientific_acceptance", "active_generation"} & set(table.c.keys())
    assert "embedding_provenance" not in Base.metadata.tables["chunks"].c


async def test_dry_run_caller_rollback_and_exact_replay_preserve_every_row(db_session):
    chunk, vector, receipt, _ = await prepared(db_session)
    before = await state(db_session)
    dry = await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt=receipt)
    assert dry["committed"] is False and dry["completion_scope"] == "embedding_response_only"
    assert await state(db_session) == before
    first = await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt=receipt, dry_run=False)
    written = await state(db_session)
    again = await append_embedding_receipt(db_session, chunk_id=chunk, vector=deepcopy(vector), receipt=deepcopy(receipt), dry_run=False)
    assert first == again and dry["receipt_id"] == first["receipt_id"]
    assert await state(db_session) == written
    assert "PRIVATE ORIGINAL WORDING" not in str(written[TABLE_NAME])
    assert len(written[TABLE_NAME]) == len(before[TABLE_NAME]) + 1
    await db_session.rollback()
    assert await db_session.scalar(sa.select(Chunk.id).where(Chunk.id == chunk)) is None


@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
async def test_immutable_receipt_rejects_all_mutations(db_session, operation):
    chunk, vector, receipt, _ = await prepared(db_session)
    await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt=receipt, dry_run=False)
    sql = {"update": f"UPDATE {TABLE_NAME} SET record_sha256=record_sha256", "delete": f"DELETE FROM {TABLE_NAME}",
           "truncate": f"TRUNCATE {TABLE_NAME}"}[operation]
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(sql))


@pytest.mark.parametrize("change", [{"provider_truncated": True}, {"provider_truncated": None},
    {"auto_truncate": True}, {"task_type": "RETRIEVAL_QUERY"}, {"provider_token_count": 2049},
    {"provider_token_count": True}, {"local_count": 2000}, {"output_dimensionality": 384},
    {"model": "unreviewed-model"}, {"source_quote": "PRIVATE"}, {"completeness_status": "uploaded"},
    {"vector_sha256": "0" * 64}, {"content_sha256": "0" * 64}])
async def test_service_rejects_incomplete_wrong_space_or_hash_mismatched_response(db_session, change):
    chunk, vector, receipt, _ = await prepared(db_session)
    before = await state(db_session)
    with pytest.raises(ValueError):
        await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt={**receipt, **change}, dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("change", [{"provider_truncated": None}, {"output_dimensionality": 768.1},
    {"local_count": None}, {"provider_token_count": "17"}, {"local_count_method": None},
    {"source_quote": "PRIVATE"}, {"task_type": "RETRIEVAL_QUERY"}, {"auto_truncate": True}])
async def test_raw_sql_enforces_closed_document_completion_metadata(db_session, change):
    chunk, vector, receipt, _ = await prepared(db_session)
    first = await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt=receipt, dry_run=False)
    values = await read_receipt(db_session, first["receipt_id"])
    values.update(id=uuid4(), metadata_json={**values["metadata_json"], **change})
    with pytest.raises(DBAPIError, match="complete_document_metadata"):
        async with db_session.begin_nested():
            await db_session.execute(Base.metadata.tables[TABLE_NAME].insert().values(**values))


async def test_changed_chunk_or_missing_evidence_cannot_append_but_history_survives(db_session):
    chunk, vector, receipt, _ = await prepared(db_session)
    first = await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt=receipt, dry_run=False)
    stored = await read_receipt(db_session, first["receipt_id"])
    await db_session.execute(sa.update(Chunk).where(Chunk.id == chunk).values(text="Changed complete input"))
    with pytest.raises(EmbeddingReceiptError, match="evidence is unavailable"):
        await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt=receipt, dry_run=False)
    assert await read_receipt(db_session, first["receipt_id"]) == stored
    with pytest.raises(DBAPIError, match="exact_current_chunk"):
        async with db_session.begin_nested():
            await db_session.execute(Base.metadata.tables[TABLE_NAME].insert().values(**{**stored, "id": uuid4()}))
    await db_session.execute(sa.delete(Chunk).where(Chunk.id == chunk))
    assert await read_receipt(db_session, first["receipt_id"]) == stored


async def test_raw_sql_rejects_numeric_hash_even_when_stringified_digest_matches(db_session):
    chunk, vector, receipt, _ = await prepared(db_session)
    first = await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt=receipt, dry_run=False)
    values = await read_receipt(db_session, first["receipt_id"])
    numeric_digest = "1" * 64
    values.update(id=uuid4(), vector_sha256=numeric_digest,
                  metadata_json={**values["metadata_json"], "vector_sha256": int(numeric_digest)})
    with pytest.raises(DBAPIError, match="complete_document_metadata"):
        async with db_session.begin_nested():
            await db_session.execute(Base.metadata.tables[TABLE_NAME].insert().values(**values))


async def test_document_local_count_is_recomputed_from_actual_full_sql_text(db_session):
    text = "test " * 100
    chunk, candidate = await seed(db_session, text=text)
    await register_chunk_evidence(db_session, chunk_id=chunk, candidate=candidate, dry_run=False)
    vector, receipt = completion(text)
    assert receipt["local_count"] == 101
    before = await state(db_session)
    with pytest.raises(EmbeddingReceiptError, match="cl100k token count mismatch"):
        await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector,
                                       receipt={**receipt, "local_count": 1}, dry_run=False)
    assert await state(db_session) == before


async def test_document_tokenizer_unavailable_fails_closed_with_complete_rollback(db_session, monkeypatch):
    chunk, vector, receipt, _ = await prepared(db_session)
    before = await state(db_session)
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    with pytest.raises(EmbeddingReceiptError, match="cl100k tokenizer is unavailable"):
        await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt=receipt, dry_run=False)
    assert await state(db_session) == before


async def test_utf8_byte_method_is_recomputed_without_a_tokenizer(db_session, monkeypatch):
    chunk, vector, receipt, _ = await prepared(db_session)
    row = await chunk_row(db_session, chunk)
    receipt.update(local_count_method="utf8-bytes/1", local_count=len(row.text.encode("utf-8")),
                   local_input_limit=8192, local_request_limit=8192)
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    before = await state(db_session)
    await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt=receipt)
    assert await state(db_session) == before
    with pytest.raises(ValueError, match="UTF-8 byte count mismatch"):
        await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector,
                                       receipt={**receipt, "local_count": 1}, dry_run=False)
    assert await state(db_session) == before


async def test_tokenizer_initialization_precedes_integrity_savepoint(db_session, monkeypatch):
    chunk, vector, receipt, _ = await prepared(db_session)
    begun = False
    original_begin = db_session.begin_nested
    original_encoder = receipt_service._document_encoder

    async def begin_nested():
        nonlocal begun
        begun = True
        return await original_begin()

    def encoder():
        assert begun is False, "Tokenizer setup must not occur under the shared SQL fence"
        return original_encoder()

    monkeypatch.setattr(db_session, "begin_nested", begin_nested)
    monkeypatch.setattr(receipt_service, "_document_encoder", encoder)
    await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt=receipt)
    assert begun is True


async def test_source_revision_or_wrong_evidence_cannot_append(db_session):
    chunk, vector, receipt, _ = await prepared(db_session)
    first = await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt=receipt, dry_run=False)
    stored = await read_receipt(db_session, first["receipt_id"])
    _, _, _, other_evidence = await prepared(db_session)
    with pytest.raises(DBAPIError, match="exact_current_chunk"):
        async with db_session.begin_nested():
            await db_session.execute(Base.metadata.tables[TABLE_NAME].insert().values(**{
                **stored, "id": uuid4(), "evidence_revision_id": UUID(other_evidence["evidence_revision_id"])}))
    row = await chunk_row(db_session, chunk)
    await db_session.execute(sa.text("UPDATE papers SET status='corrected' WHERE id=:id"), {"id": row.paper_id})
    with pytest.raises(DBAPIError, match="exact_current_chunk"):
        async with db_session.begin_nested():
            await append_embedding_receipt(db_session, chunk_id=chunk, vector=vector, receipt=receipt, dry_run=False)
