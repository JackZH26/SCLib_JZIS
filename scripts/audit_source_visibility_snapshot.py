"""Offline SC07 eligibility audit; never rewrites a frozen source-export bundle.

Version-1 source exports intentionally omit review flags. Supply a separately
authorized governance snapshot to evaluate current catalogue eligibility;
without one, the report explicitly marks eligibility as undetermined.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from services.material_anomalies import material_review, review_context  # noqa: E402
from services.material_visibility import (  # noqa: E402
    MATERIAL_VISIBILITY_VERSION,
    visibility_for_material,
)

AUDIT_VERSION = "source-visibility-audit/1.0.0"
_GOVERNANCE_KEYS = {"needs_review", "total_papers", "review_reason", "status", "disputed", "retracted",
                    "family", "parent_material_id", "anomaly_context"}
_REQUIRED_GOVERNANCE = {"needs_review", "total_papers", "review_reason", "status", "disputed", "retracted",
                        "family", "parent_material_id", "anomaly_context"}


def _indexed(rows: list[dict], name: str) -> dict[str, dict]:
    result = {}
    for row in rows:
        identifier = row.get("id") if isinstance(row, dict) else None
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise ValueError(f"{name} requires unique, nonempty string IDs")
        result[identifier] = row
    return result


def audit_snapshot(
    materials: list[dict], papers: list[dict], governance: list[dict] | None = None,
    *, evaluation_year: int,
) -> dict[str, Any]:
    """Evaluate full local input deterministically without database/network IO."""
    if isinstance(evaluation_year, bool) or not isinstance(evaluation_year, int) or not 1900 <= evaluation_year <= 9999:
        raise ValueError("evaluation_year must be an explicit integer in 1900..9999")
    indexed = _indexed(materials, "materials")
    paper_map = _indexed(papers, "papers")
    governance_map = _indexed(governance or [], "governance")
    merged = {mid: {**row, **{key: value for key, value in governance_map.get(mid, {}).items()
                             if key in _GOVERNANCE_KEYS}} for mid, row in indexed.items()}
    resolved = {}
    complete = {mid: mid in governance_map and _REQUIRED_GOVERNANCE <= governance_map[mid].keys()
                for mid in indexed}

    def resolve(mid, path=()):
        if mid in resolved:
            return resolved[mid]
        if mid not in merged or mid in path or len(path) >= 32 or not complete[mid]:
            return None
        material = merged[mid]
        records = material.get("records")
        source_statuses = {
            record["paper_id"]: paper_map.get(record["paper_id"], {}).get("status")
            for record in records if isinstance(record, dict) and isinstance(record.get("paper_id"), str)
        } if isinstance(records, list) else {}
        parent_id = material.get("parent_material_id")
        parent = resolve(parent_id, (*path, mid)) if parent_id else None
        context = {**review_context(material), "current_year": evaluation_year}
        anomaly = material_review(records, scope_id=mid, context=context, compact=True)
        visibility = visibility_for_material(material, anomaly_review=anomaly,
                                             source_statuses=source_statuses, parent_visibility=parent)
        resolved[mid] = visibility
        return visibility

    states: Counter[str] = Counter()
    changes: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    diagnostics = []
    for mid in sorted(indexed):
        material = merged[mid]
        visibility = resolve(mid)
        if visibility is None:
            states["undetermined_missing_governance"] += 1
            continue
        states[visibility["state"]] += 1
        total_papers = material.get("total_papers")
        has_papers = isinstance(total_papers, int) and not isinstance(total_papers, bool) and total_papers > 0
        legacy = (material.get("needs_review") is False
                  and has_papers
                  and material.get("review_reason") != "provenance_quarantine_nims")
        eligible = visibility["public_catalogue_eligible"] and has_papers
        changes[f"legacy_{str(legacy).lower()}_to_catalogue_{str(eligible).lower()}"] += 1
        reasons.update(visibility["reason_codes"])
        diagnostics.append({
            "material_id_sha256": hashlib.sha256(mid.encode()).hexdigest(),
            "state": visibility["state"], "public_catalogue_eligible": eligible,
            "archive_available": visibility["archive_available"],
            "reason_codes": visibility["reason_codes"],
            "review_revision": visibility["review_revision"],
        })
    return {
        "version": AUDIT_VERSION, "visibility_policy_version": MATERIAL_VISIBILITY_VERSION,
        "source_export_contract": "sclib-source-export/v1_unchanged",
        "input_materials": len(indexed), "evaluated_materials": len(diagnostics), "evaluation_year": evaluation_year,
        "state_counts": dict(sorted(states.items())), "legacy_scope_transitions": dict(sorted(changes.items())),
        "reason_counts": dict(sorted(reasons.items())), "material_diagnostics": diagnostics,
        "database_writes": 0, "scientific_acceptance": False, "ml_training_eligibility_established": False,
        "warnings": [
            "v1_public_scope_is_a_legacy_row_filter_not_current_catalogue_or_scientific_eligibility",
            "all_scope_is_a_private_source_archive_and_may_contain_quarantined_records",
            "checksums_establish_integrity_not_scientific_or_licensing_approval",
            "missing_governance_cannot_be_reconstructed_from_formula_or_exported_records",
            "source_status_unknown_is_not_active_publication_confirmation",
            "offline_snapshot_does_not_establish_current_production_state",
        ],
    }


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materials", type=Path, required=True)
    parser.add_argument("--papers", type=Path, required=True)
    parser.add_argument("--governance", type=Path)
    parser.add_argument("--evaluation-year", type=int, required=True)
    args = parser.parse_args()
    report = audit_snapshot(_load(args.materials), _load(args.papers), _load(args.governance) if args.governance else None,
                            evaluation_year=args.evaluation_year)
    report["input_sha256"] = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for name, path in (("materials", args.materials), ("papers", args.papers),
                                                 ("governance", args.governance)) if path is not None}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
