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
from urllib.parse import urlparse

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
    summary = _public_text(_pick_str(item, "summary"))
    source = _public_text(_pick_str(item, "source", "provenance"))
    return DiscoveryCandidate(
        formula=formula,
        name=_pick_str(item, "name", "label"),
        family=_pick_str(item, "family"),
        tc_kelvin=_pick_float(item, "tc_kelvin", "tc_k", "tc"),
        pressure_gpa=_pick_float(item, "pressure_gpa", "pressure"),
        evidence_level=_pick_str(item, "evidence_level", "evidence"),
        checker_status=_pick_str(item, "checker_status", "checker"),
        dossier_url=_public_url(_pick_str(item, "dossier_url")),
        summary=summary,
        source=source,
        updated_at=_pick_str(item, "updated_at"),
        metadata=_public_metadata(item),
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


_KNOWN_CANDIDATE_KEYS = {
    "formula", "material", "candidate", "name", "label", "family",
    "tc_kelvin", "tc_k", "tc", "pressure_gpa", "pressure",
    "evidence_level", "evidence", "checker_status", "checker",
    "dossier_url", "dossier_path", "dossier", "summary", "source",
    "provenance", "updated_at",
}

_INTERNAL_KEY_PARTS = {
    "argv",
    "checkpoint",
    "command",
    "container",
    "directory",
    "dossier_path",
    "env",
    "file",
    "filesystem",
    "host",
    "hostname",
    "job",
    "log",
    "machine",
    "operator",
    "path",
    "pid",
    "private",
    "root",
    "run",
    "scratch",
    "secret",
    "task",
    "temp",
    "tmp",
    "token",
    "trace",
    "workspace",
}

_INTERNAL_VALUE_MARKERS = (
    "/data/",
    "/home/",
    "/opt/",
    "/private/",
    "/root/",
    "/tmp/",
    "/users/",
    "/var/",
    ".openclaw",
    "checkpoint",
    "container=",
    "dossier_path",
    "file://",
    "hostname=",
    "localhost:",
    "run-root",
    "run root",
    "workspace",
)


def _public_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return None
    return value if not _looks_internal(value) else None


def _public_text(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value or _looks_internal(value):
        return None
    return value


def _public_metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in item.items():
        if key in _KNOWN_CANDIDATE_KEYS or _is_internal_key(key):
            continue
        safe = _sanitize_metadata_value(value)
        if safe is not None:
            metadata[key] = safe
    return metadata


def _sanitize_metadata_value(value: Any) -> Any | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _public_text(value)
    if isinstance(value, list):
        safe_items = [_sanitize_metadata_value(v) for v in value]
        return [v for v in safe_items if v is not None]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, nested_value in value.items():
            if _is_internal_key(str(key)):
                continue
            sanitized = _sanitize_metadata_value(nested_value)
            if sanitized is not None:
                safe[str(key)] = sanitized
        return safe
    return None


def _is_internal_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_").replace(" ", "_")
    return any(part in lowered for part in _INTERNAL_KEY_PARTS)


def _looks_internal(value: str) -> bool:
    lowered = value.lower()
    if lowered.startswith(("/", "~/", "./", "../")):
        return True
    if len(value) >= 3 and value[1:3] == ":\\":
        return True
    return any(marker in lowered for marker in _INTERNAL_VALUE_MARKERS)
