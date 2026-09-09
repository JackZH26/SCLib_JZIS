"""Fresh, bounded catalogue checks after generation; no scientific approval.

Private digests bind the exact selected inputs, not a permission grant. Pinned
generation reads rehydrate retained members and compare the active event (ABA),
while legacy lexical inputs reread mutable catalogue rows. A successful check
describes one new database snapshot, not future stability or scientific approval.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Text, case, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.db import Chunk, Material, Paper, get_engine
from services import index_retrieval
from services.retrieval_groups import GroupBinding, resolve_grouping_bindings
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import (
    project_source_occurrences,
    resolve_explicit_materials,
    source_visibility,
)

MAX_SOURCES = 20
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_CATALOGUE_BYTES = 8 * 1024 * 1024
MAX_MATERIAL_ROWS = 1000
MAX_MATERIAL_RECORDS = 5000
CHECK_TIMEOUT_SECONDS = 10
STATEMENT_TIMEOUT_MS = 5000
_CHUNK_FIELDS = ("id", "paper_id", "title", "section", "chunk_index", "text", "materials_mentioned")
_PAPER_FIELDS = (
    "id", "source", "arxiv_id", "doi", "external_id", "id_scheme", "related_paper_id",
    "title", "authors", "date_submitted", "date_published", "status", "publication_ref",
    "materials_extracted", "quality_flags",
)
EvidenceResolver = Callable[[AsyncSession, Sequence[Chunk]], Awaitable[Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class SelectionPin:
    chunk_id: str
    paper_id: str
    input_sha256: str
    has_evidence_pin: bool = False
    generation_pin_sha256: str | None = None
    grouping_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class CurrentnessCheck:
    status: str
    reason_code: str | None
    snapshot_at: str | None = None


class CurrentnessUnavailable(ValueError):
    """The complete selected input inventory could not be checked safely."""


def _digest(payload: Any) -> str:
    nodes, characters = 0, 0

    def validate(value, depth=0):
        nonlocal nodes, characters
        nodes += 1
        if depth > 24 or nodes > 100000:
            raise CurrentnessUnavailable("input structure budget")
        if isinstance(value, str):
            characters += len(value)
            if characters > MAX_INPUT_BYTES:
                raise CurrentnessUnavailable("input character budget")
        elif isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise CurrentnessUnavailable("input key type")
                validate(key, depth + 1)
                validate(item, depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in value:
                validate(item, depth + 1)
        elif value is not None and not isinstance(value, (bool, int, float, date, datetime)):
            raise CurrentnessUnavailable("input value type")

    validate(payload)
    digest, size = hashlib.sha256(), 0
    for piece in json.JSONEncoder(
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        default=lambda value: value.isoformat(),
    ).iterencode(payload):
        encoded = piece.encode("utf-8")
        size += len(encoded)
        if size > MAX_INPUT_BYTES:
            raise CurrentnessUnavailable("input byte budget")
        digest.update(encoded)
    return digest.hexdigest()


def selection_pin(chunk, *, material_evidence, source_review, evidence=None, grouping_binding: GroupBinding | None = None) -> SelectionPin:
    """Capture only inputs already admitted for this selected source, without I/O."""
    if (not isinstance(chunk.id, str) or not 1 <= len(chunk.id) <= 200
            or not isinstance(chunk.paper_id, str) or not 1 <= len(chunk.paper_id) <= 100
            or chunk.paper is None or chunk.paper.id != chunk.paper_id):
        raise CurrentnessUnavailable("selected source identity")
    if grouping_binding is not None and (not isinstance(grouping_binding, GroupBinding) or grouping_binding.paper_id != chunk.paper_id):
        raise CurrentnessUnavailable("selected diversity binding identity")
    try:
        generation = isinstance(chunk, index_retrieval.GenerationChunk)
        digest = _digest({
            "chunk": {name: getattr(chunk, name) for name in _CHUNK_FIELDS},
            "paper": (chunk.member["paper_snapshot_json"] if generation
                      else {name: getattr(chunk.paper, name) for name in _PAPER_FIELDS}),
            "material_evidence": material_evidence,
            "source_visibility": source_review,
            "evidence": evidence,
            "generation": chunk.generation_pin if generation else None,
            **({"grouping": {"paper_id": grouping_binding.paper_id, "accepted_work_id": grouping_binding.accepted_work_id,
                             "mapping_sha256": grouping_binding.mapping_sha256}} if grouping_binding is not None else {}),
        })
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise CurrentnessUnavailable("selected source representation") from exc
    return SelectionPin(chunk.id, chunk.paper_id, digest, evidence is not None,
                        index_retrieval.pin_sha256(chunk.generation_pin) if generation else None,
                        grouping_binding.mapping_sha256 if grouping_binding is not None else None)


def _row_size(table):
    return func.octet_length(cast(func.to_jsonb(table.table_valued()), Text))


async def _bounded_materials(db, groups):
    identifiers = {value for group in groups for record in group if isinstance(record, Mapping)
                   and isinstance(value := record.get("material_id"), str) and 0 < len(value) <= 100}
    frontier, seen, size, count = identifiers, set(), 0, 0
    for _ in range(33):
        if not frontier:
            break
        if len(frontier | seen) > MAX_MATERIAL_ROWS:
            raise CurrentnessUnavailable("material inventory limit")
        rows = (await db.execute(select(
            Material.id, Material.parent_material_id, _row_size(Material.__table__),
            case((func.jsonb_typeof(Material.records) == "array", func.jsonb_array_length(Material.records)), else_=None),
        ).where(Material.id.in_(frontier)))).all()
        # Missing explicit links already fail closed in the shared visibility
        # adapter. They need not turn an otherwise stable legacy input into 503.
        if any(records is None for _, _, _, records in rows):
            raise CurrentnessUnavailable("material record shape")
        size += sum(length for _, _, length, _ in rows)
        count += sum(records for _, _, _, records in rows)
        if size > MAX_CATALOGUE_BYTES or count > MAX_MATERIAL_RECORDS:
            raise CurrentnessUnavailable("material input budget")
        seen.update(frontier)
        frontier = {parent for _, parent, _, _ in rows if parent is not None} - seen
    if frontier:
        raise CurrentnessUnavailable("material ancestry budget")
    return await resolve_explicit_materials(db, groups)


async def _check_snapshot(db, pins, evidence_resolver):
    snapshot_at = (await db.execute(select(func.transaction_timestamp()))).scalar_one().isoformat()
    identifiers = [pin.chunk_id for pin in pins]
    generation_hashes = {pin.generation_pin_sha256 for pin in pins}
    if generation_hashes != {None}:
        if None in generation_hashes or len(generation_hashes) != 1:
            raise CurrentnessUnavailable("mixed generation inventory")
        active = await index_retrieval.load_pin(db)
        if active is None or index_retrieval.pin_sha256(active) not in generation_hashes:
            return CurrentnessCheck("changed", "retrieval_generation_changed", snapshot_at)
        chunks = list((await index_retrieval.hydrate(db, active, identifiers)).values())
        if {(chunk.id, chunk.paper_id) for chunk in chunks} != {(pin.chunk_id, pin.paper_id) for pin in pins}:
            return CurrentnessCheck("changed", "retrieval_source_changed", snapshot_at)
    else:
        chunk_sizes = (await db.execute(select(Chunk.id, Chunk.paper_id, _row_size(Chunk.__table__))
                                       .where(Chunk.id.in_(identifiers)))).all()
        if ({(identifier, paper_id) for identifier, paper_id, _ in chunk_sizes}
                != {(pin.chunk_id, pin.paper_id) for pin in pins}):
            return CurrentnessCheck("changed", "retrieval_source_changed", snapshot_at)
        papers = {pin.paper_id for pin in pins}
        paper_sizes = (await db.execute(select(Paper.id, _row_size(Paper.__table__))
                                       .where(Paper.id.in_(papers)))).all()
        if {identifier for identifier, _ in paper_sizes} != papers:
            return CurrentnessCheck("changed", "retrieval_source_changed", snapshot_at)
        if (sum(length for _, _, length in chunk_sizes) + sum(length for _, length in paper_sizes)
                > MAX_CATALOGUE_BYTES):
            raise CurrentnessUnavailable("selected catalogue byte budget")
        chunks = (await db.execute(select(Chunk).options(selectinload(Chunk.paper))
                                  .where(Chunk.id.in_(identifiers)))).scalars().all()
    groups = [chunk.materials_mentioned for chunk in chunks]
    if any(not isinstance(group, list) for group in groups) or sum(map(len, groups)) > MAX_MATERIAL_RECORDS:
        raise CurrentnessUnavailable("selected occurrence inventory")
    linked = await _bounded_materials(db, groups)
    statuses = await resolve_paper_lifecycle(db, {chunk.paper_id for chunk in chunks})
    evidence = await evidence_resolver(db, chunks) if evidence_resolver is not None else {}
    if any(pin.has_evidence_pin for pin in pins) and evidence_resolver is None:
        raise CurrentnessUnavailable("typed evidence resolver unavailable")
    expected = {pin.chunk_id: pin for pin in pins}
    grouping_papers = {pin.paper_id for pin in pins if pin.grouping_sha256 is not None}
    grouping = await resolve_grouping_bindings(db, grouping_papers) if grouping_papers else {}
    for chunk in chunks:
        status = statuses.get(chunk.paper_id)
        visibility = source_visibility(status)
        if status is None or not visibility["reported_claim_filter_eligible"]:
            return CurrentnessCheck("changed", "retrieval_source_no_longer_eligible", snapshot_at)
        occurrences, summary = project_source_occurrences(
            chunk.materials_mentioned, paper_status=status, linked_materials=linked, container_paper_id=chunk.paper_id,
        )
        visibility["warning_codes"] = sorted(set(visibility["warning_codes"] + summary["warning_codes"]))
        binding = grouping.get(chunk.paper_id) if expected[chunk.id].grouping_sha256 is not None else None
        if expected[chunk.id].grouping_sha256 is not None and (
                binding is None or binding.mapping_sha256 != expected[chunk.id].grouping_sha256):
            return CurrentnessCheck("changed", "retrieval_grouping_changed", snapshot_at)
        fresh = selection_pin(chunk, material_evidence=occurrences, source_review=visibility,
                              evidence=evidence.get(chunk.id), grouping_binding=binding)
        if fresh != expected[chunk.id]:
            return CurrentnessCheck("changed", "retrieval_source_changed", snapshot_at)
    return CurrentnessCheck("unchanged", None, snapshot_at)


async def check_selected_sources(pins, *, engine=None, evidence_resolver: EvidenceResolver | None = None):
    """Read in a NEW short transaction, never the pre-generation ORM session.

    Every selected source must still match. Failure yields no eligible subset
    for a previous draft: callers must abstain, not relabel its old citations.
    No write, row/advisory lock, network provider or approval occurs here.
    """
    if (not isinstance(pins, (list, tuple)) or not 1 <= len(pins) <= MAX_SOURCES
            or any(not isinstance(pin, SelectionPin) for pin in pins)
            or len({pin.chunk_id for pin in pins}) != len(pins)):
        return CurrentnessCheck("unavailable", "retrieval_currentness_unavailable")
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            async with AsyncSession((engine or get_engine()).execution_options(
                isolation_level="REPEATABLE READ",
            )) as db:
                async with db.begin():
                    await db.execute(text("SET TRANSACTION READ ONLY"))
                    await db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'"))
                    return await _check_snapshot(db, pins, evidence_resolver)
    except TimeoutError:
        return CurrentnessCheck("unavailable", "retrieval_currentness_timeout")
    except Exception:  # fail closed without returning source data or database errors
        return CurrentnessCheck("unavailable", "retrieval_currentness_unavailable")
