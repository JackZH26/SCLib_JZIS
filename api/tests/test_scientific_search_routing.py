"""UI science filters share source-bound lookup, never legacy numeric fallback."""
from __future__ import annotations

import pytest

from tests import test_scientific_query_http as query_fixtures
from tests.index_generation_fixtures import publish_and_activate

scientific_runtime = query_fixtures.scientific_runtime


@pytest.mark.parametrize("filters", [
    {"tc_min": 30}, {"pressure_min": 1}, {"pressure_max": 1}, {"ambient_only": True},
    {"material_family": ["mgb2"]}, {"knowledge_origin": ["Observed"]},
    {"source_role": "primary"}, {"experimental_only": True},
])
async def test_ui_scientific_filters_require_active_generation_without_legacy_retrieval(
        client, monkeypatch, scientific_runtime, filters):
    query_fixtures.forbid_providers(monkeypatch)
    async def forbidden(*args, **kwargs):
        raise AssertionError("Scientific filters must not use legacy lexical numeric witnesses")
    monkeypatch.setattr("routers.search.retrieval.lexical_search", forbidden)
    response = await client.post("/v1/search", json={"query": "MgB2", "filters": filters})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["results"] == body["scientific_results"] == []
    assert body["scientific_lookup"]["status"] == "unavailable"
    assert body["scientific_lookup"]["reason_codes"] == ["active_generation_required"]
    assert body["scientific_query"]["intent"] == "general"


@pytest.mark.parametrize("filters", [{}, {"year_min": 2020}, {"year_max": 2025}, {"include_unknown_pressure": True}])
async def test_only_year_or_browsing_filters_keep_ordinary_lexical_search(client, monkeypatch, scientific_runtime, filters):
    called = []
    async def lexical(*args, **kwargs):
        called.append(kwargs)
        return []
    async def forbidden(*args, **kwargs):
        raise AssertionError("Year-only or ordinary keywords must not become numerical lookups")
    monkeypatch.setattr("routers.search.retrieval.lexical_search", lexical)
    monkeypatch.setattr("routers.search.lookup_scientific_results", forbidden)
    response = await client.post("/v1/search", json={"query": "ordinary keywords", "filters": filters})
    assert response.status_code == 200, response.text
    assert response.json()["scientific_lookup"]["status"] == "not_requested"
    assert len(called) == 1 and called[0]["year_min"] == filters.get("year_min")
    assert called[0]["year_max"] == filters.get("year_max")


async def test_formula_only_with_ui_tc_filter_preserves_original_extent_and_binding(
        client, db_session, monkeypatch, scientific_runtime):
    value = query_fixtures.record(tc=39, raw_extraction={"tc_kelvin": "39 ± 5 K"})
    _, _, staged = await query_fixtures.stage_records(monkeypatch, db_session, scientific_runtime, [value])
    active, _, _ = await publish_and_activate(db_session, staged)
    query_fixtures.forbid_providers(monkeypatch)
    for minimum, count in ((38, 0), (34, 1)):
        response = await client.post("/v1/search", json={"query": "MgB2", "filters": {"tc_min": minimum}})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["results"] == []  # consumers migrate to scientific_results
        assert body["scientific_lookup"]["status"] == "completed"
        assert len(body["scientific_results"]) == count
        if count:
            row = body["scientific_results"][0]
            assert row["result"]["tc"]["uncertainty"] == 5
            assert row["binding"]["generation_id"] == active["generation_id"]
            assert row["binding"]["manifest_sha256"] == active["manifest_sha256"]
            assert row["binding"]["association_scope"] == "derived_extraction_not_original_support"
