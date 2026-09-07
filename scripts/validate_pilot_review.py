#!/usr/bin/env python3
"""Offline ML08 preparation/review accounting. No network, database or approval.

The bundled JSON Schema is the structural contract. This small standard-library
validator implements only its used keywords, then checks cross-record invariants.
Source permissions, human identity, independence and scientific truth are asserted
by the supplied records, not authenticated by this tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs/pilot/ML08_Pilot.schema.json"
MAX_BYTES = 8 * 1024 * 1024
MAX_REVIEWS = 2000
FIELDS = ("source_revision", "source_locator", "raw_context", "work_identity", "sample_state",
          "structure_identity", "tc_value", "tc_criterion", "pressure", "origin", "method")
WARNINGS = [
    "Preparation and accounting only; no scientific acceptance or publication is granted.",
    "Human identity, reviewer independence, actual event existence and source permissions are not authenticated.",
    "Hashes detect changes relative to a separately retained anchor; they are not signatures or proof of chronology.",
    "Sixty candidate events assess workflow feasibility, not cross-family ML sample-size sufficiency.",
    "Work/state/structure IDs are reported associations, not counts of independent experiments.",
    "No source text, local evidence files or canary bundle is opened or redistributed by this tool.",
]


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def selection_hash(selection: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in selection.items() if k != "selection_sha256"})).hexdigest()


def review_hash(reviews: list[dict]) -> str:
    """Canonical ordered JSON array, including superseded reviews; not JSONL bytes."""
    return hashlib.sha256(canonical(reviews)).hexdigest()


def _date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed


def _finite_number(value: object) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _schema_errors(value: object, rule: dict, schema: dict, path: str = "$", depth: int = 0) -> list[str]:
    if depth > 40:
        return [f"{path}: nesting_limit"]
    if "$ref" in rule:
        rule = schema["$defs"][rule["$ref"].removeprefix("#/$defs/")]
    if "anyOf" in rule:
        return [] if any(not _schema_errors(value, item, schema, path, depth + 1) for item in rule["anyOf"]) else [f"{path}: invalid_union"]
    errors = []
    types = {"null": value is None, "object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str), "boolean": isinstance(value, bool),
             "number": _finite_number(value),
             "integer": isinstance(value, int) and not isinstance(value, bool)}
    required_types = rule.get("type", [])
    if isinstance(required_types, str):
        required_types = [required_types]
    if required_types and not any(types[t] for t in required_types):
        return [f"{path}: invalid_type"]
    if "const" in rule and (value != rule["const"] or isinstance(value, bool) != isinstance(rule["const"], bool)):
        errors.append(f"{path}: invalid_constant")
    if "enum" in rule and value not in rule["enum"]:
        errors.append(f"{path}: invalid_enum")
    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0) or len(value) > rule.get("maxLength", MAX_BYTES) or ("minLength" in rule and not value.strip()):
            errors.append(f"{path}: invalid_text_length")
        if "pattern" in rule and not re.fullmatch(rule["pattern"], value):
            errors.append(f"{path}: invalid_pattern")
        if rule.get("format") == "date-time":
            try:
                _date(value)
            except ValueError:
                errors.append(f"{path}: timezone_aware_date_required")
    if types["number"] and value < rule.get("minimum", -math.inf):
        errors.append(f"{path}: below_minimum")
    if isinstance(value, list):
        if len(value) < rule.get("minItems", 0) or len(value) > rule.get("maxItems", MAX_REVIEWS):
            errors.append(f"{path}: invalid_item_count")
        if rule.get("uniqueItems") and len({canonical(item) for item in value}) != len(value):
            errors.append(f"{path}: duplicate_items")
        for index, item in enumerate(value):
            errors.extend(_schema_errors(item, rule.get("items", {}), schema, f"{path}[{index}]", depth + 1))
    if isinstance(value, dict):
        if set(rule.get("required", [])) - value.keys():
            errors.append(f"{path}: required_fields_missing")
        properties = rule.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors.extend(_schema_errors(item, properties[key], schema, f"{path}.{key}", depth + 1))
            elif rule.get("additionalProperties") is False:
                errors.append(f"{path}: unknown_field")  # Do not echo arbitrary private keys/values.
            elif isinstance(rule.get("additionalProperties"), dict):
                errors.extend(_schema_errors(item, rule["additionalProperties"], schema, f"{path}.*", depth + 1))
    return errors


def _quantity_valid(value: dict | None, unit: str) -> bool:
    if value is None or value["unit"] != unit:
        return False
    v, lower, upper = value["value"], value["lower"], value["upper"]
    if any(item is not None and item < 0 for item in (v, lower, upper)):
        return False
    relation = value["relation"]
    return ((relation == "exact" and v is not None and lower is None and upper is None)
            or (relation in {"lt", "le"} and v is None and lower is None and upper is not None)
            or (relation in {"gt", "ge"} and v is None and lower is not None and upper is None)
            or (relation == "interval" and v is None and lower is not None and upper is not None and lower <= upper))


def _result_errors(result: dict, path: str) -> list[str]:
    errors = []
    source, fields = result["source"], result["fields"]
    reported_values = {
        "source_revision": source["revision"], "source_locator": source["locator"],
        "raw_context": source["context_reference"] and source["context_sha256"],
        "work_identity": result["work_id"], "sample_state": result["state_id"] and result["state_interpretation"],
        "structure_identity": result["structure_id"], "tc_value": result["tc"],
        "tc_criterion": result["tc_criterion"], "pressure": result["pressure"],
        "origin": result["origin"] != "Unknown", "method": result["method"],
    }
    for field in FIELDS:
        if fields[field] == "reported" and not reported_values[field]:
            errors.append(f"{path}.{field}: reported_without_value")
        if fields[field] != "reported" and not result["missingness_reasons"].get(field, "").strip():
            errors.append(f"{path}.{field}: missingness_reason_required")
    if set(result["missingness_reasons"]) - set(FIELDS):
        errors.append(f"{path}: unknown_missingness_field")
    if result["tc"] is not None and not _quantity_valid(result["tc"], "K"):
        errors.append(f"{path}: invalid_tc_quantity")
    if result["pressure"] is not None and not _quantity_valid(result["pressure"], "GPa"):
        errors.append(f"{path}: invalid_pressure_quantity")
    if result["pressure_state"] in {"unknown", "not_reported", "ambiguous", "conflicted"} and result["pressure"] is not None:
        errors.append(f"{path}: unresolved_pressure_cannot_be_numeric")
    if result["pressure_state"] in {"reported", "explicit_ambient"} and result["pressure"] is None:
        errors.append(f"{path}: stated_pressure_requires_quantity")
    if result["observation"] == "not_detected" and (result["tc"] is not None or fields["tc_value"] != "not_applicable"):
        errors.append(f"{path}: negative_observation_is_not_zero_tc")
    if result["decision"] == "accepted":
        required = {"source_revision", "source_locator", "raw_context", "sample_state", "tc_criterion", "origin", "method"}
        if any(fields[key] != "reported" for key in required) or source["access_status"] != "permitted" or not source["permission_reference"] or not source["paper_id"]:
            errors.append(f"{path}: accepted_result_missing_source_state_or_method")
        if result["observation"] == "positive_tc" and (fields["tc_value"] != "reported" or result["tc"] is None):
            errors.append(f"{path}: accepted_positive_missing_tc")
        if result["observation"] == "positive_tc" and result["tc"] is not None and result["tc"]["relation"] == "exact" and result["tc"]["value"] == 0:
            errors.append(f"{path}: zero_is_not_positive_tc")
        if result["observation"] == "not_detected" and (result["tested_temperature_min_k"] is None or result["origin"] != "Observed"):
            errors.append(f"{path}: accepted_negative_requires_observed_test_window")
        if result["observation"] == "other":
            errors.append(f"{path}: other_observation_not_an_accepted_tc_label")
        if result["errors"]:
            errors.append(f"{path}: unresolved_errors_cannot_be_accepted")
    return errors


def validate(selection: dict, reviews: list[dict], conclusion: dict | None = None,
             expected_selection_sha256: str | None = None) -> dict:
    schema = json.loads(SCHEMA_PATH.read_text())
    errors = _schema_errors(selection, schema["$defs"]["selection"], schema, "selection")
    if len(reviews) > MAX_REVIEWS:
        errors.append("reviews: operational_record_limit")
    for index, review in enumerate(reviews[:MAX_REVIEWS]):
        errors.extend(_schema_errors(review, schema["$defs"]["review"], schema, f"reviews[{index}]"))
    if conclusion is not None:
        errors.extend(_schema_errors(conclusion, schema["$defs"]["conclusion"], schema, "conclusion"))
    report = {"schema_version": "ml08-accounting/1.0.0", "scientific_acceptance": False,
              "status": "invalid", "errors": errors, "warnings": WARNINGS,
              "ready_for_review": False, "ready_for_final_human_signoff": False}
    if errors:
        return report
    digest = selection_hash(selection)
    log_digest = review_hash(reviews)
    candidates = {item["candidate_id"]: item for item in selection["candidates"]}
    strata = {item["id"] for item in selection["strata"]}
    reviewers = {item["id"]: item for item in selection["reviewers"]}
    if len(candidates) != len(selection["candidates"]) or len(strata) != len(selection["strata"]) or len(reviewers) != len(selection["reviewers"]):
        errors.append("selection: duplicate_identity")
    if any(item["stratum_id"] not in strata for item in candidates.values()):
        errors.append("selection: undeclared_stratum")
    subset = set(selection["second_review_candidate_ids"])
    if not subset <= candidates.keys():
        errors.append("selection: second_review_outside_selection")
    frozen = selection["selection_status"] == "frozen"
    ready_gaps = []
    for condition, code in [
        (selection["protocol_status"] == "approved" and bool(selection["approval_reference"]) and bool(selection["protocol_sha256"]), "protocol_approval_and_digest_required"),
        (frozen, "selection_not_frozen"), (len(candidates) == 60, "exactly_60_actual_event_ids_required"),
        (bool(subset) and bool(selection["independence_plan"]), "independent_second_review_plan_required"),
        (len(reviewers) >= 2 and any("primary" in r["roles"] for r in reviewers.values()) and any("secondary" in r["roles"] for r in reviewers.values()), "human_reviewer_roster_required"),
        (selection["selection_sha256"] == digest, "selection_hash_not_frozen"),
        (expected_selection_sha256 == digest, "external_selection_anchor_required"),
        (bool(selection["selected_at"]) and bool(selection["frozen_at"]), "selection_dates_required"),
    ]:
        if not condition:
            ready_gaps.append(code)
    if selection["selected_at"] and selection["frozen_at"] and _date(selection["selected_at"]) > _date(selection["frozen_at"]):
        errors.append("selection: freeze_precedes_selection")
    if expected_selection_sha256 is not None and expected_selection_sha256 != digest:
        errors.append("selection: external_anchor_mismatch_no_silent_replacement")
    if frozen and selection["selection_sha256"] != digest:
        errors.append("selection: frozen_hash_mismatch")
    if reviews and ready_gaps:
        errors.append("reviews: reviews_require_predeclared_frozen_selection_and_external_anchor")
    latest, seen = {}, {}
    for index, review in enumerate(reviews):
        path = f"reviews[{index}]"
        cid, role, rid = review["candidate_id"], review["role"], review["review_id"]
        if cid not in candidates or rid in seen:
            errors.append(f"{path}: unknown_candidate_or_duplicate_review")
        if review["selection_sha256"] != digest:
            errors.append(f"{path}: selection_hash_mismatch")
        actor = reviewers.get(review["reviewer_id"])
        if actor is None or role not in actor["roles"]:
            errors.append(f"{path}: reviewer_role_not_predeclared")
        if selection["frozen_at"] and _date(review["completed_at"]) < _date(selection["frozen_at"]):
            errors.append(f"{path}: review_precedes_selection_freeze")
        previous = latest.get((cid, role))
        if review["supersedes_review_id"] != (previous["review_id"] if previous else None) or review["revision"] != (previous["revision"] + 1 if previous else 1):
            errors.append(f"{path}: invalid_append_only_revision")
        if previous and _date(review["completed_at"]) < _date(previous["completed_at"]):
            errors.append(f"{path}: revision_time_reversed")
        if any(ref not in seen or seen[ref]["candidate_id"] != cid for ref in review["compares_review_ids"]):
            errors.append(f"{path}: comparison_reference_invalid")
        if role == "primary" and (review["comparison"] != "not_compared" or review["compares_review_ids"]):
            errors.append(f"{path}: primary_cannot_claim_comparison")
        if role == "secondary":
            primary = latest.get((cid, "primary"))
            if not primary or primary["reviewer_id"] == review["reviewer_id"] or not review["independent_assessment"] or review["compares_review_ids"] != [primary["review_id"]] or review["comparison"] not in {"agreement", "disagreement"}:
                errors.append(f"{path}: independent_secondary_comparison_required")
        if role == "arbitration" and (review["comparison"] not in {"resolved", "unresolved"} or len(review["compares_review_ids"]) != 2):
            errors.append(f"{path}: arbitration_requires_two_reviews_and_outcome")
        if role == "arbitration":
            pair = [latest.get((cid, r)) for r in ("primary", "secondary")]
            if not all(pair) or set(review["compares_review_ids"]) != {item["review_id"] for item in pair if item}:
                errors.append(f"{path}: arbitration_must_compare_current_primary_and_secondary")
        if review["comparison"] in {"disagreement", "unresolved"} and not review["disagreement_codes"]:
            errors.append(f"{path}: disagreement_log_required")
        if set(review["active_minutes_by_field"]) - set(FIELDS):
            errors.append(f"{path}: unknown_timing_field")
        field_minutes = sum(value for value in review["active_minutes_by_field"].values() if value is not None)
        if review["active_minutes"] is not None and field_minutes > review["active_minutes"] + 1e-9:
            errors.append(f"{path}: field_minutes_exceed_disjoint_active_time")
        if review["outcome"] == "recovered" and not review["results"]:
            errors.append(f"{path}: recovery_without_atomic_results")
        if review["outcome"] in {"inaccessible", "irrecoverable", "no_relevant_result"} and review["results"]:
            errors.append(f"{path}: failed_event_cannot_contain_invented_results")
        if len({item["result_id"] for item in review["results"]}) != len(review["results"]):
            errors.append(f"{path}: duplicate_atomic_result")
        for result_index, result in enumerate(review["results"]):
            errors.extend(_result_errors(result, f"{path}.results[{result_index}]"))
        if role == "arbitration" and review["comparison"] == "unresolved" and any(item["decision"] == "accepted" for item in review["results"]):
            errors.append(f"{path}: unresolved_arbitration_cannot_accept_results")
        latest[cid, role] = review
        seen[rid] = review
    if errors:
        return report
    primary = {cid: review for (cid, role), review in latest.items() if role == "primary"}
    required_secondary = subset | {cid for cid, review in primary.items() if review["requires_second_review"] or review["outcome"] == "unresolved" or any(r["decision"] == "pending" or "conflicted" in r["fields"].values() or r["errors"] for r in review["results"])}
    final_gaps = list(ready_gaps)
    final_gaps.extend(f"{key}:{count}" for key, count in [("primary_reviews_missing", len(candidates) - len(primary)), ("secondary_reviews_missing", sum((cid, "secondary") not in latest for cid in required_secondary))] if count)
    for cid in candidates:
        first, second, arb = (latest.get((cid, role)) for role in ("primary", "secondary", "arbitration"))
        if second and first and second["compares_review_ids"] != [first["review_id"]]:
            final_gaps.append("secondary_comparison_stale")
        if second and first and second["comparison"] == "agreement":
            # Different reviewer prose is permitted; differing structured science
            # requires an explicit disagreement, not an inferred expert verdict.
            def comparable(review):
                return canonical({"outcome": review["outcome"], "results": sorted(
                    [{k: v for k, v in result.items() if k != "decision_reason"} for result in review["results"]],
                    key=lambda item: item["result_id"])})
            if comparable(first) != comparable(second):
                final_gaps.append("declared_agreement_has_structured_differences")
        if second and second["comparison"] == "disagreement":
            if not arb or set(arb["compares_review_ids"]) != {first["review_id"], second["review_id"]}:
                final_gaps.append("disagreement_arbitration_missing_or_stale")
    effective = {}
    for cid, first in primary.items():
        second, arb = latest.get((cid, "secondary")), latest.get((cid, "arbitration"))
        current_arb = arb and second and set(arb["compares_review_ids"]) == {first["review_id"], second["review_id"]}
        effective[cid] = arb if current_arb else first
    if conclusion is None or conclusion["status"] != "submitted_for_signoff":
        final_gaps.append("conclusion_not_submitted")
    else:
        if conclusion["selection_sha256"] != digest or conclusion["review_log_sha256"] != log_digest:
            final_gaps.append("conclusion_not_bound_to_current_selection_and_log")
        if conclusion["reviewer_id"] not in reviewers or not conclusion["completed_at"] or not conclusion["recommendation"] or not conclusion["rationale"] or not conclusion["canary_bundle_reference"] or not conclusion["canary_bundle_sha256"] or not conclusion["limitations"]:
            final_gaps.append("conclusion_signoff_metadata_incomplete")
        if {item["field"] for item in conclusion["field_actions"]} != set(FIELDS) or len(conclusion["field_actions"]) != len(FIELDS):
            final_gaps.append("field_keep_narrow_defer_recommendations_incomplete")
        if conclusion["completed_at"] and reviews and _date(conclusion["completed_at"]) < max(_date(r["completed_at"]) for r in reviews):
            final_gaps.append("conclusion_precedes_review_log")
    result_rows = [(cid, result) for cid, review in effective.items() for result in review["results"]]
    distinct_results = {}
    for _, result in result_rows:
        previous = distinct_results.get(result["result_id"])
        if previous and canonical({k: v for k, v in previous.items() if k != "decision_reason"}) != canonical({k: v for k, v in result.items() if k != "decision_reason"}):
            errors.append("effective_results: conflicting_content_for_same_result_id")
        distinct_results[result["result_id"]] = result
    if errors:
        return report
    field_counts = {field: dict(Counter(result["fields"][field] for result in distinct_results.values())) for field in FIELDS}
    candidate_coverage = {field: {"candidates_with_any_reported_result": len({cid for cid, result in result_rows if result["fields"][field] == "reported"}), "selected_candidate_denominator": len(candidates)} for field in FIELDS}
    time_by_group = {}
    for group_key in ("family", "source_class", "stratum_id"):
        groups = {}
        for candidate in candidates.values():
            label = candidate[group_key]
            group = groups.setdefault(label, {"selected_candidates": 0, "primary_reviewed_candidates": 0, "recorded_active_minutes_all_revisions": 0, "review_records": 0, "records_with_timing": 0, "event_outcomes": {}, "candidates_with_any_reported_field": dict.fromkeys(FIELDS, 0)})
            group["selected_candidates"] += 1
            group["primary_reviewed_candidates"] += candidate["candidate_id"] in primary
            current = effective.get(candidate["candidate_id"])
            if current:
                group["event_outcomes"][current["outcome"]] = group["event_outcomes"].get(current["outcome"], 0) + 1
                for field in FIELDS:
                    group["candidates_with_any_reported_field"][field] += any(item["fields"][field] == "reported" for item in current["results"])
        for review in reviews:
            group = groups[candidates[review["candidate_id"]][group_key]]
            group["review_records"] += 1
            if review["active_minutes"] is not None:
                group["recorded_active_minutes_all_revisions"] += review["active_minutes"]
                group["records_with_timing"] += 1
        time_by_group[group_key] = groups
    report.update({
        "status": "preparation_draft" if not frozen else "final_package_ready_for_human_signoff" if not final_gaps else "review_in_progress" if reviews else "selection_ready_not_reviewed" if not ready_gaps else "selection_not_ready",
        "selection_sha256": digest, "review_log_sha256": log_digest,
        "ready_for_review": not ready_gaps, "ready_for_final_human_signoff": not final_gaps,
        "preparation_gaps": ready_gaps, "final_gaps": sorted(set(final_gaps)),
        "counts": {"target_candidates": 60, "selected_candidates": len(candidates), "primary_reviewed_candidates": len(primary), "unreviewed_candidates": len(candidates) - len(primary), "review_records_including_superseded": len(reviews), "required_secondary_candidates": len(required_secondary), "event_result_associations": len(result_rows), "atomic_results_in_effective_reviews": len(distinct_results), "independent_work_count": None, "independent_replication_count": None},
        "event_outcomes": dict(Counter(r["outcome"] for r in effective.values())),
        "atomic_result_decisions": dict(Counter(r["decision"] for r in distinct_results.values())),
        "reported_identity_counts": {field: len({r[field] for _, r in result_rows if r[field] is not None}) for field in ("work_id", "sample_id", "state_id", "structure_id")},
        "atomic_field_missingness": {"denominator": len(distinct_results), "counts": field_counts},
        "candidate_field_recovery": candidate_coverage,
        "error_counts_separate_from_missingness": dict(Counter(error["kind"] for result in distinct_results.values() for error in result["errors"])),
        "curation_time": {"recorded_active_minutes_all_revisions": sum(r["active_minutes"] for r in reviews if r["active_minutes"] is not None), "records_with_timing": sum(r["active_minutes"] is not None for r in reviews), "review_record_denominator": len(reviews), "missing_time_is_not_zero": True},
        "curation_time_by_field": {field: {"recorded_minutes": sum(r["active_minutes_by_field"].get(field) or 0 for r in reviews), "records_with_timing": sum(r["active_minutes_by_field"].get(field) is not None for r in reviews), "review_record_denominator": len(reviews)} for field in FIELDS},
        "time_and_denominators_by_group": time_by_group,
        "agreement_counts": dict(Counter(r["comparison"] for (cid, role), r in latest.items() if role in {"secondary", "arbitration"})),
    })
    return report


def _pairs(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _loads(value: str) -> object:
    return json.loads(value, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))


def _read(path: Path) -> str:
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("input_exceeds_operational_size_limit")
    return data.decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", type=Path)
    parser.add_argument("reviews", type=Path, nargs="?")
    parser.add_argument("--conclusion", type=Path)
    parser.add_argument("--expected-selection-sha256")
    parser.add_argument("--print-selection-hash", action="store_true")
    parser.add_argument("--require", choices=["ready", "final"], help="Exit 2 when the requested documentary gate is incomplete")
    args = parser.parse_args()
    try:
        selection = _loads(_read(args.selection))
        if args.print_selection_hash:
            if not isinstance(selection, dict):
                raise ValueError("selection_object_required")
            print(selection_hash(selection))
            return 0
        review_text = _read(args.reviews) if args.reviews else ""
        reviews = [_loads(line) for line in review_text.splitlines() if line.strip()]
        conclusion = _loads(_read(args.conclusion)) if args.conclusion else None
        report = validate(selection, reviews, conclusion, args.expected_selection_sha256)
    except (ValueError, OSError, UnicodeError, RecursionError, OverflowError, TypeError):
        print(json.dumps({"status": "invalid", "scientific_acceptance": False, "errors": ["input_unreadable_or_invalid_json"]}))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    if report["errors"]:
        return 1
    if args.require and not report["ready_for_review" if args.require == "ready" else "ready_for_final_human_signoff"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
