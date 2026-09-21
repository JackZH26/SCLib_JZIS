"""Non-destructive operational anomaly review; not a physical validity oracle.

All thresholds are local legacy review references, not verified world records or
universal physical limits. This module never replaces, deletes or approves a value.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .pressure_semantics import classify_pressure
from .property_evidence import legacy_result_id
from .result_semantics import classify_result

if __package__ == "ingestion":
    from .extract.scientific_values import FIELD_UNITS, parse_scientific_value, record_quantity
else:
    from .scientific_values import FIELD_UNITS, parse_scientific_value, record_quantity

ANOMALY_POLICY_VERSION = "anomaly-review/1.0.0"
PUBLIC_RECORD_LIMIT = 100
PUBLIC_FINDING_LIMIT = 40
TC_REVIEW_REFERENCE_K = 250.0
AMBIENT_TC_REVIEW_REFERENCE_K = 152.0
PRESSURE_REVIEW_REFERENCE_GPA = 500.0
FAMILY_TC_REVIEW_REFERENCES_K = {
    "cuprate": 180.0, "iron_based": 110.0, "nickelate": 110.0,
    "hydride": 270.0, "mgb2": 50.0, "fulleride": 50.0,
    "bismuthate": 45.0, "conventional": 45.0, "chalcogenide": 40.0,
    "elemental": 40.0, "borocarbide": 30.0, "bis2_layered": 30.0,
    "heavy_fermion": 30.0, "organic": 25.0, "kagome": 15.0, "ruthenate": 10.0,
}
PARAMETER_REVIEW_REFERENCES = {
    "lambda_eph": (0.01, 10.0), "mu_star": (0.0, 0.5), "omega_log_k": (1.0, 5000.0),
}
_TC_VIEWS = ("tc_kelvin", "tc_max", "tc_max_experimental", "tc_max_theoretical", "tc_ambient")
_VIEW_FIELDS = {key: "tc_kelvin" for key in _TC_VIEWS}
_VIEW_FIELDS.update({key: key for key in FIELD_UNITS})
_VIEW_FIELDS["lattice_params"] = "lattice_params"
_LATTICE = tuple("lattice_" + key for key in ("a", "b", "c", "alpha", "beta", "gamma"))
_RAW_FIELDS = tuple(FIELD_UNITS)
_RULE_DEFINITIONS = (
    ("record_format_invalid", "format_invalid", "error", "The occurrence is not a structured scientific record."),
    ("numeric_format_invalid", "format_invalid", "error", "Reported notation/unit cannot be represented by the current parser."),
    ("numeric_relation_conflict", "metadata_conflict", "warning", "Declared quantity relation conflicts with original notation."),
    ("raw_quantity_conflict", "metadata_conflict", "warning", "Coexisting original quantity channels are inconsistent or cannot be reconciled."),
    ("tc_high_review", "unusual", "warning", "Tc crosses a local broad extraction review reference; all pressures and origins."),
    ("tc_ambient_reference_review", "unusual", "warning", "An explicit ambient Observed Tc crosses a local historical review reference."),
    ("tc_family_reference_review", "unusual", "warning", "Tc crosses a legacy family review reference, not a physical ceiling."),
    ("pressure_high_review", "unusual", "warning", "Pressure crosses a local operational review reference."),
    ("negative_pressure_protocol_review", "unusual", "warning", "Negative pressure requires a defined tensile/effective-pressure convention."),
    ("pressure_evidence_conflict", "metadata_conflict", "warning", "Pressure assertions are inconsistent or unresolved."),
    ("hydride_low_pressure_high_tc_review", "unusual", "warning", "One hydride result combines high Tc with an explicitly bounded low pressure."),
    ("parameter_reference_review", "unusual", "warning", "A parameter lies outside a legacy operational review interval."),
    ("negative_temperature_review", "unusual", "warning", "A negative temperature requires field/convention source review."),
    ("record_year_review", "unusual", "warning", "A year lies outside the operational chronology review window."),
    ("record_year_format_invalid", "format_invalid", "error", "The reported year is not an unambiguous finite integer year."),
    ("legacy_compound_reference_review", "unusual", "warning", "A value crosses a view-scoped legacy compound reference, not a cap."),
    ("legacy_numeric_override_requires_revision", "metadata_conflict", "warning", "A legacy exact numeric override requires a source-backed revision."),
    ("review_context_unresolved", "metadata_conflict", "warning", "An external review reference lacks a supported auditable shape."),
)
_RULES = {rule_id: (category, severity, description) for rule_id, category, severity, description in _RULE_DEFINITIONS}


def rule_registry() -> list[dict[str, Any]]:
    """Fresh metadata objects suitable for API/admin explanations."""
    return [{
        "rule_id": rule_id, "rule_version": ANOMALY_POLICY_VERSION, "category": category,
        "severity": severity, "description": description, "outcome": "pending",
        "action": "retain_raw_and_review", "physical_limit": False,
    } for rule_id, category, severity, description in _RULE_DEFINITIONS]


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _text(value: Any, limit: int = 200) -> str | None:
    return value if isinstance(value, str) and value.strip() and len(value) <= limit else None


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _raw(value: Any) -> Any:
    if value is None or isinstance(value, bool) or _finite(value):
        return value
    if isinstance(value, str) and len(value) <= 256:
        return value
    if isinstance(value, (list, tuple)) and len(value) <= 2:
        return [_raw(item) for item in value]
    return {"redacted": "structured_or_oversize_raw", "sha256": _digest(value)}


def _public_quantity(proposal: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: proposal.get(key) for key in (
        "status", "relation", "value", "lower", "upper", "unit", "approximate",
        "uncertainty", "uncertainty_interpretation", "unit_basis", "parser_version",
    )}
    result.update(raw_value=_raw(proposal.get("raw_value")), raw_unit=_text(proposal.get("raw_unit"), 40),
                  errors=list(proposal.get("errors") or []))
    return result


def _extent(proposal: Mapping[str, Any]) -> tuple[float | None, float | None]:
    if proposal.get("status") != "parsed" or proposal.get("errors"):
        return None, None
    value = proposal.get("value")
    if _finite(value):
        uncertainty = proposal.get("uncertainty")
        spread = uncertainty if _finite(uncertainty) and uncertainty >= 0 else 0
        return value - spread, value + spread
    lower, upper = proposal.get("lower"), proposal.get("upper")
    return (lower if _finite(lower) else None, upper if _finite(upper) else None)


def _above(proposal: Mapping[str, Any], threshold: float) -> str | None:
    lower, upper = _extent(proposal)
    if lower is not None and (lower > threshold or lower == threshold and proposal.get("relation") == "gt"):
        return "reported_extent_above_reference"
    if upper is not None and upper > threshold:
        return "reported_extent_may_exceed_reference"
    return None


def _affected(field: str) -> list[str]:
    if field == "tc_kelvin":
        return list(_TC_VIEWS)
    if field in _LATTICE:
        return [field, "lattice_params"]
    return [field]


def _finding(result_id: str, rule: str, field: str, reason: str, *,
             applicability: Mapping[str, Any] | None = None,
             quantity: Mapping[str, Any] | None = None) -> dict[str, Any]:
    category, severity, description = _RULES[rule]
    context = {"field": field, "view_properties": _affected(field),
               "reference_basis": "legacy_operational_review_reference",
               "physical_limit": False, **(applicability or {})}
    finding_id = "anomaly:" + _digest([result_id, rule, ANOMALY_POLICY_VERSION, field, reason, context])
    return {
        "finding_id": finding_id, "result_id": result_id, "rule_id": rule,
        "rule_version": ANOMALY_POLICY_VERSION, "category": category,
        "field": field, "affected_properties": _affected(field),
        "applicability": context, "reason": reason, "description": description,
        "severity": severity, "outcome": "pending", "action": "retain_raw_and_review",
        "quantity": _public_quantity(quantity) if quantity is not None else None,
        "default_view_disposition": "review_required",
    }


def record_property_quantity(record: Mapping[str, Any], field: str) -> dict[str, Any]:
    """Reparse an original numeric proposal, including aliases/nested lattice.

    This internal-service accessor retains full original raw values. Public API
    responses must use the bounded projections, not serialize this blindly.
    """
    field = {"tc": "tc_kelvin", "pressure": "pressure_gpa"}.get(field, field)
    field = _VIEW_FIELDS.get(field)
    if field not in FIELD_UNITS:
        raise ValueError("field must identify a supported scalar scientific quantity")
    source = record
    if field in _LATTICE and record.get(field) is None and isinstance(record.get("lattice_params"), Mapping):
        component = field.removeprefix("lattice_")
        nested = record["lattice_params"]
        if component in nested:
            source = {**record, field: nested[component]}
            if "unit" in nested:
                source = {**source, field + "_unit": nested["unit"]}
    if field == "pressure_gpa" and source.get("pressure_gpa_unit") is None and source.get("pressure_unit") is not None:
        source = {**source, "pressure_gpa_unit": source["pressure_unit"]}
    aliases = {"tc_kelvin": ("tc",), "pressure_gpa": ("pressure",)}.get(field, ())
    return record_quantity(source, field, *aliases)


def _view_applies(field: str, pressure: Any, origin: Any) -> bool:
    if field in {"tc_max_experimental", "tc_ambient"} and (
        origin.knowledge_origin != "Observed" or origin.classification_status != "resolved"
    ):
        return False
    if field == "tc_max_theoretical" and (
        origin.knowledge_origin != "Computed" or origin.classification_status != "resolved"
    ):
        return False
    return field != "tc_ambient" or pressure.pressure_state == "explicit_ambient"


def _quantity_channels(record: Mapping[str, Any], field: str) -> list[tuple[str, dict[str, Any]]]:
    """Independent aliases/groups, not cached normalized proposal values.

    A typed raw proposal supersedes its own compatibility flat scalar. An
    additional alias/nested channel is not silently shadowed by that precedence.
    """
    aliases = {"tc_kelvin": ("tc",), "pressure_gpa": ("pressure",)}.get(field, ())
    if not aliases and field not in _LATTICE:
        return []
    channels = []
    proposals = record.get("scientific_values")
    typed = isinstance(proposals, Mapping) and field in proposals
    if typed or record.get(field) is not None:
        channels.append(("scientific_values." + field + ".raw_value" if typed else field,
                         record_property_quantity(record, field)))
    for alias in aliases:
        if record.get(alias) is not None:
            channels.append((alias, parse_scientific_value(
                record[alias], field, raw_unit=record.get(alias + "_unit"),
            )))
    nested = record.get("lattice_params")
    component = field.removeprefix("lattice_")
    if field in _LATTICE and isinstance(nested, Mapping) and nested.get(component) is not None:
        channels.append(("lattice_params." + component, parse_scientific_value(
            nested[component], field, raw_unit=nested.get("unit", record.get(field + "_unit")),
        )))
    return [(channel, proposal) for channel, proposal in channels if proposal["status"] != "unreported"]


def _quantities_equivalent(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if any(item["status"] != "parsed" or item.get("errors") for item in (left, right)):
        return False
    if any(left.get(key) != right.get(key) for key in (
        "relation", "unit", "approximate", "uncertainty_interpretation",
    )):
        return False
    for key in ("value", "lower", "upper", "uncertainty"):
        a, b = left.get(key), right.get(key)
        if a == b:
            continue
        if not _finite(a) or not _finite(b) or not math.isclose(a, b, rel_tol=1e-12, abs_tol=0):
            return False
    return True


def assess_record_anomalies(
    record: Any, *, scope_id: str, family: str | None = None,
    compound_thresholds: Sequence[Any] = (), current_year: int | None = None,
) -> dict[str, Any]:
    """Assess original evidence only. Raw approvals and envelopes are ignored."""
    if current_year is not None and (
        isinstance(current_year, bool) or not isinstance(current_year, int) or not 1900 <= current_year <= 9998
    ):
        raise ValueError("current_year must be an explicit integer in [1900, 9998]")
    if not isinstance(record, Mapping):
        result_id = "legacy-result:" + _digest([scope_id, record])
        findings = [_finding(result_id, "record_format_invalid", "*", "record_is_not_a_mapping")]
        return _assessment(result_id, findings, current_year)
    result_id = legacy_result_id(record, scope_id=scope_id)
    pressure, origin = classify_pressure(record), classify_result(record)
    # Absent quantities cannot create a finding. Do not parse all scalar
    # fields for every legacy record, but retain every explicit typed, alias,
    # unit-only and nested-lattice channel, including malformed declarations.
    # Tc is always parsed so shared context/locator validation still occurs for
    # records with no numerical proposals. No stored normalized value is used.
    proposals = record.get("scientific_values")
    nested = record.get("lattice_params")

    def supplied(field):
        if field == "tc_kelvin" or isinstance(proposals, Mapping) and field in proposals:
            return True
        aliases = {"tc_kelvin": ("tc",), "pressure_gpa": ("pressure",)}.get(field, ())
        if any(record.get(key) is not None or record.get(key + "_unit") is not None for key in (field, *aliases)):
            return True
        return field in _LATTICE and isinstance(nested, Mapping) and field.removeprefix("lattice_") in nested

    quantities = {field: record_property_quantity(record, field) for field in _RAW_FIELDS if supplied(field)}
    findings = []
    for field, proposal in quantities.items():
        channels = _quantity_channels(record, field)
        if len(channels) > 1 and any(not _quantities_equivalent(channels[0][1], item[1]) for item in channels[1:]):
            findings.append(_finding(result_id, "raw_quantity_conflict", field,
                "coexisting_original_quantity_channels_unresolved", quantity=proposal,
                applicability={"reference_basis": "raw_channel_consistency",
                               "source_channels": [channel for channel, _ in channels]}))
        if proposal["status"] == "invalid":
            findings.append(_finding(result_id, "numeric_format_invalid", field,
                "scientific_notation_or_unit_unresolved", quantity=proposal,
                applicability={"parser_errors": list(proposal["errors"]), "reference_basis": "parser_representability"}))
        if field.endswith("_k") or field == "tc_kelvin":
            lower, upper = _extent(proposal)
            if any(value is not None and value < 0 for value in (lower, upper)):
                findings.append(_finding(result_id, "negative_temperature_review", field,
                    "negative_temperature_requires_source_convention", quantity=proposal))
    tc = quantities["tc_kelvin"]
    declared = record.get("tc_relation") or record.get("value_relation")
    if declared and tc["status"] == "parsed" and declared != tc["relation"]:
        findings.append(_finding(result_id, "numeric_relation_conflict", "tc_kelvin",
            "declared_relation_conflicts_with_raw_notation", quantity=tc))
    if reason := _above(tc, TC_REVIEW_REFERENCE_K):
        findings.append(_finding(result_id, "tc_high_review", "tc_kelvin", reason, quantity=tc,
            applicability={"threshold": TC_REVIEW_REFERENCE_K, "unit": "K",
                           "pressure_scope": "all_pressures_including_unknown", "origin_scope": "all_origins"}))
    observed = origin.knowledge_origin == "Observed" and origin.classification_status == "resolved" and origin.source_role != "conflicted"
    if pressure.pressure_state == "explicit_ambient" and observed and (reason := _above(tc, AMBIENT_TC_REVIEW_REFERENCE_K)):
        findings.append(_finding(result_id, "tc_ambient_reference_review", "tc_kelvin", reason, quantity=tc,
            applicability={"threshold": AMBIENT_TC_REVIEW_REFERENCE_K, "unit": "K",
                           "pressure_scope": "explicit_ambient_same_result", "origin_scope": "Observed"}))
    record_family = _text(record.get("family"), 80) or _text(record.get("material_family"), 80)
    actual_family = record_family or _text(family, 80)
    if actual_family in FAMILY_TC_REVIEW_REFERENCES_K:
        threshold = FAMILY_TC_REVIEW_REFERENCES_K[actual_family]
        if reason := _above(tc, threshold):
            findings.append(_finding(result_id, "tc_family_reference_review", "tc_kelvin", reason, quantity=tc,
                applicability={"threshold": threshold, "unit": "K", "family": actual_family,
                               "family_basis": "record" if record_family else "external_material_context",
                               "pressure_scope": "all_pressures_including_unknown", "origin_scope": "all_origins"}))
    pressure_quantity = {
        "status": "parsed" if pressure.pressure_state in {"reported", "explicit_ambient"} else "invalid",
        "relation": pressure.relation, "value": pressure.pressure_gpa,
        "lower": pressure.value_lower_gpa, "upper": pressure.value_upper_gpa,
        "uncertainty": pressure.uncertainty_gpa, "uncertainty_interpretation": pressure.uncertainty_interpretation,
        "approximate": pressure.approximate, "raw_value": pressure.raw_value,
        "raw_unit": pressure.raw_unit, "unit_basis": pressure.unit_basis,
        "unit": "GPa", "errors": [], "parser_version": pressure.classifier_version,
    }
    # Explicit ambient text is valid pressure metadata despite not being a
    # numeric-parser quantity; only the pressure contract decides its meaning.
    if pressure.pressure_state == "explicit_ambient":
        findings = [item for item in findings if not (item["field"] == "pressure_gpa" and item["rule_id"] == "numeric_format_invalid")]
    if "unsupported_negative_pressure" in pressure.reasons:
        findings.append(_finding(result_id, "negative_pressure_protocol_review", "pressure_gpa",
            "tensile_or_effective_pressure_convention_required", quantity=pressure_quantity))
    elif pressure.pressure_state == "ambiguous" and set(pressure.reasons) & {
        "ambient_assertion_conflicts_with_pressure", "pressure_state_conflicts_with_value",
        "unknown_pressure_state", "explicit_ambient_missing_numeric_pressure", "reported_pressure_missing_value",
    }:
        findings.append(_finding(result_id, "pressure_evidence_conflict", "pressure_gpa",
            "pressure_ambiguous_not_ambient", quantity=pressure_quantity,
            applicability={"pressure_reasons": list(pressure.reasons)}))
    if reason := _above(pressure_quantity, PRESSURE_REVIEW_REFERENCE_GPA):
        findings.append(_finding(result_id, "pressure_high_review", "pressure_gpa", reason, quantity=pressure_quantity,
            applicability={"threshold": PRESSURE_REVIEW_REFERENCE_GPA, "unit": "GPa"}))
    _, pressure_upper = _extent(pressure_quantity)
    bounded_low_pressure = (
        pressure.pressure_state in {"reported", "explicit_ambient"} and not pressure.approximate
        and pressure_upper is not None
        and (pressure_upper < 50 or pressure_upper == 50 and pressure.relation == "lt")
    )
    if actual_family == "hydride" and bounded_low_pressure and (reason := _above(tc, 100)):
        findings.append(_finding(result_id, "hydride_low_pressure_high_tc_review", "tc_kelvin", reason, quantity=tc,
            applicability={"family": "hydride", "tc_threshold_k": 100,
                           "pressure_upper_reference_gpa": 50, "pressure_scope": "entire_reported_extent_below_50"}))
    for field, (minimum, maximum) in PARAMETER_REVIEW_REFERENCES.items():
        if field not in quantities:
            continue
        proposal = quantities[field]
        lower, upper = _extent(proposal)
        if (lower is not None and lower < minimum) or (upper is not None and upper > maximum):
            findings.append(_finding(result_id, "parameter_reference_review", field,
                "reported_extent_outside_legacy_reference_interval", quantity=proposal,
                applicability={"minimum": minimum, "maximum": maximum, "unit": FIELD_UNITS[field]}))
    if record.get("year") is not None:
        year = record["year"]
        if isinstance(year, str) and year.isascii() and year.isdigit() and len(year) == 4:
            year = int(year)
        if isinstance(year, bool) or not isinstance(year, int):
            findings.append(_finding(result_id, "record_year_format_invalid", "year", "year_not_unambiguous_integer"))
        elif year < 1900 or current_year is not None and year > current_year + 1:
            findings.append(_finding(result_id, "record_year_review", "year", "year_outside_operational_window",
                applicability={"minimum_year": 1900, "maximum_year": current_year + 1 if current_year is not None else None}))
    for reference in compound_thresholds:
        if not isinstance(reference, Mapping):
            findings.append(_finding(result_id, "review_context_unresolved", "*", "compound_reference_not_a_mapping"))
            continue
        target = _text(reference.get("field"), 80)
        field = _VIEW_FIELDS.get(target)
        threshold = reference.get("threshold")
        reference_id = _text(reference.get("reference_id"), 160)
        mode = reference.get("mode", "upper_reference")
        if field is None or field == "lattice_params" or not _finite(threshold) or not reference_id or mode not in {"upper_reference", "unreviewed_exact_override"}:
            findings.append(_finding(result_id, "review_context_unresolved", target if field is not None else "*",
                                     "compound_reference_shape_unresolved"))
            continue
        if not _view_applies(target, pressure, origin):
            continue
        if field not in quantities:
            continue
        proposal = quantities[field]
        if proposal["status"] == "unreported":
            continue
        applicability = {"reference_id": reference_id, "target_view": target, "threshold": threshold,
                         "unit": FIELD_UNITS[field], "mode": mode}
        if mode == "unreviewed_exact_override":
            findings.append(_finding(result_id, "legacy_numeric_override_requires_revision", target,
                "legacy_override_value_not_a_source_backed_revision", quantity=proposal, applicability=applicability))
        elif reason := _above(proposal, threshold):
            findings.append(_finding(result_id, "legacy_compound_reference_review", target, reason,
                                     quantity=proposal, applicability=applicability))
    return _assessment(result_id, findings, current_year)


def _assessment(result_id: str, findings: list[dict[str, Any]], current_year: int | None) -> dict[str, Any]:
    unique = {item["finding_id"]: item for item in findings}
    ordered = [unique[key] for key in sorted(unique)]
    rule_counts = {rule: sum(item["rule_id"] == rule for item in ordered) for rule in sorted({item["rule_id"] for item in ordered})}
    affected = sorted({field for item in ordered for field in item["affected_properties"]})
    status = "format_invalid" if any(item["category"] == "format_invalid" for item in ordered) else "review_required" if ordered else "no_findings"
    return {"version": ANOMALY_POLICY_VERSION, "evaluation_year": current_year, "result_id": result_id, "status": status,
            "findings": ordered[:PUBLIC_FINDING_LIMIT], "total_findings": len(ordered),
            "findings_truncated": len(ordered) > PUBLIC_FINDING_LIMIT,
            "rule_counts": rule_counts, "review_required_properties": affected,
            "raw_preserved": True, "scientific_acceptance": False}


def eligible_for_property(assessment: Mapping[str, Any], field: str) -> bool:
    """Default scientific-view eligibility, not approval or an ML admission gate."""
    if assessment.get("version") != ANOMALY_POLICY_VERSION:
        return False
    affected = assessment.get("review_required_properties")
    if not isinstance(affected, list):
        return False
    field = {"tc": "tc_kelvin", "pressure": "pressure_gpa"}.get(field, field)
    return "*" not in affected and field not in affected


def build_anomaly_review(
    records: Any, *, scope_id: str, family: str | None = None,
    compound_thresholds: Sequence[Any] = (), current_year: int | None = None,
    record_limit: int = PUBLIC_RECORD_LIMIT,
) -> dict[str, Any]:
    """Assess all current occurrences while bounding the public read projection."""
    if isinstance(record_limit, bool) or not isinstance(record_limit, int) or not 0 <= record_limit <= PUBLIC_RECORD_LIMIT:
        raise ValueError("record_limit must be an integer between 0 and PUBLIC_RECORD_LIMIT")
    values = records if isinstance(records, (list, tuple)) else [records]
    assessments = [assess_record_anomalies(
        record, scope_id=scope_id, family=family, compound_thresholds=compound_thresholds, current_year=current_year,
    ) for record in values]
    counts = {key: sum(item["status"] == key for item in assessments) for key in ("no_findings", "review_required", "format_invalid")}
    counts["total_records"] = len(assessments)
    rule_counts: dict[str, int] = {}
    for item in assessments:
        for rule, count in item["rule_counts"].items():
            rule_counts[rule] = rule_counts.get(rule, 0) + count
    ordered = sorted(assessments, key=lambda item: item["result_id"])
    return {"version": ANOMALY_POLICY_VERSION, "evaluation_year": current_year, "raw_preserved": True, "scientific_acceptance": False,
            "needs_review": bool(counts["review_required"] or counts["format_invalid"]),
            "counts": counts, "rule_counts": rule_counts, "records": ordered[:record_limit],
            "total_records": len(assessments), "records_truncated": len(assessments) > record_limit,
            "warnings": ["operational_review_references_not_physical_limits",
                         "no_findings_does_not_establish_scientific_acceptance"]}


__all__ = [
    "AMBIENT_TC_REVIEW_REFERENCE_K", "ANOMALY_POLICY_VERSION", "FAMILY_TC_REVIEW_REFERENCES_K",
    "PARAMETER_REVIEW_REFERENCES", "PRESSURE_REVIEW_REFERENCE_GPA", "PUBLIC_FINDING_LIMIT",
    "PUBLIC_RECORD_LIMIT", "TC_REVIEW_REFERENCE_K", "assess_record_anomalies", "build_anomaly_review",
    "eligible_for_property", "record_property_quantity", "rule_registry",
]
