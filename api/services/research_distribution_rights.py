"""Exact reviewer-authenticated RPS rights preparation, never ML authorization.

One fixed canonical document and its existing permission are saved atomically.
Services own a savepoint only; the authenticated HTTP boundary owns durability.
Rights statements are human decisions, not legal conclusions made by this code.
"""
from __future__ import annotations

import json

import sqlalchemy as sa

from services import research_distribution as distribution
from services.research_access import active_grant, table
from services.research_distribution_contract import ResearchDistributionError, _hash
from services.research_distribution_inputs import fetch_rows, require

VERSION = "rps-rights-preparation/1.0.0"
SOURCE = "sclib:rps-rights-preparation"
AUTHORITY = {"scientific_acceptance": False, "ml_training_approved": False,
             "current_authorization_checked": False}


class RightsPreparationConflict(ResearchDistributionError):
    """Exact intent, predecessor, or pinned input no longer matches."""


class RightsPreparationNotFound(ResearchDistributionError):
    """No committed matching record in this snapshot; not proof of rollback."""


def _match(condition):
    if not condition:
        raise RightsPreparationConflict("rights_preparation_changed")


async def _target(db, package_id, dependency_id):
    package = await distribution._get(db, "packages", package_id, header=True)
    require(package["scope"] == distribution.SCOPE and package["policy_version"] == distribution.VERSION)
    relation = table(distribution.PREFIX + "dependencies")
    rows = await distribution._history(db, "dependencies", sa.and_(
        relation.c.package_id == package["id"], relation.c.dependency_id == _hash(dependency_id)))
    require(len(rows) == 1, "rights_dependency_unavailable")
    dependency = distribution._dependency_dto(rows[0])
    require(dependency["row_sha256"] == distribution._sha(dependency["projection"]))
    return package, dependency


async def _head(db, package, dependency):
    relation = table(distribution.PREFIX + "permissions")
    successor = relation.alias("next_permission")
    rows = await distribution._history(db, "permissions", sa.and_(
        relation.c.package_id == package["id"], relation.c.dependency_id == dependency["dependency_id"],
        ~sa.exists(sa.select(successor.c.id).where(successor.c.supersedes_id == relation.c.id))))
    return rows[0] if rows else None


def _head_dto(head):
    return None if head is None else {"id": str(head["id"]), **{key: head[key] for key in (
        "record_sha256", "decision", "license_code", "basis_code", "reason_code")}}


async def inspect_rights_dependency(db, *, actor_user_id, package_id, dependency_id):
    """Small private snapshot; no raw source body or claim of legal eligibility."""
    await distribution._read_session(db)
    grant = await active_grant(db, distribution._uuid(actor_user_id), role="reviewer")
    package, dependency = await _target(db, package_id, dependency_id)
    head = await _head(db, package, dependency)
    return {"version": VERSION, "actor_user_id": str(actor_user_id), "actor_grant_id": str(grant["id"]),
        "package_id": str(package["id"]), "package_record_sha256": package["record_sha256"],
        "inventory_sha256": package["inventory_sha256"], "public_bundle_sha256": package["public_bundle_sha256"],
        "dependency": {key: dependency[key] for key in (
            "dependency_id", "table", "row_id", "row_sha256", "record_sha256", "bytes_sha256")},
        "head": _head_dto(head), **AUTHORITY}


async def rights_preparation_capabilities(db, *, actor_user_id):
    await distribution._read_session(db)
    grant = await active_grant(db, distribution._uuid(actor_user_id), role="reviewer")
    return {"version": VERSION, "scope": distribution.SCOPE, "actor_user_id": str(actor_user_id),
        "actor_grant_id": str(grant["id"]), "can_read": True, "can_prepare": True, **AUTHORITY}


async def list_rights_dependencies(db, *, actor_user_id, package_id, after=None, expected_inventory_sha256=None):
    """Twenty-five compact immutable headers, never raw dependency projections."""
    await distribution._read_session(db)
    grant = await active_grant(db, distribution._uuid(actor_user_id), role="reviewer")
    require(after is None or expected_inventory_sha256 is not None, "rights_inventory_pin_required")
    package = await distribution._get(db, "packages", package_id, header=True)
    if expected_inventory_sha256 is not None:
        _match(_hash(expected_inventory_sha256) == package["inventory_sha256"])
    relation = table(distribution.PREFIX + "dependencies")
    condition = relation.c.package_id == package["id"]
    if after is not None:
        condition = sa.and_(condition, relation.c.dependency_id > _hash(after))
    columns = [relation.c[name] for name in ("dependency_id", "table_name", "row_id", "row_sha256", "record_sha256")]
    rows = (await db.execute(sa.select(*columns, distribution._HASH_FUNCTION(
        sa.func.to_jsonb(relation.table_valued())).label("verified_sha256")).where(condition)
        .order_by(relation.c.dependency_id).limit(26))).mappings().all()
    require(all(row["verified_sha256"] == row["record_sha256"] for row in rows))
    page = [{"dependency_id": row["dependency_id"], "table": row["table_name"],
             "row_id": row["row_id"], "row_sha256": row["row_sha256"]} for row in rows[:25]]
    return {"version": VERSION, "actor_user_id": str(actor_user_id), "actor_grant_id": str(grant["id"]),
        "package_id": str(package["id"]), "package_record_sha256": package["record_sha256"],
        "inventory_sha256": package["inventory_sha256"], "dependency_count": package["dependency_count"],
        "dependencies": page, "next_after": page[-1]["dependency_id"] if len(rows) > 25 else None,
        **AUTHORITY}


def _document_from_permission(permission):
    """Recover only the fixed rights object, never the full artifact projection."""
    data = json.loads(permission["rights_projection_json"])
    document = data["metadata"]["distribution_rights"]
    require(distribution._sha(document) == permission["rights_bytes_sha256"]
            == permission["rights_record_sha256"] == data["bytes_sha256"] == data["record_sha256"])
    require(data["kind"] == "review" and data["schema_version"] == distribution.RIGHTS_VERSION
            and data["hash_status"] == "verified" and data["metadata"] == {"distribution_rights": document})
    return document


def _prepared_origin(permission):
    # Revocation may inherit a document made by the older governed workflow.
    # An allow receipt attributed to this preparation path must be its artifact.
    if permission["decision"] == "allow":
        data = json.loads(permission["rights_projection_json"])
        _match(data["source"] == SOURCE and data["source_version"] == VERSION
               and data["access"] == "restricted" and data["uri"] is None and data["license"] is None)


def _intent(package, dependency, actor, values, predecessor, document):
    return {"version": VERSION, "scope": distribution.SCOPE,
        "package_id": str(package["id"]), "package_record_sha256": package["record_sha256"],
        "inventory_sha256": package["inventory_sha256"], "public_bundle_sha256": package["public_bundle_sha256"],
        "dependency_id": dependency["dependency_id"], "dependency_row_sha256": dependency["row_sha256"],
        "actor_user_id": str(actor["actor_user_id"]), "actor_grant_id": str(actor["actor_grant_id"]),
        "request_key": values["request_key"], "decision": values["decision"],
        "license_code": values["license_code"], "basis_code": values["basis_code"], "reason_code": values["reason_code"],
        "expected_head_id": None if predecessor is None else str(predecessor["id"]),
        "expected_head_sha256": None if predecessor is None else predecessor["record_sha256"],
        "rights_bytes_sha256": distribution._sha(document), **AUTHORITY}


def _result(intent, document, dry_run, replayed, permission=None):
    return {"version": VERSION, "dry_run": dry_run, "committed": False, "replayed": replayed,
        "intent": intent, "intent_sha256": distribution._sha(intent), "rights_document": document,
        "rights_bytes_sha256": distribution._sha(document),
        "permission": None if permission is None else {"id": str(permission["id"]), "record_sha256": permission["record_sha256"]},
        "artifact": None if permission is None else {"id": str(permission["rights_artifact_id"]),
            "row_sha256": permission["rights_row_sha256"], "bytes_sha256": permission["rights_bytes_sha256"]}, **AUTHORITY}


async def _create_artifact(db, document):
    """Store only exact reproducible canonical review bytes in restricted metadata."""
    encoded = distribution.contract._bounded(document)
    sha = distribution._sha(document)
    relation = table("evidence_artifacts")
    identifier = (await db.execute(relation.insert().values(kind="review", schema_version=distribution.RIGHTS_VERSION,
        source=SOURCE, source_version=VERSION, record_sha256=sha, bytes_sha256=sha, hash_status="verified",
        access="restricted", uri=None, license=None, metadata={"distribution_rights": json.loads(encoded)})
        .returning(relation.c.id))).scalar_one()
    rows = await fetch_rows(db, "evidence_artifacts", {str(identifier)})
    require(len(rows) == 1 and rows[0]["data"]["metadata"] == {"distribution_rights": document})
    return rows[0], encoded


async def rights_preparation_outcome(db, *, actor_user_id, package_id, dependency_id,
                                     request_key, expected_intent_sha256):
    """Read-only exact historical recovery; never retry or execute a write."""
    await distribution._read_session(db)
    await active_grant(db, distribution._uuid(actor_user_id), role="reviewer")
    relation = table(distribution.PREFIX + "permissions")
    rows = await distribution._history(db, "permissions", sa.and_(
        relation.c.actor_user_id == distribution._uuid(actor_user_id),
        relation.c.request_key == distribution._key(request_key)))
    if not rows:
        raise RightsPreparationNotFound("rights_preparation_outcome_not_observed")
    permission = rows[0]
    _prepared_origin(permission)
    _match(permission["package_id"] == distribution._uuid(package_id) and permission["dependency_id"] == _hash(dependency_id))
    package, dependency = await _target(db, package_id, dependency_id)
    predecessor = None if permission["supersedes_id"] is None else await distribution._get(db, "permissions", permission["supersedes_id"])
    document = _document_from_permission(permission)
    intent = _intent(package, dependency, permission, permission, predecessor, document)
    _match(distribution._sha(intent) == _hash(expected_intent_sha256))
    return _result(intent, document, False, True, permission)


async def prepare_distribution_rights(db, *, actor_user_id, request_key, package_id, dependency_id,
        decision, license_code, basis_code, reason_code, expected_package_sha256, expected_inventory_sha256,
        expected_dependency_row_sha256, expected_head_id, expected_head_sha256,
        expected_intent_sha256=None, dry_run=True):
    """Preview or atomically prepare one rights artifact and existing permission.

    Preview exercises the same actual insert/constraint path, then rolls it back.
    Exact retry recovers history before considering the now-changed current head.
    It does not reassert present source or publication eligibility.
    """
    require(type(dry_run) is bool and type(decision) is str and decision in {"allow", "revoke"}
            and type(license_code) is str and license_code in distribution.LICENSES)
    require((expected_head_id is None) == (expected_head_sha256 is None))
    if expected_head_sha256 is not None:
        _hash(expected_head_sha256)
    require(dry_run or expected_intent_sha256 is not None, "rights_preview_pin_required")
    if expected_intent_sha256 is not None:
        _hash(expected_intent_sha256)
    request_key, basis_code, reason_code = (distribution._key(request_key), distribution._code(basis_code), distribution._code(reason_code))
    async with distribution._write(db, dry_run) as operation:
        actor = await distribution._actor(db, actor_user_id, request_key, "reviewer")
        package, dependency = await _target(db, package_id, dependency_id)
        _match(package["record_sha256"] == _hash(expected_package_sha256)
               and package["inventory_sha256"] == _hash(expected_inventory_sha256)
               and dependency["row_sha256"] == _hash(expected_dependency_row_sha256))
        predecessor = None if expected_head_id is None else await distribution._get(db, "permissions", expected_head_id)
        if predecessor is not None:
            _match(predecessor["package_id"] == package["id"] and predecessor["dependency_id"] == dependency_id
                   and predecessor["record_sha256"] == expected_head_sha256)
        if decision == "revoke":
            require(predecessor is not None and license_code == predecessor["license_code"], "rights_revoke_predecessor_required")
            document = _document_from_permission(predecessor)
        else:
            document = distribution.rights_review_payload(package, dependency, license_code, basis_code)
        values = {**actor, "package_id": package["id"], "dependency_id": dependency_id, "decision": decision,
            "scope": distribution.SCOPE, "license_code": license_code, "basis_code": basis_code, "reason_code": reason_code,
            "supersedes_id": None if predecessor is None else predecessor["id"]}
        intent = _intent(package, dependency, actor, values, predecessor, document)
        if expected_intent_sha256 is not None:
            _match(distribution._sha(intent) == expected_intent_sha256)
        existing = await distribution._existing(db, "permissions", values)
        if existing is not None:
            # Immutable permission bytes recover the original result even if a
            # later permission or source hold has superseded its eligibility.
            _match(_document_from_permission(existing) == document)
            _prepared_origin(existing)
            result = _result(intent, document, dry_run, True, existing)
        else:
            head = await _head(db, package, dependency)
            _match((None if head is None else head["id"]) == (None if predecessor is None else predecessor["id"]))
            artifact, encoded = (None, None)
            if decision == "allow":
                # Check the target before creating an artifact; the unchanged
                # permission INSERT trigger independently repeats this check.
                current = await fetch_rows(db, dependency["table"], {dependency["row_id"]})
                _match(len(current) == 1 and current[0]["row_sha256"] == dependency["row_sha256"]
                       and current[0]["data"] == dependency["projection"])
                artifact, encoded = await _create_artifact(db, document)
            arguments = {"rights_artifact_id": artifact["row_id"], "expected_rights_row_sha256": artifact["row_sha256"],
                         "rights_bytes": encoded} if artifact is not None else {}
            receipt = await distribution.decide_distribution_permission(db, actor_user_id=actor_user_id,
                request_key=request_key, package_id=package_id, dependency_id=dependency_id, decision=decision,
                license_code=license_code, basis_code=basis_code, reason_code=reason_code,
                supersedes_id=expected_head_id, dry_run=False, **arguments)
            permission = await distribution._get(db, "permissions", receipt["id"])
            operation["changed"] = True
            result = _result(intent, document, dry_run, False, None if dry_run else permission)
    return result
