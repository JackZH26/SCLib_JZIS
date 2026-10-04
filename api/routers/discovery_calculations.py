"""Owner-private QE custody; authenticate before accepting any original files."""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import threading

import sqlalchemy as sa
from config import get_settings
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from services import discovery_calculation_contract as contract
from services import discovery_calculations as service
from services import discovery_designs as designs
from services.discovery_feedback_contract import checksum, closed
from services.research_release_manifest import canonical
from services.source_property_pending import SourcePropertyConflict, SourcePropertyError

from routers.discovery_designs import read
from routers.research_distributions import _strict_json
from routers.source_properties import HEADERS, _session
from routers.source_properties import PrivateRoute as SharedRoute

# 81 MiB raw files, base64 expansion, and a bounded metadata request. One upload
# and one native parse per process. A timed-out thread retains its worker slot.
MAX_BODY_BYTES = 109 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
_uploads = threading.BoundedSemaphore(1)
_workers = threading.BoundedSemaphore(1)
_tasks: set[asyncio.Task] = set()
MESSAGES = {400: "Invalid calculation return or unsupported native files", 401: "Authentication required",
    403: "Current research curator access required", 404: "Private calculation return unavailable",
    409: "Calculation return or research plan changed; refresh", 413: "Calculation files exceed the supported limits",
    415: "Uncompressed JSON required", 422: "Invalid calculation return request",
    503: "Calculation return unavailable; check the saved outcome before retrying"}


def failure(status):
    return HTTPException(status, MESSAGES.get(status, MESSAGES[400]), headers=HEADERS)


class PrivateRoute(SharedRoute):
    def get_route_handler(self):
        guarded = super().get_route_handler()

        async def handle(request):
            try:
                return await guarded(request)
            except HTTPException as exc:
                raise failure(exc.status_code) from None
        return handle


def enabled():
    if not get_settings().discovery_calculations_enabled:
        raise failure(404)


router = APIRouter(prefix="/research/discovery-calculations", tags=["discovery-calculations"],
                   route_class=PrivateRoute, dependencies=[Depends(enabled)])


def response(value):
    raw = canonical(value)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise failure(503)
    return Response(raw, media_type="application/json", headers=HEADERS)


async def worker(function, *args):
    if not _workers.acquire(blocking=False):
        raise failure(503)
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    _tasks.add(task)

    def done(completed):
        _tasks.discard(completed)
        _workers.release()
        if not completed.cancelled():
            completed.exception()  # Consume a late failure after caller timeout.
    task.add_done_callback(done)
    async with asyncio.timeout(12):
        return await asyncio.shield(task)


async def body_bytes(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json" \
            or request.headers.get("content-encoding", "identity").lower() != "identity":
        raise failure(415)
    length = request.headers.get("content-length")
    if length is not None and (not re.fullmatch(r"[0-9]{1,10}", length) or int(length) > MAX_BODY_BYTES):
        raise failure(413)
    raw = bytearray()
    async with asyncio.timeout(8):
        async for piece in request.stream():
            if len(raw) + len(piece) > MAX_BODY_BYTES:
                raise failure(413)
            raw.extend(piece)
    return raw


def prepare_body(raw, commit):
    body = _strict_json(raw)
    closed(body, {"request", "files_base64", *(["expected_preview_sha256"] if commit else [])})
    request = contract.validate(body["request"])
    encoded = body["files_base64"]
    contract.require(type(encoded) is list and len(encoded) == len(request["files"]), "calculation_exact_encoded_inventory")
    files = []
    for item, value in zip(request["files"], encoded, strict=True):
        contract.require(type(value) is str and len(value) == 4 * ((item["size_bytes"] + 2) // 3), "calculation_encoded_size")
        try:
            original = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise failure(400) from None
        contract.require(base64.b64encode(original).decode("ascii") == value, "calculation_canonical_base64")
        files.append(original)
    expected = checksum(body["expected_preview_sha256"]) if commit else None
    return contract.prepare(request, files), expected


async def operation(request, *, commit):
    # Both role and JWT session are checked before body consumption. Release the
    # read connection before upload/parse, then compare authority in the writer.
    async with _session(request, role="curator") as (db, actor):
        original_authority = await designs._grant(db, actor, "curator")
        original_actor = actor
    if not _uploads.acquire(blocking=False):
        raise failure(503)
    try:
        raw = await body_bytes(request)
        prepared, expected = await worker(prepare_body, raw, commit)
        del raw
        async with _session(request, write=True, role="curator") as (db, actor):
            if actor != original_actor or await designs._grant(db, actor, "curator") != original_authority:
                raise SourcePropertyConflict("calculation_upload_authority_changed")
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            result = await service.operate(db, actor_user_id=actor, prepared=prepared,
                                           dry_run=not commit, expected_preview_sha256=expected)
        if result["dry_run"]:
            async with read(request) as (db, actor):
                await service._design(db, actor, prepared.request["design"], current=True)
            result = {**result, "report": json.loads(prepared.report_json), "report_canonical_json": prepared.report_json}
        # An idempotent receipt contains no source quantities, including after a
        # design is withdrawn. Read the saved report under current access.
        return response(result)
    finally:
        _uploads.release()


@router.get("/capabilities")
async def capabilities(request: Request):
    async with read(request) as (db, actor):
        result = await service.capabilities(db, actor_user_id=actor)
    return response(result)


@router.get("/designs/{design_id}/context")
async def context(request: Request, design_id: str):
    async with read(request) as (db, actor):
        result = await service.context(db, actor_user_id=actor, design_id=design_id)
    return response(result)


@router.post("/operations/preview")
async def preview(request: Request):
    return await operation(request, commit=False)


@router.post("/operations/commit")
async def commit(request: Request):
    return await operation(request, commit=True)


@router.get("/operations/outcome")
async def outcome(request: Request, request_key: str, expected_request_sha256: str):
    async with read(request) as (db, actor):
        result = await service.outcome(db, actor_user_id=actor, request_key_value=request_key,
                                       expected_request_sha256=expected_request_sha256)
    return response(result)


@router.get("/designs/{design_id}/returns")
async def returns(request: Request, design_id: str, offset: int = 0, limit: int = 8):
    async with read(request) as (db, actor):
        result = await service.returns(db, actor_user_id=actor, design_id=design_id, offset=offset, limit=limit)
    return response(result)


async def reading(request, return_id):
    async with read(request) as (db, actor):
        row, eligible, files = await service.original_files(db, actor_user_id=actor, return_id=return_id)
        try:
            prepared = await worker(service.reconstruct, row, files) if files is not None else None
        except (SourcePropertyError, ValueError):
            # Stored-byte/parser integrity failure is an unavailable reading,
            # not a bad request from the researcher. Never expose partial values.
            raise failure(503) from None
        result = {"receipt": service.receipt(row), "eligibility": eligible,
                  "report": json.loads(prepared.report_json) if prepared else None, **contract.AUTHORITY}
    # Native parsing runs without write locks. Recheck the design in a fresh
    # transaction before exposing values or bytes after that potentially slow work.
    if prepared:
        async with read(request) as (db, actor):
            await service._design(db, actor, row["design_ref"], current=True)
    return result, prepared


@router.get("/returns/{return_id}")
async def detail(request: Request, return_id: str):
    result, _ = await reading(request, return_id)
    return response(result)


@router.get("/returns/{return_id}/files/{ordinal}")
async def download(request: Request, return_id: str, ordinal: int):
    contract.require(0 <= ordinal <= 10, "calculation_file_index")
    _, prepared = await reading(request, return_id)
    if prepared is None:
        raise failure(409)
    if ordinal >= len(prepared.files):
        raise failure(404)
    item = prepared.request["files"][ordinal]
    return Response(prepared.files[ordinal], media_type="application/octet-stream", headers={**HEADERS,
        "Content-Disposition": 'attachment; filename="' + item["name"] + '"', "X-Content-SHA256": item["sha256"]})
