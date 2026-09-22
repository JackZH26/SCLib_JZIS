"""Bounded internal source-observation review, never source reinstatement.

Catalogue observation hashes use the frozen PostgreSQL 0056 representation;
they are not ML01 provider-version or source-byte hashes. Actor IDs must come
from a trusted authenticated caller, not an untrusted request body. This module
does not expose a write route, fetch artifacts, commit, or clear any hold.
"""
from __future__ import annotations

import hashlib
import re
from contextlib import asynccontextmanager
from datetime import datetime
from itertools import islice
from uuid import UUID

import sqlalchemy as sa

from models.db import Base
from models.source_lifecycle_v1 import POLICY_VERSION
from services.research_access import ResearchAccessDenied, active_grant
from services.research_release_manifest import canonical, digest
from services.source_lifecycle_status import (
    combined_lifecycle_revision,
    lifecycle_review_required,
    lifecycle_revision,
    overlay_source_lifecycle,
)

MAX_SOURCES = 20_000
BATCH_SIZE = 1000
MAX_REVIEW_BYTES = 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REASON = re.compile(r"[a-z][a-z0-9_]{0,159}\Z")
_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")


class SourceLifecycleError(ValueError):
    """A lifecycle binding is missing, stale, invalid or outside safe bounds."""


def _uuid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SourceLifecycleError("A valid UUID is required") from exc


def _sha(value):
    if type(value) is not str or not _SHA.fullmatch(value):
        raise SourceLifecycleError("A lowercase SHA-256 binding is required")
    return value


def _wire(row):
    return {str(key): str(value) if isinstance(value, UUID) else
            value.isoformat() if isinstance(value, datetime) else value for key, value in row.items()}


def _verify_record(row):
    if digest(_wire({key: value for key, value in row.items()
                     if key not in {"created_at", "record_sha256"}})) != row["record_sha256"]:
        raise SourceLifecycleError("Lifecycle audit record hash mismatch")


def _identifiers(values, kind):
    if isinstance(values, (str, bytes, dict)):
        raise SourceLifecycleError("A bounded iterable of source identifiers is required")
    try:
        captured = list(islice(iter(values), MAX_SOURCES + 1))
    except TypeError as exc:
        raise SourceLifecycleError("A bounded iterable of source identifiers is required") from exc
    if len(captured) > MAX_SOURCES:
        raise SourceLifecycleError("Source inventory limit exceeded")
    if kind == "work":
        return sorted({str(_uuid(value)) for value in captured})
    if any(type(value) is not str or not 1 <= len(value) <= 100 for value in captured):
        raise SourceLifecycleError("Invalid paper identifier")
    return sorted(set(captured))


async def _resolve(db, identifiers, kind):
    """One bounded statement per batch; never send expanded source JSON out."""
    source, status, identifier_type = ("papers", "status", sa.String(100)) if kind == "paper" else (
        "works", "publication_status", sa.Uuid())
    result = {}
    statement = sa.text(f"""
        SELECT s.id, s.{status} AS status, e.record_sha256,
          CASE WHEN e.id IS NOT NULL THEN
            e.record_sha256=public.sclib_source_lifecycle_record_hash_v1(to_jsonb(e))
            AND e.snapshot_sha256=public.sclib_source_lifecycle_snapshot_hash_v1(:kind,to_jsonb(s))
          ELSE true END AS valid
        FROM {source} s LEFT JOIN LATERAL (
          SELECT * FROM source_lifecycle_events WHERE {kind}_id=s.id ORDER BY revision DESC LIMIT 1
        ) e ON true WHERE s.id IN :ids
    """).bindparams(sa.bindparam("ids", expanding=True, type_=identifier_type))
    for offset in range(0, len(identifiers), BATCH_SIZE):
        selected = identifiers[offset:offset + BATCH_SIZE]
        if kind == "work":
            selected = [_uuid(value) for value in selected]
        rows = (await db.execute(statement, {"ids": selected, "kind": kind})).mappings().all()
        for row in rows:
            if row["valid"] is not True:
                raise SourceLifecycleError("Source lifecycle head no longer matches the catalogue")
            result[str(row["id"])] = (overlay_source_lifecycle(row["status"], row["record_sha256"])
                                      if row["record_sha256"] else row["status"])
    return result


async def resolve_work_lifecycle(db, work_ids):
    return await _resolve(db, _identifiers(work_ids, "work"), "work")


async def resolve_paper_lifecycle(db, paper_ids):
    """Preserve raw bibliographic status, overlay direct/accepted-Work holds.

    Only an explicitly accepted current identity map carries a Work hold. This
    is conservative negative admission, not scientific equivalence of claims.
    Review claim binding itself always requires the claim's explicit FK.
    """
    identifiers = _identifiers(paper_ids, "paper")
    result = await _resolve(db, identifiers, "paper")
    relation = Base.metadata.tables["paper_work_map"]
    for offset in range(0, len(identifiers), BATCH_SIZE):
        rows = (await db.execute(sa.select(relation.c.paper_id, relation.c.work_id).where(
            relation.c.paper_id.in_(identifiers[offset:offset + BATCH_SIZE]),
            relation.c.review_status == "accepted"))).mappings().all()
        if not rows:
            continue
        works = await resolve_work_lifecycle(db, {str(row["work_id"]) for row in rows})
        for row in rows:
            work_revision = lifecycle_revision(works.get(str(row["work_id"])))
            if work_revision is None:
                continue
            previous = result[row["paper_id"]]
            direct_revision = lifecycle_revision(previous)
            raw_status = previous["status"] if isinstance(previous, dict) else previous
            revision = combined_lifecycle_revision(direct_revision, work_revision)
            result[row["paper_id"]] = overlay_source_lifecycle(raw_status, revision)
    return result


async def _event(db, identifier):
    table = Base.metadata.tables["source_lifecycle_events"]
    row = (await db.execute(sa.select(table).where(table.c.id == identifier))).mappings().one_or_none()
    if row is None:
        raise SourceLifecycleError("Lifecycle observation unavailable")
    row = dict(row)
    _verify_record(row)
    return row


async def _current_event(db, identifier, expected_hash):
    event = await _event(db, identifier)
    if event["record_sha256"] != expected_hash:
        raise SourceLifecycleError("Exact lifecycle event hash required")
    kind = "paper" if event["paper_id"] is not None else "work"
    table, status = ("papers", "status") if kind == "paper" else ("works", "publication_status")
    current = (await db.execute(sa.text(f"""
        SELECT s.{status} AS status,
          public.sclib_source_lifecycle_snapshot_hash_v1(:kind,to_jsonb(s)) AS snapshot_sha256,
          (SELECT id FROM source_lifecycle_events WHERE {kind}_id=s.id ORDER BY revision DESC LIMIT 1) AS event_id
        FROM {table} s WHERE id=:id
    """), {"kind": kind, "id": event[f"{kind}_id"]})).mappings().one_or_none()
    if current is None or current["event_id"] != event["id"] or current["snapshot_sha256"] != event["snapshot_sha256"]:
        raise SourceLifecycleError("Source revision changed; inspect and review the current event")
    return event, current["status"]


def _review_input(*, actor_user_id, expected_event_id, expected_event_sha256, decision,
                  reason_code, claim_id=None, expected_claim_revision_sha256=None):
    if type(decision) is not str or decision not in {"retain_hold", "requires_supersession"}:
        raise SourceLifecycleError("Only negative lifecycle review decisions are supported")
    if type(reason_code) is not str or not _REASON.fullmatch(reason_code):
        raise SourceLifecycleError("A bounded reason code is required")
    if (claim_id is None) != (expected_claim_revision_sha256 is None):
        raise SourceLifecycleError("Claim identity and exact revision hash must be supplied together")
    return dict(actor_user_id=_uuid(actor_user_id), expected_event_id=_uuid(expected_event_id),
        expected_event_sha256=_sha(expected_event_sha256), decision=decision, reason_code=reason_code,
        claim_id=_uuid(claim_id) if claim_id is not None else None,
        expected_claim_revision_sha256=_sha(expected_claim_revision_sha256)
        if expected_claim_revision_sha256 is not None else None)


async def _review_document(db, arguments):
    grant = await active_grant(db, arguments["actor_user_id"], role="reviewer")
    event, _ = await _current_event(db, arguments["expected_event_id"], arguments["expected_event_sha256"])
    claim_id = arguments["claim_id"]
    if claim_id is not None:
        claim = (await db.execute(sa.text("""SELECT paper_id, work_id,
            public.sclib_source_lifecycle_snapshot_hash_v1('claim',to_jsonb(c)) AS revision_sha256
            FROM material_claims c WHERE id=:id"""), {"id": claim_id})).mappings().one_or_none()
        if (claim is None or claim["revision_sha256"] != arguments["expected_claim_revision_sha256"]
            or (event["paper_id"] is not None and claim["paper_id"] != event["paper_id"])
            or (event["work_id"] is not None and claim["work_id"] != event["work_id"])):
            raise SourceLifecycleError("Review requires the exact explicitly linked claim revision")
    return {"policy_version": POLICY_VERSION, "event_id": str(event["id"]),
        "event_sha256": event["record_sha256"], "source_snapshot_sha256": event["snapshot_sha256"],
        "claim_id": str(claim_id) if claim_id else None,
        "claim_revision_sha256": arguments["expected_claim_revision_sha256"],
        "decision": arguments["decision"], "reason_code": arguments["reason_code"],
        "reviewer_id": str(arguments["actor_user_id"]), "reviewer_grant_id": str(grant["id"]),
        "scientific_acceptance": False, "ml_training_approved": False, "source_reinstatement": False}


async def preview_source_review(db, **arguments):
    """Read-only document preparation, neither authorization receipt nor commit."""
    document = await _review_document(db, _review_input(**arguments))
    return {"document": document, "document_sha256": digest(document),
        "bytes_sha256": hashlib.sha256(canonical(document)).hexdigest(),
        "lifecycle_review_required": True, "scientific_acceptance": False,
        "ml_training_approved": False, "source_reinstatement": False}


@asynccontextmanager
async def _write(db, dry_run):
    if type(dry_run) is not bool or db.new or db.dirty or db.deleted:
        raise SourceLifecycleError("A clean dedicated session and Boolean dry_run are required")
    if (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one() != "serializable":
        raise SourceLifecycleError("Lifecycle review writes require SERIALIZABLE isolation")
    nested = await db.begin_nested()
    try:
        # Same global order as the review INSERT guard. The scientific epoch
        # fences stale artifact/claim writers when a new audit binding is added.
        for name in ("research_integrity", "research_publication", "source_lifecycle"):
            await db.execute(sa.text(f"SELECT public.sclib_{name}_lock_v1()"))
        yield
        if dry_run:
            await nested.rollback()
        else:
            await nested.commit()
    except BaseException:
        if nested.is_active:
            await nested.rollback()
        raise


async def record_source_review(db, *, actor_user_id, expected_event_id, expected_event_sha256,
        decision, reason_code, request_key, review_artifact_id, review_bytes, claim_id=None,
        expected_claim_revision_sha256=None, supersedes_id=None, dry_run=True):
    """Append an exact-version negative review; default rehearsal rolls back.

    Idempotency is scoped to actor/request key and exact immutable payload. A
    retry is rejected after the source/claim or reviewer authority changes;
    a stored historical receipt is never silently relabeled current.
    """
    arguments = _review_input(actor_user_id=actor_user_id, expected_event_id=expected_event_id,
        expected_event_sha256=expected_event_sha256, decision=decision, reason_code=reason_code,
        claim_id=claim_id, expected_claim_revision_sha256=expected_claim_revision_sha256)
    if type(request_key) is not str or not _REQUEST.fullmatch(request_key):
        raise SourceLifecycleError("A bounded idempotency request key is required")
    if type(review_bytes) is not bytes or len(review_bytes) > MAX_REVIEW_BYTES:
        raise SourceLifecycleError("Bounded actual immutable review bytes are required")
    review_artifact_id = _uuid(review_artifact_id)
    supersedes_id = _uuid(supersedes_id) if supersedes_id is not None else None
    relation = Base.metadata.tables["source_lifecycle_reviews"]
    async with _write(db, dry_run):
        document = await _review_document(db, arguments)
        expected_bytes = canonical(document)
        if review_bytes != expected_bytes:
            raise SourceLifecycleError("Actual review bytes do not match the closed canonical document")
        artifact = Base.metadata.tables["evidence_artifacts"]
        size = (await db.execute(sa.select(sa.func.octet_length(sa.cast(
            sa.func.to_jsonb(artifact.table_valued()), sa.Text))).where(artifact.c.id == review_artifact_id))).scalar_one_or_none()
        if size is None or size > MAX_REVIEW_BYTES:
            raise SourceLifecycleError("Registered review artifact unavailable or oversized")
        row = (await db.execute(sa.select(artifact).where(artifact.c.id == review_artifact_id))).mappings().one()
        if (row["kind"] != "review" or row["hash_status"] != "verified" or row["access"] != "restricted"
            or row["record_sha256"] != digest(document) or row["bytes_sha256"] != hashlib.sha256(review_bytes).hexdigest()
            or not isinstance(row["metadata"], dict) or row["metadata"].get("source_lifecycle_review") != document):
            raise SourceLifecycleError("Registered artifact does not bind this exact review document and actual bytes")
        values = dict(event_id=arguments["expected_event_id"], event_sha256=document["event_sha256"],
            source_snapshot_sha256=document["source_snapshot_sha256"], claim_id=arguments["claim_id"],
            claim_revision_sha256=arguments["expected_claim_revision_sha256"], supersedes_id=supersedes_id,
            decision=decision, policy_version=POLICY_VERSION, reason_code=reason_code,
            reviewer_id=arguments["actor_user_id"], reviewer_grant_id=_uuid(document["reviewer_grant_id"]),
            review_artifact_id=review_artifact_id, review_artifact_sha256=digest(document),
            review_bytes_sha256=hashlib.sha256(review_bytes).hexdigest(), request_key=request_key)
        existing = (await db.execute(sa.select(relation).where(relation.c.reviewer_id == arguments["actor_user_id"],
            relation.c.request_key == request_key))).mappings().one_or_none()
        replayed = existing is not None
        if replayed:
            _verify_record(existing)
            if any(existing[key] != value for key, value in values.items()):
                raise SourceLifecycleError("Idempotency key already binds a different review")
            receipt = existing
        else:
            successor = relation.alias("successor")
            prior = (await db.execute(sa.select(relation.c.id).where(
                relation.c.event_id == arguments["expected_event_id"],
                relation.c.claim_id.is_not_distinct_from(arguments["claim_id"]),
                ~sa.exists(sa.select(successor.c.id).where(successor.c.supersedes_id == relation.c.id))
            ))).scalar_one_or_none()
            if prior != supersedes_id:
                raise SourceLifecycleError("Exact current review predecessor is required")
            receipt = (await db.execute(relation.insert().values(**values).returning(relation))).mappings().one()
            _verify_record(receipt)
        successor_exists = (await db.execute(sa.select(sa.exists(sa.select(relation.c.id).where(
            relation.c.supersedes_id == receipt["id"]))))).scalar_one()
        result = {"id": str(receipt["id"]), "record_sha256": receipt["record_sha256"],
            "dry_run": dry_run, "committed": False, "replayed": replayed,
            "current_review": not successor_exists, "lifecycle_review_required": True,
            "scientific_acceptance": False, "ml_training_approved": False, "source_reinstatement": False}
    return result


async def inspect_source_lifecycle(db, *, paper_id=None, work_id=None, limit=25, before_revision=None):
    """Bounded historical observations with separate current-source information."""
    if (paper_id is None) == (work_id is None):
        raise SourceLifecycleError("Select exactly one Paper or Work")
    if type(limit) is not int or not 1 <= limit <= 100 or (before_revision is not None and
            (type(before_revision) is not int or not 1 <= before_revision <= 2_147_483_647)):
        raise SourceLifecycleError("Invalid lifecycle history window")
    kind = "paper" if paper_id is not None else "work"
    identifier = _identifiers([paper_id if kind == "paper" else work_id], kind)[0]
    source_id = identifier if kind == "paper" else _uuid(identifier)
    table = Base.metadata.tables["source_lifecycle_events"]
    query = sa.select(table).where(table.c[f"{kind}_id"] == source_id)
    head = (await db.execute(query.order_by(table.c.revision.desc()).limit(1))).mappings().one_or_none()
    if head is not None:
        _, status = await _current_event(db, head["id"], head["record_sha256"])
    else:
        statuses = await _resolve(db, [identifier], kind)
        if identifier not in statuses:
            raise SourceLifecycleError("Source unavailable")
        status = statuses[identifier]
    if before_revision is not None:
        query = query.where(table.c.revision < before_revision)
    rows = (await db.execute(query.order_by(table.c.revision.desc()).limit(limit + 1))).mappings().all()
    for row in rows:
        _verify_record(row)
    effective = ((await resolve_paper_lifecycle(db, [identifier])).get(identifier)
                 if kind == "paper" else (overlay_source_lifecycle(status, head["record_sha256"])
                                          if head is not None else status))
    return {"source_kind": kind, "source_id": identifier, "status": status,
        "head": _wire(head) if head is not None else None,
        "events": [_wire(row) for row in rows[:limit]],
        "next_before_revision": rows[limit - 1]["revision"] if len(rows) > limit else None,
        "direct_lifecycle_review_required": head is not None,
        "lifecycle_review_required": lifecycle_review_required(effective),
        "effective_lifecycle_revision": lifecycle_revision(effective), "scientific_acceptance": False,
        "ml_training_approved": False, "source_reinstatement": False}


async def inspect_source_review(db, review_id):
    """Historical receipt with live processing currentness, never eligibility."""
    relation = Base.metadata.tables["source_lifecycle_reviews"]
    row = (await db.execute(sa.select(relation).where(relation.c.id == _uuid(review_id)))).mappings().one_or_none()
    if row is None:
        raise SourceLifecycleError("Lifecycle review unavailable")
    _verify_record(row)
    current = True
    try:
        await active_grant(db, row["reviewer_id"], role="reviewer", grant_id=row["reviewer_grant_id"])
        await _review_document(db, _review_input(actor_user_id=row["reviewer_id"],
            expected_event_id=row["event_id"], expected_event_sha256=row["event_sha256"],
            decision=row["decision"], reason_code=row["reason_code"], claim_id=row["claim_id"],
            expected_claim_revision_sha256=row["claim_revision_sha256"]))
    except (ResearchAccessDenied, SourceLifecycleError):
        current = False
    if (await db.execute(sa.select(sa.exists(sa.select(relation.c.id).where(
        relation.c.supersedes_id == row["id"]))))).scalar_one():
        current = False
    return {"review": _wire(row), "current_review": current, "lifecycle_review_required": True,
        "scientific_acceptance": False, "ml_training_approved": False, "source_reinstatement": False}
