"""Live metadata warnings alongside, never in place of, saved Ask evidence.

Saved citations do not pin a source revision or retain resolvable occurrence
identities. Current paper extractions must therefore never be presented as a
revalidation of the historical excerpt or answer. This projection has no write
path and deliberately grants no scientific or training approval.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from sqlalchemy import Text, and_, case, cast, func, or_, select, text

from models.db import Material, Paper
from services.source_visibility import (
    project_source_occurrences,
    resolve_explicit_materials,
    source_visibility,
)

MAX_SOURCES_PER_ENTRY = 50
MAX_PAPERS = 1000
MAX_OCCURRENCES = 5000
MAX_OCCURRENCE_BYTES = 4 * 1024 * 1024
MAX_MATERIAL_ROWS = 1000
MAX_MATERIAL_BYTES = 4 * 1024 * 1024
MAX_CURRENT_EVIDENCE_BYTES = 8 * 1024 * 1024
_OUTPUT_BUDGET_WARNING = "current_evidence_output_budget_exhausted"
VERSION = "ask-history-current-evidence/1.0.0"


def _wire_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _record_count():
    return case((func.jsonb_typeof(Paper.materials_extracted) == "array",
                 func.jsonb_array_length(Paper.materials_extracted)), else_=None)


def _sources(row):
    return row.sources[:MAX_SOURCES_PER_ENTRY] if isinstance(row.sources, list) else []


def _paper_id(source):
    value = source.get("paper_id") if isinstance(source, Mapping) else None
    return value if isinstance(value, str) and 0 < len(value) <= 100 else None


async def _bounded_explicit_materials(db, groups):
    """Preflight every adapter-loaded ancestor before loading full ORM rows."""
    identifiers = {value for group in groups for record in group if isinstance(record, Mapping)
                   and isinstance(value := record.get("material_id"), str) and 0 < len(value) <= 100}
    frontier, seen, byte_count, record_count = identifiers, set(), 0, 0
    relation = Material.__table__
    for _ in range(33):
        if not frontier:
            break
        if len(frontier) + len(seen) > MAX_MATERIAL_ROWS:
            return {}, False
        rows = (await db.execute(select(
            Material.id, Material.parent_material_id,
            func.octet_length(cast(func.to_jsonb(relation.table_valued()), Text)),
            case((func.jsonb_typeof(Material.records) == "array", func.jsonb_array_length(Material.records)), else_=None),
        ).where(Material.id.in_(frontier)))).all()
        if len(rows) != len(frontier) or any(count is None for _, _, _, count in rows):
            return {}, False
        byte_count += sum(size for _, _, size, _ in rows)
        record_count += sum(count for _, _, _, count in rows)
        if byte_count > MAX_MATERIAL_BYTES or record_count > MAX_OCCURRENCES:
            return {}, False
        seen.update(frontier)
        frontier = {parent for _, parent, _, _ in rows if parent is not None} - seen
    if frontier:
        return {}, False
    return await resolve_explicit_materials(db, groups), True


async def current_history_evidence(db, rows):
    """Bound extra reads in one snapshot; never revalidate the saved answer."""
    if len(rows) > 200:
        raise ValueError("Current history evidence supports at most 200 saved entries")
    if (await db.execute(text("SHOW transaction_isolation"))).scalar_one() not in {"repeatable read", "serializable"}:
        raise ValueError("Current history evidence requires a consistent database snapshot")
    snapshot_at = (await db.execute(select(func.transaction_timestamp()))).scalar_one().isoformat()
    requested = sorted({_paper_id(source) for row in rows for source in _sources(row)
                        if _paper_id(source) is not None})
    identifiers = requested[:MAX_PAPERS]
    metadata = {}
    for offset in range(0, len(identifiers), 300):
        batch = (await db.execute(select(
            Paper.id, Paper.status,
            func.octet_length(cast(Paper.materials_extracted, Text)),
            _record_count(),
        ).where(Paper.id.in_(identifiers[offset:offset + 300])))).all()
        metadata.update({identifier: (status, size, count) for identifier, status, size, count in batch})

    retained, byte_count, occurrence_count = [], 0, 0
    for identifier in identifiers:
        if identifier not in metadata:
            continue
        _, size, count = metadata[identifier]
        if (size is None or count is None or count > 200
                or byte_count + size > MAX_OCCURRENCE_BYTES
                or occurrence_count + count > MAX_OCCURRENCES):
            continue
        byte_count += size
        occurrence_count += count
        retained.append(identifier)
    records = {}
    for offset in range(0, len(retained), 300):
        # Keep the preflight reservations explicit in the loading query even
        # though the required RR/SERIALIZABLE snapshot prevents intervening edits.
        bounds = [and_(Paper.id == identifier,
                      func.octet_length(cast(Paper.materials_extracted, Text)) <= metadata[identifier][1],
                      _record_count() <= metadata[identifier][2])
                  for identifier in retained[offset:offset + 300]]
        batch = (await db.execute(select(Paper.id, Paper.status, Paper.materials_extracted)
                                 .where(or_(*bounds)))).all()
        for identifier, status, value in batch:
            records[identifier] = value
            metadata[identifier] = (status, metadata[identifier][1], metadata[identifier][2])
    linked, materials_checked = await _bounded_explicit_materials(db, list(records.values()))
    projected = {}
    for identifier, (status, _, _) in metadata.items():
        visibility = source_visibility(status)
        checked = identifier in records and materials_checked and visibility["source_status"] != "unknown"
        if not checked:
            visibility = {**visibility, "reported_claim_filter_eligible": False}
        value = {
            "paper_id": identifier,
            "source_visibility": visibility,
            "metadata_status": "checked" if checked else "incomplete",
            "occurrence_visibility_summary": None,
            "warning_codes": list(visibility["warning_codes"]),
        }
        if checked:
            _, summary = project_source_occurrences(
                records[identifier], paper_status=status, linked_materials=linked,
            )
            # The history UI needs lifecycle counts, not repeated scientific
            # records. Never export per-occurrence eligibility under an
            # incomplete/unknown parent envelope, or amplify shared records
            # across up to 200 saved entries and 50 citations per entry.
            value["occurrence_visibility_summary"] = summary
            value["warning_codes"].extend(summary["warning_codes"])
        else:
            value["warning_codes"].append("current_occurrence_inventory_unavailable")
        if not materials_checked:
            value["warning_codes"].append("current_explicit_material_inventory_unavailable")
        if visibility["source_status"] == "unknown":
            value["warning_codes"].append("current_source_status_unresolved")
        projected[identifier] = value

    result = {row.id: {
        "version": VERSION,
        "scope": "current_paper_metadata_not_saved_excerpt",
        "metadata_snapshot_at": snapshot_at,
        "saved_answer_revalidated": False,
        "scientific_acceptance": False,
        "ml_training_eligibility_established": False,
        "sources": [],
        "warning_codes": ["historical_answer_requires_new_claim_review"] + (
            ["saved_source_inventory_truncated"]
            if isinstance(row.sources, list) and len(row.sources) > MAX_SOURCES_PER_ENTRY else []),
    } for row in rows}
    # Count actual repeated JSON entries, not only unique/shared Python values.
    # Reserve one honest truncation warning per row and list separators up front.
    emitted_bytes = _wire_size(list(result.values())) + len(rows) * (_wire_size(_OUTPUT_BUDGET_WARNING) + 1)
    if emitted_bytes > MAX_CURRENT_EVIDENCE_BYTES:
        raise ValueError("Current evidence output budget is below its minimum envelope size")
    for row in rows:
        for position, source in enumerate(_sources(row)):
            identifier = _paper_id(source)
            value = projected.get(identifier)
            if value is None:
                value = {
                    "paper_id": identifier, "metadata_status": "unavailable",
                    "source_visibility": {
                        **source_visibility(None), "reported_claim_filter_eligible": False,
                        "warning_codes": ["current_source_unavailable"],
                    },
                    "occurrence_visibility_summary": None,
                    "warning_codes": ["current_source_unavailable"],
                }
            candidate = {**value, "saved_source_position": position}
            size = _wire_size(candidate) + 1
            if emitted_bytes + size > MAX_CURRENT_EVIDENCE_BYTES:
                result[row.id]["warning_codes"].append(_OUTPUT_BUDGET_WARNING)
                break
            result[row.id]["sources"].append(candidate)
            emitted_bytes += size
    return result
