"""Exact companion disclosure with fresh, private, three-account governance.

Writers own only a savepoint. Authenticated HTTP callers own outer durability;
preview and exact replay must roll back their outer transaction too. Historical
receipts are not present publication eligibility. No provider or filesystem I/O.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from uuid import UUID

import sqlalchemy as sa

from models.discovery_projection_v1 import MAX_BYTES, SCOPE, TABLE_ORDER, VERSION
from services import discovery_scientific_projection as projection
from services import research_distribution as distribution
from services.research_access import (
    active_grant,
    check_grant_inventory,
    require_research_operator,
    table,
)

AUTHORITY = {"scientific_acceptance": False, "ml_training_approved": False, "current_authorization_checked": False}
_OPERATIONS = {"register": (TABLE_ORDER[0], "curator"), "review": (TABLE_ORDER[1], "reviewer"),
               "publish": (TABLE_ORDER[2], "publisher"), "withdraw": (TABLE_ORDER[2], "publisher")}
_JSON_FIELDS = {"payload_json", "public_bundle_json", "selection_json", "dependency_ids_json", "scientific_pins_json", "rights_json"}
_HASH = sa.func.public.sclib_discovery_projection_hash_v1


class DiscoveryGovernanceError(ValueError):
    """Static private operation failure, never source-bearing SQL or JSON."""


class DiscoveryGovernanceConflict(DiscoveryGovernanceError):
    """The exact request, immutable target or current admission has changed."""


class DiscoveryGovernanceNotFound(DiscoveryGovernanceError):
    """No exact committed receipt here; absence does not prove rollback."""


def require(value, code="discovery_governance_unavailable"):
    if not value:
        raise DiscoveryGovernanceError(code)


def _match(value):
    if not value:
        raise DiscoveryGovernanceConflict("discovery_governance_changed")


def _json(value):
    result = distribution._canonical(value)
    require(len(result.encode("utf-8")) <= MAX_BYTES, "discovery_governance_byte_limit")
    return result


def _sha(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _wire(value):
    return {key: str(item) if isinstance(item, UUID) else item for key, item in value.items()}


async def _session(db, *, write=False):
    require(not (db.new or db.dirty or db.deleted), "discovery_clean_session_required")
    row = (await db.execute(sa.text("""SELECT current_setting('transaction_isolation') AS isolation,
        current_setting('TimeZone') AS timezone,
        (SELECT setting::bigint FROM pg_settings WHERE name='statement_timeout') AS timeout_ms"""))).mappings().one()
    require(row["isolation"] in ({"serializable"} if write else {"repeatable read", "serializable"})
            and row["timezone"] == "UTC" and type(row["timeout_ms"]) is int and 0 < row["timeout_ms"] <= 10000,
            "discovery_bounded_snapshot_required")


@asynccontextmanager
async def _write(db, dry_run):
    require(type(dry_run) is bool, "discovery_explicit_preview_required")
    await _session(db, write=True)
    async with asyncio.timeout(25):
        nested = await db.begin_nested()
        changed = {"value": False}
        try:
            await db.execute(sa.text("SELECT public.sclib_research_distribution_lock_v1()"))
            yield changed
            if dry_run or not changed["value"]:
                await nested.rollback()
            else:
                await nested.commit()
        except BaseException:
            if nested.is_active:
                await nested.rollback()
            raise


async def _actor(db, actor_user_id, role):
    identifier = distribution._uuid(actor_user_id)
    grant = await active_grant(db, identifier, role=role)
    return {"actor_user_id": identifier, "actor_grant_id": grant["id"]}


async def _rows(db, name, condition, *, maximum=1, header=False):
    require(name in TABLE_ORDER)
    relation = table(name)
    body = sa.func.to_jsonb(relation.table_valued())
    sizes = (await db.execute(sa.select(relation.c.id, sa.func.octet_length(sa.cast(body, sa.Text)))
        .where(condition).limit(maximum + 1))).all()
    # PostgreSQL's to_jsonb encoding escapes each retained TEXT document again;
    # the actual column-byte limit remains MAX_BYTES, independently native-bound.
    require(len(sizes) <= maximum and sum(size for _, size in sizes) <= 2 * MAX_BYTES + 1024 * 1024,
            "discovery_governance_row_limit")
    if not sizes:
        return []
    columns = [column for column in relation.c if not header or column.name not in _JSON_FIELDS]
    rows = (await db.execute(sa.select(*columns, _HASH(body).label("actual_record_sha256"))
        .where(relation.c.id.in_([identifier for identifier, _ in sizes])))).mappings().all()
    require(len(rows) == len(sizes) and all(row["record_sha256"] == row["actual_record_sha256"] for row in rows))
    return [{key: value for key, value in row.items() if key != "actual_record_sha256"} for row in rows]


async def _get(db, name, identifier, *, header=False):
    rows = await _rows(db, name, table(name).c.id == distribution._uuid(identifier), header=header)
    if not rows:
        raise DiscoveryGovernanceNotFound("discovery_operation_not_found")
    return rows[0]


async def _existing(db, operation, actor, key, request_sha256):
    name, _ = _OPERATIONS[operation]
    relation = table(name)
    rows = await _rows(db, name, sa.and_(relation.c.actor_user_id == actor["actor_user_id"], relation.c.request_key == key), header=True)
    if not rows:
        return None
    row = rows[0]
    _match(row["request_sha256"] == request_sha256 and row["actor_grant_id"] == actor["actor_grant_id"]
           and (operation not in {"publish", "withdraw"} or row["kind"] == operation))
    return row


async def _insert(db, name, values, changed):
    relation = table(name)
    row = dict((await db.execute(relation.insert().values(**values).returning(relation))).mappings().one())
    changed["value"] = True
    return row


def _report(row, operation, dry_run, replayed):
    return {"version": VERSION, "operation": operation, "id": str(row["id"]),
        "package_id": str(row["id"] if operation == "register" else row["package_id"]),
        "record_sha256": row["record_sha256"], "payload_sha256": row["payload_sha256"],
        "selection_sha256": row["selection_sha256"], "request_sha256": row["request_sha256"],
        "dry_run": dry_run, "committed": False, "replayed": replayed, **AUTHORITY}


async def _package(db, identifier):
    row = await _get(db, TABLE_ORDER[0], identifier)
    for body, sha in (("payload_json", "payload_sha256"), ("public_bundle_json", "public_bundle_text_sha256"),
            ("selection_json", "selection_sha256"), ("dependency_ids_json", "dependency_ids_sha256"),
            ("scientific_pins_json", "scientific_pins_sha256")):
        require(_text_sha(row[body]) == row[sha])
    return row


def _build_arguments(package):
    return {"distribution_package_id": package["distribution_package_id"],
        "expected_distribution_record_sha256": package["distribution_record_sha256"],
        "expected_inventory_sha256": package["inventory_sha256"],
        "public_bundle": json.loads(package["public_bundle_json"]),
        "selection": json.loads(package["selection_json"]), "expected_selection_sha256": package["selection_sha256"]}


def _accepted(pins):
    return sum(scope["scope"] == "scientific_result" and scope["effective_status"] == "accepted"
        and scope["scientific_scope_accepted"] is True
        for status in pins.values() for scope in status["scopes"])


async def _current(db, package, *, publishing=False):
    """Full rebuild, not a stored flag or an arbitrary duck-typed cell snapshot."""
    rebuilt = await projection.build_projection(db, **_build_arguments(package))
    _match(_json(rebuilt["payload"]) == package["payload_json"]
        and _json(rebuilt["scientific_pins"]) == package["scientific_pins_json"]
        and rebuilt["selection_sha256"] == package["selection_sha256"])
    original, inventory = await distribution._package(db, package["distribution_package_id"])
    _match(original["record_sha256"] == package["distribution_record_sha256"]
        and original["inventory_sha256"] == package["inventory_sha256"]
        and _json(sorted(row["dependency_id"] for row in inventory["dependencies"])) == package["dependency_ids_json"])
    if publishing:
        require(_accepted(rebuilt["scientific_pins"]) > 0, "discovery_reviewed_scientific_cell_required")
        await distribution.admitted_distribution(db, package["distribution_package_id"])
    return inventory


async def register_projection(db, *, actor_user_id, request_key, distribution_package_id,
        expected_distribution_record_sha256, expected_inventory_sha256, public_bundle, selection,
        expected_selection_sha256, expected_payload_sha256=None, dry_run=True):
    key = distribution._key(request_key)
    require(type(dry_run) is bool)
    if expected_payload_sha256 is not None:
        distribution.contract._hash(expected_payload_sha256)
    require(dry_run or expected_payload_sha256 is not None, "discovery_exact_preview_payload_required")
    arguments = {"distribution_package_id": str(distribution._uuid(distribution_package_id)),
        "expected_distribution_record_sha256": distribution.contract._hash(expected_distribution_record_sha256),
        "expected_inventory_sha256": distribution.contract._hash(expected_inventory_sha256),
        "public_bundle": json.loads(_json(public_bundle)),
        "selection": projection.capture_selection(selection, expected_selection_sha256),
        "expected_selection_sha256": expected_selection_sha256}
    require(len(_json(arguments["public_bundle"]).encode()) <= 16 * 1024 * 1024
            and len(_json(arguments["selection"]).encode()) <= 4 * 1024 * 1024, "discovery_input_byte_limit")
    request_sha = _sha({"version": VERSION, "operation": "register", **arguments})
    async with _write(db, dry_run) as changed:
        actor = await _actor(db, actor_user_id, "curator")
        row = await _existing(db, "register", actor, key, request_sha)
        replayed = row is not None
        if row is not None and expected_payload_sha256 is not None:
            _match(row["payload_sha256"] == expected_payload_sha256)
        if row is None:
            built = await projection.build_projection(db, **arguments)
            _, inventory = await distribution._package(db, arguments["distribution_package_id"])
            payload, pins = _json(built["payload"]), _json(built["scientific_pins"])
            if expected_payload_sha256 is not None:
                _match(_text_sha(payload) == expected_payload_sha256)
            ids = _json(sorted(row["dependency_id"] for row in inventory["dependencies"]))
            require(len(payload.encode()) <= 4 * 1024 * 1024, "discovery_payload_byte_limit")
            bundle_text, selection_text = _json(arguments["public_bundle"]), _json(arguments["selection"])
            require(sum(len(value.encode()) for value in (payload, pins, ids, bundle_text, selection_text)) <= MAX_BYTES)
            row = await _insert(db, TABLE_ORDER[0], {**actor, "request_key": key, "request_sha256": request_sha,
                "distribution_package_id": distribution._uuid(arguments["distribution_package_id"]),
                "distribution_record_sha256": expected_distribution_record_sha256, "inventory_sha256": expected_inventory_sha256,
                "payload_json": payload, "payload_sha256": _text_sha(payload), "selection_sha256": expected_selection_sha256,
                "public_bundle_json": bundle_text, "public_bundle_text_sha256": _text_sha(bundle_text), "selection_json": selection_text,
                "dependency_ids_json": ids, "dependency_ids_sha256": _text_sha(ids),
                "scientific_pins_json": pins, "scientific_pins_sha256": _text_sha(pins)}, changed)
        result = _report(row, "register", dry_run, replayed)
    return result


def _rights(value):
    rows = json.loads(_json(value))
    require(type(rows) is list and len(rows) <= 20000)
    for row in rows:
        require(type(row) is dict and set(row) == {"dependency_id", "row_sha256", "license_code", "basis_code"})
        distribution.contract._hash(row["dependency_id"])
        distribution.contract._hash(row["row_sha256"])
        require(type(row["license_code"]) is str and row["license_code"] in distribution.LICENSES)
        distribution._code(row["basis_code"])
    identifiers = [row["dependency_id"] for row in rows]
    require(identifiers == sorted(set(identifiers)), "discovery_exact_rights_order_required")
    require(len(_json(rows).encode()) <= 8 * 1024 * 1024)
    return rows


async def review_projection(db, *, actor_user_id, request_key, package_id, expected_payload_sha256,
        expected_selection_sha256, rights, decision, representative_selection_approved,
        disclosure_approved, reason_code, dry_run=True):
    key = distribution._key(request_key)
    require(type(decision) is str and decision in {"approve", "reject"}
        and type(representative_selection_approved) is bool and type(disclosure_approved) is bool)
    require(decision != "approve" or (representative_selection_approved and disclosure_approved))
    rights = _rights(rights)
    require(decision != "reject" or rights == [])
    body = {"package_id": str(distribution._uuid(package_id)),
        "payload_sha256": distribution.contract._hash(expected_payload_sha256),
        "selection_sha256": distribution.contract._hash(expected_selection_sha256), "decision": decision,
        "representative_selection_approved": representative_selection_approved, "disclosure_approved": disclosure_approved,
        "rights": rights, "reason_code": distribution._code(reason_code), "scope": SCOPE}
    request_sha = _sha({"version": VERSION, "operation": "review", **body})
    async with _write(db, dry_run) as changed:
        actor = await _actor(db, actor_user_id, "reviewer")
        row = await _existing(db, "review", actor, key, request_sha)
        replayed = row is not None
        if row is None:
            package = await _package(db, package_id)
            _match(package["payload_sha256"] == expected_payload_sha256 and package["selection_sha256"] == expected_selection_sha256)
            require(package["actor_user_id"] != actor["actor_user_id"], "discovery_separate_reviewer_required")
            if decision == "approve":
                await active_grant(db, package["actor_user_id"], role="curator", grant_id=package["actor_grant_id"])
                await _current(db, package)
                await db.execute(sa.text("SELECT public.sclib_discovery_projection_rights_v1(:id,CAST(:rights AS jsonb))"),
                    {"id": package["id"], "rights": _json(rights)})
            values = {key: value for key, value in body.items() if key not in {"rights", "package_id"}}
            row = await _insert(db, TABLE_ORDER[1], {**values, **actor, "package_id": package["id"],
                "request_key": key, "request_sha256": request_sha, "rights_json": _json(rights), "rights_sha256": _sha(rights)}, changed)
        result = _report(row, "review", dry_run, replayed)
    return result


async def projection_action(db, *, actor_user_id, request_key, package_id, review_id,
        expected_payload_sha256, expected_selection_sha256, kind, reason_code, dry_run=True):
    require(type(kind) is str and kind in {"publish", "withdraw"})
    key = distribution._key(request_key)
    body = {"package_id": str(distribution._uuid(package_id)), "review_id": str(distribution._uuid(review_id)),
        "payload_sha256": distribution.contract._hash(expected_payload_sha256),
        "selection_sha256": distribution.contract._hash(expected_selection_sha256), "kind": kind,
        "reason_code": distribution._code(reason_code)}
    request_sha = _sha({"version": VERSION, "operation": kind, **body})
    async with _write(db, dry_run) as changed:
        actor = await _actor(db, actor_user_id, "publisher")
        row = await _existing(db, kind, actor, key, request_sha)
        replayed = row is not None
        if row is None:
            package = await _package(db, package_id)
            review = await _get(db, TABLE_ORDER[1], review_id)
            _match(package["payload_sha256"] == expected_payload_sha256 and package["selection_sha256"] == expected_selection_sha256
                and review["package_id"] == package["id"] and review["payload_sha256"] == package["payload_sha256"]
                and review["selection_sha256"] == package["selection_sha256"] and review["decision"] == "approve")
            require(len({actor["actor_user_id"], package["actor_user_id"], review["actor_user_id"]}) == 3,
                    "discovery_three_accounts_required")
            if kind == "publish":
                await _review_current(db, package, review)
                await _current(db, package, publishing=True)
            values = {**body, "package_id": package["id"], "review_id": review["id"], **actor,
                      "request_key": key, "request_sha256": request_sha}
            row = await _insert(db, TABLE_ORDER[2], values, changed)
        result = _report(row, kind, dry_run, replayed)
    return result


async def _review_current(db, package, review):
    _match(review["package_id"] == package["id"] and review["payload_sha256"] == package["payload_sha256"]
        and review["selection_sha256"] == package["selection_sha256"] and review["decision"] == "approve"
        and review["representative_selection_approved"] is True and review["disclosure_approved"] is True)
    require(_text_sha(review["rights_json"]) == review["rights_sha256"])
    await check_grant_inventory(db, [(package["actor_user_id"], package["actor_grant_id"], "curator"),
        (review["actor_user_id"], review["actor_grant_id"], "reviewer")])
    negatives = table(TABLE_ORDER[1])
    require(not await db.scalar(sa.select(negatives.c.id).where(negatives.c.package_id == package["id"],
        negatives.c.decision == "reject").limit(1)), "discovery_projection_review_held")
    await db.execute(sa.text("SELECT public.sclib_discovery_projection_rights_v1(:id,CAST(:rights AS jsonb))"),
        {"id": package["id"], "rights": review["rights_json"]})


async def admitted_projection(db, package_id):
    """Fresh publication at this SQL read point, not permanent authorization."""
    await _session(db)
    async with asyncio.timeout(25):
        package = await _package(db, package_id)
        actions = table(TABLE_ORDER[2])
        rows = await _rows(db, TABLE_ORDER[2], actions.c.package_id == package["id"], maximum=2)
        require(len(rows) == 1 and rows[0]["kind"] == "publish", "discovery_projection_not_published")
        action = rows[0]
        review = await _get(db, TABLE_ORDER[1], action["review_id"])
        _match(action["payload_sha256"] == package["payload_sha256"] and action["selection_sha256"] == package["selection_sha256"])
        require(len({package["actor_user_id"], review["actor_user_id"], action["actor_user_id"]}) == 3)
        await active_grant(db, action["actor_user_id"], role="publisher", grant_id=action["actor_grant_id"])
        await _review_current(db, package, review)
        await _current(db, package, publishing=True)
        return {"version": VERSION, "package_id": str(package["id"]), "payload_sha256": package["payload_sha256"],
            "selection_sha256": package["selection_sha256"], "publication_sha256": action["record_sha256"],
            "review_sha256": review["record_sha256"], "payload": json.loads(package["payload_json"]), **AUTHORITY}


async def inspect_projection(db, *, actor_user_id, package_id):
    await _session(db)
    await require_research_operator(db, actor_user_id)
    package = await _package(db, package_id)
    # Reconstruct all typed cells; the caller cannot treat a matching hash of
    # manually inserted JSON as proof that the values follow from the sources.
    async with asyncio.timeout(25):
        await _current(db, package)
    dependencies = table("research_distribution_dependencies")
    rows = (await db.execute(sa.select(dependencies.c.dependency_id, dependencies.c.row_sha256)
        .where(dependencies.c.package_id == package["distribution_package_id"])
        .order_by(dependencies.c.dependency_id).limit(20001))).mappings().all()
    require(len(rows) <= 20000 and [row["dependency_id"] for row in rows] == json.loads(package["dependency_ids_json"]))
    return {"version": VERSION, "package_id": str(package["id"]), "payload_sha256": package["payload_sha256"],
        "selection_sha256": package["selection_sha256"], "payload": json.loads(package["payload_json"]),
        "rights_targets": [{"dependency_id": row["dependency_id"], "row_sha256": row["row_sha256"]}
            for row in rows], "scope": SCOPE, **AUTHORITY}


async def inspect_operation(db, *, actor_user_id, operation, request_key, expected_request_sha256):
    await _session(db)
    require(type(operation) is str and operation in _OPERATIONS)
    name, role = _OPERATIONS[operation]
    actor = await _actor(db, actor_user_id, role)
    key, sha = distribution._key(request_key), distribution.contract._hash(expected_request_sha256)
    relation = table(name)
    rows = await _rows(db, name, sa.and_(relation.c.actor_user_id == actor["actor_user_id"], relation.c.request_key == key), header=True)
    if not rows:
        raise DiscoveryGovernanceNotFound("discovery_operation_not_found")
    row = rows[0]
    _match(row["request_sha256"] == sha and (operation not in {"publish", "withdraw"} or row["kind"] == operation))
    return _report(row, operation, False, True)


async def public_projection_inventory(db):
    await _session(db)
    packages, actions = table(TABLE_ORDER[0]), table(TABLE_ORDER[2])
    withdrawn = actions.alias("withdrawn")
    ids = (await db.execute(sa.select(packages.c.id).join(actions, actions.c.package_id == packages.c.id)
        .where(actions.c.kind == "publish", ~sa.exists(sa.select(withdrawn.c.id).where(
            withdrawn.c.package_id == packages.c.id, withdrawn.c.kind == "withdraw")))
        .order_by(packages.c.id).limit(26))).scalars().all()
    require(len(ids) <= 25, "discovery_public_inventory_limit")
    items, unavailable = [], []
    async with asyncio.timeout(25):
        for identifier in ids:
            try:
                receipt = await admitted_projection(db, identifier)
            except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
                unavailable.append(str(identifier))
                continue
            items.append({key: receipt[key] for key in ("package_id", "payload_sha256", "selection_sha256", "publication_sha256")})
    return {"version": VERSION, "items": items, "unavailable": unavailable,
        "status": "degraded" if unavailable else "published" if items else "not_published", **AUTHORITY}
