"""Original-file custody for an exact private calculation question.

Transport prepares native bytes before opening its write transaction. Detail
reads reconstruct the native report; a SQL digest alone supplies no quantity.
"""
from __future__ import annotations

import json
from uuid import UUID, uuid5

import sqlalchemy as sa
from models.db import Base
from models.discovery_calculation_v1 import TABLE_ORDER

from services import discovery_calculation_contract as contract
from services import discovery_designs as designs
from services.discovery_feedback_contract import checksum, design_pin
from services.qe_pw_import import VERSION as PARSER_VERSION
from services.research_release_manifest import canonical, digest
from services.source_property_pending import (
    SourcePropertyConflict,
    SourcePropertyNotFound,
    identifier,
    request_key,
)

_NAMESPACE = UUID("e3dd9c83-759d-4ec1-9480-6266ad51140c")


def table(index=0):
    return Base.metadata.tables[TABLE_ORDER[index]]


def _body(row):
    return {str(k): str(v) if isinstance(v, UUID) else v for k, v in row.items() if k not in {"created_at", "record_sha256"}}


def intact(row):
    request = contract.validate(json.loads(row["request_json"]))
    contract.require(canonical(request).decode() == row["request_json"]
        and digest(_body(row)) == row["record_sha256"] and designs.text_sha(row["request_json"]) == row["request_sha256"]
        and designs.text_sha(row["preview_json"]) == row["preview_sha256"]
        and row["files"] == request["files"] and row["design_ref"] == request["design"]
        and str(row["design_revision_id"]) == request["design"]["revision_id"]
        and row["report_version"] == PARSER_VERSION, "calculation_receipt_integrity_unavailable")


def pin(row):
    return {"design_id": str(row["design_id"]), "revision_id": str(row["id"]),
            "record_sha256": row["record_sha256"], "next_action_sha256": digest(row["design"]["next_action"])}


async def _design(db, actor, reference, *, current=False):
    design_pin(reference)
    row = await designs._row(db, actor, reference["revision_id"])
    if pin(row) != reference:
        raise SourcePropertyConflict("calculation_design_pin_conflict")
    head = await designs._head(db, actor, reference["design_id"])
    source = await designs.eligibility(db, row["context_json"], row["baseline"])
    reasons = list(source["reason_codes"])
    if row["design"]["next_action"]["kind"] != "calculation":
        reasons.append("calculation_action_required")
    if head["operation"] == "withdraw" or row["operation"] == "withdraw":
        reasons.append("design_withdrawn")
    elif head["id"] != row["id"]:
        reasons.append("design_revision_changed")
    eligible = {"eligible": not reasons, "reason_codes": sorted(set(reasons))}
    if current and reasons:
        raise SourcePropertyConflict("calculation_design_not_currently_eligible")
    return row, eligible


async def capabilities(db, *, actor_user_id):
    grant, session = await designs.reader(db, actor_user_id)
    return {"version": contract.VERSION, "request_version": contract.REQUEST_VERSION,
        "actor_user_id": str(identifier(actor_user_id)), "session_version": session, "curator_grant_id": str(grant["id"]),
        "action_kinds": ["calculation"], "baseline_kinds": ["unanchored", "retained_result", "native_property"],
        "parser_version": PARSER_VERSION, "max_package_bytes": contract.MAX_PACKAGE_BYTES,
        "max_file_bytes": contract.MAX_FILE_BYTES, "max_input_bytes": contract.MAX_INPUT_BYTES,
        "max_files": 11, "max_page_size": contract.MAX_PAGE, **contract.AUTHORITY}


async def context(db, *, actor_user_id, design_id):
    await designs.reader(db, actor_user_id)
    row = await designs._head(db, actor_user_id, design_id)
    reference = pin(row)
    _, eligible = await _design(db, actor_user_id, reference)
    return {"version": contract.VERSION, "design": reference, "eligibility": eligible,
            "next_action": row["design"]["next_action"], "association": "researcher_linked_unverified", **contract.AUTHORITY}


def receipt(row, *, replayed=False, dry_run=False):
    intact(row)
    return {"version": contract.VERSION, "receipt_id": str(row["id"]), "receipt_sha256": row["record_sha256"],
        "request_sha256": row["request_sha256"], "preview_sha256": row["preview_sha256"],
        "request_key": row["request_key"], "design": row["design_ref"], "report_sha256": row["report_sha256"],
        "report_version": row["report_version"], "request_canonical_json": row["request_json"],
        "preview_canonical_json": row["preview_json"], "receipt_canonical_json": canonical(_body(row)).decode(),
        "replayed": replayed, "dry_run": dry_run, "private_ledger_written": not dry_run, **contract.AUTHORITY}


async def _row(db, actor, *, return_id=None, key=None):
    t = table()
    selector = t.c.id == identifier(return_id) if return_id is not None else t.c.request_key == request_key(key)
    row = (await db.execute(sa.select(t).where(t.c.actor_user_id == identifier(actor), selector))).mappings().one_or_none()
    if row is None:
        raise SourcePropertyNotFound("calculation_return_unavailable")
    intact(row)
    return row


async def operate(db, *, actor_user_id, prepared: contract.Prepared, dry_run=True, expected_preview_sha256=None):
    contract.require(type(prepared) is contract.Prepared, "calculation_native_preflight_required")
    request = contract.validate(prepared.request)
    if expected_preview_sha256 is not None:
        checksum(expected_preview_sha256)
    request_sha = designs.text_sha(prepared.request_json)
    async with designs.write(db, dry_run) as changed:
        grant, session = await designs._grant(db, actor_user_id, "curator")
        try:
            old = await _row(db, actor_user_id, key=request["request_key"])
        except SourcePropertyNotFound:
            old = None
        if old is not None:
            if old["request_sha256"] != request_sha or old["report_sha256"] != prepared.report_sha256 \
                    or expected_preview_sha256 not in {None, old["preview_sha256"]}:
                raise SourcePropertyConflict("calculation_request_conflict")
            return receipt(old, replayed=True)
        await _design(db, actor_user_id, request["design"], current=True)
        rid = uuid5(_NAMESPACE, digest([str(actor_user_id), request["request_key"]]))
        actor = {"actor_user_id": identifier(actor_user_id), "actor_grant_id": grant["id"], "actor_session_version": session}
        preview = {"version": contract.VERSION, "receipt_id": str(rid),
            "actor": {k: str(v) if isinstance(v, UUID) else v for k, v in actor.items()},
            "request_sha256": request_sha, "report_sha256": prepared.report_sha256,
            "report_version": PARSER_VERSION, "design": request["design"]}
        preview_text = canonical(preview).decode()
        preview_sha = designs.text_sha(preview_text)
        if not dry_run and expected_preview_sha256 != preview_sha:
            raise SourcePropertyConflict("calculation_exact_preview_required")
        values = {"id": rid, **actor, "design_revision_id": identifier(request["design"]["revision_id"]),
            "design_ref": request["design"], "request_key": request["request_key"], "request_json": prepared.request_json,
            "request_sha256": request_sha, "files": request["files"], "report_version": PARSER_VERSION,
            "report_sha256": prepared.report_sha256, "preview_json": preview_text, "preview_sha256": preview_sha}
        values["record_sha256"] = digest(_body(values))
        row = (await db.execute(table().insert().values(**values).returning(table()))).mappings().one()
        await db.execute(table(1).insert(), [{"return_id": rid, "ordinal": i, "original_bytes": raw}
                                           for i, raw in enumerate(prepared.files)])
        # Run the deferred inventory proof inside our rollback-capable savepoint.
        names = ", ".join(name + "_complete" for name in TABLE_ORDER)
        await db.execute(sa.text("SET CONSTRAINTS " + names + " IMMEDIATE"))
        await db.execute(sa.text("SET CONSTRAINTS " + names + " DEFERRED"))
        changed["value"] = True
        return receipt(row, dry_run=dry_run)


async def outcome(db, *, actor_user_id, request_key_value, expected_request_sha256):
    await designs.reader(db, actor_user_id)
    row = await _row(db, actor_user_id, key=request_key_value)
    if row["request_sha256"] != checksum(expected_request_sha256):
        raise SourcePropertyConflict("calculation_request_pin_conflict")
    return receipt(row, replayed=True)


async def returns(db, *, actor_user_id, design_id, offset=0, limit=8):
    await designs.reader(db, actor_user_id)
    await designs._head(db, actor_user_id, design_id)
    contract.require(type(offset) is int and 0 <= offset <= 1000 and type(limit) is int and 1 <= limit <= contract.MAX_PAGE, "calculation_page_bound")
    t = table()
    selector = sa.and_(t.c.actor_user_id == identifier(actor_user_id), t.c.design_ref["design_id"].astext == design_id)
    rows = (await db.execute(sa.select(t).where(selector).order_by(t.c.created_at.desc(), t.c.id).offset(offset).limit(limit))).mappings().all()
    entries = []
    for row in rows:
        _, eligible = await _design(db, actor_user_id, row["design_ref"])
        entries.append({"receipt": receipt(row), "eligibility": eligible})
    return {"version": contract.VERSION, "design_id": design_id, "offset": offset, "limit": limit,
            "total": await db.scalar(sa.select(sa.func.count()).select_from(t).where(selector)),
            "entries": entries, **contract.AUTHORITY}


async def original_files(db, *, actor_user_id, return_id):
    await designs.reader(db, actor_user_id)
    row = await _row(db, actor_user_id, return_id=return_id)
    _, eligible = await _design(db, actor_user_id, row["design_ref"])
    if not eligible["eligible"]:
        return row, eligible, None
    rows = (await db.execute(sa.select(table(1)).where(table(1).c.return_id == row["id"])
                             .order_by(table(1).c.ordinal))).mappings().all()
    contract.require([r["ordinal"] for r in rows] == list(range(len(row["files"]))), "calculation_original_inventory_unavailable")
    # The caller reparses these bytes; no stored JSON quantities are trusted.
    return row, eligible, tuple(r["original_bytes"] for r in rows)


def reconstruct(row, files):
    intact(row)
    prepared = contract.prepare(json.loads(row["request_json"]), files)
    contract.require(prepared.report_sha256 == row["report_sha256"], "calculation_report_integrity_unavailable")
    return prepared
