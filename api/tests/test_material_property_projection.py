"""SC02 public boundary: one selected property, one result, its own context."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from models.db import Material, get_session_factory
from models.search import MaterialDetail, MaterialSummary, VariantSummary
from services.material_property_projection import project_material_properties
from services.scientific_filters import ResultFilters, matching_result_references


def material(**overrides):
    return {
        "id": "mat:atomic", "formula": "MgB2", "formula_latex": None,
        "family": None, "subfamily": None, "tc_max": 39.0,
        "tc_max_conditions": "unsupported catalogue context", "tc_ambient": None,
        "arxiv_year": 2026, "total_papers": 1, "status": "active",
        "crystal_structure": None,
        "records": [{"tc_kelvin": 39, "paper_id": "paper:tc", "knowledge_origin": "Observed"}],
        **overrides,
    }


def test_list_replaces_untraceable_scalar_without_resurrecting_capped_result():
    row = material(tc_max=100, records=[{"tc_kelvin": 300, "paper_id": "paper:raw"}])
    saved = deepcopy(row)
    summary = MaterialSummary.model_validate(row)
    assert summary.tc_max is None
    assert summary.tc_max_conditions is None
    binding = summary.property_evidence["properties"]["tc_max"]
    assert binding["status"] == "untraceable" and binding["selected"] is None
    assert summary.property_evidence["not_joint_observation"] is True
    assert row == saved


def test_null_selection_stays_null_and_public_envelope_is_not_evidence():
    forged = {"properties": {"tc_max": {"status": "supported", "selected": {"value": 999}}}}
    summary = MaterialSummary.model_validate(material(tc_max=None, property_evidence=forged))
    assert summary.tc_max is None
    assert summary.property_evidence != forged
    rawless = MaterialSummary.model_validate(material(records=[], property_evidence=forged))
    assert rawless.tc_max is None


def test_hc2_value_conditions_and_structure_always_follow_selected_result():
    records = [
        {"hc2_tesla": 20, "hc2_conditions": "H || c, 5 K", "hc2_direction": "c",
         "hc2_temperature_k": 5, "paper_id": "paper:a", "lattice_a": 3},
        {"hc2_tesla": 100, "hc2_conditions": "H || ab, 0 K", "hc2_direction": "ab",
         "hc2_temperature_k": 0, "paper_id": "paper:b", "lattice_c": 8},
    ]
    row = material(records=records, hc2_tesla=100, hc2_conditions="H || c, 5 K",
                   lattice_params={"a": 3, "c": 8})
    detail = MaterialDetail.model_validate(SimpleNamespace(**row))
    assert detail.hc2_tesla == 100
    assert detail.hc2_conditions == "H || ab, 0 K"
    selected = detail.property_evidence["properties"]["hc2_tesla"]["selected"]
    assert selected["source"]["paper_id"] == "paper:b"
    assert selected["conditions"]["hc2_temperature_k"]["value"] == 0
    assert selected["conditions"]["hc2_direction"] == "ab"
    assert detail.lattice_params is None
    assert detail.property_evidence["properties"]["lattice_params"]["status"] == "untraceable"
    assert records == row["records"]  # Projection does not replace retained raw observations.


def test_variants_and_compact_lists_use_same_identity_as_filters():
    record = {"tc_kelvin": 39, "knowledge_origin": "Observed", "paper_id": "paper:tc"}
    base = material(records=[record], doping_level=0.15)
    summary = MaterialSummary.model_validate(base)
    variant = VariantSummary.model_validate(SimpleNamespace(**base))
    selected = summary.property_evidence["properties"]["tc_max"]["selected"]
    assert variant.tc_max == 39 and variant.doping_level is None
    assert variant.property_evidence["properties"]["tc_max"]["selected"] == selected
    matched = matching_result_references(
        [record], ResultFilters(tc_min=30), scope_id=base["id"],
    )
    assert selected["result_id"] == matched[0]["result_id"]
    assert summary.property_evidence["evidence_scope"] == "selected_only"
    assert summary.property_evidence["joint_epc"]["status"] == "not_evaluated"
    assert all(binding["evidence"] == [] for binding in summary.property_evidence["properties"].values())


def test_derived_metadata_never_changes_filter_identity():
    record = {"tc_kelvin": 39, "paper_id": "paper:tc"}
    before = matching_result_references([record], ResultFilters(tc_min=30), scope_id="mat:atomic")
    after = matching_result_references(
        [{**record, "property_evidence": {"forged": True}}],
        ResultFilters(tc_min=30), scope_id="mat:atomic",
    )
    assert before[0]["result_id"] == after[0]["result_id"]


def test_missing_pressure_cannot_support_ambient_variant_or_bookmark():
    row = material(tc_ambient=39, ambient_sc=True)
    variant = VariantSummary.model_validate(row)
    bookmarked = project_material_properties(row, {"id", "tc_max", "tc_ambient"}, compact=True)
    assert variant.tc_ambient is None and bookmarked["tc_ambient"] is None
    assert MaterialSummary.model_validate(row).ambient_sc is None


def test_governance_warnings_are_not_suppressed_by_missing_raw_property_flags():
    detail = MaterialDetail.model_validate(material(disputed=True, retracted=True))
    assert detail.disputed is True and detail.retracted is True
    assert "disputed" not in detail.property_evidence["properties"]
    assert "retracted" not in detail.property_evidence["properties"]


def test_narrow_responses_preserve_headline_origin_pool_without_borrowing_theory_source():
    row = SimpleNamespace(**material(
        tc_max_experimental=39, tc_max_theoretical=None,
        records=[{"tc_kelvin": 39, "knowledge_origin": "Computed", "paper_id": "paper:theory"}],
    ))
    summary = MaterialSummary.model_validate(row)
    variant = VariantSummary.model_validate(row)
    bookmark = project_material_properties(row, {"id", "tc_max", "tc_ambient"}, compact=True)
    assert summary.tc_max is None and variant.tc_max is None and bookmark["tc_max"] is None
    assert summary.result_origin_counts["Computed"] == 1
    assert summary.tc_max_origin == "Unknown"


@pytest.mark.asyncio
async def test_list_detail_variant_and_bookmark_responses_share_atomic_selection(client, registered_user):
    _, jwt = registered_user
    parent_id, child_id = "mat:sc02-parent", "mat:sc02-child"
    record = {"tc_kelvin": 39, "tc_conditions": "resistive onset", "tc_type": "onset",
              "knowledge_origin": "Observed", "paper_id": "paper:atomic"}
    factory = get_session_factory()
    async with factory() as session:
        session.add(Material(id=parent_id, formula="MgB2", formula_normalized="sc02-parent",
                             records=[record], tc_max=39, tc_max_conditions="wrong summary",
                             total_papers=1, needs_review=False, variant_count=1))
        await session.flush()
        session.add(Material(id=child_id, formula="MgB2", formula_normalized="sc02-child",
                             records=[record], tc_max=100, total_papers=1, needs_review=False,
                             parent_material_id=parent_id))
        await session.commit()
    listed = await client.get("/v1/materials?limit=200")
    assert listed.status_code == 200, listed.text
    parent = next(item for item in listed.json()["results"] if item["id"] == parent_id)
    detail_response = await client.get(f"/v1/materials/{parent_id}")
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    headers = {"Authorization": f"Bearer {jwt}"}
    created = await client.post("/v1/bookmarks", headers=headers,
                                json={"target_type": "material", "target_id": parent_id})
    assert created.status_code == 201, created.text
    response = await client.get("/v1/bookmarks/materials", headers=headers)
    assert response.status_code == 200, response.text
    bookmarked = response.json()["results"][0]
    selected = parent["property_evidence"]["properties"]["tc_max"]["selected"]
    assert detail["property_evidence"]["properties"]["tc_max"]["selected"] == selected
    assert bookmarked["property_evidence"]["properties"]["tc_max"]["selected"] == selected
    assert parent["tc_max_conditions"] == "resistive onset"
    assert detail["variants"][0]["tc_max"] is None
    # Read-only projection must not overwrite unsupported historical values.
    async with factory() as session:
        child = await session.get(Material, child_id)
        assert child.tc_max == 100 and child.records == [record]


@pytest.mark.asyncio
async def test_quarantined_child_cannot_leak_through_parent_evidence_or_phase_diagram(client):
    parent_id, child_id = "mat:sc02-visibility-parent", "mat:sc02-quarantined-child"
    factory = get_session_factory()
    async with factory() as session:
        session.add(Material(id=parent_id, formula="Parent", formula_normalized="sc02-visible",
                             records=[{"tc_kelvin": 39}], tc_max=39, total_papers=1,
                             needs_review=False, variant_count=1))
        await session.flush()
        session.add(Material(id=child_id, formula="Quarantined", formula_normalized="sc02-quarantined",
                             records=[{"tc_kelvin": 100}], tc_max=100, total_papers=1,
                             parent_material_id=parent_id, needs_review=False,
                             review_reason="provenance_quarantine_nims"))
        await session.commit()
    detail = await client.get(f"/v1/materials/{parent_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["variants"] == []
    points = await client.get(f"/v1/materials/{parent_id}/phase_diagram")
    assert points.status_code == 200, points.text
    assert all(row["formula"] != "Quarantined" for row in points.json())
    assert (await client.get(f"/v1/materials/{child_id}")).status_code == 404
