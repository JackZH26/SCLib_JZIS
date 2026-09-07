"""SC07 ML claims read eligibility and post-policy keyset pagination."""
from __future__ import annotations

import uuid

import pytest

from models.db import Material, MaterialClaim, Paper, SourceSnapshot, Work


async def _seed(db, *, material_changes=None, paper_status="published", work_status="active", validity="accepted", raw=None):
    suffix = uuid.uuid4().hex
    paper = Paper(id="arxiv:claim-visibility-" + suffix, source="arxiv", title="Synthetic visibility source",
                  authors=[], abstract="Synthetic source", status=paper_status)
    work = Work(id=uuid.uuid4(), canonical_title="Synthetic visibility work", publication_status=work_status)
    source = SourceSnapshot(id=uuid.uuid4(), dataset_version="sc07-synthetic-" + suffix[:8], schema_version="test")
    material = Material(id="mat:claim-visibility-" + suffix, formula="MgB2", formula_normalized="MgB2-" + suffix,
                        total_papers=1, needs_review=False, records=[], **(material_changes or {}))
    db.add_all([paper, work, source, material])
    await db.flush()
    claim = MaterialClaim(id=uuid.uuid4(), material_id=material.id, paper_id=paper.id, work_id=work.id,
                          source_snapshot_id=source.id, property_type="tc", evidence_role="primary_experimental",
                          result_status="observed", value_relation="exact", value_kelvin=39,
                          validity_status=validity, source_record_hash=uuid.uuid4().hex * 2,
                          extractor_version="synthetic-sc07", raw_record=raw or {},
                          source_locator={"section": "Results", "reviewer_email": "private@example.test",
                                          "internal_review": {"note": "private note"}})
    db.add(claim)
    await db.commit()
    return material, claim, paper, work


@pytest.mark.asyncio
async def test_claim_keeps_stored_accepted_enum_without_granting_material_or_ml_approval(client, db_session):
    material, claim, _, _ = await _seed(db_session)
    response = await client.get(f"/v1/claims/{claim.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["validity_status"] == "accepted"
    assert body["visibility"]["scientific_acceptance"] is False
    assert body["claim_visibility"]["scientific_acceptance"] is False
    assert body["claim_visibility"]["ml_training_eligibility_established"] is False
    assert body["source_locator"] == {"section": "Results"}
    assert "private@example.test" not in response.text
    assert "no-store" in response.headers["cache-control"]
    listing = await client.get(f"/v1/materials/{material.id}/claims")
    assert "no-store" in listing.headers["cache-control"]
    assert listing.json()["has_more"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["material_pending", "material_disputed", "material_corrected", "paper_corrected", "work_corrected", "claim_pending", "claim_disputed"])
async def test_held_claims_require_archive_optin_but_direct_detail_explains_hold(client, db_session, kind):
    changes = {"status": "pending"} if kind == "material_pending" else {"disputed": True} if kind == "material_disputed" else {"status": "corrected"} if kind == "material_corrected" else {}
    material, claim, _, _ = await _seed(db_session, material_changes=changes,
                                      paper_status="corrected" if kind == "paper_corrected" else "published",
                                      work_status="corrected" if kind == "work_corrected" else "active",
                                      validity="pending" if kind == "claim_pending" else "disputed" if kind == "claim_disputed" else "accepted")
    url = f"/v1/materials/{material.id}/claims"
    assert (await client.get(url)).json()["items"] == []
    archive = await client.get(url + "?include_pending=true")
    assert [item["id"] for item in archive.json()["items"]] == [str(claim.id)]
    assert archive.json()["view_scope"] == "archive"
    detail = await client.get(f"/v1/claims/{claim.id}")
    assert detail.status_code == 200
    assert not detail.json()["claim_visibility"]["public_claim_eligible"]
    assert "archive_only" in detail.json()["claim_visibility"]["warning_codes"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["paper", "work", "claim"])
async def test_retraction_needs_both_archive_and_retraction_optins(client, db_session, kind):
    material, claim, _, _ = await _seed(db_session,
                                      paper_status="retracted" if kind == "paper" else "published",
                                      work_status="retracted" if kind == "work" else "active",
                                      validity="retracted" if kind == "claim" else "accepted")
    url = f"/v1/materials/{material.id}/claims"
    for query in ("", "?include_pending=true", "?include_retracted=true"):
        assert (await client.get(url + query)).json()["items"] == []
    response = await client.get(url + "?include_pending=true&include_retracted=true")
    assert [item["id"] for item in response.json()["items"]] == [str(claim.id)]


@pytest.mark.asyncio
async def test_corrected_work_cannot_mask_material_retraction_to_bypass_retraction_optin(client, db_session):
    material, claim, _, _ = await _seed(db_session, material_changes={"retracted": True}, work_status="corrected")
    page = await client.get(f"/v1/materials/{material.id}/claims?include_pending=true")
    assert page.json()["items"] == []
    detail = await client.get(f"/v1/claims/{claim.id}")
    assert detail.json()["claim_visibility"]["state"] == "retracted"


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["material", "parent", "record"])
async def test_quarantine_cannot_escape_through_any_claim_read_path(client, db_session, where):
    changes = {"review_reason": "provenance_quarantine_other"} if where == "material" else {}
    raw = {"review_reason": "provenance_quarantine_nims"} if where == "record" else {}
    material, claim, _, _ = await _seed(db_session, material_changes=changes, raw=raw)
    if where == "parent":
        parent = Material(id=material.id + "-p", formula="X", formula_normalized="X", needs_review=False,
                          review_reason="provenance_quarantine_nims")
        db_session.add(parent)
        await db_session.flush()
        material.parent_material_id = parent.id
        await db_session.commit()
    query = "include_pending=true&include_retracted=true"
    global_page = await client.get(f"/v1/claims?material_id={material.id}&{query}")
    assert global_page.status_code == 200 and global_page.json()["items"] == []
    assert (await client.get(f"/v1/claims/{claim.id}")).status_code == 404
    material_page = await client.get(f"/v1/materials/{material.id}/claims?{query}")
    assert material_page.status_code == (200 if where == "record" else 404)
    if where == "record":
        assert material_page.json()["items"] == []


@pytest.mark.asyncio
async def test_keyset_pagination_scans_past_more_than_one_batch_of_held_claims(client, db_session):
    material, seed_claim, _, _ = await _seed(db_session, validity="pending")
    base = uuid.uuid4().int & ~((1 << 16) - 1)
    claims = []
    for index in range(105):
        claim = MaterialClaim(id=uuid.UUID(int=base + index), material_id=material.id,
                              source_snapshot_id=seed_claim.source_snapshot_id,
                              validity_status="accepted" if index in {102, 104} else "pending",
                              source_record_hash=uuid.uuid4().hex * 2, extractor_version="synthetic-sc07",
                              raw_record={})
        claims.append(claim)
    db_session.add_all(claims)
    await db_session.commit()
    first = await client.get(f"/v1/claims?material_id={material.id}&limit=1")
    assert first.status_code == 200, first.text
    page = first.json()
    assert [row["id"] for row in page["items"]] == [str(claims[102].id)]
    assert page["has_more"] and page["next_cursor"] == str(claims[102].id)
    second = await client.get(f"/v1/claims?material_id={material.id}&limit=1&cursor={page['next_cursor']}")
    assert [row["id"] for row in second.json()["items"]] == [str(claims[104].id)]
    assert second.json()["has_more"] is False and second.json()["next_cursor"] is None


@pytest.mark.asyncio
async def test_live_claim_source_change_is_not_hidden_by_material_record_membership_or_cache(client, db_session):
    material, claim, paper, _ = await _seed(db_session)
    url = f"/v1/materials/{material.id}/claims"
    assert len((await client.get(url)).json()["items"]) == 1
    before = (await client.get(f"/v1/claims/{claim.id}")).json()["claim_visibility"]["review_revision"]
    paper.status = "corrected"
    await db_session.commit()
    assert (await client.get(url)).json()["items"] == []
    detail = await client.get(f"/v1/claims/{claim.id}")
    assert detail.json()["claim_visibility"]["review_revision"] != before
    assert detail.json()["claim_visibility"]["source_status"] == "corrected"
