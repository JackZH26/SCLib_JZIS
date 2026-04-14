"""Query-time Vector Search client.

Wraps Vertex AI text-embedding-005 (for query embedding) and the
Matching Engine endpoint (for ANN lookup). The ingestion pipeline
lives in a separate process and imports ``ingestion.embed.embedder``;
here in the API we deliberately re-implement the thin query path so
the two packages stay decoupled (the API process would otherwise have
to import ingestion's pyproject, SQL Core table defs, etc).

Lazy-initialized singletons so import-time startup stays cheap and
tests can run without touching GCP.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from google.cloud import aiplatform
from google.cloud.aiplatform.matching_engine.matching_engine_index_endpoint import (
    MatchingEngineIndexEndpoint,
    Namespace,
    NumericNamespace,
)
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel
import vertexai

from config import get_settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy clients
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _embed_model() -> TextEmbeddingModel:
    settings = get_settings()
    vertexai.init(project=settings.gcp_project, location=settings.gcp_region)
    aiplatform.init(project=settings.gcp_project, location=settings.gcp_region)
    return TextEmbeddingModel.from_pretrained(settings.embedding_model)


@lru_cache(maxsize=1)
def _endpoint() -> MatchingEngineIndexEndpoint:
    settings = get_settings()
    if not settings.vertex_ai_index_endpoint:
        raise RuntimeError(
            "VERTEX_AI_INDEX_ENDPOINT is not configured on this API instance"
        )
    aiplatform.init(project=settings.gcp_project, location=settings.gcp_region)
    return MatchingEngineIndexEndpoint(
        index_endpoint_name=settings.vertex_ai_index_endpoint
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Neighbor:
    chunk_id: str
    distance: float  # lower = closer (cosine distance = 1 - cosine similarity)


def embed_query(text: str) -> list[float]:
    """One-shot query embedding for semantic search.

    Uses task_type=RETRIEVAL_QUERY so the vector lands in the same
    semantic space the ingestion pipeline indexed with RETRIEVAL_DOCUMENT.
    """
    out = _embed_model().get_embeddings(
        [TextEmbeddingInput(text=text, task_type="RETRIEVAL_QUERY")]
    )
    return list(out[0].values)


def find_neighbors(
    embedding: list[float],
    *,
    top_k: int = 20,
    year_min: int | None = None,
    year_max: int | None = None,
    material_family: list[str] | None = None,
) -> list[Neighbor]:
    """Run a filtered ANN query against Vertex VS.

    Restricts map to the namespaces the indexer writes in
    ``ingestion.index.indexer.upsert_chunks_to_vector_search``:

    * numeric ``year`` (int)
    * categorical ``material_family`` (string, future work — ingestion
      doesn't populate this yet, so the filter is a no-op today but
      the plumbing is ready for Phase 5).
    """
    settings = get_settings()

    numeric: list[NumericNamespace] = []
    if year_min is not None:
        numeric.append(NumericNamespace(name="year", value_int=year_min, op="GREATER_EQUAL"))
    if year_max is not None:
        numeric.append(NumericNamespace(name="year", value_int=year_max, op="LESS_EQUAL"))

    cat: list[Namespace] = []
    if material_family:
        cat.append(Namespace(name="material_family", allow_tokens=material_family))

    resp = _endpoint().find_neighbors(
        deployed_index_id=settings.vertex_ai_deployed_index_id,
        queries=[embedding],
        num_neighbors=top_k,
        filter=cat or None,
        numeric_filter=numeric or None,
    )
    if not resp:
        return []
    return [Neighbor(chunk_id=r.id, distance=r.distance) for r in resp[0]]


def find_neighbors_many(
    embeddings: list[list[float]],
    *,
    top_k: int = 10,
) -> list[list[Neighbor]]:
    """Batch variant used by /similar/{paper_id} — one query per chunk
    vector, merged at the caller."""
    settings = get_settings()
    resp = _endpoint().find_neighbors(
        deployed_index_id=settings.vertex_ai_deployed_index_id,
        queries=embeddings,
        num_neighbors=top_k,
    )
    return [
        [Neighbor(chunk_id=r.id, distance=r.distance) for r in row]
        for row in resp
    ]


def dispose() -> None:
    """Clear cached clients. Called from tests."""
    _embed_model.cache_clear()
    _endpoint.cache_clear()


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def chunk_id_to_paper_id(chunk_id: str) -> str:
    """Datapoint IDs look like ``arxiv:2306.07275_chunk_012``. Strip the
    chunk suffix to get the paper id the API surfaces to clients.
    """
    if "_chunk_" in chunk_id:
        return chunk_id.rsplit("_chunk_", 1)[0]
    return chunk_id
