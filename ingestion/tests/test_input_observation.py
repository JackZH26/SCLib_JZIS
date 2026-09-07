"""Pure text-free per-attempt observations; no provider or storage calls."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from ingestion.chunk.chunker import count_tokens
from ingestion.embedding_contract import (
    DIMENSION,
    LOCAL_DOCUMENT_COUNT_METHOD,
    LOCAL_DOCUMENT_INPUT_LIMIT,
    LOCAL_DOCUMENT_REQUEST_LIMIT,
    MODEL,
    validate_embedding_response,
)
from ingestion.input_observation import new_input_observation, observe_chunks, observe_embeddings
from ingestion.models import Chunk


def chunk(text="Synthetic text", index=0):
    return Chunk(id=f"synthetic_chunk_{index}", paper_id="synthetic", chunk_index=index,
                 section="Results", text=text, token_count=99999)


def complete(item, provider_count=17):
    item.embedding, item.embedding_provenance = validate_embedding_response(
        [item.text], {"embeddings": [{"values": [0.25] * DIMENSION,
            "statistics": {"truncated": False, "token_count": float(provider_count)}}]},
        model=MODEL, dimension=DIMENSION, task_type="RETRIEVAL_DOCUMENT",
        local_counts=[count_tokens(item.text)], local_count_method=LOCAL_DOCUMENT_COUNT_METHOD,
        local_input_limit=LOCAL_DOCUMENT_INPUT_LIMIT,
        local_request_limit=LOCAL_DOCUMENT_REQUEST_LIMIT,
    )[0]
    return item


def test_chunk_counts_recount_full_text_and_keep_prefix_whitespace_and_unicode():
    chunks = [chunk("Title: Synthetic\nSection: Results\n\n超导😀\r\n\t"), chunk("alpha\n\nbeta", 1)]
    before = deepcopy(chunks)
    result = observe_chunks(chunks, status="returned", duration_seconds=0.125)
    counts = [count_tokens(item.text) for item in chunks]
    assert result == {"stage_status": "returned", "duration_ms": 125.0, "reason_code": None,
                      "count": 2, "local_count_method": "tiktoken-cl100k_base/1",
                      "measurement_status": "complete", "local_token_total": sum(counts),
                      "local_token_max": max(counts)}
    assert chunks == before


def test_only_validated_current_complete_receipts_contribute_provider_counts():
    first, second = complete(chunk(), 17), complete(chunk("Another input", 1), 23)
    before = deepcopy([first, second])
    result = observe_embeddings([first, second], status="returned", duration_seconds=0.5)
    assert result["completeness_status"] == "complete"
    assert result["validated_complete_count"] == 2
    assert result["provider_token_total_for_validated_inputs"] == 40
    assert result["unavailable_count"] == result["invalid_count"] == 0
    assert result["duration_ms"] == 500
    assert [first, second] == before


def test_missing_mock_provenance_does_not_fabricate_completion_or_zero_cost():
    item = chunk()
    item.embedding = [0.25] * DIMENSION
    result = observe_embeddings([item], status="returned")
    assert result["completeness_status"] == "unavailable"
    assert result["validated_complete_count"] == 0
    assert result["unavailable_count"] == 1
    assert result["provider_token_total_for_validated_inputs"] is None
    observation = new_input_observation()
    observation["embedding"] = result
    assert observation["cost"] == {"status": "unknown", "amount": None, "currency": None}


@pytest.mark.parametrize("status", ["failed", "skipped", "not_attempted"])
def test_old_valid_receipts_are_not_attributed_to_failed_or_skipped_attempt(status):
    result = observe_embeddings([complete(chunk(), 201)], status=status, duration_seconds=0.2)
    assert result["stage_status"] == status
    assert result["completeness_status"] == "unavailable"
    assert result["validated_complete_count"] is None
    assert result["invalid_count"] is None
    assert result["provider_token_total_for_validated_inputs"] is None


@pytest.mark.parametrize("mutation", ["text", "vector", "count", "method", "missing_vector", "malformed"])
def test_malformed_or_stale_receipts_do_not_enter_complete_totals(mutation):
    item = complete(chunk())
    if mutation == "text":
        item.text += " Changed"
    elif mutation == "vector":
        item.embedding[0] = 0.75
    elif mutation == "count":
        item.embedding_provenance["local_count"] = 1
    elif mutation == "method":
        item.embedding_provenance["local_count_method"] = "unknown"
    elif mutation == "missing_vector":
        item.embedding = None
    else:
        item.embedding_provenance = {"source_quote": "PRIVATE_SOURCE_SENTINEL"}
    result = observe_embeddings([item], status="returned")
    assert result["invalid_count"] == 1
    assert result["validated_complete_count"] == 0
    assert result["provider_token_total_for_validated_inputs"] is None
    assert "PRIVATE_SOURCE_SENTINEL" not in json.dumps(result)


def test_partial_returned_coverage_is_not_reported_as_a_complete_request_total():
    valid, missing, invalid = complete(chunk("Input one"), 71), chunk("Input two", 1), chunk("Input three", 2)
    invalid.embedding_provenance = {}
    result = observe_embeddings([valid, missing, invalid], status="returned")
    assert result["completeness_status"] == "partial"
    assert result["validated_complete_count"] == result["unavailable_count"] == result["invalid_count"] == 1
    assert result["provider_token_total_for_validated_inputs"] == 71
    assert "provider_token_total" not in result


@pytest.mark.parametrize("duration", [None, True, -1, float("nan"), float("inf"), 10 ** 1000, "0.1"])
def test_bad_or_unavailable_duration_is_explicitly_unknown(duration):
    result = observe_chunks([chunk()], status="returned", duration_seconds=duration)
    assert result["duration_ms"] is None
    json.dumps(result, allow_nan=False)


def test_empty_inventory_differs_from_unobserved_inventory():
    assert observe_chunks()["count"] is None
    empty = observe_chunks([], status="returned")
    assert empty["count"] == empty["local_token_total"] == empty["local_token_max"] == 0
    assert observe_embeddings([])["input_count"] == 0


def test_fixed_shape_is_bounded_text_free_and_does_not_infer_extra_claims():
    private = "PRIVATE_SOURCE_SENTINEL " * 50
    items = [complete(chunk(private, index)) for index in range(100)]
    observation = new_input_observation()
    observation.update(chunk=observe_chunks(items, status="returned"),
                       embedding=observe_embeddings(items, status="returned"))
    encoded = json.dumps(observation, allow_nan=False)
    assert len(encoded.encode()) < 2048
    assert "PRIVATE_SOURCE_SENTINEL" not in encoded and "synthetic_chunk" not in encoded
    assert "content_sha256" not in encoded and "vector_sha256" not in encoded
    assert "generation" not in encoded and "recall" not in encoded and "permission" not in encoded
    assert observation["scope"] == "input_preparation_only"
    first = new_input_observation()
    first["cost"]["status"] = "not shared"
    assert new_input_observation()["cost"]["status"] == "unknown"


@pytest.mark.parametrize("code", ["PRIVATE_RESULT_SENTINEL", {"private": "value"}, True])
def test_reason_codes_are_closed_not_arbitrary_exception_text(code):
    with pytest.raises(ValueError, match="reason code"):
        observe_chunks(status="failed", reason_code=code)
