"""Trusted ML08 commitment persistence and own-account decisions.

Document checks must come from the installed byte verifier, never request JSON.
The authenticated boundary supplies actor identity. No source content is stored.
"""

from __future__ import annotations

import re
from uuid import UUID, uuid4

import sqlalchemy as sa

from models.ml_pilot_registration_v1 import (
    DECISION_VERSION,
    INTENT_VERSION,
    JSON_FIELDS,
    TABLES,
    VERSION,
)
from services import ml_pilot_registration_documents as documents
from services.ml_pilot_documents import canonical, json_value
from services.ml_use_access import _hash, _key, _read_session, _uuid, _write
from services.ml_use_preflight import match
from services.research_access import (
    ResearchAccessDenied,
    active_grant,
    active_user,
    check_grant_inventory,
    require_research_admin,
    table,
)

require = documents.require


def digest(value):
    return documents.sha(canonical(value))


class PilotNotObserved(Exception):
    """No matching private record in this snapshot; no rollback assertion."""


def boundary():
    return {
        "scope": "private_pilot_document_commitment_and_account_participation_only",
        "scientific_acceptance": False,
        "scientific_pilot_accepted": False,
        "human_identity_verified": False,
        "scientific_reviewer_independence_verified": False,
        "source_permissions_verified": False,
        "actual_event_existence_verified": False,
        "external_review_chronology_verified": False,
        "public_release": False,
        "ml_training_approved": False,
        "run_authorization_granted": False,
        "training_execution": "disabled",
        "source_document_bytes_retained": False,
    }


def plain(values):
    return {key: str(value) if isinstance(value, UUID) else value for key, value in values.items()}


def body(row):
    return plain(
        {
            key: value
            for key, value in row.items()
            if key not in {*JSON_FIELDS, "record_sha256", "created_at"}
        }
    )


def verified(row):
    require(
        row is not None
        and json_value(row["record_json"].encode()) == body(row)
        and documents.sha(row["record_json"].encode()) == row["record_sha256"]
    )
    for name in ("intent", "roster", "implementation", "roles"):
        if name + "_json" in row:
            require(documents.sha(row[name + "_json"].encode()) == row[name + "_sha256"])
    return row


def dto(row):
    verified(row)
    result = {
        **body(row),
        "record_sha256": row["record_sha256"],
        "created_at": row["created_at"].isoformat(),
    }
    for key in ("roster", "implementation", "roles"):
        if key + "_json" in row:
            result[key] = json_value(row[key + "_json"].encode())
    return result


async def insert(db, name, values):
    relation = table(name)
    values = {"id": uuid4(), "version": VERSION, **values}
    if "roles_json" in values:
        values["roles_sha256"] = documents.sha(values["roles_json"].encode())
    values["record_json"] = canonical(body(values)).decode()
    values["record_sha256"] = documents.sha(values["record_json"].encode())
    return verified(
        (await db.execute(relation.insert().values(**values).returning(relation))).mappings().one()
    )


async def registrar_admission(db, actor_user_id, curator_grant_id=None):
    await require_research_admin(db, _uuid(actor_user_id))
    grant = await active_grant(db, actor_user_id, role="curator", grant_id=curator_grant_id)
    return {"actor_user_id": str(actor_user_id), "curator_grant_id": str(grant["id"])}


def checked_commitment(value):
    value = json_value(canonical(value))
    require(
        set(value)
        == {
            "version",
            "selection_file_sha256",
            "protocol_file_sha256",
            "selection_sha256",
            "participant_bindings",
            "selected_candidates",
        }
        and value["version"] == documents.VERSION
        and type(value["selected_candidates"]) is int
        and value["selected_candidates"] == 60
    )
    for key in ("selection_file_sha256", "protocol_file_sha256", "selection_sha256"):
        _hash(value[key])
    rows = value["participant_bindings"]
    require(type(rows) is list and 2 <= len(rows) <= 30)
    for row in rows:
        require(
            type(row) is dict
            and set(row) == {"alias_sha256", "user_id", "reviewer_grant_id", "roles"}
        )
        _hash(row["alias_sha256"])
        documents.identifier(row["user_id"])
        documents.identifier(row["reviewer_grant_id"])
        require(
            type(row["roles"]) is list
            and row["roles"]
            and row["roles"] == [r for r in documents.ROLES if r in row["roles"]]
        )
    require(
        len({row["user_id"] for row in rows})
        == len(rows)
        == len({row["alias_sha256"] for row in rows})
    )
    require(rows == sorted(rows, key=lambda r: r["alias_sha256"]))
    require(
        any(
            a["user_id"] != b["user_id"] and "primary" in a["roles"] and "secondary" in b["roles"]
            for a in rows
            for b in rows
        )
    )
    return value


async def _by_id(db, name, identifier, expected):
    relation = table(name)
    row = (
        (await db.execute(sa.select(relation).where(relation.c.id == _uuid(identifier))))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise PilotNotObserved("pilot_record_not_observed")
    verified(row)
    match(row["record_sha256"] == _hash(expected))
    return row


async def _members(db, reg):
    relation = table(TABLES[1])
    rows = (
        (
            await db.execute(
                sa.select(relation)
                .where(relation.c.registration_id == reg["id"])
                .order_by(relation.c.alias_sha256)
                .limit(31)
            )
        )
        .mappings()
        .all()
    )
    require(2 <= len(rows) <= 30)
    actual = [
        {
            "alias_sha256": verified(r)["alias_sha256"],
            "user_id": str(r["user_id"]),
            "reviewer_grant_id": str(r["reviewer_grant_id"]),
            "roles": json_value(r["roles_json"].encode()),
        }
        for r in rows
    ]
    require(
        actual == json_value(reg["roster_json"].encode())
        and all(r["registration_sha256"] == reg["record_sha256"] for r in rows)
    )
    return rows


async def _registration_result(db, reg, intent, *, dry_run, replayed):
    members = await _members(db, reg)
    return {
        "version": VERSION,
        "dry_run": dry_run,
        "committed": False,
        "replayed": replayed,
        "intent": intent,
        "intent_sha256": digest(intent),
        "registration_recorded": not dry_run,
        "registration": None if dry_run else dto(reg),
        "participants": [] if dry_run else [dto(row) for row in members],
        "participant_confirmations_checked": False,
        **boundary(),
    }


async def register(
    db,
    *,
    actor_user_id,
    curator_grant_id,
    request_key,
    commitment,
    implementation,
    expected_intent_sha256=None,
    dry_run=True,
):
    """Internal trusted verifier output only; HTTP never accepts commitment JSON."""
    actor, grant = _uuid(actor_user_id), _uuid(curator_grant_id)
    commitment = checked_commitment(commitment)
    implementation = json_value(canonical(implementation))
    match(implementation == documents.implementation())
    values = {
        "actor_user_id": actor,
        "curator_grant_id": grant,
        "request_key": _key(request_key),
        **{
            k: commitment[k]
            for k in ("selection_file_sha256", "protocol_file_sha256", "selection_sha256")
        },
        "roster_sha256": digest(commitment["participant_bindings"]),
        "implementation_sha256": digest(implementation),
    }
    intent = {"version": INTENT_VERSION, **plain(values)}
    require(type(dry_run) is bool and (dry_run or expected_intent_sha256 is not None))
    if expected_intent_sha256 is not None:
        match(digest(intent) == _hash(expected_intent_sha256))
    async with _write(db, dry_run) as operation:
        await require_research_admin(db, actor)
        relation = table(TABLES[0])
        existing = (
            (
                await db.execute(
                    sa.select(relation).where(
                        relation.c.actor_user_id == actor,
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
            return await _registration_result(db, existing, intent, dry_run=dry_run, replayed=True)
        await registrar_admission(db, actor, grant)
        await check_grant_inventory(
            db,
            [
                (r["user_id"], r["reviewer_grant_id"], "reviewer")
                for r in commitment["participant_bindings"]
            ],
        )
        match(
            not await db.scalar(
                sa.select(
                    sa.exists(
                        sa.select(relation.c.id).where(
                            relation.c.actor_user_id == actor,
                            relation.c.selection_sha256 == commitment["selection_sha256"],
                        )
                    )
                )
            )
        )
        reg = await insert(
            db,
            TABLES[0],
            {
                **values,
                "intent_json": canonical(intent).decode(),
                "intent_sha256": digest(intent),
                "roster_json": canonical(commitment["participant_bindings"]).decode(),
                "implementation_json": canonical(implementation).decode(),
            },
        )
        for row in commitment["participant_bindings"]:
            await insert(
                db,
                TABLES[1],
                {
                    "registration_id": reg["id"],
                    "registration_sha256": reg["record_sha256"],
                    "user_id": _uuid(row["user_id"]),
                    "reviewer_grant_id": _uuid(row["reviewer_grant_id"]),
                    "alias_sha256": row["alias_sha256"],
                    "roles_json": canonical(row["roles"]).decode(),
                },
            )
        # Check completeness inside the preview too, not only at outer commit.
        await db.execute(sa.text("SET CONSTRAINTS mp76_complete IMMEDIATE"))
        await db.execute(sa.text("SET CONSTRAINTS mp76_complete DEFERRED"))
        operation["changed"] = True
        return await _registration_result(db, reg, intent, dry_run=dry_run, replayed=False)


async def _head(db, member):
    relation = table(TABLES[2])
    later = relation.alias("successor")
    row = (
        (
            await db.execute(
                sa.select(relation).where(
                    relation.c.participant_id == member["id"],
                    ~sa.exists(sa.select(later.c.id).where(later.c.supersedes_id == relation.c.id)),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else verified(row)


async def own_participant(db, actor_user_id, participant_id, participant_sha256):
    await active_user(db, _uuid(actor_user_id))
    relation = table(TABLES[1])
    member = (
        (
            await db.execute(
                sa.select(relation).where(
                    relation.c.id == _uuid(participant_id),
                    relation.c.user_id == _uuid(actor_user_id),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if member is None:
        raise PilotNotObserved("pilot_record_not_observed")
    verified(member)
    match(member["record_sha256"] == _hash(participant_sha256))
    reg = await _by_id(db, TABLES[0], member["registration_id"], member["registration_sha256"])
    return member, reg


def _decision_result(row, intent, *, dry_run, replayed):
    return {
        "version": VERSION,
        "dry_run": dry_run,
        "committed": False,
        "replayed": replayed,
        "intent": intent,
        "intent_sha256": digest(intent),
        "decision": None if dry_run else dto(row),
        "account_participation_recorded": not dry_run,
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
    decision,
    reason_code,
    supersedes_id,
    supersedes_sha256,
    document_check=None,
    expected_intent_sha256=None,
    dry_run=True,
):
    actor = _uuid(actor_user_id)
    require(
        decision in {"accept", "decline", "withdraw"}
        and type(reason_code) is str
        and re.fullmatch(r"[a-z][a-z0-9_]{0,159}", reason_code) is not None
    )
    require((supersedes_id is None) == (supersedes_sha256 is None))
    values = {
        "actor_user_id": actor,
        "participant_id": _uuid(participant_id),
        "participant_sha256": _hash(participant_sha256),
        "registration_sha256": _hash(registration_sha256),
        "request_key": _key(request_key),
        "decision": decision,
        "reason_code": reason_code,
        "supersedes_id": None if supersedes_id is None else _uuid(supersedes_id),
        "supersedes_sha256": None if supersedes_sha256 is None else _hash(supersedes_sha256),
    }
    intent = {"version": DECISION_VERSION, **plain(values)}
    require(type(dry_run) is bool and (dry_run or expected_intent_sha256 is not None))
    if expected_intent_sha256 is not None:
        match(digest(intent) == _hash(expected_intent_sha256))
    async with _write(db, dry_run) as operation:
        member, reg = await own_participant(db, actor, participant_id, participant_sha256)
        match(reg["record_sha256"] == registration_sha256)
        relation = table(TABLES[2])
        existing = (
            (
                await db.execute(
                    sa.select(relation).where(
                        relation.c.actor_user_id == actor,
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
            return _decision_result(existing, intent, dry_run=dry_run, replayed=True)
        if decision == "accept":
            await registrar_admission(db, reg["actor_user_id"], reg["curator_grant_id"])
            await active_grant(db, actor, role="reviewer", grant_id=member["reviewer_grant_id"])
            require(
                type(document_check) is dict
                and document_check.get("version") == documents.VERSION
                and document_check.get("selected_candidates") == 60
            )
            for key in ("selection_file_sha256", "protocol_file_sha256", "selection_sha256"):
                match(document_check.get(key) == reg[key])
            match(
                {
                    "alias_sha256": member["alias_sha256"],
                    "roles": json_value(member["roles_json"].encode()),
                }
                in document_check.get("reviewer_roles", [])
            )
        else:
            require(document_check is None)
        prior = await _head(db, member)
        match(
            (None if prior is None else prior["id"]) == values["supersedes_id"]
            and (None if prior is None else prior["record_sha256"]) == values["supersedes_sha256"]
        )
        match(
            (prior is None and decision != "withdraw")
            or (
                prior is not None
                and prior["decision"] != decision
                and (decision != "withdraw" or prior["decision"] == "accept")
            )
        )
        row = await insert(
            db,
            TABLES[2],
            {**values, "intent_json": canonical(intent).decode(), "intent_sha256": digest(intent)},
        )
        operation["changed"] = True
        return _decision_result(row, intent, dry_run=dry_run, replayed=False)


async def inspect(db, *, actor_user_id, registration_id, registration_sha256):
    await _read_session(db)
    actor = _uuid(actor_user_id)
    await active_user(db, actor)
    relation, participants = table(TABLES[0]), table(TABLES[1])
    reg = (
        (
            await db.execute(
                sa.select(relation).where(
                    relation.c.id == _uuid(registration_id),
                    sa.or_(
                        relation.c.actor_user_id == actor,
                        sa.exists(
                            sa.select(participants.c.id).where(
                                participants.c.registration_id == relation.c.id,
                                participants.c.user_id == actor,
                            )
                        ),
                    ),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if reg is None:
        raise PilotNotObserved("pilot_record_not_observed")
    verified(reg)
    match(reg["record_sha256"] == _hash(registration_sha256))
    rows = await _members(db, reg)
    owner = reg["actor_user_id"] == actor
    if not owner and actor not in {r["user_id"] for r in rows}:
        raise PilotNotObserved("pilot_record_not_observed")
    if owner:
        await require_research_admin(db, actor)
    heads = [await _head(db, r) for r in rows]
    current = True
    try:
        await registrar_admission(db, reg["actor_user_id"], reg["curator_grant_id"])
        await check_grant_inventory(
            db, [(r["user_id"], r["reviewer_grant_id"], "reviewer") for r in rows]
        )
    except ResearchAccessDenied:
        current = False
    accepted = sum(h is not None and h["decision"] == "accept" for h in heads)
    visible = [(r, h) for r, h in zip(rows, heads, strict=True) if owner or r["user_id"] == actor]
    return {
        "version": VERSION,
        "registration_recorded": True,
        "registration": dto(reg)
        if owner
        else {
            k: str(reg[k]) if k != "created_at" else reg[k].isoformat()
            for k in (
                "id",
                "record_sha256",
                "created_at",
                "selection_file_sha256",
                "protocol_file_sha256",
                "selection_sha256",
            )
        },
        "participants": [
            {"binding": dto(r), "head": None if h is None else dto(h)} for r, h in visible
        ],
        "participant_count": len(rows),
        "accepted_account_count": accepted,
        "current_bound_roles_checked": True,
        "current_bound_roles_available": current,
        "ready_for_prospective_review": current and accepted == len(rows),
        "readiness_scope": "current_account_protocol_participation_not_scientific_acceptance",
        **boundary(),
    }


async def outcome(db, *, actor_user_id, request_key, expected_intent_sha256, kind):
    await _read_session(db)
    require(kind in {"registration", "participation"})
    actor = _uuid(actor_user_id)
    await (require_research_admin(db, actor) if kind == "registration" else active_user(db, actor))
    relation = table(TABLES[0] if kind == "registration" else TABLES[2])
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
        raise PilotNotObserved("pilot_outcome_not_observed")
    verified(row)
    match(row["intent_sha256"] == _hash(expected_intent_sha256))
    intent = json_value(row["intent_json"].encode())
    return (
        await _registration_result(db, row, intent, dry_run=False, replayed=True)
        if kind == "registration"
        else _decision_result(row, intent, dry_run=False, replayed=True)
    )
