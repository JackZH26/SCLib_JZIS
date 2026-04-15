#!/usr/bin/env python3
"""Recompute the dashboard stats cache row.

Intended for the Phase 5 nightly cron but also handy as a manual
one-liner after a bulk ingest:

    docker compose exec api python /app/scripts/refresh_stats.py

The script shells out through SQLAlchemy directly — it reuses the same
``refresh_dashboard_cache`` service the POST /stats/refresh endpoint
wraps, so the written row is byte-identical either way.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running this script from anywhere: `python scripts/refresh_stats.py`
# or `docker compose exec api python /app/scripts/refresh_stats.py`.
ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "api"
if API_DIR.is_dir() and str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from models import get_session_factory  # noqa: E402
from services.stats_refresh import refresh_dashboard_cache  # noqa: E402


async def _main() -> int:
    Session = get_session_factory()
    async with Session() as db:
        payload = await refresh_dashboard_cache(db)
    print(
        "stats_cache[dashboard] refreshed:",
        f"{payload['total_papers']} papers /",
        f"{payload['total_materials']} materials /",
        f"{payload['total_chunks']} chunks",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
