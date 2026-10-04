"""Private owner append-only research designs with exact, rehearsed SQL receipts.

The authenticated caller owns its stable transaction. Source closures are
internal only. History survives drift but automatic source values are withheld.
No source retrieval, scientific object mutation, execution or approval occurs.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid5

import sqlalchemy as sa

from models.db import Base, Material
from models.discovery_design_v1 import TABLE_ORDER, LOCK_FUNCTION
from services import discovery_design_contract as contract
from services import material_field_cases as field_cases
from services.material_source_scope import current_visibility_allows_view
from services.material_visibility_adapter import material_view
from services.material_visibility import normalize_source_status
from services.research_release_manifest import canonical, digest
from services.source_lifecycle import resolve_paper_lifecycle, resolve_work_lifecycle
from services.source_lifecycle_status import lifecycle_review_required, lifecycle_status
from services.source_property_pending import SourcePropertyConflict, SourcePropertyNotFound, _grant, _session, identifier, request_key, checksum

VERSION = contract.VERSION
_NAMESPACE = UUID("a112d08b-d3de-4380-bf3d-bf7ee2831b21")
_ABSENT = ("field_case_material_unavailable", "field_case_record_unavailable", "field_case_native_closure_unavailable",
           "field_case_state_closure_unavailable", "field_case_sample_closure_unavailable", "scientific_subject_source_unavailable")


def table():
    return Base.metadata.tables[TABLE_ORDER[0]]


def text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable(*parts):
    return uuid5(_NAMESPACE, digest([str(value) for value in parts]))


def _body(row):
    return {str(key): str(value) if isinstance(value, UUID) else value for key, value in row.items()
            if key not in {"created_at", "record_sha256", "context_json", "projection"}}


def intact(row):
    contract.require(digest(_body(row)) == row["record_sha256"], "design_receipt_integrity_unavailable")
    contract.validate(json.loads(row["request_json"]))
    contract.require(text_sha(row["request_json"]) == row["request_sha256"]
                     and text_sha(row["preview_json"]) == row["preview_sha256"]
                     and text_sha(row["context_json"]) == row["context_sha256"], "design_proof_integrity_unavailable")


async def reader(db, actor):
    await _session(db, write=False)
    await db.execute(sa.text("SET LOCAL statement_timeout = '5000ms'"))
    return await _grant(db, actor, "curator")


async def capabilities(db, *, actor_user_id):
    grant, session = await reader(db, actor_user_id)
    return {"version": VERSION, "request_version": contract.REQUEST_VERSION,
        "actor_user_id": str(identifier(actor_user_id)), "session_version": session,
        "curator_grant_id": str(grant["id"]), "can_write": True,
        "baseline_kinds": ["unanchored", "retained_result", "native_property"],
        "modification_kinds": list(contract.MODIFICATIONS), "pairing_hypotheses": list(contract.PAIRING),
        "action_kinds": list(contract.ACTION_KINDS), "decisions": list(contract.DECISIONS),
        "budget_resources": list(contract.RESOURCES), "max_page_size": contract.MAX_PAGE,
        "max_operation_bytes": contract.MAX_BYTES, **contract.AUTHORITY}


async def sql_context(db, baseline):
    contract.baseline(baseline)
    captured = await db.scalar(sa.text("SELECT public.sclib_discovery_design_context_v1(CAST(:baseline AS jsonb))"),
                               {"baseline": canonical(baseline).decode()})
    contract.require(type(captured) is str and len(captured.encode()) <= 9437184, "design_context_bound")
    return captured


async def sql_projection_text(db, captured):
    # Hash PostgreSQL's exact canonical representation, not float reserialization.
    result = await db.scalar(sa.text("SELECT public.sclib_scientific_import_canonical_v1(public.sclib_discovery_design_projection_v1(:captured))"), {"captured": captured})
    contract.require(type(result) is str and len(result.encode()) <= 8192, "design_projection_bound")
    return result


async def sql_projection(db, captured):
    result = await sql_projection_text(db, captured)
    return json.loads(result), text_sha(result)


async def eligibility(db, captured, baseline):
    reasons = []
    try:
        async with db.begin_nested():
            current = await sql_context(db, baseline)
    except sa.exc.DBAPIError as error:
        code = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
        if code != "23514" or not any(reason in str(error.orig) for reason in _ABSENT):
            raise
        current = None
    if current != captured:
        reasons.append("source_context_changed")
    body = json.loads(captured)
    if body["kind"] == "retained_result":
        old = await db.scalar(sa.text("SELECT public.sclib_scientific_import_canonical_v1(CAST(:captured AS jsonb)->'base')"), {"captured": captured})
        target = {"kind": "retained_result", "material_id": baseline["material_id"], "record_index": baseline["record_index"],
                  "entity_id": None, "expected_context_sha256": field_cases.text_sha(old)}
        eligible = await field_cases.eligibility(db, old, target)
        reasons.extend(eligible["reason_codes"])
    elif body["kind"] == "native_property":
        view = await material_view(db, await db.get(Material, baseline["material_id"]))
        if view is None or not current_visibility_allows_view(view.visibility):
            reasons.append("material_not_currently_eligible")
        event = body["base"]["event"]
        # Negative local governance is a read hold. Pending or positive labels
        # never confer scientific validity on a proposal or on its baseline.
        if event.get("validity_status") in {"disputed", "retracted", "excluded"} or event.get("review_status") == "rejected":
            reasons.append("native_event_held")
        if current is not None:
            current_event = json.loads(current)["base"]["event"]
            if current_event.get("validity_status") in {"disputed", "retracted", "excluded"} or current_event.get("review_status") == "rejected":
                reasons.append("native_event_held")
    if body["kind"] != "unanchored":
        papers = [item["id"] for item in body["sources"] if item["kind"] == "paper"]
        works = [item["id"] for item in body["sources"] if item["kind"] == "work"]
        states = [*(await resolve_paper_lifecycle(db, papers)).values(), *(await resolve_work_lifecycle(db, works)).values()]
        if any(lifecycle_review_required(item) or normalize_source_status(item) in {"retracted", "corrected"}
               or str(lifecycle_status(item)).lower() == "disputed" for item in states):
            reasons.append("source_lifecycle_held")
    return {"eligible": not reasons, "reason_codes": sorted(set(reasons))}


async def context(db, *, actor_user_id, kind="unanchored", material_id=None, record_index=None, property_id=None):
    _, session = await reader(db, actor_user_id)
    baseline = {"kind": kind, "material_id": material_id, "record_index": record_index,
                "property_id": property_id, "expected_context_sha256": "0" * 64}
    captured = await sql_context(db, baseline)
    baseline["expected_context_sha256"] = text_sha(captured)
    eligible = await eligibility(db, captured, baseline)
    projection_text = await sql_projection_text(db, captured)
    projection, projection_sha = json.loads(projection_text), text_sha(projection_text)
    return {"version": VERSION, "actor_user_id": str(identifier(actor_user_id)), "session_version": session,
            "baseline": baseline, "context_sha256": baseline["expected_context_sha256"],
            "projection": projection if eligible["eligible"] else None,
            "projection_canonical_json": projection_text if eligible["eligible"] else None,
            "projection_sha256": projection_sha, "eligibility": eligible, **contract.AUTHORITY}


@asynccontextmanager
async def write(db, dry_run):
    contract.require(type(dry_run) is bool, "boolean_preview_required")
    await _session(db, write=True)
    await db.execute(sa.text("SET LOCAL statement_timeout = '5000ms'"))
    savepoint = await db.begin_nested()
    changed = {"value": False}
    try:
        await db.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
        yield changed
        if dry_run or not changed["value"]:
            await savepoint.rollback()
        else:
            await savepoint.commit()
    except BaseException:
        if savepoint.is_active:
            await savepoint.rollback()
        raise


def receipt(row, *, replayed=False, dry_run=False):
    intact(row)
    return {"version": VERSION, "receipt_id": str(row["id"]), "receipt_sha256": row["record_sha256"],
        "design_id": str(row["design_id"]), "revision": row["revision"], "operation": row["operation"],
        "status": "withdrawn" if row["operation"] == "withdraw" else "proposed",
        "actor_user_id": str(row["actor_user_id"]), "actor_grant_id": str(row["actor_grant_id"]),
        "actor_session_version": row["actor_session_version"], "request_key": row["request_key"],
        "request_sha256": row["request_sha256"], "preview_sha256": row["preview_sha256"],
        "request_canonical_json": row["request_json"], "preview_canonical_json": row["preview_json"],
        "receipt_canonical_json": canonical(_body(row)).decode(), "replayed": replayed,
        "dry_run": dry_run, "pending_ledger_written": not dry_run, **contract.AUTHORITY}


async def _row(db, actor, row_id):
    row = (await db.execute(sa.select(table()).where(table().c.id == identifier(row_id), table().c.actor_user_id == identifier(actor)))).mappings().one_or_none()
    if row is None:
        raise SourcePropertyNotFound("design_record_unavailable")
    intact(row)
    return row


async def _head(db, actor, design_id):
    row = (await db.execute(sa.select(table()).where(table().c.design_id == identifier(design_id), table().c.actor_user_id == identifier(actor)).order_by(table().c.revision.desc()).limit(1))).mappings().one_or_none()
    if row is None:
        raise SourcePropertyNotFound("design_record_unavailable")
    intact(row)
    return row


async def operate(db, *, actor_user_id, request, dry_run=True, expected_preview_sha256=None):
    request = contract.snapshot(request)  # Before the first await.
    if expected_preview_sha256 is not None:
        checksum(expected_preview_sha256)
    op, payload = request["operation"], request["payload"]
    request_text = canonical(request).decode()
    request_sha = text_sha(request_text)
    async with write(db, dry_run) as changed:
        grant, session = await _grant(db, actor_user_id, "curator")
        old = (await db.execute(sa.select(table()).where(table().c.actor_user_id == identifier(actor_user_id), table().c.request_key == request["request_key"]))).mappings().one_or_none()
        if old is not None:
            if old["request_sha256"] != request_sha or expected_preview_sha256 not in {None, old["preview_sha256"]}:
                raise SourcePropertyConflict("design_request_conflict")
            return receipt(old, replayed=True)
        revision_id = _stable("revision", actor_user_id, request["request_key"])
        previous_id = previous_sha = None
        if op == "propose":
            design_id, revision = _stable("design", actor_user_id, request["request_key"]), 1
        else:
            previous = await _head(db, actor_user_id, payload["design_id"])
            if previous["operation"] == "withdraw" or payload["predecessor"] != {"id": str(previous["id"]), "record_sha256": previous["record_sha256"]}:
                raise SourcePropertyConflict("design_exact_owner_head_required")
            design_id, revision = previous["design_id"], previous["revision"] + 1
            previous_id, previous_sha = previous["id"], previous["record_sha256"]
        if op == "withdraw":
            baseline, design, parent = previous["baseline"], previous["design"], previous["parent"]
            captured, projection, projection_sha = previous["context_json"], previous["projection"], previous["projection_sha256"]
        else:
            baseline, design, parent = payload["baseline"], payload["design"], payload["parent"]
            captured = await sql_context(db, baseline)
            if text_sha(captured) != baseline["expected_context_sha256"]:
                raise SourcePropertyConflict("design_source_pin_changed")
            eligible = await eligibility(db, captured, baseline)
            if not eligible["eligible"]:
                raise SourcePropertyConflict("design_source_not_currently_eligible")
            projection, projection_sha = await sql_projection(db, captured)
            if op == "revise" and parent != previous["parent"]:
                raise SourcePropertyConflict("design_parent_fixed_per_chain")
            if parent is not None:
                parent_row = await _row(db, actor_user_id, parent["revision_id"])
                head = await _head(db, actor_user_id, parent["design_id"])
                if str(parent_row["design_id"]) != parent["design_id"] or parent_row["record_sha256"] != parent["record_sha256"] or parent_row["operation"] == "withdraw" or head["operation"] == "withdraw":
                    raise SourcePropertyConflict("design_owner_parent_unavailable")
        actor = {"actor_user_id": identifier(actor_user_id), "actor_grant_id": grant["id"], "actor_session_version": session}
        preview = {"version": VERSION, "actor": {k: str(v) if isinstance(v, UUID) else v for k, v in actor.items()},
                   "request_sha256": request_sha, "receipt_id": str(revision_id), "design_id": str(design_id),
                   "revision": revision, "context_sha256": text_sha(captured)}
        preview_text = canonical(preview).decode()
        preview_sha = text_sha(preview_text)
        if not dry_run and expected_preview_sha256 != preview_sha:
            raise SourcePropertyConflict("design_exact_preview_required")
        values = {"id": revision_id, "design_id": design_id, "revision": revision, **actor, "operation": op,
            "request_key": request["request_key"], "request_json": request_text, "payload": payload,
            "request_sha256": request_sha, "preview_json": preview_text, "preview_sha256": preview_sha,
            "baseline": baseline, "design": design, "parent": parent, "predecessor_id": previous_id,
            "predecessor_sha256": previous_sha, "context_json": captured, "context_sha256": text_sha(captured),
            "projection": projection, "projection_sha256": projection_sha,
            **{k: v for k, v in contract.AUTHORITY.items() if k != "scope"}}
        values["record_sha256"] = digest(_body(values))
        inserted = (await db.execute(table().insert().values(**values).returning(table()))).mappings().one()
        changed["value"] = True
        return receipt(inserted, dry_run=dry_run)


async def outcome(db, *, actor_user_id, request_key_value, expected_request_sha256):
    await reader(db, actor_user_id)
    key, pin = request_key(request_key_value), checksum(expected_request_sha256)
    row = (await db.execute(sa.select(table()).where(table().c.actor_user_id == identifier(actor_user_id), table().c.request_key == key))).mappings().one_or_none()
    if row is None:
        raise SourcePropertyNotFound("outcome_unavailable_not_proof_of_failure")
    if row["request_sha256"] != pin:
        raise SourcePropertyConflict("design_request_pin_conflict")
    return receipt(row, replayed=True)


async def _entry(db, row, *, is_head):
    intact(row)
    eligible = await eligibility(db, row["context_json"], row["baseline"])
    projection_text = await sql_projection_text(db, row["context_json"])
    projection, sha = json.loads(projection_text), text_sha(projection_text)
    contract.require(sha == row["projection_sha256"] and projection == row["projection"], "design_projection_integrity_unavailable")
    return {"id": str(row["id"]), "record_sha256": row["record_sha256"], "design_id": str(row["design_id"]),
        "revision": row["revision"], "operation": row["operation"], "status": "withdrawn" if row["operation"] == "withdraw" else "proposed",
        "is_head": is_head, "baseline": row["baseline"], "design": row["design"], "parent": row["parent"],
        "predecessor": None if row["predecessor_id"] is None else {"id": str(row["predecessor_id"]), "record_sha256": row["predecessor_sha256"]},
        "context_sha256": row["context_sha256"], "projection_sha256": row["projection_sha256"],
        "projection": projection if eligible["eligible"] else None,
        "projection_canonical_json": projection_text if eligible["eligible"] else None, "eligibility": eligible,
        "receipt": receipt(row), **contract.AUTHORITY}


async def designs(db, *, actor_user_id, offset=0, limit=8):
    _, session = await reader(db, actor_user_id)
    contract.require(type(offset) is int and 0 <= offset <= 1000 and type(limit) is int and 1 <= limit <= contract.MAX_PAGE, "design_page_bound")
    successor = table().alias("successor")
    base = sa.select(table()).where(table().c.actor_user_id == identifier(actor_user_id),
        ~sa.exists(sa.select(successor.c.id).where(successor.c.predecessor_id == table().c.id)))
    total = await db.scalar(sa.select(sa.func.count()).select_from(base.subquery()))
    rows = (await db.execute(base.order_by(table().c.created_at.desc(), table().c.id).offset(offset).limit(limit))).mappings().all()
    return {"version": VERSION, "actor_user_id": str(identifier(actor_user_id)), "session_version": session,
            "offset": offset, "limit": limit, "total": total, "entries": [await _entry(db, row, is_head=True) for row in rows], **contract.AUTHORITY}


async def design_detail(db, *, actor_user_id, design_id):
    _, session = await reader(db, actor_user_id)
    head = await _head(db, actor_user_id, design_id)
    rows = (await db.execute(sa.select(table()).where(table().c.design_id == head["design_id"], table().c.actor_user_id == identifier(actor_user_id)).order_by(table().c.revision.desc()).limit(contract.MAX_PAGE))).mappings().all()
    return {"version": VERSION, "actor_user_id": str(identifier(actor_user_id)), "session_version": session,
        "design_id": str(head["design_id"]), "revision_total": head["revision"], "history_limit": contract.MAX_PAGE,
        "entries": [await _entry(db, row, is_head=row["id"] == head["id"]) for row in rows], **contract.AUTHORITY}
