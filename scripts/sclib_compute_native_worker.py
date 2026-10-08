#!/usr/bin/env python3
"""Run the pinned native QE worker; result publication requires separate review."""

import argparse
import json
import os
import signal
import time
from pathlib import Path

import httpx
from sclib_compute.native_contract import NativeRuntime, read_regular
from sclib_compute.native_worker import NativeWorker
from sclib_compute.worker import WorkerStopped, client_from_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, required=True, help="private mTLS client configuration"
    )
    parser.add_argument(
        "--runtime-config",
        type=Path,
        required=True,
        help="administrator provisioned binary pins and local limits",
    )
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--max-jobs", type=int, default=1)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if args.max_jobs < 0 or (args.max_jobs == 0 and not args.serve):
        parser.error("unbounded cycles require --serve")
    if args.config.stat().st_mode & 0o077 or args.runtime_config.stat().st_mode & 0o022:
        parser.error(
            "mTLS config must be private; runtime config cannot be group/world writable"
        )
    if os.getuid() == 0:
        parser.error("native worker must run as a dedicated non-root account")
    os.umask(0o077)
    config = json.loads(read_regular(args.config, 65536))
    runtime = NativeRuntime.model_validate_json(
        read_regular(args.runtime_config, 65536)
    )

    def terminate(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    with client_from_config(config) as client:
        worker = NativeWorker(client, args.state_dir, runtime)
        cycles, backoff = 0, 2
        try:
            while args.max_jobs == 0 or cycles < args.max_jobs:
                try:
                    receipt = worker.one_cycle()
                    print(
                        json.dumps(
                            {
                                key: receipt[key]
                                for key in [
                                    "status",
                                    "attempt_id",
                                    "solver_outcome",
                                    "scientific_status",
                                ]
                                if key in receipt
                            }
                        ),
                        flush=True,
                    )
                    cycles += 1
                    backoff = 2
                    if worker.stop_requested:
                        break
                    if args.serve:
                        time.sleep(30)
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    if isinstance(
                        exc, httpx.HTTPStatusError
                    ) and exc.response.status_code in {401, 403, 422}:
                        raise WorkerStopped(
                            "native authentication/contract refused; operator action required"
                        ) from None
                    if not args.serve or worker.stop_requested:
                        raise WorkerStopped(
                            "native transport interrupted; persisted state is recoverable"
                        ) from None
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
        except KeyboardInterrupt:
            pass
        finally:
            worker.close()


if __name__ == "__main__":
    main()
