"""Owned disposable-process fixture; never an application/production runner."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# The child must cross the same pre-connect guard as pytest itself. Do not
# move any application, settings or database import above this validation.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from test_safety import validate_test_environment, verify_postgres_identity  # noqa: E402

CAPABILITY = validate_test_environment()

sys.path.insert(0, str(ROOT / "api"))
from config import Settings, get_settings  # noqa: E402

Settings.model_config = {**Settings.model_config, "env_file": None}
get_settings.cache_clear()

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from models.db import AuditReport, _to_async_dsn  # noqa: E402
from services.background_jobs import run_background_cycle  # noqa: E402


def emit(value):
    print(json.dumps(value, sort_keys=True, default=str), flush=True)


async def work(args):
    engine = create_async_engine(_to_async_dsn(CAPABILITY.database_url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(verify_postgres_identity, CAPABILITY)

        async def effect(session, scheduled_for, cycle_id):
            await session.execute(sa.insert(AuditReport).values(
                started_at=scheduled_for, completed_at=sa.func.clock_timestamp(),
                rule_name=args.rule_name, severity="info", rows_flagged=1,
                sample_ids=[str(cycle_id)], suggested_fixes=[{"synthetic": True}],
            ))
            emit({"event": "effect_ready", "process_id": os.getpid(), "cycle_id": str(cycle_id)})
            if args.mode == "hold":
                # Parent uses a pipe barrier, not a timing guess, then either
                # releases or kills only this child while its SQL is pending.
                signal = await asyncio.wait_for(asyncio.to_thread(sys.stdin.readline), timeout=30)
                if signal != "continue\n":
                    raise RuntimeError("Synthetic process barrier was not released")
            return {"audit_reports_created": 1, "synthetic": True}

        result = await run_background_cycle(
            "nightly_audit", interval_seconds=1, handler=effect,
            config={"synthetic_process_fixture": args.rule_name}, engine=engine,
            scheduled_for=datetime.fromisoformat(args.scheduled_for),
        )
        emit({"event": "result", "process_id": os.getpid(), "result": result})
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rule-name", required=True)
    parser.add_argument("--scheduled-for", required=True)
    parser.add_argument("--mode", choices=("commit", "hold"), default="commit")
    args = parser.parse_args()
    if not args.rule_name.startswith("en03-process-") or len(args.rule_name) != 45:
        parser.error("Only synthetic process fixture identifiers are accepted")
    try:
        asyncio.run(work(args))
        return 0
    except Exception as exc:
        # Do not echo URLs, SQL values or configuration when a child fails.
        emit({"event": "worker_error", "error_type": type(exc).__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
