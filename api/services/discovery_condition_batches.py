"""Owner-private condition generation receipts and atomic candidate children.

The calling router owns its serializable transaction. Preview rehearses guarded
native writes within an outer savepoint. Generation artifacts remain byte-pinned
proposal history; science values and execution are separate source records.
"""
from __future__ import annotations

import json
from uuid import UUID, uuid5

import sqlalchemy as sa

from models.db import Base
from services import discovery_condition_batch_contract as contract
from services import discovery_designs as designs
from services.research_release_manifest import canonical, digest
from services.source_property_pending import SourcePropertyConflict, SourcePropertyNotFound, identifier, request_key, checksum

VERSION = contract.VERSION
_NAMESPACE = UUID("4df7c145-fc6a-4d21-8b18-855e7f8a0753")
_BATCH = "discovery_condition_batches_v1"
_LINK = "discovery_condition_child_links_v1"


def table(name=_BATCH):
    return Base.metadata.tables[name]


def text_sha(value):
    return designs.text_sha(value)


def _stable(*parts):
    return uuid5(_NAMESPACE, digest([str(part) for part in parts]))


def _body(row):
    return {str(key): str(value) if isinstance(value, UUID) else value for key, value in row.items()
            if key not in {"created_at", "record_sha256", "manifest_json"}}


def intact(row):
    contract.require(digest(_body(row)) == row["record_sha256"], "batch_receipt_integrity_unavailable")
    request = contract.validate(json.loads(row["request_json"]))
    contract.require(canonical(request).decode() == row["request_json"]
                     and text_sha(row["request_json"]) == row["request_sha256"]
                     and text_sha(row["preview_json"]) == row["preview_sha256"], "batch_proof_integrity_unavailable")


def artifact(row):
    intact(row)
    value = json.loads(row["manifest_json"])
    body = dict(value)
    pin = body.pop("manifest_sha256", None)
    contract.require(pin == row["manifest_sha256"] and text_sha(canonical(body).decode()) == pin
                     and canonical(value).decode() == row["manifest_json"]
                     and len(canonical(body)) <= contract.MAX_MANIFEST_BYTES
                     and value["input_canonical_json"] == row["input_json"]
                     and value["input_sha256"] == row["input_sha256"] == text_sha(row["input_json"])
                     and value["parent"] == row["parent"] and value["source_pins"] == row["source_pins"]
                     and len(value["scenarios"]) == row["scenario_total"], "batch_artifact_integrity_unavailable")
    return value


async def capabilities(db, *, actor_user_id):
    grant, session = await designs.reader(db, actor_user_id)
    return {"version": VERSION, "request_version": contract.REQUEST_VERSION,
            "actor_user_id": str(identifier(actor_user_id)), "session_version": session,
            "curator_grant_id": str(grant["id"]), "can_write": True,
            "operations": list(contract.OPERATIONS), "max_page_size": contract.MAX_PAGE,
            "max_operation_bytes": contract.MAX_BYTES, "max_manifest_bytes": contract.MAX_MANIFEST_BYTES,
            **contract.AUTHORITY}


async def _batch(db, actor, batch_id):
    row = (await db.execute(sa.select(table()).where(table().c.id == identifier(batch_id),
                      table().c.actor_user_id == identifier(actor)))).mappings().one_or_none()
    if row is None:
        raise SourcePropertyNotFound("condition_batch_unavailable")
    intact(row)
    return row


async def _parent(db, actor, pin, *, require_current=False):
    row = await designs._row(db, actor, pin["revision_id"])
    expected = {"design_id": str(row["design_id"]), "revision_id": str(row["id"]),
                "revision": row["revision"], "record_sha256": row["record_sha256"]}
    if pin != expected or row["operation"] == "withdraw" or row["baseline"]["kind"] == "unanchored":
        raise SourcePropertyConflict("condition_parent_pin_conflict")
    head = await designs._head(db, actor, pin["design_id"])
    eligible = await designs.eligibility(db, row["context_json"], row["baseline"])
    reasons = list(eligible["reason_codes"])
    if head["operation"] == "withdraw":
        reasons.append("parent_withdrawn")
    elif head["id"] != row["id"]:
        reasons.append("parent_revision_changed")
    eligible = {"eligible": not reasons, "reason_codes": sorted(set(reasons))}
    if require_current and not eligible["eligible"]:
        raise SourcePropertyConflict("condition_parent_not_currently_eligible")
    return row, eligible


async def _native_manifest(db, parent, axes, actor, grant, session):
    body_text = await db.scalar(sa.text("""SELECT public.sclib_discovery_condition_batch_manifest_v1(
        CAST(:parent AS jsonb), CAST(:axes AS jsonb), :actor, :grant, CAST(:session AS bigint))"""),
        {"parent": canonical(parent).decode(), "axes": canonical(axes).decode(),
         "actor": identifier(actor), "grant": grant["id"], "session": session})
    contract.require(type(body_text) is str and len(body_text.encode()) <= contract.MAX_MANIFEST_BYTES,
                     "batch_manifest_bound")
    body = json.loads(body_text)
    contract.require(canonical(body).decode() == body_text, "batch_manifest_canonical_required")
    full = {**body, "manifest_sha256": text_sha(body_text)}
    return full, canonical(full).decode()


async def _historical_manifest(db, row, parent):
    # Fresh current-source/head admission is separate from this old actor's
    # generation bytes. A renewed session does not rewrite private history.
    body_text = await db.scalar(sa.text("""SELECT public.sclib_discovery_condition_batch_body_v1(
        to_jsonb(p), CAST(:axes AS jsonb), :actor, :grant, CAST(:session AS bigint))
        FROM public.discovery_design_revisions_v1 p WHERE p.id=:parent_id"""),
        {"axes": canonical(row["payload"]["axes"]).decode(), "actor": row["actor_user_id"],
         "grant": row["actor_grant_id"], "session": row["actor_session_version"], "parent_id": parent["id"]})
    old = artifact(row)
    contract.require(type(body_text) is str and text_sha(body_text) == row["manifest_sha256"]
                     and canonical({**json.loads(body_text), "manifest_sha256": row["manifest_sha256"]}).decode()
                     == row["manifest_json"], "batch_historical_generation_integrity_unavailable")
    return old


async def receipt(db, row, *, replayed=False, dry_run=False):
    intact(row)
    retaining = row["operation"] == "retain_batch"
    batch = row if retaining else await _batch(db, row["actor_user_id"], row["batch_id"])
    child = None
    if not retaining:
        native = await designs._row(db, row["actor_user_id"], row["child_revision_id"])
        contract.require(native["record_sha256"] == row["child_record_sha256"]
                         and native["design_id"] == row["child_design_id"], "batch_child_integrity_unavailable")
        child = designs.receipt(native, replayed=replayed, dry_run=dry_run)
    return {"version": VERSION, "receipt_id": str(row["id"]), "receipt_sha256": row["record_sha256"],
        "operation": row["operation"], "actor_user_id": str(row["actor_user_id"]),
        "actor_grant_id": str(row["actor_grant_id"]), "actor_session_version": row["actor_session_version"],
        "request_key": row["request_key"], "request_sha256": row["request_sha256"],
        "preview_sha256": row["preview_sha256"], "request_canonical_json": row["request_json"],
        "preview_canonical_json": row["preview_json"], "receipt_canonical_json": canonical(_body(row)).decode(),
        "batch_id": str(batch["id"]), "batch_record_sha256": batch["record_sha256"],
        "input_sha256": batch["input_sha256"], "manifest_sha256": batch["manifest_sha256"],
        "candidate_sha256": None if retaining else row["candidate_sha256"], "child": child,
        "replayed": replayed, "dry_run": dry_run, "pending_ledger_written": not dry_run, **contract.AUTHORITY}


async def _operation_row(db, actor, key):
    found = []
    for name in (_BATCH, _LINK):
        t = table(name)
        row = (await db.execute(sa.select(t).where(t.c.actor_user_id == identifier(actor),
                                        t.c.request_key == key))).mappings().one_or_none()
        if row is not None:
            intact(row)
            found.append(row)
    contract.require(len(found) <= 1, "batch_request_inventory_conflict")
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
                raise SourcePropertyConflict("condition_batch_request_conflict")
            return await receipt(db, old, replayed=True)
        receipt_id = _stable("operation", actor_user_id, request["request_key"])
        actor = {"actor_user_id": identifier(actor_user_id), "actor_grant_id": grant["id"], "actor_session_version": session}
        actor_json = {k: str(v) if isinstance(v, UUID) else v for k, v in actor.items()}
        if operation == "retain_batch":
            parent, _ = await _parent(db, actor_user_id, payload["parent"], require_current=True)
            manifest, manifest_text = await _native_manifest(db, payload["parent"], payload["axes"], actor_user_id, grant, session)
            if manifest["input_sha256"] != payload["expected_input_sha256"] or manifest["manifest_sha256"] != payload["expected_manifest_sha256"]:
                raise SourcePropertyConflict("condition_generation_pin_changed")
            preview = {"version": VERSION, "actor": actor_json, "request_sha256": request_sha,
                       "receipt_id": str(receipt_id), "batch_id": str(receipt_id), "parent": payload["parent"],
                       "input_sha256": manifest["input_sha256"], "manifest_sha256": manifest["manifest_sha256"],
                       "scenario_total": len(manifest["scenarios"])}
            extra = {"parent": payload["parent"], "source_pins": manifest["source_pins"],
                     "input_json": manifest["input_canonical_json"], "input_sha256": manifest["input_sha256"],
                     "manifest_json": manifest_text, "manifest_sha256": manifest["manifest_sha256"],
                     "scenario_total": len(manifest["scenarios"])}
            destination = table()
        else:
            batch = await _batch(db, actor_user_id, payload["batch"]["id"])
            if payload["batch"] != {"id": str(batch["id"]), "record_sha256": batch["record_sha256"], "manifest_sha256": batch["manifest_sha256"]}:
                raise SourcePropertyConflict("condition_batch_pin_changed")
            parent, _ = await _parent(db, actor_user_id, batch["parent"], require_current=True)
            # Assert live native source/head and supported targets independently of
            # the preserved old session/grant generation artifact.
            await _native_manifest(db, batch["parent"], batch["payload"]["axes"], actor_user_id, grant, session)
            manifest = await _historical_manifest(db, batch, parent)
            scenario = next((s for s in manifest["scenarios"] if s["candidate_sha256"] == payload["candidate_sha256"]), None)
            if scenario is None:
                raise SourcePropertyNotFound("condition_candidate_unavailable")
            native_request = {"version": designs.contract.REQUEST_VERSION,
                "request_key": "condition-child:" + str(receipt_id), "operation": "propose",
                "payload": {"baseline": parent["baseline"], "design": scenario["proposal"],
                            "parent": {k: batch["parent"][k] for k in ("design_id", "revision_id", "record_sha256")}}}
            rehearsed = await designs.operate(db, actor_user_id=actor_user_id, request=native_request, dry_run=True)
            child = await designs.operate(db, actor_user_id=actor_user_id, request=native_request,
                                         dry_run=False, expected_preview_sha256=rehearsed["preview_sha256"])
            preview = {"version": VERSION, "actor": actor_json, "request_sha256": request_sha,
                "receipt_id": str(receipt_id), "batch_id": str(batch["id"]), "batch_record_sha256": batch["record_sha256"],
                "manifest_sha256": batch["manifest_sha256"], "candidate_sha256": scenario["candidate_sha256"],
                "child": {"design_id": child["design_id"], "revision_id": child["receipt_id"], "record_sha256": child["receipt_sha256"]}}
            extra = {"batch_id": batch["id"], "batch_record_sha256": batch["record_sha256"],
                     "manifest_sha256": batch["manifest_sha256"], "candidate_sha256": scenario["candidate_sha256"],
                     "child_revision_id": identifier(child["receipt_id"]), "child_design_id": identifier(child["design_id"]),
                     "child_record_sha256": child["receipt_sha256"]}
            destination = table(_LINK)
        preview_text = canonical(preview).decode()
        preview_sha = text_sha(preview_text)
        if not dry_run and expected_preview_sha256 != preview_sha:
            raise SourcePropertyConflict("condition_batch_exact_preview_required")
        values = {"id": receipt_id, **actor, "operation": operation, "request_key": request["request_key"],
                  "request_json": request_text, "payload": payload, "request_sha256": request_sha,
                  "preview_json": preview_text, "preview_sha256": preview_sha, **extra,
                  **{k: v for k, v in contract.AUTHORITY.items() if k != "scope"}}
        values["record_sha256"] = digest(_body(values))
        inserted = (await db.execute(destination.insert().values(**values).returning(destination))).mappings().one()
        changed["value"] = True
        return await receipt(db, inserted, dry_run=dry_run)


async def outcome(db, *, actor_user_id, request_key_value, expected_request_sha256):
    await designs.reader(db, actor_user_id)
    key, pin = request_key(request_key_value), checksum(expected_request_sha256)
    row = await _operation_row(db, actor_user_id, key)
    if row is None:
        raise SourcePropertyNotFound("outcome_unavailable_not_proof_of_failure")
    if row["request_sha256"] != pin:
        raise SourcePropertyConflict("condition_request_pin_conflict")
    return await receipt(db, row, replayed=True)


async def _entry(db, row):
    intact(row)
    _, eligible = await _parent(db, row["actor_user_id"], row["parent"])
    return {"id": str(row["id"]), "record_sha256": row["record_sha256"], "parent": row["parent"],
            "source_pins": row["source_pins"], "input_sha256": row["input_sha256"],
            "manifest_sha256": row["manifest_sha256"], "scenario_total": row["scenario_total"],
            "eligibility": eligible, "receipt": await receipt(db, row), **contract.AUTHORITY}


async def batches(db, *, actor_user_id, offset=0, limit=8):
    _, session = await designs.reader(db, actor_user_id)
    contract.require(type(offset) is int and 0 <= offset <= 1000 and type(limit) is int and 1 <= limit <= contract.MAX_PAGE, "condition_page_bound")
    owner = table().c.actor_user_id == identifier(actor_user_id)
    total = await db.scalar(sa.select(sa.func.count()).select_from(table()).where(owner))
    rows = (await db.execute(sa.select(table()).where(owner).order_by(table().c.created_at.desc(), table().c.id)
                             .offset(offset).limit(limit))).mappings().all()
    return {"version": VERSION, "actor_user_id": str(identifier(actor_user_id)), "session_version": session,
            "offset": offset, "limit": limit, "total": total, "entries": [await _entry(db, row) for row in rows], **contract.AUTHORITY}


async def batch_detail(db, *, actor_user_id, batch_id, offset=0, limit=8):
    _, session = await designs.reader(db, actor_user_id)
    contract.require(type(offset) is int and 0 <= offset <= 63 and type(limit) is int and 1 <= limit <= contract.MAX_PAGE, "condition_scenario_page_bound")
    row = await _batch(db, actor_user_id, batch_id)
    manifest = artifact(row)
    link_rows = (await db.execute(sa.select(table(_LINK)).where(table(_LINK).c.batch_id == row["id"],
                          table(_LINK).c.actor_user_id == identifier(actor_user_id)))).mappings().all()
    links = {}
    for link in link_rows:
        intact(link)
        links[link["candidate_sha256"]] = {"design_id": str(link["child_design_id"]),
            "revision_id": str(link["child_revision_id"]), "record_sha256": link["child_record_sha256"]}
    scenarios = [{**s, "child": links.get(s["candidate_sha256"])} for s in manifest["scenarios"][offset:offset + limit]]
    return {"version": VERSION, "actor_user_id": str(identifier(actor_user_id)), "session_version": session,
            "entry": await _entry(db, row), "offset": offset, "limit": limit,
            "scenario_total": row["scenario_total"], "scenarios": scenarios, **contract.AUTHORITY}


async def export_manifest(db, *, actor_user_id, batch_id):
    await designs.reader(db, actor_user_id)
    row = await _batch(db, actor_user_id, batch_id)
    artifact(row)
    contract.require(len(row["manifest_json"].encode()) <= contract.MAX_MANIFEST_BYTES + 128, "condition_manifest_export_bound")
    return row["manifest_json"]
