"""Generation-pinned, bounded 'more like this' retrieval; not scientific support."""
from __future__ import annotations

import asyncio
import math
import threading
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models import get_db
from models.db import Paper
from models.index_read import generation_read_metadata
from models.search import SimilarPaper, SimilarResponse
from routers.deps import Identity, peek_identity
from services import index_retrieval, index_vector_adapter, provider_resilience

router = APIRouter(tags=["similar"])
_UNAVAILABLE = "Similarity search is temporarily unavailable. Please try again later."


@router.get("/similar/{paper_id:path}", response_model=SimilarResponse)
async def similar_papers(
    paper_id: str,
    top_k: int = Query(10, ge=1, le=50),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> SimilarResponse:
    if await db.get(Paper, paper_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Paper {paper_id!r} not found")
    try:
        async with asyncio.timeout(10):
            pin = await index_retrieval.load_pin(db)
            if pin is None:
                # There is no honest cosine-like result without a pinned
                # semantic generation. Do not invent lexical similarity.
                raise index_retrieval.IndexRetrievalError("No active retrieval generation")
            chunks = await index_retrieval.paper_chunks(db, pin, paper_id)
            evidence = await index_retrieval.resolve_evidence(db, chunks)
            members = [chunk.member for chunk in chunks if evidence[chunk.id]["permission_status"] != "restricted"
                     and evidence[chunk.id]["currentness"] != "stale"]
            excluded_revisions = await index_retrieval.paper_revision_exclusions(db, pin, paper_id)
            if any(member["chunk_revision_sha256"] not in excluded_revisions for member in members):
                raise index_retrieval.IndexRetrievalError("Incomplete source revision exclusion inventory")
            await index_retrieval.require_current_pin(db, pin)
    except Exception:
        raise HTTPException(503, _UNAVAILABLE) from None
    if not members:
        return SimilarResponse(source_paper_id=paper_id, results=[],
                               retrieval_generation=generation_read_metadata(pin))

    stopped = threading.Event()
    settings = get_settings()
    try:
        per_chunk = await provider_resilience.run_blocking(
            "similar_search", lambda: index_vector_adapter.query_members(
                pin, members, top_k=min(top_k + 5, index_retrieval.MAX_HYDRATE // len(members)), stop_event=stopped,
                excluded_revisions=excluded_revisions),
            timeout_seconds=settings.vector_search_timeout_seconds,
            failure_threshold=settings.provider_circuit_failure_threshold,
            cooldown_seconds=settings.provider_circuit_cooldown_seconds,
            max_attempts=1,
        )
    except provider_resilience.ProviderUnavailable:
        raise HTTPException(503, _UNAVAILABLE) from None
    finally:
        stopped.set()

    try:
        async with asyncio.timeout(10):
            if type(per_chunk) is not list or len(per_chunk) != len(members):
                raise index_retrieval.IndexRetrievalError("Similarity result inventory mismatch")
            unique = {}
            for row in per_chunk:
                if type(row) is not list or len(row) > 100:
                    raise index_retrieval.IndexRetrievalError("Similarity row limit exceeded")
                row_ids = set()
                for hit in row:
                    if (type(hit.distance) not in {int, float} or not math.isfinite(hit.distance)
                            or not 0 <= hit.distance <= 2):
                        raise index_retrieval.IndexRetrievalError("Invalid similarity distance")
                    if hit.vector_id in row_ids:
                        raise index_retrieval.IndexRetrievalError("Duplicate similarity member")
                    row_ids.add(hit.vector_id)
                    previous = unique.get(hit.vector_id)
                    if previous is not None and any(getattr(previous, key) != getattr(hit, key)
                            for key in ("content_sha256", "vector_sha256", "chunk_revision_sha256")):
                        raise index_retrieval.IndexRetrievalError("Inconsistent similarity member")
                    unique[hit.vector_id] = hit
            verified = await index_retrieval.verified_vector_hits(db, pin, list(unique.values()))
            hydrated = await index_retrieval.hydrate(db, pin, [identifier for identifier, _ in verified])
            descriptors = await index_retrieval.resolve_evidence(db, list(hydrated.values()))
            acc, paper_by_id = defaultdict(list), {}
            for row in per_chunk:
                for hit in row:
                    chunk = hydrated.get(hit.vector_id)
                    if chunk is None or chunk.paper_id == paper_id:
                        continue
                    descriptor = descriptors[chunk.id]
                    if descriptor["permission_status"] == "restricted" or descriptor["currentness"] == "stale":
                        continue
                    acc[chunk.paper_id].append(hit.distance)
                    paper_by_id.setdefault(chunk.paper_id, index_retrieval.attribution(chunk))
            scored = sorted(((identifier, sum(values) / len(values)) for identifier, values in acc.items()),
                            key=lambda item: (item[1], item[0]))[:top_k]
            await index_retrieval.require_current_pin(db, pin)
    except Exception:
        raise HTTPException(503, _UNAVAILABLE) from None

    results = []
    for identifier, distance in scored:
        paper = paper_by_id[identifier]
        results.append(SimilarPaper(paper_id=paper.id, arxiv_id=paper.arxiv_id, title=paper.title,
            authors=list(paper.authors or []), year=paper.date_submitted.year if paper.date_submitted else None,
            similarity=round(1.0 - distance, 6)))
    return SimilarResponse(source_paper_id=paper_id, results=results,
                           retrieval_generation=generation_read_metadata(pin))
