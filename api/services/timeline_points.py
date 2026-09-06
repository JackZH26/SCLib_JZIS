"""Pure Timeline record classification and projection helpers.

Both the legacy JSONB fallback and the materialized projection refresher use
this module. Keeping the filtering and de-duplication rules in one place makes
the two read paths byte-for-byte comparable during rollout.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from services.anomaly_review import (
    ANOMALY_POLICY_VERSION,
    assess_record_anomalies,
    eligible_for_property,
)
from services.pressure_semantics import PRESSURE_POLICY_VERSION, classify_pressure
from services.result_semantics import CLASSIFIER_VERSION, classify_result, is_computed_result
from services.scientific_values import record_quantity


@dataclass(frozen=True, slots=True)
class ProjectedTimelinePoint:
    id: str
    material_id: str
    tc_kelvin: float
    year: int
    pressure_gpa: float | None
    paper_id: str | None
    is_theoretical: bool
    is_aps: bool
    knowledge_origin: str = "Unknown"
    classification_status: str = "unknown"
    source_role: str = "unknown"
    classifier_version: str = CLASSIFIER_VERSION
    pressure_semantics: dict = field(default_factory=dict)


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def is_theoretical(record: dict[str, Any]) -> bool:
    """Compatibility flag only; its negation is not an Observed predicate."""
    return is_computed_result(record)


def is_aps_record(record: dict[str, Any]) -> bool:
    paper_id = record.get("paper_id")
    return isinstance(paper_id, str) and paper_id.startswith("aps:")


def missing_year_paper_ids(
    records: list[Any] | None,
    *,
    only_aps: bool = False,
) -> set[str]:
    missing: set[str] = set()
    for record in records or []:
        if not isinstance(record, dict):
            continue
        if only_aps and not is_aps_record(record):
            continue
        if record.get("year") is not None or record.get("measurement_year") is not None:
            continue
        paper_id = record.get("paper_id")
        if isinstance(paper_id, str):
            missing.add(paper_id)
    return missing


def _point_id(
    material_id: str,
    year: int,
    tc_bin: float,
    pressure_bin: int | None,
    theoretical: bool,
    classification: tuple[str, str, str],
    pressure_key: str,
) -> str:
    identity = json.dumps(
        [material_id, year, tc_bin, pressure_bin, theoretical, classification, CLASSIFIER_VERSION, pressure_key, PRESSURE_POLICY_VERSION, ANOMALY_POLICY_VERSION],
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def extract_timeline_points(
    material_id: str,
    records: list[Any] | None,
    paper_years: dict[str, int],
    *,
    current_year: int | None = None,
    family: str | None = None,
    compound_thresholds: tuple | list = (),
) -> list[ProjectedTimelinePoint]:
    """Validate and de-duplicate all Timeline points for one material."""
    year_hi = (current_year or datetime.now(UTC).year) + 1
    seen: dict[tuple, ProjectedTimelinePoint] = {}

    for record in records or []:
        if not isinstance(record, dict):
            continue
        proposal = record_quantity(record, "tc_kelvin", "tc")
        tc = proposal["value"]
        paper_id_value = record.get("paper_id")
        paper_id = paper_id_value if isinstance(paper_id_value, str) else None
        year = (
            record.get("year")
            or record.get("measurement_year")
            or (paper_years.get(paper_id) if paper_id else None)
        )
        if (tc is None or year is None or proposal["status"] != "parsed" or proposal["relation"] != "exact"
                or proposal["errors"] or proposal["approximate"] or proposal["uncertainty"] is not None):
            continue
        tc_value = as_float(tc)
        if tc_value is None or isinstance(year, bool):
            continue
        try:
            year_value = int(year)
            if float(year) != year_value:
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        assessment = assess_record_anomalies(record, scope_id=material_id, family=family,
                                              compound_thresholds=compound_thresholds, current_year=year_hi - 1)
        if tc_value <= 0 or not all(eligible_for_property(assessment, field) for field in ("tc_kelvin", "year", "pressure_gpa")):
            continue
        if year_value < 1900 or year_value > year_hi:
            continue

        assessment = classify_pressure(record)
        pressure_metadata = assessment.to_dict()
        pressure = assessment.pressure_gpa if assessment.pressure_state in {"reported", "explicit_ambient"} else None
        pressure_key = json.dumps(pressure_metadata, sort_keys=True, separators=(",", ":"))
        classification = classify_result(record)
        classification_key = (
            classification.knowledge_origin, classification.classification_status,
            classification.source_role,
        )
        theoretical = is_theoretical(record)
        tc_bin = round(tc_value, 1)
        pressure_bin = round(pressure) if pressure is not None else None
        dedup_key = (year_value, tc_bin, pressure_bin, theoretical, classification_key, pressure_key)
        if dedup_key in seen:
            continue
        seen[dedup_key] = ProjectedTimelinePoint(
            id=_point_id(
                material_id,
                year_value,
                tc_bin,
                pressure_bin,
                theoretical,
                classification_key,
                pressure_key,
            ),
            material_id=material_id,
            tc_kelvin=tc_value,
            year=year_value,
            pressure_gpa=pressure,
            paper_id=paper_id,
            is_theoretical=theoretical,
            is_aps=is_aps_record(record),
            knowledge_origin=classification.knowledge_origin,
            classification_status=classification.classification_status,
            source_role=classification.source_role,
            pressure_semantics=pressure_metadata,
        )

    return sorted(seen.values(), key=lambda point: (point.year, -point.tc_kelvin))
