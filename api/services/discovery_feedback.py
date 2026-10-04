"""Evidence → explicit researcher decision → exact saved follow-up association.

Archival inspection is not new execution, scientific review or an assertion
that an evidence record describes the proposed sample, structure or state.
The router owns a serializable transaction. SQL reconstructs source projections
and independently admits all inserts. Source values stay out of receipts.
"""
from __future__ import annotations

import json
from uuid import UUID, uuid5

import sqlalchemy as sa

from models.db import Base
from services import discovery_designs as designs
from services import discovery_feedback_contract as contract
from services.research_release_manifest import canonical, digest
from services.source_property_pending import (
    SourcePropertyConflict,
    SourcePropertyNotFound,
    checksum,
    identifier,
    request_key,
)

VERSION = contract.VERSION
_NAMESPACE = UUID("efeddd9a-1d13-4c08-892d-764f8c7f08c9")
_RETURN = "discovery_evidence_returns_v1"
_LINK = "discovery_feedback_follow_ups_v1"


def table(name=_RETURN):
    return Base.metadata.tables[name]


def text_sha(value):
    return designs.text_sha(value)


def _stable(*parts):
    return uuid5(_NAMESPACE, digest([str(part) for part in parts]))


def _body(row):
    return {str(key): str(value) if isinstance(value, UUID) else value for key, value in row.items()
            if key not in {"created_at", "record_sha256", "context_json", "projection"}}


def intact(row):
    contract.require(digest(_body(row)) == row["record_sha256"], "feedback_receipt_integrity_unavailable")
    request = contract.validate(json.loads(row["request_json"]))
    contract.require(canonical(request).decode() == row["request_json"]
                     and text_sha(row["request_json"]) == row["request_sha256"]
                     and text_sha(row["preview_json"]) == row["preview_sha256"], "feedback_proof_integrity_unavailable")


def _design_pin(row):
    return {"design_id": str(row["design_id"]), "revision_id": str(row["id"]),
            "record_sha256": row["record_sha256"], "next_action_sha256": digest(row["design"]["next_action"])}


async def capabilities(db, *, actor_user_id):
    grant, session = await designs.reader(db, actor_user_id)
    return {"version": VERSION, "request_version": contract.REQUEST_VERSION,
        "actor_user_id": str(identifier(actor_user_id)), "session_version": session,
        "curator_grant_id": str(grant["id"]), "can_write": True,
        "baseline_kinds": ["retained_result"], "action_kinds": ["source_review"],
        "operations": list(contract.OPERATIONS), "decisions": list(contract.DECISIONS),
        "max_page_size": contract.MAX_PAGE, "max_operation_bytes": contract.MAX_BYTES, **contract.AUTHORITY}


async def _design(db, actor, pin, *, require_current=False):
    contract.design_pin(pin)
    row = await designs._row(db, actor, pin["revision_id"])
    if _design_pin(row) != pin:
        raise SourcePropertyConflict("feedback_design_pin_conflict")
    head = await designs._head(db, actor, pin["design_id"])
    eligible = await designs.eligibility(db, row["context_json"], row["baseline"])
    reasons = ["design_" + code for code in eligible["reason_codes"]]
    if head["operation"] == "withdraw" or row["operation"] == "withdraw":
        reasons.append("design_withdrawn")
    elif head["id"] != row["id"]:
        reasons.append("design_revision_changed")
    if row["baseline"]["kind"] != "retained_result":
        reasons.append("design_baseline_unsupported")
    if row["design"]["next_action"]["kind"] != "source_review":
        reasons.append("design_action_unsupported")
    eligible = {"eligible": not reasons, "reason_codes": sorted(set(reasons))}
    if require_current and not eligible["eligible"]:
        raise SourcePropertyConflict("feedback_design_not_currently_eligible")
    return row, eligible


async def _projection_text(db, captured):
    value = await db.scalar(sa.text("""SELECT public.sclib_scientific_import_canonical_v1(
        public.sclib_discovery_feedback_projection_v1(:captured))"""), {"captured": captured})
    contract.require(type(value) is str and len(value.encode()) <= contract.MAX_PROJECTION_BYTES,
                     "feedback_projection_bound")
    return value


async def _eligible(db, row):
    _, design_eligible = await _design(db, row["actor_user_id"], row["design_ref"])
    evidence_eligible = await designs.eligibility(db, row["context_json"], row["evidence"])
    reasons = [*design_eligible["reason_codes"], *("evidence_" + code for code in evidence_eligible["reason_codes"])]
    return {"eligible": not reasons, "reason_codes": sorted(set(reasons))}


async def context(db, *, actor_user_id, design_id, revision_id, record_sha256, material_id, record_index):
    _, session = await designs.reader(db, actor_user_id)
    contract.identifier(design_id)
    contract.identifier(revision_id)
    contract.checksum(record_sha256)
    row = await designs._row(db, actor_user_id, revision_id)
    pin = _design_pin(row)
    if pin["design_id"] != design_id or pin["record_sha256"] != record_sha256:
        raise SourcePropertyConflict("feedback_design_pin_conflict")
    _, design_eligible = await _design(db, actor_user_id, pin)
    evidence = {"kind": "retained_result", "material_id": material_id, "record_index": record_index,
                "property_id": None, "expected_context_sha256": "0" * 64}
    contract.evidence(evidence)
    captured = await designs.sql_context(db, evidence)
    evidence["expected_context_sha256"] = text_sha(captured)
    evidence_eligible = await designs.eligibility(db, captured, evidence)
    reasons = [*design_eligible["reason_codes"], *("evidence_" + code for code in evidence_eligible["reason_codes"])]
    eligible = {"eligible": not reasons, "reason_codes": sorted(set(reasons))}
    projection_text = await _projection_text(db, captured)
    return {"version": VERSION, "actor_user_id": str(identifier(actor_user_id)), "session_version": session,
        "design": pin, "evidence": evidence, "context_sha256": text_sha(captured),
        "projection": json.loads(projection_text) if eligible["eligible"] else None,
        "projection_canonical_json": projection_text if eligible["eligible"] else None,
        "projection_sha256": text_sha(projection_text), "eligibility": eligible, **contract.AUTHORITY}


async def _return(db, actor, return_id):
    row = (await db.execute(sa.select(table()).where(table().c.id == identifier(return_id),
                  table().c.actor_user_id == identifier(actor)))).mappings().one_or_none()
    if row is None:
        raise SourcePropertyNotFound("feedback_record_unavailable")
    intact(row)
    return row


async def _child(db, actor, parent, pin, *, require_current=False):
    contract.child_pin(pin)
    child = await designs._row(db, actor, pin["revision_id"])
    expected = {"design_id": str(child["design_id"]), "revision_id": str(child["id"]), "record_sha256": child["record_sha256"]}
    if expected != pin or child["revision"] != 1 or child["operation"] != "propose" \
            or child["parent"] != {key: parent[key] for key in ("design_id", "revision_id", "record_sha256")}:
        raise SourcePropertyConflict("feedback_initial_linked_child_required")
    head = await designs._head(db, actor, child["design_id"])
    eligible = await designs.eligibility(db, child["context_json"], child["baseline"])
    reasons = ["follow_up_" + code for code in eligible["reason_codes"]]
    if child["baseline"]["kind"] not in {"retained_result", "native_property"}:
        reasons.append("follow_up_child_baseline_unsupported")
    if head["operation"] == "withdraw":
        reasons.append("follow_up_child_withdrawn")
    elif head["id"] != child["id"]:
        reasons.append("follow_up_child_revision_changed")
    eligible = {"eligible": not reasons, "reason_codes": sorted(set(reasons))}
    if require_current and not eligible["eligible"]:
        raise SourcePropertyConflict("feedback_child_not_currently_eligible")
    return child, eligible


async def receipt(db, row, *, replayed=False, dry_run=False):
    intact(row)
    returning = row["operation"] == "return_evidence"
    feedback = row if returning else await _return(db, row["actor_user_id"], row["feedback_id"])
    return {"version": VERSION, "receipt_id": str(row["id"]), "receipt_sha256": row["record_sha256"],
        "operation": row["operation"], "actor_user_id": str(row["actor_user_id"]),
        "actor_grant_id": str(row["actor_grant_id"]), "actor_session_version": row["actor_session_version"],
        "request_key": row["request_key"], "request_sha256": row["request_sha256"],
        "preview_sha256": row["preview_sha256"], "request_canonical_json": row["request_json"],
        "preview_canonical_json": row["preview_json"], "receipt_canonical_json": canonical(_body(row)).decode(),
        "design": feedback["design_ref"], "feedback_id": str(feedback["id"]),
        "feedback_record_sha256": feedback["record_sha256"], "child": None if returning else row["child"],
        "replayed": replayed, "dry_run": dry_run, "pending_ledger_written": not dry_run, **contract.AUTHORITY}


async def _operation_row(db, actor, key):
    found = []
    for name in (_RETURN, _LINK):
        t = table(name)
        row = (await db.execute(sa.select(t).where(t.c.actor_user_id == identifier(actor), t.c.request_key == key))).mappings().one_or_none()
        if row is not None:
            intact(row)
            found.append(row)
    contract.require(len(found) <= 1, "feedback_request_inventory_conflict")
    return found[0] if found else None


async def operate(db, *, actor_user_id, request, dry_run=True, expected_preview_sha256=None):
    request = contract.snapshot(request)
    if expected_preview_sha256 is not None:
        checksum(expected_preview_sha256)
    request_text = canonical(request).decode()
    request_sha = text_sha(request_text)
    payload, operation = request["payload"], request["operation"]
    async with designs.write(db, dry_run) as changed:
        grant, session = await designs._grant(db, actor_user_id, "curator")
        old = await _operation_row(db, actor_user_id, request["request_key"])
        if old is not None:
            if old["request_sha256"] != request_sha or expected_preview_sha256 not in {None, old["preview_sha256"]}:
                raise SourcePropertyConflict("feedback_request_conflict")
            return await receipt(db, old, replayed=True)
        receipt_id = _stable("operation", actor_user_id, request["request_key"])
        actor = {"actor_user_id": identifier(actor_user_id), "actor_grant_id": grant["id"], "actor_session_version": session}
        actor_json = {key: str(value) if isinstance(value, UUID) else value for key, value in actor.items()}
        if operation == "return_evidence":
            await _design(db, actor_user_id, payload["design"], require_current=True)
            captured = await designs.sql_context(db, payload["evidence"])
            if text_sha(captured) != payload["evidence"]["expected_context_sha256"]:
                raise SourcePropertyConflict("feedback_evidence_source_pin_changed")
            eligible = await designs.eligibility(db, captured, payload["evidence"])
            if not eligible["eligible"]:
                raise SourcePropertyConflict("feedback_evidence_not_currently_eligible")
            projection_text = await _projection_text(db, captured)
            projection_sha = text_sha(projection_text)
            preview = {"version": VERSION, "actor": actor_json, "request_sha256": request_sha,
                "receipt_id": str(receipt_id), "feedback_id": str(receipt_id), "design": payload["design"],
                "context_sha256": text_sha(captured), "projection_sha256": projection_sha}
            extra = {"design_ref": payload["design"], "design_revision_id": identifier(payload["design"]["revision_id"]),
                "evidence": payload["evidence"], "findings": payload["findings"], "decision": payload["decision"],
                "reason": payload["reason"], "unknowns": payload["unknowns"], "context_json": captured,
                "context_sha256": text_sha(captured), "projection": json.loads(projection_text), "projection_sha256": projection_sha}
            destination = table()
        else:
            feedback = await _return(db, actor_user_id, payload["feedback"]["id"])
            if feedback["record_sha256"] != payload["feedback"]["record_sha256"]:
                raise SourcePropertyConflict("feedback_return_pin_conflict")
            if not (await _eligible(db, feedback))["eligible"]:
                raise SourcePropertyConflict("feedback_return_not_currently_eligible")
            await _child(db, actor_user_id, feedback["design_ref"], payload["child"], require_current=True)
            preview = {"version": VERSION, "actor": actor_json, "request_sha256": request_sha,
                "receipt_id": str(receipt_id), "feedback_id": str(feedback["id"]),
                "feedback_record_sha256": feedback["record_sha256"], "child": payload["child"]}
            extra = {"feedback_id": feedback["id"], "feedback_record_sha256": feedback["record_sha256"],
                     "child": payload["child"], "child_revision_id": identifier(payload["child"]["revision_id"])}
            destination = table(_LINK)
        preview_text = canonical(preview).decode()
        preview_sha = text_sha(preview_text)
        if not dry_run and expected_preview_sha256 != preview_sha:
            raise SourcePropertyConflict("feedback_exact_preview_required")
        values = {"id": receipt_id, **actor, "operation": operation, "request_key": request["request_key"],
            "request_json": request_text, "payload": payload, "request_sha256": request_sha,
            "preview_json": preview_text, "preview_sha256": preview_sha, **extra,
            **{key: value for key, value in contract.AUTHORITY.items() if key != "scope"}}
        values["record_sha256"] = digest(_body(values))
        inserted = (await db.execute(destination.insert().values(**values).returning(destination))).mappings().one()
        changed["value"] = True
        return await receipt(db, inserted, dry_run=dry_run)


async def outcome(db, *, actor_user_id, request_key_value, expected_request_sha256):
    await designs.reader(db, actor_user_id)
    row = await _operation_row(db, actor_user_id, request_key(request_key_value))
    pin = checksum(expected_request_sha256)
    if row is None:
        raise SourcePropertyNotFound("outcome_unavailable_not_proof_of_failure")
    if row["request_sha256"] != pin:
        raise SourcePropertyConflict("feedback_request_pin_conflict")
    return await receipt(db, row, replayed=True)


async def _entry(db, row):
    intact(row)
    projection_text = await _projection_text(db, row["context_json"])
    contract.require(text_sha(row["context_json"]) == row["context_sha256"]
                     and text_sha(projection_text) == row["projection_sha256"]
                     and json.loads(projection_text) == row["projection"], "feedback_source_integrity_unavailable")
    eligible = await _eligible(db, row)
    links = (await db.execute(sa.select(table(_LINK)).where(table(_LINK).c.feedback_id == row["id"],
        table(_LINK).c.actor_user_id == row["actor_user_id"]).order_by(table(_LINK).c.created_at, table(_LINK).c.id)
        .limit(contract.MAX_FOLLOW_UPS + 1))).mappings().all()
    contract.require(len(links) <= contract.MAX_FOLLOW_UPS, "feedback_follow_up_inventory_bound")
    follow_ups = []
    for link in links:
        intact(link)
        contract.require(link["feedback_record_sha256"] == row["record_sha256"], "feedback_follow_up_integrity_unavailable")
        _, child_eligible = await _child(db, row["actor_user_id"], row["design_ref"], link["child"])
        reasons = sorted(set([*eligible["reason_codes"], *child_eligible["reason_codes"]]))
        follow_ups.append({"id": str(link["id"]), "record_sha256": link["record_sha256"], "child": link["child"],
            "eligibility": {"eligible": not reasons, "reason_codes": reasons}, "receipt": await receipt(db, link), **contract.AUTHORITY})
    return {"id": str(row["id"]), "record_sha256": row["record_sha256"], "design": row["design_ref"],
        "evidence": row["evidence"], "findings": row["findings"], "decision": row["decision"],
        "reason": row["reason"], "unknowns": row["unknowns"], "context_sha256": row["context_sha256"],
        "projection_sha256": row["projection_sha256"], "projection": row["projection"] if eligible["eligible"] else None,
        "projection_canonical_json": projection_text if eligible["eligible"] else None,
        "eligibility": eligible, "follow_ups": follow_ups, "receipt": await receipt(db, row), **contract.AUTHORITY}


async def returns(db, *, actor_user_id, design_id, offset=0, limit=8):
    _, session = await designs.reader(db, actor_user_id)
    contract.identifier(design_id)
    await designs._head(db, actor_user_id, design_id)  # Do not disclose foreign design existence.
    contract.require(type(offset) is int and 0 <= offset <= 1000 and type(limit) is int and 1 <= limit <= contract.MAX_PAGE,
                     "feedback_page_bound")
    owner = sa.and_(table().c.actor_user_id == identifier(actor_user_id), table().c.design_ref["design_id"].astext == design_id)
    total = await db.scalar(sa.select(sa.func.count()).select_from(table()).where(owner))
    rows = (await db.execute(sa.select(table()).where(owner).order_by(table().c.created_at.desc(), table().c.id)
                            .offset(offset).limit(limit))).mappings().all()
    return {"version": VERSION, "actor_user_id": str(identifier(actor_user_id)), "session_version": session,
        "design_id": design_id, "offset": offset, "limit": limit, "total": total,
        "entries": [await _entry(db, row) for row in rows], **contract.AUTHORITY}
