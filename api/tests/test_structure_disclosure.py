"""Synthetic SC11 raw-DTO disclosure regressions; no source text is licensed data."""
from __future__ import annotations

import json
from copy import deepcopy
from uuid import uuid4

import pytest

from models.db import Chunk, Material, Paper, get_session_factory
from models.search import MaterialDetail, PaperDetail, SearchMatch
from services import provider_resilience, retrieval
from services.material_property_projection import project_material_properties
from services.property_evidence import legacy_result_id
from services.source_visibility import project_source_occurrences
from services.structure_disclosure import redact_structure_payloads

PRIVATE = "SYNTHETIC_NONPUBLIC_STRUCTURE_EXCERPT_8e92"


def record(**changes):
    claims = [{"field": "space_group", "value": "Im-3m", "evidence_text": PRIVATE}]
    stored = {"version": "untrusted", "proposals": [{"evidence": {"text": PRIVATE}}]}
    return {"paper_id": "synthetic:disclosure", "formula": "Nb", "tc_kelvin": 8,
            "knowledge_origin": "Observed", "source_role": "primary", "pressure_gpa": 1,
            "structure_claims": claims, "structure_evidence": stored,
            "raw_extraction": {"formula": "Nb", "tc_kelvin": 8, "structure_claims": deepcopy(claims),
                               "alternate": [{"Structure-Evidence": deepcopy(stored)}]},
            "other_metadata": {"nested": [{"structure_claims": deepcopy(claims)}]}, **changes}


def material(row):
    return {"id": "mat:disclosure", "formula": "Nb", "formula_latex": None, "family": "elemental",
            "subfamily": None, "status": "active_research", "total_papers": 1, "needs_review": False,
            "disputed": False, "records": [row], "arxiv_year": None, "tc_max": 8,
            "tc_max_conditions": None, "tc_ambient": None, "crystal_structure": None}


@pytest.mark.parametrize("key", ["structure_claims", "structure_evidence", "Structure-Claims", "STRUCTURE_EVIDENCE", "structureClaims"])
def test_guard_removes_nested_stored_containers_without_changing_scientific_values(key):
    raw = {"tc_kelvin": 8, "raw_extraction": {"a": [{key: {"text": PRIVATE}, "pressure_gpa": 1}]}}
    before = deepcopy(raw)
    public = redact_structure_payloads(raw)
    assert PRIVATE not in json.dumps(public)
    assert public == {"tc_kelvin": 8, "raw_extraction": {"a": [{"pressure_gpa": 1}]}}
    assert raw == before


def test_guard_handles_cycles_without_mutation():
    raw = {"tc_kelvin": 8}
    raw["cycle"] = raw
    public = redact_structure_payloads(raw)
    assert public["cycle"] == {"redacted": "cyclic_metadata"}
    assert raw["cycle"] is raw


@pytest.mark.parametrize("status", ["published", "corrected", "retracted", None])
def test_source_status_never_grants_raw_structure_excerpt_permission(status):
    raw = record()
    before = deepcopy(raw)
    rows, summary = project_source_occurrences([raw], paper_status=status, linked_materials={})
    assert summary["returned_occurrences"] == 1
    assert PRIVATE not in json.dumps(rows)
    assert rows[0]["tc_kelvin"] == 8
    assert raw == before


def test_search_and_paper_dtos_do_not_bypass_source_projection():
    raw = record()
    before = deepcopy(raw)
    search = SearchMatch(paper_id="synthetic:disclosure", arxiv_id=None, title="Synthetic", authors=[],
                         year=2026, date_submitted=None, relevance_score=1, matched_chunk="Public fixture",
                         matched_section=None, materials=[raw], citation_count=0, material_family=None,
                         has_equation=False, has_table=False)
    paper = PaperDetail(id="synthetic:disclosure", arxiv_id=None, doi=None, title="Synthetic", authors=[],
                        date_submitted=None, material_family=None, status="published", citation_count=0,
                        chunk_count=1, abstract="Public fixture", categories=[], materials_extracted=[raw],
                        quality_flags=[], indexed_at=None)
    assert PRIVATE not in search.model_dump_json()
    assert PRIVATE not in paper.model_dump_json()
    assert raw == before


def test_material_raw_atomic_and_archive_paths_redact_without_changing_result_identity(monkeypatch):
    row = record()
    raw = material(row)
    before = deepcopy(raw)
    public_envelope = {"version": "synthetic-recomputed", "proposals": [{"evidence": {"text": None}}]}
    monkeypatch.setattr("services.material_property_projection.build_structure_evidence", lambda *_args, **_kwargs: deepcopy(public_envelope))
    public = MaterialDetail.model_validate(raw).model_dump()
    assert PRIVATE not in json.dumps(public, default=str)
    assert public["structure_evidence"] == public_envelope
    assert public["tc_max"] == 8
    assert public["property_evidence"]["properties"]["tc_max"]["selected"]["result_id"] == legacy_result_id(row, scope_id=raw["id"])
    assert public["raw_archive"]["records"][0]["raw"]["tc_kelvin"] == 8
    assert raw == before


def test_final_projection_guards_alternate_nested_payloads_but_keeps_recomputed_envelope(monkeypatch):
    raw = material(record())
    raw["alternate_archive"] = {"records": [{"structure_evidence": {"text": PRIVATE}, "tc_kelvin": 8}]}
    envelope = {"version": "synthetic-recomputed", "scientific_acceptance": False}
    monkeypatch.setattr("services.material_property_projection.build_structure_evidence", lambda *_args, **_kwargs: envelope)
    public = project_material_properties(raw, MaterialDetail.model_fields)
    assert PRIVATE not in json.dumps(public, default=str)
    assert public["alternate_archive"] == {"records": [{"tc_kelvin": 8}]}
    assert public["structure_evidence"] == envelope


@pytest.mark.asyncio
async def test_http_material_paper_and_search_raw_records_do_not_disclose_stored_structure_text(client, monkeypatch):
    suffix = uuid4().hex[:12]
    pid, mid, cid = "synthetic:sc11-disclosure-" + suffix, "mat:sc11-disclosure-" + suffix, "chunk:sc11-disclosure-" + suffix
    raw = record(paper_id=pid)
    before = deepcopy(raw)
    async with get_session_factory()() as session:
        paper = Paper(id=pid, source="arxiv", title="Synthetic structure disclosure", authors=[],
                      abstract="Public synthetic abstract", status="published", materials_extracted=[raw])
        row = Material(id=mid, formula="Nb", formula_normalized="sc11-disclosure-" + suffix,
                       family="elemental", total_papers=1, needs_review=False, tc_max=8, records=[raw])
        chunk = Chunk(id=cid, paper_id=pid, title=paper.title, text="Public synthetic chunk", materials_mentioned=[raw])
        session.add_all([paper, row, chunk])
        await session.commit()
        response = await client.get(f"/v1/materials/{mid}")
        assert response.status_code == 200, response.text
        # The separately rebuilt top-level contract has its own redaction tests.
        for field in ("records", "raw_archive", "property_evidence"):
            assert PRIVATE not in json.dumps(response.json()[field])
        response = await client.get(f"/v1/paper/{pid}")
        assert response.status_code == 200, response.text
        assert PRIVATE not in response.text
        provider_resilience.reset()
        monkeypatch.setattr("routers.search.vector_search.embed_query", lambda _: (_ for _ in ()).throw(RuntimeError("offline fixture")))
        async def lexical(*_args, **_kwargs):
            return [retrieval.LexicalHit(cid, 1.0)]
        monkeypatch.setattr("routers.search.retrieval.lexical_search", lexical)
        try:
            response = await client.post("/v1/search", json={"query": "synthetic structure disclosure"})
            assert response.status_code == 200, response.text
            assert response.json()["results"][0]["paper_id"] == pid
            assert PRIVATE not in response.text
        finally:
            provider_resilience.reset()
        await session.refresh(row)
        await session.refresh(paper)
        assert row.records == paper.materials_extracted == [before]
