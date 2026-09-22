"""Bounded same-occurrence extraction reports, not source entailment or labels.

This pure selector has no authority over source rights, currentness, immutable
parent association or original-text support. Callers must establish those
bindings independently before exposing any selected record.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace

from models.scientific_query import ScientificQueryInterpretation
from models.scientific_query_result import ScientificQueryResult
from services.anomaly_review import assess_record_anomalies, eligible_for_property
from services.claim_outcomes import MISSING_METHODS, outcome_conflicts_with_positive
from services.pressure_semantics import classify_pressure
from services.rag_evidence_contract import canonical, extraction_projection
from services.scientific_filters import ResultFilters, finite_number
from services.scientific_values import parse_scientific_value, record_quantity

VERSION = "scientific-query-result/1.0.0"
MAX_RECORDS = 1000
MAX_INPUT_BYTES = 1024 * 1024
_QUANTITY_KEYS = ("status", "relation", "value", "lower", "upper", "uncertainty", "approximate", "unit")
_OUTCOME_KEYS = ("result_status", "outcome_state", "outcome")
_BOOL_KEYS = ("no_transition", "not_detected", "superconductivity_observed", "transition_observed", "is_superconducting")
_POSITIVE = {"observed", "detected", "transition_observed", "superconducting", "positive", "positive_reported"}
_NEGATIVE = {"not_detected", "not_observed", "notdetected", "no_transition", "no_superconductivity", "non_transition_observed"}


class ScientificResultSelectionError(ValueError):
    """The bounded selector input cannot be interpreted safely."""


def _bounded_records(records):
    # Reject oversized string inventories before JSON serialization allocates
    # another full copy. canonical() then verifies the exact encoded size.
    pending, nodes, text_bytes = [(records, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 20000 or depth > 20:
            raise ValueError
        if isinstance(item, Mapping):
            pending.extend((value, depth + 1) for pair in item.items() for value in pair)
        elif type(item) is list:
            pending.extend((value, depth + 1) for value in item)
        elif type(item) is str:
            if len(item) > MAX_INPUT_BYTES:
                raise ValueError
            text_bytes += len(item.encode("utf-8"))
            if text_bytes > MAX_INPUT_BYTES:
                raise ValueError
    canonical(records)


def _inputs(record):
    raw = record.get("raw_extraction")
    return (record, raw) if isinstance(raw, Mapping) else (record,)


def _text(value, maximum=160):
    if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    return value.strip()


def _label(record, keys, warnings, name, maximum=160):
    values, malformed = set(), False
    for item in _inputs(record):
        for key in keys:
            if item.get(key) is not None:
                value = _text(item[key], maximum)
                malformed |= value is None
                if value is not None:
                    values.add(value)
    if malformed or len(values) > 1:
        warnings.add(name + "_ambiguous")
        return None
    return next(iter(values)) if values else None


def _invalid(field):
    value = parse_scientific_value(None, field)
    return {**value, "status": "invalid", "errors": ["conflicting_or_invalid_quantity"]}


def _has(record, field, aliases):
    typed = record.get("scientific_values")
    return any(record.get(key) is not None for key in (field, *aliases)) or isinstance(typed, Mapping) and field in typed


def _compatible(selected, other):
    if all(selected[key] == other[key] for key in _QUANTITY_KEYS):
        return True
    # A legacy scalar may retain only the original point or bound endpoint.
    # Preserve the original relation/uncertainty, never promote this scalar.
    return (selected["status"] == other["status"] == "parsed" and other["relation"] == "exact"
            and other["uncertainty"] is None and not other["approximate"]
            and other["value"] in {selected["value"], selected["lower"], selected["upper"]})


def _local_quantity(record, field, aliases):
    selected = record_quantity(record, field, *aliases)
    for key in (field, *aliases):
        if record.get(key) is not None:
            proposal = parse_scientific_value(record[key], field, raw_unit=record.get(key + "_unit"))
            if not _compatible(selected, proposal):
                return _invalid(field)
    return selected


def _quantity(record, field, aliases=()):
    top = _local_quantity(record, field, aliases)
    raw = record.get("raw_extraction")
    if isinstance(raw, Mapping) and _has(raw, field, aliases):
        original = _local_quantity(raw, field, aliases)
        typed = record.get("scientific_values")
        if isinstance(typed, Mapping) and field in typed:
            if any(original[key] != top[key] for key in _QUANTITY_KEYS):
                return _invalid(field)
        elif _has(record, field, aliases) and not _compatible(original, top):
            return _invalid(field)
        top = original
    for item in _inputs(record):
        flags = item.get("validation_flags")
        if isinstance(flags, list) and any(type(flag) is str and flag.split(":", 1)[0] in (field, *aliases) for flag in flags):
            return _invalid(field)
        if field == "tc_kelvin" and any(item.get(key) is not None and item[key] != top["relation"]
                                        for key in ("tc_relation", "value_relation")):
            return _invalid(field)
    if any(top[key] is not None and top[key] < 0 for key in ("value", "lower", "upper", "uncertainty")):
        return _invalid(field)
    return top


def _pressure(record):
    current = classify_pressure(record)
    raw = record.get("raw_extraction")
    if isinstance(raw, Mapping):
        original = classify_pressure(raw)
        if current.pressure_state == "not_reported":
            current = original
        elif original.pressure_state != "not_reported":
            keys = ("relation", "pressure_gpa", "value_lower_gpa", "value_upper_gpa", "uncertainty_gpa", "approximate")
            same = all(getattr(current, key) == getattr(original, key) for key in keys)
            legacy_zero = current.reasons == ("legacy_zero_pressure_not_explicitly_ambient", "legacy_field_unit_assumed_gpa")
            typed = record.get("scientific_values")
            # Old normalized scalars can be lossy copies of a source point or
            # endpoint. Retain the original extent, but never excuse a typed
            # proposal conflict or an ambient/ambiguous condition conflict.
            scalar_copy = (not (isinstance(typed, Mapping) and "pressure_gpa" in typed)
                and current.pressure_state == original.pressure_state == "reported"
                and current.relation == "exact" and current.uncertainty_gpa is None and not current.approximate
                and current.pressure_gpa is not None and current.pressure_gpa in
                {original.pressure_gpa, original.value_lower_gpa, original.value_upper_gpa})
            if same and (current.pressure_state == original.pressure_state or legacy_zero) or scalar_copy:
                current = original
            else:
                current = replace(current, pressure_state="ambiguous")
    for item in _inputs(record):
        if (item.get("pressure_condition") is not None and type(item["pressure_condition"]) is not str
                or item.get("pressure_state") is not None and type(item["pressure_state"]) is not str):
            current = replace(current, pressure_state="ambiguous")
        for key in ("pressure_gpa", "pressure"):
            if item.get(key) is not None:
                local = classify_pressure({key: item[key], key + "_unit": item.get(key + "_unit", item.get("pressure_unit"))})
                exact_copy = all(getattr(local, field) == getattr(current, field) for field in
                    ("relation", "pressure_gpa", "value_lower_gpa", "value_upper_gpa", "uncertainty_gpa", "approximate"))
                scalar_copy = (local.relation == "exact" and local.uncertainty_gpa is None and not local.approximate
                    and local.pressure_gpa is not None and local.pressure_gpa in
                    {current.pressure_gpa, current.value_lower_gpa, current.value_upper_gpa})
                if not (exact_copy or scalar_copy):
                    current = replace(current, pressure_state="ambiguous")
        flags = item.get("validation_flags")
        if isinstance(flags, list) and any(type(flag) is str and flag.split(":", 1)[0] in
                                          ("pressure_gpa", "pressure", "pressure_condition", "pressure_state") for flag in flags):
            current = replace(current, pressure_state="ambiguous")
    return current


def _outcome(record):
    positive, negative, unresolved = False, False, False
    for item in _inputs(record):
        flags = item.get("validation_flags")
        unresolved |= isinstance(flags, list) and any(type(flag) is str and flag.split(":", 1)[0] in _OUTCOME_KEYS + _BOOL_KEYS for flag in flags)
        for key in _OUTCOME_KEYS:
            value = item.get(key)
            if value is None:
                continue
            if type(value) is not str:
                unresolved = True
                continue
            slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
            positive |= slug in _POSITIVE
            negative |= slug in _NEGATIVE
            unresolved |= slug not in _POSITIVE | _NEGATIVE
        for key in _BOOL_KEYS:
            value = item.get(key)
            if value is not None and type(value) is not bool:
                unresolved = True
            elif type(value) is bool:
                negative |= value if key in _BOOL_KEYS[:2] else not value
                positive |= value if key in _BOOL_KEYS[2:] else False
    if positive and negative:
        return "conflicted"
    if unresolved:
        return "unresolved"
    if negative:
        return "not_detected"
    if any(outcome_conflicts_with_positive(item) for item in _inputs(record)):
        return "unresolved"
    return "positive_reported" if positive else "unspecified"


def _quantity_dto(value):
    return {key: value[key] for key in (*_QUANTITY_KEYS, "unit_basis", "uncertainty_interpretation")}


def _pressure_dto(value):
    status = "parsed" if value.pressure_state in {"reported", "explicit_ambient"} else "unreported" if value.pressure_state == "not_reported" else "invalid"
    return {"status": status, "pressure_state": value.pressure_state, "relation": value.relation,
            "value": value.pressure_gpa, "lower": value.value_lower_gpa, "upper": value.value_upper_gpa,
            "uncertainty": value.uncertainty_gpa, "approximate": value.approximate, "unit": "GPa",
            "unit_basis": value.unit_basis, "uncertainty_interpretation": value.uncertainty_interpretation}


def _entails(quantity, constraint):
    if quantity["status"] != "parsed" or quantity["approximate"] or quantity["unit"] != constraint["unit"]:
        return False
    relation = quantity["relation"]
    lower, upper = quantity["lower"], quantity["upper"]
    lower_open, upper_open = relation == "gt", relation == "lt"
    if relation == "exact":
        spread = quantity["uncertainty"] or 0
        lower, upper = quantity["value"] - spread, quantity["value"] + spread
    requested = constraint["relation"]
    if requested == "exact":
        return lower is not None and lower == upper == constraint["value"] and not lower_open and not upper_open
    if requested in {"gt", "ge", "interval"}:
        limit = constraint["lower"] if requested == "interval" else constraint["value"] if constraint["value"] is not None else constraint["lower"]
        if lower is None or lower < limit or requested == "gt" and lower == limit and not lower_open:
            return False
    if requested in {"lt", "le", "interval"}:
        limit = constraint["upper"] if requested == "interval" else constraint["value"] if constraint["value"] is not None else constraint["upper"]
        if upper is None or upper > limit or requested == "lt" and upper == limit and not upper_open:
            return False
    return True


def _anomaly_assessment(record, quantities, pressure, classification, family, scope_id):
    """Adapt resolved original proposals, not legacy cache scalars or approvals.

    Internal pressure/origin labels here come only from the conflict-checked
    source assertions above. No data is written and no approval is inferred.
    """
    resolved = {"formula": record.get("formula"), "family": family, **classification,
        "pressure_state": pressure.pressure_state,
        "pressure_condition": "ambient pressure" if pressure.pressure_state == "explicit_ambient" else None,
        "scientific_values": {**quantities, "pressure_gpa": {
            "raw_value": pressure.raw_value, "input_unit": pressure.raw_unit,
        }}}
    return assess_record_anomalies(resolved, scope_id=scope_id)


def _validate_filters(filters):
    if filters is None:
        return ResultFilters()
    if type(filters) is not ResultFilters:
        raise ValueError
    for field in ("ambient_only", "include_unknown_pressure", "experimental_only", "only_aps", "positive_tc"):
        if type(getattr(filters, field)) is not bool:
            raise ValueError
    for field in ("tc_min", "pressure_min", "pressure_max"):
        value = getattr(filters, field)
        if value is not None and (finite_number(value) is None or value < 0):
            raise ValueError
    if filters.pressure_min is not None and filters.pressure_max is not None and filters.pressure_min > filters.pressure_max:
        raise ValueError
    if (type(filters.families) is not tuple or len(filters.families) > 100
            or any(_text(value) is None for value in filters.families)
            or type(filters.origins) is not tuple or len(filters.origins) > 5
            or any(type(value) is not str or value not in {"Observed", "Computed", "Inferred", "AI-Proposed", "Unknown"}
                   for value in filters.origins)
            or filters.source_role is not None and filters.source_role not in ("primary", "cited", "unknown", "conflicted")):
        raise ValueError
    # Source authority is not established by raw occurrence labels. These
    # source-level predicates belong in the independently verified caller.
    if filters.only_aps or filters.min_tier is not None:
        raise ValueError
    return filters


def _matches_filters(filters, *, quantities, pressure, classification, family, outcome, anomaly):
    if filters.families and family not in filters.families:
        return False
    if filters.origins and classification["knowledge_origin"] not in filters.origins:
        return False
    if filters.source_role is not None and classification["source_role"] != filters.source_role:
        return False
    if filters.experimental_only and (classification["knowledge_origin"] != "Observed"
            or classification["classification_status"] != "resolved"):
        return False
    if filters.tc_min is not None or filters.positive_tc:
        if outcome in {"not_detected", "unresolved", "conflicted"} or not eligible_for_property(anomaly, "tc_kelvin"):
            return False
        for relation, lower in (("ge", filters.tc_min), ("gt", 0 if filters.positive_tc else None)):
            if lower is not None and not _entails(quantities["tc_kelvin"], {
                    "relation": relation, "lower": lower, "value": None, "unit": "K"}):
                return False
    if filters.pressure_min is not None or filters.pressure_max is not None or filters.ambient_only:
        # Unknown inclusion is a browsing preference, not evidence that an
        # absent or ambiguous reported extent satisfies a scientific bound.
        if pressure["status"] != "parsed" or not eligible_for_property(anomaly, "pressure_gpa"):
            return False
        if filters.ambient_only and (pressure["pressure_state"] != "explicit_ambient"
                or not eligible_for_property(anomaly, "tc_ambient")):
            return False
        for relation, bound in (("ge", filters.pressure_min), ("le", filters.pressure_max)):
            if bound is not None and not _entails(pressure, {
                    "relation": relation, "lower" if relation == "ge" else "upper": bound, "value": None, "unit": "GPa"}):
                return False
    return True


def select_record_results(records, interpretation, *, scope_id, filters: ResultFilters | None = None):
    """Return strict closed DTOs for independently matched supplied occurrences.

    Bounds use set containment, including strict endpoints. Missing state labels
    are disclosed, never synthesized. No formula equality establishes identity
    across records, source captures, experiments, samples or material states.
    """
    from services.scientific_query import normalize_query_formula

    try:
        if type(records) is not list or len(records) > MAX_RECORDS or _text(scope_id, 200) is None:
            raise ValueError
        _bounded_records(records)
        filters = _validate_filters(filters)
        query = ScientificQueryInterpretation.model_validate(
            interpretation.model_dump() if isinstance(interpretation, ScientificQueryInterpretation) else interpretation,
            strict=True).model_dump()
        if query["status"] != "resolved":
            return []
        if not (filters.active or query["requested_fields"] or query["constraints"] or query["evidence_constraints"] or query["formulas"]):
            return []
        wanted = {item["normalization"]["normalized_formula"] for item in query["formulas"]}
        if None in wanted:
            return []
        results = []
        for index, record in enumerate(records):
            if type(record) is not dict or "raw_extraction" in record and not isinstance(record["raw_extraction"], Mapping):
                continue
            if any(item.get("validation_flags") is not None and (type(item["validation_flags"]) is not list
                    or any(type(flag) is not str for flag in item["validation_flags"])) for item in _inputs(record)):
                continue
            warnings = {"machine_extraction_not_scientific_approval", "same_record_not_resolved_sample_identity"}
            formula_inputs = [item["formula"] for item in _inputs(record) if item.get("formula") is not None]
            if not formula_inputs or any(_text(value, 200) is None for value in formula_inputs):
                continue
            formula = _text(formula_inputs[0], 200)
            normalized = normalize_query_formula(formula)
            if any(value != formula and (normalized.status != "normalized"
                    or normalize_query_formula(value).status != "normalized"
                    or normalize_query_formula(value).normalized_formula != normalized.normalized_formula)
                   for value in formula_inputs[1:]):
                continue
            if wanted and (normalized.status != "normalized" or normalized.normalized_formula not in wanted):
                continue
            if normalized.status != "normalized":
                warnings.add("formula_normalization_unresolved")
            projection = extraction_projection(record)
            classification = {key: projection[key] for key in ("knowledge_origin", "classification_status", "source_role")}
            if classification["classification_status"] == "conflicted" or classification["source_role"] == "conflicted":
                continue
            outcome = _outcome(record)
            quantities = {"tc_kelvin": _quantity(record, "tc_kelvin", ("tc",)),
                          "minimum_temperature_k": _quantity(record, "minimum_temperature_k")}
            pressure = _pressure(record)
            pressure_dto = _pressure_dto(pressure)
            family = _label(record, ("family", "material_family"), warnings, "family")
            anomaly = _anomaly_assessment(record, quantities, pressure, classification, family, scope_id)
            if not _matches_filters(filters, quantities=quantities, pressure=pressure_dto,
                                    classification=classification, family=family, outcome=outcome, anomaly=anomaly):
                continue
            if any(not eligible_for_property(anomaly, constraint["field"])
                   or constraint["unit_basis"] == "explicit_ambient_reference" and not eligible_for_property(anomaly, "tc_ambient")
                   for constraint in query["constraints"]):
                continue
            if anomaly["status"] != "no_findings":
                warnings.add("local_anomaly_review_required")
                warnings.update("local_review_rule_" + rule for rule in anomaly["rule_counts"])
            if any(constraint["field"] == "tc_kelvin" for constraint in query["constraints"]) and outcome in {"not_detected", "unresolved", "conflicted"}:
                continue
            if any(not _entails(pressure_dto if constraint["field"] == "pressure_gpa" else quantities["tc_kelvin"], constraint)
                   or constraint["unit_basis"] == "explicit_ambient_reference" and pressure.pressure_state != "explicit_ambient"
                   for constraint in query["constraints"]):
                continue
            if any((outcome if constraint["field"] == "experimental_outcome" else classification[constraint["field"]]) != constraint["value"]
                   for constraint in query["evidence_constraints"]):
                continue
            if outcome in {"unresolved", "conflicted"}:
                continue
            if outcome == "not_detected" and quantities["tc_kelvin"]["relation"] not in {"unreported", "lt", "le"}:
                quantities["tc_kelvin"] = _invalid("tc_kelvin")
                warnings.add("positive_tc_not_inferred_from_non_detection")
            if quantities["tc_kelvin"]["status"] != "parsed" and pressure_dto["status"] != "parsed" and outcome != "not_detected":
                continue
            context = {name: _label(record, keys, warnings, name) for name, keys in {
                "tc_criterion": ("tc_criterion", "tc_definition", "tc_type"),
                "sample_label": ("sample_label", "sample_id"), "sample_form": ("sample_form",),
                "structure_phase": ("structure_phase", "structure_phase_raw"),
                "measurement_method": ("measurement_method", "measurement", "method"),
            }.items()}
            for name in ("tc_criterion", "sample_label", "structure_phase"):
                if context[name] is None:
                    warnings.add(name + "_unreported_or_unresolved")
            if outcome == "not_detected":
                warnings.add("non_detection_is_condition_specific_not_negative_training_label")
                if quantities["minimum_temperature_k"]["status"] != "parsed":
                    warnings.add("minimum_test_temperature_unreported_or_invalid")
                if context["measurement_method"] is None or context["measurement_method"].lower() in MISSING_METHODS:
                    warnings.add("non_detection_measurement_method_unreported")
            if classification["knowledge_origin"] == "Unknown":
                warnings.add("result_origin_unresolved")
            if classification["source_role"] == "unknown":
                warnings.add("source_role_unresolved")
            for field, proposal in quantities.items():
                if proposal["unit_basis"] == "field_schema_assumption":
                    warnings.add(field + "_unit_assumed_from_legacy_field")
                if proposal["uncertainty"] is not None:
                    warnings.add(field + "_uncertainty_interpretation_unspecified")
            if pressure.pressure_state in {"ambiguous", "not_reported"}:
                warnings.add("pressure_" + pressure.pressure_state)
            results.append(ScientificQueryResult(
                result_id="legacy-result:" + hashlib.sha256(canonical([scope_id, record])).hexdigest(), record_index=index,
                formula=formula, family=family,
                tc=_quantity_dto(quantities["tc_kelvin"]), pressure=pressure_dto,
                minimum_temperature=_quantity_dto(quantities["minimum_temperature_k"]),
                result_classification=classification, outcome_state=outcome, reported_context=context,
                warning_codes=sorted(warnings)))
        return results
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise ScientificResultSelectionError("Scientific report selection input is invalid or exceeds its bounded scope") from None
