#!/usr/bin/env python3
"""Enrich papers table with Semantic Scholar metadata.

Queries the Semantic Scholar Academic Graph API to backfill:
  - doi (from S2 externalIds)
  - citation_count (from S2 citationCount)
  - journal (from S2 journal.name)
  - paper_type (from S2 publicationTypes — mapped to our taxonomy)

Uses POST /paper/batch endpoint (up to 500 IDs per request).
Free tier rate limit for batch: ~1 req/2s, with occasional 429 requiring 60s backoff.
At 500 papers/batch × ~3s/batch, 40k papers → ~4 minutes plus cooldowns.

Usage:
    python scripts/enrich_papers_s2.py [--dry-run] [--batch-size 500] [--limit 0]

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
from typing import Any

import httpx
from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_FIELDS = "externalIds,citationCount,journal,publicationTypes"

# Map S2 publicationTypes → our paper_type taxonomy
_S2_TYPE_MAP: dict[str, str] = {
    "JournalArticle": "experimental",
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
    if not s2_types:
        return None
    if "Review" in s2_types:
        return "review"
    for t in s2_types:
        if t in _S2_TYPE_MAP:
            return _S2_TYPE_MAP[t]
    return None


def _do_batch_request(
    client: httpx.Client,
    s2_ids: list[str],
    max_retries: int = 3,
) -> list[dict[str, Any] | None]:
    """POST batch request with retry on 429."""
    for attempt in range(max_retries):
        try:
            resp = client.post(
                S2_BATCH_URL,
                params={"fields": S2_FIELDS},
                json={"ids": s2_ids},
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                wait = 30 * (attempt + 1)  # 30s, 60s, 90s
                log.warning("  429 rate limited, waiting %ds (attempt %d/%d)...",
                            wait, attempt + 1, max_retries)
                time.sleep(wait)
                continue
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            log.error("  HTTP %d: %s", e.response.status_code, e.response.text[:200])
            if attempt < max_retries - 1:
                time.sleep(10)
            continue
        except Exception as e:
            log.error("  Request error: %s", e)
            if attempt < max_retries - 1:
                time.sleep(10)
            continue

    return []  # all retries exhausted


def main():
    parser = argparse.ArgumentParser(description="Enrich papers from Semantic Scholar")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--limit", type=int, default=0, help="Max papers (0=all)")
    parser.add_argument("--delay", type=float, default=3.0,
                        help="Seconds between batch requests")
    parser.add_argument("--skip-enriched", action="store_true",
                        help="Skip papers that already have citation_count > 0")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        log.error("DATABASE_URL not set")
        sys.exit(1)

    sync_url = db_url.replace("+asyncpg", "").replace("+aiopg", "")
    engine = create_engine(sync_url)

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
    client = httpx.Client(timeout=30.0)

    total_enriched = 0
    total_not_found = 0
    total_errors = 0
    db_writes = 0
    t0 = time.time()

    total_batches = (len(papers) + args.batch_size - 1) // args.batch_size

    for batch_num, batch_start in enumerate(
        range(0, len(papers), args.batch_size), 1
    ):
        batch = papers[batch_start: batch_start + args.batch_size]
        s2_ids = [f"ArXiv:{arxiv_id}" for _, arxiv_id in batch]

        results = _do_batch_request(client, s2_ids)

        if not results:
            total_errors += len(batch)
            log.error("Batch %d/%d FAILED — %d papers lost",
                      batch_num, total_batches, len(batch))
            time.sleep(args.delay)
            continue

        # Process results (same order as input, null if not found)
        updates: list[dict[str, Any]] = []
        for i, result in enumerate(results):
            if i >= len(batch):
                break
            db_id = batch[i][0]
            if result is None:
                total_not_found += 1
                continue

            doi = None
            ext_ids = result.get("externalIds") or {}
            if ext_ids.get("DOI"):
                doi = ext_ids["DOI"]

            citation_count = result.get("citationCount") or 0
            journal_name = None
            j = result.get("journal")
            if j and isinstance(j, dict):
                journal_name = j.get("name")

            pub_types = result.get("publicationTypes")
            paper_type = _map_paper_type(pub_types)

            updates.append({
                "paper_id": db_id,
                "doi": doi,
                "citation_count": citation_count,
                "journal": journal_name,
                "paper_type": paper_type,
            })

        # Write batch to DB
        if updates and not args.dry_run:
            with engine.begin() as conn:
                for u in updates:
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
                        set_parts.append("paper_type = :pt")
                        params["pt"] = u["paper_type"]

                    if set_parts:
                        sql = f"UPDATE papers SET {', '.join(set_parts)} WHERE id = :pid"
                        conn.execute(text(sql), params)

            db_writes += len(updates)

        total_enriched += len(updates)

        elapsed = time.time() - t0
        done = total_enriched + total_not_found + total_errors
        rate = done / elapsed if elapsed > 0 else 0
        eta = (len(papers) - done) / rate if rate > 0 else 0

        if batch_num % 5 == 0 or batch_num == total_batches:
            log.info(
                "Batch %d/%d: enriched=%d, not_found=%d (%.0f/s, ETA %.1fm)",
                batch_num, total_batches, total_enriched, total_not_found,
                rate, eta / 60,
            )

        if args.dry_run and batch_num == 1:
            for u in updates[:3]:
                log.info("[DRY] %s → doi=%s, cites=%s, journal=%s, type=%s",
                         u["paper_id"], u.get("doi"), u.get("citation_count"),
                         u.get("journal"), u.get("paper_type"))

        time.sleep(args.delay)

    client.close()
    elapsed = time.time() - t0

    log.info("=== DONE (%.1f min) ===", elapsed / 60)
    log.info("  Enriched:  %d (%.1f%%)", total_enriched,
             100 * total_enriched / len(papers) if papers else 0)
    log.info("  Not found: %d (%.1f%%)", total_not_found,
             100 * total_not_found / len(papers) if papers else 0)
    log.info("  Errors:    %d", total_errors)
    log.info("  DB writes: %d", db_writes)
    log.info("  Total:     %d", len(papers))


if __name__ == "__main__":
    main()
