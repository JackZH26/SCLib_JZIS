"""Small source-backed material vocabulary; reports are never approval.

Vendored byte-for-byte by API and ingestion. This pure read projection never
edits raw records, joins formulas, votes on truth, or counts replication.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from .pressure_semantics import classify_pressure
from .result_semantics import classify_result

if __package__ == "ingestion":
    from .extract.scientific_values import record_quantity
else:
    from .scientific_values import record_quantity

MATERIAL_SEMANTICS_VERSION = "material-semantics/1.0.0"
MATERIAL_SEMANTICS_FIELDS = ("has_competing_order", "is_unconventional", "pairing_symmetry")
STATUS_VOCABULARY = ("reported", "unknown", "not_reported", "not_extracted", "not_computed", "failed", "conflicted", "not_applicable")
MAX_RECORDS = 10000
MAX_EVIDENCE = 20
MAX_COMPARISONS = 10000
_ORDERS = frozenset({"CDW", "AFM", "SDW", "Mott_insulator", "PDW"})
_DERIVED = frozenset({"material_semantics", "property_evidence", "anomaly_review", "visibility", "pressure_semantics", "result_classification", "result_metadata", "structure_evidence", "ingestion_capture", "temporal_provenance",
                      "admin_decision", "review_reason", "reviewed_by", "reviewed_at"})
_STATE_TEXT = ("state_id", "sample_id", "structure_id", "run_id", "sample_form", "substrate", "structure_phase", "doping_type")
_LOCATOR = ("page", "table", "figure", "row", "column", "section", "chunk_id", "span_id")
_CONDITIONS = ("description", "temperature_min_k", "temperature_max_k", "magnetic_field_t", "pressure_gpa", "detection_limit", "protocol_id")
_QUANTITY_KEYS = ("relation", "value", "lower", "upper", "uncertainty", "approximate", "unit")
_STATUS_ALIASES = {"n/a": "not_applicable", "not applicable": "not_applicable", "not reported": "not_reported",
                   "not extracted": "not_extracted", "not computed": "not_computed", "none": "unknown", "null": "unknown", "": "unknown"}
_MISSING_TEXT = frozenset(STATUS_VOCABULARY[1:]) | frozenset(_STATUS_ALIASES)


def _text(value: Any, limit: int = 160) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() and len(value) <= limit else None


def _scalar(value: Any, limit: int = 160) -> Any:
    if isinstance(value, str):
        return _text(value, limit)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return value if math.isfinite(value) else None
        except OverflowError:
            return None
    return None


def _selected(mapping: Any, fields: tuple, limit: int = 160) -> dict:
    return {key: value for key in fields if (value := _scalar(mapping.get(key), limit)) is not None} if isinstance(mapping, Mapping) else {}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _identity(record: Mapping, scope: str) -> str:
    budget = 10000
    chars = 100000

    def visit(value: Any, depth: int = 0) -> Any:
        nonlocal budget, chars
        budget -= 1
        if budget < 0 or depth > 16:
            raise ValueError("record_identity_budget")
        if isinstance(value, str):
            chars -= len(value)
            if chars < 0:
                raise ValueError("record_identity_budget")
            return value
        if value is None or isinstance(value, (int, bool)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else {"nonfinite": str(value)}
        if isinstance(value, Mapping):
            return {key: visit(item, depth + 1) for key, item in value.items()
                    if isinstance(key, str) and key not in _DERIVED
                    and not key.startswith(("reviewer", "curator", "private_review", "internal_review"))}
        if isinstance(value, (list, tuple)):
            return [visit(item, depth + 1) for item in value]
        raise ValueError("record_identity_format")

    return "legacy-semantics:" + _digest([scope, visit(record)])


def _source_status(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 80:
        return "unknown"
    token = value.strip().lower()
    if token in {"active", "active_research", "published", "preprint", "indexed", "processed"}:
        return "active"
    if token in {"withdrawn", "retracted"}:
        return "retracted"
    if token in {"corrected", "disputed", "quarantined", "pending"}:
        return token
    return "unknown"


def _sources(record: Mapping, statuses: Any) -> tuple[list[dict], str, list[str]]:
    identifiers = [{"kind": key, "value": value} for key in ("paper_id", "doi", "arxiv_id")
                   if (value := _text(record.get(key), 200)) is not None]
    reasons = []
    paper_id = _text(record.get("paper_id"), 200)
    if not identifiers:
        reasons.append("bibliographic_source_missing")
    if statuses is None:
        state = "unknown"
        reasons.append("current_source_status_not_checked")
    elif not isinstance(statuses, Mapping):
        state = "unknown"
        reasons.append("source_status_map_invalid")
    else:
        state = _source_status(statuses.get(paper_id)) if paper_id else "unknown"
        if state != "active":
            reasons.append("current_source_" + state)
    raw_status = _source_status(record.get("source_status"))
    if record.get("source_status") is not None and (
        not isinstance(record["source_status"], str)
        or raw_status == "unknown" and record["source_status"].strip().lower() not in {"", "unknown", "not_reported"}
    ):
        state = "unknown"
        reasons.append("record_source_status_invalid")
    if raw_status not in {"unknown", "active"}:
        state = raw_status
        reasons.append("record_source_" + state)
    return identifiers, state, reasons


def _record_holds(record: Mapping) -> list[str]:
    reasons = []
    for key in ("needs_review", "retracted", "corrected", "disputed"):
        value = record.get(key)
        if value is True:
            reasons.append("record_" + key)
        elif value is not None and not isinstance(value, bool):
            reasons.append("record_governance_invalid")
    for key in ("status", "review_status", "provenance_status"):
        value = record.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 160):
            reasons.append("record_governance_invalid")
        elif isinstance(value, str) and value.strip().lower() in {"retracted", "withdrawn", "disputed", "refuted", "quarantined", "pending", "corrected", "excluded"}:
            reasons.append("record_governance_hold")
    reason = record.get("review_reason")
    if reason is not None and not isinstance(reason, str):
        reasons.append("record_governance_invalid")
    if isinstance(reason, str) and reason.lower().startswith("provenance_quarantine"):
        reasons.append("record_provenance_quarantined")
    return sorted(set(reasons))


def _conditions(record: Mapping, field: str) -> tuple[dict, bool]:
    raw = record.get(field + "_detection_conditions", record.get("detection_conditions"))
    if isinstance(raw, str):
        text = _text(raw, 240)
        return ({"description": text}, False) if text and text.lower() not in _MISSING_TEXT else ({}, True)
    if raw is None:
        return {}, False
    if not isinstance(raw, Mapping):
        return {}, True
    result = _selected(raw, _CONDITIONS, 240)
    invalid = False
    for key in _CONDITIONS:
        value = raw.get(key)
        if value is None:
            continue
        if key in {"temperature_min_k", "temperature_max_k", "magnetic_field_t", "pressure_gpa"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or _scalar(value) is None:
                invalid = True
                result.pop(key, None)
        elif not isinstance(value, str) or _text(value, 240) is None or value.strip().lower() in _MISSING_TEXT:
            invalid = True
            result.pop(key, None)
    lower, upper = result.get("temperature_min_k"), result.get("temperature_max_k")
    if (lower is not None and lower < 0 or upper is not None and upper < 0
            or lower is not None and upper is not None and lower > upper):
        invalid = True
    return result, invalid


def _state(record: Mapping) -> dict:
    result = _selected(record, _STATE_TEXT)
    pressure = classify_pressure(record)
    result["pressure"] = {"state": pressure.pressure_state, "relation": pressure.relation,
                          "value": pressure.pressure_gpa, "lower": pressure.value_lower_gpa,
                          "upper": pressure.value_upper_gpa, "uncertainty": pressure.uncertainty_gpa}
    doping = record_quantity(record, "doping_level")
    if doping["status"] == "parsed" and not doping["errors"]:
        result["doping_level"] = {key: doping[key] for key in _QUANTITY_KEYS}
    return result


def _different_states(left: dict, right: dict) -> bool:
    for key in _STATE_TEXT + ("doping_level",):
        if left.get(key) is not None and right.get(key) is not None and left[key] != right[key]:
            return True
    a, b = left.get("pressure", {}), right.get("pressure", {})
    return a.get("state") in {"reported", "explicit_ambient"} and b.get("state") in {"reported", "explicit_ambient"} and a != b


def _raw_property(record: Mapping, field: str) -> tuple[str, Any, str, list[str], Any]:
    raw = record.get(field)
    declared = record.get(field + "_status")
    reason = _text(record.get(field + "_reason"), 240)
    basis, reasons, source_value = "explicit_record_value", [], None
    status = None
    if declared is not None:
        label = _text(declared, 40)
        if label is None or label.lower() not in STATUS_VOCABULARY:
            return "unknown", None, "unresolved_record_metadata", ["property_status_invalid"], None
        status = label.lower()
    if isinstance(raw, str) and raw.strip().lower() in set(STATUS_VOCABULARY) | set(_STATUS_ALIASES):
        status = status or _STATUS_ALIASES.get(raw.strip().lower(), raw.strip().lower())
        raw = None
    if field == "has_competing_order" and isinstance(record.get("competing_order"), str) and record["competing_order"] in _ORDERS:
        source_value = record["competing_order"]
        if raw is False:
            return "conflicted", False, "conflicting_record_channels", ["competing_order_indicator_conflicts_with_false"], source_value
        if raw is None and status in {None, "reported"}:
            raw, basis = True, "reported_competing_order_label"
            reasons.append("reported_order_indicator_not_causal_competition")
    if status is not None and status != "reported":
        if raw is not None:
            return "conflicted", raw if isinstance(raw, bool) else _text(raw), "conflicting_record_channels", ["value_and_missingness_status_conflict"], source_value
        if status == "not_applicable" and reason is None:
            return "unknown", None, "unqualified_status_declaration", ["not_applicable_requires_reason"], source_value
        return status, None, "explicit_status_declaration", ["source_declared_" + status], source_value
    if raw is None:
        return "unknown", None, "unresolved_missingness", ["not_reported_or_not_extracted_unresolved"], source_value
    if field in {"has_competing_order", "is_unconventional"}:
        value = raw if isinstance(raw, bool) else None
    else:
        if isinstance(raw, str) and len(raw) > 100:
            return "unknown", None, "unresolved_record_value", ["pairing_symmetry_value_exceeds_storage_limit"], source_value
        value = _text(raw, 100)
    if value is None:
        return "unknown", None, "unresolved_record_value", ["property_value_invalid"], source_value
    return "reported", value, basis, reasons, source_value


def _evidence(record: Mapping, field: str, *, scope_id: str, occurrence_id: str, source_statuses: Any) -> dict:
    status, value, basis, reasons, source_value = _raw_property(record, field)
    identifiers, source_status, source_reasons = _sources(record, source_statuses)
    reasons.extend(source_reasons)
    holds = _record_holds(record)
    reasons.extend(holds)
    origin = classify_result(record)
    if origin.classification_status == "conflicted" or origin.source_role == "conflicted":
        reasons.append("result_classification_conflict")
    method = next((_text(record.get(key)) for key in (field + "_method", "measurement_method", "measurement", "method", "calculation_method")
                   if _text(record.get(key)) and record[key].strip().lower() not in _MISSING_TEXT), None)
    conditions, conditions_invalid = _conditions(record, field)
    qualified_negative = value is False and not conditions_invalid and bool(method and conditions and identifiers)
    if conditions_invalid:
        reasons.append("detection_conditions_invalid")
    if value is False and not qualified_negative:
        reasons.append("explicit_false_requires_method_detection_conditions_and_source")
    prior_basis = _text(record.get(field + "_basis"), 80)
    if prior_basis in {"family_prior", "physics_prior", "family_default", "inferred_family_default"}:
        reasons.append("prior_not_result_specific_evidence")
        basis = "source_declared_prior"
    source_ok = (bool(identifiers) and (source_statuses is None or source_status == "active")
                 and source_status not in {"retracted", "corrected", "disputed", "quarantined", "pending"}
                 and "record_source_status_invalid" not in reasons)
    eligible = source_ok and not holds and "result_classification_conflict" not in reasons and basis != "source_declared_prior"
    if status == "reported":
        eligible &= value is not False or qualified_negative
    elif status == "not_applicable":
        eligible &= _text(record.get(field + "_reason"), 240) is not None
    else:
        eligible = status in {"unknown", "not_reported", "not_extracted", "not_computed", "failed"} and not holds
    supplied = _text(record.get("result_id"), 200)
    revision = _scalar(record.get("result_revision", record.get("revision")), 100)
    return {
        "result_id": supplied or occurrence_id, "result_revision": revision, "occurrence_id": occurrence_id,
        "paper_id": _text(record.get("paper_id"), 200), "bibliographic_identifiers": identifiers,
        "source_status": source_status, "status": status, "value": value, "basis": basis,
        "eligible_for_summary": bool(eligible), "negative_qualified": bool(qualified_negative and eligible),
        "knowledge_origin": origin.knowledge_origin, "classification_status": origin.classification_status,
        "source_role": origin.source_role, "state": _state(record), "method": method,
        "detection_conditions": conditions, "source_locator": _selected(record.get("source_locator"), _LOCATOR, 120),
        "status_reason": _text(record.get(field + "_reason"), 240), "source_value": source_value,
        "reason_codes": sorted(set(reasons)),
    }


def _conflict_item(field: str, evidence: list[dict], reason: str) -> dict:
    result_ids = sorted({item["result_id"] for item in evidence})
    occurrence_ids = sorted({item["occurrence_id"] for item in evidence})
    return {"property": field, "result_ids": result_ids[:MAX_EVIDENCE],
            "occurrence_ids": occurrence_ids[:MAX_EVIDENCE], "result_count": len(result_ids),
            "occurrence_count": len(occurrence_ids), "identifiers_truncated": len(result_ids) > MAX_EVIDENCE or len(occurrence_ids) > MAX_EVIDENCE,
            "reason_codes": [reason]}


def _bounded_conflicts(items: list[dict]) -> dict:
    unique = {_digest(item): item for item in items}
    ordered = [unique[key] for key in sorted(unique)]
    return {"detected": bool(ordered), "count": len(ordered), "properties": sorted({item["property"] for item in ordered}),
            "evidence": ordered[:MAX_EVIDENCE], "total_evidence": len(ordered), "evidence_truncated": len(ordered) > MAX_EVIDENCE}


def _priors(family: Any) -> list[dict]:
    if family != "cuprate":
        return []
    return [{"property": field, "value": value, "knowledge_origin": "Inferred", "basis": "legacy_family_heuristic",
             "policy_version": MATERIAL_SEMANTICS_VERSION,
             "provenance": {"kind": "legacy_sclib_application_rule", "scientific_citation": None},
             "applicability": {"family": "cuprate", "sample_state": "not_assessed", "universally_applicable": False},
             "warning_codes": ["inferred_prior_not_result_evidence", "not_universally_applicable", "scientific_reference_not_adjudicated"]}
            for field, value in (("pairing_symmetry", "d-wave"), ("is_unconventional", True))]


def build_material_semantics(records: Any, *, scope_id: str, family: str | None = None,
                             legacy_summary: Mapping | None = None, source_statuses: Mapping | None = None) -> dict:
    """Project three source-bound properties without voting or auto-adjudication."""
    legacy = legacy_summary if isinstance(legacy_summary, Mapping) else {}
    values = records if isinstance(records, (list, tuple)) else []
    incomplete = len(values) > MAX_RECORDS or not isinstance(records, (list, tuple))
    warnings = {"reported_does_not_mean_scientifically_accepted", "identifiers_do_not_establish_independent_replication"}
    if source_statuses is None:
        warnings.add("current_source_status_not_checked")
    evidence = {field: [] for field in MATERIAL_SEMANTICS_FIELDS}
    tc_observations = {}
    identifiers, occurrence_ids = set(), set()
    structured = backed = invalid = 0
    dispute_evidence = []
    for record in values[:MAX_RECORDS]:
        if not isinstance(record, Mapping):
            invalid += 1
            incomplete = True
            continue
        try:
            occurrence = _identity(record, scope_id)
            entries = {field: _evidence(record, field, scope_id=scope_id, occurrence_id=occurrence, source_statuses=source_statuses)
                       for field in MATERIAL_SEMANTICS_FIELDS}
            tc = record_quantity(record, "tc_kelvin", "tc")
        except (ValueError, TypeError, OverflowError, RecursionError):
            invalid += 1
            incomplete = True
            continue
        structured += 1
        occurrence_ids.add(occurrence)
        source_ids = entries[MATERIAL_SEMANTICS_FIELDS[0]]["bibliographic_identifiers"]
        identifiers.update((item["kind"], item["value"]) for item in source_ids)
        backed += bool(source_ids)
        for field, item in entries.items():
            evidence[field].append(item)
        if (tc["status"] == "parsed" and not tc["errors"] and tc["relation"] == "exact"
                and tc["uncertainty"] is None and not tc["approximate"]
                and _scalar(tc["value"]) is not None and tc["value"] > 0):
            tc_observations[occurrence] = {**entries[MATERIAL_SEMANTICS_FIELDS[0]], "tc_value": tc["value"]}
        if record.get("disputed") is True or record.get("scientific_dispute") is True:
            dispute_evidence.append({"result_id": entries[MATERIAL_SEMANTICS_FIELDS[0]]["result_id"],
                                     "paper_id": _text(record.get("paper_id"), 200), "reason_codes": ["explicit_unadjudicated_dispute_marker"]})
    if legacy.get("disputed") is True:
        dispute_evidence.append({"result_id": None, "paper_id": None, "reason_codes": ["legacy_governance_dispute_flag"]})
    properties, state_conflicts, extraction_conflicts = {}, [], []
    comparisons = 0
    for field, items in evidence.items():
        distinct = {}
        for item in items:
            key = _digest(item)
            if key in distinct:
                distinct[key]["occurrence_count"] += 1
            else:
                distinct[key] = {**item, "occurrence_count": 1}
        items = sorted(distinct.values(), key=lambda item: (item["occurrence_id"], _digest(item)))
        local_extraction = []
        by_revision = defaultdict(list)
        by_value = defaultdict(list)
        for item in items:
            if item["status"] == "conflicted" and item["basis"] == "conflicting_record_channels":
                local_extraction.append(_conflict_item(field, [item], "contradictory_extraction_channels"))
            if item["status"] == "reported" and item["value"] is not None:
                by_value[_digest(item["value"])].append(item)
                if not item["result_id"].startswith("legacy-semantics:") and item["result_revision"] is not None:
                    by_revision[(item["result_id"], str(item["result_revision"]))].append(item)
        for group in by_revision.values():
            if len({_digest(item["value"]) for item in group}) > 1:
                local_extraction.append(_conflict_item(field, group, "same_supplied_result_revision_value_conflict"))
        local_state = []
        groups = [by_value[key] for key in sorted(by_value)]
        stop = False
        for index, group in enumerate(groups):
            for other in groups[index + 1:]:
                for left in group:
                    for right in other:
                        comparisons += 1
                        if comparisons > MAX_COMPARISONS:
                            incomplete, stop = True, True
                            break
                        if _different_states(left["state"], right["state"]):
                            local_state.append(_conflict_item(field, [left, right], "reported_state_context_differs"))
                    if stop:
                        break
                if stop:
                    break
            if stop:
                break
        extraction_conflicts.extend(local_extraction)
        state_conflicts.extend(local_state)
        reasons = set()
        eligible = [item for item in items if item["eligible_for_summary"] and item["status"] == "reported"]
        value, status, basis = None, "unknown", "unresolved_retained_records"
        if local_extraction:
            status, basis = "conflicted", "extraction_conflict"
            reasons.add("extraction_conflict_requires_review")
        elif any(item["status"] == "conflicted" for item in items):
            status, basis = "conflicted", "explicit_property_conflict_declaration"
            reasons.add("declared_property_conflict_requires_review")
        elif len(by_value) > 1:
            reasons.add("reported_state_variability" if local_state else "value_alternatives_context_unresolved")
        elif eligible:
            status, value, basis = "reported", eligible[0]["value"], "consistent_eligible_reported_occurrences"
        else:
            declared = {item["status"] for item in items if item["eligible_for_summary"]}
            if len(declared) == 1:
                candidate = next(iter(declared))
                if candidate != "reported":
                    status, basis = candidate, "explicit_status_declaration" if candidate != "unknown" else basis
            if not items:
                reasons.add("no_retained_property_evidence")
            elif any(item["value"] is False for item in items):
                reasons.add("unqualified_or_ineligible_negative_report")
            else:
                reasons.add("no_eligible_reported_value")
        if field in legacy and legacy[field] is not None and (status != "reported" or type(legacy[field]) is not type(value) or legacy[field] != value):
            reasons.add("legacy_summary_not_source_supported")
        # Preserve an inspectable witness even when many missing entries would
        # otherwise fill the bounded display before the contributing result.
        displayed = sorted(items, key=lambda item: (not (item["eligible_for_summary"] and item["status"] == "reported" and type(item["value"]) is type(value) and item["value"] == value), item["occurrence_id"]))
        properties[field] = {"status": status, "value": value, "basis": basis, "reason_codes": sorted(reasons),
                             "evidence": displayed[:MAX_EVIDENCE], "total_evidence": len(items),
                             "total_occurrences": sum(item["occurrence_count"] for item in items), "evidence_truncated": len(items) > MAX_EVIDENCE}
    # Tc variation is only a context diagnostic, never a fourth classification
    # property or an automatic dispute. Do not invent comparable states when
    # identity/pressure/doping context is absent, or turn ranges into points.
    tc_groups = defaultdict(list)
    for observation in sorted(tc_observations.values(), key=lambda item: item["occurrence_id"]):
        tc_groups[observation["tc_value"]].append(observation)
    groups = [tc_groups[key] for key in sorted(tc_groups)]
    stop = False
    for index, group in enumerate(groups):
        for other in groups[index + 1:]:
            for left in group:
                for right in other:
                    comparisons += 1
                    if comparisons > MAX_COMPARISONS:
                        incomplete, stop = True, True
                        break
                    if _different_states(left["state"], right["state"]):
                        state_conflicts.append(_conflict_item("tc_kelvin", [left, right], "reported_tc_and_state_context_differ"))
                if stop:
                    break
            if stop:
                break
        if stop:
            break
    if incomplete:
        warnings.add("assessment_incomplete")
        for item in properties.values():
            item.update(status="unknown", value=None, reason_codes=sorted(set(item["reason_codes"] + ["assessment_incomplete"])) )
    dispute_evidence.sort(key=_digest)
    legacy_count = legacy.get("total_papers")
    legacy_count = legacy_count if isinstance(legacy_count, int) and not isinstance(legacy_count, bool) and legacy_count >= 0 else None
    return {
        "version": MATERIAL_SEMANTICS_VERSION, "scientific_acceptance": False,
        "properties": properties, "priors": _priors(family),
        "conflicts": {"state_variability": _bounded_conflicts(state_conflicts),
                      "extraction_conflict": _bounded_conflicts(extraction_conflicts),
                      "scientific_dispute": {"status": "reported_unadjudicated" if dispute_evidence else "not_reported",
                          "count": len(dispute_evidence), "evidence": dispute_evidence[:MAX_EVIDENCE],
                          "evidence_truncated": len(dispute_evidence) > MAX_EVIDENCE,
                          "scientific_acceptance": False, "basis": "explicit_markers_only_not_numeric_tc_spread"}},
        "support": {"occurrence_count": len(values), "assessed_occurrence_count": structured,
                    "invalid_occurrence_count": invalid, "distinct_occurrence_count": len(occurrence_ids),
                    "source_backed_occurrence_count": backed, "bibliographic_identifier_count": len(identifiers),
                    "legacy_total_papers": legacy_count,
                    "legacy_total_papers_matches_identifier_count": legacy_count == len(identifiers) if legacy_count is not None else None,
                    "count_basis": "bibliographic_identifiers_in_assessed_raw_occurrences; legacy_total_papers_can_include_parent_rollups_or_other_catalogue_policy",
                    "independent_work_count": None, "independent_replication_count": None,
                    "basis": "retained_occurrences_and_identifiers_not_independent_replication",
                    "assessment_complete": not incomplete, "identity_adjudicated": False},
        "warnings": sorted(warnings),
    }
