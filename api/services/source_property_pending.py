"""Authenticated, atomic pending-source import and fidelity-note appends.

Trusted HTTP callers authenticate the actor and own the outer transaction.
Every mutation rehearses actual SQL in a savepoint, binds exact live authority
and returns the same receipt on replay. No material/claim/event is written.
"""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from uuid import UUID, uuid5

import sqlalchemy as sa

from models.db import Base
from models.source_property_pending_v1 import LOCK_FUNCTION, TABLE_ORDER
from services import source_property_contract as contract
from services.research_access import ResearchAccessDenied, active_grant
from services.research_release_manifest import canonical, digest

VERSION = "source-property-pending/1.0.0"
_NAMESPACE = UUID("807b1d9e-4650-4a78-9352-c13fb632b991")
CHECKS = frozenset({"source_expression", "source_locator", "raw_units", "source_subject",
                    "source_window", "derivation_role"})
ACTIONS = frozenset({"matches_inspected_source", "requires_clarification", "source_mismatch", "withdraw_note"})


class SourcePropertyError(ValueError):
    """Static request failure; never reflect private payload or SQL."""


class SourcePropertyConflict(SourcePropertyError):
    """The request, source inventory, authority or preview head differs."""


class SourcePropertyNotFound(SourcePropertyError):
    """An exact private observation/receipt is not present."""


def require(ok, code):
    if not ok:
        raise SourcePropertyError(code)


def identifier(value):
    try:
        result = UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise SourcePropertyError("invalid_identifier") from None
    require(str(result) == str(value), "canonical_identifier_required")
    return result


def request_key(value):
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}", value), "request_key_required")
    return value


def checksum(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "checksum_required")
    return value


def _table(name):
    return Base.metadata.tables[name]


def _stable(*parts):
    return uuid5(_NAMESPACE, digest([str(value) for value in parts]))


def _body(row):
    return {str(key): str(value) if isinstance(value, UUID) else value for key, value in row.items()
            if key not in {"created_at", "record_sha256", "assembly_xid"}}


async def _session(db, *, write):
    require(not (db.new or db.dirty or db.deleted), "clean_session_required")
    isolation = await db.scalar(sa.text("SHOW transaction_isolation"))
    require(isolation == "serializable" if write else isolation in {"serializable", "repeatable read"}, "stable_session_required")
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))


async def _grant(db, actor, role, *, grant_id=None, session_version=None):
    grant = await active_grant(db, actor, role=role, grant_id=grant_id)
    version = await db.scalar(sa.select(_table("users").c.session_version).where(_table("users").c.id == identifier(actor)))
    if session_version is not None and version != session_version:
        raise ResearchAccessDenied("source_property_session_changed")
    return grant, version


async def reader(db, actor):
    await _session(db, write=False)
    try:
        return await _grant(db, actor, "curator")
    except ResearchAccessDenied:
        return await _grant(db, actor, "reviewer")


@asynccontextmanager
async def _write(db, dry_run):
    require(type(dry_run) is bool, "boolean_preview_required")
    await _session(db, write=True)
    nested = await db.begin_nested()
    operation = {"changed": False}
    try:
        await db.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
        yield operation
        await db.execute(sa.text("SET CONSTRAINTS sp82_complete IMMEDIATE"))
        await db.execute(sa.text("SET CONSTRAINTS sp82_complete DEFERRED"))
        if dry_run or not operation["changed"]:
            await nested.rollback()
        else:
            await nested.commit()
    except BaseException:
        if nested.is_active:
            await nested.rollback()
        raise


async def _insert(db, name, values):
    values = {**values, "record_sha256": digest(_body(values))}
    return (await db.execute(_table(name).insert().values(**values).returning(_table(name)))).mappings().one()


async def _row(db, name, row_id):
    return (await db.execute(sa.select(_table(name)).where(_table(name).c.id == identifier(row_id)))).mappings().one_or_none()


def _import_dto(row, *, replayed=False):
    return {"version": VERSION, "receipt_id": str(row["id"]), "receipt_sha256": row["record_sha256"],
        "actor_user_id": str(row["actor_user_id"]), "actor_session_version": row["actor_session_version"],
        "actor_grant_id": str(row["actor_grant_id"]), "request_sha256": row["request_sha256"],
        "preview_sha256": row["preview_sha256"], "source_json_sha256": row["source_json_sha256"],
        "original_batch_sha256": row["original_batch_sha256"], "batch_id": row["batch_id"],
        "summary": row["summary"], "observation_manifest": row["observation_manifest"],
        "status": "pending", "scientific_acceptance": False, "canonical_promotions": 0,
        "selected_result_association": "unestablished", "replayed": replayed, "pending_ledger_written": True}


async def capabilities(db, *, actor_user_id):
    _, session_version = await reader(db, actor_user_id)
    capabilities = {}
    for role in ("curator", "reviewer"):
        try:
            grant, _ = await _grant(db, actor_user_id, role)
            capabilities[role] = str(grant["id"])
        except ResearchAccessDenied:
            capabilities[role] = None
    return {"version": VERSION, "actor_user_id": str(identifier(actor_user_id)), "session_version": session_version,
        "can_import": capabilities["curator"] is not None,
        "can_append_source_note": capabilities["reviewer"] is not None, "grants": capabilities,
        "registry_sha256": contract.REGISTRY_SHA256, "canonical_promotions": 0,
        "scientific_acceptance": False, "scope": "private_pending_source_expressions"}


async def import_snapshot(db, *, actor_user_id, request_key_value, source_bytes,
                          dry_run=True, expected_preview_sha256=None):
    key = request_key(request_key_value)
    prepared = contract.compile_public_snapshot(source_bytes)
    request_hash = digest({"version": VERSION, "source_json_sha256": prepared.source_json_sha256,
                           "original_batch_sha256": prepared.original_batch_sha256,
                           "registry_sha256": prepared.registry_sha256})
    async with _write(db, dry_run) as operation:
        grant, session_version = await _grant(db, actor_user_id, "curator")
        receipts = _table(TABLE_ORDER[0])
        existing = (await db.execute(sa.select(receipts).where(receipts.c.actor_user_id == identifier(actor_user_id),
                    receipts.c.request_key == key))).mappings().one_or_none()
        if existing is not None:
            if existing["request_sha256"] != request_hash:
                raise SourcePropertyConflict("request_key_conflict")
            if expected_preview_sha256 is not None and existing["preview_sha256"] != expected_preview_sha256:
                raise SourcePropertyConflict("preview_conflict")
            return _import_dto(existing, replayed=True)
        if await db.scalar(sa.select(sa.exists().where(receipts.c.source_json_sha256 == prepared.source_json_sha256))):
            raise SourcePropertyConflict("snapshot_already_imported")
        actor = {"actor_user_id": identifier(actor_user_id), "actor_grant_id": grant["id"],
                 "actor_session_version": session_version}
        manifest = [{"source_entry_id": obs["source_entry_id"], "entry_sha256": obs["entry_sha256"],
                     "projection_sha256": digest(obs)} for obs in prepared.observations]
        preview = digest({"version": VERSION, "request_key": key, "request_sha256": request_hash,
            "actor": _body(actor), "summary": prepared.summary, "observation_manifest": manifest})
        if not dry_run and (expected_preview_sha256 is None or expected_preview_sha256 != preview):
            raise SourcePropertyConflict("exact_preview_required")
        receipt_id = _stable("import", actor_user_id, key)
        receipt = await _insert(db, TABLE_ORDER[0], {"id": receipt_id, **actor, "request_key": key,
            "request_sha256": request_hash, "preview_sha256": preview,
            "source_json_sha256": prepared.source_json_sha256, "original_batch_sha256": prepared.original_batch_sha256,
            "registry_sha256": prepared.registry_sha256, "batch_id": prepared.batch_id,
            "source_public_json": source_bytes.decode("utf-8"), "observation_manifest": manifest,
            "summary": prepared.summary, "observation_count": len(prepared.observations)})
        operation["changed"] = True
        for obs in prepared.observations:
            contract.validate_observation(obs)
            await _insert(db, TABLE_ORDER[1], {"id": _stable("observation", prepared.source_json_sha256, obs["source_entry_id"]),
                **actor, "import_receipt_id": receipt_id, "source_entry_id": obs["source_entry_id"],
                "source_json_pointer": obs["source_json_pointer"], "source_json_sha256": prepared.source_json_sha256,
                "original_batch_sha256": prepared.original_batch_sha256, "registry_sha256": prepared.registry_sha256,
                "entry_sha256": obs["entry_sha256"], "field_id": obs["field_id"], "profile": obs["profile"],
                "revision_number": 1, "predecessor_id": None, "status": "pending", "association_status": "unestablished",
                "scientific_acceptance": False, "display_context_material_id": None,
                "projection_json": canonical(obs).decode("utf-8"), "projection_sha256": digest(obs)})
        return {**_import_dto(receipt), "dry_run": dry_run, "pending_ledger_written": not dry_run}


async def lookup_import(db, *, actor_user_id, request_key_value, expected_request_sha256):
    await _session(db, write=False)
    await _grant(db, actor_user_id, "curator")
    key, pin = request_key(request_key_value), checksum(expected_request_sha256)
    row = (await db.execute(sa.select(_table(TABLE_ORDER[0])).where(
        _table(TABLE_ORDER[0]).c.actor_user_id == identifier(actor_user_id),
        _table(TABLE_ORDER[0]).c.request_key == key))).mappings().one_or_none()
    if row is None:
        raise SourcePropertyNotFound("outcome_unavailable_not_proof_of_failure")
    if row["request_sha256"] != pin:
        raise SourcePropertyConflict("request_pin_conflict")
    return _import_dto(row, replayed=True)


def _review_request(value):
    keys = {"request_key", "observation_id", "observation_sha256", "expected_previous_review_id",
            "expected_previous_review_sha256", "scope", "action", "checks", "note", "source_inspection_attested"}
    require(type(value) is dict and set(value) == keys, "closed_review_request_required")
    request_key(value["request_key"])
    identifier(value["observation_id"])
    checksum(value["observation_sha256"])
    parent = value["expected_previous_review_id"]
    parent_hash = value["expected_previous_review_sha256"]
    require((parent is None) == (parent_hash is None), "paired_review_head_required")
    if parent is not None:
        identifier(parent)
        checksum(parent_hash)
    require(value["scope"] == "source_expression_fidelity_note" and value["action"] in ACTIONS,
            "source_note_scope_required")
    require(type(value["source_inspection_attested"]) is bool and value["source_inspection_attested"], "explicit_source_inspection_attestation_required")
    require(type(value["checks"]) is list and 1 <= len(value["checks"]) <= 6
            and all(type(item) is str and item in CHECKS for item in value["checks"])
            and len(set(value["checks"])) == len(value["checks"]), "closed_source_note_checks_required")
    require(type(value["note"]) is str and 1 <= len(value["note"]) <= 2000
            and value["note"] == value["note"].strip() and not any(ord(ch) < 32 for ch in value["note"]), "bounded_note_required")
    return value


def _review_dto(row, *, replayed=False, dry_run=False):
    return {"version": VERSION, "review_id": str(row["id"]), "review_sha256": row["record_sha256"],
        "actor_user_id": str(row["actor_user_id"]), "actor_grant_id": str(row["actor_grant_id"]),
        "actor_session_version": row["actor_session_version"],
        "source_note_sha256": row["review_sha256"],
        "observation_id": str(row["observation_id"]), "request_sha256": row["request_sha256"],
        "preview_sha256": row["preview_sha256"], "review_number": row["review_number"],
        "source_note": json.loads(row["review_json"]), "status": "pending", "scientific_acceptance": False,
        "canonical_promotions": 0, "selected_result_association": "unestablished", "replayed": replayed, "dry_run": dry_run,
        "pending_ledger_written": not dry_run}


async def append_review(db, *, actor_user_id, request, dry_run=True, expected_preview_sha256=None):
    request = _review_request(request)
    async with _write(db, dry_run) as operation:
        grant, session_version = await _grant(db, actor_user_id, "reviewer")
        reviews = _table(TABLE_ORDER[2])
        req_hash = digest(request)
        old = (await db.execute(sa.select(reviews).where(reviews.c.actor_user_id == identifier(actor_user_id),
            reviews.c.request_key == request["request_key"]))).mappings().one_or_none()
        if old is not None:
            if old["request_sha256"] != req_hash or expected_preview_sha256 not in {None, old["preview_sha256"]}:
                raise SourcePropertyConflict("review_request_conflict")
            return _review_dto(old, replayed=True)
        obs = await _row(db, TABLE_ORDER[1], request["observation_id"])
        if obs is None:
            raise SourcePropertyNotFound("observation_unavailable")
        if obs["record_sha256"] != request["observation_sha256"]:
            raise SourcePropertyConflict("observation_pin_conflict")
        head = (await db.execute(sa.select(reviews).where(reviews.c.observation_id == obs["id"])
            .order_by(reviews.c.review_number.desc()).limit(1))).mappings().one_or_none()
        parent_id, parent_hash = (None, None) if head is None else (str(head["id"]), head["record_sha256"])
        if parent_id != request["expected_previous_review_id"] or parent_hash != request["expected_previous_review_sha256"]:
            raise SourcePropertyConflict("review_head_conflict")
        if request["action"] == "withdraw_note" and (head is None or head["actor_user_id"] != identifier(actor_user_id)
                                                       or head["action"] == "withdraw_note"):
            raise SourcePropertyConflict("withdraw_own_preceding_note_required")
        actor = {"actor_user_id": identifier(actor_user_id), "actor_grant_id": grant["id"], "actor_session_version": session_version}
        preview = digest({"version": VERSION, "actor": _body(actor), "request_sha256": req_hash,
                          "observation_sha256": obs["record_sha256"], "previous_review_sha256": parent_hash})
        if not dry_run and (expected_preview_sha256 is None or expected_preview_sha256 != preview):
            raise SourcePropertyConflict("exact_preview_required")
        note = {key: request[key] for key in ("scope", "action", "observation_id", "observation_sha256",
                                            "source_inspection_attested", "checks", "note")}
        row = await _insert(db, TABLE_ORDER[2], {"id": _stable("review", actor_user_id, request["request_key"]), **actor,
            "request_key": request["request_key"], "request_sha256": req_hash, "preview_sha256": preview,
            "observation_id": obs["id"], "observation_sha256": obs["record_sha256"],
            "review_number": 1 if head is None else head["review_number"] + 1,
            "predecessor_id": None if head is None else head["id"], "predecessor_sha256": parent_hash,
            "action": request["action"], "review_json": canonical(note).decode("utf-8"), "review_sha256": digest(note)})
        operation["changed"] = True
        return _review_dto(row, dry_run=dry_run)


async def lookup_review(db, *, actor_user_id, request_key_value, expected_request_sha256):
    await _session(db, write=False)
    await _grant(db, actor_user_id, "reviewer")
    key, pin = request_key(request_key_value), checksum(expected_request_sha256)
    row = (await db.execute(sa.select(_table(TABLE_ORDER[2])).where(_table(TABLE_ORDER[2]).c.actor_user_id == identifier(actor_user_id),
           _table(TABLE_ORDER[2]).c.request_key == key))).mappings().one_or_none()
    if row is None:
        raise SourcePropertyNotFound("outcome_unavailable_not_proof_of_failure")
    if row["request_sha256"] != pin:
        raise SourcePropertyConflict("request_pin_conflict")
    return _review_dto(row, replayed=True)


def _observation_dto(row):
    projection = json.loads(row["projection_json"])
    contract.validate_observation(projection)
    require(digest(projection) == row["projection_sha256"] and digest(_body(row)) == row["record_sha256"], "observation_integrity_unavailable")
    return {"id": str(row["id"]), "record_sha256": row["record_sha256"], "revision_number": row["revision_number"],
        "source_json_sha256": row["source_json_sha256"], "original_batch_sha256": row["original_batch_sha256"],
        "registry_sha256": row["registry_sha256"], "projection_sha256": row["projection_sha256"], "projection": projection}


async def observations(db, *, actor_user_id, offset=0, limit=25, field_id=None, source_role=None, profile=None):
    await reader(db, actor_user_id)
    require(type(offset) is int and 0 <= offset <= 10000 and type(limit) is int and 1 <= limit <= 50, "bounded_pagination_required")
    table = _table(TABLE_ORDER[1])
    filters = []
    for name, value in (("field_id", field_id), ("profile", profile)):
        if value is not None:
            require(type(value) is str and 1 <= len(value) <= 160, "bounded_filter_required")
            filters.append(table.c[name] == value)
    if source_role is not None:
        require(type(source_role) is str and 1 <= len(source_role) <= 160, "bounded_filter_required")
        filters.append(sa.cast(table.c.projection_json, sa.JSON)["source_role"].as_string() == source_role)
    count = await db.scalar(sa.select(sa.func.count()).select_from(table).where(*filters))
    rows = (await db.execute(sa.select(table).where(*filters).order_by(table.c.source_json_sha256, table.c.source_json_pointer)
                            .offset(offset).limit(limit))).mappings().all()
    return {"version": VERSION, "total": count, "offset": offset, "limit": limit,
        "count_scope": "pending_source_task_observations_not_independent_experiments",
        "observations": [_observation_dto(row) for row in rows], "canonical_promotions": 0, "scientific_acceptance": False}


async def observation(db, *, actor_user_id, observation_id):
    await reader(db, actor_user_id)
    row = await _row(db, TABLE_ORDER[1], observation_id)
    if row is None:
        raise SourcePropertyNotFound("observation_unavailable")
    reviews = (await db.execute(sa.select(_table(TABLE_ORDER[2])).where(_table(TABLE_ORDER[2]).c.observation_id == row["id"])
        .order_by(_table(TABLE_ORDER[2]).c.review_number.desc()).limit(20))).mappings().all()
    count = await db.scalar(sa.select(sa.func.count()).select_from(_table(TABLE_ORDER[2])).where(_table(TABLE_ORDER[2]).c.observation_id == row["id"]))
    return {**_observation_dto(row), "source_notes": [_review_dto(review) for review in reviews],
            "source_notes_total": count, "source_notes_truncated": count > len(reviews)}
