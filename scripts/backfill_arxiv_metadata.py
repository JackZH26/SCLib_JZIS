#!/usr/bin/env python3
"""Backfill title + abstract from arXiv API for papers with missing metadata.

Finds papers where title/abstract is NULL/empty but chunks exist,
fetches metadata via the arXiv Atom API (batch of 50 IDs per request),
and updates the papers table.

Usage:
    docker compose run --rm ingestion python /app/scripts/backfill_arxiv_metadata.py [--limit 0] [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET

import httpx
from sqlalchemy import text

from ingestion.index.indexer import _session_factory, dispose

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ARXIV_API = "http://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
BATCH_SIZE = 50


def _clean_text(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def _fetch_batch(client: httpx.Client, arxiv_ids: list[str]) -> dict[str, dict]:
    """Fetch metadata for a batch of arXiv IDs. Returns {arxiv_id: {title, abstract, authors}}."""
    id_list = ",".join(arxiv_ids)
    results: dict[str, dict] = {}

    for attempt in range(3):
        try:
            resp = client.get(
                ARXIV_API,
                params={
                    "id_list": id_list,
                    "max_results": str(len(arxiv_ids)),
                },
            )
            if resp.status_code == 200:
                break
            if resp.status_code == 429:
                wait = 30 * (attempt + 1)
                log.warning("429 rate limited, waiting %ds...", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
        except Exception as e:
            log.error("Request error: %s", e)
            if attempt < 2:
                time.sleep(10)
            continue
    else:
        return results

    root = ET.fromstring(resp.text)
    for entry in root.findall(f"{ATOM_NS}entry"):
        id_el = entry.find(f"{ATOM_NS}id")
        if id_el is None or id_el.text is None:
            continue
        raw_id = id_el.text.strip().split("/abs/")[-1]
        arxiv_id = re.sub(r"v\d+$", "", raw_id)

        title_el = entry.find(f"{ATOM_NS}title")
        abstract_el = entry.find(f"{ATOM_NS}summary")
        authors = [
            a.find(f"{ATOM_NS}name").text
            for a in entry.findall(f"{ATOM_NS}author")
            if a.find(f"{ATOM_NS}name") is not None and a.find(f"{ATOM_NS}name").text
        ]

        title = _clean_text(title_el.text if title_el is not None else None)
        abstract = _clean_text(abstract_el.text if abstract_el is not None else None)

        if title and title != "Error":
            results[arxiv_id] = {
                "title": title,
                "abstract": abstract,
                "authors": authors,
            }

    return results


async def main():
    parser = argparse.ArgumentParser(description="Backfill arXiv metadata")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max papers (0=all)")
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()

    Session = _session_factory()

    async with Session() as db:
        rows = (await db.execute(text("""
            SELECT id, arxiv_id FROM papers
            WHERE (title IS NULL OR title = '')
              AND (abstract IS NULL OR abstract = '')
              AND arxiv_id IS NOT NULL AND arxiv_id != ''
              AND chunk_count > 0
            ORDER BY id
        """))).all()

    log.info("Papers with missing metadata: %d", len(rows))
    if args.limit > 0:
        rows = rows[: args.limit]
        log.info("Limited to %d", len(rows))

    papers = [(r[0], r[1]) for r in rows]
    client = httpx.Client(timeout=30.0)

    total_updated = 0
    total_not_found = 0
    total_batches = (len(papers) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num, batch_start in enumerate(range(0, len(papers), BATCH_SIZE), 1):
        batch = papers[batch_start : batch_start + BATCH_SIZE]
        arxiv_ids = [aid for _, aid in batch]
        id_map = {aid: pid for pid, aid in batch}

        results = await asyncio.to_thread(_fetch_batch, client, arxiv_ids)

        updates = []
        for aid, meta in results.items():
            pid = id_map.get(aid)
            if pid and meta.get("title"):
                updates.append(
                    {
                        "paper_id": pid,
                        "title": meta["title"],
                        "abstract": meta.get("abstract", ""),
                        "authors": meta.get("authors", []),
                    }
                )

        not_found = len(batch) - len(updates)
        total_not_found += not_found

        if updates and not args.dry_run:
            async with Session() as db:
                for u in updates:
                    await db.execute(
                        text("""
                        UPDATE papers
                        SET title = :title,
                            abstract = :abstract,
                            authors = :authors
                        WHERE id = :pid
                          AND (title IS NULL OR title = '')
                    """),
                        {
                            "pid": u["paper_id"],
                            "title": u["title"],
                            "abstract": u["abstract"],
                            "authors": u["authors"],
                        },
                    )
                await db.commit()
            total_updated += len(updates)

        if args.dry_run and batch_num == 1:
            for u in updates[:3]:
                log.info("[DRY] %s → title=%s", u["paper_id"], u["title"][:80])

        if batch_num % 10 == 0 or batch_num == total_batches:
            log.info(
                "Batch %d/%d: updated=%d, not_found=%d",
                batch_num,
                total_batches,
                total_updated,
                total_not_found,
            )

        await asyncio.sleep(args.delay)

    client.close()
    await dispose()

    log.info("=== DONE ===")
    log.info("  Updated:   %d", total_updated)
    log.info("  Not found: %d", total_not_found)
    log.info("  Total:     %d", len(papers))


if __name__ == "__main__":
    asyncio.run(main())
