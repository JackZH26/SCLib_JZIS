"""Exact private run plans and independent conditional reviews, never a lease.

Trusted callers supply authenticated actors. Readiness joins actual retained
input reconstruction and current rights in one fresh read-only snapshot. These
records neither schedule computation nor authorize model fitting.
"""
from __future__ import annotations

import hashlib
import re
from importlib.resources import files
from uuid import UUID, uuid4

import sqlalchemy as sa

from models.ml_use_request import PURPOSE, identifier, sha
from models.ml_use_runs_v1 import (
    DECISION_FIELDS,
    DECISION_INTENT,
    PLAN_FIELDS,
    PLAN_INTENT,
    PROFILE,
    TABLES,
    VERSION,
)
from services import ml_use_rights as rights
from services import ml_use_submissions as submissions
from services.ml_audited_dataset import canonical, digest, loads
from services.ml_baseline_rehearsal import _implementation
from services.ml_use_access import _key, _read_session, _write, active_ml_role
from services.ml_use_preflight import admission, match
from services.ml_use_reconstruction import require
from services.research_access import (
    ResearchAccessDenied,
    active_grant,
    require_research_admin,
    table,
)


class RunNotObserved(Exception):
    """No exact private record observed, not proof of rollback."""


def boundary():
    return {**rights.boundary(), "conditional_run_approval_current": False,
            "execution_environment_attested": False, "budget_reserved": False,
            "scientific_pilot_accepted": False, "execution_consumer_available": False}


async def approver_admission(db, actor_user_id, *, approver_grant_id=None, curator_grant_id=None):
    await require_research_admin(db, actor_user_id)
    curator = await active_grant(db, actor_user_id, role="curator", grant_id=curator_grant_id)
    role = await active_ml_role(db, actor_user_id, role="run_approver", grant_id=approver_grant_id)
    return {"actor_user_id": str(actor_user_id), "curator_grant_id": str(curator["id"]),
            "approver_grant_id": str(role["id"])}


def fingerprints():
    """Bounded fixed-path source/host observation, NOT a release-image attestation."""
    observed = _implementation()
    modules = dict(observed.pop("source_sha256"))
    observed.pop("verification")  # The rehearsal's replay policy is not a performed attestation.
    for name in ("models.ml_use_runs_v1", "services.ml_use_runs", "services.ml_use_reconstruction",
                 "services.ml_use_currentness", "services.ml_use_rights", "routers.ml_use_runs"):
        package, module = name.rsplit(".", 1)
        raw = files(package).joinpath(module + ".py").read_bytes()
        require(0 < len(raw) <= 1024 * 1024)
        modules[name] = hashlib.sha256(raw).hexdigest()
    implementation = {"version": "ml-run-source-observation/1.0.0", "selected_modules": modules,
        "scope": "on_disk_selected_sources_not_loaded_code_or_complete_release_attestation"}
    runtime = {"version": "ml-run-host-observation/1.0.0", "observed": observed,
        "scope": "host_properties_and_lockfile_not_installed_dependency_or_execution_image_attestation"}
    result = {}
    for key, value in (("implementation", implementation), ("runtime", runtime)):
        raw = canonical(value)
        require(len(raw) <= 16384)
        result[key + "_json"] = raw.decode()
        result[key + "_sha256"] = hashlib.sha256(raw).hexdigest()
    return result


def body(row):
    return {str(key): str(value) if isinstance(value, UUID) else value for key, value in row.items()
            if key not in {"created_at", "record_sha256"}}


def intent(row, kind):
    fields, version = (PLAN_FIELDS, PLAN_INTENT) if kind == "plan" else (DECISION_FIELDS, DECISION_INTENT)
    values = body(row)
    return {"version": version, **{key: values[key] for key in fields}}


def verified(row, kind):
    require(row["version"] == VERSION and digest(body(row)) == row["record_sha256"]
            and digest(intent(row, kind)) == row["intent_sha256"])
    if kind == "plan":
        require(row["purpose"] == PURPOSE and row["runner_profile"] == PROFILE)
        for key in ("implementation", "runtime"):
            raw = row[key + "_json"].encode()
            require(len(raw) <= 16384 and canonical(loads(raw)) == raw
                    and hashlib.sha256(raw).hexdigest() == row[key + "_sha256"])
    return row


def dto(row, kind):
    return {**body(verified(row, kind)), "record_sha256": row["record_sha256"],
            "created_at": row["created_at"].isoformat()}


def result(row, kind, *, dry_run, replayed):
    verified(row, kind)
    return {"version": VERSION, "dry_run": dry_run, "committed": False, "replayed": replayed,
        "intent": intent(row, kind), "intent_sha256": row["intent_sha256"],
        kind: None if dry_run else dto(row, kind),
        "scope": "historical_exact_run_contract_not_live_permission_or_execution_authority", **boundary()}


async def load_plan(db, plan_id, plan_sha256):
    relation = table(TABLES[0])
    row = (await db.execute(sa.select(relation).where(relation.c.id == UUID(identifier(plan_id))))).mappings().one_or_none()
    if row is None:
        raise RunNotObserved("ml_run_plan_not_observed")
    match(verified(row, "plan")["record_sha256"] == sha(plan_sha256))
    return row


async def owner(db, actor_user_id, parent, *, exact=True):
    if str(parent["actor_user_id"]) != str(actor_user_id):
        raise ResearchAccessDenied("ml_run_original_owner_required")
    return await admission(db, actor_user_id, **({"requester_grant_id": parent["requester_grant_id"],
        "curator_grant_id": parent["curator_grant_id"]} if exact else {}))


async def retained(db, parent):
    now = await db.scalar(sa.select(sa.func.extract("epoch", sa.func.clock_timestamp())))
    relation = table("ml_use_private_inputs")
    present = await db.scalar(sa.select(sa.exists(sa.select(relation.c.submission_id).where(
        relation.c.submission_id == parent["id"]))))
    match(bool(present) and now < parent["expires_at"].timestamp())
    return now


def parent_pins(parent):
    original = loads(parent["request_json"].encode())["input_pins"]
    return {"submission_id": str(parent["id"]), "submission_sha256": parent["record_sha256"],
        "inventory_sha256": parent["inventory_sha256"],
        "prepared_sha256": loads(parent["observation_json"].encode())["reconstruction"]["prepared_sha256"],
        **{key: original[key] for key in ("task_sha256", "config_sha256", "package_sha256")}}


async def context(db, *, actor_user_id, submission_id, submission_sha256, inventory_sha256):
    await _read_session(db)
    parent = await rights.submission(db, submission_id, submission_sha256)
    actor = await owner(db, actor_user_id, parent)
    match(parent["inventory_sha256"] == sha(inventory_sha256))
    await retained(db, parent)
    return {"version": VERSION, **actor, **parent_pins(parent), **fingerprints(),
        "runner_profile": PROFILE, "purpose": PURPOSE,
        "input_access_expires_at": parent["expires_at"].isoformat(),
        "budget_limits": {"cpu_seconds_min": 1, "cpu_seconds_max": 1800, "wall_seconds_min": 1,
            "wall_seconds_max": 1800, "memory_mib_min": 128, "memory_mib_max": 4096},
        "budget_scope": "requested_single_process_cpu_budget_not_reserved_or_enforced_by_this_endpoint", **boundary()}


async def existing(db, kind, actor_user_id, request_key):
    relation = table(TABLES[0 if kind == "plan" else 1])
    return (await db.execute(sa.select(relation).where(relation.c.actor_user_id == UUID(str(actor_user_id)),
        relation.c.request_key == request_key))).mappings().one_or_none()


async def insert(db, values, kind):
    record = {"id": str(uuid4()), "version": VERSION, **values, "intent_sha256": digest(intent(values, kind))}
    converted = {key: UUID(value) if (key == "id" or key.endswith("_id")) and value is not None else value
                 for key, value in record.items()}
    relation = table(TABLES[0 if kind == "plan" else 1])
    return (await db.execute(relation.insert().values(**converted, record_sha256=digest(record))
                            .returning(relation))).mappings().one()


async def propose(db, *, actor_user_id, dry_run=True, expected_intent_sha256=None, **values):
    require(set(values) == set(PLAN_FIELDS) - {"actor_user_id"})
    values = {"actor_user_id": identifier(str(actor_user_id)), **values}
    for key, value in values.items():
        if key.endswith("_id"):
            identifier(value)
        elif key.endswith("_sha256"):
            sha(value)
    _key(values["request_key"])
    require(all(type(values[key]) is int for key in ("cpu_seconds", "wall_seconds", "memory_mib")))
    require(1 <= values["cpu_seconds"] <= values["wall_seconds"] <= 1800 and 128 <= values["memory_mib"] <= 4096)
    require(type(dry_run) is bool and (dry_run or expected_intent_sha256 is not None))
    pin = digest(intent(values, "plan"))
    if expected_intent_sha256 is not None:
        match(pin == sha(expected_intent_sha256))
    async with _write(db, dry_run) as operation:
        await admission(db, actor_user_id)
        old = await existing(db, "plan", actor_user_id, values["request_key"])
        if old is not None:
            match(verified(old, "plan")["intent_sha256"] == pin)
            return result(old, "plan", dry_run=dry_run, replayed=True)
        parent = await rights.submission(db, values["submission_id"], values["submission_sha256"])
        actor = await owner(db, actor_user_id, parent)
        match(all(values[key] == value for key, value in {**actor, **parent_pins(parent)}.items()))
        await retained(db, parent)
        measured = fingerprints()
        match(all(values[key] == measured[key] for key in ("implementation_sha256", "runtime_sha256")))
        row = await insert(db, {**values, **measured, "runner_profile": PROFILE, "purpose": PURPOSE}, "plan")
        match(measured == fingerprints())
        operation["changed"] = True
        return result(row, "plan", dry_run=dry_run, replayed=False)


async def head(db, plan):
    relation = table(TABLES[1])
    successor = relation.alias("run_successor")
    row = (await db.execute(sa.select(relation).where(relation.c.plan_id == plan["id"],
        ~sa.exists(sa.select(successor.c.id).where(successor.c.supersedes_id == relation.c.id))))).mappings().one_or_none()
    return None if row is None else verified(row, "decision")


async def decision_status(db, record, now):
    if record is None:
        return "unreviewed"
    if record["decision"] != "approve":
        return "denied" if record["decision"] == "deny" else "revoked"
    try:
        await approver_admission(db, record["actor_user_id"], approver_grant_id=record["approver_grant_id"],
                                 curator_grant_id=record["curator_grant_id"])
    except ResearchAccessDenied:
        return "approver_unavailable"
    return "expired" if record["expires_epoch"] <= now else "conditional_approval_recorded"


async def inspect(db, *, actor_user_id, plan_id, plan_sha256):
    await _read_session(db)
    actor = await approver_admission(db, actor_user_id)
    plan = await load_plan(db, plan_id, plan_sha256)
    if str(plan["actor_user_id"]) == str(actor_user_id):
        raise ResearchAccessDenied("independent_run_approver_required")
    parent = await rights.submission(db, str(plan["submission_id"]), plan["submission_sha256"])
    current = await head(db, plan)
    now = await db.scalar(sa.select(sa.func.extract("epoch", sa.func.clock_timestamp())))
    return {"version": VERSION, **actor, "plan": dto(plan, "plan"),
        "head": None if current is None else dto(current, "decision"),
        "recorded_approval_status": await decision_status(db, current, now),
        "input_access_expires_at": parent["expires_at"].isoformat(),
        "scope": "conditional_plan_review_metadata_not_live_readiness", **boundary()}


async def decide(db, *, actor_user_id, dry_run=True, expected_intent_sha256=None, **values):
    require(set(values) == set(DECISION_FIELDS) - {"actor_user_id"})
    values = {"actor_user_id": identifier(str(actor_user_id)), **values}
    for key, value in values.items():
        if key.endswith("_id") and value is not None:
            identifier(value)
        elif key.endswith("_sha256") and value is not None:
            sha(value)
    _key(values["request_key"])
    require(type(values["reason_code"]) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,159}", values["reason_code"]) is not None)
    require(values["decision"] in {"approve", "deny", "revoke"}
            and (values["supersedes_id"] is None) == (values["supersedes_sha256"] is None))
    expiry = values["expires_epoch"]
    require((type(expiry) is int and 0 < expiry < 2**63 and values["evidence_sha256"] is not None)
            if values["decision"] == "approve" else expiry is None)
    require(type(dry_run) is bool and (dry_run or expected_intent_sha256 is not None))
    pin = digest(intent(values, "decision"))
    if expected_intent_sha256 is not None:
        match(pin == sha(expected_intent_sha256))
    async with _write(db, dry_run) as operation:
        await approver_admission(db, actor_user_id)
        old = await existing(db, "decision", actor_user_id, values["request_key"])
        if old is not None:
            match(verified(old, "decision")["intent_sha256"] == pin)
            return result(old, "decision", dry_run=dry_run, replayed=True)
        await approver_admission(db, actor_user_id, approver_grant_id=values["approver_grant_id"],
                                 curator_grant_id=values["curator_grant_id"])
        plan = await load_plan(db, values["plan_id"], values["plan_sha256"])
        if str(plan["actor_user_id"]) == str(actor_user_id):
            raise ResearchAccessDenied("independent_run_approver_required")
        current = await head(db, plan)
        match((None if current is None else str(current["id"])) == values["supersedes_id"]
              and (None if current is None else current["record_sha256"]) == values["supersedes_sha256"])
        require(values["decision"] != "revoke" or (current is not None and current["decision"] == "approve"))
        if values["decision"] == "approve":
            parent = await rights.submission(db, str(plan["submission_id"]), plan["submission_sha256"])
            await owner(db, plan["actor_user_id"], parent)
            now = await retained(db, parent)
            match(now < expiry <= parent["expires_at"].timestamp())
        row = await insert(db, values, "decision")
        operation["changed"] = True
        return result(row, "decision", dry_run=dry_run, replayed=False)


async def outcome(db, *, actor_user_id, request_key, expected_intent_sha256, kind):
    require(kind in {"plan", "decision"})
    await _read_session(db)
    await (admission(db, actor_user_id) if kind == "plan" else approver_admission(db, actor_user_id))
    row = await existing(db, kind, actor_user_id, _key(request_key))
    if row is None:
        raise RunNotObserved("ml_run_outcome_not_observed")
    match(verified(row, kind)["intent_sha256"] == sha(expected_intent_sha256))
    return result(row, kind, dry_run=False, replayed=True)


async def owned_plan(db, *, actor_user_id, plan_id, plan_sha256):
    plan = await load_plan(db, plan_id, plan_sha256)
    parent = await rights.submission(db, str(plan["submission_id"]), plan["submission_sha256"])
    await owner(db, actor_user_id, parent)
    match(all(str(plan[key]) == value for key, value in parent_pins(parent).items()))
    return plan, parent


async def retained_inputs(db, *, actor_user_id, plan_id, plan_sha256):
    await _read_session(db)
    _, parent = await owned_plan(db, actor_user_id=actor_user_id, plan_id=plan_id, plan_sha256=plan_sha256)
    return await submissions.retained_inputs(db, actor_user_id=actor_user_id,
        request_key=parent["request_key"], expected_intent_sha256=parent["intent_sha256"])


async def readiness(db, *, actor_user_id, plan_id, plan_sha256, current_inspection):
    """Internal same-snapshot companion to actual reconstruction, not uploadable evidence."""
    await _read_session(db)
    plan, parent = await owned_plan(db, actor_user_id=actor_user_id, plan_id=plan_id, plan_sha256=plan_sha256)
    match(current_inspection["reconstruction"]["prepared_sha256"] == plan["prepared_sha256"])
    coverage = await rights.coverage(db, actor_user_id=actor_user_id, parent=parent, current_inspection=current_inspection)
    current = await head(db, plan)
    now = await retained(db, parent)
    status = await decision_status(db, current, now)
    measured = fingerprints()
    matches = {key: measured[key + "_sha256"] == plan[key + "_sha256"] for key in ("implementation", "runtime")}
    blockers = ["independent_scientific_pilot_not_attested", "guarded_execution_consumer_unavailable",
                "execution_environment_not_attested"]
    if not coverage["source_permission_granted"]:
        blockers.append("current_source_permissions_or_validity_incomplete")
    if status != "conditional_approval_recorded":
        blockers.append("exact_plan_approval_" + status)
    blockers.extend(key + "_fingerprint_changed" for key, value in matches.items() if not value)
    return {"version": VERSION, "plan_id": str(plan["id"]), "plan_sha256": plan["record_sha256"],
        "approval": None if current is None else dto(current, "decision"), "approval_status": status,
        "source_coverage": coverage, "fingerprints_match": matches, "observed_epoch": str(now),
        "blockers": blockers, "decision": "not_authorized", "ready_for_execution": False,
        "scope": "current_snapshot_only_not_a_permission_lease", **boundary(),
        "conditional_run_approval_current": status == "conditional_approval_recorded",
        "source_permission_granted": coverage["source_permission_granted"],
        "live_source_rights_checked": True, "current_source_validity_checked": True}
