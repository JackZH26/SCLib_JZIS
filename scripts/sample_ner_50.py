#!/usr/bin/env python3
"""NER 50 previously-unprocessed papers and report quality metrics.

Picks 50 random papers from the eligible pool (has SC keywords,
no existing NER, not flagged no_sc_keywords). Runs NER and saves
results, then prints a quality report comparing distributions with
the earlier 100-paper re-NER baseline.

Usage:
    docker compose run --rm ingestion python /app/scripts/sample_ner_50.py
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter

from sqlalchemy import select, text, update

from ingestion.extract.material_ner import extract_materials
from ingestion.index.indexer import _session_factory, papers_table, chunks_table, dispose
from ingestion.models import PaperMetadata, ParsedPaper, Section

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# Baseline from the 100-paper re-NER sample (papers that already had NER)
BASELINE_100 = {
    "papers": 100,
    "records": 454,
    "records_per_paper": 4.54,
    "evidence_type": {
        "primary_experimental": 229,
        "cited": 211,
        "primary_theoretical": 14,
    },
    "tc_regime": {
        "bulk_equilibrium": 259,
        "unknown": 93,
        "thin_film": 59,
        "high_pressure": 39,
        "interface": 4,
    },
}


async def _rebuild_parsed(session, row) -> ParsedPaper | None:
    chunk_rows = (await session.execute(
        select(chunks_table.c.section, chunks_table.c.chunk_index, chunks_table.c.text)
        .where(chunks_table.c.paper_id == row.id)
        .order_by(chunks_table.c.section, chunks_table.c.chunk_index)
    )).all()

    if not chunk_rows:
        return None

    sections_by_name: dict[str, list[str]] = {}
    for sec_name, _idx, t in chunk_rows:
        sections_by_name.setdefault(sec_name or "Body", []).append(t)
    sections = [Section(name=n, text="\n".join(parts))
                for n, parts in sections_by_name.items()]

    meta = PaperMetadata(
        arxiv_id=row.arxiv_id or row.id.replace("arxiv:", ""),
        title=row.title,
        authors=list(row.authors or []),
        abstract=row.abstract,
        date_submitted=row.date_submitted,
        categories=list(row.categories or []),
        primary_category=None,
    )
    return ParsedPaper(meta=meta, sections=sections)


async def main():
    Session = _session_factory()

    async with Session() as db:
        rows = (await db.execute(text("""
            SELECT p.id, p.arxiv_id, p.title, p.abstract, p.authors,
                   p.date_submitted, p.categories
            FROM papers p
            WHERE chunk_count > 0
              AND jsonb_array_length(materials_extracted) = 0
              AND title IS NOT NULL AND title != ''
              AND NOT quality_flags ? 'no_sc_keywords'
            ORDER BY random()
            LIMIT 50
        """))).all()

    log.info("Selected %d papers for NER sample", len(rows))

    evidence: Counter = Counter()
    regime: Counter = Counter()
    total_records = 0
    papers_with_records = 0
    papers_empty = 0
    papers_err = 0
    tc_values: list[dict] = []

    for i, row in enumerate(rows):
        try:
            async with Session() as db:
                parsed = await _rebuild_parsed(db, row)
                if parsed is None:
                    papers_err += 1
                    continue

                materials = await asyncio.to_thread(extract_materials, parsed)

                await db.execute(
                    update(papers_table)
                    .where(papers_table.c.id == row.id)
                    .values(materials_extracted=materials)
                )
                await db.commit()

            if materials:
                papers_with_records += 1
            else:
                papers_empty += 1

            total_records += len(materials)
            for m in materials:
                evidence[m.get("evidence_type", "unset")] += 1
                regime[m.get("tc_regime", "unset")] += 1
                if m.get("tc_kelvin") is not None:
                    tc_values.append({
                        "paper": row.id,
                        "formula": m.get("formula", "?"),
                        "tc_kelvin": m["tc_kelvin"],
                        "evidence": m.get("evidence_type", "?"),
                        "regime": m.get("tc_regime", "?"),
                    })

        except Exception as e:
            log.error("%s: NER failed: %s", row.id, e)
            papers_err += 1

        if (i + 1) % 10 == 0:
            log.info("Progress: %d/%d", i + 1, len(rows))

    await dispose()

    # Report
    log.info("=" * 70)
    log.info("50-PAPER NER SAMPLE REPORT")
    log.info("=" * 70)
    log.info("")
    log.info("Papers: with_records=%d, empty=%d, err=%d",
             papers_with_records, papers_empty, papers_err)
    log.info("Total NER records: %d (%.2f per paper)",
             total_records, total_records / max(1, papers_with_records + papers_empty))
    log.info("")

    # Side-by-side evidence_type comparison
    log.info("%-30s %10s %10s", "evidence_type", "THIS (50)", "BASELINE (100)")
    log.info("-" * 55)
    all_ev = sorted(set(list(evidence.keys()) + list(BASELINE_100["evidence_type"].keys())))
    for k in all_ev:
        new_v = evidence.get(k, 0)
        old_v = BASELINE_100["evidence_type"].get(k, 0)
        new_pct = f"{new_v / max(1, total_records) * 100:.0f}%" if total_records else "-"
        old_total = sum(BASELINE_100["evidence_type"].values())
        old_pct = f"{old_v / max(1, old_total) * 100:.0f}%" if old_total else "-"
        log.info("  %-28s %4d (%s) %6d (%s)", k, new_v, new_pct, old_v, old_pct)
    log.info("")

    # Side-by-side tc_regime comparison
    log.info("%-30s %10s %10s", "tc_regime", "THIS (50)", "BASELINE (100)")
    log.info("-" * 55)
    all_re = sorted(set(list(regime.keys()) + list(BASELINE_100["tc_regime"].keys())))
    for k in all_re:
        new_v = regime.get(k, 0)
        old_v = BASELINE_100["tc_regime"].get(k, 0)
        new_pct = f"{new_v / max(1, total_records) * 100:.0f}%" if total_records else "-"
        old_total = sum(BASELINE_100["tc_regime"].values())
        old_pct = f"{old_v / max(1, old_total) * 100:.0f}%" if old_total else "-"
        log.info("  %-28s %4d (%s) %6d (%s)", k, new_v, new_pct, old_v, old_pct)
    log.info("")

    # Sample Tc values
    log.info("Sample Tc extractions (up to 15):")
    tc_values.sort(key=lambda x: -x["tc_kelvin"])
    for t in tc_values[:15]:
        log.info("  %s  Tc=%.1fK  %s  %s  (%s)",
                 t["formula"], t["tc_kelvin"], t["evidence"], t["regime"], t["paper"])


if __name__ == "__main__":
    asyncio.run(main())
