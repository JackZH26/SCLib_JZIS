"""Independent enrichment cannot inherit approval or expose private review data."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from models.db import HydrideTcParameter, Material, Paper, get_session_factory
from models.search import TimelinePoint
from routers.timeline import _timeline_response
from services.scientific_values import parse_scientific_value


async def _seed(*, flags=None, proposal=None, source_status="published"):
    suffix = uuid.uuid4().hex
    material_id, paper_id = f"mat:hydride-visibility-{suffix}", f"arxiv:hv-{suffix}"
    async with get_session_factory()() as db:
        db.add(Paper(id=paper_id, source="arxiv", title="Synthetic hydride visibility fixture",
                     authors=[], abstract="Test only", status=source_status))
        db.add(Material(id=material_id, formula="LaH10", formula_normalized=f"lah10-{suffix}",
                        family="test_hydride", total_papers=1, needs_review=False,
                        records=[{"tc_kelvin": 10, "pressure_gpa": 10, "year": 2026}]))
        await db.flush()
        provenance = {"source_locator": {"table": "2", "reviewer_email": "private-review@example.test"},
                      "admin_decision": {"note": "private note"}}
        if proposal is not None:
            provenance["extraction_proposal"] = {"scientific_values": proposal}
        row = HydrideTcParameter(record_key=suffix, material_id=material_id, paper_id=paper_id,
                                formula="LaH10", formula_normalized="lah10", source="arxiv",
                                tc_kelvin=10, pressure_gpa=10, lambda_eph=1, mu_star=0.1,
                                omega_log_k=100, year=2026, validation_flags=flags if flags is not None else [],
                                provenance=provenance, prompt_version="test")
        db.add(row)
        await db.commit()
    return material_id


@pytest.mark.asyncio
@pytest.mark.parametrize("flags", [
    ["omega_log_source_conversion_conflict"],
    {"unexpected": "legacy object"},
    ["pressure_gpa:non_scalar_or_invalid_preserved_in_provenance"],
])
async def test_enrichment_flags_require_archive_and_private_provenance_is_removed(client, flags):
    material_id = await _seed(flags=flags)
    url = f"/v1/materials/{material_id}/hydride_parameters"
    response = await client.get(url)
    assert response.status_code == 200, response.text
    assert response.json() == []
    archive = await client.get(url, params={"include_pending": True})
    assert archive.status_code == 200, archive.text
    [row] = archive.json()
    assert row["visibility"]["state"] == "pending"
    assert row["visibility"]["scientific_acceptance"] is False
    assert row["provenance"]["source_locator"]["table"] == "2"
    assert "private-review" not in archive.text
    assert "private note" not in archive.text
    assert "admin_decision" not in archive.text
    assert archive.headers["cache-control"] == "private, no-store"
    async with get_session_factory()() as db:
        from sqlalchemy import select
        original = (await db.execute(select(HydrideTcParameter).where(
            HydrideTcParameter.material_id == material_id))).scalar_one()
        assert original.validation_flags == flags
        assert original.provenance["admin_decision"]["note"] == "private note"


@pytest.mark.asyncio
async def test_hydride_typed_quantity_cannot_be_erased_by_flat_normalized_scalar(client):
    material_id = await _seed(proposal={
        "pressure_gpa": parse_scientific_value("not a pressure", "pressure_gpa"),
    })
    url = f"/v1/materials/{material_id}/hydride_parameters"
    assert (await client.get(url)).json() == []
    archive = await client.get(url, params={"include_pending": True})
    assert archive.status_code == 200, archive.text
    [row] = archive.json()
    assert row["visibility"]["public_catalogue_eligible"] is False
    assert row["pressure_semantics"]["pressure_state"] == "ambiguous"
    assert row["pressure_semantics"]["pressure_gpa"] is None


@pytest.mark.asyncio
async def test_hydride_independent_source_status_is_current(client):
    material_id = await _seed(source_status="retracted")
    assert (await client.get(f"/v1/materials/{material_id}")).json()["visibility"]["public_catalogue_eligible"] is True
    url = f"/v1/materials/{material_id}/hydride_parameters"
    assert (await client.get(url)).json() == []
    [row] = (await client.get(url, params={"include_pending": True})).json()
    assert row["visibility"]["source_status"] == "retracted"
    assert row["visibility"]["public_catalogue_eligible"] is False


def test_timeline_dataset_version_tracks_governance_even_with_unchanged_material_timestamp():
    time = datetime(2026, 9, 6, tzinfo=UTC)
    point = TimelinePoint(material="Fixture", material_id="mat:fixture", tc_kelvin=10,
                          year=2026, formula_latex=None, family=None, pressure_gpa=None, paper_id=None,
                          visibility={"review_revision": "old", "state": "catalogue"})
    args = {"family": None, "max_points": None, "data_updated_at": time}
    before = _timeline_response(points=[point], **args)
    point.visibility = {"review_revision": "new", "state": "corrected"}
    after = _timeline_response(points=[point], **args)
    assert before.data_version != after.data_version
    assert after.data_version == _timeline_response(points=[point], limit=1, **args).data_version
    assert after.data_version != _timeline_response(points=[], **args).data_version
