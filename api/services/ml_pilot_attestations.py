"""Trusted authenticated own-review declarations and exact historical recovery.

Original documents are reverified for each new declaration. An account assertion
is not verified human independence, a source licence or final pilot acceptance.
"""

from __future__ import annotations

import re
from uuid import uuid4

import sqlalchemy as sa

from models.ml_pilot_attestations_v1 import (
    BASIS_FIELDS,
    DECLARATION_VERSION,
    INTENT_VERSION,
    JSON_FIELDS,
    TABLE,
    VERSION,
)
from services import ml_pilot_attestation_contract as contract
from services import ml_pilot_registration as registration
from services import ml_pilot_review_admission as admission
from services.ml_pilot_documents import canonical, json_value
from services.ml_use_access import _hash, _key, _read_session, _uuid, _write
from services.ml_use_preflight import match
from services.research_access import active_user, table

require = registration.require
digest = registration.digest


def boundary():
    return {
        **registration.boundary(),
        "scope": "authenticated_own_review_declaration_not_collective_pilot_acceptance",
        "external_digital_signature_verified": False,
        "canary_replay_verified": False,
        "context_bytes_checked": False,
        "current_collective_signoff_verified": False,
    }


def body(row):
    return registration.plain(
        {k: v for k, v in row.items() if k not in {*JSON_FIELDS, "record_sha256", "created_at"}}
    )


def verified(row):
    require(
        row is not None
        and json_value(row["record_json"].encode()) == body(row)
        and digest(body(row)) == row["record_sha256"]
        and registration.documents.sha(row["intent_json"].encode()) == row["intent_sha256"]
        and registration.documents.sha(row["basis_json"].encode()) == row["basis_sha256"]
    )
    expected = {
        "version": INTENT_VERSION,
        **{k: v for k, v in body(row).items() if k not in {"id", "version", "intent_sha256"}},
    }
    require(json_value(row["intent_json"].encode()) == expected)
    basis = json_value(row["basis_json"].encode())
    require(set(basis) == set(BASIS_FIELDS))
    return row


def dto(row):
    if row is None:
        return None
    verified(row)
    return {
        **body(row),
        "record_sha256": row["record_sha256"],
        "created_at": row["created_at"].isoformat(),
        "basis": json_value(row["basis_json"].encode()),
    }


async def head(db, participant):
    relation = table(TABLE)
    child = relation.alias("child")
    row = (
        (
            await db.execute(
                sa.select(relation).where(
                    relation.c.participant_id == participant,
                    ~sa.exists(sa.select(child.c.id).where(child.c.supersedes_id == relation.c.id)),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else verified(row)


def result(intent, row, *, dry_run, replayed):
    return {
        "version": VERSION,
        "dry_run": dry_run,
        "committed": False,
        "replayed": replayed,
        "intent": intent,
        "intent_sha256": digest(intent),
        "declaration_recorded": not dry_run,
        "declaration": None if dry_run else dto(row),
        **boundary(),
    }


async def decide(
    db,
    *,
    actor_user_id,
    participant_id,
    participant_sha256,
    registration_sha256,
    request_key,
    action,
    reason_code,
    supersedes_id,
    supersedes_sha256,
    declaration_version,
    declaration_sha256,
    declaration_acknowledged,
    document_check=None,
    implementation=None,
    expected_intent_sha256=None,
    dry_run=True,
):
    require(
        action in {"attest", "withdraw"}
        and declaration_version == DECLARATION_VERSION
        and declaration_sha256 == contract.SHA256
        and declaration_acknowledged is True
        and type(dry_run) is bool
        and (dry_run or expected_intent_sha256 is not None)
        and type(reason_code) is str
        and re.fullmatch(r"[a-z][a-z0-9_]{0,159}", reason_code)
        and (supersedes_id is None) == (supersedes_sha256 is None)
    )
    if expected_intent_sha256 is not None:
        _hash(expected_intent_sha256)
    predecessor = None if supersedes_id is None else _uuid(supersedes_id)
    if supersedes_sha256 is not None:
        _hash(supersedes_sha256)
    relation = table(TABLE)
    async with _write(db, dry_run) as operation:
        member, reg = await registration.own_participant(
            db, actor_user_id, participant_id, participant_sha256
        )
        match(reg["record_sha256"] == _hash(registration_sha256))
        previous = None
        if predecessor is not None:
            previous = (
                (
                    await db.execute(
                        sa.select(relation).where(
                            relation.c.id == predecessor, relation.c.participant_id == member["id"]
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            match(previous is not None and verified(previous)["record_sha256"] == supersedes_sha256)
        if action == "attest":
            require(document_check is not None and implementation is not None)
            checked = await admission.bind(
                db,
                actor_user_id=actor_user_id,
                participant_id=participant_id,
                participant_sha256=participant_sha256,
                registration_sha256=registration_sha256,
                document_check=document_check,
                implementation=implementation,
            )
            require(
                checked["own_review_record_count"] > 0
                or checked["conclusion_author_is_current_account"]
            )
            basis = {key: checked[key] for key in BASIS_FIELDS}
            participation = await registration._head(db, member)
            match(participation is not None and participation["decision"] == "accept")
            participation_id, participation_sha256 = (
                participation["id"],
                participation["record_sha256"],
            )
        else:
            require(document_check is None and implementation is None)
            match(previous is not None and previous["action"] == "attest")
            basis = json_value(previous["basis_json"].encode())
            participation_id, participation_sha256 = (
                previous["participation_id"],
                previous["participation_sha256"],
            )
        values = {
            "version": VERSION,
            "declaration_version": DECLARATION_VERSION,
            "declaration_sha256": contract.SHA256,
            "actor_user_id": member["user_id"],
            "participant_id": member["id"],
            "participant_sha256": member["record_sha256"],
            "registration_sha256": reg["record_sha256"],
            "participation_id": participation_id,
            "participation_sha256": participation_sha256,
            "request_key": _key(request_key),
            "action": action,
            "reason_code": reason_code,
            "supersedes_id": predecessor,
            "supersedes_sha256": supersedes_sha256,
            "basis_sha256": digest(basis),
        }
        intent = {**registration.plain(values), "version": INTENT_VERSION}
        if expected_intent_sha256 is not None:
            match(digest(intent) == expected_intent_sha256)
        existing = (
            (
                await db.execute(
                    sa.select(relation).where(
                        relation.c.actor_user_id == member["user_id"],
                        relation.c.request_key == values["request_key"],
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            verified(existing)
            match(existing["intent_sha256"] == digest(intent))
            return result(intent, existing, dry_run=dry_run, replayed=True)
        current = await head(db, member["id"])
        match((None if current is None else current["id"]) == predecessor)
        match(
            not (
                action == "attest"
                and current is not None
                and current["action"] == "attest"
                and current["basis_sha256"] == values["basis_sha256"]
                and current["participation_id"] == participation_id
            )
        )
        values.update(
            id=uuid4(),
            basis_json=canonical(basis).decode(),
            intent_json=canonical(intent).decode(),
            intent_sha256=digest(intent),
        )
        values.update(
            record_json=canonical(body(values)).decode(), record_sha256=digest(body(values))
        )
        row = (
            (await db.execute(relation.insert().values(**values).returning(relation)))
            .mappings()
            .one()
        )
        verified(row)
        operation["changed"] = True
        return result(intent, row, dry_run=dry_run, replayed=False)


async def inspect(db, *, actor_user_id, participant_id, participant_sha256, registration_sha256):
    await _read_session(db)
    member, reg = await registration.own_participant(
        db, actor_user_id, participant_id, participant_sha256
    )
    match(reg["record_sha256"] == _hash(registration_sha256))
    latest = await head(db, member["id"])
    return {
        "version": VERSION,
        "actor_user_id": str(member["user_id"]),
        "participant_id": str(member["id"]),
        "participant_sha256": member["record_sha256"],
        "registration_sha256": reg["record_sha256"],
        "head": dto(latest),
        "historical_record_only": True,
        **boundary(),
    }


async def outcome(db, *, actor_user_id, request_key, expected_intent_sha256):
    await _read_session(db)
    actor = _uuid(actor_user_id)
    await active_user(db, actor)
    relation = table(TABLE)
    row = (
        (
            await db.execute(
                sa.select(relation).where(
                    relation.c.actor_user_id == actor, relation.c.request_key == _key(request_key)
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise registration.PilotNotObserved("pilot_attestation_not_observed")
    verified(row)
    match(row["intent_sha256"] == _hash(expected_intent_sha256))
    return result(json_value(row["intent_json"].encode()), row, dry_run=False, replayed=True)
