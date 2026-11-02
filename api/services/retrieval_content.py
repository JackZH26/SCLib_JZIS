"""Bounded content/publication construction; callers own commit and activation.

No provider RPC, live pointer update or text/vector duplication occurs here.
The source universe and every sealed partition remain immutable on replay.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid5

import sqlalchemy as sa

from models.db import Base
from models.index_generations_v1 import PROFILE
from models.retrieval_content_v2 import TABLE_ORDER

NAMESPACE = UUID("9afdfbdd-855d-44fc-b6d9-063ad8c79771")
REFERENCE_FIELDS = {"vector_id", "origin_kind", "origin_generation_id", "native_revision_id"}


class RetrievalContentError(ValueError):
    """A complete immutable content/publication binding is unavailable."""


def _identity(kind, values):
    return uuid5(NAMESPACE, json.dumps([kind, values], sort_keys=True, separators=(",", ":"), default=str))


def _table(name):
    if name not in TABLE_ORDER:
        raise RetrievalContentError("Unknown content history relation")
    return Base.metadata.tables[name]


async def _existing(db, name, keys):
    table = _table(name)
    predicates = [table.c[key] == value for key, value in keys.items()]
    result = (await db.execute(sa.select(table).where(*predicates))).mappings().one_or_none()
    if result is not None:
        valid = await db.scalar(sa.select(table.c.record_sha256 ==
            sa.func.sclib_retrieval_record_hash_v2(sa.func.to_jsonb(table.table_valued()))).where(*predicates))
        if valid is not True:
            raise RetrievalContentError("Retained content history integrity mismatch")
        return dict(result)
    return None


async def _put(db, name, keys, values):
    prior = await _existing(db, name, keys)
    if prior is not None:
        if any(prior[key] != value for key, value in values.items()):
            raise RetrievalContentError("Immutable content identity conflict")
        return prior
    await db.execute(_table(name).insert().values(**keys, **values))
    return await _existing(db, name, keys)


@asynccontextmanager
async def _preview(db, dry_run):
    if type(dry_run) is not bool or db.new or db.dirty or db.deleted:
        raise RetrievalContentError("Flush caller changes and choose explicit preview/apply mode")
    transaction = await db.begin_nested()
    try:
        yield
        await (transaction.rollback() if dry_run else transaction.commit())
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise


async def seal_native_publication(db, *, paper_id, native_revision_ids, dry_run=True):
    """Seal all current chunks of a paper, using real captured revision IDs.

    The database refuses omissions, duplicate chunk keys, stale snapshots and
    old current-evidence links. Synthetic fixtures are not provider evidence.
    """
    if type(native_revision_ids) is not list or not 1 <= len(native_revision_ids) <= 1000:
        raise RetrievalContentError("A native publication requires 1..1000 revisions")
    identifiers = sorted({UUID(str(value)) for value in native_revision_ids})
    if len(identifiers) != len(native_revision_ids):
        raise RetrievalContentError("Duplicate native publication revision")
    identifier = _identity("native-publication/2", [paper_id, identifiers])
    async with _preview(db, dry_run):
        await _put(db, TABLE_ORDER[0], {"id": identifier}, {
            "paper_id": paper_id, "expected_member_count": len(identifiers), "profile": PROFILE})
        for revision in identifiers:
            await _put(db, TABLE_ORDER[1], {"publication_id": identifier, "native_revision_id": revision}, {})
        sealed = await _put(db, TABLE_ORDER[2], {"publication_id": identifier}, {})
    return {"publication_id": str(identifier), "manifest_sha256": sealed["manifest_sha256"],
            "record_sha256": sealed["record_sha256"], "member_count": sealed["member_count"],
            "dry_run": dry_run, "committed": False, "active_pointer_changed": False}


async def stage_legacy_content(db, *, generation_id, dry_run=True):
    generation_id = UUID(str(generation_id))
    row = (await db.execute(sa.text("SELECT logical_index,manifest_sha256,profile,expected_member_count "
        "FROM index_generations WHERE id=:id"), {"id": generation_id})).mappings().one_or_none()
    if row is None:
        raise RetrievalContentError("Legacy source generation unavailable")
    identifier = _identity("legacy-content/2", [generation_id, row["manifest_sha256"]])
    async with _preview(db, dry_run):
        result = await _put(db, TABLE_ORDER[3], {"id": identifier}, {
            "logical_index": row["logical_index"], "source_generation_id": generation_id,
            "base_content_id": None, "profile": row["profile"], "expected_member_count": row["expected_member_count"]})
    return {"content_id": str(identifier), "expected_member_count": result["expected_member_count"],
            "record_sha256": result["record_sha256"], "dry_run": dry_run, "committed": False}


async def stage_native_content(db, *, base_content_id, publication_ids, dry_run=True):
    if type(publication_ids) is not list or not 1 <= len(publication_ids) <= 1000:
        raise RetrievalContentError("A native batch requires 1..1000 sealed paper publications")
    base_id = UUID(str(base_content_id))
    identifiers = sorted({UUID(str(value)) for value in publication_ids})
    if len(identifiers) != len(publication_ids):
        raise RetrievalContentError("Duplicate publication identity")
    async with _preview(db, dry_run):
        base = await _existing(db, TABLE_ORDER[3], {"id": base_id})
        base_seal = await _existing(db, TABLE_ORDER[7], {"content_id": base_id})
        if base is None or base_seal is None:
            raise RetrievalContentError("An immutable sealed base content is required")
        publications = []
        for identifier in identifiers:
            event = await _existing(db, TABLE_ORDER[0], {"id": identifier})
            seal = await _existing(db, TABLE_ORDER[2], {"publication_id": identifier})
            if event is None or seal is None:
                raise RetrievalContentError("An immutable sealed publication is required")
            publications.append((event, seal))
        paper_ids = [event["paper_id"] for event, _ in publications]
        if len(set(paper_ids)) != len(paper_ids):
            raise RetrievalContentError("Choose one complete revision per paper in a content batch")
        members = _table(TABLE_ORDER[5])
        retained = await db.scalar(sa.select(sa.func.count()).select_from(members).where(
            members.c.content_id == base_id, members.c.paper_id.not_in(paper_ids)))
        expected = retained + sum(seal["member_count"] for _, seal in publications)
        identifier = _identity("native-content/2", [base_id, base_seal["record_sha256"],
            [(event["id"], seal["record_sha256"]) for event, seal in publications]])
        await _put(db, TABLE_ORDER[3], {"id": identifier}, {
            "logical_index": base["logical_index"], "source_generation_id": None,
            "base_content_id": base_id, "profile": base["profile"], "expected_member_count": expected})
        for event, _ in publications:
            await _put(db, TABLE_ORDER[4], {"content_id": identifier, "paper_id": event["paper_id"]},
                       {"publication_id": event["id"]})
    return {"content_id": str(identifier), "expected_member_count": expected, "dry_run": dry_run, "committed": False}


async def source_reference_page(db, *, content_id, after="", limit=1000):
    """Keyset enumerate the complete allowed universe without loading texts."""
    if type(limit) is not int or not 1 <= limit <= 1000 or type(after) is not str or len(after) > 120:
        raise RetrievalContentError("Invalid bounded source page")
    identifier = UUID(str(content_id))
    source = await _existing(db, TABLE_ORDER[3], {"id": identifier})
    if source is None:
        raise RetrievalContentError("Content plan unavailable")
    if source["source_generation_id"] is not None:
        sql = """SELECT vector_id,'legacy_v1' AS origin_kind,generation_id AS origin_generation_id,
          NULL::uuid AS native_revision_id FROM index_generation_members WHERE generation_id=:source
          AND vector_id COLLATE "C">:after ORDER BY vector_id COLLATE "C" LIMIT :limit"""
        parameters = {"source": source["source_generation_id"], "after": after, "limit": limit}
    else:
        sql = """SELECT vector_id,origin_kind,origin_generation_id,native_revision_id FROM (
          SELECT base.vector_id,base.origin_kind,base.origin_generation_id,base.native_revision_id
          FROM retrieval_content_members_v2 base WHERE base.content_id=:source AND NOT EXISTS(
            SELECT 1 FROM retrieval_content_changes_v2 change WHERE change.content_id=:content AND change.paper_id=base.paper_id)
          UNION ALL SELECT m.vector_id,'native_v2',NULL::uuid,m.native_revision_id
          FROM retrieval_content_changes_v2 change JOIN retrieval_publication_members_v2 m USING(publication_id)
          WHERE change.content_id=:content) universe WHERE vector_id COLLATE "C">:after
          ORDER BY vector_id COLLATE "C" LIMIT :limit"""
        parameters = {"source": source["base_content_id"], "content": identifier, "after": after, "limit": limit}
    return [dict(row) for row in (await db.execute(sa.text(sql), parameters)).mappings()]


async def append_content_partition(db, *, content_id, partition_id, references, dry_run=True):
    if (type(partition_id) is not int or partition_id < 0 or type(references) is not list
            or not 1 <= len(references) <= 1000
            or any(type(row) is not dict or set(row) != REFERENCE_FIELDS
                or type(row["vector_id"]) is not str or not 1 <= len(row["vector_id"]) <= 120
                or row["origin_kind"] not in {"legacy_v1", "native_v2"} for row in references)):
        raise RetrievalContentError("An exact bounded partition reference inventory is required")
    identifier = UUID(str(content_id))
    if len({row["vector_id"] for row in references}) != len(references):
        raise RetrievalContentError("Duplicate partition member identity")
    async with _preview(db, dry_run):
        # One parent lock freezes the plan before a batched insert. Enumerate
        # this <=1000-row partition once; do not issue millions of per-member
        # Python round trips when importing the full retained corpus.
        await db.execute(sa.select(_table(TABLE_ORDER[3]).c.id).where(
            _table(TABLE_ORDER[3]).c.id == identifier).with_for_update())
        table = _table(TABLE_ORDER[5])
        rows = (await db.execute(sa.select(table, (table.c.record_sha256 ==
            sa.func.sclib_retrieval_record_hash_v2(sa.func.to_jsonb(table.table_valued()))).label("intact"))
            .where(table.c.content_id == identifier, table.c.partition_id == partition_id))).mappings().all()
        existing = {row["vector_id"]: row for row in rows}
        if len(rows) > 1000 or not set(existing) <= {row["vector_id"] for row in references}:
            raise RetrievalContentError("Partition replay omitted existing members")
        missing = []
        for row in references:
            values = dict(row)
            for key in ("origin_generation_id", "native_revision_id"):
                values[key] = UUID(str(values[key])) if values[key] is not None else None
            vector = values.pop("vector_id")
            prior = existing.get(vector)
            if prior is not None:
                if prior["intact"] is not True or any(prior[key] != value for key, value in values.items()):
                    raise RetrievalContentError("Immutable partition identity conflict")
            else:
                missing.append({"content_id": identifier, "vector_id": vector,
                                "partition_id": partition_id, **values})
        if missing:
            await db.execute(table.insert(), missing)
        sealed = await _put(db, TABLE_ORDER[6], {"content_id": identifier, "partition_id": partition_id}, {})
        if sealed["member_count"] != len(references):
            raise RetrievalContentError("Partition replay omitted existing members")
    return {"content_id": str(identifier), "partition_id": partition_id, "member_count": sealed["member_count"],
            "manifest_sha256": sealed["manifest_sha256"], "dry_run": dry_run, "committed": False}


async def seal_content(db, *, content_id, dry_run=True):
    identifier = UUID(str(content_id))
    async with _preview(db, dry_run):
        sealed = await _put(db, TABLE_ORDER[7], {"content_id": identifier}, {})
    return {"content_id": str(identifier), "manifest_sha256": sealed["manifest_sha256"],
            "member_count": sealed["member_count"], "partition_count": sealed["partition_count"],
            "dry_run": dry_run, "committed": False, "active_pointer_changed": False}
