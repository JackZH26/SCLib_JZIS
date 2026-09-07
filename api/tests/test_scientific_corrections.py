"""SC03 proposed revisions: run ONLY with scripts/run_disposable_tests.py.

All sources, actors and corrections below are synthetic. These tests establish
workflow/DB invariants, not the scientific validity of any proposed value.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from models.db import (
    Chunk,
    Material,
    Paper,
    ScientificCorrectionProposal,
    User,
    get_session_factory,
)
from services.anomaly_review import ANOMALY_POLICY_VERSION
from services.property_evidence import legacy_result_id

ENDPOINT = "/v1/admin/scientific-corrections"


@pytest_asyncio.fixture
async def correction_case(registered_user):
    user, jwt = registered_user
    suffix = uuid4().hex
    material_id, paper_id = f"mat:correction-{suffix}", f"paper:correction-{suffix}"
    raw = {"formula": "TEST", "tc_kelvin": "60 K", "paper_id": paper_id,
           "knowledge_origin": "Observed", "tc_type": "onset", "pressure_gpa": 0,
           "source_locator": {"table": "S1", "row": "2"}}
    async with get_session_factory()() as session:
        actor = await session.get(User, user.id)
        actor.is_reviewer = True
        session.add(Paper(id=paper_id, source="arxiv", title="Synthetic correction source",
                          authors=["Synthetic test author"], abstract="Synthetic only", status="published"))
        session.add(Material(id=material_id, formula="TEST", formula_normalized=f"correction-{suffix}",
                             family="conventional", records=[raw], tc_max=60, tc_max_experimental=60,
                             tc_ambient=60, total_papers=1, needs_review=True, review_reason="anomaly_review"))
        await session.commit()
    body = {"material_id": material_id, "source_result_id": legacy_result_id(raw, scope_id=material_id),
            "field": "tc_kelvin", "raw_value": "55 ± 2 K", "raw_unit": "K",
            "evidence_paper_id": paper_id, "evidence_locator": {"table": "S1", "row": "2"},
            "reason": "Synthetic source-backed proposal; not actual scientific approval.",
            "policy_version": ANOMALY_POLICY_VERSION}
    return {"body": body, "headers": {"Authorization": f"Bearer {jwt}"},
            "user_id": user.id, "material_id": material_id, "paper_id": paper_id, "raw": raw}


async def _post(client, case, **changes):
    return await client.post(ENDPOINT, headers=case["headers"], json={**case["body"], **changes})


async def _source_snapshot(material_id):
    async with get_session_factory()() as session:
        material = await session.get(Material, material_id)
        return deepcopy({key: getattr(material, key) for key in (
            "records", "tc_max", "tc_max_experimental", "tc_ambient", "needs_review", "review_reason",
            "anomaly_review", "anomaly_context", "admin_decision",
        )})


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "post"])
async def test_anonymous_and_nonreviewer_cannot_access_corrections(client, correction_case, method):
    case = correction_case
    args = {"json": case["body"]} if method == "post" else {"params": {"material_id": case["material_id"]}}
    assert (await getattr(client, method)(ENDPOINT, **args)).status_code == 401
    async with get_session_factory()() as session:
        actor = await session.get(User, case["user_id"])
        actor.is_reviewer = False
        actor.is_admin = False
        await session.commit()
    assert (await getattr(client, method)(ENDPOINT, headers=case["headers"], **args)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["reviewer", "admin"])
async def test_authorized_proposal_is_proposed_only_and_preserves_every_source_field(client, correction_case, role):
    case = correction_case
    async with get_session_factory()() as session:
        actor = await session.get(User, case["user_id"])
        actor.is_reviewer, actor.is_admin = role == "reviewer", role == "admin"
        await session.commit()
    before = await _source_snapshot(case["material_id"])
    response = await _post(client, case)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["revision"] == 1 and row["supersedes_id"] is None
    assert row["source_quantity"]["raw_value"] == "60 K"
    assert row["source_quantity"]["value"] == 60
    assert row["proposed_quantity"]["value"] == 55
    assert row["proposed_quantity"]["uncertainty"] == 2
    assert row["proposed_quantity"]["uncertainty_interpretation"] == "unspecified"
    assert row["disposition"] == "proposed"
    assert row["evidence_validation"] == "source_membership_only_not_content_verified"
    assert row["applied_to_source"] is False and row["scientific_acceptance"] is False
    assert await _source_snapshot(case["material_id"]) == before
    listed = await client.get(ENDPOINT, headers=case["headers"], params={"material_id": case["material_id"]})
    assert listed.status_code == 200 and [item["id"] for item in listed.json()] == [row["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["policy", "unknown_result", "raw_changed"])
async def test_stale_policy_or_result_is_a_conflict(client, correction_case, change):
    case = correction_case
    edits = {}
    if change == "policy":
        edits["policy_version"] = "anomaly-review/old"
    elif change == "unknown_result":
        edits["source_result_id"] = "legacy-result:" + "0" * 64
    else:
        async with get_session_factory()() as session:
            material = await session.get(Material, case["material_id"])
            material.records = [{**case["raw"], "tc_kelvin": "61 K"}]
            await session.commit()
    response = await _post(client, case, **edits)
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["wrong_paper", "missing_paper", "empty_locator", "unsupported_locator", "boolean_locator", "nested_locator", "oversize_locator", "unverifiable_span"])
async def test_specific_existing_source_paper_and_bounded_locator_required(client, correction_case, change):
    case = correction_case
    edits = {}
    if change == "wrong_paper":
        edits["evidence_paper_id"] = "paper:not-the-retained-source"
    elif change == "missing_paper":
        async with get_session_factory()() as session:
            await session.execute(delete(Paper).where(Paper.id == case["paper_id"]))
            await session.commit()
    else:
        edits["evidence_locator"] = {
            "empty_locator": {}, "unsupported_locator": {"private_source_text": "not a locator"},
            "boolean_locator": {"page": True}, "nested_locator": {"page": {"value": 1}},
            "oversize_locator": {"section": "x" * 201},
            "unverifiable_span": {"span_id": "synthetic-unverifiable-span"},
        }[change]
    response = await _post(client, case, **edits)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["same_paper", "other_paper", "missing"])
async def test_internal_chunk_locator_must_resolve_to_the_evidence_paper(client, correction_case, location):
    case = correction_case
    chunk_id = f"synthetic-chunk:{uuid4().hex}"
    if location != "missing":
        async with get_session_factory()() as session:
            paper_id = case["paper_id"]
            if location == "other_paper":
                paper_id = f"paper:other-{uuid4().hex}"
                session.add(Paper(id=paper_id, source="arxiv", title="Unrelated synthetic paper",
                                  authors=[], abstract="Not evidence for the selected result", status="published"))
                await session.flush()
            session.add(Chunk(id=chunk_id, paper_id=paper_id, text="Synthetic text; never returned by the correction endpoint."))
            await session.commit()
    response = await _post(client, case, evidence_locator={"chunk_id": chunk_id})
    assert response.status_code == (201 if location == "same_paper" else 422), response.text
    assert "Synthetic text; never returned" not in response.text
    if location == "same_paper":
        assert response.json()["evidence_validation"] == "source_membership_only_not_content_verified"


@pytest.mark.asyncio
async def test_unusual_but_representable_proposal_does_not_clip_or_approve_a_value(client, correction_case):
    before = await _source_snapshot(correction_case["material_id"])
    response = await _post(client, correction_case, raw_value="1000 K")
    assert response.status_code == 201, response.text
    assert response.json()["proposed_quantity"]["value"] == 1000
    assert response.json()["disposition"] == "proposed"
    assert response.json()["scientific_acceptance"] is False
    assert await _source_snapshot(correction_case["material_id"]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"field": "tc_max"}, {"field": "lambda_eph"}, {"raw_value": "NaN K"},
    {"raw_value": True}, {"raw_value": "55 eV", "raw_unit": "eV"},
    {"scientific_acceptance": True}, {"disposition": "approved"},
])
async def test_invalid_or_unreported_quantity_and_forged_approval_are_rejected(client, correction_case, changes):
    before = await _source_snapshot(correction_case["material_id"])
    response = await _post(client, correction_case, **changes)
    assert response.status_code == 422, response.text
    assert await _source_snapshot(correction_case["material_id"]) == before


@pytest.mark.asyncio
async def test_revision_chain_requires_exact_current_predecessor_and_never_rewrites_it(client, correction_case):
    case = correction_case
    first = (await _post(client, case)).json()
    assert (await _post(client, case)).status_code == 409
    second_response = await _post(client, case, supersedes_id=first["id"], raw_value="54 K")
    assert second_response.status_code == 201, second_response.text
    second = second_response.json()
    assert second["revision"] == 2 and second["supersedes_id"] == first["id"]
    assert (await _post(client, case, supersedes_id=first["id"], raw_value="53 K")).status_code == 409
    rows = (await client.get(ENDPOINT, headers=case["headers"], params={"material_id": case["material_id"]})).json()
    assert [row["revision"] for row in rows] == [2, 1]
    assert rows[1] == first


@pytest.mark.asyncio
async def test_concurrent_proposals_cannot_both_supersede_one_revision(client, correction_case):
    case = correction_case
    first_response = await _post(client, case)
    assert first_response.status_code == 201, first_response.text
    predecessor = first_response.json()["id"]
    responses = await asyncio.gather(
        _post(client, case, supersedes_id=predecessor, raw_value="54 K"),
        _post(client, case, supersedes_id=predecessor, raw_value="53 K"),
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    rows = (await client.get(ENDPOINT, headers=case["headers"], params={"material_id": case["material_id"]})).json()
    assert len(rows) == 2 and rows[0]["revision"] == 2
    assert rows[0]["supersedes_id"] == predecessor


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_database_rejects_direct_rewriting_or_deleting_revision_rows(client, correction_case, operation):
    response = await _post(client, correction_case)
    assert response.status_code == 201, response.text
    row = response.json()
    identity = UUID(row["id"])
    async with get_session_factory()() as session:
        stmt = update(ScientificCorrectionProposal).where(ScientificCorrectionProposal.id == identity).values(reason="rewritten") if operation == "update" else delete(ScientificCorrectionProposal).where(ScientificCorrectionProposal.id == identity)
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(stmt)
        await session.rollback()
        retained = await session.scalar(select(ScientificCorrectionProposal).where(ScientificCorrectionProposal.id == identity))
        assert retained is not None and retained.reason == row["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_quarantined_or_unavailable_material_is_not_a_correction_archive_escape(client, correction_case, missing):
    case = correction_case
    if missing:
        case["body"]["material_id"] = "mat:missing-correction-target"
    else:
        async with get_session_factory()() as session:
            material = await session.get(Material, case["material_id"])
            material.review_reason = "provenance_quarantine_nims"
            await session.commit()
    assert (await _post(client, case)).status_code == 404
    response = await client.get(ENDPOINT, headers=case["headers"], params={"material_id": case["body"]["material_id"]})
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("field,source,proposed", [
    ("tc_kelvin", {"tc": "60 K"}, "55 K"),
    ("lattice_a", {"lattice_params": {"a": 3.9, "unit": "angstrom"}}, "3.8 angstrom"),
])
async def test_corrections_use_same_legacy_alias_and_nested_quantity_accessor_as_anomaly_policy(client, correction_case, field, source, proposed):
    case = correction_case
    raw = {"paper_id": case["paper_id"], **source}
    async with get_session_factory()() as session:
        material = await session.get(Material, case["material_id"])
        material.records = [raw]
        await session.commit()
    response = await _post(client, case, source_result_id=legacy_result_id(raw, scope_id=case["material_id"]),
                           field=field, raw_value=proposed, raw_unit="K" if field == "tc_kelvin" else "angstrom")
    assert response.status_code == 201, response.text
    assert response.json()["source_quantity"]["status"] == "parsed"


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_decision", [False, True])
async def test_legacy_override_cannot_clear_current_anomaly_even_with_old_flag_or_decision(client, correction_case, prior_decision):
    case = correction_case
    async with get_session_factory()() as session:
        material = await session.get(Material, case["material_id"])
        material.review_reason = "legacy_non_numeric_flag"
        if prior_decision:
            material.admin_decision = {"action": "override", "note": "Old synthetic approval is not current evidence"}
            material.needs_review = False
        await session.commit()
    before = await _source_snapshot(case["material_id"])
    response = await client.post(f"/v1/admin/audit/queue/{case['material_id']}/override", headers=case["headers"],
                                 json={"note": "Legacy note-only approval must not bypass anomaly review"})
    assert response.status_code == 409, response.text
    assert await _source_snapshot(case["material_id"]) == before


@pytest.mark.asyncio
async def test_legacy_numeric_flag_without_retained_source_cannot_be_note_approved(client, correction_case):
    case = correction_case
    async with get_session_factory()() as session:
        material = await session.get(Material, case["material_id"])
        material.records = []
        material.review_reason = "tc_exceeds_family_cap"
        material.needs_review = True
        await session.commit()
    before = await _source_snapshot(case["material_id"])
    response = await client.post(f"/v1/admin/audit/queue/{case['material_id']}/override", headers=case["headers"],
                                 json={"note": "Missing source cannot become an approved correction by note"})
    assert response.status_code == 409, response.text
    assert await _source_snapshot(case["material_id"]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["override", "confirm"])
async def test_nims_quarantine_is_not_accessible_through_legacy_audit_actions(client, correction_case, action):
    case = correction_case
    async with get_session_factory()() as session:
        material = await session.get(Material, case["material_id"])
        material.review_reason = "provenance_quarantine_nims"
        await session.commit()
    before = await _source_snapshot(case["material_id"])
    response = await client.post(f"/v1/admin/audit/queue/{case['material_id']}/{action}", headers=case["headers"],
                                 json={"note": "This synthetic attempt must not touch quarantine"})
    assert response.status_code == 404, response.text
    assert await _source_snapshot(case["material_id"]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["retracted", "withdrawn", "corrected", "disputed"])
async def test_legacy_override_cannot_clear_a_changed_source_even_without_numeric_anomaly(client, correction_case, status):
    case = correction_case
    async with get_session_factory()() as session:
        material = await session.get(Material, case["material_id"])
        material.records = [{"paper_id": case["paper_id"], "tc_kelvin": 10}]
        material.tc_max = material.tc_max_experimental = material.tc_ambient = 10
        material.review_reason = "legacy_governance_hold"
        material.admin_decision = {"action": "override", "note": "Historical synthetic note"}
        (await session.get(Paper, case["paper_id"])).status = status
        await session.commit()
    before = await _source_snapshot(case["material_id"])
    response = await client.post(f"/v1/admin/audit/queue/{case['material_id']}/override", headers=case["headers"],
                                 json={"note": "A new source hold cannot be cleared by an old review note"})
    assert response.status_code == 409, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert "Current evidence or provenance" in response.json()["detail"]
    assert await _source_snapshot(case["material_id"]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["source_eligibility_review_required", "sole_source_retracted",
                                    "source_support_unavailable: current linked sources require review"])
async def test_restoring_source_status_does_not_authorize_legacy_override_of_lifecycle_hold(client, correction_case, reason):
    case = correction_case
    async with get_session_factory()() as session:
        material = await session.get(Material, case["material_id"])
        material.records = [{"paper_id": case["paper_id"], "tc_kelvin": 10}]
        material.tc_max = material.tc_max_experimental = material.tc_ambient = 10
        material.review_reason = reason
        (await session.get(Paper, case["paper_id"])).status = "published"
        await session.commit()
    before = await _source_snapshot(case["material_id"])
    response = await client.post(f"/v1/admin/audit/queue/{case['material_id']}/override", headers=case["headers"],
                                 json={"note": "Lifecycle changes still require exact revision review"})
    assert response.status_code == 409, response.text
    assert "retained source lifecycle hold" in response.json()["detail"]
    assert await _source_snapshot(case["material_id"]) == before
