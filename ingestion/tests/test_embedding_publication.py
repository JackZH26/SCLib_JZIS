"""Complete batch validation occurs before any cloud-client interaction."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ingestion.chunk.chunker import count_tokens
from ingestion.config import get_settings
from ingestion.embedding_contract import (
    LOCAL_DOCUMENT_COUNT_METHOD,
    LOCAL_DOCUMENT_INPUT_LIMIT,
    LOCAL_DOCUMENT_REQUEST_LIMIT,
    validate_embedding_response,
)
from ingestion.index import indexer
from ingestion.models import ApsArticleMeta, Chunk, PaperMetadata, ParsedPaper


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE_TOKENS", "512")
    monkeypatch.setenv("CHUNK_OVERLAP_TOKENS", "64")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-005")
    monkeypatch.setenv("EMBEDDING_OUTPUT_DIMENSIONALITY", "768")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def fixture(aps=False):
    meta = (ApsArticleMeta(doi="10.0000/synthetic", title="Synthetic", authors=[], abstract="") if aps else
            PaperMetadata(arxiv_id="2609.12345", title="Synthetic", authors=[], abstract="", categories=[],
                          primary_category=None, date_submitted=None))
    chunks = []
    for index in range(2):
        text = f"Synthetic input number {index}."
        count = count_tokens(text)
        vector, report = validate_embedding_response([text], SimpleNamespace(embeddings=[SimpleNamespace(
            values=[0.1] * 768, statistics=SimpleNamespace(truncated=False, token_count=float(count)))]),
            model="text-embedding-005", dimension=768, task_type="RETRIEVAL_DOCUMENT", local_counts=[count],
            local_count_method=LOCAL_DOCUMENT_COUNT_METHOD, local_input_limit=LOCAL_DOCUMENT_INPUT_LIMIT,
            local_request_limit=LOCAL_DOCUMENT_REQUEST_LIMIT)[0]
        chunks.append(Chunk(id=f"{meta.paper_id}_chunk_{index:03}", paper_id=meta.paper_id, chunk_index=index,
            section="Abstract", text=text, token_count=count, embedding=vector, embedding_provenance=report,
            evidence_candidate={"version": "rag-evidence/1.0.0", "chunk_kind": "abstract"}))
    return meta, chunks


def publish(meta, chunks, aps):
    if aps:
        indexer.upsert_aps_chunks_to_vector_search(meta, chunks)
    else:
        indexer.upsert_chunks_to_vector_search(ParsedPaper(meta=meta, sections=[]), chunks)


@pytest.mark.parametrize("aps", [False, True])
def test_valid_complete_batch_has_every_expected_datapoint(monkeypatch, aps):
    meta, chunks = fixture(aps)
    before = deepcopy(chunks)
    cloud = SimpleNamespace(upsert_datapoints=Mock())
    lookup = Mock(return_value=cloud)
    monkeypatch.setattr(indexer, "_index", lookup)
    publish(meta, chunks, aps)
    points = cloud.upsert_datapoints.call_args.kwargs["datapoints"]
    assert [point.datapoint_id for point in points] == [chunk.id for chunk in chunks]
    assert [list(point.feature_vector) for point in points] == [chunk.embedding for chunk in chunks]
    assert chunks == before
    lookup.assert_called_once()


@pytest.mark.parametrize("aps", [False, True])
@pytest.mark.parametrize("bad", ["vector_missing", "report_missing", "text_changed", "vector_changed", "count_changed",
                                "restricted", "no_lineage", "duplicate", "wrong_paper", "truncated", "wrong_task", "extra_field"])
def test_any_invalid_member_rejects_entire_batch_before_cloud(monkeypatch, aps, bad):
    meta, chunks = fixture(aps)
    chunk = chunks[-1]
    if bad == "vector_missing": chunk.embedding = None
    elif bad == "report_missing": chunk.embedding_provenance = None
    elif bad == "text_changed": chunk.text += " Changed."
    elif bad == "vector_changed": chunk.embedding[-1] += 0.1
    elif bad == "count_changed": chunk.token_count += 1
    elif bad == "restricted": chunk.evidence_candidate["permission_status"] = "restricted"
    elif bad == "no_lineage": chunk.evidence_candidate = None
    elif bad == "duplicate": chunk.id = chunks[0].id
    elif bad == "wrong_paper": chunk.paper_id = "other"
    elif bad == "truncated": chunk.embedding_provenance["provider_truncated"] = True
    elif bad == "wrong_task": chunk.embedding_provenance["task_type"] = "RETRIEVAL_QUERY"
    elif bad == "extra_field": chunk.embedding_provenance["scientific_acceptance"] = True
    before = deepcopy(chunks)
    lookup = Mock(side_effect=AssertionError("Must not reach cloud client"))
    monkeypatch.setattr(indexer, "_index", lookup)
    with pytest.raises(ValueError):
        publish(meta, chunks, aps)
    lookup.assert_not_called()
    assert chunks == before
