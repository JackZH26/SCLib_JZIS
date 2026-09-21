"""Reviewer-owned exact result/original-passage links and live resolution.

The append-only ledger records a reviewed relation between one immutable
extraction revision and one immutable original-passage revision.  It neither
copies passage text nor establishes causality, independent support, source
rights, publication approval or scientific acceptance.
"""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa

from models.db import Base
from models.scientific_result_passage_v1 import (
    CLAIM_VERSION,
    SAMPLE_VERSION,
    TABLE,
    VERSION as RECORD_VERSION,
)
from services.research_access import ResearchAccessDenied, active_grant
from services.research_release_manifest import canonical, digest
from services.scientific_result_subject import require_read_session

REQUEST_VERSION = "scientific-result-passage-review/1.0.0"
CONTEXT_VERSION = "scientific-result-passage-context/1.0.0"
PREVIEW_VERSION = "scientific-result-passage-preview/1.0.0"
RECEIPT_VERSION = "scientific-result-passage-receipt/1.0.0"
MAX_BYTES = 32 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
_HASH = re.compile(r"^[0-9a-f]{64}$")
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_REQUEST_FIELDS = {
    "version", "request_key", "action", "parent_result_revision_id",
    "expected_parent_result_sha256", "source_evidence_revision_id",
    "expected_source_evidence_record_sha256", "expected_source_content_sha256",
    "expected_source_locator_sha256", "expected_claim_identity_sha256",
    "expected_sample_identity_sha256", "expected_predecessor_id",
    "expected_predecessor_sha256",
}


class ResultPassageConflict(ValueError):
    """Pinned evidence, reviewer, request key or current head changed."""


class ResultPassageUnavailable(ValueError):
    """The exact reviewed-link inventory could not be verified safely."""


def _table(name=TABLE):
    return Base.metadata.tables[name]


def _uuid(value, *, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not str:
        raise ValueError("A canonical UUID is required")
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError("A canonical UUID is required")
    return parsed


def _checksum(value, *, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ValueError("A lowercase SHA-256 is required")
    return value


def loads(body):
    if type(body) is not bytes or len(body) > MAX_BYTES:
        raise ValueError("Reviewed link request exceeds its byte limit")
    try:
        def closed_object(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("Reviewed link request contains a repeated key")
                result[key] = item
            return result

        value = json.loads(body, object_pairs_hook=closed_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Reviewed link request requires JSON") from exc
    canonical(value)
    return value


def validate_request(value):
    if type(value) is not dict or set(value) != _REQUEST_FIELDS:
        raise ValueError("A closed reviewed-link request is required")
    if value["version"] != REQUEST_VERSION or value["action"] not in {"establish", "withdraw"}:
        raise ValueError("Unsupported reviewed-link action")
    if type(value["request_key"]) is not str or _KEY.fullmatch(value["request_key"]) is None:
        raise ValueError("A bounded request key is required")
    for field in ("parent_result_revision_id", "source_evidence_revision_id"):
        _uuid(value[field])
    for field in (
        "expected_parent_result_sha256", "expected_source_evidence_record_sha256",
        "expected_source_content_sha256", "expected_source_locator_sha256",
        "expected_claim_identity_sha256", "expected_sample_identity_sha256",
    ):
        _checksum(value[field])
    predecessor = _uuid(value["expected_predecessor_id"], nullable=True)
    predecessor_hash = _checksum(value["expected_predecessor_sha256"], nullable=True)
    if (predecessor is None) != (predecessor_hash is None):
        raise ValueError("The predecessor ID and hash must be supplied together")
    if value["action"] == "withdraw" and predecessor is None:
        raise ValueError("Withdrawal requires the exact established head")
    canonical(value)
    return value


async def _reviewer(db, actor_user_id):
    return await active_grant(db, actor_user_id, role="reviewer")


async def _reader(db, actor_user_id):
    await require_read_session(db)
    try:
        return await _reviewer(db, actor_user_id)
    except ResearchAccessDenied:
        await active_grant(db, actor_user_id, role="curator")
        return None


async def _head(db, parent_id, evidence_id):
    links = _table()
    successor = links.alias("successor")
    rows = (await db.execute(sa.select(links).where(
        links.c.parent_result_revision_id == parent_id,
        links.c.source_evidence_revision_id == evidence_id,
        ~sa.exists(sa.select(successor.c.id).where(successor.c.predecessor_id == links.c.id)),
    ).limit(2))).mappings().all()
    if len(rows) > 1:
        raise ResultPassageUnavailable("Reviewed link has multiple current heads")
    return rows[0] if rows else None


async def _exact_context(db, parent_id, evidence_id):
    row = (await db.execute(sa.text("""
      WITH exact AS (
        SELECT x.id AS parent_id,x.paper_id,x.source_snapshot_sha256,
          x.record_sha256 AS parent_sha256,x.input_record_sha256,x.projection_json,
          e.id AS evidence_id,e.paper_id AS evidence_paper_id,e.source_snapshot_sha256 AS evidence_snapshot_sha256,
          e.record_sha256 AS evidence_sha256,
          e.content_sha256,e.source_locator,e.chunk_key,e.permission_status,e.chunk_kind,
          x.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(x)) AS parent_intact,
          e.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(e)) AS evidence_intact,
          public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p)) AS current_snapshot,
          EXISTS(SELECT 1 FROM public.chunk_evidence_current c
            WHERE c.chunk_id=e.chunk_key AND c.evidence_revision_id=e.id) AS original_current,
          EXISTS(SELECT 1 FROM public.chunk_evidence_current c
            JOIN public.rag_evidence_revisions d ON d.id=c.evidence_revision_id
            WHERE d.parent_extraction_revision_id=x.id AND d.paper_id=x.paper_id
              AND d.source_snapshot_sha256=x.source_snapshot_sha256 AND d.chunk_kind='derived_fact'
              AND d.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(d))) AS result_current
        FROM public.rag_extraction_revisions x
        JOIN public.rag_evidence_revisions e ON e.id=:evidence_id
        JOIN public.papers p ON p.id=x.paper_id
        WHERE x.id=:parent_id
      ), identities AS (
        SELECT exact.*,
          jsonb_build_object(
            'version',CAST(:claim_version AS text),'parent_result_revision_id',parent_id::text,
            'parent_result_sha256',parent_sha256,'input_record_sha256',input_record_sha256,
            'projection_sha256',encode(public.digest(convert_to(projection_json::text,'UTF8'),'sha256'),'hex'))::text AS claim_json,
          jsonb_build_object(
            'version',CAST(:sample_version AS text),'parent_result_revision_id',parent_id::text,
            'input_record_sha256',input_record_sha256,'scope','exact_retained_result_record')::text AS sample_json,
          source_locator::text AS locator_json
        FROM exact
      )
      SELECT identities.*,
        encode(public.digest(convert_to(claim_json,'UTF8'),'sha256'),'hex') AS claim_sha256,
        encode(public.digest(convert_to(sample_json,'UTF8'),'sha256'),'hex') AS sample_sha256,
        encode(public.digest(convert_to(locator_json,'UTF8'),'sha256'),'hex') AS locator_sha256
      FROM identities
    """), {"parent_id": parent_id, "evidence_id": evidence_id,
             "claim_version": CLAIM_VERSION, "sample_version": SAMPLE_VERSION})).mappings().one_or_none()
    if row is None:
        raise ResultPassageUnavailable("Exact extraction or passage revision unavailable")
    if not (row["parent_intact"] and row["evidence_intact"] and row["original_current"] and row["result_current"]
            and row["current_snapshot"] == row["source_snapshot_sha256"]
            and row["evidence_snapshot_sha256"] == row["source_snapshot_sha256"]
            and row["evidence_paper_id"] == row["paper_id"]
            and row["chunk_kind"] == "original_passage" and row["permission_status"] != "restricted"):
        raise ResultPassageConflict("Exact result or passage is not current and eligible")
    return row


def _context_wire(row, head, *, can_review):
    return {
        "version": CONTEXT_VERSION,
        "can_review": can_review,
        "parent_result_revision_id": str(row["parent_id"]),
        "parent_result_sha256": row["parent_sha256"],
        "source_evidence_revision_id": str(row["evidence_id"]),
        "source_evidence_record_sha256": row["evidence_sha256"],
        "source_content_sha256": row["content_sha256"],
        "source_locator_sha256": row["locator_sha256"],
        "paper_id": row["paper_id"],
        "source_snapshot_sha256": row["source_snapshot_sha256"],
        "claim_identity": json.loads(row["claim_json"]),
        "claim_identity_sha256": row["claim_sha256"],
        "sample_identity": json.loads(row["sample_json"]),
        "sample_identity_sha256": row["sample_sha256"],
        "current_head": None if head is None else {
            "bridge_revision_id": str(head["id"]),
            "bridge_record_sha256": head["record_sha256"],
            "action": head["action"],
        },
        "relation": "exact_result_original_passage",
        "scientific_acceptance": False,
        "causal_explanation_established": False,
    }


async def action_context(db, *, actor_user_id, parent_result_revision_id, source_evidence_revision_id):
    grant = await _reader(db, actor_user_id)
    parent_id = _uuid(parent_result_revision_id)
    evidence_id = _uuid(source_evidence_revision_id)
    row = await _exact_context(db, parent_id, evidence_id)
    return _context_wire(row, await _head(db, parent_id, evidence_id), can_review=grant is not None)


def request_from_context(context, *, request_key, action):
    if type(context) is not dict or context.get("version") != CONTEXT_VERSION:
        raise ValueError("An exact reviewed-link context is required")
    head = context.get("current_head")
    request = {
        "version": REQUEST_VERSION,
        "request_key": request_key,
        "action": action,
        "parent_result_revision_id": context["parent_result_revision_id"],
        "expected_parent_result_sha256": context["parent_result_sha256"],
        "source_evidence_revision_id": context["source_evidence_revision_id"],
        "expected_source_evidence_record_sha256": context["source_evidence_record_sha256"],
        "expected_source_content_sha256": context["source_content_sha256"],
        "expected_source_locator_sha256": context["source_locator_sha256"],
        "expected_claim_identity_sha256": context["claim_identity_sha256"],
        "expected_sample_identity_sha256": context["sample_identity_sha256"],
        "expected_predecessor_id": None if head is None else head["bridge_revision_id"],
        "expected_predecessor_sha256": None if head is None else head["bridge_record_sha256"],
    }
    return validate_request(request)


@asynccontextmanager
async def _write(db, *, dry_run):
    if type(dry_run) is not bool or db.new or db.dirty or db.deleted:
        raise ValueError("A clean dedicated session and explicit preview mode are required")
    await require_read_session(db)
    if await db.scalar(sa.text("SHOW transaction_isolation")) != "serializable":
        raise ValueError("Reviewed link writes require SERIALIZABLE isolation")
    nested = await db.begin_nested()
    changed = {"value": False}
    try:
        await db.execute(sa.text("SELECT public.sclib_research_publication_lock_v1()"))
        yield changed
        if dry_run or not changed["value"]:
            await nested.rollback()
        else:
            await nested.commit()
    except BaseException:
        if nested.is_active:
            await nested.rollback()
        raise


def _preview(request, actor, grant, decision_id):
    binding = {"request": request, "actor_user_id": str(actor), "actor_grant_id": str(grant),
               "bridge_revision_id": str(decision_id)}
    return {
        "version": PREVIEW_VERSION,
        "request_key": request["request_key"],
        "request_sha256": digest(request),
        "preview_sha256": digest(binding),
        "bridge_revision_id": str(decision_id),
        "action": request["action"],
        "can_commit": True,
        "database_mutated": False,
        "scientific_acceptance": False,
        "causal_explanation_established": False,
    }


def _stored_matches(row, request):
    mapping = {
        "parent_result_revision_id": "parent_result_revision_id",
        "expected_parent_result_sha256": "parent_result_sha256",
        "source_evidence_revision_id": "source_evidence_revision_id",
        "expected_source_evidence_record_sha256": "source_evidence_record_sha256",
        "expected_source_content_sha256": "source_content_sha256",
        "expected_source_locator_sha256": "source_locator_sha256",
        "expected_claim_identity_sha256": "claim_identity_sha256",
        "expected_sample_identity_sha256": "sample_identity_sha256",
        "expected_predecessor_id": "predecessor_id",
        "expected_predecessor_sha256": "predecessor_sha256",
    }
    for requested, stored in mapping.items():
        left = request[requested]
        right = row[stored]
        if isinstance(right, UUID):
            right = str(right)
        if left != right:
            return False
    return row["version"] == RECORD_VERSION and row["action"] == request["action"]


def _receipt(row, request, preview, *, replayed):
    return {
        "version": RECEIPT_VERSION,
        "request_key": request["request_key"],
        "request_sha256": digest(request),
        "preview_sha256": preview["preview_sha256"],
        "bridge_revision_id": str(row["id"]),
        "bridge_record_sha256": row["record_sha256"],
        "parent_result_revision_id": str(row["parent_result_revision_id"]),
        "source_evidence_revision_id": str(row["source_evidence_revision_id"]),
        "action": row["action"],
        "committed": False,
        "replayed": replayed,
        "scientific_acceptance": False,
        "causal_explanation_established": False,
    }


async def review(db, *, actor_user_id, request, expected_preview_sha256=None, dry_run=True):
    request = validate_request(request)
    if not dry_run:
        _checksum(expected_preview_sha256)
    actor = _uuid(str(actor_user_id))
    async with _write(db, dry_run=dry_run) as changed:
        grant = await _reviewer(db, actor)
        links = _table()
        existing = (await db.execute(sa.select(links).where(
            links.c.actor_user_id == actor, links.c.request_key == request["request_key"]))).mappings().one_or_none()
        decision_id = uuid5(NAMESPACE_URL, "sclib-result-passage:" + str(actor) + ":" + request["request_key"])
        preview = _preview(request, actor, grant["id"], decision_id)
        if not dry_run and expected_preview_sha256 != preview["preview_sha256"]:
            raise ResultPassageConflict("Reviewer or exact preview changed")
        replayed = existing is not None
        if existing is not None:
            if existing["id"] != decision_id or not _stored_matches(existing, request):
                raise ResultPassageConflict("Request key already binds another reviewed link")
            verified = await db.scalar(sa.text(
                "SELECT public.sclib_scientific_result_passage_hash_v1(to_jsonb(r)) FROM public.scientific_result_passage_links r WHERE id=:id"),
                {"id": existing["id"]})
            if verified != existing["record_sha256"]:
                raise ResultPassageUnavailable("Reviewed link receipt integrity mismatch")
            row = existing
        else:
            parent_id = _uuid(request["parent_result_revision_id"])
            evidence_id = _uuid(request["source_evidence_revision_id"])
            context = await _exact_context(db, parent_id, evidence_id)
            head = await _head(db, parent_id, evidence_id)
            actual_head_id = None if head is None else str(head["id"])
            actual_head_hash = None if head is None else head["record_sha256"]
            checks = (
                context["parent_sha256"] == request["expected_parent_result_sha256"],
                context["evidence_sha256"] == request["expected_source_evidence_record_sha256"],
                context["content_sha256"] == request["expected_source_content_sha256"],
                context["locator_sha256"] == request["expected_source_locator_sha256"],
                context["claim_sha256"] == request["expected_claim_identity_sha256"],
                context["sample_sha256"] == request["expected_sample_identity_sha256"],
                actual_head_id == request["expected_predecessor_id"],
                actual_head_hash == request["expected_predecessor_sha256"],
                request["action"] == ("establish" if head is None or head["action"] == "withdraw" else "withdraw"),
            )
            if not all(checks):
                raise ResultPassageConflict("Exact evidence or reviewed-link head changed")
            values = {
                "id": decision_id,
                "version": RECORD_VERSION,
                "actor_user_id": actor,
                "actor_grant_id": grant["id"],
                "parent_result_revision_id": parent_id,
                "parent_result_sha256": context["parent_sha256"],
                "source_evidence_revision_id": evidence_id,
                "source_evidence_record_sha256": context["evidence_sha256"],
                "source_content_sha256": context["content_sha256"],
                "source_locator_sha256": context["locator_sha256"],
                "paper_id": context["paper_id"],
                "source_snapshot_sha256": context["source_snapshot_sha256"],
                "claim_identity_json": context["claim_json"],
                "claim_identity_sha256": context["claim_sha256"],
                "sample_identity_json": context["sample_json"],
                "sample_identity_sha256": context["sample_sha256"],
                "relation": "exact_result_original_passage",
                "action": request["action"],
                "reason_code": "reviewed_exact_claim_sample_passage" if request["action"] == "establish" else "review_withdrawn",
                "predecessor_id": None if head is None else head["id"],
                "predecessor_sha256": None if head is None else head["record_sha256"],
                "request_key": request["request_key"],
            }
            row = dict((await db.execute(links.insert().values(**values).returning(links))).mappings().one())
            changed["value"] = True
        result = preview if dry_run else _receipt(row, request, preview, replayed=replayed)
    return result


async def inspect_request(db, *, actor_user_id, request_key):
    await require_read_session(db)
    await _reviewer(db, actor_user_id)
    if type(request_key) is not str or _KEY.fullmatch(request_key) is None:
        raise ValueError("A bounded request key is required")
    links = _table()
    row = (await db.execute(sa.select(links).where(
        links.c.actor_user_id == _uuid(str(actor_user_id)), links.c.request_key == request_key))).mappings().one_or_none()
    if row is None:
        return None
    verified = await db.scalar(sa.text(
        "SELECT public.sclib_scientific_result_passage_hash_v1(to_jsonb(r)) FROM public.scientific_result_passage_links r WHERE id=:id"),
        {"id": row["id"]})
    if verified != row["record_sha256"]:
        raise ResultPassageUnavailable("Reviewed link receipt integrity mismatch")
    return {
        "version": RECEIPT_VERSION,
        "request_key": request_key,
        "bridge_revision_id": str(row["id"]),
        "bridge_record_sha256": row["record_sha256"],
        "parent_result_revision_id": str(row["parent_result_revision_id"]),
        "source_evidence_revision_id": str(row["source_evidence_revision_id"]),
        "action": row["action"],
        "committed": True,
        "replayed": True,
        "scientific_acceptance": False,
        "causal_explanation_established": False,
    }


async def resolve_current_links(db, pairs):
    """Resolve reviewed heads inside the caller's current read snapshot."""
    if type(pairs) is not list or len(pairs) > 100:
        raise ResultPassageUnavailable("Reviewed link pair inventory exceeds its limit")
    normalized = []
    for pair in pairs:
        if type(pair) is not tuple or len(pair) != 2:
            raise ResultPassageUnavailable("Reviewed link pair inventory is invalid")
        normalized.append((_uuid(pair[0]), _uuid(pair[1])))
    if len(set(normalized)) != len(normalized):
        raise ResultPassageUnavailable("Reviewed link pair inventory is repeated")
    if not normalized:
        return {}
    links = _table()
    successor = links.alias("successor")
    predicate = sa.tuple_(links.c.parent_result_revision_id, links.c.source_evidence_revision_id).in_(normalized)
    rows = (await db.execute(sa.select(links,
        sa.func.sclib_scientific_result_passage_hash_v1(sa.func.to_jsonb(links.table_valued())).label("verified_hash"),
    ).where(predicate, ~sa.exists(sa.select(successor.c.id).where(successor.c.predecessor_id == links.c.id))).limit(101))).mappings().all()
    if len(rows) > len(normalized):
        raise ResultPassageUnavailable("Reviewed link head inventory is inconsistent")
    grants = _table("research_role_grants")
    users = _table("users")
    revoked = _table("research_role_revocations")
    grant_ids = {row["actor_grant_id"] for row in rows if row["action"] == "establish"}
    authority = {}
    if grant_ids:
        grant_rows = (await db.execute(sa.select(grants, users.c.is_active, users.c.email_verified).join(
            users, users.c.id == grants.c.user_id).where(grants.c.id.in_(grant_ids),
            ~sa.exists(sa.select(revoked.c.id).where(revoked.c.grant_id == grants.c.id))))).mappings().all()
        for grant in grant_rows:
            body = {str(key): str(value) if isinstance(value, UUID) else value for key, value in grant.items()
                    if key not in {"id", "created_at", "record_sha256", "is_active", "email_verified"}}
            if digest(body) != grant["record_sha256"]:
                raise ResultPassageUnavailable("Reviewed link authority integrity mismatch")
            if grant["is_active"] and grant["email_verified"] and grant["role"] == "reviewer":
                authority[(grant["user_id"], grant["id"])] = True
    resolved = {}
    for row in rows:
        if row["verified_hash"] != row["record_sha256"]:
            raise ResultPassageUnavailable("Reviewed link integrity mismatch")
        if row["action"] != "establish":
            continue
        if not authority.get((row["actor_user_id"], row["actor_grant_id"])):
            continue
        try:
            current = await _exact_context(db, row["parent_result_revision_id"], row["source_evidence_revision_id"])
        except ResultPassageConflict:
            continue
        if not (row["parent_result_sha256"] == current["parent_sha256"]
                and row["source_evidence_record_sha256"] == current["evidence_sha256"]
                and row["source_content_sha256"] == current["content_sha256"]
                and row["source_locator_sha256"] == current["locator_sha256"]
                and row["source_snapshot_sha256"] == current["source_snapshot_sha256"]
                and row["claim_identity_sha256"] == current["claim_sha256"]
                and row["sample_identity_sha256"] == current["sample_sha256"]):
            raise ResultPassageUnavailable("Reviewed link no longer matches its immutable identities")
        resolved[(str(row["parent_result_revision_id"]), str(row["source_evidence_revision_id"]))] = {
            "bridge_revision_id": str(row["id"]),
            "bridge_record_sha256": row["record_sha256"],
            "claim_identity_sha256": row["claim_identity_sha256"],
            "sample_identity_sha256": row["sample_identity_sha256"],
            "source_locator_sha256": row["source_locator_sha256"],
        }
    return resolved
