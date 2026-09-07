"""ML01 consumer wiring with synthetic trusted resolvers, not registry approval.

Registry persistence/review validation has its own integration suite. These
tests verify that the public consumer never substitutes raw legacy timestamps.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import SQLAlchemyError

from models.db import MaterialClaim
from routers import ml_foundation
from services.temporal_provenance import SourceAvailabilityWitness
from tests.test_ml_claim_visibility import _seed

EARLY = datetime(2020, 1, 1, tzinfo=UTC)
LATE = datetime(2021, 1, 1, tzinfo=UTC)


def witness(claim, paper, work, *, at=EARLY, verified=True):
    return SourceAvailabilityWitness(
        claim_id=str(claim.id), paper_id=paper.id, work_id=str(work.id),
        source_revision_id=str(uuid.uuid4()), source_version="v2",
        capture_id=str(uuid.uuid4()), source_version_public_at=at,
        captured_at=datetime(2026, 1, 1, tzinfo=UTC), bytes_sha256="a" * 64,
        representation="source_text", locator={"page": 2, "private_note": "SECRET-ML01", "text": "SECRET-ML01"},
        review_reference="SECRET-ML01-review-reference", version_resolved=True,
        binding_verified=verified, public_time_verified=True,
    )


def resolved(monkeypatch, values):
    calls = []
    async def resolver(_db, claim_ids):
        calls.append([str(key) for key in claim_ids])
        return {str(key): values.get(str(key), []) for key in claim_ids}
    monkeypatch.setattr(ml_foundation, "resolve_claim_source_witnesses", resolver)
    return calls


@pytest.mark.asyncio
async def test_legacy_and_forged_extraction_dates_never_become_public_known_by(client, db_session, monkeypatch):
    material, claim, _, work = await _seed(db_session, raw={
        "available_at": "1900-01-01", "result_available_at": "1900-01-01T00:00:00Z",
        "temporal_provenance": {"version": "temporal-provenance/1.0.0", "status": "known_by"},
    })
    claim.available_at = date(1900, 1, 1)
    work.available_at = date(1900, 1, 1)
    claim.extraction_metadata = {"temporal_provenance": {"status": "known_by", "result_available_at": "1900-01-01T00:00:00Z"}}
    await db_session.commit()
    resolved(monkeypatch, {})
    response = await client.get(f"/v1/claims/{claim.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available_at"] is None
    assert body["legacy_available_at"] == "1900-01-01"
    assert body["available_at_basis"] == "result_known_by_utc_date_or_null"
    assert body["temporal_provenance"]["status"] == "unknown"
    assert body["temporal_provenance"]["result_available_at"] is None
    assert body["temporal_provenance"]["scientific_acceptance"] is False
    assert "no-store" in response.headers["cache-control"]
    unfiltered = await client.get(f"/v1/materials/{material.id}/claims")
    assert [row["id"] for row in unfiltered.json()["items"]] == [str(claim.id)]
    filtered = await client.get(f"/v1/materials/{material.id}/claims", params={"cutoff": "2020-06-01T00:00:00Z"})
    assert filtered.json()["items"] == []
    assert filtered.json()["temporal_filter"]["active"] is True
    work_response = await client.get(f"/v1/works/{work.id}")
    assert work_response.json()["available_at_basis"] == "legacy_work_date_hint_not_result_availability"


@pytest.mark.asyncio
async def test_resolved_v2_known_by_time_and_public_provenance_allowlist(client, db_session, monkeypatch):
    material, claim, paper, work = await _seed(db_session)
    claim.available_at = date(1900, 1, 1)
    await db_session.commit()
    calls = resolved(monkeypatch, {str(claim.id): [witness(claim, paper, work, at=LATE)]})
    response = await client.get(f"/v1/claims/{claim.id}")
    body = response.json()
    assert body["available_at"] == "2021-01-01"
    assert body["legacy_available_at"] == "1900-01-01"
    temporal = body["temporal_provenance"]
    assert temporal["status"] == "known_by"
    assert temporal["result_available_at"] == "2021-01-01T00:00:00Z"
    assert temporal["captured_at"] == "2026-01-01T00:00:00Z"
    assert temporal["witnesses"][0]["locator"] == {"page": 2}
    assert "SECRET-ML01" not in response.text
    assert temporal["first_appearance_established"] is False
    for url, filters in (("/v1/claims", {"material_id": material.id}), (f"/v1/materials/{material.id}/claims", {})):
        before = await client.get(url, params={**filters, "cutoff": "2020-06-01T00:00:00Z"})
        assert before.json()["items"] == []
        at = await client.get(url, params={**filters, "cutoff": "2021-01-01T08:00:00+08:00"})
        assert [row["id"] for row in at.json()["items"]] == [str(claim.id)]
        assert at.json()["temporal_filter"] == {
            "version": "claim-temporal-filter/1.0.0", "scope": "live_claim_known_by_filter", "active": True,
            "cutoff": "2021-01-01T00:00:00Z", "unknown_policy": "excluded_when_cutoff_active",
            "reproducible_snapshot_established": False,
        }
    assert calls and all(len(call) <= 400 for call in calls)


@pytest.mark.asyncio
async def test_unresolved_witness_is_uncertain_and_archive_optin_does_not_bypass_cutoff(client, db_session, monkeypatch):
    material, claim, paper, work = await _seed(db_session, validity="pending")
    resolved(monkeypatch, {str(claim.id): [witness(claim, paper, work, verified=False)]})
    detail = await client.get(f"/v1/claims/{claim.id}")
    assert detail.json()["temporal_provenance"]["status"] == "uncertain"
    assert detail.json()["available_at"] is None
    response = await client.get(f"/v1/materials/{material.id}/claims", params={"include_pending": "true", "cutoff": "2022-01-01T00:00:00Z"})
    assert response.json()["items"] == []


@pytest.mark.asyncio
async def test_known_time_does_not_override_current_visibility_hold(client, db_session, monkeypatch):
    material, claim, paper, work = await _seed(db_session, paper_status="corrected")
    resolved(monkeypatch, {str(claim.id): [witness(claim, paper, work)]})
    response = await client.get(f"/v1/materials/{material.id}/claims", params={"cutoff": "2022-01-01T00:00:00Z"})
    assert response.json()["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["2020-01-01", "2020-01-01T00:00:00", "not-a-time", "1577836800", ""])
async def test_cutoff_rejects_missing_timezones_without_coercing_midnight(client, value):
    response = await client.get("/v1/claims", params={"cutoff": value})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_registry_failure_is_unavailable_not_silent_unknown_or_legacy_date(client, db_session, monkeypatch):
    material, claim, _, _ = await _seed(db_session)
    async def broken(_db, _ids):
        raise SQLAlchemyError("SECRET-ML01 database detail")
    monkeypatch.setattr(ml_foundation, "resolve_claim_source_witnesses", broken)
    for url in (f"/v1/claims/{claim.id}", f"/v1/materials/{material.id}/claims"):
        response = await client.get(url)
        assert response.status_code == 503
        assert response.json()["detail"] == "Temporal provenance registry unavailable"
        assert response.json()["error_code"] == "service_unavailable"
        assert isinstance(response.json()["request_id"], str)
        assert set(response.json()) == {"detail", "error_code", "request_id"}
        assert "no-store" in response.headers["cache-control"]
        assert "SECRET-ML01" not in response.text


@pytest.mark.asyncio
async def test_cutoff_keyset_scans_past_unknown_future_and_uncertain_rows(client, db_session, monkeypatch):
    material, seed_claim, paper, work = await _seed(db_session)
    base = uuid.uuid4().int & ~((1 << 16) - 1)
    claims = []
    for index in range(106):
        claim = MaterialClaim(id=uuid.UUID(int=base + index), material_id=material.id, paper_id=paper.id, work_id=work.id,
                              source_snapshot_id=seed_claim.source_snapshot_id, validity_status="accepted",
                              source_record_hash=uuid.uuid4().hex * 2, extractor_version="synthetic-ML01", raw_record={})
        claims.append(claim)
    db_session.add_all(claims)
    await db_session.commit()
    values = {str(claims[index].id): [witness(claims[index], paper, work)] for index in (102, 105)}
    values[str(claims[101].id)] = [witness(claims[101], paper, work, at=LATE)]
    values[str(claims[103].id)] = [witness(claims[103], paper, work, verified=False)]
    calls = resolved(monkeypatch, values)
    params = {"material_id": material.id, "limit": 1, "cutoff": "2020-06-01T00:00:00Z"}
    first = await client.get("/v1/claims", params=params)
    assert first.status_code == 200, first.text
    page = first.json()
    assert [item["id"] for item in page["items"]] == [str(claims[102].id)]
    assert page["has_more"] and page["next_cursor"] == str(claims[102].id)
    second = await client.get("/v1/claims", params={**params, "cursor": page["next_cursor"]})
    assert [item["id"] for item in second.json()["items"]] == [str(claims[105].id)]
    assert not second.json()["has_more"] and second.json()["next_cursor"] is None
    assert any(len(call) == 100 for call in calls)


async def _scan_fixture(db_session, count, *, validity="accepted"):
    material, seed, paper, work = await _seed(db_session)
    snapshot_id = seed.source_snapshot_id
    await db_session.delete(seed)
    base = uuid.uuid4().int & ~((1 << 16) - 1)
    claims = [MaterialClaim(
        id=uuid.UUID(int=base + index), material_id=material.id, paper_id=paper.id,
        work_id=work.id, source_snapshot_id=snapshot_id, validity_status=validity,
        source_record_hash=uuid.uuid4().hex * 2, extractor_version="synthetic-scan-bound",
        raw_record={},
    ) for index in range(count)]
    db_session.add_all(claims)
    await db_session.commit()
    return material, claims, paper, work


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["global", "material"])
async def test_unknown_claim_scan_budget_is_explicit_failure_not_empty_page(
    client, db_session, monkeypatch, surface,
):
    monkeypatch.setattr(ml_foundation, "MAX_CLAIM_SCAN_ROWS", 3)
    material, claims, paper, work = await _scan_fixture(db_session, 4)
    # The one eligible row beyond the cap must not be silently overlooked.
    calls = resolved(monkeypatch, {str(claims[3].id): [witness(claims[3], paper, work)]})
    url = "/v1/claims" if surface == "global" else f"/v1/materials/{material.id}/claims"
    params = {"limit": 1, "cutoff": "2020-06-01T00:00:00Z"}
    if surface == "global":
        params["material_id"] = material.id
    response = await client.get(url, params=params)
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "Claim scan budget exceeded; narrow material or work filters."
    assert "no-store" in response.headers["cache-control"]
    assert "items" not in response.json() and "has_more" not in response.json()
    assert sum(map(len, calls)) == 3
    assert str(claims[3].id) not in {key for call in calls for key in call}


@pytest.mark.asyncio
async def test_scan_cap_does_not_return_a_partial_page_with_false_has_more(
    client, db_session, monkeypatch,
):
    monkeypatch.setattr(ml_foundation, "MAX_CLAIM_SCAN_ROWS", 3)
    material, claims, paper, work = await _scan_fixture(db_session, 4)
    resolved(monkeypatch, {str(claim.id): [witness(claim, paper, work)]
                          for claim in (claims[0], claims[3])})
    response = await client.get("/v1/claims", params={
        "material_id": material.id, "limit": 1, "cutoff": "2020-06-01T00:00:00Z",
    })
    assert response.status_code == 503
    assert "items" not in response.json()


@pytest.mark.asyncio
async def test_scan_cap_applies_without_cutoff_to_visibility_held_rows(
    client, db_session, monkeypatch,
):
    monkeypatch.setattr(ml_foundation, "MAX_CLAIM_SCAN_ROWS", 3)
    material, _, _, _ = await _scan_fixture(db_session, 4, validity="pending")
    calls = resolved(monkeypatch, {})
    response = await client.get("/v1/claims", params={"material_id": material.id, "limit": 1})
    assert response.status_code == 503
    assert sum(map(len, calls)) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("known_index", [None, 2])
async def test_exact_budget_eof_uses_identifier_only_probe_and_returns_complete_page(
    client, db_session, monkeypatch, known_index,
):
    monkeypatch.setattr(ml_foundation, "MAX_CLAIM_SCAN_ROWS", 3)
    material, claims, paper, work = await _scan_fixture(db_session, 3)
    mapping = {} if known_index is None else {
        str(claims[known_index].id): [witness(claims[known_index], paper, work)],
    }
    calls = resolved(monkeypatch, mapping)
    probes = []
    session_class = type(db_session)
    execute = session_class.execute

    async def track(session, statement, *args, **kwargs):
        columns = getattr(statement, "column_descriptions", [])
        if len(columns) == 1 and columns[0].get("entity") is MaterialClaim:
            probes.append(statement)
        return await execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(session_class, "execute", track)
    response = await client.get("/v1/claims", params={
        "material_id": material.id, "limit": 1, "cutoff": "2020-06-01T00:00:00Z",
    })
    assert response.status_code == 200, response.text
    page = response.json()
    assert [item["id"] for item in page["items"]] == (
        [] if known_index is None else [str(claims[known_index].id)]
    )
    assert page["has_more"] is False and page["next_cursor"] is None
    assert sum(map(len, calls)) == 3
    assert len(probes) == 1
    assert probes[0].column_descriptions[0]["name"] == "id"
    assert probes[0]._limit_clause.value == 1


@pytest.mark.asyncio
async def test_eligible_lookahead_within_budget_preserves_normal_keyset_page(
    client, db_session, monkeypatch,
):
    monkeypatch.setattr(ml_foundation, "MAX_CLAIM_SCAN_ROWS", 3)
    material, claims, paper, work = await _scan_fixture(db_session, 4)
    calls = resolved(monkeypatch, {str(claim.id): [witness(claim, paper, work)]
                                  for claim in (claims[0], claims[2], claims[3])})
    first = await client.get("/v1/claims", params={
        "material_id": material.id, "limit": 1, "cutoff": "2020-06-01T00:00:00Z",
    })
    assert first.status_code == 200, first.text
    page = first.json()
    assert [item["id"] for item in page["items"]] == [str(claims[0].id)]
    assert page["has_more"] and page["next_cursor"] == str(claims[0].id)
    assert sum(map(len, calls)) == 3
