"""Prepare exact completed inputs for an explicit SQL generation stager.

No API-package import, provider call, filesystem export, SQL write or implicit
commit occurs here. The generation service revalidates these inputs inside its
own savepoint. A completion receipt is not an upload or source-use grant.
"""
from __future__ import annotations

import re

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from ingestion.chunk.chunker import require_token_budget
from ingestion.config import get_settings
from ingestion.embedding_contract import (
    LOCAL_DOCUMENT_COUNT_METHOD,
    validate_embedding_provenance,
    validate_vector,
)
from ingestion.models import Chunk

MAX_ITEMS = 1000
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}\Z")


async def prepare_generation_items(db, chunks):
    """Return all exact inputs or reject, never infer a parser or old receipt."""
    if type(chunks) is not list or not 1 <= len(chunks) <= MAX_ITEMS:
        raise ValueError("An explicit bounded generation chunk inventory is required")
    if db.new or db.dirty or db.deleted:
        raise ValueError("A clean caller-owned session is required")
    settings = get_settings()
    prepared, requests = [], []
    for chunk in chunks:
        if (type(chunk) is not Chunk or type(chunk.id) is not str or not 1 <= len(chunk.id) <= 200
                or type(chunk.parser_version) is not str or not _VERSION.fullmatch(chunk.parser_version)
                or chunk.parser_version in {"unknown", "legacy_unknown", "unrecorded"}):
            raise ValueError("Exact chunk and prospective parser identities are required")
        count = require_token_budget(chunk.text, max_tokens=settings.chunk_size_tokens)
        vector = validate_vector(chunk.embedding)
        report = validate_embedding_provenance(chunk.embedding_provenance, text=chunk.text,
                                              vector=vector, expected_task="RETRIEVAL_DOCUMENT")
        if (report["local_count_method"] != LOCAL_DOCUMENT_COUNT_METHOD or report["local_count"] != count
                or type(chunk.token_count) is not int or chunk.token_count != count):
            raise ValueError("Complete-text token count does not match the current input")
        prepared.append({"chunk_id": chunk.id, "vector": vector, "parser_version": chunk.parser_version})
        requests.append({"chunk_id": chunk.id, "metadata_json": report})
    if len({item["chunk_id"] for item in prepared}) != len(prepared):
        raise ValueError("Duplicate generation chunk identities are not supported")
    query = text("""WITH requested AS (
        SELECT * FROM jsonb_to_recordset(:requests) AS r(chunk_id text,metadata_json jsonb)
      ) SELECT r.chunk_key AS chunk_id,r.id AS receipt_id
        FROM requested expected JOIN chunks c ON c.id=expected.chunk_id
        JOIN chunk_evidence_current link ON link.chunk_id=c.id
        JOIN rag_evidence_revisions e ON e.id=link.evidence_revision_id
        JOIN embedding_completion_receipts r ON r.chunk_key=c.id
          AND r.evidence_revision_id=e.id AND r.metadata_json=expected.metadata_json
        JOIN papers p ON p.id=c.paper_id
        WHERE r.evidence_record_sha256=e.record_sha256
          AND r.chunk_binding_sha256=public.sclib_rag_chunk_hash_v1(to_jsonb(c))
          AND e.source_snapshot_sha256=public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p))
          AND r.content_sha256=encode(public.digest(convert_to(c.text,'UTF8'),'sha256'),'hex')
        LIMIT 1001""").bindparams(bindparam("requests", type_=JSONB))
    rows = (await db.execute(query, {"requests": requests})).mappings().all()
    if len(rows) != len(prepared) or {row["chunk_id"] for row in rows} != {item["chunk_id"] for item in prepared}:
        raise ValueError("Every generation input requires one exact current SQL completion receipt")
    receipts = {row["chunk_id"]: str(row["receipt_id"]) for row in rows}
    return [item | {"receipt_id": receipts[item["chunk_id"]]} for item in prepared]
