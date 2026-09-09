"""Actual guarded staging: initialize only the tokenizer that receipts require."""
from __future__ import annotations

import sys
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base, get_session_factory
from services import index_generations as service
from services.embedding_contract import validate_embedding_response
from services.embedding_receipt_contract import build_embedding_receipt_row
from services.embedding_receipts import EmbeddingReceiptError, append_embedding_receipt
from services.rag_evidence import register_chunk_evidence
from tests.test_index_generations import resource
from tests.test_rag_evidence import seed
from tests.test_research_freeze import state


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


async def item(db, *, method="utf8-bytes/1", text="Synthetic pending restore vector fixture."):
    chunk, candidate = await seed(db, text=text)
    await register_chunk_evidence(db, chunk_id=chunk, candidate=candidate, dry_run=False)
    if method == "tiktoken-cl100k_base/1":
        import tiktoken
        count = len(tiktoken.get_encoding("cl100k_base").encode(text, disallowed_special=()))
        input_limit, request_limit = 1536, 14000
    else:
        count = len(text.encode("utf-8"))
        input_limit = request_limit = 8192
    vector, metadata = validate_embedding_response([text], {"embeddings": [{
        "values": [0.25] * 768, "statistics": {"truncated": False, "token_count": 1}}]},
        model="text-embedding-005", dimension=768, task_type="RETRIEVAL_DOCUMENT",
        local_counts=[count], local_count_method=method,
        local_input_limit=input_limit, local_request_limit=request_limit)[0]
    receipt = await append_embedding_receipt(db, chunk_id=chunk, vector=vector, receipt=metadata, dry_run=False)
    return {"chunk_id": chunk, "receipt_id": receipt["receipt_id"], "vector": vector,
            "parser_version": "synthetic-tokenizer-admission/1"}


async def test_utf8_staging_and_exact_replay_need_no_tokenizer_or_cache(db_session, monkeypatch):
    value = await item(db_session)
    def forbidden():
        raise AssertionError("UTF8 staging must not initialize a tokenizer or its cache")
    monkeypatch.setattr(service, "_document_encoder", forbidden)
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    generation_id = uuid4()
    first = await service.stage_generation(db_session, generation_id=generation_id,
        items=[value], resource=resource(), dry_run=False)
    before = await state(db_session)
    second = await service.stage_generation(db_session, generation_id=generation_id,
        items=[value], resource=resource(), dry_run=False)
    assert first == second and first["member_count"] == 1
    assert await state(db_session) == before
    assert len(await service.load_generation_members(db_session, generation_id=generation_id)) == 1


@pytest.mark.parametrize("mixed", [False, True])
async def test_cl100k_prepared_once_before_fence_and_recounted_inside(db_session, monkeypatch, mixed):
    values = [await item(db_session, method="tiktoken-cl100k_base/1", text="test " * 100)]
    if mixed:
        values.append(await item(db_session))
    events = []
    original_encoder, original_count = service._document_encoder, service._document_token_count
    original_begin = db_session.begin_nested
    def encoder():
        assert events == []
        events.append("encoder")
        return original_encoder()
    async def begin():
        events.append("savepoint")
        return await original_begin()
    def count(text, prepared):
        assert events == ["encoder", "savepoint"]
        events.append("recount")
        result = original_count(text, prepared)
        assert result == 101
        return result
    monkeypatch.setattr(service, "_document_encoder", encoder)
    monkeypatch.setattr(service, "_document_token_count", count)
    monkeypatch.setattr(db_session, "begin_nested", begin)
    result = await service.stage_generation(db_session, generation_id=uuid4(), items=values,
                                            resource=resource(), dry_run=False)
    assert result["member_count"] == len(values)
    assert events == ["encoder", "savepoint", "recount"]


async def test_valid_raw_sql_receipt_undercount_still_rejected_by_actual_stager(db_session):
    value = await item(db_session, method="tiktoken-cl100k_base/1", text="test " * 100)
    table = Base.metadata.tables["embedding_completion_receipts"]
    stored = (await db_session.execute(sa.select(table).where(table.c.id == UUID(value["receipt_id"])))).mappings().one()
    assert stored["metadata_json"]["local_count"] == 101
    forged = build_embedding_receipt_row(chunk_key=value["chunk_id"],
        receipt={**stored["metadata_json"], "local_count": 1},
        **{key: stored[key] for key in ("evidence_revision_id", "evidence_record_sha256", "chunk_binding_sha256")})
    await db_session.execute(table.insert().values(**{
        key: UUID(item) if key in {"id", "evidence_revision_id"} else item for key, item in forged.items()}))
    before = await state(db_session)
    with pytest.raises(service.IndexGenerationError, match="local token count mismatch"):
        await service.stage_generation(db_session, generation_id=uuid4(),
            items=[{**value, "receipt_id": forged["id"]}], resource=resource(), dry_run=False)
    assert await state(db_session) == before


async def test_missing_receipt_refuses_without_initializing_unrelated_tokenizer(db_session, monkeypatch):
    value = await item(db_session)
    before = await state(db_session)
    def forbidden():
        raise AssertionError("Missing receipt must not initialize tokenizer")
    monkeypatch.setattr(service, "_document_encoder", forbidden)
    with pytest.raises(service.IndexGenerationError, match="receipt inventory unavailable"):
        await service.stage_generation(db_session, generation_id=uuid4(),
            items=[{**value, "receipt_id": str(uuid4())}], resource=resource(), dry_run=False)
    assert await state(db_session) == before


async def test_required_tokenizer_unavailable_fails_before_any_staging_savepoint(db_session, monkeypatch):
    value = await item(db_session, method="tiktoken-cl100k_base/1")
    before = await state(db_session)
    def unavailable():
        raise EmbeddingReceiptError("Local cl100k tokenizer is unavailable")
    async def forbidden():
        raise AssertionError("Unavailable encoder must fail before staging fence")
    monkeypatch.setattr(service, "_document_encoder", unavailable)
    monkeypatch.setattr(db_session, "begin_nested", forbidden)
    with pytest.raises(EmbeddingReceiptError, match="tokenizer is unavailable"):
        await service.stage_generation(db_session, generation_id=uuid4(), items=[value], resource=resource(), dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_receipt_preflight_relies_on_native_immutable_rows(db_session, operation):
    await item(db_session)
    before = await state(db_session)
    command = {"UPDATE": "UPDATE embedding_completion_receipts SET metadata_json=metadata_json",
               "DELETE": "DELETE FROM embedding_completion_receipts",
               "TRUNCATE": "TRUNCATE embedding_completion_receipts CASCADE"}[operation]
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(command))
    assert await state(db_session) == before
