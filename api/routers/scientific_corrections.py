"""Reviewer-only proposed scientific revisions, never in-place corrections."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import Chunk, Material, Paper, ScientificCorrectionProposal, User
from routers.admin import current_reviewer_or_admin
from services.anomaly_review import ANOMALY_POLICY_VERSION, record_property_quantity
from services.material_anomalies import _raw_value
from services.property_evidence import legacy_result_id
from services.scientific_values import FIELD_UNITS, parse_scientific_value

router = APIRouter(prefix="/admin/scientific-corrections", tags=["scientific review"])
_LOCATORS = {"page", "table", "figure", "section", "row", "column", "chunk_id"}


class CorrectionProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    material_id: str = Field(min_length=1, max_length=100)
    source_result_id: str = Field(pattern=r"^legacy-result:[0-9a-f]{64}$")
    field: str
    raw_value: Any
    raw_unit: str | None = Field(None, max_length=40)
    evidence_paper_id: str = Field(min_length=1, max_length=100)
    evidence_locator: dict[str, Any]
    reason: str = Field(min_length=10, max_length=2000)
    policy_version: str = Field(min_length=1, max_length=80)
    supersedes_id: UUID | None = None

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Provide a substantive source-backed reason")
        return value

    @field_validator("field")
    @classmethod
    def raw_scientific_field(cls, value):
        if value not in FIELD_UNITS or value == "confidence":
            raise ValueError("Choose a supported raw scientific quantity, not a catalogue summary field")
        return value

    @field_validator("evidence_locator")
    @classmethod
    def bounded_locator(cls, value):
        if not value or set(value) - _LOCATORS:
            raise ValueError("A specific supported evidence locator is required; do not submit source text")
        for item in value.values():
            if isinstance(item, bool) or not (
                isinstance(item, int) and 0 <= item <= 1000000
                or isinstance(item, str) and 0 < len(item.strip()) <= 200
            ):
                raise ValueError("Locator components must be bounded nonempty strings or nonnegative integers")
        return value


class CorrectionProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    material_id: str
    source_result_id: str
    field: str
    revision: int
    supersedes_id: UUID | None
    source_quantity: dict[str, Any]
    proposed_quantity: dict[str, Any]
    evidence_paper_id: str
    evidence_locator: dict[str, Any]
    reason: str
    policy_version: str
    disposition: Literal["proposed"]
    created_at: datetime
    applied_to_source: Literal[False] = False
    scientific_acceptance: Literal[False] = False
    evidence_validation: Literal["source_membership_only_not_content_verified"] = "source_membership_only_not_content_verified"


def _quantity_snapshot(quantity):
    result = {key: quantity.get(key) for key in (
        "field", "raw_value", "raw_unit", "unit", "status", "relation", "value",
        "lower", "upper", "uncertainty", "uncertainty_interpretation", "approximate", "unit_basis", "parser_version", "errors",
    )}
    result["raw_value"] = _raw_value(result.get("raw_value"))
    result["raw_unit"] = _raw_value(result.get("raw_unit"))
    return result


@router.post("", response_model=CorrectionProposalRead, status_code=201)
async def propose_correction(
    body: CorrectionProposalInput,
    session: Annotated[AsyncSession, Depends(get_db)],
    reviewer: Annotated[User, Depends(current_reviewer_or_admin)],
):
    if body.policy_version != ANOMALY_POLICY_VERSION:
        raise HTTPException(409, "Anomaly policy changed; reload the evidence and submit against the current version")
    # Serialize proposals for the material so concurrent revisions cannot both
    # claim to supersede the same current revision.
    material = (await session.execute(select(Material).where(Material.id == body.material_id).with_for_update())).scalar_one_or_none()
    if material is None or material.review_reason == "provenance_quarantine_nims":
        raise HTTPException(404, "Material not available for this correction workflow")
    source = next((record for record in (material.records or []) if isinstance(record, dict)
                   and legacy_result_id(record, scope_id=material.id) == body.source_result_id), None)
    if source is None:
        raise HTTPException(409, "Source result changed or is no longer retained; reload before proposing a revision")
    if source.get("paper_id") != body.evidence_paper_id or await session.get(Paper, body.evidence_paper_id) is None:
        raise HTTPException(422, "Evidence must identify the retained result's existing source paper")
    chunk_id = body.evidence_locator.get("chunk_id")
    if chunk_id is not None:
        chunk_paper = (await session.execute(select(Chunk.paper_id).where(Chunk.id == str(chunk_id)))).scalar_one_or_none()
        if chunk_paper != body.evidence_paper_id:
            raise HTTPException(422, "The chunk locator must resolve to the same existing source paper")
    original = record_property_quantity(source, body.field)
    if original["status"] == "unreported":
        raise HTTPException(422, "The selected result does not report this quantity; this endpoint is not a new-result importer")
    proposed = parse_scientific_value(body.raw_value, body.field, raw_unit=body.raw_unit)
    if proposed["status"] != "parsed" or proposed["errors"]:
        raise HTTPException(422, "Proposed quantity is not a valid finite scientific representation; preserve unresolved evidence for review")
    previous = (await session.execute(select(ScientificCorrectionProposal).where(
        ScientificCorrectionProposal.material_id == material.id,
        ScientificCorrectionProposal.source_result_id == body.source_result_id,
        ScientificCorrectionProposal.field == body.field,
    ).order_by(ScientificCorrectionProposal.revision.desc()).limit(1))).scalar_one_or_none()
    if body.supersedes_id != (previous.id if previous else None):
        raise HTTPException(409, "Supersedes must identify the current proposal revision for this same result and field")
    row = ScientificCorrectionProposal(
        material_id=material.id, source_result_id=body.source_result_id, field=body.field,
        revision=previous.revision + 1 if previous else 1,
        supersedes_id=previous.id if previous else None,
        source_quantity=_quantity_snapshot(original), proposed_quantity=_quantity_snapshot(proposed),
        evidence_paper_id=body.evidence_paper_id, evidence_locator=body.evidence_locator,
        reason=body.reason, reviewer_id=reviewer.id, policy_version=ANOMALY_POLICY_VERSION,
        disposition="proposed",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.get("", response_model=list[CorrectionProposalRead])
async def list_correction_proposals(
    session: Annotated[AsyncSession, Depends(get_db)],
    _reviewer: Annotated[User, Depends(current_reviewer_or_admin)],
    material_id: str = Query(min_length=1, max_length=100),
    limit: int = Query(100, ge=1, le=200),
):
    material = await session.get(Material, material_id)
    if material is None or material.review_reason == "provenance_quarantine_nims":
        raise HTTPException(404, "Material not available for this correction workflow")
    return (await session.execute(select(ScientificCorrectionProposal).where(
        ScientificCorrectionProposal.material_id == material_id,
    ).order_by(ScientificCorrectionProposal.created_at.desc(), ScientificCorrectionProposal.id).limit(limit))).scalars().all()
