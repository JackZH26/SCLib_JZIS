"""Public SC SuperLoop discovery feed.

The source feed is a JSON file refreshed out-of-band.  Parsing and validating
that file on every request made the original page both CPU-heavy and slow.  A
per-process snapshot now reloads only when the file signature changes.  The
legacy full-feed endpoint remains available, while the frontend uses additive
metadata, paginated-summary, and on-demand detail endpoints.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi import Path as PathParam

from services.discovery_contract import (
    DiscoveryCandidate,
    DiscoveryCandidateDetail,
    DiscoveryCandidatePage,
    DiscoveryCandidateSummary,
    DiscoveryMetadata,
    DiscoveryResponse,
)
from services.discovery_feed import (
    FeedDocument, atomic_write_document, last_good_path, read_document,
    update_failed_after, update_status_path,
)
from routers.deps import Identity, peek_identity
from services.http_cache import conditional_json_response, data_version

router = APIRouter(tags=["discovery"])
log = logging.getLogger(__name__)

_CACHE_CONTROL = "public, no-cache, must-revalidate"
_DEFAULT_FEED_PATH = "/data/sclib/discovery/discovery_feed.json"
_UNCLASSIFIED_ROLE = "unclassified"

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

FeedSignature: TypeAlias = tuple[str, int | None, int | None, int | None, tuple]


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


def _candidate_role(candidate: DiscoveryCandidate) -> str:
    return candidate.record_role or _UNCLASSIFIED_ROLE


def _candidate_summary(candidate: DiscoveryCandidate) -> DiscoveryCandidateSummary:
    return DiscoveryCandidateSummary.model_validate(
        candidate.model_dump(include=set(DiscoveryCandidateSummary.model_fields))
    )


@dataclass(frozen=True, slots=True)
class DiscoverySnapshot:
    signature: FeedSignature
    source_status: str
    feed: DiscoveryResponse
    full_json: str
    metadata: DiscoveryMetadata
    summaries: tuple[DiscoveryCandidateSummary, ...]
    summaries_by_role: dict[str, tuple[DiscoveryCandidateSummary, ...]]
    candidates_by_id: dict[str, DiscoveryCandidate]
    data_version: str
    last_modified: datetime | None
    document: FeedDocument | None


def _feed_signature(path: Path) -> FeedSignature:
    try:
        update_stat = update_status_path(path).stat()
        update_signature = (update_stat.st_mtime_ns, update_stat.st_size, update_stat.st_ino)
    except OSError:
        update_signature = ()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None, None, update_signature)
    return (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino, update_signature)


def _build_snapshot(
    path: Path,
    signature: FeedSignature,
) -> DiscoverySnapshot:
    document = read_document(path)
    try:
        failed = update_failed_after(path, document.validated_at)
    except (OSError, ValueError, TypeError, KeyError):
        failed = True
    return _project_snapshot(signature, document, "stale" if failed else "ready")


def _project_snapshot(
    signature: FeedSignature,
    document: FeedDocument | None,
    source_status: Literal["ready", "stale", "missing", "invalid"],
) -> DiscoverySnapshot:
    feed = document.feed if document else DiscoveryResponse.model_validate(_default_payload())
    full_json = feed.model_dump_json()
    version = data_version("discovery", full_json)
    last_modified = document.validated_at if document else None

    summaries = tuple(_candidate_summary(candidate) for candidate in feed.candidates)
    grouped: dict[str, list[DiscoveryCandidateSummary]] = {}
    for candidate, summary in zip(feed.candidates, summaries, strict=True):
        grouped.setdefault(_candidate_role(candidate), []).append(summary)
    summaries_by_role = {role: tuple(items) for role, items in grouped.items()}
    role_counts = dict(Counter(_candidate_role(candidate) for candidate in feed.candidates))
    metadata = DiscoveryMetadata(
        page_title=feed.page_title,
        intro=feed.intro,
        status=feed.status,
        updated_at_utc=feed.updated_at_utc,
        source=feed.source,
        filter_rules=feed.filter_rules,
        total_candidates=len(feed.candidates),
        role_counts=role_counts,
        data_version=version,
        source_status=source_status,
        last_successful_at=last_modified,
        source_error=(
            None if source_status == "ready" else
            "source_missing" if signature[1] is None else "invalid_update"
        ),
    )
    return DiscoverySnapshot(
        signature=signature,
        source_status=source_status,
        feed=feed,
        full_json=full_json,
        metadata=metadata,
        summaries=summaries,
        summaries_by_role=summaries_by_role,
        candidates_by_id={candidate.candidate_id: candidate for candidate in feed.candidates},
        data_version=version,
        last_modified=last_modified,
        document=document,
    )


class DiscoveryFeedStore:
    """Reload the validated feed once per file version and API worker."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._snapshot: DiscoverySnapshot | None = None

    async def get(self, path: Path) -> tuple[DiscoverySnapshot, str]:
        signature = await asyncio.to_thread(_feed_signature, path)
        if self._snapshot is not None and self._snapshot.signature == signature:
            return self._snapshot, "HIT"

        async with self._lock:
            if self._snapshot is not None and self._snapshot.signature == signature:
                return self._snapshot, "HIT"
            try:
                snapshot = await asyncio.to_thread(_build_snapshot, path, signature)
                # Persistence is best-effort for an API reader: production
                # deliberately mounts this directory read-only. A valid feed
                # remains usable when its recovery sidecar cannot be written.
                try:
                    await asyncio.to_thread(atomic_write_document, last_good_path(path), snapshot.document)
                except OSError:
                    log.info("Discovery feed validated; recovery sidecar is not writable")
            except (OSError, ValueError, TypeError, KeyError):
                log.warning("Discovery update unavailable; attempting last-good recovery")
                previous = self._snapshot
                document = (
                    previous.document if previous and previous.signature[0] == str(path) else None
                )
                if document is None:
                    try:
                        document = await asyncio.to_thread(read_document, last_good_path(path))
                    except (OSError, ValueError, TypeError, KeyError):
                        document = None
                status = "stale" if document else "missing" if signature[1] is None else "invalid"
                snapshot = _project_snapshot(signature, document, status)
            self._snapshot = snapshot
            return snapshot, "MISS"

    def clear(self) -> None:
        """Drop the local snapshot; used by tests and controlled reloads."""
        self._snapshot = None


_store = DiscoveryFeedStore()


def _configured_path() -> Path:
    return Path(os.getenv("SCLIB_DISCOVERY_FEED_PATH", _DEFAULT_FEED_PATH))


def _http_response(
    request: Request,
    payload: str,
    *,
    snapshot: DiscoverySnapshot,
    cache_status: str,
) -> Response:
    response = conditional_json_response(
        request,
        payload,
        cache_control=_CACHE_CONTROL,
        data_version_value=snapshot.data_version,
        # The source timestamp alone cannot validate status transitions (or
        # multiple updates within one second). Use ETags for conditional reads.
        last_modified=None,
        cache_header="X-Discovery-Cache",
        cache_status=cache_status,
    )
    response.headers["X-Discovery-Source-Status"] = snapshot.source_status
    if snapshot.last_modified is not None:
        response.headers["Last-Modified"] = format_datetime(snapshot.last_modified.astimezone(UTC), usegmt=True)
    return response


def _version_fields(snapshot: DiscoverySnapshot) -> dict:
    return snapshot.metadata.model_dump(include={
        "data_version", "source_status", "last_successful_at", "source_error",
    })


def _require_version(snapshot: DiscoverySnapshot, expected: str | None, *, required: bool = False) -> None:
    if snapshot.source_status in {"missing", "invalid"}:
        raise HTTPException(503, "Discovery feed unavailable; no validated version is available", headers={"Cache-Control": "no-store"})
    if required and expected is None:
        raise HTTPException(428, "data_version is required; load Discovery metadata first", headers={"Cache-Control": "no-store"})
    if expected is not None and expected != snapshot.data_version:
        raise HTTPException(409, {
            "code": "discovery_version_conflict",
            "message": "Discovery feed changed; restart from metadata before loading more records.",
            "current_data_version": snapshot.data_version,
        }, headers={"Cache-Control": "no-store"})


async def _snapshot() -> tuple[DiscoverySnapshot, str]:
    return await _store.get(_configured_path())


async def get_discovery_feed_health() -> dict:
    """Return non-sensitive feed state for the public data-health surface."""
    snapshot, cache_status = await _snapshot()
    updated_at = snapshot.metadata.updated_at_utc
    return {
        "status": snapshot.source_status,
        "updated_at": updated_at.isoformat() if updated_at is not None else None,
        "candidate_count": snapshot.metadata.total_candidates,
        "size_bytes": snapshot.signature[2],
        "cache": cache_status,
        "data_version": snapshot.data_version,
        "last_successful_at": snapshot.metadata.last_successful_at.isoformat() if snapshot.metadata.last_successful_at else None,
        "source_error": snapshot.metadata.source_error,
    }


@router.get(
    "/discovery",
    response_model=DiscoveryResponse,
    responses={304: {"description": "Cached representation is still current"}},
)
async def discovery_feed(
    request: Request,
    schema_version: Literal["1"] = Query("1", description="Response schema version"),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001, B008
) -> Response:
    """Return the original full payload for backward compatibility."""
    snapshot, cache_status = await _snapshot()
    _require_version(snapshot, None)
    return _http_response(
        request,
        snapshot.full_json,
        snapshot=snapshot,
        cache_status=cache_status,
    )


@router.get(
    "/discovery/metadata",
    response_model=DiscoveryMetadata,
    responses={304: {"description": "Cached representation is still current"}},
)
async def discovery_metadata(
    request: Request,
    schema_version: Literal["1"] = Query("1", description="Response schema version"),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001, B008
) -> Response:
    snapshot, cache_status = await _snapshot()
    return _http_response(
        request,
        snapshot.metadata.model_dump_json(),
        snapshot=snapshot,
        cache_status=cache_status,
    )


@router.get(
    "/discovery/candidates",
    response_model=DiscoveryCandidatePage,
    responses={304: {"description": "Cached representation is still current"}},
)
async def discovery_candidates(
    request: Request,
    offset: int = Query(0, ge=0, le=1_000_000),
    limit: int = Query(24, ge=1, le=100),
    record_role: str | None = Query(None, min_length=1, max_length=64),
    schema_version: Literal["1"] = Query("1", description="Response schema version"),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001, B008
    data_version: Annotated[str | None, Query(pattern=r"^discovery-v1-[a-f0-9]{16}$")] = None,
) -> Response:
    snapshot, cache_status = await _snapshot()
    _require_version(snapshot, data_version, required=offset > 0)
    summaries = (
        snapshot.summaries_by_role.get(record_role, ())
        if record_role is not None
        else snapshot.summaries
    )
    total = len(summaries)
    page = DiscoveryCandidatePage(
        items=list(summaries[offset : offset + limit]),
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
        record_role=record_role,
        **_version_fields(snapshot),
    )
    return _http_response(
        request,
        page.model_dump_json(),
        snapshot=snapshot,
        cache_status=cache_status,
    )


@router.get(
    "/discovery/candidates/{candidate_id}",
    response_model=DiscoveryCandidateDetail,
    responses={
        304: {"description": "Cached representation is still current"},
        404: {"description": "Candidate not found"},
    },
)
async def discovery_candidate_detail(
    request: Request,
    candidate_id: str = PathParam(..., min_length=1, max_length=160),
    schema_version: Literal["1"] = Query("1", description="Response schema version"),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001, B008
    data_version: Annotated[str | None, Query(pattern=r"^discovery-v1-[a-f0-9]{16}$")] = None,
) -> Response:
    snapshot, cache_status = await _snapshot()
    _require_version(snapshot, data_version, required=True)
    candidate = snapshot.candidates_by_id.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Discovery candidate not found")
    return _http_response(
        request,
        DiscoveryCandidateDetail(**candidate.model_dump(), **_version_fields(snapshot)).model_dump_json(),
        snapshot=snapshot,
        cache_status=cache_status,
    )
