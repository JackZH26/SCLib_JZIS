"""Historical arXiv batches; source transport is separate from local proposal staging.

This is not the reviewed-drafting full-corpus runner. Its extraction contract is
retained for replay, and ambiguous source representations require explicit review.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re
import time

from .contract import canonical, digest
from .database import ingest_job
from .planning import acquire_batch, load_plan
from .proposals import ProposalDatabase
from .sources import load_bundle, private_write
from .store import Store
from .worker import configuration, run_one


def available_bundles(root: Path, allowed: set[str]) -> dict:
    found = {}
    for path in sorted((root / "bundles").glob("*.json")):
        bundle = load_bundle(path)
        if any(note.startswith("SOURCE_WINDOW ") for note in bundle.acquisition_notes):
            continue
        if bundle.work_id in allowed:
            identifier = digest(bundle.model_dump())
            if identifier != path.stem:
                raise ValueError("bundle filename is not its hash")
            if bundle.work_id in found and found[bundle.work_id] != identifier:
                raise ValueError("explicit_source_selection_required: " + bundle.work_id)
            found[bundle.work_id] = identifier
    return found


def campaign_status(root: Path, name: str) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", name):
        raise ValueError("invalid campaign name")
    path = root / "campaigns" / name / "state.json"
    state = json.loads(path.read_bytes())
    with Store(root).connect() as db:
        rows = {row["id"]: dict(row) for row in db.execute("SELECT id,state,work_id FROM jobs")}
    counts = {}
    for identifier in state["jobs"].values():
        value = rows[identifier]["state"]
        counts[value] = counts.get(value, 0) + 1
    return {"campaign": name, "model": state["config"]["model"],
            "scope": "arxiv_only", "planned_works": state["planned_works"],
            "selected_works": len(state["jobs"]), "states": counts,
            "batches": state["batches"], "stop_reason": state.get("stop_reason"),
            "proposal_database": ProposalDatabase(root).summary(), "aps_enabled": False}


def run_campaign(root: Path, plan_path: Path, *, name="arxiv-luna-20261021", batch_size=10,
                 max_batches=1, workers=2, max_wall_seconds=3600, source_ssh_host=None,
                 max_input_tokens=90000, timeout_seconds=600, progress=print):
    if (not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", name) or not 1 <= batch_size <= 100
            or not 1 <= max_batches <= 1000 or not 1 <= workers <= 4
            or not 1 <= max_wall_seconds <= 86400):
        raise ValueError("invalid bounded campaign parameters")
    plan, plan_hash = load_plan(plan_path)
    papers = {row["id"]: row for row in plan["papers"] if row["source"] == "arxiv"}
    directory = root / "campaigns" / name
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    state_path = directory / "state.json"
    config = configuration(model="gpt-6-luna", max_input_tokens=max_input_tokens,
                           timeout_seconds=timeout_seconds)
    store = Store(root)
    started = time.monotonic()
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if state_path.exists():
            state = json.loads(state_path.read_bytes())
            if state["plan_sha256"] != plan_hash or state["config"] != config:
                raise ValueError("campaign contract changed; select a new campaign name")
        else:
            state = {"schema": "materials-ner-campaign/1", "name": name, "plan_sha256": plan_hash,
                     "planned_works": len(papers), "config": config, "jobs": {}, "batches": [],
                     "created_at": datetime.now(timezone.utc).isoformat(), "aps_enabled": False}
            private_write(state_path, canonical(state).encode())
        state["stop_reason"] = None
        for _ in range(max_batches):
            if time.monotonic() - started >= max_wall_seconds:
                state["stop_reason"] = "wall_budget_exhausted"
                break
            if (directory / "STOP").exists():
                state["stop_reason"] = "operator_stop_file"
                break
            queue = {row["id"]: row for row in store.results()}
            # Replay exact packets against the actual local database. A saved
            # receipt alone cannot prove that this destination still has the rows.
            for identifier in state["jobs"].values():
                job = queue[identifier]
                if job["state"] not in {"queued", "running"} and job["result_hash"]:
                    ingest_job(store, identifier)
            pending = [identifier for identifier in state["jobs"].values()
                       if queue[identifier]["state"] in {"queued", "running"}]
            room = batch_size - len(pending)
            if room > 0:
                bundles = available_bundles(root, set(papers))
                candidates = [work for work in bundles if work not in state["jobs"]]
                if len(candidates) < room:
                    # Existing GCS archives can advance independently of missing-source recovery.
                    acquire_batch(root, plan_path, limit=min(100, room - len(candidates)),
                                  ssh_host=source_ssh_host, processing_allowed=True)
                    bundles = available_bundles(root, set(papers))
                    candidates = [work for work in bundles if work not in state["jobs"]]
                candidates.sort(key=lambda work: (-(papers[work].get("old_ner_records") or 0), digest(work)))
                for work in candidates[:room]:
                    identifier = store.enqueue(work_id=work, bundle_hash=bundles[work], config=config)
                    state["jobs"][work] = identifier
                    pending.append(identifier)
                private_write(state_path, canonical(state).encode())
            if not pending:
                state["stop_reason"] = "no_ready_original_sources"
                break
            batch_id = len(state["batches"]) + 1
            batch = {"batch": batch_id, "job_ids": pending[:batch_size],
                     "started_at": datetime.now(timezone.utc).isoformat(), "outcomes": []}
            progress(canonical({"event": "batch_started", "campaign": name, "batch": batch_id,
                                "jobs": len(batch["job_ids"]), "model": "gpt-6-luna"}))
            batch_start = time.monotonic()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                def task(identifier):
                    remaining = max_wall_seconds - (time.monotonic() - started)
                    if remaining < 1:
                        return None
                    return run_one(store, job_id=identifier, max_seconds=remaining)
                futures = {pool.submit(task, identifier): identifier for identifier in batch["job_ids"]}
                for future in as_completed(futures):
                    result = future.result()
                    if result is None:
                        continue
                    with store.connect() as db:
                        current = db.execute("SELECT state FROM jobs WHERE id=?", (result["job_id"],)).fetchone()[0]
                    if current not in {"queued", "running"}:
                        imported = ingest_job(store, result["job_id"])
                        result["database_imported"] = True
                        result["remote_readback_verified"] = bool(
                            imported.get("remote") and imported["remote"].get("readback_verified"))
                        for key in ("candidate_results", "pending_review_results", "quarantined_results"):
                            result[key] = imported[key]
                    batch["outcomes"].append(result)
                    private_write(directory / f"batch-{batch_id:05d}.json", canonical(batch).encode())
                    progress(canonical({"event": "job_finished", **result}))
            batch["elapsed_seconds"] = time.monotonic() - batch_start
            private_write(directory / f"batch-{batch_id:05d}.json", canonical(batch).encode())
            state["batches"].append({"batch": batch_id, "jobs": len(batch["job_ids"]),
                                     "completed": len(batch["outcomes"]),
                                     "elapsed_seconds": batch["elapsed_seconds"]})
            # Provider outage/quota must stop this campaign instead of burning through the corpus.
            errors = [r for r in batch["outcomes"] if r["state"] == "failed"]
            if errors:
                state["stop_reason"] = "provider_or_worker_failure"
            schema_failures = sum(r.get("error_code") == "output_schema_invalid" for r in batch["outcomes"])
            if schema_failures >= max(2, len(batch["outcomes"]) / 2):
                state["stop_reason"] = "schema_failure_circuit_breaker"
            if (len(batch["outcomes"]) >= 5
                    and sum(r.get("pending_review_results", 0) for r in batch["outcomes"]) == 0):
                state["stop_reason"] = "no_usable_proposals_circuit_breaker"
            if not batch["outcomes"]:
                state["stop_reason"] = "no_claimable_jobs"
            private_write(state_path, canonical(state).encode())
            if state["stop_reason"]:
                break
        state["stop_reason"] = state.get("stop_reason") or "bounded_run_complete"
        private_write(state_path, canonical(state).encode())
    return campaign_status(root, name)
