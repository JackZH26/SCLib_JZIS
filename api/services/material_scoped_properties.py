"""Current atomic summaries for the explicit source-scoped catalogue policy.

This does not change the legacy property projector or frozen release compilers.
Each value still belongs to one reported result, not a synthesized joint state.
"""
from __future__ import annotations

from services.property_evidence import EVIDENCE_LIMIT, build_property_evidence
from services.result_semantics import classify_result

SCOPED_SELECTION_POLICY = "source-scoped-atomic-selection/1.0.0"


def scoped_property_evidence(records, *, scope_id, property_fields, include_joint_epc, anomaly_context):
    envelope = build_property_evidence(
        records, scope_id=scope_id, property_fields=property_fields,
        include_joint_epc=include_joint_epc, anomaly_context=anomaly_context,
    )
    # A historical cached headline may belong exclusively to a held source.
    # Re-select from eligible atomic records, preferring resolved observations
    # over calculations. No unknown origin becomes an observed measurement.
    if "tc_max" in property_fields:
        pools = {origin: [] for origin in ("Observed", "Computed")}
        for record in records:
            classification = classify_result(record)
            if (classification.knowledge_origin in pools
                    and classification.classification_status == "resolved"
                    and classification.source_role != "conflicted"):
                pools[classification.knowledge_origin].append(record)
        selected = None
        for origin in ("Observed", "Computed"):
            candidate = build_property_evidence(
                pools[origin], scope_id=scope_id, property_fields=["tc_max"],
                include_joint_epc=False, anomaly_context=anomaly_context,
            )["properties"]["tc_max"]
            if selected is None or candidate["status"] == "supported":
                selected = candidate
            if candidate["status"] == "supported":
                break
        headline = envelope["properties"]["tc_max"]
        # Keep the bounded eligible-source alternatives across origins. The
        # chosen headline is not a reason to erase a calculated/unknown result.
        headline["selected"] = selected["selected"]
        headline["selection"] = selected["selection"]
        headline["status"] = ("supported" if selected["selected"] else
                              "pending" if headline["total_evidence_count"] else "not_reported")
        headline["warnings"] = sorted(set(selected["warnings"] + ["headline_prefers_resolved_observation_then_calculation"]))
        if selected["selected"]:
            headline["evidence"] = [selected["selected"]] + [
                item for item in headline["evidence"] if item["result_id"] != selected["selected"]["result_id"]
            ][:EVIDENCE_LIMIT - 1]
    envelope["selection_policy"] = SCOPED_SELECTION_POLICY
    envelope["warnings"] = sorted(set(envelope["warnings"] + [
        "source_scoped_reported_records_only", "not_independent_replication_or_scientific_approval",
    ]))
    return envelope
