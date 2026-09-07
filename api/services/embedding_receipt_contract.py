"""Pure deterministic embedding receipt rows, mirrored in API and ingestion.

This builder authenticates nothing. The writer must first check actual text
and vector with validate_embedding_provenance and obtain the exact current
0060 bindings from SQL under the integrity fence.
"""
from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID, uuid5

from .embedding_contract import validate_embedding_provenance

NAMESPACE = UUID("4eae790e-3a7e-40bc-9876-cc6c77244c28")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def build_embedding_receipt_row(*, chunk_key, evidence_revision_id, evidence_record_sha256,
                                chunk_binding_sha256, receipt):
    """Return the closed insert payload; ID includes every persisted input."""
    if type(chunk_key) is not str or not 1 <= len(chunk_key) <= 200:
        raise ValueError("An exact bounded chunk key is required")
    if any(type(value) is not str or not _SHA.fullmatch(value) for value in (evidence_record_sha256, chunk_binding_sha256)):
        raise ValueError("Exact SQL evidence hashes are required")
    metadata = validate_embedding_provenance(receipt, expected_task="RETRIEVAL_DOCUMENT")
    row = {"chunk_key": chunk_key, "evidence_revision_id": str(UUID(str(evidence_revision_id))),
           "evidence_record_sha256": evidence_record_sha256, "chunk_binding_sha256": chunk_binding_sha256,
           "content_sha256": metadata["content_sha256"], "vector_sha256": metadata["vector_sha256"],
           "metadata_json": metadata, "completion_scope": "embedding_response_only"}
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    row["id"] = str(uuid5(NAMESPACE, hashlib.sha256(encoded).hexdigest()))
    return row
