#!/usr/bin/env python3
"""Run a durable dummy transport worker; QE/M4 scientific execution is not enabled."""
import argparse
import json
import os
import time
from pathlib import Path

import httpx
from sclib_compute.worker import DummyWorker, WorkerStopped, client_from_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--max-jobs", type=int, default=1, help="bounded cycles; 0 requires --serve")
    parser.add_argument("--serve", action="store_true", help="standalone poll worker, not an Agent turn")
    args = parser.parse_args()
    if args.max_jobs < 0 or (args.max_jobs == 0 and not args.serve):
        parser.error("unbounded cycles require explicit --serve")
    if args.config.is_symlink() or args.config.stat().st_mode & 0o077:
        parser.error("worker config must be an owner-only regular file")
    os.umask(0o077)
    config = json.loads(args.config.read_bytes())
    with client_from_config(config) as client:
        worker = DummyWorker(client, args.state_dir, runtime_id=config.get("runtime_id", "dummy-v1"), platform=config.get("platform", "dummy_test"))
        cycles, backoff = 0, 2
        try:
            while args.max_jobs == 0 or cycles < args.max_jobs:
                try:
                    receipt = worker.one_cycle()
                    print(json.dumps({key: receipt[key] for key in ["status", "attempt_id", "scientific_status"] if key in receipt}), flush=True)
                    cycles += 1
                    backoff = 2
                    if not args.serve:
                        continue
                    time.sleep(30)
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    # Tokens, request headers and response bodies are never logged.
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403, 422}:
                        raise WorkerStopped("authentication or contract refused; operator action required") from None
                    if not args.serve:
                        raise WorkerStopped("transport interrupted; rerun recovers persisted request") from None
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
        finally:
            worker.close()


if __name__ == "__main__":
    main()
