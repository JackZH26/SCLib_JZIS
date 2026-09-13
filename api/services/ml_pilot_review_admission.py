"""Read-only binding of a complete documentary review log to real account rows.

Authenticated account/SQL observations do not authenticate the declared external
review chronology, evidence support, source rights, or any scientific signature.
"""

from __future__ import annotations

import sqlalchemy as sa

from services import ml_pilot_accounting as accounting
from services import ml_pilot_registration as registration
from services import ml_pilot_registration_documents as registration_documents
from services import ml_pilot_review_documents as documents
from services.ml_pilot_documents import canonical, json_value
from services.ml_use_access import _hash, _read_session
from services.ml_use_preflight import match
from services.research_access import check_grant_inventory, table

VERSION = "ml08-review-admission/1.0.0"
MAX_PARTICIPATION_HISTORY = 4096
require = documents.require


def accepted_at(history, instant):
    """Use recorded transitions, not today's head or the browser clock."""
    applicable = [row for row in history if row["created_at"] <= instant]
    return bool(applicable) and applicable[-1]["decision"] == "accept"


async def inspect(
    db,
    *,
    actor_user_id,
    participant_id,
    participant_sha256,
    registration_sha256,
    document_check,
    implementation,
):
    await _read_session(db)
    return await bind(
        db,
        actor_user_id=actor_user_id,
        participant_id=participant_id,
        participant_sha256=participant_sha256,
        registration_sha256=registration_sha256,
        document_check=document_check,
        implementation=implementation,
    )


async def bind(
    db,
    *,
    actor_user_id,
    participant_id,
    participant_sha256,
    registration_sha256,
    document_check,
    implementation,
):
    """Trusted read/write binding; callers must not supply a cached HTTP result."""
    require(
        (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one()
        in {"repeatable read", "serializable"}
    )
    own, reg = await registration.own_participant(
        db, actor_user_id, participant_id, participant_sha256
    )
    match(reg["record_sha256"] == _hash(registration_sha256))
    await registration.registrar_admission(db, reg["actor_user_id"], reg["curator_grant_id"])
    members = await registration._members(db, reg)
    await check_grant_inventory(
        db, [(m["user_id"], m["reviewer_grant_id"], "reviewer") for m in members]
    )
    match(
        json_value(reg["implementation_json"].encode())["version"] == registration_documents.VERSION
    )
    value = documents.checked(document_check)
    match(implementation == documents.implementation())
    for name in ("selection_file_sha256", "protocol_file_sha256"):
        match(value["input_pins"][name] == reg[name])
    match(value["selection_sha256"] == reg["selection_sha256"])
    registration_documents.check_chronology(
        value["selection_chronology"], observed_at=reg["created_at"]
    )
    now = await db.scalar(sa.select(sa.func.clock_timestamp()))
    conclusion_at = accounting._date(value["conclusion_completed_at"])
    match(reg["created_at"] <= conclusion_at <= now)
    contributions = {r["alias_sha256"]: r for r in value["reviewer_contributions"]}
    match(set(contributions) == {m["alias_sha256"] for m in members})
    decisions = table(registration.TABLES[2])
    all_records = (
        (
            await db.execute(
                sa.select(decisions)
                .where(decisions.c.participant_id.in_([m["id"] for m in members]))
                .order_by(decisions.c.created_at, decisions.c.id)
                .limit(MAX_PARTICIPATION_HISTORY + 1)
            )
        )
        .mappings()
        .all()
    )
    require(len(all_records) <= MAX_PARTICIPATION_HISTORY)
    histories = {m["id"]: [] for m in members}
    for row in all_records:
        registration.verified(row)
        histories[row["participant_id"]].append(row)
    for member in members:
        contribution = contributions[member["alias_sha256"]]
        match(contribution["roles"] == json_value(member["roles_json"].encode()))
        history = histories[member["id"]]
        previous = None
        for row in history:
            match(
                row["actor_user_id"] == member["user_id"]
                and row["participant_sha256"] == member["record_sha256"]
                and row["registration_sha256"] == reg["record_sha256"]
                and row["supersedes_id"] == (None if previous is None else previous["id"])
                and row["supersedes_sha256"]
                == (None if previous is None else previous["record_sha256"])
            )
            previous = row
        match(bool(history) and history[-1]["decision"] == "accept")
        for declared in contribution["declared_completion_instants"]:
            instant = accounting._date(declared)
            match(reg["created_at"] <= instant <= now and accepted_at(history, instant))
        if member["alias_sha256"] == value["conclusion_author_alias_sha256"]:
            match(accepted_at(history, conclusion_at))
    contribution = contributions[own["alias_sha256"]]
    # Only the caller's attribution is returned; do not disclose other roster
    # accounts, individual review dates, reviewer aliases or source-bearing text.
    result = {
        "version": VERSION,
        "scope": "private_preregistration_and_review_document_binding_only",
        "actor_user_id": str(own["user_id"]),
        "participant_id": str(own["id"]),
        "participant_sha256": own["record_sha256"],
        "registration_id": str(reg["id"]),
        "registration_sha256": reg["record_sha256"],
        "input_pins": value["input_pins"],
        "selection_sha256": value["selection_sha256"],
        "review_log_sha256": value["review_log_sha256"],
        "document_projection_sha256": documents.sha(canonical(value)),
        "implementation_sha256": documents.sha(canonical(implementation)),
        "selected_candidates": 60,
        "review_record_count": value["review_record_count"],
        "own_review_record_count": contribution["review_record_count"],
        "own_review_records_sha256": contribution["review_records_sha256"],
        "conclusion_author_is_current_account": own["alias_sha256"]
        == value["conclusion_author_alias_sha256"],
        "recorded_recommendation": value["recommendation"],
        "declared_canary_sha256": value["declared_canary_sha256"],
        "current_accounts_and_roles_checked": True,
        "declared_review_times_fit_recorded_participation": True,
        "documentary_binding_checked": True,
        "attestation_recorded": False,
        "context_bytes_checked": False,
        "canary_replay_verified": False,
        "conclusion_endorsed": False,
        **{k: v for k, v in registration.boundary().items() if k != "scope"},
    }
    return result
