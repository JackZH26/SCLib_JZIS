from uuid import uuid4

import pytest

from models.db import Chunk, Material, Paper, get_session_factory


async def seed(*, status="active_research"):
    suffix = uuid4().hex[:12]
    material_id, paper_id = f"mat:recovery:{suffix}", f"arxiv:recovery:{suffix}"
    records = [
        {"paper_id": paper_id, "formula": "NbN", "tc_kelvin": 200, "pressure_gpa": 300,
         "knowledge_origin": "Computed", "method": "DFT", "year": 2026},
        {"paper_id": paper_id, "formula": "NbN", "tc_kelvin": 23, "pressure_gpa": 2,
         "knowledge_origin": "Observed", "measurement": "resistivity", "tc_criterion": "onset", "year": 2024},
    ]
    async with get_session_factory()() as session:
        session.add(Paper(id=paper_id, source="arxiv", title="Synthetic recovery test",
                          authors=[], abstract="Synthetic fixture", status="published"))
        session.add(Material(id=material_id, formula="NbN", formula_normalized=suffix, family=suffix,
                             records=records, tc_max=200, tc_max_theoretical=200, total_papers=1,
                             needs_review=False, status=status))
        await session.commit()
        session.add_all([
            Chunk(id=f"{paper_id}:0", paper_id=paper_id, chunk_index=0, section="Results",
                  text="NbN has a superconducting transition temperature of 23 K at 2 GPa, measured by resistivity."),
            Chunk(id=f"{paper_id}:1", paper_id=paper_id, chunk_index=1, section="Facts",
                  text="NbN has a superconducting transition temperature of 999 K at 888 GPa."),
        ])
        await session.commit()
    return material_id, suffix, records


@pytest.mark.asyncio
async def test_matched_tc_is_atomic_and_does_not_borrow_catalogue_maximum(client):
    _, family, _ = await seed()
    response = await client.get("/v1/materials", params={"family": family, "pressure_max": 3, "tc_min": 20})
    assert response.status_code == 200
    body = response.json()["results"][0]
    assert body["tc_max"] == 200
    match = body["matching_results"][0]
    assert match["tc_evidence"]["result_id"] == match["result_id"]
    assert match["tc_evidence"]["value"] == 23
    assert match["tc_evidence"]["state"]["pressure_semantics"]["pressure_gpa"] == 2
    assert match["tc_evidence"]["source"]["year"] == 2024
    assert match["tc_evidence"]["conditions"]["tc_criterion"] == "onset"


@pytest.mark.asyncio
async def test_recovery_omits_facts_and_excerpts_and_never_changes_retained_records(client):
    identifier, _, records = await seed()
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scientific_acceptance"] is False and body["database_changed"] is False
    assert body["counts"]["promoted_facts"] == 0
    assert body["candidates"]
    for candidate in body["candidates"]:
        assert "evidence_text" not in candidate
        assert candidate["value"] not in {999, 888}
        assert candidate["source"]["kind"] == "legacy_unknown"
        assert candidate["source"]["publication_revision_verified"] is False
        assert candidate["source_content_checked"] is False
    async with get_session_factory()() as session:
        assert (await session.get(Material, identifier)).records == records


@pytest.mark.asyncio
async def test_external_reference_and_recovery_routes_cannot_bypass_hold(client, monkeypatch):
    identifier, _, _ = await seed(status="pending")
    from routers import materials
    async def unexpected(*args, **kwargs):
        raise AssertionError("Upstream must not be queried for an ineligible material")
    monkeypatch.setattr(materials, "fetch_external_references", unexpected)
    assert (await client.get(f"/v1/materials/{identifier}/external_references")).status_code == 404
    assert (await client.get(f"/v1/materials/{identifier}/enrichment")).status_code == 404


@pytest.mark.asyncio
async def test_recovery_discards_snapshot_if_source_withdraws_during_read(client, monkeypatch):
    identifier, _, records = await seed()
    from services import material_enrichment_read
    original = material_enrichment_read.read_material_enrichment

    async def withdrawing(db, material):
        report = await original(db, material)
        async with get_session_factory()() as session:
            paper = await session.get(Paper, records[0]["paper_id"])
            paper.status = "withdrawn"
            await session.commit()
        return report

    monkeypatch.setattr(material_enrichment_read, "read_material_enrichment", withdrawing)
    response = await client.get(f"/v1/materials/{identifier}/enrichment")
    assert response.status_code == 503
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["retry-after"] == "1"
    assert "candidates" not in response.json()
