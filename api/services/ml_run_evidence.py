"""Exact private run-review text, not a source licence or scientific signoff."""
from __future__ import annotations

import hashlib
from uuid import UUID

import sqlalchemy as sa

from models.ml_run_evidence_v1 import MAX_BYTES, TABLES, VERSION
from models.ml_use_request import identifier, sha
from services.ml_use_access import _read_session, _write
from services.ml_use_preflight import match
from services.ml_use_reconstruction import require
from services.research_access import ResearchAccessDenied, require_research_admin, table


def boundary():
    return {"scope": "private_run_review_text_not_scientific_acceptance_or_execution_authority",
        "scientific_acceptance": False, "source_permission_granted": False,
        "run_authorization_granted": False, "ml_training_approved": False, "training_execution": "disabled"}


def text_bytes(value, expected_sha256):
    require(type(value) is str and bool(value.strip()) and "\x00" not in value)
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError:
        require(False)
    require(0 < len(raw) <= MAX_BYTES)
    match(hashlib.sha256(raw).hexdigest() == sha(expected_sha256))
    return raw


async def store(db, decision, raw):
    require(decision["decision"] == "approve" and type(raw) is bytes)
    text_bytes(raw.decode("utf-8"), decision["evidence_sha256"])
    await db.execute(table(TABLES[0]).insert().values(decision_id=decision["id"], payload=raw))


async def expiry(db, decision):
    plans, parents = table("ml_use_run_plans"), table("ml_use_submissions")
    return (await db.execute(sa.select(parents.c.expires_at).join(plans, plans.c.submission_id == parents.c.id)
        .where(plans.c.id == decision["plan_id"]))).scalar_one()


async def available(db, decision, now):
    """Only exact retained text availability; caller separately checks issuer roles."""
    if decision is None or decision["decision"] != "approve" or (await expiry(db, decision)).timestamp() <= now:
        return False
    relation = table(TABLES[0])
    observed = await db.scalar(sa.select(sa.func.encode(sa.func.digest(relation.c.payload, "sha256"), "hex"))
        .where(relation.c.decision_id == decision["id"]))
    return observed is not None and observed == decision["evidence_sha256"]


async def load_decision(db, decision_id, decision_sha256):
    from services import ml_use_runs as runs
    relation = table("ml_use_run_decisions")
    row = (await db.execute(sa.select(relation).where(relation.c.id == UUID(identifier(decision_id))))).mappings().one_or_none()
    if row is None:
        raise runs.RunNotObserved("run_review_unavailable")
    match(runs.verified(row, "decision")["record_sha256"] == sha(decision_sha256))
    return row


async def read(db, *, actor_user_id, decision_id, decision_sha256):
    from services import ml_use_runs as runs
    await _read_session(db)
    await runs.approver_admission(db, actor_user_id)
    decision = await load_decision(db, decision_id, decision_sha256)
    if str(decision["actor_user_id"]) != str(actor_user_id):
        raise ResearchAccessDenied("original_review_author_required")
    await runs.approver_admission(db, actor_user_id, approver_grant_id=decision["approver_grant_id"],
                                curator_grant_id=decision["curator_grant_id"])
    now = await db.scalar(sa.select(sa.func.extract("epoch", sa.func.clock_timestamp())))
    if not await available(db, decision, now):
        raise runs.RunNotObserved("run_review_document_unavailable")
    raw = bytes(await db.scalar(sa.select(table(TABLES[0]).c.payload).where(table(TABLES[0]).c.decision_id == decision["id"])))
    text = raw.decode("utf-8")
    text_bytes(text, decision["evidence_sha256"])
    return {"version": VERSION, "decision_id": str(decision["id"]), "decision_sha256": decision["record_sha256"],
        "decision": runs.dto(decision, "decision"),
        "plan_id": str(decision["plan_id"]), "plan_sha256": decision["plan_sha256"],
        "content_sha256": decision["evidence_sha256"], "content_type": "text/plain; charset=utf-8",
        "text": text, "size_bytes": len(raw), "access_expires_at": (await expiry(db, decision)).isoformat(), **boundary()}


async def purge(db, *, actor_user_id, decision_id, decision_sha256, dry_run=False):
    require(dry_run is False)
    async with _write(db, False) as operation:
        await require_research_admin(db, actor_user_id)
        decision = await load_decision(db, decision_id, decision_sha256)
        if str(decision["actor_user_id"]) != str(actor_user_id):
            raise ResearchAccessDenied("original_review_author_required")
        purges = table(TABLES[1])
        previous = (await db.execute(sa.select(purges).where(purges.c.decision_id == decision["id"]))).mappings().one_or_none()
        if previous is None:
            if not await db.scalar(sa.select(sa.exists().where(table(TABLES[0]).c.decision_id == decision["id"]))):
                from services.ml_use_runs import RunNotObserved
                raise RunNotObserved("run_review_document_unavailable")
            previous = (await db.execute(purges.insert().values(decision_id=decision["id"],
                actor_user_id=UUID(str(actor_user_id)), reason="reviewer_request").returning(purges))).mappings().one()
            operation["changed"] = True
        return {"version": VERSION, "decision_id": str(decision["id"]), "decision_sha256": decision["record_sha256"],
            "evidence_state": "purged", "replayed": not operation["changed"],
            "purge": {"reason": previous["reason"], "created_at": previous["created_at"].isoformat()}, **boundary()}


async def purge_expired(db, *, actor_user_id, dry_run=False):
    require(dry_run is False)
    async with _write(db, False) as operation:
        await require_research_admin(db, actor_user_id)
        evidence, decisions, plans, parents = (table(name) for name in (
            TABLES[0], "ml_use_run_decisions", "ml_use_run_plans", "ml_use_submissions"))
        rows = (await db.execute(sa.select(evidence.c.decision_id).join(decisions, decisions.c.id == evidence.c.decision_id)
            .join(plans, plans.c.id == decisions.c.plan_id).join(parents, parents.c.id == plans.c.submission_id)
            .where(parents.c.expires_at <= sa.func.clock_timestamp()).order_by(parents.c.expires_at, evidence.c.decision_id).limit(20))).scalars().all()
        for identifier_value in rows:
            await db.execute(table(TABLES[1]).insert().values(decision_id=identifier_value,
                actor_user_id=UUID(str(actor_user_id)), reason="retention_expired"))
        operation["changed"] = bool(rows)
        return {"version": VERSION, "purged_count": len(rows), "batch_limit": 20,
            "more_may_remain": len(rows) == 20, "replayed": not bool(rows), **boundary()}
