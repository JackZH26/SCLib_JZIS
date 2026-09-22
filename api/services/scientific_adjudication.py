"""Exact, append-only result decisions with caller-owned commit and replay.

Preview executes the real SQL insertion/constraint path in a rolled-back
savepoint. Commit rechecks all subject, head, impact, role and evidence pins.
Neither operation edits original results or grants ML/publication permission.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa

from models.db import Base
from models.scientific_adjudication_v1 import LOCK_FUNCTION
from services import scientific_adjudication_contract as contract
from services.research_access import ResearchAccessDenied, active_grant
from services.research_release_manifest import canonical, digest
from services.scientific_result_subject import capture_result_subject, require_read_session


def _table(name):
    return Base.metadata.tables[name]


def _uuid(value):
    return UUID(value) if value is not None else None


def _conflict(condition, code):
    if not condition:
        raise contract.ScientificAdjudicationConflict(code)


async def _reviewer(db, actor_user_id):
    return await active_grant(db, actor_user_id, role="reviewer")


async def _reader(db, actor_user_id):
    await require_read_session(db)
    try:
        return await _reviewer(db, actor_user_id)
    except ResearchAccessDenied:
        await active_grant(db, actor_user_id, role="curator")
        return None


async def _impact(db, property_id):
    value = await db.scalar(sa.text("SELECT public.sclib_scientific_result_impact_capture_v1(:id)"),
                            {"id": _uuid(str(property_id))})
    contract.require(type(value) is str and len(value.encode()) <= 1024 * 1024,
                     "bounded_adjudication_impact_required")
    result = json.loads(value)
    contract.require(type(result) is dict, "adjudication_impact_unavailable")
    return result, hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _subject(db, property_id):
    """Reuse a genuine SQL-registered snapshot identity, including non-UUID5 IDs."""
    subject = await capture_result_subject(db, property_id)
    table = _table("scientific_result_subjects")
    stored = (await db.execute(sa.select(table.c.id, table.c.basis_json, table.c.property_row_sha256).where(
        table.c.property_id == _uuid(str(property_id)), table.c.subject_sha256 == subject.sha256))).mappings().one_or_none()
    if stored is not None:
        _conflict(stored["basis_json"] == subject.text and stored["property_row_sha256"] == subject.property_row_sha256,
                  "adjudication_stored_subject_mismatch")
        return replace(subject, subject_id=stored["id"])
    return subject


async def _heads(db, property_id):
    decisions = _table("scientific_result_decisions")
    successor = decisions.alias("successor")
    rows = (await db.execute(sa.select(decisions).where(decisions.c.property_id == _uuid(str(property_id)),
        ~sa.exists(sa.select(successor.c.id).where(successor.c.predecessor_id == decisions.c.id)))
        .order_by(decisions.c.scope).limit(3))).mappings().all()
    contract.require(len(rows) <= 2 and len({row["scope"] for row in rows}) == len(rows),
                     "adjudication_head_inventory_invalid")
    return {row["scope"]: row for row in rows}


def _required_artifacts(data):
    artifacts = {row["artifact_id"]: row for row in data["artifacts"]}
    native = data["native_import"]
    identifiers = ({row["artifact_id"] for row in native["source_files"]} if native is not None
                   else set(data["support_artifact_ids"]))
    return [{"artifact_id": identifier, "bytes_sha256": artifacts[identifier]["bytes_sha256"]}
            for identifier in sorted(identifiers) if identifier in artifacts
            and artifacts[identifier]["hash_status"] == "verified"
            and type(artifacts[identifier]["bytes_sha256"]) is str]


def _property(data):
    rows = [row["snapshot"] for row in data["rows"] if row["table"] == "event_properties"
            and row["row_id"] == data["target"]["property_id"]]
    contract.require(len(rows) == 1, "adjudication_property_snapshot_required")
    return rows[0]


async def action_context(db, *, actor_user_id, property_ids):
    contract.require(type(property_ids) is list and 1 <= len(property_ids) <= contract.MAX_ITEMS,
                     "adjudication_item_limit")
    ids = [contract.identifier(value) for value in property_ids]
    contract.require(len(set(ids)) == len(ids), "duplicate_adjudication_target")
    grant = await _reader(db, actor_user_id)
    from services.scientific_result_dossier import result_dossier
    from services.scientific_result_effects import resolve_result_status
    targets = []
    total = 0
    for identifier in ids:
        subject = await _subject(db, identifier)
        total += len(subject.text.encode())
        contract.require(total <= 16 * 1024 * 1024, "combined_adjudication_subject_limit")
        data, heads = subject.data, await _heads(db, identifier)
        impact, impact_hash = await _impact(db, identifier)
        prop = _property(data)
        supported = prop["property_key"] == "phonon_min_frequency" and prop["unit"] == "THz"
        profiles = list(contract.PROFILES) if supported else []
        if data["native_import"] is None and profiles:
            profiles.remove("native-sampled-frequency-extraction/1.0.0")
        evidence = _required_artifacts(data)
        reasons = [] if supported else ["unsupported_result_profile"]
        if not evidence:
            reasons.append("verified_direct_source_unavailable")
        if len(evidence) > 50:
            raise contract.ScientificAdjudicationError("adjudication_evidence_inventory_limit")
        if prop["relation"] != "exact":
            reasons.append("acceptance_requires_exact_sampled_quantity")
        targets.append({"property_id": identifier, "subject_id": str(subject.subject_id),
            "subject_sha256": subject.sha256, "event_id": data["target"]["event_id"],
            "event_revision": data["target"]["event_revision"], "impact_sha256": impact_hash,
            "available_profiles": profiles, "required_artifacts": evidence,
            "heads": [{"scope": scope, "decision_id": str(heads[scope]["id"]) if scope in heads else None}
                      for scope in contract.SCOPES],
            "status": await resolve_result_status(db, property_id=identifier),
            "impact": impact, "reason_codes": reasons,
            # Side-by-side evidence belongs to this very same stable snapshot,
            # not an earlier independently fetched browser dossier.
            "dossier": await result_dossier(db, actor_user_id=actor_user_id, property_id=identifier)})
    result = {"version": contract.CONTEXT_VERSION, "actor_user_id": str(actor_user_id),
              "actor_grant_id": str(grant["id"]) if grant is not None else None,
              "can_review": grant is not None, "max_items": contract.MAX_ITEMS, "targets": targets}
    contract.require(len(canonical(result)) <= contract.MAX_RESPONSE_BYTES, "adjudication_context_response_limit")
    return result


@asynccontextmanager
async def _write(db, *, dry_run):
    contract.require(type(dry_run) is bool, "explicit_adjudication_preview_required")
    await require_read_session(db)
    contract.require(await db.scalar(sa.text("SHOW transaction_isolation")) == "serializable",
                     "serializable_adjudication_required")
    nested = await db.begin_nested()
    outcome = {"changed": False}
    try:
        await db.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
        yield outcome
        await db.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
        await db.execute(sa.text("SET CONSTRAINTS sa67_complete DEFERRED"))
        if dry_run or not outcome["changed"]:
            await nested.rollback()
        else:
            await nested.commit()
    except BaseException:
        if nested.is_active:
            await nested.rollback()
        raise


def _preview(request, actor, grant):
    return {"version": contract.PREVIEW_VERSION, "actor_user_id": str(actor), "actor_grant_id": str(grant),
        "request_key": request["request_key"], "request_sha256": digest(request),
        "preview_sha256": contract.preview_binding(request, actor, grant), "can_commit": True,
        "items": [{"decision_id": item["decision_id"], "subject_id": item["subject_id"],
            "property_id": item["property_id"], "scope": item["scope"], "profile_version": item["profile_version"],
            "decision": item["decision"], "subject_sha256": item["expected_subject_sha256"],
            "expected_previous_decision_id": item["expected_previous_decision_id"],
            "impact_sha256": item["expected_impact_sha256"]} for item in request["items"]],
        "database_mutated": False, **contract.AUTHORITY}


async def _receipt(db, stored, *, replayed=False):
    rows = (await db.execute(sa.text("""SELECT d.*,
        public.sclib_scientific_adjudication_record_hash_v1(to_jsonb(d)) AS verified_record_sha256
        FROM scientific_result_decisions d WHERE d.request_id=:id ORDER BY d.item_index LIMIT 21"""),
        {"id": stored["id"]})).mappings().all()
    contract.require(len(rows) == stored["item_count"] and [row["item_index"] for row in rows] == list(range(len(rows))),
                     "complete_adjudication_receipt_required")
    request = contract.validate_request(json.loads(stored["request_json"]))
    contract.require(digest(request) == stored["request_sha256"]
        and request["request_key"] == stored["request_key"]
        and request["version"] == stored["request_version"]
        and len(request["items"]) == len(rows), "adjudication_receipt_binding_invalid")
    for row, item in zip(rows, request["items"], strict=True):
        aliases = {"id": "decision_id", "predecessor_id": "expected_previous_decision_id"}
        uuid_fields = ("id", "subject_id", "property_id", "predecessor_id", "resolves_decision_id", "extraction_decision_id")
        contract.require(all((str(row[key]) if row[key] is not None else None) == item[aliases.get(key, key)]
            for key in uuid_fields)
            and all(row[key] == item[key] for key in ("scope", "profile_version", "decision", "reason_code"))
            and row["actor_user_id"] == stored["actor_user_id"] and row["actor_grant_id"] == stored["actor_grant_id"]
            and row["item_sha256"] == digest(item) and row["record_sha256"] == row["verified_record_sha256"],
            "adjudication_receipt_item_binding_invalid")
    return {"version": contract.RECEIPT_VERSION, "request_id": str(stored["id"]),
        "request_key": stored["request_key"], "request_sha256": stored["request_sha256"],
        "preview_sha256": contract.preview_binding(request, stored["actor_user_id"], stored["actor_grant_id"]),
        # The HTTP caller can set this only after its outer transaction exits.
        "committed": False, "replayed": replayed,
        "items": [{"decision_id": str(row["id"]), "subject_id": str(row["subject_id"]),
            "property_id": str(row["property_id"]), "scope": row["scope"], "profile_version": row["profile_version"],
            "decision": row["decision"], "decision_sha256": row["record_sha256"]} for row in rows],
        **contract.AUTHORITY}


async def _request_row(db, actor_user_id, key):
    relation = _table("scientific_adjudication_requests")
    return (await db.execute(sa.select(relation).where(relation.c.actor_user_id == _uuid(str(actor_user_id)),
        relation.c.request_key == key))).mappings().one_or_none()


async def inspect_request(db, *, actor_user_id, request_key):
    """A historical exact receipt, not current scientific or serving approval."""
    contract.request_key(request_key)
    await require_read_session(db)
    await _reviewer(db, actor_user_id)
    stored = await _request_row(db, actor_user_id, request_key)
    return None if stored is None else await _receipt(db, stored, replayed=True)


async def adjudicate(db, *, actor_user_id, request, expected_preview_sha256=None, dry_run=True):
    """Rehearse or append one complete enumerated request; never outer-commit."""
    request = contract.validate_request(request)
    if not dry_run:
        contract.checksum(expected_preview_sha256)
    async with _write(db, dry_run=dry_run) as outcome:
        grant = await _reviewer(db, actor_user_id)
        stored = await _request_row(db, actor_user_id, request["request_key"])
        if stored is not None:
            _conflict(stored["request_sha256"] == digest(request) and stored["request_json"].encode() == canonical(request),
                      "adjudication_request_key_conflict")
            preview = _preview(request, stored["actor_user_id"], stored["actor_grant_id"])
            if not dry_run:
                _conflict(expected_preview_sha256 == preview["preview_sha256"], "adjudication_preview_actor_changed")
            result = preview if dry_run else await _receipt(db, stored, replayed=True)
        else:
            preview = _preview(request, actor_user_id, grant["id"])
            if not dry_run:
                _conflict(expected_preview_sha256 == preview["preview_sha256"], "adjudication_preview_actor_changed")
            subjects, total = {}, 0
            for item in request["items"]:
                identifier = item["property_id"]
                if identifier not in subjects:
                    subject = await _subject(db, identifier)
                    total += len(subject.text.encode())
                    contract.require(total <= 16 * 1024 * 1024, "combined_adjudication_subject_limit")
                    subjects[identifier] = subject
                subject = subjects[identifier]
                _conflict(str(subject.subject_id) == item["subject_id"] and subject.sha256 == item["expected_subject_sha256"],
                          "adjudication_subject_changed")
                _, impact_hash = await _impact(db, identifier)
                _conflict(impact_hash == item["expected_impact_sha256"], "adjudication_impact_changed")
                heads = await _heads(db, identifier)
                head = heads.get(item["scope"])
                _conflict((str(head["id"]) if head else None) == item["expected_previous_decision_id"],
                          "adjudication_head_changed")
            relation = _table("scientific_result_subjects")
            for identifier, subject in subjects.items():
                current = (await db.execute(sa.select(relation).where(relation.c.id == subject.subject_id))).mappings().one_or_none()
                if current is not None:
                    _conflict(current["subject_sha256"] == subject.sha256 and current["basis_json"] == subject.text,
                              "adjudication_stored_subject_mismatch")
                    continue
                target = subject.data["target"]
                fields = {key: _uuid(target[key]) for key in
                          ("property_id", "event_id", "state_id", "sample_id", "structure_id", "producer_run_id", "native_outcome_id")}
                await db.execute(relation.insert().values(id=subject.subject_id, **fields,
                    event_revision=target["event_revision"], material_id=target["material_id"],
                    subject_version="scientific-result-subject/1.0.0", property_row_sha256=subject.property_row_sha256,
                    basis_json=subject.text, subject_sha256=subject.sha256))
            request_id = uuid5(NAMESPACE_URL, "scientific-adjudication:" + str(actor_user_id) + ":" + request["request_key"])
            requests = _table("scientific_adjudication_requests")
            stored = (await db.execute(requests.insert().values(id=request_id, actor_user_id=_uuid(str(actor_user_id)),
                actor_grant_id=grant["id"], request_key=request["request_key"], request_version=contract.VERSION,
                request_json=canonical(request).decode(), request_sha256=digest(request), item_count=len(request["items"]))
                .returning(requests))).mappings().one()
            decisions = _table("scientific_result_decisions")
            for index, item in enumerate(request["items"]):
                target = subjects[item["property_id"]].data["target"]
                await db.execute(decisions.insert().values(id=_uuid(item["decision_id"]), request_id=request_id,
                    item_index=index, subject_id=_uuid(item["subject_id"]), property_id=_uuid(item["property_id"]),
                    event_id=_uuid(target["event_id"]), scope=item["scope"], profile_version=item["profile_version"],
                    decision=item["decision"], reason_code=item["reason_code"], predecessor_id=_uuid(item["expected_previous_decision_id"]),
                    resolves_decision_id=_uuid(item["resolves_decision_id"]), extraction_decision_id=_uuid(item["extraction_decision_id"]),
                    actor_user_id=_uuid(str(actor_user_id)), actor_grant_id=grant["id"], item_sha256=digest(item)))
            outcome["changed"] = True
            result = preview if dry_run else await _receipt(db, stored)
    return result
