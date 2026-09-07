"""SC07 disposable-DB matrix: read eligibility is never scientific approval.

Run only through scripts/run_disposable_tests.py. Every case owns unique IDs
and a unique family, so shared-session fixtures cannot confer eligibility or
change expected pagination. These are synthetic records, not scientific data.
"""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from models.db import Bookmark, Material, Paper, get_session_factory
from services.material_visibility import MATERIAL_VISIBILITY_VERSION
from services.timeline_projection import (
    fetch_projected_timeline_points,
    refresh_timeline_projection,
)

STATES = ("catalogue", "pending", "disputed", "corrected", "retracted", "quarantined")


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    # Tests deliberately keep transactions open across HTTP reads. Teardown must
    # run on their function loop, not the suite's default session fixture loop.
    async with get_session_factory()() as session:
        yield session


async def _material(session, state="catalogue", *, family=None, parent=None, records=None):
    suffix = uuid4().hex[:12]
    material_id = f"mat:sc07-surface:{suffix}"
    family = family or f"sc07_surface_{suffix}"
    paper_id = f"arxiv:sc07-surface-{suffix}"
    secret = f"PRIVATE-SC07-{suffix}"
    paper = Paper(id=paper_id, source="arxiv", arxiv_id=f"sc07-{suffix}",
                  title="Synthetic SC07 visibility test source", authors=[], abstract="Synthetic fixture.",
                  status="published")
    session.add(paper)
    raw = records if records is not None else [{
        "tc_kelvin": 10, "year": 2026, "pressure_gpa": 1, "doping_level": 0.1,
        "paper_id": paper_id, "family": family, "knowledge_origin": "Observed",
        "measurement": "resistivity", "reviewer_email": secret,
        "reviewer_notes": {"reviewer_id": secret},
    }]
    row = Material(
        id=material_id, formula="Nb", formula_normalized=f"sc07-{suffix}",
        family=family, records=deepcopy(raw), tc_max=10, total_papers=1,
        needs_review=state == "pending", disputed=state == "disputed", retracted=state == "retracted",
        status="corrected" if state == "corrected" else "active_research",
        review_reason="provenance_quarantine_nims" if state == "quarantined" else secret,
        admin_decision={"reviewer_email": secret, "note": secret, "decision": "legacy override"},
        parent_material_id=parent, variant_count=0,
    )
    session.add(row)
    await session.commit()
    return row, paper, secret


def _assert_policy(response, state, *, eligible=None):
    assert response["version"] == MATERIAL_VISIBILITY_VERSION
    assert response["state"] == state
    assert response["scientific_acceptance"] is False
    assert response["public_catalogue_eligible"] is (state == "catalogue" if eligible is None else eligible)
    assert response["archive_available"] is (state != "quarantined")
    assert len(response["review_revision"]) == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("state", STATES)
async def test_state_matrix_list_archive_detail_and_sitemap(client, db_session, state):
    row, _, secret = await _material(db_session, state)
    default = await client.get("/v1/materials", params={"family": row.family, "limit": 200})
    assert default.status_code == 200, default.text
    assert default.headers["cache-control"] == "private, no-store"
    assert default.json()["total"] == (1 if state == "catalogue" else 0)
    assert {item["id"] for item in default.json()["results"]} == ({row.id} if state == "catalogue" else set())

    archive = await client.get("/v1/materials", params={"family": row.family, "include_pending": True})
    assert archive.status_code == 200, archive.text
    assert archive.json()["total"] == (0 if state == "quarantined" else 1)
    if state != "quarantined":
        _assert_policy(archive.json()["results"][0]["visibility"], state)
        assert secret not in archive.text

    detail = await client.get(f"/v1/materials/{row.id}")
    assert detail.headers["cache-control"] == "private, no-store"
    if state == "quarantined":
        assert detail.status_code == 404
    else:
        assert detail.status_code == 200, detail.text
        body = detail.json()
        _assert_policy(body["visibility"], state)
        assert body["needs_review"] is (state != "catalogue")
        assert bool(body["review_reason"]) is (state != "catalogue")
        assert secret not in detail.text
        assert "admin_decision" not in body
        assert "reviewer_email" not in body["records"][0]
        assert body["raw_archive"]["visibility"] == body["visibility"]
        assert body["raw_archive"]["records"][0]["raw"]["tc_kelvin"] == 10

    sitemap = await client.get("/v1/sitemap/resources", params={"kind": "material", "limit": 10000})
    assert sitemap.status_code == 200, sitemap.text
    assert sitemap.headers["cache-control"] == "private, no-store"
    assert (row.id in {item["id"] for item in sitemap.json()["results"]}) is (state == "catalogue")
    await db_session.refresh(row)
    assert row.admin_decision["note"] == secret  # Read-time privacy, not destructive erasure.
    assert row.records[0]["reviewer_email"] == secret


@pytest.mark.asyncio
@pytest.mark.parametrize("state", STATES)
async def test_parent_hold_inherits_into_child_variant_and_phase_reads(client, db_session, state):
    parent, _, _ = await _material(db_session, state)
    child, _, _ = await _material(db_session, family=parent.family, parent=parent.id)
    assert parent.variant_count == 0  # Deliberately stale aggregate counter.
    detail = await client.get(f"/v1/materials/{parent.id}")
    child_detail = await client.get(f"/v1/materials/{child.id}")
    phase = await client.get(f"/v1/materials/{parent.id}/phase_diagram")
    archive_phase = await client.get(f"/v1/materials/{parent.id}/phase_diagram", params={"include_pending": True})
    if state == "quarantined":
        assert {detail.status_code, child_detail.status_code, phase.status_code, archive_phase.status_code} == {404}
        return
    assert detail.status_code == child_detail.status_code == 200
    body = detail.json()
    assert body["variant_count"] == 1
    assert [item["id"] for item in body["variants"]] == [child.id]
    assert child_detail.json()["visibility"] == body["variants"][0]["visibility"]
    child_policy = child_detail.json()["visibility"]
    assert child_policy["public_catalogue_eligible"] is (state == "catalogue")
    assert child_policy["scientific_acceptance"] is False
    if state != "catalogue":
        assert "parent_review_hold" in child_policy["reason_codes"]
    assert phase.status_code == archive_phase.status_code == 200
    assert {point["material_id"] for point in phase.json()} == ({parent.id, child.id} if state == "catalogue" else set())
    assert {point["material_id"] for point in archive_phase.json()} == {parent.id, child.id}
    assert all(point["visibility"]["scientific_acceptance"] is False for point in archive_phase.json())


@pytest.mark.asyncio
@pytest.mark.parametrize("state", STATES)
async def test_bookmark_state_matrix_keeps_warned_archive_not_quarantine(client, db_session, registered_user, state):
    _, token = registered_user
    headers = {"Authorization": f"Bearer {token}"}
    row, _, secret = await _material(db_session, state)
    created = await client.post("/v1/bookmarks", headers=headers,
                                json={"target_type": "material", "target_id": row.id})
    assert created.status_code == (404 if state == "quarantined" else 201), created.text
    listed = await client.get("/v1/bookmarks/materials", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.headers["cache-control"] == "private, no-store"
    assert listed.json()["total"] == (0 if state == "quarantined" else 1)
    assert secret not in listed.text
    if state != "quarantined":
        _assert_policy(listed.json()["results"][0]["visibility"], state)


@pytest.mark.asyncio
async def test_existing_bookmark_does_not_keep_a_newly_quarantined_material_public(client, db_session, registered_user):
    user, token = registered_user
    headers = {"Authorization": f"Bearer {token}"}
    row, _, _ = await _material(db_session)
    created = await client.post("/v1/bookmarks", headers=headers,
                                json={"target_type": "material", "target_id": row.id})
    assert created.status_code == 201, created.text
    row.review_reason = "provenance_quarantine_nims"
    await db_session.commit()
    listed = await client.get("/v1/bookmarks/materials", headers=headers)
    assert listed.status_code == 200 and listed.json() == {"total": 0, "results": []}
    assert (await db_session.execute(select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.target_id == row.id))).scalar_one() is not None


@pytest.mark.asyncio
async def test_phase_archive_keeps_anomaly_gate_and_original_records(client, db_session):
    row, paper, _ = await _material(db_session, "pending")
    row.records = [
        {"tc_kelvin": 10, "year": 2026, "pressure_gpa": 1, "paper_id": paper.id, "knowledge_origin": "Observed"},
        {"tc_kelvin": 999, "year": 2026, "pressure_gpa": 1, "paper_id": paper.id, "knowledge_origin": "Observed"},
    ]
    original = deepcopy(row.records)
    await db_session.commit()
    default = await client.get(f"/v1/materials/{row.id}/phase_diagram")
    archive = await client.get(f"/v1/materials/{row.id}/phase_diagram", params={"include_pending": True})
    assert default.status_code == archive.status_code == 200
    assert default.json() == []
    assert [point["tc_kelvin"] for point in archive.json()] == [10]
    assert archive.json()[0]["visibility"]["public_catalogue_eligible"] is False
    await db_session.refresh(row)
    assert row.records == original


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ("fallback", "projection"))
async def test_timeline_rechecks_live_source_status_before_conditional_response(client, db_session, monkeypatch, mode):
    row, paper, _ = await _material(db_session)
    source_updated = row.updated_at
    if mode == "fallback":
        async def no_projection(*args, **kwargs):
            return None
        monkeypatch.setattr("routers.timeline.fetch_projected_timeline_points", no_projection)
    else:
        await refresh_timeline_projection(db_session)
        await db_session.commit()
        projected = await fetch_projected_timeline_points(db_session, family=row.family, include_pending=False,
                                                         experimental_only=False, only_aps=False)
        assert projected is not None
        assert [point.material_id for point in projected.points] == [row.id]
    params = {"family": row.family, "compact": True}
    initial = await client.get("/v1/timeline", params=params)
    assert initial.status_code == 200, initial.text
    assert [point["material_id"] for point in initial.json()["points"]] == [row.id]
    _assert_policy(initial.json()["points"][0]["visibility"], "catalogue")
    etag = initial.headers["etag"]
    paper.status = "retracted"
    await db_session.commit()
    await db_session.refresh(row)
    assert row.updated_at == source_updated  # Source-only governance change.
    held = await client.get("/v1/timeline", params=params, headers={"If-None-Match": etag})
    assert held.status_code == 200, held.text
    assert held.json()["points"] == []
    assert held.headers["etag"] != etag
    assert held.headers["cache-control"] == "private, no-store"
    archived = await client.get("/v1/timeline", params={**params, "include_pending": True})
    assert archived.status_code == 200, archived.text
    assert len(archived.json()["points"]) == 1
    _assert_policy(archived.json()["points"][0]["visibility"], "retracted")
    old_archive_etag = archived.headers["etag"]
    paper.status = "corrected"
    await db_session.commit()
    corrected = await client.get("/v1/timeline", params={**params, "include_pending": True}, headers={"If-None-Match": old_archive_etag})
    assert corrected.status_code == 200, corrected.text
    assert corrected.headers["etag"] != old_archive_etag
    _assert_policy(corrected.json()["points"][0]["visibility"], "corrected")
