"""POST /ask — grounded retrieval-augmented Q&A.

The hybrid retrieval path fuses Vertex ANN and PostgreSQL full-text results,
reranks them, and admits no more than one source per paper. Source excerpts are
passed to Gemini as explicitly untrusted data with a strict citation contract.
Provider failures degrade to lexical retrieval and an extractive answer.

The shape of `sources` in the response maps 1:1 to the [n] markers
Gemini emits — frontend just hyperlinks each bracket to the paper.
"""
from __future__ import annotations

import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import get_settings
from models import get_db
from models.db import AskHistory, Chunk
from models.search import AskRequest, AskResponse, AskSource
from routers.deps import Identity, require_identity
from services import provider_resilience, rag, retrieval, vector_search
from services.authors import short as _authors_short

log = logging.getLogger(__name__)

router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    identity: Identity = Depends(require_identity),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> AskResponse:
    t0 = time.perf_counter()

    # 1. Retrieve candidate chunks via ANN.
    def _vs_lookup() -> list[vector_search.Neighbor]:
        vec = vector_search.embed_query(body.question)
        return vector_search.find_neighbors(
            vec,
            top_k=min(body.max_sources * 4, 80),
        )

    settings = get_settings()
    try:
        neighbors = await provider_resilience.run_blocking(
            "vector_search",
            _vs_lookup,
            timeout_seconds=settings.vector_search_timeout_seconds,
            max_attempts=settings.provider_max_attempts,
            failure_threshold=settings.provider_circuit_failure_threshold,
            cooldown_seconds=settings.provider_circuit_cooldown_seconds,
        )
    except provider_resilience.ProviderUnavailable as exc:
        log.warning("Ask semantic retrieval unavailable; using lexical fallback: %s", exc)
        neighbors = []

    candidate_limit = min(body.max_sources * 5, 100)
    lexical_hits = await retrieval.lexical_search(
        db,
        body.question,
        limit=candidate_limit,
    )
    candidates = retrieval.fuse_rankings(
        [(item.chunk_id, 1.0 - item.distance) for item in neighbors],
        lexical_hits,
        limit=candidate_limit,
    )
    if not candidates:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        empty_answer = "No indexed sources match this question."
        if identity.user is not None:
            await _persist_history(
                db, identity.user.id, body.question, empty_answer,
                [], 0, latency_ms, body.language,
            )
        return AskResponse(
            answer=empty_answer,
            sources=[],
            tokens_used=0,
            query_time_ms=latency_ms,
            citation_valid=True,
            citation_warnings=[],
            guest_remaining=identity.guest_remaining,
            remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
        )

    # 2. Hydrate chunks + papers from Postgres, keeping ANN order.
    # Defensive cap on the IN clause — schema already bounds max_sources,
    # but a buggy vector_search could still return a runaway list.
    MAX_IN_CLAUSE = 100
    candidates = candidates[:MAX_IN_CLAUSE]
    chunk_ids = [candidate.chunk_id for candidate in candidates]
    q = (
        select(Chunk)
        .options(selectinload(Chunk.paper))
        .where(Chunk.id.in_(chunk_ids))
    )
    rows = (await db.execute(q)).scalars().all()
    chunk_by_id = {c.id: c for c in rows}
    candidates = retrieval.rerank_candidates(body.question, candidates, chunk_by_id)

    rag_inputs: list[rag.RagSourceInput] = []
    sources_out: list[AskSource] = []
    seen_papers: set[str] = set()
    idx = 0
    for candidate in candidates:
        chunk = chunk_by_id.get(candidate.chunk_id)
        if chunk is None or chunk.paper is None:
            continue
        if chunk.paper.status == "retracted":
            continue
        if chunk.paper.id in seen_papers:
            continue
        seen_papers.add(chunk.paper.id)
        idx += 1
        paper = chunk.paper
        authors_short = _authors_short(paper.authors or [])
        year = paper.date_submitted.year if paper.date_submitted else None
        rag_inputs.append(
            rag.RagSourceInput(
                index=idx,
                paper_id=paper.id,
                title=paper.title,
                authors_short=authors_short,
                year=year,
                section=chunk.section,
                text=chunk.text,
            )
        )
        sources_out.append(
            AskSource(
                index=idx,
                paper_id=paper.id,
                arxiv_id=paper.arxiv_id,
                title=paper.title,
                authors_short=authors_short,
                year=year,
                section=chunk.section,
                snippet=_snippet(chunk.text),
            )
        )
        if len(rag_inputs) >= body.max_sources:
            break

    # 3. Gemini call behind a timeout + circuit breaker. A provider outage
    # degrades to cited excerpts instead of turning the whole endpoint into 5xx.
    try:
        result = await provider_resilience.run_blocking(
            "gemini_generation",
            lambda: rag.generate_answer(
                body.question,
                rag_inputs,
                language=body.language,
            ),
            timeout_seconds=settings.gemini_timeout_seconds,
            max_attempts=settings.provider_max_attempts,
            failure_threshold=settings.provider_circuit_failure_threshold,
            cooldown_seconds=settings.provider_circuit_cooldown_seconds,
        )
    except provider_resilience.ProviderUnavailable as exc:
        log.warning("Gemini generation unavailable; returning extractive fallback: %s", exc)
        result = rag.extractive_fallback(rag_inputs)

    retrieval_modes = sorted(
        {mode for candidate in candidates for mode in candidate.retrieval_modes}
    )
    log.info(
        "rag_quality sources=%d papers=%d retrieval=%s citation_valid=%s warnings=%s",
        len(rag_inputs),
        len(seen_papers),
        "+".join(retrieval_modes) or "none",
        result.citation_valid,
        ",".join(result.citation_warnings) or "none",
    )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    if identity.user is not None:
        await _persist_history(
            db, identity.user.id, body.question, result.answer,
            [s.model_dump(mode="json") for s in sources_out],
            result.tokens_used, latency_ms, body.language,
        )

    return AskResponse(
        answer=result.answer,
        sources=sources_out,
        tokens_used=result.tokens_used,
        query_time_ms=latency_ms,
        citation_valid=result.citation_valid,
        citation_warnings=result.citation_warnings,
        guest_remaining=identity.guest_remaining,
        remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
    )


async def _persist_history(
    db: AsyncSession,
    user_id: UUID,
    question: str,
    answer: str,
    sources: list[dict],
    tokens_used: int | None,
    latency_ms: int,
    language: str | None,
) -> None:
    """Record a single Ask interaction for the dashboard history tab.

    Failures here never fail the outer /ask response — the user already
    has their answer, and history writes are eventually-consistent with
    the 90-day prune job. We log and swallow.
    """
    try:
        db.add(AskHistory(
            user_id=user_id,
            question=question,
            answer=answer,
            sources=sources,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            language=language,
        ))
        await db.commit()
    except Exception:  # noqa: BLE001
        log.exception("ask_history write failed (non-fatal)")
        await db.rollback()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snippet(text: str, max_chars: int = 280) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
