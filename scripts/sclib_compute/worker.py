"""Bounded dummy-only worker with durable claim and completion recovery.

No shell execution, solver installation, production DB credentials or Tc values.
The synthetic checkpoint is a transport fixture, never a Quantum ESPRESSO restart.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import resource
import ssl
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .contracts import Completion, DummyInput, FilePin, JobSpec, canonical


class WorkerStopped(Exception):
    pass


def atomic_json(path: Path, data: dict):
    temporary = path.with_name("pending-" + uuid.uuid4().hex)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical(data))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


class DummyWorker:
    def __init__(self, client, root: Path, *, runtime_id="dummy-v1", platform="dummy_test", sleep=time.sleep):
        self.client, self.root, self.runtime_id, self.platform, self.sleep = client, root.absolute(), runtime_id, platform, sleep
        for path in [self.root, *self.root.parents]:
            if path.is_symlink():
                raise ValueError("worker state path must not contain symlinks")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.stat().st_mode & 0o077:
            raise ValueError("worker state must be owner-only")
        self.state_path = self.root / "state.json"
        if self.state_path.is_symlink():
            raise ValueError("worker state cannot be a symlink")
        descriptor = os.open(self.root / "worker.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        self.lock = os.fdopen(descriptor, "w")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise ValueError("another worker already owns this state directory") from None

    def close(self):
        self.lock.close()

    def request(self, method, path, **kwargs):
        response = self.client.request(method, "/compute/v1" + path, **kwargs)
        response.raise_for_status()
        return response

    def persist(self, state):
        atomic_json(self.state_path, state)

    def heartbeat(self, claim, phase, elapsed):
        attempt = claim["attempt"]
        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        peak_bytes = peak if sys.platform == "darwin" else peak * 1024
        result = self.request("POST", f"/attempts/{attempt['attempt_id']}/heartbeat", json={
            "fencing_token": attempt["fencing_token"], "phase": phase,
            "elapsed_seconds": elapsed, "observed_memory_bytes": peak_bytes}).json()
        if not result["continue"]:
            raise WorkerStopped("server ended this lease; execution stops")
        return result

    def one_cycle(self):
        self.request("POST", "/nodes/register", json={"runtime_id": self.runtime_id, "capabilities": ["dummy"], "platform": self.platform})
        state = json.loads(self.state_path.read_bytes()) if self.state_path.exists() else {}
        if state.get("acknowledged") or state.get("abandoned"):
            state = {}
        if "claim_request_id" not in state:
            # Fsync BEFORE claim. A timeout/process death replays this same key.
            state = {"schema_version": "sclib-dummy-worker-state/1", "claim_request_id": "claim-" + uuid.uuid4().hex}
            self.persist(state)
        if "claim" not in state:
            state["claim"] = self.request("POST", "/jobs/claim", json={"claim_request_id": state["claim_request_id"]}).json()
            self.persist(state)
        claim = state["claim"]
        if claim["attempt"] is None:
            state["acknowledged"] = {"status": "empty_claim"}
            self.persist(state)
            return state["acknowledged"]
        attempt = claim["attempt"]
        if "outbox" not in state:
            current = self.request("GET", f"/attempts/{attempt['attempt_id']}").json()
            if current.get("receipt"):
                state["acknowledged"] = current["receipt"]
                self.persist(state)
                return current["receipt"]
            if current["attempt"]["status"] not in {"leased", "preparing", "running", "uploading"}:
                state["abandoned"] = {"status": current["attempt"]["status"], "reason": "old_claim_not_executed"}
                self.persist(state)
                return state["abandoned"]
            spec = JobSpec.model_validate(claim["job"])
            if spec.kind != "dummy" or spec.runtime_id != self.runtime_id or spec.input_manifest_sha256 != claim["input_manifest_sha256"]:
                raise WorkerStopped("job is outside dummy capability or input binding")
            # This initial adapter has exactly one bounded, closed JSON input.
            if len(spec.input_artifacts) != 1:
                raise WorkerStopped("dummy requires exactly one input")
            initial_phase = "preparing" if current["attempt"]["status"] in {"leased", "preparing"} else "running"
            baseline_elapsed = current["attempt"]["elapsed_seconds"]
            # Dummy execution is deliberately idempotent. A native solver must
            # not reuse this rule: it needs its own verified checkpoint adapter.
            self.heartbeat(claim, initial_phase, baseline_elapsed)
            pin = spec.input_artifacts[0]
            response = self.request("GET", f"/attempts/{attempt['attempt_id']}/inputs/{pin.name}", headers={"X-SCLib-Fencing-Token": str(attempt["fencing_token"])})
            data = response.content
            if len(data) != pin.bytes or hashlib.sha256(data).hexdigest() != pin.sha256:
                raise WorkerStopped("download checksum mismatch")
            inputs = DummyInput.model_validate_json(data)
            started = time.monotonic()
            for _step in range(inputs.steps):
                self.heartbeat(claim, "running", baseline_elapsed + int(time.monotonic() - started))
                self.sleep(0.02)
            elapsed = baseline_elapsed + int(time.monotonic() - started)
            if elapsed > spec.resources.wall_seconds:
                raise WorkerStopped("dummy wall budget exhausted")
            result = {"adapter": "dummy", "transport_fixture": True, "solver_outcome": inputs.mode,
                      "scientific_status": "not_assessed", "input_manifest_sha256": spec.input_manifest_sha256,
                      "runtime_id": self.runtime_id, "checkpoint": "synthetic-only" if inputs.mode == "clean_checkpoint" else None}
            files = {"result.json": canonical(result), "stdout.txt": b"SCLib dummy transport fixture; no scientific calculation performed.\n",
                     "execution.json": canonical({"attempt_id": attempt["attempt_id"], "fencing_token": attempt["fencing_token"],
                         "runtime_id": self.runtime_id, "elapsed_seconds": elapsed, "shell_execution": False})}
            if set(files) != {rule.name for rule in spec.output_rules}:
                raise WorkerStopped("dummy output contract requires result.json, stdout.txt and execution.json")
            manifest = [FilePin(name=name, sha256=hashlib.sha256(body).hexdigest(), bytes=len(body)) for name, body in sorted(files.items())]
            completion = Completion(fencing_token=attempt["fencing_token"], input_manifest_sha256=spec.input_manifest_sha256,
                runtime_id=self.runtime_id, manifest=manifest, solver_outcome=inputs.mode, elapsed_seconds=elapsed)
            # Fsync exact bytes and complete body BEFORE first upload. Restart never
            # recomputes an existing outbox, including after lease expiration.
            state["outbox"] = {"completion": completion.model_dump(mode="json"), "files": {name: base64.b64encode(body).decode() for name, body in files.items()}}
            self.persist(state)
            self.heartbeat(claim, "uploading", elapsed)
        outbox = state["outbox"]
        for pin in outbox["completion"]["manifest"]:
            data = base64.b64decode(outbox["files"][pin["name"]], validate=True)
            if len(data) != pin["bytes"] or hashlib.sha256(data).hexdigest() != pin["sha256"]:
                raise WorkerStopped("durable outbox corrupted")
            self.request("PUT", f"/attempts/{attempt['attempt_id']}/outputs/{pin['name']}", content=data,
                         headers={"X-SCLib-Fencing-Token": str(attempt["fencing_token"]), "X-SCLib-Content-SHA256": pin["sha256"]})
        receipt = self.request("POST", f"/attempts/{attempt['attempt_id']}/complete", json=outbox["completion"]).json()
        state["acknowledged"] = receipt
        self.persist(state)
        return receipt


def client_from_config(config):
    parsed = urlparse(config["base_url"])
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("base_url must be a server origin")
    test = config.get("loopback_test", False)
    if test:
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("test HTTP is restricted to literal 127.0.0.1")
        credential = Path(config["bearer_file"])
        if credential.is_symlink() or credential.stat().st_mode & 0o077:
            raise ValueError("test credential must be owner-only")
        return httpx.Client(base_url=config["base_url"], headers={"Authorization": "Bearer " + credential.read_text().strip()}, timeout=15, follow_redirects=False)
    if parsed.scheme != "https":
        raise ValueError("worker needs HTTPS with verified mTLS")
    certificate, key = Path(config["client_certificate"]), Path(config["client_key"])
    if certificate.is_symlink() or key.is_symlink() or key.stat().st_mode & 0o077:
        raise ValueError("client key must be private and certificate paths must not be symlinks")
    context = ssl.create_default_context(cafile=config["ca_certificate"])
    context.load_cert_chain(certificate, key)
    return httpx.Client(base_url=config["base_url"], verify=context, timeout=15, follow_redirects=False)
