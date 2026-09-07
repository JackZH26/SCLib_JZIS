"""Phase-1 safeguards for reproducible material data exports."""

from __future__ import annotations

import pytest

from models.db import Material, get_session_factory
from services.pressure_semantics import classify_pressure


@pytest.mark.asyncio
async def test_material_list_uses_material_id_as_stable_tie_breaker(client) -> None:
    prefix = "mat:phase1-order-"
    factory = get_session_factory()
    async with factory() as session:
        for suffix in ("c", "a", "b"):
            session.add(
                Material(
                    id=f"{prefix}{suffix}",
                    formula=f"Phase1{suffix.upper()}",
                    formula_normalized=f"phase1{suffix}",
                    tc_max=10.0,
                    total_papers=1,
                    needs_review=False,
                    records=[],
                )
            )
        await session.commit()

    response = await client.get("/v1/materials?sort=tc_max&limit=200")
    assert response.status_code == 200
    ids = [row["id"] for row in response.json()["results"] if row["id"].startswith(prefix)]
    assert ids == sorted(ids)


@pytest.mark.asyncio
async def test_phase_diagram_does_not_inherit_material_level_doping(client) -> None:
    material_id = "mat:phase1-no-doping-inheritance"
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Material(
                id=material_id,
                formula="Phase1D",
                formula_normalized="phase1d",
                tc_max=8.0,
                total_papers=1,
                doping_level=0.3,
                needs_review=False,
                records=[
                    {
                        "tc_kelvin": 8.0,
                        "pressure_gpa": 1.0,
                        "paper_id": "arxiv:phase1",
                        "year": 2026,
                    }
                ],
            )
        )
        await session.commit()

    response = await client.get(f"/v1/materials/{material_id}/phase_diagram")
    assert response.status_code == 200
    row = response.json()[0]
    assert row.pop("material_id") == material_id
    assert row.pop("visibility")["public_catalogue_eligible"] is True
    assert [row] == [
        {
            "formula": "Phase1D",
            "tc_kelvin": 8.0,
            "doping_level": None,
            "pressure_gpa": 1.0,
            "pressure_semantics": classify_pressure({"pressure_gpa": 1.0}).to_dict(),
            "paper_id": "arxiv:phase1",
            "year": 2026,
        }
    ]
