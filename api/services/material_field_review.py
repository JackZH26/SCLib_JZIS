"""Reviewer-only, rollback-rehearsed private metadata appends."""
from __future__ import annotations

import json
from uuid import UUID, uuid5

import sqlalchemy as sa

from models.db import Base
from models.material_field_review_v1 import TABLE_ORDER
from services import material_field_cases as cases
from services import material_field_review_contract as contract
from services import source_expression_intake_v2 as expressions
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical, digest
from services.source_property_pending import (
    SourcePropertyConflict,
    SourcePropertyNotFound,
    _body,
    _grant,
    _insert,
    checksum,
    identifier,
    reader,
    request_key,
    require,
)

NAMESPACE = UUID("fd2218c7-4291-4295-88a7-041c29393722")


def table(index):
    return Base.metadata.tables[TABLE_ORDER[index]]


def intact(row):
    require(digest(_body(row)) == row["record_sha256"], "field_review_receipt_integrity")


async def subject(db, selector):
    contract.subject(selector)
    result = await db.scalar(sa.text("SELECT public.sclib_material_field_review_subject_v1(CAST(:p AS jsonb))"),
                             {"p": canonical(selector).decode()})
    require(type(result) is dict and len(canonical(result)) <= 65536, "field_review_subject_bound")
    return result


async def context(db, *, actor_user_id, target_id, field_id, expression_revision_id, component_index=0,
                  component_kind="condition", association_id=None, tc_expression_revision_id=None):
    _, session = await reader(db, actor_user_id)
    target = await cases.row_by_id(db, "target", target_id)
    expression = await expressions.expression(db, actor_user_id=actor_user_id, revision_id=expression_revision_id)
    def pin(row):
        return {"id": row["id"], "record_sha256": row["record_sha256"], "projection_sha256": row["projection_sha256"]}
    assoc = None
    if association_id is not None:
        row = await cases.row_by_id(db, "association", association_id)
        assoc = {"id": str(row["id"]), "record_sha256": row["record_sha256"]}
    companion = None
    if tc_expression_revision_id is not None:
        companion = pin(await expressions.expression(db, actor_user_id=actor_user_id, revision_id=tc_expression_revision_id))
    field = {"tc_criterion": "criterion_statement", "measurement_method": "method_statement", "pressure_gpa": "pressure_gpa"}.get(field_id)
    selector = {"target_id": str(target["id"]), "target_sha256": target["record_sha256"], "field_id": field_id,
        "association": assoc, "expression": pin(expression), "tc_expression": companion,
        "source_identity": {"paper_id": json.loads(target["context_json"])["result"].get("paper_id"), "work_id": None},
        "component": {"kind": component_kind, "index": component_index if component_kind == "condition" else None,
                      "field_id": field, "role": "reported_result_condition" if component_kind == "condition" else None}}
    proof = await subject(db, selector)
    item = {**selector, "expected_subject_sha256": digest(proof),
        **{"expected_"+k: proof[k] for k in ("candidate_sha256", "missingness_sha256", "tuple_sha256")},
        "decision": "request_clarification", "checks": {k: "unresolved" for k in contract.CHECKS},
        "source_inspection_attested": False, "rationale": "Source inspection and exact scope review are required.",
        "predecessor": None, "resolves_decision_id": None}
    d = table(1)
    successor = d.alias("successor")
    prior = (await db.execute(sa.select(d).where(d.c.target_id == target["id"], d.c.field_id == field_id,
        ~sa.exists(sa.select(successor.c.id).where(successor.c.predecessor_id == d.c.id))))).mappings().one_or_none()
    if prior is not None:
        intact(prior)
        item["predecessor"] = {"id": str(prior["id"]), "record_sha256": prior["record_sha256"]}
        if prior["decision"] == "request_clarification":
            item["resolves_decision_id"] = str(prior["id"])
    return {"version": contract.VERSION, "profile_version": contract.PROFILE, "actor_user_id": str(actor_user_id),
        "session_version": session, "subject": proof, "subject_canonical_json": canonical(proof).decode(),
        "subject_sha256": digest(proof), "item_template": item, **contract.AUTHORITY}


async def capabilities(db, *, actor_user_id):
    _, session = await reader(db, actor_user_id)
    try:
        grant, _ = await _grant(db, actor_user_id, "reviewer")
    except ResearchAccessDenied:
        grant = None
    return {"version": contract.VERSION, "profile_version": contract.PROFILE,
        "actor_user_id": str(actor_user_id), "session_version": session,
        "reviewer_grant_id": str(grant["id"]) if grant else None, "can_write": grant is not None,
        "field_ids": list(contract.FIELDS), "checks": list(contract.CHECKS), "max_items": 8,
        "max_operation_bytes": contract.MAX_BYTES, "max_page_size": 8,
        "supported_target_kinds": ["retained_result"], "field_fidelity_acceptance_available": True,
        "support_scope": "finite_flat_retained_records_with_current_source_expression_and_reviewed_tc_window",
        **contract.AUTHORITY}


def receipt(row, *, dry_run=False, replayed=False):
    intact(row)
    return {"version": contract.VERSION, "receipt_id": str(row["id"]), "receipt_sha256": row["record_sha256"],
        "actor_user_id": str(row["actor_user_id"]), "actor_grant_id": str(row["actor_grant_id"]),
        "actor_session_version": row["actor_session_version"], "request_key": row["request_key"],
        "request_sha256": row["request_sha256"], "preview_sha256": row["preview_sha256"],
        "request_canonical_json": row["request_json"], "preview_canonical_json": row["preview_json"],
        "receipt_canonical_json": canonical(_body(row)).decode(), "dry_run": dry_run, "replayed": replayed,
        "review_ledger_written": not dry_run, "decision_ids": [str(uuid5(NAMESPACE, digest([str(row["id"]), i])))
            for i in range(len(json.loads(row["request_json"])["items"]))], **contract.AUTHORITY}


async def operate(db, *, actor_user_id, request, dry_run=True, expected_preview_sha256=None):
    request = contract.validate(request)
    text = canonical(request).decode()
    async with cases.write(db, dry_run) as changed:
        grant, session = await _grant(db, actor_user_id, "reviewer")
        old = (await db.execute(sa.select(table(0)).where(table(0).c.actor_user_id == identifier(actor_user_id),
            table(0).c.request_key == request["request_key"]))).mappings().one_or_none()
        if old is not None:
            if old["request_sha256"] != digest(request) or expected_preview_sha256 not in {None, old["preview_sha256"]}:
                raise SourcePropertyConflict("field_review_request_conflict")
            return receipt(old, replayed=True)
        row_id = uuid5(NAMESPACE, digest([str(actor_user_id), request["request_key"]]))
        preview = {"version": contract.VERSION, "receipt_id": str(row_id), "actor_user_id": str(actor_user_id),
            "actor_grant_id": str(grant["id"]), "actor_session_version": session, "request_sha256": digest(request)}
        preview_text = canonical(preview).decode()
        if not dry_run and expected_preview_sha256 != digest(preview):
            raise SourcePropertyConflict("field_review_exact_preview_required")
        row = {"id": row_id, "actor_user_id": identifier(actor_user_id), "actor_grant_id": grant["id"],
            "actor_session_version": session, "request_key": request["request_key"], "request_json": text,
            "request_sha256": digest(request), "preview_json": preview_text, "preview_sha256": digest(preview)}
        row["record_sha256"] = digest(_body(row))
        await _insert(db, table(0).name, row)
        for i, item in enumerate(request["items"]):
            d = {"id": uuid5(NAMESPACE, digest([str(row_id), i])), "actor_user_id": identifier(actor_user_id),
                "actor_grant_id": grant["id"], "actor_session_version": session, "request_id": row_id,
                "request_sha256": row["record_sha256"], "item_index": i, "target_id": identifier(item["target_id"]),
                "field_id": item["field_id"], "decision": item["decision"], "payload": item,
                "chain_key": item["target_id"]+":"+item["field_id"],
                "predecessor_id": identifier(item["predecessor"]["id"]) if item["predecessor"] else None,
                "predecessor_sha256": item["predecessor"]["record_sha256"] if item["predecessor"] else None}
            d["record_sha256"] = digest(_body(d))
            await _insert(db, table(1).name, d)
        await db.execute(sa.text("SET CONSTRAINTS fr85_complete IMMEDIATE"))
        await db.execute(sa.text("SET CONSTRAINTS fr85_complete DEFERRED"))
        changed["value"] = True
        return receipt(row, dry_run=dry_run)


async def outcome(db, *, actor_user_id, request_key_value, expected_request_sha256):
    await reader(db, actor_user_id)
    key, pin = request_key(request_key_value), checksum(expected_request_sha256)
    row = (await db.execute(sa.select(table(0)).where(table(0).c.actor_user_id == identifier(actor_user_id),
        table(0).c.request_key == key))).mappings().one_or_none()
    if row is None:
        raise SourcePropertyNotFound("field_review_outcome_unavailable_not_proof_of_failure")
    if row["request_sha256"] != pin:
        raise SourcePropertyConflict("field_review_outcome_pin_changed")
    return receipt(row, replayed=True)


async def entry(db, row, *, actor_user_id):
    intact(row)
    reasons = []
    d = table(1)
    if await db.scalar(sa.select(sa.exists().where(d.c.predecessor_id == row["id"]))):
        reasons.append("decision_superseded")
    try:
        await _grant(db, row["actor_user_id"], "reviewer", grant_id=row["actor_grant_id"], session_version=row["actor_session_version"])
    except ResearchAccessDenied:
        reasons.append("reviewer_authority_unavailable")
    p = row["payload"]
    proof = await subject(db, {k: p[k] for k in contract.SUBJECT_KEYS})
    reasons.extend(proof["reason_codes"])
    if digest(proof) != p["expected_subject_sha256"]:
        reasons.append("subject_changed")
    accepted = row["decision"] == "accept" and not reasons
    candidate_text = canonical(proof["candidate"]).decode() if accepted else None
    if accepted:
        require(cases.text_sha(candidate_text) == p["expected_candidate_sha256"], "field_review_effective_value_integrity")
    return {"id": str(row["id"]), "record_sha256": row["record_sha256"],
        "record_canonical_json": canonical(_body(row)).decode(), "target_id": str(row["target_id"]),
        "field_id": row["field_id"], "decision": row["decision"], "is_head": "decision_superseded" not in reasons,
        "field_fidelity_accepted": accepted, "effective_value": proof["candidate"] if accepted else None,
        "effective_value_canonical_json": candidate_text,
        "reason_codes": sorted(set(reasons)), "source_identity_status": "reviewed_field_fidelity_only" if accepted else "unestablished",
        "created_at": row["created_at"].isoformat(), **contract.AUTHORITY}


async def history(db, *, actor_user_id, target_id, field_id=None, offset=0, limit=8):
    _, session = await reader(db, actor_user_id)
    cases.bounds(offset, limit)
    filters = [table(1).c.target_id == identifier(target_id)]
    if field_id is not None:
        require(field_id in contract.FIELDS, "field_review_field_required")
        filters.append(table(1).c.field_id == field_id)
    total = await db.scalar(sa.select(sa.func.count()).select_from(table(1)).where(*filters))
    d = table(1)
    successor = d.alias("successor")
    head = ~sa.exists(sa.select(successor.c.id).where(successor.c.predecessor_id == d.c.id).correlate(d))
    rows = (await db.execute(sa.select(d).where(*filters).order_by(head.desc(), d.c.created_at.desc(), d.c.id.desc())
                            .offset(offset).limit(limit))).mappings().all()
    result = {"version": contract.VERSION, "actor_user_id": str(actor_user_id), "session_version": session,
        "total": total, "offset": offset, "limit": limit, "entries": [await entry(db, r, actor_user_id=actor_user_id) for r in rows],
        **contract.AUTHORITY}
    return cases.bounded_response(result)


async def effective(db, *, actor_user_id, target_id, field_id):
    page = await history(db, actor_user_id=actor_user_id, target_id=target_id, field_id=field_id)
    head = next((r for r in page["entries"] if r["is_head"]), None)
    return {"version": contract.VERSION, "actor_user_id": page["actor_user_id"], "session_version": page["session_version"],
        "target_id": target_id, "field_id": field_id, "field_fidelity_accepted": bool(head and head["field_fidelity_accepted"]),
        "effective_value": head["effective_value"] if head else None,
        "effective_value_canonical_json": head["effective_value_canonical_json"] if head else None,
        "decision": head, **contract.AUTHORITY}
