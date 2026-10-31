"""Exact claim preview/commit, reusing the existing immutable review ledger.

All previews execute and roll back the real SQL path. Commit is caller owned;
review decisions never mutate claims, source bindings, QC or ML authority.
"""
import hashlib
import json
from dataclasses import replace
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa

from models.db import Base
from services import materials_adjudication_contract as contract
from services import scientific_adjudication as legacy
from services.materials_review_subject import VERSION as SUBJECT_VERSION, capture_subject
from services.research_release_manifest import canonical, digest
from services.scientific_result_subject import require_read_session


async def _subject(db, result_id):
    subject = await capture_subject(db, result_kind="claim", result_id=result_id)
    table = Base.metadata.tables["scientific_result_subjects"]
    stored = (await db.execute(sa.select(table).where(table.c.claim_id == UUID(str(result_id)),
        table.c.subject_sha256 == subject.sha256))).mappings().one_or_none()
    if stored is not None:
        legacy._conflict(stored["basis_json"] == subject.text and stored["property_row_sha256"] == subject.result_row_sha256,
                         "adjudication_stored_subject_mismatch")
        return replace(subject, subject_id=stored["id"])
    return subject


async def _heads(db, result_id):
    table = Base.metadata.tables["scientific_result_decisions"]; successor = table.alias("successor")
    rows = (await db.execute(sa.select(table).where(table.c.claim_id == UUID(str(result_id)),
        ~sa.exists(sa.select(successor.c.id).where(successor.c.predecessor_id == table.c.id)))
        .order_by(table.c.scope).limit(3))).mappings().all()
    contract.require(len(rows) <= 2 and len({r["scope"] for r in rows}) == len(rows), "adjudication_head_inventory_invalid")
    return {row["scope"]: row for row in rows}


async def _impact(db, result_id):
    value = await db.scalar(sa.text("SELECT public.sclib_materials_claim_impact_v2(:id)"), {"id": UUID(str(result_id))})
    contract.require(type(value) is str and 0 < len(value.encode()) <= 1048576, "bounded_adjudication_impact_required")
    result = json.loads(value)
    contract.require(type(result) is dict and result["version"] == "materials-claim-impact/2.0.0", "adjudication_impact_unavailable")
    return result, hashlib.sha256(value.encode()).hexdigest()


def evidence(data):
    rows = {(r["table"], r["row_id"]): r["snapshot"] for r in data["rows"]}
    result = []
    for (name, key), row in sorted(rows.items()):
        if name != "claim_source_occurrences" or row["claim_id"] != data["target"]["result_id"]: continue
        revision = rows["source_revisions", row["source_revision_id"]]
        capture = rows["source_captures", row["capture_id"]]
        if row["binding_status"] == "reviewed" and revision["version_status"] == "pinned":
            result.append({"occurrence_id": key, "source_revision_id": row["source_revision_id"],
                           "capture_id": row["capture_id"], "bytes_sha256": capture["bytes_sha256"]})
    contract.require(len(result) <= 50, "adjudication_evidence_inventory_limit")
    return result


async def action_context(db, *, actor_user_id, targets):
    contract.require(type(targets) is list and 1 <= len(targets) <= contract.MAX_ITEMS, "adjudication_item_limit")
    ids = []
    for target in targets:
        contract.legacy._object(target, ("result_kind", "result_id"))
        contract.require(target["result_kind"] == "claim", "unsupported_materials_adjudication_target")
        ids.append(contract.identifier(target["result_id"]))
    contract.require(len(set(ids)) == len(ids), "duplicate_adjudication_target")
    grant = await legacy._reader(db, actor_user_id)
    from services.materials_review_context import review_context
    from services.materials_review_effects import resolve_claim_status
    result, size = [], 0
    for key in ids:
        subject = await _subject(db, key); size += len(subject.text.encode())
        contract.require(size <= 16 * 1024 * 1024, "combined_adjudication_subject_limit")
        heads = await _heads(db, key); impact, impact_sha = await _impact(db, key)
        dossier = await review_context(db, actor_user_id=actor_user_id, result_kind="claim", result_id=key)
        profiles = (["reported-tc-fidelity/1.0.0", "experimental-tc-review/1.0.0"]
                    if dossier["result"]["property_type"] == "tc" else ["reported-non-detection-fidelity/1.0.0"])
        refs = evidence(subject.data)
        result.append({"result_kind": "claim", "result_id": key, "subject_id": str(subject.subject_id),
            "subject_sha256": subject.sha256, "result_row_sha256": subject.result_row_sha256,
            "available_profiles": profiles, "eligible_evidence_refs": refs,
            "heads": [{"scope": scope, "decision_id": str(heads[scope]["id"]) if scope in heads else None} for scope in contract.SCOPES],
            "impact_sha256": impact_sha, "impact": impact, "status": await resolve_claim_status(db, key),
            "reason_codes": [] if refs else ["pinned_reviewed_source_occurrence_unavailable"], "dossier": dossier})
    value = {"version": contract.CONTEXT_VERSION, "actor_user_id": str(actor_user_id),
        "actor_grant_id": str(grant["id"]) if grant is not None else None, "can_review": grant is not None,
        "max_items": contract.MAX_ITEMS, "targets": result,
        "acceptance_requires_successful_sql_preview": True, **contract.AUTHORITY}
    contract.require(len(canonical(value)) <= contract.MAX_RESPONSE_BYTES, "adjudication_context_response_limit")
    return value


def _preview(request, actor, grant):
    return {"version": contract.PREVIEW_VERSION, "actor_user_id": str(actor), "actor_grant_id": str(grant),
        "request_key": request["request_key"], "request_sha256": digest(request),
        "preview_sha256": contract.preview_binding(request, actor, grant), "can_commit": True,
        "items": [{key: item[key] for key in ("decision_id", "subject_id", "result_kind", "result_id", "scope",
            "profile_version", "decision", "expected_subject_sha256", "expected_previous_decision_id", "expected_impact_sha256")}
            for item in request["items"]], "database_mutated": False, **contract.AUTHORITY}


async def _receipt(db, stored, *, replayed=False):
    request = contract.validate_request(json.loads(stored["request_json"]))
    rows = (await db.execute(sa.text("""SELECT d.*,
      d.record_sha256=public.sclib_scientific_adjudication_record_hash_v1(to_jsonb(d)) AS intact
      FROM scientific_result_decisions d WHERE request_id=:id ORDER BY item_index LIMIT 21"""),
      {"id": stored["id"]})).mappings().all()
    contract.require(digest(request) == stored["request_sha256"] and request["version"] == stored["request_version"]
        and request["request_key"] == stored["request_key"] and len(rows) == stored["item_count"] == len(request["items"]),
        "adjudication_receipt_binding_invalid")
    for index, (row, item) in enumerate(zip(rows, request["items"], strict=True)):
        aliases = {"id": "decision_id", "claim_id": "result_id", "predecessor_id": "expected_previous_decision_id"}
        contract.require(row["intact"] and row["property_id"] is None and row["item_index"] == index
            and row["item_sha256"] == digest(item) and row["actor_user_id"] == stored["actor_user_id"]
            and row["actor_grant_id"] == stored["actor_grant_id"]
            and all((str(row[k]) if row[k] is not None else None) == item[aliases.get(k,k)]
                    for k in ("id", "subject_id", "claim_id", "predecessor_id", "resolves_decision_id", "extraction_decision_id"))
            and all(row[k] == item[k] for k in ("scope", "profile_version", "decision", "reason_code")),
            "adjudication_receipt_item_binding_invalid")
    return {"version": contract.RECEIPT_VERSION, "request_id": str(stored["id"]), "request_key": stored["request_key"],
        "request_sha256": stored["request_sha256"],
        "preview_sha256": contract.preview_binding(request, stored["actor_user_id"], stored["actor_grant_id"]),
        "committed": False, "replayed": replayed,
        "items": [{"decision_id": str(r["id"]), "subject_id": str(r["subject_id"]), "result_kind": "claim",
                   "result_id": str(r["claim_id"]), "scope": r["scope"], "profile_version": r["profile_version"],
                   "decision": r["decision"], "decision_sha256": r["record_sha256"]} for r in rows], **contract.AUTHORITY}


async def inspect_request(db, *, actor_user_id, request_key):
    contract.request_key(request_key); await require_read_session(db); await legacy._reviewer(db, actor_user_id)
    stored = await legacy._request_row(db, actor_user_id, request_key)
    return None if stored is None or stored["request_version"] != contract.VERSION else await _receipt(db, stored, replayed=True)


async def adjudicate(db, *, actor_user_id, request, expected_preview_sha256=None, dry_run=True):
    request = contract.validate_request(request)
    if not dry_run: contract.checksum(expected_preview_sha256)
    async with legacy._write(db, dry_run=dry_run) as outcome:
        grant = await legacy._reviewer(db, actor_user_id)
        stored = await legacy._request_row(db, actor_user_id, request["request_key"])
        if stored is not None:
            legacy._conflict(stored["request_sha256"] == digest(request) and stored["request_json"].encode() == canonical(request),
                             "adjudication_request_key_conflict")
            preview = _preview(request, stored["actor_user_id"], stored["actor_grant_id"])
            if not dry_run: legacy._conflict(expected_preview_sha256 == preview["preview_sha256"], "adjudication_preview_actor_changed")
            result = preview if dry_run else await _receipt(db, stored, replayed=True)
        else:
            preview = _preview(request, actor_user_id, grant["id"])
            if not dry_run: legacy._conflict(expected_preview_sha256 == preview["preview_sha256"], "adjudication_preview_actor_changed")
            subjects, size = {}, 0
            for item in request["items"]:
                key = item["result_id"]
                if key not in subjects:
                    subjects[key] = await _subject(db, key); size += len(subjects[key].text.encode())
                    contract.require(size <= 16 * 1024 * 1024, "combined_adjudication_subject_limit")
                subject = subjects[key]
                legacy._conflict(str(subject.subject_id) == item["subject_id"] and subject.sha256 == item["expected_subject_sha256"], "adjudication_subject_changed")
                _, impact_sha = await _impact(db, key)
                legacy._conflict(impact_sha == item["expected_impact_sha256"], "adjudication_impact_changed")
                head = (await _heads(db, key)).get(item["scope"])
                legacy._conflict((str(head["id"]) if head else None) == item["expected_previous_decision_id"], "adjudication_head_changed")
            table = Base.metadata.tables["scientific_result_subjects"]
            for key, subject in subjects.items():
                current = (await db.execute(sa.select(table).where(table.c.id == subject.subject_id))).mappings().one_or_none()
                if current is not None:
                    legacy._conflict(current["subject_sha256"] == subject.sha256 and current["basis_json"] == subject.text, "adjudication_stored_subject_mismatch")
                    continue
                target = subject.data["target"]
                fields = {k: legacy._uuid(target[k]) for k in ("event_id", "state_id", "sample_id", "structure_id", "producer_run_id", "native_outcome_id")}
                await db.execute(table.insert().values(id=subject.subject_id, claim_id=UUID(key), property_id=None, **fields,
                    event_revision=target["event_revision"], material_id=target["material_id"], subject_version=SUBJECT_VERSION,
                    property_row_sha256=subject.result_row_sha256, basis_json=subject.text, subject_sha256=subject.sha256))
            request_id = uuid5(NAMESPACE_URL, "materials-adjudication:" + str(actor_user_id) + ":" + request["request_key"])
            table = Base.metadata.tables["scientific_adjudication_requests"]
            stored = (await db.execute(table.insert().values(id=request_id, actor_user_id=UUID(str(actor_user_id)),
                actor_grant_id=grant["id"], request_key=request["request_key"], request_version=contract.VERSION,
                request_json=canonical(request).decode(), request_sha256=digest(request), item_count=len(request["items"]))
                .returning(table))).mappings().one()
            table = Base.metadata.tables["scientific_result_decisions"]
            for index, item in enumerate(request["items"]):
                await db.execute(table.insert().values(id=UUID(item["decision_id"]), request_id=request_id, item_index=index,
                    subject_id=UUID(item["subject_id"]), claim_id=UUID(item["result_id"]), property_id=None,
                    event_id=UUID(subjects[item["result_id"]].data["target"]["event_id"]), scope=item["scope"], profile_version=item["profile_version"],
                    decision=item["decision"], reason_code=item["reason_code"], predecessor_id=legacy._uuid(item["expected_previous_decision_id"]),
                    resolves_decision_id=legacy._uuid(item["resolves_decision_id"]), extraction_decision_id=legacy._uuid(item["extraction_decision_id"]),
                    actor_user_id=UUID(str(actor_user_id)), actor_grant_id=grant["id"], item_sha256=digest(item)))
            outcome["changed"] = True
            result = preview if dry_run else await _receipt(db, stored)
    return result
