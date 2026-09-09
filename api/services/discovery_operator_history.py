"""Bounded recorded governance, not source admission or scientific approval.

Only scalar ledger columns are read. Historical grants need not remain active;
the requesting operator must. No payload, source/rights body or another actor's
request key is returned, and no positive publication eligibility is inferred.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from services import discovery_projection_governance as governance
from services.research_access import (
    active_user,
    check_grant_inventory,
    require_research_operator,
    table,
)

VERSION = "discovery-operator-history/1.0.0"
MAX_REVIEWS = 1000
PAGE_SIZE = 25
AUTHORITY = {**governance.AUTHORITY, "public_release_authorized": False}
PACKAGE_FIELDS = ("id", "record_sha256", "created_at", "actor_user_id", "actor_grant_id",
    "distribution_package_id", "distribution_record_sha256", "inventory_sha256", "payload_sha256", "selection_sha256")
REVIEW_FIELDS = ("id", "record_sha256", "created_at", "actor_user_id", "actor_grant_id", "package_id",
    "payload_sha256", "selection_sha256", "decision", "representative_selection_approved", "disclosure_approved",
    "rights_sha256", "reason_code")
ACTION_FIELDS = ("id", "record_sha256", "created_at", "actor_user_id", "actor_grant_id", "package_id",
    "payload_sha256", "selection_sha256", "review_id", "kind", "reason_code")


def _wire(row, fields):
    def scalar(value):
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            governance.require(value.tzinfo is not None)
            return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        return value
    return {key: scalar(row[key]) for key in fields}


async def operator_access(db, *, actor_user_id):
    await governance._session(db)
    actor = governance.distribution._uuid(actor_user_id)
    await active_user(db, actor)
    grants, revoked = table("research_role_grants"), table("research_role_revocations")
    rows = (await db.execute(sa.select(grants.c.id, grants.c.role).where(grants.c.user_id == actor,
        ~sa.exists(sa.select(revoked.c.id).where(revoked.c.grant_id == grants.c.id)))
        .order_by(grants.c.role, grants.c.id).limit(4))).mappings().all()
    governance.require(0 < len(rows) <= 3 and len({row["role"] for row in rows}) == len(rows)
        and all(row["role"] in {"curator", "reviewer", "publisher"} for row in rows))
    await check_grant_inventory(db, [(actor, row["id"], row["role"]) for row in rows])
    return {"version": VERSION, "scope": governance.SCOPE, "actor_user_id": str(actor),
        "grants": [{"role": row["role"], "id": str(row["id"])} for row in rows],
        "admission_scope": "current_read_snapshot_role_only", **AUTHORITY}


async def _headers(db, name, condition, *, maximum, order):
    """Hash the same scalar header as the native function, without TOAST bodies.

    Even header=True on the general ledger helper sizes to_jsonb(full row).
    Instead use a column-only subquery; the native hash intentionally excludes
    these same JSON document columns. This verifies header pins, NOT body bytes.
    """
    relation = table(name)
    columns = [c for c in relation.c if c.name not in governance._JSON_FIELDS]
    selected = sa.select(*columns).where(condition).order_by(*[relation.c[k] for k in order]).limit(maximum + 1).subquery()
    # Do not transfer request keys/hashes to the service layer. They participate
    # in the native scalar record hash only, inside PostgreSQL.
    visible = [c for c in selected.c if c.name not in {"request_key", "request_sha256"}]
    rows = (await db.execute(sa.select(*visible, governance._HASH(sa.func.to_jsonb(selected.table_valued()))
        .label("actual_sha256")).order_by(*[selected.c[k] for k in order]))).mappings().all()
    governance.require(len(rows) <= maximum, "discovery_history_inventory_limit")
    governance.require(all(row["actual_sha256"] == row["record_sha256"] and row["scope"] == governance.SCOPE for row in rows),
        "discovery_history_header_invalid")
    return rows


async def _inventory(db, *, actor_user_id, package_id):
    await governance._session(db)
    await require_research_operator(db, actor_user_id)
    identifier = governance.distribution._uuid(package_id)
    packages, reviews, actions = [table(name) for name in governance.TABLE_ORDER]
    rows = await _headers(db, packages.name, packages.c.id == identifier, maximum=1, order=("id",))
    if not rows:
        raise governance.DiscoveryGovernanceNotFound("discovery_history_not_found")
    package = _wire(rows[0], PACKAGE_FIELDS)
    review_rows = await _headers(db, reviews.name, reviews.c.package_id == identifier,
        maximum=MAX_REVIEWS, order=("created_at", "id"))
    action_rows = await _headers(db, actions.name, actions.c.package_id == identifier, maximum=2, order=("kind", "id"))
    recorded_reviews = [_wire(row, REVIEW_FIELDS) for row in review_rows]
    recorded_actions = [_wire(row, ACTION_FIELDS) for row in action_rows]
    by_id = {row["id"]: row for row in recorded_reviews}
    for row in [*recorded_reviews, *recorded_actions]:
        governance.require(row["package_id"] == package["id"] and row["payload_sha256"] == package["payload_sha256"]
            and row["selection_sha256"] == package["selection_sha256"])
    for row in recorded_reviews:
        governance.require(row["actor_user_id"] != package["actor_user_id"])
    for row in recorded_actions:
        review = by_id.get(row["review_id"])
        governance.require(review is not None and review["decision"] == "approve"
            and len({row["actor_user_id"], review["actor_user_id"], package["actor_user_id"]}) == 3)
    # Include every recorded decision/action, not just the displayed page.
    history_sha256 = governance._sha({"version": VERSION, "package": package,
        "reviews": recorded_reviews, "actions": recorded_actions})
    return package, recorded_reviews, recorded_actions, history_sha256


def _summary(package, reviews, actions, history_sha256):
    rejected = sum(row["decision"] == "reject" for row in reviews)
    return {"version": VERSION, "scope": governance.SCOPE, "package": package,
        "history_sha256": history_sha256, "review_count": len(reviews), "rejection_count": rejected,
        "has_rejection": rejected > 0, "actions": actions,
        "has_withdrawal": any(row["kind"] == "withdraw" for row in actions),
        "current_publication_eligibility": "not_checked", "history_semantics": "append_only_any_rejection_holds",
        **AUTHORITY}


async def inspect_governance(db, *, actor_user_id, package_id):
    result = _summary(*await _inventory(db, actor_user_id=actor_user_id, package_id=package_id))
    return {**result, "actor_user_id": str(governance.distribution._uuid(actor_user_id))}


async def review_history(db, *, actor_user_id, package_id, after=None, expected_history_sha256=None):
    governance.require(after is None or expected_history_sha256 is not None, "discovery_history_pin_required")
    if expected_history_sha256 is not None:
        governance.distribution.contract._hash(expected_history_sha256)
    if after is not None:
        after = str(governance.distribution._uuid(after))
    package, reviews, actions, pin = await _inventory(db, actor_user_id=actor_user_id, package_id=package_id)
    if expected_history_sha256 is not None:
        governance._match(expected_history_sha256 == pin)
    start = 0
    if after is not None:
        positions = [index for index, row in enumerate(reviews) if row["id"] == after]
        governance._match(len(positions) == 1)
        start = positions[0] + 1
    page = reviews[start:start + PAGE_SIZE]
    return {**_summary(package, reviews, actions, pin), "actor_user_id": str(governance.distribution._uuid(actor_user_id)),
        "reviews": page, "after": after, "next_after": page[-1]["id"] if start + len(page) < len(reviews) else None,
        "page_size": PAGE_SIZE, "returned_count": len(page), "history_order": "created_at_then_id_ascending"}
