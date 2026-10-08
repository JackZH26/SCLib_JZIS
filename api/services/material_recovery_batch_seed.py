"""Append source-inspection metadata onto unchanged current Materials records.

This independent batch leaves the earlier primary/classification seeds intact.
AI source inspection is not human approval, canonical correction or ML consent.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from services.material_enrichment import (
    AUTHORITY,
    bounded_source_rows,
    digest,
    validate_candidate_identity,
)
from services.material_enrichment_seed import _metadata_only
from services.property_evidence import legacy_result_id

VERSION = "materials-recovery-batch-seed/1.0.0"
SEED_PATH = Path(__file__).parent / "resources" / "material_recovery_batch_20261008_seed.json"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_URL = re.compile(r"https://arxiv\.org/pdf/\d{4}\.\d{4,5}v\d+\Z")


@lru_cache(maxsize=1)
def load_batch():
    try:
        if SEED_PATH.stat().st_size > 1_000_000:
            return None
        batch = json.loads(SEED_PATH.read_bytes())
        if (batch.get("version") != VERSION or batch.get("source_text_included") is not False
                or batch.get("human_reviewed") is not False
                or any(batch.get(k) is not False for k in AUTHORITY)
                or not _metadata_only(batch)
                or batch.get("seed_sha256") != digest({k: v for k, v in batch.items() if k != "seed_sha256"})
                or not isinstance(batch.get("rows"), list) or not 1 <= len(batch["rows"]) <= 20):
            return None
        ids = set()
        for row in batch["rows"]:
            if (row["material_id"] in ids or row["status"] != "checked"
                    or row.get("source_available") is not True
                    or any(row.get(k) is not False for k in ("scientific_acceptance", "human_reviewed", "database_changed"))
                    or not 1 <= len(row["observations"]) <= 12
                    or not 1 <= len(row["retained_result_refs"]) <= 32
                    or not isinstance(row["summary"], str) or not 1 <= len(row["summary"]) <= 1000
                    or not isinstance(row["unknowns"], list) or len(row["unknowns"]) > 12
                    or any(not isinstance(x, str) or not 1 <= len(x) <= 1000 for x in row["unknowns"])):
                return None
            ids.add(row["material_id"])
            refs = row["retained_result_refs"]
            if any(not _SHA.fullmatch(ref["record_sha256"]) or not ref["paper_id"] or not ref["result_id"] for ref in refs):
                return None
            observation_ids = set()
            for observation in row["observations"]:
                source = observation["source"]
                if (observation["source_content_inspected"] is not True
                        or observation["inspection_actor"] != "AI-assisted source check"
                        or observation["knowledge_origin"] not in ("Observed", "Computed")
                        or observation["sample_association_status"] != "pending"
                        or observation["id"] in observation_ids
                        or source["paper_id"] not in {ref["paper_id"] for ref in refs}
                        or source["source_status"] != "unknown"
                        or not _URL.fullmatch(source["source_url"])
                        or not all(_SHA.fullmatch(source[k]) for k in ("capture_sha256", "content_sha256"))
                        or not _SHA.fullmatch(source["span"]["text_sha256"])
                        or type(source["locator"]["page"]) is not int or source["locator"]["page"] < 1
                        or type(source["span"]["char_start"]) is not int
                        or type(source["span"]["char_end"]) is not int
                        or not 0 <= source["span"]["char_start"] < source["span"]["char_end"]):
                    return None
                observation_ids.add(observation["id"])
        for report in batch["reports"]:
            for candidate in report["candidates"]:
                validate_candidate_identity(candidate)
                if candidate["material_id"] not in ids:
                    return None
        if batch["counts"] != {
            "checked_materials": len(batch["rows"]),
            "available_materials": len(batch["rows"]),
            "source_observations": sum(len(r["observations"]) for r in batch["rows"]),
            "pending_candidate_facts": sum(len(r["candidates"]) for r in batch["reports"]),
            "canonical_facts_changed": 0, "approved_facts": 0,
        }:
            return None
        return batch
    except (OSError, ValueError, KeyError, TypeError):
        return None


def merge_recovery_batch(report, material):
    batch = load_batch()
    row = next((r for r in batch["rows"] if r["material_id"] == material.id
                and r["formula"] == material.formula), None) if batch else None
    if row is None:
        return report
    current = {(r.get("paper_id"), legacy_result_id(r, scope_id=material.id), digest(r))
               for r in material.current_records() if isinstance(r, dict)}
    if any((ref["paper_id"], ref["result_id"], ref["record_sha256"]) not in current
           for ref in row["retained_result_refs"]):
        # A changed/excluded record invalidates its entire captured observation
        # window. This is a stale-source guard, not scientific rejection.
        return report
    existing = {c["candidate_id"] for c in report["candidates"]}
    applicable = [c for r in batch["reports"] for c in r["candidates"]
                  if c["material_id"] == material.id and c["subject"]["formula"] == material.formula
                  and c["candidate_id"] not in existing
                  and all((c["source"]["paper_id"], ref["result_id"], ref["record_sha256"]) in current
                          for ref in c["retained_result_refs"])]
    added = json.loads(json.dumps(applicable))
    fields = Counter(c["field"] for c in added)
    old_captures = {(c["source"]["paper_id"], c["source"]["capture_id"]) for c in report["candidates"]}
    captures = {(c["source"]["paper_id"], c["source"]["capture_id"]) for c in added} - old_captures
    for coverage in report["coverage"]:
        if coverage["material_id"] != material.id:
            continue
        for field in coverage["fields"]:
            field["candidate_count"] += fields[field["field"]]
            if not field["retained_present"] and field["candidate_count"]:
                field["status"] = "pending_review"
                field["reason_codes"] = ["source_candidates_available"]
        coverage["primary_source_capture_count"] = coverage.get("primary_source_capture_count", 0) + len(captures)
    counts = report["counts"]
    counts["candidate_facts"] += len(added)
    counts["candidate_retained_references"] += sum(c["retained_reference_count"] for c in added)
    counts["primary_source_captures"] = counts.get("primary_source_captures", 0) + len(captures)
    for field, count in fields.items():
        counts["candidate_fields"][field] = counts["candidate_fields"].get(field, 0) + count
    combined = sorted([*report["candidates"], *added], key=lambda c: c["candidate_id"])
    report["candidates_truncated"] = report.get("candidates_truncated", False) or len(combined) > 100
    report["candidates"] = bounded_source_rows(combined)
    counts["candidate_facts_returned"] = len(report["candidates"])
    counts["candidate_facts_omitted"] = counts["candidate_facts"] - len(report["candidates"])
    report["source_recovery_batch"] = json.loads(json.dumps({
        "version": VERSION, "seed_id": batch["seed_id"], "seed_sha256": batch["seed_sha256"],
        "material_id": row["material_id"], "formula": row["formula"], "status": row["status"],
        "summary": row["summary"], "unknowns": row["unknowns"], "observations": row["observations"],
        "retained_result_refs": row["retained_result_refs"], "pending_candidates_in_batch": row["pending_candidates"],
        "scientific_acceptance": False, "human_reviewed": False, "database_changed": False,
    }))
    report.pop("report_sha256", None)
    report["report_sha256"] = digest(report)
    return report
