#!/usr/bin/env python3
"""Re-run classify_family() on all NULL-family materials in Postgres.

Usage (inside ingestion container):
    python -m scripts.reclassify_families [--dry-run]

Or from docker compose:
    docker compose exec ingestion python /app/scripts/reclassify_families.py
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure the ingestion package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))

from ingestion.nims import classify_family, infer_unconventional

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def main(dry_run: bool = False) -> None:
    # Late import — only needed at runtime
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    import os

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://sclib:sclib@localhost:5432/sclib",
    )
    engine = create_async_engine(db_url)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Fetch all clean materials with NULL family
        result = await session.execute(text(
            "SELECT id, formula FROM materials "
            "WHERE family IS NULL AND needs_review = FALSE"
        ))
        rows = result.fetchall()
        log.info("Found %d materials with NULL family", len(rows))

        classified = 0
        by_family: dict[str, int] = {}
        for row in rows:
            family = classify_family(row[1])  # row[1] = formula
            if family is None:
                continue
            unconv = infer_unconventional(family)
            by_family[family] = by_family.get(family, 0) + 1

            if not dry_run:
                await session.execute(
                    text(
                        "UPDATE materials "
                        "SET family = :f, "
                        "    is_unconventional = COALESCE(is_unconventional, :u) "
                        "WHERE id = :id"
                    ),
                    {"f": family, "u": unconv, "id": row[0]},
                )
            classified += 1

        if not dry_run:
            await session.commit()

        log.info(
            "%s %d/%d materials",
            "Would classify" if dry_run else "Classified",
            classified,
            len(rows),
        )
        for fam, n in sorted(by_family.items(), key=lambda x: -x[1]):
            log.info("  %-18s %d", fam, n)

        # Report remaining NULL
        remaining = len(rows) - classified
        log.info("Remaining NULL-family: %d", remaining)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
