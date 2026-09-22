"""Capture/retry failure paths with only in-memory synthetic dependencies."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ingestion import pipeline, storage
from ingestion.extract.material_ner import _MAX_CHARS, _assemble_text
from ingestion.models import Chunk, PaperMetadata, ParsedPaper, Section


def metadata(identifier="2602.00001v1"):
    return PaperMetadata(arxiv_id=identifier, title="Synthetic capture", authors=[],
                         abstract="Synthetic public metadata", date_submitted=date(2026, 2, 1),
                         categories=[], primary_category=None)


@pytest.fixture
def capture_flow(monkeypatch):
    seen = {"manifests": [], "order": []}
    def archive(value):
        seen["order"].append("archive")
        seen["manifests"].append(copy.deepcopy(value))
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        return f"captures/arxiv/manifests/sha256/{digest}.json"
    def chunk(parsed):
        seen["order"].append("chunk")
        return [Chunk(id="synthetic-chunk", paper_id=parsed.meta.paper_id, chunk_index=0,
                      section="Body", text="Synthetic body", token_count=2)]
    def embed(_):
        seen["order"].append("embed")
    def extract(_):
        seen["order"].append("ner")
        return [{"formula": "SYNTHETIC"}]
    monkeypatch.setattr(storage, "archive_arxiv_capture_manifest", archive)
    monkeypatch.setattr(pipeline, "chunk_paper", chunk)
    monkeypatch.setattr(pipeline, "embed_chunks", embed)
    monkeypatch.setattr(pipeline, "extract_materials", extract)
    monkeypatch.setattr(pipeline, "upsert_paper_with_chunks", AsyncMock())
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["chunk", "embed"])
async def test_prepared_input_and_source_observation_survive_early_failure(monkeypatch, capture_flow, stage):
    parsed = ParsedPaper(meta=metadata(), sections=[Section("Results", "Synthetic body " * 2000)],
                         ingestion_capture={"artifact": {"sha256": "a" * 64,
                                            "captured_at": "2026-09-07T00:00:00Z",
                                            "storage_object": "captures/arxiv/synthetic/source"}})
    body = _assemble_text(parsed)
    def broken(_):
        capture_flow["order"].append(stage)
        raise RuntimeError("synthetic downstream failure")
    monkeypatch.setattr(pipeline, "chunk_paper" if stage == "chunk" else "embed_chunks", broken)
    result = await pipeline._finish(parsed, True, False, True, {"arxiv_id": parsed.meta.arxiv_id, "ok": False})
    assert result["ok"] is False and result["stage"] == stage
    assert capture_flow["order"][0] == "archive"
    assert "ner" not in capture_flow["order"]
    assert len(capture_flow["manifests"]) == 1
    capture = result["ingestion_capture"]
    assert capture["artifact"]["captured_at"] == "2026-09-07T00:00:00Z"
    assert capture["ner_input"]["status"] == "prepared"
    assert capture["ner_input"]["sha256"] == hashlib.sha256(body[:_MAX_CHARS].encode()).hexdigest()
    assert capture["manifest_object"].startswith("captures/arxiv/manifests/sha256/")
    assert "Synthetic body" not in json.dumps(capture)
    pool = {}
    failure = storage.record_failure(pool, parsed.meta, stage=stage, error="synthetic")
    pipeline._retain_capture_reference(failure, result)
    assert failure.meta["last_capture_manifest_object"] == capture["manifest_object"]
    assert PaperMetadata.from_dict(failure.meta).download_id == parsed.meta.download_id


@pytest.mark.asyncio
async def test_attempted_manifest_is_separate_and_keeps_preparation_reference(capture_flow):
    parsed = ParsedPaper(meta=metadata(), sections=[Section("Results", "Synthetic body")])
    result = await pipeline._finish(parsed, True, False, True, {"arxiv_id": parsed.meta.arxiv_id, "ok": False})
    assert result["ok"]
    first, final = capture_flow["manifests"]
    assert first["ner_input"]["status"] == "prepared"
    assert final["ner_input"]["status"] == "attempted"
    assert final["captured_at"] == first["captured_at"]
    assert final["ner_input"]["sha256"] == first["ner_input"]["sha256"]
    assert "manifest_object" not in first and "manifest_object" not in final
    assert final["prepared_manifest_object"].startswith("captures/arxiv/manifests/sha256/")
    assert result["ingestion_capture"]["manifest_object"] != final["prepared_manifest_object"]


@pytest.mark.asyncio
async def test_skipped_ner_keeps_not_run_and_only_one_manifest(capture_flow):
    parsed = ParsedPaper(meta=metadata(), sections=[])
    result = await pipeline._finish(parsed, True, True, True, {"arxiv_id": parsed.meta.arxiv_id, "ok": False})
    assert result["ok"]
    assert len(capture_flow["manifests"]) == 1
    assert result["ingestion_capture"]["ner_input"]["status"] == "not_run"
    assert result["ingestion_capture"]["ner_input"]["sha256"] is None
    assert "ner" not in capture_flow["order"]


@pytest.mark.asyncio
async def test_initial_archive_failure_prevents_paid_work(monkeypatch, capture_flow):
    def unavailable(_):
        raise RuntimeError("synthetic archive unavailable")
    monkeypatch.setattr(storage, "archive_arxiv_capture_manifest", unavailable)
    parsed = ParsedPaper(meta=metadata(), sections=[])
    result = await pipeline._finish(parsed, True, False, True, {"arxiv_id": parsed.meta.arxiv_id, "ok": False})
    assert result["stage"] == "capture" and not result["ok"]
    assert capture_flow["order"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_meta", [
    {"arxiv_id": "0607123"},  # missing old-style archive prefix cannot be guessed
    {"arxiv_id": "2602.00001v0"},
    {"arxiv_id": "2602.00001v1", "requested_version": "v2"},
    {"arxiv_id": "2602.00001v2"},  # valid ID but mismatched saved retry identity
    None,
])
async def test_bad_legacy_retry_metadata_is_retained_without_aborting_later_entries(monkeypatch, bad_meta):
    original = {**metadata().to_dict(), **bad_meta} if isinstance(bad_meta, dict) else bad_meta
    bad = storage.FailedPaper(arxiv_id="2602.00001v1", yymm="2602", meta=copy.deepcopy(original),
                              first_failed_at="2026-01-01T00:00:00Z", last_failed_at="2026-01-01T00:00:00Z")
    valid_meta = metadata("2602.00002v1")
    valid = storage.FailedPaper(arxiv_id=valid_meta.download_id, yymm="2602", meta=valid_meta.to_dict(),
                                first_failed_at="2026-01-02T00:00:00Z", last_failed_at="2026-01-02T00:00:00Z")
    pool = {bad.arxiv_id: bad, valid.arxiv_id: valid}
    saved = []
    class LocalClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
    process = AsyncMock(return_value={"arxiv_id": valid_meta.arxiv_id, "ok": True})
    monkeypatch.setattr(pipeline, "get_settings", lambda: SimpleNamespace(failure_max_attempts=5))
    monkeypatch.setattr(storage, "load_failed_papers", lambda: pool)
    monkeypatch.setattr(storage, "save_failed_papers", lambda values: saved.append(copy.deepcopy(values)))
    monkeypatch.setattr(pipeline, "ArxivClient", LocalClient)
    monkeypatch.setattr(pipeline, "process_paper", process)
    result = await pipeline._run_retry(limit=None)
    assert [item["ok"] for item in result] == [False, True]
    assert result[0]["stage"] == "metadata" and result[0]["terminal"] is True
    assert "manual review required" in result[0]["error"]
    assert process.await_count == 1 and process.await_args.args[1].download_id == valid_meta.download_id
    assert saved and set(saved[0]) == {bad.arxiv_id}
    assert saved[0][bad.arxiv_id].meta == original
    assert saved[0][bad.arxiv_id].status == "dead"
    assert saved[0][bad.arxiv_id].last_stage == "metadata"


@pytest.mark.parametrize("value", ["https://example.test/secret", "captures/arxiv/manifests/sha256/../bad.json", None])
def test_failure_reference_cannot_copy_arbitrary_payload(value):
    failure = storage.record_failure({}, metadata(), stage="synthetic", error="synthetic")
    pipeline._retain_capture_reference(failure, {"ingestion_capture": {"manifest_object": value, "text": "SECRET"}})
    assert "last_capture_manifest_object" not in failure.meta
    assert "SECRET" not in str(failure.meta)
