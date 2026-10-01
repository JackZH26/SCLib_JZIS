"""Primary source-statement metadata, scoped to unchanged eligible occurrences."""
from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from services.material_classification_candidates import (
    EXTRACTOR_VERSION,
    validate_candidate_identity,
)
from services.material_enrichment import AUTHORITY, digest
from services.property_evidence import legacy_result_id

SEED_PATH = Path(__file__).parent / "resources" / "material_classification_seed.json"
VERSION = "material-classification-seed/1.0.0"
_PRIVATE_KEYS = {"evidence_text", "text", "sentence", "source_excerpt", "raw_record", "records", "abstract",
                 "raw_chunk", "rawchunk", "source_fulltext", "private_notes", "reviewer_email"}


def _metadata_only(value):
    if type(value) is dict:
        return not (_PRIVATE_KEYS & value.keys()) and all(_metadata_only(item) for item in value.values())
    if type(value) is list:
        return all(_metadata_only(item) for item in value)
    return True


@lru_cache(maxsize=1)
def load_seed():
    try:
        if SEED_PATH.stat().st_size > 1_000_000:
            return None
        seed = json.loads(SEED_PATH.read_bytes())
        if (type(seed) is not dict or seed.get("version") != VERSION
                or seed.get("classification_extractor_version") != EXTRACTOR_VERSION
                or seed.get("source_text_included") is not False
                or any(seed.get(key) is not False for key in AUTHORITY)
                or type(seed.get("seed_id")) is not str or not 0 < len(seed["seed_id"]) <= 100
                or type(seed.get("candidates")) is not list or len(seed["candidates"]) > 100
                or not _metadata_only(seed)
                or seed.get("seed_sha256") != digest({key: value for key, value in seed.items() if key != "seed_sha256"})):
            return None
        identifiers = set()
        for candidate in seed["candidates"]:
            validate_candidate_identity(candidate)
            refs = candidate.get("retained_result_refs")
            if (type(refs) is not list or not refs or len(refs) > 32
                    or candidate.get("retained_reference_count") != len(refs)
                    or candidate["candidate_id"] in identifiers):
                return None
            identifiers.add(candidate["candidate_id"])
        return seed
    except (OSError, ValueError, KeyError, TypeError):
        return None


def merge_primary_classification_seed(report, material):
    """Never reuse a source statement after any retained reference changes.

    Lifecycle/visibility partitioning precedes this call. The router checks the
    same source/catalogue epochs again before returning the merged response.
    A statement remains pending even with an unchanged source fingerprint.
    """
    seed = load_seed()
    if seed is None:
        report["classification_primary_source_seed"] = {"status": "unavailable", "candidate_facts_added": 0}
        return _seal(report)
    applicable = [candidate for candidate in seed["candidates"]
                  if candidate["material_id"] == material.id and candidate["subject"]["formula"] == material.formula]
    current = {(record.get("paper_id"), legacy_result_id(record, scope_id=material.id), digest(record))
               for record in (material.current_records() if applicable else []) if type(record) is dict}
    existing = report.get("classification_candidates", [])
    identifiers = {candidate["candidate_id"] for candidate in existing}
    added = []
    for candidate in applicable:
        paper_id = candidate["source"]["paper_id"]
        refs = candidate["retained_result_refs"]
        if (any((paper_id, ref["result_id"], ref["record_sha256"]) not in current for ref in refs)
                or candidate["candidate_id"] in identifiers):
            continue
        added.append(candidate)
        identifiers.add(candidate["candidate_id"])
    added = json.loads(json.dumps(added))
    field_counts = Counter(candidate["field"] for candidate in added)
    captures = {(candidate["source"]["paper_id"], candidate["source"]["capture_id"]) for candidate in added}
    report["classification_primary_source_seed"] = {
        "status": "available", "version": VERSION, "seed_id": seed["seed_id"], "seed_sha256": seed["seed_sha256"],
        "candidate_facts_added": len(added), "primary_source_captures": len(captures),
    }
    for row in report.get("coverage", []):
        if row["material_id"] != material.id:
            continue
        for field in row["fields"]:
            field["candidate_count"] += field_counts[field["field"]]
            if not field["retained_present"] and field["candidate_count"]:
                field["status"] = "pending_review"
                field["reason_codes"] = ["source_candidates_available"]
        row["classification_primary_source_capture_count"] = len(captures)
    counts = report.setdefault("classification_counts", {})
    counts["candidate_facts"] = counts.get("candidate_facts", len(existing)) + len(added)
    counts["primary_source_candidate_facts_added"] = len(added)
    counts["primary_source_captures"] = len(captures)
    counts["primary_source_retained_references_added"] = sum(candidate["retained_reference_count"] for candidate in added)
    for field, value in field_counts.items():
        candidate_fields = counts.setdefault("candidate_fields", {})
        candidate_fields[field] = candidate_fields.get(field, 0) + value
    combined = sorted([*existing, *added], key=lambda candidate: candidate["candidate_id"])
    report["classification_candidates_truncated"] = report.get("classification_candidates_truncated", False) or len(combined) > 100
    report["classification_candidates"] = combined[:100]
    counts["candidate_facts_returned"] = len(report["classification_candidates"])
    counts["candidate_facts_omitted"] = counts.get("candidate_facts_omitted", 0) + max(0, len(combined) - 100)
    return _seal(report)


def _seal(report):
    report.pop("report_sha256", None)
    report["report_sha256"] = digest(report)
    return report
