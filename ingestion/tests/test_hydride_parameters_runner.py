"""Tests for hydride parameter runner helpers."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ingestion import hydride_parameters as runner
from ingestion.extract.hydride_ner import HydrideExtractionBatch, hydride_proposal
from ingestion.hydride_parameters import _dedupe_upsert_values, _read_manifest


def test_read_manifest_keeps_explicit_aps_id_separate_from_doi(tmp_path) -> None:
    manifest = tmp_path / "manifest.txt"
    manifest.write_text(
        "aps:10.1103/PhysRevB.111.184512\n10.1103/PhysRevB.111.134516\narxiv:2505.05176",
        encoding="utf-8",
    )

    ids, dois = _read_manifest(manifest)

    assert "aps:10.1103/PhysRevB.111.184512" in ids
    assert "arxiv:2505.05176" in ids
    assert "10.1103/PhysRevB.111.184512" not in dois
    assert "10.1103/PhysRevB.111.134516" in dois


def test_dedupe_upsert_values_keeps_highest_confidence() -> None:
    values = [
        {"record_key": "same", "confidence": 0.4, "formula": "H3S"},
        {"record_key": "other", "confidence": None, "formula": "LaH10"},
        {"record_key": "same", "confidence": 0.9, "formula": "D3S"},
    ]

    deduped = _dedupe_upsert_values(values)

    assert len(deduped) == 2
    by_key = {row["record_key"]: row for row in deduped}
    assert by_key["same"]["formula"] == "D3S"


def _proposal_batch():
    batch = HydrideExtractionBatch()
    proposal = hydride_proposal(
        {"formula": "LaH10", "tc_kelvin": "80–95 K", "pressure_gpa": "20 kbar"}
    )
    proposal.update(scalar_row_eligible=False, exclusion_reason="non_scalar_tc")
    batch.proposals.append(proposal)
    return batch


def test_runner_journals_unpersisted_proposal_before_parameter_write(monkeypatch, tmp_path):
    journal = tmp_path / "checkpoint.jsonl"
    batch = _proposal_batch()
    monkeypatch.setattr(runner, "_rebuild_parsed_from_chunks", AsyncMock(return_value=object()))
    monkeypatch.setattr(runner, "extract_hydride_parameters", lambda _parsed: batch)

    async def check_upsert(*_args):
        event = json.loads(journal.read_text())
        assert event["stage"] == "extraction_proposals"
        assert event["proposals"][0]["raw_extraction"]["tc_kelvin"] == "80–95 K"
        return 0

    monkeypatch.setattr(runner, "_upsert_records", check_upsert)
    session = SimpleNamespace(rollback=AsyncMock())
    event = asyncio.run(
        runner._process_row(
            session,
            {"id": "synthetic:test", "source": "arxiv"},
            aps_client=None,
            dry_run=False,
            material_cache={},
            proposal_checkpoint=journal,
        )
    )
    assert event["ok"] is True
    assert event["n_unpersisted_proposals"] == 1
    assert event["persisted"] == 0


def test_runner_does_not_write_database_when_proposal_journal_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_rebuild_parsed_from_chunks", AsyncMock(return_value=object()))
    monkeypatch.setattr(runner, "extract_hydride_parameters", lambda _parsed: _proposal_batch())

    def no_disk(*_args):
        raise OSError("synthetic journal unavailable")

    monkeypatch.setattr(runner, "_append_checkpoint", no_disk)
    upsert = AsyncMock()
    monkeypatch.setattr(runner, "_upsert_records", upsert)
    session = SimpleNamespace(rollback=AsyncMock())
    event = asyncio.run(
        runner._process_row(
            session,
            {"id": "synthetic:test", "source": "arxiv"},
            aps_client=None,
            dry_run=False,
            material_cache={},
            proposal_checkpoint=tmp_path / "checkpoint.jsonl",
        )
    )
    assert event["ok"] is False
    upsert.assert_not_called()
    session.rollback.assert_awaited_once()


def test_missing_checkpoint_is_rejected_before_any_extraction():
    with pytest.raises(ValueError, match="checkpoint"):
        runner._ensure_checkpoint_writable(None)
