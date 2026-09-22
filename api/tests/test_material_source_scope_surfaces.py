"""SC08 synthetic current-read matrix; run only in the disposable API runner."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from models.db import HydrideTcParameter, Material, Paper, get_session_factory
from models.search import MaterialDetail, MaterialSummary, VariantSummary
from services.material_anomalies import material_review, review_context
from services.material_property_projection import project_material_properties
from services.material_source_scope import scoped_material_visibility
from services.material_visibility import visibility_for_material
from services.material_visibility_adapter import MaterialReadContext, prepare_material_views
from services.property_evidence import legacy_result_id
from services.timeline_projection import refresh_timeline_projection


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        try:
            yield session
        finally:
            await session.rollback()
            identifiers = session.info.get("scope_surface_materials", [])
            if identifiers:
                await session.execute(delete(Material).where(Material.id.in_(identifiers)))
                await session.commit()


async def seed(session, *, held=False):
    suffix = uuid4().hex[:12]
    family = f"sc08_scope_{suffix}"
    papers = []
    for tag in ("held", "good", "computed"):
        paper = Paper(id=f"scope:{tag}:{suffix}", source="arxiv", title="Synthetic scoped-source fixture",
                      authors=[], abstract="Synthetic, not scientific evidence.", status="published")
        session.add(paper)
        papers.append(paper)
    records = [
        {"paper_id": paper.id, "formula": "Nb", "family": family, "tc_kelvin": tc,
         "year": 2025, "pressure_gpa": pressure, "knowledge_origin": origin,
         "measurement": "resistivity" if origin == "Observed" else "DFT",
         "tc_conditions": conditions, "doping_level": 0.1,
         "reviewer_notes": "PRIVATE-SCOPE-FIXTURE"}
        for paper, tc, pressure, origin, conditions in zip(papers, (120, 30, 40), (9, 1, 3),
            ("Observed", "Observed", "Computed"), ("excluded onset", "eligible midpoint", "calculated transition"))
    ]
    material = Material(id=f"mat:scope:{suffix}", formula="Nb", formula_normalized=f"scope-{suffix}",
        family=family, records=deepcopy(records), tc_max=120, tc_max_experimental=120,
        tc_max_theoretical=40, tc_max_conditions="excluded onset", total_papers=3,
        arxiv_year=2020, best_credibility_tier="T1", needs_review=False, status="active_research")
    session.add(material)
    session.info.setdefault("scope_surface_materials", []).append(material.id)
    await session.commit()
    if held:
        papers[0].status = "retracted"
        await session.commit()
    return material, papers, records


def assert_scoped(body):
    visibility = body["visibility"]
    assert visibility["version"] == "material-visibility/2.0.0"
    assert visibility["public_catalogue_eligible"] is True
    assert visibility["scientific_acceptance"] is False
    scope = visibility["source_scope"]
    assert (scope["total_records"], scope["eligible_records"], scope["excluded_records"], scope["eligible_source_count"]) == (3, 2, 1, 2)
    assert scope["independent_support_count"] is None
    assert body["tc_max"] == 30
    assert body["property_evidence"]["selection_policy"] == "source-scoped-atomic-selection/1.0.0"


@pytest.mark.asyncio
async def test_mixed_source_summary_filters_archive_and_bookmark_share_scope(client, db_session, registered_user):
    material, papers, records = await seed(db_session, held=True)
    original_updated = material.updated_at
    params = {"family": material.family}
    listed = await client.get("/v1/materials", params=params)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    summary = listed.json()["results"][0]
    assert_scoped(summary)
    assert summary["tc_max_conditions"] == "eligible midpoint"
    assert summary["tc_max_experimental"] == 30 and summary["tc_max_theoretical"] == 40
    assert summary["total_papers"] == 2
    assert summary["arxiv_year"] is summary["best_credibility_tier"] is None
    assert summary["result_origin_counts"]["Observed"] == 1
    assert summary["result_origin_counts"]["Computed"] == 1
    assert (await client.get("/v1/materials", params={**params, "tc_min": 100})).json()["total"] == 0
    assert (await client.get("/v1/materials", params={**params, "min_papers": 3})).json()["total"] == 0
    matched = await client.get("/v1/materials", params={**params, "tc_min": 29, "pressure_max": 2})
    result = matched.json()["results"][0]
    assert [item["record_index"] for item in result["matching_results"]] == [1]
    expected_id = legacy_result_id(records[1], scope_id=material.id)
    assert result["matching_results"][0]["result_id"] == expected_id
    detail = await client.get(f"/v1/materials/{material.id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert_scoped(body)
    assert body["property_evidence"]["properties"]["tc_max"]["selected"]["result_id"] == expected_id
    assert body["property_evidence"]["properties"]["tc_max"]["selected"]["source"]["paper_id"] == papers[1].id
    assert [item["tc_kelvin"] for item in body["records"]] == [120, 30, 40]
    assert [item["visibility"]["public_catalogue_eligible"] for item in body["records"]] == [False, True, True]
    assert [item["record_index"] for item in body["raw_archive"]["records"]] == [0, 1, 2]
    assert body["raw_archive"]["records"][0]["visibility"]["public_catalogue_eligible"] is False
    assert "PRIVATE-SCOPE-FIXTURE" not in detail.text
    for include_pending in (False, True):
        phase = await client.get(f"/v1/materials/{material.id}/phase_diagram", params={"include_pending": include_pending})
        assert phase.status_code == 200, phase.text
        assert {point["paper_id"] for point in phase.json()} == {papers[1].id, papers[2].id}
    _, token = registered_user
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post("/v1/bookmarks", headers=headers, json={"target_type": "material", "target_id": material.id})
    assert created.status_code == 201, created.text
    bookmarked = await client.get("/v1/bookmarks/materials", headers=headers)
    assert bookmarked.status_code == 200, bookmarked.text
    item = next(item for item in bookmarked.json()["results"] if item["target_id"] == material.id)
    assert_scoped(item)
    assert item["arxiv_year"] is None
    await db_session.refresh(material)
    assert material.records == records and material.tc_max == 120 and material.updated_at == original_updated


@pytest.mark.asyncio
async def test_enrichment_source_and_stale_source_count_cannot_override_scope(client, db_session):
    material, papers, _ = await seed(db_session, held=True)
    material.total_papers = 1  # Deliberately stale: two eligible sources exist.
    for paper in papers[:2]:
        db_session.add(HydrideTcParameter(record_key=uuid4().hex, material_id=material.id,
            paper_id=paper.id, formula="Nb", formula_normalized="nb", source="arxiv",
            tc_kelvin=10, pressure_gpa=10, lambda_eph=1, mu_star=0.1, omega_log_k=100,
            year=2025, validation_flags=[], provenance={}, prompt_version="synthetic-scope-test"))
    await db_session.commit()
    listed = await client.get("/v1/materials", params={"family": material.family, "min_papers": 2})
    assert listed.status_code == 200 and listed.json()["total"] == 1
    for include_pending in (False, True):
        response = await client.get(f"/v1/materials/{material.id}/hydride_parameters",
                                    params={"include_pending": include_pending})
        assert response.status_code == 200, response.text
        assert [row["paper_id"] for row in response.json()] == [papers[1].id]
        assert response.json()[0]["visibility"]["scientific_acceptance"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["x" * 101, "x" * 501, " leading-space", "", {"paper": "invalid"}, False])
async def test_invalid_raw_source_identifier_does_not_fail_other_material_reads(client, db_session, bad_id):
    material, papers, original = await seed(db_session, held=True)
    material.records = [*original, {"paper_id": bad_id, "tc_kelvin": 250, "knowledge_origin": "Observed"}]
    await db_session.commit()
    response = await client.get("/v1/materials", params={"family": material.family})
    assert response.status_code == 200, response.text
    [current] = response.json()["results"]
    assert current["tc_max"] == 30
    assert current["visibility"]["source_scope"]["excluded_records"] == 2
    assert current["visibility"]["source_scope"]["eligible_source_count"] == 2
    detail = await client.get(f"/v1/materials/{material.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["records"][3]["visibility"]["public_catalogue_eligible"] is False
    assert detail.json()["records"][1]["paper_id"] == papers[1].id


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ("fallback", "projection"))
async def test_source_only_change_reselects_timeline_without_changing_result_ids(client, db_session, monkeypatch, mode):
    material, papers, _ = await seed(db_session)
    if mode == "fallback":
        async def fallback(*args, **kwargs):
            return None
        monkeypatch.setattr("routers.timeline.fetch_projected_timeline_points", fallback)
    else:
        await refresh_timeline_projection(db_session)
        await db_session.commit()
    params = {"family": material.family, "experimental_only": False}
    before = await client.get("/v1/timeline", params=params)
    assert before.status_code == 200, before.text
    assert len(before.json()["points"]) == 3
    ids = {point["paper_id"]: point["point_id"] for point in before.json()["points"]}
    papers[0].status = "retracted"
    await db_session.commit()
    after = await client.get("/v1/timeline", params=params, headers={"If-None-Match": before.headers["etag"]})
    assert after.status_code == 200, after.text
    assert after.headers["etag"] != before.headers["etag"]
    assert after.json()["visibility_policy_version"] == "material-visibility/2.0.0"
    assert {point["paper_id"] for point in after.json()["points"]} == {papers[1].id, papers[2].id}
    for point in after.json()["points"]:
        assert point["point_id"] == ids[point["paper_id"]]
        assert point["visibility"]["scientific_acceptance"] is False
    # Restoring a bibliographic status cannot erase its persistent review hold.
    papers[0].status = "published"
    await db_session.commit()
    restored = await client.get("/v1/timeline", params=params, headers={"If-None-Match": after.headers["etag"]})
    assert restored.status_code == 200
    assert restored.headers["etag"] != after.headers["etag"]
    assert {point["paper_id"] for point in restored.json()["points"]} == {papers[1].id, papers[2].id}


@pytest.mark.asyncio
@pytest.mark.parametrize("hold", ("needs_review", "retracted", "disputed", "parent", "quarantine"))
async def test_global_and_ancestor_holds_are_not_cleared_by_a_good_source(client, db_session, hold):
    material, _, _ = await seed(db_session, held=True)
    if hold == "parent":
        parent, _, _ = await seed(db_session)
        parent.needs_review = True
        material.parent_material_id = parent.id
    elif hold == "quarantine":
        material.review_reason = "provenance_quarantine_scoped_fixture"
    else:
        setattr(material, hold, True)
    await db_session.commit()
    response = await client.get("/v1/materials", params={"family": material.family})
    assert response.status_code == 200 and response.json()["total"] == 0
    detail = await client.get(f"/v1/materials/{material.id}")
    if hold == "quarantine":
        assert detail.status_code == 404
    else:
        assert detail.status_code == 200
        assert detail.json()["visibility"]["version"] == "material-visibility/1.0.0"
        assert detail.json()["visibility"]["public_catalogue_eligible"] is False


def test_scoped_atomic_projection_is_opt_in_and_compact_paths_agree():
    records = [{"paper_id": "scope:bad", "tc_kelvin": 120, "knowledge_origin": "Observed"},
               {"paper_id": "scope:good", "tc_kelvin": 30, "knowledge_origin": "Observed"}]
    raw = {"id": "mat:scope:pure", "formula": "Nb", "formula_latex": None, "family": None,
           "subfamily": None, "arxiv_year": None, "total_papers": 2, "status": "active_research",
           "needs_review": False, "tc_max": None, "tc_ambient": None, "tc_max_conditions": None,
           "crystal_structure": None, "records": records}
    statuses = {"scope:bad": "retracted", "scope:good": "published"}
    visibility, scope = scoped_material_visibility(raw, source_statuses=statuses)
    assert scope is not None
    context = MaterialReadContext(raw, visibility, statuses, scope)
    summary, detail, variant = (model.model_validate(context) for model in (MaterialSummary, MaterialDetail, VariantSummary))
    narrow = project_material_properties(context, {"id", "tc_max", "tc_ambient"}, compact=True)
    assert summary.tc_max == detail.tc_max == variant.tc_max == narrow["tc_max"] == 30
    assert MaterialSummary.model_validate(raw).tc_max is None
    # A caller-supplied public DTO cannot authorize a current scoped selection.
    assert MaterialSummary.model_validate({**raw, "visibility": visibility}).tc_max is None
    assert raw["tc_max"] is None and raw["records"] == records


@pytest.mark.asyncio
@pytest.mark.parametrize("length", [500, 501, 2000])
async def test_invalid_raw_source_preserves_exact_v1_fallback_without_a_real_source_hold(client, db_session, length):
    material, _, _ = await seed(db_session)
    raw_id = "x" * length
    records = [{"paper_id": raw_id, "tc_kelvin": 10, "knowledge_origin": "Observed",
                "measurement": "resistivity"}]
    material.records = records
    await db_session.commit()
    await db_session.refresh(material)
    legacy = visibility_for_material(material,
        anomaly_review=material_review(records, scope_id=material.id, context=review_context(material), compact=True),
        source_statuses={raw_id: None})
    context = (await prepare_material_views(db_session, [material]))[0]
    assert context.source_statuses == {}  # None of these raw IDs is sent to SQL.
    assert context.source_scope is None and context.visibility == legacy
    # Preserve the frozen v1 distinction at 500 characters; missing source
    # knowledge does not excuse the explicit invalid-metadata hold above it.
    assert legacy["public_catalogue_eligible"] is (length <= 500)
    assert ("source_metadata_invalid" in legacy["reason_codes"]) is (length > 500)
    listed = await client.get("/v1/materials", params={"family": material.family})
    assert listed.status_code == 200 and listed.json()["total"] == int(length <= 500)
    detail = await client.get(f"/v1/materials/{material.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["visibility"] == legacy
    assert detail.json()["records"][0]["paper_id"] == raw_id
    await db_session.refresh(material)
    assert material.records == records


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix,suffix", [(" ", ""), ("", "\t"), ("", "\nlegacy")])
@pytest.mark.parametrize("good_sibling", [False, True])
async def test_legacy_noncanonical_sql_id_cannot_lose_its_negative_lifecycle(client, db_session, prefix, suffix, good_sibling):
    material, papers, original = await seed(db_session)
    legacy_id = f"{prefix}legacy:{uuid4().hex[:12]}{suffix}"
    paper = Paper(id=legacy_id, source="arxiv", title="Synthetic noncanonical legacy source",
                  authors=[], abstract="Synthetic fixture, not scientific evidence.", status="published")
    db_session.add(paper)
    records = [{"paper_id": legacy_id, "tc_kelvin": 10, "knowledge_origin": "Observed",
                "measurement": "resistivity"}]
    if good_sibling:
        records.append(original[1])
    material.records = records
    await db_session.commit()
    await db_session.refresh(material)
    for state in ("retracted", "published"):
        # A real SQL-compatible legacy ID retains its negative ledger even
        # after bibliographic reactivation; it is never trimmed/renamed.
        paper.status = state
        await db_session.commit()
        context = (await prepare_material_views(db_session, [material]))[0]
        assert legacy_id not in context.source_statuses  # Strict v2 identities only.
        assert context.source_scope is None
        assert context.visibility["version"] == "material-visibility/1.0.0"
        assert context.visibility["public_catalogue_eligible"] is False
        assert "source_lifecycle_review_required" in context.visibility["reason_codes"]
        listed = await client.get("/v1/materials", params={"family": material.family})
        assert listed.status_code == 200 and listed.json()["total"] == 0
        detail = await client.get(f"/v1/materials/{material.id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["visibility"]["public_catalogue_eligible"] is False
        assert detail.json()["records"][0]["paper_id"] == legacy_id
    await db_session.refresh(material)
    await db_session.refresh(papers[1])
    assert material.records == records and papers[1].status == "published"
