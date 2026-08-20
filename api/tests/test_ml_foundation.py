"""HTTP contract for the additive ML Foundation read path."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from config import get_settings
from models.db import (
    ClaimQC,
    Material,
    MaterialClaim,
    MlDatasetSnapshot,
    Paper,
    PaperWorkMap,
    SourceSnapshot,
    User,
    Work,
    get_session_factory,
)


@pytest.mark.asyncio
async def test_ml_foundation_routes_fail_closed_by_default(client, monkeypatch) -> None:
    monkeypatch.setenv("ML_FOUNDATION_PUBLIC_ENABLED", "false")
    get_settings.cache_clear()
    try:
        response = await client.get("/v1/claims")
        assert response.status_code == 404
    finally:
        monkeypatch.setenv("ML_FOUNDATION_PUBLIC_ENABLED", "true")
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_claim_work_and_snapshot_endpoints_preserve_lineage(client) -> None:
    now = datetime.now(UTC)
    material_id = f"mat:ml-foundation-{uuid.uuid4().hex[:8]}"
    quarantined_material_id = f"mat:quarantine-{uuid.uuid4().hex[:8]}"
    paper_id = f"arxiv:mlf-{uuid.uuid4().hex[:8]}"
    work_id = uuid.uuid4()
    retracted_work_id = uuid.uuid4()
    source_snapshot_id = uuid.uuid4()
    claim_id = uuid.uuid4()
    retracted_work_claim_id = uuid.uuid4()
    quarantined_claim_id = uuid.uuid4()
    dataset_snapshot_id = uuid.uuid4()

    factory = get_session_factory()
    async with factory() as session:
        session.add(
            SourceSnapshot(
                id=source_snapshot_id,
                dataset_version="v2026.08.20-test",
                site_git_sha="a" * 40,
                database_watermark=now,
                paper_count=1,
                material_count=1,
                chunk_count=0,
                schema_version="ml-foundation-v1",
                manifest_sha256="b" * 64,
                license_manifest_sha256="c" * 64,
                status="frozen",
                snapshot_metadata={"purpose": "test"},
                frozen_at=now,
            )
        )
        session.add(
            Work(
                id=work_id,
                canonical_title="A lineage-aware superconductivity claim",
                canonical_arxiv_id=paper_id.removeprefix("arxiv:"),
                publication_status="active",
                available_at=date(2026, 8, 20),
                identity_metadata={"match": "exact_arxiv"},
            )
        )
        session.add(
            Work(
                id=retracted_work_id,
                canonical_title="A retracted version cluster",
                publication_status="retracted",
                available_at=date(2026, 8, 19),
            )
        )
        session.add(
            Paper(
                id=paper_id,
                source="arxiv",
                arxiv_id=paper_id.removeprefix("arxiv:"),
                title="A lineage-aware superconductivity claim",
                authors=["A. Researcher"],
                abstract="A typed test claim.",
                status="published",
            )
        )
        session.add(
            Material(
                id=material_id,
                formula="MgB2",
                formula_normalized="mgb2",
                total_papers=1,
                needs_review=False,
                composition_status="exact",
                composition_data={"formula_reduced": "MgB2"},
                records=[],
            )
        )
        session.add(
            Material(
                id=quarantined_material_id,
                formula="LegacyQuarantine",
                formula_normalized="legacyquarantine",
                total_papers=1,
                needs_review=True,
                review_reason="provenance_quarantine_nims",
                records=[],
            )
        )
        await session.flush()
        session.add(
            PaperWorkMap(
                paper_id=paper_id,
                work_id=work_id,
                relation_type="canonical_version",
                match_method="exact_arxiv",
                match_score=1.0,
                review_status="accepted",
            )
        )
        session.add(
            MaterialClaim(
                id=claim_id,
                material_id=material_id,
                paper_id=paper_id,
                work_id=work_id,
                source_snapshot_id=source_snapshot_id,
                property_type="tc",
                evidence_role="primary_experimental",
                result_status="observed",
                value_relation="exact",
                value_kelvin=39.0,
                tc_definition="onset",
                pressure_state="explicit_ambient",
                pressure_gpa=0.0,
                measurement_method="resistivity",
                source_kind="prose",
                source_locator={
                    "section": "Results",
                    "evidence_text": "licensed source excerpt must remain private",
                    "reference": {"evidence_text": "nested source excerpt must remain private"},
                },
                extraction_confidence=0.99,
                relation_confidence=0.98,
                validity_status="accepted",
                raw_record={"tc_kelvin": 39.0},
                extraction_metadata={"test": True},
                source_record_hash="d" * 64,
                semantic_fingerprint="e" * 64,
                available_at=date(2026, 8, 20),
                extractor_version="test-v1",
            )
        )
        session.add(
            MaterialClaim(
                id=retracted_work_claim_id,
                material_id=material_id,
                work_id=retracted_work_id,
                source_snapshot_id=source_snapshot_id,
                property_type="tc",
                evidence_role="cited",
                result_status="observed",
                value_relation="exact",
                value_kelvin=999.0,
                tc_definition="unknown",
                pressure_state="not_reported",
                source_kind="legacy",
                validity_status="pending",
                raw_record={"tc_kelvin": 999.0},
                extraction_metadata={"test": True},
                source_record_hash="8" * 64,
                extractor_version="test-v1",
            )
        )
        session.add(
            MaterialClaim(
                id=quarantined_claim_id,
                material_id=quarantined_material_id,
                source_snapshot_id=source_snapshot_id,
                property_type="tc",
                evidence_role="unknown",
                result_status="unknown",
                value_relation="unreported",
                tc_definition="unknown",
                pressure_state="not_reported",
                source_kind="legacy",
                validity_status="pending",
                raw_record={},
                extraction_metadata={"test": True},
                source_record_hash="9" * 64,
                extractor_version="test-v1",
            )
        )
        session.add(
            MlDatasetSnapshot(
                id=dataset_snapshot_id,
                source_snapshot_id=source_snapshot_id,
                name="tc-primary-experimental",
                version="v1-test",
                status="frozen",
                label_policy_version="claim-policy-v1",
                feature_schema_version="composition-v1",
                split_ruleset_version="group-time-v1",
                manifest_sha256="f" * 64,
                row_count=1,
                filters={"validity_status": "accepted"},
                data_card_uri="https://example.test/data-card",
                frozen_at=now,
            )
        )
        await session.commit()

    claims = await client.get(f"/v1/materials/{material_id}/claims")
    assert claims.status_code == 200
    assert claims.json()["items"][0]["id"] == str(claim_id)
    assert [row["id"] for row in claims.json()["items"]] == [str(claim_id)]
    assert claims.json()["items"][0]["pressure_state"] == "explicit_ambient"
    assert "raw_record" not in claims.json()["items"][0]
    assert claims.json()["items"][0]["source_locator"] == {"section": "Results"}

    global_claims = await client.get("/v1/claims")
    assert global_claims.status_code == 200
    assert {row["material_id"] for row in global_claims.json()["items"]}.isdisjoint(
        {quarantined_material_id}
    )

    pending_claims = await client.get("/v1/claims?validity_status=pending")
    assert pending_claims.status_code == 200
    assert str(retracted_work_claim_id) not in {row["id"] for row in pending_claims.json()["items"]}

    hidden_claim = await client.get(f"/v1/claims/{quarantined_claim_id}")
    assert hidden_claim.status_code == 404

    material = await client.get(f"/v1/materials/{material_id}")
    assert material.status_code == 200
    assert material.json()["composition_status"] == "exact"
    assert material.json()["composition_data"] == {"formula_reduced": "MgB2"}

    work = await client.get(f"/v1/works/{work_id}")
    assert work.status_code == 200
    assert work.json()["paper_ids"] == [paper_id]

    sources = await client.get("/v1/ml/source-snapshots")
    assert sources.status_code == 200
    source = next(row for row in sources.json() if row["id"] == str(source_snapshot_id))
    assert source["metadata"] == {"purpose": "test"}

    manifest = await client.get(f"/v1/ml/snapshots/{dataset_snapshot_id}/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["manifest_sha256"] == "f" * 64
    assert manifest.json()["row_count"] == 1


@pytest.mark.asyncio
async def test_gold_qc_survives_reviewer_account_deletion() -> None:
    """Reviewer accounts may be privacy-deleted without erasing gold lineage."""
    now = datetime.now(UTC)
    source_snapshot_id = uuid.uuid4()
    material_id = f"mat:reviewer-delete-{uuid.uuid4().hex[:8]}"
    claim_id = uuid.uuid4()
    qc_id = uuid.uuid4()
    reviewer_id = uuid.uuid4()

    factory = get_session_factory()
    async with factory() as session:
        reviewer = User(
            id=reviewer_id,
            email=f"reviewer-{uuid.uuid4().hex[:8]}@example.test",
            name="Phase 1 Reviewer",
            is_active=True,
            is_reviewer=True,
        )
        session.add(reviewer)
        session.add(
            SourceSnapshot(
                id=source_snapshot_id,
                dataset_version=f"v-reviewer-delete-{uuid.uuid4().hex[:8]}",
                paper_count=0,
                material_count=1,
                chunk_count=0,
                schema_version="ml-foundation-v1",
                manifest_sha256=uuid.uuid4().hex * 2,
                status="validated",
            )
        )
        session.add(
            Material(
                id=material_id,
                formula="Nb",
                formula_normalized="nb",
                total_papers=0,
                needs_review=False,
                records=[],
            )
        )
        await session.flush()
        session.add(
            MaterialClaim(
                id=claim_id,
                material_id=material_id,
                source_snapshot_id=source_snapshot_id,
                property_type="tc",
                evidence_role="unknown",
                result_status="unknown",
                value_relation="unreported",
                tc_definition="unknown",
                pressure_state="not_reported",
                source_kind="legacy",
                validity_status="pending",
                raw_record={},
                extraction_metadata={"test": True},
                source_record_hash=uuid.uuid4().hex * 2,
                extractor_version="test-v1",
            )
        )
        await session.flush()
        session.add(
            ClaimQC(
                id=qc_id,
                claim_id=claim_id,
                review_status="approved",
                reviewed_by=reviewer_id,
                reviewed_at=now,
                is_gold=True,
                qc_version="test-v1",
            )
        )
        await session.commit()

        await session.delete(reviewer)
        await session.commit()

        qc = await session.get(ClaimQC, qc_id)
        assert qc is not None
        assert qc.is_gold is True
        assert qc.review_status == "approved"
        assert qc.reviewed_at is not None
        assert qc.reviewed_by is None
