"""Actual synthetic reviewer decisions; no real science or source is approved."""
from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from models.db import Base
from services import scientific_adjudication as service
from services import scientific_adjudication_contract as contract
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import digest
from services.scientific_result_effects import resolve_result_status
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_freeze import state
from tests.test_scientific_result_dossier import prepared

db_session = _serializable_db_session


def request_for(context, *, decision="accept", scope="extraction_fidelity", key=None):
    items = []
    for target in context["targets"]:
        profiles = [name for name in target["available_profiles"] if contract.PROFILES[name][0] == scope]
        profile = profiles[0]
        heads = {row["scope"]: row["decision_id"] for row in target["heads"]}
        items.append({"decision_id": str(uuid4()), "subject_id": target["subject_id"],
            "property_id": target["property_id"], "scope": scope, "profile_version": profile,
            "expected_subject_sha256": target["subject_sha256"], "expected_previous_decision_id": heads[scope],
            "expected_impact_sha256": target["impact_sha256"], "decision": decision,
            "reason_code": {"accept": "evidence_and_scope_match", "reject": "scientific_concern",
                            "request_clarification": "insufficient_evidence"}[decision],
            "rationale": "Synthetic reviewer checked only the declared retained fixture evidence.",
            "proposition": contract.PROFILES[profile][1], "limitations": list(contract.LIMITATIONS),
            "checks": {name: "satisfied" if decision == "accept" else "unresolved" for name in contract.CHECKS},
            "evidence_refs": deepcopy(target["required_artifacts"]) if decision == "accept" else [],
            "source_inspection_attested": decision == "accept", "resolves_decision_id": None,
            "extraction_decision_id": heads["extraction_fidelity"] if scope == "scientific_result" and decision == "accept" else None})
    return {"version": contract.VERSION, "request_key": key or "synthetic-adjudication:" + uuid4().hex, "items": items}


async def setup(db):
    fixture, ids = await prepared(db)
    actor = fixture["actors"]["reviewer"]
    context = await service.action_context(db, actor_user_id=actor, property_ids=[ids["property"]])
    return fixture, ids, actor, context


async def append(db, actor, request):
    preview = await service.adjudicate(db, actor_user_id=actor, request=request)
    receipt = await service.adjudicate(db, actor_user_id=actor, request=request,
        expected_preview_sha256=preview["preview_sha256"], dry_run=False)
    assert receipt["committed"] is False  # Only the caller can establish commit.
    await db.commit()
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    return preview, receipt


async def test_context_and_real_preview_preserve_all_rows_and_matching_evidence(db_session):
    fixture, ids, actor, context = await setup(db_session)
    target = context["targets"][0]
    assert target["dossier"]["target"]["property_id"] == ids["property"]
    assert target["dossier"]["result"]["value"] < 0
    assert target["dossier"]["state"]["pressure_gpa"] is None
    assert target["dossier"]["run"]["run_kind"] == "extraction"
    before = await state(db_session)
    repeated = await service.action_context(db_session, actor_user_id=actor, property_ids=[ids["property"]])
    assert repeated == context
    request = request_for(context)
    preview = await service.adjudicate(db_session, actor_user_id=actor, request=request)
    assert preview == await service.adjudicate(db_session, actor_user_id=actor, request=request)
    assert preview["can_commit"] and not preview["database_mutated"]
    assert await state(db_session) == before
    assert not preview["ml_training_approved"] and not preview["public_release_authorized"]
    assert "Synthetic reviewer" not in str(preview)


@pytest.mark.parametrize("decision,expected", [("accept", "accepted"), ("reject", "rejected"),
                                               ("request_clarification", "clarification_required")])
async def test_exact_decisions_are_auditable_and_leave_original_rows_unchanged(db_session, decision, expected):
    _, ids, actor, context = await setup(db_session)
    before = await state(db_session)
    request = request_for(context, decision=decision)
    _, receipt = await append(db_session, actor, request)
    after = await state(db_session)
    assert receipt["items"][0]["decision"] == decision
    assert len(after["scientific_result_decisions"]) == len(before["scientific_result_decisions"]) + 1
    ignored = {"scientific_result_subjects", "scientific_adjudication_requests", "scientific_result_decisions",
               "research_integrity_epoch", "research_publication_epoch", "source_lifecycle_epoch"}
    assert {key: value for key, value in after.items() if key not in ignored} == {
        key: value for key, value in before.items() if key not in ignored}
    result = await resolve_result_status(db_session, property_id=ids["property"])
    fidelity = next(row for row in result["scopes"] if row["scope"] == "extraction_fidelity")
    assert fidelity["effective_status"] == expected
    assert fidelity["scientific_scope_accepted"] is False
    assert all(not row["scientific_scope_accepted"] for row in result["scopes"])


async def test_identical_replay_is_full_sql_and_epoch_noop(db_session):
    _, _, actor, context = await setup(db_session)
    request = request_for(context)
    preview, receipt = await append(db_session, actor, request)
    before = await state(db_session)
    replay = await service.adjudicate(db_session, actor_user_id=actor, request=request,
        expected_preview_sha256=preview["preview_sha256"], dry_run=False)
    assert {**replay, "replayed": False} == receipt
    assert await state(db_session) == before
    changed = deepcopy(request)
    changed["items"][0]["rationale"] += " Changed private rationale."
    with pytest.raises(contract.ScientificAdjudicationConflict):
        await service.adjudicate(db_session, actor_user_id=actor, request=changed,
            expected_preview_sha256=preview["preview_sha256"], dry_run=False)
    assert await state(db_session) == before


async def test_two_scopes_can_be_atomically_declared_without_event_approval(db_session):
    _, ids, actor, context = await setup(db_session)
    request = request_for(context)
    science = request_for(context, scope="scientific_result")["items"][0]
    science["extraction_decision_id"] = request["items"][0]["decision_id"]
    request["items"].append(science)
    _, receipt = await append(db_session, actor, request)
    assert len(receipt["items"]) == 2
    result = await resolve_result_status(db_session, property_id=ids["property"])
    assert [row["scientific_scope_accepted"] for row in result["scopes"]] == [False, True]
    events = Base.metadata.tables["research_events"]
    assert await db_session.scalar(sa.select(events.c.review_status).where(events.c.id == UUID(ids["event"]))) == "pending"


@pytest.mark.parametrize("field", ["subject", "impact", "head", "preview_actor"])
async def test_stale_pin_refuses_every_write(db_session, field):
    _, _, actor, context = await setup(db_session)
    request = request_for(context)
    preview = await service.adjudicate(db_session, actor_user_id=actor, request=request)
    expected = preview["preview_sha256"]
    if field == "subject": request["items"][0]["expected_subject_sha256"] = "0" * 64
    if field == "impact": request["items"][0]["expected_impact_sha256"] = "0" * 64
    if field == "head": request["items"][0]["expected_previous_decision_id"] = str(uuid4())
    if field == "preview_actor": expected = "0" * 64
    else: expected = contract.preview_binding(request, actor, context["actor_grant_id"])
    before = await state(db_session)
    with pytest.raises(contract.ScientificAdjudicationConflict):
        await service.adjudicate(db_session, actor_user_id=actor, request=request,
            expected_preview_sha256=expected, dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("role", ["curator", "publisher", "member", "admin"])
async def test_no_actor_or_legacy_role_escalation(db_session, role):
    fixture, _, _, context = await setup(db_session)
    before = await state(db_session)
    with pytest.raises(ResearchAccessDenied):
        await service.adjudicate(db_session, actor_user_id=fixture["actors"][role], request=request_for(context))
    assert await state(db_session) == before


async def test_batch_conflict_rolls_back_all_valid_earlier_items(db_session):
    fixture, ids, actor, _ = await setup(db_session)
    _, second = await prepared(db_session)
    context = await service.action_context(db_session, actor_user_id=actor, property_ids=[ids["property"], second["property"]])
    request = request_for(context)
    request["items"][1]["expected_impact_sha256"] = "0" * 64
    before = await state(db_session)
    with pytest.raises(contract.ScientificAdjudicationConflict):
        await service.adjudicate(db_session, actor_user_id=actor, request=request)
    assert await state(db_session) == before


async def test_exact_request_receipt_is_actor_scoped_and_contains_no_private_rationale(db_session):
    fixture, _, actor, context = await setup(db_session)
    request = request_for(context)
    _, receipt = await append(db_session, actor, request)
    found = await service.inspect_request(db_session, actor_user_id=actor, request_key=request["request_key"])
    assert found["request_id"] == receipt["request_id"]
    assert found["request_sha256"] == digest(request)
    assert "Synthetic reviewer" not in str(found)
    with pytest.raises(ResearchAccessDenied):
        await service.inspect_request(db_session, actor_user_id=fixture["actors"]["curator"], request_key=request["request_key"])


async def test_existing_sql_registered_uuid4_subject_is_reused_without_conflict(db_session):
    from tests.test_research_freeze import add
    from tests.test_scientific_adjudication_schema import capture
    _, ids, actor, original = await setup(db_session)
    registered = await add(db_session, "scientific_result_subjects", **await capture(db_session, UUID(ids["property"])))
    assert registered["id"].version == 4
    assert str(registered["id"]) != original["targets"][0]["subject_id"]
    context = await service.action_context(db_session, actor_user_id=actor, property_ids=[ids["property"]])
    assert context["targets"][0]["subject_id"] == str(registered["id"])
    _, receipt = await append(db_session, actor, request_for(context))
    assert receipt["items"][0]["subject_id"] == str(registered["id"])
