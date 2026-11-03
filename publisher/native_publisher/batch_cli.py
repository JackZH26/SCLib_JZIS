"""Operator batch worker: preview by default; no automatic acceptance/activation."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import stat
from uuid import uuid4

import sqlalchemy as sa

from config import get_settings
from models.db import get_engine, get_session_factory
from services.schema_lifecycle import check_application_schema
from native_publisher.batch import (BatchPlan, NativeBatchError, claim_and_plan, finish_batch,
    latest_pending_jobs, materialize_content, prepare_projection, retry_batch, supersede_pending, verify_plan)


def read_plan(path):
    path = Path(path)
    if not path.is_absolute():
        raise NativeBatchError("Absolute operator plan file required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= 1024**2:
            raise NativeBatchError("Bounded regular plan file required")
        payload = b""
        while chunk := os.read(descriptor, 65536):
            payload += chunk
            if len(payload) > 1024**2:
                raise NativeBatchError("Plan file exceeds its limit")
        after, named = os.fstat(descriptor), path.stat(follow_symlinks=False)
        if len(payload) != before.st_size or any(getattr(before, key) != getattr(row, key)
                for row in (after, named) for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")):
            raise NativeBatchError("Plan file changed during read")
    finally:
        os.close(descriptor)
    return BatchPlan.from_dict(json.loads(payload))


def write_new_plan(path, plan):
    path = Path(path)
    if not path.is_absolute():
        raise NativeBatchError("Absolute fresh operator plan path required")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(plan.to_dict(), output, sort_keys=True, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    # The file is only an input candidate. SQL verification is authoritative;
    # a failure to commit leaves no usable plan and no success receipt.


async def execute(args):
    if get_settings().retrieval_backend != "pgvector":
        raise NativeBatchError("An explicit pgvector worker deployment is required")
    engine = get_engine()
    factory = get_session_factory()
    try:
        await check_application_schema(engine)
        async with factory() as db:
            member = await db.scalar(sa.text("SELECT pg_has_role(current_user,'sclib_retrieval_queue_worker','member')"))
            if member is not True:
                raise NativeBatchError("Separate queue-worker capability required")
            if args.phase == "supersede":
                if not args.logical_index or not args.worker_id:
                    raise NativeBatchError("Explicit logical index and worker required")
                result = await supersede_pending(db, logical_index=args.logical_index,
                    worker_id=args.worker_id, limit=args.limit, dry_run=not args.apply)
                if args.apply:
                    await db.commit()
                    result["committed"] = True
                return result
            if args.phase in {"select", "claim"}:
                if not args.logical_index:
                    raise NativeBatchError("Explicit logical index required")
                jobs = args.job_id or await latest_pending_jobs(db, logical_index=args.logical_index, limit=args.limit)
                if args.phase == "select" or not jobs:
                    return {"status": "selection_only", "jobs": jobs, "committed": False}
                if not args.base_content_id or not args.worker_id or args.apply and not args.plan_out:
                    raise NativeBatchError("Explicit sealed base, worker and fresh plan output are required")
                plan = await claim_and_plan(db, batch_id=args.batch_id or str(uuid4()),
                    logical_index=args.logical_index, base_content_id=args.base_content_id, job_ids=jobs,
                    worker_id=args.worker_id, lease_seconds=args.lease_seconds, dry_run=not args.apply)
                if args.apply:
                    write_new_plan(args.plan_out, plan)
                    await db.commit()
                return {"status": "claimed_and_planned" if args.apply else "preview_rolled_back",
                    "committed": args.apply, "plan": plan.to_dict(), "activation_performed": False}
            if not args.plan:
                raise NativeBatchError("An exact retained batch plan is required")
            plan = read_plan(args.plan)
            target = await verify_plan(db, plan, usable=args.phase not in {"finish", "retry"})
            await db.rollback()
            if not args.apply:
                return {"status": "preview_no_work", "phase": args.phase, "content_id": plan.content_id,
                    "expected_members": target["expected_member_count"], "committed": False, "activation_performed": False}
            progress = lambda value: print(json.dumps(value), flush=True)
            if args.phase == "content":
                return await materialize_content(plan, session_factory=factory, progress=progress)
            if args.phase in {"projection", "copy-vectors", "small-graph", "small-validate", "graph", "seal-projection", "validate"}:
                if not all((args.build_id, args.image_digest, args.implementation_revision)):
                    raise NativeBatchError("Explicit immutable build/image/revision required")
                return await prepare_projection(plan, phase=args.phase, session_factory=factory, progress=progress,
                    build_id=args.build_id, image_digest=args.image_digest, implementation_revision=args.implementation_revision,
                    validation_id=args.validation_id,host_graph_budget=args.host_graph_budget)
            if args.phase == "finish":
                if not args.activation_event_id:
                    raise NativeBatchError("Actual activation event required")
                result = await finish_batch(db, plan, activation_event_id=args.activation_event_id, dry_run=False)
            else:
                result = await retry_batch(db, plan, error_code=args.error_code, dry_run=False)
            await db.commit()
            result["committed"] = True
            return result
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--phase", choices=["select", "claim", "supersede", "content", "projection", "copy-vectors",
        "small-graph", "small-validate", "graph", "seal-projection", "validate", "finish", "retry"], default="select")
    for name in ("logical-index", "base-content-id", "worker-id", "batch-id", "plan-out", "plan", "build-id",
                 "image-digest", "implementation-revision", "validation-id", "activation-event-id"):
        parser.add_argument("--" + name)
    parser.add_argument("--job-id", action="append")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--lease-seconds", type=int, default=7200)
    parser.add_argument("--error-code", choices=["transient_io", "build_failed", "validation_failed", "source_changed", "operator_retry"],
        default="operator_retry")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--host-graph-budget", action="store_true")
    try:
        print(json.dumps(asyncio.run(execute(parser.parse_args()))), flush=True)
    except Exception as error:
        print(json.dumps({"status": "failed", "error_class": type(error).__name__,
            "message": "Native batch refused or interrupted; verify retained SQL state before retry"}), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
