"""Audit source-supported property views from a local material JSONL snapshot.

No database, API, model, backfill or input rewrite. Legacy displayed values are
anchors, not permission to revive filtered or capped results. Missing summary
fields are reported as not comparable, never as evidence of zero impact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))

from ingestion.property_evidence import build_property_evidence

_LATTICE_COMPONENTS = ("a", "b", "c", "alpha", "beta", "gamma")
_CONDITION_TEXT = (
    "hc2_conditions", "tc_conditions", "tc_type", "tc_criterion", "hc2_direction",
    "field_orientation", "magnetic_field_orientation", "method", "measurement", "measurement_method",
    "calculation_method", "protocol_id", "calculation_protocol",
)
_TEMPERATURE_FIELDS = ("temperature_k", "measurement_temperature_k", "hc2_temperature_k")
_QUANTITY_KEYS = (
    "status", "relation", "value_kind", "value", "lower", "upper", "unit", "uncertainty",
    "uncertainty_interpretation", "approximate", "raw_value", "raw_unit", "unit_basis", "parser_version",
)
_PRESSURE_KEYS = (
    "pressure_state", "relation", "pressure_gpa", "value_lower_gpa", "value_upper_gpa",
    "uncertainty_gpa", "approximate", "raw_value", "raw_unit", "version", "reason",
    "classifier_version", "reasons", "unit_basis", "uncertainty_interpretation",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _redacted(value):
    raw = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()
    return {"redacted": "unsupported_or_oversize_value", "sha256": hashlib.sha256(raw).hexdigest()}


def _scalar(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            if math.isfinite(value):
                return value
        except (OverflowError, ValueError):
            pass
    if isinstance(value, str) and len(value) <= 240:
        return value
    return _redacted(value)


def _quantity(value):
    if value is None:
        return None
    if not isinstance(value, Mapping):
        return _redacted(value)
    return {key: _scalar(value[key]) for key in _QUANTITY_KEYS if key in value}


def _lattice(value):
    if value is None:
        return None
    if not isinstance(value, Mapping):
        return _redacted(value)
    result = {key: _scalar(value[key]) for key in _LATTICE_COMPONENTS if key in value}
    extra = {key: item for key, item in value.items() if key not in _LATTICE_COMPONENTS}
    if extra:
        result["unsupported_fields"] = _redacted(extra)
    return result


def _conditions(value):
    source = _mapping(value)
    result = {key: _scalar(source[key]) for key in _CONDITION_TEXT if key in source}
    result.update({key: _quantity(source[key]) for key in _TEMPERATURE_FIELDS if key in source})
    return result


def _state(value):
    source = _mapping(value)
    result = {key: _scalar(source[key]) for key in (
        "state_id", "structure_id", "sample_id", "run_id", "sample_form", "substrate", "doping_type",
        "formula", "formula_raw",
    ) if key in source}
    if "doping_level" in source:
        result["doping_level"] = _quantity(source["doping_level"])
    if "pressure_semantics" in source:
        pressure = _mapping(source["pressure_semantics"])
        result["pressure_semantics"] = {key: _scalar(pressure[key]) for key in _PRESSURE_KEYS if key in pressure}
    return result


def _structure(value):
    source = _mapping(value)
    result = {key: _scalar(source[key]) for key in (
        "crystal_structure", "space_group", "structure_phase",
    ) if key in source}
    if "lattice_params" in source:
        result["lattice_params"] = _lattice(source["lattice_params"])
    quantities = _mapping(source.get("lattice_quantities"))
    if quantities:
        result["lattice_quantities"] = {
            key: _quantity(quantities[key]) for key in _LATTICE_COMPONENTS if key in quantities}
    return result


def _changes(before, after):
    changed = sorted(key for key, value in before.items() if value != after.get(key))
    added = sorted(key for key, value in after.items() if key not in before and value not in (None, {}, []))
    return changed, added


def _report_hash(report: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        {key: value for key, value in report.items() if key != "report_sha256"},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def _property_change(material, field, entry, previous):
    selected = _mapping(entry.get("selected"))
    prior = _mapping(_mapping(previous.get(field)).get("selected"))
    old_id, new_id = (value if isinstance(value, str) and 0 < len(value) <= 240 else None
                      for value in (prior.get("result_id"), selected.get("result_id")))
    provenance = ("unchanged" if old_id == new_id and old_id else
                  "changed" if old_id and new_id else
                  "added" if new_id else "removed" if old_id else "unavailable")
    old_conditions = _conditions(prior.get("conditions"))
    if field == "hc2_tesla" and "hc2_conditions" in material:
        old_conditions.setdefault("hc2_conditions", _scalar(material["hc2_conditions"]))
    if field == "tc_max" and "tc_max_conditions" in material:
        old_conditions.setdefault("tc_conditions", _scalar(material["tc_max_conditions"]))
    conditions = _conditions(selected.get("conditions"))
    changed_conditions, added_conditions = _changes(old_conditions, conditions)
    old_state, proposed_state = _state(prior.get("state")), _state(selected.get("state"))
    changed_state, added_state = _changes(old_state, proposed_state)
    old_structure, proposed_structure = _structure(prior.get("structure")), _structure(selected.get("structure"))
    changed_structure, added_structure = _changes(old_structure, proposed_structure)
    comparable = field in material
    value_change = material.get(field) != selected.get("value") if comparable else None
    sanitize_value = _lattice if field == "lattice_params" else _scalar
    return {
        "property": field,
        "status": entry.get("status"),
        "comparison_status": "compared" if comparable else "legacy_summary_field_missing",
        "legacy_catalogue_value": sanitize_value(material.get(field)),
        "proposed_source_supported_value": sanitize_value(selected.get("value")),
        "supported_value_changes": value_change,
        "old_result_id": old_id,
        "proposed_result_id": new_id,
        "provenance_change": provenance,
        "old_conditions": old_conditions,
        "proposed_conditions": conditions,
        "conditions_changed_fields": changed_conditions,
        "conditions_added_fields": added_conditions,
        "old_state": old_state,
        "proposed_state": proposed_state,
        "state_changed_fields": changed_state,
        "state_added_fields": added_state,
        "old_structure": old_structure,
        "proposed_structure": proposed_structure,
        "structure_changed_fields": changed_structure,
        "structure_added_fields": added_structure,
        "selected_source": selected.get("source"),
        "warnings": list(entry.get("warnings") or []),
    }


def build_impact_report(materials: Iterable[Mapping[str, Any]], *, sample_limit: int = 100) -> dict[str, Any]:
    """Separate view-value, source and condition impact without mutating rows."""
    if isinstance(sample_limit, bool) or not isinstance(sample_limit, int) or not 0 <= sample_limit <= 10000:
        raise ValueError("sample_limit must be an integer between 0 and 10000")
    seen = set()
    totals: Counter = Counter({key: 0 for key in (
        "materials_evaluated", "properties_evaluated", "supported_value_changes",
        "not_comparable_properties", "provenance_unchanged", "provenance_changed",
        "provenance_added", "provenance_removed", "provenance_unavailable",
        "conditions_changed", "conditions_added", "untraceable_properties",
        "state_changed", "state_added", "structure_changed", "structure_added",
    )})
    samples = []
    versions = set()
    for material in materials:
        if not isinstance(material, Mapping):
            raise TypeError("Each material JSONL row must be an object")
        identifier = material.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("Each material must have a nonempty string id")
        if identifier in seen:
            raise ValueError("Material ids must be unique within one audit snapshot")
        seen.add(identifier)
        records = material.get("records")
        if not isinstance(records, list) or not all(isinstance(row, Mapping) for row in records):
            raise TypeError("material.records must be a list of objects")
        bundle = build_property_evidence(records, scope_id=identifier, legacy_summary=material)
        versions.add(str(bundle.get("version")))
        previous = _mapping(_mapping(material.get("property_evidence")).get("properties"))
        changes = []
        for field, entry in sorted(bundle["properties"].items()):
            change = _property_change(material, field, entry, previous)
            totals["properties_evaluated"] += 1
            totals["supported_value_changes"] += change["supported_value_changes"] is True
            totals["not_comparable_properties"] += change["supported_value_changes"] is None
            totals["provenance_" + change["provenance_change"]] += 1
            totals["conditions_changed"] += bool(change["conditions_changed_fields"])
            totals["conditions_added"] += bool(change["conditions_added_fields"])
            totals["state_changed"] += bool(change["state_changed_fields"])
            totals["state_added"] += bool(change["state_added_fields"])
            totals["structure_changed"] += bool(change["structure_changed_fields"])
            totals["structure_added"] += bool(change["structure_added_fields"])
            totals["untraceable_properties"] += change["status"] == "untraceable"
            # Omit entirely empty property rows from the sampled detail only;
            # counters above still account for every contract property.
            if (field in material or entry.get("evidence") or entry.get("selected")
                    or field in previous):
                changes.append(change)
        totals["materials_evaluated"] += 1
        if changes and sample_limit:
            samples.append({"material_id": identifier, "properties": changes,
                            "joint_epc": bundle.get("joint_epc")})
            samples.sort(key=lambda row: row["material_id"])
            del samples[sample_limit:]
    report = {
        "schema": "sclib-property-aggregation-impact/v1",
        "mode": "offline_read_only_view_audit",
        "scientific_semantics": "catalogue_summary_not_joint_observation",
        "property_evidence_versions": sorted(versions),
        "totals": dict(sorted(totals.items())),
        "stored_values_rewritten": 0,
        "scientific_acceptance_implied": False,
        "sample_limit": sample_limit,
        "samples": samples,
        "limitations": [
            "The proposed value is the source-supported view, not a proposed database rewrite.",
            "A capped/overridden value without exact support is withheld; a higher raw value is not revived.",
            "Absent prior result ids are provenance additions, not proof of previously wrong provenance.",
            "Absent legacy summary fields cannot be compared; a records-only source export is not a zero-impact baseline.",
            "Input records must already reflect the intended visibility/review scope; this tool cannot reconstruct missing override or exclusion history.",
            "Matching a source value does not validate the measurement or authorize a joint ML feature row.",
        ],
    }
    report["report_sha256"] = _report_hash(report)
    return report


def _reject_nonfinite(_value):
    raise ValueError("JSONL must not contain non-finite numeric literals")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("materials_jsonl", type=Path)
    parser.add_argument("--sample-limit", type=int, default=100)
    args = parser.parse_args()
    digest = hashlib.sha256()

    def rows(source):
        for number, line in enumerate(source, 1):
            digest.update(line)
            if not line.strip():
                continue
            try:
                yield json.loads(line, parse_constant=_reject_nonfinite)
            except (ValueError, UnicodeError) as exc:
                raise ValueError(f"Invalid material JSONL at line {number}") from exc

    try:
        with args.materials_jsonl.open("rb") as source:
            report = build_impact_report(rows(source), sample_limit=args.sample_limit)
        report["input_sha256"] = digest.hexdigest()
        report["report_sha256"] = _report_hash(report)
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
