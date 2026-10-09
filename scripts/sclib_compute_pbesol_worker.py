#!/usr/bin/env python3
"""Run one PBEsol initialization cycle under exclusive operator host ownership."""

import argparse
import json
import os
import signal
from pathlib import Path

from sclib_compute.native_contract import read_regular
from sclib_compute.pbesol_execution import PbesolWorker
from sclib_compute.worker import client_from_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--profile-config", type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    if os.getuid() == 0 or args.config.stat().st_mode & 0o077:
        parser.error("dedicated non-root account and private mTLS config required")
    os.umask(0o077)
    config = json.loads(read_regular(args.config, 65536))

    def terminate(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    with client_from_config(config) as client:
        worker = PbesolWorker(
            client, args.state_dir, args.profile_config, args.profile_sha256
        )
        try:
            receipt = worker.one_cycle()
            print(
                json.dumps(
                    {
                        k: receipt[k]
                        for k in ("status", "attempt_id", "solver_outcome")
                        if k in receipt
                    }
                )
            )
        except KeyboardInterrupt:
            pass
        finally:
            worker.close()


if __name__ == "__main__":
    main()
