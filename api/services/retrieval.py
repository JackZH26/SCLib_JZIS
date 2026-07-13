"""PostgreSQL lexical retrieval, rank fusion, and deterministic reranking."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Chunk, Paper

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+_.-]*")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "that", "the", "this",
    "to", "was", "what", "when", "where", "which", "with",
}


@dataclass(slots=True, frozen=True)
class LexicalHit:
    chunk_id: str
    score: float


@dataclass(slots=True, frozen=True)
class RankedCandidate:
    chunk_id: str
    fusion_score: float
    vector_score: float | None
    lexical_score: float | None
    retrieval_modes: tuple[str, ...]
    rerank_score: float = 0.0


async def lexical_search(
    db: AsyncSession,
    query_text: str,
    *,
    limit: int,
    year_min: int | None = None,
    year_max: int | None = None,
    exclude_retracted: bool = True,
) -> list[LexicalHit]:
    """Run bounded PostgreSQL web-style full-text search over title + chunk."""
    config = literal_column("'english'::regconfig")
    document = func.to_tsvector(
        config,
        func.coalesce(Chunk.title, "") + " " + Chunk.text,
    )
    query = func.websearch_to_tsquery(config, query_text)
    rank = func.ts_rank_cd(document, query)
    stmt = select(Chunk.id, rank.label("rank")).join(Paper, Paper.id == Chunk.paper_id)
    stmt = stmt.where(document.op("@@")(query))
    if exclude_retracted:
        stmt = stmt.where(Paper.status != "retracted")
    if year_min is not None:
        stmt = stmt.where(Chunk.year >= year_min)
    if year_max is not None:
        stmt = stmt.where(Chunk.year <= year_max)
    stmt = stmt.order_by(rank.desc(), Chunk.id.asc()).limit(max(1, min(limit, 300)))
    rows = (await db.execute(stmt)).all()
    return [LexicalHit(chunk_id=row.id, score=float(row.rank or 0.0)) for row in rows]


def fuse_rankings(
    vector_hits: list[tuple[str, float]],
    lexical_hits: list[LexicalHit],
    *,
    limit: int,
    rrf_k: int = 60,
) -> list[RankedCandidate]:
    """Fuse semantic and lexical ranks with Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    vector_scores: dict[str, float] = {}
    lexical_scores: dict[str, float] = {}
    modes: dict[str, set[str]] = {}

    for rank, (chunk_id, score) in enumerate(vector_hits, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
        vector_scores[chunk_id] = max(score, vector_scores.get(chunk_id, float("-inf")))
        modes.setdefault(chunk_id, set()).add("vector")
    for rank, hit in enumerate(lexical_hits, start=1):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rrf_k + rank)
        lexical_scores[hit.chunk_id] = max(
            hit.score, lexical_scores.get(hit.chunk_id, float("-inf"))
        )
        modes.setdefault(hit.chunk_id, set()).add("lexical")

    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    return [
        RankedCandidate(
            chunk_id=chunk_id,
            fusion_score=scores[chunk_id],
            vector_score=vector_scores.get(chunk_id),
            lexical_score=lexical_scores.get(chunk_id),
            retrieval_modes=tuple(sorted(modes[chunk_id])),
        )
        for chunk_id in ordered[:limit]
    ]


def rerank_candidates(
    query_text: str,
    candidates: list[RankedCandidate],
    chunk_by_id: dict[str, Chunk],
) -> list[RankedCandidate]:
    """Apply a transparent lexical-coverage reranker after rank fusion."""
    if not candidates:
        return []
    terms = _terms(query_text)
    max_fusion = max(candidate.fusion_score for candidate in candidates) or 1.0
    reranked: list[RankedCandidate] = []
    for candidate in candidates:
        chunk = chunk_by_id.get(candidate.chunk_id)
        if chunk is None:
            continue
        text_terms = _terms(f"{chunk.title or ''} {chunk.text}")
        title_terms = _terms(chunk.title or "")
        coverage = len(terms & text_terms) / max(1, len(terms))
        title_coverage = len(terms & title_terms) / max(1, len(terms))
        score = (
            0.72 * (candidate.fusion_score / max_fusion)
            + 0.20 * coverage
            + 0.08 * title_coverage
        )
        reranked.append(
            RankedCandidate(
                chunk_id=candidate.chunk_id,
                fusion_score=candidate.fusion_score,
                vector_score=candidate.vector_score,
                lexical_score=candidate.lexical_score,
                retrieval_modes=candidate.retrieval_modes,
                rerank_score=score,
            )
        )
    return sorted(reranked, key=lambda item: (-item.rerank_score, item.chunk_id))


def _terms(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if token.lower() not in _STOPWORDS and len(token) > 1
    }
