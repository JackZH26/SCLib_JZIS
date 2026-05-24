#!/usr/bin/env python3
"""Re-NER papers that have old NER output (missing tc_regime field).

Selects papers whose materials_extracted is non-empty but none of the
records contain a tc_regime key.  Processes sequentially, overwrites
each paper's NER output with the new-prompt result, and reports
old-vs-new distribution comparisons on completion.

Usage:
    docker compose run --rm ingestion python /app/scripts/rener_old_batch.py [--limit 0] [--offset 0] [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import Counter

from sqlalchemy import select, text, update

from ingestion.extract.material_ner import extract_materials
from ingestion.index.indexer import (
    _session_factory,
    chunks_table,
    dispose,
    papers_table,
)
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
    parser = argparse.ArgumentParser(description="Re-NER old-prompt papers (no tc_regime)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max papers (0=all)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N eligible papers")
    args = parser.parse_args()

    Session = _session_factory()

    async with Session() as db:
        rows = (await db.execute(text("""
            SELECT id, arxiv_id, title, abstract, authors,
                   date_submitted, categories,
                   jsonb_array_length(materials_extracted) AS old_record_count
            FROM papers
            WHERE jsonb_array_length(materials_extracted) > 0
              AND NOT EXISTS (
                  SELECT 1 FROM jsonb_array_elements(materials_extracted) AS r
                  WHERE r->>'tc_regime' IS NOT NULL
              )
            ORDER BY id
        """))).all()

    total_eligible = len(rows)
    log.info("Eligible old-NER papers: %d", total_eligible)

    if args.offset > 0:
        rows = rows[args.offset:]
        log.info("Offset by %d, remaining: %d", args.offset, len(rows))
    if args.limit > 0:
        rows = rows[:args.limit]
        log.info("Limited to %d", len(rows))

    if args.dry_run:
        for r in rows[:5]:
            log.info("[DRY] %s (old_records=%d) — %s", r.id, r.old_record_count, (r.title or "")[:80])
        log.info("[DRY] Would re-NER %d papers total", len(rows))
        await dispose()
        return

    total_ok = 0
    total_err = 0
    total_old_records = 0
    total_new_records = 0
    ev_old: Counter = Counter()
    ev_new: Counter = Counter()
    regime_new: Counter = Counter()

    for i, row in enumerate(rows):
        try:
            async with Session() as db:
                # Count old records
                old_mats_row = (await db.execute(
                    select(papers_table.c.materials_extracted)
                    .where(papers_table.c.id == row.id)
                )).scalar()
                old_mats = old_mats_row or []
                total_old_records += len(old_mats)
                for m in old_mats:
                    ev_old[m.get("evidence_type", "unset")] += 1

                parsed = await _rebuild_parsed(db, row)
                if parsed is None:
                    log.warning("%s: no chunks, skipping", row.id)
                    total_err += 1
                    continue

                new_mats = await asyncio.to_thread(extract_materials, parsed)

                await db.execute(
                    update(papers_table)
                    .where(papers_table.c.id == row.id)
                    .values(materials_extracted=new_mats)
                )
                await db.commit()

            total_ok += 1
            total_new_records += len(new_mats)
            for m in new_mats:
                ev_new[m.get("evidence_type", "unset")] += 1
                regime_new[m.get("tc_regime", "unset")] += 1

        except Exception as e:
            log.error("%s: NER failed: %s", row.id, e)
            total_err += 1

        if (i + 1) % 50 == 0:
            log.info(
                "Progress: %d/%d (ok=%d, err=%d, old_records=%d, new_records=%d)",
                i + 1, len(rows), total_ok, total_err, total_old_records, total_new_records,
            )

    await dispose()

    # Report
    log.info("=" * 70)
    log.info("OLD-NER RE-RUN REPORT (batch of %d papers)", len(rows))
    log.info("=" * 70)
    log.info("  Papers OK:      %d", total_ok)
    log.info("  Papers error:   %d", total_err)
    log.info("  Old records:    %d", total_old_records)
    log.info("  New records:    %d (delta %+d)", total_new_records, total_new_records - total_old_records)
    log.info("")

    log.info("evidence_type comparison:")
    log.info("  %-25s %8s %8s", "Type", "OLD", "NEW")
    log.info("  " + "-" * 45)
    all_ev = sorted(set(list(ev_old.keys()) + list(ev_new.keys())))
    for k in all_ev:
        log.info("  %-25s %8d %8d", k, ev_old.get(k, 0), ev_new.get(k, 0))
    log.info("")

    log.info("tc_regime distribution (NEW):")
    for k, v in sorted(regime_new.items(), key=lambda x: -x[1]):
        log.info("  %-25s %6d", k, v)


if __name__ == "__main__":
    asyncio.run(main())
