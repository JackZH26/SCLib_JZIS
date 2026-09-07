"""arXiv observation diagnostics, not authoritative temporal witnesses.

The artifact digest and the assembled NER document digest have different bases.
OAI title/abstract are unversioned even when the downloaded body selects vN.
Never infer scientific availability from these observations or work dates.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from ingestion.models import ParsedPaper

CAPTURE_VERSION = "arxiv-ingestion-capture/1.0.0"


def _bounded_datetime(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.isoformat() if parsed.tzinfo is not None else None


def build_ingestion_capture(
    parsed: ParsedPaper, *, ner_input: str | None, document_char_limit: int = 16_000,
) -> dict[str, Any]:
    meta = parsed.meta
    record_digest = meta.metadata_sha256
    if not isinstance(record_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", record_digest):
        record_digest = None
    modified = meta.metadata_modified_date
    datestamp = meta.metadata_datestamp
    if not isinstance(datestamp, str) or len(datestamp) > 32:
        datestamp = None
    if datestamp is not None:
        try:
            datetime.fromisoformat(datestamp)
        except ValueError:
            datestamp = None
    # The text-only payload digest is distinct from the original XML record.
    metadata_text = json.dumps({"title": meta.title, "abstract": meta.abstract},
                               ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # material_ner._build_prompt slices by characters, not encoded byte length.
    document = ner_input[:document_char_limit] if ner_input is not None else None
    input_bytes = document.encode("utf-8") if document is not None else None
    artifact = parsed.ingestion_capture.get("artifact")
    offset = len(f"Title: {meta.title}\n\nAbstract: {meta.abstract}")
    sections_used = 0
    for section in parsed.sections[:8]:
        offset += len("\n\n")
        if document is not None and len(document) > offset:
            sections_used += 1
        offset += len(f"\n## {section.name}\n{section.text}")
    uses_body = sections_used > 0
    return {
        "version": CAPTURE_VERSION,
        "canonical_paper_id": meta.paper_id,
        "requested_version": meta.requested_version,
        "captured_at": datetime.now(UTC).isoformat(),
        "artifact": artifact,
        "metadata": {
            "record_sha256": record_digest,
            "record_hash_basis": "elementtree-record-serialization/1" if record_digest else None,
            "text_sha256": hashlib.sha256(metadata_text.encode("utf-8")).hexdigest(),
            "text_hash_basis": "title-abstract-json-utf8/1",
            "captured_at": _bounded_datetime(meta.metadata_captured_at),
            "modified_date": modified.isoformat() if modified else None,
            "oai_datestamp": datestamp,
            "version_status": "unversioned_metadata",
        },
        "ner_input": {
            "sha256": hashlib.sha256(input_bytes).hexdigest() if input_bytes is not None else None,
            "byte_length": len(input_bytes) if input_bytes is not None else None,
            "representation": "material-ner-document-text/1",
            "document_char_limit": document_char_limit,
            "truncated": ner_input is not None and len(ner_input) > document_char_limit,
            "assembled_sha256": hashlib.sha256(ner_input.encode("utf-8")).hexdigest()
            if ner_input is not None else None,
            "sections_used": sections_used,
            "input_binding": "mixed_unverified" if uses_body else "metadata_only",
            "artifact_used": uses_body,
            "status": "attempted" if input_bytes is not None else "not_run",
        },
        "scientific_available_at": None,
        "temporal_status": "unknown",
        "reason_codes": ["result_occurrence_not_bound_to_verified_revision",
                         "oai_metadata_not_version_pinned"],
    }
