"""Real owned SQL with explicitly synthetic pilot/account declarations only."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from models.ml_pilot_registration_v1 import TABLES
from services import ml_pilot_accounting as accounting
from services import ml_pilot_registration as service
from services import ml_pilot_registration_documents as documents
from services.ml_use_preflight import MlUsePreflightConflict
from services.research_access import ResearchAccessDenied
from services.research_audit_retention import has_research_audit_references
from services.research_publication import grant_role, revoke_role
from tests.test_ml_label_capture import read_snapshot
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as db_session


def no_authority(value):
    for key, item in service.boundary().items():
        assert value[key] == item


async def fixture(db):
    people = [uuid4() for _ in range(4)]
    for i, uid in enumerate(people):
        await add(
            db,
            "users",
            id=uid,
            email=f"pilot-{uid}@example.test",
            name="SYNTHETIC pilot account",
            is_active=True,
            email_verified=True,
            is_admin=i == 0,
        )
    owner = people[0]
    curator = await grant_role(
        db,
        actor_user_id=owner,
        user_id=owner,
        role="curator",
        reason_code="synthetic_pilot",
        dry_run=False,
    )
    bindings = []
    for i, uid in enumerate(people[1:]):
        reviewer = await grant_role(
            db,
            actor_user_id=owner,
            user_id=uid,
            role="reviewer",
            reason_code="synthetic_pilot",
            dry_run=False,
        )
        bindings.append(
            {
                "reviewer_alias": f"SYNTHETIC-reviewer-{i}",
                "user_id": str(uid),
                "reviewer_grant_id": reviewer["id"],
            }
        )
    root = Path(__file__).resolve().parents[2]
    selection = json.loads((root / "docs/pilot/selection.template.json").read_bytes())
    protocol = b"SYNTHETIC protocol bytes, not an actual approved study or source licence."
    selection.update(
        pilot_id="SYNTHETIC-" + uuid4().hex,
        protocol_status="approved",
        protocol_sha256=documents.sha(protocol),
        approval_reference="Synthetic assertion only",
        selection_status="frozen",
        selection_method="Synthetic fixture only",
        strata=[{"id": "synthetic", "definition": "Synthetic group, not a material-family quota"}],
        candidates=[
            {
                "candidate_id": f"SYNTHETIC-{i}",
                "selection_kind": "actual_source_event",
                "stratum_id": "synthetic",
                "family": "synthetic",
                "source_class": "synthetic",
                "source_reference": "PRIVATE_SYNTHETIC_SOURCE",
                "event_locator": "Synthetic position",
                "selection_rationale": "No actual source event",
            }
            for i in range(60)
        ],
        reviewers=[
            {"id": b["reviewer_alias"], "kind": "human", "roles": [role]}
            for b, role in zip(bindings, documents.ROLES, strict=True)
        ],
        second_review_candidate_ids=["SYNTHETIC-0"],
        independence_plan="Synthetic only; no actual participants",
        selected_at="2026-09-01T00:00:00Z",
        frozen_at="2026-09-02T00:00:00Z",
    )
    selection["selection_sha256"] = accounting.selection_hash(selection)
    selection_raw = accounting.canonical(selection)
    inputs = {
        "selection_raw": selection_raw,
        "protocol_raw": protocol,
        "selection_file_sha256": documents.sha(selection_raw),
        "protocol_file_sha256": documents.sha(protocol),
        "selection_sha256": selection["selection_sha256"],
    }
    return {
        "people": people,
        "bindings": bindings,
        "inputs": inputs,
        "args": {
            "actor_user_id": owner,
            "curator_grant_id": curator["id"],
            "request_key": "synthetic-pilot-" + uuid4().hex,
            "commitment": documents.check(**inputs, bindings=bindings),
            "implementation": documents.implementation(),
        },
    }


async def registered(db, args):
    preview = await service.register(db, **args)
    assert preview["registration"] is None and not preview["registration_recorded"]
    no_authority(preview)
    return await service.register(
        db, **args, dry_run=False, expected_intent_sha256=preview["intent_sha256"]
    )


def decision_args(member, inputs, *, decision="accept", prior=None):
    return {
        "actor_user_id": member["user_id"],
        "participant_id": member["id"],
        "participant_sha256": member["record_sha256"],
        "registration_sha256": member["registration_sha256"],
        "request_key": "synthetic-participation-" + uuid4().hex,
        "decision": decision,
        "reason_code": "synthetic_protocol_participation",
        "supersedes_id": None if prior is None else prior["id"],
        "supersedes_sha256": None if prior is None else prior["record_sha256"],
        "document_check": documents.verify_files(**inputs) if decision == "accept" else None,
    }


async def confirmed(db, args):
    preview = await service.decide(db, **args)
    no_authority(preview)
    assert preview["decision"] is None
    return await service.decide(
        db, **args, dry_run=False, expected_intent_sha256=preview["intent_sha256"]
    )


async def test_actual_registration_preview_commit_no_source_storage_and_self_confirmation(
    db_session,
):
    f = await fixture(db_session)
    before = await state(db_session)
    await service.register(db_session, **f["args"])
    assert await state(db_session) == before
    first = await registered(db_session, f["args"])
    no_authority(first)
    reg = first["registration"]
    assert len(first["participants"]) == 3
    stable = await state(db_session)
    assert "PRIVATE_SYNTHETIC_SOURCE" not in json.dumps(
        {name: stable[name] for name in TABLES}, default=str
    )
    for alias in f["bindings"]:
        assert alias["reviewer_alias"] not in json.dumps(
            {name: stable[name] for name in TABLES}, default=str
        )
    replay = await service.register(
        db_session, **f["args"], dry_run=False, expected_intent_sha256=first["intent_sha256"]
    )
    assert (
        replay["replayed"] and replay["registration"] == reg and await state(db_session) == stable
    )
    assert reg["created_at"] > "2026-09-02"  # server time, not supplied frozen_at
    for member in first["participants"]:
        await confirmed(db_session, decision_args(member, f["inputs"]))
    await read_snapshot(db_session)
    result = await service.inspect(
        db_session,
        actor_user_id=f["people"][0],
        registration_id=reg["id"],
        registration_sha256=reg["record_sha256"],
    )
    assert result["accepted_account_count"] == 3 and result["ready_for_prospective_review"]
    no_authority(result)
    own = await service.inspect(
        db_session,
        actor_user_id=first["participants"][0]["user_id"],
        registration_id=reg["id"],
        registration_sha256=reg["record_sha256"],
    )
    assert len(own["participants"]) == 1 and "roster" not in own["registration"]


async def test_no_substitution_or_duplicate_selection_under_new_key(db_session):
    f = await fixture(db_session)
    first = await registered(db_session, f["args"])
    stable = await state(db_session)
    with pytest.raises(MlUsePreflightConflict):
        await service.register(db_session, **{**f["args"], "request_key": "changed-key"})
    with pytest.raises(MlUsePreflightConflict):
        await service.register(
            db_session,
            **{**f["args"], "curator_grant_id": str(uuid4())},
            dry_run=False,
            expected_intent_sha256=first["intent_sha256"],
        )
    assert await state(db_session) == stable


async def test_other_account_cannot_confirm_and_revoked_grant_cannot_accept(db_session):
    f = await fixture(db_session)
    first = await registered(db_session, f["args"])
    member = first["participants"][0]
    args = decision_args(member, f["inputs"])
    stable = await state(db_session)
    with pytest.raises(service.PilotNotObserved):
        await service.decide(db_session, **{**args, "actor_user_id": str(f["people"][0])})
    assert await state(db_session) == stable
    await revoke_role(
        db_session,
        actor_user_id=f["people"][0],
        grant_id=member["reviewer_grant_id"],
        reason_code="synthetic_withdrawal",
        dry_run=False,
    )
    with pytest.raises(ResearchAccessDenied):
        await service.decide(db_session, **args)
    declined = await confirmed(db_session, decision_args(member, f["inputs"], decision="decline"))
    assert declined["decision"]["decision"] == "decline"


async def test_withdrawal_and_historical_recovery_survive_role_revocation(db_session):
    f = await fixture(db_session)
    first = await registered(db_session, f["args"])
    member = first["participants"][0]
    args = decision_args(member, f["inputs"])
    accepted = await confirmed(db_session, args)
    await revoke_role(
        db_session,
        actor_user_id=f["people"][0],
        grant_id=member["reviewer_grant_id"],
        reason_code="synthetic_withdrawal",
        dry_run=False,
    )
    withdrawal = await confirmed(
        db_session,
        decision_args(member, f["inputs"], decision="withdraw", prior=accepted["decision"]),
    )
    assert withdrawal["decision"]["decision"] == "withdraw"
    await read_snapshot(db_session)
    recovered = await service.outcome(
        db_session,
        actor_user_id=member["user_id"],
        kind="participation",
        request_key=args["request_key"],
        expected_intent_sha256=accepted["intent_sha256"],
    )
    assert recovered["decision"] == accepted["decision"] and recovered["replayed"]
    inspected = await service.inspect(
        db_session,
        actor_user_id=f["people"][0],
        registration_id=first["registration"]["id"],
        registration_sha256=first["registration"]["record_sha256"],
    )
    assert (
        not inspected["ready_for_prospective_review"]
        and not inspected["current_bound_roles_available"]
    )


@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
async def test_actual_sql_immutable_registry_and_identity_retention(db_session, operation):
    f = await fixture(db_session)
    first = await registered(db_session, f["args"])
    for member in first["participants"]:
        await confirmed(db_session, decision_args(member, f["inputs"]))
    for name in TABLES:
        query = {
            "update": f"UPDATE {name} SET created_at=created_at",
            "delete": f"DELETE FROM {name}",
            "truncate": f"TRUNCATE {name} CASCADE",
        }[operation]
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(sa.text(query))
    for uid in f["people"]:
        assert await has_research_audit_references(db_session, uid)
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(
                    Base.metadata.tables["users"]
                    .delete()
                    .where(Base.metadata.tables["users"].c.id == uid)
                )


async def test_outer_rollback_removes_all_registration_and_participation_rows(db_session):
    f = await fixture(db_session)
    before = await state(db_session)
    transaction = await db_session.begin_nested()
    first = await registered(db_session, f["args"])
    await confirmed(db_session, decision_args(first["participants"][0], f["inputs"]))
    await transaction.rollback()
    assert await state(db_session) == before
