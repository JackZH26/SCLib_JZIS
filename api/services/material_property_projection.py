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
from services.property_evidence import PROPERTY_FIELDS, build_property_evidence


def project_material_properties(
    value: Any,
    field_names: Iterable[str],
    *,
    scope_id: str | None = None,
    compact: bool = False,
) -> dict[str, Any]:
    """Bind existing selections without resurrecting capped/hidden values.

    A missing aggregate stays missing even when other raw results exist.
    Unsupported historical scalars become null in this *response*, with the
    reason and independently browsable evidence retained in the envelope.
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
    records = raw_records if isinstance(raw_records, list) else []
    identity = scope_id or str(payload.get("id") or "unknown-material")
    context = review_context(value)
    envelope = build_property_evidence(
        records, scope_id=identity, legacy_summary=payload,
        property_fields=[field for field in PROPERTY_FIELDS if field in names],
        include_joint_epc=not compact,
        anomaly_context=context,
    )
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
    if not compact and "records" in names:
        payload["records"] = [
            {**record, "anomaly_review": record_assessment(record, scope_id=identity, context=context)}
            for record in records if isinstance(record, dict)
        ]
        payload["raw_archive"] = retained_record_archive(records, scope_id=identity, context=context)
    return payload
