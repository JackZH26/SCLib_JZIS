#!/usr/bin/env python3
"""Perform an opt-in real mTLS dummy roundtrip against a separate staging service.

Only transport fixtures are submitted. This makes no scientific candidate or
production application write. Credentials are read from private local files.
"""
import argparse
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import httpx
from sclib_compute.contracts import JobSpec, canonical
from sclib_compute.worker import DummyWorker, atomic_json, client_from_config


class LoseAck:
    def __init__(self, client, endpoint):
        self.client, self.endpoint, self.lost = client, endpoint, False

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if path.endswith(self.endpoint) and not self.lost and response.status_code == 200:
            self.lost = True
            raise httpx.ReadTimeout("injected lost ACK after staging commit")
        return response


def private_config(path):
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("probe config must be owner-only")
    return json.loads(path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-config", type=Path, required=True)
    parser.add_argument("--worker-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a new private directory")
    os.umask(0o077)
    args.output.mkdir(parents=True, mode=0o700)
    operator_config, worker_config = private_config(args.operator_config), private_config(args.worker_config)
    if operator_config["base_url"] != worker_config["base_url"]:
        parser.error("operator and node must use the same staging origin")
    if operator_config.get("loopback_test") or worker_config.get("loopback_test"):
        parser.error("deployment probe requires actual verified HTTPS/mTLS")
    body = canonical({"mode": "clean_checkpoint", "steps": 2})
    checksum = hashlib.sha256(body).hexdigest()
    job_id = "dummy-probe-" + uuid.uuid4().hex
    spec = JobSpec(job_id=job_id, kind="dummy", runtime_id=worker_config.get("runtime_id", "dummy-v1"),
        case_ref="transport-probe", state_ref="synthetic-state", action_ref="dummy-roundtrip",
        input_artifacts=[{"name": "input.json", "sha256": checksum, "bytes": len(body)}],
        output_rules=[{"name": name, "max_bytes": 4096} for name in ["result.json", "stdout.txt", "execution.json"]],
        resources={"cpu_cores": 1, "wall_seconds": 60, "memory_bytes": 512 * 1024**2, "output_bytes": 12288},
        max_attempts=2, deadline_unix=int(time.time()) + 900)
    with client_from_config(operator_config) as operator, client_from_config(worker_config) as client:
        before = operator.get("/compute/v1/status")
        before.raise_for_status()
        staged = operator.put("/compute/v1/inputs/" + checksum, content=body)
        staged.raise_for_status()
        queued = operator.post("/compute/v1/jobs", json=spec.model_dump(mode="json"))
        queued.raise_for_status()
        forbidden = client.get("/compute/v1/status")
        if forbidden.status_code != 403:
            raise ValueError("node unexpectedly has operator authority")
        for endpoint in ["/claim", "/complete"]:
            worker = DummyWorker(LoseAck(client, endpoint), args.output.resolve() / "worker", runtime_id=spec.runtime_id,
                                 platform=worker_config.get("platform", "dummy_test"))
            try:
                try:
                    worker.one_cycle()
                except httpx.ReadTimeout:
                    pass
                else:
                    raise ValueError("expected fault injection did not trigger")
            finally:
                worker.close()
        worker = DummyWorker(client, args.output.resolve() / "worker", runtime_id=spec.runtime_id, platform=worker_config.get("platform", "dummy_test"))
        try:
            receipt = worker.one_cycle()
        finally:
            worker.close()
        if receipt["status"] != "returned" or receipt["scientific_status"] != "not_assessed":
            raise ValueError("dummy result was not durably returned")
        saved = json.loads((args.output / "worker/state.json").read_bytes())
        replay = client.post(f"/compute/v1/attempts/{receipt['attempt_id']}/complete", json=saved["outbox"]["completion"])
        replay.raise_for_status()
        if replay.json() != receipt:
            raise ValueError("accepted complete retry changed receipt")
        after = operator.get("/compute/v1/status")
        after.raise_for_status()
        charged = after.json()["reserved_cpu_core_seconds"] - before.json()["reserved_cpu_core_seconds"]
        if charged != 60:
            raise ValueError("claim retries were charged more than once, or another job ran concurrently")
        report = {"schema_version": "sclib-compute-deployment-probe/1", "job_id": job_id, "receipt": receipt,
            "https_mtls_roundtrip": True, "lost_claim_ack_recovered": True, "lost_complete_ack_recovered": True,
            "complete_replay_identical": True, "node_operator_route_denied": True, "reserved_cpu_core_seconds": charged,
            "adapter": "dummy", "m4_node_acceptance": False, "soak_24h": False, "scientific_calculation": False,
            "production_database_access": False, "measured_at_unix": int(time.time())}
        atomic_json(args.output / "report.json", report)
        print(json.dumps({"status": "passed", "adapter": "dummy", "job_id": job_id, "report": str(args.output / "report.json")}), flush=True)


if __name__ == "__main__":
    main()
