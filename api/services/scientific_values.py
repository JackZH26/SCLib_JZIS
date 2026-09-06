"""Raw-preserving, deterministic scientific quantity normalization.

This is a proposal parser, not scientific validation. Units omitted from a
legacy field use that field's documented unit, explicitly marked as a schema
assumption. A numeric legacy record cannot prove that an older parser did not
already discard units; callers must not confuse parsing with source review.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

PARSER_VERSION = "scientific-value/1.0.0"

FIELD_UNITS = {
    "tc_kelvin": "K",
    "minimum_temperature_k": "K",
    "temperature_k": "K",
    "measurement_temperature_k": "K",
    "hc2_temperature_k": "K",
    "omega_log_k": "K",
    "t_cdw_k": "K",
    "t_sdw_k": "K",
    "t_afm_k": "K",
    "pressure_gpa": "GPa",
    "hc2_tesla": "T",
    "magnetic_field_t": "T",
    "lattice_a": "angstrom",
    "lattice_b": "angstrom",
    "lattice_c": "angstrom",
    "lattice_alpha": "degree",
    "lattice_beta": "degree",
    "lattice_gamma": "degree",
    "lambda_london_nm": "nm",
    "xi_gl_nm": "nm",
    "layer_thickness_nm": "nm",
    "rho_s_mev": "meV",
    "lambda_eph": "1",
    "rho_exponent": "1",
    "doping_level": "1",
    "confidence": "1",
    "mu_star": "1",
    "omega_log_source_value": "K",
}
# Unit spelling is intentionally case-sensitive where SI prefixes differ.
_UNITS = {
    "K": {"K": 1, "k": 1, "kelvin": 1, "Kelvin": 1, "mK": 0.001},
    "GPa": {
        "GPa": 1,
        "gpa": 1,
        "MPa": 0.001,
        "kPa": 0.000001,
        "Pa": 1e-9,
        "bar": 0.0001,
        "kbar": 0.1,
        "atm": 0.000101325,
    },
    "T": {"T": 1, "t": 1, "tesla": 1, "Tesla": 1, "mT": 0.001},
    "angstrom": {"angstrom": 1, "angstroms": 1, "Å": 1, "Å": 1, "nm": 10, "pm": 0.01},
    "nm": {"nm": 1, "pm": 0.001, "angstrom": 0.1, "angstroms": 0.1, "Å": 0.1, "Å": 0.1},
    "degree": {"degree": 1, "degrees": 1, "deg": 1, "°": 1},
    "meV": {"meV": 1, "eV": 1000},
    "1": {"1": 1, "dimensionless": 1},
}
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_RELATION = {"<": "lt", "<=": "le", "≤": "le", ">": "gt", ">=": "ge", "≥": "ge"}
_SCALAR = re.compile(rf"^({_NUMBER})\s*([^\d\s].*?)?$")
_BOUND = re.compile(rf"^(<=|>=|<|>|≤|≥)\s*({_NUMBER})\s*(.*?)$")
_RANGE = re.compile(rf"^({_NUMBER})\s*(?:–|—|-|to)\s*({_NUMBER})\s*(.*?)$")
_UNCERTAINTY = re.compile(rf"^({_NUMBER})\s*(?:±|\+/-)\s*({_NUMBER})\s*(.*?)$")
_APPROX = re.compile(r"^(?:~|≈|about\s+|approximately\s+)", re.IGNORECASE)


def json_safe_raw(value: Any) -> Any:
    """Keep otherwise non-JSON numeric failures as diagnostic text, not NaN."""
    if isinstance(value, Mapping):
        return {str(k): json_safe_raw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_raw(v) for v in value]
    if isinstance(value, (float, Decimal)):
        return float(value) if math.isfinite(value) else str(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return repr(value)


def parse_scientific_value(
    raw: Any,
    field: str,
    *,
    raw_unit: str | None = None,
    source_context: str | None = None,
    source_locator: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize one quantity without coercing ranges/bounds to point labels.

    Supported uncertainty notation is symmetric ``x ± u``. Its statistical
    interpretation remains unspecified, never silently one standard deviation.
    Units on both interval endpoints can be expressed as a two-item sequence.
    Unsupported syntax remains an invalid proposal with its complete raw input.
    """
    if field not in FIELD_UNITS:
        raise ValueError(f"Unknown scientific field: {field}")
    canonical = FIELD_UNITS[field]
    result: dict[str, Any] = {
        "parser_version": PARSER_VERSION,
        "field": field,
        "raw_value": json_safe_raw(raw),
        "raw_unit": raw_unit,
        "input_unit": raw_unit,
        "source_context": source_context,
        "source_locator": json_safe_raw(source_locator or {}),
        "status": "unreported",
        "relation": "unreported",
        "value_kind": "unreported",
        "value": None,
        "lower": None,
        "upper": None,
        "uncertainty": None,
        "uncertainty_interpretation": None,
        "approximate": False,
        "unit": canonical,
        "unit_basis": "unreported",
        "errors": [],
    }
    result["proposal_hash"] = hashlib.sha256(
        json.dumps(
            {
                k: result[k]
                for k in ("field", "raw_value", "raw_unit", "source_context", "source_locator")
            },
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()

    def invalid(reason: str) -> dict[str, Any]:
        result.update(
            status="invalid",
            errors=[reason],
            relation="unreported",
            value_kind="unreported",
            value=None,
            lower=None,
            upper=None,
        )
        return result

    if raw is None or raw == "":
        return result
    if isinstance(raw, bool):
        return invalid("boolean_not_quantity")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        if len(raw) != 2:
            return invalid("unsupported_quantity_sequence")
        endpoints = [parse_scientific_value(v, field, raw_unit=raw_unit) for v in raw]
        if not all(
            e["status"] == "parsed" and e["relation"] == "exact"
            and e["uncertainty"] is None and not e["approximate"]
            for e in endpoints
        ):
            return invalid("invalid_interval_endpoints")
        lower, upper = [e["value"] for e in endpoints]
        if lower > upper:
            return invalid("reversed_interval")
        result.update(
            status="parsed",
            relation="interval",
            value_kind="interval",
            lower=lower,
            upper=upper,
            unit_basis="endpoint_units",
            endpoint_proposals=endpoints,
        )
        return result
    if not isinstance(raw, (int, float, Decimal, str)):
        return invalid("unsupported_quantity_type")
    if isinstance(raw, (int, float, Decimal)):
        try:
            if not math.isfinite(float(raw)):
                return invalid("nonfinite_quantity")
        except (OverflowError, ValueError):
            return invalid("nonfinite_quantity")
    text = str(raw).strip().replace("−", "-")
    approx = _APPROX.match(text)
    if approx:
        result["approximate"] = True
        text = text[approx.end() :].strip()

    relation, kind, values, inline_unit = "exact", "point", {}, ""
    match = _UNCERTAINTY.fullmatch(text)
    if match:
        values = {"value": match[1], "uncertainty": match[2]}
        inline_unit = match[3]
        kind = "point_with_uncertainty"
        result["uncertainty_interpretation"] = "unspecified"
    elif match := _BOUND.fullmatch(text):
        relation = _RELATION[match[1]]
        kind = "upper_bound" if relation in {"lt", "le"} else "lower_bound"
        values = {"upper" if relation in {"lt", "le"} else "lower": match[2]}
        inline_unit = match[3]
    elif match := _RANGE.fullmatch(text):
        relation, kind = "interval", "interval"
        values, inline_unit = {"lower": match[1], "upper": match[2]}, match[3]
    elif match := _SCALAR.fullmatch(text):
        values, inline_unit = {"value": match[1]}, match[2] or ""
    else:
        return invalid("unsupported_quantity_syntax")

    inline_unit = inline_unit.strip()
    explicit_unit = str(raw_unit).strip() if raw_unit is not None else ""
    aliases = _UNITS[canonical]
    if field == "omega_log_source_value":
        # Explicit hydride energy/frequency convention, not a generic K<->Hz
        # coercion. Preserve the historical conversion constants/version.
        aliases = {**aliases, "meV": 11.6045, "cm^-1": 1.43877, "THz": 47.9924}
        result["conversion_convention"] = "energy/k_B; cyclic_frequency*h/k_B; wavenumber*h*c/k_B"
    if field == "doping_level":
        aliases = {**aliases, "%": 0.01}
    if (
        inline_unit
        and explicit_unit
        and (
            inline_unit not in aliases
            or explicit_unit not in aliases
            or aliases[inline_unit] != aliases[explicit_unit]
        )
    ):
        return invalid("conflicting_units")
    unit = inline_unit or explicit_unit
    if field == "omega_log_source_value" and not unit:
        return invalid("missing_source_unit")
    if unit and unit not in aliases:
        return invalid("unit_mismatch")
    factor = aliases[unit] if unit else 1
    result["raw_unit"] = raw_unit if raw_unit is not None else (inline_unit or None)
    result["unit_basis"] = (
        "explicit" if unit else ("dimensionless" if canonical == "1" else "field_schema_assumption")
    )
    try:
        converted = {
            key: float(Decimal(value) * Decimal(str(factor))) for key, value in values.items()
        }
    except (OverflowError, ValueError):
        return invalid("nonfinite_quantity")
    if not all(math.isfinite(number) for number in converted.values()):
        return invalid("nonfinite_quantity")
    if "uncertainty" in converted and converted["uncertainty"] < 0:
        return invalid("negative_uncertainty")
    if relation == "interval" and converted["lower"] > converted["upper"]:
        return invalid("reversed_interval")
    result.update(converted)
    result.update(status="parsed", relation=relation, value_kind=kind)
    return result


def record_quantity(record: Mapping[str, Any], field: str, *aliases: str) -> dict[str, Any]:
    """Reparse preserved raw proposals; never trust stored normalized values."""
    proposals = record.get("scientific_values")
    proposal = proposals.get(field) if isinstance(proposals, Mapping) else None
    if isinstance(proposals, Mapping) and field in proposals and (
        not isinstance(proposal, Mapping) or "raw_value" not in proposal
    ):
        # Archive the complete unresolved proposal rather than promoting its
        # cached scalar to a fresh exact source measurement.
        invalid = parse_scientific_value(
            proposal,
            field,
            raw_unit=proposal.get("input_unit", proposal.get("raw_unit"))
            if isinstance(proposal, Mapping) else None,
            source_context=proposal.get("source_context")
            if isinstance(proposal, Mapping) else None,
            source_locator=proposal.get("source_locator")
            if isinstance(proposal, Mapping) else None,
        )
        invalid.update(
            status="invalid", errors=["missing_raw_proposal"],
            relation="unreported", value_kind="unreported",
            value=None, lower=None, upper=None, uncertainty=None,
            uncertainty_interpretation=None, approximate=False,
            unit_basis="unreported",
        )
        return invalid
    if isinstance(proposal, Mapping) and "raw_value" in proposal:
        return parse_scientific_value(
            proposal["raw_value"],
            field,
            raw_unit=proposal.get("input_unit", proposal.get("raw_unit")),
            source_context=proposal.get("source_context"),
            source_locator=proposal.get("source_locator"),
        )
    key = next((key for key in (field, *aliases) if record.get(key) is not None), field)
    return parse_scientific_value(
        record.get(key),
        field,
        raw_unit=record.get(f"{key}_unit"),
        source_context=record.get("evidence_text") or record.get("source_quote"),
        source_locator=record.get("source_locator")
        if isinstance(record.get("source_locator"), Mapping)
        else None,
    )


def legacy_scalar(proposal: Mapping[str, Any]) -> float | None:
    """Compatibility point only; intervals and censoring have no scalar value."""
    return (
        proposal.get("value")
        if proposal.get("status") == "parsed" and proposal.get("relation") == "exact"
        else None
    )


__all__ = [
    "FIELD_UNITS",
    "PARSER_VERSION",
    "json_safe_raw",
    "legacy_scalar",
    "parse_scientific_value",
    "record_quantity",
]
