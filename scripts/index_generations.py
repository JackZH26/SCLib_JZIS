#!/usr/bin/env python3
"""Private index-generation operator. Default: preview only, no provider calls.

See docs/INDEX_GENERATIONS.md before use. The CLI never creates indexes, grants
source rights, deletes vectors, activates on publication, or exports snapshots.
An explicitly selected DATABASE_URL is required; no implicit .env target.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

MAX_INPUT_BYTES = 16 * 1024 * 1024


def _uuid(value):
    try:
        canonical = str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise argparse.ArgumentTypeError("A canonical UUID is required") from None
    if canonical != value:
        raise argparse.ArgumentTypeError("A canonical UUID is required")
    return value


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage", help="Retain exact current SQL evidence/receipt members")
    stage.add_argument("--input", type=Path, required=True, help="Private JSON with generation_id, logical_index, resource, items")
    stage.add_argument("--apply", action="store_true")
    for name in ("inspect", "publish", "observe", "activate"):
        command = commands.add_parser(name)
        command.add_argument("--generation-id", required=True, type=_uuid)
        if name != "inspect":
            command.add_argument("--apply", action="store_true")
        if name == "observe":
            command.add_argument("--read-remote", action="store_true", help="Explicitly permit remote member readback")
        if name == "activate":
            command.add_argument("--validation-id", required=True, type=_uuid)
            command.add_argument("--expected-event-id", required=True, help="Exact current activation UUID, or 'none' only for the first activation")
            command.add_argument("--idempotency-key", required=True)
            command.add_argument("--action", required=True, choices=("promote", "rollback"))
    return root


def request_from_args(args):
    if args.command == "stage":
        with args.input.open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("Private staging input exceeds 16 MiB")
        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate JSON field")
                result[key] = value
            return result
        def invalid_constant(value):
            raise ValueError("Non-finite JSON constant")
        value = json.loads(raw, object_pairs_hook=unique_keys, parse_constant=invalid_constant)
        if type(value) is not dict or set(value) != {"generation_id", "logical_index", "resource", "items"}:
            raise ValueError("Exact staging file fields are required")
        return {"command": "stage", **value}
    request = {"command": args.command, "generation_id": args.generation_id}
    if args.command == "activate":
        request.update(validation_id=args.validation_id, action=args.action,
            expected_event_id=None if args.expected_event_id == "none" else _uuid(args.expected_event_id),
            idempotency_key=args.idempotency_key)
    return request


async def run(args, request):
    # Require an explicit process target, not the app's implicit dotenv fallback.
    if not os.environ.get("DATABASE_URL") or not os.environ["DATABASE_URL"].startswith(("postgresql://", "postgresql+asyncpg://")):
        raise ValueError("An explicitly selected PostgreSQL DATABASE_URL is required")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
    from models.db import get_engine, get_session_factory
    from services.index_operations import run_operation
    from services.schema_lifecycle import check_connection_schema
    engine = get_engine()
    try:
        async with engine.connect() as connection:
            await connection.run_sync(check_connection_schema)
        async with get_session_factory()() as db:
            result = await run_operation(db, request, apply=getattr(args, "apply", False),
                                         read_remote=getattr(args, "read_remote", False))
            if getattr(args, "apply", False):
                await db.commit()
                result["committed"] = True
            else:
                await db.rollback()
            return result
    finally:
        await engine.dispose()


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = asyncio.run(run(args, request_from_args(args)))
    except (Exception, KeyboardInterrupt):
        # DB/provider exceptions may contain DSNs, SQL parameters or source text.
        print(json.dumps({"status": "failed", "detail": "Index operation failed or was interrupted. An explicitly requested SQL commit or remote upsert may already have succeeded. Inspect current state and reuse the same activation idempotency key before retrying; no automatic activation or deletion follows failure."}))
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
