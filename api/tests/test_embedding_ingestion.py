"""Actual ingestion/0060/0061 writes on disposable PostgreSQL, no cloud IO."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion"))

from ingestion.chunk.chunker import count_tokens  # noqa: E402
from ingestion.embedding_contract import (  # noqa: E402
    LOCAL_DOCUMENT_COUNT_METHOD,
    LOCAL_DOCUMENT_INPUT_LIMIT,
    LOCAL_DOCUMENT_REQUEST_LIMIT,
    validate_embedding_response,
)
from ingestion.index import indexer  # noqa: E402
from ingestion.models import ApsArticleMeta, Chunk, PaperMetadata, ParsedPaper  # noqa: E402

from models.db import get_session_factory  # noqa: E402
from services.embedding_receipts import append_embedding_receipt  # noqa: E402
from services.rag_evidence import CURRENT_FACT_RENDERER_VERSION  # noqa: E402


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


@pytest.fixture
def writer(monkeypatch):
    monkeypatch.setattr(indexer, "_session_factory", get_session_factory)
    monkeypatch.setattr(indexer, "_index", lambda: (_ for _ in ()).throw(AssertionError("Unexpected cloud IO")))
    monkeypatch.setenv("CHUNK_SIZE_TOKENS", "512")
    monkeypatch.setenv("CHUNK_OVERLAP_TOKENS", "64")
    indexer.get_settings.cache_clear()
    yield indexer
    indexer.get_settings.cache_clear()


def fixture(aps=True):
    token = uuid4().hex[:16]
    meta = (ApsArticleMeta(doi="10.0000/EmbeddingFixture." + token, title="Synthetic completion", authors=[], abstract="") if aps else
            PaperMetadata(arxiv_id="2609.99961", title="Synthetic completion", authors=[], abstract="", date_submitted=None,
                          categories=[], primary_category=None))
    record = {"formula": "Nb", "result_status": "not_detected", "minimum_temperature_k": "1 K"}
    text_value = "Synthetic non-detection; minimum test temperature is 1 K."
    count = count_tokens(text_value)
    vector, metadata = validate_embedding_response([text_value], SimpleNamespace(embeddings=[SimpleNamespace(
        values=[0.1] * 768, statistics=SimpleNamespace(truncated=False, token_count=float(count)))]),
        model="text-embedding-005", dimension=768, task_type="RETRIEVAL_DOCUMENT", local_counts=[count],
        local_count_method=LOCAL_DOCUMENT_COUNT_METHOD, local_input_limit=LOCAL_DOCUMENT_INPUT_LIMIT,
        local_request_limit=LOCAL_DOCUMENT_REQUEST_LIMIT)[0]
    chunk = Chunk(id=meta.paper_id + "_fact_000", paper_id=meta.paper_id, section="Facts", chunk_index=0,
                  text=text_value, token_count=count, embedding=vector, embedding_provenance=metadata,
                  materials_mentioned=[record], evidence_candidate={"version": "rag-evidence/1.0.0", "chunk_kind": "derived_fact",
                      "parent_record": record, "extraction_version": "synthetic/1", "rendering_version": CURRENT_FACT_RENDERER_VERSION})
    return meta, record, chunk


async def save(writer, meta, record, chunks, aps):
    if aps:
        await writer.upsert_aps_paper_with_chunks(meta, chunks, [record])
    else:
        await writer.upsert_paper_with_chunks(ParsedPaper(meta=meta, sections=[]), chunks, [record])


async def rows(db, chunk_id):
    return (await db.execute(text("SELECT to_jsonb(r) FROM embedding_completion_receipts r WHERE chunk_key=:key ORDER BY id"),
                             {"key": chunk_id})).scalars().all()


@pytest.mark.asyncio
@pytest.mark.parametrize("aps", [False, True])
async def test_real_writer_retains_completion_bound_to_actual_evidence(writer, db_session, aps):
    meta, record, chunk = fixture(aps)
    original = deepcopy(chunk)
    await save(writer, meta, record, [chunk], aps)
    receipt, = await rows(db_session, chunk.id)
    assert receipt["metadata_json"] == chunk.embedding_provenance
    assert receipt["content_sha256"] == chunk.embedding_provenance["content_sha256"]
    assert receipt["vector_sha256"] == chunk.embedding_provenance["vector_sha256"]
    evidence = (await db_session.execute(text("SELECT to_jsonb(e) FROM rag_evidence_revisions e WHERE id=:id"),
                                        {"id": receipt["evidence_revision_id"]})).scalar_one()
    assert receipt["evidence_record_sha256"] == evidence["record_sha256"]
    assert receipt["chunk_binding_sha256"] == evidence["chunk_binding_sha256"]
    assert receipt["completion_scope"] == "embedding_response_only"
    assert chunk.text not in str(receipt) and "values" not in str(receipt)
    assert "active_generation" not in receipt and chunk == original
    before = await rows(db_session, chunk.id)
    replay = await append_embedding_receipt(db_session, chunk_id=chunk.id, vector=chunk.embedding,
                                          receipt=chunk.embedding_provenance, dry_run=False)
    assert replay["receipt_id"] == receipt["id"] and replay["committed"] is False
    assert await rows(db_session, chunk.id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["missing_report", "missing_vector", "text_changed", "no_lineage", "local_count"])
async def test_invalid_completed_input_rolls_back_paper_chunks_and_all_lineage(writer, db_session, bad):
    meta, record, chunk = fixture()
    if bad == "missing_report": chunk.embedding_provenance = None
    elif bad == "missing_vector": chunk.embedding = None
    elif bad == "text_changed": chunk.text += " Altered after embedding."
    elif bad == "no_lineage": chunk.evidence_candidate = None
    elif bad == "local_count": chunk.embedding_provenance["local_count"] += 1
    with pytest.raises(ValueError):
        await save(writer, meta, record, [chunk], True)
    for table in ("papers", "chunks", "rag_extraction_revisions", "rag_evidence_revisions"):
        field = "id" if table == "papers" else "paper_id"
        assert await db_session.scalar(text(f"SELECT count(*) FROM {table} WHERE {field}=:id"), {"id": meta.paper_id}) == 0
    assert await rows(db_session, chunk.id) == []


@pytest.mark.asyncio
async def test_sql_only_chunks_have_no_fabricated_embedding_completion(writer, db_session):
    meta, record, chunk = fixture()
    chunk.embedding = chunk.embedding_provenance = None
    await save(writer, meta, record, [chunk], True)
    assert await rows(db_session, chunk.id) == []
    assert await db_session.scalar(text("SELECT count(*) FROM chunks WHERE id=:id"), {"id": chunk.id}) == 1


@pytest.mark.asyncio
async def test_replacement_failure_preserves_prior_committed_sql_and_receipt(writer, db_session):
    meta, record, chunk = fixture()
    await save(writer, meta, record, [chunk], True)
    before = await rows(db_session, chunk.id)
    saved_text = chunk.text
    chunk.text += " Later mismatched text."
    with pytest.raises(ValueError):
        await save(writer, meta, record, [chunk], True)
    await db_session.rollback()
    assert await rows(db_session, chunk.id) == before
    assert await db_session.scalar(text("SELECT text FROM chunks WHERE id=:id"), {"id": chunk.id}) == saved_text
