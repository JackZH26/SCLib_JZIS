"""Current exact claim decisions and conservative downstream review holds."""
import asyncio
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from services import materials_adjudication_contract as contract
from services import scientific_result_effects as legacy
from services.materials_review_subject import capture_subject
from services.research_access import ResearchAccessDenied, active_grant
from services.research_release_manifest import digest

VERSION = "materials-claim-review-status/2.0.0"


async def _resolve(db, claim_id, budget):
    subject = await capture_subject(db, result_kind="claim", result_id=claim_id)
    budget["bytes"] += len(subject.text.encode()); legacy._require(budget["bytes"] <= legacy.MAX_BYTES)
    rows = (await db.execute(sa.text("""SELECT d.*,s.subject_sha256,
      d.record_sha256=public.sclib_scientific_adjudication_record_hash_v1(to_jsonb(d))
      AND s.record_sha256=public.sclib_scientific_adjudication_record_hash_v1(to_jsonb(s))
      AND r.record_sha256=public.sclib_scientific_adjudication_record_hash_v1(to_jsonb(r))
      AND s.subject_sha256=public.sclib_scientific_adjudication_text_hash_v1(s.basis_json)
      AND r.request_sha256=public.sclib_scientific_adjudication_text_hash_v1(r.request_json)
      AND d.item_sha256=public.sclib_scientific_adjudication_text_hash_v1(
        public.sclib_scientific_adjudication_canonical_v1(r.request_json::jsonb->'items'->d.item_index))
      AND s.claim_id=d.claim_id AND s.event_id=d.event_id AND d.property_id IS NULL
      AND r.request_version='materials-result-adjudication/2.0.0' AS intact
      FROM scientific_result_decisions d JOIN scientific_result_subjects s ON s.id=d.subject_id
      JOIN scientific_adjudication_requests r ON r.id=d.request_id
      WHERE d.claim_id=:id AND NOT EXISTS(SELECT 1 FROM scientific_result_decisions x WHERE x.predecessor_id=d.id)
      ORDER BY d.scope LIMIT 3"""), {"id": UUID(str(claim_id))})).mappings().all()
    legacy._require(len(rows) <= 2)
    heads, roles = {}, {}
    for row in rows:
        legacy._require(row["intact"] is True and row["scope"] in contract.SCOPES and row["scope"] not in heads
            and row["profile_version"] in contract.PROFILES and contract.PROFILES[row["profile_version"]][0] == row["scope"])
        heads[row["scope"]] = row; available = True
        if row["decision"] == "accept":
            try: await active_grant(db, row["actor_user_id"], role="reviewer", grant_id=row["actor_grant_id"])
            except ResearchAccessDenied: available = False
        roles[row["scope"]] = available
    held, source_observation = await legacy._sources(db, subject.data)
    # A faithful transcription can survive a paper hold as a historical
    # extraction assertion. The separate source_held veto still prevents use.
    fidelity = legacy._scope_status("extraction_fidelity", heads.get("extraction_fidelity"),
        subject_sha256=subject.sha256, source_held=False, reviewer_available=roles.get("extraction_fidelity",False))
    science = legacy._scope_status("scientific_result", heads.get("scientific_result"),
        subject_sha256=subject.sha256, source_held=held, reviewer_available=roles.get("scientific_result",False), extraction=fidelity)
    result = {"version": VERSION, "result_kind": "claim", "result_id": str(claim_id),
        "subject_sha256": subject.sha256, "scopes": [fidelity,science], "source_held": held, **contract.AUTHORITY}
    result["revision_sha256"] = digest({"status": result, "source_observation": source_observation, "reviewer_available": roles})
    return result


async def resolve_claim_status(db, claim_id):
    contract.identifier(str(claim_id))
    try:
        async with asyncio.timeout(legacy.MAX_SECONDS):
            return await _resolve(db, claim_id, {"bytes":0})
    except (SQLAlchemyError, TimeoutError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise legacy.ScientificResultStatusUnavailable("materials_claim_status_unavailable") from None


async def gate_exact_claim_reviews(db, claim_ids):
    """Negative-only overlay; None means no reviewed claim in this inventory.

The absence of a hold never establishes a scientific or ML qualification.
Existing release policy, evidence and source-rights gates remain mandatory.
"""
    legacy._require(type(claim_ids) in {list,tuple,set} and len(claim_ids) <= 20000)
    legacy._require(not (db.new or db.dirty or db.deleted))
    keys = sorted({UUID(contract.identifier(str(key))) for key in claim_ids})
    if not keys: return None
    try:
        async with asyncio.timeout(legacy.MAX_SECONDS):
            nested = await db.begin_nested()
            try:
                await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
                await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                query = sa.text("SELECT DISTINCT claim_id FROM scientific_result_decisions WHERE claim_id IN :ids ORDER BY claim_id LIMIT 201").bindparams(sa.bindparam("ids",expanding=True,type_=sa.Uuid()))
                reviewed = (await db.execute(query,{"ids":keys})).scalars().all()
                legacy._require(len(reviewed) <= legacy.MAX_GATE_RESULTS)
                if not reviewed: return None
                budget = {"bytes":0}; statuses = {str(key): await _resolve(db,key,budget) for key in reviewed}
                if any(s["source_held"] or any(scope["effective_status"] in legacy.BLOCKED for scope in s["scopes"]) for s in statuses.values()):
                    raise legacy.ScientificResultReviewHeld("exact_materials_claim_review_hold")
                return digest({key:s["revision_sha256"] for key,s in sorted(statuses.items())})
            finally:
                if nested.is_active: await nested.rollback()
    except legacy.ScientificResultReviewHeld: raise
    except (SQLAlchemyError, TimeoutError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise legacy.ScientificResultStatusUnavailable("materials_claim_status_unavailable") from None
