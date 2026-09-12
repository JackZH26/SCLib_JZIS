"""Read-only, source-derived ML intake requirements; never grants permission.

Online verification covers the stored capsule and registered dependency graph,
not the unavailable private bytes of the seven other declared input pins.
"""
from __future__ import annotations

from collections import defaultdict
from uuid import UUID

import sqlalchemy as sa

from models.ml_use_request import MAX_BINDINGS, identifier, sha, validate_request
from services.ml_dataset_builder import AUTHORITY
from services.ml_feature_companion import _plain, _release, binding_sha256
from services.ml_use_access import active_ml_role
from services.research_access import active_grant, require_research_admin, table
from services.research_freeze import _fetch
from services.research_publication import PublicationUnavailable, _current_catalogue
from services.research_release_manifest import canonical, dependencies, digest, owned_relations
from services.research_release_spec import SPEC

VERSION = "ml-use-preflight/1.0.0"
MAX_ROWS = 1000
MAX_RESPONSE_BYTES = 512 * 1024
SCOPE = "registered_capsule_and_feature_binding_dependencies_only"


class MlUsePreflightConflict(ValueError):
    """An independently pinned request or registration no longer matches."""


def match(condition):
    if not condition:
        raise MlUsePreflightConflict("ml_use_exact_registration_changed")


async def admission(db, actor_user_id, *, requester_grant_id=None, curator_grant_id=None):
    # Preserve the strong private ML audit-export policy until dataset ACLs
    # exist. ML membership alone must not expose someone else's input inventory.
    await require_research_admin(db, actor_user_id)
    curator = await active_grant(db, actor_user_id, role="curator", grant_id=curator_grant_id)
    requester = await active_ml_role(db, actor_user_id, role="requester", grant_id=requester_grant_id)
    return {"actor_user_id": str(actor_user_id), "curator_grant_id": str(curator["id"]),
            "requester_grant_id": str(requester["id"])}


async def _bindings(db, request):
    relation = table("ml_feature_source_bindings")
    condition = relation.c.base_release_id == UUID(request["base_release_id"])
    sizes = (await db.execute(sa.select(sa.func.octet_length(sa.cast(
        sa.func.to_jsonb(relation.table_valued()), sa.Text))).where(condition).limit(MAX_BINDINGS + 1))).scalars().all()
    match(len(sizes) <= MAX_BINDINGS and sum(sizes) <= 2 * 1024 * 1024)
    values = (await db.execute(sa.select(relation).where(condition).order_by(relation.c.id)
                              .limit(MAX_BINDINGS + 1))).mappings().all()
    match(len(values) == len(sizes))
    rows = [_plain(row) for row in values]
    match(all(row["record_sha256"] == binding_sha256(row)
        and row["base_manifest_sha256"] == request["input_pins"]["manifest_sha256"] for row in rows))
    match([{"id": row["id"], "record_sha256": row["record_sha256"]} for row in rows]
          == request["feature_binding_pins"])
    return rows


async def _closure(db, frozen, bindings):
    # Every frozen row is a conservative root, including policy/review/source
    # evidence and unused rows. This is not a selected-feature-only licence list.
    pending = {(row["table"], row["row_id"]) for row in frozen}
    for row in bindings:
        pending.update({("source_revisions", row["source_revision_id"]), ("source_captures", row["capture_id"]),
                        ("works", row["work_id"]), ("evidence_artifacts", row["review_artifact_id"])})
    found, expanded, budget = {}, set(), {}
    while pending:
        match(len(found.keys() | pending) <= MAX_ROWS)
        groups = defaultdict(set)
        for name, row_id in pending - found.keys():
            match(name in SPEC)
            groups[name].add(row_id)
        for name, ids in sorted(groups.items()):
            rows = await _fetch(db, name, identifiers=ids, byte_budget=budget)
            match({row["row_id"] for row in rows} == ids)
            found.update({(row["table"], row["row_id"]): row for row in rows})
        current = pending - expanded
        owners = defaultdict(set)
        for name, row_id in current:
            owners[name].add(row_id)
        children = []
        for owner, ids in sorted(owners.items()):
            relations = set(owned_relations(owner))
            if owner == "material_claims":
                relations.add(("claim_source_occurrences", "claim_id"))
            if owner == "source_revisions":
                relations.add(("source_captures", "source_revision_id"))
            for child, column in sorted(relations):
                children.extend(await _fetch(db, child, identifiers=ids, column=column, byte_budget=budget))
        for row in children:
            key = row["table"], row["row_id"]
            match(key not in found or found[key] == row)
            found[key] = row
        match(len(found) <= MAX_ROWS)
        next_keys = {(row["table"], row["row_id"]) for row in children}
        for key in current:
            next_keys.update(dependencies(key[0], found[key]["data"]))
        expanded.update(current)
        pending = next_keys - expanded
    return [found[key] for key in sorted(found)]


async def preflight_ml_use(db, *, actor_user_id, request, expected_request_sha256,
                          expected_requester_grant_id, expected_curator_grant_id):
    request = validate_request(request)  # private immutable capture before awaits
    match(digest(request) == sha(expected_request_sha256))
    requester_id, curator_id = identifier(expected_requester_grant_id), identifier(expected_curator_grant_id)
    if db.new or db.dirty or db.deleted:
        raise ValueError("ml_use_clean_snapshot_required")
    isolation = await db.scalar(sa.text("SHOW transaction_isolation"))
    readonly = await db.scalar(sa.text("SHOW transaction_read_only"))
    timeout = await db.scalar(sa.text("SELECT setting::bigint FROM pg_settings WHERE name='statement_timeout'"))
    if isolation not in {"serializable", "repeatable read"} or readonly != "on" or not 0 < timeout <= 5000:
        raise ValueError("ml_use_bounded_readonly_snapshot_required")
    actor = await admission(db, actor_user_id, requester_grant_id=requester_id, curator_grant_id=curator_id)
    release = await _release(db, base_id=request["base_release_id"])
    match(release["manifest_sha256"] == request["input_pins"]["manifest_sha256"]
          and release["dataset_snapshot_id"] == UUID(request["dataset_id"])
          and release["manifest"]["dataset_id"] == request["dataset_id"])
    bindings = await _bindings(db, request)
    frozen = release["manifest"]["rows"]
    rows = await _closure(db, frozen, bindings)
    historic = {(row["table"], row["row_id"]): row for row in frozen}
    # This is a conservative negative gate, not an independent scientific review.
    catalogue_held = False
    try:
        await _current_catalogue(db, {"manifest": {"rows": rows}})
    except PublicationUnavailable:
        catalogue_held = True
    requirements = []
    for row in rows:
        previous = historic.get((row["table"], row["row_id"]))
        requirements.append({"table": row["table"], "row_id": row["row_id"], "row_sha256": row["row_sha256"],
            "frozen_row_sha256": None if previous is None else previous["row_sha256"],
            "frozen_row_changed": previous is not None and previous["row_sha256"] != row["row_sha256"],
            "purpose_permission_status": "not_available", "permission_granted": False})
    blockers = ["purpose_specific_permission_registry_unavailable", "private_input_bytes_not_rebuilt_online",
                "independent_run_approval_unavailable", "real_reviewed_pilot_not_checked"]
    if catalogue_held:
        blockers.append("current_catalogue_or_scientific_hold")
    if any(row["frozen_row_changed"] for row in requirements):
        blockers.append("frozen_dependency_changed")
    result = {"version": VERSION, "request_sha256": expected_request_sha256, "purpose": request["purpose"],
        "input_pins": request["input_pins"], "dataset_id": request["dataset_id"],
        "base_release_id": request["base_release_id"], "admission": actor,
        "observed_at": (await db.scalar(sa.text("SELECT transaction_timestamp()"))).isoformat(),
        "dependency_scope": SCOPE, "registered_dependency_inventory_checked": True,
        "catalogue_and_scientific_gate": "held_or_unavailable" if catalogue_held else "no_hold_observed",
        "online_private_input_reconstruction_verified": False,
        "requirements": requirements, "requirements_sha256": digest(requirements),
        "feature_binding_pins": request["feature_binding_pins"],
        "dependency_count": len(requirements), "feature_binding_count": len(bindings),
        "decision": "not_authorized", "blockers": sorted(blockers),
        "request_persisted": False, "database_mutated": False, "source_permission_granted": False,
        "data_access_granted": False,
        "run_authorization_granted": False, "training_execution": "disabled", **AUTHORITY}
    if len(canonical(result)) > MAX_RESPONSE_BYTES:
        raise ValueError("ml_use_report_limit")
    return result
