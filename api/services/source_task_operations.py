"""Bounded private operator admission for the existing Timeline action only.

Caller-supplied identity is never accepted in request JSON. The authenticated
router owns the outer transaction and must roll it back for preview/replay.
Hashes bind an operation/actor/snapshot; they do not attest scientific approval,
full propagation, an actual rebuild, or that a preview was previously requested.
"""
from __future__ import annotations

import asyncio
import json
import re
from uuid import UUID

import sqlalchemy as sa

from models.source_tasks_v1 import ACTION_VERSION
from services import source_tasks as tasks
from services.research_access import active_grant
from services.research_release_manifest import canonical, digest
from services.source_impact import SourceImpactError
from services.source_lifecycle import SourceLifecycleError

VERSION = "source-task-operation/1.0.0"
PREVIEW_VERSION = "source-task-preview/1.0.0"
RECEIPT_VERSION = "source-task-operation-receipt/1.0.0"
MAX_BYTES = 8192
MAX_COMMIT_BYTES = MAX_BYTES + 256
MAX_RESPONSE_BYTES = 32768
_COMMON = {"version", "operation"}
_ENQUEUE = {"request_key", "event_id", "expected_event_sha256", "expected_inventory_sha256"}
_EXECUTE = {"request_id", "expected_request_sha256", "execution_key",
            "expected_predecessor_id", "expected_predecessor_sha256"}


class SourceTaskOperationError(ValueError):
    """Malformed closed operation; all messages are static reason codes."""


class SourceTaskOperationConflict(SourceTaskOperationError):
    """Exact request, actor, head or preview binding changed."""


class SourceTaskOperationUnavailable(SourceTaskOperationError):
    """The bounded operation could not be verified."""


def _require(condition, code="invalid_source_task_operation"):
    if not condition:
        raise SourceTaskOperationError(code)


def _conflict(condition):
    if not condition:
        raise SourceTaskOperationConflict("source_task_operation_binding_changed")


def identifier(value):
    _require(type(value) is str)
    try:
        parsed = UUID(value)
    except ValueError:
        raise SourceTaskOperationError("canonical_identifier_required") from None
    _require(str(parsed) == value, "canonical_identifier_required")
    return value


def checksum(value):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
             "exact_checksum_required")
    return value


def operation_key(value):
    _require(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", value) is not None,
             "bounded_operation_key_required")
    return value


def loads(payload, *, max_bytes=MAX_BYTES):
    """Strict bounded UTF-8 JSON, before constructing the closed request DTO."""
    _require(type(payload) is bytes and type(max_bytes) is int and 1 <= max_bytes <= MAX_COMMIT_BYTES
             and 0 < len(payload) <= max_bytes, "source_task_body_limit")
    try:
        text = payload.decode("utf-8", errors="strict")
        quoted = escaped = False
        depth = 0
        for char in text:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                _require(depth <= 16, "source_task_json_depth_limit")
            elif char in "]}":
                depth -= 1
                _require(depth >= 0)

        def pairs(values):
            result = {}
            for key, value in values:
                _require(key not in result, "duplicate_source_task_key")
                result[key] = value
            return result

        def bad_number(_value):
            raise SourceTaskOperationError("numeric_source_task_value_unsupported")

        value = json.loads(text, object_pairs_hook=pairs, parse_constant=bad_number,
                           parse_float=bad_number, parse_int=bad_number)
        _require(type(value) is dict)
        canonical(value)  # Reject lone surrogates, not just invalid UTF-8 bytes.
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, SourceTaskOperationError):
            raise
        raise SourceTaskOperationError("invalid_source_task_json") from None


def validate_request(value):
    _require(type(value) is dict and type(value.get("operation")) is str)
    operation = value["operation"]
    _require(operation in {"enqueue", "execute"})
    _require(set(value) == _COMMON | (_ENQUEUE if operation == "enqueue" else _EXECUTE))
    _require(type(value["version"]) is str and value["version"] == VERSION)
    if operation == "enqueue":
        operation_key(value["request_key"])
        identifier(value["event_id"])
        checksum(value["expected_event_sha256"])
        checksum(value["expected_inventory_sha256"])
    else:
        identifier(value["request_id"])
        operation_key(value["execution_key"])
        checksum(value["expected_request_sha256"])
        previous, previous_hash = value["expected_predecessor_id"], value["expected_predecessor_sha256"]
        _require((previous is None) == (previous_hash is None))
        if previous is not None:
            identifier(previous)
            checksum(previous_hash)
    result = dict(value)
    _require(len(canonical(result)) <= MAX_BYTES, "source_task_body_limit")
    return result


def validate_commit(value):
    _require(type(value) is dict and set(value) == {"request", "expected_preview_sha256"})
    return {"request": validate_request(value["request"]),
            "expected_preview_sha256": checksum(value["expected_preview_sha256"])}


def _preview(request, actor, grant, *, status, code, replayed):
    binding = {"version": PREVIEW_VERSION, "operation": request["operation"],
        "actor_user_id": str(actor), "actor_grant_id": str(grant),
        "operation_sha256": digest(request), "predicted_status": status,
        "predicted_outcome_code": code, "receipt_semantics": tasks._semantics()}
    return {**binding, "preview_sha256": digest(binding), "can_commit": True,
            "database_mutated": False, "replayed": replayed}


def _receipt(request, preview, stored, attempt=None, *, replayed):
    value = {"version": RECEIPT_VERSION, "operation": request["operation"],
        "actor_user_id": preview["actor_user_id"], "actor_grant_id": preview["actor_grant_id"],
        "operation_sha256": preview["operation_sha256"], "preview_sha256": preview["preview_sha256"],
        "request": tasks._record(stored), "attempt": tasks._record(attempt) if attempt is not None else None,
        "replayed": replayed, "committed": False, "requires_outer_commit": True,
        "executed_now": not replayed and attempt is not None and attempt["status"] == "succeeded",
        "receipt_semantics": tasks._semantics()}
    if len(canonical(value)) > MAX_RESPONSE_BYTES:
        raise SourceTaskOperationUnavailable("source_task_response_limit")
    return value


def _enqueued_request(row):
    return {"version": VERSION, "operation": "enqueue", "request_key": row["request_key"],
            "event_id": str(row["event_id"]), "expected_event_sha256": row["event_sha256"],
            "expected_inventory_sha256": row["inventory_sha256"]}


def _executed_request(row, attempt, attempts):
    prior = next((item for item in attempts if item["id"] == attempt["predecessor_id"]), None)
    _conflict(prior is not None or attempt["predecessor_id"] is None)
    return {"version": VERSION, "operation": "execute", "request_id": str(row["id"]),
            "expected_request_sha256": row["record_sha256"], "execution_key": attempt["execution_key"],
            "expected_predecessor_id": str(prior["id"]) if prior else None,
            "expected_predecessor_sha256": prior["record_sha256"] if prior else None}


async def _stored_enqueue(db, actor, key):
    table = tasks._table("requests")
    identifier_ = await db.scalar(sa.select(table.c.id).where(
        table.c.requester_id == actor, table.c.request_key == key))
    return None if identifier_ is None else await tasks._request(db, identifier_)


async def _historical(db, actor, request):
    if request["operation"] == "enqueue":
        stored = await _stored_enqueue(db, actor, request["request_key"])
        if stored is None:
            return None
        _conflict(_enqueued_request(stored) == request and stored["action_version"] == ACTION_VERSION)
        preview = _preview(request, actor, stored["requester_grant_id"], status="queued", code=None, replayed=True)
        return preview, stored, None
    stored = await tasks._request(db, UUID(request["request_id"]), request["expected_request_sha256"])
    attempts = await tasks._attempts(db, stored["id"])
    old = tasks._replay(attempts, request["execution_key"], actor)
    if old is None:
        return None
    _conflict(_executed_request(stored, old, attempts) == request)
    preview = _preview(request, actor, old["executor_grant_id"], status=old["status"],
                       code=old["outcome_code"], replayed=True)
    return preview, stored, old


async def _invoke(db, actor, grant, request, *, dry_run):
    args = {key: value for key, value in request.items() if key not in _COMMON}
    if request["operation"] == "execute":
        args["check_predecessor"] = True
    function = tasks.enqueue_source_task if request["operation"] == "enqueue" else tasks.execute_source_task
    return await function(db, actor_user_id=actor, expected_actor_grant_id=grant,
                          dry_run=dry_run, **args)


async def _operate(db, actor_user_id, request, *, expected_preview_sha256=None, dry_run):
    request = validate_request(request)
    actor = tasks._uuid(actor_user_id)
    if not dry_run:
        checksum(expected_preview_sha256)
    try:
        # Outer fence survives the inner rollback rehearsal: no unlocked gap
        # exists between exact-head preview validation and the actual insertion.
        async with tasks._write(db, dry_run):
            grant = await active_grant(db, actor, role="curator")
            historical = await _historical(db, actor, request)
            if historical is not None:
                preview, stored, attempt = historical
                if not dry_run:
                    _conflict(preview["preview_sha256"] == expected_preview_sha256)
                return preview if dry_run else _receipt(request, preview, stored, attempt, replayed=True)
            rehearsal = await _invoke(db, actor, grant["id"], request, dry_run=True)
            predicted = rehearsal["attempt"]
            preview = _preview(request, actor, grant["id"],
                status=predicted["status"] if predicted else "queued",
                code=predicted["outcome_code"] if predicted else None, replayed=False)
            if dry_run:
                return preview
            _conflict(preview["preview_sha256"] == expected_preview_sha256)
            result = await _invoke(db, actor, grant["id"], request, dry_run=False)
            stored = await tasks._request(db, UUID(result["request"]["id"]))
            attempt = None
            if result["attempt"] is not None:
                attempt = next(item for item in await tasks._attempts(db, stored["id"])
                               if str(item["id"]) == result["attempt"]["id"])
                _conflict((attempt["status"], attempt["outcome_code"]) ==
                          (preview["predicted_status"], preview["predicted_outcome_code"]))
            return _receipt(request, preview, stored, attempt, replayed=False)
    except (tasks.SourceTaskError, SourceLifecycleError, SourceImpactError):
        raise SourceTaskOperationConflict("source_task_operation_binding_changed") from None


async def preview_operation(db, *, actor_user_id, request):
    return await _operate(db, actor_user_id, request, dry_run=True)


async def commit_operation(db, *, actor_user_id, request, expected_preview_sha256):
    return await _operate(db, actor_user_id, request, expected_preview_sha256=expected_preview_sha256, dry_run=False)


async def _read_admission(db, actor_user_id):
    if db.new or db.dirty or db.deleted:
        raise SourceTaskOperationUnavailable("clean_source_task_read_session_required")
    isolation = await db.scalar(sa.text("SHOW transaction_isolation"))
    if isolation not in {"repeatable read", "serializable"}:
        raise SourceTaskOperationUnavailable("consistent_source_task_read_snapshot_required")
    actor = tasks._uuid(actor_user_id)
    await active_grant(db, actor, role="curator")
    return actor


async def inspect_by_key(db, *, actor_user_id, request_key):
    key = operation_key(request_key)
    async with asyncio.timeout(10):
        actor = await _read_admission(db, actor_user_id)
        stored = await _stored_enqueue(db, actor, key)
        if stored is None:
            return None
        request = _enqueued_request(stored)
        preview = _preview(request, actor, stored["requester_grant_id"], status="queued", code=None, replayed=True)
        return _receipt(request, preview, stored, replayed=True)


async def inspect_execution(db, *, actor_user_id, request_id, execution_key):
    identifier_, key = identifier(request_id), operation_key(execution_key)
    async with asyncio.timeout(10):
        actor = await _read_admission(db, actor_user_id)
        table = tasks._table("requests")
        if await db.scalar(sa.select(table.c.id).where(table.c.id == UUID(identifier_))) is None:
            return None
        stored = await tasks._request(db, UUID(identifier_))
        attempts = await tasks._attempts(db, stored["id"])
        attempt = next((item for item in attempts if item["execution_key"] == key
                        and item["executor_id"] == actor), None)
        if attempt is None:
            return None
        request = _executed_request(stored, attempt, attempts)
        preview = _preview(request, actor, attempt["executor_grant_id"], status=attempt["status"],
                           code=attempt["outcome_code"], replayed=True)
        return _receipt(request, preview, stored, attempt, replayed=True)
