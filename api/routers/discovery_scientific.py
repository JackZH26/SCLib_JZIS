"""Opt-in scientific Discovery delivery with two fresh read-only admissions.

No latest/maximum-score fallback, cross-request cache, provider or file reads.
The old RPS switches and exact release/bundle pins remain mandatory alongside
the new explicit projection pin. Responses never carry unavailable private IDs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import get_engine
from routers import discovery_priority
from services import discovery_projection_governance as service
from services import research_distribution_contract as contract

CATALOG_VERSION = "discovery-scientific-catalog/1.0.0"
MAX_PROJECTIONS = 25
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
MAX_RECEIPT_BYTES = MAX_PAYLOAD_BYTES + 64 * 1024
MAX_OBSERVATION_BYTES = 16 * 1024 * 1024
PASS_SECONDS = 25
TOTAL_SECONDS = 55
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_slots = threading.BoundedSemaphore(2)
_RECEIPT_FIELDS = {"version", "package_id", "payload_sha256", "selection_sha256",
    "publication_sha256", "review_sha256", "payload", *service.AUTHORITY}
_CATALOG_FIELDS = ("package_id", "payload_sha256", "selection_sha256", "publication_sha256", "review_sha256")


def _error(status, code):
    raise HTTPException(status, code)


class _ScientificRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                if len(request.scope.get("query_string", b"")) > 1024:
                    _error(400, "scientific_discovery_query_not_supported")
                return await original(request)
            except RequestValidationError:
                _error(400, "invalid_scientific_discovery_request")
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
                raise
            except (SQLAlchemyError, TimeoutError, ValueError, TypeError, KeyError, AttributeError,
                    OverflowError, RecursionError, UnicodeError):
                raise HTTPException(503, "scientific_discovery_unavailable", headers={
                    "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}) from None
            except Exception:
                # Includes unexpected driver/reader failures, but not request
                # cancellation or process interrupts (BaseException).
                raise HTTPException(503, "scientific_discovery_unavailable", headers={
                    "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}) from None
        return handler

    async def handle(self, scope, receive, send):
        # Includes router-generated 405 responses, without retaining body/error
        # text or letting an ETag short-circuit fresh authorization.
        async def no_store(message):
            if message["type"] == "http.response.start":
                headers = [(key, value) for key, value in message.get("headers", [])
                           if key.lower() not in {b"cache-control", b"x-content-type-options", b"etag", b"last-modified"}]
                message = {**message, "headers": headers + [(b"cache-control", b"no-store"),
                                                          (b"x-content-type-options", b"nosniff")]}
            await send(message)
        if self.methods and scope["method"] not in self.methods:
            # Starlette otherwise raises its 405 outside the wrapped sender.
            await Response('{"detail":"Method Not Allowed"}', status_code=405,
                media_type="application/json", headers={"Allow": ", ".join(sorted(self.methods))})(scope, receive, no_store)
            return
        await super().handle(scope, receive, no_store)


router = APIRouter(prefix="/discovery/scientific", tags=["scientific-discovery"], route_class=_ScientificRoute)


def _id(value):
    try:
        if type(value) is not str or len(value) != 36 or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        _error(400, "invalid_scientific_projection_identifier")
    return value


@dataclass(frozen=True)
class _Approval:
    enabled: bool
    projections: tuple[tuple[str, str], ...]
    rps: discovery_priority._Approval


def _approval():
    settings = get_settings()
    enabled, values = settings.discovery_scientific_public_enabled, settings.discovery_scientific_approved_projections
    if type(enabled) is not bool or type(values) is not dict or len(values) > MAX_PROJECTIONS:
        _error(503, "scientific_discovery_configuration_unavailable")
    entries = []
    for identifier, sha in values.items():
        try:
            if type(identifier) is not str or len(identifier) != 36 or str(UUID(identifier)) != identifier:
                raise ValueError
            if type(sha) is not str or _HASH.fullmatch(sha) is None:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            _error(503, "scientific_discovery_configuration_unavailable")
        entries.append((identifier, sha))
    return _Approval(enabled, tuple(sorted(entries)), discovery_priority._approval())


async def _inputs(request):
    if request.scope.get("query_string"):
        _error(400, "scientific_discovery_query_not_supported")
    # Even a chunked GET cannot smuggle an alternate selection or source body.
    count = 0
    async for chunk in request.stream():
        count += 1
        if chunk or count > 4096:
            _error(400, "scientific_discovery_body_not_supported")


def _receipt(value, identifier, expected, approval):
    if type(value) is not dict or set(value) != _RECEIPT_FIELDS:
        raise ValueError("receipt_shape")
    raw = contract._bounded(value)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError("receipt_limit")
    value = json.loads(raw)
    if value["version"] != service.VERSION or value["package_id"] != identifier:
        raise ValueError("receipt_identity")
    if any(value[key] is not False for key in service.AUTHORITY):
        raise ValueError("receipt_authority")
    for key in _CATALOG_FIELDS[1:]:
        if type(value[key]) is not str or _HASH.fullmatch(value[key]) is None:
            raise ValueError("receipt_hash")
    payload = value["payload"]
    payload_bytes = contract._bounded(payload)
    if len(payload_bytes) > MAX_PAYLOAD_BYTES or hashlib.sha256(payload_bytes).hexdigest() != value["payload_sha256"]:
        raise ValueError("payload_hash")
    if value["payload_sha256"] != expected:
        _error(404, "scientific_projection_not_published")
    if (type(payload) is not dict or payload.get("version") != "discovery-scientific-projection/1.0.0"
        or payload.get("selection_sha256") != value["selection_sha256"]
        or any(payload.get(key) is not False for key in ("scientific_acceptance", "ml_training_approved", "public_release_authorized"))):
        raise ValueError("payload_contract")
    base = payload["base"]
    release_id = base["release_id"]
    if type(release_id) is not str or not release_id or any(
        type(base.get(key)) is not str or _HASH.fullmatch(base[key]) is None
        for key in ("release_manifest_sha256", "public_bundle_sha256")
    ):
        raise ValueError("base_pins")
    if (not approval.rps.enabled or dict(approval.rps.releases).get(release_id) != base["release_manifest_sha256"]
        or dict(approval.rps.bundles).get(release_id) != base["public_bundle_sha256"]):
        _error(404, "scientific_projection_not_published")
    return value, raw


async def _observe(approval, identifiers, *, detail):
    """Independent bounded snapshot; never uses the caller's request session."""
    values, signatures, unavailable, budget = [], [], 0, 0
    expected = dict(approval.projections)
    async with asyncio.timeout(PASS_SECONDS):
        async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
            async with db.begin():
                await db.execute(sa.text("SET TRANSACTION READ ONLY"))
                await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
                await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                for identifier in identifiers:
                    try:
                        value = await service.admitted_projection(db, identifier)
                        value, raw = _receipt(value, identifier, expected[identifier], approval)
                    except service.DiscoveryGovernanceNotFound:
                        if detail:
                            _error(404, "scientific_projection_not_published")
                        unavailable += 1
                        continue
                    except HTTPException:
                        if detail:
                            raise
                        unavailable += 1
                        continue
                    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, UnicodeError):
                        if detail:
                            _error(503, "scientific_projection_unavailable")
                        unavailable += 1
                        continue
                    budget += len(raw)
                    if budget > MAX_OBSERVATION_BYTES:
                        _error(503, "scientific_discovery_inventory_limit")
                    signatures.append((identifier, hashlib.sha256(raw).hexdigest()))
                    values.append(value if detail else {key: value[key] for key in _CATALOG_FIELDS})
    return values, tuple(signatures), unavailable


async def _deliver(request, identifier=None):
    approval = _approval()
    if not approval.enabled or not approval.rps.enabled:
        _error(404, "scientific_discovery_not_published")
    if identifier is not None and identifier not in dict(approval.projections):
        _error(404, "scientific_projection_not_published")
    if not _slots.acquire(blocking=False):
        raise HTTPException(503, "scientific_discovery_capacity_unavailable", headers={"Retry-After": "1"})
    try:
        async with asyncio.timeout(TOTAL_SECONDS):
            await _inputs(request)
            identifiers = (identifier,) if identifier is not None else tuple(key for key, _ in approval.projections)
            first = await _observe(approval, identifiers, detail=identifier is not None)
            if _approval() != approval:
                _error(409, "scientific_discovery_changed")
            # The first transaction has exited before a new MVCC snapshot starts.
            second = await _observe(approval, identifiers, detail=identifier is not None)
            if first != second or _approval() != approval:
                _error(409, "scientific_discovery_changed")
            if identifier is not None:
                value = second[0][0]
            else:
                items, _, unavailable = second
                value = {"version": CATALOG_VERSION, "status": "degraded" if unavailable and items else
                         "unavailable" if unavailable else "published" if items else "not_published",
                         "items": items, "unavailable_count": unavailable,
                         "scientific_acceptance": False, "ml_training_approved": False}
            return Response(contract._bounded(value), media_type="application/json", headers={
                "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    finally:
        _slots.release()


@router.get("")
async def catalog(request: Request):
    return await _deliver(request)


@router.get("/{projection_id}")
async def detail(request: Request, projection_id: str):
    return await _deliver(request, _id(projection_id))
