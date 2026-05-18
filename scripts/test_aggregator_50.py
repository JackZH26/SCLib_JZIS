#!/usr/bin/env python3
"""Test aggregator on 50 random materials: compare new output vs current DB.

Picks 50 random canonical formulas that have NER records, runs
_derive_summary on each, and compares key fields against the
existing materials table row. Reports changes, regressions, and
overall quality metrics.

Usage:
    docker compose run --rm ingestion python /app/scripts/test_aggregator_50.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select, text

from ingestion.extract.materials_aggregator import (
    _derive_summary,
    _load_all_overrides,
    _load_all_refuted,
    _material_id,
    _clean_display,
    normalize_formula,
    _MIN_CONFIDENCE,
)
from ingestion.extract import formula_validator as _fv
from ingestion.index.indexer import (
    _session_factory,
    dispose,
    materials_table,
    papers_table,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

COMPARE_FIELDS = [
    "tc_max", "tc_ambient", "tc_max_experimental", "tc_max_theoretical",
    "dominant_evidence", "family", "best_credibility_tier",
    "total_papers", "is_unconventional", "disputed", "needs_review",
    "pairing_symmetry", "crystal_structure", "ambient_sc",
]

_TIER_MULTIPLIER = {"T1": 1.0, "T2": 1.0, "T3": 0.8, "T4": 0.0, "T5": 0.0}
_DEFAULT_CONFIDENCE = 0.5


async def main():
    Session = _session_factory()

    async with Session() as db:
        override_map = await _load_all_overrides(db)
        refuted_map = await _load_all_refuted(db)

        # Pick 50 random materials that exist in both papers NER and materials table
        sample_rows = (await db.execute(text("""
            SELECT m.id, m.formula, m.formula_normalized,
                   m.tc_max, m.tc_ambient, m.tc_max_experimental,
                   m.tc_max_theoretical, m.dominant_evidence, m.family,
                   m.best_credibility_tier, m.total_papers,
                   m.is_unconventional, m.disputed, m.needs_review,
                   m.pairing_symmetry, m.crystal_structure, m.ambient_sc
            FROM materials m
            WHERE m.total_papers >= 1
              AND m.tc_max IS NOT NULL
            ORDER BY random()
            LIMIT 50
        """))).all()

        log.info("Selected %d materials for aggregator test", len(sample_rows))

        # Load all papers with NER records (same as aggregator does)
        all_papers = (await db.execute(
            select(
                papers_table.c.id,
                papers_table.c.date_submitted,
                papers_table.c.materials_extracted,
                papers_table.c.credibility_tier,
            ).where(
                (papers_table.c.status != "retracted")
                | (papers_table.c.status.is_(None))
            )
        )).all()

    # Build grouped records (same logic as aggregate_from_papers)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    display_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for paper_id, date_submitted, mats, cred_tier in all_papers:
        if not isinstance(mats, list) or not mats:
            continue
        tier_mult = _TIER_MULTIPLIER.get(cred_tier, 1.0)
        if tier_mult <= 0.0:
            continue
        year = date_submitted.year if date_submitted else None
        for m in mats:
            if not isinstance(m, dict):
                continue
            raw = m.get("formula")
            if not raw or not isinstance(raw, str):
                continue
            raw = _fv.normalize_whitespace(raw)
            ok, _ = _fv.validate_formula(raw)
            if not ok:
                continue
            if m.get("evidence_type") == "cited":
                continue
            conf = m.get("confidence")
            if isinstance(conf, (int, float)) and conf < _MIN_CONFIDENCE:
                continue
            tc = m.get("tc_kelvin")
            if isinstance(tc, (int, float)) and (tc < 0.01 or tc > 300):
                continue
            norm = normalize_formula(raw)
            if not norm:
                continue
            record = dict(m)
            record["paper_id"] = paper_id
            record["credibility_tier"] = cred_tier
            if tier_mult < 1.0:
                raw_conf = record.get("confidence", _DEFAULT_CONFIDENCE)
                record["confidence"] = round(raw_conf * tier_mult, 3)
            if year is not None and "year" not in record:
                record["year"] = year
            grouped[norm].append(record)
            display_counts[norm][_clean_display(raw) or raw.strip()] += 1

    log.info("Built %d canonical groups from papers NER", len(grouped))

    # Compare each sample material
    changes_summary: Counter = Counter()
    tc_changes: list[dict] = []
    field_changes: dict[str, list[dict]] = defaultdict(list)
    total_checked = 0
    no_records = 0

    for row in sample_rows:
        norm = row.formula_normalized
        if norm not in grouped:
            no_records += 1
            continue

        records = grouped[norm]
        candidates = display_counts[norm].most_common()
        top_count = candidates[0][1]
        top_raws = [r for r, c in candidates if c == top_count]
        display_raw = min(top_raws, key=len)

        new_summary = _derive_summary(
            display_raw, records,
            overrides=override_map.get(norm),
            refuted=refuted_map.get(norm),
        )

        total_checked += 1
        old = {f: getattr(row, f, None) for f in COMPARE_FIELDS}

        for field in COMPARE_FIELDS:
            old_val = old.get(field)
            new_val = new_summary.get(field)

            # Normalize for comparison
            if isinstance(old_val, float) and isinstance(new_val, float):
                if abs(old_val - new_val) < 0.01:
                    continue
            elif old_val == new_val:
                continue

            changes_summary[field] += 1
            change = {
                "formula": row.formula,
                "old": old_val,
                "new": new_val,
            }
            field_changes[field].append(change)

            if field in ("tc_max", "tc_ambient"):
                tc_changes.append({
                    "formula": row.formula,
                    "field": field,
                    "old": old_val,
                    "new": new_val,
                    "total_papers": new_summary.get("total_papers", 0),
                })

    await dispose()

    # Report
    log.info("=" * 70)
    log.info("AGGREGATOR TEST REPORT (50 materials)")
    log.info("=" * 70)
    log.info("")
    log.info("Checked: %d materials (skipped %d with no NER records)",
             total_checked, no_records)
    log.info("")

    # Overall change rate
    total_field_checks = total_checked * len(COMPARE_FIELDS)
    total_changes = sum(changes_summary.values())
    log.info("Field-level changes: %d / %d (%.1f%%)",
             total_changes, total_field_checks,
             total_changes / max(1, total_field_checks) * 100)
    log.info("")

    # Per-field change count
    log.info("%-25s %6s %6s", "Field", "Changed", "Rate")
    log.info("-" * 45)
    for field in COMPARE_FIELDS:
        n = changes_summary.get(field, 0)
        rate = n / max(1, total_checked) * 100
        marker = " <<<" if rate > 30 else ""
        log.info("  %-23s %4d   %5.1f%%%s", field, n, rate, marker)
    log.info("")

    # Tc changes detail (most important)
    if tc_changes:
        log.info("Tc value changes (tc_max / tc_ambient):")
        log.info("%-25s %-10s %10s %10s %6s", "Formula", "Field", "Old", "New", "Papers")
        log.info("-" * 65)
        for c in sorted(tc_changes, key=lambda x: abs((x["new"] or 0) - (x["old"] or 0)), reverse=True)[:20]:
            old_s = f"{c['old']:.1f}" if c['old'] is not None else "NULL"
            new_s = f"{c['new']:.1f}" if c['new'] is not None else "NULL"
            log.info("  %-23s %-10s %10s %10s %6d",
                     c["formula"][:23], c["field"], old_s, new_s, c["total_papers"])
    else:
        log.info("No Tc value changes detected.")
    log.info("")

    # Dominant evidence changes
    if "dominant_evidence" in field_changes:
        log.info("dominant_evidence changes:")
        for c in field_changes["dominant_evidence"][:10]:
            log.info("  %s: %s -> %s", c["formula"][:30], c["old"], c["new"])
    log.info("")

    # best_credibility_tier changes
    if "best_credibility_tier" in field_changes:
        log.info("best_credibility_tier changes:")
        for c in field_changes["best_credibility_tier"][:10]:
            log.info("  %s: %s -> %s", c["formula"][:30], c["old"], c["new"])
    log.info("")

    # needs_review changes (regression check)
    if "needs_review" in field_changes:
        log.info("needs_review changes (potential regressions):")
        for c in field_changes["needs_review"][:10]:
            log.info("  %s: %s -> %s", c["formula"][:30], c["old"], c["new"])
    log.info("")

    # Verdict
    tc_change_count = len(tc_changes)
    needs_review_regressions = sum(
        1 for c in field_changes.get("needs_review", [])
        if c["old"] is False and c["new"] is True
    )
    log.info("=" * 70)
    log.info("VERDICT")
    log.info("=" * 70)
    log.info("  Tc changes:              %d / %d materials", tc_change_count, total_checked)
    log.info("  needs_review regressions: %d", needs_review_regressions)
    log.info("  Total field changes:      %d / %d", total_changes, total_field_checks)

    if needs_review_regressions > 5:
        log.info("  STATUS: CAUTION — many materials newly flagged for review")
    elif tc_change_count > total_checked * 0.3:
        log.info("  STATUS: CAUTION — >30%% materials have Tc changes")
    else:
        log.info("  STATUS: OK — changes within expected range")


if __name__ == "__main__":
    asyncio.run(main())
