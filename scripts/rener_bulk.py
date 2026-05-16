#!/usr/bin/env python3
"""Bulk re-NER for papers that have no materials_extracted yet.

Selects papers with SC-relevant keywords in title/abstract, skips
papers flagged with "no_sc_keywords" in quality_flags. Processes
sequentially with a configurable concurrency limit.

Usage:
    docker compose run --rm ingestion python /app/scripts/rener_bulk.py [--limit 0] [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

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

SKIP_FLAG = "no_sc_keywords"


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
    parser = argparse.ArgumentParser(description="Bulk re-NER for papers missing NER output")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max papers (0=all)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N eligible papers")
    args = parser.parse_args()

    Session = _session_factory()

    async with Session() as db:
        rows = (await db.execute(text("""
            SELECT id, arxiv_id, title, abstract, authors,
                   date_submitted, categories
            FROM papers
            WHERE chunk_count > 0
              AND jsonb_array_length(materials_extracted) = 0
              AND title IS NOT NULL AND title != ''
              AND NOT quality_flags ? :skip_flag
            ORDER BY id
        """), {"skip_flag": SKIP_FLAG})).all()

    log.info("Eligible papers for NER: %d (skipping %s-flagged)", len(rows), SKIP_FLAG)

    if args.offset > 0:
        rows = rows[args.offset:]
        log.info("Offset by %d, remaining: %d", args.offset, len(rows))
    if args.limit > 0:
        rows = rows[:args.limit]
        log.info("Limited to %d", len(rows))

    if args.dry_run:
        for r in rows[:5]:
            log.info("[DRY] %s — %s", r.id, (r.title or "")[:80])
        log.info("[DRY] Would process %d papers total", len(rows))
        await dispose()
        return

    total_ok = 0
    total_err = 0
    total_records = 0

    for i, row in enumerate(rows):
        try:
            async with Session() as db:
                parsed = await _rebuild_parsed(db, row)
                if parsed is None:
                    log.warning("%s: no chunks, skipping", row.id)
                    total_err += 1
                    continue

                materials = await asyncio.to_thread(extract_materials, parsed)

                await db.execute(
                    update(papers_table)
                    .where(papers_table.c.id == row.id)
                    .values(materials_extracted=materials)
                )
                await db.commit()

            total_ok += 1
            total_records += len(materials)

        except Exception as e:
            log.error("%s: NER failed: %s", row.id, e)
            total_err += 1

        if (i + 1) % 50 == 0:
            log.info(
                "Progress: %d/%d (ok=%d, err=%d, records=%d)",
                i + 1, len(rows), total_ok, total_err, total_records,
            )

    await dispose()

    log.info("=" * 60)
    log.info("BULK RE-NER COMPLETE")
    log.info("=" * 60)
    log.info("  Papers OK:     %d", total_ok)
    log.info("  Papers error:  %d", total_err)
    log.info("  Total records: %d", total_records)
    log.info("  Total:         %d", len(rows))


if __name__ == "__main__":
    asyncio.run(main())
