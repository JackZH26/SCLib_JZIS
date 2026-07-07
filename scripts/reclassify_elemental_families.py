#!/usr/bin/env python3
"""Reclassify standalone elemental superconductors in ``materials``.

The family classifier already has an ``elemental`` bucket, but older
migrations and occasional NER family votes can leave pure elements such
as Hg, Pb, Sn, Nb, or In under ``conventional`` or NULL. This script is
safe to run after deploying classifier changes:

    python /app/scripts/reclassify_elemental_families.py          # dry run
    python /app/scripts/reclassify_elemental_families.py --apply  # update DB
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))

from ingestion.nims import classify_family  # noqa: E402

log = logging.getLogger("sclib.reclassify_elemental")


def _async_db_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def main(*, apply: bool) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    db_url = _async_db_url(
        os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://sclib:sclib@localhost:5432/sclib",
        )
    )
    engine = create_async_engine(db_url)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, formula, family, is_unconventional, tc_max, total_papers "
                    "FROM materials ORDER BY formula"
                )
            )
        ).mappings().all()

        candidates = [
            row for row in rows
            if classify_family(row["formula"]) == "elemental"
            and row["family"] != "elemental"
        ]

        action = "Updating" if apply else "Would update"
        log.info("%s %d elemental material rows", action, len(candidates))
        for row in candidates[:50]:
            log.info(
                "  %-40s %-16s -> elemental  tc=%s papers=%s id=%s",
                row["formula"],
                row["family"] or "(null)",
                row["tc_max"],
                row["total_papers"],
                row["id"],
            )
        if len(candidates) > 50:
            log.info("  ... %d more", len(candidates) - 50)

        if apply and candidates:
            update_stmt = text(
                "UPDATE materials "
                "SET family = 'elemental', is_unconventional = FALSE "
                "WHERE id = :id"
            )
            for row in candidates:
                await session.execute(update_stmt, {"id": row["id"]})
            await session.commit()
            log.info("Updated %d rows", len(candidates))

        remaining = (
            await session.execute(
                text("SELECT count(*) FROM materials WHERE family = 'elemental'")
            )
        ).scalar_one()
        log.info("Current elemental family rows: %d", remaining)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write updates to Postgres")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main(apply=args.apply))
