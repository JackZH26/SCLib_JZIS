"""SC10 synthetic read/filter contracts; no material claims or production data."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from models.db import Material, Paper, get_session_factory
from models.search import MaterialSummary, VariantSummary
from services.audit_rules import rule_by_name
from services.material_property_projection import (
    project_material_properties,
    project_material_semantics,
)
from services.material_semantics import MATERIAL_SEMANTICS_VERSION


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


def record(**changes):
    return {"paper_id": "synthetic:sc10-source", "knowledge_origin": "Observed", "source_role": "primary",
            "method": "synthetic diffraction", "sample_id": "sample-A", "state_id": "state-A",
            "pressure_gpa": 1, "detection_conditions": "Synthetic 5–20 K interval, stated detection limit",
            "source_locator": {"page": 2}, **changes}


def material(**changes):
    return {"id": "mat:sc10-direct", "formula": "Nb", "formula_latex": None, "family": "cuprate",
            "subfamily": None, "status": "active_research", "total_papers": 1,
            "needs_review": False, "disputed": False, "records": [], "arxiv_year": None,
            "tc_max": None, "tc_max_conditions": None, "tc_ambient": None, **changes}


def test_read_projection_does_not_trust_cached_semantics_or_family_prior_columns():
    raw = material(pairing_symmetry="d-wave", is_unconventional=True, has_competing_order=False,
                   material_semantics={"version": MATERIAL_SEMANTICS_VERSION,
                                       "properties": {"pairing_symmetry": {"status": "reported", "value": "d-wave"}}})
    before = deepcopy(raw)
    public = MaterialSummary.model_validate(raw)
    assert public.pairing_symmetry is None and public.is_unconventional is None
    assert public.has_competing_order is None
    assert public.material_semantics["version"] == MATERIAL_SEMANTICS_VERSION
    assert public.material_semantics["priors"]
    assert public.property_evidence["properties"]["pairing_symmetry"]["selected"] is None
    assert raw == before


@pytest.mark.parametrize("status", ["unknown", "not_reported", "not_extracted", "not_computed", "failed", "not_applicable"])
def test_explicit_missingness_survives_public_serialization(status):
    raw = material(records=[record(pairing_symmetry_status=status, pairing_symmetry_reason="Synthetic explicit status")])
    public = MaterialSummary.model_validate(raw).model_dump()
    prop = public["material_semantics"]["properties"]["pairing_symmetry"]
    assert prop["status"] == status and prop["value"] is None
    assert public["pairing_symmetry"] is None


def test_unqualified_negative_record_is_retained_but_not_a_material_absence():
    raw = material(has_competing_order=False, records=[{
        "paper_id": "synthetic:sc10-unqualified", "has_competing_order": False,
    }])
    public = MaterialSummary.model_validate(raw)
    prop = public.material_semantics["properties"]["has_competing_order"]
    assert public.has_competing_order is None and prop["value"] is None
    assert any(item["value"] is False for item in prop["evidence"])
    assert public.property_evidence["properties"]["has_competing_order"]["selected"] is None
    assert raw["records"][0]["has_competing_order"] is False


def test_qualified_false_is_distinct_from_unknown_and_preserves_detection_context():
    raw = material(records=[record(has_competing_order=False)])
    public = MaterialSummary.model_validate(raw)
    prop = public.material_semantics["properties"]["has_competing_order"]
    assert public.has_competing_order is False and prop["status"] == "reported"
    assert prop["evidence"][0]["method"] and prop["evidence"][0]["detection_conditions"]


def test_enum_competing_order_is_reported_indicator_not_a_temperature_heuristic():
    explicit = project_material_semantics(material(records=[record(competing_order="CDW")]))
    only_temperature = project_material_semantics(material(records=[record(t_cdw_k=20)]))
    assert explicit["properties"]["has_competing_order"]["value"] is True
    assert only_temperature["properties"]["has_competing_order"]["value"] is None


def test_narrow_variant_and_bookmark_projection_do_not_lose_semantic_context():
    raw = material(records=[record(pairing_symmetry="s-wave")])
    variant = VariantSummary.model_validate(raw)
    projected = project_material_properties(raw, {"id", "formula", "tc_max", "material_semantics"}, compact=True)
    assert variant.material_semantics["properties"]["pairing_symmetry"]["value"] == "s-wave"
    assert projected["material_semantics"] == variant.material_semantics


def test_catalogue_family_audit_does_not_recommend_manufacturing_a_negative_label():
    rule = rule_by_name("family_unconv_contradiction")
    assert "not an adjudicated physical contradiction" in rule.description
    assert "Never infer false" in rule.suggested_fix
    assert "source-linked review" in rule.suggested_fix
    assert not rule.fix_query


async def seed(session, *, family=None, records=None, paper_status="published", **columns):
    suffix = uuid4().hex[:12]
    family = family or "sc10_" + suffix
    pid = "synthetic:sc10-" + suffix
    session.add(Paper(id=pid, source="arxiv", title="Synthetic SC10 source", authors=[],
                      abstract="Synthetic fixture only", status=paper_status))
    raw_records = [{**row, "paper_id": pid, "family": family} for row in records or [record()]]
    row = Material(id="mat:sc10-" + suffix, formula="Nb", formula_normalized="sc10-" + suffix,
                   family=family, records=raw_records, total_papers=1, needs_review=False,
                   **columns)
    session.add(row)
    await session.commit()
    return row, pid


@pytest.mark.asyncio
async def test_filter_count_and_pagination_use_current_semantics_not_default_false(client, db_session):
    family = "sc10_filter_" + uuid4().hex[:8]
    unknown, _ = await seed(db_session, family=family, records=[record()], has_competing_order=False)
    explicit, _ = await seed(db_session, family=family, records=[record(has_competing_order=False)], has_competing_order=None)
    positive, _ = await seed(db_session, family=family, records=[record(competing_order="CDW")], has_competing_order=False)
    for value, expected in (("false", explicit.id), ("true", positive.id)):
        response = await client.get("/v1/materials", params={"family": family, "has_competing_order": value, "limit": 1})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1 and [row["id"] for row in body["results"]] == [expected]
        assert body["results"][0]["classification_filter_policy_version"] == MATERIAL_SEMANTICS_VERSION
        assert body["results"][0]["classification_filter_scope"] == "material_reported_summary_not_joint_state"
    all_rows = await client.get("/v1/materials", params={"family": family})
    assert all_rows.json()["total"] == 3
    await db_session.refresh(unknown)
    assert unknown.has_competing_order is False  # No read-time repair of historical bytes.


@pytest.mark.asyncio
async def test_pairing_filter_rejects_stale_prior_but_accepts_source_value_missing_from_column(client, db_session):
    family = "sc10_pair_" + uuid4().hex[:8]
    prior, _ = await seed(db_session, family=family, pairing_symmetry="d-wave")
    reported, _ = await seed(db_session, family=family, records=[record(pairing_symmetry="d-wave")], pairing_symmetry=None)
    response = await client.get("/v1/materials", params={"family": family, "pairing_symmetry": "d-wave"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["results"][0]["id"] == reported.id
    await db_session.refresh(prior)
    assert prior.pairing_symmetry == "d-wave"


@pytest.mark.asyncio
async def test_unconventional_false_filter_excludes_silence_and_unqualified_negatives(client, db_session):
    family = "sc10_unconventional_" + uuid4().hex[:8]
    await seed(db_session, family=family, records=[record()], is_unconventional=False)
    await seed(db_session, family=family, records=[{
        "is_unconventional": False, "paper_id": "synthetic:unqualified",
    }], is_unconventional=False)
    scoped, _ = await seed(db_session, family=family, records=[record(is_unconventional=False)], is_unconventional=None)
    response = await client.get("/v1/materials", params={"family": family, "is_unconventional": "false"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["results"]] == [scoped.id]


@pytest.mark.asyncio
async def test_classification_scope_is_separate_from_same_result_numeric_filter(client, db_session):
    row, _ = await seed(db_session, records=[
        record(tc_kelvin=10, pairing_symmetry="s-wave", state_id="A"),
        record(is_unconventional=True, state_id="B", pressure_gpa=10),
    ])
    response = await client.get("/v1/materials", params={
        "family": row.family, "tc_min": 8, "pressure_max": 2,
        "is_unconventional": "true", "pairing_symmetry": "s-wave",
    })
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    result = response.json()["results"][0]
    assert result["classification_filter_scope"] == "material_reported_summary_not_joint_state"
    assert [item["record_index"] for item in result["matching_results"]] == [0]
    evidence = result["material_semantics"]["properties"]["is_unconventional"]["evidence"]
    assert any(item["value"] is True and item["state"]["state_id"] == "B" for item in evidence)


@pytest.mark.asyncio
async def test_live_source_hold_cannot_be_overridden_by_stored_semantic_envelope(client, db_session):
    row, pid = await seed(db_session, records=[record(pairing_symmetry="s-wave")], pairing_symmetry="s-wave",
                          material_semantics={"version": MATERIAL_SEMANTICS_VERSION, "scientific_acceptance": True})
    first = await client.get(f"/v1/materials/{row.id}")
    assert first.status_code == 200 and first.json()["pairing_symmetry"] == "s-wave"
    paper = await db_session.get(Paper, pid)
    paper.status = "corrected"
    await db_session.commit()
    second = await client.get(f"/v1/materials/{row.id}")
    assert second.status_code == 200, second.text
    assert second.json()["pairing_symmetry"] is None
    assert second.json()["material_semantics"]["properties"]["pairing_symmetry"]["status"] != "reported"
    assert second.json()["visibility"]["scientific_acceptance"] is False


@pytest.mark.asyncio
async def test_legacy_dispute_hold_is_preserved_without_claiming_adjudication(client, db_session):
    row, _ = await seed(db_session, records=[record(tc_kelvin=10), record(tc_kelvin=30, sample_id="sample-B")],
                        disputed=True)
    detail = await client.get(f"/v1/materials/{row.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["disputed"] is True
    semantics = detail.json()["material_semantics"]
    assert semantics["conflicts"]["scientific_dispute"]["status"] != "adjudicated"
    assert semantics["support"]["independent_replication_count"] is None
    await db_session.refresh(row)
    assert row.disputed is True


@pytest.mark.asyncio
async def test_bookmark_route_contains_current_semantics(client, db_session, registered_user):
    row, _ = await seed(db_session, records=[record(pairing_symmetry="s-wave")])
    _, token = registered_user
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post("/v1/bookmarks", json={"target_type": "material", "target_id": row.id}, headers=headers)
    assert created.status_code == 201, created.text
    response = await client.get("/v1/bookmarks/materials", headers=headers)
    assert response.status_code == 200, response.text
    saved = next(item for item in response.json()["results"] if item["target_id"] == row.id)
    assert saved["material_semantics"]["version"] == MATERIAL_SEMANTICS_VERSION
    stored = (await db_session.execute(select(Material).where(Material.id == row.id))).scalar_one()
    assert stored.records[0]["pairing_symmetry"] == "s-wave"
