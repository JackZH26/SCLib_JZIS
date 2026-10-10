"""NER adapter for the existing private, fenced, outbox-based compute transport."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from scripts.sclib_compute.contracts import Closed, Completion, FilePin, JobSpec, Sha256
from scripts.sclib_compute.worker import DummyWorker, WorkerStopped

from . import PARSER_VERSION
from .blocks import verify_document
from .contract import canonical, digest, schema
from .ledger import Ledger
from .pipeline import Budget, Pipeline, implementation_hash
from .providers import MODEL, REVISION


class NERJob(Closed):
    schema_version: Literal["sclib-ner-job/1"] = "sclib-ner-job/1"
    paper_id: Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[^\x00-\x1f]+$")]
    work_id: Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[^\x00-\x1f]+$")]
    source_sha256: Sha256
    document_manifest_sha256: Sha256
    implementation_sha256: Sha256
    schema_sha256: Sha256
    provider_config_sha256: Sha256
    budget_sha256: Sha256
    model_manifest_sha256: Sha256
    runtime_lock_sha256: Sha256
    transfer_allowed: Literal[True]
    local_inference_allowed: Literal[True]


class NERWorker(DummyWorker):
    """Reuses durable transport primitives, with a separate NER execution path.

    The caller owns the model session and host-wide heavy lock for bounded cycles.
    No model download, arbitrary command, cloud key or scientific DB access occurs here.
    """

    def __init__(
        self,
        client,
        root: Path,
        provider,
        *,
        runtime_id,
        model_manifest_sha256,
        runtime_lock_sha256,
        budget=None,
        memory=lambda: 0,
    ):
        super().__init__(client, root, runtime_id=runtime_id, platform="macos_arm64")
        self.provider, self.budget = provider, budget or Budget()
        if (
            provider.config.provider != "local_mlx"
            or provider.config.model != MODEL
            or provider.config.revision != REVISION
            or provider.config.endpoint is not None
        ):
            self.close()
            raise ValueError("compute_requires_pinned_in_process_mlx")
        self.model_manifest_sha256, self.runtime_lock_sha256 = (
            model_manifest_sha256,
            runtime_lock_sha256,
        )
        self.memory = memory

    def heartbeat(self, claim, phase, elapsed):
        attempt = claim["attempt"]
        result = self.request(
            "POST",
            f"/attempts/{attempt['attempt_id']}/heartbeat",
            json={
                "fencing_token": attempt["fencing_token"],
                "phase": phase,
                "elapsed_seconds": elapsed,
                "observed_memory_bytes": self.memory(),
            },
        ).json()
        if not result["continue"]:
            raise WorkerStopped("server_ended_ner_lease")
        return result

    def _spec(self, claim):
        spec = JobSpec.model_validate(claim["job"])
        if (
            spec.kind != "ner_qwen_mlx"
            or spec.runtime_id != self.runtime_id
            or spec.input_manifest_sha256 != claim["input_manifest_sha256"]
            or {p.name for p in spec.input_artifacts} != {"document.json", "ner-job.json"}
            or {p.name for p in spec.output_rules} != {"result.json", "execution.json"}
            or spec.resources.memory_bytes > 32 * 1024**3
            or spec.resources.cpu_cores > 4
            or spec.resources.wall_seconds < self.budget.paper_seconds
            or spec.resources.wall_seconds > 7200
            or spec.deadline_unix <= time.time()
        ):
            raise WorkerStopped("ner_job_outside_frozen_adapter_envelope")
        return spec

    def one_cycle(self):
        self.request(
            "POST",
            "/nodes/register",
            json={
                "runtime_id": self.runtime_id,
                "capabilities": ["ner_qwen_mlx"],
                "platform": self.platform,
            },
        )
        state = json.loads(self.state_path.read_bytes()) if self.state_path.exists() else {}
        if state.get("acknowledged") or state.get("abandoned"):
            state = {}
        if "claim_request_id" not in state:
            import uuid

            state = {
                "schema_version": "sclib-ner-worker-state/1",
                "claim_request_id": "claim-" + uuid.uuid4().hex,
            }
            self.persist(state)
        if "claim" not in state:
            state["claim"] = self.request(
                "POST", "/jobs/claim", json={"claim_request_id": state["claim_request_id"]}
            ).json()
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
                state["abandoned"] = {
                    "status": current["attempt"]["status"],
                    "reason": "old_claim_not_executed",
                }
                self.persist(state)
                return state["abandoned"]
            spec = self._spec(claim)
            baseline = current["attempt"]["elapsed_seconds"]
            phase = (
                "preparing"
                if current["attempt"]["status"] in {"leased", "preparing"}
                else "running"
            )
            self.heartbeat(claim, phase, baseline)
            inputs = {}
            for pin in spec.input_artifacts:
                data = self.request(
                    "GET",
                    f"/attempts/{attempt['attempt_id']}/inputs/{pin.name}",
                    headers={"X-SCLib-Fencing-Token": str(attempt["fencing_token"])},
                ).content
                if len(data) != pin.bytes or hashlib.sha256(data).hexdigest() != pin.sha256:
                    raise WorkerStopped("ner_input_checksum_mismatch")
                inputs[pin.name] = data
            job = NERJob.model_validate_json(inputs["ner-job.json"])
            document = json.loads(inputs["document.json"])
            verify_document(document)
            if (
                document["source_sha256"] != job.source_sha256
                or document["manifest_sha256"] != job.document_manifest_sha256
                or document["parser_version"] != PARSER_VERSION
                or job.implementation_sha256 != implementation_hash()
                or job.schema_sha256 != digest(schema())
                or job.provider_config_sha256 != self.provider.config.sha256
                or job.budget_sha256 != digest(self.budget.__dict__)
                or job.model_manifest_sha256 != self.model_manifest_sha256
                or job.runtime_lock_sha256 != self.runtime_lock_sha256
            ):
                raise WorkerStopped("ner_job_code_source_runtime_binding_mismatch")
            started, last_heartbeat = time.monotonic(), 0.0
            original_guard = getattr(self.provider, "guard", None)

            def guard():
                nonlocal last_heartbeat
                elapsed = baseline + int(time.monotonic() - started)
                if elapsed > spec.resources.wall_seconds or spec.deadline_unix <= time.time():
                    raise WorkerStopped("ner_execution_budget_exhausted")
                if self.memory() > spec.resources.memory_bytes:
                    raise WorkerStopped("ner_execution_memory_exhausted")
                if original_guard:
                    original_guard()
                if time.monotonic() - last_heartbeat >= 5:
                    self.heartbeat(claim, "running", elapsed)
                    last_heartbeat = time.monotonic()

            self.provider.guard = guard
            ledger = Ledger(self.root / ("ner-" + spec.job_id + ".sqlite"))
            try:
                guard()
                result = Pipeline(self.provider, ledger, budget=self.budget).run(
                    document, paper_id=job.paper_id, work_id=job.work_id
                )
                guard()
            finally:
                self.provider.guard = original_guard
                ledger.close()
            elapsed = baseline + int(time.monotonic() - started)
            outcome = "success" if result["coverage"]["machine_text_complete"] else "solver_failure"
            execution = {
                "adapter": "ner_qwen_mlx",
                "runtime_id": self.runtime_id,
                "scientific_status": "not_assessed",
                "attempt_id": attempt["attempt_id"],
                "fencing_token": attempt["fencing_token"],
                "elapsed_seconds": elapsed,
                "model_manifest_sha256": self.model_manifest_sha256,
                "runtime_lock_sha256": self.runtime_lock_sha256,
                "input_manifest_sha256": spec.input_manifest_sha256,
                "shell_execution": False,
            }
            files = {"result.json": canonical(result), "execution.json": canonical(execution)}
            for rule in spec.output_rules:
                if len(files[rule.name]) > rule.max_bytes:
                    raise WorkerStopped("ner_output_budget_exhausted")
            manifest = [
                FilePin(name=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                for name, data in sorted(files.items())
            ]
            completion = Completion(
                fencing_token=attempt["fencing_token"],
                input_manifest_sha256=spec.input_manifest_sha256,
                runtime_id=self.runtime_id,
                manifest=manifest,
                solver_outcome=outcome,
                elapsed_seconds=elapsed,
            )
            state["outbox"] = {
                "completion": completion.model_dump(mode="json"),
                "files": {name: base64.b64encode(data).decode() for name, data in files.items()},
            }
            self.persist(state)
            self.heartbeat(claim, "uploading", elapsed)
        outbox = state["outbox"]
        for pin in outbox["completion"]["manifest"]:
            data = base64.b64decode(outbox["files"][pin["name"]], validate=True)
            if len(data) != pin["bytes"] or hashlib.sha256(data).hexdigest() != pin["sha256"]:
                raise WorkerStopped("ner_durable_outbox_corrupted")
            self.request(
                "PUT",
                f"/attempts/{attempt['attempt_id']}/outputs/{pin['name']}",
                content=data,
                headers={
                    "X-SCLib-Fencing-Token": str(attempt["fencing_token"]),
                    "X-SCLib-Content-SHA256": pin["sha256"],
                },
            )
        receipt = self.request(
            "POST", f"/attempts/{attempt['attempt_id']}/complete", json=outbox["completion"]
        ).json()
        state["acknowledged"] = receipt
        self.persist(state)
        return receipt
