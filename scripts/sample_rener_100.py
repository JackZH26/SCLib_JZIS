#!/usr/bin/env python3
"""Re-NER 100 sample papers to validate B1+B2 prompt improvements.

Picks 100 papers that have existing materials_extracted but whose
records lack the tc_regime field (i.e. extracted with the old prompt).
Runs the new NER prompt and compares old vs new output.

Usage:
    docker compose run --rm ingestion python /app/scripts/sample_rener_100.py

Skips the aggregator — this is a quality check, not a production run.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
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


async def _rebuild_parsed(session, row) -> ParsedPaper | None:
    chunk_rows = (await session.execute(
        select(chunks_table.c.section, chunks_table.c.chunk_index, chunks_table.c.text)
        .where(chunks_table.c.paper_id == row.id)
        .order_by(chunks_table.c.section, chunks_table.c.chunk_index)
    )).all()

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
        # Pick 100 papers with NER records that lack tc_regime
        rows = (await db.execute(text("""
            SELECT p.id, p.arxiv_id, p.title, p.abstract, p.authors,
                   p.date_submitted, p.categories,
                   p.materials_extracted
            FROM papers p
            WHERE jsonb_array_length(p.materials_extracted) > 0
              AND NOT EXISTS (
                  SELECT 1 FROM jsonb_array_elements(p.materials_extracted) AS r
                  WHERE r->>'tc_regime' IS NOT NULL
              )
            ORDER BY random()
            LIMIT 100
        """))).all()

        log.info("Selected %d papers for re-NER sample", len(rows))

        # Counters
        evidence_old: Counter = Counter()
        evidence_new: Counter = Counter()
        regime_new: Counter = Counter()
        total_old_records = 0
        total_new_records = 0
        papers_ok = 0
        papers_err = 0

        for i, row in enumerate(rows):
            old_mats = row.materials_extracted or []
            total_old_records += len(old_mats)
            for m in old_mats:
                evidence_old[m.get("evidence_type", "unset")] += 1

            try:
                parsed = await _rebuild_parsed(db, row)
                if parsed is None:
                    papers_err += 1
                    continue
                new_mats = await asyncio.to_thread(extract_materials, parsed)
            except Exception as e:
                log.error("%s: NER failed: %s", row.id, e)
                papers_err += 1
                continue

            total_new_records += len(new_mats)
            for m in new_mats:
                evidence_new[m.get("evidence_type", "unset")] += 1
                regime_new[m.get("tc_regime", "unset")] += 1

            # Save the new NER output back to the DB
            await db.execute(
                update(papers_table)
                .where(papers_table.c.id == row.id)
                .values(materials_extracted=new_mats)
            )
            await db.commit()
            papers_ok += 1

            if (i + 1) % 10 == 0:
                log.info("Progress: %d/%d papers processed", i + 1, len(rows))

    await dispose()

    # Report
    log.info("=" * 60)
    log.info("SAMPLE RE-NER REPORT (100 papers)")
    log.info("=" * 60)
    log.info("Papers: ok=%d, err=%d", papers_ok, papers_err)
    log.info("Records: old=%d, new=%d (delta %+d)",
             total_old_records, total_new_records,
             total_new_records - total_old_records)
    log.info("")
    log.info("evidence_type distribution (OLD):")
    for k, v in sorted(evidence_old.items(), key=lambda x: -x[1]):
        log.info("  %-25s %4d", k, v)
    log.info("")
    log.info("evidence_type distribution (NEW):")
    for k, v in sorted(evidence_new.items(), key=lambda x: -x[1]):
        log.info("  %-25s %4d", k, v)
    log.info("")
    log.info("tc_regime distribution (NEW):")
    for k, v in sorted(regime_new.items(), key=lambda x: -x[1]):
        log.info("  %-25s %4d", k, v)


if __name__ == "__main__":
    asyncio.run(main())
