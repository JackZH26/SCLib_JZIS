"""Build a metadata-only, append-only Materials source-inspection batch.

Inputs are explicit local snapshot exports, original-source captures and an
AI-assisted inspection spec. No network, DB writes, property computation or
approval. Full passages stay in the private source store; output contains
locators/hashes, short factual observations and pending literal candidates.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from services.material_enrichment import (  # noqa: E402
    AUTHORITY, EXTRACTOR_VERSION, MAX_RECORD_COVERAGE_RECORDS, RECORD_COVERAGE_VERSION,
    build_enrichment_report, canonical, digest, text_digest, validate_candidate_identity,
)
from services.property_evidence import legacy_result_id  # noqa: E402

VERSION = "materials-recovery-batch-seed/1.0.0"
MAX_INPUT = 16 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def read(path, jsonl=False):
    if Path(path).stat().st_size > MAX_INPUT:
        raise ValueError("input_byte_limit")
    body = Path(path).read_bytes()
    if len(body) > MAX_INPUT:
        raise ValueError("input_byte_limit")
    return ([json.loads(line) for line in body.splitlines() if line.strip()]
            if jsonl else json.loads(body))


def retained_bindings(material, request):
    """Bind complete records to a separately reviewed public coverage snapshot.

    raw_archive.records[].raw is a lossy display allowlist, not the retained
    record. Never manufacture runtime IDs or hashes from that projection.
    Coverage is independently versioned/hashed by the API using the same
    current eligible records as the unchanged runtime merge guard.
    """
    coverage = material.get("record_coverage")
    expected = request.get("record_coverage_sha256")
    records = material.get("records")
    if (not isinstance(coverage, dict) or not isinstance(expected, str)
            or not _SHA.fullmatch(expected)
            or coverage.get("version") != RECORD_COVERAGE_VERSION
            or coverage.get("material_id") != material["id"]
            or coverage.get("record_denominator") != "current_eligible_retained_records"
            or any(coverage.get(key) is not False for key in AUTHORITY)
            or coverage.get("coverage_sha256") != expected
            or digest({k: v for k, v in coverage.items() if k != "coverage_sha256"}) != expected):
        raise ValueError("reviewed_record_coverage_required")
    rows = coverage.get("records")
    if (type(records) is not list or not 1 <= len(records) <= MAX_RECORD_COVERAGE_RECORDS
            or any(type(record) is not dict for record in records)
            or type(rows) is not list or len(rows) != len(records)
            or any(type(coverage.get(key)) is not int or coverage[key] != len(records)
                   for key in ("records_total", "records_inspected"))
            or type(coverage.get("records_unchecked")) is not int or coverage["records_unchecked"] != 0):
        raise ValueError("complete_record_coverage_required")
    by_offset = {}
    for row in rows:
        offset = row.get("record_offset") if isinstance(row, dict) else None
        if type(offset) is not int or not 0 <= offset < len(records) or offset in by_offset:
            raise ValueError("record_coverage_offset_mismatch")
        record = records[offset]
        if (not isinstance(row.get("paper_id"), str) or not row["paper_id"]
                or row["paper_id"] != record.get("paper_id")
                or row.get("result_id") != legacy_result_id(record, scope_id=material["id"])
                or row.get("record_sha256") != digest(record)):
            raise ValueError("retained_record_coverage_mismatch")
        by_offset[offset] = {key: row[key] for key in ("paper_id", "result_id", "record_sha256")}
    return by_offset


def build(materials, sources, spec):
    if len(materials) > 20 or len(spec["rows"]) != len(materials):
        raise ValueError("review_batch_material_scope")
    rows, reports = [], []
    source_map = {s["id"]: s for s in sources}
    if len(source_map) != len(sources):
        raise ValueError("duplicate_source")
    for request in spec["rows"]:
        material = next(m for m in materials if m["id"] == request["material_id"])
        bindings = retained_bindings(material, request)
        own = [s for s in sources if s["paper_id"] in {r.get("paper_id") for r in material["records"]}]
        report = build_enrichment_report([material], own, include_evidence_text=False)
        rules = request["candidate_rules"]
        chosen = []
        for rule in rules:
            if not isinstance(rule, dict) or set(rule) != {"candidate_id", "paper_id", "capture_id", "page", "field", "value", "expected_subject"}:
                raise ValueError("reviewed_candidate_identity_and_conditions_required")
            matches = [c for c in report["candidates"] if c["candidate_id"] == rule["candidate_id"]
                       and c["source"]["paper_id"] == rule["paper_id"]
                       and c["source"]["capture_id"] == rule["capture_id"]
                       and [c["source"]["locator"]["page"], c["field"], c["value"]]
                       == [rule["page"], rule["field"], rule["value"]]]
            if len(matches) != 1:
                raise ValueError("selected_literal_or_source_identity_changed")
            if matches[0]["subject"] != rule["expected_subject"]:
                raise ValueError("selected_literal_conditions_changed")
            if matches[0]["candidate_id"] in {c["candidate_id"] for c in chosen}:
                raise ValueError("duplicate_reviewed_candidate")
            chosen.append(matches[0])
        for candidate in chosen:
            validate_candidate_identity(candidate)
        # Selection is source review, never permission to promote a candidate.
        # Full-page coverage/classification counts cannot describe a selected
        # window. Save only the reviewed pending facts and their own counts.
        report = {"version": report["version"], "extractor_version": report["extractor_version"],
                  "candidates": chosen, "counts": {
                      "candidate_facts": len(chosen),
                      "candidate_fields": {f: sum(c["field"] == f for c in chosen) for f in sorted({c["field"] for c in chosen})},
                      "candidate_retained_references": sum(c["retained_reference_count"] for c in chosen),
                      "promoted_facts": 0}, **AUTHORITY}
        report["report_sha256"] = digest(report)
        reports.append(report)
        observations = []
        for index, (field, label, value, page, pattern, origin, scope) in enumerate(request["observations"]):
            matches = [(source, match) for source in own if source["locator"].get("page") == page
                       for match in re.finditer(pattern, source["text"], re.I | re.S)]
            if len(matches) != 1:
                raise ValueError(f"source_span_not_unique:{material['id']}:{index}:{page}")
            source, match = matches[0]
            observations.append({"id": "inspection:" + digest({"material_id": material["id"], "field": field, "value": value, "source_id": source["id"], "start": match.start()}),
                "field": field, "label": label, "value": value, "knowledge_origin": origin, "scope": scope,
                "source_content_inspected": True, "inspection_actor": "AI-assisted source check",
                "sample_association_status": "pending", "source": {"paper_id": source["paper_id"],
                    "source_revision": source["source_revision"], "source_url": source["source_url"],
                    "capture_sha256": source["capture_sha256"], "content_sha256": source["content_sha256"],
                    "locator": source["locator"], "span": {"char_start": match.start(), "char_end": match.end(),
                    "text_sha256": text_digest(match.group())}, "source_status": source.get("source_status", "unknown")}})
        paper_ids = {o["source"]["paper_id"] for o in observations}
        refs = [dict(bindings[index]) for index, record in enumerate(material["records"])
                if record.get("paper_id") in paper_ids]
        rows.append({"material_id": material["id"], "formula": material["formula"], "status": "checked",
            "source_available": True, "summary": request["summary"], "unknowns": request["unknowns"],
            "retained_result_refs": refs, "observations": observations, "pending_candidates": len(chosen),
            "scientific_acceptance": False, "human_reviewed": False, "database_changed": False})
    seed = {"version": VERSION, "seed_id": "materials-primary16-2026-10-09-v2", "extractor_version": EXTRACTOR_VERSION,
            "inspection_scope": "AI-assisted original-source inspection; sample/state and scientific approval remain pending",
            "source_text_included": False, "human_reviewed": False, "reports": reports, "rows": rows,
            "counts": {"checked_materials": len(rows), "available_materials": sum(r["source_available"] for r in rows),
                "source_observations": sum(len(r["observations"]) for r in rows),
                "pending_candidate_facts": sum(len(r["candidates"]) for r in reports),
                "canonical_facts_changed": 0, "approved_facts": 0}, **AUTHORITY}
    seed["seed_sha256"] = digest(seed)
    return seed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materials", required=True)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--review-spec", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    seed = build(read(args.materials, True), read(args.sources, True), read(args.review_spec))
    body = canonical(seed)
    if len(body) > 1_000_000:
        raise ValueError("output_byte_limit")
    with Path(args.output).open("xb") as handle:
        handle.write(body)
    print(json.dumps({"bytes": len(body), "seed_sha256": seed["seed_sha256"], "counts": seed["counts"]}))


if __name__ == "__main__":
    main()
