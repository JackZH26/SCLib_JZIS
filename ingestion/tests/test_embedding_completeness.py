"""Offline all-or-nothing embedding publication; synthetic provider responses."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from ingestion.embed import embedder
from ingestion.embedding_contract import EmbeddingCompletenessError, validate_embedding_provenance
from ingestion.models import Chunk


def chunks():
    return [Chunk(id=f"synthetic-{index}", paper_id="synthetic", chunk_index=index, section="Results",
                  text=f"Synthetic result {index}.", token_count=1,
                  embedding=[9.0] * 768, embedding_provenance={"old": index}) for index in range(3)]


@pytest.fixture
def settings(monkeypatch):
    value = SimpleNamespace(embedding_model="text-embedding-005", embedding_output_dimensionality=768,
                            embed_batch_size=1)
    monkeypatch.setattr(embedder, "get_settings", lambda: value)
    return value


def provider(monkeypatch, behavior):
    calls = []
    def embed_content(**kwargs):
        calls.append(kwargs)
        return behavior(kwargs, len(calls))
    monkeypatch.setattr(embedder, "_client", lambda: SimpleNamespace(models=SimpleNamespace(embed_content=embed_content)))
    return calls


def valid(kwargs, _position):
    return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1] * 768,
        statistics=SimpleNamespace(truncated=False, token_count=8.0)) for _ in kwargs["contents"]])


@pytest.mark.parametrize("failure", ["exception", "truncated", "statistics", "dimension", "count", "float32"])
def test_late_batch_failure_does_not_publish_any_earlier_embedding_or_report(monkeypatch, settings, failure):
    selected = chunks()
    before = deepcopy([(chunk.embedding, chunk.embedding_provenance) for chunk in selected])
    def behavior(kwargs, position):
        if position != 2:
            return valid(kwargs, position)
        if failure == "exception":
            raise RuntimeError("Synthetic offline provider failure")
        result = valid(kwargs, position)
        if failure == "truncated":
            result.embeddings[0].statistics.truncated = True
        elif failure == "statistics":
            result.embeddings[0].statistics = None
        elif failure == "dimension":
            result.embeddings[0].values = [1.0] * 767
        elif failure == "count":
            result.embeddings = []
        else:
            result.embeddings[0].values = [1e100] * 768
        return result
    calls = provider(monkeypatch, behavior)
    with pytest.raises(EmbeddingCompletenessError) as error:
        embedder.embed_chunks(selected)
    if failure == "exception":
        assert str(error.value) == "Embedding provider request failed"
        assert error.value.__suppress_context__ is True
    assert len(calls) == 2
    assert [(chunk.embedding, chunk.embedding_provenance) for chunk in selected] == before


def test_all_valid_batches_publish_reports_only_after_last_response(monkeypatch, settings):
    selected = chunks()
    before = deepcopy([(chunk.embedding, chunk.embedding_provenance) for chunk in selected])
    def behavior(kwargs, position):
        assert [(chunk.embedding, chunk.embedding_provenance) for chunk in selected] == before
        return valid(kwargs, position)
    calls = provider(monkeypatch, behavior)
    embedder.embed_chunks(selected)
    assert len(calls) == 3
    for chunk in selected:
        value = validate_embedding_provenance(chunk.embedding_provenance, text=chunk.text,
            vector=chunk.embedding, expected_task="RETRIEVAL_DOCUMENT")
        assert value["local_count"] == embedder.count_tokens(chunk.text) != chunk.token_count
        assert value["provider_token_count"] == 8
        assert value["local_count_method"] == "tiktoken-cl100k_base/1"
    assert all(call["config"].auto_truncate is False and call["config"].task_type == "RETRIEVAL_DOCUMENT" for call in calls)


def test_late_oversized_input_rejects_whole_inventory_before_first_call(monkeypatch, settings):
    selected = chunks()
    selected[-1].text = "overflow " * 1600
    calls = provider(monkeypatch, valid)
    with pytest.raises(EmbeddingCompletenessError):
        embedder.embed_chunks(selected)
    assert calls == [] and selected[0].embedding == [9.0] * 768


@pytest.mark.parametrize("field,value", [("embedding_model", "gemini-embedding-001"),
                                          ("embedding_output_dimensionality", 256), ("embed_batch_size", 251)])
def test_unknown_space_or_invalid_batch_configuration_refused_pre_call(monkeypatch, settings, field, value):
    setattr(settings, field, value)
    calls = provider(monkeypatch, valid)
    with pytest.raises(EmbeddingCompletenessError):
        embedder.embed_chunks(chunks())
    assert calls == []


def test_mutated_input_during_provider_response_never_gets_mismatched_vector(monkeypatch, settings):
    selected = chunks()
    def behavior(kwargs, position):
        if position == 3:
            selected[0].text = "Changed full text"
        return valid(kwargs, position)
    provider(monkeypatch, behavior)
    with pytest.raises(EmbeddingCompletenessError, match="inputs changed"):
        embedder.embed_chunks(selected)
    assert all(chunk.embedding == [9.0] * 768 for chunk in selected)


def test_query_remains_explicit_query_task_and_checks_provider_statistics(monkeypatch, settings):
    calls = provider(monkeypatch, valid)
    assert len(embedder.embed_query("Synthetic query")) == 768
    assert calls[0]["config"].task_type == "RETRIEVAL_QUERY" and calls[0]["config"].auto_truncate is False


def test_batch_packing_uses_actual_local_counts_and_never_sends_one_oversized_chunk(monkeypatch, settings):
    selected = chunks()
    monkeypatch.setattr(embedder, "count_tokens", lambda _text: 700)
    monkeypatch.setattr(embedder, "_MAX_TOKENS_PER_REQUEST", 1600)
    assert list(embedder._batched_by_tokens(selected)) == [selected[:2], selected[2:]]
    monkeypatch.setattr(embedder, "count_tokens", lambda _text: 1537)
    with pytest.raises(EmbeddingCompletenessError):
        list(embedder._batched_by_tokens(selected))
