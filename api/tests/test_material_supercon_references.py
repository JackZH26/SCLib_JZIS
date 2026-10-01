"""MDR references exercise real source partitions on owned disposable services."""
from copy import deepcopy
from uuid import uuid4

import pytest

from models.db import Material, Paper, get_session_factory


async def seed(*, status="active_research", quarantine=False, excluded=False, mixed=False):
    suffix = uuid4().hex[:12]
    identifier, paper_id = f"mat:supercon/{suffix}", f"supercon:active:{suffix}"
    records = [{"paper_id": paper_id, "formula": "Nb", "formula_raw": "Nb", "tc_kelvin": 9,
                "year": 2025, "knowledge_origin": "Observed", "measurement": "resistivity"}]
    async with get_session_factory()() as session:
        session.add(Paper(id=paper_id, source="arxiv", title="Synthetic SuperCon route fixture",
                          authors=[], abstract="Synthetic test, not scientific evidence.",
                          status="withdrawn" if excluded else "published"))
        if mixed:
            excluded_id = f"supercon:excluded:{suffix}"
            session.add(Paper(id=excluded_id, source="arxiv", title="Synthetic excluded isotope fixture",
                              authors=[], abstract="Synthetic test.", status="retracted"))
            records.append({"paper_id": excluded_id, "formula": "Nb", "formula_raw": "⁹³Nb",
                            "tc_kelvin": 200, "knowledge_origin": "Observed", "year": 2024})
        material = Material(id=identifier, formula="Nb", formula_normalized=f"supercon-{suffix}",
                            family=f"supercon-{suffix}", records=deepcopy(records), tc_max=9,
                            total_papers=len(records), needs_review=False, status=status,
                            review_reason="provenance_quarantine_nims" if quarantine else None)
        session.add(material)
        await session.commit()
        updated = material.updated_at
    return identifier, paper_id, records, updated


@pytest.mark.asyncio
async def test_actual_snapshot_route_uses_only_current_sources_and_preserves_canonical_records(client):
    identifier, _, records, updated = await seed(mixed=True)
    response = await client.get(f"/v1/materials/{identifier}/external_supercon")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    report = response.json()
    assert report["version"] == "material-supercon-references/1.0.0"
    assert report["status"] == "available" and len(report["references"]) == report["matches_total"] == 19
    assert report["omitted_rows"] == 0 and report["truncated"] is False
    assert report["source_publication_status"] == "not_checked"
    assert report["scientific_acceptance"] is report["sample_identity_established"] is report["phase_identity_established"] is False
    assert all(row["source_table"] == "oxide_metallic" for row in report["references"])
    assert all(row["url"] == "https://doi.org/10.48505/nims.4487" for row in report["references"])
    assert {q["field"] for row in report["references"] for q in row["quantities"]} >= {"tc", "t1", "t2"}
    async with get_session_factory()() as session:
        material = await session.get(Material, identifier)
        assert material.records == records and material.tc_max == 9 and material.updated_at == updated


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["held", "quarantined", "source_excluded"])
async def test_actual_db_ineligible_rows_cannot_load_external_snapshot(client, monkeypatch, state):
    identifier, _, _, _ = await seed(status="pending" if state == "held" else "active_research",
                                     quarantine=state == "quarantined", excluded=state == "source_excluded")
    from services import material_supercon_references

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("Ineligible material must be rejected before external snapshot access")

    monkeypatch.setattr(material_supercon_references, "fetch_material_supercon_references", unexpected)
    response = await client.get(f"/v1/materials/{identifier}/external_supercon")
    assert response.status_code == 404
    assert "references" not in response.json()


@pytest.mark.asyncio
async def test_actual_source_withdrawal_during_snapshot_read_discards_response(client, monkeypatch):
    identifier, paper_id, _, _ = await seed()
    from services import material_supercon_references
    original = material_supercon_references.fetch_material_supercon_references

    async def withdrawing(formula, *, current_records):
        assert formula == "Nb" and [row["paper_id"] for row in current_records] == [paper_id]
        report = await original(formula, current_records=current_records)
        assert report["status"] == "available"
        async with get_session_factory()() as session:
            paper = await session.get(Paper, paper_id)
            paper.status = "withdrawn"
            await session.commit()
        return report

    monkeypatch.setattr(material_supercon_references, "fetch_material_supercon_references", withdrawing)
    response = await client.get(f"/v1/materials/{identifier}/external_supercon")
    assert response.status_code == 503
    assert "no-store" in response.headers["cache-control"] and response.headers["retry-after"] == "1"
    assert "references" not in response.json()


def test_suffix_route_is_registered_before_greedy_detail():
    from routers.materials import router
    paths = [route.path for route in router.routes]
    assert paths.index("/materials/{material_id:path}/external_supercon") < paths.index("/materials/{material_id:path}")
