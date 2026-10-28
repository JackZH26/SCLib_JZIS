"""Luna original-window campaign; complete coverage is tracked per parent paper."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
from pathlib import Path
import re
import time

from .campaign import available_bundles
from .contract import canonical
from .database import ingest_job
from .planning import load_plan
from .proposals import ProposalDatabase
from .sources import load_bundle, private_write
from .store import Store
from .windows import make_windows
from .worker import configuration, run_one


def run_window_campaign(root: Path, plan_path: Path, *, name, work_ids=None,
                        paper_limit=3, max_jobs=40, workers=2, max_wall_seconds=3600,
                        max_chars=4000, progress=print):
    if (not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", name) or not 1 <= paper_limit <= 100
            or not 1 <= max_jobs <= 2000 or not 1 <= workers <= 4
            or not 1 <= max_wall_seconds <= 86400):
        raise ValueError("invalid window campaign bounds")
    directory = root / "campaigns" / name
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    path = directory / "windows-state.json"
    store = Store(root)
    plan, plan_hash = load_plan(plan_path)
    allowed = {p["id"] for p in plan["papers"] if p["source"] == "arxiv"}
    config = configuration(model="gpt-6-luna", max_input_tokens=30000, timeout_seconds=300)
    started = time.monotonic()
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists():
            state = json.loads(path.read_bytes())
            if state["config"] != config or state["plan_sha256"] != plan_hash or state["max_chars"] != max_chars:
                raise ValueError("window campaign configuration drift")
            if work_ids and set(work_ids) != set(state["papers"]):
                raise ValueError("resume must preserve selected papers")
        else:
            originals = available_bundles(root, allowed)
            selected = list(dict.fromkeys(work_ids or sorted(originals)[:paper_limit]))
            if not selected or set(selected) - originals.keys():
                raise ValueError("selected arXiv paper has no acquired original bundle")
            state = {"schema": "materials-ner-window-campaign/1", "name": name,
                     "plan_sha256": plan_hash, "config": config, "max_chars": max_chars,
                     "papers": {}, "outcomes": [], "aps_enabled": False}
            for work in selected:
                bundle = load_bundle(root / "bundles" / f"{originals[work]}.json")
                manifest = make_windows(root, bundle, max_chars=max_chars)
                jobs = [store.enqueue(work_id=work, bundle_hash=w["bundle_sha256"], config=config)
                        for w in manifest["windows"]]
                state["papers"][work] = {"parent_bundle_sha256": originals[work], "jobs": jobs,
                                        "target_characters": manifest["target_characters"],
                                        "text_coverage_planned": True}
            private_write(path, canonical(state).encode())
        ids = [j for paper in state["papers"].values() for j in paper["jobs"]]
        queue = {j["id"]: j for j in store.results()}
        for identifier in ids:
            job = queue[identifier]
            if job["state"] not in {"queued", "running"} and job["result_hash"]:
                ingest_job(store, identifier)
        pending = [j for j in ids if queue[j]["state"] == "queued" and queue[j]["available_at"] <= time.time()
                   or queue[j]["state"] == "running" and (queue[j]["lease_until"] or 0) < time.time()]
        completed = 0
        stop_reason = "bounded_run_complete"
        # Batches limit in-flight work and provide failure/STOP checkpoints.
        while pending and completed < max_jobs and time.monotonic() - started < max_wall_seconds:
            if (directory / "STOP").exists():
                stop_reason = "operator_stop_file"
                break
            selected, pending = pending[:min(10, max_jobs - completed)], pending[min(10, max_jobs - completed):]
            outcomes = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                def task(identifier):
                    remaining = max_wall_seconds - (time.monotonic() - started)
                    return run_one(store, job_id=identifier, max_seconds=remaining) if remaining > 1 else None
                futures = [pool.submit(task, identifier) for identifier in selected]
                for future in as_completed(futures):
                    result = future.result()
                    if result is None:
                        continue
                    completed += 1
                    with store.connect() as db:
                        terminal = db.execute("SELECT state FROM jobs WHERE id=?", (result["job_id"],)).fetchone()[0]
                    if terminal not in {"running", "queued"}:
                        imported = ingest_job(store, result["job_id"])
                        for key in ("candidate_results", "pending_review_results", "quarantined_results"):
                            result[key] = imported[key]
                        result["remote_readback_verified"] = bool(imported.get("remote") and imported["remote"].get("readback_verified"))
                    outcomes.append(result)
                    state["outcomes"].append(result)
                    private_write(path, canonical(state).encode())
                    progress(canonical({"event": "window_finished", **result}))
            if any(r["state"] == "failed" for r in outcomes):
                stop_reason = "provider_or_worker_failure"
                break
            if sum(r.get("error_code") == "output_schema_invalid" for r in outcomes) >= max(2, len(outcomes) / 2):
                stop_reason = "schema_failure_circuit_breaker"
                break
        queue = {j["id"]: j for j in store.results()}
        paper_status = {}
        for work, paper in state["papers"].items():
            states = [queue[j]["state"] for j in paper["jobs"]]
            paper_status[work] = {"windows": len(states), "states": {s: states.count(s) for s in set(states)},
                                  "all_windows_attempted": all(s not in {"queued", "running"} for s in states),
                                  "all_windows_technically_valid": all(s in {"succeeded", "success_empty"} for s in states),
                                  "scientific_acceptance": False}
        state.update(stop_reason=stop_reason, paper_status=paper_status)
        private_write(path, canonical(state).encode())
    return {"campaign": name, "papers": paper_status, "attempted_this_run": completed,
            "stop_reason": stop_reason, "elapsed_seconds": time.monotonic() - started,
            "proposal_database": ProposalDatabase(root).summary()}
