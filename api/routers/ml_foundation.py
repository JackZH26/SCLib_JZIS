"""Read-only endpoints for auditable SCLib ML Foundation data.

Phase 1 deliberately exposes typed claims and immutable snapshot metadata
without changing the legacy material-detail response.  UUID keyset cursors
avoid the unstable offset pagination that is unsuitable for reproducible
training exports.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models import get_db
from models.db import (
    Material,
    MaterialClaim,
    MlDatasetSnapshot,
    Paper,
    PaperWorkMap,
    SourceSnapshot,
    Work,
)
from models.ml_foundation import (
    MaterialClaimPage,
    MaterialClaimResponse,
    MlDatasetManifestResponse,
    MlDatasetSnapshotResponse,
    SourceSnapshotResponse,
    WorkResponse,
)
from routers.deps import Identity, peek_identity
from services.material_visibility import MATERIAL_VISIBILITY_VERSION, sanitize_review_metadata
from services.material_visibility_adapter import material_view, prepare_material_views
from services.source_visibility import occurrence_visibility, source_visibility


async def require_ml_foundation_public_enabled() -> None:
    """Fail closed until the reviewed shadow dataset is approved for release."""
    if not get_settings().ml_foundation_public_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


router = APIRouter(
    tags=["ml-foundation"],
    dependencies=[Depends(require_ml_foundation_public_enabled)],
)

PublicIdentity = Annotated[Identity, Depends(peek_identity)]
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


def claims_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _claim_response(claim, material_context, paper_status, work_status):
    """Keep claim validity distinct from current material and source visibility."""
    occurrence = occurrence_visibility(
        claim.raw_record if isinstance(claim.raw_record, dict) else {}, paper_status=paper_status,
        linked_visibility=material_context.visibility,
    )
    source = source_visibility(paper_status)
    work = source_visibility(work_status)
    reasons = set(occurrence["reason_codes"])
    warnings = set(occurrence["warning_codes"])
    warnings.add("stored_claim_validity_is_not_material_or_ml_approval")
    if claim.validity_status != "accepted":
        reasons.add("claim_validity_" + claim.validity_status)
    if work["source_status"] in {"retracted", "corrected", "disputed"}:
        reasons.add("claim_work_" + work["source_status"])
    if claim.work_id and work["source_status"] == "unknown":
        warnings.add("claim_work_status_unknown")
    state = occurrence["state"]
    lifecycle_states = {state, source["source_status"], work["source_status"], claim.validity_status}
    if not occurrence["archive_available"]:
        state = "quarantined"
    elif "retracted" in lifecycle_states:
        state = "retracted"
    elif "disputed" in lifecycle_states:
        state = "disputed"
    elif "corrected" in lifecycle_states:
        state = "corrected"
    elif claim.validity_status != "accepted" and state == "catalogue":
        state = "pending"
    eligible = (occurrence["public_catalogue_eligible"] and claim.validity_status == "accepted"
                and work["reported_claim_filter_eligible"] and source["reported_claim_filter_eligible"])
    if not eligible:
        warnings.add("archive_only")
    claim_visibility = {
        "version": MATERIAL_VISIBILITY_VERSION, "state": state,
        "public_claim_eligible": eligible, "archive_available": occurrence["archive_available"],
        "scientific_acceptance": False, "ml_training_eligibility_established": False,
        "stored_validity_status": claim.validity_status,
        "source_status": source["source_status"], "work_status": work["source_status"],
        "reason_codes": sorted(reasons), "warning_codes": sorted(warnings),
    }
    fingerprint = {**claim_visibility, "material_revision": material_context.visibility["review_revision"],
                   "claim_id": str(claim.id), "claim_updated_at": str(claim.updated_at)}
    claim_visibility["review_revision"] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    payload = {name: getattr(claim, name) for name in MaterialClaimResponse.model_fields if hasattr(claim, name)}
    payload.update(visibility=material_context.visibility, claim_visibility=claim_visibility)
    typed = MaterialClaimResponse.model_validate(payload)
    return MaterialClaimResponse.model_validate(sanitize_review_metadata(typed.model_dump(mode="json")))


def _claim_allowed(response, *, include_pending, include_retracted):
    visibility = response.claim_visibility
    if not visibility["archive_available"]:
        return False
    if visibility["state"] == "retracted" and not include_retracted:
        return False
    return visibility["public_claim_eligible"] or include_pending


def _source_snapshot_response(row: SourceSnapshot) -> SourceSnapshotResponse:
    return SourceSnapshotResponse(
        id=row.id,
        dataset_version=row.dataset_version,
        site_git_sha=row.site_git_sha,
        database_watermark=row.database_watermark,
        paper_count=row.paper_count,
        material_count=row.material_count,
        chunk_count=row.chunk_count,
        schema_version=row.schema_version,
        manifest_sha256=row.manifest_sha256,
        license_manifest_sha256=row.license_manifest_sha256,
        status=row.status,
        metadata=row.snapshot_metadata,
        created_at=row.created_at,
        frozen_at=row.frozen_at,
    )


async def _claim_page(
    db: AsyncSession,
    *,
    material_id: str | None,
    work_id: uuid.UUID | None,
    evidence_role: str | None,
    result_status: str | None,
    validity_status: str | None,
    include_retracted: bool,
    include_pending: bool,
    cursor: uuid.UUID | None,
    limit: int,
) -> MaterialClaimPage:
    stmt = (
        select(MaterialClaim, Material, Paper.status, Work.publication_status)
        .join(Material, Material.id == MaterialClaim.material_id)
        .outerjoin(Paper, Paper.id == MaterialClaim.paper_id)
        .outerjoin(Work, Work.id == MaterialClaim.work_id)
    )
    if material_id is not None:
        stmt = stmt.where(MaterialClaim.material_id == material_id)
    if work_id is not None:
        stmt = stmt.where(MaterialClaim.work_id == work_id)
    if evidence_role is not None:
        stmt = stmt.where(MaterialClaim.evidence_role == evidence_role)
    if result_status is not None:
        stmt = stmt.where(MaterialClaim.result_status == result_status)
    if validity_status is not None:
        stmt = stmt.where(MaterialClaim.validity_status == validity_status)
    # Continue scanning after held rows until limit+1 *eligible* claims exist.
    # Cursor remains the last returned eligible ID, never the lookahead ID.
    visible = []
    scan_cursor = cursor
    batch_size = max(100, limit * 2)
    while len(visible) <= limit:
        query = stmt.where(MaterialClaim.id > scan_cursor) if scan_cursor is not None else stmt
        rows = (await db.execute(query.order_by(MaterialClaim.id.asc()).limit(batch_size))).all()
        if not rows:
            break
        material_rows = {material.id: material for _, material, _, _ in rows}
        contexts = {context.id: context for context in await prepare_material_views(db, material_rows.values())}
        for claim, material, paper_status, work_status in rows:
            response = _claim_response(claim, contexts[material.id], paper_status, work_status)
            if _claim_allowed(response, include_pending=include_pending, include_retracted=include_retracted):
                visible.append(response)
                if len(visible) > limit:
                    break
        scan_cursor = rows[-1][0].id
        if len(rows) < batch_size:
            break
    has_more = len(visible) > limit
    visible = visible[:limit]
    return MaterialClaimPage(
        items=visible,
        limit=limit,
        next_cursor=visible[-1].id if has_more and visible else None,
        has_more=has_more,
        view_scope="archive" if include_pending else "catalogue",
    )


@router.get("/claims", response_model=MaterialClaimPage, dependencies=[Depends(claims_no_store)])
async def list_claims(
    identity: PublicIdentity,  # noqa: ARG001
    db: DatabaseSession,
    material_id: Annotated[str | None, Query()] = None,
    work_id: Annotated[uuid.UUID | None, Query()] = None,
    evidence_role: Annotated[str | None, Query()] = None,
    result_status: Annotated[str | None, Query()] = None,
    validity_status: Annotated[str | None, Query()] = None,
    include_retracted: Annotated[bool, Query()] = False,
    include_pending: Annotated[bool, Query()] = False,
    cursor: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> MaterialClaimPage:
    return await _claim_page(
        db,
        material_id=material_id,
        work_id=work_id,
        evidence_role=evidence_role,
        result_status=result_status,
        validity_status=validity_status,
        include_retracted=include_retracted,
        include_pending=include_pending,
        cursor=cursor,
        limit=limit,
    )


@router.get("/claims/{claim_id}", response_model=MaterialClaimResponse, dependencies=[Depends(claims_no_store)])
async def claim_detail(
    claim_id: uuid.UUID,
    identity: PublicIdentity,  # noqa: ARG001
    db: DatabaseSession,
) -> MaterialClaimResponse:
    claim = await db.get(MaterialClaim, claim_id)
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Claim {claim_id!s} not found")
    material = await db.get(Material, claim.material_id)
    context = await material_view(db, material)
    if context is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Claim {claim_id!s} not found")
    paper = await db.get(Paper, claim.paper_id) if claim.paper_id else None
    work = await db.get(Work, claim.work_id) if claim.work_id else None
    response = _claim_response(claim, context, paper.status if paper else None, work.publication_status if work else None)
    if not response.claim_visibility["archive_available"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Claim {claim_id!s} not found")
    return response


@router.get("/materials/{material_id:path}/claims", response_model=MaterialClaimPage, dependencies=[Depends(claims_no_store)])
async def material_claims(
    material_id: str,
    identity: PublicIdentity,  # noqa: ARG001
    db: DatabaseSession,
    include_retracted: Annotated[bool, Query()] = False,
    include_pending: Annotated[bool, Query()] = False,
    cursor: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> MaterialClaimPage:
    material = await db.get(Material, material_id)
    if await material_view(db, material) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Material {material_id!r} not found",
        )
    return await _claim_page(
        db,
        material_id=material_id,
        work_id=None,
        evidence_role=None,
        result_status=None,
        validity_status=None,
        include_retracted=include_retracted,
        include_pending=include_pending,
        cursor=cursor,
        limit=limit,
    )


@router.get("/works/{work_id}", response_model=WorkResponse)
async def work_detail(
    work_id: uuid.UUID,
    identity: PublicIdentity,  # noqa: ARG001
    db: DatabaseSession,
) -> WorkResponse:
    work = await db.get(Work, work_id)
    if work is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Work {work_id!s} not found")
    paper_ids = (
        (
            await db.execute(
                select(PaperWorkMap.paper_id)
                .where(PaperWorkMap.work_id == work_id)
                .order_by(PaperWorkMap.paper_id.asc())
            )
        )
        .scalars()
        .all()
    )
    return WorkResponse(
        id=work.id,
        canonical_title=work.canonical_title,
        canonical_doi=work.canonical_doi,
        canonical_arxiv_id=work.canonical_arxiv_id,
        publication_status=work.publication_status,
        available_at=work.available_at,
        identity_metadata=work.identity_metadata,
        paper_ids=list(paper_ids),
        created_at=work.created_at,
        updated_at=work.updated_at,
    )


@router.get("/ml/source-snapshots", response_model=list[SourceSnapshotResponse])
async def list_source_snapshots(
    identity: PublicIdentity,  # noqa: ARG001
    db: DatabaseSession,
    include_unfrozen: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[SourceSnapshotResponse]:
    stmt = select(SourceSnapshot)
    if not include_unfrozen:
        stmt = stmt.where(SourceSnapshot.status == "frozen")
    rows = (
        (
            await db.execute(
                stmt.order_by(SourceSnapshot.created_at.desc(), SourceSnapshot.id.asc()).limit(
                    limit
                )
            )
        )
        .scalars()
        .all()
    )
    return [_source_snapshot_response(row) for row in rows]


@router.get("/ml/snapshots", response_model=list[MlDatasetSnapshotResponse])
async def list_ml_snapshots(
    identity: PublicIdentity,  # noqa: ARG001
    db: DatabaseSession,
    include_unfrozen: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[MlDatasetSnapshotResponse]:
    stmt = select(MlDatasetSnapshot)
    if not include_unfrozen:
        stmt = stmt.where(MlDatasetSnapshot.status == "frozen")
    rows = (
        (
            await db.execute(
                stmt.order_by(
                    MlDatasetSnapshot.created_at.desc(),
                    MlDatasetSnapshot.id.asc(),
                ).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [MlDatasetSnapshotResponse.model_validate(row) for row in rows]


@router.get(
    "/ml/snapshots/{snapshot_id}/manifest",
    response_model=MlDatasetManifestResponse,
)
async def ml_snapshot_manifest(
    snapshot_id: uuid.UUID,
    identity: PublicIdentity,  # noqa: ARG001
    db: DatabaseSession,
) -> MlDatasetManifestResponse:
    snapshot = await db.get(MlDatasetSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"ML dataset snapshot {snapshot_id!s} not found",
        )
    return MlDatasetManifestResponse(
        dataset_snapshot_id=snapshot.id,
        source_snapshot_id=snapshot.source_snapshot_id,
        name=snapshot.name,
        version=snapshot.version,
        status=snapshot.status,
        manifest_sha256=snapshot.manifest_sha256,
        row_count=snapshot.row_count,
        label_policy_version=snapshot.label_policy_version,
        feature_schema_version=snapshot.feature_schema_version,
        split_ruleset_version=snapshot.split_ruleset_version,
        filters=snapshot.filters,
        data_card_uri=snapshot.data_card_uri,
        created_at=snapshot.created_at,
        frozen_at=snapshot.frozen_at,
    )
