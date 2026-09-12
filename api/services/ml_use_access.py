"""Explicit ML role membership and append-only administration, not ML rights.

Actor identity must originate at an authenticated trusted boundary. Role
membership grants neither data access, source permission, nor model execution.
"""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import sqlalchemy as sa

from models.ml_use_roles_v1 import ROLES, TABLE, VERSION
from services.ml_dataset_builder import AUTHORITY
from services.research_access import (
    ResearchAccessDenied,
    active_user,
    require_research_admin,
    table,
)
from services.research_release_manifest import digest

INTENT_VERSION = "ml-use-role-intent/1.0.0"
HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


class MlUseConflict(ValueError):
    """An intent, exact predecessor or idempotency key no longer matches."""


class MlUseOutcomeNotObserved(ValueError):
    """No matching durable outcome in this snapshot; not proof of rollback."""


def _require(condition):
    if not condition:
        raise ValueError("invalid_ml_use_role_request")


def _match(condition):
    if not condition:
        raise MlUseConflict("ml_use_role_intent_changed")


def _uuid(value):
    identifier = UUID(str(value))
    _require(str(identifier) == str(value))
    return identifier


def _hash(value):
    _require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None)
    return value


def _key(value):
    _require(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", value) is not None)
    return value


def _body(row):
    return {str(key): str(value) if isinstance(value, UUID) else value for key, value in row.items()
            if key not in {"created_at", "record_sha256"}}


def _verified(row):
    _require(row is not None and digest(_body(row)) == row["record_sha256"])
    return row


def _dto(row):
    return None if row is None else {**_body(_verified(row)), "record_sha256": row["record_sha256"],
                                   "created_at": row["created_at"].isoformat()}


def _boundary():
    return {"scope": "ml_workflow_membership_only", "training_execution": "disabled",
            "data_access_granted": False, "source_permission_granted": False,
            "run_authorization_granted": False, **AUTHORITY}


async def _read_session(db):
    isolation = (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one()
    readonly = (await db.execute(sa.text("SHOW transaction_read_only"))).scalar_one()
    _require(isolation in {"repeatable read", "serializable"} and readonly == "on")


async def _head(db, user_id, role):
    relation = table(TABLE)
    successor = relation.alias("successor")
    row = (await db.execute(sa.select(relation).where(relation.c.user_id == user_id, relation.c.role == role,
        ~sa.exists(sa.select(successor.c.id).where(successor.c.supersedes_id == relation.c.id)))))
    found = row.mappings().one_or_none()
    return None if found is None else _verified(found)


async def active_ml_role(db, user_id, *, role, grant_id=None):
    """For future trusted services: recheck the exact current membership only."""
    _require((await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one()
             in {"repeatable read", "serializable"})
    _require(role in ROLES)
    user_id = _uuid(user_id)
    await active_user(db, user_id)
    head = await _head(db, user_id, role)
    if head is None or head["action"] != "grant" or (grant_id is not None and head["id"] != _uuid(grant_id)):
        raise ResearchAccessDenied("An explicit active ML workflow role is required")
    return head


async def inspect_ml_access(db, *, actor_user_id, user_id=None):
    await _read_session(db)
    actor = await active_user(db, _uuid(actor_user_id))
    target = actor["id"] if user_id is None else _uuid(user_id)
    if target != actor["id"]:
        await require_research_admin(db, actor["id"])
    users = table("users")
    subject = (await db.execute(sa.select(users.c.id, users.c.is_active, users.c.email_verified)
                               .where(users.c.id == target))).mappings().one_or_none()
    if subject is None:
        raise MlUseOutcomeNotObserved("ml_use_subject_unavailable")
    heads = [await _head(db, target, role) for role in ROLES]
    active = bool(subject["is_active"] and subject["email_verified"])
    return {"version": VERSION, "actor_user_id": str(actor["id"]), "user_id": str(target),
            "can_administer_roles": bool(actor["is_admin"]), "subject_active_verified": active,
            "active_roles": [head["role"] for head in heads if active and head is not None and head["action"] == "grant"],
            "heads": [_dto(head) for head in heads if head is not None], **_boundary()}


def _intent(values, predecessor):
    return {"version": INTENT_VERSION,
            **{key: str(value) if isinstance(value, UUID) else value for key, value in values.items()
               if key != "version"},
            "expected_head_sha256": None if predecessor is None else predecessor["record_sha256"]}


def _result(intent, row, *, dry_run, replayed):
    return {"version": VERSION, "dry_run": dry_run, "committed": False, "replayed": replayed,
            "intent": intent, "intent_sha256": digest(intent),
            "decision": None if dry_run else _dto(row), **_boundary()}


@asynccontextmanager
async def _write(db, dry_run):
    _require(type(dry_run) is bool and not (db.new or db.dirty or db.deleted))
    _require((await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one() == "serializable")
    operation = {"changed": False}
    nested = await db.begin_nested()
    try:
        await db.execute(sa.text("SELECT public.sclib_research_publication_lock_v1()"))
        yield operation
        if dry_run or not operation["changed"]:
            await nested.rollback()
        else:
            await nested.commit()
    except BaseException:
        if nested.is_active:
            await nested.rollback()
        raise


async def decide_ml_role(db, *, actor_user_id, user_id, role, action, request_key, reason_code,
                         expected_head_id, expected_head_sha256, expected_intent_sha256=None, dry_run=True):
    actor_user_id, user_id = _uuid(actor_user_id), _uuid(user_id)
    _require(type(role) is str and role in ROLES and type(action) is str and action in {"grant", "revoke"})
    _require(type(reason_code) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,159}", reason_code) is not None)
    _require((expected_head_id is None) == (expected_head_sha256 is None))
    _require(type(dry_run) is bool and (dry_run or expected_intent_sha256 is not None))
    if expected_intent_sha256 is not None:
        _hash(expected_intent_sha256)
    predecessor_id = None if expected_head_id is None else _uuid(expected_head_id)
    if expected_head_sha256 is not None:
        _hash(expected_head_sha256)
    values = {"version": VERSION, "actor_user_id": actor_user_id, "user_id": user_id, "role": role,
              "action": action, "request_key": _key(request_key), "reason_code": reason_code,
              "supersedes_id": predecessor_id}
    relation = table(TABLE)
    async with _write(db, dry_run) as operation:
        await require_research_admin(db, actor_user_id)
        predecessor = None
        if predecessor_id is not None:
            predecessor = (await db.execute(sa.select(relation).where(relation.c.id == predecessor_id))).mappings().one_or_none()
            _match(predecessor is not None)
            _verified(predecessor)
            _match(predecessor["user_id"] == user_id and predecessor["role"] == role
                   and predecessor["record_sha256"] == expected_head_sha256)
        intent = _intent(values, predecessor)
        if expected_intent_sha256 is not None:
            _match(digest(intent) == expected_intent_sha256)
        existing = (await db.execute(sa.select(relation).where(relation.c.actor_user_id == actor_user_id,
                      relation.c.request_key == values["request_key"]))).mappings().one_or_none()
        if existing is not None:
            _verified(existing)
            _match(all(existing[key] == value for key, value in values.items()))
            return _result(intent, existing, dry_run=dry_run, replayed=True)
        head = await _head(db, user_id, role)
        _match((None if head is None else head["id"]) == predecessor_id)
        _match((head is None and action == "grant") or (head is not None and head["action"] != action))
        if action == "grant":
            await active_user(db, user_id)
        inserted = {**values, "id": uuid4()}
        inserted["record_sha256"] = digest(_body(inserted))
        row = (await db.execute(relation.insert().values(**inserted).returning(relation))).mappings().one()
        _verified(row)
        operation["changed"] = True
        return _result(intent, row, dry_run=dry_run, replayed=False)


async def ml_role_outcome(db, *, actor_user_id, request_key, expected_intent_sha256):
    """Read-only recovery of the actor's exact historical operation, not status."""
    await _read_session(db)
    actor_user_id = _uuid(actor_user_id)
    await require_research_admin(db, actor_user_id)
    relation = table(TABLE)
    row = (await db.execute(sa.select(relation).where(relation.c.actor_user_id == actor_user_id,
                           relation.c.request_key == _key(request_key)))).mappings().one_or_none()
    if row is None:
        raise MlUseOutcomeNotObserved("ml_use_role_outcome_not_observed")
    _verified(row)
    previous = None if row["supersedes_id"] is None else _verified((await db.execute(
        sa.select(relation).where(relation.c.id == row["supersedes_id"]))).mappings().one())
    values = {key: value for key, value in _body(row).items() if key != "id"}
    intent = _intent(values, previous)
    _match(digest(intent) == _hash(expected_intent_sha256))
    return _result(intent, row, dry_run=False, replayed=True)
