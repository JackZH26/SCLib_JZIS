"""Recoverable private ML requests. Historical inspection is never a run grant.

The HTTP boundary supplies authenticated identity and actual server inspection;
neither an uploaded report nor a claimed storage policy proves source rights.
"""
from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

import sqlalchemy as sa

from models.ml_use_request import sha, validate_request
from models.ml_use_submissions_v1 import RECORD_FIELDS, RETENTION_POLICY, TABLES, VERSION
from services.ml_audited_dataset import canonical, digest, loads
from services.ml_dataset_builder import AUTHORITY
from services.ml_use_access import _key, _read_session, _write
from services.ml_use_currentness import INVENTORY_VERSION
from services.ml_use_currentness import VERSION as CURRENT_VERSION
from services.ml_use_preflight import admission, match
from services.ml_use_reconstruction import MAX_ENVELOPE_BYTES, decode_envelope, require
from services.research_access import require_research_admin, table

INTENT_VERSION = "ml-use-submission-intent/1.0.0"


class SubmissionNotObserved(Exception):
    """No matching owned record in this snapshot; not proof of rollback."""


def intent(*, request_key, envelope_sha256, inventory_sha256, retention_policy):
    require(retention_policy == RETENTION_POLICY)
    return {"version": INTENT_VERSION, "request_key": _key(request_key),
            "envelope_sha256": sha(envelope_sha256), "inventory_sha256": sha(inventory_sha256),
            "retention_policy": retention_policy}


def validate_observation(raw, observation, expected_intent, actor_user_id):
    require(type(raw) is bytes)
    envelope, _, _ = decode_envelope(raw)
    observation = loads(canonical(observation))
    match(hashlib.sha256(raw).hexdigest() == expected_intent["envelope_sha256"])
    require(observation["version"] == CURRENT_VERSION and observation["decision"] == "not_authorized")
    require(all(observation[key] is False for key in (*AUTHORITY, "request_persisted", "database_mutated",
                "data_access_granted", "source_permission_granted", "run_authorization_granted")))
    require(observation["companion_observations_rechecked_online"] is True
            and observation["online_private_input_reconstruction_verified"] is True)
    require(observation["admission"] == {"actor_user_id": str(actor_user_id),
        "curator_grant_id": envelope["expected_curator_grant_id"],
        "requester_grant_id": envelope["expected_requester_grant_id"]})
    proof = observation["reconstruction"]
    require(proof["envelope_sha256"] == expected_intent["envelope_sha256"]
            and proof["request_sha256"] == envelope["expected_request_sha256"]
            and proof["input_pins"] == envelope["request"]["input_pins"]
            and proof["all_eight_input_bytes_verified"] is True and proof["dataset_and_preparation_rebuilt"] is True)
    inventory = observation["dependency_inventory"]
    require(inventory["version"] == INVENTORY_VERSION and inventory["input_pins"] == envelope["request"]["input_pins"])
    match(digest(inventory) == observation["dependency_inventory_sha256"] == expected_intent["inventory_sha256"])
    require(len(canonical(observation)) <= 1024 * 1024)
    return envelope, observation


def verified(row):
    body = loads(row["record_json"].encode())
    require(body == {key: str(row[key]) for key in RECORD_FIELDS} and digest(body) == row["record_sha256"])
    for key in ("intent", "request", "observation"):
        require(hashlib.sha256(row[key + "_json"].encode()).hexdigest() == row[key + "_sha256"])
    proposal = loads(row["intent_json"].encode())
    require(proposal == intent(**{key: row[key] for key in
        ("request_key", "envelope_sha256", "inventory_sha256", "retention_policy")}))
    request = validate_request(loads(row["request_json"].encode()))
    observation = loads(row["observation_json"].encode())
    require(digest(observation["dependency_inventory"]) == row["inventory_sha256"]
            and observation["dependency_inventory"]["input_pins"] == request["input_pins"])
    return row


async def _owned(db, actor_user_id, request_key, expected_intent_sha256):
    relation = table(TABLES[0])
    row = (await db.execute(sa.select(relation).where(relation.c.actor_user_id == UUID(str(actor_user_id)),
        relation.c.request_key == _key(request_key)))).mappings().one_or_none()
    if row is None:
        raise SubmissionNotObserved("ml_submission_outcome_not_observed")
    verified(row)
    match(row["intent_sha256"] == sha(expected_intent_sha256))
    return row


async def result(db, row, *, replayed):
    verified(row)
    purges, inputs = table(TABLES[2]), table(TABLES[1])
    purge = (await db.execute(sa.select(purges.c.reason, purges.c.created_at).where(
        purges.c.submission_id == row["id"]))).mappings().one_or_none()
    expired = row["expires_at"] <= await db.scalar(sa.select(sa.func.clock_timestamp()))
    retained = await db.scalar(sa.select(sa.exists(sa.select(inputs.c.submission_id).where(inputs.c.submission_id == row["id"]))))
    require(bool(retained) != (purge is not None))
    return {"version": VERSION, "submission_id": str(row["id"]), "request_persisted": True, "replayed": replayed,
        "record_sha256": row["record_sha256"], "intent": loads(row["intent_json"].encode()),
        "intent_sha256": row["intent_sha256"], "request": loads(row["request_json"].encode()),
        "created_at": row["created_at"].isoformat(), "input_access_expires_at": row["expires_at"].isoformat(),
        "input_state": "purged" if purge else "expired" if expired else "retained",
        "purge": None if purge is None else {"reason": purge["reason"], "created_at": purge["created_at"].isoformat()},
        "stored_observation": loads(row["observation_json"].encode()), "observation_sha256": row["observation_sha256"],
        "observation_scope": "historical_pre_submission_snapshot_not_commit_time_currentness",
        "currentness_checked_now": False, "training_execution": "disabled", "decision": "not_authorized",
        "source_permission_granted": False, "run_authorization_granted": False, "data_access_granted": False, **AUTHORITY}


async def outcome(db, *, actor_user_id, request_key, expected_intent_sha256):
    await _read_session(db)
    await admission(db, actor_user_id)
    return await result(db, await _owned(db, actor_user_id, request_key, expected_intent_sha256), replayed=True)


async def store_submission(db, *, actor_user_id, raw, observation, submission_intent, expected_intent_sha256):
    """Caller commits one SERIALIZABLE write; observation came from a prior RO snapshot.

Persisting that historical evidence is not a claim that sources remained current
at commit. Approval/consumption must inspect again under their own concurrency gate.
"""
    proposal = intent(**{key: submission_intent[key] for key in
        ("request_key", "envelope_sha256", "inventory_sha256", "retention_policy")})
    match(proposal == submission_intent and digest(proposal) == sha(expected_intent_sha256))
    envelope, observation = validate_observation(raw, observation, proposal, actor_user_id)
    async with _write(db, False) as operation:
        await admission(db, actor_user_id, requester_grant_id=envelope["expected_requester_grant_id"],
                        curator_grant_id=envelope["expected_curator_grant_id"])
        try:
            row = await _owned(db, actor_user_id, proposal["request_key"], expected_intent_sha256)
        except SubmissionNotObserved:
            row = None
        if row is not None:
            return await result(db, row, replayed=True)
        body = {"id": str(uuid4()), "version": VERSION, "actor_user_id": str(actor_user_id),
            "requester_grant_id": envelope["expected_requester_grant_id"],
            "curator_grant_id": envelope["expected_curator_grant_id"], "request_key": proposal["request_key"],
            "intent_sha256": digest(proposal), "request_sha256": envelope["expected_request_sha256"],
            "envelope_sha256": proposal["envelope_sha256"], "inventory_sha256": proposal["inventory_sha256"],
            "observation_sha256": digest(observation), "retention_policy": RETENTION_POLICY}
        values = {key: UUID(value) if key in {"id", "actor_user_id", "requester_grant_id", "curator_grant_id"}
                  else value for key, value in body.items()}
        values.update(record_json=canonical(body).decode(), record_sha256=digest(body),
                      intent_json=canonical(proposal).decode(), request_json=canonical(envelope["request"]).decode(),
                      observation_json=canonical(observation).decode())
        relation = table(TABLES[0])
        row = (await db.execute(relation.insert().values(**values).returning(relation))).mappings().one()
        await db.execute(table(TABLES[1]).insert().values(submission_id=row["id"], payload=raw))
        await db.execute(sa.text("SET CONSTRAINTS mu72_complete IMMEDIATE"))
        await db.execute(sa.text("SET CONSTRAINTS mu72_complete DEFERRED"))
        operation["changed"] = True
        return await result(db, row, replayed=False)


async def retained_inputs(db, *, actor_user_id, request_key, expected_intent_sha256):
    """Internal owner-only retrieval for another actual worker, never a download."""
    await _read_session(db)
    await admission(db, actor_user_id)
    row = await _owned(db, actor_user_id, request_key, expected_intent_sha256)
    if row["expires_at"] <= await db.scalar(sa.select(sa.func.clock_timestamp())):
        raise SubmissionNotObserved("ml_private_input_expired")
    relation = table(TABLES[1])
    size = await db.scalar(sa.select(sa.func.octet_length(relation.c.payload)).where(relation.c.submission_id == row["id"]))
    if size is None:
        raise SubmissionNotObserved("ml_private_input_purged")
    require(0 < size <= MAX_ENVELOPE_BYTES)
    raw = await db.scalar(sa.select(relation.c.payload).where(relation.c.submission_id == row["id"]))
    require(type(raw) is bytes and hashlib.sha256(raw).hexdigest() == row["envelope_sha256"])
    return raw


async def purge_inputs(db, *, actor_user_id, request_key, expected_intent_sha256):
    async with _write(db, False) as operation:
        await admission(db, actor_user_id)
        row = await _owned(db, actor_user_id, request_key, expected_intent_sha256)
        relation = table(TABLES[2])
        if not await db.scalar(sa.select(sa.exists(sa.select(relation.c.submission_id).where(relation.c.submission_id == row["id"])))):
            await db.execute(relation.insert().values(submission_id=row["id"], actor_user_id=UUID(str(actor_user_id)), reason="owner_request"))
            operation["changed"] = True
        return await result(db, row, replayed=not operation["changed"])


async def purge_expired(db, *, actor_user_id):
    """Bounded administrator maintenance; no source bytes or other owners' IDs."""
    async with _write(db, False) as operation:
        await require_research_admin(db, actor_user_id)
        requests, inputs, purges = (table(name) for name in TABLES)
        ids = (await db.execute(sa.select(requests.c.id).join(inputs, inputs.c.submission_id == requests.c.id)
            .where(requests.c.expires_at <= sa.func.clock_timestamp()).order_by(requests.c.expires_at, requests.c.id).limit(20))).scalars().all()
        for identifier in ids:
            await db.execute(purges.insert().values(submission_id=identifier, actor_user_id=UUID(str(actor_user_id)), reason="retention_expired"))
        operation["changed"] = bool(ids)
        return {"version": VERSION, "purged_count": len(ids), "batch_limit": 20, "more_may_remain": len(ids) == 20,
                "source_permission_granted": False, "run_authorization_granted": False, **AUTHORITY}
