"""Offline strict embedding contract/query tests; never contact a provider."""
from __future__ import annotations

import hashlib
import struct
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import models as sdk_models
from google.genai import types as sdk_types

from services import embedding_contract as contract
from services import vector_search


def arguments(texts, **changes):
    return {
        "model": contract.MODEL, "dimension": 768, "task_type": "RETRIEVAL_QUERY",
        "local_counts": [len(text.encode()) for text in texts],
        "local_count_method": contract.LOCAL_QUERY_COUNT_METHOD,
        "local_input_limit": 8192, "local_request_limit": 8192, **changes,
    }


def response(*, statistics=None, values=None, count=1):
    return SimpleNamespace(embeddings=[SimpleNamespace(
        values=[0.1] * 768 if values is None else values,
        statistics={"truncated": False, "token_count": 13.0} if statistics is None else statistics,
    ) for _ in range(count)])


def test_contract_mirrors_match_and_valid_report_binds_actual_float32_transport():
    root = Path(__file__).resolve().parents[2]
    assert (root / "api/services/embedding_contract.py").read_bytes() == (
        root / "ingestion/ingestion/embedding_contract.py").read_bytes()
    [(vector, metadata)] = contract.validate_embedding_response(["Synthetic query"], response(), **arguments(["Synthetic query"]))
    expected = struct.unpack("!f", struct.pack("!f", 0.1))[0]
    assert vector == [expected] * 768 and expected != 0.1
    assert metadata["vector_sha256"] == hashlib.sha256(struct.pack("!768f", *vector)).hexdigest()
    assert metadata["content_sha256"] == hashlib.sha256(b"Synthetic query").hexdigest()
    assert type(metadata["provider_token_count"]) is int and metadata["provider_token_count"] == 13
    assert metadata["completeness_status"] == "provider_reported_complete"
    assert len(metadata) == 17 and "uploaded" not in metadata and "active" not in metadata


@pytest.mark.parametrize("statistics", [
    {}, {"token_count": 1}, {"truncated": False},
    {"truncated": True, "token_count": 1}, {"truncated": None, "token_count": 1},
    {"truncated": 0, "token_count": 1}, {"truncated": "false", "token_count": 1},
    *[{"truncated": False, "token_count": value} for value in (None, True, 0, -1, 1.5, "1", float("nan"), float("inf"), 2049)],
])
def test_missing_truncated_or_unusable_provider_statistics_are_rejected(statistics):
    with pytest.raises(contract.EmbeddingCompletenessError):
        contract.validate_embedding_response(["Synthetic"], response(statistics=statistics), **arguments(["Synthetic"]))


@pytest.mark.parametrize("values", [
    [], [1.0] * 767, [1.0] * 769, [None] * 768, [True] * 768, ["0.1"] * 768,
    [float("inf")] * 768, [float("nan")] * 768, [1e100] * 768, [1e-50] * 768, [0.0] * 768,
])
def test_wrong_dimensions_nonfinite_and_float32_unusable_vectors_are_rejected(values):
    with pytest.raises(contract.EmbeddingCompletenessError):
        contract.validate_embedding_response(["Synthetic"], response(values=values), **arguments(["Synthetic"]))


def test_negative_zero_normalizes_and_partial_underflow_is_explicit_float32_conversion():
    vector = [1.0, -0.0, 1e-50] + [0.5] * 765
    canonical = contract.validate_vector(vector)
    assert canonical[1:3] == [0.0, 0.0]
    assert struct.pack("!f", canonical[1]) == b"\0\0\0\0"
    assert contract.vector_sha256(vector) == contract.vector_sha256(canonical)


@pytest.mark.parametrize("count", [0, 2])
def test_exact_response_inventory_required(count):
    with pytest.raises(contract.EmbeddingCompletenessError):
        contract.validate_embedding_response(["Synthetic"], response(count=count), **arguments(["Synthetic"]))


def test_provider_aggregate_budget_is_checked_independently_of_local_estimate():
    texts = ["x"] * 10
    # Local counts are small, but 10 * provider2048 exceeds the20k provider cap.
    with pytest.raises(contract.EmbeddingCompletenessError, match="request token budget"):
        contract.validate_embedding_response(texts, response(count=10, statistics={"truncated": False, "token_count": 2048}),
                                             **arguments(texts))


@pytest.mark.parametrize("changes", [
    {"model": "unreviewed-model"}, {"dimension": 256}, {"dimension": True},
    {"task_type": "SEMANTIC_SIMILARITY"}, {"local_count_method": "provider-exact-guessed"},
    {"local_input_limit": 8193}, {"local_counts": [True]}, {"local_counts": [1]},
])
def test_unknown_profile_and_invalid_local_admission_rejected(changes):
    with pytest.raises(contract.EmbeddingCompletenessError):
        contract.validate_embedding_inputs(["Synthetic"], **arguments(["Synthetic"], **changes))


def test_provenance_has_closed_fields_and_actual_consumer_hash_and_task_checks():
    [(vector, metadata)] = contract.validate_embedding_response(["Synthetic"], response(), **arguments(["Synthetic"]))
    before = deepcopy(metadata)
    assert contract.validate_embedding_provenance(metadata, text="Synthetic", vector=vector,
                                                  expected_task="RETRIEVAL_QUERY") == metadata
    for changes in ({"auto_truncate": True}, {"provider_truncated": 0}, {"provider_token_count": 13.0},
                    {"uploaded": True}, {"content_sha256": "a" * 64}, {"vector_sha256": "b" * 64}):
        with pytest.raises(contract.EmbeddingCompletenessError):
            contract.validate_embedding_provenance({**metadata, **changes}, text="Synthetic", vector=vector)
    with pytest.raises(contract.EmbeddingCompletenessError):
        contract.validate_embedding_provenance(metadata, expected_task="RETRIEVAL_DOCUMENT")
    assert metadata == before


def test_installed_sdk_preserves_autotruncate_false_and_explicit_statistics():
    config = sdk_types.EmbedContentConfig(task_type="RETRIEVAL_QUERY", output_dimensionality=768,
                                         auto_truncate=False)
    wire = {"instances": [{"content": "Synthetic"}]}
    sdk_models._EmbedContentConfig_to_vertex(config.model_dump(), wire)
    assert wire["parameters"] == {"outputDimensionality": 768, "autoTruncate": False}
    assert wire["instances"][0]["task_type"] == "RETRIEVAL_QUERY"
    parsed = sdk_types.EmbedContentResponse.model_validate(sdk_models._EmbedContentResponse_from_vertex({
        "predictions": [{"embeddings": {"values": [0.1] * 768,
                                         "statistics": {"truncated": False, "token_count": 13}}}],
    }))
    assert parsed.embeddings[0].statistics.truncated is False
    assert parsed.embeddings[0].statistics.token_count == 13.0
    assert contract.validate_embedding_response(["Synthetic"], parsed, **arguments(["Synthetic"]))


@pytest.mark.parametrize("bad", [False, True])
def test_api_query_uses_query_task_disables_truncation_and_refuses_bad_response(monkeypatch, bad):
    calls = []
    monkeypatch.setattr(vector_search, "get_settings", lambda: SimpleNamespace(
        embedding_model=contract.MODEL, embedding_output_dimensionality=768))
    def embed_content(**kwargs):
        calls.append(kwargs)
        return response(statistics={} if bad else None)
    monkeypatch.setattr(vector_search, "genai_client", lambda: SimpleNamespace(models=SimpleNamespace(embed_content=embed_content)))
    if bad:
        with pytest.raises(contract.EmbeddingCompletenessError):
            vector_search.embed_query("合成查询")
    else:
        assert vector_search.embed_query("合成查询") == contract.validate_vector([0.1] * 768)
    assert len(calls) == 1 and calls[0]["contents"] == ["合成查询"]
    assert calls[0]["config"].auto_truncate is False
    assert calls[0]["config"].task_type == "RETRIEVAL_QUERY"


@pytest.mark.parametrize("value", ["", " ", "x" * 8193, "\ud800", None])
def test_api_invalid_input_never_constructs_provider_client(monkeypatch, value):
    monkeypatch.setattr(vector_search, "get_settings", lambda: SimpleNamespace(
        embedding_model=contract.MODEL, embedding_output_dimensionality=768))
    def forbidden():
        raise AssertionError("Invalid input must not call provider")
    monkeypatch.setattr(vector_search, "genai_client", forbidden)
    with pytest.raises(contract.EmbeddingCompletenessError):
        vector_search.embed_query(value)


def test_api_provider_exception_does_not_expose_request_payload(monkeypatch):
    monkeypatch.setattr(vector_search, "get_settings", lambda: SimpleNamespace(
        embedding_model=contract.MODEL, embedding_output_dimensionality=768))
    def broken():
        raise RuntimeError("PRIVATE_PROVIDER_PAYLOAD_SENTINEL")
    monkeypatch.setattr(vector_search, "genai_client", broken)
    with pytest.raises(contract.EmbeddingCompletenessError) as error:
        vector_search.embed_query("Synthetic")
    assert str(error.value) == "Embedding provider request failed"
    assert error.value.__suppress_context__ is True
