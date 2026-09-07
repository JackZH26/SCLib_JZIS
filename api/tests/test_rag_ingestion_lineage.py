"""Actual ingestion writer/0060 transaction integration on guarded native PG.

API conftest verifies the private disposable capability before app/DB imports.
The ingestion image's producer is imported explicitly; no live cloud IO runs.
"""
from __future__ import annotations

import hashlib
import sys
import uuid
from copy import deepcopy
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion"))

from ingestion.index import indexer  # noqa: E402
from ingestion.models import ApsArticleMeta, Chunk, PaperMetadata, ParsedPaper  # noqa: E402
from ingestion.rag_evidence_contract import VERSION, canonical  # noqa: E402

from models.db import get_session_factory  # noqa: E402
from services.rag_evidence import (  # noqa: E402
    CURRENT_FACT_RENDERER_VERSION,
    register_chunk_evidence,
    resolve_chunk_evidence,
)


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


@pytest.fixture
def writer(monkeypatch):
    monkeypatch.setattr(indexer, "_session_factory", get_session_factory)

    def forbidden_vector_io():
        raise AssertionError("SQL lineage writer must not call vector service")

    monkeypatch.setattr(indexer, "_index", forbidden_vector_io)
    return indexer


def fixture_values():
    meta = ApsArticleMeta(doi="10.1103/SyntheticEvidence." + uuid.uuid4().hex,
                          title="Synthetic lineage", authors=[], abstract="Authorized synthetic abstract.")
    record = {"formula": "MgB2", "tc_kelvin": "<2 K", "minimum_temperature_k": 2,
              "result_status": "not_detected", "knowledge_origin": "Observed",
              "source_role": "primary", "measurement_method": "resistivity",
              "extractor_version": "synthetic-extractor/1", "confidence": 0.95,
              "evidence_text": "LICENSED_BODY_SENTINEL", "raw_extraction": {
                  "source_quote": "PRIVATE_SOURCE_QUOTE_SENTINEL"}}
    candidate = {"version": VERSION, "chunk_kind": "derived_fact", "parent_record": record,
                 "extraction_version": record["extractor_version"],
                 "rendering_version": CURRENT_FACT_RENDERER_VERSION, "source_capture_id": None,
                 "source_locator": {}, "unresolved_reason": "missing_original_source",
                 "permission_status": "unresolved"}
    chunk = Chunk(id=meta.paper_id + "_fact_000", paper_id=meta.paper_id, chunk_index=0,
                  section="Facts", text="Synthetic controlled non-detection at 2 K.", token_count=12,
                  materials_mentioned=[record], evidence_candidate=candidate)
    return meta, record, chunk


async def snapshot(db, paper_id):
    result = {}
    for table in ("papers", "chunks", "rag_extraction_revisions", "rag_evidence_revisions"):
        field = "id" if table == "papers" else "paper_id"
        result[table] = (await db.execute(text(
            f"SELECT to_jsonb(t) FROM {table} t WHERE {field}=:paper ORDER BY id"
        ), {"paper": paper_id})).scalars().all()
    result["pointers"] = (await db.execute(text("""SELECT to_jsonb(link) FROM chunk_evidence_current link
        JOIN chunks c ON c.id=link.chunk_id WHERE c.paper_id=:paper ORDER BY link.chunk_id"""),
        {"paper": paper_id})).scalars().all()
    return result


async def test_aps_actual_writer_commits_exact_text_free_parent_and_replays_with_api_service(writer, db_session):
    meta, record, chunk = fixture_values()
    before = deepcopy(record)
    await writer.upsert_aps_paper_with_chunks(meta, [chunk], [record])
    saved = await snapshot(db_session, meta.paper_id)
    assert [len(saved[table]) for table in ("papers", "chunks", "rag_extraction_revisions", "rag_evidence_revisions", "pointers")] == [1] * 5
    parent, evidence = saved["rag_extraction_revisions"][0], saved["rag_evidence_revisions"][0]
    assert parent["input_record_sha256"] == hashlib.sha256(canonical(record)).hexdigest()
    assert parent["scientific_acceptance"] is False
    assert evidence["parent_extraction_revision_id"] == parent["id"]
    assert evidence["content_sha256"] == hashlib.sha256(chunk.text.encode()).hexdigest()
    assert "LICENSED_BODY_SENTINEL" not in str(parent)
    assert "PRIVATE_SOURCE_QUOTE_SENTINEL" not in str(parent)
    assert record == before
    assert saved["papers"][0]["materials_extracted"] == [before]
    descriptor = (await resolve_chunk_evidence(db_session, [saved["chunks"][0]]))[chunk.id]
    assert descriptor["currentness"] == "current"
    assert descriptor["root_status"] == descriptor["permission_status"] == "unresolved"
    assert descriptor["support_eligible"] is descriptor["independent_evidence"] is descriptor["scientific_acceptance"] is False
    replay = await register_chunk_evidence(db_session, chunk_id=chunk.id,
                                           candidate=chunk.evidence_candidate, dry_run=False)
    assert replay["evidence_revision_id"] == evidence["id"]
    await db_session.commit()
    assert await snapshot(db_session, meta.paper_id) == saved


async def test_replacement_appends_new_renderer_revision_preserving_parent_and_history(writer, db_session):
    meta, record, chunk = fixture_values()
    await writer.upsert_aps_paper_with_chunks(meta, [chunk], [record])
    first = await snapshot(db_session, meta.paper_id)
    chunk.text = "Revised controlled rendering of the same extracted result."
    chunk.evidence_candidate = {**chunk.evidence_candidate, "rendering_version": "synthetic-renderer/3"}
    await db_session.rollback()  # Release observer transaction before writer's source fence.
    await writer.upsert_aps_paper_with_chunks(meta, [chunk], [record])
    second = await snapshot(db_session, meta.paper_id)
    assert len(second["rag_extraction_revisions"]) == 1
    assert len(second["rag_evidence_revisions"]) == 2
    assert first["rag_evidence_revisions"][0] in second["rag_evidence_revisions"]
    assert second["pointers"][0]["evidence_revision_id"] != first["pointers"][0]["evidence_revision_id"]
    assert second["chunks"][0]["text"] == chunk.text


async def test_lineage_failure_rolls_back_paper_chunk_parent_and_pointer_as_one_effect_set(writer, db_session):
    meta, record, chunk = fixture_values()
    await writer.upsert_aps_paper_with_chunks(meta, [chunk], [record])
    before = await snapshot(db_session, meta.paper_id)
    await db_session.rollback()
    changed = deepcopy(record)
    changed["minimum_temperature_k"] = 1
    chunk.materials_mentioned = [changed]
    chunk.text = "Changed controlled rendering."
    chunk.evidence_candidate = {**chunk.evidence_candidate, "parent_record": changed,
                                "source_capture_id": str(uuid.uuid4())}
    meta.title = "Changed paper must also roll back"
    # Parent insert succeeds first; evidence INSERT then rejects nonexistent
    # capture provenance. Even append-only history must roll back with chunks.
    with pytest.raises(SQLAlchemyError):
        await writer.upsert_aps_paper_with_chunks(meta, [chunk], [changed])
    assert await snapshot(db_session, meta.paper_id) == before


async def test_derived_parent_must_match_both_actual_paper_and_chunk_records(writer, db_session):
    meta, record, chunk = fixture_values()
    with pytest.raises(ValueError, match="actual paper and chunk"):
        await writer.upsert_aps_paper_with_chunks(meta, [chunk], [])
    assert not any((await snapshot(db_session, meta.paper_id)).values())


@pytest.mark.parametrize("permission", ["unresolved", "restricted"])
async def test_legacy_replacement_removes_only_current_pointer_without_fabricating_new_history(writer, db_session, permission):
    meta, record, chunk = fixture_values()
    chunk.evidence_candidate["permission_status"] = permission
    await writer.upsert_aps_paper_with_chunks(meta, [chunk], [record])
    before = await snapshot(db_session, meta.paper_id)
    await db_session.rollback()
    chunk.evidence_candidate = None
    await writer.upsert_aps_paper_with_chunks(meta, [chunk], [record])
    after = await snapshot(db_session, meta.paper_id)
    assert after["pointers"] == []
    assert after["rag_extraction_revisions"] == before["rag_extraction_revisions"]
    assert after["rag_evidence_revisions"] == before["rag_evidence_revisions"]
    descriptor = (await resolve_chunk_evidence(db_session, [after["chunks"][0]]))[chunk.id]
    assert descriptor["chunk_kind"] == "derived_fact"
    assert descriptor["currentness"] == "stale"
    assert descriptor["permission_status"] == permission
    assert "current_pointer_invalidated" in descriptor["warning_codes"]
    assert descriptor["support_eligible"] is False


async def test_reingestion_insert_defaults_never_clear_existing_source_holds(writer, db_session):
    meta, record, chunk = fixture_values()
    await writer.upsert_aps_paper_with_chunks(meta, [chunk], [record])
    await db_session.execute(text("""UPDATE papers SET status='retracted', citation_count=17,
        quality_flags='["synthetic_hold"]'::jsonb WHERE id=:paper"""), {"paper": meta.paper_id})
    await db_session.commit()
    await writer.upsert_aps_paper_with_chunks(meta, [chunk], [record])
    paper = (await snapshot(db_session, meta.paper_id))["papers"][0]
    assert paper["status"] == "retracted"
    assert paper["citation_count"] == 17
    assert paper["quality_flags"] == ["synthetic_hold"]


async def test_arxiv_writer_uses_same_atomic_binding_with_explicit_original_kind(writer, db_session):
    meta = PaperMetadata(arxiv_id="2609.65001", title="Synthetic original",
                         authors=[], abstract="Synthetic original abstract.", date_submitted=None,
                         categories=[], primary_category=None)
    parsed = ParsedPaper(meta=meta, sections=[])
    chunk = Chunk(id=meta.paper_id + "_chunk_000", paper_id=meta.paper_id,
                  chunk_index=0, section="Facts", text="Original source passage, not derived.", token_count=8,
                  evidence_candidate={"version": VERSION, "chunk_kind": "original_passage",
                                      "unresolved_reason": "original_binding_unreviewed"})
    await writer.upsert_paper_with_chunks(parsed, [chunk], [])
    saved = await snapshot(db_session, meta.paper_id)
    assert saved["rag_extraction_revisions"] == []
    assert saved["rag_evidence_revisions"][0]["chunk_kind"] == "original_passage"
    assert saved["rag_evidence_revisions"][0]["source_capture_id"] is None
    assert len(saved["pointers"]) == 1
