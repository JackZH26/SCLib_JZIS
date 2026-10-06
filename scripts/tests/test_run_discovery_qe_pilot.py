"""Exercise deadlines and fail-closed custody with fake processes; never execute QE."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import run_discovery_qe_pilot as runner  # noqa: E402


class Clock:
    now = 0.0


class Process:
    pid = 987654321  # Never signalled: killpg is replaced in every execution test.

    def __init__(self, clock, outcomes):
        self.clock, self.outcomes, self.timeouts = clock, list(outcomes), []

    def wait(self, *, timeout):
        assert timeout is not None and timeout >= 0
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if outcome == "timeout":
            self.clock.now += timeout
            raise subprocess.TimeoutExpired("fake-qe-no-execution", timeout)
        elapsed, code = outcome
        assert elapsed <= timeout
        self.clock.now += elapsed
        return code


@pytest.fixture
def runtime(monkeypatch):
    clock, signals, processes = Clock(), [], []
    monkeypatch.setattr(runner.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(runner.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    pending = []

    def spawn(*args, **kwargs):
        assert kwargs["start_new_session"] is True
        process = Process(clock, pending.pop(0))
        processes.append(process)
        return process

    monkeypatch.setattr(runner.subprocess, "Popen", spawn)
    return clock, signals, processes, pending


def launch(deadline):
    return runner.execute_before_deadline(["fake-mpirun", "fake-pw"], cwd=Path("."), stdout=None, env={}, deadline=deadline)


def test_initialization_and_execution_share_the_same_450_second_job_budget(runtime):
    clock, signals, processes, pending = runtime
    pending.extend([[(50, 0)], ["timeout", "timeout", (1, -9)]])
    deadline = clock.now + runner.JOB_WALL_SECONDS
    assert launch(deadline) == {"exit_code": 0, "timed_out": False, "process_reaped": True}
    result = launch(deadline)
    assert result == {"exit_code": -9, "timed_out": True, "process_reaped": True}
    assert processes[0].timeouts == [439]
    assert processes[1].timeouts == [389, 10, 1]
    assert clock.now == 450  # Two phases AND termination/reaping share this budget.
    assert signals == [(Process.pid, signal.SIGTERM), (Process.pid, signal.SIGKILL)]


def test_total_pilot_deadline_takes_precedence_over_a_fresh_job_budget(runtime):
    clock, _, processes, pending = runtime
    clock.now = 3300
    pending.extend([[(100, 0)], ["timeout", "timeout", (1, -9)]])
    deadline = min(runner.WORK_WALL_SECONDS, clock.now + runner.JOB_WALL_SECONDS)
    launch(deadline)
    assert launch(deadline)["timed_out"] is True
    assert processes[0].timeouts == [189]
    assert processes[1].timeouts == [89, 10, 1]
    assert clock.now == runner.WORK_WALL_SECONDS


@pytest.mark.parametrize("remaining", [0, 10, 11, -1])
def test_does_not_start_when_termination_reserve_cannot_fit(runtime, remaining):
    clock, signals, processes, pending = runtime
    pending.append([(0, 0)])
    assert launch(clock.now + remaining) is None
    assert not processes and not signals


def test_successful_term_reap_preserves_timeout_instead_of_claiming_success(runtime):
    _, signals, processes, pending = runtime
    pending.append(["timeout", (2, 0)])
    assert launch(100) == {"exit_code": 0, "timed_out": True, "process_reaped": True}
    assert processes[0].timeouts == [89, 10]
    assert signals == [(Process.pid, signal.SIGTERM)]


def test_kill_reap_is_bounded_and_does_not_fabricate_exit_code(runtime):
    clock, signals, processes, pending = runtime
    pending.append(["timeout", "timeout", "timeout"])
    assert launch(100) == {"exit_code": None, "timed_out": True, "process_reaped": False}
    assert clock.now == 100
    assert processes[0].timeouts == [89, 10, 1]
    assert len(signals) == 2


def test_signal_exit_race_is_reaped_without_losing_the_timeout_record(runtime, monkeypatch):
    _, _, _, pending = runtime
    pending.append(["timeout", (0, 0)])

    def exited(*_):
        raise ProcessLookupError()

    monkeypatch.setattr(runner.os, "killpg", exited)
    assert launch(100) == {"exit_code": 0, "timed_out": True, "process_reaped": True}


def test_nonzero_process_exit_remains_a_failure(runtime):
    _, signals, _, pending = runtime
    pending.append([(2, 7)])
    assert launch(100) == {"exit_code": 7, "timed_out": False, "process_reaped": True}
    assert not signals


def test_frozen_file_hash_length_and_symlink_guards(tmp_path):
    base = tmp_path / "bundle"
    base.mkdir()
    path = base / "input.in"
    path.write_bytes(b"frozen input\n")
    item = {"path": "input.in", "bytes": path.stat().st_size, "sha256": runner.digest(path)}
    assert runner.check_file(base, item) == path
    path.write_bytes(b"changed input\n")
    with pytest.raises(ValueError, match="hash or length"):
        runner.check_file(base, item)
    (base / "link.in").symlink_to(path)
    with pytest.raises(ValueError, match="regular files"):
        runner.regular(base, "link.in")
    outside = tmp_path / "outside.in"
    outside.write_bytes(b"outside\n")
    with pytest.raises(ValueError, match="regular files"):
        runner.regular(base, "../outside.in")


def test_verify_only_never_starts_a_process_or_creates_execution_receipts(tmp_path, monkeypatch, capsys):
    plan = {"schema_version": "discovery-qe-pilot-plan/1.0.0", "status": "prepared_not_executed", "jobs": [{} for _ in range(9)],
            "assigned_execution_bounds": {"maximum_cpu_cores": 4, "maximum_memory_gib": 12, "total_wall_seconds": 3600, "external_per_job_wall_seconds": 450}}
    base = tmp_path / "bundle"
    base.mkdir()
    plan_path, manifest_path = base / "pilot-plan.json", base / "bundle-manifest.json"
    plan_path.write_text(json.dumps(plan))
    manifest_path.write_text(json.dumps({"pilot_plan": {"path": plan_path.name, "bytes": plan_path.stat().st_size, "sha256": runner.digest(plan_path)}, "files": []}))
    pw = tmp_path / "never-executed-pw"
    pw.write_bytes(b"synthetic runtime pin; not an executable")
    monkeypatch.setattr(sys, "argv", ["runner", "--bundle", str(base), "--plan-sha256", runner.digest(plan_path), "--manifest-sha256", runner.digest(manifest_path), "--pw", str(pw), "--pw-sha256", runner.digest(pw)])
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("verify-only attempted execution"))
    runner.main()
    assert json.loads(capsys.readouterr().out)["status"] == "verified_not_executed"
    assert not (base / "execution-started.json").exists()
    assert not (base / "execution-finished.json").exists()


def test_existing_receipt_is_never_replaced(tmp_path):
    target = tmp_path / "receipt.json"
    runner.atomic_new(target, {"status": "first"})
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        runner.atomic_new(target, {"status": "second"})
    assert hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(before).digest()


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    """Frozen synthetic inputs plus fake cgroup reads; no native program can run."""
    clock, base = Clock(), tmp_path / "bundle"
    base.mkdir()
    jobs, files = [], []
    for i in range(9):
        work = base / f"job{i}"
        work.mkdir()
        job = {"id": f"job{i}", "directory": work.name, "catalogue_state_id": f"synthetic-state-{i}", "pseudopotentials": []}
        for kind in ("initialization", "execution"):
            deck = work / f"{kind}.in"
            deck.write_text(f"prefix = 'synthetic_{kind}'\n")
            pin = {"path": str(deck.relative_to(base)), "sha256": runner.digest(deck), "bytes": deck.stat().st_size}
            job[f"{kind}_input"] = pin
            files.append(pin)
        jobs.append(job)
    plan = {"schema_version": "discovery-qe-pilot-plan/1.0.0", "status": "prepared_not_executed", "jobs": jobs,
            "assigned_execution_bounds": {"maximum_cpu_cores": 4, "maximum_memory_gib": 12, "total_wall_seconds": 3600, "external_per_job_wall_seconds": 450}}
    plan_path, manifest = base / "pilot-plan.json", base / "bundle-manifest.json"
    plan_path.write_text(json.dumps(plan))
    manifest.write_text(json.dumps({"pilot_plan": {"path": plan_path.name, "bytes": plan_path.stat().st_size, "sha256": runner.digest(plan_path)}, "files": files}))
    pw = tmp_path / "pw-never-executed"
    pw.write_bytes(b"not executable")
    (tmp_path / "mpirun").write_bytes(b"not executable")
    monkeypatch.setattr(sys, "argv", ["runner", "--execute", "--bundle", str(base), "--plan-sha256", runner.digest(plan_path), "--manifest-sha256", runner.digest(manifest), "--pw", str(pw), "--pw-sha256", runner.digest(pw)])
    monkeypatch.setattr(runner.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_a, **_kw: pytest.fail("synthetic pilot must never execute"))
    original_read = Path.read_text
    def safe_read(path, *args, **kwargs):
        if str(path) == "/proc/self/cgroup":
            return "0::/sclib-qe-pilot-20261006.service"
        if str(path) == "/sys/fs/cgroup/sclib-qe-pilot-20261006.service/cpu.max":
            return "400000 100000"
        if str(path) == "/sys/fs/cgroup/sclib-qe-pilot-20261006.service/memory.max":
            return str(12 * 2**30)
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", safe_read)
    calls = []
    def capture(argv, *, cwd, stdout, env, deadline):
        calls.append({"job": cwd.name, "kind": Path(argv[-1]).stem, "deadline": deadline, "started": clock.now})
        if deadline - clock.now <= 11:
            return None
        clock.now += 5
        native = cwd / "out" / f"synthetic_{Path(argv[-1]).stem}.save" / "data-file-schema.xml"
        native.parent.mkdir()
        native.write_bytes(b"synthetic custody fixture, not scientific XML")
        stdout.write(b"synthetic output\n")
        return {"exit_code": 0, "timed_out": False, "process_reaped": True}
    monkeypatch.setattr(runner, "execute_before_deadline", capture)
    return base, clock, calls, capture


def test_main_reuses_job_deadline_between_phases_and_pins_captured_artifacts(pilot):
    base, _, calls, _ = pilot
    runner.main()
    assert len(calls) == 18
    for first, second in zip(calls[::2], calls[1::2]):
        assert first["job"] == second["job"]
        assert first["deadline"] == second["deadline"] == first["started"] + 450
        assert second["started"] > first["started"]
    receipt = json.loads((base / "job0/execution-receipt.json").read_text())
    assert receipt["job_deadline_exceeded"] is False
    for step in receipt["steps"]:
        assert step["xml"]["sha256"] == runner.digest(base / step["xml"]["path"])
        assert step["stdout"]["sha256"] == runner.digest(base / step["stdout"]["path"])
    assert json.loads((base / "execution-finished.json").read_text())["status"] == "execution_files_captured"


def test_main_does_not_launch_execution_after_initialization_spends_job_budget(pilot, monkeypatch):
    base, clock, calls, capture = pilot
    def slow_initialization(argv, **kwargs):
        outcome = capture(argv, **kwargs)
        if kwargs["cwd"].name == "job0":
            clock.now += 435  # Ten seconds remain, less than termination reserve.
        return outcome
    monkeypatch.setattr(runner, "execute_before_deadline", slow_initialization)
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 1
    assert [c["kind"] for c in calls if c["job"] == "job0"] == ["initialization"]
    receipt = json.loads((base / "job0/execution-receipt.json").read_text())
    assert receipt["budget_exhausted"] is True
    assert not (base / "job0/pw.out").exists()


def test_postprocess_overrun_is_retained_but_not_counted_as_budget_compliant(pilot, monkeypatch):
    base, clock, _, _ = pilot
    original_digest = runner.digest
    def slow_capture(path):
        if path == base / "job0/pw.out":
            clock.now += 500
        return original_digest(path)
    monkeypatch.setattr(runner, "digest", slow_capture)
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 1
    receipt = json.loads((base / "job0/execution-receipt.json").read_text())
    assert len(receipt["steps"]) == 2 and receipt["job_deadline_exceeded"] is True
    final = json.loads((base / "execution-finished.json").read_text())
    assert final["status"] == "partial_or_failed"
    assert "job0" not in final["jobs_with_complete_execution_files"]
    assert len(final["jobs_with_complete_execution_files"]) == 8
