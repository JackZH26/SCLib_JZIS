"""Native adapter fault tests use pinned executable fixtures, never scientific QE.

Actual M4/QE output/version correctness and 24-hour acceptance are external tests.
"""

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from sclib_compute.api import AuthConfig, Principal, ServiceConfig, create_app
from sclib_compute.contracts import JobSpec, canonical
from sclib_compute.native_contract import NativeRuntime, validate_inputs
from sclib_compute.native_worker import NativeWorker
from sclib_compute.store import Limits, Store


def sha(data):
    return hashlib.sha256(data).hexdigest()


DECK = """&CONTROL
 calculation = 'scf',
 restart_mode = 'from_scratch',
 prefix = 'sclib_test',
 pseudo_dir = './pseudo',
 outdir = './out',
 nstep = 1,
 max_seconds = 10,
 tprnfor = .true.,
 tstress = .true.,
/
&SYSTEM
 ibrav = 0,
 nat = 1,
 ntyp = 1,
 ecutwfc = 20,
 ecutrho = 100,
 tot_charge = 0,
 nspin = 1,
 noncolin = .false.,
 lspinorb = .false.,
 occupations = 'smearing',
 smearing = 'mv',
 degauss = 0.02,
/
&ELECTRONS
 conv_thr = 1e-8,
 electron_maxstep = 50,
 mixing_beta = 0.3,
 diagonalization = 'david',
 startingpot = 'atomic',
 startingwfc = 'atomic+random',
/
ATOMIC_SPECIES
H 1 H.UPF
CELL_PARAMETERS angstrom
2 0 0
0 2 0
0 0 2
ATOMIC_POSITIONS crystal
H 0 0 0
K_POINTS automatic
1 1 1 0 0 0
"""


def payload(kind="qe_scf", deck=None):
    data = (deck or DECK).encode()
    if kind == "qe_initialize":
        data = data.replace(b"nstep = 1", b"nstep = 0")
    return {
        "native.json": canonical(
            {
                "schema_version": "sclib-native-qe/1",
                "input_name": "input.in",
                "source_manifest_name": "source.json",
                "prefix": "sclib_test",
                "pseudo_names": ["H.UPF"],
            }
        ),
        "input.in": data,
        "H.UPF": b"pinned fixture UPF",
        "source.json": canonical(
            {
                "version": "discovery-qe-input/1.0.0",
                "settings": {"calculation": "scf"},
                "files": {
                    "execution" if kind == "qe_scf" else "initialization": {
                        "filename": "input.in",
                        "sha256": sha(data),
                    }
                },
                "pseudopotentials": [
                    {
                        "filename": "H.UPF",
                        "sha256": sha(b"pinned fixture UPF"),
                        "byte_length": len(b"pinned fixture UPF"),
                    }
                ],
            }
        ),
    }


@pytest.fixture
def native_env(tmp_path):
    root = tmp_path.resolve()
    limits = Limits(
        lease_seconds=30,
        retry_grace_seconds=2,
        max_cpu_cores=4,
        max_wall_seconds=30,
        max_memory_bytes=1024**3,
        min_free_bytes=1,
        total_cpu_core_seconds=1000,
    )
    store = Store(root / "store", limits)
    token = sha(b"native-token")
    auth = AuthConfig(
        mode="loopback_test",
        test_bearer_sha256_principals={
            token: Principal(
                role="node",
                node_id="native-a",
                runtime_id="qe-test",
                capabilities=["qe_initialize", "qe_scf"],
            )
        },
    )
    client = TestClient(
        create_app(
            store,
            ServiceConfig(auth=auth, enabled_job_kinds=["qe_initialize", "qe_scf"]),
        ),
        client=("127.0.0.1", 5000),
        headers={"Authorization": "Bearer native-token"},
    )
    mpi = root / "mpiexec"
    mpi.write_text(
        f"#!{sys.executable}\nimport os,sys\nos.execv(sys.argv[3],sys.argv[3:])\n"
    )
    mpi.chmod(0o700)

    def setup(mode="success", kind="qe_scf", wall=20, stdout_max=65536):
        pw = root / "pw.x"
        script = f"""#!{sys.executable}
import os,time,subprocess,sys
from pathlib import Path
counter=Path({str(root / "launch-count")!r})
counter.write_text(str(int(counter.read_text())+1) if counter.exists() else '1')
if {mode!r} == 'slow':
 child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
 Path('rank-pids.json').write_text(str(os.getpid())+' '+str(child.pid))
 time.sleep(60)
if {mode!r} == 'output': print('X'*100000, flush=True); time.sleep(2)
Path('out/sclib_test.save').mkdir(parents=True,exist_ok=True)
Path('out/sclib_test.save/data-file-schema.xml').write_text('<espresso><test>fixture</test></espresso>')
print('Program PWSCF v.7.5 starts')
print('convergence NOT achieved' if {mode!r}=='nonconverged' else 'convergence has been achieved')
print('JOB DONE.')
sys.exit(1 if {mode!r}=='failure' else 0)
"""
        pw.write_text(script)
        pw.chmod(0o700)
        runtime = NativeRuntime(
            runtime_id="qe-test",
            pw={"path": str(pw), "sha256": sha(pw.read_bytes())},
            mpiexec={"path": str(mpi), "sha256": sha(mpi.read_bytes())},
            max_wall_seconds=30,
            max_memory_bytes=1024**3,
            min_free_bytes=1024**2,
            max_scratch_bytes=1024**2,
            min_available_memory_bytes=1024**2,
            heartbeat_seconds=1,
        )
        files = payload(kind)
        for data in files.values():
            store.put_blob(data, sha(data))
        spec = JobSpec(
            job_id="native-job",
            kind=kind,
            runtime_id="qe-test",
            case_ref="case",
            state_ref="state",
            action_ref="action",
            input_artifacts=[
                {"name": name, "sha256": sha(data), "bytes": len(data)}
                for name, data in files.items()
            ],
            output_rules=[
                {
                    "name": name,
                    "max_bytes": stdout_max if name == "stdout.txt" else 65536,
                }
                for name in [
                    "stdout.txt",
                    "stderr.txt",
                    "data-file-schema.xml",
                    "execution.json",
                ]
            ],
            resources={
                "cpu_cores": 2,
                "wall_seconds": wall,
                "memory_bytes": 1024**3,
                "output_bytes": stdout_max + 3 * 65536,
            },
            deadline_unix=int(time.time()) + 300,
        )
        store.enqueue(spec)
        return runtime, spec, files

    yield root, store, client, setup
    client.close()


def execution(root):
    return json.loads(
        next((root / "worker").glob("attempt-*/return/execution.json")).read_bytes()
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("success", "success"),
        ("nonconverged", "not_converged"),
        ("failure", "solver_failure"),
    ],
)
def test_native_full_roundtrip_explicit_outcomes(native_env, mode, expected):
    root, _store, client, setup = native_env
    runtime, _spec, _files = setup(mode)
    worker = NativeWorker(client, root / "worker", runtime)
    try:
        receipt = worker.one_cycle()
    finally:
        worker.close()
    assert receipt["solver_outcome"] == expected
    assert receipt["scientific_status"] == "not_assessed"
    record = execution(root)
    assert (
        record["restart_mode"] == "from_scratch"
        and record["checkpoint_resume"] is False
    )
    assert record["process"]["thread_environment"]["OMP_NUM_THREADS"] == "1"
    assert len(record["input_manifest"]) == 4
    assert next((root / "worker").glob("attempt-*/archive.json")).is_file()


def test_initialization_is_separate_kind(native_env):
    root, _store, client, setup = native_env
    runtime, _spec, _files = setup(kind="qe_initialize")
    worker = NativeWorker(client, root / "worker", runtime)
    try:
        assert worker.one_cycle()["solver_outcome"] == "success"
    finally:
        worker.close()
    assert execution(root)["kind"] == "qe_initialize"


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.replace("'from_scratch'", "'restart'"),
        lambda d: d.replace("'./out'", "'/tmp/escape'"),
        lambda d: d.replace(
            " electron_maxstep", " wfcdir = '/tmp',\n electron_maxstep"
        ),
        lambda d: d + "HUBBARD ortho-atomic\nU H-1s 3\n",
        lambda d: d.replace("H.UPF", "../H.UPF"),
    ],
)
def test_native_rejects_unreviewed_paths_restart_and_cards(native_env, change):
    _root, _store, _client, setup = native_env
    _runtime, spec, _files = setup()
    files = payload(deck=change(DECK))
    changed = spec.model_copy(
        update={
            "input_artifacts": [
                type(spec.input_artifacts[0])(
                    name=name, sha256=sha(data), bytes=len(data)
                )
                for name, data in files.items()
            ]
        }
    )
    with pytest.raises(ValueError):
        validate_inputs(changed, files)


def test_native_binary_and_input_corruption_rejected(native_env):
    root, _store, _client, setup = native_env
    runtime, spec, files = setup()
    files["H.UPF"] += b"changed"
    with pytest.raises(ValueError, match="checksum"):
        validate_inputs(spec, files)
    (root / "pw.x").write_text("modified")
    with pytest.raises(ValueError, match="checksum"):
        runtime.validate_job(spec)


class LostComplete:
    def __init__(self, client):
        self.client, self.lost = client, False

    def request(self, method, path, **kwargs):
        result = self.client.request(method, path, **kwargs)
        if path.endswith("/complete") and not self.lost:
            self.lost = True
            raise httpx.ReadTimeout("injected native complete ACK loss")
        return result


def test_native_ack_loss_replays_outbox_without_solver_rerun(native_env):
    root, store, client, setup = native_env
    runtime, _spec, _files = setup()
    worker = NativeWorker(LostComplete(client), root / "worker", runtime)
    try:
        with pytest.raises(httpx.ReadTimeout):
            worker.one_cycle()
    finally:
        worker.close()
    worker = NativeWorker(client, root / "worker", runtime)
    try:
        receipt = worker.one_cycle()
    finally:
        worker.close()
    assert receipt["status"] == "returned"
    assert (root / "launch-count").read_text() == "1"
    assert store.status()["reserved_cpu_core_seconds"] == 40


def test_native_wall_watchdog_stops_tree_and_marks_interrupted(native_env):
    root, _store, client, setup = native_env
    runtime, _spec, _files = setup("slow", wall=4)
    worker = NativeWorker(client, root / "worker", runtime)
    start = time.monotonic()
    try:
        receipt = worker.one_cycle()
    finally:
        worker.close()
    assert time.monotonic() - start < 10
    assert receipt["solver_outcome"] == "interrupted"
    assert execution(root)["process"]["reason"] in {
        "wall_limit",
        "worker_disconnected",
        "lease_expired",
    }


def test_native_output_overrun_is_explicitly_truncated_failure(native_env):
    root, _store, client, setup = native_env
    runtime, _spec, _files = setup("output", stdout_max=1024)
    worker = NativeWorker(client, root / "worker", runtime)
    try:
        receipt = worker.one_cycle()
    finally:
        worker.close()
    assert receipt["solver_outcome"] == "interrupted"
    assert execution(root)["capture"]["stdout.txt"]["truncated"] is True


def test_native_cancellation_stops_tree(native_env):
    root, store, client, setup = native_env
    runtime, _spec, _files = setup("slow")

    class Cancel:
        beats = 0

        def request(self, method, path, **kwargs):
            if path.endswith("/heartbeat") and kwargs["json"]["phase"] == "running":
                self.beats += 1
                if self.beats == 2:
                    store.cancel("native-job")
            return client.request(method, path, **kwargs)

    worker = NativeWorker(Cancel(), root / "worker", runtime)
    try:
        receipt = worker.one_cycle()
    finally:
        worker.close()
    assert receipt["status"] == "quarantined"
    assert receipt["solver_outcome"] == "interrupted"
    assert execution(root)["process"]["reason"] == "worker_disconnected"


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX guardian test")
def test_worker_sigkill_guardian_stops_tree_and_restart_never_reruns(native_env):
    root, _store, client, setup = native_env
    runtime, _spec, _files = setup("slow")

    launch = root / "fixture-launch.json"
    launch.write_bytes(
        canonical({"runtime": runtime.model_dump(mode="json"), "root": str(root)})
    )
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), str(launch)]
    )
    end = time.monotonic() + 10
    marker = []
    while time.monotonic() < end:
        marker = list((root / "worker").glob("attempt-*/work/rank-pids.json"))
        if marker:
            break
        time.sleep(0.05)
    assert marker, "native fixture never started"
    os.kill(child.pid, signal.SIGKILL)
    child.wait(timeout=5)
    end = time.monotonic() + 10
    while (
        not list((root / "worker").glob("attempt-*/solver-result.json"))
        and time.monotonic() < end
    ):
        time.sleep(0.05)
    process = json.loads(
        next((root / "worker").glob("attempt-*/solver-result.json")).read_bytes()
    )
    assert process["reason"] == "worker_disconnected"
    from sclib_compute.native_supervisor import processes

    rows = processes()
    assert all(int(pid) not in rows for pid in marker[0].read_text().split())
    worker = NativeWorker(client, root / "worker", runtime)
    try:
        receipt = worker.one_cycle()
    finally:
        worker.close()
    assert receipt["solver_outcome"] == "interrupted"
    assert (root / "launch-count").read_text() == "1"


def test_missing_stderr_cannot_be_success(native_env):
    root, _store, client, setup = native_env
    runtime, _spec, _files = setup()
    worker = NativeWorker(client, root / "worker", runtime)
    original = worker.run_guardian

    def remove_stderr(state, spec, attempt_dir):
        original(state, spec, attempt_dir)
        (attempt_dir / "work" / "stderr.txt").unlink()

    worker.run_guardian = remove_stderr
    try:
        assert worker.one_cycle()["solver_outcome"] == "solver_failure"
    finally:
        worker.close()


def test_insufficient_available_memory_does_not_claim(native_env, monkeypatch):
    root, store, client, setup = native_env
    runtime, _spec, _files = setup()
    monkeypatch.setattr("sclib_compute.native_worker.available_memory_bytes", lambda: 0)
    worker = NativeWorker(client, root / "worker", runtime)
    try:
        assert worker.one_cycle()["status"] == "local_resource_wait"
    finally:
        worker.close()
    assert store.status()["reserved_cpu_core_seconds"] == 0
    assert not (root / "launch-count").exists()


def test_missing_guardian_result_blocks_restart_and_next_claim(native_env):
    root, _store, client, setup = native_env
    runtime, _spec, _files = setup()
    worker = NativeWorker(LostComplete(client), root / "worker", runtime)
    try:
        with pytest.raises(httpx.ReadTimeout):
            worker.one_cycle()
    finally:
        worker.close()
    state = json.loads((root / "worker" / "state.json").read_bytes())
    state.pop("outbox")
    # Simulate interrupted execution with no completion receipt, without leaving
    # any real orphan process. A fresh pending attempt prevents receipt shortcut.
    state["claim"]["attempt"]["attempt_id"] = "attempt-" + "a" * 32
    (root / "worker" / "state.json").write_bytes(canonical(state))

    class Missing:
        def request(self, method, path, **kwargs):
            if path.endswith("/attempts/attempt-" + "a" * 32):
                return httpx.Response(
                    200,
                    json={"attempt": {"status": "running"}},
                    request=httpx.Request(method, "http://test" + path),
                )
            return client.request(method, path, **kwargs)

    worker = NativeWorker(Missing(), root / "worker", runtime)
    from sclib_compute.worker import WorkerStopped

    try:
        with pytest.raises(WorkerStopped, match="operator must verify process cleanup"):
            worker.one_cycle()
    finally:
        worker.close()
    assert (root / "launch-count").read_text() == "1"


def test_partial_outbox_recovery_preserves_exact_execution_and_never_reruns(
    native_env, monkeypatch
):
    root, _store, client, setup = native_env
    runtime, _spec, _files = setup()
    from sclib_compute import native_worker

    original = native_worker.write_once

    def fail_second(path, data):
        if path.parent.name == "return" and path.name == "stderr.txt":
            raise OSError("injected outbox write interruption")
        return original(path, data)

    monkeypatch.setattr(native_worker, "write_once", fail_second)
    worker = NativeWorker(client, root / "worker", runtime)
    try:
        with pytest.raises(OSError, match="outbox write interruption"):
            worker.one_cycle()
    finally:
        worker.close()
    frozen = next((root / "worker").glob("attempt-*/execution-final.json")).read_bytes()
    monkeypatch.setattr(native_worker, "write_once", original)
    worker = NativeWorker(client, root / "worker", runtime)
    try:
        assert worker.one_cycle()["solver_outcome"] == "success"
    finally:
        worker.close()
    assert (
        next((root / "worker").glob("attempt-*/return/execution.json")).read_bytes()
        == frozen
    )
    assert (root / "launch-count").read_text() == "1"


def test_guardian_lease_deadline_survives_blocked_heartbeat(native_env):
    root, store, client, setup = native_env
    runtime, _spec, _files = setup("slow")
    store.limits = replace(store.limits, lease_seconds=3)

    class SlowHeartbeat:
        beats = 0

        def request(self, method, path, **kwargs):
            if path.endswith("/heartbeat") and kwargs["json"]["phase"] == "running":
                self.beats += 1
                if self.beats == 2:
                    time.sleep(5)
                    raise httpx.ReadTimeout("injected stalled heartbeat")
            return client.request(method, path, **kwargs)

    worker = NativeWorker(SlowHeartbeat(), root / "worker", runtime)
    try:
        receipt = worker.one_cycle()
    finally:
        worker.close()
    assert receipt["solver_outcome"] == "interrupted"
    assert execution(root)["process"]["reason"] == "lease_expired"


if __name__ == "__main__":
    # Clean subprocess fixture: never fork a process containing TestClient's
    # background threads (unsafe with Darwin system SQLite/Python frameworks).
    config = json.loads(Path(sys.argv[1]).read_bytes())
    root = Path(config["root"])
    store = Store(
        root / "store",
        Limits(
            lease_seconds=30,
            retry_grace_seconds=2,
            max_cpu_cores=4,
            max_wall_seconds=30,
            max_memory_bytes=1024**3,
            min_free_bytes=1,
            total_cpu_core_seconds=1000,
        ),
    )
    auth = AuthConfig(
        mode="loopback_test",
        test_bearer_sha256_principals={
            sha(b"native-token"): Principal(
                role="node",
                node_id="native-a",
                runtime_id="qe-test",
                capabilities=["qe_initialize", "qe_scf"],
            )
        },
    )
    with TestClient(
        create_app(
            store,
            ServiceConfig(auth=auth, enabled_job_kinds=["qe_initialize", "qe_scf"]),
        ),
        client=("127.0.0.1", 5000),
        headers={"Authorization": "Bearer native-token"},
    ) as client:
        worker = NativeWorker(
            client, root / "worker", NativeRuntime.model_validate(config["runtime"])
        )
        try:
            worker.one_cycle()
        finally:
            worker.close()
