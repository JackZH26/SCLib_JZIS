"""All-or-nothing embeddings with explicit per-input completion reports.

Local cl100k counts size requests; they do not prove provider tokenization.
No chunk receives a new embedding or report until all batches validate.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Iterable

from google import genai
from google.genai import types as genai_types

from ingestion.chunk.chunker import count_tokens
from ingestion.config import get_settings
from ingestion.embedding_contract import (
    LOCAL_DOCUMENT_COUNT_METHOD,
    LOCAL_DOCUMENT_INPUT_LIMIT,
    LOCAL_DOCUMENT_REQUEST_LIMIT,
    PROVIDER_INPUT_COUNT_LIMIT,
    EmbeddingCompletenessError,
    validate_embedding_inputs,
    validate_embedding_response,
    validate_profile,
)
from ingestion.genai_client import make_genai_client
from ingestion.models import Chunk

log = logging.getLogger(__name__)

_MAX_TOKENS_PER_REQUEST = LOCAL_DOCUMENT_REQUEST_LIMIT
_MAX_INPUTS_PER_REQUEST = PROVIDER_INPUT_COUNT_LIMIT


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    return make_genai_client()


def _arguments(settings, task_type, counts):
    return {
        "model": settings.embedding_model,
        "dimension": settings.embedding_output_dimensionality,
        "task_type": task_type,
        "local_counts": counts,
        "local_count_method": LOCAL_DOCUMENT_COUNT_METHOD,
        "local_input_limit": LOCAL_DOCUMENT_INPUT_LIMIT,
        "local_request_limit": _MAX_TOKENS_PER_REQUEST,
    }


def _embed(texts, settings, *, task_type):
    arguments = _arguments(settings, task_type, [count_tokens(value) for value in texts])
    validate_embedding_inputs(texts, **arguments)
    config = genai_types.EmbedContentConfig(
        task_type=task_type,
        output_dimensionality=settings.embedding_output_dimensionality,
        auto_truncate=False,
    )
    if getattr(config, "auto_truncate", None) is not False:
        raise EmbeddingCompletenessError("Embedding SDK cannot disable input truncation")
    try:
        out = _client().models.embed_content(model=settings.embedding_model, contents=texts, config=config)
    except Exception:
        # Provider exception strings may contain request bodies or credentials.
        raise EmbeddingCompletenessError("Embedding provider request failed") from None
    return validate_embedding_response(texts, out, **arguments)


def embed_chunks(chunks: list[Chunk]) -> None:
    """Publish embeddings/reports only after the entire input set validates.

    Failure leaves every pre-existing vector/report unchanged. An in-memory
    completion report must not be interpreted as an upload receipt.
    """
    if type(chunks) is not list or any(type(chunk) is not Chunk for chunk in chunks):
        raise EmbeddingCompletenessError("An explicit document chunk list is required")
    if not chunks:
        return
    settings = get_settings()
    validate_profile(model=settings.embedding_model, dimension=settings.embedding_output_dimensionality,
                     task_type="RETRIEVAL_DOCUMENT")
    snapshots = [(chunk, chunk.id, chunk.text) for chunk in chunks]
    if any(type(identifier) is not str or not 1 <= len(identifier) <= 200 for _, identifier, _ in snapshots):
        raise EmbeddingCompletenessError("A bounded document embedding identity is required")
    if len({identifier for _, identifier, _ in snapshots}) != len(chunks):
        raise EmbeddingCompletenessError("Duplicate document embedding identities are not supported")
    # Materialize the entire validated inventory before the first provider call.
    batches = list(_batched_by_tokens(chunks, max_inputs=settings.embed_batch_size))
    completed = []
    for batch in batches:
        completed.extend(_embed([chunk.text for chunk in batch], settings, task_type="RETRIEVAL_DOCUMENT"))
        log.info("validated embedding batch of %d chunks", len(batch))
    if len(completed) != len(chunks) or any(
            chunk.id != identifier or chunk.text != original_text for chunk, identifier, original_text in snapshots):
        raise EmbeddingCompletenessError("Document embedding inputs changed before completion")
    for (chunk, _, _), (vector, metadata) in zip(snapshots, completed, strict=True):
        chunk.embedding = vector
        chunk.embedding_provenance = metadata


def embed_query(text: str) -> list[float]:
    """Query task stays distinct from document indexing, with identical checks."""
    settings = get_settings()
    validate_profile(model=settings.embedding_model, dimension=settings.embedding_output_dimensionality,
                     task_type="RETRIEVAL_QUERY")
    return _embed([text], settings, task_type="RETRIEVAL_QUERY")[0][0]


def _batched_by_tokens(chunks: list[Chunk], *, max_inputs: int = PROVIDER_INPUT_COUNT_LIMIT) -> Iterable[list[Chunk]]:
    """Reject oversized full texts; never send them for silent truncation."""
    if type(max_inputs) is not int or not 1 <= max_inputs <= _MAX_INPUTS_PER_REQUEST:
        raise EmbeddingCompletenessError("Invalid local embedding batch size")
    batch: list[Chunk] = []
    batch_tokens = 0
    for chunk in chunks:
        count = count_tokens(chunk.text)
        # Recount the final text; a cached chunk.token_count is not authoritative.
        validate_embedding_inputs([chunk.text], model="text-embedding-005", dimension=768,
            task_type="RETRIEVAL_DOCUMENT", local_counts=[count],
            local_count_method=LOCAL_DOCUMENT_COUNT_METHOD, local_input_limit=LOCAL_DOCUMENT_INPUT_LIMIT,
            local_request_limit=_MAX_TOKENS_PER_REQUEST)
        if batch and (batch_tokens + count > _MAX_TOKENS_PER_REQUEST or len(batch) >= max_inputs):
            yield batch
            batch, batch_tokens = [], 0
        batch.append(chunk)
        batch_tokens += count
    if batch:
        yield batch
