"""POST /search — hybrid search over chunks.

Pipeline:
  1. Run the Vertex ANN retriever behind timeout/circuit-breaker isolation.
  2. Run PostgreSQL full-text retrieval so search survives a provider outage.
  3. Fuse vector and lexical ranks, then apply a deterministic query-coverage
     reranker.
  4. Hydrate Paper/Chunk rows and enforce authoritative metadata filters in
     PostgreSQL, including material families not present in the vector index.

Blocking cloud SDK calls run in a worker thread; PostgreSQL work stays on the
main event loop.
"""
from __future__ import annotations

import logging
import time
from datetime import date as _date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import get_settings
from models import get_db
from models.db import Chunk
from models.search import SearchMatch, SearchRequest, SearchResponse
from routers.deps import Identity, require_identity
from services import provider_resilience, retrieval, vector_search
from services.anomaly_review import eligible_for_property
from services.scientific_filters import ResultFilters, matching_result_references
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import (
    occurrence_visibility,
    project_source_occurrences,
    resolve_explicit_materials,
    source_visibility,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    identity: Identity = Depends(require_identity),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> SearchResponse:
    t0 = time.perf_counter()

    # 1. Embed + ANN — both blocking SDK calls, push to a worker thread.
    def _vs_lookup() -> list[vector_search.Neighbor]:
        vec = vector_search.embed_query(body.query)
        # Ask for a few extra so Postgres-side filters don't starve us.
        overfetch = min(body.top_k * 3, 100)
        return vector_search.find_neighbors(
            vec,
            top_k=overfetch,
            year_min=body.filters.year_min,
            year_max=body.filters.year_max,
            # Existing Vertex datapoints do not yet carry this namespace.
            # Enforce family against hydrated PostgreSQL metadata below so
            # requesting a family can never silently produce a fake filter.
            material_family=None,
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
        log.warning("semantic search unavailable; using PostgreSQL lexical fallback: %s", exc)
        neighbors = []

    candidate_limit = min(body.top_k * 5, 300)
    lexical_hits = await retrieval.lexical_search(
        db,
        body.query,
        limit=candidate_limit,
        year_min=body.filters.year_min,
        year_max=body.filters.year_max,
        exclude_retracted=body.filters.exclude_retracted,
    )
    candidates = retrieval.fuse_rankings(
        [(item.chunk_id, 1.0 - item.distance) for item in neighbors],
        lexical_hits,
        limit=candidate_limit,
    )
    if not candidates:
        return SearchResponse(
            total=0,
            results=[],
            query_time_ms=int((time.perf_counter() - t0) * 1000),
            guest_remaining=identity.guest_remaining,
            remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
        )

    # 2. Fetch chunks + parent papers in one round-trip. Defensive cap:
    # even though overfetch is 3x top_k (max 100), a buggy vector_search
    # implementation could return more — cap the IN clause so a runaway
    # list cannot blow out the Postgres parser.
    MAX_IN_CLAUSE = 300
    candidates = candidates[:MAX_IN_CLAUSE]
    chunk_ids = [candidate.chunk_id for candidate in candidates]

    q = (
        select(Chunk)
        .options(selectinload(Chunk.paper))
        .where(Chunk.id.in_(chunk_ids))
    )
    rows = (await db.execute(q)).scalars().all()
    chunk_by_id = {c.id: c for c in rows}
    candidates = retrieval.rerank_candidates(body.query, candidates, chunk_by_id)
    linked_materials = await resolve_explicit_materials(
        db, [chunk.paper.materials_extracted for chunk in rows if chunk.paper is not None],
    )
    source_statuses = await resolve_paper_lifecycle(db, {chunk.paper_id for chunk in rows})

    # 3. Preserve ANN ordering, apply row-level filters that don't
    #    fit in the index namespaces.
    f = body.filters
    scientific_filters = ResultFilters(
        families=tuple(f.material_family or []), tc_min=f.tc_min,
        pressure_min=f.pressure_min, pressure_max=f.pressure_max,
        ambient_only=f.ambient_only, include_unknown_pressure=f.include_unknown_pressure,
        origins=tuple(f.knowledge_origin or []), source_role=f.source_role,
        experimental_only=f.experimental_only,
    )
    matches: list[SearchMatch] = []
    seen_papers: set[str] = set()  # deduplicate: one result per paper
    for candidate in candidates:
        chunk = chunk_by_id.get(candidate.chunk_id)
        if chunk is None:
            continue  # neighbor not in Postgres (e.g. deleted)
        paper = chunk.paper
        if paper is None:
            continue
        if paper.id in seen_papers:
            continue  # already have a higher-ranked chunk from this paper
        paper_status = source_statuses.get(paper.id)
        if f.exclude_retracted and source_visibility(paper_status)["source_status"] == "retracted":
            continue
        materials, occurrence_summary = project_source_occurrences(
            paper.materials_extracted, paper_status=paper_status, linked_materials=linked_materials,
        )
        # Compute identities/indices from the original source records, then
        # apply visibility by index. Derived envelopes must not change IDs.
        visibility_by_index = {}
        for index, record in enumerate(paper.materials_extracted or []):
            if isinstance(record, dict):
                material_id = record.get("material_id")
                visibility_by_index[index] = occurrence_visibility(
                    record, paper_status=paper_status,
                    linked_visibility=linked_materials.get(material_id) if isinstance(material_id, str) else None,
                )
        matched_results = matching_result_references(
            paper.materials_extracted, scientific_filters, scope_id=paper.id,
        )
        matched_results = [
            {**result, "visibility": visibility_by_index[result["record_index"]]}
            for result in matched_results
            if visibility_by_index[result["record_index"]]["reported_claim_filter_eligible"]
        ]
        if scientific_filters.active and not matched_results:
            continue

        seen_papers.add(paper.id)
        matches.append(
            SearchMatch(
                paper_id=paper.id,
                arxiv_id=paper.arxiv_id,
                title=paper.title,
                authors=list(paper.authors or []),
                year=(paper.date_submitted.year if paper.date_submitted else None),
                date_submitted=paper.date_submitted,
                relevance_score=round(candidate.rerank_score, 6),
                matched_chunk=chunk.text,
                matched_section=chunk.section,
                materials=materials,
                citation_count=paper.citation_count or 0,
                material_family=paper.material_family,
                has_equation=bool(chunk.has_equation),
                has_table=bool(chunk.has_table),
                matching_results=matched_results if scientific_filters.active else [],
                source_visibility=source_visibility(paper_status),
                occurrence_visibility_summary=occurrence_summary,
            )
        )
        if len(matches) >= body.top_k:
            break

    # 4. Optional reorder. "relevance" keeps ANN order. The others are
    #    cheap client-side sorts over at most top_k rows.
    if body.sort == "date":
        matches.sort(
            key=lambda m: (m.date_submitted or _EPOCH),
            reverse=True,
        )
    elif body.sort == "tc":
        matches.sort(key=_best_tc, reverse=True)

    return SearchResponse(
        total=len(matches),
        results=matches,
        query_time_ms=int((time.perf_counter() - t0) * 1000),
        guest_remaining=identity.guest_remaining,
        remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EPOCH = _date(1900, 1, 1)


def _best_tc(m: SearchMatch) -> float:
    if m.matching_results:
        return max((r["tc_lower_bound_k"] or 0 for r in m.matching_results
                    if eligible_for_property(r.get("anomaly_review", {}), "tc_kelvin")), default=0.0)
    eligible = [mat for mat in m.materials if isinstance(mat, dict)
                and mat.get("visibility", {}).get("reported_claim_filter_eligible", False)]
    matches = matching_result_references(eligible, ResultFilters(positive_tc=True), scope_id=m.paper_id)
    return max((record["tc_lower_bound_k"] or 0 for record in matches), default=0.0)
