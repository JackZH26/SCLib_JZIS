"""Read-time visibility of reported source occurrences, not claim approval.

Only an explicit, resolvable ``material_id`` is joined to the material policy.
Formula equality is not an identity relation. Bibliographic source text remains
accessible even when a linked catalogue occurrence is withheld.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from services.material_visibility import (
    MATERIAL_VISIBILITY_VERSION,
    normalize_source_status,
    sanitize_review_metadata,
)
from services.result_semantics import evidence_classifications

_HELD_SOURCE_STATES = {"retracted", "corrected", "disputed"}


def source_visibility(status: Any) -> dict[str, Any]:
    normalized = normalize_source_status(status)
    disputed = isinstance(status, str) and status.strip().lower() == "disputed"
    state = "disputed" if disputed else normalized
    warnings = [f"source_{state}"] if state != "active" else []
    return {
        "version": MATERIAL_VISIBILITY_VERSION,
        "source_status": state,
        "bibliography_available": True,
        "reported_claim_filter_eligible": state not in _HELD_SOURCE_STATES,
        "scientific_acceptance": False,
        "warning_codes": warnings,
    }


def _explicit_material_id(record: Mapping[str, Any]) -> str | None:
    value = record.get("material_id")
    return value if isinstance(value, str) and 0 < len(value) <= 100 else None


def occurrence_visibility(
    record: Mapping[str, Any], *, paper_status: Any,
    linked_visibility: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute a bounded envelope; never trust a source-provided envelope."""
    source = source_visibility(paper_status)
    warnings = list(source["warning_codes"])
    reasons: list[str] = []
    material_id = _explicit_material_id(record)
    explicit_link = record.get("material_id") is not None
    if linked_visibility is None:
        state = "unknown"
        reasons.append("unresolved_material_id" if material_id else "invalid_material_id" if explicit_link else "unlinked_unreviewed_occurrence")
        catalogue_eligible = False
        # An explicit link claims catalogue identity; its provenance restriction
        # cannot be established when resolution fails. Keep bibliography/text,
        # not the unresolved structured material occurrence. Never formula-join.
        archive_available = not explicit_link
        reported_eligible = not explicit_link
        review_revision = None
    else:
        state = linked_visibility.get("state", "unknown")
        catalogue_eligible = linked_visibility.get("public_catalogue_eligible") is True
        archive_available = linked_visibility.get("archive_available") is True
        reported_eligible = catalogue_eligible
        reasons.extend(linked_visibility.get("reason_codes", []))
        warnings.extend(linked_visibility.get("warning_codes", []))
        review_revision = linked_visibility.get("review_revision")

    holds = {state} if state in {"quarantined", "pending", "disputed", "retracted", "corrected"} else set()
    malformed = any(record.get(key) is not None and not isinstance(record[key], bool)
                    for key in ("needs_review", "disputed", "retracted", "corrected"))
    malformed |= any(record.get(key) is not None and not isinstance(record[key], str)
                     for key in ("review_status", "provenance_status", "review_reason", "source_status", "status"))
    if malformed:
        holds.add("pending")
        reasons.append("occurrence_review_metadata_invalid")

    # These are *holds*, never a source's assertion of approval. A source cannot
    # set "reviewed=true" or a forged visibility payload to remove a hold.
    # Negative source/record assertions add holds even without an authoritative
    # link. Their positive counterparts never establish source acceptance.
    record_statuses = {str(record.get(key, "")).strip().lower()
                       for key in ("review_status", "status", "source_status")}
    provenance = str(record.get("provenance_status", "")).strip().lower()
    reason = record.get("review_reason")
    if ((isinstance(reason, str) and reason.strip().lower().startswith("provenance_quarantine"))
            or provenance in {"quarantined", "quarantine"}
            or record_statuses & {"quarantined", "provenance_quarantined"}):
        holds.add("quarantined")
        archive_available = False
        reasons.append("occurrence_provenance_quarantine")
    elif record.get("retracted") is True or record_statuses & {"retracted", "withdrawn"}:
        holds.add("retracted")
        reasons.append("occurrence_retracted")
    elif record.get("disputed") is True or record_statuses & {"disputed", "refuted"}:
        holds.add("disputed")
        reasons.append("occurrence_disputed")
    elif record.get("corrected") is True or "corrected" in record_statuses:
        holds.add("corrected")
        reasons.append("occurrence_corrected_requires_revision_review")
    elif record.get("needs_review") is True or record_statuses & {"pending", "unreviewed", "excluded"}:
        holds.add("pending")
        reasons.append("occurrence_review_required")

    if source["source_status"] in _HELD_SOURCE_STATES:
        holds.add(source["source_status"])
        reasons.append(f"source_{source['source_status']}")
    if holds:
        state = next(item for item in ("quarantined", "retracted", "disputed", "corrected", "pending") if item in holds)
    held = bool(holds)
    return {
        "version": MATERIAL_VISIBILITY_VERSION,
        "state": state,
        "material_link_status": "resolved" if linked_visibility is not None else "unresolved" if explicit_link else "unlinked",
        "public_catalogue_eligible": catalogue_eligible and not held,
        "reported_claim_filter_eligible": reported_eligible and not held and source["reported_claim_filter_eligible"],
        "archive_available": archive_available,
        "scientific_acceptance": False,
        "reason_codes": sorted(set(reasons)),
        "warning_codes": sorted(set(warnings + (
            ["unresolved_material_identity" if explicit_link else "unlinked_unreviewed_occurrence"]
            if linked_visibility is None else []))),
        "review_revision": review_revision,
        "source_status": source["source_status"],
    }


async def resolve_explicit_materials(db: Any, record_groups: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """One bounded material lookup, followed by the shared parent/source adapter."""
    from sqlalchemy import select

    from models.db import Material
    from services.material_visibility_adapter import prepare_material_views

    identifiers = sorted({
        value for records in record_groups if isinstance(records, list)
        for record in records if isinstance(record, Mapping)
        if (value := _explicit_material_id(record)) is not None
    })
    result = {}
    # Bound each SQL IN query without dropping later identities from a large
    # source array. No formula, title or textual attribution is used as a join.
    for offset in range(0, len(identifiers), 300):
        rows = (await db.execute(select(Material).where(Material.id.in_(identifiers[offset:offset + 300])))).scalars().all()
        views = await prepare_material_views(db, rows)
        result.update({view.id: view.visibility for view in views})
    return result


def project_source_occurrences(
    records: Any, *, paper_status: Any, linked_materials: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    retained = []
    counts: Counter[str] = Counter()
    omitted = 0
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, Mapping):
            counts["malformed"] += 1
            omitted += 1
            continue
        visibility = occurrence_visibility(
            record, paper_status=paper_status,
            linked_visibility=linked_materials.get(_explicit_material_id(record)),
        )
        counts[visibility["state"]] += 1
        if not visibility["archive_available"]:
            omitted += 1
            continue
        retained.append({**sanitize_review_metadata(record), "visibility": visibility})
    return retained, {
        "version": MATERIAL_VISIBILITY_VERSION,
        "total_occurrences": sum(counts.values()),
        "returned_occurrences": len(retained),
        "omitted_occurrences": omitted,
        "state_counts": dict(sorted(counts.items())),
        "scientific_acceptance": False,
        "warning_codes": ["restricted_or_malformed_occurrences_omitted"] if omitted else [],
    }


def citation_evidence(records: Any, *, visibility_resolved: bool = False) -> list[dict[str, Any]]:
    """Whitelist citation labels; source-controlled visibility is ignored.

    Only routers that just ran ``project_source_occurrences`` may opt into the
    server-derived envelope. The default accepts untrusted extraction records.
    """
    result = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, Mapping):
            continue
        item = evidence_classifications([record])[0]
        visibility = record.get("visibility")
        if visibility_resolved and isinstance(visibility, Mapping) and visibility.get("version") == MATERIAL_VISIBILITY_VERSION:
            item["visibility"] = {
                key: value for key, value in visibility.items()
                if key in {"version", "state", "material_link_status", "public_catalogue_eligible",
                           "reported_claim_filter_eligible", "archive_available", "scientific_acceptance",
                           "reason_codes", "warning_codes", "review_revision", "source_status"}
            }
        result.append(item)
        if len(result) == 50:
            break
    return result
