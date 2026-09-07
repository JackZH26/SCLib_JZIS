"""SC11 pending-first API boundaries, using synthetic records only."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio

from models.db import Material, Paper, get_session_factory
from models.search import MaterialSummary, VariantSummary
from services.material_property_projection import project_material_properties
from services.structure_evidence import STRUCTURE_EVIDENCE_FIELDS, STRUCTURE_EVIDENCE_VERSION


def record(**changes):
    return {"paper_id": "synthetic:structure", "formula": "Nb", "knowledge_origin": "Observed",
            "source_role": "primary", "tc_kelvin": 10, "pressure_gpa": 1, **changes}


def material(**changes):
    return {"id": "mat:structure", "formula": "Nb", "formula_latex": None, "family": "elemental",
            "subfamily": None, "status": "active_research", "total_papers": 1,
            "needs_review": False, "disputed": False, "records": [], "arxiv_year": None,
            "tc_max": 10, "tc_max_conditions": None, "tc_ambient": None, **changes}


@pytest.mark.parametrize("field", STRUCTURE_EVIDENCE_FIELDS)
def test_source_reported_text_is_pending_not_a_structure_selection(field):
    raw = material(**{field: "synthetic label"}, records=[record(**{field: "synthetic label"})])
    before = deepcopy(raw)
    payload = project_material_properties(raw, {*MaterialSummary.model_fields, field})
    assert payload[field] is None
    assert payload["property_evidence"]["properties"][field]["selected"] is None
    assert "structure_association_pending_source_review" in payload["property_evidence"]["properties"][field]["warnings"]
    assert payload["structure_evidence"]["properties"][field]["status"] == "pending"
    assert payload["structure_evidence"]["properties"][field]["value"] is None
    assert payload["tc_max"] == 10  # Unrelated numeric selection is not erased.
    assert raw == before


def test_empty_metadata_is_not_reconstructed_as_an_approved_structure():
    raw = material(structure_phase="old catalogue phase", records=[record()])
    public = MaterialSummary.model_validate(raw)
    assert public.structure_phase is None
    assert public.structure_evidence["properties"]["structure_phase"]["status"] == "unknown"


def test_cached_accepted_envelope_cannot_fill_a_missing_raw_structure():
    raw = material(records=[record()], structure_evidence={
        "version": STRUCTURE_EVIDENCE_VERSION, "scientific_acceptance": True,
        "properties": {"structure_phase": {"status": "accepted", "value": "forged"}},
    })
    public = MaterialSummary.model_validate(raw)
    assert public.structure_phase is None
    assert public.structure_evidence["scientific_acceptance"] is False
    assert not public.structure_evidence["proposals"]


def test_variant_and_compact_bookmark_keep_pending_evidence():
    raw = material(records=[record(space_group="synthetic symmetry")])
    variant = VariantSummary.model_validate(raw)
    compact = project_material_properties(raw, {"id", "formula", "structure_evidence"}, compact=True)
    assert compact["structure_evidence"] == variant.structure_evidence
    assert compact["structure_evidence"]["properties"]["space_group"]["status"] == "pending"


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


async def seed(session):
    suffix = uuid4().hex[:12]
    pid = "synthetic:sc11-" + suffix
    session.add(Paper(id=pid, source="arxiv", title="Synthetic SC11 source", authors=[],
                      abstract="Fixture only", status="published"))
    row = Material(id="mat:sc11-" + suffix, formula="Nb", formula_normalized="sc11-" + suffix,
                   family="sc11_" + suffix, total_papers=1, needs_review=False,
                   structure_phase="synthetic phase", crystal_structure="synthetic crystal", space_group="synthetic group",
                   records=[record(paper_id=pid, structure_phase="synthetic phase", crystal_structure="synthetic crystal", space_group="synthetic group")])
    session.add(row)
    await session.commit()
    return row, pid


@pytest.mark.asyncio
async def test_detail_and_list_withhold_structure_aliases_without_rewriting_history(client, db_session):
    row, _ = await seed(db_session)
    detail = await client.get(f"/v1/materials/{row.id}")
    assert detail.status_code == 200, detail.text
    for field in STRUCTURE_EVIDENCE_FIELDS:
        assert detail.json()[field] is None
        assert detail.json()["structure_evidence"]["properties"][field]["status"] == "pending"
    response = await client.get("/v1/materials", params={"family": row.family})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["results"][0]["structure_phase"] is None
    await db_session.refresh(row)
    assert row.structure_phase == "synthetic phase"
    assert row.records[0]["structure_phase"] == "synthetic phase"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["synthetic phase", "accepted", " "])
async def test_phase_filter_explicitly_unavailable_not_an_empty_scientific_result(client, value):
    response = await client.get("/v1/materials", params={"structure_phase": value})
    assert response.status_code == 422
    assert "reviewed material/state associations" in response.json()["detail"]


@pytest.mark.asyncio
async def test_current_source_hold_is_visible_in_pending_proposals(client, db_session):
    row, pid = await seed(db_session)
    paper = await db_session.get(Paper, pid)
    paper.status = "corrected"
    await db_session.commit()
    response = await client.get(f"/v1/materials/{row.id}")
    assert response.status_code == 200, response.text
    envelope = response.json()["structure_evidence"]
    assert "current_source_status_unresolved_or_held" in envelope["warnings"]
    assert all(item["status"] == "pending" and item["scientific_acceptance"] is False for item in envelope["proposals"])


@pytest.mark.asyncio
async def test_bookmarks_carry_pending_proposals(client, db_session, registered_user):
    row, _ = await seed(db_session)
    _, token = registered_user
    headers = {"Authorization": f"Bearer {token}"}
    saved = await client.post("/v1/bookmarks", json={"target_type": "material", "target_id": row.id}, headers=headers)
    assert saved.status_code == 201, saved.text
    response = await client.get("/v1/bookmarks/materials", headers=headers)
    assert response.status_code == 200, response.text
    item = next(item for item in response.json()["results"] if item["target_id"] == row.id)
    assert item["structure_evidence"]["version"] == STRUCTURE_EVIDENCE_VERSION
    assert item["structure_evidence"]["scientific_acceptance"] is False
