#!/usr/bin/env python3
"""Backfill paper_type from existing NER extraction records.

Each NER record has a 'paper_type' field (experimental/theoretical/computational).
This script reads materials_extracted JSONB, takes the majority vote, and writes
paper_type to the new DB column. Run BEFORE S2 enrichment so S2 paper_type
only fills gaps (COALESCE logic).

Usage:
    docker compose exec -T api python /app/scripts/backfill_paper_type.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import Counter

from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main():
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        log.error("DATABASE_URL not set")
        sys.exit(1)

    sync_url = db_url.replace("+asyncpg", "").replace("+aiopg", "")
    engine = create_engine(sync_url)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, materials_extracted
            FROM papers
            WHERE materials_extracted::text != '[]'
              AND paper_type IS NULL
        """)).fetchall()

    log.info("Papers to backfill: %d", len(rows))

    updates: list[tuple[str, str]] = []  # (paper_type, paper_id)
    type_dist: Counter = Counter()

    for row in rows:
        paper_id = row[0]
        records = row[1] if isinstance(row[1], list) else json.loads(row[1])

        # Majority vote from NER records
        vote: Counter = Counter()
        for r in records:
            pt = r.get("paper_type")
            if pt:
                vote[pt] += 1

        if vote:
            winner = vote.most_common(1)[0][0]
            updates.append((winner, paper_id))
            type_dist[winner] += 1

    log.info("Paper type distribution from NER:")
    for t, c in type_dist.most_common():
        log.info("  %s: %d", t, c)

    # Write
    log.info("Writing %d updates...", len(updates))
    with engine.begin() as conn:
        batch_size = 5000
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            for pt, pid in batch:
                conn.execute(
                    text("UPDATE papers SET paper_type = :pt WHERE id = :pid"),
                    {"pt": pt, "pid": pid},
                )
            log.info("  Written %d/%d", min(i + batch_size, len(updates)), len(updates))

    log.info("Done.")


if __name__ == "__main__":
    main()
