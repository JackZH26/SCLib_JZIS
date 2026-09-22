"""Read-time visibility of reported source occurrences, not claim approval.

Only an explicit, resolvable ``material_id`` is joined to the material policy.
Formula equality is not an identity relation. Bibliographic source text remains
accessible even when a linked catalogue occurrence is withheld.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from services.material_visibility import (
    MATERIAL_VISIBILITY_VERSION,
    normalize_source_status,
    sanitize_review_metadata,
)
from services.result_semantics import evidence_classifications
from services.source_lifecycle_status import (
    lifecycle_review_required,
    lifecycle_revision,
    lifecycle_status,
)
from services.structure_disclosure import redact_structure_payloads

_HELD_SOURCE_STATES = {"retracted", "corrected", "disputed"}


class _ResolvedMaterialVisibility(dict):
    """Internal lookup value. JSON serialization intentionally excludes scope.

    A public visibility dictionary, including its public ``source_scope``
    summary, cannot provide this private captured membership context.
    """
    __slots__ = ("source_scope", "material_id", "review_context")

    def __init__(self, value, *, material_id, source_scope, review_context):
        super().__init__(deepcopy(value))
        self.material_id = material_id
        self.source_scope = source_scope
        self.review_context = deepcopy(review_context)


def linked_material_visibility(context) -> dict[str, Any]:
    """Bind an actual read context, never a caller's public summary.

    Material.records hashes are checked here against their own original array.
    They are not matched to Paper/Chunk extraction arrays, whose metadata may
    legitimately differ after aggregation.
    """
    from services.material_anomalies import review_context
    from services.material_source_scope import VISIBILITY_VERSION, SourceScope, SourceScopeError
    from services.material_visibility_adapter import MaterialReadContext

    visibility = deepcopy(context.visibility)
    scope = None
    assessment_context = None
    if visibility.get("version") == VISIBILITY_VERSION and type(context) is MaterialReadContext:
        candidate = getattr(context, "source_scope", None)
        if type(candidate) is SourceScope and candidate.material_id == context.id:
            try:
                candidate.validate(context.records)
                scope = candidate
                assessment_context = review_context(context.material)
            except (SourceScopeError, ValueError, TypeError, IndexError, AttributeError):
                pass  # No v1 downgrade; the v2 occurrence will fail closed.
    return _ResolvedMaterialVisibility(visibility, material_id=context.id, source_scope=scope,
        review_context=assessment_context)


def _scope_reason(linked_visibility, material_id, record, container_paper_id, paper_status):
    from services.material_anomalies import record_assessment
    from services.material_source_scope import (
        VISIBILITY_VERSION,
        SourceScope,
        SourceScopeError,
        validate_scoped_visibility,
    )

    if linked_visibility.get("version") == MATERIAL_VISIBILITY_VERSION:
        return None  # Preserve the frozen v1 policy.
    if (linked_visibility.get("version") != VISIBILITY_VERSION
            or type(linked_visibility) is not _ResolvedMaterialVisibility
            or type(linked_visibility.source_scope) is not SourceScope
            or type(linked_visibility.review_context) is not dict):
        return "occurrence_source_scope_unavailable"
    scope = linked_visibility.source_scope
    try:
        summary = validate_scoped_visibility(dict(linked_visibility))["source_scope"]
        eligible_papers = scope.eligible_paper_ids
    except (SourceScopeError, ValueError, TypeError, IndexError, AttributeError):
        return "occurrence_source_scope_unavailable"
    if (scope.material_id != linked_visibility.material_id
            or material_id is not None and material_id != scope.material_id
            or record.get("material_id") is not None and material_id is None
            or scope.fingerprint != summary["fingerprint"]
            or len(scope.indices) != summary["total_records"]
            or len(scope.eligible_indices) != summary["eligible_records"]
            or len(eligible_papers) != summary["eligible_source_count"]):
        return "occurrence_source_scope_unavailable"
    # A source record cannot nominate another container, even if that other
    # paper independently has an eligible record for the same material.
    if (type(container_paper_id) is not str or not 0 < len(container_paper_id) <= 100
            or container_paper_id != container_paper_id.strip()
            or any(ord(char) < 32 for char in container_paper_id)):
        return "occurrence_container_source_unresolved"
    if record.get("paper_id") is not None and record["paper_id"] != container_paper_id:
        return "occurrence_container_source_conflict"
    source = source_visibility(paper_status)
    if source["source_status"] != "active" or not source["reported_claim_filter_eligible"]:
        return "occurrence_source_not_currently_eligible"
    if container_paper_id not in eligible_papers:
        return "occurrence_source_outside_eligible_scope"
    # Membership admits only the source identity. A good record in that paper
    # cannot confer a current-use badge on an anomalous sibling occurrence.
    # Use the trusted material's context, never a public/raw record override.
    try:
        assessment = record_assessment(record, scope_id=scope.material_id, context=linked_visibility.review_context)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return "occurrence_record_assessment_unavailable"
    if assessment["status"] != "no_findings":
        return "occurrence_anomaly_review_required"
    return None


def source_visibility(status: Any) -> dict[str, Any]:
    held = lifecycle_review_required(status)
    revision = lifecycle_revision(status)
    status = lifecycle_status(status)
    normalized = normalize_source_status(status)
    disputed = isinstance(status, str) and status.strip().lower() == "disputed"
    state = "disputed" if disputed else normalized
    warnings = [f"source_{state}"] if state != "active" else []
    if held:
        warnings.append("source_lifecycle_review_required")
    return {
        "version": MATERIAL_VISIBILITY_VERSION,
        "source_status": state,
        "bibliography_available": True,
        "reported_claim_filter_eligible": state not in _HELD_SOURCE_STATES and not held,
        "scientific_acceptance": False,
        "warning_codes": warnings,
        **({"lifecycle_review_required": True, "lifecycle_revision": revision} if held else {}),
    }


def _explicit_material_id(record: Mapping[str, Any]) -> str | None:
    value = record.get("material_id")
    return value if isinstance(value, str) and 0 < len(value) <= 100 else None


def occurrence_visibility(
    record: Mapping[str, Any], *, paper_status: Any,
    linked_visibility: Mapping[str, Any] | None = None,
    container_paper_id: str | None = None,
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
        scope_reason = _scope_reason(linked_visibility, material_id, record, container_paper_id, paper_status)
        if scope_reason is not None:
            catalogue_eligible = reported_eligible = False
            if state == "catalogue":
                # This is the occurrence's current-use policy, not a mutation
                # or assertion that the whole material needs scientific review.
                state = "pending"
            reasons.append(scope_reason)
            warnings.append("source_scoped_occurrence_withheld")

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
    if source.get("lifecycle_review_required"):
        holds.add("pending")
        reasons.append("source_lifecycle_review_required")
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
        **({"lifecycle_revision": source.get("lifecycle_revision")} if source.get("lifecycle_review_required") else {}),
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
        result.update({view.id: linked_material_visibility(view) for view in views})
    return result


def project_source_occurrences(
    records: Any, *, paper_status: Any, linked_materials: Mapping[str, Mapping[str, Any]],
    container_paper_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    retained = []
    counts: Counter[str] = Counter()
    omitted = 0
    scoped_withheld = False
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, Mapping):
            counts["malformed"] += 1
            omitted += 1
            continue
        visibility = occurrence_visibility(
            record, paper_status=paper_status,
            linked_visibility=linked_materials.get(_explicit_material_id(record)),
            container_paper_id=container_paper_id,
        )
        counts[visibility["state"]] += 1
        scoped_withheld |= "source_scoped_occurrence_withheld" in visibility["warning_codes"]
        if not visibility["archive_available"]:
            omitted += 1
            continue
        retained.append({**redact_structure_payloads(sanitize_review_metadata(record)), "visibility": visibility})
    return retained, {
        "version": MATERIAL_VISIBILITY_VERSION,
        "total_occurrences": sum(counts.values()),
        "returned_occurrences": len(retained),
        "omitted_occurrences": omitted,
        "state_counts": dict(sorted(counts.items())),
        "scientific_acceptance": False,
        "warning_codes": (["restricted_or_malformed_occurrences_omitted"] if omitted else [])
        + (["source_scoped_occurrence_withheld"] if scoped_withheld else []),
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
