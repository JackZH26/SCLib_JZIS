"""Transport fault tests; no solver/M4/scientific publication assertion."""
import hashlib
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from sclib_compute.api import AuthConfig, Principal, ServiceConfig, create_app
from sclib_compute.contracts import (
    Completion,
    Failure,
    FilePin,
    Heartbeat,
    JobSpec,
    NodeRegistration,
    canonical,
)
from sclib_compute.store import ComputeError, Limits, Store
from sclib_compute.worker import DummyWorker


class Clock:
    value = 100000

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    limits = Limits(lease_seconds=10, retry_grace_seconds=5, max_wall_seconds=30, min_free_bytes=1)
    root = tmp_path.resolve() / "service"
    store = Store(root, limits, clock)
    registration = NodeRegistration(runtime_id="dummy-v1", capabilities=["dummy"], platform="dummy_test")
    store.register("node-a", registration)
    store.register("node-b", registration)
    return store, clock, tmp_path.resolve()


def spec_for(store, clock, job_id="job-a", *, mode="success", max_attempts=2, kind="dummy", runtime="dummy-v1"):
    data = canonical({"mode": mode, "steps": 1})
    store.put_blob(data, sha(data))
    return JobSpec(job_id=job_id, kind=kind, runtime_id=runtime, case_ref="case-a", state_ref="state-a", action_ref="action-a",
        input_artifacts=[{"name": "input.json", "sha256": sha(data), "bytes": len(data)}],
        output_rules=[{"name": name, "max_bytes": 4096} for name in ["result.json", "stdout.txt", "execution.json"]],
        resources={"cpu_cores": 1, "wall_seconds": 30, "memory_bytes": 256 * 1024**2, "output_bytes": 12288},
        max_attempts=max_attempts, deadline_unix=clock.value + 1000)


def start(store, clock, **kwargs):
    spec = spec_for(store, clock, **kwargs)
    store.enqueue(spec)
    claim = store.claim("node-a", "claim-a")
    return spec, claim


def outputs(store, spec, claim, node="node-a", marker=b"test"):
    attempt = claim["attempt"]
    pins = []
    for rule in spec.output_rules:
        data = marker + rule.name.encode()
        pin = store.attach_output(node, attempt["attempt_id"], rule.name, attempt["fencing_token"], data, sha(data))
        pins.append(FilePin(name=rule.name, **pin))
    return Completion(fencing_token=attempt["fencing_token"], input_manifest_sha256=spec.input_manifest_sha256,
        runtime_id=spec.runtime_id, manifest=pins, solver_outcome="success", elapsed_seconds=1)


def client_for(store, *, peer="127.0.0.1", role="node"):
    principals = {sha(b"node-token"): Principal(role="node", node_id="node-a", runtime_id="dummy-v1", capabilities=["dummy"]),
                  sha(b"operator-token"): Principal(role="operator")}
    config = ServiceConfig(auth=AuthConfig(mode="loopback_test", test_bearer_sha256_principals=principals))
    return TestClient(create_app(store, config), client=(peer, 53000), headers={"Authorization": f"Bearer {role}-token"})


def test_t01_authentication_identity_and_operator_separation(env):
    store, clock, _ = env
    spec = spec_for(store, clock)
    with client_for(store) as client:
        assert client.post("/compute/v1/jobs", json=spec.model_dump(mode="json")).status_code == 403
        assert client.put("/compute/v1/inputs/" + sha(b"x"), content=b"x").status_code == 403
        assert client.post("/compute/v1/jobs/job-a/cancel").status_code == 403
        assert client.post("/compute/v1/nodes/node-a/drain", json={"enabled": True}).status_code == 403
        assert client.post("/compute/v1/nodes/register", json={"node_id": "node-b", "runtime_id": "dummy-v1", "capabilities": ["dummy"], "platform": "dummy_test"}).status_code == 422
        assert client.post("/compute/v1/nodes/register", json={"runtime_id": "qe-runtime", "capabilities": ["qe_scf"], "platform": "dummy_test"}).status_code == 403
        assert client.post("/compute/v1/jobs/claim", json={"claim_request_id": "request", "budget": 99999}).status_code == 422
    with client_for(store, role="operator") as client:
        assert client.post("/compute/v1/jobs/claim", json={"claim_request_id": "request"}).status_code == 403
        assert client.post("/compute/v1/jobs", json=spec.model_dump(mode="json")).status_code == 200
    with client_for(store, peer="198.51.100.4") as client:
        assert client.get("/health", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
        assert client.post("/compute/v1/jobs/claim", json={"claim_request_id": "request"}).status_code == 403


def test_t01_proxy_certificate_sha256_pin_not_subject(env):
    store, _, _ = env
    # Only tests trusted terminator contract; actual TLS validation belongs to
    # nginx and is separately exercised with real certificates by deployment.
    pem = ssl.DER_cert_to_PEM_cert(b"verified-certificate-fixture")
    config = ServiceConfig(auth=AuthConfig(proxy_token_sha256=sha(b"proxy-secret"),
        certificate_sha256_principals={sha(b"verified-certificate-fixture"): Principal(role="operator")}))
    with TestClient(create_app(store, config), client=("127.0.0.1", 1)) as client:
        headers = {"X-SCLib-Proxy-Token": "proxy-secret", "X-SCLib-Client-Verify": "SUCCESS", "X-SCLib-Client-Certificate": quote(pem, safe="")}
        assert client.get("/compute/v1/status", headers=headers).status_code == 200
        assert client.get("/compute/v1/status", headers={"X-SCLib-Cert-Fingerprint": sha(b"verified-certificate-fixture"), "X-SCLib-Client-Subject": "node-a"}).status_code == 401
        assert client.get("/compute/v1/status", headers={**headers, "X-SCLib-Client-Verify": "FAILED"}).status_code == 401
        assert client.get("/compute/v1/status", headers={**headers, "X-SCLib-Proxy-Token": "wrong"}).status_code == 401
        assert client.get("/compute/v1/status", headers={**headers, "X-SCLib-Client-Certificate": quote(ssl.DER_cert_to_PEM_cert(b"unapproved"), safe="")}).status_code == 403


def test_t02_checksum_and_frozen_job_binding(env):
    store, clock, _ = env
    with pytest.raises(ComputeError, match="checksum"):
        store.put_blob(b"input", "0" * 64)
    spec = spec_for(store, clock)
    assert store.enqueue(spec) == store.enqueue(spec)
    changed = spec.model_copy(update={"state_ref": "state-different"})
    with pytest.raises(ComputeError, match="job_id_content_changed"):
        store.enqueue(changed)
    missing = spec.model_copy(update={"job_id": "missing", "input_artifacts": [FilePin(name="input.json", sha256="0" * 64, bytes=1)]})
    with pytest.raises(ComputeError, match="input_not_staged"):
        store.enqueue(missing)


def test_t03_lost_claim_ack_durable_before_and_after_expiry(env):
    store, clock, _ = env
    spec, first = start(store, clock)
    again = Store(store.root, store.limits, clock)
    assert again.claim("node-a", "claim-a")["attempt"] == first["attempt"]
    assert again.status()["reserved_cpu_core_seconds"] == 30
    clock.advance(16)
    expired = again.claim("node-a", "claim-a")
    assert expired["attempt"]["attempt_id"] == first["attempt"]["attempt_id"]
    assert expired["attempt"]["status"] == "lost"
    assert expired["job"] == spec.model_dump(mode="json")
    second = again.claim("node-a", "claim-new")["attempt"]
    assert second["attempt_id"] != first["attempt"]["attempt_id"]
    assert second["fencing_token"] == first["attempt"]["fencing_token"] + 1
    assert again.status()["reserved_cpu_core_seconds"] == 60


def test_t03_empty_claim_replay_never_claims_later_job(env):
    store, clock, _ = env
    assert store.claim("node-a", "empty") == {"attempt": None}
    store.enqueue(spec_for(store, clock))
    assert Store(store.root, store.limits, clock).claim("node-a", "empty") == {"attempt": None}
    assert store.claim("node-a", "new")["attempt"]


def test_t04_complete_ack_lost_replayed_after_lease_expiry(env):
    store, clock, _ = env
    spec, claim = start(store, clock)
    completion = outputs(store, spec, claim)
    receipt = store.complete("node-a", claim["attempt"]["attempt_id"], completion)
    clock.advance(100)
    restarted = Store(store.root, store.limits, clock)
    assert restarted.complete("node-a", claim["attempt"]["attempt_id"], completion) == receipt
    assert restarted.status()["reserved_cpu_core_seconds"] == 30
    assert receipt["status"] == "returned" and receipt["scientific_status"] == "not_assessed"
    assert receipt["scientific_publication_authority"] is False
    with pytest.raises(ComputeError, match="completion_id_content_changed"):
        restarted.complete("node-a", claim["attempt"]["attempt_id"], completion.model_copy(update={"solver_outcome": "not_converged"}))


def test_t05_stale_attempt_is_quarantined_cannot_override_new_attempt(env):
    store, clock, _ = env
    spec, first = start(store, clock)
    completion_a = outputs(store, spec, first)
    clock.advance(16)
    second = store.claim("node-b", "new")
    assert second["attempt"]["fencing_token"] == 2
    stale = store.complete("node-a", first["attempt"]["attempt_id"], completion_a)
    assert stale["status"] == "quarantined" and stale["reason"] == "stale_attempt"
    assert store.status()["jobs"] == {"leased": 1}
    completion_b = outputs(store, spec, second, "node-b", b"new")
    assert store.complete("node-b", second["attempt"]["attempt_id"], completion_b)["status"] == "returned"
    assert store.complete("node-a", first["attempt"]["attempt_id"], completion_a) == stale
    assert store.status()["jobs"] == {"returned": 1}


def test_t06_expired_lease_cannot_renew_or_download(env):
    store, clock, _ = env
    _, claim = start(store, clock)
    attempt = claim["attempt"]
    clock.advance(11)
    assert store.heartbeat("node-a", attempt["attempt_id"], Heartbeat(fencing_token=1, phase="running", elapsed_seconds=1, observed_memory_bytes=0))["continue"] is False
    with pytest.raises(ComputeError, match="lease_or_fence"):
        store.input_file("node-a", attempt["attempt_id"], "input.json", 1)
    with pytest.raises(ComputeError, match="node_busy"):
        store.claim("node-a", "too-early")


def test_t07_concurrent_claims_transaction_and_restart(env):
    store, clock, _ = env
    store.enqueue(spec_for(store, clock))
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda node: store.claim(node, "request"), ["node-a", "node-b"]))
    assert sum(reply["attempt"] is not None for reply in replies) == 1
    assert Store(store.root, store.limits, clock).status()["reserved_cpu_core_seconds"] == 30


@pytest.mark.parametrize("mode", ["solver_failure", "not_converged", "clean_checkpoint"])
def test_t08_solver_outcomes_retained_without_scientific_success(env, mode):
    store, clock, root = env
    spec = spec_for(store, clock, mode=mode)
    store.enqueue(spec)
    with client_for(store) as client:
        worker = DummyWorker(client, root / "worker", sleep=lambda _: None)
        try:
            receipt = worker.one_cycle()
        finally:
            worker.close()
    assert receipt["solver_outcome"] == mode
    assert receipt["scientific_status"] == "not_assessed"
    assert receipt["scientific_publication_authority"] is False
    assert not {"tc", "tc_k", "superconductivity_verified"} & set(receipt)
    assert store.status()["jobs"] == {"returned": 1}


def test_t08_scientific_failures_not_automatically_retried(env):
    store, clock, _ = env
    _, claim = start(store, clock)
    assert store.fail("node-a", claim["attempt"]["attempt_id"], Failure(fencing_token=1, code="not_converged"))["status"] == "failed"
    assert store.claim("node-a", "next")["attempt"] is None


def test_t09_artifacts_traversal_symlink_size_integrity_and_disk(env, monkeypatch):
    store, clock, _ = env
    spec, claim = start(store, clock)
    data = b"x" * 4097
    with pytest.raises(ComputeError, match="output_too_large"):
        store.attach_output("node-a", claim["attempt"]["attempt_id"], "stdout.txt", 1, data, sha(data))
    with pytest.raises(ComputeError, match="artifact_hash_invalid"):
        store.read_blob("../../secret", 1)
    blob = spec.input_artifacts[0]
    original = store.objects / blob.sha256
    original.unlink()
    original.symlink_to(store.db_path)
    with pytest.raises(ComputeError, match="artifact_unavailable"):
        store.read_blob(blob.sha256, blob.bytes)
    original.unlink()
    original.write_bytes(b"corrupted")
    with pytest.raises(ComputeError, match="artifact_corrupted"):
        store.read_blob(blob.sha256, blob.bytes)
    monkeypatch.setattr("sclib_compute.store.shutil.disk_usage", lambda _: type("Usage", (), {"free": 0})())
    with pytest.raises(ComputeError, match="insufficient_disk"):
        store.put_blob(b"new", sha(b"new"))
    with client_for(store, role="operator") as client:
        assert client.put("/compute/v1/inputs/" + sha(b"too-big"), content=b"x" * (store.limits.max_artifact_bytes + 1)).status_code == 413
        invalid = spec.model_dump(mode="json")
        invalid["input_artifacts"][0]["name"] = "../input"
        assert client.post("/compute/v1/jobs", json=invalid).status_code == 422


def test_t10_cancel_drain_and_bounded_retry(env):
    store, clock, _ = env
    spec, claim = start(store, clock)
    store.drain("node-a", True)
    beat = Heartbeat(fencing_token=1, phase="running", elapsed_seconds=1, observed_memory_bytes=0)
    assert store.heartbeat("node-a", claim["attempt"]["attempt_id"], beat)["drain"] is True
    completion = outputs(store, spec, claim)
    store.cancel(spec.job_id)
    store.cancel(spec.job_id)
    assert store.heartbeat("node-a", claim["attempt"]["attempt_id"], beat)["continue"] is False
    assert store.complete("node-a", claim["attempt"]["attempt_id"], completion)["status"] == "quarantined"
    with pytest.raises(ComputeError, match="node_draining"):
        store.claim("node-a", "next")
    store.drain("node-a", False)
    next_spec = spec_for(store, clock, "job-b", max_attempts=2)
    store.enqueue(next_spec)
    first = store.claim("node-a", "b1")
    assert store.fail("node-a", first["attempt"]["attempt_id"], Failure(fencing_token=1, code="worker_crash"))["status"] == "queued"
    second = store.claim("node-a", "b2")
    assert store.fail("node-a", second["attempt"]["attempt_id"], Failure(fencing_token=2, code="worker_crash"))["status"] == "failed"
    assert store.claim("node-a", "b3")["attempt"] is None
    assert store.status()["reserved_cpu_core_seconds"] == 90


def test_t13_binding_mismatch_and_fence_cannot_poison_live_attempt(env):
    store, clock, _ = env
    spec, claim = start(store, clock)
    completion = outputs(store, spec, claim)
    with pytest.raises(ComputeError, match="attempt_fence_invalid"):
        store.complete("node-a", claim["attempt"]["attempt_id"], completion.model_copy(update={"fencing_token": 999}))
    assert store.get_attempt("node-a", claim["attempt"]["attempt_id"])["receipt"] is None
    bad = completion.model_copy(update={"input_manifest_sha256": "0" * 64})
    assert store.complete("node-a", claim["attempt"]["attempt_id"], bad)["reason"] == "input_or_runtime_mismatch"
    assert store.status()["jobs"] == {"failed": 1}
    store.enqueue(spec_for(store, clock, "qe-job", kind="qe_scf"))
    store.enqueue(spec_for(store, clock, "different-runtime", runtime="dummy-v2"))
    assert store.claim("node-a", "unmatched")["attempt"] is None


def test_budget_counted_once_per_attempt_never_refunded(env):
    store, clock, _ = env
    store.limits = replace(store.limits, total_cpu_core_seconds=30)
    _, claim = start(store, clock)
    store.fail("node-a", claim["attempt"]["attempt_id"], Failure(fencing_token=1, code="worker_crash"))
    with pytest.raises(ComputeError, match="cpu_budget"):
        store.claim("node-a", "second")
    assert store.claim("node-a", "claim-a")["attempt"]["attempt_id"] == claim["attempt"]["attempt_id"]
    assert store.status()["reserved_cpu_core_seconds"] == 30


class LoseAck:
    def __init__(self, client, endpoint):
        self.client, self.endpoint, self.lost = client, endpoint, False

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if path.endswith(self.endpoint) and not self.lost:
            self.lost = True
            raise httpx.ReadTimeout("injected lost ACK")
        return response


@pytest.mark.parametrize("endpoint", ["/claim", "/complete"])
def test_dummy_worker_restart_recovers_lost_ack_exactly_once(env, endpoint):
    store, clock, root = env
    store.enqueue(spec_for(store, clock))
    with client_for(store) as client:
        worker = DummyWorker(LoseAck(client, endpoint), root / "worker", sleep=lambda _: None)
        try:
            with pytest.raises(httpx.ReadTimeout):
                worker.one_cycle()
        finally:
            worker.close()
        if endpoint == "/complete":
            clock.advance(100)
        recovered = DummyWorker(client, root / "worker", sleep=lambda _: None)
        try:
            receipt = recovered.one_cycle()
        finally:
            recovered.close()
    assert receipt["status"] == "returned"
    assert store.status()["reserved_cpu_core_seconds"] == 30
    assert store.status()["jobs"] == {"returned": 1}


def test_private_worker_single_process_lock(env):
    _, _, root = env
    worker = DummyWorker(None, root / "worker")
    try:
        with pytest.raises(ValueError, match="another worker"):
            DummyWorker(None, root / "worker")
    finally:
        worker.close()
