"""Atomic private new-source intake and exact pending expression successors."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid5

import sqlalchemy as sa

from models.db import Base
from models.source_expression_intake_v2 import LOCK_FUNCTION, TABLE_ORDER
from services import source_expression_contract_v2 as contract
from services import source_expression_contract_v2_1 as literal_contract
from services import source_expression_contract_v2_2 as table_contract
from services.research_release_manifest import canonical, digest
from services.source_property_pending import (
    SourcePropertyConflict,
    SourcePropertyNotFound,
    _body,
    _grant,
    _insert,
    _session,
    checksum,
    identifier,
    reader,
    request_key,
    require,
)

VERSION = "source-expression-intake/2.0.0"
LITERAL_VERSION = "source-expression-intake/2.1.0"
TABLE_VERSION = "source-expression-intake/2.2.0"
MAX_EXPRESSION_PAGE_SIZE = 8
NAMESPACE = UUID("0a0e56cd-a9bf-4c29-b85a-85293a2fcb38")


def profile_contract(profile=None):
    choices = {None: contract, literal_contract.PROFILE: literal_contract, table_contract.PROFILE: table_contract}
    require(profile is None or type(profile) is str, "source_expression_profile_required")
    require(profile in choices, "source_expression_profile_required")
    return choices[profile]


def package_contract(package):
    require(type(package) is dict, "source_expression_package_required")
    version = package.get("version")
    choices = {item.VERSION: item for item in (contract, literal_contract, table_contract)}
    require(type(version) is str and version in choices, "supported_package_version_required")
    return choices[version]


def intake_version(selected):
    return {contract: VERSION, literal_contract: LITERAL_VERSION, table_contract: TABLE_VERSION}[selected]


def _stable(*parts):
    return uuid5(NAMESPACE, digest([str(value) for value in parts]))


def _table(index):
    return Base.metadata.tables[TABLE_ORDER[index]]


@asynccontextmanager
async def _write(db, dry_run):
    require(type(dry_run) is bool, "boolean_preview_required")
    await _session(db, write=True)
    savepoint = await db.begin_nested()
    changed = {"value": False}
    try:
        await db.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
        yield changed
        await db.execute(sa.text("SET CONSTRAINTS se83_complete IMMEDIATE"))
        await db.execute(sa.text("SET CONSTRAINTS se83_complete DEFERRED"))
        if dry_run or not changed["value"]:
            await savepoint.rollback()
        else:
            await savepoint.commit()
    except BaseException:
        if savepoint.is_active:
            await savepoint.rollback()
        raise


async def capabilities(db, *, actor_user_id, profile=None):
    selected = profile_contract(profile)
    _, session = await reader(db, actor_user_id)
    from services.research_access import ResearchAccessDenied

    try:
        grant, _ = await _grant(db, actor_user_id, "curator")
    except ResearchAccessDenied:
        grant = None
    return {
        "version": intake_version(selected),
        "package_version": selected.VERSION,
        "actor_user_id": str(identifier(actor_user_id)),
        "session_version": session,
        "can_import": grant is not None,
        "curator_grant_id": None if grant is None else str(grant["id"]),
        "registry_sha256": selected.REGISTRY_SHA256,
        "field_profiles": dict(selected.FIELDS),
        "max_source_bytes": contract.MAX_TEXT_BYTES,
        "max_expressions": contract.MAX_EXPRESSIONS,
        "max_package_bytes": contract.MAX_PACKAGE_BYTES,
        "max_projection_bytes": contract.MAX_PROJECTION_BYTES,
        "max_expression_page_size": MAX_EXPRESSION_PAGE_SIZE,
        "scope": "private_pending_source_expressions",
        "scientific_acceptance": False,
        "canonical_promotions": 0,
        "public_content_release": False,
    }


def _receipt(row, *, replayed=False, dry_run=False):
    _intact(row)
    selected = package_contract(json.loads(row["package_json"]))
    version = intake_version(selected)
    request_body = {"version": version, "package_sha256": row["package_sha256"]}
    preview_body = {
        "version": version,
        "request_key": row["request_key"],
        "request_sha256": row["request_sha256"],
        "actor": _body(
            {key: row[key] for key in ("actor_user_id", "actor_grant_id", "actor_session_version")}
        ),
        "manifest": row["expression_manifest"],
    }
    return {
        "version": version,
        "receipt_id": str(row["id"]),
        "receipt_sha256": row["record_sha256"],
        "actor_user_id": str(row["actor_user_id"]),
        "actor_grant_id": str(row["actor_grant_id"]),
        "actor_session_version": row["actor_session_version"],
        "request_key": row["request_key"],
        "request_sha256": row["request_sha256"],
        "preview_sha256": row["preview_sha256"],
        "capture_id": str(row["capture_id"]),
        "package_sha256": row["package_sha256"],
        "package_canonical_json": row["package_json"],
        "request_canonical_json": canonical(request_body).decode(),
        "preview_canonical_json": canonical(preview_body).decode(),
        "receipt_canonical_json": canonical(_body(row)).decode(),
        "expression_count": row["expression_count"],
        "expression_manifest": row["expression_manifest"],
        "count_scope": "source_expression_revisions_not_independent_experiments",
        "replayed": replayed,
        "dry_run": dry_run,
        "pending_ledger_written": not dry_run,
        "status": "pending",
        "scientific_acceptance": False,
        "canonical_promotions": 0,
        "selected_result_association": "unestablished",
        "public_content_release": False,
    }


async def import_package(
    db, *, actor_user_id, request_key_value, package, dry_run=True, expected_preview_sha256=None
):
    key = request_key(request_key_value)
    selected = package_contract(package)
    prepared = selected.compile_package(package)
    version = intake_version(selected)
    req_hash = digest({"version": version, "package_sha256": prepared.package_sha256})
    async with _write(db, dry_run) as changed:
        grant, session = await _grant(db, actor_user_id, "curator")
        old = (
            (
                await db.execute(
                    sa.select(_table(1)).where(
                        _table(1).c.actor_user_id == identifier(actor_user_id),
                        _table(1).c.request_key == key,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if old is not None:
            if old["request_sha256"] != req_hash or expected_preview_sha256 not in {
                None,
                old["preview_sha256"],
            }:
                raise SourcePropertyConflict("source_expression_request_conflict")
            return _receipt(old, replayed=True)
        if await db.scalar(
            sa.select(sa.exists().where(_table(1).c.package_sha256 == prepared.package_sha256))
        ):
            raise SourcePropertyConflict("source_expression_package_already_imported")
        heads, manifest = [], []
        for index, (projection, entry) in enumerate(
            zip(prepared.projections, prepared.package["expressions"], strict=True)
        ):
            head = (
                (
                    await db.execute(
                        sa.select(_table(2))
                        .where(_table(2).c.expression_key == projection["expression_key"])
                        .order_by(_table(2).c.revision_number.desc())
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
            pin = (
                None
                if head is None
                else {
                    "revision_id": str(head["id"]),
                    "record_sha256": head["record_sha256"],
                    "revision_number": head["revision_number"],
                }
            )
            if entry["predecessor"] != pin:
                raise SourcePropertyConflict("source_expression_exact_current_head_required")
            heads.append(head)
            manifest.append(
                {
                    "entry_index": index,
                    "expression_key": projection["expression_key"],
                    "entry_sha256": digest(entry),
                    "projection_sha256": digest(projection),
                    "predecessor_id": None if head is None else str(head["id"]),
                    "predecessor_sha256": None if head is None else head["record_sha256"],
                    "revision_number": 1 if head is None else head["revision_number"] + 1,
                }
            )
        actor = {
            "actor_user_id": identifier(actor_user_id),
            "actor_grant_id": grant["id"],
            "actor_session_version": session,
        }
        preview = digest(
            {
                "version": version,
                "request_key": key,
                "request_sha256": req_hash,
                "actor": _body(actor),
                "manifest": manifest,
            }
        )
        if not dry_run and expected_preview_sha256 != preview:
            raise SourcePropertyConflict("source_expression_exact_preview_required")
        metadata_hash = digest(prepared.package["source"])
        capture = (
            (
                await db.execute(
                    sa.select(_table(0)).where(
                        _table(0).c.metadata_sha256 == metadata_hash,
                        _table(0).c.source_content_sha256
                        == prepared.package["source_content_sha256"],
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if capture is None:
            capture = await _insert(
                db,
                TABLE_ORDER[0],
                {
                    "id": _stable(
                        "capture", metadata_hash, prepared.package["source_content_sha256"]
                    ),
                    **actor,
                    "source_id": prepared.package["source"]["source_id"],
                    "source_content_sha256": prepared.package["source_content_sha256"],
                    "metadata_sha256": metadata_hash,
                    "source_text": prepared.source_text,
                    "source_metadata": prepared.package["source"],
                    "declared_currentness": prepared.package["source"]["currentness"],
                },
            )
        receipt_id = _stable("import", actor_user_id, key)
        receipt = await _insert(
            db,
            TABLE_ORDER[1],
            {
                "id": receipt_id,
                **actor,
                "request_key": key,
                "request_sha256": req_hash,
                "preview_sha256": preview,
                "capture_id": capture["id"],
                "package_json": canonical(prepared.package).decode(),
                "package_sha256": prepared.package_sha256,
                "expression_count": len(prepared.projections),
                "expression_manifest": manifest,
            },
        )
        for index, (projection, head) in enumerate(zip(prepared.projections, heads, strict=True)):
            m = manifest[index]
            await _insert(
                db,
                TABLE_ORDER[2],
                {
                    "id": _stable("revision", receipt_id, index),
                    **actor,
                    "import_receipt_id": receipt_id,
                    "import_receipt_sha256": receipt["record_sha256"],
                    "capture_id": capture["id"],
                    "entry_index": index,
                    "entry_sha256": m["entry_sha256"],
                    "expression_key": projection["expression_key"],
                    "field_id": projection["field_id"],
                    "revision_number": m["revision_number"],
                    "predecessor_id": None if head is None else head["id"],
                    "predecessor_sha256": m["predecessor_sha256"],
                    "projection_json": canonical(projection).decode(),
                    "projection_sha256": m["projection_sha256"],
                },
            )
        changed["value"] = True
        return _receipt(receipt, dry_run=dry_run)


async def outcome(db, *, actor_user_id, request_key_value, expected_request_sha256):
    await _session(db, write=False)
    await _grant(db, actor_user_id, "curator")
    row = (
        (
            await db.execute(
                sa.select(_table(1)).where(
                    _table(1).c.actor_user_id == identifier(actor_user_id),
                    _table(1).c.request_key == request_key(request_key_value),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise SourcePropertyNotFound("source_expression_outcome_unknown")
    if row["request_sha256"] != checksum(expected_request_sha256):
        raise SourcePropertyConflict("source_expression_request_pin_conflict")
    return _receipt(row, replayed=True)


def _intact(row):
    require(
        digest(_body(row)) == row["record_sha256"], "source_expression_record_integrity_unavailable"
    )


async def _capture_dto(db, row):
    _intact(row)
    contract.source_metadata(row["source_metadata"])
    require(
        digest(row["source_metadata"]) == row["metadata_sha256"],
        "source_expression_metadata_integrity_unavailable",
    )
    import hashlib

    require(
        hashlib.sha256(row["source_text"].encode()).hexdigest() == row["source_content_sha256"],
        "source_expression_content_integrity_unavailable",
    )
    latest = await db.scalar(
        sa.select(_table(0).c.id)
        .where(_table(0).c.source_id == row["source_id"])
        .order_by(_table(0).c.created_at.desc(), _table(0).c.id.desc())
        .limit(1)
    )
    return {
        "id": str(row["id"]),
        "record_sha256": row["record_sha256"],
        "source": row["source_metadata"],
        "source_metadata_canonical_json": canonical(row["source_metadata"]).decode(),
        "source_content_sha256": row["source_content_sha256"],
        "metadata_sha256": row["metadata_sha256"],
        "retained_utf8_bytes": len(row["source_text"].encode()),
        "fragment_integrity": "server_verified_retained_bytes",
        "parent_integrity": "declared_not_verified",
        "publication_revision_verified": False,
        "rights_verified": False,
        "publication_currentness_verified": False,
        "latest_retained_capture_for_source": latest == row["id"],
        "public_content_release": False,
    }


def _bounds(offset, limit, *, maximum=50):
    require(
        type(offset) is int
        and 0 <= offset <= 10000
        and type(limit) is int
        and 1 <= limit <= maximum,
        "bounded_pagination_required",
    )


async def captures(db, *, actor_user_id, offset=0, limit=25, currentness=None):
    await reader(db, actor_user_id)
    _bounds(offset, limit)
    filters = []
    if currentness is not None:
        require(
            currentness in {"unresolved", "declared_current", "historical"},
            "declared_currentness_filter_required",
        )
        filters.append(_table(0).c.declared_currentness == currentness)
    total = await db.scalar(sa.select(sa.func.count()).select_from(_table(0)).where(*filters))
    rows = (
        (
            await db.execute(
                sa.select(_table(0))
                .where(*filters)
                .order_by(_table(0).c.created_at, _table(0).c.id)
                .offset(offset)
                .limit(limit)
            )
        )
        .mappings()
        .all()
    )
    return {
        "version": VERSION,
        "total": total,
        "offset": offset,
        "limit": limit,
        "count_scope": "retained_source_fragments_not_publications_or_experiments",
        "captures": [await _capture_dto(db, row) for row in rows],
    }


async def capture(db, *, actor_user_id, capture_id):
    await reader(db, actor_user_id)
    row = (
        (await db.execute(sa.select(_table(0)).where(_table(0).c.id == identifier(capture_id))))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise SourcePropertyNotFound("source_expression_capture_unavailable")
    return {"version": VERSION, **await _capture_dto(db, row)}


async def _expression_dto(db, row, *, include_receipt=False):
    _intact(row)
    source = (
        (await db.execute(sa.select(_table(0)).where(_table(0).c.id == row["capture_id"])))
        .mappings()
        .one()
    )
    receipt = (
        (await db.execute(sa.select(_table(1)).where(_table(1).c.id == row["import_receipt_id"])))
        .mappings()
        .one()
    )
    _intact(receipt)
    require(
        row["import_receipt_sha256"] == receipt["record_sha256"],
        "source_expression_receipt_integrity_unavailable",
    )
    package = json.loads(receipt["package_json"])
    selected = package_contract(package)
    entry = package["expressions"][row["entry_index"]]
    expected = selected.project(source["source_metadata"], source["source_text"], entry)
    require(
        digest(entry) == row["entry_sha256"]
        and digest(expected) == row["projection_sha256"]
        and canonical(expected).decode() == row["projection_json"],
        "source_expression_projection_integrity_unavailable",
    )
    head = await db.scalar(
        sa.select(_table(2).c.id)
        .where(_table(2).c.expression_key == row["expression_key"])
        .order_by(_table(2).c.revision_number.desc())
        .limit(1)
    )
    return {
        "id": str(row["id"]),
        "record_sha256": row["record_sha256"],
        "expression_key": row["expression_key"],
        "revision_canonical_json": canonical(_body(row)).decode(),
        "entry_index": row["entry_index"],
        "source_entry_sha256": row["entry_sha256"],
        "import_receipt_id": str(row["import_receipt_id"]),
        "import_receipt_sha256": row["import_receipt_sha256"],
        "import_receipt": _receipt(receipt) if include_receipt else None,
        "revision_number": row["revision_number"],
        "predecessor_id": None if row["predecessor_id"] is None else str(row["predecessor_id"]),
        "predecessor_sha256": row["predecessor_sha256"],
        "projection_sha256": row["projection_sha256"],
        "projection_canonical_json": row["projection_json"],
        "projection": expected,
        "source_entry": entry,
        "is_expression_head": row["id"] == head,
        "capture": await _capture_dto(db, source),
    }


async def expressions(
    db, *, actor_user_id, offset=0, limit=8, source_id=None, field_id=None, currentness=None, profile=None
):
    selected = profile_contract(profile)
    await reader(db, actor_user_id)
    _bounds(offset, limit, maximum=MAX_EXPRESSION_PAGE_SIZE)
    table, older = _table(2), _table(2).alias("newer")
    filters = [table.c.field_id.in_(tuple(selected.FIELDS)),
        sa.cast(table.c.projection_json, sa.JSON)["profile"].as_string().is_not_distinct_from(getattr(selected, "PROFILE", None)),
        ~sa.exists(
            sa.select(1).where(
                older.c.expression_key == table.c.expression_key,
                older.c.revision_number > table.c.revision_number,
            )
        )
    ]
    if field_id is not None:
        require(field_id in selected.FIELDS, "closed_field_filter_required")
        filters.append(table.c.field_id == field_id)
    if source_id is not None:
        contract.text(source_id)
        filters.append(_table(0).c.source_id == source_id)
    if currentness is not None:
        require(
            currentness in {"unresolved", "declared_current", "historical"},
            "declared_currentness_filter_required",
        )
        filters.append(_table(0).c.declared_currentness == currentness)
    query = sa.select(table).join(_table(0), table.c.capture_id == _table(0).c.id).where(*filters)
    total = await db.scalar(sa.select(sa.func.count()).select_from(query.subquery()))
    rows = (
        (await db.execute(query.order_by(table.c.expression_key).offset(offset).limit(limit)))
        .mappings()
        .all()
    )
    return {
        "version": intake_version(selected),
        "total": total,
        "offset": offset,
        "limit": limit,
        "count_scope": "current_pending_expression_heads_not_experiments_or_verified_properties",
        "expressions": [await _expression_dto(db, row) for row in rows],
        "scientific_acceptance": False,
        "canonical_promotions": 0,
    }


async def expression(db, *, actor_user_id, revision_id, profile=None):
    selected = profile_contract(profile)
    await reader(db, actor_user_id)
    row = (
        (await db.execute(sa.select(_table(2)).where(_table(2).c.id == identifier(revision_id))))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise SourcePropertyNotFound("source_expression_revision_unavailable")
    require(row["field_id"] in selected.FIELDS
            and json.loads(row["projection_json"]).get("profile") == getattr(selected, "PROFILE", None),
            "source_expression_profile_mismatch")
    return {"version": intake_version(selected), **await _expression_dto(db, row, include_receipt=True)}
