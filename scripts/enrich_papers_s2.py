#!/usr/bin/env python3
"""Enrich papers table with Semantic Scholar metadata.

Queries the Semantic Scholar Academic Graph API to backfill:
  - doi (from S2 externalIds)
  - citation_count (from S2 citationCount)
  - journal (from S2 journal.name)
  - paper_type (from S2 publicationTypes — mapped to our taxonomy)

Uses individual GET /paper/ArXiv:{id} requests with concurrent workers.
S2 free tier: ~10 requests/second for individual endpoints.

At 10 req/s, 40k papers take ~67 minutes. With --concurrency 5 and
polite delays, we target ~5 req/s → ~2.2 hours (safe margin).

Usage:
    python scripts/enrich_papers_s2.py [--dry-run] [--concurrency 5] [--limit 0]

    # Inside Docker:
    docker compose exec -T api python /app/scripts/enrich_papers_s2.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx
from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

S2_BASE = "https://api.semanticscholar.org/graph/v1/paper"
S2_FIELDS = "externalIds,citationCount,journal,publicationTypes"

# Map S2 publicationTypes → our paper_type taxonomy
_S2_TYPE_MAP: dict[str, str] = {
    "JournalArticle": "experimental",   # default for journal articles
    "Conference": "experimental",
    "Review": "review",
    "CaseReport": "experimental",
    "ClinicalTrial": "experimental",
    "Editorial": "review",
    "LettersAndComments": "experimental",
    "MetaAnalysis": "review",
    "Study": "experimental",
    "Book": "review",
    "BookSection": "review",
    "Dataset": "computational",
}


def _map_paper_type(s2_types: list[str] | None) -> str | None:
    """Map S2 publicationTypes list to a single paper_type string."""
    if not s2_types:
        return None
    if "Review" in s2_types:
        return "review"
    for t in s2_types:
        if t in _S2_TYPE_MAP:
            return _S2_TYPE_MAP[t]
    return None


def _fetch_one(
    client: httpx.Client,
    arxiv_id: str,
    db_id: str,
) -> dict[str, Any] | None:
    """Fetch a single paper from S2. Returns update dict or None."""
    url = f"{S2_BASE}/ArXiv:{arxiv_id}"
    try:
        resp = client.get(url, params={"fields": S2_FIELDS})
        if resp.status_code == 404:
            return None  # not in S2
        if resp.status_code == 429:
            # Rate limited — back off and retry once
            time.sleep(5)
            resp = client.get(url, params={"fields": S2_FIELDS})
            if resp.status_code != 200:
                return None
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    doi = None
    ext_ids = data.get("externalIds") or {}
    if ext_ids.get("DOI"):
        doi = ext_ids["DOI"]

    citation_count = data.get("citationCount") or 0
    journal_name = None
    j = data.get("journal")
    if j and isinstance(j, dict):
        journal_name = j.get("name")

    pub_types = data.get("publicationTypes")
    paper_type = _map_paper_type(pub_types)

    return {
        "paper_id": db_id,
        "doi": doi,
        "citation_count": citation_count,
        "journal": journal_name,
        "paper_type": paper_type,
    }


def main():
    parser = argparse.ArgumentParser(description="Enrich papers from Semantic Scholar")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be done, don't write DB")
    parser.add_argument("--concurrency", type=int, default=3,
                        help="Concurrent requests (default 3, max 8)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max papers to process (0=all)")
    parser.add_argument("--delay", type=float, default=0.25,
                        help="Delay between requests per thread (seconds)")
    parser.add_argument("--skip-enriched", action="store_true",
                        help="Skip papers that already have citation_count > 0")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        log.error("DATABASE_URL not set")
        sys.exit(1)

    sync_url = db_url.replace("+asyncpg", "").replace("+aiopg", "")
    engine = create_engine(sync_url)

    # Load papers needing enrichment
    skip_clause = "AND citation_count = 0" if args.skip_enriched else ""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, arxiv_id FROM papers
            WHERE arxiv_id IS NOT NULL AND arxiv_id != ''
            {skip_clause}
            ORDER BY id
        """)).fetchall()

    log.info("Total papers to enrich: %d", len(rows))
    if args.limit > 0:
        rows = rows[:args.limit]
        log.info("Limited to %d papers", len(rows))

    papers = [(r[0], r[1]) for r in rows]
    concurrency = min(args.concurrency, 8)

    client = httpx.Client(timeout=20.0)

    total_enriched = 0
    total_not_found = 0
    total_errors = 0
    db_writes = 0
    t0 = time.time()

    # Process with thread pool for concurrent requests
    write_buffer: list[dict[str, Any]] = []
    FLUSH_SIZE = 500

    def _process_paper(idx_db_arxiv):
        idx, db_id, arxiv_id = idx_db_arxiv
        time.sleep(args.delay)  # per-thread delay
        return idx, _fetch_one(client, arxiv_id, db_id)

    def _flush_writes():
        nonlocal db_writes
        if not write_buffer:
            return
        with engine.begin() as conn:
            for u in write_buffer:
                set_parts = []
                params: dict[str, Any] = {"pid": u["paper_id"]}

                if u.get("doi"):
                    set_parts.append("doi = COALESCE(NULLIF(doi, ''), :doi)")
                    params["doi"] = u["doi"]

                if u.get("citation_count", 0) > 0:
                    set_parts.append("citation_count = :cc")
                    params["cc"] = u["citation_count"]

                if u.get("journal"):
                    set_parts.append("journal = COALESCE(journal, :journal)")
                    params["journal"] = u["journal"]

                if u.get("paper_type"):
                    # S2 paper_type overwrites NER-inferred type
                    set_parts.append("paper_type = :pt")
                    params["pt"] = u["paper_type"]

                if set_parts:
                    sql = f"UPDATE papers SET {', '.join(set_parts)} WHERE id = :pid"
                    conn.execute(text(sql), params)

        db_writes += len(write_buffer)
        write_buffer.clear()

    work = [(i, db_id, arxiv_id) for i, (db_id, arxiv_id) in enumerate(papers)]

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_process_paper, w): w for w in work}

        for future in as_completed(futures):
            idx, result = future.result()
            if result is None:
                total_not_found += 1
            else:
                total_enriched += 1
                if not args.dry_run:
                    write_buffer.append(result)
                elif total_enriched <= 5:
                    log.info("[DRY] %s → doi=%s, cites=%s, journal=%s, type=%s",
                             result["paper_id"], result.get("doi"),
                             result.get("citation_count"),
                             result.get("journal"), result.get("paper_type"))

            done = total_enriched + total_not_found + total_errors
            if done % 500 == 0 or done == len(papers):
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(papers) - done) / rate if rate > 0 else 0
                log.info(
                    "Progress: %d/%d (%.0f/s, ETA %.0fm) — enriched=%d, "
                    "not_found=%d, errors=%d",
                    done, len(papers), rate, eta / 60,
                    total_enriched, total_not_found, total_errors,
                )

            if len(write_buffer) >= FLUSH_SIZE:
                _flush_writes()

    # Final flush
    if not args.dry_run:
        _flush_writes()

    client.close()
    elapsed = time.time() - t0

    log.info("=== DONE (%.1f min) ===", elapsed / 60)
    log.info("  Enriched:  %d", total_enriched)
    log.info("  Not found: %d", total_not_found)
    log.info("  Errors:    %d", total_errors)
    log.info("  DB writes: %d", db_writes)
    log.info("  Total:     %d", len(papers))


if __name__ == "__main__":
    main()
