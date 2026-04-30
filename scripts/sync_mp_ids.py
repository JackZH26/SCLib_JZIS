#!/usr/bin/env python3
"""Sync ``materials.mp_id`` against the Materials Project API.

Phase B of the SCLib × MP integration. For every row in ``materials``,
ask MP whether it has an entry with the same formula; if yes, store
the lowest-energy_above_hull match as ``mp_id`` and the full sorted
list as ``mp_alternate_ids``. Stamp ``mp_synced_at`` either way so
the next run can skip rows we recently checked.

Usage::

    # one-off backfill on VPS2 (runs inside the api container so it
    # picks up DATABASE_URL and MP_API_KEY from the existing .env):
    docker compose exec -T api python /app/scripts/sync_mp_ids.py

    # smoke test on a small sample:
    docker compose exec -T api python /app/scripts/sync_mp_ids.py --limit 50

    # re-sync stale rows (default cutoff: 30 days):
    docker compose exec -T api python /app/scripts/sync_mp_ids.py --max-age-days 30

Throttling: MP allows 5 req/s on the free tier. We sleep
``--throttle-sec`` (default 0.25 = 4 req/s) between requests so we
stay safely under the limit. Roughly 11k materials at 4 req/s →
~45 minutes for a full backfill.

Idempotency: rerun is safe. ``mp_synced_at`` filters out rows touched
within ``max_age_days``. Pass ``--force`` to ignore that filter.

Failure handling: per-formula errors (404, transient 5xx, network)
are logged and the row is skipped — we still stamp ``mp_synced_at``
so we don't retry on every run, but we leave ``mp_id`` NULL so a
later forced re-sync can fill it. Hard failures (bad credentials,
bad DB) abort the script.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running this script outside the container too:
#   `python scripts/sync_mp_ids.py`
ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "api"
if API_DIR.is_dir() and str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import httpx  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

from models import get_session_factory  # noqa: E402
from models.db import Material  # noqa: E402
from services.materials_project import MaterialsProjectClient, best_match  # noqa: E402


log = logging.getLogger("sync_mp_ids")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument(
        "--limit", type=int, default=None,
        help="Only process the first N materials (smoke test). Default: all.",
    )
    p.add_argument(
        "--max-age-days", type=int, default=30,
        help="Skip rows whose mp_synced_at is newer than this many days "
             "(default: 30). Use --force to override entirely.",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Re-sync every row, regardless of mp_synced_at.",
    )
    p.add_argument(
        "--throttle-sec", type=float, default=0.25,
        help="Sleep this long between MP requests (default: 0.25 = 4 req/s, "
             "safely under MP's 5 req/s free-tier cap).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Query MP and print matches but do not write to the DB.",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Log each matched row (default: only summary every 100).",
    )
    return p.parse_args()


async def _candidate_materials(
    Session,
    *,
    limit: int | None,
    max_age_days: int,
    force: bool,
) -> list[tuple[str, str]]:
    """Pick the (id, formula) rows we'll send to MP.

    Returns ID + formula tuples — we don't load full Material rows
    because the loop below only reads ``formula`` and writes a few
    fields back via ``UPDATE``. Pulling everything would balloon the
    transaction footprint for no gain.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    stmt = select(Material.id, Material.formula).order_by(Material.id)
    if not force:
        stmt = stmt.where(
            (Material.mp_synced_at.is_(None)) | (Material.mp_synced_at < cutoff)
        )
    if limit is not None:
        stmt = stmt.limit(limit)
    async with Session() as db:
        return list((await db.execute(stmt)).all())


async def _process_one(
    mp: MaterialsProjectClient,
    Session,
    material_id: str,
    formula: str,
    *,
    dry_run: bool,
    verbose: bool,
) -> tuple[bool, str | None]:
    """Sync one material. Returns (matched, primary_mp_id).

    Skip-on-error: per-formula HTTP errors are logged, the row is
    stamped (mp_synced_at) with mp_id=NULL, and we move on. Hard
    auth (401/403) errors raise — the run aborts cleanly.
    """
    try:
        rows = await mp.search_by_formula(formula)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            raise  # bad credentials → abort
        log.warning(
            "MP HTTP %s for %s (%s); stamping with no match",
            e.response.status_code, material_id, formula,
        )
        rows = []
    except httpx.RequestError as e:
        log.warning(
            "MP transport error for %s (%s): %s; stamping with no match",
            material_id, formula, e,
        )
        rows = []

    primary, alternates = best_match(rows)
    if verbose and primary:
        log.info(
            "  %-40s -> %s  (%d alternate%s)",
            f"{material_id} ({formula})",
            primary,
            len(alternates),
            "" if len(alternates) == 1 else "s",
        )

    if dry_run:
        return primary is not None, primary

    async with Session() as db:
        await db.execute(
            update(Material)
            .where(Material.id == material_id)
            .values(
                mp_id=primary,
                mp_alternate_ids=alternates,
                mp_synced_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    return primary is not None, primary


async def _main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s  %(message)s",
        datefmt="%H:%M:%S",
    )

    api_key = os.environ.get("MP_API_KEY", "").strip()
    if not api_key:
        log.error(
            "MP_API_KEY is not set. Add it to .env (see .env.example) and "
            "either restart the api container or `docker compose exec` with "
            "-e MP_API_KEY=...",
        )
        return 2

    Session = get_session_factory()
    targets = await _candidate_materials(
        Session,
        limit=args.limit,
        max_age_days=args.max_age_days,
        force=args.force,
    )
    if not targets:
        log.info("No materials need syncing (everything is fresh — pass --force to override)")
        return 0

    log.info(
        "syncing %d material%s against Materials Project (throttle=%.2fs)%s",
        len(targets),
        "" if len(targets) == 1 else "s",
        args.throttle_sec,
        " [DRY RUN]" if args.dry_run else "",
    )

    matched = 0
    async with MaterialsProjectClient(api_key) as mp:
        for i, (mid, formula) in enumerate(targets, start=1):
            ok, _primary = await _process_one(
                mp, Session, mid, formula,
                dry_run=args.dry_run, verbose=args.verbose,
            )
            if ok:
                matched += 1
            if i % 100 == 0 or i == len(targets):
                log.info(
                    "progress: %d/%d processed, %d matched (%.1f%%)",
                    i, len(targets), matched, 100.0 * matched / i,
                )
            if i < len(targets):
                await asyncio.sleep(args.throttle_sec)

    log.info(
        "done: %d/%d materials matched an MP entry%s",
        matched,
        len(targets),
        " (dry run — no DB writes)" if args.dry_run else "",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
