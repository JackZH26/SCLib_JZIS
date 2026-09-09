"""Internal read-only endpoints for auditable SCLib ML Foundation data.

The legacy feature flag is an operational kill switch, never public release
approval. Authenticated, explicitly granted research operators can inspect
typed claims and snapshot metadata without changing material-detail responses.
UUID keyset cursors
avoid the unstable offset pagination that is unsuitable for reproducible
training exports.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import AwareDatetime, BeforeValidator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
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
    User,
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
from routers.auth import current_user_from_jwt
from services.material_visibility import MATERIAL_VISIBILITY_VERSION, sanitize_review_metadata
from services.material_visibility_adapter import material_view, prepare_material_views
from services.research_access import ResearchAccessDenied, require_research_operator
from services.source_lifecycle import resolve_paper_lifecycle, resolve_work_lifecycle
from services.source_lifecycle_status import lifecycle_fingerprint, lifecycle_review_required
from services.source_registry import resolve_claim_source_witnesses
from services.source_visibility import (
    linked_material_visibility,
    occurrence_visibility,
    source_visibility,
)
from services.temporal_provenance import result_temporal_provenance, utc_datetime
from services.temporal_snapshots import utc_instant


async def require_ml_foundation_public_enabled() -> None:
    """Retain the legacy kill switch without treating it as release authority."""
    if not get_settings().ml_foundation_public_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


async def require_ml_foundation_operator(
    user: Annotated[User, Depends(current_user_from_jwt)],
    db: DatabaseSession,
) -> None:
    """A live, explicit research role is required even for a site administrator."""
    try:
        await require_research_operator(db, user.id)
    except ResearchAccessDenied:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Research operator access required",
            headers={"Cache-Control": "private, no-store"},
        ) from None
    except SQLAlchemyError:
        # Admission registry failure is not evidence that access is allowed.
        # Never disclose database/driver details to the authenticated caller.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Research access registry unavailable",
            headers={"Cache-Control": "private, no-store"},
        ) from None


router = APIRouter(
    tags=["ml-foundation"],
    dependencies=[
        Depends(require_ml_foundation_public_enabled),
        Depends(require_ml_foundation_operator),
    ],
)

MAX_CLAIM_SCAN_ROWS = 5_000


def _cutoff_instant(value):
    parsed = utc_instant(value)
    if parsed is None:
        raise ValueError("cutoff requires a timezone-aware ISO 8601 instant")
    return parsed


TemporalCutoff = Annotated[AwareDatetime, BeforeValidator(_cutoff_instant)]


def claims_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


async def _resolved_witnesses(db, claim_ids):
    try:
        return await resolve_claim_source_witnesses(db, claim_ids)
    except SQLAlchemyError:
        # Registry unavailability is not evidence that there are no witnesses.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Temporal provenance registry unavailable",
                            headers={"Cache-Control": "no-store"}) from None


def _claim_response(claim, material_context, paper_status, work_status, witnesses=()):
    """Keep claim validity distinct from current material and source visibility."""
    occurrence = occurrence_visibility(
        claim.raw_record if isinstance(claim.raw_record, dict) else {}, paper_status=paper_status,
        linked_visibility=linked_material_visibility(material_context), container_paper_id=claim.paper_id,
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
    if work.get("lifecycle_review_required"):
        reasons.add("claim_work_lifecycle_review_required")
        warnings.add("source_lifecycle_review_required")
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
    elif (claim.validity_status != "accepted" or work.get("lifecycle_review_required")) and state == "catalogue":
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
    if lifecycle_review_required(paper_status) or lifecycle_review_required(work_status):
        fingerprint.update(paper_lifecycle=lifecycle_fingerprint(paper_status), work_lifecycle=lifecycle_fingerprint(work_status))
    claim_visibility["review_revision"] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    payload = {name: getattr(claim, name) for name in MaterialClaimResponse.model_fields if hasattr(claim, name)}
    temporal = result_temporal_provenance(claim_id=str(claim.id), witnesses=witnesses)
    known_at = utc_datetime(temporal["result_available_at"]) if temporal["status"] == "known_by" else None
    payload.update(visibility=material_context.visibility, claim_visibility=claim_visibility,
                   temporal_provenance=temporal, legacy_available_at=claim.available_at,
                   available_at=known_at.date() if known_at is not None else None)
    typed = MaterialClaimResponse.model_validate(payload)
    return MaterialClaimResponse.model_validate(sanitize_review_metadata(typed.model_dump(mode="json")))


def _claim_allowed(response, *, include_pending, include_retracted):
    visibility = response.claim_visibility
    if not visibility["archive_available"]:
        return False
    if visibility["state"] == "retracted" and not include_retracted:
        return False
    return visibility["public_claim_eligible"] or include_pending


def _claim_known_by(response, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    temporal = response.temporal_provenance
    known_at = utc_datetime(temporal.result_available_at)
    return (temporal.status == "known_by" and temporal.assessment_complete is True
            and temporal.availability_basis == "source_version_witness"
            and known_at is not None and known_at <= cutoff.astimezone(UTC))


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
    cutoff: datetime | None = None,
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
    scanned_rows = 0
    while len(visible) <= limit:
        query = stmt.where(MaterialClaim.id > scan_cursor) if scan_cursor is not None else stmt
        remaining = MAX_CLAIM_SCAN_ROWS - scanned_rows
        if remaining <= 0:
            # Exactly-at-budget EOF is valid. Probe only one identifier, without
            # material hydration or source resolution, to distinguish EOF from
            # an incomplete scan. Never return a misleading partial/empty page.
            probe = query.with_only_columns(MaterialClaim.id, maintain_column_froms=True)
            more = (await db.execute(probe.order_by(MaterialClaim.id.asc()).limit(1))).first()
            if more is not None:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Claim scan budget exceeded; narrow material or work filters.",
                    headers={"Cache-Control": "no-store"},
                )
            break
        fetch_size = min(batch_size, remaining)
        rows = (await db.execute(query.order_by(MaterialClaim.id.asc()).limit(fetch_size))).all()
        if not rows:
            break
        scanned_rows += len(rows)
        material_rows = {material.id: material for _, material, _, _ in rows}
        contexts = {context.id: context for context in await prepare_material_views(db, material_rows.values())}
        resolved = await _resolved_witnesses(db, [claim.id for claim, _, _, _ in rows])
        paper_lifecycle = await resolve_paper_lifecycle(db, {claim.paper_id for claim, _, _, _ in rows if claim.paper_id})
        work_lifecycle = await resolve_work_lifecycle(db, {claim.work_id for claim, _, _, _ in rows if claim.work_id})
        for claim, material, paper_status, work_status in rows:
            paper_status = paper_lifecycle.get(claim.paper_id)
            work_status = work_lifecycle.get(str(claim.work_id))
            response = _claim_response(claim, contexts[material.id], paper_status, work_status, resolved.get(str(claim.id), []))
            if (_claim_allowed(response, include_pending=include_pending, include_retracted=include_retracted)
                    and _claim_known_by(response, cutoff)):
                visible.append(response)
                if len(visible) > limit:
                    break
        scan_cursor = rows[-1][0].id
        if len(rows) < fetch_size:
            break
    has_more = len(visible) > limit
    visible = visible[:limit]
    return MaterialClaimPage(
        items=visible,
        limit=limit,
        next_cursor=visible[-1].id if has_more and visible else None,
        has_more=has_more,
        view_scope="archive" if include_pending else "catalogue",
        temporal_filter={"active": cutoff is not None, "cutoff": cutoff.astimezone(UTC) if cutoff else None},
    )


@router.get("/claims", response_model=MaterialClaimPage, dependencies=[Depends(claims_no_store)])
async def list_claims(
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
    cutoff: Annotated[TemporalCutoff | None, Query(description="Inclusive result known-by cutoff (timezone-aware instant). Live filtering, not a frozen historical snapshot.")] = None,
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
        cutoff=cutoff,
    )


@router.get("/claims/{claim_id}", response_model=MaterialClaimResponse, dependencies=[Depends(claims_no_store)])
async def claim_detail(
    claim_id: uuid.UUID,
    db: DatabaseSession,
) -> MaterialClaimResponse:
    claim = await db.get(MaterialClaim, claim_id)
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Claim {claim_id!s} not found")
    material = await db.get(Material, claim.material_id)
    context = await material_view(db, material)
    if context is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Claim {claim_id!s} not found")
    paper_status = (await resolve_paper_lifecycle(db, [claim.paper_id] if claim.paper_id else [])).get(claim.paper_id)
    work_status = (await resolve_work_lifecycle(db, [claim.work_id] if claim.work_id else [])).get(str(claim.work_id))
    resolved = await _resolved_witnesses(db, [claim.id])
    response = _claim_response(claim, context, paper_status, work_status, resolved.get(str(claim.id), []))
    if not response.claim_visibility["archive_available"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Claim {claim_id!s} not found")
    return response


@router.get("/materials/{material_id:path}/claims", response_model=MaterialClaimPage, dependencies=[Depends(claims_no_store)])
async def material_claims(
    material_id: str,
    db: DatabaseSession,
    include_retracted: Annotated[bool, Query()] = False,
    include_pending: Annotated[bool, Query()] = False,
    cursor: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    cutoff: Annotated[TemporalCutoff | None, Query(description="Inclusive result known-by cutoff (timezone-aware instant). Unknown availability is excluded.")] = None,
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
        cutoff=cutoff,
    )


@router.get("/works/{work_id}", response_model=WorkResponse)
async def work_detail(
    work_id: uuid.UUID,
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
