"""Internal, bounded source-impact tasks with atomic Timeline invalidation.

Actor IDs must come from a trusted authenticated caller. No public write route,
scheduler, outer commit, scientific approval or external-system effect lives
here. Success acknowledges only invalidation in the execution DB snapshot;
the existing periodic refresher may subsequently rebuild the projection.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from contextlib import asynccontextmanager

import sqlalchemy as sa

from models.db import Base, TimelineProjectionState
from models.source_tasks_v1 import ACTION_VERSION, INVENTORY_VERSION
from services.research_access import ResearchAccessDenied, active_grant
from services.research_release_manifest import canonical, digest
from services.source_impact import (
    SourceImpactError,
    SourceImpactLimitError,
    inspect_source_impact,
)
from services.source_lifecycle import SourceLifecycleError, _current_event, _sha, _uuid, _wire

MAX_ATTEMPTS = 5
TRANSIENT_CODES = frozenset({"database_busy", "statement_timeout", "serialization_failure"})
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")


class SourceTaskError(ValueError):
    """The exact task, chain, authority or idempotency binding is unavailable."""


def _table(name):
    return Base.metadata.tables["source_task_" + name]


def _key(value):
    if type(value) is not str or not _KEY.fullmatch(value):
        raise SourceTaskError("A bounded task idempotency key is required")
    return value


def _record(row):
    body = _wire({key: value for key, value in row.items()
                  if key not in {"created_at", "record_sha256", "inventory_json"}})
    if digest(body) != row["record_sha256"]:
        raise SourceTaskError("Source task audit record hash mismatch")
    return _wire({key: value for key, value in row.items() if key != "inventory_json"})


def _inventory(row):
    raw = row["inventory_json"].encode("utf-8")
    if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != row["inventory_sha256"]:
        raise SourceTaskError("Source task inventory byte binding mismatch")
    try:
        body = json.loads(raw)
        if type(body) is not dict or canonical(body) != raw:
            raise SourceTaskError("Canonical task inventory required")
        event = body["event"]
        if (body["version"] != row["inventory_version"] or event["id"] != str(row["event_id"])
                or event["record_sha256"] != row["event_sha256"]
                or event["source_snapshot_sha256"] != row["source_snapshot_sha256"]):
            raise SourceTaskError("Source task inventory envelope mismatch")
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        raise SourceTaskError("Invalid source task inventory") from exc
    return body


async def _request(db, identifier, expected_hash=None):
    table = _table("requests")
    row = (await db.execute(sa.select(table).where(table.c.id == identifier))).mappings().one_or_none()
    if row is None:
        raise SourceTaskError("Source task unavailable")
    _record(row)
    _inventory(row)
    if expected_hash is not None and row["record_sha256"] != expected_hash:
        raise SourceTaskError("Exact source task request hash required")
    return row


async def _attempts(db, identifier):
    table = _table("attempts")
    rows = (await db.execute(sa.select(table).where(table.c.request_id == identifier)
                            .order_by(table.c.attempt_number).limit(MAX_ATTEMPTS + 1))).mappings().all()
    if len(rows) > MAX_ATTEMPTS:
        raise SourceTaskError("Source task attempt limit exceeded")
    prior = None
    for number, row in enumerate(rows, 1):
        _record(row)
        if (row["attempt_number"] != number or row["predecessor_id"] != (prior["id"] if prior else None)
                or (prior is not None and prior["status"] != "retryable_failure")):
            raise SourceTaskError("Source task attempt chain mismatch")
        prior = row
    return rows


def _semantics():
    return {"action_version": ACTION_VERSION, "propagation_complete": False,
            "timeline_rebuilt": False, "scientific_acceptance": False,
            "ml_training_approved": False, "source_reinstatement": False,
            "external_cache_invalidated": False,
            "currentness": "historical_receipt_not_live_projection_state"}


def _receipt(request, attempt=None, *, dry_run, replayed):
    return {"request": _record(request), "attempt": _record(attempt) if attempt else None,
            "dry_run": dry_run, "replayed": replayed, "committed": False,
            "requires_outer_commit": not dry_run,
            "executed_now": attempt is not None and not replayed and not dry_run
                            and attempt["status"] == "succeeded",
            "receipt_semantics": _semantics()}


@asynccontextmanager
async def _write(db, dry_run):
    if type(dry_run) is not bool or db.new or db.dirty or db.deleted:
        raise SourceTaskError("A clean dedicated session and Boolean dry_run are required")
    if (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one() != "serializable":
        raise SourceTaskError("Source task writes require SERIALIZABLE isolation")
    nested = await db.begin_nested()
    try:
        async with asyncio.timeout(10):
            old_timeout = (await db.execute(sa.text("SHOW statement_timeout"))).scalar_one()
            await db.execute(sa.text("SET LOCAL statement_timeout = '5000ms'"))
            for name in ("research_integrity", "research_publication", "source_lifecycle", "source_task"):
                await db.execute(sa.text(f"SELECT public.sclib_{name}_lock_v1()"))
            yield
            if not dry_run:
                await db.execute(sa.text("SELECT set_config('statement_timeout', :value, true)"),
                                 {"value": old_timeout})
        if dry_run:
            await nested.rollback()
        else:
            await nested.commit()
    except BaseException:
        if nested.is_active:
            await nested.rollback()
        raise


async def enqueue_source_task(db, *, actor_user_id, event_id, expected_event_sha256,
                              expected_inventory_sha256, request_key, dry_run=True):
    """Recompute the declared inventory; persist exact bytes, default rehearsal."""
    actor, identifier = _uuid(actor_user_id), _uuid(event_id)
    event_hash, inventory_hash, key = _sha(expected_event_sha256), _sha(expected_inventory_sha256), _key(request_key)
    async with _write(db, dry_run):
        grant = await active_grant(db, actor, role="curator")
        table = _table("requests")
        old = (await db.execute(sa.select(table).where(table.c.requester_id == actor,
                    table.c.request_key == key))).mappings().one_or_none()
        if old is not None:
            _record(old)
            _inventory(old)
            if (old["event_id"] != identifier or old["event_sha256"] != event_hash
                    or old["inventory_sha256"] != inventory_hash or old["action_version"] != ACTION_VERSION):
                raise SourceTaskError("Idempotency key is bound to a different request")
            return _receipt(old, dry_run=dry_run, replayed=True)
        report = await inspect_source_impact(db, event_id=identifier, expected_event_sha256=event_hash)
        if report["inventory_sha256"] != inventory_hash:
            raise SourceTaskError("Source impact inventory changed; inspect it again")
        body = {key: value for key, value in report.items() if key not in {"observation", "inventory_sha256"}}
        row = (await db.execute(table.insert().values(event_id=identifier, event_sha256=event_hash,
            source_snapshot_sha256=report["event"]["source_snapshot_sha256"], inventory_version=INVENTORY_VERSION,
            inventory_sha256=inventory_hash, inventory_json=canonical(body).decode("utf-8"),
            action_version=ACTION_VERSION, requester_id=actor, requester_grant_id=grant["id"], request_key=key)
            .returning(table))).mappings().one()
        return _receipt(row, dry_run=dry_run, replayed=False)


def _replay(rows, key, actor):
    for row in rows:
        if row["execution_key"] == key:
            if row["executor_id"] != actor:
                raise SourceTaskError("Execution key is bound to a different executor")
            return row
    return None


def _head(rows):
    prior = rows[-1] if rows else None
    if prior and (prior["status"] != "retryable_failure" or prior["attempt_number"] >= MAX_ATTEMPTS):
        raise SourceTaskError("Source task is terminal; inspect or create a new exact request")
    return prior


async def _append(db, request, prior, actor, grant, key, status, code):
    table = _table("attempts")
    row = (await db.execute(table.insert().values(request_id=request["id"],
        attempt_number=prior["attempt_number"] + 1 if prior else 1, predecessor_id=prior["id"] if prior else None,
        executor_id=actor, executor_grant_id=grant["id"], execution_key=key, status=status, outcome_code=code)
        .returning(table))).mappings().one()
    # SQL itself performs successful invalidation. Expire only the readiness
    # identity (not user/scientific records) after the Core trigger side effect.
    if status == "succeeded":
        for value in list(db.identity_map.values()):
            if isinstance(value, TimelineProjectionState):
                db.expire(value)
    return row


async def execute_source_task(db, *, actor_user_id, request_id, expected_request_sha256,
                              execution_key, dry_run=True):
    """One atomic attempt. DB failures escape; never fabricate an aborted receipt."""
    actor, identifier = _uuid(actor_user_id), _uuid(request_id)
    expected_hash, key = _sha(expected_request_sha256), _key(execution_key)
    async with _write(db, dry_run):
        grant = await active_grant(db, actor, role="curator")
        request = await _request(db, identifier, expected_hash)
        rows = await _attempts(db, identifier)
        old = _replay(rows, key, actor)
        if old is not None:
            return _receipt(request, old, dry_run=dry_run, replayed=True)
        prior = _head(rows)
        status, code = "succeeded", "timeline_cache_invalidated"
        try:
            await active_grant(db, request["requester_id"], role="curator", grant_id=request["requester_grant_id"])
        except ResearchAccessDenied:
            status, code = "blocked", "request_authority_unavailable"
        if status == "succeeded":
            try:
                await _current_event(db, request["event_id"], request["event_sha256"])
            except SourceLifecycleError:
                status, code = "obsolete", "source_changed"
        if status == "succeeded":
            try:
                report = await inspect_source_impact(db, event_id=request["event_id"],
                                                     expected_event_sha256=request["event_sha256"])
                if report["inventory_sha256"] != request["inventory_sha256"]:
                    status, code = "obsolete", "inventory_changed"
            except SourceImpactLimitError:
                status, code = "blocked", "scope_limit"
            except (SourceImpactError, SourceLifecycleError):
                status, code = "blocked", "inventory_unavailable"
        attempt = await _append(db, request, prior, actor, grant, key, status, code)
        return _receipt(request, attempt, dry_run=dry_run, replayed=False)


async def record_source_task_failure(db, *, actor_user_id, request_id, expected_request_sha256,
        execution_key, outcome_code, expected_predecessor_id=None, expected_predecessor_sha256=None, dry_run=True):
    """Trusted runner report AFTER rollback, in a fresh SERIALIZABLE transaction.

This is an attributed allowlisted failure report, not independent SQL-error
attestation. No arbitrary exceptions/DSNs are stored, and no retry is scheduled.
"""
    if type(outcome_code) is not str or outcome_code not in TRANSIENT_CODES:
        raise SourceTaskError("An allowlisted transient failure code is required")
    if (expected_predecessor_id is None) != (expected_predecessor_sha256 is None):
        raise SourceTaskError("Exact predecessor identity and hash must be supplied together")
    predecessor = _uuid(expected_predecessor_id) if expected_predecessor_id is not None else None
    predecessor_hash = _sha(expected_predecessor_sha256) if expected_predecessor_sha256 is not None else None
    actor, identifier = _uuid(actor_user_id), _uuid(request_id)
    expected_hash, key = _sha(expected_request_sha256), _key(execution_key)
    async with _write(db, dry_run):
        grant = await active_grant(db, actor, role="curator")
        request = await _request(db, identifier, expected_hash)
        rows = await _attempts(db, identifier)
        old = _replay(rows, key, actor)
        if old is not None:
            if old["outcome_code"] != outcome_code or old["predecessor_id"] != predecessor:
                raise SourceTaskError("Execution key is bound to a different failure")
            if predecessor is not None:
                previous = next(row for row in rows if row["id"] == predecessor)
                if previous["record_sha256"] != predecessor_hash:
                    raise SourceTaskError("Exact predecessor hash required")
            return _receipt(request, old, dry_run=dry_run, replayed=True)
        prior = _head(rows)
        if (predecessor != (prior["id"] if prior else None)
                or predecessor_hash != (prior["record_sha256"] if prior else None)):
            raise SourceTaskError("Exact current attempt predecessor required")
        status = "exhausted" if prior and prior["attempt_number"] == MAX_ATTEMPTS - 1 else "retryable_failure"
        attempt = await _append(db, request, prior, actor, grant, key, status, outcome_code)
        return _receipt(request, attempt, dry_run=dry_run, replayed=False)


async def inspect_source_task(db, request_id):
    """Bounded immutable history, not live cache readiness or scientific approval."""
    if db.new or db.dirty or db.deleted:
        raise SourceTaskError("A clean dedicated inspection session is required")
    if (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one() not in {"repeatable read", "serializable"}:
        raise SourceTaskError("Source task inspection requires REPEATABLE READ or SERIALIZABLE")
    request = await _request(db, _uuid(request_id))
    rows = await _attempts(db, request["id"])
    return {"request": _record(request), "attempts": [_record(row) for row in rows],
            "stored_state": rows[-1]["status"] if rows else "queued",
            "retry_scheduled": False, "receipt_semantics": _semantics()}
