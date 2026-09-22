"""Offline producer/lineage contract gates; no model, database or vector IO."""
from __future__ import annotations

import ast
import hashlib
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ingestion.chunk.chunker import chunk_paper
from ingestion.extract.fact_sentences import FACT_RENDERER_VERSION
from ingestion.index import indexer
from ingestion.models import Chunk, PaperMetadata, ParsedPaper, Section
from ingestion.rag_evidence_contract import (
    VERSION,
    build_revision_rows,
    canonical,
    validate_candidate,
)

ROOT = Path(__file__).resolve().parents[2]


def test_lineage_pure_contract_is_byte_identical_across_images():
    assert (ROOT / "api/services/rag_evidence_contract.py").read_bytes() == (
        ROOT / "ingestion/ingestion/rag_evidence_contract.py"
    ).read_bytes()


def test_api_current_renderer_matches_actual_ingestion_producer():
    module = ast.parse((ROOT / "api/services/rag_evidence.py").read_text())
    versions = [ast.literal_eval(node.value) for node in module.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "CURRENT_FACT_RENDERER_VERSION" for target in node.targets)]
    assert versions == [FACT_RENDERER_VERSION]


def test_original_producer_never_infers_derived_kind_from_facts_section_name():
    meta = PaperMetadata(arxiv_id="2609.00001", title="Synthetic", authors=[],
                         abstract="Synthetic abstract.", date_submitted=None,
                         categories=[], primary_category=None)
    parsed = ParsedPaper(meta=meta, sections=[Section(name="Facts", text="Original source passage.")])
    passage = chunk_paper(parsed)[0]
    candidate = validate_candidate(passage.evidence_candidate)
    assert candidate["chunk_kind"] == "original_passage"
    assert candidate["parent_record"] is None
    assert candidate["source_capture_id"] is None
    assert candidate["permission_status"] == "unresolved"
    assert candidate["unresolved_reason"] == "original_binding_unreviewed"
    abstract = chunk_paper(ParsedPaper(meta=meta, sections=[]))[0]
    assert validate_candidate(abstract.evidence_candidate)["chunk_kind"] == "abstract"


def test_machine_parent_has_no_original_text_or_raw_extraction_and_never_claims_acceptance():
    record = {"formula": "MgB2", "tc_kelvin": "<2 K", "result_status": "not_detected",
              "minimum_temperature_k": 2, "measurement_method": "resistivity",
              "evidence_text": "LICENSED_BODY_SENTINEL", "raw_extraction": {
                  "source_quote": "PRIVATE_SOURCE_QUOTE_SENTINEL"}}
    before = deepcopy(record)
    candidate = {"version": VERSION, "chunk_kind": "derived_fact", "parent_record": record,
                 "extraction_version": "test-extractor/1", "rendering_version": "test-renderer/1"}
    values = build_revision_rows(paper_id="synthetic:test", chunk_id="synthetic:chunk", chunk_text="Derived controlled text.",
        chunk_binding_sha256="a" * 64, source_snapshot_sha256="b" * 64, candidate=candidate)
    parent = values["extraction"]
    assert parent["input_record_sha256"] == hashlib.sha256(canonical(record)).hexdigest()
    assert parent["scientific_acceptance"] is False
    assert "LICENSED_BODY_SENTINEL" not in str(values)
    assert "PRIVATE_SOURCE_QUOTE_SENTINEL" not in str(values)
    assert "raw_extraction" not in parent and "text" not in parent
    assert values["evidence"]["root_status"] == "unresolved"
    assert values["evidence"]["permission_status"] == "unresolved"
    assert record == before


@pytest.mark.asyncio
async def test_legacy_chunk_without_candidate_performs_no_lineage_write():
    session = AsyncMock()
    legacy = Chunk(id="paper_chunk_000", paper_id="paper", chunk_index=0,
                   section="Facts", text="Legacy content.", token_count=3)
    await indexer._persist_chunk_evidence(session, "paper", [legacy])
    session.execute.assert_not_awaited()
    assert legacy.evidence_candidate is None
    # The frozen ML04 v1 chunk row has no added provenance field/column.
    assert "evidence_candidate" not in indexer.chunks_table.c
    assert "evidence_revision_id" not in indexer.chunks_table.c


@pytest.mark.asyncio
async def test_candidate_cannot_supply_forged_hash_or_approved_root():
    session = AsyncMock()
    for extra in ({"root_status": "accepted"}, {"content_sha256": "c" * 64},
                  {"permission_status": "granted"}):
        chunk = Chunk(id="paper_chunk_000", paper_id="paper", chunk_index=0,
                      section="Abstract", text="Synthetic", token_count=1,
                      evidence_candidate={"version": VERSION, "chunk_kind": "abstract", **extra})
        with pytest.raises(ValueError):
            await indexer._persist_chunk_evidence(session, "paper", [chunk])
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_candidate_paper_mismatch_is_rejected_before_lineage_read():
    session = AsyncMock()
    chunk = Chunk(id="other_chunk", paper_id="other", chunk_index=0,
                  section="Facts", text="Synthetic", token_count=1,
                  evidence_candidate={"version": VERSION, "chunk_kind": "abstract"})
    with pytest.raises(ValueError, match="identity"):
        await indexer._persist_chunk_evidence(session, "paper", [chunk])
    session.execute.assert_not_awaited()
