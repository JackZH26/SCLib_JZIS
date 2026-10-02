"""Merge packaged primary-source candidates only onto unchanged eligible records."""
from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from services.material_enrichment import (
    AUTHORITY,
    bounded_source_rows,
    digest,
    validate_candidate_identity,
)
from services.property_evidence import legacy_result_id

SEED_PATH = Path(__file__).parent / "resources" / "material_enrichment_seed.json"
_PRIVATE_KEYS = {"evidence_text", "text", "sentence", "source_excerpt", "raw_record", "records", "abstract"}


def _metadata_only(value):
    if isinstance(value, dict):
        return not (_PRIVATE_KEYS & value.keys()) and all(_metadata_only(v) for v in value.values())
    if isinstance(value, list):
        return all(_metadata_only(v) for v in value)
    return True


@lru_cache(maxsize=1)
def load_seed():
    # Bounded, installed package resource. No provider text or local pilot
    # exports are served by this interface.
    try:
        if SEED_PATH.stat().st_size > 1_000_000:
            return None
        seed = json.loads(SEED_PATH.read_text())
        if (seed.get("version") != "materials-enrichment-seed/1.0.0"
                or seed.get("source_text_included") is not False
                or any(seed.get(key) is not False for key in AUTHORITY)
                or not _metadata_only(seed)
                or seed.get("seed_sha256") != digest({k: v for k, v in seed.items() if k != "seed_sha256"})):
            return None
        for report in seed["reports"]:
            for candidate in report["candidates"]:
                validate_candidate_identity(candidate)
        return seed
    except (OSError, ValueError, KeyError, TypeError):
        return None


def merge_primary_seed(report, material):
    """Require the exact current source and every retained reference fingerprint.

    A formula/material ID match alone never permits reuse after correction,
    source withdrawal or record replacement. Conservative all-reference
    matching also prevents a candidate retaining stale occurrence metadata.
    """
    seed = load_seed()
    if seed is None:
        report["primary_source_seed"] = {"status": "unavailable", "candidate_facts_added": 0}
        return _reseal(report)
    applicable = [candidate for source_report in seed["reports"] for candidate in source_report["candidates"]
                  if candidate["material_id"] == material.id and candidate["subject"].get("formula") == material.formula]
    # Most catalogue rows have no packaged capture. Do not hash their full
    # record inventory just to establish that there is no seed for their ID.
    records = material.current_records() if applicable else []
    current = {(record.get("paper_id"), legacy_result_id(record, scope_id=material.id), digest(record))
               for record in records if isinstance(record, dict)}
    existing = {candidate["candidate_id"] for candidate in report["candidates"]}
    added = []
    for candidate in applicable:
        source = candidate["source"]
        refs = candidate.get("retained_result_refs", [])
        if (not refs
                or any((source["paper_id"], ref["result_id"], ref["record_sha256"]) not in current for ref in refs)
                or candidate["candidate_id"] in existing):
            continue
        added.append(candidate)
        existing.add(candidate["candidate_id"])
    # Clone before merging so caller mutation cannot alter the cached seed.
    added = json.loads(json.dumps(added))
    fields = Counter(candidate["field"] for candidate in added)
    captures = {(c["source"]["paper_id"], c["source"]["capture_id"]) for c in added}
    report["primary_source_seed"] = {
        "status": "available", "version": seed["version"], "seed_id": seed["seed_id"],
        "seed_sha256": seed["seed_sha256"], "candidate_facts_added": len(added),
        "primary_source_captures": len(captures),
    }
    for coverage in report["coverage"]:
        for field in coverage["fields"]:
            field["candidate_count"] += fields[field["field"]]
            if not field["retained_present"] and field["candidate_count"]:
                field["status"] = "pending_review"
                field["reason_codes"] = ["source_candidates_available"]
        coverage["primary_source_capture_count"] = len(captures)
    counts = report["counts"]
    counts["candidate_facts"] += len(added)
    counts["candidate_retained_references"] += sum(c["retained_reference_count"] for c in added)
    counts["primary_source_captures"] = len(captures)
    for field, count in fields.items():
        counts["candidate_fields"][field] = counts["candidate_fields"].get(field, 0) + count
    candidates = sorted([*report["candidates"], *added], key=lambda c: c["candidate_id"])
    report["candidates_truncated"] = report.get("candidates_truncated", False) or len(candidates) > 100
    report["candidates"] = bounded_source_rows(candidates)
    counts["candidate_facts_returned"] = len(report["candidates"])
    counts["candidate_facts_omitted"] = counts["candidate_facts"] - len(report["candidates"])
    return _reseal(report)


def _reseal(report):
    report.pop("report_sha256", None)
    report["report_sha256"] = digest(report)
    return report
