"""Read-only, fail-closed compatibility projection for material responses.

Catalogue columns are selection hints, not a joint scientific observation.
Only raw records can support a displayed property; a cached/public evidence
envelope never serves as input evidence. No database mutation is performed.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from services.material_anomalies import (
    material_review,
    record_assessment,
    retained_record_archive,
    review_context,
)
from services.material_scoped_properties import scoped_property_evidence
from services.material_semantics import MATERIAL_SEMANTICS_FIELDS, build_material_semantics
from services.material_visibility import sanitize_review_metadata, visibility_for_material
from services.material_visibility_adapter import MaterialReadContext
from services.property_evidence import PROPERTY_FIELDS, build_property_evidence
from services.structure_disclosure import redact_structure_payloads
from services.structure_evidence import STRUCTURE_EVIDENCE_FIELDS, build_structure_evidence


def project_material_semantics(value: Any, *, scope_id: str | None = None) -> dict[str, Any]:
    """Rebuild from current raw records; a stored envelope is never evidence."""
    def read(name: str, default=None):
        return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)
    legacy = {name: read(name) for name in (*MATERIAL_SEMANTICS_FIELDS, "disputed", "total_papers")}
    return build_material_semantics(
        value.current_records() if isinstance(value, MaterialReadContext) else read("records"),
        scope_id=scope_id or str(read("id") or "unknown-material"),
        family=read("family"), legacy_summary=legacy,
        source_statuses=value.source_statuses if isinstance(value, MaterialReadContext) else None,
    )


def project_material_properties(
    value: Any,
    field_names: Iterable[str],
    *,
    scope_id: str | None = None,
    compact: bool = False,
) -> dict[str, Any]:
    """Bind existing selections without resurrecting capped/hidden values.

    Missing quantitative aggregates remain missing even when other raw results
    exist. SC10 classifications instead use their explicit reported-summary
    policy. Unsupported historical scalars become null in this *response*,
    with independently browsable raw evidence retained in the envelopes.
    """
    names = set(field_names)
    payload = dict(value) if isinstance(value, dict) else {
        name: getattr(value, name) for name in names if hasattr(value, name)
    }
    # The same source pool must apply on narrow variants/bookmarks as on a
    # full material response. These are selection hints, never origin evidence.
    for hint in ("tc_max_experimental", "tc_max_theoretical"):
        if hint not in payload:
            payload[hint] = value.get(hint) if isinstance(value, dict) else getattr(value, hint, None)
    raw_records = value.get("records") if isinstance(value, dict) else getattr(value, "records", None)
    retained = raw_records if isinstance(raw_records, list) else []
    scoped = isinstance(value, MaterialReadContext) and value.source_scope is not None
    records = value.current_records() if scoped else retained
    identity = scope_id or str(payload.get("id") or "unknown-material")
    context = review_context(value)
    semantics = project_material_semantics(value, scope_id=identity)
    structures = build_structure_evidence(
        records, scope_id=identity,
        source_statuses=value.source_statuses if isinstance(value, MaterialReadContext) else None,
    )
    # SC11 currently supplies pending text relations, not reviewed structure
    # associations or coordinate artifacts. Never approve a stored envelope.
    for field in STRUCTURE_EVIDENCE_FIELDS:
        if field in names:
            payload[field] = None
    # SC10 aliases come from reported classification semantics, not stale
    # weighted votes, family priors or defaults. Other legacy properties retain
    # their existing atomic-selection policy.
    for field in MATERIAL_SEMANTICS_FIELDS:
        if field in names:
            item = semantics["properties"][field]
            payload[field] = item["value"] if item["status"] == "reported" else None
    evidence_options = dict(
        scope_id=identity,
        property_fields=[field for field in PROPERTY_FIELDS if field in names],
        include_joint_epc=not compact,
        anomaly_context=context,
    )
    envelope = (scoped_property_evidence(records, **evidence_options) if scoped else
                build_property_evidence(records, legacy_summary=payload, **evidence_options))
    if scoped:
        # Legacy aggregate metadata may be supported only by an excluded source.
        # A known source count is bibliographic membership, never replication.
        if "total_papers" in names:
            payload["total_papers"] = value.visibility["source_scope"]["eligible_source_count"]
        for field in ("arxiv_year", "best_credibility_tier"):
            if field in names:
                payload[field] = None
    properties = envelope["properties"]
    for field, binding in properties.items():
        if field in names:
            selected = binding.get("selected")
            payload[field] = selected["value"] if binding["status"] == "supported" and selected else None

    # Independent legacy condition strings cannot inherit the selected value's
    # provenance. Copy only text from the selected atomic tuple.
    for field, property_name, condition_name in (
        ("tc_max_conditions", "tc_max", "tc_conditions"),
        ("hc2_conditions", "hc2_tesla", "hc2_conditions"),
    ):
        if field in names:
            selected = properties.get(property_name, {}).get("selected")
            payload[field] = selected["conditions"].get(condition_name) if selected else None
    if "ambient_sc" in names:
        payload["ambient_sc"] = True if payload.get("tc_ambient") is not None else None

    for field in MATERIAL_SEMANTICS_FIELDS:
        if field in names:
            item = semantics["properties"][field]
            payload[field] = item["value"] if item["status"] == "reported" else None
            if field in properties:
                properties[field]["warnings"] = sorted(set([
                    *properties[field]["warnings"], "classification_summary_uses_material_semantics",
                ]))
    payload["material_semantics"] = semantics
    payload["structure_evidence"] = structures
    for field in STRUCTURE_EVIDENCE_FIELDS:
        if field in names:
            payload[field] = None
            if field in properties:
                properties[field]["selected"] = None
                properties[field]["warnings"] = sorted(set([
                    *properties[field]["warnings"], "structure_association_pending_source_review",
                    "text_label_is_not_a_coordinate_structure",
                ]))

    if compact:
        # Lists/bookmarks carry selected tuples only; detailed alternative
        # evidence remains on the detail endpoint. Keep counts and warnings.
        envelope["properties"] = {
            field: {**binding, "evidence": []}
            for field, binding in properties.items() if field in names
        }
        envelope["evidence_scope"] = "selected_only"
    else:
        envelope["evidence_scope"] = "bounded_alternatives"
    payload["property_evidence"] = envelope
    payload["anomaly_review"] = material_review(records, scope_id=identity, context=context, compact=compact)
    visibility = value.visibility if isinstance(value, MaterialReadContext) else visibility_for_material(value, anomaly_review=payload["anomaly_review"])
    payload["visibility"] = visibility
    payload["needs_review"] = not visibility["public_catalogue_eligible"]
    payload["review_reason"] = "; ".join(visibility.get("reason_messages", [])) or None
    for private in ("admin_decision", "anomaly_context", "reviewer_id", "reviewer_email"):
        payload.pop(private, None)
    if not compact and "records" in names:
        payload["records"] = [
            {**redact_structure_payloads(sanitize_review_metadata(record)),
             "anomaly_review": record_assessment(record, scope_id=identity, context=context),
             "visibility": value.record_visibility(index) if scoped else visibility}
            for index, record in enumerate(retained) if isinstance(record, dict)
        ]
        payload["raw_archive"] = retained_record_archive(retained, scope_id=identity, context=context)
        payload["raw_archive"]["visibility"] = visibility
        if scoped:
            for item in payload["raw_archive"]["records"]:
                item["visibility"] = value.record_visibility(item["record_index"])
    # Derived evidence includes source locators as well as retained records.
    # Strip private structured review metadata only after computing identities
    # and all scientific decisions from the untouched originals.
    # Only this freshly rebuilt top-level envelope has its own excerpt policy.
    # Raw records/archive/other nested containers must never republish stored
    # structure_claims or structure_evidence merely because a source is active.
    public = {
        key: (sanitize_review_metadata(item) if key == "structure_evidence"
              else redact_structure_payloads(sanitize_review_metadata(item)))
        if isinstance(item, (dict, list)) else item
        for key, item in payload.items()
    }
    public["review_reason"] = payload["review_reason"]
    return public
