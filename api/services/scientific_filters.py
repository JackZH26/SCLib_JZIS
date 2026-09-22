"""Conservative, same-result predicates for legacy scientific read surfaces.

These references identify a legacy occurrence, not an adjudicated scientific
result. No paper-wide family, catalogue maximum or missing pressure can satisfy
a predicate on a different occurrence. The research loader remains authoritative
for future revisioned result identities and reviewed ML admission.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from services.anomaly_review import assess_record_anomalies, eligible_for_property
from services.claim_outcomes import outcome_conflicts_with_positive
from services.pressure_semantics import classify_pressure, pressure_matches
from services.result_semantics import classify_result
from services.scientific_values import record_quantity

FILTER_POLICY_VERSION = "same-result/1.1.0"


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, OverflowError):
        return None


def tc_lower_bound(record: dict[str, Any]) -> float | None:
    """A supported minimum, never an interval midpoint or censored upper limit.

    Reparse original text/units; cached normalized fields are not authoritative.
    Uncertainty extents are reported extents, not inferred confidence intervals.
    """
    proposal = record_quantity(record, "tc_kelvin", "tc")
    if proposal["status"] != "parsed" or proposal["errors"] or proposal["approximate"]:
        return None
    relation = proposal["relation"]
    declared = record.get("tc_relation") or record.get("value_relation")
    if declared and declared != relation:
        return None
    if relation in ("interval", "gt", "ge"):
        return finite_number(proposal["lower"])
    if relation != "exact":
        return None
    value, uncertainty = finite_number(proposal["value"]), finite_number(proposal["uncertainty"])
    return value - uncertainty if value is not None and uncertainty is not None else value


@dataclass(frozen=True)
class ResultFilters:
    families: tuple[str, ...] = ()
    tc_min: float | None = None
    pressure_min: float | None = None
    pressure_max: float | None = None
    ambient_only: bool = False
    include_unknown_pressure: bool = False
    origins: tuple[str, ...] = ()
    source_role: str | None = None
    experimental_only: bool = False
    only_aps: bool = False
    min_tier: str | None = None
    positive_tc: bool = False

    @property
    def active(self) -> bool:
        return bool(
            self.families or self.tc_min is not None or self.pressure_min is not None
            or self.pressure_max is not None or self.ambient_only or self.origins
            or self.source_role or self.experimental_only or self.only_aps or self.min_tier or self.positive_tc
        )


def matching_result_references(
    records: Any,
    filters: ResultFilters,
    *,
    scope_id: str,
    material_family: str | None = None,
    compound_thresholds: tuple | list = (),
    current_year: int | None = None,
) -> list[dict[str, Any]]:
    """Return all matching occurrences in input order with reproducible IDs.

    Only a material entity's family may supply an absent record family. A
    paper/chunk family is never passed as this fallback. An explicit conflicting
    record family always wins over the catalogue's classification.
    """
    matches = []
    for index, record in enumerate(records if isinstance(records, list) else []):
        if not isinstance(record, dict):
            continue
        family = record.get("family") or record.get("material_family") or material_family
        anomaly = assess_record_anomalies(record, scope_id=scope_id, family=material_family,
                                           compound_thresholds=compound_thresholds,
                                           current_year=datetime.now(UTC).year if current_year is None else current_year)
        if filters.families and family not in filters.families:
            continue
        tc = tc_lower_bound(record)
        if (filters.tc_min is not None or filters.positive_tc) and not eligible_for_property(anomaly, "tc_kelvin"):
            continue
        if filters.ambient_only and not eligible_for_property(anomaly, "tc_ambient"):
            continue
        if (filters.tc_min is not None or filters.positive_tc) and outcome_conflicts_with_positive(record):
            continue
        if filters.positive_tc and (tc is None or tc <= 0):
            continue
        if filters.tc_min is not None and (tc is None or tc < filters.tc_min):
            continue
        origin = classify_result(record)
        if filters.origins and origin.knowledge_origin not in filters.origins:
            continue
        if filters.source_role and origin.source_role != filters.source_role:
            continue
        if filters.experimental_only and (
            origin.knowledge_origin != "Observed" or origin.classification_status != "resolved"
            or origin.source_role == "conflicted"
        ):
            continue
        if filters.only_aps and not str(record.get("paper_id", "")).startswith("aps:"):
            continue
        if filters.min_tier:
            tier = record.get("credibility_tier") or record.get("source_tier")
            allowed = {"T1": {"T1"}, "T2": {"T1", "T2"}, "T3": {"T1", "T2", "T3"}}
            if tier not in allowed[filters.min_tier]:
                continue
        pressure = classify_pressure(record)
        pressure_filter_active = filters.pressure_min is not None or filters.pressure_max is not None or filters.ambient_only
        if pressure_filter_active and not eligible_for_property(anomaly, "pressure_gpa"):
            continue
        if pressure_filter_active and not pressure_matches(
            pressure, max_gpa=filters.pressure_max, min_gpa=filters.pressure_min,
            ambient_only=filters.ambient_only, include_unknown=filters.include_unknown_pressure,
        ):
            continue
        identity_record = {
            k: v for k, v in record.items()
            if k not in {"result_classification", "pressure_semantics", "property_evidence", "anomaly_review", "visibility", "structure_evidence", "ingestion_capture", "temporal_provenance"}
        }
        identity = json.dumps([scope_id, identity_record], sort_keys=True, separators=(",", ":"), default=str)
        matches.append({
            "result_id": "legacy-result:" + hashlib.sha256(identity.encode()).hexdigest(),
            "record_index": index,
            "formula": record.get("formula") if isinstance(record.get("formula"), str) else None,
            "family": family,
            "tc_lower_bound_k": tc,
            "pressure_semantics": pressure.to_dict(),
            "result_classification": origin.as_dict(),
            "filter_policy_version": FILTER_POLICY_VERSION,
            "anomaly_review": anomaly,
        })
    return matches


def supported_ambient_summary(records: Any, stored_tc: Any) -> tuple[float | None, bool | None]:
    """Validate a legacy ambient headline; never create a new maximum/negative."""
    matches = matching_result_references(
        records, ResultFilters(ambient_only=True, experimental_only=True, positive_tc=True), scope_id="ambient-summary",
    )
    positive = [m for m in matches if m["tc_lower_bound_k"] is not None and m["tc_lower_bound_k"] > 0]
    value = finite_number(stored_tc)
    supported = value is not None and any(
        finite_number(records[m["record_index"]].get("tc_kelvin")) == value
        and tc_lower_bound(records[m["record_index"]]) == value for m in positive
    )
    return (value if supported else None, True if positive else None)
