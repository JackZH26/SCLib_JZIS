"""Read-only, opt-in RPS publication. Existing discovery/v1 contracts stay intact."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import TypeAdapter

from config import get_settings
from services.http_cache import conditional_json_response
from services.priority_release_cache import file_signature
from services.priority_releases import PriorityRelease, read_release, read_release_projection
from services.research_priority import POLICY, POLICY_HASH, Hash, Identifier, canonical_json, digest


class _PublicationRoute(APIRoute):
    """Even negative/invalid publication reads must not retain stale approval."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request):
            try:
                response = await handler(request)
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
                raise
            except RequestValidationError as exc:
                response = await request_validation_exception_handler(request, exc)
            if response.status_code >= 400:
                response.headers["Cache-Control"] = "no-store"
            return response

        return guarded


router = APIRouter(prefix="/discovery/rps", tags=["research-priority"], route_class=_PublicationRoute)
log = logging.getLogger(__name__)
_offload_slots = threading.BoundedSemaphore(8)


async def _offload(function, *args):
    """Bound submitted worker jobs too, including jobs whose clients cancel."""
    if not _offload_slots.acquire(blocking=False):
        raise HTTPException(503, "RPS verification capacity unavailable; retry", headers={"Retry-After": "1"})

    def run():
        try:
            return function(*args)
        finally:
            _offload_slots.release()

    try:
        future = asyncio.get_running_loop().run_in_executor(None, run)
    except BaseException:
        _offload_slots.release()
        raise
    # Shield keeps a cancelled HTTP reader from cancelling a queued job before
    # its finally can return the permit. Observe late exceptions without output.
    future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return await asyncio.shield(future)


def _response(request: Request, value: dict, release: PriorityRelease | None = None):
    return conditional_json_response(
        request,
        canonical_json(value),
        cache_control="public, max-age=0, must-revalidate",
        data_version_value=release.manifest_sha256 if release else value.get("catalog_revision", POLICY_HASH),
        # Publication dates cannot validate mutable approval or a replacement
        # manifest with the same date. ETags are checked only after fresh reads.
        last_modified=None,
        cache_header="X-RPS-Validation",
        cache_status="VERIFIED" if release else "CATALOG" if "catalog_revision" in value else "POLICY",
    )


@dataclass(frozen=True)
class _Approval:
    enabled: bool
    directory: str
    releases: tuple[tuple[str, str], ...]
    bundles: tuple[tuple[str, str], ...]

    @property
    def sha256(self) -> str:
        # No internal path is disclosed, even through public config metadata.
        return digest({"enabled": self.enabled, "releases": dict(self.releases), "bundles": dict(self.bundles)})


def _approval() -> _Approval:
    settings = get_settings()
    try:
        maps = []
        for value in (settings.discovery_rps_approved_releases, settings.discovery_rps_approved_public_bundles):
            if not isinstance(value, dict) or len(value) > 128:
                raise ValueError("invalid or oversized approval map")
            validated = TypeAdapter(dict[Identifier, Hash]).validate_python(value, strict=True)
            if any(identifier in {".", ".."} for identifier in validated):
                raise ValueError("dot-segment release identifiers cannot be routed")
            maps.append(tuple(sorted(validated.items())))
        if type(settings.discovery_rps_public_enabled) is not bool:
            raise ValueError("invalid enablement")
        return _Approval(settings.discovery_rps_public_enabled, str(settings.discovery_rps_release_dir), *maps)
    except (ValueError, TypeError):
        raise HTTPException(503, "RPS publication configuration unavailable") from None


def _approved(release_id: str, approval: _Approval, *, bundle: bool = False) -> str:
    entries = dict(approval.bundles if bundle else approval.releases)
    if not approval.enabled or release_id not in entries:
        raise HTTPException(404, "RPS release not published")
    return entries[release_id]


def _stamp(path: Path) -> tuple | None:
    try:
        return file_signature(path)
    except (OSError, ValueError):
        return None


def _unchanged(witnesses: list[tuple[Path, tuple | None]]) -> bool:
    return all(_stamp(path) == signature for path, signature in witnesses)


async def _release(release_id: str) -> PriorityRelease:
    approval = _approval()
    expected = _approved(release_id, approval)
    try:
        def load():
            path = Path(approval.directory) / f"{release_id}.json"
            before = file_signature(path)
            value = read_release(Path(approval.directory), release_id, expected)
            if file_signature(path) != before:
                raise ValueError("release changed")
            return value, (path, before)

        release, witness = await _offload(load)
        if not await _offload(_unchanged, [witness]):
            raise ValueError("release changed")
    except (OSError, ValueError, KeyError):
        log.warning("Approved RPS release verification unavailable")
        raise HTTPException(503, "RPS release unavailable: verification failed") from None
    current = _approval()
    if _approved(release_id, current) != expected or current.directory != approval.directory:
        raise HTTPException(503, "RPS publication changed; retry the request")
    return release


def _catalog_entry(approval: _Approval, release_id: str, expected: str) -> tuple[dict | None, list]:
    directory = Path(approval.directory)
    path = directory / f"{release_id}.json"
    witnesses = [(path, _stamp(path))]
    try:
        item = read_release_projection(directory, release_id, expected)
    except (OSError, ValueError, KeyError):
        log.warning("RPS catalogue entry unavailable")
        return None, witnesses
    public_hash = dict(approval.bundles).get(release_id)
    item["public_bundle"] = {"status": "not_published", "sha256": None, "verifier_version": None}
    if public_hash:
        from services.priority_public_bundle import read_public_bundle

        public_path = directory / f"{release_id}.public.json"
        witnesses.append((public_path, _stamp(public_path)))
        try:
            receipt = read_public_bundle(directory, release_id, public_hash, expected_release_sha256=expected)
            item["public_bundle"] = {
                "status": "available", "sha256": receipt.bundle_sha256,
                "verifier_version": receipt.verifier_version,
            }
        except (OSError, ValueError, KeyError):
            log.warning("RPS public bundle unavailable")
            item["public_bundle"]["status"] = "unavailable"
    return item, witnesses


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
    for _attempt in range(2):
        approval = _approval()
        pending = iter(approval.releases if approval.enabled else ())
        items, unavailable, witnesses = [], [], []

        async def worker():
            for release_id, expected in pending:
                item, checked = await _offload(_catalog_entry, approval, release_id, expected)
                witnesses.extend(checked)
                if item is None:
                    unavailable.append({"id": release_id, "status": "unavailable", "reason_code": "verification_failed"})
                else:
                    items.append(item)

        # Four worker tasks, not one thread/task for every catalogue member.
        workers = [asyncio.create_task(worker()) for _ in range(min(4, len(approval.releases)))]
        try:
            await asyncio.gather(*workers)
        except BaseException:
            # gather propagates a failed worker without stopping its siblings.
            # Stop future catalogue traversal; shielded jobs already submitted
            # retain their permits and finish safely, but cannot enqueue more.
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            raise
        stable = await _offload(_unchanged, witnesses)
        if approval != _approval() or not stable:
            continue
        items.sort(key=lambda item: (datetime.fromisoformat(item["published_at"]), item["id"]), reverse=True)
        unavailable.sort(key=lambda item: item["id"])
        degraded = bool(unavailable) or any(item["public_bundle"]["status"] == "unavailable" for item in items)
        value = {
            "schema_version": "rps-catalog/1.3", "items": items, "unavailable": unavailable,
            "status": ("degraded" if degraded else "published") if items else "unavailable" if unavailable else "not_published",
            "approval_sha256": approval.sha256,
        }
        value["catalog_revision"] = digest(value)
        return _response(request, value)
    raise HTTPException(503, "RPS catalogue changed during verification; retry the request")


@router.get("/releases/{release_id}/bundle")
async def public_bundle(
    request: Request, release_id: str,
    manifest_sha256: str = Query(..., pattern=r"^[0-9a-f]{64}$"),
    bundle_sha256: str = Query(..., pattern=r"^[0-9a-f]{64}$"),
):
    from services.priority_public_bundle import read_public_bundle

    approval = _approval()
    expected = _approved(release_id, approval)
    public_hash = _approved(release_id, approval, bundle=True)
    if expected != manifest_sha256 or public_hash != bundle_sha256:
        raise HTTPException(409, "RPS publication changed; refresh the catalogue")
    try:
        def load():
            directory = Path(approval.directory)
            paths = [directory / f"{release_id}.json", directory / f"{release_id}.public.json"]
            witnesses = [(path, file_signature(path)) for path in paths]
            read_release_projection(directory, release_id, expected)
            receipt = read_public_bundle(directory, release_id, public_hash, expected_release_sha256=expected)
            response = conditional_json_response(
                request, receipt.canonical_bytes.decode("utf-8"),
                cache_control="public, max-age=0, must-revalidate",
                data_version_value=expected, last_modified=None,
                cache_header="X-RPS-Validation", cache_status="INTEGRITY_AND_CONTRACT_VERIFIED",
            )
            response.headers["Content-Disposition"] = f'attachment; filename="{release_id}.public.json"'
            response.headers["X-RPS-Bundle-SHA256"] = public_hash
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response, witnesses

        response, witnesses = await _offload(load)
        if not await _offload(_unchanged, witnesses):
            raise ValueError("RPS input changed")
    except (OSError, ValueError, KeyError):
        log.warning("Approved RPS public download unavailable")
        raise HTTPException(503, "RPS public bundle unavailable: verification failed") from None
    current = _approval()
    if (_approved(release_id, current) != expected
            or _approved(release_id, current, bundle=True) != public_hash
            or current.directory != approval.directory):
        raise HTTPException(409, "RPS publication changed; refresh the catalogue")
    return response


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
