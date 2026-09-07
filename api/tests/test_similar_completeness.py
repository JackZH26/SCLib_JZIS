"""Similarity failures must be bounded503, never successful empty results."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Chunk, Paper, get_engine
from services import provider_resilience, vector_search
from services.embedding_contract import EmbeddingCompletenessError


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with AsyncSession(get_engine(), expire_on_commit=False) as session:
        yield session


@pytest.fixture(autouse=True)
def isolated_provider_state():
    provider_resilience.reset()
    yield
    provider_resilience.reset()


async def seed(db, *, texts=("Synthetic first", "Synthetic second")):
    paper = Paper(id="synthetic:similar-" + uuid4().hex, source="arxiv", title="Synthetic similarity fixture",
                  authors=[], abstract="Synthetic", status="published", materials_extracted=[])
    db.add(paper)
    db.add_all([Chunk(id=paper.id + f"_chunk_{index:03}", paper=paper, title=paper.title,
                      text=value, section="Results", materials_mentioned=[]) for index, value in enumerate(texts)])
    await db.commit()
    return paper


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["completeness", "provider"])
async def test_similarity_incomplete_embedding_or_ann_failure_returns_sanitized503(client, db_session, monkeypatch, failure):
    paper = await seed(db_session)
    embeddings, searches = [], []
    def embed(_text):
        embeddings.append(True)
        if failure == "completeness":
            raise EmbeddingCompletenessError("PRIVATE_SOURCE_SENTINEL")
        return [0.1] * 768
    def find(*_args, **_kwargs):
        searches.append(True)
        raise RuntimeError("PRIVATE_PROVIDER_SENTINEL")
    monkeypatch.setattr(vector_search, "embed_query", embed)
    monkeypatch.setattr(vector_search, "find_neighbors_many", find)
    response = await client.get("/v1/similar/" + paper.id)
    assert response.status_code == 503, response.text
    assert set(response.json()) == {"detail", "error_code", "request_id"}
    assert response.json()["detail"] == "Similarity search is temporarily unavailable. Please try again later."
    assert "PRIVATE_" not in response.text
    assert len(embeddings) == (1 if failure == "completeness" else 2)
    assert searches == ([] if failure == "completeness" else [True])


@pytest.mark.asyncio
async def test_similarity_actual_local_input_rejection_never_constructs_provider(client, db_session, monkeypatch):
    paper = await seed(db_session, texts=("x" * 8193,))
    monkeypatch.setattr(vector_search, "get_settings", lambda: SimpleNamespace(
        embedding_model="text-embedding-005", embedding_output_dimensionality=768))
    calls = []
    def forbidden():
        calls.append(True)
        raise AssertionError("Oversized source must not reach provider")
    monkeypatch.setattr(vector_search, "genai_client", forbidden)
    response = await client.get("/v1/similar/" + paper.id)
    assert response.status_code == 503 and "results" not in response.json()
    assert calls == []


@pytest.mark.asyncio
async def test_similarity_timeout_does_not_start_more_embeddings_or_late_ann(client, db_session, monkeypatch):
    paper = await seed(db_session)
    release, entered, finished = threading.Event(), threading.Event(), threading.Event()
    calls, searches = [], []
    def embed(value):
        calls.append(value)
        entered.set()
        try:
            if not release.wait(3):
                raise AssertionError("Synthetic worker barrier not released")
            return [0.1] * 768
        finally:
            finished.set()
    monkeypatch.setattr(vector_search, "embed_query", embed)
    monkeypatch.setattr(vector_search, "find_neighbors_many", lambda *_args, **_kwargs: searches.append(True))
    monkeypatch.setattr("routers.similar.get_settings", lambda: SimpleNamespace(
        vector_search_timeout_seconds=0.02, provider_circuit_failure_threshold=5,
        provider_circuit_cooldown_seconds=1))
    try:
        response = await asyncio.wait_for(client.get("/v1/similar/" + paper.id), 2)
        assert entered.is_set() and not release.is_set()
        assert response.status_code == 503 and "results" not in response.json()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    # Give the resumed worker an event-loop turn to encounter the stop flag.
    await asyncio.sleep(0.01)
    assert len(calls) == 1 and searches == []


@pytest.mark.asyncio
async def test_successful_empty_neighbor_result_is_still_a_real200(client, db_session, monkeypatch):
    paper = await seed(db_session)
    monkeypatch.setattr(vector_search, "embed_query", lambda _: [0.1] * 768)
    monkeypatch.setattr(vector_search, "find_neighbors_many", lambda *_args, **_kwargs: [[], []])
    response = await client.get("/v1/similar/" + paper.id)
    assert response.status_code == 200 and response.json()["results"] == []
