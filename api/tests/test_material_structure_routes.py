"""Source-scoped external routes never publish across an epoch change."""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["structures", "calculations"])
@pytest.mark.parametrize("change", [False, True])
async def test_external_route_current_partition_epoch_and_private_response(monkeypatch, kind, change):
    from routers import materials
    from services import material_calculation_references
    records = [{"formula_raw": "FeSe", "paper_id": "active"}]
    material = SimpleNamespace(formula="FeSe", visibility={}, current_records=lambda: records,
                               records=[*records, {"formula_raw": "FeSe/SrTiO3", "paper_id": "withdrawn"}])
    epoch = 1
    class Session:
        async def get(self, *_args): return material
    async def view(*_args): return material
    async def revision(*_args): return (epoch,)
    async def fetch(formula, *, current_records):
        nonlocal epoch
        assert formula == "FeSe" and current_records is records
        if change:
            epoch = 2
        return {"status": "no_match"}
    monkeypatch.setattr(materials, "material_view", view)
    monkeypatch.setattr(materials, "_material_page_revision", revision)
    monkeypatch.setattr(materials, "visibility_allows_view", lambda _value: True)
    if kind == "structures":
        monkeypatch.setattr(materials, "fetch_material_crystal_references", fetch)
    else:
        monkeypatch.setattr(material_calculation_references, "fetch_material_calculation_references", fetch)
    route = materials.material_external_structures if kind == "structures" else materials.material_external_calculations
    if change:
        with pytest.raises(HTTPException) as exc:
            await route("mat:fixture/path", identity=None, db=Session())
        assert exc.value.status_code == 503 and exc.value.headers["Cache-Control"] == "no-store"
    else:
        response = await route("mat:fixture/path", identity=None, db=Session())
        assert json.loads(response.body) == {"status": "no_match"}
        assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["structures", "calculations"])
async def test_ineligible_material_never_queries_external_provider(monkeypatch, kind):
    from routers import materials
    class Session:
        async def get(self, *_args): return None
    async def view(*_args): return None
    async def revision(*_args): return None
    monkeypatch.setattr(materials, "material_view", view)
    monkeypatch.setattr(materials, "_material_page_revision", revision)
    route = materials.material_external_structures if kind == "structures" else materials.material_external_calculations
    with pytest.raises(HTTPException) as exc:
        await route("absent", identity=None, db=Session())
    assert exc.value.status_code == 404
