"""Small, text-free observations of one pipeline input-preparation attempt.

These describe local full-text counts and validated response metadata, not
provider billing, vector delivery, an active index, corpus coverage or recall.
The helpers perform no IO and never copy source text, identifiers, vectors,
raw receipts or exception messages into the returned fixed-shape summaries.
"""
from __future__ import annotations

import math

from ingestion.chunk.chunker import count_tokens
from ingestion.embedding_contract import (
    LOCAL_DOCUMENT_COUNT_METHOD,
    validate_embedding_provenance,
    validate_vector,
)

VERSION = "sclib-input-observation/1.0.0"
_STATUSES = {"not_attempted", "returned", "failed", "skipped"}
_REASONS = {None, "chunk_stage_failed", "embedding_stage_failed", "no_chunks_produced",
            "atomic_fact_exceeds_complete_text_limit", "dry_run", "vector_search_skipped"}


def _duration_ms(seconds):
    if type(seconds) not in {int, float} or not 0 <= seconds <= 604800:
        return None
    if not math.isfinite(seconds):
        return None
    return round(seconds * 1000, 3)


def _stage(status, duration_seconds, reason_code):
    if type(status) is not str or status not in _STATUSES:
        raise ValueError("Unsupported input-observation stage status")
    if reason_code is not None and (type(reason_code) is not str or reason_code not in _REASONS):
        raise ValueError("Unsupported input-observation reason code")
    return {"stage_status": status, "duration_ms": _duration_ms(duration_seconds),
            "reason_code": reason_code}


def _actual_count(chunk):
    text = getattr(chunk, "text", None)
    try:
        if type(text) is not str or len(text.encode("utf-8", errors="strict")) > 1048576:
            return None
        return count_tokens(text)
    except (ValueError, TypeError, UnicodeError):
        return None


def observe_chunks(chunks=None, *, status="not_attempted", duration_seconds=None,
                   reason_code=None):
    """Measure complete strings, ignoring potentially stale Chunk.token_count."""
    result = {**_stage(status, duration_seconds, reason_code),
              "count": None, "local_count_method": LOCAL_DOCUMENT_COUNT_METHOD,
              "measurement_status": "unavailable", "local_token_total": None,
              "local_token_max": None}
    if type(chunks) not in {list, tuple}:
        return result
    result["count"] = len(chunks)
    counts = [_actual_count(chunk) for chunk in chunks]
    if all(count is not None for count in counts):
        result.update(measurement_status="complete", local_token_total=sum(counts),
                      local_token_max=max(counts, default=0))
    return result


def observe_embeddings(chunks=None, *, status="not_attempted", duration_seconds=None,
                       reason_code=None):
    """Count only exact current text/vector-bound, count-verified receipts.

    The provider-token total covers validated inputs only. For partial reports
    it is not the attempt's provider total; absent reports never imply zero
    provider usage or zero cost. A returned mock call is not completion proof.
    """
    result = {**_stage(status, duration_seconds, reason_code),
              "input_count": None, "completeness_status": "unavailable",
              "validated_complete_count": None, "unavailable_count": None,
              "invalid_count": None, "provider_token_total_for_validated_inputs": None}
    if type(chunks) not in {list, tuple}:
        return result
    result.update(input_count=len(chunks), unavailable_count=len(chunks))
    # A failed embed call deliberately preserves previous chunk fields. Those
    # may describe an older response and must never be charged to this attempt.
    if status != "returned":
        return result
    complete, unavailable, invalid, provider_tokens = 0, 0, 0, 0
    for chunk in chunks:
        receipt = getattr(chunk, "embedding_provenance", None)
        if receipt is None:
            unavailable += 1
            continue
        try:
            vector = validate_vector(getattr(chunk, "embedding", None))
            metadata = validate_embedding_provenance(
                receipt, text=getattr(chunk, "text", None), vector=vector,
                expected_task="RETRIEVAL_DOCUMENT",
            )
            actual_count = _actual_count(chunk)
            if (actual_count is None or metadata["local_count_method"] != LOCAL_DOCUMENT_COUNT_METHOD
                    or metadata["local_count"] != actual_count):
                raise ValueError("Current document count is not verified")
        except (ValueError, TypeError, UnicodeError):
            invalid += 1
            continue
        complete += 1
        provider_tokens += metadata["provider_token_count"]
    availability = "complete" if chunks and complete == len(chunks) else "unavailable"
    if complete and complete < len(chunks):
        availability = "partial"
    result.update(completeness_status=availability, validated_complete_count=complete,
                  unavailable_count=unavailable, invalid_count=invalid,
                  provider_token_total_for_validated_inputs=provider_tokens if complete else None)
    return result


def new_input_observation():
    return {"version": VERSION, "scope": "input_preparation_only",
            "chunk": observe_chunks(), "embedding": observe_embeddings(),
            "cost": {"status": "unknown", "amount": None, "currency": None}}
