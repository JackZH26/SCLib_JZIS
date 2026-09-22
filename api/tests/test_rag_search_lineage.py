"""Synthetic HTTP regressions for lineage-aware search; disposable DB only."""
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from models.db import Chunk, Paper, get_session_factory
from services import rag_evidence, retrieval


async def _search_fixture(monkeypatch, state):
    token = uuid4().hex
    paper_id, chunk_id = "synthetic:search-lineage:" + token, "synthetic:lineage-chunk:" + token
    record = {"formula": "Nb", "tc_kelvin": "9.2 K", "evidence_role": "primary_experimental"}
    async with get_session_factory()() as db:
        paper = Paper(id=paper_id, title="Synthetic lineage fixture", source="arxiv", authors=[], abstract="",
                      status="published", materials_extracted=[record])
        chunk = Chunk(id=chunk_id, paper=paper, text="SOURCE_EXCERPT_SENTINEL", section="Facts", materials_mentioned=[record])
        db.add_all([paper, chunk])
        await db.flush()
        if state != "legacy":
            await rag_evidence.register_chunk_evidence(db, chunk_id=chunk_id, dry_run=False, candidate={
                "version": "rag-evidence/1.0.0", "chunk_kind": "derived_fact", "parent_record": record,
                "extraction_version": "synthetic-extractor/1", "rendering_version": rag_evidence.CURRENT_FACT_RENDERER_VERSION,
                "permission_status": "restricted" if "restricted" in state else "unresolved"})
        if state in {"stale", "restricted_replaced"}:
            await db.execute(update(Chunk).where(Chunk.id == chunk_id).values(text="CHANGED_EXCERPT_SENTINEL"))
        await db.commit()

    async def no_vectors(*args, **kwargs):
        return []

    async def lexical(*args, **kwargs):
        return [retrieval.LexicalHit(chunk_id, 2.0)]

    monkeypatch.setattr("routers.search.provider_resilience.run_blocking", no_vectors)
    monkeypatch.setattr("routers.search.retrieval.lexical_search", lexical)
    return paper_id, chunk_id


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["legacy", "current", "restricted", "stale", "restricted_replaced"])
async def test_search_publishes_closed_descriptor_and_withholds_held_text(client, monkeypatch, state):
    paper_id, _ = await _search_fixture(monkeypatch, state)
    response = await client.post("/v1/search", json={"query": "synthetic lineage"})
    assert response.status_code == 200, response.text
    result, = response.json()["results"]
    assert result["paper_id"] == paper_id
    descriptor = result["evidence_provenance"]
    assert descriptor["support_eligible"] is descriptor["independent_evidence"] is descriptor["scientific_acceptance"] is False
    assert descriptor["root_status"] == "unresolved"
    assert "projection_json" not in str(descriptor)
    if state in {"restricted", "stale", "restricted_replaced"}:
        assert result["matched_chunk"] == ""
        assert "EXCERPT_SENTINEL" not in response.text
    else:
        assert result["matched_chunk"] == "SOURCE_EXCERPT_SENTINEL"
    if state == "legacy":
        assert descriptor["chunk_kind"] == "legacy_unknown" and descriptor["currentness"] == "unresolved"
    else:
        assert descriptor["chunk_kind"] == "derived_fact" and descriptor["parent_result_revision_id"]
    if state == "restricted_replaced":
        assert descriptor["currentness"] == "stale" and descriptor["permission_status"] == "restricted"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["sql", "timeout", "missing", "malformed"])
async def test_search_fails_closed_if_lineage_cannot_be_resolved(client, monkeypatch, failure):
    _, chunk_id = await _search_fixture(monkeypatch, "legacy")

    async def unavailable(*args, **kwargs):
        if failure == "sql":
            raise SQLAlchemyError("PRIVATE_SQL_DETAIL")
        if failure == "timeout":
            raise TimeoutError("PRIVATE_TIMEOUT_DETAIL")
        return {} if failure == "missing" else {chunk_id: {"scientific_acceptance": True}}

    monkeypatch.setattr(rag_evidence, "resolve_chunk_evidence", unavailable)
    response = await client.post("/v1/search", json={"query": "synthetic lineage"})
    assert response.status_code == 503, response.text
    assert "Evidence provenance is unavailable" in response.text
    assert "EXCERPT_SENTINEL" not in response.text and "PRIVATE_" not in response.text
