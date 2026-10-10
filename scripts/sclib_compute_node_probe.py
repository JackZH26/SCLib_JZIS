#!/usr/bin/env python3
"""Node-only, bounded real mTLS probe; an operator stages exactly one dummy job.

No operator credential is needed on the compute node. This validates transport,
not native scientific execution or 24-hour readiness.
"""
import argparse
import json
import os
import time
from pathlib import Path

import httpx
from sclib_compute.worker import DummyWorker, atomic_json, client_from_config
from sclib_compute_probe import LoseAck, private_config


def run(config, output):
    if config.get("loopback_test"):
        raise ValueError("node acceptance needs real HTTPS/mTLS")
    if output.exists():
        raise ValueError("use a new probe evidence directory; preserve prior attempts")
    output.mkdir(mode=0o700, parents=True)
    with client_from_config(config) as client:
        denied = client.get("/compute/v1/status")
        if denied.status_code != 403:
            raise ValueError("node/operator boundary failed")
        for endpoint in ["/claim", "/complete"]:
            worker = DummyWorker(LoseAck(client, endpoint), output / "worker",
                                 runtime_id=config["runtime_id"], platform="macos_arm64")
            try:
                try:
                    worker.one_cycle()
                except httpx.ReadTimeout:
                    pass
                else:
                    raise ValueError("expected ACK fault not reached; check pre-staged job")
            finally:
                worker.close()
        worker = DummyWorker(client, output / "worker", runtime_id=config["runtime_id"], platform="macos_arm64")
        try:
            receipt = worker.one_cycle()
        finally:
            worker.close()
        state = json.loads((output / "worker/state.json").read_bytes())
        replay = client.post(f"/compute/v1/attempts/{receipt['attempt_id']}/complete", json=state["outbox"]["completion"])
        replay.raise_for_status()
        if receipt["status"] != "returned" or replay.json() != receipt:
            raise ValueError("receipt replay is not identical and returned")
        report = {"schema_version": "sclib-node-transport-probe/1", "observed_at_unix": time.time(),
                  "receipt": receipt, "node_operator_denied": True,
                  "lost_claim_ack_recovered": True, "lost_complete_ack_recovered": True,
                  "complete_replay_identical": True, "operator_credentials_on_node": False,
                  "native_science_run": False, "soak_24h": False}
        atomic_json(output / "report.json", report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    result = run(private_config(args.config), args.output.resolve())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
