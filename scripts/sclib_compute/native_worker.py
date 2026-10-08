"""Durable native QE worker. Never reruns an attempt after execution started."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from .contracts import Completion, FilePin, JobSpec, canonical, digest
from .native_contract import (
    NativeRuntime,
    available_memory_bytes,
    read_regular,
    validate_inputs,
)
from .native_supervisor import kill_tree
from .worker import DummyWorker, WorkerStopped, atomic_json


def write_once(path: Path, data: bytes):
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def sync_directory(path: Path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def directory(path: Path):
    if path.is_symlink():
        raise ValueError("native directory must not be a symlink")
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir() or path.stat().st_mode & 0o077:
        raise ValueError("native directory must be owner-only")
    sync_directory(path.parent)


class NativeWorker(DummyWorker):
    def __init__(self, client, root: Path, runtime: NativeRuntime):
        super().__init__(
            client,
            root,
            runtime_id=runtime.runtime_id,
            platform="macos_arm64" if sys.platform == "darwin" else "linux_x86_64",
        )
        self.runtime = runtime
        self.stop_requested = False

    def heartbeat(self, claim, phase, elapsed, memory=0):
        attempt = claim["attempt"]
        result = self.request(
            "POST",
            f"/attempts/{attempt['attempt_id']}/heartbeat",
            json={
                "fencing_token": attempt["fencing_token"],
                "phase": phase,
                "elapsed_seconds": min(86400, elapsed),
                "observed_memory_bytes": memory,
            },
        ).json()
        if not result["continue"]:
            raise WorkerStopped("server ended native lease")
        return result

    def one_cycle(self):
        self.request(
            "POST",
            "/nodes/register",
            json={
                "runtime_id": self.runtime_id,
                "capabilities": ["qe_initialize", "qe_scf"],
                "platform": self.platform,
            },
        )
        state = (
            json.loads(read_regular(self.state_path, 256 * 1024))
            if self.state_path.exists()
            else {}
        )
        if state.get("acknowledged") or state.get("abandoned"):
            state = {}
        if "claim_request_id" not in state:
            if available_memory_bytes() < self.runtime.min_available_memory_bytes:
                return {
                    "status": "local_resource_wait",
                    "reason": "available_memory_below_launch_floor",
                }
            if (
                shutil.disk_usage(self.root).free
                < self.runtime.min_free_bytes + self.runtime.max_scratch_bytes
            ):
                return {"status": "local_resource_wait", "reason": "insufficient_disk"}
        if "claim_request_id" not in state:
            state = {
                "schema_version": "sclib-native-worker-state/1",
                "claim_request_id": "claim-" + uuid.uuid4().hex,
            }
            self.persist(state)
        if "claim" not in state:
            state["claim"] = self.request(
                "POST",
                "/jobs/claim",
                json={"claim_request_id": state["claim_request_id"]},
            ).json()
            self.persist(state)
        claim = state["claim"]
        if claim["attempt"] is None:
            state["acknowledged"] = {"status": "empty_claim"}
            self.persist(state)
            return state["acknowledged"]
        spec = JobSpec.model_validate(claim["job"])
        if spec.input_manifest_sha256 != claim["input_manifest_sha256"]:
            raise WorkerStopped("native input binding mismatch")
        attempt = claim["attempt"]
        # Pydantic JobSpec fixes the job ID, but validate server-generated attempt
        # ID too before using it in a local path.
        if not re.fullmatch(r"attempt-[0-9a-f]{32}", attempt["attempt_id"]):
            raise WorkerStopped("invalid native attempt ID")
        attempt_dir = self.root / attempt["attempt_id"]
        directory(attempt_dir)
        if "outbox" not in state:
            current = self.request("GET", f"/attempts/{attempt['attempt_id']}").json()
            if current.get("receipt"):
                state["acknowledged"] = current["receipt"]
                self.persist(state)
                return current["receipt"]
            if state.get("execution_started"):
                # A previous worker may have died. Its pipe EOF stops the guardian.
                # Complete saved results can be archived; incomplete work is an
                # explicit interruption. It is NEVER restarted from a checkpoint.
                deadline = time.monotonic() + 10
                while (
                    not (attempt_dir / "solver-result.json").exists()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.1)
                if not (attempt_dir / "solver-result.json").exists():
                    # If both worker and guardian were killed, saved PIDs may
                    # have been reused. Never blindly signal them or move to the
                    # next job. Keep this attempt blocked for verified operator
                    # cleanup; the LaunchDaemon must stop the complete job tree.
                    raise WorkerStopped(
                        "guardian result missing; operator must verify process cleanup before recovery"
                    )
                self.prepare_outbox(state, spec, attempt_dir)
            else:
                if current["attempt"]["status"] not in {"leased", "preparing"}:
                    state["abandoned"] = {
                        "status": current["attempt"]["status"],
                        "reason": "old_claim_not_executed",
                    }
                    self.persist(state)
                    return state["abandoned"]
                self.runtime.validate_job(spec)
                if (
                    shutil.disk_usage(self.root).free
                    < self.runtime.min_free_bytes + self.runtime.max_scratch_bytes
                ):
                    raise WorkerStopped(
                        "insufficient local disk before native execution"
                    )
                self.heartbeat(claim, "preparing", self.elapsed(claim))
                files = {}
                for pin in spec.input_artifacts:
                    files[pin.name] = self.request(
                        "GET",
                        f"/attempts/{attempt['attempt_id']}/inputs/{pin.name}",
                        headers={
                            "X-SCLib-Fencing-Token": str(attempt["fencing_token"])
                        },
                    ).content
                    if (
                        len(files[pin.name]) != pin.bytes
                        or hashlib.sha256(files[pin.name]).hexdigest() != pin.sha256
                    ):
                        raise WorkerStopped("native download checksum mismatch")
                    self.heartbeat(claim, "preparing", self.elapsed(claim))
                descriptor = validate_inputs(spec, files)
                work = attempt_dir / "work"
                # Interrupted preparation is safe to repeat only before durable
                # execution_started. No solver has run and the exact pins are read again.
                if work.exists():
                    if work.is_symlink():
                        raise WorkerStopped("symlink in native work path")
                    shutil.rmtree(work)
                directory(work)
                for name in ["pseudo", "out", "tmp"]:
                    directory(work / name)
                for name, data in files.items():
                    write_once(
                        (work / "pseudo" / name)
                        if name in descriptor.pseudo_names
                        else (work / name),
                        data,
                    )
                atomic_json(
                    attempt_dir / "descriptor.json", descriptor.model_dump(mode="json")
                )
                remaining = min(
                    spec.resources.wall_seconds - self.elapsed(claim),
                    spec.deadline_unix - time.time(),
                )
                if remaining <= 1:
                    raise WorkerStopped("native envelope expired during preparation")
                atomic_json(
                    attempt_dir / "request.json",
                    {
                        "runtime": self.runtime.model_dump(mode="json"),
                        "spec": spec.model_dump(mode="json"),
                        "descriptor": descriptor.model_dump(mode="json"),
                        "work": str(work),
                        "remaining_wall_seconds": remaining,
                    },
                )
                state["execution_started"] = {
                    "at_unix": time.time(),
                    "runtime": self.runtime.model_dump(mode="json"),
                }
                self.persist(state)  # durable BEFORE launching any native process
                self.run_guardian(state, spec, attempt_dir)
                self.prepare_outbox(state, spec, attempt_dir)
        return self.upload(state, spec, attempt_dir)

    @staticmethod
    def elapsed(claim):
        return max(0, int(time.time() - claim["attempt"]["started_at_unix"]))

    def run_guardian(self, state, spec, attempt_dir):
        claim = state["claim"]
        read_fd, write_fd = os.pipe()
        guardian = None
        stop_reason = None
        try:
            lease = self.heartbeat(claim, "running", self.elapsed(claim))
            atomic_json(
                attempt_dir / "lease.json",
                {"lease_until_unix": lease["lease_until_unix"]},
            )
            env = {
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                "LC_ALL": "C",
            }
            with (attempt_dir / "guardian.log").open("xb") as log:
                guardian = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "sclib_compute.native_supervisor",
                        "--request",
                        str(attempt_dir / "request.json"),
                        "--parent-fd",
                        str(read_fd),
                    ],
                    pass_fds=(read_fd,),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                os.close(read_fd)
                read_fd = -1
                next_heartbeat = time.monotonic() + self.runtime.heartbeat_seconds
                while guardian.poll() is None:
                    if time.monotonic() >= next_heartbeat:
                        progress = (
                            json.loads(
                                read_regular(attempt_dir / "progress.json", 4096)
                            )
                            if (attempt_dir / "progress.json").exists()
                            else {}
                        )
                        memory = progress.get("observed_memory_bytes", 0)
                        # The guardian independently handles memory excess; don't
                        # disguise an over-limit observation as a valid heartbeat.
                        if memory > spec.resources.memory_bytes:
                            raise WorkerStopped("native memory limit exceeded")
                        lease = self.heartbeat(
                            claim, "running", self.elapsed(claim), memory
                        )
                        atomic_json(
                            attempt_dir / "lease.json",
                            {"lease_until_unix": lease["lease_until_unix"]},
                        )
                        next_heartbeat = (
                            time.monotonic() + self.runtime.heartbeat_seconds
                        )
                    time.sleep(0.1)
        except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 -- close guardian pipe on any worker fault
            stop_reason = "worker_stop:" + type(exc).__name__
            if isinstance(exc, KeyboardInterrupt):
                self.stop_requested = True
        finally:
            if read_fd >= 0:
                os.close(read_fd)
            os.close(write_fd)  # EOF independently cancels the full solver tree
            if guardian is not None:
                try:
                    guardian.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    guardian.terminate()
                    try:
                        guardian.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        guardian.kill()
                        guardian.wait(timeout=5)
            if not (attempt_dir / "solver-result.json").exists():
                # Guardian died unexpectedly: its recorded dedicated process group
                # is also killed by the still-live worker before archiving failure.
                process_file = attempt_dir / "process.json"
                if process_file.exists():
                    process = json.loads(read_regular(process_file, 8192))
                    kill_tree(process["pid"])
                atomic_json(
                    attempt_dir / "solver-result.json",
                    {
                        "schema_version": "sclib-native-process/1",
                        "reason": stop_reason or "guardian_exit_without_result",
                        "exit_code": None,
                        "elapsed_seconds": 0,
                        "peak_memory_bytes": 0,
                        "argv": [],
                        "thread_environment": {},
                    },
                )
            if stop_reason:
                atomic_json(attempt_dir / "worker-stop.json", {"reason": stop_reason})

    def prepare_outbox(self, state, spec, attempt_dir):
        work = attempt_dir / "work"
        descriptor = json.loads(read_regular(attempt_dir / "descriptor.json", 8192))
        process = json.loads(read_regular(attempt_dir / "solver-result.json", 32768))
        rules = {rule.name: rule.max_bytes for rule in spec.output_rules}
        capture, files = {}, {}
        for name, path in {
            "stdout.txt": work / "stdout.txt",
            "stderr.txt": work / "stderr.txt",
            "data-file-schema.xml": work
            / "out"
            / (descriptor["prefix"] + ".save")
            / "data-file-schema.xml",
        }.items():
            if not path.exists():
                files[name] = b""
                capture[name] = {
                    "present": False,
                    "truncated": False,
                    "original_bytes": None,
                }
            else:
                size = path.stat().st_size
                # Full files in every normal return. On bound violations retain
                # raw files locally and explicitly expose only a bounded prefix.
                if size > rules[name]:
                    for parent in [path, *path.parents]:
                        if parent.is_symlink():
                            raise WorkerStopped("symlink in solver output")
                    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                    with os.fdopen(fd, "rb") as stream:
                        files[name] = stream.read(rules[name])
                else:
                    files[name] = read_regular(path, rules[name])
                capture[name] = {
                    "present": True,
                    "truncated": size > rules[name],
                    "original_bytes": size,
                }
        stdout = files["stdout.txt"].decode("utf-8", errors="replace")
        xml_parseable = False
        if (
            files["data-file-schema.xml"]
            and not capture["data-file-schema.xml"]["truncated"]
        ):
            try:
                # QE emits no DTD. Reject declarations instead of permitting
                # entity expansion in a result supplied by an external binary.
                xml = files["data-file-schema.xml"]
                if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                    raise ValueError("XML declaration")
                ET.fromstring(xml)
                xml_parseable = True
            except (ET.ParseError, ValueError):
                pass
        version_seen = bool(re.search(r"Program\s+PWSCF\s+v\.7\.5(?:\s|\b)", stdout))
        job_done = "JOB DONE." in stdout
        scf_converged = bool(
            re.search(r"convergence has been achieved", stdout, re.IGNORECASE)
        )
        not_converged = bool(
            re.search(
                r"convergence NOT achieved|convergence has NOT been achieved",
                stdout,
                re.IGNORECASE,
            )
        )
        interrupted = process["reason"] != "completed" or any(
            item["truncated"] for item in capture.values()
        )
        if interrupted:
            outcome = "interrupted"
        elif not_converged:
            outcome = "not_converged"
        elif (
            process["exit_code"] != 0
            or not version_seen
            or not job_done
            or not xml_parseable
            or any(not item["present"] for item in capture.values())
            or (spec.kind == "qe_scf" and not scf_converged)
        ):
            outcome = "solver_failure"
        else:
            outcome = "success"
        elapsed = min(
            86400,
            max(self.elapsed(state["claim"]), math.ceil(process["elapsed_seconds"])),
        )
        runtime = state["execution_started"]["runtime"]
        execution = {
            "schema_version": "sclib-native-qe-execution/1",
            "adapter_version": "native-qe/1",
            "job_id": spec.job_id,
            "attempt_id": state["claim"]["attempt"]["attempt_id"],
            "fencing_token": state["claim"]["attempt"]["fencing_token"],
            "kind": spec.kind,
            "runtime_id": spec.runtime_id,
            "runtime_pins": runtime,
            "runtime_config_sha256": digest(runtime),
            "input_manifest_sha256": spec.input_manifest_sha256,
            "input_manifest": [
                pin.model_dump(mode="json") for pin in spec.input_artifacts
            ],
            "solver_outcome": outcome,
            "process": process,
            "elapsed_seconds": elapsed,
            "capture": capture,
            "checks": {
                "pwscf_7_5_seen": version_seen,
                "job_done_seen": job_done,
                "xml_parseable": xml_parseable,
                "scf_convergence_message": scf_converged,
            },
            "artifacts": [
                {
                    "name": name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
                for name, data in sorted(files.items())
            ],
            "restart_mode": "from_scratch",
            "checkpoint_resume": False,
            "shell_execution": False,
            "scientific_status": "not_assessed",
            "scientific_publication_authority": False,
            "limitations": [
                "Execution checks do not establish numerical convergence or scientific validity.",
                "RSS, disk and output limits are sampled watchdog bounds; no hard memory reservation is claimed.",
                "Interrupted outputs are retained as failed evidence and must not be imported as complete scientific results.",
            ],
        }
        final_path = attempt_dir / "execution-final.json"
        if final_path.exists():
            # Freeze elapsed time and exact metadata before any partial outbox
            # write; a crash while writing files must replay identical bytes.
            execution = json.loads(read_regular(final_path, rules["execution.json"]))
            elapsed = execution["elapsed_seconds"]
            outcome = execution["solver_outcome"]
        else:
            atomic_json(final_path, execution)
        files["execution.json"] = canonical(execution)
        if len(files["execution.json"]) > rules["execution.json"]:
            raise WorkerStopped("execution receipt exceeds frozen output rule")
        out = attempt_dir / "return"
        directory(out)
        for name, data in files.items():
            if (out / name).exists():
                if read_regular(out / name, rules[name]) != data:
                    raise WorkerStopped("immutable native outbox changed")
            else:
                write_once(out / name, data)
        manifest = [
            FilePin(name=name, sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
            for name, body in sorted(files.items())
        ]
        completion = Completion(
            fencing_token=state["claim"]["attempt"]["fencing_token"],
            input_manifest_sha256=spec.input_manifest_sha256,
            runtime_id=spec.runtime_id,
            manifest=manifest,
            solver_outcome=outcome,
            elapsed_seconds=elapsed,
        )
        state["outbox"] = {"completion": completion.model_dump(mode="json")}
        self.persist(state)

    def upload(self, state, spec, attempt_dir):
        attempt = state["claim"]["attempt"]
        completion = Completion.model_validate(state["outbox"]["completion"])
        # No heartbeat is needed for a saved outbox: stale results are deliberately
        # uploaded for quarantine, and a lost accepted ACK replays the same receipt.
        for pin in completion.manifest:
            try:
                self.heartbeat(
                    state["claim"], "uploading", self.elapsed(state["claim"])
                )
            except WorkerStopped:
                # Ended leases and already-accepted ACK replays still upload the
                # exact outbox for the server's receipt/quarantine decision.
                pass
            data = read_regular(attempt_dir / "return" / pin.name, pin.bytes)
            if len(data) != pin.bytes or hashlib.sha256(data).hexdigest() != pin.sha256:
                raise WorkerStopped("native durable outbox corrupted")
            self.request(
                "PUT",
                f"/attempts/{attempt['attempt_id']}/outputs/{pin.name}",
                content=data,
                headers={
                    "X-SCLib-Fencing-Token": str(attempt["fencing_token"]),
                    "X-SCLib-Content-SHA256": pin.sha256,
                },
            )
        receipt = self.request(
            "POST",
            f"/attempts/{attempt['attempt_id']}/complete",
            json=completion.model_dump(mode="json"),
        ).json()
        if receipt.get("completion_sha256") != digest(
            completion.model_dump(mode="json")
        ):
            raise WorkerStopped("native completion receipt hash mismatch")
        atomic_json(attempt_dir / "receipt.json", receipt)
        atomic_json(
            attempt_dir / "archive.json",
            {
                "schema_version": "sclib-native-archive/1",
                "receipt_sha256": digest(receipt),
                "completion_sha256": digest(completion.model_dump(mode="json")),
                "manifest_sha256": digest(
                    [pin.model_dump(mode="json") for pin in completion.manifest]
                ),
                "manifest": [
                    pin.model_dump(mode="json") for pin in completion.manifest
                ],
            },
        )
        state["acknowledged"] = receipt
        self.persist(state)
        return receipt
