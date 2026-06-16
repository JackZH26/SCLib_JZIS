"""Batch text embeddings via Google Gen AI ``text-embedding-005``.

text-embedding-005 caps each request at **20,000 input tokens total**
across all inputs in the batch. A single 512-token chunk is fine, but
100 chunks × ~500 tokens would blow the limit (~50k). So we pack
batches by cumulative token count, not by fixed size. We also cap the
number of inputs per request at 250 (the SDK's hard limit).

Task type ``RETRIEVAL_DOCUMENT`` is used for indexing; queries issued by
the API router should use ``RETRIEVAL_QUERY``.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Iterable

from google import genai
from google.genai import types as genai_types

from ingestion.chunk.chunker import count_tokens
from ingestion.config import get_settings
from ingestion.genai_client import make_genai_client
from ingestion.models import Chunk

log = logging.getLogger(__name__)

# text-embedding-005 enforces a 20k input-token cap per request using its
# own SentencePiece tokenizer. We measure with cl100k_base (from tiktoken)
# because we already use it in the chunker — but cl100k undercounts
# SentencePiece by up to ~15% on scientific text (observed during Phase 2
# smoke: cl100k=18000 → server=20680). Set the budget to 14k cl100k tokens
# to leave a healthy ~30% margin. Still packs ~27× 512-token chunks per
# request, which keeps the batch count reasonable.
_MAX_TOKENS_PER_REQUEST = 14000
_MAX_INPUTS_PER_REQUEST = 250


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    return make_genai_client()


def embed_chunks(chunks: list[Chunk]) -> None:
    """Mutates each chunk in-place, populating ``.embedding``."""
    if not chunks:
        return
    settings = get_settings()

    for batch in _batched_by_tokens(chunks):
        out = _client().models.embed_content(
            model=settings.embedding_model,
            contents=[c.text for c in batch],
            config=genai_types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=settings.embedding_output_dimensionality,
            ),
        )
        embeddings = out.embeddings or []
        if len(embeddings) != len(batch):
            raise RuntimeError(
                f"Embedding API returned {len(embeddings)} embeddings for "
                f"{len(batch)} inputs"
            )
        for chunk, emb in zip(batch, embeddings):
            chunk.embedding = list(emb.values)
        log.info("embedded batch of %d chunks", len(batch))


def embed_query(text: str) -> list[float]:
    """One-shot embedding for API search-time use."""
    settings = get_settings()
    out = _client().models.embed_content(
        model=settings.embedding_model,
        contents=[text],
        config=genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=settings.embedding_output_dimensionality,
        ),
    )
    embeddings = out.embeddings or []
    if not embeddings:
        raise RuntimeError("Embedding API returned no query embedding")
    return list(embeddings[0].values)


def _batched_by_tokens(chunks: list[Chunk]) -> Iterable[list[Chunk]]:
    """Yield sub-lists whose total token count stays under the per-request cap."""
    batch: list[Chunk] = []
    batch_tokens = 0
    for c in chunks:
        n = count_tokens(c.text)
        # A single chunk larger than the cap is truncated server-side
        # anyway — send it alone rather than stalling the loop.
        if n >= _MAX_TOKENS_PER_REQUEST:
            if batch:
                yield batch
                batch, batch_tokens = [], 0
            yield [c]
            continue
        if (
            batch_tokens + n > _MAX_TOKENS_PER_REQUEST
            or len(batch) >= _MAX_INPUTS_PER_REQUEST
        ):
            yield batch
            batch, batch_tokens = [], 0
        batch.append(c)
        batch_tokens += n
    if batch:
        yield batch
