"""Internal integrity capsules over existing research rows; never ML approval.

Callers own dedicated SERIALIZABLE transactions and the outer commit. Actual
artifact bytes and a separately registered review are required. No provider,
filesystem, canonical scientific promotion, or public endpoint is involved.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from uuid import UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from models.db import Base
from services import research_release_manifest as contract
from services.research_release_spec import SPEC

VERSION = "research-freeze-service/1.0.0"
NOTICE_REVIEW_VERSION = "research-release-notice-review/1.0.0"
_NAMESPACE = UUID("8495705b-a968-4fc4-bb43-5d4b7486e709")


class ResearchFreezeError(ValueError):
    """A complete reviewed integrity capsule cannot be produced."""


def _id(value):
    return UUID(str(value))


def _capture_artifact_bytes(artifact_bytes):
    if type(artifact_bytes) is not dict or len(artifact_bytes) > 200:
        raise ResearchFreezeError("artifact byte inventory limit or shape")
    total = 0
    for key, payload in artifact_bytes.items():
        if (type(key) is not str or re.fullmatch(r"[0-9a-f]{64}", key) is None
                or type(payload) is not bytes or len(payload) > 8 * 1024 * 1024):
            raise ResearchFreezeError("artifact byte inventory limit or shape")
        total += len(payload)
        if total > 64 * 1024 * 1024:
            raise ResearchFreezeError("combined artifact byte limit")
    return dict(artifact_bytes)


def _inputs(dataset_id, policy_artifact_ids, source_roots, artifact_bytes):
    """Bound and privately capture caller containers before any async boundary."""
    if type(policy_artifact_ids) is not list or not 2 <= len(policy_artifact_ids) <= 20:
        raise ResearchFreezeError("two to twenty explicit policy artifact roots required")
    if type(source_roots) is not list or len(source_roots) > 1000:
        raise ResearchFreezeError("source root limit or shape")
    roots = []
    for root in source_roots:
        if (type(root) is not dict or set(root) != {"table", "row_id"}
                or root["table"] not in contract.SOURCE_ROOT_TABLES):
            raise ResearchFreezeError("unsupported source root")
        roots.append({"table": root["table"], "row_id": str(_id(root["row_id"]))})
    return {"dataset_id": str(_id(dataset_id)),
            "policy_artifact_ids": [str(_id(value)) for value in policy_artifact_ids],
            "source_roots": roots, "artifact_bytes": _capture_artifact_bytes(artifact_bytes)}


def _key_column(name):
    return "paper_id" if name == "paper_work_map" else "id"


def _row(name, data):
    return {"table": name, "row_id": str(data[_key_column(name)]),
            "data": data, "row_sha256": contract.digest(data)}


async def _session(db):
    if db.new or db.dirty or db.deleted:
        raise ResearchFreezeError("a clean dedicated session is required")
    isolation = (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one()
    if isolation != "serializable":
        raise ResearchFreezeError("SERIALIZABLE isolation and caller-owned commit are required")


async def _guard(db):
    # Same database-owned guard used by direct SQL dependency writers. Its epoch
    # write also invalidates stale higher-isolation snapshots; a lock alone does not.
    from models.research_release_v1 import LOCK_FUNCTION
    await db.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))


async def _fetch(db, name, *, column=None, identifiers, byte_budget=None):
    if name not in SPEC:
        raise ResearchFreezeError("unsupported closure table")
    if not identifiers:
        return []
    table = Base.metadata.tables[name]
    field = table.c[column or _key_column(name)]
    # Cast supplied IDs, not the indexed key. All allowed keys are UUID or text.
    values = [_id(value) for value in identifiers] if isinstance(field.type, sa.UUID) else list(identifiers)
    body = sa.func.to_jsonb(table.table_valued())
    # Check expanded wire sizes, not TOAST/compressed storage sizes, before
    # transmitting or deserializing source JSON. This bounds client memory,
    # not the database CPU needed to inspect an oversized legacy object.
    sizes = (await db.execute(sa.select(table.c[_key_column(name)],
        sa.func.octet_length(sa.cast(body, sa.Text))).where(field.in_(values)).limit(1001))).all()
    if len(sizes) > 1000:
        raise ResearchFreezeError("closure row limit exceeded")
    budget = byte_budget if byte_budget is not None else {}
    additions = {}
    for identifier, size in sizes:
        if size > 8 * 1024 * 1024:
            raise ResearchFreezeError("closure row byte limit exceeded")
        additions[(name, str(identifier))] = size
    if sum({**budget, **additions}.values()) > 8 * 1024 * 1024:
        raise ResearchFreezeError("combined closure row byte limit exceeded")
    budget.update(additions)
    statement = sa.select(body).where(field.in_(values)).limit(1001)
    data = (await db.execute(statement)).scalars().all()
    if len(data) != len(sizes):
        raise ResearchFreezeError("closure row capture changed")
    return [_row(name, item) for item in data]


async def _collect(db, *, dataset_id, policy_artifact_ids, source_roots, review_artifact_id=None):
    """Enumerate declared FKs and every current owned child under the writer guard."""
    roots = [("ml_dataset_snapshots", str(_id(dataset_id)))]
    roots.extend(("evidence_artifacts", str(_id(value))) for value in policy_artifact_ids)
    roots.extend((item["table"], item["row_id"]) for item in source_roots)
    if review_artifact_id is not None:
        roots.append(("evidence_artifacts", str(_id(review_artifact_id))))
    pending, collected, expanded, byte_budget = set(roots), {}, set(), {}
    while pending:
        requested = pending - collected.keys()
        if len(requested) + len(collected) > 1000:
            raise ResearchFreezeError("closure row limit exceeded")
        grouped = defaultdict(set)
        for name, identifier in requested:
            grouped[name].add(identifier)
        for name, identifiers in sorted(grouped.items()):
            rows = await _fetch(db, name, identifiers=identifiers, byte_budget=byte_budget)
            if {row["row_id"] for row in rows} != identifiers:
                raise ResearchFreezeError("closure reference missing from current database")
            for row in rows:
                collected[(row["table"], row["row_id"])] = row
        current = pending - expanded
        owners = defaultdict(set)
        for name, identifier in current:
            owners[name].add(identifier)
        # Child discovery is DB-derived; a supplied root/row inventory cannot
        # omit an existing example, feature, result, or evidence sibling.
        owned = []
        for owner_table, identifiers in sorted(owners.items()):
            for name, column in contract.owned_relations(owner_table):
                owned.extend(await _fetch(db, name, column=column, identifiers=identifiers, byte_budget=byte_budget))
        for row in owned:
            key = (row["table"], row["row_id"])
            if key not in collected:
                collected[key] = row
        if len(collected) > 1000 or sum(row["table"] == "ml_examples" for row in collected.values()) > 100:
            raise ResearchFreezeError("bounded dataset closure exceeded")
        pending = set()
        for key in current:
            row = collected[key]
            pending.update(contract.dependencies(row["table"], row["data"]))
        # Newly discovered owned rows also own children. Process their IDs once
        # through the same queue rather than treating them as already expanded.
        pending.update((row["table"], row["row_id"]) for row in owned)
        expanded.update(current)
        pending -= expanded
    return sorted(collected.values(), key=lambda row: (row["table"], row["row_id"]))


async def _manifest(db, *, dataset_id, policy_artifact_ids, source_roots, artifact_bytes,
                    review_artifact_id=None):
    rows = await _collect(db, dataset_id=dataset_id, policy_artifact_ids=policy_artifact_ids,
                          source_roots=source_roots, review_artifact_id=review_artifact_id)
    return contract.build_manifest(dataset_id=str(_id(dataset_id)), rows=rows,
        policy_artifact_ids=[str(_id(value)) for value in policy_artifact_ids],
        source_roots=source_roots,
        review_artifact_id=str(_id(review_artifact_id)) if review_artifact_id else None,
        artifact_bytes=artifact_bytes)


async def preview_research_release(db, *, dataset_id, policy_artifact_ids, source_roots, artifact_bytes):
    """Read a coherent preview and roll back even the temporary guard epoch."""
    parameters = _inputs(dataset_id, policy_artifact_ids, source_roots, artifact_bytes)
    await _session(db)
    transaction = await db.begin_nested()
    try:
        await _guard(db)
        manifest = await _manifest(db, **parameters)
        return {"version": VERSION, "manifest": manifest, "preview_sha256": contract.digest(manifest),
                "database_mutated": False, "scientific_acceptance": False,
                "public_release": False, "ml_training_approved": False}
    finally:
        if transaction.is_active:
            await transaction.rollback()


async def _stored(db, name, identifier):
    table = Base.metadata.tables[name]
    size = (await db.execute(sa.select(sa.func.octet_length(sa.cast(
        sa.func.to_jsonb(table.table_valued()), sa.Text))).where(table.c.id == _id(identifier)))).scalar_one_or_none()
    if size is not None and size > 9 * 1024 * 1024:
        raise ResearchFreezeError("stored release row byte limit exceeded")
    return (await db.execute(sa.select(table).where(table.c.id == _id(identifier)))).mappings().one_or_none()


async def _verify_pins(db, release):
    table = Base.metadata.tables["research_release_pins"]
    count, size = (await db.execute(sa.select(sa.func.count(), sa.func.coalesce(sa.func.sum(
        sa.func.octet_length(sa.cast(table.c.row_data, sa.Text))), 0)).where(table.c.release_id == release["id"]))).one()
    if count > 1000 or size > 8 * 1024 * 1024:
        raise ResearchFreezeError("stored release pin budget exceeded")
    pins = (await db.execute(sa.select(table).where(table.c.release_id == release["id"]).limit(1001))).mappings().all()
    rows = sorted(({"table": row["table_name"], "row_id": row["row_id"], "data": row["row_data"],
                    "row_sha256": row["row_sha256"]} for row in pins), key=lambda row: (row["table"], row["row_id"]))
    if contract.digest(rows) != contract.digest(release["manifest"]["rows"]):
        raise ResearchFreezeError("stored release membership integrity mismatch")
    if contract.digest(release["manifest"]) != release["manifest_sha256"]:
        raise ResearchFreezeError("stored release manifest integrity mismatch")


def _bundle_hash(manifest):
    return contract.digest({"manifest_sha256": contract.digest(manifest), "artifacts": manifest["artifacts"]})


async def freeze_research_release(db, *, dataset_id, policy_artifact_ids, source_roots,
                                  artifact_bytes, review_artifact_id, dry_run=True):
    """Atomically pin an independently reviewed capsule; never commit the caller."""
    if type(dry_run) is not bool:
        raise ResearchFreezeError("dry_run must be Boolean")
    parameters = _inputs(dataset_id, policy_artifact_ids, source_roots, artifact_bytes)
    review_artifact_id = str(_id(review_artifact_id))
    await _session(db)
    transaction = await db.begin_nested()
    try:
        await _guard(db)
        manifest = await _manifest(db, **parameters, review_artifact_id=review_artifact_id)
        contract.verify_manifest(manifest, artifact_bytes=parameters["artifact_bytes"])
        manifest_hash = contract.digest(manifest)
        identifier = uuid5(_NAMESPACE, "release:" + manifest_hash)
        release = await _stored(db, "research_releases", identifier)
        inserted = release is None
        if inserted:
            table = Base.metadata.tables["research_releases"]
            await db.execute(insert(table).values(id=identifier, dataset_snapshot_id=_id(parameters["dataset_id"]),
                manifest=manifest, manifest_sha256=manifest_hash, bundle_sha256=_bundle_hash(manifest),
                closure_policy_version=manifest["closure_policy_version"], scientific_acceptance=False,
                public_release=False))
            pins = Base.metadata.tables["research_release_pins"]
            for row in manifest["rows"]:
                await db.execute(insert(pins).values(id=uuid5(identifier, row["table"] + ":" + row["row_id"]),
                    release_id=identifier, table_name=row["table"], row_id=row["row_id"],
                    row_data=row["data"], row_sha256=row["row_sha256"]))
            release = await _stored(db, "research_releases", identifier)
        if release["bundle_sha256"] != _bundle_hash(manifest):
            raise ResearchFreezeError("stored release bundle integrity mismatch")
        await _verify_pins(db, release)
        # Exercise deferred completeness even in rollback rehearsals. Caller
        # must not mix unrelated writes into this dedicated transaction.
        await db.execute(sa.text("SET CONSTRAINTS rf54_complete IMMEDIATE"))
        await db.execute(sa.text("SET CONSTRAINTS rf54_complete DEFERRED"))
        report = {"version": VERSION, "release_id": str(identifier), "manifest_sha256": manifest_hash,
            "bundle_sha256": release["bundle_sha256"], "manifest": manifest,
            "rows_pinned": len(manifest["rows"]), "rows_inserted": len(manifest["rows"]) + 1 if inserted else 0,
            "replayed": not inserted, "dry_run": dry_run, "committed": False,
            "scientific_acceptance": False, "public_release": False, "ml_training_approved": False}
        if dry_run:
            await transaction.rollback()
        else:
            await transaction.commit()
        return report
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise


async def inspect_research_release(db, *, release_id, expected_manifest_sha256, artifact_bytes):
    """Verify pinned historical bytes/rows, not current scientific admissibility."""
    release_id = str(_id(release_id))
    # Reuse the same bounded byte-only capture without acquiring a write lock.
    captured = _capture_artifact_bytes(artifact_bytes)
    release = await _stored(db, "research_releases", release_id)
    if release is None or release["manifest_sha256"] != expected_manifest_sha256:
        raise ResearchFreezeError("exact retained release required")
    contract.verify_manifest(release["manifest"], artifact_bytes=captured,
                             expected_manifest_sha256=expected_manifest_sha256)
    await _verify_pins(db, release)
    if release["bundle_sha256"] != _bundle_hash(release["manifest"]):
        raise ResearchFreezeError("stored release bundle integrity mismatch")
    notices_table = Base.metadata.tables["research_release_notices"]
    notices = (await db.execute(sa.select(notices_table).where(
        notices_table.c.release_id == _id(release_id)).order_by(notices_table.c.created_at, notices_table.c.id).limit(1001)))
    notices = [dict(row) for row in notices.mappings().all()]
    if len(notices) > 1000:
        raise ResearchFreezeError("notice history exceeds bounded inspection")
    for notice in notices:
        successor = await _stored(db, "research_releases", notice["successor_release_id"]) if notice["successor_release_id"] else None
        document = notice_review_payload(release_id=release_id, manifest_sha256=release["manifest_sha256"],
            kind=notice["kind"], reason_code=notice["reason_code"], successor_release_id=notice["successor_release_id"],
            successor_manifest_sha256=successor["manifest_sha256"] if successor else None)
        record = {key: str(notice[key]) if key.endswith("_id") and notice[key] is not None else notice[key]
                  for key in ("release_id", "kind", "successor_release_id", "review_artifact_id",
                              "review_artifact_kind", "review_sha256", "reason_code")}
        artifacts = await _fetch(db, "evidence_artifacts", identifiers=[str(notice["review_artifact_id"])])
        artifact = artifacts[0]["data"] if artifacts else None
        if (contract.digest(record) != notice["record_sha256"] or artifact is None
                or artifact["kind"] != "review" or artifact["schema_version"] != NOTICE_REVIEW_VERSION
                or artifact["hash_status"] != "verified" or artifact["record_sha256"] != notice["review_sha256"]
                or artifact["record_sha256"] != contract.digest(document)
                or artifact["bytes_sha256"] != hashlib.sha256(contract.canonical(document)).hexdigest()
                or contract.digest(artifact["metadata"].get("release_notice_review")) != contract.digest(document)):
            raise ResearchFreezeError("retained notice review binding invalid")
        notice["review_document_binding_verified"] = True
        notice["external_review_bytes_rechecked"] = False
        notice["reviewer_authority_authenticated"] = False
    return {"version": VERSION, "release_id": str(release_id), "manifest": release["manifest"],
            "manifest_sha256": expected_manifest_sha256, "notices": notices,
            "current_eligibility_reassessed": False, "scientific_acceptance": False,
            "public_release": False, "ml_training_approved": False}


def notice_review_payload(*, release_id, manifest_sha256, kind, reason_code,
                          successor_release_id=None, successor_manifest_sha256=None):
    """Exact independent-review document; constructing it grants no authority."""
    if kind not in {"superseded", "withdrawn", "correction"}:
        raise ResearchFreezeError("unsupported release notice kind")
    if (type(reason_code) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,159}", reason_code) is None
            or (kind == "superseded" and successor_release_id is None)
            or (kind == "withdrawn" and successor_release_id is not None)):
        raise ResearchFreezeError("invalid notice reason or successor")
    if bool(successor_release_id) != bool(successor_manifest_sha256):
        raise ResearchFreezeError("exact successor manifest binding required")
    if successor_release_id is not None and _id(successor_release_id) == _id(release_id):
        raise ResearchFreezeError("release cannot supersede itself")
    return {"version": NOTICE_REVIEW_VERSION, "release_id": str(_id(release_id)),
            "manifest_sha256": manifest_sha256, "kind": kind, "reason_code": reason_code,
            "successor_release_id": str(_id(successor_release_id)) if successor_release_id else None,
            "successor_manifest_sha256": successor_manifest_sha256,
            "restricted_internal_notice_approved": True, "scientific_acceptance": False,
            "public_release_approved": False}


async def append_release_notice(db, *, release_id, kind, reason_code, review_artifact_id,
                                review_bytes, successor_release_id=None, dry_run=True):
    """Append a reviewed historical notice, without rewriting or propagating it."""
    if type(dry_run) is not bool or type(review_bytes) is not bytes or len(review_bytes) > 1024 * 1024:
        raise ResearchFreezeError("bounded review bytes and Boolean dry_run required")
    release_id, review_artifact_id = str(_id(release_id)), str(_id(review_artifact_id))
    successor_release_id = str(_id(successor_release_id)) if successor_release_id else None
    if type(kind) is not str or type(reason_code) is not str:
        raise ResearchFreezeError("notice kind and reason must be immutable text")
    await _session(db)
    transaction = await db.begin_nested()
    try:
        await _guard(db)
        release = await _stored(db, "research_releases", release_id)
        successor = await _stored(db, "research_releases", successor_release_id) if successor_release_id else None
        if release is None or (successor_release_id and successor is None):
            raise ResearchFreezeError("release or successor missing")
        document = notice_review_payload(release_id=release_id, manifest_sha256=release["manifest_sha256"],
            kind=kind, reason_code=reason_code, successor_release_id=successor_release_id,
            successor_manifest_sha256=successor["manifest_sha256"] if successor else None)
        artifacts = await _fetch(db, "evidence_artifacts", identifiers=[str(_id(review_artifact_id))])
        artifact = artifacts[0]["data"] if artifacts else None
        if (artifact is None or artifact["kind"] != "review" or artifact["schema_version"] != NOTICE_REVIEW_VERSION
                or artifact["hash_status"] != "verified" or artifact["record_sha256"] != contract.digest(document)
                or artifact["bytes_sha256"] != hashlib.sha256(review_bytes).hexdigest()
                or review_bytes != contract.canonical(document)
                or contract.digest(artifact["metadata"].get("release_notice_review")) != contract.digest(document)):
            raise ResearchFreezeError("exact independently registered notice review required")
        record = {"release_id": str(_id(release_id)), "kind": kind,
                  "successor_release_id": str(_id(successor_release_id)) if successor_release_id else None,
                  "review_artifact_id": str(_id(review_artifact_id)), "review_artifact_kind": "review",
                  "review_sha256": artifact["record_sha256"], "reason_code": reason_code}
        record_hash = contract.digest(record)
        identifier = uuid5(_NAMESPACE, "notice:" + record_hash)
        existing = await _stored(db, "research_release_notices", identifier)
        if existing is None:
            values = {**record, "id": identifier, "record_sha256": record_hash}
            for field in ("release_id", "successor_release_id", "review_artifact_id"):
                values[field] = _id(values[field]) if values[field] else None
            await db.execute(insert(Base.metadata.tables["research_release_notices"]).values(**values))
        else:
            body = {key: str(existing[key]) if key.endswith("_id") and existing[key] is not None
                    else existing[key] for key in record}
            if contract.digest(body) != record_hash or existing["record_sha256"] != record_hash:
                raise ResearchFreezeError("immutable notice content mismatch")
        if dry_run:
            await transaction.rollback()
        else:
            await transaction.commit()
        return {"notice_id": str(identifier), "replayed": existing is not None, "dry_run": dry_run,
                "committed": False, "public_release": False, "downstream_propagation_performed": False}
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise
