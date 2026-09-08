"""Exact, private RPS distribution workflow and fresh public admission.

Actors must come from a trusted authentication boundary. Services own only a
savepoint, never the outer commit. Permission is a recorded disclosure decision,
not legal proof, scientific acceptance, or permission to train a model.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_engine
from models.research_distribution_v1 import HISTORY_TABLES, LOCK_FUNCTION, SCOPE, VERSION
from services import research_distribution_contract as contract
from services import research_publication as publication
from services import research_release_manifest as capsule
from services.research_access import (
    ResearchAccessDenied,
    active_grant,
    check_grant_inventory,
    table,
)
from services.research_distribution_contract import ResearchDistributionError
from services.research_distribution_inputs import (
    build_inventory,
    capture_inputs,
    fetch_rows,
    require,
)
from services.research_freeze import ResearchFreezeError, _bundle_hash, _stored, _verify_pins
from services.source_lifecycle import SourceLifecycleError

RIGHTS_VERSION = "rps-distribution-rights/1.0.0"
LICENSES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "permission-on-file"}
PREFIX = "research_distribution_"
_BODY_FIELDS = {"binding_manifest", "inventory_json"}
_HASH_FUNCTION = sa.func.public.sclib_research_distribution_record_hash_v1


class DistributionRegistryUnavailable(ValueError):
    """A safe, bounded current database observation cannot be completed."""


class DistributionAdmissionChanged(ValueError):
    """The request's previously observed public admission has changed."""


def _sha(value):
    return hashlib.sha256(contract._bounded(value)).hexdigest()


def _code(value):
    require(type(value) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,159}", value))
    return value


def _key(value):
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}", value))
    return value


def _uuid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ResearchDistributionError("distribution_invalid_identifier") from None


def _canonical(value):
    return contract._bounded(value).decode("utf-8")


async def _read_session(db):
    """No implicit ORM flush or mixed-snapshot/locale-dependent projections."""
    require(not (db.new or db.dirty or db.deleted), "distribution_clean_session_required")
    isolation = (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one()
    require(isolation in {"repeatable read", "serializable"}, "distribution_stable_read_session_required")
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))


@asynccontextmanager
async def _write(db, dry_run):
    require(type(dry_run) is bool and not (db.new or db.dirty or db.deleted))
    require((await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one() == "serializable",
            "distribution_serializable_session_required")
    nested = await db.begin_nested()
    operation = {"changed": False}
    try:
        await db.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
        await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
        yield operation
        # Exercise deferred atomic inventory completeness during previews too.
        await db.execute(sa.text("SET CONSTRAINTS rd63_complete IMMEDIATE"))
        await db.execute(sa.text("SET CONSTRAINTS rd63_complete DEFERRED"))
        if dry_run or not operation["changed"]:
            await nested.rollback()
        else:
            await nested.commit()
    except BaseException:
        if nested.is_active:
            await nested.rollback()
        raise


async def _history(db, name, condition, *, limit=1, header=False, budget=None):
    require(PREFIX + name in HISTORY_TABLES and 1 <= limit <= contract.MAX_DEPENDENCIES)
    relation = table(PREFIX + name)
    columns = [column for column in relation.c if not (header and column.name in _BODY_FIELDS)]
    body = sa.func.to_jsonb(relation.table_valued())
    # Large canonical bodies are preflighted before transfer, including JSON
    # escaping expansion. SQL computes the compact immutable record checksum.
    size_body = body.op("-")(sa.cast(list(_BODY_FIELDS), sa.ARRAY(sa.Text))) if header else body
    sizes = (await db.execute(sa.select(relation.c.id, sa.func.octet_length(sa.cast(size_body, sa.Text)))
                             .where(condition).limit(limit + 1))).all()
    require(len(sizes) <= limit, "distribution_inventory_limit")
    total = sum(size for _, size in sizes)
    require(total <= contract.MAX_BYTES * 2, "distribution_inventory_limit")
    if budget is not None:
        budget["bytes"] = budget.get("bytes", 0) + total
        budget["rows"] = budget.get("rows", 0) + len(sizes)
        if budget["bytes"] > 128 * 1024 * 1024 or budget["rows"] > 50000:
            raise DistributionRegistryUnavailable("distribution_request_budget_exceeded")
    rows = (await db.execute(sa.select(*columns, _HASH_FUNCTION(body).label("verified_sha256"))
                            .where(condition).limit(limit + 1))).mappings().all()
    require(len(rows) == len(sizes))
    result = []
    for row in rows:
        value = dict(row)
        require(value.pop("verified_sha256") == value["record_sha256"], "distribution_record_integrity")
        result.append(value)
    return result


async def _get(db, name, identifier, *, header=False, budget=None):
    relation = table(PREFIX + name)
    rows = await _history(db, name, relation.c.id == _uuid(identifier), header=header, budget=budget)
    require(len(rows) == 1, "distribution_record_unavailable")
    return rows[0]


async def _existing(db, name, values):
    relation = table(PREFIX + name)
    rows = await _history(db, name, sa.and_(relation.c.actor_user_id == values["actor_user_id"],
                                         relation.c.request_key == values["request_key"]))
    if not rows:
        return None
    row = rows[0]
    require(all(row[key] == value for key, value in values.items()), "distribution_request_key_conflict")
    return row


async def _insert(db, name, values, operation):
    relation = table(PREFIX + name)
    result = dict((await db.execute(relation.insert().values(**values).returning(relation))).mappings().one())
    operation["changed"] = True
    return result


def _report(row, dry_run, operation):
    return {"id": str(row["id"]), "record_sha256": row["record_sha256"], "dry_run": dry_run,
            "committed": False, "replayed": not operation["changed"],
            "scientific_acceptance": False, "ml_training_approved": False}


async def _actor(db, actor_user_id, request_key, role):
    grant = await active_grant(db, _uuid(actor_user_id), role=role)
    return {"actor_user_id": _uuid(actor_user_id), "actor_grant_id": grant["id"], "request_key": _key(request_key)}


def _dependency_dto(row):
    return {"dependency_id": row["dependency_id"], "table": row["table_name"], "row_id": row["row_id"],
            "row_sha256": row["row_sha256"], "record_sha256": row["source_record_sha256"],
            "bytes_sha256": row["bytes_sha256"], "projection": json.loads(row["projection_json"]),
            "capsule_manifest_sha256s": row["capsule_manifest_sha256s"]}


async def _package(db, package_id, *, budget=None):
    package = await _get(db, "packages", package_id, budget=budget)
    inventory, bindings = json.loads(package["inventory_json"]), json.loads(package["binding_manifest"])
    require(_canonical(inventory) == package["inventory_json"] and _sha(inventory) == package["inventory_sha256"])
    require(_canonical(bindings) == package["binding_manifest"] and _sha(bindings) == package["bindings_sha256"])
    require(package["scope"] == SCOPE and package["policy_version"] == VERSION)
    require(inventory["version"] == contract.VERSION and bindings["version"] == contract.BINDINGS_VERSION)
    for key in ("release_id", "release_manifest_sha256", "public_bundle_sha256"):
        require(inventory[key] == bindings[key] == package[key])
    require(inventory["bindings_sha256"] == package["bindings_sha256"])
    require(all(inventory[key] is False for key in contract.AUTHORITY))
    require(package["binding_count"] == len(inventory["artifact_bindings"]) == len(bindings["bindings"]))
    relation = table(PREFIX + "dependencies")
    stored = await _history(db, "dependencies", relation.c.package_id == package["id"],
                            limit=contract.MAX_DEPENDENCIES, budget=budget)
    dependencies = sorted((_dependency_dto(row) for row in stored), key=lambda item: item["dependency_id"])
    require(package["dependency_count"] == len(dependencies) and dependencies == inventory["dependencies"])
    for row in dependencies:
        require(row["row_sha256"] == _sha(row["projection"]))
        require(row["dependency_id"] == _sha({"version": contract.DEPENDENCY_VERSION,
            "table": row["table"], "row_id": row["row_id"], "row_sha256": row["row_sha256"]}))
    return package, inventory


async def inspect_distribution(db, *, package_id):
    """Private inspection; caller must authenticate and authorize this endpoint."""
    await _read_session(db)
    package, inventory = await _package(db, package_id)
    return {"package_id": str(package["id"]), "inventory_sha256": package["inventory_sha256"],
            "bindings": json.loads(package["binding_manifest"]), "inventory": inventory,
            "scientific_acceptance": False, "ml_training_approved": False, "current_authorization_checked": False}


async def register_distribution(db, *, actor_user_id, request_key, release, bindings,
                                expected_release_sha256, expected_bindings_sha256, public_bundle,
                                expected_public_bundle_sha256, artifact_bytes, capsule_artifact_bytes=None,
                                dry_run=True):
    inputs = capture_inputs(release=release, bindings=bindings, public_bundle=public_bundle,
        artifact_bytes=artifact_bytes, capsule_artifact_bytes={} if capsule_artifact_bytes is None else capsule_artifact_bytes)
    pins = {"expected_release_sha256": contract._hash(expected_release_sha256),
            "expected_bindings_sha256": contract._hash(expected_bindings_sha256),
            "expected_public_bundle_sha256": contract._hash(expected_public_bundle_sha256)}
    request_key = _key(request_key)
    async with _write(db, dry_run) as operation:
        actor = await _actor(db, actor_user_id, request_key, "curator")
        inventory = await build_inventory(db, **pins, **inputs)
        values = {**actor, "release_id": inventory["release_id"],
            "release_manifest_sha256": expected_release_sha256, "public_bundle_sha256": expected_public_bundle_sha256,
            "scope": SCOPE, "policy_version": VERSION, "binding_manifest": _canonical(inputs["bindings"]),
            "bindings_sha256": expected_bindings_sha256, "inventory_json": _canonical(inventory),
            "inventory_sha256": _sha(inventory)}
        row = await _existing(db, "packages", values)
        if row is None:
            row = await _insert(db, "packages", values, operation)
            for item in inventory["dependencies"]:
                await _insert(db, "dependencies", {"package_id": row["id"], "dependency_id": item["dependency_id"],
                    "table_name": item["table"], "row_id": item["row_id"], "row_sha256": item["row_sha256"],
                    "source_record_sha256": item["record_sha256"], "bytes_sha256": item["bytes_sha256"],
                    "projection_json": _canonical(item["projection"]),
                    "capsule_manifest_sha256s": item["capsule_manifest_sha256s"]}, operation)
        result = {**_report(row, dry_run, operation), "package_id": str(row["id"]),
                  "inventory_sha256": row["inventory_sha256"], "inventory": inventory}
    return result


def rights_review_payload(package, dependency, license_code, basis_code):
    """Canonical intent to be backed by an actual privately stored review file."""
    require(license_code in LICENSES)
    return {"version": RIGHTS_VERSION, "scope": SCOPE, "package_id": str(package["id"]),
            "inventory_sha256": package["inventory_sha256"], "dependency_id": dependency["dependency_id"],
            "dependency_row_sha256": dependency["row_sha256"], "public_bundle_sha256": package["public_bundle_sha256"],
            "license_code": license_code, "basis_code": _code(basis_code), "distribution_permitted": True,
            "scientific_acceptance": False, "ml_training_approved": False}


async def decide_distribution_permission(db, *, actor_user_id, request_key, package_id, dependency_id,
        decision, license_code, basis_code, reason_code, rights_artifact_id=None,
        expected_rights_row_sha256=None, rights_bytes=None, supersedes_id=None, dry_run=True):
    require(type(decision) is str and decision in {"allow", "revoke"} and license_code in LICENSES)
    dependency_id = contract._hash(dependency_id)
    basis_code, reason_code, request_key = _code(basis_code), _code(reason_code), _key(request_key)
    # bytes are immutable; mutable bytearray/memoryview are deliberately rejected.
    require(rights_bytes is None or type(rights_bytes) is bytes and len(rights_bytes) <= capsule.LIMITS["file_bytes"])
    async with _write(db, dry_run) as operation:
        actor = await _actor(db, actor_user_id, request_key, "reviewer")
        package = await _get(db, "packages", package_id, header=True)
        relation = table(PREFIX + "dependencies")
        rows = await _history(db, "dependencies", sa.and_(relation.c.package_id == package["id"],
                                                         relation.c.dependency_id == dependency_id))
        require(len(rows) == 1)
        dependency = _dependency_dto(rows[0])
        values = {**actor, "package_id": package["id"], "dependency_id": dependency_id,
            "decision": decision, "scope": SCOPE, "license_code": license_code, "basis_code": basis_code,
            "reason_code": reason_code, "supersedes_id": _uuid(supersedes_id) if supersedes_id is not None else None}
        if decision == "allow":
            document = rights_review_payload(package, dependency, license_code, basis_code)
            expected_bytes = contract._bounded(document)
            require(rights_bytes == expected_bytes, "distribution_exact_rights_bytes_required")
            rights = await fetch_rows(db, "evidence_artifacts", {str(_uuid(rights_artifact_id))})
            require(len(rights) == 1 and rights[0]["row_sha256"] == contract._hash(expected_rights_row_sha256))
            data = rights[0]["data"]
            require(data["kind"] == "review" and data["schema_version"] == RIGHTS_VERSION
                and data["hash_status"] == "verified" and data["metadata"] == {"distribution_rights": document}
                and data["record_sha256"] == data["bytes_sha256"] == hashlib.sha256(expected_bytes).hexdigest(),
                "distribution_exact_rights_artifact_required")
            values.update(rights_artifact_id=_uuid(data["id"]), rights_row_sha256=rights[0]["row_sha256"],
                rights_record_sha256=data["record_sha256"], rights_bytes_sha256=data["bytes_sha256"],
                rights_projection_json=_canonical(data))
        else:
            require(supersedes_id is not None, "distribution_revoke_requires_predecessor")
            previous = await _get(db, "permissions", supersedes_id)
            require(previous["package_id"] == package["id"] and previous["dependency_id"] == dependency_id
                    and previous["license_code"] == license_code)
            require(rights_artifact_id is None or _uuid(rights_artifact_id) == previous["rights_artifact_id"])
            require(expected_rights_row_sha256 is None or expected_rights_row_sha256 == previous["rights_row_sha256"])
            require(rights_bytes is None or hashlib.sha256(rights_bytes).hexdigest() == previous["rights_bytes_sha256"])
            values.update({key: previous[key] for key in ("rights_artifact_id", "rights_row_sha256",
                "rights_record_sha256", "rights_bytes_sha256", "rights_projection_json")})
        row = await _existing(db, "permissions", values) or await _insert(db, "permissions", values, operation)
        result = _report(row, dry_run, operation)
    return result


async def _current_sources(db, inventory):
    grouped = defaultdict(set)
    for row in inventory["dependencies"]:
        grouped[row["table"]].add(row["row_id"])
    expected = {(row["table"], row["row_id"]): row for row in inventory["dependencies"]}
    budget, actual = {}, {}
    for name, identifiers in sorted(grouped.items()):
        for row in await fetch_rows(db, name, identifiers, budget=budget):
            actual[(name, row["row_id"])] = row
    require(set(actual) == set(expected))
    for key, row in actual.items():
        require(row["row_sha256"] == expected[key]["row_sha256"]
                and row["data"] == expected[key]["projection"], "distribution_current_dependency_changed")
    # Reuse the site's actual material/source lifecycle projection, including
    # legacy material records and ancestors, rather than only old boolean flags.
    public_rows = [row for row in actual.values() if row["table"] in {"materials", "papers", "works"}]
    for start in range(0, len(public_rows), 500):
        await publication._current_catalogue(db, {"manifest": {"rows": public_rows[start:start + 500]}})
    manifests = sorted({sha for row in inventory["dependencies"] for sha in row["capsule_manifest_sha256s"]})
    require(len(manifests) <= contract.MAX_CAPSULES)
    releases, notices = table("research_releases"), table("research_release_notices")
    for sha in manifests:
        ids = (await db.execute(sa.select(releases.c.id).where(releases.c.manifest_sha256 == sha).limit(2))).scalars().all()
        require(len(ids) == 1)
        stored = await _stored(db, "research_releases", ids[0])
        await _verify_pins(db, stored)
        require(stored["bundle_sha256"] == _bundle_hash(stored["manifest"]))
        require(not (await db.execute(sa.select(notices.c.id).where(notices.c.release_id == ids[0]).limit(1))).first(),
                "distribution_capsule_notice_hold")


async def _permissions(db, package, inventory, *, budget=None):
    relation = table(PREFIX + "permissions")
    next_row = relation.alias("successor")
    rows = await _history(db, "permissions", sa.and_(relation.c.package_id == package["id"],
        ~sa.exists(sa.select(next_row.c.id).where(next_row.c.supersedes_id == relation.c.id))),
        limit=contract.MAX_DEPENDENCIES, budget=budget)
    expected = {row["dependency_id"]: row for row in inventory["dependencies"]}
    require(len(rows) == len(expected) and {row["dependency_id"] for row in rows} == set(expected),
            "distribution_complete_permissions_required")
    rights = await fetch_rows(db, "evidence_artifacts", {str(row["rights_artifact_id"]) for row in rows})
    found = {row["row_id"]: row for row in rights}
    for row in rows:
        require(row["decision"] == "allow" and row["scope"] == SCOPE)
        envelope = found.get(str(row["rights_artifact_id"]))
        require(envelope is not None and envelope["row_sha256"] == row["rights_row_sha256"])
        data = envelope["data"]
        document = rights_review_payload(package, expected[row["dependency_id"]], row["license_code"], row["basis_code"])
        require(_canonical(data) == row["rights_projection_json"] and data["metadata"] == {"distribution_rights": document}
                and data["schema_version"] == RIGHTS_VERSION and data["kind"] == "review" and data["hash_status"] == "verified"
                and _sha(document) == data["record_sha256"] == data["bytes_sha256"]
                == row["rights_record_sha256"] == row["rights_bytes_sha256"])
    grants = sorted({(row["actor_user_id"], row["actor_grant_id"], "reviewer") for row in rows})
    for start in range(0, len(grants), 1000):
        await check_grant_inventory(db, grants[start:start + 1000])
    return sorted(({"dependency_id": row["dependency_id"], "permission_id": str(row["id"]),
                    "permission_sha256": row["record_sha256"]} for row in rows), key=lambda item: item["dependency_id"])


async def review_distribution(db, *, actor_user_id, request_key, package_id, expected_inventory_sha256,
                              disclosure_approved, reason_code, dry_run=True):
    require(type(disclosure_approved) is bool)
    reason_code, request_key = _code(reason_code), _key(request_key)
    expected_inventory_sha256 = contract._hash(expected_inventory_sha256)
    async with _write(db, dry_run) as operation:
        actor = await _actor(db, actor_user_id, request_key, "reviewer")
        package, inventory = await _package(db, package_id)
        require(package["inventory_sha256"] == expected_inventory_sha256 and package["actor_user_id"] != actor["actor_user_id"])
        permissions = []
        if disclosure_approved:
            await active_grant(db, package["actor_user_id"], role="curator", grant_id=package["actor_grant_id"])
            await _current_sources(db, inventory)
            permissions = await _permissions(db, package, inventory)
        values = {**actor, "package_id": package["id"], "inventory_sha256": expected_inventory_sha256,
            "permission_manifest": _canonical(permissions), "permission_manifest_sha256": _sha(permissions),
            "disclosure_approved": disclosure_approved, "scientific_acceptance": False,
            "ml_training_approved": False, "reason_code": reason_code}
        row = await _existing(db, "reviews", values) or await _insert(db, "reviews", values, operation)
        result = _report(row, dry_run, operation)
    return result


async def _review_permissions(db, package, inventory, review, *, budget=None):
    require(review["package_id"] == package["id"] and review["inventory_sha256"] == package["inventory_sha256"]
        and review["disclosure_approved"] is True and review["scientific_acceptance"] is False
        and review["ml_training_approved"] is False and review["actor_user_id"] != package["actor_user_id"])
    permissions = await _permissions(db, package, inventory, budget=budget)
    require(_sha(permissions) == review["permission_manifest_sha256"] and _canonical(permissions) == review["permission_manifest"],
            "distribution_review_permissions_changed")


async def distribution_action(db, *, actor_user_id, request_key, package_id, review_id,
                               expected_inventory_sha256, kind, reason_code, dry_run=True):
    require(type(kind) is str and kind in {"publish", "withdraw"})
    reason_code, request_key = _code(reason_code), _key(request_key)
    expected_inventory_sha256 = contract._hash(expected_inventory_sha256)
    async with _write(db, dry_run) as operation:
        actor = await _actor(db, actor_user_id, request_key, "publisher")
        package, inventory = await _package(db, package_id)
        review = await _get(db, "reviews", review_id)
        require(package["inventory_sha256"] == expected_inventory_sha256 and review["package_id"] == package["id"]
            and review["inventory_sha256"] == expected_inventory_sha256 and review["disclosure_approved"] is True
            and len({actor["actor_user_id"], package["actor_user_id"], review["actor_user_id"]}) == 3)
        if kind == "publish":
            await check_grant_inventory(db, [(package["actor_user_id"], package["actor_grant_id"], "curator"),
                                            (review["actor_user_id"], review["actor_grant_id"], "reviewer")])
            await _current_sources(db, inventory)
            await _review_permissions(db, package, inventory, review)
            reviews = table(PREFIX + "reviews")
            require(not (await db.execute(sa.select(reviews.c.id).where(reviews.c.package_id == package["id"],
                reviews.c.disclosure_approved.is_(False)).limit(1))).first(), "distribution_negative_review_hold")
        values = {**actor, "package_id": package["id"], "review_id": review["id"],
                  "inventory_sha256": expected_inventory_sha256, "kind": kind, "reason_code": reason_code}
        row = await _existing(db, "actions", values) or await _insert(db, "actions", values, operation)
        result = _report(row, dry_run, operation)
    return result


async def admitted_distribution(db, package_id, *, budget=None):
    """One snapshot, no cache; every positive control is revalidated live."""
    await _read_session(db)
    package, inventory = await _package(db, package_id, budget=budget)
    actions = table(PREFIX + "actions")
    rows = await _history(db, "actions", actions.c.package_id == package["id"], limit=2, budget=budget)
    require(len(rows) == 1 and rows[0]["kind"] == "publish", "distribution_not_published")
    action = rows[0]
    require(action["inventory_sha256"] == package["inventory_sha256"])
    reviews = table(PREFIX + "reviews")
    require(not (await db.execute(sa.select(reviews.c.id).where(reviews.c.package_id == package["id"],
        reviews.c.disclosure_approved.is_(False)).limit(1))).first(), "distribution_negative_review_hold")
    review = await _get(db, "reviews", action["review_id"], budget=budget)
    require(len({package["actor_user_id"], review["actor_user_id"], action["actor_user_id"]}) == 3)
    await check_grant_inventory(db, [(package["actor_user_id"], package["actor_grant_id"], "curator"),
        (review["actor_user_id"], review["actor_grant_id"], "reviewer"),
        (action["actor_user_id"], action["actor_grant_id"], "publisher")])
    await _current_sources(db, inventory)
    await _review_permissions(db, package, inventory, review, budget=budget)
    return {"package_id": str(package["id"]), "release_id": package["release_id"],
            "release_sha256": package["release_manifest_sha256"], "bundle_sha256": package["public_bundle_sha256"],
            "inventory_sha256": package["inventory_sha256"], "package_sha256": package["record_sha256"],
            "review_sha256": review["record_sha256"], "publication_sha256": action["record_sha256"]}


@dataclass(frozen=True)
class DistributionAccessReceipt:
    purpose: str
    pins: tuple[tuple[str, str, str], ...]
    admitted_release_ids: tuple[str, ...]
    revision_sha256: str


def _pins(pins, purpose):
    require(type(purpose) is str and purpose in {"catalog", "page", "detail", "download"})
    require(type(pins) is list and len(pins) <= 128)
    result = []
    for pin in pins:
        require(type(pin) is dict and set(pin) == {"release_id", "release_sha256", "bundle_sha256"})
        identifier = pin["release_id"]
        require(type(identifier) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", identifier)
                and identifier not in {".", ".."})
        result.append((identifier, contract._hash(pin["release_sha256"]), contract._hash(pin["bundle_sha256"])))
    require(len({pin[0] for pin in result}) == len(result))
    return tuple(sorted(result))


_HELD = (ResearchDistributionError, ResearchAccessDenied, publication.PublicationUnavailable,
         ResearchFreezeError, capsule.ResearchReleaseVerificationError, SourceLifecycleError)


async def _observe(db, pins, purpose):
    admitted, budget = [], {}
    if pins:
        packages, actions = table(PREFIX + "packages"), table(PREFIX + "actions")
        withdrawn = actions.alias("withdrawn")
        # Only published candidates are scanned. Missing/pending IDs never
        # appear in the catalogue or its approval fingerprint.
        rows = (await db.execute(sa.select(packages.c.id, packages.c.release_id,
            packages.c.release_manifest_sha256, packages.c.public_bundle_sha256).join(actions,
                actions.c.package_id == packages.c.id).where(actions.c.kind == "publish",
            sa.tuple_(packages.c.release_id, packages.c.release_manifest_sha256, packages.c.public_bundle_sha256).in_(pins),
            ~sa.exists(sa.select(withdrawn.c.id).where(withdrawn.c.package_id == packages.c.id,
                                                    withdrawn.c.kind == "withdraw"))).limit(257))).all()
        if len(rows) > 256:
            raise DistributionRegistryUnavailable("distribution_inventory_limit")
        grouped = defaultdict(list)
        for row in rows:
            grouped[(row.release_id, row.release_manifest_sha256, row.public_bundle_sha256)].append(row.id)
        for pin in pins:
            identifiers = grouped.get(pin, [])
            if len(identifiers) != 1:
                continue  # ambiguous is not resolved by recency or score
            try:
                value = await admitted_distribution(db, identifiers[0], budget=budget)
                require((value["release_id"], value["release_sha256"], value["bundle_sha256"]) == pin)
                admitted.append(value)
            except _HELD:
                continue
    return DistributionAccessReceipt(purpose, pins, tuple(row["release_id"] for row in admitted), _sha(admitted))


async def prepare_rps_distribution_access(*, pins, purpose):
    """Observe a dedicated bounded read-only snapshot for this HTTP request."""
    try:
        pinned = _pins(pins, purpose)  # private immutable capture before await
        async with asyncio.timeout(25):
            async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as db:
                async with db.begin():
                    await db.execute(sa.text("SET TRANSACTION READ ONLY"))
                    await db.execute(sa.text("SET LOCAL statement_timeout = '5000ms'"))
                    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                    return await _observe(db, pinned, purpose)
    except (SQLAlchemyError, TimeoutError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise DistributionRegistryUnavailable("distribution_registry_unavailable") from None


async def recheck_rps_distribution_access(receipt):
    if type(receipt) is not DistributionAccessReceipt:
        raise DistributionRegistryUnavailable("distribution_receipt_unavailable")
    current = await prepare_rps_distribution_access(pins=[{"release_id": item[0], "release_sha256": item[1],
        "bundle_sha256": item[2]} for item in receipt.pins], purpose=receipt.purpose)
    if current != receipt:
        raise DistributionAdmissionChanged("distribution_admission_changed")
