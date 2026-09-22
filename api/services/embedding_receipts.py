"""Text-free document embedding response receipts; never upload confirmation.

The trusted writer supplies the actual complete vector and provider metadata.
Both hashes are independently checked against actual inputs; SQL additionally
checks the exact current Chunk and 0060 evidence pointer. No outer commit,
provider call, vector storage, permission grant or active-index claim occurs.
"""
from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from models.db import Base
from services.embedding_contract import (
    LOCAL_DOCUMENT_COUNT_METHOD,
    VERSION,
    validate_embedding_provenance,
    validate_vector,
)
from services.embedding_receipt_contract import build_embedding_receipt_row

TABLE_NAME = "embedding_completion_receipts"


class EmbeddingReceiptError(ValueError):
    """An exact current, complete document embedding cannot be recorded."""


def _document_encoder():
    """Resolve tiktoken's cached encoder before taking the shared SQL fence."""
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        raise EmbeddingReceiptError("Local cl100k tokenizer is unavailable") from exc


def _document_token_count(text, encoder):
    """CPU-only local estimate using an already initialized tokenizer."""
    try:
        return len(encoder.encode(text, disallowed_special=()))
    except Exception as exc:
        raise EmbeddingReceiptError("Local cl100k token count verification failed") from exc


async def append_embedding_receipt(db, *, chunk_id, vector, receipt, dry_run=True):
    """Append/verify inside a private savepoint, defaulting to rollback.

    Identical committed replays roll back their fence-only epoch changes too.
    The caller, not this function, owns and commits the outer transaction.
    """
    if type(dry_run) is not bool or type(chunk_id) is not str or not 1 <= len(chunk_id) <= 200:
        raise EmbeddingReceiptError("An exact chunk ID and boolean dry_run are required")
    if db.new or db.dirty or db.deleted:
        raise EmbeddingReceiptError("A clean caller-owned session is required")
    actual_vector = validate_vector(vector)
    metadata = validate_embedding_provenance(receipt, vector=actual_vector, expected_task="RETRIEVAL_DOCUMENT")
    encoder = _document_encoder() if metadata["local_count_method"] == LOCAL_DOCUMENT_COUNT_METHOD else None
    transaction = await db.begin_nested()
    try:
        await db.execute(sa.text("SELECT public.sclib_research_integrity_lock_v1()"))
        current = (await db.execute(sa.text("""SELECT c.text, link.evidence_revision_id,
            e.record_sha256 AS evidence_record_sha256,
            public.sclib_rag_chunk_hash_v1(to_jsonb(c)) AS chunk_binding_sha256
            FROM chunks c JOIN chunk_evidence_current link ON link.chunk_id=c.id
            JOIN rag_evidence_revisions e ON e.id=link.evidence_revision_id
            WHERE c.id=:id AND octet_length(c.text)<=1048576"""), {"id": chunk_id})).mappings().one_or_none()
        if current is None:
            raise EmbeddingReceiptError("Current exact chunk evidence is unavailable")
        validate_embedding_provenance(metadata, text=current["text"], vector=actual_vector, expected_task="RETRIEVAL_DOCUMENT")
        if (metadata["local_count_method"] == LOCAL_DOCUMENT_COUNT_METHOD
                and _document_token_count(current["text"], encoder) != metadata["local_count"]):
            raise EmbeddingReceiptError("Local cl100k token count mismatch")
        values = build_embedding_receipt_row(chunk_key=chunk_id, receipt=metadata,
            **{key: current[key] for key in ("evidence_revision_id", "evidence_record_sha256", "chunk_binding_sha256")})
        table = Base.metadata.tables[TABLE_NAME]
        values = {key: UUID(value) if key in {"id", "evidence_revision_id"} else value for key, value in values.items()}
        written = (await db.execute(insert(table).values(**values).on_conflict_do_nothing().returning(table))).mappings().one_or_none()
        inserted = written is not None
        if written is None:
            written = (await db.execute(sa.select(table).where(table.c.id == values["id"]))).mappings().one_or_none()
            if written is None or any(written[key] != value for key, value in values.items()):
                raise EmbeddingReceiptError("Immutable embedding receipt identity/content conflict")
        result = {"version": VERSION, "receipt_id": str(written["id"]), "receipt_sha256": written["record_sha256"],
                  "completion_scope": "embedding_response_only", "dry_run": dry_run, "committed": False}
        if dry_run or not inserted:
            await transaction.rollback()
        else:
            await transaction.commit()
        return result
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise
