"""Private pending target/proposal/attempt ledger and eligible material adapter."""
from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid5
from contextlib import asynccontextmanager

import sqlalchemy as sa

from models.db import Base, Material
from models.material_field_cases_v1 import TABLE_ORDER
from services import material_field_case_contract as contract
from services import source_expression_intake_v2 as expressions
from services.material_visibility_adapter import material_view
from services.material_visibility import normalize_source_status, visibility_allows_view
from services.property_evidence import legacy_result_id
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical, digest
from services.source_lifecycle import resolve_paper_lifecycle, resolve_work_lifecycle
from services.source_lifecycle_status import lifecycle_review_required
from services.source_property_pending import (_body, _grant, _insert, _session, checksum,
    identifier, reader, require, request_key, SourcePropertyConflict, SourcePropertyNotFound)

VERSION = contract.VERSION
NAMESPACE = UUID("b2377ff3-e435-4cf1-a565-c43471b2abe8")
FIELD_MAP = {"measurement_method": "method_statement", "sample_form": "sample_form_statement",
    "space_group": "structure_statement", "crystal_structure": "structure_statement",
    "pairing_symmetry": "classification_statement", "gap_structure": "classification_statement",
    "is_unconventional": "classification_statement", "competing_order": "classification_statement"}


def table(operation):
    return Base.metadata.tables[TABLE_ORDER[("target", "association", "attempt").index(operation)]]


def text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def intact(row):
    require(digest(_body(row)) == row["record_sha256"], "field_case_receipt_integrity_unavailable")
    contract.validate(json.loads(row["request_json"]))
    require(text_sha(row["request_json"]) == row["request_sha256"]
            and text_sha(row["context_json"]) == row["context_sha256"]
            and text_sha(row["preview_json"]) == row["preview_sha256"], "field_case_proof_integrity_unavailable")


async def row_by_id(db, operation, row_id):
    row = (await db.execute(sa.select(table(operation)).where(table(operation).c.id == identifier(row_id)))).mappings().one_or_none()
    if row is None:
        raise SourcePropertyNotFound("field_case_record_unavailable")
    intact(row)
    return row


async def sql_context(db, target):
    contract.selector(target)
    result = await db.scalar(sa.text("SELECT public.sclib_material_field_context_v1(CAST(:target AS jsonb))"),
                             {"target": canonical(target).decode()})
    require(type(result) is str and len(result.encode()) <= 131072, "field_case_context_bound")
    return result


def closure(body):
    result, event, state, sample = body["result"], body["event"], body["state"], body["sample"]
    raw = result if body["kind"] == "retained_result" else result.get("raw_record") if body["kind"] == "tc_claim" else None
    return {"material_id": body["material_id"], "kind": body["kind"], "record_index": body["record_index"],
        "entity_id": body["entity_id"], "paper_id": result.get("paper_id"), "work_id": result.get("work_id"),
        "event_id": None if event is None else event["id"], "state_id": None if state is None else state["id"],
        "sample_id": None if sample is None else sample["id"],
        "legacy_result_id": legacy_result_id(raw, scope_id=body["material_id"]) if isinstance(raw, dict) else None,
        "retained_record_sha256": digest(raw) if isinstance(raw, dict) else None}


async def eligibility(db, context_text, target):
    reasons = []
    try:
        # Only controlled closure disappearance is a history disposition.
        # A savepoint keeps the read transaction usable after that SQL guard;
        # integrity, syntax, permissions, timeout and database faults propagate.
        async with db.begin_nested():
            current = await sql_context(db, target)
    except sa.exc.DBAPIError as error:
        original = error.orig
        code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
        absent = ("field_case_material_unavailable", "field_case_record_unavailable",
                  "field_case_native_closure_unavailable", "field_case_state_closure_unavailable",
                  "field_case_sample_closure_unavailable")
        if code != "23514" or not any(reason in str(original) for reason in absent):
            raise
        current = None
    if current != context_text:
        reasons.append("target_fingerprint_changed")
    body = json.loads(context_text)
    material = await material_view(db, await db.get(Material, body["material_id"]))
    if material is None or not visibility_allows_view(material.visibility):
        reasons.append("material_not_currently_eligible")
    else:
        result = body["result"]
        raw = result if body["kind"] == "retained_result" else result.get("raw_record") if body["kind"] == "tc_claim" else None
        current_refs = {(r.get("paper_id"), legacy_result_id(r, scope_id=material.id), digest(r))
                        for r in material.current_records() if isinstance(r, dict)}
        if not isinstance(raw, dict) or (raw.get("paper_id"), legacy_result_id(raw, scope_id=material.id), digest(raw)) not in current_refs:
            reasons.append("native_source_binding_unavailable" if body["kind"] != "retained_result" else "material_not_currently_eligible")
        elif body["kind"] == "tc_claim" and (result.get("paper_id") != raw.get("paper_id") or result.get("validity_status") in {"disputed", "retracted", "excluded"}):
            reasons.append("native_source_binding_unavailable")
    return {"eligible": not reasons, "reason_codes": sorted(set(reasons))}


async def context(db, *, actor_user_id, material_id, kind="retained_result", record_index=None, entity_id=None):
    _, session = await reader(db, actor_user_id)
    target = {"kind": kind, "material_id": material_id, "record_index": record_index, "entity_id": entity_id,
              "expected_context_sha256": "0" * 64}
    body = await sql_context(db, target)
    sha = text_sha(body)
    target["expected_context_sha256"] = sha
    return {"version": VERSION, "actor_user_id": str(actor_user_id), "session_version": session,
        "target": target, "context_canonical_json": body, "context_sha256": sha,
        "closure": closure(json.loads(body)), "eligibility": await eligibility(db, body, target), **contract.AUTHORITY}


async def capabilities(db, *, actor_user_id):
    _, session = await reader(db, actor_user_id)
    try:
        grant, _ = await _grant(db, actor_user_id, "curator")
    except ResearchAccessDenied:
        grant = None
    return {"version": VERSION, "request_version": contract.REQUEST_VERSION,
        "actor_user_id": str(actor_user_id), "session_version": session,
        "curator_grant_id": None if grant is None else str(grant["id"]), "can_write": grant is not None,
        "field_ids": list(contract.FIELDS), "outcomes": list(contract.OUTCOMES), "reason_codes": list(contract.REASONS),
        "expression_field_map": {field: FIELD_MAP.get(field, field) if FIELD_MAP.get(field, field) in expressions.contract.FIELDS else
            "tc_kelvin:criterion_statement:reported_result_condition" if field == "tc_criterion" else None for field in contract.FIELDS},
        "max_page_size": 8, "max_operation_bytes": contract.MAX_BYTES, **contract.AUTHORITY}


@asynccontextmanager
async def write(db, dry_run):
    require(type(dry_run) is bool, "boolean_preview_required")
    await _session(db, write=True)
    savepoint = await db.begin_nested()
    changed = {"value": False}
    try:
        await db.execute(sa.text("SELECT public.sclib_material_field_lock_v1()"))
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
        "operation": row["operation"], "target_id": str(row["id"] if row["operation"] == "target" else row["target_id"]),
        "actor_user_id": str(row["actor_user_id"]), "actor_grant_id": str(row["actor_grant_id"]),
        "actor_session_version": row["actor_session_version"], "request_key": row["request_key"],
        "request_sha256": row["request_sha256"], "preview_sha256": row["preview_sha256"],
        "request_canonical_json": row["request_json"], "preview_canonical_json": row["preview_json"],
        "receipt_canonical_json": canonical(_body(row)).decode(), "replayed": replayed, "dry_run": dry_run,
        "pending_ledger_written": not dry_run, **contract.AUTHORITY}


async def operate(db, *, actor_user_id, request, dry_run=True, expected_preview_sha256=None):
    contract.validate(request)
    op, p = request["operation"], request["payload"]
    request_text = canonical(request).decode()
    request_sha = text_sha(request_text)
    async with write(db, dry_run) as changed:
        grant, session = await _grant(db, actor_user_id, "curator")
        # Keys span all three tables, preventing uncertain-outcome type changes.
        for name in TABLE_ORDER:
            t = Base.metadata.tables[name]
            old = (await db.execute(sa.select(t).where(t.c.actor_user_id == identifier(actor_user_id),
                                                       t.c.request_key == request["request_key"]))).mappings().one_or_none()
            if old is not None:
                if old["request_sha256"] != request_sha or expected_preview_sha256 not in {None, old["preview_sha256"]}:
                    raise SourcePropertyConflict("field_case_request_conflict")
                return receipt(old, replayed=True)
        target_id = expression_id = expression_sha = chain = previous_id = previous_sha = None
        if op == "target":
            context_text = await sql_context(db, p["target"])
            if text_sha(context_text) != p["target"]["expected_context_sha256"]:
                raise SourcePropertyConflict("field_case_target_fingerprint_changed")
            field = p["field_id"]
        else:
            target = await row_by_id(db, "target", p["target_id"])
            if target["record_sha256"] != p["target_sha256"]:
                raise SourcePropertyConflict("field_case_target_pin_changed")
            context_text, target_id, field = target["context_json"], target["id"], target["field_id"]
            if p["predecessor"] is not None:
                previous_id = identifier(p["predecessor"]["id"])
                previous_sha = p["predecessor"]["record_sha256"]
            if op == "association":
                expression = await expressions.expression(db, actor_user_id=actor_user_id, revision_id=p["expression_revision_id"])
                if expression["record_sha256"] != p["expression_record_sha256"]:
                    raise SourcePropertyConflict("field_case_expression_pin_changed")
                expression_id, expression_sha = identifier(expression["id"]), expression["record_sha256"]
                chain = digest([str(target_id), expression["expression_key"]])
            else:
                chain = str(target_id)
        row_id = uuid5(NAMESPACE, digest([str(actor_user_id), request["request_key"]]))
        actor = {"actor_user_id": identifier(actor_user_id), "actor_grant_id": grant["id"], "actor_session_version": session}
        context_sha = text_sha(context_text)
        preview_text = canonical({"version": VERSION, "actor": _body(actor), "request_sha256": request_sha,
                                  "receipt_id": str(row_id), "context_sha256": context_sha}).decode()
        preview_sha = text_sha(preview_text)
        if not dry_run and expected_preview_sha256 != preview_sha:
            raise SourcePropertyConflict("field_case_exact_preview_required")
        row = {"id": row_id, **actor, "operation": op, "request_key": request["request_key"],
            "request_json": request_text, "payload": p, "request_sha256": request_sha,
            "preview_json": preview_text, "preview_sha256": preview_sha, "context_json": context_text,
            "context_sha256": context_sha, "field_id": field, "target_id": target_id, "chain_key": chain,
            "predecessor_id": previous_id, "predecessor_sha256": previous_sha,
            "expression_revision_id": expression_id, "expression_record_sha256": expression_sha}
        row["record_sha256"] = digest(_body(row))
        await _insert(db, table(op).name, row)
        changed["value"] = True
        return receipt(row, dry_run=dry_run)


async def outcome(db, *, actor_user_id, request_key_value, expected_request_sha256):
    await reader(db, actor_user_id)
    key, pin = request_key(request_key_value), checksum(expected_request_sha256)
    for name in TABLE_ORDER:
        t = Base.metadata.tables[name]
        row = (await db.execute(sa.select(t).where(t.c.actor_user_id == identifier(actor_user_id), t.c.request_key == key))).mappings().one_or_none()
        if row is not None:
            if row["request_sha256"] != pin:
                raise SourcePropertyConflict("field_case_outcome_pin_changed")
            return receipt(row, replayed=True)
    raise SourcePropertyNotFound("field_case_outcome_unavailable_not_proof_of_failure")


async def entry(db, row, *, actor_user_id, include_expression=False, expression_budget=None):
    intact(row)
    target = row if row["operation"] == "target" else await row_by_id(db, "target", str(row["target_id"]))
    state = await eligibility(db, target["context_json"], target["payload"]["target"])
    result = {"id": str(row["id"]), "record_sha256": row["record_sha256"], "operation": row["operation"],
        "record_canonical_json": canonical(_body(row)).decode(),
        "payload": row["payload"], "context_canonical_json": row["context_json"] if row["operation"] == "target" else None,
        "context_sha256": row["context_sha256"],
        "created_at": row["created_at"].isoformat(), "eligibility": state, **contract.AUTHORITY}
    if row["operation"] != "target":
        t = table(row["operation"])
        result["is_head"] = not bool(await db.scalar(sa.select(sa.exists().where(t.c.predecessor_id == row["id"]))))
    if row["operation"] == "association":
        reasons = list(state["reason_codes"])
        if not result["is_head"] or row["payload"]["action"] == "withdraw":
            reasons.append("association_unresolved")
        expression_row = (await db.execute(sa.select(expressions._table(2)).where(
            expressions._table(2).c.id == row["expression_revision_id"]))).mappings().one()
        expression = await expressions._expression_dto(db, expression_row, include_receipt=False)
        if not expression["is_expression_head"]:
            reasons.append("expression_superseded")
        source = row["payload"]["source_identity"]
        if source["paper_id"] is None:
            reasons.append("source_identity_unresolved")
        else:
            status = (await resolve_paper_lifecycle(db, [source["paper_id"]])).get(source["paper_id"])
            if normalize_source_status(status) != "active" or lifecycle_review_required(status):
                reasons.append("source_lifecycle_held")
        if source["work_id"] is not None:
            status = (await resolve_work_lifecycle(db, [source["work_id"]])).get(source["work_id"])
            if normalize_source_status(status) != "active" or lifecycle_review_required(status):
                reasons.append("source_lifecycle_held")
        capture_source = expression["capture"]["source"]
        if capture_source["rights_status"] == "restricted" or capture_source["currentness"] == "historical":
            reasons.append("source_lifecycle_held")
        result["eligibility"] = {"eligible": not reasons, "reason_codes": sorted(set(reasons))}
        permitted = include_expression and not reasons
        if permitted and expression_budget is not None:
            if expression_budget["remaining"]:
                expression_budget["remaining"] -= 1
                expression_budget["returned"] += 1
            else:
                permitted = False
                expression_budget["omitted"] += 1
        result["expression"] = expression if permitted else None
        result["source_identity_status"] = "proposed"
    return result


def bounds(offset, limit):
    require(type(offset) is int and 0 <= offset <= 100000 and type(limit) is int and 1 <= limit <= 8,
            "field_case_page_bound")


async def targets(db, *, actor_user_id, offset=0, limit=8, material_id=None, field_id=None, byte_bound=True):
    _, session = await reader(db, actor_user_id)
    bounds(offset, limit)
    t, filters = table("target"), []
    if material_id is not None:
        contract.bounded_text(material_id, 100)
        filters.append(t.c.payload["target"]["material_id"].astext == material_id)
    if field_id is not None:
        require(field_id in contract.FIELDS, "field_case_field_filter")
        filters.append(t.c.field_id == field_id)
    total = await db.scalar(sa.select(sa.func.count()).select_from(t).where(*filters))
    rows = (await db.execute(sa.select(t).where(*filters).order_by(t.c.created_at, t.c.id).offset(offset).limit(limit))).mappings().all()
    result = {"version": VERSION, "actor_user_id": str(actor_user_id), "session_version": session,
        "total": total, "offset": offset, "limit": limit,
        "entries": [await entry(db, row, actor_user_id=actor_user_id) for row in rows], **contract.AUTHORITY}
    return bounded_response(result) if byte_bound else result


async def target_detail(db, *, actor_user_id, target_id, include_expression=True, expression_budget=None):
    _, session = await reader(db, actor_user_id)
    target = await row_by_id(db, "target", target_id)
    result = {"version": VERSION, "actor_user_id": str(actor_user_id), "session_version": session,
        "target": await entry(db, target, actor_user_id=actor_user_id), **contract.AUTHORITY}
    for operation, listkey, totalkey, returnedkey in (("association", "associations", "association_total", "association_returned"),
                                                     ("attempt", "attempts", "attempt_total", "attempt_returned")):
        t = table(operation)
        filters = [t.c.target_id == target["id"]]
        result[totalkey] = await db.scalar(sa.select(sa.func.count()).select_from(t).where(*filters))
        successor = t.alias("successor")
        head = ~sa.exists(sa.select(successor.c.id).where(successor.c.predecessor_id == t.c.id).correlate(t))
        rows = (await db.execute(sa.select(t).where(*filters).order_by(head.desc(), t.c.created_at.desc(), t.c.id.desc()).limit(8))).mappings().all()
        result[listkey] = [await entry(db, row, actor_user_id=actor_user_id, include_expression=include_expression,
                                       expression_budget=expression_budget) for row in rows]
        result[returnedkey] = len(rows)
    return bounded_response(result)


async def material_adapter(db, *, actor_user_id, material_id, offset=0, limit=8):
    _, session = await reader(db, actor_user_id)
    page = await targets(db, actor_user_id=actor_user_id, material_id=material_id, offset=offset, limit=limit, byte_bound=False)
    material = await material_view(db, await db.get(Material, material_id))
    allowed = material is not None and visibility_allows_view(material.visibility)
    # No private source expression is returned through an ineligible material.
    budget = {"remaining": 8, "returned": 0, "omitted": 0}
    entries = [await target_detail(db, actor_user_id=actor_user_id, target_id=row["id"], include_expression=allowed,
                                   expression_budget=budget)
               for row in page["entries"]]
    result = {"version": VERSION, "actor_user_id": str(actor_user_id), "session_version": session,
        "material_id": material_id, "total": page["total"], "offset": offset, "limit": limit, "entries": entries,
        "eligibility": {"eligible": allowed, "reason_codes": [] if allowed else ["material_not_currently_eligible"]},
        "expressions_returned": budget["returned"], "expressions_omitted": budget["omitted"], **contract.AUTHORITY}
    return bounded_response(result)


def bounded_response(result):
    """Account for JSON escaping before egress; never truncate canonical text."""
    maximum = 2 * 1024 * 1024 - 4096
    result["response_truncated"] = False
    if "entries" in result:
        available = len(result["entries"])
        result["entries_returned"], result["entries_omitted"] = available, 0
        result["next_offset"] = result["offset"] + available if result["offset"] + available < result["total"] else None
        while len(canonical(result)) > maximum and result["entries"]:
            result["entries"].pop()
            result["entries_returned"] -= 1
            result["entries_omitted"] += 1
            result["response_truncated"] = True
        result["next_offset"] = result["offset"] + result["entries_returned"] if result["offset"] + result["entries_returned"] < result["total"] else None
        require(result["entries_returned"] or result["offset"] >= result["total"], "field_case_response_bound")
    else:
        for kind in ("association", "attempt"):
            result[kind + "_omitted"] = result[kind + "_total"] - result[kind + "_returned"]
        while len(canonical(result)) > maximum:
            key = "associations" if result["associations"] else "attempts"
            require(result[key], "field_case_response_bound")
            result[key].pop()
            kind = "association" if key == "associations" else "attempt"
            result[kind + "_returned"] -= 1
            result[kind + "_omitted"] += 1
            result["response_truncated"] = True
    if "expressions_returned" in result:
        actual = sum(1 for detail in result["entries"] for a in detail["associations"] if a["expression"] is not None)
        result["expressions_omitted"] += result["expressions_returned"] - actual
        result["expressions_returned"] = actual
    require(len(canonical(result)) <= maximum, "field_case_response_bound")
    return result
