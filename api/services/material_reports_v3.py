"""Atomic, paged report view over current eligible records. No cached maxima joins."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping

from services.result_semantics import classify_result
from services.scientific_values import record_quantity


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


def _text(record, *keys):
    return next(
        (record[k] for k in keys if isinstance(record.get(k), str) and record[k].strip()), None
    )


def report_projection(
    material_id, records, *, work_map=None, papers=None, offset=0, limit=50, original_indices=None
):
    """Unknown samples/series stay source-position scoped; no numeric-point dedup."""
    work_map, papers = work_map or {}, papers or {}
    rows = []
    original_indices = list(range(len(records))) if original_indices is None else original_indices
    if len(original_indices) != len(records):
        raise ValueError("record_index_scope_mismatch")
    for index, raw in zip(original_indices, records, strict=True):
        if not isinstance(raw, dict):
            continue
        source = _text(raw, "paper_id")
        work = work_map.get(source)
        occurrence = _hash(
            {
                "material_id": material_id,
                "paper_id": source,
                "record_index": index,
                "locator": raw.get("source_locator", {}),
            }
        )
        # Legacy array offsets are explicit provisional identities, never source occurrences.
        classification = classify_result(raw)
        tc = record_quantity(raw, "tc_kelvin")
        pressure = record_quantity(raw, "pressure_gpa")
        sample = _text(raw, "sample_id", "sample_label")
        series = _text(raw, "series_id", "series_label")
        path = _text(raw, "path_direction") or "unknown"
        paper = papers.get(source, {})
        locator = raw.get("source_locator")
        locator = locator if isinstance(locator, Mapping) else {}
        props = []
        for key, field, unit in (
            ("upper_critical_field", "hc2_tesla", "T"),
            ("electron_phonon_lambda", "lambda_eph", "1"),
            ("omega_log", "omega_log_k", "K"),
            ("coulomb_mu_star", "mu_star", "1"),
        ):
            q = record_quantity(raw, field)
            if q["status"] == "parsed":
                props.append({"key": key, "quantity": q, "unit": unit})
        year = paper.get("year") or raw.get("year")
        year = year if type(year) is int and 1000 <= year <= 9999 else None
        rows.append(
            {
                "point_id": "retained:" + occurrence,
                "event_id": _text(raw, "event_id"),
                "work_id": str(work) if work else None,
                "paper_id": source,
                "title": _text(paper, "title"),
                "year": year,
                "sample_label": sample,
                "sample_form": _text(raw, "sample_form"),
                "series_id": str(series) if series else None,
                "path_direction": path,
                "point_label": _text(raw, "point_label"),
                "replicate_label": _text(raw, "replicate_label"),
                "sc_outcome": _text(raw, "sc_outcome", "result_status") or "unknown",
                "tc": tc,
                "pressure": pressure,
                "pressure_role": raw.get("pressure_role")
                if raw.get("pressure_role") in ("measurement_pressure", "calculation_pressure")
                else "unknown",
                "pressure_semantics": _text(raw, "pressure_semantics"),
                "tc_definition": _text(raw, "tc_definition", "tc_criterion", "tc_type")
                or "unknown",
                "method": _text(
                    raw, "calculation_method", "measurement_method", "measurement", "method"
                ),
                "knowledge_origin": classification.knowledge_origin,
                "source_role": classification.source_role,
                "minimum_test_temperature": record_quantity(raw, "minimum_temperature_k"),
                "source_locator": {
                    k: v
                    for k, v in locator.items()
                    if k
                    in {
                        "section",
                        "page",
                        "paragraph",
                        "table",
                        "row",
                        "column",
                        "figure",
                        "chunk_id",
                        "span_id",
                        "start",
                        "end",
                        "line",
                        "block_id",
                    }
                    and type(v) in {str, int}
                },
                "properties": props,
                "record_index": index,
                "identity_status": "legacy_record_position",
                "review_status": "pending",
            }
        )
    groups = defaultdict(list)
    for row in rows[offset : offset + limit]:
        group = row["work_id"] or "unresolved-source:" + (row["paper_id"] or row["point_id"])
        groups[group].append(row)
    return {
        "version": "material-reports/3.0",
        "material_id": material_id,
        "projection_kind": "current_eligible_retained_records",
        "total_points": len(rows),
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < len(rows),
        "report_groups": [
            {"group_id": group, "work_id": points[0]["work_id"], "points": points}
            for group, points in groups.items()
        ],
        "support_counts": {
            "source_ids": len({r["paper_id"] for r in rows if r["paper_id"]}),
            "verified_unique_works": len({r["work_id"] for r in rows if r["work_id"]}),
            "work_identity_unknown_sources": len(
                {r["paper_id"] for r in rows if r["paper_id"] and not r["work_id"]}
            ),
            "result_points": len(rows),
            "independent_data_groups": None,
            "cited_report_points": sum(r["source_role"] == "cited" for r in rows),
        },
        "coverage": {"status": "legacy_extraction_scope_unknown", "no_claim_found_allowed": False},
        "scientific_acceptance": False,
        "projection_sha256": _hash(rows),
    }
