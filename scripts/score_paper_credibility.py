#!/usr/bin/env python3
"""Score paper credibility tiers (T1-T5) using internal + enriched signals.

Tier definitions:
  T1 (high credibility):
    - Has formal journal DOI AND not a review paper, OR
    - 1-3 extractions, all evidence_type=primary/primary_experimental,
      avg confidence >= 0.8, no Tc anomalies
  T2 (normal credibility):
    - <= 10 extractions, no Tc anomalies
    - evidence_type mix of primary + cited acceptable
  T3 (use with caution):
    - 11-30 extractions (mini-review), OR
    - cited ratio > 50%, OR
    - low average confidence (< 0.6)
  T4 (low credibility):
    - > 30 extractions (large review/survey), OR
    - Tc anomaly rate > 30%, OR
    - purely theoretical/cited evidence
  T5 (exclude):
    - Retracted papers
    - All extracted Tc exceed per-compound caps
    - In refuted_claims table

Signals used:
  - distinct_formulas: count of extraction records
  - primary_ratio: fraction of records with evidence_type in (primary, primary_experimental)
  - avg_confidence: mean confidence across records
  - tc_anomaly_rate: fraction of records where tc_kelvin exceeds per-compound cap
  - has_journal_doi: papers.doi starts with '10.'
  - paper_type: from S2 enrichment or inferred from NER records
  - citation_count: from S2 enrichment (higher = more credible)
  - is_retracted: papers.status = 'retracted'
  - categories: whether paper is in cond-mat.supr-con

Usage:
    python scripts/score_paper_credibility.py [--dry-run]

    # Inside Docker:
    docker compose exec -T api python /app/scripts/score_paper_credibility.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def _load_caps(conn) -> dict[str, float]:
    """Load per-compound Tc caps from manual_overrides."""
    rows = conn.execute(text("""
        SELECT canonical, override_value::float
        FROM manual_overrides
        WHERE field = 'tc_max' AND is_cap = true
    """)).fetchall()
    return {r[0]: r[1] for r in rows}


def _load_refuted(conn) -> set[str]:
    """Load refuted canonical formulas."""
    rows = conn.execute(text("SELECT DISTINCT canonical FROM refuted_claims")).fetchall()
    return {r[0] for r in rows}


# Family-level Tc caps (fallback when no per-compound cap exists)
_FAMILY_TC_CAPS: dict[str, float] = {
    "cuprate": 165,
    "iron_based": 60,
    "hydride": 300,
    "conventional": 40,
    "heavy_fermion": 3,
    "organic": 15,
    "fulleride": 45,
    "elemental": 12,
    "mgb2": 42,
    "nickelate": 100,
    "kagome": 5,
    "bismuthate": 35,
    "borocarbide": 25,
    "ruthenate": 2,
    "bis2_layered": 15,
    "chalcogenide": 20,
}
_TC_SANITY_MAX = 300  # absolute max for any material


def _infer_paper_type(records: list[dict]) -> str | None:
    """Infer paper_type from NER record-level paper_type fields."""
    types: dict[str, int] = {}
    for r in records:
        pt = r.get("paper_type")
        if pt:
            types[pt] = types.get(pt, 0) + 1
    if not types:
        return None
    # If all the same, return that
    return max(types, key=types.get)


def score_paper(
    paper: dict[str, Any],
    records: list[dict[str, Any]],
    caps: dict[str, float],
    refuted_set: set[str],
) -> tuple[str, str]:
    """Return (tier, reason) for a single paper.

    paper: row from papers table
    records: materials_extracted JSONB parsed
    caps: canonical → Tc cap mapping
    refuted_set: set of refuted canonical formulas
    """
    # ---- T5: hard disqualifiers ----
    if paper["status"] == "retracted":
        return "T5", "retracted"

    # Check if all formulas are refuted
    formulas = set()
    for r in records:
        f = r.get("formula", "")
        if f:
            formulas.add(f.lower().replace(" ", ""))
    if formulas and all(f in refuted_set for f in formulas):
        return "T5", "all_formulas_refuted"

    # ---- Compute signals ----
    n_records = len(records)
    if n_records == 0:
        return "T3", "no_extraction_records"

    # Distinct formulas
    distinct_formulas = len(set(r.get("formula", "") for r in records if r.get("formula")))

    # Evidence type ratios
    primary_count = 0
    cited_count = 0
    for r in records:
        et = r.get("evidence_type", "")
        if et in ("primary", "primary_experimental"):
            primary_count += 1
        elif et == "cited":
            cited_count += 1
    primary_ratio = primary_count / n_records if n_records > 0 else 0
    cited_ratio = cited_count / n_records if n_records > 0 else 0

    # Average confidence
    confs = [r.get("confidence", 0.5) for r in records]
    avg_conf = sum(confs) / len(confs) if confs else 0.5

    # Tc anomaly rate (records with tc_kelvin exceeding cap)
    tc_anomalies = 0
    tc_total = 0
    for r in records:
        tc = r.get("tc_kelvin")
        if tc is not None and tc > 0:
            tc_total += 1
            formula_key = (r.get("formula") or "").lower().replace(" ", "")
            family = r.get("family", "")
            cap = caps.get(formula_key) or _FAMILY_TC_CAPS.get(family, _TC_SANITY_MAX)
            if tc > cap * 1.2:  # 20% tolerance
                tc_anomalies += 1
    anomaly_rate = tc_anomalies / tc_total if tc_total > 0 else 0

    # Journal DOI
    doi = paper.get("doi") or ""
    has_journal_doi = bool(doi and doi.startswith("10."))

    # Paper type (prefer DB column, fallback to NER inference)
    paper_type = paper.get("paper_type") or _infer_paper_type(records)

    # Citation count
    citation_count = paper.get("citation_count", 0) or 0

    # arXiv category: is it cond-mat.supr-con?
    categories = paper.get("categories") or []
    is_supr_con = "cond-mat.supr-con" in categories if isinstance(categories, list) else False

    # ---- T5: all Tc values anomalous ----
    if tc_total > 0 and anomaly_rate > 0.8:
        return "T5", f"anomaly_rate={anomaly_rate:.0%}"

    # ---- T4: low credibility ----
    if distinct_formulas > 30:
        return "T4", f"review_paper_{distinct_formulas}_formulas"

    if paper_type == "review":
        return "T4", "s2_classified_review"

    if anomaly_rate > 0.3:
        return "T4", f"high_anomaly_rate={anomaly_rate:.0%}"

    if primary_ratio == 0 and n_records > 5:
        return "T4", "no_primary_evidence_many_records"

    # ---- T1: high credibility ----
    # Rule: journal DOI + not a review
    if has_journal_doi and paper_type != "review" and distinct_formulas <= 10:
        return "T1", "journal_doi"

    # Rule: focused experimental paper
    if (distinct_formulas <= 3
            and primary_ratio >= 0.8
            and avg_conf >= 0.8
            and anomaly_rate == 0
            and n_records <= 10):
        reason_parts = ["focused_experimental"]
        if citation_count >= 50:
            reason_parts.append(f"citations={citation_count}")
        if is_supr_con:
            reason_parts.append("supr-con")
        return "T1", "_".join(reason_parts)

    # High-citation focused paper
    if citation_count >= 100 and distinct_formulas <= 5 and anomaly_rate == 0:
        return "T1", f"high_citation_{citation_count}"

    # ---- T2: normal credibility ----
    if distinct_formulas <= 10 and anomaly_rate == 0:
        return "T2", "normal"

    if distinct_formulas <= 10 and anomaly_rate <= 0.1:
        return "T2", f"minor_anomaly={anomaly_rate:.0%}"

    if primary_ratio >= 0.5 and distinct_formulas <= 15:
        return "T2", "mostly_primary"

    # ---- T3: use with caution ----
    if distinct_formulas > 10:
        return "T3", f"many_formulas_{distinct_formulas}"

    if cited_ratio > 0.5:
        return "T3", f"mostly_cited={cited_ratio:.0%}"

    if avg_conf < 0.6:
        return "T3", f"low_confidence={avg_conf:.2f}"

    # Default: T2
    return "T2", "default"


def main():
    parser = argparse.ArgumentParser(description="Score paper credibility tiers")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max papers to score (0=all)")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        log.error("DATABASE_URL not set")
        sys.exit(1)

    sync_url = db_url.replace("+asyncpg", "").replace("+aiopg", "")
    engine = create_engine(sync_url)

    with engine.connect() as conn:
        caps = _load_caps(conn)
        log.info("Loaded %d per-compound Tc caps", len(caps))
        refuted = _load_refuted(conn)
        log.info("Loaded %d refuted formulas", len(refuted))

    # Load papers with extractions
    with engine.connect() as conn:
        limit_clause = f"LIMIT {args.limit}" if args.limit > 0 else ""
        rows = conn.execute(text(f"""
            SELECT id, doi, status, citation_count, categories, paper_type,
                   materials_extracted
            FROM papers
            WHERE materials_extracted::text != '[]'
            ORDER BY id
            {limit_clause}
        """)).fetchall()

    log.info("Scoring %d papers with extractions...", len(rows))

    # Also score papers without extractions (give them T3 by default)
    with engine.connect() as conn:
        no_ext_rows = conn.execute(text(f"""
            SELECT id, doi, status, citation_count, categories, paper_type
            FROM papers
            WHERE materials_extracted::text = '[]'
            ORDER BY id
            {limit_clause}
        """)).fetchall()

    log.info("Papers without extractions: %d (will be T3 by default)", len(no_ext_rows))

    tier_counts: dict[str, int] = {"T1": 0, "T2": 0, "T3": 0, "T4": 0, "T5": 0}
    updates: list[tuple[str, str]] = []  # (tier, paper_id)

    # Score papers with extractions
    for row in rows:
        paper = {
            "id": row[0],
            "doi": row[1],
            "status": row[2],
            "citation_count": row[3],
            "categories": row[4],
            "paper_type": row[5],
        }
        records = row[6] if isinstance(row[6], list) else json.loads(row[6])

        tier, reason = score_paper(paper, records, caps, refuted)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        updates.append((tier, paper["id"]))

        if args.dry_run and len(updates) <= 20:
            log.info("[DRY] %s → %s (%s) [%d records]",
                     paper["id"], tier, reason, len(records))

    # Score papers without extractions
    for row in no_ext_rows:
        paper_id = row[0]
        status = row[2]
        if status == "retracted":
            tier = "T5"
        else:
            tier = "T3"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        updates.append((tier, paper_id))

    # Summary
    log.info("=== Tier distribution ===")
    total = sum(tier_counts.values())
    for t in ("T1", "T2", "T3", "T4", "T5"):
        c = tier_counts.get(t, 0)
        pct = 100 * c / total if total > 0 else 0
        log.info("  %s: %5d (%5.1f%%)", t, c, pct)
    log.info("  Total: %d", total)

    # Write to DB
    if not args.dry_run:
        log.info("Writing tiers to database...")
        with engine.begin() as conn:
            # Batch update using a temp approach for speed
            batch_size = 5000
            for i in range(0, len(updates), batch_size):
                batch = updates[i:i + batch_size]
                for tier, paper_id in batch:
                    conn.execute(
                        text("UPDATE papers SET credibility_tier = :tier WHERE id = :pid"),
                        {"tier": tier, "pid": paper_id},
                    )
                log.info("  Written %d/%d", min(i + batch_size, len(updates)), len(updates))
        log.info("Done writing tiers.")
    else:
        log.info("[DRY RUN] No DB writes.")


if __name__ == "__main__":
    main()
