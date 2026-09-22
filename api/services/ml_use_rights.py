"""Independent per-resource rights records for one exact private ML request.

The reviewer records a documented decision, not a code-generated legal opinion.
Recovery is historical; only a fresh full input inspection plus current ledger
coverage may satisfy the source-permission gate. No function authorizes a run.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from models.ml_use_request import PURPOSE, identifier, sha
from models.ml_use_rights_v1 import (
    BASES,
    INTENT_FIELDS,
    INTENT_VERSION,
    TABLE,
    UUID_FIELDS,
    VERSION,
)
from services.ml_audited_dataset import digest, loads
from services.ml_dataset_builder import AUTHORITY
from services.ml_use_access import _key, _read_session, _write, active_ml_role
from services.ml_use_preflight import admission, match
from services.ml_use_reconstruction import require
from services.ml_use_submissions import verified as verified_submission
from services.research_access import (
    ResearchAccessDenied,
    active_grant,
    require_research_admin,
    table,
)


class RightsNotObserved(Exception):
    """No exact private record was observed; not proof of transaction rollback."""


def boundary():
    return {**AUTHORITY, "source_permission_granted": False, "run_authorization_granted": False,
            "data_access_granted": False, "training_execution": "disabled",
            "current_source_validity_checked": False, "legal_evidence_independently_verified": False}


async def reviewer_admission(db, actor_user_id, *, reviewer_grant_id=None, curator_grant_id=None):
    await require_research_admin(db, actor_user_id)
    curator = await active_grant(db, actor_user_id, role="curator", grant_id=curator_grant_id)
    reviewer = await active_ml_role(db, actor_user_id, role="rights_reviewer", grant_id=reviewer_grant_id)
    return {"actor_user_id": str(actor_user_id), "reviewer_grant_id": str(reviewer["id"]),
            "curator_grant_id": str(curator["id"])}


async def submission(db, submission_id, submission_sha256):
    relation = table("ml_use_submissions")
    row = (await db.execute(sa.select(relation).where(relation.c.id == UUID(identifier(submission_id))))).mappings().one_or_none()
    if row is None:
        raise RightsNotObserved("ml_rights_submission_unavailable")
    verified_submission(row)
    match(row["record_sha256"] == sha(submission_sha256))
    return row


def resources(parent):
    inventory = loads(parent["observation_json"].encode())["dependency_inventory"]
    require(digest(inventory) == parent["inventory_sha256"])
    result = {}
    for kind, entries in (("row", inventory["rows"]), ("artifact", inventory["artifact_digests"])):
        require(type(entries) is list and len(entries) <= 4000)
        for entry in entries:
            value = {"kind": kind, "entry": entry}
            pin = digest(value)
            require(pin not in result)
            result[pin] = value
    require(0 < len(result) <= 8000)
    return dict(sorted(result.items()))


def body(row):
    return {str(key): str(value) if isinstance(value, UUID) else value for key, value in row.items()
            if key not in {"created_at", "record_sha256", "reviewer_current"}}


def verified(row):
    values = body(row)
    require(digest(values) == row["record_sha256"])
    require(digest({"version": INTENT_VERSION, **{key: values[key] for key in INTENT_FIELDS}}) == row["intent_sha256"])
    return row


def dto(row):
    if row is None:
        return None
    return {**body(verified(row)), "record_sha256": row["record_sha256"], "created_at": row["created_at"].isoformat()}


async def heads(db, parent, *, resource_id=None):
    relation = table(TABLE)
    following = relation.alias("next_rights")
    role, successor = table("ml_use_role_decisions"), table("ml_use_role_decisions").alias("next_role")
    users, grants, revocations = table("users"), table("research_role_grants"), table("research_role_revocations")
    # Publication actor/role SQL helpers acquire FOR SHARE locks and belong on
    # writes only. This query must stay genuinely read-only in its fresh snapshot.
    grant_body = sa.func.to_jsonb(grants.table_valued()).op("-")(
        sa.cast(["id", "created_at", "record_sha256"], ARRAY(sa.Text)))
    grant_hash = sa.func.sclib_scientific_adjudication_text_hash_v1(
        sa.func.sclib_scientific_adjudication_canonical_v1(grant_body))
    current = sa.and_(sa.exists(sa.select(users.c.id).where(users.c.id == relation.c.actor_user_id,
            users.c.is_active.is_(True), users.c.email_verified.is_(True), users.c.is_admin.is_(True))),
        sa.exists(sa.select(grants.c.id).where(grants.c.id == relation.c.curator_grant_id,
            grants.c.user_id == relation.c.actor_user_id, grants.c.role == "curator", grants.c.record_sha256 == grant_hash,
            ~sa.exists(sa.select(revocations.c.id).where(revocations.c.grant_id == grants.c.id)))),
        sa.exists(sa.select(role.c.id).where(role.c.id == relation.c.reviewer_grant_id,
            role.c.user_id == relation.c.actor_user_id, role.c.role == "rights_reviewer", role.c.action == "grant",
            role.c.record_sha256 == sa.func.sclib_ml_use_role_hash_v1(sa.func.to_jsonb(role.table_valued())),
            ~sa.exists(sa.select(successor.c.id).where(successor.c.supersedes_id == role.c.id)))))
    found = (await db.execute(sa.select(relation, current.label("reviewer_current")).where(
        relation.c.submission_id == parent["id"],
        sa.true() if resource_id is None else relation.c.resource_id == resource_id,
        ~sa.exists(sa.select(following.c.id).where(following.c.supersedes_id == relation.c.id)))
        .order_by(relation.c.resource_id).limit(8001))).mappings().all()
    require(len(found) <= 8000)
    return {row["resource_id"]: verified(row) for row in found}


async def inspect(db, *, actor_user_id, submission_id, submission_sha256, inventory_sha256, after=None):
    await _read_session(db)
    actor = await reviewer_admission(db, actor_user_id)
    parent = await submission(db, submission_id, submission_sha256)
    if str(actor_user_id) == str(parent["actor_user_id"]):
        raise ResearchAccessDenied("independent_rights_reviewer_required")
    match(parent["inventory_sha256"] == sha(inventory_sha256))
    if after is not None:
        sha(after)
    inventory = resources(parent)
    current = await heads(db, parent)
    now = await db.scalar(sa.select(sa.func.extract("epoch", sa.func.clock_timestamp())))
    selected = [(key, value) for key, value in inventory.items() if after is None or key > after][:26]
    return {"version": VERSION, **actor, "submission_id": str(parent["id"]),
        "submission_sha256": parent["record_sha256"], "inventory_sha256": parent["inventory_sha256"],
        "purpose": PURPOSE, "input_access_expires_at": parent["expires_at"].isoformat(),
        "resource_count": len(inventory), "resources": [{"resource_id": key, **value,
            "head": dto(current.get(key)), "recorded_permission_status": status(current.get(key), now)}
            for key, value in selected[:25]], "next_after": selected[24][0] if len(selected) > 25 else None,
        "inventory_scope": "exact_registered_and_recaptured_inventory_not_external_completeness",
        **boundary()}


def status(head, now):
    if head is None:
        return "unreviewed"
    if head["decision"] != "allow":
        return "denied" if head["decision"] == "deny" else "revoked"
    if not head["reviewer_current"]:
        return "reviewer_unavailable"
    if head["expires_epoch"] <= now:
        return "expired"
    return "allow_recorded"


def result(row, *, dry_run, replayed):
    values = body(verified(row))
    return {"version": VERSION, "dry_run": dry_run, "committed": False, "replayed": replayed,
        "intent": {"version": INTENT_VERSION, **{key: values[key] for key in INTENT_FIELDS}},
        "intent_sha256": row["intent_sha256"], "decision": None if dry_run else dto(row),
        "scope": "historical_rights_decision_not_current_permission_or_run_authority", **boundary()}


async def decide(db, *, actor_user_id, submission_id, submission_sha256, inventory_sha256, resource_id,
                 reviewer_grant_id, curator_grant_id, request_key, decision, basis_code,
                 evidence_sha256, expires_epoch, supersedes_id, supersedes_sha256,
                 purpose=PURPOSE, expected_intent_sha256=None, dry_run=True):
    require(type(dry_run) is bool and (dry_run or expected_intent_sha256 is not None))
    require(purpose == PURPOSE and decision in {"allow", "deny", "revoke"} and basis_code in BASES)
    require((supersedes_id is None) == (supersedes_sha256 is None))
    if evidence_sha256 is not None:
        sha(evidence_sha256)
    if decision == "allow":
        require(basis_code in BASES[:3] and evidence_sha256 is not None
                and type(expires_epoch) is int and 0 < expires_epoch < 2**63)
    else:
        require(expires_epoch is None and basis_code in BASES[3:])
    actor = {"actor_user_id": identifier(str(actor_user_id)), "reviewer_grant_id": identifier(reviewer_grant_id),
             "curator_grant_id": identifier(curator_grant_id)}
    values = {**actor, "submission_id": identifier(submission_id), "submission_sha256": sha(submission_sha256),
        "inventory_sha256": sha(inventory_sha256), "resource_id": sha(resource_id), "purpose": purpose,
        "request_key": _key(request_key), "decision": decision, "basis_code": basis_code,
        "evidence_sha256": evidence_sha256, "expires_epoch": expires_epoch,
        "supersedes_id": None if supersedes_id is None else identifier(supersedes_id),
        "supersedes_sha256": None if supersedes_sha256 is None else sha(supersedes_sha256)}
    intent = {"version": INTENT_VERSION, **values}
    if expected_intent_sha256 is not None:
        match(digest(intent) == sha(expected_intent_sha256))
    relation = table(TABLE)
    async with _write(db, dry_run) as operation:
        await reviewer_admission(db, actor_user_id)  # recovery requires current access, not the historical grant
        existing = (await db.execute(sa.select(relation).where(relation.c.actor_user_id == UUID(str(actor_user_id)),
            relation.c.request_key == values["request_key"]))).mappings().one_or_none()
        if existing is not None:
            match(verified(existing)["intent_sha256"] == digest(intent))
            return result(existing, dry_run=dry_run, replayed=True)
        await reviewer_admission(db, **actor)
        parent = await submission(db, submission_id, submission_sha256)
        if str(parent["actor_user_id"]) == str(actor_user_id):
            raise ResearchAccessDenied("independent_rights_reviewer_required")
        match(parent["inventory_sha256"] == inventory_sha256 and resource_id in resources(parent))
        current = (await heads(db, parent, resource_id=resource_id)).get(resource_id)
        match((None if current is None else str(current["id"])) == supersedes_id
              and (None if current is None else current["record_sha256"]) == supersedes_sha256)
        require(decision != "revoke" or (current is not None and current["decision"] == "allow"))
        if decision == "allow":
            await admission(db, parent["actor_user_id"], requester_grant_id=parent["requester_grant_id"],
                            curator_grant_id=parent["curator_grant_id"])
            now = await db.scalar(sa.select(sa.func.extract("epoch", sa.func.clock_timestamp())))
            match(now < expires_epoch <= parent["expires_at"].timestamp())
            inputs = table("ml_use_private_inputs")
            match(bool(await db.scalar(sa.select(sa.exists(sa.select(inputs.c.submission_id).where(
                inputs.c.submission_id == parent["id"]))))))
        record = {"id": str(uuid4()), "version": VERSION, **values, "intent_sha256": digest(intent)}
        inserted = {key: UUID(value) if key in UUID_FIELDS and value is not None else value for key, value in record.items()}
        row = (await db.execute(relation.insert().values(**inserted, record_sha256=digest(record))
                                .returning(relation))).mappings().one()
        operation["changed"] = True
        return result(row, dry_run=dry_run, replayed=False)


async def outcome(db, *, actor_user_id, request_key, expected_intent_sha256):
    await _read_session(db)
    await reviewer_admission(db, actor_user_id)
    relation = table(TABLE)
    row = (await db.execute(sa.select(relation).where(relation.c.actor_user_id == UUID(str(actor_user_id)),
        relation.c.request_key == _key(request_key)))).mappings().one_or_none()
    if row is None:
        raise RightsNotObserved("ml_rights_outcome_not_observed")
    match(verified(row)["intent_sha256"] == sha(expected_intent_sha256))
    return result(row, dry_run=False, replayed=True)


async def coverage(db, *, actor_user_id, parent, current_inspection):
    """Same fresh RO snapshot as actual full-input inspection; never a cached lease."""
    await _read_session(db)
    await admission(db, actor_user_id, requester_grant_id=parent["requester_grant_id"],
                    curator_grant_id=parent["curator_grant_id"])
    require(str(parent["actor_user_id"]) == str(actor_user_id))
    match(current_inspection["dependency_inventory_sha256"] == parent["inventory_sha256"]
          and current_inspection["request_sha256"] == parent["request_sha256"]
          and current_inspection["reconstruction"]["envelope_sha256"] == parent["envelope_sha256"])
    require(current_inspection["companion_observations_rechecked_online"] is True
            and current_inspection["online_private_input_reconstruction_verified"] is True)
    inventory, current = resources(parent), await heads(db, parent)
    require(set(current) <= set(inventory))
    now = await db.scalar(sa.select(sa.func.extract("epoch", sa.func.clock_timestamp())))
    inputs = table("ml_use_private_inputs")
    match(parent["expires_at"].timestamp() > now and bool(await db.scalar(sa.select(sa.exists(
        sa.select(inputs.c.submission_id).where(inputs.c.submission_id == parent["id"]))))))
    records = [{"resource_id": key, "status": status(current.get(key), now),
                "decision_id": None if key not in current else str(current[key]["id"]),
                "record_sha256": None if key not in current else current[key]["record_sha256"]} for key in inventory]
    counts = {name: sum(row["status"] == name for row in records) for name in
              ("allow_recorded", "unreviewed", "denied", "revoked", "expired", "reviewer_unavailable")}
    source_valid = current_inspection["catalogue_and_scientific_gate"] == "no_hold_observed" and not any(
        item["frozen_row_changed"] for item in current_inspection["requirements"])
    complete = counts["allow_recorded"] == len(records)
    return {"version": VERSION, "submission_id": str(parent["id"]), "submission_sha256": parent["record_sha256"],
        "inventory_sha256": parent["inventory_sha256"], "purpose": PURPOSE, "resource_count": len(records),
        "status_counts": counts, "coverage_sha256": digest(records), "recorded_permissions_complete": complete,
        "first_blocked_resources": [row for row in records if row["status"] != "allow_recorded"][:25],
        "observed_epoch": str(now), "scope": "exact_current_inventory_private_baseline_only_no_authorization_lease",
        **boundary(), "source_permission_granted": complete and source_valid,
        "live_source_rights_checked": True, "current_source_validity_checked": True,
        "current_source_validity_passed": source_valid}
