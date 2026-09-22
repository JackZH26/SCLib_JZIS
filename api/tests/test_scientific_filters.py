"""SC04: same-result filtering, explicit pressure and read-surface parity."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from models.db import Chunk, Material, Paper, get_session_factory
from models.search import MaterialSummary, SearchFilters
from services import provider_resilience, retrieval
from services.pressure_semantics import PRESSURE_POLICY_VERSION, classify_pressure
from services.scientific_filters import ResultFilters, matching_result_references, tc_lower_bound
from services.timeline_points import extract_timeline_points
from services.timeline_projection import PROJECTION_SCHEMA_VERSION, fetch_projected_timeline_points


def matches(records, **kwargs):
    return matching_result_references(records, ResultFilters(**kwargs), scope_id="synthetic")


def test_pressure_contract_is_identical_across_independent_images():
    root = Path(__file__).resolve().parents[2]
    assert (root / "api/services/pressure_semantics.py").read_bytes() == (
        root / "ingestion/ingestion/pressure_semantics.py"
    ).read_bytes()
    assert (root / "api/services/scientific_values.py").read_bytes() == (
        root / "ingestion/ingestion/extract/scientific_values.py"
    ).read_bytes()


@pytest.mark.parametrize("pressure", [None, 0, True, "unclear", float("inf"), float("nan")])
def test_unknown_pressure_never_satisfies_default_numeric_or_ambient_filter(pressure):
    record = {"formula": "X", "tc_kelvin": 230, "pressure_gpa": pressure}
    assert not matches([record], pressure_max=1)
    assert not matches([record], ambient_only=True)
    assert matches([record], tc_min=200)  # no pressure predicate
    # Missing/legacy zero may be included as Unknown. Malformed/nonfinite
    # pressure remains pending under SC03, not a bypass via include_unknown.
    assert bool(matches([record], pressure_max=1, include_unknown_pressure=True)) == (pressure is None or pressure == 0)


def test_negative_pressure_is_not_ambient_or_an_opt_in_unknown_candidate():
    record = {"pressure_gpa": -1, "tc_kelvin": 10}
    assert not matches([record], pressure_max=1, include_unknown_pressure=True)
    assert matches([record], tc_min=5)


def test_independent_results_cannot_jointly_satisfy_compound_filters():
    records = [
        {"formula": "A", "family": "hydride", "tc_kelvin": 230, "pressure_gpa": 200, "knowledge_origin": "Computed"},
        {"formula": "B", "family": "cuprate", "tc_kelvin": 5, "pressure_gpa": 0, "pressure_state": "explicit_ambient", "knowledge_origin": "Observed"},
    ]
    assert not matches(records, tc_min=200, pressure_max=1)
    assert not matches(records, families=("cuprate",), tc_min=200)
    assert not matches(records, tc_min=200, experimental_only=True)
    result = matches(records, families=("hydride",), tc_min=200, pressure_max=201, origins=("Computed",))
    assert len(result) == 1 and result[0]["record_index"] == 0
    assert result[0]["formula"] == "A"


def test_source_role_and_tier_also_match_the_same_result():
    records = [
        {"tc_kelvin": 230, "source_role": "cited", "credibility_tier": "T3"},
        {"tc_kelvin": 5, "source_role": "primary", "credibility_tier": "T1"},
    ]
    assert not matches(records, tc_min=200, source_role="primary")
    assert not matches(records, tc_min=200, min_tier="T1")


def test_matching_ids_survive_reordering_and_derived_envelope_roundtrips():
    record = {"formula": "A", "tc_kelvin": 30, "pressure_gpa": 1}
    first = matches([record], tc_min=20)[0]
    reordered = matches([{}, {**record, "pressure_semantics": {"ignored": True}, "result_classification": {}}], tc_min=20)[0]
    assert first["result_id"] == reordered["result_id"]
    assert first["record_index"] != reordered["record_index"]
    assert matches([{**record, "tc_kelvin": 40}], tc_min=20)[0]["result_id"] != first["result_id"]


@pytest.mark.parametrize("raw,limit,expected", [("20 kbar", 2, True), ("1–3 GPa", 2, False), ("1–3 GPa", 3, True), ("2 ± 0.5 GPa", 2, False), ("~2 GPa", 3, False)])
def test_pressure_ranges_units_and_uncertainty_are_not_midpoint_filters(raw, limit, expected):
    assert bool(matches([{"pressure_gpa": raw}], pressure_max=limit)) is expected


@pytest.mark.parametrize("value", [True, 10**400, float("nan"), float("inf"), "300 unicorns"])
def test_tc_filter_rejects_nonfinite_boolean_and_unparsed_text(value):
    assert tc_lower_bound({"tc_kelvin": value}) is None


def test_typed_tc_bounds_do_not_become_exact_or_censored_upper_bound_matches():
    base = {"status": "parsed", "unit": "K", "errors": [], "approximate": False}
    assert tc_lower_bound({"scientific_values": {"tc_kelvin": {**base, "raw_value": "80–95 K", "relation": "interval", "lower": 80, "upper": 95}}}) == 80
    assert tc_lower_bound({"tc_kelvin": 95, "scientific_values": {"tc_kelvin": {**base, "raw_value": "<95 K", "relation": "lt", "upper": 95}}}) is None
    assert not matches([{"tc_kelvin": 230, "result_status": "not_detected"}], tc_min=200)


def test_tc_raw_parser_prevents_stale_cached_magnitudes_and_invalid_uncertainty():
    assert tc_lower_bound({"scientific_values": {"tc_kelvin": {
        "raw_value": "39 K", "value": 300, "status": "parsed", "relation": "exact", "uncertainty": -100,
    }}}) == 39
    assert tc_lower_bound({"scientific_values": {"tc_kelvin": {"raw_value": "39 ± -100 K"}}}) is None
    assert tc_lower_bound({"scientific_values": {"tc_kelvin": {"raw_value": "300–100 K"}}}) is None
    assert tc_lower_bound({"tc_kelvin": "20 mK"}) == pytest.approx(0.02)


@pytest.mark.parametrize("signal", [{"result_status": "not_detected"}, {"outcome_state": "not_detected"},
                                     {"no_transition": True}, {"superconductivity_observed": False},
                                     {"result_status": "non_transition_observed"}, {"result_status": "refuted"},
                                     {"result_status": "observed", "outcome": "negative"}])
def test_contradictory_negative_aliases_cannot_support_positive_or_ambient_summary(signal):
    from services.scientific_filters import supported_ambient_summary
    record = {"tc_kelvin": 39, "pressure_gpa": 0, "pressure_state": "explicit_ambient",
              "knowledge_origin": "Observed", **signal}
    assert not matches([record], tc_min=30)
    assert supported_ambient_summary([record], 39) == (None, None)


def test_legacy_ambient_summary_is_not_authoritative_pressure_evidence():
    base = dict(id="mat:fixture", formula="X", formula_latex=None, family=None,
                subfamily=None, tc_max=30, tc_max_conditions=None, tc_ambient=30,
                arxiv_year=2025, total_papers=1, status="active", ambient_sc=True)
    legacy = MaterialSummary.model_validate({**base, "records": [{"tc_kelvin": 30, "pressure_gpa": 0, "knowledge_origin": "Observed"}]})
    assert legacy.tc_ambient is None and legacy.ambient_sc is None
    supported = MaterialSummary.model_validate({**base, "records": [{"tc_kelvin": 30, "pressure_gpa": 0, "pressure_state": "explicit_ambient", "knowledge_origin": "Observed"}]})
    assert supported.tc_ambient == 30 and supported.ambient_sc is True
    missing = MaterialSummary.model_validate({**base, "records": None})
    assert missing.tc_ambient is None and missing.ambient_sc is None


def test_timeline_preserves_explicit_unknown_and_ambiguous_pressure_separately():
    base = {"tc_kelvin": 5, "year": 2025, "knowledge_origin": "Observed"}
    records = [base, {**base, "pressure_gpa": 0}, {**base, "pressure_gpa": 0, "pressure_state": "explicit_ambient"}]
    points = extract_timeline_points("mat:x", records, {})
    assert len(points) == 3
    assert {p.pressure_semantics["pressure_state"] for p in points} == {"not_reported", "ambiguous", "explicit_ambient"}
    assert len({p.id for p in points}) == 3
    assert all(p.pressure_gpa is None for p in points if p.pressure_semantics["pressure_state"] != "explicit_ambient")


@pytest.mark.asyncio
async def test_pressure_policy_version_change_invalidates_projection_before_read():
    from services.result_semantics import CLASSIFIER_VERSION

    class Session:
        async def get(self, *_, populate_existing=False):
            assert populate_existing is True
            return SimpleNamespace(schema_version=PROJECTION_SCHEMA_VERSION, classifier_version=CLASSIFIER_VERSION,
                                   pressure_policy_version="old", source_year=2026)

        async def execute(self, *_):
            raise AssertionError("Do not read a stale pressure projection")

    result = await fetch_projected_timeline_points(Session(), family=None, include_pending=False,
                                                 experimental_only=False, only_aps=False, current_year=2026)
    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize("filters", [
    {"tc_min": 200, "pressure_max": 1}, {"tc_min": 200, "material_family": ["cuprate"]},
    {"tc_min": 200, "pressure_max": 201},
])
async def test_search_requires_generation_for_scientific_filters_not_legacy_witnesses(client, monkeypatch, filters):
    provider_resilience.reset()
    suffix = uuid4().hex[:8]
    paper = Paper(id=f"arxiv:same-result-{suffix}", source="arxiv", title="Synthetic same result fixture",
                  authors=[], abstract="Synthetic", status="published", material_family="cuprate",
                  materials_extracted=[
                      {"formula": "A", "family": "hydride", "tc_kelvin": 230, "pressure_gpa": 200},
                      {"formula": "B", "family": "cuprate", "tc_kelvin": 5, "pressure_gpa": 0, "pressure_state": "explicit_ambient"},
                  ])
    chunk = Chunk(id=f"{paper.id}:chunk", paper_id=paper.id, title=paper.title, text="Synthetic superconductivity", material_family="cuprate")
    async with get_session_factory()() as session:
        session.add_all([paper, chunk])
        await session.commit()

    async def no_vectors(*_, **__):
        return []

    async def lexical(*_, **__):
        return [retrieval.LexicalHit(chunk.id, 2)]

    monkeypatch.setattr("routers.search.provider_resilience.run_blocking", no_vectors)
    monkeypatch.setattr("routers.search.retrieval.lexical_search", lexical)
    response = await client.post("/v1/search", json={"query": "Synthetic superconductivity", "filters": filters})
    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["scientific_results"] == []
    assert response.json()["scientific_lookup"]["status"] == "unavailable"
    assert response.json()["scientific_lookup"]["reason_codes"] == ["active_generation_required"]
    # Unfiltered bibliography still exercises legacy material disclosure;
    # these rows are not a version-pinned quantitative filter witness.
    response = await client.post("/v1/search", json={"query": "Synthetic superconductivity"})
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["matching_results"] == []
    assert result["materials"][1]["pressure_semantics"]["pressure_state"] == "explicit_ambient"
    provider_resilience.reset()


@pytest.mark.asyncio
async def test_materials_stream_matches_before_count_and_page_and_ignores_stale_summary(client):
    family = f"test_{uuid4().hex[:8]}"
    records = [
        [{"tc_kelvin": 230, "pressure_gpa": 200}, {"tc_kelvin": 5, "pressure_gpa": 0, "pressure_state": "explicit_ambient"}],
        [{"tc_kelvin": 220, "pressure_gpa": 0.5}],
        [{"tc_kelvin": 250, "pressure_gpa": 0.8}],
    ]
    async with get_session_factory()() as session:
        for i, rows in enumerate(records):
            session.add(Material(id=f"mat:{family}:{i}", formula=f"X{i}", formula_normalized=f"{family}{i}",
                                 family=family, tc_max=999, total_papers=1, needs_review=False, records=rows))
        await session.commit()
    response = await client.get("/v1/materials", params={"family": family, "tc_min": 200, "pressure_max": 1, "limit": 1, "offset": 1})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2
    assert [r["id"] for r in data["results"]] == [f"mat:{family}:2"]
    assert data["results"][0]["matching_results"][0]["tc_lower_bound_k"] == 250


@pytest.mark.asyncio
async def test_material_negative_and_invalid_bound_requests_fail_explicitly(client):
    for query in ("ambient_sc=false", "pressure_min=2&pressure_max=1", "pressure_max=inf"):
        response = await client.get(f"/v1/materials?{query}")
        assert response.status_code == 422
    with pytest.raises(ValueError):
        SearchFilters(pressure_min=2, pressure_max=1)


@pytest.mark.asyncio
async def test_material_family_prefilter_retains_record_family_and_escapes_input(client):
    family = f'quoted"family_{uuid4().hex[:8]}'
    async with get_session_factory()() as session:
        session.add(Material(id=f"mat:family-prefilter:{uuid4().hex}", formula="Synthetic-X",
                             formula_normalized=uuid4().hex, family="different", total_papers=1,
                             needs_review=False, records=[{"family": family, "tc_kelvin": 10}]))
        await session.commit()
    response = await client.get("/v1/materials", params={"family": family, "tc_min": 5})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["results"][0]["matching_results"][0]["family"] == family


def test_representative_pressure_metadata_is_versioned():
    result = classify_pressure({"pressure_gpa": "20 kbar"}).to_dict()
    assert result["pressure_gpa"] == 2
    assert result["classifier_version"] == PRESSURE_POLICY_VERSION


def test_timeline_data_identity_changes_with_pressure_policy_even_without_source_change(monkeypatch):
    from routers import timeline
    before = timeline._timeline_data_version(None)
    key_before = timeline._cache_key(None, False, False, False, None, False)
    monkeypatch.setattr(timeline, "PRESSURE_POLICY_VERSION", "pressure-policy/future")
    assert timeline._timeline_data_version(None) != before
    assert timeline._cache_key(None, False, False, False, None, False) != key_before
