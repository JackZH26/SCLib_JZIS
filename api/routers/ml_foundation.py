"""Read-only endpoints for auditable SCLib ML Foundation data.

Phase 1 deliberately exposes typed claims and immutable snapshot metadata
without changing the legacy material-detail response.  UUID keyset cursors
avoid the unstable offset pagination that is unsuitable for reproducible
training exports.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models import get_db
from models.db import (
    Material,
    MaterialClaim,
    MlDatasetSnapshot,
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
    cursor: uuid.UUID | None,
    limit: int,
) -> MaterialClaimPage:
    # Apply the same provenance quarantine as the legacy materials API. A
    # global claim query must not make hidden material rows visible through a
    # different endpoint.
    stmt = (
        select(MaterialClaim)
        .join(Material, Material.id == MaterialClaim.material_id)
        .outerjoin(Work, Work.id == MaterialClaim.work_id)
    )
    stmt = stmt.where(
        (Material.review_reason.is_(None))
        | (Material.review_reason != "provenance_quarantine_nims")
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
    if not include_retracted:
        stmt = stmt.where(
            MaterialClaim.validity_status != "retracted",
            (MaterialClaim.work_id.is_(None)) | (Work.publication_status != "retracted"),
        )
    if cursor is not None:
        stmt = stmt.where(MaterialClaim.id > cursor)

    rows = (
        (await db.execute(stmt.order_by(MaterialClaim.id.asc()).limit(limit + 1))).scalars().all()
    )
    has_more = len(rows) > limit
    visible = rows[:limit]
    return MaterialClaimPage(
        items=[MaterialClaimResponse.model_validate(row) for row in visible],
        limit=limit,
        next_cursor=visible[-1].id if has_more and visible else None,
    )


@router.get("/claims", response_model=MaterialClaimPage)
async def list_claims(
    identity: PublicIdentity,  # noqa: ARG001
    db: DatabaseSession,
    material_id: Annotated[str | None, Query()] = None,
    work_id: Annotated[uuid.UUID | None, Query()] = None,
    evidence_role: Annotated[str | None, Query()] = None,
    result_status: Annotated[str | None, Query()] = None,
    validity_status: Annotated[str | None, Query()] = None,
    include_retracted: Annotated[bool, Query()] = False,
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
        cursor=cursor,
        limit=limit,
    )


@router.get("/claims/{claim_id}", response_model=MaterialClaimResponse)
async def claim_detail(
    claim_id: uuid.UUID,
    identity: PublicIdentity,  # noqa: ARG001
    db: DatabaseSession,
) -> MaterialClaimResponse:
    claim = await db.get(MaterialClaim, claim_id)
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Claim {claim_id!s} not found")
    material = await db.get(Material, claim.material_id)
    if material is None or material.review_reason == "provenance_quarantine_nims":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Claim {claim_id!s} not found")
    return MaterialClaimResponse.model_validate(claim)


@router.get("/materials/{material_id:path}/claims", response_model=MaterialClaimPage)
async def material_claims(
    material_id: str,
    identity: PublicIdentity,  # noqa: ARG001
    db: DatabaseSession,
    include_retracted: Annotated[bool, Query()] = False,
    cursor: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> MaterialClaimPage:
    material = await db.get(Material, material_id)
    if material is None or material.review_reason == "provenance_quarantine_nims":
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
