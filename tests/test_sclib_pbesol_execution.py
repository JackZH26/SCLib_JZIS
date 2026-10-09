"""One-shot adapter tests use an in-memory service and mocked solver processes.

No actual QE, installed node, authenticated remote capture or scientific result.
"""

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/tests"))

import test_sclib_pbesol_native_contract as envelope_tests
import test_sclib_pbesol_profile as binding_tests
from pbesol_init_fixtures import initialization_outputs
from sclib_compute import (
    native_supervisor,
    native_worker,
    pbesol_execution,
    pbesol_supervisor,
)
from sclib_compute.api import AuthConfig, Principal, ServiceConfig, create_app
from sclib_compute.contracts import JobSpec, canonical
from sclib_compute.native_contract import NativeRuntime
from sclib_compute.pbesol_execution import (
    PbesolWorker,
    load_profile,
    sha,
)
from sclib_compute.pbesol_result_custody import (
    CoordinatorPins,
    validate_returned_initialization,
)
from sclib_compute.store import Limits, Store
from sclib_compute.worker import atomic_json

synthetic = binding_tests.synthetic
SID = "agm001228974"


@pytest.fixture
def environment(tmp_path, synthetic, monkeypatch):
    root = tmp_path.resolve()
    executable = root / "unused-executable"
    executable.write_bytes(b"mocked executable; must never actually run\n")
    executable.chmod(0o700)
    runtime = NativeRuntime(
        runtime_id="fixture-pbesol-runtime",
        pw={"path": str(executable), "sha256": sha(executable.read_bytes())},
        mpiexec={"path": str(executable), "sha256": sha(executable.read_bytes())},
        max_wall_seconds=900,
        min_free_bytes=1024**2,
        min_available_memory_bytes=1024**2,
    )
    runtime_raw = canonical(runtime.model_dump(mode="json"))
    (root / "runtime.json").write_bytes(runtime_raw)
    release_raw = canonical(
        {"synthetic_release": True, "installed_contents_verified": False}
    )
    (root / "release.json").write_bytes(release_raw)
    profile_raw = canonical(
        {
            "schema_version": "sclib-pbesol-local-profile/1",
            "method_profile": "pbesol-source-coarse-qe75/1",
            "stage": "initialize",
            "runtime_id": runtime.runtime_id,
            "runtime_config_path": str(root / "runtime.json"),
            "runtime_config_sha256": sha(runtime_raw),
            "adapter_release_manifest_path": str(root / "release.json"),
            "adapter_release_manifest_sha256": sha(release_raw),
        }
    )
    profile_path = root / "profile.json"
    profile_path.write_bytes(profile_raw)
    for name in ("runtime.json", "release.json", "profile.json"):
        (root / name).chmod(0o600)
    profile = load_profile(profile_path, sha(profile_raw))
    spec, inputs = envelope_tests.fixture_job(
        SID, "initialize", synthetic[0][SID, "initialize"]
    )
    spec = JobSpec.model_validate(
        {**spec.model_dump(mode="json"), "deadline_unix": int(time.time()) + 600}
    )
    store = Store(
        root / "store",
        Limits(
            max_wall_seconds=900,
            max_memory_bytes=16 * 1024**3,
            max_artifact_bytes=8 * 1024**2,
            max_output_bytes=32 * 1024**2,
            total_cpu_core_seconds=10000,
            min_free_bytes=1,
        ),
    )
    for raw in inputs.values():
        store.put_blob(raw, sha(raw))
    store.enqueue(spec)
    app = create_app(
        store,
        ServiceConfig(
            auth=AuthConfig(
                mode="loopback_test",
                test_bearer_sha256_principals={
                    sha(b"pbesol-test"): Principal(
                        role="node",
                        node_id="pbesol-test",
                        runtime_id=runtime.runtime_id,
                        capabilities=["qe_initialize"],
                    )
                },
            ),
            enabled_job_kinds=["qe_initialize"],
        ),
    )
    client = TestClient(
        app, client=("127.0.0.1", 5000), headers={"Authorization": "Bearer pbesol-test"}
    )
    xml, stdout = initialization_outputs(json.loads(inputs["preparation.json"]))
    xml_raw = pbesol_execution.ET.tostring(xml)
    calls = []

    def popen(argv, **kwargs):
        calls.append(argv)
        kwargs["stdout"].write(stdout)
        kwargs["stderr"].write(b"")
        prefix = json.loads(inputs["pbesol-input-binding.json"])["prefix"]
        target = Path(kwargs["cwd"]) / "out" / (prefix + ".save")
        target.mkdir()
        (target / "data-file-schema.xml").write_bytes(xml_raw)
        return SimpleNamespace(pid=987654, poll=lambda: 0, wait=lambda **_: 0)

    monkeypatch.setattr(native_supervisor.subprocess, "Popen", popen)
    monkeypatch.setattr(native_supervisor, "processes", dict)
    # Resource observations are explicitly controlled fixture values.
    monkeypatch.setattr(
        native_supervisor, "available_memory_bytes", lambda: 48 * 1024**3
    )
    monkeypatch.setattr(native_worker, "available_memory_bytes", lambda: 48 * 1024**3)
    monkeypatch.setattr(
        pbesol_supervisor, "available_memory_bytes", lambda: 48 * 1024**3
    )
    monkeypatch.setattr(
        native_worker.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=100 * 1024**3),
    )
    env = SimpleNamespace(
        root=root,
        profile=profile,
        runtime=runtime,
        runtime_raw=runtime_raw,
        release_raw=release_raw,
        profile_raw=profile_raw,
        spec=spec,
        inputs=inputs,
        client=client,
        store=store,
        calls=calls,
    )
    yield env
    client.close()


def make_worker(env, client=None):
    worker = PbesolWorker(
        client or env.client, env.root / "worker", env.profile.path, env.profile.sha256
    )

    def direct_guardian(state, spec, attempt_dir):
        lease = worker.heartbeat(
            state["claim"], "running", worker.elapsed(state["claim"])
        )
        atomic_json(
            attempt_dir / "lease.json", {"lease_until_unix": lease["lease_until_unix"]}
        )
        read_fd, write_fd = os.pipe()
        try:
            pbesol_supervisor.run_guardian(
                attempt_dir / "request.json",
                read_fd,
                env.profile.path,
                env.profile.sha256,
            )
        finally:
            os.close(read_fd)
            os.close(write_fd)

    worker.run_guardian = direct_guardian
    return worker


def attempt_path(env):
    return next((env.root / "worker").glob("attempt-*"))


def test_mocked_initialization_roundtrip_has_matching_custody(environment):
    env = environment
    worker = make_worker(env)
    try:
        receipt = worker.one_cycle()
    finally:
        worker.close()
    assert receipt["status"] == "returned" and receipt["solver_outcome"] == "success"
    assert len(env.calls) == 1
    attempt = attempt_path(env)
    outputs = {path.name: path.read_bytes() for path in (attempt / "return").iterdir()}
    record = json.loads(outputs["execution.json"])
    assert record["schema_version"] == "sclib-pbesol-qe-execution/1"
    assert (
        record["adapter_release_manifest_sha256"]
        == env.profile.config.adapter_release_manifest_sha256
    )
    assert record["preparation_phase"] == "initialize"
    # The service export format is captured from the owned test store only.
    with env.store.connection() as db:
        job = dict(
            db.execute(
                "SELECT * FROM jobs WHERE job_id=?", (env.spec.job_id,)
            ).fetchone()
        )
        attempt_row = dict(
            db.execute(
                "SELECT * FROM attempts WHERE attempt_id=?", (receipt["attempt_id"],)
            ).fetchone()
        )
        pins = [
            dict(row)
            for row in db.execute(
                "SELECT name,bytes,sha256 FROM artifacts WHERE attempt_id=? ORDER BY name",
                (receipt["attempt_id"],),
            )
        ]
    job["spec"] = json.loads(job["spec"])
    attempt_row["receipt"] = json.loads(attempt_row["receipt"])
    export = {"job": job, "attempt": attempt_row, "files": pins}
    raw_export = canonical(export)
    submitted = canonical(env.spec.model_dump(mode="json"))
    report = validate_returned_initialization(
        raw_export,
        env.inputs,
        outputs,
        submitted_spec_bytes=submitted,
        runtime_config_bytes=env.runtime_raw,
        adapter_release_manifest_bytes=env.release_raw,
        expected=CoordinatorPins(
            sha(raw_export),
            sha(submitted),
            sha(env.runtime_raw),
            sha(env.release_raw),
            "pbesol-test",
            receipt["attempt_id"],
            receipt["fencing_token"],
            str(attempt),
        ),
    )
    assert report["rejection"] is None, report
    assert (
        report["custody_verified"] is True
        and report["semantic_reading_status"] == "initialization_only"
    )
    assert report["coordinator_capture_authenticated"] is None
    assert (
        report["scientific_acceptance"]
        is report["execution_consistency_ready_for_review"]
        is False
    )


@pytest.mark.parametrize(
    "target",
    [
        "input.in",
        "pseudo/Ti.upf",
        "out",
        "tmp",
        "lease",
        "deadline",
        "profile",
        "memory",
        "disk",
        "lease_after_resources",
    ],
)
def test_last_moment_change_blocks_process_and_returns_failed_capture(
    environment, monkeypatch, target
):
    env = environment
    original = pbesol_supervisor.supervise

    def alter_then_supervise(request, parent_fd, **kwargs):
        work = Path(request["work"])
        if target in {"input.in", "pseudo/Ti.upf"}:
            (work / target).write_bytes(b"changed after validation")
        elif target in {"out", "tmp"}:
            (work / target).rmdir()
            (work / target).symlink_to(env.root)
        elif target == "lease":
            atomic_json(
                work.parent / "lease.json", {"lease_until_unix": time.time() - 1}
            )
        elif target == "deadline":
            request["launch_deadline_unix"] = time.time() - 1
        elif target == "memory":
            monkeypatch.setattr(pbesol_supervisor, "available_memory_bytes", lambda: 0)
        elif target == "disk":
            monkeypatch.setattr(
                pbesol_supervisor.shutil,
                "disk_usage",
                lambda path: SimpleNamespace(
                    free=0 if Path(path) == work else 100 * 1024**3
                ),
            )
        elif target == "lease_after_resources":
            clock = [time.time()]
            atomic_json(work.parent / "lease.json", {"lease_until_unix": clock[0] + 3})
            monkeypatch.setattr(
                pbesol_supervisor, "time", SimpleNamespace(time=lambda: clock[0])
            )

            def delayed_resource_observation():
                clock[0] += 5
                return 48 * 1024**3

            monkeypatch.setattr(
                pbesol_supervisor,
                "available_memory_bytes",
                delayed_resource_observation,
            )
        else:
            (env.root / "release.json").write_bytes(b"changed local release")
        return original(request, parent_fd, **kwargs)

    monkeypatch.setattr(pbesol_supervisor, "supervise", alter_then_supervise)
    worker = make_worker(env)
    try:
        if target == "profile":
            with pytest.raises(ValueError, match="checksum"):
                worker.one_cycle()
            # Restore the independently retained old configuration, never relabel it.
            (env.root / "release.json").write_bytes(env.release_raw)
            assert worker.one_cycle()["solver_outcome"] == "interrupted"
        else:
            assert worker.one_cycle()["solver_outcome"] == "interrupted"
    finally:
        worker.close()
    assert env.calls == []
    path = attempt_path(env)
    assert json.loads((path / "solver-result.json").read_bytes())["exit_code"] is None
    record = json.loads((path / "return/execution.json").read_bytes())
    assert record["solver_outcome"] == "interrupted"
    assert record["capture"]["data-file-schema.xml"]["present"] is False


class LostComplete:
    def __init__(self, client):
        self.client = client

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if path.endswith("/complete"):
            raise httpx.ReadTimeout("fixture lost completed ACK")
        return response


def test_ack_replay_retains_old_identity_without_requiring_live_binary(environment):
    env = environment
    worker = make_worker(env, LostComplete(env.client))
    try:
        with pytest.raises(httpx.ReadTimeout):
            worker.one_cycle()
    finally:
        worker.close()
    path = attempt_path(env)
    frozen = (path / "return/execution.json").read_bytes()
    Path(env.runtime.pw.path).write_bytes(b"binary upgraded after completed execution")
    worker = make_worker(env)
    try:
        assert worker.one_cycle()["status"] == "returned"
    finally:
        worker.close()
    assert len(env.calls) == 1
    assert (path / "return/execution.json").read_bytes() == frozen


def test_partial_outbox_recovery_reuses_frozen_bytes_without_process(
    environment, monkeypatch
):
    env = environment
    write_once = native_worker.write_once
    failed = []

    def fail_one_output(path, data):
        if path.parent.name == "return" and path.name == "stderr.txt" and not failed:
            failed.append(True)
            raise OSError("fixture interrupted partial outbox")
        return write_once(path, data)

    monkeypatch.setattr(native_worker, "write_once", fail_one_output)
    worker = make_worker(env)
    try:
        with pytest.raises(OSError, match="partial outbox"):
            worker.one_cycle()
    finally:
        worker.close()
    path = attempt_path(env)
    frozen = (path / "execution-final.json").read_bytes()
    (path / "work/input.in").write_bytes(
        b"work is no longer an input authority after completion"
    )
    worker = make_worker(env)
    try:
        assert worker.one_cycle()["solver_outcome"] == "success"
    finally:
        worker.close()
    assert len(env.calls) == 1
    assert (path / "return/execution.json").read_bytes() == frozen


def test_recovery_refuses_corrupted_original_input_evidence(environment):
    env = environment
    worker = make_worker(env, LostComplete(env.client))
    try:
        with pytest.raises(httpx.ReadTimeout):
            worker.one_cycle()
    finally:
        worker.close()
    (attempt_path(env) / "input-evidence/input.in").write_bytes(
        b"corrupted immutable input archive"
    )
    worker = make_worker(env)
    try:
        with pytest.raises(ValueError, match="pin mismatch"):
            worker.one_cycle()
    finally:
        worker.close()
    assert len(env.calls) == 1


def test_scf_envelope_cannot_reach_new_profile(environment):
    env = environment
    scf = JobSpec.model_validate({**env.spec.model_dump(mode="json"), "kind": "qe_scf"})
    worker = make_worker(env)
    try:
        with pytest.raises(ValueError, match="initialization only"):
            worker.validate_input(scf, env.inputs)
        with pytest.raises(ValueError, match="initialization only"):
            worker.validate_recovery({}, scf, env.root)
    finally:
        worker.close()
    assert env.calls == []


def test_opaque_release_never_selects_module_or_command(environment):
    env = environment
    worker = make_worker(env)
    try:
        assert worker.guardian_module == "sclib_compute.pbesol_supervisor"
        assert worker.capabilities == ("qe_initialize",)
        assert worker.guardian_args() == [
            "--profile-config",
            env.profile.path,
            "--profile-sha256",
            env.profile.sha256,
        ]
    finally:
        worker.close()


def test_recovery_rejects_missing_profile_or_changed_saved_descriptor(environment):
    env = environment
    worker = make_worker(env, LostComplete(env.client))
    try:
        with pytest.raises(httpx.ReadTimeout):
            worker.one_cycle()
    finally:
        worker.close()
    state_path = env.root / "worker/state.json"
    state = json.loads(state_path.read_bytes())
    state["execution_started"]["local_profile"]["profile_sha256"] = "0" * 64
    atomic_json(state_path, state)
    worker = make_worker(env)
    try:
        with pytest.raises(ValueError, match="identity differs"):
            worker.one_cycle()
    finally:
        worker.close()
    assert len(env.calls) == 1


@pytest.mark.parametrize(
    "raw",
    [
        b"<espresso>\x00</espresso>",
        b'<!DOCTYPE x [<!ENTITY p "small">]><x>&p;</x>',
        '<?xml version="1.0"?><x/>'.encode("utf-16-le"),
    ],
)
def test_pbesol_capture_uses_safe_xml_domain(raw, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unsafe XML reached parser")

    monkeypatch.setattr(
        pbesol_execution,
        "ET",
        SimpleNamespace(fromstring=forbidden, ParseError=ValueError),
    )
    assert PbesolWorker.xml_parseable(raw) is False
