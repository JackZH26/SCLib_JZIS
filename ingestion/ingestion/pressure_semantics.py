"""Canonical, stdlib-only pressure semantics shared byte-for-byte with API.

This classifies reported pressure information, not scientific validity. Numeric
legacy zero is not evidence of ambient pressure. Explicit ambient is represented
as 0 GPa under the catalog's ambient-reference convention, not as zero absolute
thermodynamic pressure. Bounds and uncertainty are never replaced by midpoints.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

PRESSURE_POLICY_VERSION = "pressure-policy/1.0.0"
_STATES = {"explicit_ambient", "reported", "not_reported", "ambiguous"}
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_POINT = re.compile(rf"^({_NUMBER})\s*(.*?)$")
_INTERVAL = re.compile(rf"^({_NUMBER})\s*(?:–|—|-|to)\s*({_NUMBER})\s*(.*?)$")
_BOUND = re.compile(rf"^(<=|>=|<|>|≤|≥)\s*({_NUMBER})\s*(.*?)$")
_UNCERTAINTY = re.compile(rf"^({_NUMBER})\s*(?:±|\+/-)\s*({_NUMBER})\s*(.*?)$")
_APPROX = re.compile(r"^(?:~|≈|about\s+|approximately\s+)", re.IGNORECASE)
_AMBIENT = re.compile(
    r"^(?:(?:at\s+)?(?:ambient|atmospheric)(?:\s+pressure)?|zero\s+pressure|"
    r"p\s*=\s*0(?:\.0+)?(?:\s*gpa)?)$",
    re.IGNORECASE,
)
_FACTORS = {
    "GPa": 1,
    "gpa": 1,
    "MPa": 0.001,
    "kPa": 0.000001,
    "Pa": 1e-9,
    "bar": 0.0001,
    "kbar": 0.1,
    "atm": 0.000101325,
}
_RELATIONS = {"<": "lt", "<=": "le", "≤": "le", ">": "gt", ">=": "ge", "≥": "ge"}


def _raw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _raw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_raw_json(item) for item in value]
    if isinstance(value, (float, Decimal)):
        try:
            number = float(value)
            return number if math.isfinite(number) else str(value)
        except (OverflowError, ValueError):
            return str(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return repr(value)


@dataclass(frozen=True)
class PressureAssessment:
    pressure_state: str
    pressure_gpa: float | None = None
    relation: str = "unreported"
    value_lower_gpa: float | None = None
    value_upper_gpa: float | None = None
    uncertainty_gpa: float | None = None
    uncertainty_interpretation: str | None = None
    raw_value: Any = None
    raw_unit: Any = None
    unit_basis: str = "unreported"
    approximate: bool = False
    source_locator: Any = None
    reasons: tuple[str, ...] = ()
    classifier_version: str = PRESSURE_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        return result


def _quantity_source(record: Mapping[str, Any]) -> tuple[Any, Any, Any, str | None]:
    values = record.get("scientific_values")
    proposal = values.get("pressure_gpa") if isinstance(values, Mapping) else None
    if isinstance(values, Mapping) and "pressure_gpa" in values and (
        not isinstance(proposal, Mapping) or "raw_value" not in proposal
    ):
        # A typed proposal may describe a range or unresolved evidence. Its
        # compatibility scalar cannot recover the missing original quantity.
        return (
            proposal,
            proposal.get("input_unit", proposal.get("raw_unit"))
            if isinstance(proposal, Mapping) else None,
            proposal.get("source_locator") if isinstance(proposal, Mapping) else None,
            "missing_raw_proposal",
        )
    if isinstance(proposal, Mapping) and "raw_value" in proposal:
        return (
            proposal["raw_value"],
            proposal.get("input_unit", proposal.get("raw_unit")),
            proposal.get("source_locator"),
            None,
        )
    key = "pressure_gpa" if record.get("pressure_gpa") is not None else "pressure"
    return (
        record.get(key),
        record.get(f"{key}_unit", record.get("pressure_unit")),
        record.get("source_locator"),
        None,
    )


def _parse(raw: Any, raw_unit: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "relation": "unreported",
        "value": None,
        "lower": None,
        "upper": None,
        "uncertainty": None,
        "approximate": False,
        "unit": raw_unit,
        "unit_basis": "unreported",
        "error": None,
    }
    if raw is None or raw == "":
        return parsed
    if isinstance(raw, bool):
        return {**parsed, "error": "boolean_not_pressure"}
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        if len(raw) != 2:
            return {**parsed, "error": "unsupported_pressure_sequence"}
        endpoints = [_parse(value, raw_unit) for value in raw]
        if any(
            e["error"]
            or e["relation"] != "exact"
            or e["uncertainty"] is not None
            or e["approximate"]
            for e in endpoints
        ):
            return {**parsed, "error": "invalid_pressure_interval_endpoints"}
        lower, upper = [e["value"] for e in endpoints]
        if lower is None or upper is None or lower > upper:
            return {**parsed, "error": "reversed_or_missing_pressure_interval"}
        return {
            **parsed,
            "relation": "interval",
            "lower": lower,
            "upper": upper,
            "unit_basis": "endpoint_units",
        }
    if not isinstance(raw, (str, int, float, Decimal)):
        return {**parsed, "error": "unsupported_pressure_type"}
    text = str(raw).strip().replace("−", "-")
    if _AMBIENT.fullmatch(text):
        if raw_unit is not None and str(raw_unit).strip() not in _FACTORS:
            return {**parsed, "error": "pressure_unit_mismatch"}
        return {
            **parsed,
            "relation": "exact",
            "value": 0.0,
            "unit_basis": "explicit_ambient_reference",
            "ambient_phrase": True,
        }
    match = _APPROX.match(text)
    if match:
        parsed["approximate"] = True
        text = text[match.end() :].strip()
    relation, tokens, inline_unit = "exact", {}, ""
    if match := _UNCERTAINTY.fullmatch(text):
        tokens, inline_unit = {"value": match[1], "uncertainty": match[2]}, match[3]
    elif match := _BOUND.fullmatch(text):
        relation = _RELATIONS[match[1]]
        tokens = {"upper" if relation in {"lt", "le"} else "lower": match[2]}
        inline_unit = match[3]
    elif match := _INTERVAL.fullmatch(text):
        relation = "interval"
        tokens, inline_unit = {"lower": match[1], "upper": match[2]}, match[3]
    elif match := _POINT.fullmatch(text):
        tokens, inline_unit = {"value": match[1]}, match[2]
    else:
        return {**parsed, "error": "unparseable_pressure"}
    unit = str(raw_unit).strip() if raw_unit is not None else ""
    inline_unit = inline_unit.strip()
    if (
        inline_unit
        and unit
        and (
            inline_unit not in _FACTORS
            or unit not in _FACTORS
            or _FACTORS[inline_unit] != _FACTORS[unit]
        )
    ):
        return {**parsed, "error": "conflicting_pressure_units"}
    unit = inline_unit or unit
    if unit and unit not in _FACTORS:
        return {**parsed, "error": "pressure_unit_mismatch"}
    factor = Decimal(str(_FACTORS[unit])) if unit else Decimal(1)
    try:
        numbers = {key: float(Decimal(value) * factor) for key, value in tokens.items()}
    except (ValueError, OverflowError, InvalidOperation):
        return {**parsed, "error": "nonfinite_pressure"}
    if any(not math.isfinite(value) for value in numbers.values()):
        return {**parsed, "error": "nonfinite_pressure"}
    if numbers.get("uncertainty", 0) < 0:
        return {**parsed, "error": "negative_pressure_uncertainty"}
    if relation == "interval" and numbers["lower"] > numbers["upper"]:
        return {**parsed, "error": "reversed_pressure_interval"}
    return {
        **parsed,
        **numbers,
        "relation": relation,
        "unit": raw_unit if raw_unit is not None else (inline_unit or None),
        "unit_basis": "explicit" if unit else "field_schema_assumption",
    }


def classify_pressure(record: Mapping[str, Any]) -> PressureAssessment:
    """Classify original record evidence, ignoring derived envelopes.

    ``pressure_condition`` is a direct condition assertion; its legacy
    ``*_normalized`` derivative, ambient_sc, bulk/sample form and pressure_type
    are not evidence. Explicit state alone with no quantity remains ambiguous.
    """
    # Specialized hydride rows store original structured proposals in
    # provenance. Prefer those over their compatibility scalar columns.
    provenance = record.get("provenance")
    proposal = provenance.get("extraction_proposal") if isinstance(provenance, Mapping) else None
    if isinstance(proposal, Mapping) and isinstance(proposal.get("raw_extraction"), Mapping):
        record = {
            **proposal["raw_extraction"],
            "scientific_values": proposal.get("scientific_values", {}),
        }
    raw, raw_unit, locator, source_error = _quantity_source(record)
    parsed = (
        {**_parse(None, raw_unit), "error": source_error}
        if source_error else _parse(raw, raw_unit)
    )
    state_claim = str(record.get("pressure_state") or "").strip().lower()
    condition = record.get("pressure_condition")
    condition_ambient = (
        isinstance(condition, str) and _AMBIENT.fullmatch(condition.strip()) is not None
    )
    reasons: list[str] = []
    state = "reported"
    if parsed["error"]:
        state = "ambiguous"
        reasons.append(parsed["error"])
    elif parsed["relation"] == "unreported":
        if condition_ambient:
            parsed.update(relation="exact", value=0.0, unit_basis="explicit_ambient_reference")
            state = "explicit_ambient"
            reasons.append("explicit_pressure_condition")
        elif state_claim in {"explicit_ambient", "reported", "ambiguous"}:
            state = "ambiguous"
            reasons.append(
                "explicit_ambient_missing_numeric_pressure"
                if state_claim == "explicit_ambient"
                else "reported_pressure_missing_value"
                if state_claim == "reported"
                else "declared_ambiguous_pressure"
            )
        else:
            state = "not_reported"
            reasons.append("pressure_not_reported")
    elif any(parsed[key] is not None and parsed[key] < 0 for key in ("value", "lower", "upper")):
        state = "ambiguous"
        reasons.append("unsupported_negative_pressure")
    elif parsed.get("ambient_phrase"):
        state = "explicit_ambient"
        reasons.append("explicit_ambient_phrase")
    elif parsed["relation"] == "exact" and parsed["value"] == 0:
        if (
            (condition_ambient or state_claim == "explicit_ambient")
            and not parsed["approximate"]
            and parsed["uncertainty"] is None
        ):
            state = "explicit_ambient"
            reasons.append("explicit_ambient_zero_assertion")
        else:
            state = "ambiguous"
            reasons.append("legacy_zero_pressure_not_explicitly_ambient")
    elif condition_ambient or state_claim == "explicit_ambient":
        state = "ambiguous"
        reasons.append("ambient_assertion_conflicts_with_pressure")
    if state_claim in {"not_reported", "ambiguous"} and parsed["relation"] != "unreported":
        state = "ambiguous"
        reasons.append(
            "pressure_state_conflicts_with_value"
            if state_claim == "not_reported"
            else "declared_ambiguous_pressure"
        )
    if state_claim and state_claim not in _STATES:
        state = "ambiguous"
        reasons.append("unknown_pressure_state")
    if parsed["unit_basis"] == "field_schema_assumption":
        reasons.append("legacy_field_unit_assumed_gpa")
    if parsed["uncertainty"] is not None:
        reasons.append("reported_uncertainty_interpretation_unspecified")
    if parsed["approximate"]:
        reasons.append("approximate_pressure")
    return PressureAssessment(
        pressure_state=state,
        pressure_gpa=parsed["value"],
        relation=parsed["relation"],
        value_lower_gpa=parsed["lower"],
        value_upper_gpa=parsed["upper"],
        uncertainty_gpa=parsed["uncertainty"],
        uncertainty_interpretation="unspecified" if parsed["uncertainty"] is not None else None,
        raw_value=_raw_json(raw),
        raw_unit=_raw_json(parsed["unit"]),
        unit_basis=parsed["unit_basis"],
        approximate=parsed["approximate"],
        source_locator=_raw_json(locator or {}),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def pressure_matches(
    assessment: PressureAssessment,
    *,
    max_gpa: float | None = None,
    min_gpa: float | None = None,
    ambient_only: bool = False,
    include_unknown: bool = False,
) -> bool:
    """Match only when the entire reported extent satisfies every bound.

    A +/- quantity is tested over its reported extent, not assigned an invented
    confidence level. Approximate points without an extent cannot prove a numeric
    bound. Unknown inclusion is explicit; unsupported negative pressure is never
    admitted as ambient or as an unknown conventional-pressure candidate.
    """
    for limit in (max_gpa, min_gpa):
        if limit is not None and (
            isinstance(limit, bool)
            or not isinstance(limit, (int, float))
            or not math.isfinite(limit)
        ):
            raise ValueError("Pressure bounds must be finite numeric values")
    if max_gpa is not None and min_gpa is not None and min_gpa > max_gpa:
        raise ValueError("min_gpa must not exceed max_gpa")
    if max_gpa is None and min_gpa is None and not ambient_only:
        return True
    if "unsupported_negative_pressure" in assessment.reasons:
        return False
    if assessment.pressure_state in {"not_reported", "ambiguous"}:
        return include_unknown
    if ambient_only and assessment.pressure_state != "explicit_ambient":
        return False
    if max_gpa is None and min_gpa is None:
        return True
    if assessment.approximate and assessment.uncertainty_gpa is None:
        return False
    lower, upper = assessment.value_lower_gpa, assessment.value_upper_gpa
    if assessment.pressure_gpa is not None:
        spread = assessment.uncertainty_gpa or 0
        lower, upper = assessment.pressure_gpa - spread, assessment.pressure_gpa + spread
    if max_gpa is not None and (upper is None or upper > max_gpa):
        return False
    return not (min_gpa is not None and (lower is None or lower < min_gpa))


def annotate_pressure_records(records: Sequence[Any]) -> list[Any]:
    """Return copies with derived envelopes; never mutate original records."""
    return [
        {**record, "pressure_semantics": classify_pressure(record).to_dict()}
        if isinstance(record, Mapping)
        else record
        for record in records
    ]


__all__ = [
    "PRESSURE_POLICY_VERSION",
    "PressureAssessment",
    "annotate_pressure_records",
    "classify_pressure",
    "pressure_matches",
]
