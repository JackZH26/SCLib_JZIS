"""POST /search — hybrid search over chunks.

Pin one active immutable generation before ANN, compare all returned bindings
to its SQL members, and fuse with full-text retrieval in that same generation.
With no active generation only legacy lexical retrieval is admitted. Frozen
snapshot attribution is separate from current source/material governance.

Blocking cloud SDK calls run in a worker thread; PostgreSQL work stays on the
main event loop.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models import get_db
from models.index_read import generation_read_metadata
from models.scientific_lookup import ScientificLookupStatus
from models.search import SearchMatch, SearchRequest, SearchResponse
from routers.deps import Identity, require_identity
from services import index_retrieval, index_vector_adapter, provider_resilience, retrieval
from services.anomaly_review import eligible_for_property
from services.scientific_filters import ResultFilters, matching_result_references
from services.scientific_query import interpret_scientific_query
from services.scientific_query_lookup import lookup_scientific_results, result_query, unavailable
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
    interpretation = interpret_scientific_query(body.query)
    f = body.filters
    scientific_filters = ResultFilters(
        families=tuple(f.material_family or []), tc_min=f.tc_min,
        pressure_min=f.pressure_min, pressure_max=f.pressure_max,
        ambient_only=f.ambient_only, include_unknown_pressure=f.include_unknown_pressure,
        origins=tuple(f.knowledge_origin or []), source_role=f.source_role,
        experimental_only=f.experimental_only,
    )
    if interpretation.status == "clarification_required":
        return SearchResponse(total=0, results=[], query_time_ms=int((time.perf_counter() - t0) * 1000),
            guest_remaining=identity.guest_remaining,
            remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
            scientific_query=interpretation, scientific_lookup=ScientificLookupStatus(
                status="clarification_required", reason_codes=["unresolved_query_constraints"]))

    try:
        async with asyncio.timeout(10):
            pin = await index_retrieval.load_pin(db)
    except Exception:
        raise HTTPException(503, "Retrieval generation is unavailable") from None
    # UI scientific predicates have exactly the same source-bound admission
    # as conditions written in the query. They never fall back to legacy
    # paper-wide numeric projections. Consumers read scientific_results here.
    if result_query(interpretation) or scientific_filters.active:
        try:
            async with asyncio.timeout(15):
                outcome = await lookup_scientific_results(db, pin, interpretation, limit=min(body.top_k, 20), filters=scientific_filters,
                    year_min=f.year_min, year_max=f.year_max, sort=body.sort)
        except Exception:
            await db.rollback()
            outcome = unavailable("scientific_lookup_unavailable")
        return SearchResponse(total=0, results=[], query_time_ms=int((time.perf_counter() - t0) * 1000),
            guest_remaining=identity.guest_remaining,
            remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
            retrieval_generation=generation_read_metadata(pin), scientific_query=interpretation,
            scientific_lookup=outcome.status, scientific_results=outcome.results)
    # No active generation means lexical-only. Positional legacy ANN IDs must
    # never be interpreted as pointers to the latest mutable Chunk rows.
    settings = get_settings()
    vector_hits = []
    if pin is not None:
        try:
            neighbors = await provider_resilience.run_blocking(
                "vector_search", lambda: index_vector_adapter.query(pin, body.query,
                    top_k=min(body.top_k * 3, 100), year_min=body.filters.year_min, year_max=body.filters.year_max),
                timeout_seconds=settings.vector_search_timeout_seconds,
                max_attempts=settings.provider_max_attempts,
                failure_threshold=settings.provider_circuit_failure_threshold,
                cooldown_seconds=settings.provider_circuit_cooldown_seconds,
            )
            async with asyncio.timeout(10):
                vector_hits = await index_retrieval.verified_vector_hits(db, pin, neighbors)
        except Exception:
            log.warning("Semantic generation search unavailable; using generation-scoped lexical fallback")
            await db.rollback()

    candidate_limit = min(body.top_k * 5, 300)
    lexical_hits = await retrieval.lexical_search(
        db,
        interpretation.normalized_query,
        limit=candidate_limit,
        year_min=body.filters.year_min,
        year_max=body.filters.year_max,
        exclude_retracted=body.filters.exclude_retracted,
        generation_id=pin["generation_id"] if pin is not None else None,
    )
    try:
        async with asyncio.timeout(15):
            formula_hits = await retrieval.formula_lexical_search(db, interpretation, pin, limit=candidate_limit,
                year_min=body.filters.year_min, year_max=body.filters.year_max)
        lexical_hits = retrieval.combine_lexical_hits(formula_hits, lexical_hits, limit=candidate_limit)
    except Exception:
        raise HTTPException(503, "Formula-aware retrieval is unavailable") from None
    candidates = retrieval.fuse_rankings(
        vector_hits,
        lexical_hits,
        limit=candidate_limit,
    )
    if not candidates:
        if pin is not None:
            try:
                async with asyncio.timeout(10):
                    await index_retrieval.require_current_pin(db, pin)
            except Exception:
                raise HTTPException(503, "Retrieval generation changed; please search again") from None
        return SearchResponse(
            total=0,
            results=[],
            query_time_ms=int((time.perf_counter() - t0) * 1000),
            guest_remaining=identity.guest_remaining,
            remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
            retrieval_generation=generation_read_metadata(pin),
            scientific_query=interpretation,
        )

    # Hydrate exact generation members (or explicit legacy lexical rows),
    # retaining a defensive cap on the SQL identity inventory.
    MAX_IN_CLAUSE = 300
    candidates = candidates[:MAX_IN_CLAUSE]
    chunk_ids = [candidate.chunk_id for candidate in candidates]

    try:
        async with asyncio.timeout(10):
            chunk_by_id = await index_retrieval.hydrate(db, pin, chunk_ids)
    except Exception:
        raise HTTPException(503, "Retrieval generation is unavailable") from None
    rows = list(chunk_by_id.values())
    candidates = retrieval.rerank_candidates(body.query, candidates, chunk_by_id)
    linked_materials = await resolve_explicit_materials(
        db, [index_retrieval.attribution(chunk).materials_extracted for chunk in rows if chunk.paper is not None],
    )
    source_statuses = await resolve_paper_lifecycle(db, {chunk.paper_id for chunk in rows})
    from services.rag_evidence_contract import validate_evidence_descriptor

    try:
        async with asyncio.timeout(10):
            evidence_by_chunk = await index_retrieval.resolve_evidence(db, rows)
            if set(evidence_by_chunk) != set(chunk_by_id):
                raise ValueError("Evidence inventory mismatch")
            evidence_by_chunk = {key: validate_evidence_descriptor(value) for key, value in evidence_by_chunk.items()}
    except (TimeoutError, SQLAlchemyError, ValueError, TypeError):
        # Never return previously hydrated text when its current provenance
        # cannot be checked; omit SQL/provider details from the public error.
        raise HTTPException(503, "Evidence provenance is unavailable") from None

    # Preserve fused ordering and reapply authoritative filters to retained
    # metadata with independently resolved live governance.
    matches: list[SearchMatch] = []
    seen_papers: set[str] = set()  # deduplicate: one result per paper
    for candidate in candidates:
        chunk = chunk_by_id.get(candidate.chunk_id)
        if chunk is None:
            continue  # neighbor not in Postgres (e.g. deleted)
        paper = index_retrieval.attribution(chunk)
        if paper is None:
            continue
        if paper.id in seen_papers:
            continue  # already have a higher-ranked chunk from this paper
        selected_year = (chunk.member["snapshot_json"].get("year")
                         if isinstance(chunk, index_retrieval.GenerationChunk) else chunk.year)
        if ((f.year_min is not None or f.year_max is not None)
                and (type(selected_year) is not int
                     or f.year_min is not None and selected_year < f.year_min
                     or f.year_max is not None and selected_year > f.year_max)):
            continue
        text_available = (evidence_by_chunk[chunk.id]["permission_status"] != "restricted"
                          and evidence_by_chunk[chunk.id]["currentness"] != "stale")
        if scientific_filters.active and not text_available:
            continue
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
                matched_chunk=chunk.text if text_available else "",
                matched_section=chunk.section,
                materials=materials if text_available else [],
                citation_count=paper.citation_count or 0,
                material_family=paper.material_family,
                has_equation=bool(chunk.has_equation),
                has_table=bool(chunk.has_table),
                matching_results=matched_results if scientific_filters.active else [],
                source_visibility=source_visibility(paper_status),
                occurrence_visibility_summary=occurrence_summary,
                evidence_provenance=evidence_by_chunk[chunk.id],
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

    if pin is not None:
        try:
            async with asyncio.timeout(10):
                await index_retrieval.require_current_pin(db, pin)
        except Exception:
            raise HTTPException(503, "Retrieval generation changed; please search again") from None
    return SearchResponse(
        total=len(matches),
        results=matches,
        query_time_ms=int((time.perf_counter() - t0) * 1000),
        guest_remaining=identity.guest_remaining,
        remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
        retrieval_generation=generation_read_metadata(pin),
        scientific_query=interpretation,
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
