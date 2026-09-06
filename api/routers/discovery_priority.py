"""Read-only, opt-in RPS publication. Existing discovery/v1 contracts stay intact."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from config import get_settings
from services.http_cache import conditional_json_response
from services.priority_releases import PriorityRelease, read_release
from services.research_priority import POLICY, POLICY_HASH, canonical_json

router = APIRouter(prefix="/discovery/rps", tags=["research-priority"])
log = logging.getLogger(__name__)


def _response(request: Request, value: dict, release: PriorityRelease | None = None):
    return conditional_json_response(
        request,
        canonical_json(value),
        cache_control="public, max-age=60, must-revalidate",
        data_version_value=release.manifest_sha256 if release else POLICY_HASH,
        last_modified=release.published_at if release else None,
        cache_header="X-RPS-Validation",
        cache_status="VERIFIED" if release else "POLICY",
    )


async def _release(release_id: str) -> PriorityRelease:
    settings = get_settings()
    approved = settings.discovery_rps_approved_releases
    if not settings.discovery_rps_public_enabled or release_id not in approved:
        raise HTTPException(404, "RPS release not published")
    try:
        return await asyncio.to_thread(
            read_release,
            Path(settings.discovery_rps_release_dir),
            release_id,
            approved[release_id],
        )
    except (OSError, ValueError, KeyError):
        log.exception("Approved RPS release failed verification: %s", release_id)
        raise HTTPException(503, "RPS release unavailable: verification failed") from None


@router.get("/policy")
async def policy(request: Request):
    return _response(
        request,
        {
            "schema_version": "rps-policy/1.2",
            "policy": POLICY,
            "policy_hash": POLICY_HASH,
            "meaning": "Research priority for a specified action and campaign; not superconductivity probability.",
            "comparability": "Same campaign, budget, policy and release only; empirical calibration pending.",
        },
    )


@router.get("/releases")
async def releases(request: Request):
    settings = get_settings()
    items = []
    if settings.discovery_rps_public_enabled:
        for release_id in settings.discovery_rps_approved_releases:
            release = await _release(release_id)
            items.append(
                {
                    "id": release.id,
                    "manifest_sha256": release.manifest_sha256,
                    "campaign_id": release.campaign.id,
                    "campaign_version": release.campaign.version,
                    "objective": release.campaign.objective,
                    "published_at": release.published_at.isoformat(),
                    "evidence_cutoff": release.evidence_cutoff.isoformat(),
                    "total": len(release.assessments),
                }
            )
    items.sort(key=lambda item: (item["published_at"], item["id"]), reverse=True)
    return _response(
        request,
        {
            "schema_version": "rps-catalog/1.2",
            "items": items,
            "status": "published" if items else "not_published",
        },
    )


@router.get("/releases/{release_id}/assessments")
async def assessments(
    request: Request,
    release_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=100),
    group: Literal["all", "discovery", "mechanism", "unranked"] = "all",
):
    release = await _release(release_id)
    rows = release.rows()
    if group != "all":
        rows = [
            r
            for r in rows
            if (
                r["result"]["score_display"] is None
                if group == "unranked"
                else r["result"]["score_display"] is not None and r["result"]["rank_group"] == group
            )
        ]
    return _response(
        request,
        {
            "schema_version": "rps-page/1.2",
            "release_id": release.id,
            "manifest_sha256": release.manifest_sha256,
            "policy_hash": release.policy_hash,
            "campaign": {
                "id": release.campaign.id,
                "version": release.campaign.version,
                "objective": release.campaign.objective,
            },
            "evidence_cutoff": release.evidence_cutoff.isoformat(),
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "offset": offset,
            "group": group,
            "release_total": len(release.assessments),
            "limit": limit,
            "has_more": offset + limit < len(rows),
        },
        release,
    )


@router.get("/releases/{release_id}/assessments/{assessment_id}")
async def assessment_detail(request: Request, release_id: str, assessment_id: str):
    release = await _release(release_id)
    entry = next((e for e in release.assessments if e.assessment.id == assessment_id), None)
    if entry is None:
        raise HTTPException(404, "Assessment not found in this release")
    row = next(r for r in release.rows() if r["id"] == assessment_id)
    artifacts = {a.id: a for a in release.artifacts}
    state = artifacts[entry.assessment.state.id]
    action = artifacts[entry.assessment.action.id]
    evidence_ids = {
        ref.id
        for judged in (
            *entry.assessment.dimensions.values(),
            entry.assessment.decision_impact,
            entry.assessment.discrimination,
            entry.assessment.readiness,
            *entry.assessment.costs,
            *entry.assessment.action_requirements.prerequisites,
            *entry.assessment.action_requirements.dependencies,
            *entry.assessment.action_requirements.resources,
        )
        for ref in judged.evidence
    }
    evidence_ids.update(ref["id"] for ref in action.content.get("conversion_evidence", []))
    template_review = artifacts[entry.assessment.action_requirements.template_review.id]
    evidence_ids.update(ref["id"] for ref in template_review.content["evidence"])
    return _response(
        request,
        {
            "schema_version": "rps-detail/1.2",
            "release_id": release.id,
            "manifest_sha256": release.manifest_sha256,
            "assessment": entry.assessment.model_dump(mode="json"),
            "review": entry.review.model_dump(),
            "result": row["result"],
            "state": state.content,
            "action": action.content,
            # Only typed bibliographic/locator metadata, never source full text.
            "evidence": [
                {
                    "id": a.id,
                    "sha256": a.sha256,
                    "kind": a.kind,
                    "available_at": a.available_at.isoformat(),
                    "source": a.content,
                }
                for a in release.artifacts
                if a.kind == "evidence" and a.id in evidence_ids
            ],
        },
        release,
    )
