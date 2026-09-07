"""Pure, provenance-preserving Timeline occurrence extraction.

The Timeline is a reported-result view, not a discovery history or an accepted
result registry. Identical legacy occurrences can consolidate, but numerical
overlap is never evidence that two reported results are the same result.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any

from services.anomaly_review import assess_record_anomalies, eligible_for_property
from services.pressure_semantics import classify_pressure
from services.result_semantics import CLASSIFIER_VERSION, classify_result, is_computed_result
from services.scientific_values import record_quantity

TIMELINE_RESULT_CONTRACT_VERSION = "timeline-result/1.0.0"
_DERIVED_FIELDS = frozenset({
    "result_classification", "pressure_semantics", "property_evidence",
    "anomaly_review", "visibility", "result_metadata", "occurrence_count",
    "review_status", "review_reason", "reviewed_at", "reviewed_by",
    "admin_decision", "review_metadata", "needs_review", "scientific_acceptance",
    "retracted", "disputed", "corrected", "source_status", "validity_status",
})
_STATE_FIELDS = (
    "state_id", "sample_id", "structure_id", "run_id", "formula", "formula_raw",
    "structure_phase", "sample_form", "substrate", "doping_type", "doping_level",
    "magnetic_field_tesla", "strain_percent", "carrier_density_cm3",
)
_LOCATOR_FIELDS = ("page", "table", "figure", "row", "column", "section", "chunk_id", "span_id")
_DECLARED_YEAR_BASES = {
    "measurement": "explicit_measurement_year", "measurement_year": "explicit_measurement_year",
    "explicit_measurement_year": "explicit_measurement_year",
    "report": "explicit_report_year", "report_year": "explicit_report_year",
    "explicit_report_year": "explicit_report_year",
    "publication": "source_publication_year", "publication_year": "source_publication_year",
    "source_publication_year": "source_publication_year",
    "submission": "source_submission_year", "submission_year": "source_submission_year",
    "source_submission_year": "source_submission_year",
}


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
    result_metadata: dict = field(default_factory=dict)


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


def referenced_paper_ids(records: list[Any] | None, *, only_aps: bool = False) -> set[str]:
    """All linked works: source-date metadata matters even with an explicit year."""
    return {
        paper_id for record in _records(records)
        if isinstance(record, dict) and (not only_aps or is_aps_record(record))
        and (paper_id := _text(record.get("paper_id"), 100)) is not None
    }


def missing_year_paper_ids(
    records: list[Any] | None,
    *,
    only_aps: bool = False,
) -> set[str]:
    missing: set[str] = set()
    for record in _records(records):
        if not isinstance(record, dict):
            continue
        if only_aps and not is_aps_record(record):
            continue
        if any(record.get(key) is not None for key in (
            "year", "measurement_year", "measurement_date", "report_year", "report_date",
        )):
            continue
        paper_id = _text(record.get("paper_id"), 100)
        if paper_id is not None:
            missing.add(paper_id)
    return missing


def _records(value: Any) -> list | tuple:
    return value if isinstance(value, (list, tuple)) else ()


def _text(value: Any, limit: int = 160) -> str | None:
    # Omit, never truncate, an identifier into a different identifier.
    if not isinstance(value, str) or len(value) > limit or not value.strip():
        return None
    return value.strip()


def _scalar(value: Any, limit: int = 160) -> str | int | float | None:
    if isinstance(value, str):
        return _text(value, limit)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and as_float(value) is not None:
        return value
    return None


def _year(value: Any) -> int | None:
    # Floats, booleans, decimal strings and numeric coercion are not chronology.
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and len(value) == 4 and value.isascii() and value.isdigit():
        return int(value)
    return None


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not 10 <= len(value) <= 40:
        return None
    try:
        # ISO day or timestamp only: never invent January 1 for a year-only value.
        if len(value) == 10:
            return date.fromisoformat(value)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _source_context(record: dict, paper_value: Any) -> tuple[dict, list[str]]:
    metadata = paper_value if isinstance(paper_value, Mapping) else {}
    warnings: list[str] = []
    source_date = None
    basis = "unknown"
    for key, owner, candidate_basis in (
        ("date_published", record, "publication"),
        ("publication_date", record, "publication"),
        ("date_published", metadata, "publication"),
        ("date_submitted", record, "submission"),
        ("submission_date", record, "submission"),
        ("date_submitted", metadata, "submission"),
    ):
        raw = owner.get(key)
        if raw is None:
            continue
        parsed = _date(raw)
        if parsed is None:
            warnings.append("invalid_source_" + candidate_basis + "_date")
        elif source_date is None:
            source_date, basis = parsed, candidate_basis
        elif candidate_basis == basis and parsed != source_date:
            warnings.append("source_date_assertions_disagree")
    version = _scalar(record.get("source_version"))
    if version is None:
        version = _scalar(metadata.get("source_version"))
    return {
        "source_date": source_date.isoformat() if source_date else None,
        "source_date_basis": basis,
        "source_version": version,
    }, warnings


def _chronology(record: dict, paper_value: Any) -> tuple[int | None, dict]:
    source, warnings = _source_context(record, paper_value)
    candidates: list[tuple[int, str]] = []
    # Precedence is explicit, not truthiness: invalid explicit chronology cannot
    # be replaced silently by a bibliographic fallback.
    for key, basis, date_field in (
        ("measurement_year", "explicit_measurement_year", False),
        ("measurement_date", "explicit_measurement_date", True),
        ("report_year", "explicit_report_year", False),
        ("report_date", "explicit_report_date", True),
        ("year", "legacy_record_year_unspecified", False),
    ):
        raw = record.get(key)
        if raw is None:
            continue
        parsed = _date(raw) if date_field else _year(raw)
        if parsed is None:
            return None, {}
        value = parsed.year if date_field else parsed
        if key == "year" and (declared := _text(record.get("year_basis"), 80)) is not None:
            basis = _DECLARED_YEAR_BASES.get(declared.lower(), basis)
            if declared.lower() not in _DECLARED_YEAR_BASES:
                warnings.append("year_basis_unrecognized")
        candidates.append((value, basis))
    if candidates:
        year, basis = candidates[0]
        if len({value for value, _ in candidates}) > 1:
            warnings.append("chronology_fields_disagree")
    elif source["source_date"] is not None:
        year = int(source["source_date"][:4])
        basis = "source_" + source["source_date_basis"] + "_date"
    else:
        year = _year(paper_value)
        basis = "legacy_source_year" if year is not None else "unknown"
    return year, {**source, "year_basis": basis, "chronology_warnings": sorted(set(warnings))}


def _original_content(value: Any, *, depth: int = 0) -> Any:
    """Canonical JSON identity input, not a public source-payload projection.

    Bounded nesting rejects malformed objects individually. Governance and
    derived envelopes do not create a new scientific occurrence. All other raw
    source content remains in the fingerprint; no formula or number matching.
    """
    if depth > 24:
        raise ValueError("Timeline occurrence nesting exceeds the identity bound")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite occurrence content")
        return value
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Timeline occurrence keys must be strings")
            if key in _DERIVED_FIELDS or key.lower().startswith((
                "reviewer", "curator", "private_review", "internal_review",
            )):
                continue
            result[key] = _original_content(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_original_content(item, depth=depth + 1) for item in value]
    raise ValueError("Timeline occurrence contains a non-JSON value")


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _state(record: dict) -> dict:
    nested = record.get("state") if isinstance(record.get("state"), Mapping) else {}
    return {
        key: value for key in _STATE_FIELDS
        if (value := _scalar(record.get(key) if record.get(key) is not None else nested.get(key))) is not None
    }


def _locator(record: dict) -> dict:
    nested = record.get("source_locator")
    if not isinstance(nested, Mapping):
        return {}
    return {key: value for key in _LOCATOR_FIELDS if (value := _scalar(nested.get(key), 120)) is not None}


def _extract_point(material_id: str, record: dict, paper_years: Mapping, *,
                   year_hi: int, family: str | None, compound_thresholds: tuple | list) -> ProjectedTimelinePoint | None:
    proposal = record_quantity(record, "tc_kelvin", "tc")
    tc = proposal["value"]
    if (tc is None or proposal["status"] != "parsed" or proposal["relation"] != "exact"
            or proposal["errors"] or proposal["approximate"] or proposal["uncertainty"] is not None):
        return None
    tc_value = as_float(tc)
    paper_id = _text(record.get("paper_id"), 100)
    if record.get("paper_id") is not None and paper_id is None:
        return None
    year_value, chronology = _chronology(record, paper_years.get(paper_id) if paper_id else None)
    if tc_value is None or tc_value <= 0 or year_value is None or not 1900 <= year_value <= year_hi:
        return None
    anomalies = assess_record_anomalies(record, scope_id=material_id, family=family,
        compound_thresholds=compound_thresholds, current_year=year_hi - 1)
    if not all(eligible_for_property(anomalies, name) for name in ("tc_kelvin", "year", "pressure_gpa")):
        return None
    pressure = classify_pressure(record)
    classification = classify_result(record)
    raw_fingerprint = _digest([material_id, _original_content(record)])
    supplied_id = _text(record.get("result_id"), 500)
    revision = _scalar(record.get("result_revision"))
    if revision is None:
        revision = _scalar(record.get("revision"))
    result_id = supplied_id or "legacy-timeline-result:" + raw_fingerprint
    metadata = {
        "version": TIMELINE_RESULT_CONTRACT_VERSION,
        "result_id": result_id,
        "result_revision": revision,
        "identity_basis": "result_revision_content" if supplied_id else "legacy_occurrence_content",
        "identity_conflict": False,
        "identity_warnings": [],
        **chronology,
        "state": _state(record),
        "tc_criterion": _text(record.get("tc_criterion"), 120) or _text(record.get("tc_type"), 120) or "unknown",
        "source_locator": _locator(record),
        "occurrence_count": 1,
        "review_status": "legacy_unreviewed",
    }
    point_id = _digest([TIMELINE_RESULT_CONTRACT_VERSION, material_id, result_id, revision,
                        raw_fingerprint, year_value, chronology])
    pressure_metadata = pressure.to_dict()
    # Pressure source locators can contain arbitrary input dictionaries; the
    # public Timeline exposes only bounded scientific locator coordinates.
    pressure_metadata["source_locator"] = _locator({"source_locator": pressure_metadata.get("source_locator")})
    return ProjectedTimelinePoint(
        id=point_id, material_id=material_id, tc_kelvin=tc_value, year=year_value,
        pressure_gpa=pressure.pressure_gpa if pressure.pressure_state in {"reported", "explicit_ambient"} else None,
        paper_id=paper_id, is_theoretical=is_theoretical(record), is_aps=is_aps_record(record),
        knowledge_origin=classification.knowledge_origin,
        classification_status=classification.classification_status,
        source_role=classification.source_role,
        pressure_semantics=pressure_metadata, result_metadata=metadata,
    )


def extract_timeline_points(
    material_id: str,
    records: list[Any] | None,
    paper_years: Mapping[str, Any],
    *,
    current_year: int | None = None,
    family: str | None = None,
    compound_thresholds: tuple | list = (),
) -> list[ProjectedTimelinePoint]:
    """Keep provenance-distinct results; consolidate only identical occurrences.

    Malformed inputs are omitted individually, never repaired or written back.
    Parent/source visibility remains the caller's separate, mandatory policy.
    """
    year_hi = (current_year or datetime.now(UTC).year) + 1
    seen: dict[str, ProjectedTimelinePoint] = {}

    for record in _records(records):
        if not isinstance(record, dict):
            continue
        try:
            point = _extract_point(material_id, record, paper_years, year_hi=year_hi,
                family=family, compound_thresholds=compound_thresholds)
        except (TypeError, ValueError, OverflowError, RecursionError):
            # Source JSONB can contain malformed nested scientific notation.
            # One occurrence must not fail the complete response or refresh.
            continue
        if point is None:
            continue
        if point.id in seen:
            previous = seen[point.id]
            seen[point.id] = replace(previous, result_metadata={**previous.result_metadata,
                "occurrence_count": previous.result_metadata["occurrence_count"] + 1})
        else:
            seen[point.id] = point

    supplied_identities: dict[tuple, list[str]] = {}
    for point in seen.values():
        metadata = point.result_metadata
        if metadata["identity_basis"] == "result_revision_content":
            key = (metadata["result_id"], metadata["result_revision"])
            supplied_identities.setdefault(key, []).append(point.id)
    for identities in supplied_identities.values():
        if len(identities) < 2:
            continue
        for point_id in identities:
            point = seen[point_id]
            seen[point_id] = replace(point, result_metadata={**point.result_metadata,
                "identity_conflict": True,
                "identity_warnings": ["supplied_result_revision_has_conflicting_occurrences"]})
    return sorted(seen.values(), key=lambda point: (point.year, -point.tc_kelvin, point.id))
