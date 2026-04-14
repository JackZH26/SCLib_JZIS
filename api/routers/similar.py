"""GET /similar/{paper_id} — "more like this" via vector search.

Approach: pull every chunk id for the source paper, look each one up
in Vertex VS (batched via find_neighbors_many), then aggregate by
paper_id using the average distance across all matching chunks.
Exclude the source paper itself from the results.

We deliberately do NOT re-embed — the chunks are already indexed,
and the indexer stores the same vector we would compute now.
Re-embedding would double-charge for no benefit.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import Paper
from models.search import SimilarPaper, SimilarResponse
from routers.deps import Identity, peek_identity
from services import vector_search

router = APIRouter(tags=["similar"])


@router.get("/similar/{paper_id:path}", response_model=SimilarResponse)
async def similar_papers(
    paper_id: str,
    top_k: int = Query(10, ge=1, le=50),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> SimilarResponse:
    src = await db.get(Paper, paper_id)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Paper {paper_id!r} not found")

    # Neighbor lookup currently re-embeds each chunk since we don't
    # store vectors in Postgres. Cheaper alternative: ask VS to
    # self-retrieve by datapoint id (not available in all SDK
    # versions), or stash the vectors at ingest time. Phase 5 TODO.
    #
    # For now: fetch chunk texts, embed them, batch-query.
    from models.db import Chunk  # local import to keep top of file lean

    chunk_rows = (
        await db.execute(
            select(Chunk.text).where(Chunk.paper_id == paper_id).limit(20)
        )
    ).scalars().all()
    if not chunk_rows:
        return SimilarResponse(source_paper_id=paper_id, results=[])

    def _compute() -> list[tuple[str, float]]:
        vectors = [vector_search.embed_query(t) for t in chunk_rows]
        per_chunk = vector_search.find_neighbors_many(vectors, top_k=top_k + 5)
        # Aggregate: mean distance per paper, ignoring self-hits.
        acc: dict[str, list[float]] = defaultdict(list)
        for row in per_chunk:
            for n in row:
                pid = vector_search.chunk_id_to_paper_id(n.chunk_id)
                if pid == paper_id:
                    continue
                acc[pid].append(n.distance)
        scored = [(pid, sum(ds) / len(ds)) for pid, ds in acc.items()]
        scored.sort(key=lambda x: x[1])  # smaller distance = closer
        return scored[:top_k]

    scored = await asyncio.to_thread(_compute)
    if not scored:
        return SimilarResponse(source_paper_id=paper_id, results=[])

    # Hydrate paper rows for the final response.
    ids = [pid for pid, _ in scored]
    rows = (
        await db.execute(select(Paper).where(Paper.id.in_(ids)))
    ).scalars().all()
    paper_by_id = {p.id: p for p in rows}

    results: list[SimilarPaper] = []
    for pid, dist in scored:
        p = paper_by_id.get(pid)
        if p is None:
            continue
        results.append(
            SimilarPaper(
                paper_id=p.id,
                arxiv_id=p.arxiv_id,
                title=p.title,
                authors=list(p.authors or []),
                year=p.date_submitted.year if p.date_submitted else None,
                similarity=round(1.0 - dist, 6),
            )
        )

    return SimilarResponse(source_paper_id=paper_id, results=results)
