"""Literal formula lookup over real SQL scopes; disposable native runner only.

These catalogue labels and records are synthetic regression fixtures. Formula
text matching never confers chemical equivalence or scientific acceptance.
"""
from __future__ import annotations

import inspect
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from models.db import Material, Paper, get_session_factory


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        try:
            yield session
        finally:
            await session.rollback()
            identifiers = session.info.get("formula_lookup_materials", [])
            if identifiers:
                await session.execute(delete(Material).where(Material.id.in_(identifiers)))
                await session.commit()


async def _seed(session, family, label, formula, *, records=None, pending=False):
    paper = Paper(id=f"arxiv:{family}:{label}", source="arxiv", title="Synthetic formula lookup source",
                  authors=[], abstract="Synthetic test fixture.", status="published")
    session.add(paper)
    raw = records if records is not None else [{"paper_id": paper.id, "formula": "Nb",
        "family": family, "tc_kelvin": 20, "year": 2025, "pressure_gpa": 2,
        "knowledge_origin": "Observed", "measurement": "resistivity"}]
    material = Material(id=f"mat:{family}:{label}", formula=formula,
        formula_normalized=f"{family}:{label}", family=family, records=raw,
        tc_max=20, total_papers=1, needs_review=pending, status="active_research")
    session.add(material)
    session.info.setdefault("formula_lookup_materials", []).append(material.id)
    await session.commit()
    return material, paper


@pytest.mark.asyncio
async def test_formula_text_nfkc_case_contains_page_count_blank_and_no_match(client, db_session):
    family = "formula_lookup_"+uuid4().hex[:12]
    expected = []
    for label, formula in (("a", "CrB2"), ("b", "CrB₂"), ("c", "CrB20"), ("d", "NbN")):
        material, _ = await _seed(db_session, family, label, formula)
        if label != "d":
            expected.append(material.id)
    pages = []
    for offset in range(4):
        response = await client.get("/v1/materials", params={"family": family, "q": "cRb₂", "limit": 1, "offset": offset})
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 3
        pages.extend(row["id"] for row in response.json()["results"])
    assert pages == sorted(expected)
    for q in ("", "   ", "\u00a0\u3000"):
        assert (await client.get("/v1/materials", params={"family": family, "q": q})).json()["total"] == 4
    missing = await client.get("/v1/materials", params={"family": family, "q": "B2Cr"})
    assert missing.status_code == 200
    assert missing.json()["total"] == 0 and missing.json()["results"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("literal", ["%", "_", "\\"])
async def test_literal_formula_wildcards_are_not_search_operators(client, db_session, literal):
    family = "formula_literal_"+uuid4().hex[:12]
    match, _ = await _seed(db_session, family, "literal", "Cr"+literal+"B2")
    await _seed(db_session, family, "other", "CrAnythingB2")
    response = await client.get("/v1/materials", params={"family": family, "q": literal})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert [row["id"] for row in response.json()["results"]] == [match.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["Nb\x00", "Nb\x1f", "Nb\x7f", "Nb\x85", "Nb\x9f", "A"*201, "ﬃ"*67])
async def test_invalid_formula_query_returns_422(client, query):
    response = await client.get("/v1/materials", params={"q": query})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_formula_search_cannot_combine_tc_pressure_and_origin_across_results_or_held_sources(client, db_session):
    family = "formula_atomic_"+uuid4().hex[:12]
    row, source = await _seed(db_session, family, "scoped", "NbN")
    held = Paper(id=f"arxiv:{family}:held", source="arxiv", title="Synthetic held source",
                 authors=[], abstract="Synthetic fixture.", status="retracted")
    db_session.add(held)
    row.records = [
        {"paper_id": source.id, "formula": "NbN", "family": family, "year": 2025,
         "tc_kelvin": 30, "pressure_gpa": 2, "knowledge_origin": "Observed", "measurement": "resistivity"},
        {"paper_id": source.id, "formula": "NbN", "family": family, "year": 2025,
         "tc_kelvin": 100, "pressure_gpa": 10, "knowledge_origin": "Observed", "measurement": "resistivity"},
        {"paper_id": source.id, "formula": "NbN", "family": family, "year": 2025,
         "tc_kelvin": 200, "pressure_gpa": 2, "knowledge_origin": "Computed", "method": "DFT"},
        {"paper_id": held.id, "formula": "NbN", "family": family, "year": 2025,
         "tc_kelvin": 120, "pressure_gpa": 2, "knowledge_origin": "Observed", "measurement": "resistivity"},
    ]
    await db_session.commit()
    await _seed(db_session, family, "pending", "NbN", pending=True)
    excluded, excluded_source = await _seed(db_session, family, "allheld", "NbN")
    excluded_source.status = "retracted"
    await db_session.commit()
    params = {"family": family, "q": "NbN", "pressure_max": 3, "knowledge_origin": "Observed"}
    impossible = await client.get("/v1/materials", params={**params, "tc_min": 100})
    assert impossible.status_code == 200, impossible.text
    assert impossible.json()["total"] == 0
    match = await client.get("/v1/materials", params={**params, "tc_min": 29})
    assert match.status_code == 200, match.text
    assert match.json()["total"] == 1
    result, = match.json()["results"]
    assert result["id"] == row.id and result["id"] != excluded.id
    assert [item["record_index"] for item in result["matching_results"]] == [0]
    assert result["matching_results"][0]["tc_evidence"]["value"] == 30
    assert result["visibility"]["scientific_acceptance"] is False


@pytest.mark.asyncio
async def test_formula_query_isolates_page_and_ranking_caches_and_rechecks_sources(client, db_session, monkeypatch):
    import routers.materials as routes
    monkeypatch.setattr(routes, "_material_pages", routes._MaterialPageCache())
    monkeypatch.setattr(routes, "_material_rankings", routes._MaterialPageCache())
    family = "formula_cache_"+uuid4().hex[:12]
    sources = []
    for label, formula in (("a", "Nb"), ("b", "NbN"), ("c", "CrB2")):
        _, source = await _seed(db_session, family, label, formula)
        sources.append(source)
    for extra, total in (({"q": "Nb"}, 2), ({"q": "CrB2"}, 1), ({}, 3), ({"q": "AbsentFormula"}, 0)):
        params = {"family": family, **extra}
        cold = await client.get("/v1/materials", params=params)
        warm = await client.get("/v1/materials", params=params)
        assert cold.status_code == warm.status_code == 200
        assert cold.json() == warm.json() and warm.json()["total"] == total
        assert cold.headers["X-Materials-Cache"] == "MISS"
        assert warm.headers["X-Materials-Cache"] == "HIT"
    assert len(routes._material_pages.entries) == 4
    for source in sources[:2]:
        source.status = "retracted"
    await db_session.commit()
    held = await client.get("/v1/materials", params={"family": family, "q": "Nb"})
    assert held.status_code == 200, held.text
    assert held.json()["total"] == 0
    assert held.headers["X-Materials-Cache"] == "MISS"


def test_internal_list_default_q_is_a_scalar_none():
    from routers.materials import list_materials
    assert inspect.signature(list_materials).parameters["q"].default is None


@pytest.mark.asyncio
async def test_repeated_formula_query_is_rejected_before_warm_cache_or_catalogue_read(client, db_session, monkeypatch):
    import routers.materials as routes
    monkeypatch.setattr(routes, "_material_pages", routes._MaterialPageCache())
    monkeypatch.setattr(routes, "_material_rankings", routes._MaterialPageCache())
    family = "formula_duplicate_"+uuid4().hex[:12]
    await _seed(db_session, family, "nb", "Nb")
    await _seed(db_session, family, "nbn", "NbN")
    for q in ("Nb", "NbN", ""):
        params = {"family": family, "q": q}
        cold = await client.get("/v1/materials", params=params)
        warm = await client.get("/v1/materials", params=params)
        assert cold.status_code == warm.status_code == 200
        assert cold.headers["X-Materials-Cache"] == "MISS"
        assert warm.headers["X-Materials-Cache"] == "HIT"

    async def no_catalogue_read(_db):
        raise AssertionError("Repeated q must be rejected before catalogue/cache access")
    monkeypatch.setattr(routes, "_material_page_revision", no_catalogue_read)
    for first, second in (("Nb", "NbN"), ("NbN", "Nb"), ("NbN", "NbN"), ("", "NbN"), ("NbN", ""), ("", ""), ("NbN", "A"*201), ("NbN", "Nb\x00")):
        response = await client.get("/v1/materials", params=[("family", family), ("q", first), ("q", second)])
        assert response.status_code == 422
        assert response.json()["detail"] == "q must be supplied at most once"
        assert response.json()["error_code"] == "validation_error"
        assert isinstance(response.json()["request_id"], str)
        assert "X-Materials-Cache" not in response.headers
    for q, detail in (("A"*201, "q must contain at most 200 characters before and after NFKC normalization"),
                      ("ﬃ"*67, "q must contain at most 200 characters before and after NFKC normalization"),
                      ("Nb\x00", "q must not contain C0 or C1 control characters")):
        response = await client.get("/v1/materials", params={"family": family, "q": q})
        assert response.status_code == 422
        assert response.json()["detail"] == detail
        assert response.json()["error_code"] == "validation_error"
        assert isinstance(response.json()["request_id"], str)
        assert "X-Materials-Cache" not in response.headers


def test_formula_query_openapi_retains_the_declared_unicode_length_bound():
    from main import app
    parameters = app.openapi()["paths"]["/v1/materials"]["get"]["parameters"]
    query, = [item for item in parameters if item["name"] == "q"]
    assert query["in"] == "query" and query["required"] is False
    assert query["schema"]["maxLength"] == 200
