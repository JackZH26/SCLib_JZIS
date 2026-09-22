"""Offline orchestration observations with synthetic provider/storage doubles."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ingestion import aps_pipeline, pipeline
from ingestion.chunk import chunker
from ingestion.embedding_contract import (
    DIMENSION,
    LOCAL_DOCUMENT_COUNT_METHOD,
    LOCAL_DOCUMENT_INPUT_LIMIT,
    LOCAL_DOCUMENT_REQUEST_LIMIT,
    MODEL,
    validate_embedding_response,
)
from ingestion.extract import fact_sentences
from ingestion.extract.fact_sentences import FactChunkLimitError
from ingestion.models import ApsArticleMeta, PaperMetadata, ParsedPaper, Section


def _embed_complete(chunks):
    for item in chunks:
        item.embedding, item.embedding_provenance = validate_embedding_response(
            [item.text], {"embeddings": [{"values": [0.25] * DIMENSION,
                "statistics": {"truncated": False, "token_count": 17.0}}]},
            model=MODEL, dimension=DIMENSION, task_type="RETRIEVAL_DOCUMENT",
            local_counts=[chunker.count_tokens(item.text)],
            local_count_method=LOCAL_DOCUMENT_COUNT_METHOD,
            local_input_limit=LOCAL_DOCUMENT_INPUT_LIMIT,
            local_request_limit=LOCAL_DOCUMENT_REQUEST_LIMIT,
        )[0]


def _clock(monkeypatch, module, values=(10, 10.125, 20, 20.75)):
    ticks = iter(values)
    monkeypatch.setattr(module, "perf_counter", lambda: next(ticks))


@pytest.fixture
def arxiv_flow(monkeypatch):
    meta = PaperMetadata(arxiv_id="2609.00001", title="Synthetic title", authors=[],
                         abstract="Abstract conditions and materials. " * 150,
                         date_submitted=None, categories=[], primary_category=None)
    monkeypatch.setattr(pipeline.storage, "archive_arxiv_capture_manifest", lambda _: "synthetic-manifest")
    monkeypatch.setattr(pipeline, "embed_chunks", _embed_complete)
    write = AsyncMock()
    monkeypatch.setattr(pipeline, "upsert_paper_with_chunks", write)
    _clock(monkeypatch, pipeline)
    return meta, write


@pytest.mark.asyncio
async def test_arxiv_reports_full_counts_complete_receipts_timings_and_unknown_cost(arxiv_flow, caplog):
    meta, write = arxiv_flow
    result = await pipeline.process_paper(object(), meta, strategy="abstract_only",
                                         skip_vector_search=True, skip_ner=True, skip_geo=True)
    assert result["ok"]
    chunks = write.await_args.args[1]
    observation = result["input_observation"]
    assert observation["chunk"]["count"] == len(chunks) > 1
    assert observation["chunk"]["local_token_total"] == sum(chunker.count_tokens(c.text) for c in chunks)
    assert observation["chunk"]["local_token_max"] == max(chunker.count_tokens(c.text) for c in chunks)
    assert observation["chunk"]["duration_ms"] == 125
    assert observation["embedding"]["duration_ms"] == 750
    assert observation["embedding"]["validated_complete_count"] == len(chunks)
    assert observation["embedding"]["provider_token_total_for_validated_inputs"] == 17 * len(chunks)
    assert observation["cost"] == {"status": "unknown", "amount": None, "currency": None}
    with caplog.at_level("INFO"):
        pipeline._print_status(result)
    assert "input_observation=" in caplog.text
    assert "Abstract conditions" not in json.dumps(observation)


@pytest.mark.asyncio
async def test_arxiv_mock_without_provenance_is_unavailable_not_complete(monkeypatch, arxiv_flow):
    meta, _ = arxiv_flow
    monkeypatch.setattr(pipeline, "embed_chunks", lambda _: None)
    result = await pipeline.process_paper(object(), meta, strategy="abstract_only",
                                         skip_vector_search=True, skip_ner=True, skip_geo=True)
    assert result["ok"]
    embed = result["input_observation"]["embedding"]
    assert embed["stage_status"] == "returned"
    assert embed["completeness_status"] == "unavailable"
    assert embed["validated_complete_count"] == 0
    assert embed["provider_token_total_for_validated_inputs"] is None


@pytest.mark.asyncio
async def test_failed_arxiv_embedding_cannot_attribute_preexisting_reports(monkeypatch, arxiv_flow):
    meta, write = arxiv_flow
    def fail_with_existing_receipts(chunks):
        _embed_complete(chunks)
        raise RuntimeError("synthetic provider failure")
    monkeypatch.setattr(pipeline, "embed_chunks", fail_with_existing_receipts)
    result = await pipeline.process_paper(object(), meta, strategy="abstract_only",
                                         skip_vector_search=True, skip_ner=True, skip_geo=True)
    assert not result["ok"] and result["stage"] == "embed"
    embed = result["input_observation"]["embedding"]
    assert embed["stage_status"] == "failed" and embed["reason_code"] == "embedding_stage_failed"
    assert embed["duration_ms"] == 750
    assert embed["validated_complete_count"] is None
    assert embed["provider_token_total_for_validated_inputs"] is None
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_arxiv_fact_limit_exception_is_a_fixed_code_not_exception_payload(monkeypatch, arxiv_flow):
    meta, write = arxiv_flow
    def reject(_):
        error = FactChunkLimitError("PRIVATE_RESULT_SENTINEL")
        error.reason_code = "PRIVATE_REASON_SENTINEL"
        raise error
    monkeypatch.setattr(pipeline, "chunk_paper", reject)
    embed = Mock()
    monkeypatch.setattr(pipeline, "embed_chunks", embed)
    result = await pipeline.process_paper(object(), meta, strategy="abstract_only",
                                         skip_vector_search=True, skip_ner=True, skip_geo=True)
    assert result["error"] == result["reason_code"] == FactChunkLimitError.reason_code
    assert result["input_observation"]["chunk"]["duration_ms"] == 125
    assert result["input_observation"]["embedding"]["stage_status"] == "not_attempted"
    assert "PRIVATE_" not in json.dumps(result)
    embed.assert_not_called()
    write.assert_not_awaited()


@pytest.fixture
def aps_flow(monkeypatch):
    meta = ApsArticleMeta(doi="10.0000/Synthetic.Observation", title="Synthetic title", authors=[],
                          abstract="Synthetic abstract.", journal_abbrev="SYN")
    client = SimpleNamespace(get_article=AsyncMock(return_value=meta),
                             download_bagit=AsyncMock(return_value=b"synthetic"))
    class MemoryWork:
        def __init__(self, _):
            self.root = None
            self.deleted = False
            self.deleted_at = None
            self.bagit_bytes = 0
            self.files = []
        def __enter__(self):
            return self
        def extract(self, body):
            self.bagit_bytes = len(body)
        def __exit__(self, *_):
            self.deleted = True
            self.deleted_at = datetime(2026, 9, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(aps_pipeline, "TempBagit", MemoryWork)
    monkeypatch.setattr(aps_pipeline, "parse_bagit_payload", lambda *_: SimpleNamespace(
        parsed=ParsedPaper(meta=meta, sections=[Section("Body", "PRIVATE_SOURCE_SENTINEL")]),
        parser_mode="jats", source_path=Path("synthetic.xml"),
    ))
    monkeypatch.setattr(aps_pipeline, "extract_materials", lambda _: [{"formula": "Nb", "tc_kelvin": "9.2 K"}])
    monkeypatch.setattr(aps_pipeline, "embed_chunks", _embed_complete)
    write, audit, related = AsyncMock(), AsyncMock(), AsyncMock(return_value=None)
    publish = Mock()
    monkeypatch.setattr(aps_pipeline, "upsert_aps_paper_with_chunks", write)
    monkeypatch.setattr(aps_pipeline, "upsert_aps_chunks_to_vector_search", publish)
    monkeypatch.setattr(aps_pipeline, "find_related_arxiv_paper", related)
    monkeypatch.setattr(aps_pipeline, "write_audit_log", audit)
    _clock(monkeypatch, aps_pipeline)
    return SimpleNamespace(meta=meta, client=client, write=write, audit=audit, publish=publish,
                           related=related)


@pytest.mark.asyncio
async def test_aps_observes_abstract_and_facts_but_not_transient_body(aps_flow):
    flow = aps_flow
    result = await aps_pipeline.process_aps_paper(flow.client, flow.meta.doi)
    assert result["ok"]
    chunks = flow.write.await_args.args[1]
    observation = result["input_observation"]
    assert {c.section for c in chunks} == {"Abstract", "Facts"}
    assert observation["chunk"]["count"] == observation["embedding"]["validated_complete_count"] == 2
    assert observation["embedding"]["provider_token_total_for_validated_inputs"] == 34
    assert observation["chunk"]["duration_ms"] == 125
    assert observation["embedding"]["duration_ms"] == 750
    assert "PRIVATE_SOURCE_SENTINEL" not in json.dumps(result)
    assert flow.audit.await_args.args[0].deletion_confirmed


@pytest.mark.asyncio
@pytest.mark.parametrize("option,reason", [("dry_run", "dry_run"), ("skip_vector_search", "vector_search_skipped")])
async def test_aps_skip_and_dry_run_do_not_claim_embedding_completion(monkeypatch, aps_flow, option, reason):
    flow = aps_flow
    embed = Mock()
    monkeypatch.setattr(aps_pipeline, "embed_chunks", embed)
    result = await aps_pipeline.process_aps_paper(flow.client, flow.meta.doi, **{option: True})
    assert result["ok"]
    observed = result["input_observation"]["embedding"]
    assert observed["stage_status"] == "skipped" and observed["reason_code"] == reason
    assert observed["duration_ms"] is None and observed["validated_complete_count"] is None
    assert observed["provider_token_total_for_validated_inputs"] is None
    embed.assert_not_called()


@pytest.mark.asyncio
async def test_actual_oversized_fact_aborts_before_embed_db_vs_and_sanitizes_audit(monkeypatch, aps_flow, caplog):
    flow = aps_flow
    settings = SimpleNamespace(chunk_size_tokens=64, chunk_overlap_tokens=0)
    monkeypatch.setattr(chunker, "get_settings", lambda: settings)
    monkeypatch.setattr(fact_sentences, "get_settings", lambda: settings)
    record = {"formula": "Nb", "tc_kelvin": "9.2 K", "result_status": "not_detected",
              "minimum_temperature_k": "1 K", "knowledge_origin": "Observed", "source_role": "primary",
              "sample_form": "PRIVATE_RESULT_VALUE " * 6}
    monkeypatch.setattr(aps_pipeline, "extract_materials", lambda _: [record])
    embed = Mock()
    monkeypatch.setattr(aps_pipeline, "embed_chunks", embed)
    result = await aps_pipeline.process_aps_paper(flow.client, flow.meta.doi)
    assert result["ok"] is False and result["stage"] == "chunk"
    assert result["error"] == result["reason_code"] == FactChunkLimitError.reason_code
    assert result["input_observation"]["chunk"]["reason_code"] == FactChunkLimitError.reason_code
    assert result["input_observation"]["chunk"]["count"] is None
    assert result["input_observation"]["chunk"]["duration_ms"] == 125
    assert result["input_observation"]["embedding"]["stage_status"] == "not_attempted"
    audit = flow.audit.await_args.args[0]
    assert audit.status == "error" and audit.error == FactChunkLimitError.reason_code
    assert audit.deletion_confirmed
    assert "PRIVATE_RESULT_VALUE" not in json.dumps(result) + str(audit.to_values()) + caplog.text
    assert "PRIVATE_SOURCE_SENTINEL" not in json.dumps(result) + str(audit.to_values()) + caplog.text
    embed.assert_not_called()
    flow.write.assert_not_awaited()
    flow.related.assert_not_awaited()
    flow.publish.assert_not_called()
