"""Discovery preview feed.

The feed is produced out-of-band by the SC SuperLoop workflow and stored as
JSON on the VPS. This API intentionally degrades to an empty preview when the
file is absent so the public page stays online during handoffs.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import get_settings

log = logging.getLogger(__name__)

router = APIRouter(tags=["discovery"])


class DiscoveryCandidate(BaseModel):
    formula: str
    name: str | None = None
    family: str | None = None
    tc_kelvin: float | None = None
    pressure_gpa: float | None = None
    evidence_level: str | None = None
    checker_status: str | None = None
    dossier_url: str | None = None
    dossier_path: str | None = None
    summary: str | None = None
    source: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscoveryStandard(BaseModel):
    mode: str = "preview"
    benchmarks_excluded: bool = True
    minimum_evidence_level: str = "E3"
    dossier_required: bool = True
    accepted_checker_statuses: list[str] = Field(default_factory=lambda: ["pass", "pending"])


class DiscoveryResponse(BaseModel):
    status: str
    updated_at: str
    candidates: list[DiscoveryCandidate]
    standard: DiscoveryStandard = Field(default_factory=DiscoveryStandard)
    message: str | None = None


@router.get("/discovery", response_model=DiscoveryResponse)
async def discovery() -> DiscoveryResponse:
    settings = get_settings()
    path = Path(settings.discovery_feed_path)
    now = datetime.now(timezone.utc).isoformat()
    if not path.exists():
        return DiscoveryResponse(
            status="planned",
            updated_at=now,
            candidates=[],
            message="Discovery preview feed is not available yet.",
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.exception("failed to read discovery feed: %s", path)
        raise HTTPException(status_code=503, detail="Discovery preview feed is invalid") from exc

    payload = raw if isinstance(raw, dict) else {"candidates": raw}
    updated_at = str(payload.get("updated_at") or payload.get("generated_at") or now)
    items = payload.get("candidates") or payload.get("materials") or payload.get("items") or []
    if not isinstance(items, list):
        raise HTTPException(status_code=503, detail="Discovery preview feed candidates must be a list")

    candidates = [_candidate_from_item(item) for item in items if _is_visible_preview_item(item)]
    return DiscoveryResponse(
        status=str(payload.get("status") or "preview"),
        updated_at=updated_at,
        candidates=candidates,
        message=payload.get("message") if isinstance(payload.get("message"), str) else None,
    )


def _candidate_from_item(item: Any) -> DiscoveryCandidate:
    if not isinstance(item, dict):
        return DiscoveryCandidate(formula=str(item))

    formula = _pick_str(item, "formula", "material", "candidate", "name", "label") or "unknown"
    metadata = {
        k: v
        for k, v in item.items()
        if k not in {
            "formula", "material", "candidate", "name", "label", "family",
            "tc_kelvin", "tc_k", "tc", "pressure_gpa", "pressure",
            "evidence_level", "evidence", "checker_status", "checker",
            "dossier_url", "dossier_path", "dossier", "summary", "source",
            "updated_at",
        }
    }
    return DiscoveryCandidate(
        formula=formula,
        name=_pick_str(item, "name", "label"),
        family=_pick_str(item, "family"),
        tc_kelvin=_pick_float(item, "tc_kelvin", "tc_k", "tc"),
        pressure_gpa=_pick_float(item, "pressure_gpa", "pressure"),
        evidence_level=_pick_str(item, "evidence_level", "evidence"),
        checker_status=_pick_str(item, "checker_status", "checker"),
        dossier_url=_pick_str(item, "dossier_url"),
        dossier_path=_pick_str(item, "dossier_path", "dossier"),
        summary=_pick_str(item, "summary"),
        source=_pick_str(item, "source"),
        updated_at=_pick_str(item, "updated_at"),
        metadata=metadata,
    )


def _is_visible_preview_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return True
    if bool(item.get("benchmark") or item.get("is_benchmark")):
        return False
    if str(item.get("kind") or item.get("type") or "").lower() == "benchmark":
        return False

    checker = _pick_str(item, "checker_status", "checker")
    if checker and checker.lower() not in {"pass", "pending"}:
        return False

    evidence = _pick_str(item, "evidence_level", "evidence")
    rank = _evidence_rank(evidence)
    if rank is not None and rank > 3:
        return False

    return True


def _evidence_rank(value: str | None) -> int | None:
    if not value:
        return None
    value = value.strip().upper()
    if len(value) >= 2 and value[0] == "E" and value[1:].isdigit():
        return int(value[1:])
    return None


def _pick_str(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return str(value)
    return None


def _pick_float(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = item.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
