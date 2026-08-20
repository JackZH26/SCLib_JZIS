"""Pure legacy-record -> Phase-1 typed-claim mapping.

The current materials table stores heterogeneous dictionaries in
``materials.records``.  This module provides the conservative, deterministic
translation used by the Phase-1 backfill.  It intentionally performs no I/O
and does not import SQLAlchemy models.

Important semantics:

* a missing pressure stays missing; it is never rewritten as ``0 GPa``;
* a missing Tc is not a negative example;
* ``not_detected`` is emitted only from an explicit negative statement/flag;
* legacy claims default to ``validity_status=pending``;
* hashes are stable across mapping-key order and repeated dry runs.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

CLAIM_MAPPER_VERSION = "legacy-material-record/v1"

# A fixed application namespace makes claim UUIDs deterministic without
# coupling their identity to a database sequence.
_CLAIM_NAMESPACE = uuid.UUID("ce9da7e7-6db1-4ca1-bb9b-9b1a3ecf2c6e")

_EVIDENCE_ROLES = {
    "primary_experimental",
    "primary_theoretical",
    "cited",
    "unknown",
}
_RESULT_STATUSES = {"observed", "not_detected", "inconclusive", "unknown"}
_VALUE_RELATIONS = {"exact", "interval", "lt", "le", "gt", "ge", "unreported"}
_TC_DEFINITIONS = {
    "onset",
    "zero_resistance",
    "midpoint",
    "diamagnetic",
    "heat_capacity",
    "unknown",
}
_PRESSURE_STATES = {"explicit_ambient", "reported", "not_reported", "ambiguous"}
_VALIDITY_STATUSES = {"accepted", "pending", "disputed", "retracted", "excluded"}
_SOURCE_KINDS = {"prose", "abstract", "table", "synthetic_fact", "legacy"}

_EXPERIMENTAL_MEASUREMENTS = {
    "resistivity",
    "susceptibility",
    "specific_heat",
    "musr",
    "arpes",
    "stm",
    "neutron",
    "nmr",
    "nqr",
    "magnetization",
    "thermal_conductivity",
    "raman",
    "andreev_reflection",
    "nernst",
    "tunneling",
    "esr",
    "torque_magnetometry",
    "hall_effect",
    "transport",
}
_THEORETICAL_MEASUREMENTS = {
    "calculation",
    "dft",
    "first_principles",
    "computational",
    "ab_initio",
    "allen_dynes",
    "eliashberg",
    "tight_binding",
}

_MEASUREMENT_ALIASES = {
    "resistance": "resistivity",
    "resistive": "resistivity",
    "electrical_resistivity": "resistivity",
    "electrical_transport": "transport",
    "magnetic_susceptibility": "susceptibility",
    "ac_susceptibility": "susceptibility",
    "dc_susceptibility": "susceptibility",
    "heat_capacity": "specific_heat",
    "specific_heat_capacity": "specific_heat",
    "mu_sr": "musr",
    "muon_spin_rotation": "musr",
    "muon_spin_relaxation": "musr",
    "first_principle": "first_principles",
    "first_principles_calculation": "first_principles",
    "density_functional_theory": "dft",
    "abinitio": "ab_initio",
    "allen_dynes_calculation": "allen_dynes",
}

_SAMPLE_ALIASES = {
    "single_crystalline": "single_crystal",
    "single_crystals": "single_crystal",
    "singlecrystal": "single_crystal",
    "polycrystalline": "polycrystal",
    "polycrystals": "polycrystal",
    "film": "thin_film",
    "monolayer": "thin_film",
    "bulk_sample": "bulk",
}

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_RANGE_RE = re.compile(
    rf"^\s*(?:~|≈|about\s+|approximately\s+)?({_NUMBER})"
    rf"\s*(?:-|–|—|to)\s*({_NUMBER})\s*(?:k|kelvin)?\s*$",
    re.IGNORECASE,
)
_INEQUALITY_RE = re.compile(
    rf"^\s*(<=|>=|<|>|≤|≥)\s*({_NUMBER})\s*(?:k|kelvin)?\s*$",
    re.IGNORECASE,
)
_QUANTITY_RE = re.compile(
    rf"^\s*(?:~|≈|about\s+|approximately\s+)?({_NUMBER})\s*([a-z]+)?\s*$",
    re.IGNORECASE,
)
_AMBIENT_RE = re.compile(
    r"^\s*(?:(?:at\s+)?(?:ambient|atmospheric)(?:\s+pressure)?|zero\s+pressure|"
    r"p\s*=\s*0(?:\.0+)?(?:\s*gpa)?)\s*$",
    re.IGNORECASE,
)


def source_record_identity(
    *,
    material_id: str,
    paper_id: str | None,
    raw_record: Mapping[str, Any],
    source_locator: Mapping[str, Any],
) -> tuple[str, uuid.UUID]:
    """Return the canonical source-record hash and deterministic claim UUID.

    Keeping this identity contract public lets the independent parity layer
    verify persisted payloads instead of merely checking that a supplied hash
    looks like 64 hexadecimal characters.
    """
    hash_input = {
        "hash_schema": "sclib-source-record/v1",
        "material_id": material_id.strip(),
        "paper_id": paper_id,
        "raw_record": _json_safe(dict(raw_record)),
        "source_locator": _json_safe(dict(source_locator)),
    }
    source_record_hash = _sha256_json(hash_input)
    return source_record_hash, uuid.uuid5(_CLAIM_NAMESPACE, source_record_hash)


@dataclass(frozen=True)
class _TemperatureClaim:
    relation: str = "unreported"
    value: float | None = None
    lower: float | None = None
    upper: float | None = None
    warnings: tuple[str, ...] = ()

    @property
    def has_threshold(self) -> bool:
        return any(v is not None for v in (self.value, self.lower, self.upper))


def map_record_to_claim(
    record: Mapping[str, Any],
    *,
    material_id: str,
    source_snapshot_id: uuid.UUID | str,
    material_formula: str | None = None,
    paper: Mapping[str, Any] | None = None,
    work_id: uuid.UUID | str | None = None,
    source_kind: str | None = None,
    source_locator: Mapping[str, Any] | None = None,
    extractor_version: str | None = None,
    ingestion_run_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    """Map one legacy record to a ``material_claims`` insert payload.

    ``paper`` is optional context from the papers table.  It is consulted for
    source identity, retraction status, and the earliest exact availability
    date.  No material summary field (for example ``materials.tc_max``) is
    used to fill a missing record-level value.
    """
    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    if not isinstance(material_id, str) or not material_id.strip():
        raise ValueError("material_id must be a non-empty string")
    try:
        resolved_snapshot_id = uuid.UUID(str(source_snapshot_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("source_snapshot_id must be a valid UUID") from exc

    paper_data: Mapping[str, Any] = paper or {}
    warnings: list[str] = []

    raw_record = _json_safe(dict(record))
    paper_id = _first_text(record, "paper_id") or _first_text(paper_data, "id", "paper_id")

    measurement = _normalise_measurement(
        _first_text(record, "measurement_method", "measurement", "method")
    )
    evidence_role = _normalise_evidence_role(record, paper_data, measurement)
    tc = _parse_temperature_claim(record)
    warnings.extend(tc.warnings)

    explicit_result = _explicit_result_status(record)
    if explicit_result is not None:
        result_status = explicit_result
    elif tc.relation in {"exact", "interval", "gt", "ge"} and tc.has_threshold:
        result_status = "observed"
    elif tc.relation in {"lt", "le"} and tc.has_threshold:
        # An upper bound alone does not prove whether a transition was looked
        # for or detected.  Only an explicit negative flag may create a
        # not_detected training example.
        result_status = "inconclusive"
    else:
        result_status = "unknown"

    if result_status == "not_detected" and tc.relation == "exact" and tc.value is not None:
        warnings.append("negative_result_conflicts_with_exact_tc")
        result_status = "inconclusive"

    property_type = "non_transition" if result_status == "not_detected" else "tc"
    minimum_temperature_k, minimum_temperature_issue = _first_quantity_scalar(
        record,
        frozenset({"k", "kelvin"}),
        "minimum_temperature_k",
        "minimum_temperature",
        "minimum_measured_temperature_k",
        "tmin_k",
        "t_min_k",
        "down_to_k",
    )
    if minimum_temperature_issue is not None:
        warnings.append(f"minimum_temperature_{minimum_temperature_issue}")
    magnetic_field_t, magnetic_field_issue = _first_quantity_scalar(
        record,
        frozenset({"t", "tesla"}),
        "magnetic_field_t",
        "magnetic_field_tesla",
        "field_t",
        "field_tesla",
    )
    if magnetic_field_issue is not None:
        warnings.append(f"magnetic_field_{magnetic_field_issue}")

    if minimum_temperature_k is not None and minimum_temperature_k < 0:
        minimum_temperature_k = None
        warnings.append("negative_minimum_temperature_discarded")
    if magnetic_field_t is not None and magnetic_field_t < 0:
        magnetic_field_t = None
        warnings.append("negative_magnetic_field_discarded")

    pressure_state, pressure_gpa, pressure_warnings = _normalise_pressure(record)
    warnings.extend(pressure_warnings)

    tc_definition = _normalise_tc_definition(
        _first_text(record, "tc_definition", "tc_type", "criterion")
    )
    sample_form = _normalise_sample_form(_first_text(record, "sample_form", "sample"))
    structure_phase_raw = _bounded_text(
        _first_text(record, "structure_phase_raw", "structure_phase", "phase"),
        200,
        "structure_phase_raw",
        warnings,
    )
    doping_raw, doping_derived = _normalise_doping(record, warnings)
    if doping_derived:
        warnings.append("doping_raw_rendered_from_structured_legacy_fields")
    sample_label = _bounded_text(
        _first_text(record, "sample_label", "sample_id", "specimen"),
        100,
        "sample_label",
        warnings,
    )

    locator, chunk_id = _build_source_locator(
        record,
        paper_id=paper_id,
        supplied=source_locator,
    )
    resolved_source_kind = _normalise_source_kind(
        source_kind or _first_text(record, "source_kind"),
        locator,
    )
    available_at = _available_at(record, paper_data)

    extraction_confidence, extraction_confidence_issue = _confidence(
        record.get("extraction_confidence")
    )
    extraction_confidence_issues = [extraction_confidence_issue]
    if extraction_confidence is None:
        extraction_confidence, fallback_issue = _confidence(record.get("confidence"))
        extraction_confidence_issues.append(fallback_issue)
    warnings.extend(
        f"extraction_confidence_{issue}"
        for issue in extraction_confidence_issues
        if issue is not None
    )
    relation_confidence, relation_confidence_issue = _confidence(record.get("relation_confidence"))
    if relation_confidence_issue is not None:
        warnings.append(f"relation_confidence_{relation_confidence_issue}")

    validity_status = _normalise_validity_status(record, paper_data, warnings)
    if result_status == "not_detected" and minimum_temperature_k is None:
        warnings.append("negative_result_missing_minimum_temperature")
        if validity_status == "accepted":
            validity_status = "pending"
    if result_status == "observed" and tc.relation == "unreported":
        warnings.append("observed_result_missing_tc_value")
        if validity_status == "accepted":
            validity_status = "pending"

    if pressure_state == "not_reported" and pressure_gpa is not None:
        # Defense in depth for future edits: this is also a DB constraint.
        raise AssertionError("not_reported pressure must not carry a value")
    if pressure_state == "reported" and pressure_gpa is None:
        raise AssertionError("reported pressure must carry a value")
    if pressure_state == "explicit_ambient" and pressure_gpa != 0.0:
        raise AssertionError("explicit_ambient pressure must be exactly 0 GPa")

    source_record_hash, claim_id = source_record_identity(
        material_id=material_id,
        paper_id=paper_id,
        raw_record=raw_record,
        source_locator=locator,
    )

    semantic_input = {
        "fingerprint_schema": "sclib-material-claim/v1",
        "material_id": material_id.strip(),
        "property_type": property_type,
        "evidence_role": evidence_role,
        "result_status": result_status,
        "value_relation": tc.relation,
        "value_kelvin": _canonical_number(tc.value),
        "value_lower_kelvin": _canonical_number(tc.lower),
        "value_upper_kelvin": _canonical_number(tc.upper),
        "tc_definition": tc_definition,
        "pressure_state": pressure_state,
        "pressure_gpa": _canonical_number(pressure_gpa),
        "minimum_temperature_k": _canonical_number(minimum_temperature_k),
        "magnetic_field_t": _canonical_number(magnetic_field_t),
        "measurement_method": measurement,
        "sample_form": sample_form,
        "structure_phase_raw": structure_phase_raw,
        "doping_raw": doping_raw,
        "sample_label": sample_label,
    }
    semantic_fingerprint = _sha256_json(semantic_input)

    metadata: dict[str, Any] = {
        "mapper": "legacy_material_record",
        "mapper_version": CLAIM_MAPPER_VERSION,
        "source_schema": "materials.records",
    }
    if material_formula:
        metadata["material_formula"] = material_formula
    if warnings:
        metadata["warnings"] = sorted(set(warnings))

    return {
        "id": claim_id,
        "material_id": material_id.strip(),
        "paper_id": paper_id,
        "work_id": work_id,
        "source_snapshot_id": resolved_snapshot_id,
        "chunk_id": chunk_id,
        "property_type": property_type,
        "evidence_role": evidence_role,
        "result_status": result_status,
        "value_relation": tc.relation,
        "value_kelvin": tc.value,
        "value_lower_kelvin": tc.lower,
        "value_upper_kelvin": tc.upper,
        "tc_definition": tc_definition,
        "pressure_state": pressure_state,
        "pressure_gpa": pressure_gpa,
        "minimum_temperature_k": minimum_temperature_k,
        "magnetic_field_t": magnetic_field_t,
        "measurement_method": measurement,
        "sample_form": sample_form,
        "structure_phase_raw": structure_phase_raw,
        "doping_raw": doping_raw,
        "sample_label": sample_label,
        "source_kind": resolved_source_kind,
        "source_locator": locator,
        "extraction_confidence": extraction_confidence,
        "relation_confidence": relation_confidence,
        "validity_status": validity_status,
        "raw_record": raw_record,
        "extraction_metadata": metadata,
        "source_record_hash": source_record_hash,
        "semantic_fingerprint": semantic_fingerprint,
        "duplicate_cluster_id": None,
        "available_at": available_at,
        "extractor_version": (
            extractor_version
            or _first_text(record, "extractor_version", "prompt_version")
            or CLAIM_MAPPER_VERSION
        )[:80],
        "ingestion_run_id": str(ingestion_run_id)[:100] if ingestion_run_id is not None else None,
    }


def _normalise_evidence_role(
    record: Mapping[str, Any],
    paper: Mapping[str, Any],
    measurement: str | None,
) -> str:
    raw = _first_text(record, "evidence_role", "evidence_type", "claim_kind")
    value = _slug(raw)
    aliases = {
        "experimental": "primary_experimental",
        "experiment": "primary_experimental",
        "measured": "primary_experimental",
        "theoretical": "primary_theoretical",
        "theory": "primary_theoretical",
        "calculated": "primary_theoretical",
        "predicted": "primary_theoretical",
        "secondary": "cited",
        "citation": "cited",
        "referenced": "cited",
    }
    value = aliases.get(value, value)
    if value in _EVIDENCE_ROLES:
        return value

    # Legacy "primary" is explicitly ambiguous.  Resolve it only when an
    # independent technique or paper-type signal is available.
    if measurement in _EXPERIMENTAL_MEASUREMENTS:
        return "primary_experimental"
    if measurement in _THEORETICAL_MEASUREMENTS:
        return "primary_theoretical"
    paper_type = _slug(_first_text(record, "paper_type") or _first_text(paper, "paper_type"))
    if paper_type in {"computational", "theoretical"}:
        return "primary_theoretical"
    if paper_type == "experimental":
        return "primary_experimental"
    return "unknown"


def _explicit_result_status(record: Mapping[str, Any]) -> str | None:
    raw = _first_text(record, "result_status", "outcome_state", "outcome")
    value = _slug(raw)
    aliases = {
        "detected": "observed",
        "superconducting": "observed",
        "positive": "observed",
        "not_observed": "not_detected",
        "notdetected": "not_detected",
        "no_transition": "not_detected",
        "no_superconductivity": "not_detected",
        "non_superconducting": "not_detected",
        "negative": "not_detected",
        "ambiguous": "inconclusive",
        "uncertain": "inconclusive",
        "unreported": "unknown",
    }
    value = aliases.get(value, value)
    if value in _RESULT_STATUSES:
        return value

    for key in ("no_transition", "not_detected"):
        if record.get(key) is True:
            return "not_detected"
    for key in ("superconductivity_observed", "transition_observed", "is_superconducting"):
        if key in record and isinstance(record.get(key), bool):
            return "observed" if record[key] else "not_detected"
    return None


def _parse_temperature_claim(record: Mapping[str, Any]) -> _TemperatureClaim:
    explicit_relation = _normalise_relation(
        _first_text(record, "value_relation", "tc_relation", "relation")
    )
    raw_value = _first_present(record, "value_kelvin", "tc_kelvin", "tc")
    parsed = _parse_temperature_value(raw_value)
    warnings = list(parsed.warnings)

    lower, lower_issue = _first_quantity_scalar(
        record,
        frozenset({"k", "kelvin"}),
        "value_lower_kelvin",
        "tc_lower_kelvin",
        "tc_lower_k",
        "tc_lower",
        "tc_min",
    )
    if lower_issue is not None:
        warnings.append(f"tc_lower_{lower_issue}")
    upper, upper_issue = _first_quantity_scalar(
        record,
        frozenset({"k", "kelvin"}),
        "value_upper_kelvin",
        "tc_upper_kelvin",
        "tc_upper_k",
        "tc_upper",
        "tc_max",
    )
    if upper_issue is not None:
        warnings.append(f"tc_upper_{upper_issue}")

    relation = explicit_relation or parsed.relation
    value = parsed.value
    lower = lower if lower is not None else parsed.lower
    upper = upper if upper is not None else parsed.upper

    if relation == "interval":
        if lower is None and value is not None:
            lower = value
        if upper is None and value is not None:
            upper = value
        value = None
        if lower is not None and upper is not None and lower > upper:
            lower, upper = upper, lower
            warnings.append("tc_interval_bounds_reordered")
        if lower is None or upper is None:
            warnings.append("tc_interval_missing_bound")
            lower = upper = None
            relation = "unreported"
    elif relation in {"lt", "le"}:
        upper = upper if upper is not None else value
        value = None
        lower = None
        if upper is None:
            warnings.append("tc_upper_bound_missing")
            relation = "unreported"
    elif relation in {"gt", "ge"}:
        lower = lower if lower is not None else value
        value = None
        upper = None
        if lower is None:
            warnings.append("tc_lower_bound_missing")
            relation = "unreported"
    elif relation == "exact":
        if value is None and lower is not None and upper is not None and lower == upper:
            value = lower
        lower = None
        upper = None
        if value is None:
            relation = "unreported"
            warnings.append("exact_tc_missing_value")
    else:
        relation = "unreported"
        value = lower = upper = None

    for name, number in (("value", value), ("lower", lower), ("upper", upper)):
        if number is not None and number < 0:
            warnings.append(f"negative_tc_{name}_discarded")
            if name == "value":
                value = None
            elif name == "lower":
                lower = None
            else:
                upper = None

    # Revalidate the relation after discarding non-physical bounds. Keeping an
    # interval with one missing endpoint would both misstate the source and
    # violate the typed-claim database shape constraint.
    if relation == "interval" and (lower is None or upper is None):
        relation = "unreported"
        value = lower = upper = None
        warnings.append("invalid_tc_interval_discarded")

    if not any(v is not None for v in (value, lower, upper)):
        relation = "unreported"

    return _TemperatureClaim(relation, value, lower, upper, tuple(warnings))


def _parse_temperature_value(value: Any) -> _TemperatureClaim:
    if value is None or value == "":
        return _TemperatureClaim()
    if _is_number(value):
        return _TemperatureClaim("exact", float(value))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) == 2:
            lower, lower_issue = _quantity_scalar(value[0], frozenset({"k", "kelvin"}))
            upper, upper_issue = _quantity_scalar(value[1], frozenset({"k", "kelvin"}))
            if lower is not None and upper is not None:
                return _TemperatureClaim("interval", lower=lower, upper=upper)
            if "unit_mismatch" in {lower_issue, upper_issue}:
                return _TemperatureClaim(warnings=("invalid_tc_unit",))
        return _TemperatureClaim(warnings=("unparseable_tc_sequence",))
    if not isinstance(value, str):
        return _TemperatureClaim(warnings=("unparseable_tc_value",))

    text = value.strip()
    match = _RANGE_RE.match(text)
    if match:
        lower = _finite_float_token(match.group(1))
        upper = _finite_float_token(match.group(2))
        if lower is None or upper is None:
            return _TemperatureClaim(warnings=("nonfinite_tc_range",))
        return _TemperatureClaim(
            "interval",
            lower=lower,
            upper=upper,
        )
    match = _INEQUALITY_RE.match(text)
    if match:
        relation = {"<": "lt", "<=": "le", "≤": "le", ">": "gt", ">=": "ge", "≥": "ge"}[
            match.group(1)
        ]
        threshold = _finite_float_token(match.group(2))
        if threshold is None:
            return _TemperatureClaim(warnings=("nonfinite_tc_threshold",))
        if relation in {"lt", "le"}:
            return _TemperatureClaim(relation, upper=threshold)
        return _TemperatureClaim(relation, lower=threshold)
    number, issue = _quantity_scalar(text, frozenset({"k", "kelvin"}))
    if number is not None:
        warning = ()
        if re.match(r"\s*(?:~|≈|about|approximately)", text, re.IGNORECASE):
            warning = ("approximate_tc_collapsed_to_exact",)
        return _TemperatureClaim("exact", number, warnings=warning)
    if issue == "unit_mismatch":
        return _TemperatureClaim(warnings=("invalid_tc_unit",))
    if issue == "nonfinite":
        return _TemperatureClaim(warnings=("nonfinite_tc_value",))
    return _TemperatureClaim(warnings=("unparseable_tc_text",))


def _normalise_pressure(record: Mapping[str, Any]) -> tuple[str, float | None, list[str]]:
    warnings: list[str] = []
    explicit_state = _slug(_first_text(record, "pressure_state"))
    raw = _first_present(record, "pressure_gpa", "pressure")

    if raw is None or raw == "":
        if explicit_state == "explicit_ambient":
            # The state claims ambient, but manufacturing the numeric zero
            # would violate the Phase-1 missingness rule.  Keep it ambiguous.
            warnings.append("explicit_ambient_missing_numeric_pressure")
            return "ambiguous", None, warnings
        if explicit_state == "reported":
            warnings.append("reported_pressure_missing_value")
            return "ambiguous", None, warnings
        if record.get("ambient_sc") is True:
            warnings.append("ambient_flag_without_pressure_value")
            return "ambiguous", None, warnings
        return "not_reported", None, warnings

    if isinstance(raw, str) and _AMBIENT_RE.fullmatch(raw.strip()):
        return "explicit_ambient", 0.0, warnings

    pressure, pressure_issue = _quantity_scalar(raw, frozenset({"gpa"}))
    if pressure is None:
        warnings.append(
            "pressure_unit_mismatch"
            if pressure_issue == "unit_mismatch"
            else "unparseable_pressure"
        )
        return "ambiguous", None, warnings
    if pressure < 0:
        warnings.append("negative_pressure_discarded")
        return "ambiguous", None, warnings
    if pressure > 0:
        if explicit_state == "not_reported":
            warnings.append("pressure_state_conflicts_with_value")
        return "reported", pressure, warnings

    # Numeric zero in old NER records was historically used as a missing
    # fallback.  Require an independent ambient signal before calling it an
    # explicit ambient measurement; otherwise preserve 0 but mark ambiguous.
    if (
        explicit_state == "explicit_ambient"
        or record.get("ambient_sc") is True
        or _slug(_first_text(record, "pressure_type")) == "none"
    ):
        return "explicit_ambient", 0.0, warnings
    warnings.append("legacy_zero_pressure_not_explicitly_ambient")
    return "ambiguous", 0.0, warnings


def _normalise_tc_definition(value: str | None) -> str:
    slug = _slug(value)
    aliases = {
        "tc_onset": "onset",
        "resistive_onset": "onset",
        "zero": "zero_resistance",
        "zero_resistivity": "zero_resistance",
        "tc_zero": "zero_resistance",
        "mid": "midpoint",
        "mid_point": "midpoint",
        "diamagnetism": "diamagnetic",
        "magnetic": "diamagnetic",
        "specific_heat": "heat_capacity",
        "heat_capacity_anomaly": "heat_capacity",
        "none": "unknown",
    }
    slug = aliases.get(slug, slug)
    return slug if slug in _TC_DEFINITIONS else "unknown"


def _normalise_measurement(value: str | None) -> str | None:
    slug = _slug(value)
    if not slug:
        return None
    slug = _MEASUREMENT_ALIASES.get(slug, slug)
    return slug[:100]


def _normalise_sample_form(value: str | None) -> str | None:
    slug = _slug(value)
    if not slug:
        return None
    return _SAMPLE_ALIASES.get(slug, slug)[:50]


def _normalise_doping(record: Mapping[str, Any], warnings: list[str]) -> tuple[str | None, bool]:
    raw = _first_text(record, "doping_raw", "doping")
    if raw:
        return _bounded_text(raw, 200, "doping_raw", warnings), False
    doping_type = _slug(_first_text(record, "doping_type"))
    doping_level, doping_issue = _first_quantity_scalar(
        record,
        frozenset(),
        "doping_level",
    )
    if doping_issue is not None:
        warnings.append(f"doping_level_{doping_issue}")
    parts: list[str] = []
    if doping_type and doping_type != "none":
        parts.append(f"type={doping_type}")
    if doping_level is not None:
        parts.append(f"level={_canonical_number(doping_level)}")
    return ("; ".join(parts)[:200] if parts else None), bool(parts)


def _build_source_locator(
    record: Mapping[str, Any],
    *,
    paper_id: str | None,
    supplied: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], str | None]:
    locator: dict[str, Any] = {}
    raw_locator = record.get("source_locator")
    if isinstance(raw_locator, Mapping):
        locator.update(_json_safe(dict(raw_locator)))
    if supplied:
        locator.update(_json_safe(dict(supplied)))

    aliases = {
        "section": ("source_section", "section"),
        "page": ("source_page", "page"),
        "table": ("source_table", "table"),
        "span_start": ("source_span_start", "span_start"),
        "span_end": ("source_span_end", "span_end"),
        "evidence_text": ("evidence_text", "source_quote", "quote"),
        "reference": ("reference",),
    }
    for target, keys in aliases.items():
        if target in locator and locator[target] not in (None, ""):
            continue
        value = _first_present(record, *keys)
        if value not in (None, ""):
            locator[target] = _json_safe(value)

    chunk_id = _first_text(record, "chunk_id", "source_chunk_id")
    if not chunk_id:
        candidate = locator.get("chunk_id")
        chunk_id = str(candidate).strip() if candidate not in (None, "") else None
    if chunk_id:
        chunk_id = chunk_id[:200]
        locator["chunk_id"] = chunk_id

    quality = "unknown"
    if any(key in locator for key in ("span_start", "span_end", "evidence_text")):
        quality = "span"
    elif any(key in locator for key in ("page", "table")):
        quality = "page_or_table"
    elif chunk_id:
        quality = "chunk"
    elif locator.get("section"):
        quality = "section"
    elif paper_id:
        quality = "paper_only"
    elif locator.get("reference"):
        quality = "reference_only"
    locator["locator_quality"] = quality
    return locator, chunk_id


def _normalise_source_kind(value: str | None, locator: Mapping[str, Any]) -> str:
    slug = _slug(value)
    if slug in _SOURCE_KINDS:
        return slug
    if locator.get("table"):
        return "table"
    if _slug(str(locator.get("section") or "")) == "abstract":
        return "abstract"
    # Backfilled material records lack a guaranteed source span.  Calling
    # them prose would imply provenance we do not possess.
    return "legacy"


def _normalise_validity_status(
    record: Mapping[str, Any],
    paper: Mapping[str, Any],
    warnings: list[str],
) -> str:
    paper_status = _slug(_first_text(paper, "status", "publication_status"))
    if record.get("retracted") is True or paper_status == "retracted":
        return "retracted"
    if record.get("disputed") is True:
        return "disputed"
    raw = _slug(_first_text(record, "validity_status"))
    if raw in _VALIDITY_STATUSES:
        if raw == "accepted":
            # This mapper is specifically for legacy ``materials.records``.
            # Historical acceptance has no field-level QC lineage, so every
            # such row must be re-reviewed in the typed claim store.
            warnings.append("legacy_accepted_status_requires_revalidation")
            return "pending"
        return raw
    # Mechanical backfill is never auto-accepted.  QC/human review promotes
    # rows later, preserving a clean boundary between migration and evidence.
    return "pending"


def _normalise_relation(value: str | None) -> str | None:
    slug = _slug(value)
    aliases = {
        "eq": "exact",
        "equal": "exact",
        "range": "interval",
        "between": "interval",
        "less_than": "lt",
        "less_than_or_equal": "le",
        "lte": "le",
        "greater_than": "gt",
        "greater_than_or_equal": "ge",
        "gte": "ge",
        "missing": "unreported",
        "unknown": "unreported",
    }
    slug = aliases.get(slug, slug)
    return slug if slug in _VALUE_RELATIONS else None


def _available_at(record: Mapping[str, Any], paper: Mapping[str, Any]) -> date | None:
    explicit = _parse_date(_first_present(record, "available_at"))
    if explicit:
        return explicit
    candidates = [
        _parse_date(_first_present(paper, "available_at")),
        _parse_date(_first_present(paper, "date_submitted")),
        _parse_date(_first_present(paper, "date_published")),
    ]
    exact = [candidate for candidate in candidates if candidate is not None]
    return min(exact) if exact else None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None


def _confidence(value: Any) -> tuple[float | None, str | None]:
    number, issue = _quantity_scalar(value, frozenset())
    if number is None:
        return None, issue
    if not 0.0 <= number <= 1.0:
        return None, "out_of_range"
    return number, None


def _first_quantity_scalar(
    record: Mapping[str, Any],
    allowed_units: frozenset[str],
    *keys: str,
) -> tuple[float | None, str | None]:
    return _quantity_scalar(_first_present(record, *keys), allowed_units)


def _quantity_scalar(
    value: Any,
    allowed_units: frozenset[str],
) -> tuple[float | None, str | None]:
    if value is None or value == "":
        return None, None
    if _is_number(value):
        return float(value), None
    if isinstance(value, str):
        match = _QUANTITY_RE.match(value.strip())
        if match:
            unit = (match.group(2) or "").lower()
            if unit and unit not in allowed_units:
                return None, "unit_mismatch"
            number = _finite_float_token(match.group(1))
            return (number, None) if number is not None else (None, "nonfinite")
    return None, "unparseable"


def _finite_float_token(value: str) -> float | None:
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_number(value: Any) -> bool:
    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _first_present(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _first_text(record: Mapping[str, Any], *keys: str) -> str | None:
    value = _first_present(record, *keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bounded_text(
    value: str | None,
    maximum: int,
    field: str,
    warnings: list[str],
) -> str | None:
    if value is None or len(value) <= maximum:
        return value
    warnings.append(f"{field}_too_long_for_typed_column")
    return None


def _slug(value: str | None) -> str:
    if not value:
        return ""
    slug = value.strip().lower()
    slug = slug.replace("μ", "mu").replace("±", "_pm_")
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def _canonical_number(value: float | None) -> str | None:
    if value is None:
        return None
    decimal = Decimal(str(value))
    if decimal == 0:
        return "0"
    return format(decimal.normalize(), "f")


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return 0.0 if value == 0 else value
    if isinstance(value, Decimal):
        return _canonical_number(float(value))
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC)
        return dt.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        items = [_json_safe(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return str(value)
