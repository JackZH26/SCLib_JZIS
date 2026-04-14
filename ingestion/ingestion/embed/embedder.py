"""Batch text embeddings via Vertex AI ``text-embedding-005``.

The Vertex SDK's ``TextEmbeddingModel.get_embeddings`` accepts up to 250
inputs per request, but we default to 100 to keep payloads under the
gRPC message size limit when chunks are long.

Task type ``RETRIEVAL_DOCUMENT`` is used for indexing; queries issued by
the API router should use ``RETRIEVAL_QUERY``.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Iterable

from google.cloud import aiplatform
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel
import vertexai

from ingestion.config import get_settings
from ingestion.models import Chunk

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _model() -> TextEmbeddingModel:
    settings = get_settings()
    vertexai.init(project=settings.gcp_project, location=settings.gcp_region)
    aiplatform.init(project=settings.gcp_project, location=settings.gcp_region)
    return TextEmbeddingModel.from_pretrained(settings.embedding_model)


def embed_chunks(chunks: list[Chunk]) -> None:
    """Mutates each chunk in-place, populating ``.embedding``."""
    if not chunks:
        return
    settings = get_settings()
    batch_size = settings.embed_batch_size
    model = _model()

    for batch in _batched(chunks, batch_size):
        inputs = [
            TextEmbeddingInput(text=c.text, task_type="RETRIEVAL_DOCUMENT")
            for c in batch
        ]
        # output_dimensionality defaults to 768 for text-embedding-005.
        out = model.get_embeddings(inputs)
        for chunk, emb in zip(batch, out):
            chunk.embedding = list(emb.values)
        log.info("embedded batch of %d chunks", len(batch))


def embed_query(text: str) -> list[float]:
    """One-shot embedding for API search-time use."""
    model = _model()
    out = model.get_embeddings(
        [TextEmbeddingInput(text=text, task_type="RETRIEVAL_QUERY")]
    )
    return list(out[0].values)


def _batched(seq: list[Chunk], n: int) -> Iterable[list[Chunk]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]
