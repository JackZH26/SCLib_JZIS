"""Real private compute HTTP/SQLite transport with synthetic model output only."""

import hashlib
import json
import time
from pathlib import Path
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))

from ingestion.materials_v3.blocks import parse_source
from ingestion.materials_v3.compute import NERJob, NERWorker
from ingestion.materials_v3.contract import canonical, digest, schema
from ingestion.materials_v3.pipeline import Budget, implementation_hash
from ingestion.materials_v3.providers import MODEL, REVISION, ProviderConfig, Response
from scripts.sclib_compute.api import AuthConfig, Principal, ServiceConfig, create_app
from scripts.sclib_compute.contracts import JobSpec
from scripts.sclib_compute.store import Limits, Store
from scripts.sclib_compute.worker import WorkerStopped


def sha(data):
    return hashlib.sha256(data).hexdigest()


class SyntheticProvider:
    config = ProviderConfig("local_mlx", MODEL, REVISION)
    guard = None
    calls = 0

    def generate(self, messages):
        self.calls += 1
        return Response(
            json.dumps(
                {
                    "schema_version": "materials-ner-candidate/3.0",
                    "results": [],
                    "unresolved_links": [],
                }
            )
        )


def setup(tmp_path, *, wrong_code=False):
    root = tmp_path.resolve()
    source = root / "synthetic.txt"
    source.write_text("Synthetic transport fixture without target claims.")
    document = parse_source(source, source_id="synthetic:compute")
    budget, provider = Budget(paper_seconds=20), SyntheticProvider()
    job = NERJob(
        paper_id="synthetic:paper",
        work_id="synthetic:work",
        source_sha256=document["source_sha256"],
        document_manifest_sha256=document["manifest_sha256"],
        implementation_sha256="0" * 64 if wrong_code else implementation_hash(),
        schema_sha256=digest(schema()),
        provider_config_sha256=provider.config.sha256,
        budget_sha256=digest(budget.__dict__),
        model_manifest_sha256="a" * 64,
        runtime_lock_sha256="b" * 64,
        transfer_allowed=True,
        local_inference_allowed=True,
    )
    store = Store(
        root / "store",
        Limits(
            max_wall_seconds=30,
            max_memory_bytes=32 * 1024**3,
            max_output_bytes=16 * 1024**2,
            max_artifact_bytes=8 * 1024**2,
            min_free_bytes=1,
        ),
    )
    inputs = {
        "document.json": canonical(document),
        "ner-job.json": canonical(job.model_dump(mode="json")),
    }
    for data in inputs.values():
        store.put_blob(data, sha(data))
    spec = JobSpec(
        job_id="ner-fixture",
        kind="ner_qwen_mlx",
        runtime_id="ner-test-v1",
        case_ref="synthetic",
        state_ref="shadow",
        action_ref="extract",
        input_artifacts=[
            {"name": name, "bytes": len(data), "sha256": sha(data)}
            for name, data in inputs.items()
        ],
        output_rules=[
            {"name": "result.json", "max_bytes": 8 * 1024**2},
            {"name": "execution.json", "max_bytes": 4096},
        ],
        resources={
            "cpu_cores": 1,
            "memory_bytes": 32 * 1024**3,
            "wall_seconds": 30,
            "output_bytes": 8 * 1024**2 + 4096,
        },
        max_attempts=1,
        deadline_unix=int(time.time()) + 300,
    )
    store.enqueue(spec)
    principal = Principal(
        role="node",
        node_id="ner-node",
        runtime_id="ner-test-v1",
        capabilities=["ner_qwen_mlx"],
    )
    config = ServiceConfig(
        auth=AuthConfig(
            mode="loopback_test",
            test_bearer_sha256_principals={sha(b"synthetic-token"): principal},
        ),
        enabled_job_kinds=["ner_qwen_mlx"],
    )
    client = TestClient(
        create_app(store, config),
        client=("127.0.0.1", 1),
        headers={"Authorization": "Bearer synthetic-token"},
    )
    return root, client, provider, budget


def adapter(root, client, provider, budget):
    return NERWorker(
        client,
        root / "worker",
        provider,
        budget=budget,
        runtime_id="ner-test-v1",
        model_manifest_sha256="a" * 64,
        runtime_lock_sha256="b" * 64,
    )


def test_real_queue_consumes_pinned_document_and_only_returns_private_candidates(
    tmp_path,
):
    root, client, provider, budget = setup(tmp_path)
    with client:
        worker = adapter(root, client, provider, budget)
        try:
            receipt = worker.one_cycle()
            state = json.loads(worker.state_path.read_bytes())
            assert provider.calls == 1 and receipt == state["acknowledged"]
            assert state["outbox"]["completion"]["scientific_status"] == "not_assessed"
            assert worker.one_cycle()["status"] == "empty_claim" and provider.calls == 1
        finally:
            worker.close()


def test_wrong_implementation_hash_rejects_job_before_inference(tmp_path):
    root, client, provider, budget = setup(tmp_path, wrong_code=True)
    with client:
        worker = adapter(root, client, provider, budget)
        try:
            with pytest.raises(WorkerStopped, match="binding_mismatch"):
                worker.one_cycle()
            assert provider.calls == 0
        finally:
            worker.close()


def test_lost_completion_ack_replays_exact_outbox_without_reinference(tmp_path):
    root, client, provider, budget = setup(tmp_path)

    class LoseOnce:
        lost = False

        def request(self, method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            if path.endswith("/complete") and not self.lost:
                self.lost = True
                raise httpx.ReadTimeout(
                    "synthetic ACK loss after durable server completion"
                )
            return response

    with client:
        worker = adapter(root, LoseOnce(), provider, budget)
        try:
            with pytest.raises(httpx.ReadTimeout):
                worker.one_cycle()
        finally:
            worker.close()
        restarted = adapter(root, client, provider, budget)
        try:
            receipt = restarted.one_cycle()
            assert (
                receipt == json.loads(restarted.state_path.read_bytes())["acknowledged"]
            )
            assert provider.calls == 1
        finally:
            restarted.close()
