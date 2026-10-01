"""NOMAD route keeps eligible-source and in-flight revision fences intact."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services import material_calculation_references as nomad


def context():
    current = [{"formula_raw": "NbN", "paper_id": "paper:current"}]
    return SimpleNamespace(formula="NbN", visibility={}, current_records=lambda: current,
                           records=[*current, {"formula_raw": "Nb¹⁵N", "paper_id": "paper:excluded"}])


@pytest.mark.asyncio
async def test_calculation_route_passes_only_current_source_records_and_is_no_store(monkeypatch):
    from routers import materials

    material = context()

    class Session:
        async def get(self, *args):
            return material

    async def view(*args):
        return material

    async def revision(*args):
        return (1, 1)

    async def fetch(formula, *, current_records):
        assert formula == "NbN" and current_records is material.current_records()
        assert nomad.external_query_formula(formula, current_records=current_records) == "NbN"
        assert nomad.external_query_formula(formula, current_records=material.records) is None
        return nomad._base(formula, "no_match", query="NNb")

    monkeypatch.setattr(materials, "material_view", view)
    monkeypatch.setattr(materials, "_material_page_revision", revision)
    monkeypatch.setattr(materials, "visibility_allows_view", lambda value: True)
    monkeypatch.setattr(nomad, "fetch_material_calculation_references", fetch)
    response = await materials.material_external_calculations("mat:synthetic", identity=None, db=Session())
    assert json.loads(response.body)["status"] == "no_match"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["X-Materials-Cache"] == "CALCULATION_REFERENCE"


@pytest.mark.asyncio
async def test_calculation_route_does_not_publish_when_source_changes_midrequest(monkeypatch):
    from routers import materials

    material, epoch = context(), 1

    class Session:
        async def get(self, *args):
            return material

    async def view(*args):
        return material

    async def revision(*args):
        return (epoch,)

    async def fetch(*args, **kwargs):
        nonlocal epoch
        epoch = 2
        return nomad._base("NbN", "available", query="NNb")

    monkeypatch.setattr(materials, "material_view", view)
    monkeypatch.setattr(materials, "_material_page_revision", revision)
    monkeypatch.setattr(materials, "visibility_allows_view", lambda value: True)
    monkeypatch.setattr(nomad, "fetch_material_calculation_references", fetch)
    with pytest.raises(HTTPException) as error:
        await materials.material_external_calculations("mat:synthetic", identity=None, db=Session())
    assert error.value.status_code == 503 and error.value.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_unavailable_material_is_checked_before_cache_or_provider(monkeypatch):
    from routers import materials

    class Session:
        async def get(self, *args):
            return None

    async def view(*args):
        return None

    async def revision(*args):
        return None

    async def unexpected(*args, **kwargs):
        raise AssertionError("Excluded material must not access cache or provider")

    monkeypatch.setattr(materials, "material_view", view)
    monkeypatch.setattr(materials, "_material_page_revision", revision)
    monkeypatch.setattr(nomad, "fetch_material_calculation_references", unexpected)
    with pytest.raises(HTTPException) as error:
        await materials.material_external_calculations("mat:excluded", identity=None, db=Session())
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_reported_dft_metadata_is_additive_and_does_not_promote_underlying_gw_method(monkeypatch):
    from routers import materials

    material = context()

    class Session:
        async def get(self, *args):
            return material

    async def view(*args):
        return material

    async def revision(*args):
        return (1,)

    async def fetch(formula, *, current_records):
        row = {"entry_id": "synthetic_gw", "results": {
            "material": {"chemical_formula_hill": "NNb"},
            "method": {"method_name": "G0W0", "simulation": {
                "program_name": "exciting", "dft": {
                    "xc_functional_names": ["GGA_X_PBE", "GGA_C_PBE"],
                    "xc_functional_type": "GGA", "spin_polarized": False,
                },
            }},
        }}
        return nomad.project_calculation_references(formula, {"data": [row], "pagination": {"total": 1}}, retrieved_at="2026-10-02T00:00:00+00:00")

    monkeypatch.setattr(materials, "material_view", view)
    monkeypatch.setattr(materials, "_material_page_revision", revision)
    monkeypatch.setattr(materials, "visibility_allows_view", lambda value: True)
    monkeypatch.setattr(nomad, "fetch_material_calculation_references", fetch)
    response = await materials.material_external_calculations("mat:synthetic", identity=None, db=Session())
    report = json.loads(response.body)
    row = report["references"][0]
    assert row["method"] == "G0W0" and row["xc_functional_names"] == ["GGA_X_PBE", "GGA_C_PBE"]
    assert row["spin_polarized"] is False and row["dft_metadata_status"] == "reported"
    assert row["dft_metadata_scope"] == "reported_underlying_dft_metadata_not_complete_method"
    assert row["conditions_status"] == "not_inspected"
    assert row["phase_identity_established"] is False and report["scientific_acceptance"] is False
    assert response.headers["cache-control"] == "private, no-store"
