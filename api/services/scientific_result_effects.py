"""Live exact-property review effects, independent of reverse consumers.

An acceptance is scoped; it cannot grant source rights, training permission or
event-wide approval. Negative history does not disappear when a role is revoked.
No cross-request cache or transaction ownership is introduced here.
"""

from __future__ import annotations

import asyncio
import hashlib

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from services.research_access import ResearchAccessDenied, active_grant
from services.research_release_manifest import canonical, digest
from services.scientific_adjudication_contract import PROFILES, SCOPES
from services.scientific_result_subject import (
    ScientificSubjectError,
    capture_result_subject,
    identifier,
)
from services.source_lifecycle import (
    SourceLifecycleError,
    resolve_paper_lifecycle,
    resolve_work_lifecycle,
)
from services.source_visibility import source_visibility

VERSION = "scientific-result-review-status/1.0.0"
MAX_RESULTS = 20
MAX_GATE_RESULTS = 200
MAX_SECONDS = 10
MAX_BYTES = 16 * 1024 * 1024
BLOCKED = frozenset(
    {
        "rejected",
        "clarification_required",
        "stale",
        "source_held",
        "reviewer_unavailable",
        "dependency_review_held",
    }
)


class ScientificResultStatusUnavailable(ValueError):
    """Cannot verify the entire current status; never means no decision."""


class ScientificResultReviewHeld(ValueError):
    """An exact dependency has a current scientific-review hold."""


def _require(condition):
    if not condition:
        raise ScientificResultStatusUnavailable("scientific_result_status_unavailable")


async def _heads(db, property_id):
    rows = (
        (
            await db.execute(
                sa.text("""
        SELECT d.*,s.subject_sha256,s.property_row_sha256,
          d.record_sha256=public.sclib_scientific_adjudication_record_hash_v1(to_jsonb(d))
          AND s.record_sha256=public.sclib_scientific_adjudication_record_hash_v1(to_jsonb(s))
          AND r.record_sha256=public.sclib_scientific_adjudication_record_hash_v1(to_jsonb(r))
          AND s.subject_sha256=public.sclib_scientific_adjudication_text_hash_v1(s.basis_json)
          AND r.request_sha256=public.sclib_scientific_adjudication_text_hash_v1(r.request_json)
          AND d.item_sha256=public.sclib_scientific_adjudication_text_hash_v1(
            public.sclib_scientific_adjudication_canonical_v1((r.request_json::jsonb->'items')->d.item_index))
          AS intact
        FROM scientific_result_decisions d
        JOIN scientific_result_subjects s ON s.id=d.subject_id
        JOIN scientific_adjudication_requests r ON r.id=d.request_id
        WHERE d.property_id=:property_id AND NOT EXISTS (
          SELECT 1 FROM scientific_result_decisions successor WHERE successor.predecessor_id=d.id)
        ORDER BY d.scope LIMIT 3
    """),
                {"property_id": property_id},
            )
        )
        .mappings()
        .all()
    )
    _require(len(rows) <= 2)
    result = {}
    for row in rows:
        value = dict(row)
        _require(
            value["intact"] is True
            and value["scope"] in SCOPES
            and value["scope"] not in result
            and value["profile_version"] in PROFILES
            and PROFILES[value["profile_version"]][0] == value["scope"]
            and value["decision"] in {"accept", "reject", "request_clarification"}
        )
        result[value["scope"]] = value
    return result


async def _sources(db, data):
    keys = {
        name: sorted({row["row_id"] for row in data["rows"] if row["table"] == name})
        for name in ("papers", "works")
    }
    observed = {}
    for name, resolver in (("papers", resolve_paper_lifecycle), ("works", resolve_work_lifecycle)):
        values = await resolver(db, keys[name])
        _require(set(values) == set(keys[name]))
        observed[name] = {key: source_visibility(value) for key, value in sorted(values.items())}
    held = any(
        not value["reported_claim_filter_eligible"]
        for values in observed.values()
        for value in values.values()
    )
    # Only explicit negative parent/dependency states are vetoes. Pending event
    # review and restricted artifact disclosure do not nullify a new exact
    # property's private, scoped acceptance.
    for name in ("research_events", "material_claims"):
        ids = sorted({row["row_id"] for row in data["rows"] if row["table"] == name})
        if not ids:
            observed[name] = {}
            continue
        extra = ",review_status" if name == "research_events" else ""
        query = sa.text(
            f"SELECT id,validity_status{extra} FROM {name} WHERE id IN :ids"
        ).bindparams(sa.bindparam("ids", expanding=True, type_=sa.Uuid()))
        rows = (
            (await db.execute(query, {"ids": [identifier(value) for value in ids]}))
            .mappings()
            .all()
        )
        _require({str(row["id"]) for row in rows} == set(ids))
        observed[name] = {
            str(row["id"]): {key: row[key] for key in row if key != "id"} for row in rows
        }
        held |= any(
            row["validity_status"] in {"disputed", "retracted", "excluded"}
            or row.get("review_status") == "rejected"
            for row in rows
        )
    return held, observed


def _scope_status(scope, head, *, subject_sha256, source_held, reviewer_available, extraction=None):
    result = {
        "scope": scope,
        "profile_version": None,
        "decision_id": None,
        "decision_sha256": None,
        "decision": None,
        "effective_status": "unreviewed",
        "reason_codes": [],
        "scientific_scope_accepted": False,
    }
    if head is None:
        return result
    result.update(
        profile_version=head["profile_version"],
        decision_id=str(head["id"]),
        decision_sha256=head["record_sha256"],
        decision=head["decision"],
    )
    if head["subject_sha256"] != subject_sha256:
        status, reason = "stale", "scientific_subject_changed"
    elif source_held:
        status, reason = "source_held", "scientific_source_held"
    elif head["decision"] == "reject":
        status, reason = "rejected", "exact_result_rejected"
    elif head["decision"] == "request_clarification":
        status, reason = "clarification_required", "exact_result_clarification_required"
    elif not reviewer_available:
        status, reason = "reviewer_unavailable", "current_reviewer_grant_unavailable"
    elif scope == "scientific_result" and not (
        extraction
        and extraction["effective_status"] == "accepted"
        and extraction["decision_id"] == str(head["extraction_decision_id"])
    ):
        status, reason = "dependency_review_held", "current_extraction_fidelity_required"
    else:
        status, reason = "accepted", None
    result["effective_status"] = status
    result["reason_codes"] = [reason] if reason else []
    result["scientific_scope_accepted"] = scope == "scientific_result" and status == "accepted"
    return result


async def _resolve(db, property_id, budget):
    subject = await capture_result_subject(db, property_id)
    budget["bytes"] += len(subject.text.encode("utf-8"))
    _require(budget["bytes"] <= MAX_BYTES)
    heads = await _heads(db, property_id)
    held, source_observation = await _sources(db, subject.data)
    roles = {}
    for scope, head in heads.items():
        available = True
        if head["decision"] == "accept":
            try:
                await active_grant(
                    db, head["actor_user_id"], role="reviewer", grant_id=head["actor_grant_id"]
                )
            except ResearchAccessDenied:
                available = False
        roles[scope] = available
    extraction = _scope_status(
        "extraction_fidelity",
        heads.get("extraction_fidelity"),
        subject_sha256=subject.sha256,
        source_held=held,
        reviewer_available=roles.get("extraction_fidelity", False),
    )
    scientific = _scope_status(
        "scientific_result",
        heads.get("scientific_result"),
        subject_sha256=subject.sha256,
        source_held=held,
        reviewer_available=roles.get("scientific_result", False),
        extraction=extraction,
    )
    result = {
        "version": VERSION,
        "property_id": str(property_id),
        "subject_sha256": subject.sha256,
        "scopes": [extraction, scientific],
        "ml_training_approved": False,
        "public_release_authorized": False,
    }
    result["revision_sha256"] = digest(
        {"status": result, "source_observation": source_observation, "reviewer_available": roles}
    )
    return result


async def resolve_result_statuses(db, property_ids):
    _require(type(property_ids) in {list, tuple} and len(property_ids) <= MAX_RESULTS)
    keys = [identifier(value) for value in property_ids]
    _require(len(keys) == len(set(keys)))
    budget = {"bytes": 0}
    try:
        async with asyncio.timeout(MAX_SECONDS):
            return {str(key): await _resolve(db, key, budget) for key in keys}
    except (
        SQLAlchemyError,
        TimeoutError,
        ScientificSubjectError,
        SourceLifecycleError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        RecursionError,
    ):
        raise ScientificResultStatusUnavailable("scientific_result_status_unavailable") from None


async def resolve_result_status(db, property_id):
    key = identifier(property_id)
    return (await resolve_result_statuses(db, [key]))[str(key)]


async def gate_exact_property_reviews(db, property_ids):
    """Negative-only admission overlay; unchanged unreviewed policy survives.

    Resolve only actually reviewed exact IDs. A read savepoint temporarily bounds
    older callers' statement timeout and restores their transaction settings.
    It never upgrades isolation or opens a second connection.
    """
    _require(type(property_ids) in {list, tuple, set} and len(property_ids) <= 20000)
    _require(not (db.new or db.dirty or db.deleted))
    keys = sorted({identifier(value) for value in property_ids})
    if not keys:
        return hashlib.sha256(canonical([])).hexdigest()
    try:
        async with asyncio.timeout(MAX_SECONDS):
            nested = await db.begin_nested()
            try:
                await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
                await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                statement = sa.text("""SELECT DISTINCT property_id FROM scientific_result_decisions
                    WHERE property_id IN :ids ORDER BY property_id LIMIT :limit""").bindparams(
                    sa.bindparam("ids", expanding=True, type_=sa.Uuid())
                )
                reviewed = (
                    (await db.execute(statement, {"ids": keys, "limit": MAX_GATE_RESULTS + 1}))
                    .scalars()
                    .all()
                )
                _require(len(reviewed) <= MAX_GATE_RESULTS)
                # Consumer inventory is separate from the 20-item interactive
                # request limit, but shares one complete byte/deadline budget.
                budget = {"bytes": 0}
                statuses = {str(key): await _resolve(db, key, budget) for key in reviewed}
                for status in statuses.values():
                    if any(scope["effective_status"] in BLOCKED for scope in status["scopes"]):
                        raise ScientificResultReviewHeld("exact_scientific_result_review_hold")
                return digest(
                    {key: value["revision_sha256"] for key, value in sorted(statuses.items())}
                )
            finally:
                if nested.is_active:
                    await nested.rollback()
    except ScientificResultReviewHeld:
        raise
    except (
        SQLAlchemyError,
        TimeoutError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        RecursionError,
    ):
        raise ScientificResultStatusUnavailable("scientific_result_status_unavailable") from None
