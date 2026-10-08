"""Independent bounded MPI guardian. An EOF on the worker pipe stops its tree.

RSS/output/disk are sampled watchdog bounds, not kernel cgroup guarantees. The
local trusted MPI runtime is the only launcher; no queued command is executable.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import signal
import subprocess
import time
import traceback
from pathlib import Path

from .contracts import JobSpec
from .native_contract import (
    NativeInput,
    NativeRuntime,
    available_memory_bytes,
    executable,
    read_regular,
)
from .worker import atomic_json


def processes():
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,pgid=,rss=,stat="],
        capture_output=True,
        text=True,
        timeout=3,
        check=True,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    rows = {}
    for line in result.stdout.splitlines():
        values = line.split()
        if len(values) == 5 and not values[4].startswith("Z"):
            pid, parent, group, rss = map(int, values[:4])
            rows[pid] = (parent, group, rss * 1024)
    return rows


def tree(rows, leader, previous=()):
    selected = {pid for pid, (_, group, _) in rows.items() if group == leader}
    selected.update(pid for pid in previous if pid in rows)
    selected.add(leader)
    while True:
        expanded = selected | {
            pid for pid, (parent, _, _) in rows.items() if parent in selected
        }
        if expanded == selected:
            return selected
        selected = expanded


def kill_tree(leader, tracked=()):
    """Terminate the dedicated session and tracked descendants, then force kill."""
    for sig in [signal.SIGTERM, signal.SIGKILL]:
        try:
            rows = processes()
            tracked = tree(rows, leader, tracked)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        try:
            os.killpg(leader, sig)
        except (ProcessLookupError, PermissionError):
            # Some macOS sessions refuse group signals after the leader exits;
            # individually address every still-observed owned descendant below.
            pass
        for pid in tracked:
            if pid not in {os.getpid(), os.getppid()}:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
        if sig == signal.SIGTERM:
            time.sleep(0.25)
    end = time.monotonic() + 3
    while time.monotonic() < end:
        rows = processes()
        remaining = tree(rows, leader, tracked) & rows.keys()
        if not remaining:
            return
        time.sleep(0.05)
    raise RuntimeError("native process cleanup could not be verified")


def scratch_size(path):
    total = 0
    for directory, dirs, files in os.walk(path, followlinks=False):
        for name in [*dirs, *files]:
            entry = Path(directory) / name
            if entry.is_symlink():
                raise ValueError("solver produced symlink")
        for name in files:
            try:
                total += (Path(directory) / name).stat().st_size
            except FileNotFoundError:
                # MPI and QE may legitimately remove transient scratch files
                # during this sampled walk. Required outputs are checked later.
                continue
    return total


def supervise(request, parent_fd):
    runtime = NativeRuntime.model_validate(request["runtime"])
    spec = JobSpec.model_validate(request["spec"])
    descriptor = NativeInput.model_validate(request["descriptor"])
    runtime.validate_job(spec)
    work = Path(request["work"])
    control = work.parent
    for path in [work, *work.parents]:
        if path.is_symlink():
            raise ValueError("symlink in work directory")
    # A fixed environment prevents inherited shell variables, user MPI settings,
    # Python hooks and thread oversubscription from altering execution.
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(work),
        "TMPDIR": str(work / "tmp"),
        "LC_ALL": "C",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    argv = [
        str(executable(runtime.mpiexec)),
        "-n",
        str(spec.resources.cpu_cores),
        str(executable(runtime.pw)),
        "-in",
        str(work / descriptor.input_name),
    ]
    stopped = []

    def stop(_sig, _frame):
        stopped.append("supervisor_signal")

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    started = time.monotonic()
    process = None
    tracked = set()
    peak, reason, code = 0, "completed", None
    limits = {rule.name: rule.max_bytes for rule in spec.output_rules}
    try:
        if available_memory_bytes() < runtime.min_available_memory_bytes:
            raise ValueError("available_memory_below_launch_floor")
        if select.select([parent_fd], [], [], 0)[0] and os.read(parent_fd, 1) == b"":
            raise ValueError("worker_disconnected_before_launch")
        with (
            (work / "stdout.txt").open("xb") as stdout,
            (work / "stderr.txt").open("xb") as stderr,
        ):
            process = subprocess.Popen(
                argv,
                cwd=work,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                close_fds=True,
            )
            atomic_json(control / "process.json", {"pid": process.pid, "argv": argv})
            while True:
                elapsed = time.monotonic() - started
                rows = processes()
                tracked = tree(rows, process.pid, tracked)
                memory = sum(rows.get(pid, (0, 0, 0))[2] for pid in tracked)
                peak = max(peak, memory)
                size = scratch_size(work)
                atomic_json(
                    control / "progress.json",
                    {
                        "elapsed_seconds": elapsed,
                        "observed_memory_bytes": memory,
                        "peak_memory_bytes": peak,
                        "scratch_bytes": size,
                    },
                )
                if stopped:
                    reason = stopped[0]
                elif (
                    select.select([parent_fd], [], [], 0)[0]
                    and os.read(parent_fd, 1) == b""
                ):
                    reason = "worker_disconnected"
                elif elapsed >= request["remaining_wall_seconds"]:
                    reason = "wall_limit"
                elif (
                    time.time()
                    >= json.loads(read_regular(control / "lease.json", 4096))[
                        "lease_until_unix"
                    ]
                ):
                    reason = "lease_expired"
                elif memory > spec.resources.memory_bytes:
                    reason = "memory_limit"
                elif (
                    size > runtime.max_scratch_bytes
                    or shutil.disk_usage(work).free < runtime.min_free_bytes
                ):
                    reason = "disk_limit"
                elif any(
                    (work / name).stat().st_size > limits[name]
                    for name in ["stdout.txt", "stderr.txt"]
                ):
                    reason = "output_limit"
                xml = (
                    work
                    / "out"
                    / (descriptor.prefix + ".save")
                    / "data-file-schema.xml"
                )
                if xml.exists() and (
                    xml.is_symlink()
                    or xml.stat().st_size > limits["data-file-schema.xml"]
                ):
                    reason = "output_limit"
                if reason != "completed":
                    kill_tree(process.pid, tracked)
                    code = process.wait(timeout=5)
                    break
                code = process.poll()
                if code is not None:
                    # MPI must not leave ranks running after its launcher exits.
                    lingering = [
                        pid
                        for pid in tracked
                        if pid != process.pid and pid in processes()
                    ]
                    if lingering:
                        reason = "orphaned_rank"
                        kill_tree(process.pid, tracked)
                    break
                time.sleep(0.25)
            stdout.flush()
            os.fsync(stdout.fileno())
            stderr.flush()
            os.fsync(stderr.fileno())
    except BaseException as exc:  # noqa: BLE001 -- guardian must kill MPI on every exit path
        traceback.print_exc()
        reason = "supervisor_error:" + type(exc).__name__
        if process is not None:
            kill_tree(process.pid, tracked)
            code = process.wait(timeout=5)
    result = {
        "schema_version": "sclib-native-process/1",
        "reason": reason,
        "exit_code": code,
        "elapsed_seconds": time.monotonic() - started,
        "peak_memory_bytes": peak,
        "argv": argv,
        "thread_environment": {
            key: value for key, value in env.items() if key.endswith("THREADS")
        },
    }
    atomic_json(control / "solver-result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--parent-fd", type=int, required=True)
    args = parser.parse_args()
    supervise(json.loads(args.request.read_bytes()), args.parent_fd)


if __name__ == "__main__":
    main()
