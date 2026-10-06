"""Execute a frozen, bounded QE pilot. Run only inside externally enforced resource limits."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

JOB_WALL_SECONDS = 450
WORK_WALL_SECONDS = 3500  # Leave 100 s inside the external 3600 s service limit.
TERM_GRACE_SECONDS = 10
KILL_REAP_SECONDS = 1


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def regular(base, relative):
    if not isinstance(relative, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", relative):
        raise ValueError("Unsupported artifact path")
    path = base / relative
    if path.is_symlink() or not path.is_file() or base not in path.resolve().parents:
        raise ValueError("Artifacts must be regular files inside the bundle")
    if any(parent.is_symlink() for parent in path.parents if parent != base.parent):
        raise ValueError("Symlink artifact paths are unsupported")
    return path


def check_file(base, item):
    path = regular(base, item["path"])
    if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
        raise ValueError("Frozen artifact hash or length differs")
    return path


def atomic_new(path, value):
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)


def execute_before_deadline(argv, *, cwd, stdout, env, deadline):
    """One process group, using a shared job/global deadline including termination.

    None means there was insufficient remaining budget to start. An unreaped
    process stops the entire pilot; the resource-limited service remains the
    final hard boundary for kernel/process or artifact-I/O stalls.
    """
    reserve = TERM_GRACE_SECONDS + KILL_REAP_SECONDS
    if deadline - time.monotonic() <= reserve:
        return None
    proc = subprocess.Popen(argv, cwd=cwd, stdout=stdout, stderr=subprocess.STDOUT,
                            env=env, start_new_session=True)
    timed_out = False

    def send(sig):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass  # The child may have exited between wait and signal.

    try:
        code = proc.wait(timeout=max(0, deadline - time.monotonic() - reserve))
    except subprocess.TimeoutExpired:
        timed_out = True
        grace = min(TERM_GRACE_SECONDS, max(0, deadline - time.monotonic() - KILL_REAP_SECONDS))
        if grace > 0:
            send(signal.SIGTERM)
            try:
                code = proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                code = None
        else:
            code = None
        if code is None:
            send(signal.SIGKILL)
            try:
                code = proc.wait(timeout=min(KILL_REAP_SECONDS, max(0, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                return {"exit_code": None, "timed_out": True, "process_reaped": False}
    return {"exit_code": code, "timed_out": timed_out, "process_reaped": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--pw", type=Path, required=True)
    parser.add_argument("--pw-sha256", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    base = args.bundle.resolve()
    plan_path = regular(base, "pilot-plan.json")
    manifest_path = regular(base, "bundle-manifest.json")
    if digest(plan_path) != args.plan_sha256 or digest(manifest_path) != args.manifest_sha256 or digest(args.pw) != args.pw_sha256:
        raise ValueError("Plan, bundle inventory or runtime bytes changed")
    plan, inventory = json.loads(plan_path.read_text()), json.loads(manifest_path.read_text())
    if plan["schema_version"] != "discovery-qe-pilot-plan/1.0.0" or plan["status"] != "prepared_not_executed" or len(plan["jobs"]) != 9:
        raise ValueError("Unsupported frozen pilot plan")
    bounds = plan["assigned_execution_bounds"]
    if (bounds["maximum_cpu_cores"] != 4 or bounds["total_wall_seconds"] != 3600
            or bounds["maximum_memory_gib"] != 12
            or bounds["external_per_job_wall_seconds"] != JOB_WALL_SECONDS):
        raise ValueError("Execution bounds differ from the frozen plan")
    for item in [inventory["pilot_plan"], *inventory["files"]]:
        check_file(base, item)
    if not args.execute:
        print(json.dumps({"status": "verified_not_executed", "files": len(inventory["files"]), "jobs": 9}))
        return
    cgroup = Path("/proc/self/cgroup").read_text()
    if "sclib-qe-pilot-20261006.service" not in cgroup:
        raise ValueError("Run in the named resource-limited pilot service")
    # Verify enforced limits, rather than trusting planned bounds or shell thread hints.
    group = cgroup.strip().split(":", 2)[-1].lstrip("/")
    cg = Path("/sys/fs/cgroup") / group
    cpu = (cg / "cpu.max").read_text().split()
    if cpu[0] == "max" or int(cpu[0]) / int(cpu[1]) > 4 or int((cg / "memory.max").read_text()) > 12 * 2**30:
        raise ValueError("CPU or memory cgroup limits are absent or excessive")
    start = time.monotonic()
    common = {"version": "discovery-qe-pilot-execution/1.0.0", "plan_sha256": args.plan_sha256, "manifest_sha256": args.manifest_sha256,
              "pw_sha256": args.pw_sha256, "runner_sha256": digest(Path(__file__)), "started_at_utc": utc(), "cpu_max": cpu,
              "memory_max_bytes": int((cg / "memory.max").read_text()), "scientific_acceptance": False, "rps_score": None,
              "work_wall_seconds": WORK_WALL_SECONDS, "per_job_wall_seconds": JOB_WALL_SECONDS,
              "term_grace_seconds": TERM_GRACE_SECONDS, "kill_reap_seconds": KILL_REAP_SECONDS,
              "execution_authentication": "coordinator_capture_not_formal_scientific_attestation"}
    atomic_new(base / "execution-started.json", common)
    receipts = []
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", OMPI_ALLOW_RUN_AS_ROOT="1", OMPI_ALLOW_RUN_AS_ROOT_CONFIRM="1")
    mpi = args.pw.parent / "mpirun"
    process_unreaped = False
    for job in plan["jobs"]:
        job_start = time.monotonic()
        deadline = min(start + WORK_WALL_SECONDS, job_start + JOB_WALL_SECONDS)
        work = (base / job["directory"]).resolve()
        if base not in work.parents or work.is_symlink():
            raise ValueError("Invalid job directory")
        (work / "out").mkdir(mode=0o700, exist_ok=False)
        receipt = {**common, "job_id": job["id"], "catalogue_state_id": job["catalogue_state_id"], "steps": [],
                   "job_started_at_utc": utc(), "available_job_wall_seconds": deadline - job_start}
        for kind, output_name in [("initialization", "initialization.out"), ("execution", "pw.out")]:
            if deadline - time.monotonic() <= TERM_GRACE_SECONDS + KILL_REAP_SECONDS:
                receipt["budget_exhausted"] = True
                break
            deck = check_file(base, job[f"{kind}_input"])
            prefixes = re.findall(r"^\s*prefix\s*=\s*'([A-Za-z0-9_]{1,64})'\s*,?\s*$", deck.read_text(), re.MULTILINE)
            if len(prefixes) != 1:
                raise ValueError("The prepared input must declare one safe output prefix")
            native_xml = work / "out" / f"{prefixes[0]}.save" / "data-file-schema.xml"
            if native_xml.exists():
                raise ValueError("The selected run already has native XML output")
            for pseudo in job["pseudopotentials"]:
                pp = regular(base, f"{job['directory']}/pseudo/{pseudo['filename']}")
                if digest(pp) != pseudo["sha256"]:
                    raise ValueError("Pseudopotential bytes changed")
            t0 = time.monotonic()
            with (work / output_name).open("xb") as log:
                argv = [str(mpi), "--allow-run-as-root", "--bind-to", "core", "-np", "4", str(args.pw), "-in", deck.name]
                outcome = execute_before_deadline(argv, cwd=work, stdout=log, env=env, deadline=deadline)
            if outcome is None:
                receipt["budget_exhausted"] = True
                break
            process_unreaped = not outcome["process_reaped"]
            stdout = work / output_name
            xml_pin = None
            if not process_unreaped and native_xml.is_file() and not native_xml.is_symlink():
                xml = native_xml
                saved = work / f"{kind}.xml"
                saved.write_bytes(xml.read_bytes())
                xml_pin = {"path": str(saved.relative_to(base)), "sha256": digest(saved), "bytes": saved.stat().st_size}
            step = {"kind": kind, **outcome, "wall_seconds": time.monotonic() - t0,
                    "argv": argv, "mpirun_sha256": digest(mpi), "thread_environment": {k: env[k] for k in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"]},
                    "input_sha256": digest(deck), "stdout": {"path": str(stdout.relative_to(base)), "sha256": digest(stdout), "bytes": stdout.stat().st_size}, "xml": xml_pin}
            receipt["steps"].append(step)
            # An initializer must complete before execution. Scientific status is assigned by the original-file reader.
            if outcome["exit_code"] != 0 or outcome["timed_out"] or process_unreaped or xml_pin is None:
                break
        receipt["job_finished_at_utc"] = utc()
        receipt["job_wall_seconds"] = time.monotonic() - job_start
        # Filesystem work cannot be forcibly interrupted in this process. Preserve
        # an overrun instead of counting a late artifact capture as within budget.
        receipt["job_deadline_exceeded"] = time.monotonic() > deadline
        atomic_new(work / "execution-receipt.json", receipt)
        receipts.append({"job_id": job["id"], "receipt_sha256": digest(work / "execution-receipt.json"), "steps": len(receipt["steps"])})
        print(json.dumps({"job_id": job["id"], "steps": receipt["steps"]}), flush=True)
        if process_unreaped or time.monotonic() - start >= WORK_WALL_SECONDS:
            break
    completed = []
    for job in plan["jobs"]:
        file = base / job["directory"] / "execution-receipt.json"
        if file.exists():
            saved = json.loads(file.read_text())
            if (not saved["job_deadline_exceeded"] and len(saved["steps"]) == 2
                    and all(s["exit_code"] == 0 and not s["timed_out"] and s["process_reaped"] and s["xml"] for s in saved["steps"])):
                completed.append(job["id"])
    status = "execution_files_captured" if len(completed) == len(plan["jobs"]) else "partial_or_failed"
    atomic_new(base / "execution-finished.json", {**common, "finished_at_utc": utc(), "wall_seconds": time.monotonic() - start,
               "status": status, "jobs": receipts, "jobs_with_complete_execution_files": completed})
    if status != "execution_files_captured":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
