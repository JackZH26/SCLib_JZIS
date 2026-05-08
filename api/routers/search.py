"""POST /search — semantic search over chunks.

Pipeline:
  1. Embed the query with Vertex text-embedding-005 (RETRIEVAL_QUERY).
  2. Ask Matching Engine for the top-K neighbors, with optional
     year / material_family filters pushed into the index namespaces.
  3. Load the matched Chunk rows + their Paper parents in a single
     JOIN query. Apply the Postgres-side filters the vector index
     can't express (tc_min, pressure_max, exclude_retracted).
  4. Assemble SearchMatch rows preserving neighbor order, so
     relevance-sorted results mirror the ANN ranking exactly.

The Vertex search is offloaded to a thread because the google-cloud
SDK is blocking; Postgres work stays on the main event loop.
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import get_db
from models.db import Chunk, Paper
from models.search import SearchMatch, SearchRequest, SearchResponse
from routers.deps import Identity, require_identity
from services import vector_search

log = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    identity: Identity = Depends(require_identity),
    db: AsyncSession = Depends(get_db),
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
            material_family=body.filters.material_family,
        )

    neighbors = await asyncio.to_thread(_vs_lookup)
    if not neighbors:
        return SearchResponse(
            total=0,
            results=[],
            query_time_ms=int((time.perf_counter() - t0) * 1000),
            guest_remaining=identity.guest_remaining,
        )

    # 2. Fetch chunks + parent papers in one round-trip. Defensive cap:
    # even though overfetch is 3x top_k (max 100), a buggy vector_search
    # implementation could return more — cap the IN clause so a runaway
    # list cannot blow out the Postgres parser.
    MAX_IN_CLAUSE = 300
    neighbors = neighbors[:MAX_IN_CLAUSE]
    chunk_ids = [n.chunk_id for n in neighbors]
    distance_by_chunk = {n.chunk_id: n.distance for n in neighbors}

    q = (
        select(Chunk)
        .options(selectinload(Chunk.paper))
        .where(Chunk.id.in_(chunk_ids))
    )
    rows = (await db.execute(q)).scalars().all()
    chunk_by_id = {c.id: c for c in rows}

    # 3. Preserve ANN ordering, apply row-level filters that don't
    #    fit in the index namespaces.
    f = body.filters
    matches: list[SearchMatch] = []
    seen_papers: set[str] = set()  # deduplicate: one result per paper
    for cid in chunk_ids:
        chunk = chunk_by_id.get(cid)
        if chunk is None:
            continue  # neighbor not in Postgres (e.g. deleted)
        paper = chunk.paper
        if paper is None:
            continue
        if paper.id in seen_papers:
            continue  # already have a higher-ranked chunk from this paper
        if f.exclude_retracted and paper.status == "retracted":
            continue
        if f.tc_min is not None:
            materials = paper.materials_extracted or []
            if not _any_tc_meets(materials, f.tc_min):
                continue
        if f.pressure_max is not None:
            materials = paper.materials_extracted or []
            if not _any_pressure_below(materials, f.pressure_max):
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
                relevance_score=round(1.0 - distance_by_chunk[cid], 6),
                matched_chunk=chunk.text,
                matched_section=chunk.section,
                materials=list(paper.materials_extracted or []),
                citation_count=paper.citation_count or 0,
                material_family=paper.material_family,
                has_equation=bool(chunk.has_equation),
                has_table=bool(chunk.has_table),
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
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from datetime import date as _date

_EPOCH = _date(1900, 1, 1)


def _any_tc_meets(materials: list[dict], tc_min: float) -> bool:
    for m in materials:
        tc = m.get("tc_kelvin") if isinstance(m, dict) else None
        if isinstance(tc, (int, float)) and tc >= tc_min:
            return True
    return False


def _any_pressure_below(materials: list[dict], pressure_max: float) -> bool:
    # Ambient (None/0) always satisfies "pressure_max" — the caller
    # wants "no more than this much pressure".
    for m in materials:
        if not isinstance(m, dict):
            continue
        p = m.get("pressure_gpa")
        if p is None or (isinstance(p, (int, float)) and p <= pressure_max):
            return True
    return False


def _best_tc(m: SearchMatch) -> float:
    best = 0.0
    for mat in m.materials:
        if not isinstance(mat, dict):
            continue
        tc = mat.get("tc_kelvin")
        if isinstance(tc, (int, float)) and tc > best:
            best = float(tc)
    return best
