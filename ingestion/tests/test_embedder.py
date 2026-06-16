from __future__ import annotations

from types import SimpleNamespace

import ingestion.embed.embedder as E
from ingestion.models import Chunk


class _FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def embed_content(self, *, model, contents, config):
        self.calls.append({
            "model": model,
            "contents": contents,
            "task_type": config.task_type,
            "output_dimensionality": config.output_dimensionality,
        })
        return SimpleNamespace(
            embeddings=[
                SimpleNamespace(values=[float(i)] * config.output_dimensionality)
                for i, _ in enumerate(contents, 1)
            ]
        )


def test_embed_chunks_uses_genai_document_task(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://sclib:test@postgres:5432/sclib")
    E.get_settings.cache_clear()
    E._client.cache_clear()

    models = _FakeModels()
    monkeypatch.setattr(E, "make_genai_client", lambda: SimpleNamespace(models=models))

    chunks = [
        Chunk(
            id="c1", paper_id="p", chunk_index=0, section="Abstract",
            text="alpha", token_count=1,
        ),
        Chunk(
            id="c2", paper_id="p", chunk_index=1, section="Facts",
            text="beta", token_count=1,
        ),
    ]
    E.embed_chunks(chunks)

    assert models.calls == [{
        "model": "text-embedding-005",
        "contents": ["alpha", "beta"],
        "task_type": "RETRIEVAL_DOCUMENT",
        "output_dimensionality": 768,
    }]
    assert chunks[0].embedding == [1.0] * 768
    assert chunks[1].embedding == [2.0] * 768


def test_embed_query_uses_genai_query_task(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://sclib:test@postgres:5432/sclib")
    E.get_settings.cache_clear()
    E._client.cache_clear()

    models = _FakeModels()
    monkeypatch.setattr(E, "make_genai_client", lambda: SimpleNamespace(models=models))

    assert E.embed_query("why superconductivity?") == [1.0] * 768
    assert models.calls == [{
        "model": "text-embedding-005",
        "contents": ["why superconductivity?"],
        "task_type": "RETRIEVAL_QUERY",
        "output_dimensionality": 768,
    }]
