"""Pinned similarity failures are bounded503, not successful-empty laundering."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from models.db import get_session_factory
from services import index_vector_adapter
from services.embedding_contract import EmbeddingCompletenessError
from tests import test_index_retrieval_http as generation_fixtures
from tests.index_generation_fixtures import publish_and_activate, write_generation

generation = generation_fixtures.generation


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["completeness", "provider"])
async def test_similarity_incomplete_embedding_or_ann_failure_returns_sanitized503(client, generation, monkeypatch, failure):
    calls = []
    def failed(_pin, texts, **_kwargs):
        calls.append(texts)
        if failure == "completeness":
            raise EmbeddingCompletenessError("PRIVATE_SOURCE_SENTINEL")
        raise RuntimeError("PRIVATE_PROVIDER_SENTINEL")
    monkeypatch.setattr(index_vector_adapter, "query_members", failed)
    response = await client.get("/v1/similar/" + generation["meta"].paper_id)
    assert response.status_code == 503, response.text
    assert set(response.json()) == {"detail", "error_code", "request_id"}
    assert response.json()["detail"] == "Similarity search is temporarily unavailable. Please try again later."
    assert "PRIVATE_" not in response.text
    assert len(calls) == 1 and len(calls[0]) == 5


@pytest.mark.asyncio
async def test_similarity_uses_completed_document_vectors_without_reembedding_large_text(client, generation, monkeypatch):
    # Document-to-document similarity uses the already completed vector.
    # The separate query text byte limit must not reject retained documents.
    meta, _, staged = await write_generation(monkeypatch, logical_index=generation["logical"],
        count=1, label=" " * 8200)
    async with get_session_factory()() as db:
        await publish_and_activate(db, staged, expected_event_id=generation["pin"]["activation_event_id"])
    calls = []
    def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("Oversized full query must not reach transport")
    monkeypatch.setattr(index_vector_adapter, "_embed", forbidden)
    response = await client.get("/v1/similar/" + meta.paper_id)
    assert response.status_code == 200 and response.json()["results"] == []
    assert calls == []


@pytest.mark.asyncio
async def test_similarity_timeout_sets_worker_stop_and_never_delivers_late_results(client, generation, monkeypatch):
    release, entered, finished = threading.Event(), threading.Event(), threading.Event()
    stops, late_work = [], []
    def query_many(_pin, _texts, *, stop_event, **_kwargs):
        stops.append(stop_event)
        entered.set()
        try:
            assert release.wait(3), "Synthetic worker barrier not released"
            if not stop_event.is_set():
                late_work.append(True)
            return [[] for _ in _texts]
        finally:
            finished.set()
    monkeypatch.setattr(index_vector_adapter, "query_members", query_many)
    monkeypatch.setattr("routers.similar.get_settings", lambda: SimpleNamespace(
        vector_search_timeout_seconds=0.02, provider_circuit_failure_threshold=5,
        provider_circuit_cooldown_seconds=1))
    try:
        response = await asyncio.wait_for(client.get("/v1/similar/" + generation["meta"].paper_id), 2)
        assert entered.is_set() and not release.is_set()
        assert response.status_code == 503 and "results" not in response.json()
        assert stops[0].is_set()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    assert late_work == []


@pytest.mark.asyncio
async def test_successful_empty_neighbor_result_is_still_a_real200(client, generation, monkeypatch):
    calls = []
    def query(_pin, texts, **_kwargs):
        calls.append(True)
        return [[] for _ in texts]
    monkeypatch.setattr(index_vector_adapter, "query_members", query)
    response = await client.get("/v1/similar/" + generation["meta"].paper_id)
    assert response.status_code == 200 and response.json()["results"] == [] and calls == [True]
    assert response.json()["retrieval_generation"]["generation_id"] == generation["pin"]["generation_id"]
