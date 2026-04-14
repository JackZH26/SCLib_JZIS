"""POST /ask — retrieval-augmented Q&A.

Identical retrieval path to /search (same embedding model, same
Matching Engine endpoint), but we then feed the top-N chunks into
Gemini 2.5 Flash with a strict "cite [n] only from the sources"
prompt and return the grounded markdown answer.

The shape of `sources` in the response maps 1:1 to the [n] markers
Gemini emits — frontend just hyperlinks each bracket to the paper.
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
from models.db import Chunk
from models.search import AskRequest, AskResponse, AskSource
from routers.deps import Identity, require_identity
from services import rag, vector_search

log = logging.getLogger(__name__)

router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    identity: Identity = Depends(require_identity),
    db: AsyncSession = Depends(get_db),
) -> AskResponse:
    t0 = time.perf_counter()

    # 1. Retrieve candidate chunks via ANN.
    def _vs_lookup() -> list[vector_search.Neighbor]:
        vec = vector_search.embed_query(body.question)
        return vector_search.find_neighbors(vec, top_k=body.max_sources)

    neighbors = await asyncio.to_thread(_vs_lookup)
    if not neighbors:
        return AskResponse(
            answer="No indexed sources match this question.",
            sources=[],
            tokens_used=0,
            query_time_ms=int((time.perf_counter() - t0) * 1000),
            guest_remaining=identity.guest_remaining,
        )

    # 2. Hydrate chunks + papers from Postgres, keeping ANN order.
    chunk_ids = [n.chunk_id for n in neighbors]
    q = (
        select(Chunk)
        .options(selectinload(Chunk.paper))
        .where(Chunk.id.in_(chunk_ids))
    )
    rows = (await db.execute(q)).scalars().all()
    chunk_by_id = {c.id: c for c in rows}

    rag_inputs: list[rag.RagSourceInput] = []
    sources_out: list[AskSource] = []
    idx = 0
    for cid in chunk_ids:
        chunk = chunk_by_id.get(cid)
        if chunk is None or chunk.paper is None:
            continue
        if chunk.paper.status == "retracted":
            continue
        idx += 1
        paper = chunk.paper
        authors_short = _authors_short(paper.authors or [])
        year = paper.date_submitted.year if paper.date_submitted else None
        rag_inputs.append(
            rag.RagSourceInput(
                index=idx,
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

    # 3. Gemini call (blocking SDK) on a worker thread.
    result = await asyncio.to_thread(
        rag.generate_answer,
        body.question,
        rag_inputs,
        language=body.language,
    )

    return AskResponse(
        answer=result.answer,
        sources=sources_out,
        tokens_used=result.tokens_used,
        query_time_ms=int((time.perf_counter() - t0) * 1000),
        guest_remaining=identity.guest_remaining,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _authors_short(authors: list) -> str:
    """'Smith et al.' for >2 authors, else 'Smith & Jones' / 'Smith'."""
    names: list[str] = []
    for a in authors[:3]:
        if isinstance(a, str):
            names.append(a.split(",")[0].strip())
        elif isinstance(a, dict):
            names.append(str(a.get("name") or a.get("family") or "").strip())
    names = [n for n in names if n]
    if not names:
        return "Unknown"
    if len(authors) > 2:
        return f"{names[0]} et al."
    return " & ".join(names)


def _snippet(text: str, max_chars: int = 280) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
