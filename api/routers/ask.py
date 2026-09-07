"""POST /ask — grounded retrieval-augmented Q&A.

The hybrid retrieval path fuses Vertex ANN and PostgreSQL full-text results,
reranks them, and admits no more than one source per paper. Source excerpts are
passed to Gemini as explicitly untrusted data with a strict citation contract.
Provider failures degrade to lexical retrieval and an extractive answer.

The shape of `sources` in the response maps 1:1 to the [n] markers
Gemini emits — frontend just hyperlinks each bracket to the paper.
"""
from __future__ import annotations

import asyncio
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
from services import provider_resilience, rag, retrieval, retrieval_currentness, vector_search
from services.authors import short as _authors_short
from services.metrics import observe_rag
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import (
    citation_evidence,
    project_source_occurrences,
    resolve_explicit_materials,
    source_visibility,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["ask"])
EVIDENCE_RESOLUTION_TIMEOUT_SECONDS = 10.0


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    identity: Identity = Depends(require_identity),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> AskResponse:
    t0 = time.perf_counter()
    # The catalogue read transaction is closed before provider generation.
    # Retain primitives, not an ORM User that rollback would expire.
    history_user_id = identity.user.id if identity.user is not None else None

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
        result = rag.no_source_result()
        observe_rag(
            sources=0, tokens=0, citation_valid=result.citation_valid, fallback=False,
            citation_indices_valid=result.citation_indices_valid,
            scientific_support_status=result.scientific_support_status, answer_mode=result.answer_mode,
        )
        if history_user_id is not None:
            await _persist_history(
                db, history_user_id, body.question, result.answer,
                [], 0, latency_ms, body.language,
            )
        return AskResponse(
            answer=result.answer,
            sources=[],
            tokens_used=0,
            query_time_ms=latency_ms,
            **result.quality_fields(),
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
    linked_materials = await resolve_explicit_materials(db, [chunk.materials_mentioned for chunk in rows])
    source_statuses = await resolve_paper_lifecycle(db, {chunk.paper_id for chunk in rows})
    evidence_failure_reason = None
    try:
        evidence_by_chunk = await _resolve_evidence(db, rows)
    except TimeoutError:
        log.warning("Ask typed evidence resolution timed out; selected text withheld")
        evidence_by_chunk = None
        evidence_failure_reason = "retrieval_currentness_timeout"
    except Exception:  # no raw error/source payload reaches the answer
        log.warning("Ask typed evidence resolution unavailable; selected text withheld")
        evidence_by_chunk = None
        evidence_failure_reason = "retrieval_currentness_unavailable"

    rag_inputs: list[rag.RagSourceInput] = []
    sources_out: list[AskSource] = []
    selected_pins: list[retrieval_currentness.SelectionPin] = []
    pin_unavailable = evidence_by_chunk is None
    seen_papers: set[str] = set()
    idx = 0
    for candidate in candidates:
        if pin_unavailable:
            break
        chunk = chunk_by_id.get(candidate.chunk_id)
        if chunk is None or chunk.paper is None:
            continue
        evidence = evidence_by_chunk[chunk.id]
        # Never send or quote a known-restricted/stale evidence projection.
        # Other unresolved lineage is navigation data, not original support.
        if evidence["permission_status"] == "restricted" or evidence["currentness"] == "stale":
            continue
        paper_status = source_statuses.get(chunk.paper.id)
        if not source_visibility(paper_status)["reported_claim_filter_eligible"]:
            continue
        if chunk.paper.id in seen_papers:
            continue
        seen_papers.add(chunk.paper.id)
        idx += 1
        paper = chunk.paper
        authors_short = _authors_short(paper.authors or [])
        year = paper.date_submitted.year if paper.date_submitted else None
        occurrences, occurrence_summary = project_source_occurrences(
            chunk.materials_mentioned, paper_status=paper_status, linked_materials=linked_materials,
        )
        source_review = source_visibility(paper_status)
        source_review["warning_codes"] = sorted(set(source_review["warning_codes"] + occurrence_summary["warning_codes"]))
        try:
            selected_pins.append(retrieval_currentness.selection_pin(
                chunk, material_evidence=occurrences, source_review=source_review, evidence=evidence,
            ))
        except retrieval_currentness.CurrentnessUnavailable:
            pin_unavailable = True
            break
        rag_inputs.append(
            rag.RagSourceInput(
                index=idx,
                paper_id=paper.id,
                title=paper.title,
                authors_short=authors_short,
                year=year,
                section=chunk.section,
                text=chunk.text,
                material_evidence=occurrences,
                source_visibility=source_review,
                visibility_resolved=True,
                evidence_provenance=evidence,
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
                material_evidence=citation_evidence(occurrences, visibility_resolved=True),
                source_visibility=source_review,
                evidence_provenance=evidence,
            )
        )
        if len(rag_inputs) >= body.max_sources:
            break

    # No transaction, snapshot or table locks span a potentially slow provider
    # call. API-key accounting has already committed in require_identity.
    await db.rollback()
    if pin_unavailable:
        rag_inputs, sources_out, selected_pins = [], [], []

    # 3. Gemini call behind a timeout + circuit breaker. A provider outage
    # degrades to cited excerpts instead of turning the whole endpoint into 5xx.
    try:
        if not rag_inputs:
            result = rag.no_source_result()
        else:
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

    # A seal only checks in-memory consistency. Re-read selected catalogue
    # inputs in a new bounded snapshot before accepting that provisional seal.
    currentness = (await retrieval_currentness.check_selected_sources(selected_pins, evidence_resolver=_resolve_evidence)
                   if rag_inputs else None)
    if pin_unavailable or currentness is not None and currentness.status != "unchanged":
        reason = (currentness.reason_code if currentness is not None
                  else evidence_failure_reason or "retrieval_currentness_unavailable")
        tokens_used = result.tokens_used if isinstance(result, rag.RagResult) else None
        # Never pass an already replaced fallback through the draft checker
        # again. No old excerpt, source label, or draft assessment is retained.
        result = _currentness_abstention(reason, tokens_used)
        rag_inputs, sources_out = [], []
    else:
        # Alternate/legacy generators still cannot bypass server checks. Stable
        # sources preserve the existing seal and original draft assessment.
        result = rag.finalize_result(result, rag_inputs)

    retrieval_modes = sorted(
        {mode for candidate in candidates for mode in candidate.retrieval_modes}
    )
    log.info(
        "rag_quality sources=%d papers=%d retrieval=%s citation_valid=%s warnings=%s indices_valid=%s support=%s mode=%s",
        len(rag_inputs),
        len(seen_papers),
        "+".join(retrieval_modes) or "none",
        result.citation_valid,
        ",".join(result.citation_warnings) or "none",
        result.citation_indices_valid,
        result.scientific_support_status,
        result.answer_mode,
    )
    observe_rag(
        sources=len(rag_inputs),
        tokens=result.tokens_used,
        citation_valid=result.citation_valid,
        fallback="generation_provider_unavailable" in result.citation_warnings,
        citation_indices_valid=result.citation_indices_valid,
        scientific_support_status=result.scientific_support_status,
        answer_mode=result.answer_mode,
    )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    if history_user_id is not None:
        await _persist_history(
            db, history_user_id, body.question, result.answer,
            [s.model_dump(mode="json") for s in sources_out],
            result.tokens_used, latency_ms, body.language,
        )

    return AskResponse(
        answer=result.answer,
        sources=sources_out,
        tokens_used=result.tokens_used,
        query_time_ms=latency_ms,
        **result.quality_fields(),
        guest_remaining=identity.guest_remaining,
        remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
    )


async def _resolve_evidence(db, chunks):
    """One strict resolver path for initial hydration and the fresh snapshot."""
    from services.rag_evidence import resolve_chunk_evidence
    from services.rag_evidence_contract import validate_evidence_descriptor

    async with asyncio.timeout(EVIDENCE_RESOLUTION_TIMEOUT_SECONDS):
        resolved = await resolve_chunk_evidence(db, chunks)
        if not isinstance(resolved, dict) or set(resolved) != {chunk.id for chunk in chunks}:
            raise retrieval_currentness.CurrentnessUnavailable("incomplete typed evidence inventory")
        return {identifier: validate_evidence_descriptor(value) for identifier, value in resolved.items()}


def _currentness_abstention(reason: str, tokens_used: int | None) -> rag.RagResult:
    return rag.RagResult(
        answer="The selected evidence changed or could not be checked. "
               "No synthesized answer or old excerpt is provided. Please ask again to retrieve current sources.",
        tokens_used=tokens_used, citation_valid=False, citation_warnings=[reason],
        citation_indices_valid=True, support_warnings=[reason],
        answer_mode="abstention", assessment_scope="none",
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
