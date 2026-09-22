"""Read-only anomaly context and bounded retained-record archive adapters."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any

from services.anomaly_review import (
    ANOMALY_POLICY_VERSION,
    assess_record_anomalies,
    build_anomaly_review,
)
from services.scientific_values import FIELD_UNITS

_RAW_FIELDS = set(FIELD_UNITS) | {
    "tc", "tc_unit", "pressure", "pressure_unit", "measurement_year",
    "formula", "formula_raw", "family", "material_family", "paper_id", "doi", "arxiv_id", "year",
    "state_id", "sample_id", "structure_id", "run_id", "method", "measurement", "measurement_method",
    "calculation_method", "protocol_id", "calculation_protocol", "knowledge_origin", "result_origin",
    "source_role", "evidence_type", "tc_type", "tc_criterion", "tc_conditions", "hc2_conditions",
    "hc2_direction", "field_orientation", "sample_form", "substrate", "doping_type", "pressure_state",
    "crystal_structure", "space_group", "structure_phase", "pairing_symmetry", "gap_structure",
    "result_status", "outcome", "outcome_state", "no_transition", "superconductivity_observed",
}
_RAW_FIELDS |= {field + "_unit" for field in FIELD_UNITS}


def _get(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def review_context(value: Any) -> dict[str, Any]:
    context = _get(value, "anomaly_context")
    context = context if isinstance(context, dict) else {}
    references = context.get("compound_thresholds", [])
    if not isinstance(references, (list, tuple)) or len(references) > 200:
        references = [None]  # A malformed review input fails closed, never disappears.
    return {
        "policy_version": ANOMALY_POLICY_VERSION,
        "current_year": datetime.now(UTC).year,
        "selection_policy": context.get("selection_policy"),
        "family": _get(value, "family") or context.get("family"),
        "compound_thresholds": references,
    }


def record_assessment(record, *, scope_id, context):
    return assess_record_anomalies(
        record, scope_id=scope_id, family=context.get("family"),
        compound_thresholds=context.get("compound_thresholds", ()), current_year=context.get("current_year", datetime.now(UTC).year),
    )


def material_review(records, *, scope_id, context, compact=False):
    return build_anomaly_review(
        records, scope_id=scope_id, family=context.get("family"),
        compound_thresholds=context.get("compound_thresholds", ()), current_year=context.get("current_year", datetime.now(UTC).year),
        record_limit=0 if compact else 100,
    )


def _raw_value(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            if math.isfinite(value):
                return value
        except OverflowError:
            pass
    if isinstance(value, str) and len(value) <= 500:
        return value
    if isinstance(value, (list, tuple)) and len(value) <= 2:
        return [_raw_value(item) for item in value]
    return {"redacted": "structured_or_oversize_raw", "sha256": hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()}


def _archive_record(record):
    if not isinstance(record, dict):
        return {"unstructured_record": _raw_value(record)}
    raw = {field: _raw_value(record[field]) for field in sorted(_RAW_FIELDS) if field in record}
    proposals = record.get("scientific_values")
    if isinstance(proposals, dict):
        raw["scientific_values"] = {
            field: {key: _raw_value(proposal[key]) for key in ("raw_value", "raw_unit", "input_unit") if key in proposal}
            if isinstance(proposal, dict) else _raw_value(proposal)
            for field, proposal in proposals.items() if field in FIELD_UNITS
        }
    if isinstance(record.get("lattice_params"), dict):
        raw["lattice_params"] = {key: _raw_value(item) for key, item in record["lattice_params"].items()
                                  if key in {"a", "b", "c", "alpha", "beta", "gamma", "unit"}}
    return raw


def retained_record_archive(records, *, scope_id, context):
    source = records if isinstance(records, list) else []
    rows = []
    for index, record in enumerate(source[:100]):
        assessment = record_assessment(record, scope_id=scope_id, context=context)
        rows.append({"result_id": assessment["result_id"], "record_index": index,
                     "raw": _archive_record(record), "assessment": assessment})
    return {
        "version": ANOMALY_POLICY_VERSION, "scope": "material_retained_records",
        "raw_field_policy": "scientific_allowlist_not_full_source", "records": rows,
        "total": len(source), "returned": len(rows), "truncated": len(source) > len(rows),
    }
