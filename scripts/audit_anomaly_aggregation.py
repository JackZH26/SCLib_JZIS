"""Read-only SC03 comparison against a local, explicitly provided JSONL snapshot.

Requires the ingestion environment, but never initializes its database session.
Input rows: {id?, formula, records, legacy_summary?, overrides?}. ``records``
must be the current occurrences after existing non-numeric source/quality
filters. This tool neither revives historical deleted records nor approves data.
Overrides: [{field, value, is_cap: bool, reference_id?}]; free-text authority is
not consumed. Output goes to stdout; there is no --apply or database option.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_property_aggregation import _conditions, _scalar

from ingestion.anomaly_review import (
    ANOMALY_POLICY_VERSION,
    assess_record_anomalies,
    eligible_for_property,
)
from ingestion.extract.materials_aggregator import (
    _derive_summary,
    _material_id,
    _OverrideEntry,
    normalize_formula,
)
from ingestion.property_evidence import build_property_evidence, legacy_result_id

LEGACY_RULE_VERSION = "legacy-numeric-gates/2026-09-05-code-inventory"
REPORT_VERSION = "anomaly-aggregation-impact/1.0.0"
FIELDS = ("tc_max", "tc_max_experimental", "tc_max_theoretical", "tc_ambient",
          "hc2_tesla", "lambda_eph", "omega_log_k", "rho_s_mev", "t_cdw_k",
          "t_sdw_k", "t_afm_k", "rho_exponent", "doping_level", "lattice_params")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _overrides(raw):
    if not isinstance(raw, list):
        raise TypeError("overrides must be an array")
    result = []
    for row in raw:
        if not isinstance(row, Mapping) or row.get("field") not in FIELDS:
            raise ValueError("override must identify a supported numeric summary field")
        value = row.get("value")
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise TypeError("override value must be a finite numeric scalar")
        try:
            finite = math.isfinite(float(value))
        except (ValueError, OverflowError):
            finite = False
        if not finite or not isinstance(row.get("is_cap"), bool):
            raise ValueError("override must have a finite value and a boolean is_cap")
        reference_id = row.get("reference_id")
        if reference_id is not None and (not isinstance(reference_id, str) or not reference_id or len(reference_id) > 160):
            raise ValueError("override reference_id must be a short nonempty identifier")
        result.append(_OverrideEntry(row["field"], str(value), row["is_cap"],
                                     "local snapshot reference (not authorization)", None, reference_id))
    return result


def _legacy_numeric_dispositions(records, overrides):
    """Replay only the inventoried destructive numeric branches, not history.

    Legacy family/quality flags are not guessed. Actual previous displayed
    values and material visibility are compared only if supplied in the snapshot.
    """
    cap = next((entry.numeric_value for entry in overrides
                if entry.field == "tc_max" and entry.is_cap), None)
    driver_retained, derivation_retained = [], []
    for record in records:
        tc = record.get("tc_kelvin")
        numeric = isinstance(tc, (int, float))
        driver_ok = not (numeric and (tc < 0.01 or tc > 300))
        derive_ok = not (numeric and (tc > 250 or cap is not None and tc > cap * 1.5))
        driver_retained.append(driver_ok)
        derivation_retained.append(driver_ok and derive_ok)
    fallback = any(driver_retained) and not any(derivation_retained)
    result = []
    for record, driver_ok, derive_ok in zip(records, driver_retained, derivation_retained):
        tc = record.get("tc_kelvin")
        if not driver_ok:
            result.append({"status": "dropped_before_grouping", "reason": "legacy_tc_outside_0.01_to_300_K"})
        elif not derive_ok:
            result.append({"status": "retained_all_flagged_fallback" if fallback else "dropped_from_material_records",
                           "reason": "legacy_tc_above_250_K" if tc > 250 else "legacy_tc_above_1.5_times_cap"})
        else:
            result.append({"status": "retained_numeric_branch", "reason": None})
    return result


def audit_rows(rows, *, current_year, sample_limit=50):
    if isinstance(sample_limit, bool) or not isinstance(sample_limit, int) or not 0 <= sample_limit <= 1000:
        raise ValueError("sample_limit must be an integer from 0 to 1000")
    if isinstance(current_year, bool) or not isinstance(current_year, int) or not 1900 <= current_year <= 9999:
        raise ValueError("current_year must be an explicit integer chronology reference")
    counts, rule_counts = Counter(), Counter()
    samples = []
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("formula"), str) or not row["formula"]:
            raise ValueError("each row must contain a formula")
        records = row.get("records")
        if not isinstance(records, list) or not all(isinstance(record, Mapping) for record in records):
            raise ValueError("records must be an array of structured current occurrences")
        overrides = _overrides(row.get("overrides", []))
        summary = _derive_summary(row["formula"], records, overrides=overrides, current_year=current_year)
        scope_id = _material_id(normalize_formula(row["formula"]))
        context = summary["anomaly_context"]
        proposed = build_property_evidence(records, scope_id=scope_id, legacy_summary=summary,
                                           anomaly_context=context, property_fields=FIELDS,
                                           include_joint_epc=False)
        legacy = row.get("legacy_summary", {})
        if not isinstance(legacy, Mapping):
            raise TypeError("legacy_summary must be an object if supplied")
        old_dispositions = _legacy_numeric_dispositions(records, overrides)
        record_changes = []
        for record, old in zip(records, old_dispositions):
            assessment = assess_record_anomalies(record, scope_id=scope_id,
                family=context["family"], compound_thresholds=context["compound_thresholds"], current_year=current_year)
            counts["records_seen"] += 1
            counts["proposed_raw_records_retained"] += 1
            counts["legacy_" + old["status"]] += 1
            counts["proposed_" + assessment["status"]] += 1
            excluded = [field for field in FIELDS if not eligible_for_property(assessment, field)]
            rules = sorted({finding["rule_id"] for finding in assessment["findings"]})
            rule_counts.update(rules)
            old_excluded = old["status"].startswith("dropped_")
            if old_excluded or excluded or assessment["status"] != "no_findings":
                counts["records_with_disposition_difference_or_review"] += 1
                record_changes.append({"result_id": legacy_result_id(record, scope_id=scope_id),
                    "old_numeric_disposition": old, "proposed_status": assessment["status"],
                    "proposed_raw_preserved": True, "excluded_properties": excluded,
                    "rule_ids": rules, "scientific_acceptance": False})
        changes = []
        for field in FIELDS:
            if field not in legacy:
                counts["fields_not_comparable"] += 1
                continue
            counts["fields_compared"] += 1
            new_value, old_value = summary.get(field), legacy[field]
            selected = proposed["properties"][field]["selected"]
            previous_bundle = legacy.get("property_evidence")
            previous_properties = previous_bundle.get("properties") if isinstance(previous_bundle, Mapping) else None
            previous_property = previous_properties.get(field) if isinstance(previous_properties, Mapping) else None
            previous = previous_property.get("selected") if isinstance(previous_property, Mapping) else None
            previous = previous if isinstance(previous, Mapping) else {}
            old_id = previous.get("result_id")
            new_id = selected["result_id"] if selected else None
            value_changed = old_value != new_value
            provenance_status = ("changed" if old_id != new_id else "unchanged") if old_id else (
                "added" if new_id else "unavailable")
            old_conditions = _conditions(previous.get("conditions"))
            condition_field = {"tc_max": "tc_max_conditions", "hc2_tesla": "hc2_conditions"}.get(field)
            if condition_field in legacy:
                old_conditions = {**old_conditions,
                    "tc_conditions" if field == "tc_max" else "hc2_conditions": _scalar(legacy[condition_field])}
            new_conditions = _conditions(selected.get("conditions")) if selected else {}
            condition_key = "tc_conditions" if field == "tc_max" else "hc2_conditions"
            if condition_field:
                # Compare actual generated catalogue text, not a different raw
                # condition representation that happened to share its source.
                new_conditions[condition_key] = _scalar(summary.get(condition_field))
            condition_changes = sorted(key for key in old_conditions
                                       if old_conditions[key] != new_conditions.get(key))
            counts["value_changes"] += value_changed
            counts["provenance_" + provenance_status] += 1
            counts["condition_changes"] += bool(condition_changes)
            if value_changed or provenance_status in {"changed", "added"} or condition_changes:
                changes.append({"field": field, "old_value": _scalar(old_value),
                    "proposed_value": _scalar(new_value), "value_changed": value_changed,
                    "old_result_id": _scalar(old_id), "proposed_result_id": new_id,
                    "provenance_comparison": provenance_status,
                    "conditions_changed_fields": condition_changes,
                    "old_conditions": old_conditions, "proposed_conditions": new_conditions,
                    "proposed_evidence_status": proposed["properties"][field]["status"]})
        counts["materials_seen"] += 1
        if "needs_review" in legacy:
            counts["material_visibility_compared"] += 1
            counts["material_visibility_changes"] += legacy["needs_review"] != summary["needs_review"]
        if record_changes or changes:
            samples.append({"input_id": _scalar(row.get("id")), "proposed_scope_id": scope_id,
                "input_record_count": len(records), "proposed_record_count": len(summary["records"]),
                "old_needs_review": legacy.get("needs_review") if isinstance(legacy.get("needs_review"), bool) else None,
                "proposed_needs_review": summary["needs_review"], "record_changes": record_changes[:20],
                "record_changes_truncated": len(record_changes) > 20, "property_changes": changes})
            samples.sort(key=lambda sample: (sample["proposed_scope_id"], str(sample["input_id"])))
            if len(samples) > sample_limit:
                samples.pop()
    report = {"report_version": REPORT_VERSION, "old_rule_version": LEGACY_RULE_VERSION,
        "proposed_rule_version": ANOMALY_POLICY_VERSION,
        "current_year": current_year,
        "scope": "local_current_input_after_non_numeric_source_filters",
        "historical_values": "compared_only_when_supplied_in_legacy_summary",
        "legacy_replay": "numeric_driver_and_record_deletion_branches_only",
        "summary_semantics": "catalogue_summary_not_joint_observation",
        "joint_epc": "not_evaluated", "scientific_acceptance": False,
        "database_connections": 0, "database_rewrites": 0, "source_rewrites": 0,
        "counts": dict(sorted(counts.items())), "proposed_rule_counts": dict(sorted(rule_counts.items())),
        "sample_limit": sample_limit, "samples": samples,
        "limitations": ["No production census is implied by a local or synthetic snapshot.",
            "Previously deleted records require authorized original source snapshots; this tool cannot recover them.",
            "Non-numeric source/quality exclusions and historical curator decisions are not replayed or undone.",
            "Cross-view Tc summaries can differ because eligibility and support pools differ.",
            "No-findings is not approval, scientific acceptance, or ML admission."]}
    report["report_sha256"] = _digest(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--sample-limit", type=int, default=50)
    parser.add_argument("--current-year", type=int, required=True,
                        help="Explicit UTC chronology reference used for this reproducible run")
    args = parser.parse_args(argv)
    try:
        raw = args.input.read_bytes()
        rows = [json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
                for line in raw.decode("utf-8").splitlines() if line.strip()]
        report = audit_rows(rows, current_year=args.current_year, sample_limit=args.sample_limit)
    except (ValueError, OSError, TypeError):
        parser.exit(2, "Input must be valid local JSONL with formula, current records and structured optional references. No writes performed.\n")
    report["input_sha256"] = hashlib.sha256(raw).hexdigest()
    report.pop("report_sha256")
    report["report_sha256"] = _digest(report)
    print(json.dumps(report, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
