"""GET /discovery — reviewed SC SuperLoop candidates prepared for public display."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends

from models.search import DiscoveryResponse
from routers.deps import Identity, peek_identity

router = APIRouter(tags=["discovery"])

_DEFAULT_INTRO = [
    "This page presents exploratory superconductivity candidates exported from SC SuperLoop into SCLib.",
    "Candidates are generated with physics-informed heuristics, then filtered through prescreening, bounded DFT checks, mechanism audit, and checker review before public display.",
    "The current release uses a preview standard so that early reviewed candidates can be inspected publicly while the evidence base is still growing.",
]

_DEFAULT_FILTER_RULES = [
    {"key": "exclude_benchmarks", "label": "Benchmarks", "value": "Excluded"},
    {"key": "minimum_evidence_level", "label": "Minimum evidence", "value": "DFT-screened"},
    {"key": "required_checker_status", "label": "Checker", "value": "pass or pending (preview)"},
    {"key": "require_dossier", "label": "Dossier", "value": "Required"},
]


def _default_payload() -> dict:
    return {
        "page_title": "Discovery",
        "intro": _DEFAULT_INTRO,
        "status": "planned",
        "updated_at_utc": None,
        "source": None,
        "filter_rules": _DEFAULT_FILTER_RULES,
        "candidates": [],
    }


@router.get("/discovery", response_model=DiscoveryResponse)
async def discovery_feed(
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
) -> DiscoveryResponse:
    path_str = os.getenv(
        "SCLIB_DISCOVERY_FEED_PATH",
        "/data/sclib/discovery/discovery_feed.json",
    )
    path = Path(path_str)
    if not path.exists():
        return DiscoveryResponse.model_validate(_default_payload())

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return DiscoveryResponse.model_validate(_default_payload())

    merged = _default_payload()
    merged.update(payload if isinstance(payload, dict) else {})
    return DiscoveryResponse.model_validate(merged)
