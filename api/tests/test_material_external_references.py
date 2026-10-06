"""External composition matches cannot become selected sample properties."""
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from services import material_external_references as references


def row(identifier="mp-1", formula="NbN", **values):
    return {"material_id": identifier, "formula_pretty": formula, "band_gap": 0,
            "density": 8.3, "energy_above_hull": 0.03,
            "symmetry": {"symbol": "Fm-3m", "number": 225},
            "structure": {"lattice": {"a": 4.4}, "sites": [{"secret": "not public"}]},
            "origins": [{"name": "structure", "task_id": "mp-12"}], **values}


def test_all_polymorphs_stay_composition_only_and_outside_tc():
    result = references.project_external_references("NbN", [row("mp-2"), row("mp-1")], retrieved_at="2026-10-01T00:00:00Z")
    assert [item["id"] for item in result["candidates"]] == ["mp-1", "mp-2"]
    assert result["sample_identity_established"] is False
    assert result["scientific_acceptance"] is False
    for candidate in result["candidates"]:
        assert candidate["knowledge_origin"] == "Computed"
        assert candidate["phase_identity_established"] is False
        assert candidate["band_gap_ev"] == 0
        assert "tc_kelvin" not in candidate and "structure" not in candidate
        assert candidate["origins"] == [{"property": "structure", "task_id": "mp-12", "last_updated": None}]


@pytest.mark.parametrize("formula", ["LaAlO3/SrTiO3", "YBa2Cu3O7-x", "MgB2-x", "D2S", "Nb-N", "Bi_2Sr_2CaCu_2O_{8+δ}"])
def test_unresolved_compositions_have_no_bulk_surrogate(formula):
    assert references.external_query_formula(formula) is None
    assert references.project_external_references(formula, [row()], retrieved_at="now")["status"] == "not_applicable"


@pytest.mark.parametrize("record", [
    {"formula_raw": "La₂Cu¹⁸O₄"},
    {"raw_extraction": {"formula_raw": "La₂Cu¹⁸O₄"}},
    {"formula": "La₂Cu¹⁸O₄"},
])
def test_normalized_catalogue_formula_cannot_erase_retained_isotope_identity(record):
    assert references.external_query_formula("La2Cu18O4", current_records=[record]) is None
    assert references.external_query_formula("La2CuO4", current_records=[{"formula_raw": "La₂CuO₄"}]) == "La2CuO4"


@pytest.mark.parametrize("formula,record", [
    ("LaScH", {"formula_raw": "LaδSc1−δH10", "formula": "LaScH"}),
    ("LaScH", {"raw_extraction": {"formula_raw": "LaδSc1−δH10"}, "formula": "LaScH"}),
    ("LaScH", {"raw_extraction": {"formula": "LaδSc1−δH10"}, "formula": "LaScH"}),
    ("LaScH", {"formula": "LaδSc1−δH10"}),
    ("FeSe", {"formula_raw": "FeSe/SrTiO3"}),
    ("YBa2Cu3O7", {"formula_raw": "YBCO"}),
    ("MgB2", {"formula_raw": "MgB2^+"}),
    ("BaFe1.906Pt0.094As2", {"formula_raw": "BaFe1.90Pt0.10As2"}),
    ("BaFe1.906Pt0.094As2", {"formula_raw": "BaFe2As2"}),
])
def test_unresolved_or_different_original_composition_cannot_use_catalogue_alias(formula, record):
    assert references.external_query_formula(formula, current_records=[record]) is None


def test_missing_original_formula_and_equal_fixed_composition_allow_catalogue_lookup():
    assert references.external_query_formula("MgB2", current_records=[{"paper_id": "paper:1"}]) == "MgB2"
    assert references.external_query_formula("MgB2", current_records=[{"formula_raw": "B2Mg"}]) == "MgB2"


@pytest.mark.parametrize("formula, reordered", [
    ("CaO2Zr", "ZrCaO2"), ("TcTi2Zn", "ZnTi2Tc"), ("HfO2Y", "YHfO2"),
    ("V", "V1"), ("C", "C1"), ("Y", "Y1"),
])
def test_fixed_element_tokens_allow_composition_only_references(formula, reordered):
    assert references.external_query_formula(formula, current_records=[{"formula_raw": reordered}]) == formula
    result = references.project_external_references(formula, [row(formula=reordered)], retrieved_at="now")
    assert len(result["candidates"]) == 1
    assert result["sample_identity_established"] is False
    assert result["scientific_acceptance"] is False
    assert result["candidates"][0]["phase_identity_established"] is False


@pytest.mark.parametrize("formula, raw", [
    ("Y", "Y1-x"), ("C", "13C"), ("V", "V/Nb"),
    ("HfO2Y", "HfO2Yy"), ("CaO2Zr", "CaO2Zrz"),
    ("YBa2Cu3O7", "YBa2Cu3O7-X"), ("La2CuO4", "La2CuO4-Y"),
])
def test_fixed_alias_does_not_override_unresolved_original_state(formula, raw):
    assert references.external_query_formula(formula, current_records=[{"formula_raw": raw}]) is None


@pytest.mark.asyncio
async def test_isotope_identity_is_checked_before_cache_or_provider(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("An unresolved isotope must not read cached bulk references or query MP")
    monkeypatch.setattr(references, "get_redis", unexpected)
    monkeypatch.setattr(references, "MaterialsProjectClient", unexpected)
    result = await references.fetch_external_references(
        "La2Cu18O4", api_key="test-only", current_records=[{"formula_raw": "La₂Cu¹⁸O₄"}],
    )
    assert result["status"] == "not_applicable"
    assert result["reason"] == "composition_requires_resolution"
    assert result["candidates"] == []


@pytest.mark.asyncio
async def test_external_route_passes_only_current_eligible_source_records(monkeypatch):
    from routers import materials
    current = [{"formula_raw": "NbN", "paper_id": "paper:active"}]
    context = SimpleNamespace(
        formula="NbN", visibility={}, current_records=lambda: current,
        records=[*current, {"formula_raw": "Nb¹⁵N", "paper_id": "paper:excluded"}],
    )
    class ReadSession:
        async def get(self, *_args): return context
    async def view(*_args): return context
    async def revision(*_args): return None
    async def fetch(formula, *, api_key, current_records):
        assert formula == "NbN" and api_key == "test-only"
        assert current_records is current
        assert references.external_query_formula(formula, current_records=current_records) is not None
        assert references.external_query_formula(formula, current_records=context.records) is None
        return {"status": "no_match"}
    monkeypatch.setattr(materials, "material_view", view)
    monkeypatch.setattr(materials, "_material_page_revision", revision)
    monkeypatch.setattr(materials, "visibility_allows_view", lambda _value: True)
    monkeypatch.setattr(materials, "get_settings", lambda: SimpleNamespace(mp_api_key="test-only"))
    monkeypatch.setattr(materials, "fetch_external_references", fetch)
    response = await materials.material_external_references("mat:fixture", identity=None, db=ReadSession())
    assert json.loads(response.body) == {"status": "no_match"}
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_external_route_does_not_publish_after_source_revision_changes(monkeypatch):
    from routers import materials
    context = SimpleNamespace(formula="NbN", visibility={}, current_records=lambda: [])
    revision_number = 1
    class ReadSession:
        async def get(self, *_args): return context
    async def view(*_args): return context
    async def revision(*_args): return (revision_number,)
    async def fetch(*_args, **_kwargs):
        nonlocal revision_number
        revision_number = 2  # Source withdrawal while the provider request was in flight.
        return {"status": "available", "candidates": [row()]}
    monkeypatch.setattr(materials, "material_view", view)
    monkeypatch.setattr(materials, "_material_page_revision", revision)
    monkeypatch.setattr(materials, "visibility_allows_view", lambda _value: True)
    monkeypatch.setattr(materials, "get_settings", lambda: SimpleNamespace(mp_api_key="test-only"))
    monkeypatch.setattr(materials, "fetch_external_references", fetch)
    with pytest.raises(HTTPException) as error:
        await materials.material_external_references("mat:fixture", identity=None, db=ReadSession())
    assert error.value.status_code == 503
    assert error.value.headers["Cache-Control"] == "no-store"


def test_wrong_composition_invalid_ids_and_nonfinite_data_are_not_promoted():
    result = references.project_external_references("NbN", [row(formula="Nb2N"), row("https://bad.example"), row("mp-3", density=float("nan"), tc_kelvin=300)], retrieved_at="now")
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["density_g_cm3"] is None
    assert "tc_kelvin" not in result["candidates"][0]


def test_current_alphabetic_provider_ids_survive_and_filtered_rows_are_not_absence():
    result = references.project_external_references("NbN", [row("mp-aaaaaciu")], retrieved_at="now")
    assert result["status"] == "available"
    assert result["candidates"][0]["id"] == "mp-aaaaaciu"
    assert references.project_external_references("NbN", [row(formula="Nb2N")], retrieved_at="now")["status"] == "unavailable"
    assert references.project_external_references("NbN", [], retrieved_at="now")["status"] == "no_match"


class Cache:
    def __init__(self): self.values, self.budget = {}, 0
    async def get(self, key): return self.values.get(key)
    async def set(self, key, value, ex): self.values[key] = value
    def pipeline(self, transaction=True): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def incr(self, key): self.budget += 1
    def expire(self, key, ttl): pass
    async def execute(self): return self.budget, True


@pytest.mark.asyncio
async def test_cache_reuses_references_without_upstream_and_errors_are_not_absence(monkeypatch):
    cache = Cache()
    monkeypatch.setattr(references, "get_redis", lambda: cache)
    class Client:
        calls = 0
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def search_by_formula(self, *args, **kwargs):
            assert kwargs["strict"] is True
            assert kwargs["max_response_bytes"] == references.MAX_BYTES
            Client.calls += 1
            return [row()]
    monkeypatch.setattr(references, "MaterialsProjectClient", Client)
    first = await references.fetch_external_references("NbN", api_key="test-only")
    second = await references.fetch_external_references("NbN", api_key="test-only")
    assert first == second and Client.calls == 1
    class Broken(Client):
        async def search_by_formula(self, *args, **kwargs):
            raise httpx.ConnectError("private upstream diagnostics")
    monkeypatch.setattr(references, "MaterialsProjectClient", Broken)
    failed = await references.fetch_external_references("MgB2", api_key="test-only")
    assert failed["status"] == "unavailable"
    assert "private" not in json.dumps(failed)
    assert not any(value.get("formula") == "MgB2" for value in map(json.loads, cache.values.values()))


@pytest.mark.asyncio
async def test_no_credentials_or_invalid_composition_do_not_query_provider():
    assert (await references.fetch_external_references("NbN", api_key=""))["reason"] == "provider_not_configured"
    assert (await references.fetch_external_references("LaAlO3/SrTiO3", api_key="unused"))["status"] == "not_applicable"
