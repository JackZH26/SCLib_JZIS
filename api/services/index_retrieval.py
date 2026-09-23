"""Generation-pinned reads of immutable retrieval inputs, never rights grants.

The mutable Chunk table remains a legacy lexical surface. An ANN result must
resolve through its exact active-generation member and all three content/vector
bindings before it can influence rank or expose text.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from config import get_settings
from models.db import Chunk, Paper
from services.rag_evidence_contract import VERSION, validate_evidence_descriptor
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import source_visibility

MAX_HYDRATE = 1000
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024


class IndexRetrievalError(ValueError):
    """A complete pinned retrieval selection could not be established."""


def pin_sha256(pin):
    if type(pin) is not dict:
        raise IndexRetrievalError("An explicit generation pin is required")
    try:
        payload = json.dumps(pin, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise IndexRetrievalError("Invalid generation pin") from exc
    if len(payload.encode()) > 16384:
        raise IndexRetrievalError("Generation pin exceeds its size limit")
    return hashlib.sha256(payload.encode()).hexdigest()


async def load_pin(db):
    from services.index_generations import load_active_generation
    return await load_active_generation(db, logical_index=get_settings().retrieval_logical_index)


async def require_current_pin(db, pin):
    current = await load_pin(db)
    if current is None or pin_sha256(current) != pin_sha256(pin):
        raise IndexRetrievalError("Active retrieval generation changed")


def _ids(values):
    if type(values) not in {list, tuple} or len(values) > MAX_HYDRATE:
        raise IndexRetrievalError("Retrieval member inventory exceeds its limit")
    if any(type(value) is not str or not 1 <= len(value) <= 200 for value in values):
        raise IndexRetrievalError("Invalid retrieval member identity")
    return sorted(set(values))


async def _members(db, pin, identifiers):
    from services.index_generations import load_generation_members
    ids = _ids(identifiers)
    if not ids:
        return []
    members = await load_generation_members(db, generation_id=pin["generation_id"], vector_ids=ids)
    if (type(members) is not list or len(members) > len(ids)
            or len({member["vector_id"] for member in members}) != len(members)
            or any(str(member["generation_id"]) != str(pin["generation_id"])
                   or member["vector_id"] not in ids for member in members)):
        raise IndexRetrievalError("Generation member inventory mismatch")
    size = sum(len(json.dumps({"chunk": member["snapshot_json"], "paper": member["paper_snapshot_json"]},
        ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()) for member in members)
    if size > MAX_SNAPSHOT_BYTES:
        raise IndexRetrievalError("Retrieval snapshot byte budget exceeded")
    return members


async def verified_vector_hits(db, pin, neighbors):
    """Drop unknown IDs; a known member's mismatched hashes reject the ANN set."""
    if type(neighbors) not in {list, tuple} or len(neighbors) > MAX_HYDRATE:
        raise IndexRetrievalError("ANN result inventory exceeds its limit")
    identifiers = [getattr(item, "vector_id", None) for item in neighbors]
    _ids(identifiers)
    if len(set(identifiers)) != len(identifiers):
        raise IndexRetrievalError("Duplicate ANN member identity")
    members = {member["vector_id"]: member for member in await _members(db, pin, identifiers)}
    result = []
    for neighbor in neighbors:
        member = members.get(neighbor.vector_id)
        if member is None:
            continue
        if any(getattr(neighbor, name, None) != member[name]
               for name in ("content_sha256", "vector_sha256", "chunk_revision_sha256")):
            raise IndexRetrievalError("ANN payload does not match its immutable member")
        if (type(neighbor.distance) not in {int, float} or not math.isfinite(neighbor.distance)
                or not 0 <= neighbor.distance <= 2):
            raise IndexRetrievalError("ANN distance is invalid")
        result.append((neighbor.vector_id, 1.0 - neighbor.distance))
    return result


@dataclass(frozen=True, slots=True)
class GenerationChunk:
    id: str
    paper_id: str
    title: str | None
    section: str | None
    chunk_index: int | None
    text: str
    materials_mentioned: list
    has_equation: bool
    has_table: bool
    paper: Paper
    member: dict
    generation_pin: dict


def attribution(chunk):
    """Frozen bibliographic/results fields; current Paper is only a live overlay."""
    if not isinstance(chunk, GenerationChunk):
        return chunk.paper
    fields = dict(chunk.member["paper_snapshot_json"])
    for name in ("date_submitted", "date_published"):
        if fields.get(name) is not None:
            fields[name] = date.fromisoformat(fields[name])
    fields.setdefault("citation_count", 0)
    fields.setdefault("material_family", None)
    return SimpleNamespace(**fields)


async def hydrate(db, pin, identifiers):
    ids = _ids(identifiers)
    if not ids:
        return {}
    if pin is None:
        rows = (await db.execute(sa.select(Chunk).options(selectinload(Chunk.paper)).where(Chunk.id.in_(ids)))).scalars().all()
        return {row.id: row for row in rows}
    members = await _members(db, pin, ids)
    paper_ids = {member["paper_id"] for member in members}
    if not paper_ids:
        return {}
    sizes = (await db.execute(sa.select(Paper.id, sa.func.octet_length(sa.cast(
        sa.func.to_jsonb(Paper.__table__.table_valued()), sa.Text))).where(Paper.id.in_(paper_ids)))).all()
    if {identifier for identifier, _ in sizes} != paper_ids or sum(size for _, size in sizes) > MAX_SNAPSHOT_BYTES:
        raise IndexRetrievalError("Current source inventory unavailable or oversized")
    papers = {paper.id: paper for paper in (await db.execute(sa.select(Paper).where(Paper.id.in_(paper_ids))
                                                            .execution_options(populate_existing=True))).scalars().all()}
    result = {}
    for member in members:
        snapshot = member["snapshot_json"]
        if (snapshot.get("paper_id") != member["paper_id"] or member["paper_snapshot_json"].get("id") != member["paper_id"]
                or type(snapshot.get("text")) is not str or type(snapshot.get("materials_mentioned")) is not list):
            raise IndexRetrievalError("Malformed generation snapshot")
        result[member["vector_id"]] = GenerationChunk(
            id=member["vector_id"], paper_id=member["paper_id"], title=snapshot.get("title"),
            section=snapshot.get("section"), chunk_index=snapshot.get("chunk_index"), text=snapshot["text"],
            materials_mentioned=snapshot["materials_mentioned"], has_equation=bool(snapshot.get("has_equation")),
            has_table=bool(snapshot.get("has_table")), paper=papers[member["paper_id"]], member=member,
            generation_pin=pin,
        )
    return result


async def paper_chunks(db, pin, paper_id, *, limit=20):
    if pin is None:
        rows = (await db.execute(sa.select(Chunk).options(selectinload(Chunk.paper)).where(Chunk.paper_id == paper_id)
                                .order_by(Chunk.id).limit(limit))).scalars().all()
        return list(rows)
    statement = sa.text("SELECT vector_id FROM index_generation_members WHERE generation_id=:generation "
                        "AND paper_id=:paper ORDER BY vector_id LIMIT :limit")
    ids = (await db.execute(statement, {"generation": pin["generation_id"], "paper": paper_id,
                                       "limit": min(max(1, limit), 20)})).scalars().all()
    return list((await hydrate(db, pin, ids)).values())


async def paper_revision_exclusions(db, pin, paper_id):
    """Complete bounded source inventory, including unsampled source chunks."""
    from services.index_vector_adapter import MAX_EXCLUDED_REVISIONS
    statement = sa.text("SELECT chunk_revision_sha256 FROM index_generation_members "
                        "WHERE generation_id=:generation AND paper_id=:paper "
                        "ORDER BY chunk_revision_sha256 LIMIT :limit")
    revisions = list((await db.execute(statement, {"generation": pin["generation_id"], "paper": paper_id,
                       "limit": MAX_EXCLUDED_REVISIONS + 1})).scalars().all())
    if len(revisions) > MAX_EXCLUDED_REVISIONS or len(set(revisions)) != len(revisions):
        raise IndexRetrievalError("Source revision exclusion inventory exceeds its bound")
    return revisions


async def resolve_evidence(db, chunks):
    from services.rag_evidence import CURRENT_FACT_RENDERER_VERSION, resolve_chunk_evidence
    if not chunks or all(not isinstance(chunk, GenerationChunk) for chunk in chunks):
        return await resolve_chunk_evidence(db, chunks)
    if not all(isinstance(chunk, GenerationChunk) for chunk in chunks):
        raise IndexRetrievalError("Mixed retrieval generations are not admissible")
    evidence_ids = [chunk.member["evidence_revision_id"] for chunk in chunks]
    statement = sa.text("""SELECT to_jsonb(e) AS evidence, to_jsonb(x) AS parent,
        e.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(e)) AS evidence_intact,
        x.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(x)) AS parent_intact,
        EXISTS(SELECT 1 FROM rag_evidence_revisions previous WHERE previous.chunk_key IN (e.chunk_key,legacy_window.source_key)
            AND previous.permission_status='restricted') AS historically_restricted,
        (e.chunk_kind<>'retained_legacy_snapshot' OR legacy_window.chunk_key IS NOT NULL
          AND legacy_window.record_sha256=public.sclib_index_record_hash_v1(to_jsonb(legacy_window))) AS legacy_intact
        FROM rag_evidence_revisions e LEFT JOIN rag_extraction_revisions x ON x.id=e.parent_extraction_revision_id
        LEFT JOIN legacy_index_windows legacy_window ON legacy_window.chunk_key=e.chunk_key
        WHERE e.id IN :ids""").bindparams(sa.bindparam("ids", expanding=True, type_=sa.Uuid()))
    from uuid import UUID
    rows = (await db.execute(statement, {"ids": [UUID(str(value)) for value in evidence_ids]})).mappings().all()
    by_id = {row["evidence"]["id"]: row for row in rows}
    statuses = await resolve_paper_lifecycle(db, {chunk.paper_id for chunk in chunks})
    result = {}
    for chunk in chunks:
        member = chunk.member
        row = by_id.get(str(member["evidence_revision_id"]))
        if row is None:
            raise IndexRetrievalError("Immutable generation evidence unavailable")
        evidence, parent = row["evidence"], row["parent"]
        if (row["evidence_intact"] is not True or row["legacy_intact"] is not True or parent is not None and row["parent_intact"] is not True
                or evidence["record_sha256"] != member["evidence_record_sha256"]
                or evidence["content_sha256"] != member["content_sha256"]
                or evidence["source_snapshot_sha256"] != member["source_snapshot_sha256"]
                or evidence["paper_id"] != chunk.paper_id or evidence["chunk_key"] != member["chunk_key"]):
            raise IndexRetrievalError("Generation evidence integrity mismatch")
        permission = "restricted" if row["historically_restricted"] else evidence["permission_status"]
        warnings = ["original_root_unresolved", "source_permission_" + permission,
                    "generation_snapshot_catalogue_freshness_unverified"]
        if evidence["chunk_kind"] == "retained_legacy_snapshot":
            warnings.extend(["historical_parser_unrecorded", "historical_text_lineage_unverified"])
        stale = False
        if evidence["chunk_kind"] == "derived_fact" and evidence["rendering_version"] != CURRENT_FACT_RENDERER_VERSION:
            warnings.append("renderer_version_changed")
            stale = True
        if not source_visibility(statuses.get(chunk.paper_id))["reported_claim_filter_eligible"]:
            warnings.append("current_source_held")
            stale = True
        result[chunk.id] = validate_evidence_descriptor({
            "version": VERSION, "chunk_kind": evidence["chunk_kind"],
            "evidence_revision_id": evidence["id"], "evidence_record_sha256": evidence["record_sha256"],
            "content_sha256": evidence["content_sha256"], "parent_result_revision_id": parent["id"] if parent else None,
            "parent_result_sha256": parent["record_sha256"] if parent else None,
            "extraction_version": evidence["extraction_version"], "rendering_version": evidence["rendering_version"],
            "source_capture_id": evidence["source_capture_id"], "source_locator": evidence["source_locator"],
            "root_status": "unresolved", "permission_status": permission,
            "currentness": "stale" if stale else "current", "warning_codes": warnings,
            "support_eligible": False, "independent_evidence": False, "scientific_acceptance": False,
        })
    return result
