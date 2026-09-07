"""Bounded immutable retrieval lineage over current SQL chunks.

No source text is retained in history, no scientific/permission approval is
created, and caller-owned transactions are never committed. Ingestion uses
the same pure row builder inside its paper/chunk replacement transaction.
"""
from __future__ import annotations

import hashlib
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from models.db import Base
from services.rag_evidence_contract import (
    VERSION,
    build_revision_rows,
    canonical,
    validate_candidate,
    validate_evidence_descriptor,
)

CURRENT_FACT_RENDERER_VERSION = "sclib-fact-renderer/2.0.0"
MAX_CHUNKS = 300


class RagEvidenceError(ValueError):
    """A current exact bounded lineage binding could not be established."""


def _ids(chunks):
    if type(chunks) not in {list, tuple} or len(chunks) > MAX_CHUNKS:
        raise RagEvidenceError("At most 300 explicit chunks are supported")
    result = []
    for chunk in chunks:
        identifier = chunk if isinstance(chunk, str) else _get(chunk, "id")
        if type(identifier) is not str or not 1 <= len(identifier) <= 200:
            raise RagEvidenceError("An exact bounded chunk identifier is required")
        result.append(identifier)
    return result


def _get(value, key):
    return value.get(key) if isinstance(value, dict) or isinstance(value, sa.engine.RowMapping) else getattr(value, key, None)


async def _clean_lock(db):
    if db.new or db.dirty or db.deleted:
        raise RagEvidenceError("A clean caller-owned session is required")
    await db.execute(sa.text("SELECT public.sclib_research_integrity_lock_v1()"))


async def _chunk(db, chunk_id):
    _ids([chunk_id])
    size = await db.scalar(sa.text("SELECT octet_length(text)+octet_length(materials_mentioned::text) FROM chunks WHERE id=:id"), {"id": chunk_id})
    if size is None or size > 1024 * 1024:
        raise RagEvidenceError("Current chunk is missing or exceeds the input limit")
    row = (await db.execute(sa.text("""SELECT c.*, public.sclib_rag_chunk_hash_v1(to_jsonb(c)) AS binding_sha256,
        public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p)) AS source_sha256
        FROM chunks c JOIN papers p ON p.id=c.paper_id WHERE c.id=:id"""), {"id": chunk_id})).mappings().one()
    return row


async def _insert_or_verify(db, name, values):
    table = Base.metadata.tables[name]
    supplied = {key: UUID(value) if value is not None and isinstance(table.c[key].type, sa.Uuid) else value
                for key, value in values.items()}
    inserted = (await db.execute(insert(table).values(**supplied).on_conflict_do_nothing().returning(table))).mappings().one_or_none()
    if inserted is not None:
        return inserted, True
    existing = (await db.execute(sa.select(table).where(table.c.id == supplied["id"]))).mappings().one_or_none()
    if existing is None or any(existing[key] != value for key, value in supplied.items()):
        raise RagEvidenceError("Immutable evidence identity/content conflict")
    return existing, False


async def _bind(db, chunk_id, evidence_revision_id):
    table = Base.metadata.tables["chunk_evidence_current"]
    current = await db.scalar(sa.select(table.c.evidence_revision_id).where(table.c.chunk_id == chunk_id))
    if current == evidence_revision_id:
        # Recheck actual source/content even on an otherwise no-op replay.
        evidence = Base.metadata.tables["rag_evidence_revisions"]
        row = (await db.execute(sa.select(evidence).where(evidence.c.id == current))).mappings().one()
        chunk = await _chunk(db, chunk_id)
        if row["chunk_binding_sha256"] != chunk["binding_sha256"] or row["source_snapshot_sha256"] != chunk["source_sha256"]:
            raise RagEvidenceError("The existing evidence pointer is stale")
        return False
    await db.execute(insert(table).values(chunk_id=chunk_id, evidence_revision_id=evidence_revision_id)
        .on_conflict_do_update(index_elements=[table.c.chunk_id], set_={"evidence_revision_id": evidence_revision_id}))
    return True


async def register_chunk_evidence(db, *, chunk_id, candidate, bind=True, dry_run=True):
    """Append actual extraction/evidence rows and optionally bind the live chunk.

    A derived parent must equal one current materials_mentioned record. The
    caller cannot manufacture a canonical result ID or supply trusted hashes.
    Dry runs roll back this operation's savepoint, not unrelated caller work.
    """
    if type(dry_run) is not bool or type(bind) is not bool:
        raise RagEvidenceError("Explicit boolean dry_run/bind required")
    selected = validate_candidate(candidate)
    if db.new or db.dirty or db.deleted:
        raise RagEvidenceError("A clean caller-owned session is required")
    transaction = await db.begin_nested()
    try:
        await _clean_lock(db)
        chunk = await _chunk(db, chunk_id)
        if selected["chunk_kind"] == "derived_fact" and not any(
                canonical(selected["parent_record"]) == canonical(record)
                for record in chunk["materials_mentioned"] if type(record) is dict):
            raise RagEvidenceError("Derived parent must equal an actual current chunk result record")
        rows = build_revision_rows(paper_id=chunk["paper_id"], chunk_id=chunk_id, chunk_text=chunk["text"],
            chunk_binding_sha256=chunk["binding_sha256"], source_snapshot_sha256=chunk["source_sha256"], candidate=selected)
        parent, parent_inserted = (await _insert_or_verify(db, "rag_extraction_revisions", rows["extraction"])) if rows["extraction"] else (None, False)
        evidence, evidence_inserted = await _insert_or_verify(db, "rag_evidence_revisions", rows["evidence"])
        pointer_changed = await _bind(db, chunk_id, evidence["id"]) if bind else False
        result = {"version": VERSION, "dry_run": dry_run, "committed": False,
                  "evidence_revision_id": str(evidence["id"]), "evidence_record_sha256": evidence["record_sha256"],
                  "parent_result_revision_id": str(parent["id"]) if parent else None,
                  "scientific_acceptance": False, "permission_granted": False}
        if dry_run or not (parent_inserted or evidence_inserted or pointer_changed):
            # A verified replay must not persist the shared epoch increments
            # used to fence its reads or run INSERT conflict guards.
            await transaction.rollback()
        else:
            await transaction.commit()
        return result
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise


async def bind_chunk_evidence(db, *, chunk_id, evidence_revision_id, dry_run=True):
    if type(dry_run) is not bool:
        raise RagEvidenceError("Explicit boolean dry_run required")
    _ids([chunk_id])
    identifier = UUID(str(evidence_revision_id))
    if db.new or db.dirty or db.deleted:
        raise RagEvidenceError("A clean caller-owned session is required")
    transaction = await db.begin_nested()
    try:
        await _clean_lock(db)
        changed = await _bind(db, chunk_id, identifier)
        if dry_run or not changed:
            await transaction.rollback()
        else:
            await transaction.commit()
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise


def _legacy(chunk):
    text = _get(chunk, "text") or ""
    return {"version": VERSION, "chunk_kind": "legacy_unknown", "evidence_revision_id": None,
            "evidence_record_sha256": None, "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "parent_result_revision_id": None, "parent_result_sha256": None, "extraction_version": None,
            "rendering_version": None, "source_capture_id": None, "source_locator": {},
            "root_status": "unresolved", "permission_status": "unresolved", "currentness": "unresolved",
            "warning_codes": ["legacy_evidence_unresolved"], "support_eligible": False,
            "independent_evidence": False, "scientific_acceptance": False}


async def resolve_chunk_evidence(db, chunks, *, rendering_version=None):
    """Read bounded sanitized descriptors; never return raw parent or text.

    No lineage in this schema can establish independent support or permission.
    A matching current pointer records reproducibility, not scientific truth.
    """
    ids = _ids(chunks)
    if not ids:
        return {}
    supplied = dict(zip(ids, chunks, strict=True))
    results = {identifier: _legacy(chunk) for identifier, chunk in supplied.items()}
    for descriptor in results.values():
        descriptor.update(currentness="stale", warning_codes=["current_chunk_unavailable"])
    sizes = (await db.execute(sa.text("SELECT id,octet_length(text)+octet_length(materials_mentioned::text) AS bytes "
        "FROM chunks WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)), {"ids": ids})).mappings().all()
    if sum(row["bytes"] for row in sizes) > 8 * 1024 * 1024:
        raise RagEvidenceError("Combined current chunk byte limit exceeded")
    statement = sa.text("""SELECT c.id, c.paper_id, c.text, c.materials_mentioned,
        public.sclib_rag_chunk_hash_v1(to_jsonb(c)) AS live_binding,
        public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p)) AS live_source,
        to_jsonb(e) AS evidence, to_jsonb(x) AS parent,
        link.evidence_revision_id IS NOT NULL AS has_current_pointer,
        EXISTS(SELECT 1 FROM rag_evidence_revisions previous WHERE previous.chunk_key=c.id
          AND previous.permission_status='restricted') AS historically_restricted,
        e.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(e)) AS evidence_intact,
        x.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(x)) AS parent_intact
        FROM chunks c JOIN papers p ON p.id=c.paper_id
        LEFT JOIN chunk_evidence_current link ON link.chunk_id=c.id
        LEFT JOIN LATERAL (SELECT id FROM rag_evidence_revisions history WHERE history.chunk_key=c.id
          ORDER BY history.created_at DESC,history.id DESC LIMIT 1) prior ON link.evidence_revision_id IS NULL
        LEFT JOIN rag_evidence_revisions e ON e.id=COALESCE(link.evidence_revision_id,prior.id)
        LEFT JOIN rag_extraction_revisions x ON x.id=e.parent_extraction_revision_id
        WHERE c.id IN :ids AND octet_length(c.text)+octet_length(c.materials_mentioned::text)<=1048576
        """).bindparams(sa.bindparam("ids", expanding=True))
    rows = (await db.execute(statement, {"ids": ids})).mappings().all()
    for row in rows:
        expected = supplied[row["id"]]
        evidence, parent = row["evidence"], row["parent"]
        if evidence is None:
            descriptor = _legacy(dict(row))
            if not isinstance(expected, str) and any(_get(expected, key) != row[key] for key in ("paper_id", "text", "materials_mentioned")):
                descriptor.update(currentness="stale", warning_codes=["selected_chunk_changed"])
            results[row["id"]] = descriptor
            continue
        permission = "restricted" if row["historically_restricted"] else evidence["permission_status"]
        warnings = ["original_root_unresolved", "source_permission_" + permission]
        stale = False
        if row["has_current_pointer"] is not True:
            warnings.append("current_pointer_invalidated")
            stale = True
        if row["evidence_intact"] is not True or parent is not None and row["parent_intact"] is not True:
            warnings.append("evidence_integrity_mismatch")
            stale = True
        if row["live_binding"] != evidence["chunk_binding_sha256"]:
            warnings.append("chunk_content_changed")
            stale = True
        if not isinstance(expected, str) and any(_get(expected, key) != row[key] for key in ("paper_id", "text", "materials_mentioned")):
            warnings.append("selected_chunk_changed")
            stale = True
        if row["live_source"] != evidence["source_snapshot_sha256"]:
            warnings.append("source_snapshot_changed")
            stale = True
        if evidence["chunk_kind"] == "derived_fact" and evidence["rendering_version"] != (rendering_version or CURRENT_FACT_RENDERER_VERSION):
            warnings.append("renderer_version_changed")
            stale = True
        descriptor = {"version": VERSION, "chunk_kind": evidence["chunk_kind"],
            "evidence_revision_id": evidence["id"], "evidence_record_sha256": evidence["record_sha256"],
            "content_sha256": evidence["content_sha256"], "parent_result_revision_id": parent["id"] if parent else None,
            "parent_result_sha256": parent["record_sha256"] if parent else None,
            "extraction_version": evidence["extraction_version"], "rendering_version": evidence["rendering_version"],
            "source_capture_id": evidence["source_capture_id"], "source_locator": evidence["source_locator"],
            "root_status": "unresolved", "permission_status": permission,
            "currentness": "stale" if stale else "current", "warning_codes": sorted(warnings),
            "support_eligible": False, "independent_evidence": False, "scientific_acceptance": False}
        results[row["id"]] = validate_evidence_descriptor(descriptor)
    return results
