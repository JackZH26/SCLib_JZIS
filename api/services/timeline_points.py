"""Pure Timeline record classification and projection helpers.

Both the legacy JSONB fallback and the materialized projection refresher use
this module. Keeping the filtering and de-duplication rules in one place makes
the two read paths byte-for-byte comparable during rollout.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


TIMELINE_TC_MAX_K = 300.0

_EXPERIMENTAL_MEASUREMENTS = frozenset({
    "resistivity", "susceptibility", "specific_heat",
    "arpes", "musr", "stm", "neutron", "nmr", "nqr",
    "magnetization", "thermal_conductivity",
    "raman scattering", "raman", "andreev reflection",
    "nernst", "tunneling", "esr", "torque magnetometry",
    "hall effect", "hall_effect", "transport",
})

_THEORETICAL_MEASUREMENTS = frozenset({
    "calculation", "dft", "first-principles", "first principles",
    "computational", "ab initio", "ab-initio",
    "allen-dynes", "eliashberg", "tight-binding",
})


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


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_theoretical(record: dict[str, Any]) -> bool:
    """Classify one Tc record using the chart's audited precedence rules."""
    measurement = (record.get("measurement") or "").strip().lower()
    if measurement in _EXPERIMENTAL_MEASUREMENTS:
        return False
    if measurement in _THEORETICAL_MEASUREMENTS:
        return True
    paper_type = (record.get("paper_type") or "").strip().lower()
    if paper_type not in {"theoretical", "computational"}:
        return False
    pressure = as_float(record.get("pressure_gpa"))
    return pressure is not None and pressure > 0


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
) -> str:
    identity = json.dumps(
        [material_id, year, tc_bin, pressure_bin, theoretical],
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def extract_timeline_points(
    material_id: str,
    records: list[Any] | None,
    paper_years: dict[str, int],
    *,
    current_year: int | None = None,
) -> list[ProjectedTimelinePoint]:
    """Validate and de-duplicate all Timeline points for one material."""
    year_hi = (current_year or datetime.now(UTC).year) + 1
    seen: dict[tuple[int, float, int | None, bool], ProjectedTimelinePoint] = {}

    for record in records or []:
        if not isinstance(record, dict):
            continue
        tc = record.get("tc_kelvin")
        paper_id_value = record.get("paper_id")
        paper_id = paper_id_value if isinstance(paper_id_value, str) else None
        year = (
            record.get("year")
            or record.get("measurement_year")
            or (paper_years.get(paper_id) if paper_id else None)
        )
        if tc is None or year is None:
            continue
        try:
            tc_value = float(tc)
            year_value = int(year)
        except (TypeError, ValueError):
            continue
        if tc_value <= 0 or tc_value > TIMELINE_TC_MAX_K:
            continue
        if year_value < 1900 or year_value > year_hi:
            continue

        pressure = as_float(record.get("pressure_gpa"))
        theoretical = is_theoretical(record)
        tc_bin = round(tc_value, 1)
        pressure_bin = round(pressure) if pressure is not None else None
        dedup_key = (year_value, tc_bin, pressure_bin, theoretical)
        if dedup_key in seen:
            continue
        seen[dedup_key] = ProjectedTimelinePoint(
            id=_point_id(
                material_id,
                year_value,
                tc_bin,
                pressure_bin,
                theoretical,
            ),
            material_id=material_id,
            tc_kelvin=tc_value,
            year=year_value,
            pressure_gpa=pressure,
            paper_id=paper_id,
            is_theoretical=theoretical,
            is_aps=is_aps_record(record),
        )

    return sorted(seen.values(), key=lambda point: (point.year, -point.tc_kelvin))
