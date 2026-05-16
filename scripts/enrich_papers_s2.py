#!/usr/bin/env python3
"""Enrich papers table with Semantic Scholar metadata.

Batch-queries the Semantic Scholar Academic Graph API to backfill:
  - doi (from S2 externalIds)
  - citation_count (from S2 citationCount)
  - journal (from S2 journal.name)
  - paper_type (from S2 publicationTypes — mapped to our taxonomy)

Uses the /paper/batch endpoint (POST, up to 500 IDs per request) for efficiency.
S2 API: https://api.semanticscholar.org/api-docs/graph#tag/Paper-Data

Rate limits (no API key): 1 request/second for batch endpoint.
With API key: 10 requests/second. We default to 1/s for safety.

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
S2_BATCH_SIZE = 500  # max per API call
S2_DELAY = 1.1  # seconds between requests (polite, no API key)

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
    # If "Review" is present anywhere, it's a review
    if "Review" in s2_types:
        return "review"
    # Otherwise take the first recognized type
    for t in s2_types:
        if t in _S2_TYPE_MAP:
            return _S2_TYPE_MAP[t]
    return None


def main():
    parser = argparse.ArgumentParser(description="Enrich papers from Semantic Scholar")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done, don't write DB")
    parser.add_argument("--batch-size", type=int, default=S2_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=0, help="Max papers to process (0=all)")
    parser.add_argument("--s2-key", type=str, default=os.environ.get("S2_API_KEY", ""),
                        help="Semantic Scholar API key (optional, increases rate limit)")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        log.error("DATABASE_URL not set")
        sys.exit(1)

    # Ensure sync driver
    sync_url = db_url.replace("+asyncpg", "").replace("+aiopg", "")
    engine = create_engine(sync_url)

    # Load all arxiv_ids that need enrichment
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, arxiv_id FROM papers
            WHERE arxiv_id IS NOT NULL AND arxiv_id != ''
            ORDER BY id
        """)).fetchall()

    log.info("Total papers with arxiv_id: %d", len(rows))
    if args.limit > 0:
        rows = rows[:args.limit]
        log.info("Limited to %d papers", len(rows))

    # Build (paper_db_id, arxiv_id) pairs
    papers = [(r[0], r[1]) for r in rows]

    # Process in batches
    headers: dict[str, str] = {}
    if args.s2_key:
        headers["x-api-key"] = args.s2_key
        log.info("Using S2 API key (higher rate limit)")

    total_enriched = 0
    total_not_found = 0
    total_errors = 0

    client = httpx.Client(timeout=30.0, headers=headers)

    for batch_start in range(0, len(papers), args.batch_size):
        batch = papers[batch_start: batch_start + args.batch_size]
        # S2 accepts ArXiv IDs as "ArXiv:{id}" or "ARXIV:{id}"
        s2_ids = [f"ArXiv:{arxiv_id}" for _, arxiv_id in batch]
        id_to_dbid = {f"ArXiv:{arxiv_id}": db_id for db_id, arxiv_id in batch}

        try:
            resp = client.post(
                S2_BATCH_URL,
                params={"fields": S2_FIELDS},
                json={"ids": s2_ids},
            )
            resp.raise_for_status()
            results: list[dict[str, Any] | None] = resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                log.warning("Rate limited at batch %d, sleeping 60s...",
                            batch_start // args.batch_size)
                time.sleep(60)
                # Retry once
                try:
                    resp = client.post(
                        S2_BATCH_URL,
                        params={"fields": S2_FIELDS},
                        json={"ids": s2_ids},
                    )
                    resp.raise_for_status()
                    results = resp.json()
                except Exception:
                    log.error("Retry failed at batch %d, skipping", batch_start // args.batch_size)
                    total_errors += len(batch)
                    continue
            else:
                log.error("HTTP %d at batch %d: %s", e.response.status_code,
                          batch_start // args.batch_size, e.response.text[:200])
                total_errors += len(batch)
                time.sleep(S2_DELAY)
                continue
        except Exception as e:
            log.error("Request error at batch %d: %s", batch_start // args.batch_size, e)
            total_errors += len(batch)
            time.sleep(S2_DELAY)
            continue

        # Process results (one per ID, in same order, null if not found)
        updates: list[dict[str, Any]] = []
        for i, result in enumerate(results):
            db_id = batch[i][0]
            if result is None:
                total_not_found += 1
                continue

            doi = None
            ext_ids = result.get("externalIds") or {}
            if ext_ids.get("DOI"):
                doi = ext_ids["DOI"]

            citation_count = result.get("citationCount")
            journal_name = None
            j = result.get("journal")
            if j and isinstance(j, dict):
                journal_name = j.get("name")

            pub_types = result.get("publicationTypes")
            paper_type = _map_paper_type(pub_types)

            updates.append({
                "paper_id": db_id,
                "doi": doi,
                "citation_count": citation_count or 0,
                "journal": journal_name,
                "paper_type": paper_type,
            })

        # Write batch to DB
        if updates and not args.dry_run:
            with engine.begin() as conn:
                for u in updates:
                    set_parts = []
                    params: dict[str, Any] = {"pid": u["paper_id"]}

                    # Only update doi if currently empty and S2 has one
                    if u["doi"]:
                        set_parts.append("doi = COALESCE(NULLIF(doi, ''), :doi)")
                        params["doi"] = u["doi"]

                    if u["citation_count"] > 0:
                        set_parts.append("citation_count = :citation_count")
                        params["citation_count"] = u["citation_count"]

                    if u["journal"]:
                        set_parts.append("journal = COALESCE(journal, :journal)")
                        params["journal"] = u["journal"]

                    if u["paper_type"]:
                        set_parts.append("paper_type = COALESCE(paper_type, :paper_type)")
                        params["paper_type"] = u["paper_type"]

                    if set_parts:
                        sql = f"UPDATE papers SET {', '.join(set_parts)} WHERE id = :pid"
                        conn.execute(text(sql), params)

            total_enriched += len(updates)
        elif updates and args.dry_run:
            total_enriched += len(updates)
            # Show a sample
            if batch_start == 0:
                for u in updates[:3]:
                    log.info("[DRY RUN] %s → doi=%s, citations=%s, journal=%s, type=%s",
                             u["paper_id"], u["doi"], u["citation_count"],
                             u["journal"], u["paper_type"])

        batch_num = batch_start // args.batch_size + 1
        total_batches = (len(papers) + args.batch_size - 1) // args.batch_size
        log.info("Batch %d/%d: %d enriched, %d not found",
                 batch_num, total_batches, len(updates),
                 len(batch) - len(updates))

        # Rate limiting
        time.sleep(S2_DELAY)

    client.close()

    log.info("=== DONE ===")
    log.info("  Enriched:  %d", total_enriched)
    log.info("  Not found: %d", total_not_found)
    log.info("  Errors:    %d", total_errors)
    log.info("  Total:     %d", len(papers))


if __name__ == "__main__":
    main()
