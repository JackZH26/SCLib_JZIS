#!/usr/bin/env python3
"""Backfill papers.affiliations + papers.paper_geo for existing papers.

Drives the affiliation_ner geo-NER flow over every paper that has no
paper_geo yet. Concurrent, resumable (a re-run only picks up papers
still missing paper_geo) and safe to interrupt at any time.

Reads GCS + Gemini; writes ONLY papers.affiliations / papers.paper_geo.
It never touches materials, chunks, or vector search.

Run on VPS2 (Postgres binds 127.0.0.1, so this runs inside the compose
network):

    cd /opt/SCLib_JZIS
    # 1. metered sub-batch first — measure throughput / cost:
    docker compose run --rm ingestion \\
        python /app/scripts/backfill_paper_geo.py --limit 500
    # 2. then the full run:
    docker compose run --rm ingestion \\
        python /app/scripts/backfill_paper_geo.py

Options:
    --limit N        process at most N papers (metered sub-batch)
    --concurrency N  parallel workers (default 12)
    --retry-failed   re-process papers whose paper_geo.status is
                     'error' or 'no_source', instead of the NULL ones
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from collections import Counter

from sqlalchemy import text

from ingestion.extract.affiliation_ner import extract_paper_geo
from ingestion.index.indexer import _session_factory, dispose, upsert_paper_geo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill_geo")


async def _select_papers(retry_failed: bool, limit: int | None) -> list[tuple[str, str]]:
    """Return (paper_id, arxiv_id) for the papers still needing geo."""
    if retry_failed:
        where = (
            "paper_geo IS NOT NULL "
            "AND paper_geo->>'status' IN ('error', 'no_source')"
        )
    else:
        where = "paper_geo IS NULL"
    sql = (
        f"SELECT id, arxiv_id FROM papers "
        f"WHERE source = 'arxiv' AND ({where}) "
        f"ORDER BY id"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    async with _session_factory()() as db:
        rows = (await db.execute(text(sql))).all()
    return [(r.id, r.arxiv_id or r.id.replace("arxiv:", "")) for r in rows]


async def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill paper author geography")
    ap.add_argument("--limit", type=int, default=0, help="max papers (0 = all)")
    ap.add_argument("--concurrency", type=int, default=12,
                    help="parallel workers (default 12)")
    ap.add_argument("--retry-failed", action="store_true",
                    help="re-process papers with paper_geo status error/no_source")
    args = ap.parse_args()

    papers = await _select_papers(args.retry_failed, args.limit or None)
    total = len(papers)
    log.info("Backfill: %d papers to process (concurrency=%d, retry_failed=%s)",
             total, args.concurrency, args.retry_failed)
    if total == 0:
        log.info("Nothing to do — every paper already has paper_geo.")
        await dispose()
        return

    sem = asyncio.Semaphore(args.concurrency)
    stats: Counter = Counter()
    done = 0
    t0 = time.time()

    async def _one(paper_id: str, arxiv_id: str) -> None:
        nonlocal done
        async with sem:
            try:
                # extract_paper_geo never raises; it reports failure via
                # paper_geo['status']. The try/except guards the DB write.
                geo = await asyncio.to_thread(extract_paper_geo, arxiv_id)
                await upsert_paper_geo(
                    paper_id, geo["affiliations"], geo["paper_geo"],
                )
                status = geo["paper_geo"].get("status", "error")
            except Exception as e:  # noqa: BLE001
                # DB write failed — leave paper_geo NULL so a later
                # re-run retries this paper.
                log.error("%s: backfill write failed: %s", paper_id, e)
                status = "crash"
        stats[status] += 1
        done += 1
        if done % 200 == 0 or done == total:
            el = time.time() - t0
            rate = done / el if el else 0.0
            eta = (total - done) / rate / 60 if rate else 0.0
            log.info("progress %d/%d  %.1f papers/s  ETA %.0f min  %s",
                     done, total, rate, eta, dict(sorted(stats.items())))

    await asyncio.gather(*[_one(pid, aid) for pid, aid in papers])
    await dispose()

    el = time.time() - t0
    ok = stats.get("ok", 0)
    log.info("=" * 64)
    log.info("BACKFILL DONE — %d papers in %.1f min (%.2f papers/s)",
             total, el / 60, total / el if el else 0.0)
    for k in sorted(stats):
        log.info("  %-16s %6d  (%.1f%%)", k, stats[k], 100 * stats[k] / total)
    log.info("  geography recovered (status=ok): %d / %d  (%.1f%%)",
             ok, total, 100 * ok / total if total else 0.0)
    log.info("=" * 64)


if __name__ == "__main__":
    asyncio.run(main())
