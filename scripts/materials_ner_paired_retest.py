#!/usr/bin/env python3
"""Bounded paired Luna retest on exactly the locked baseline window bundles.

These engineering diagnostics measure technical defects and candidate yield,
not precision/recall against scientific Gold. Every attempt is retained.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
from ingestion.materials_ner.contract import canonical, digest  # noqa: E402
from ingestion.materials_ner.database import ingest_job  # noqa: E402
from ingestion.materials_ner.proposals import review_rows  # noqa: E402
from ingestion.materials_ner.contract import parse_extraction  # noqa: E402
from ingestion.materials_ner.sources import private_write, sha  # noqa: E402
from ingestion.materials_ner.store import Store  # noqa: E402
from ingestion.materials_ner.worker import configuration, run_one  # noqa: E402


def summarize(root, jobs):
    codes, states, review, kinds, papers = Counter(), Counter(), Counter(), Counter(), {}
    tokens, elapsed = Counter(), 0.0
    for job in jobs:
        states[job["state"]] += 1
        if not job["result_path"]:
            continue
        receipt_raw = (root / job["result_path"]).read_bytes()
        if sha(receipt_raw) != job["result_hash"]:
            raise ValueError("paired receipt integrity failure")
        receipt = json.loads(receipt_raw)
        elapsed += receipt["elapsed_seconds"]
        tokens.update(receipt.get("usage", {}))
        codes.update(i["code"] for i in receipt.get("validation", {}).get("issues", []))
        if receipt.get("error_code") and "validation" not in receipt:
            codes[receipt["error_code"]] += 1
        work = papers.setdefault(job["work_id"], Counter())
        work["windows"] += 1
        if "extraction" in receipt:
            extraction = parse_extraction(receipt["extraction"])
            rows = review_rows(extraction, receipt["validation"])["results"]
            review.update(row["review_status"] for row in rows)
            kinds.update(row["payload"]["quantity_kind"] for row in rows)
            work["candidate_results"] += len(rows)
            work.update(row["review_status"] for row in rows)
    return {"states": dict(states), "issues": dict(codes), "review_states": dict(review),
            "candidate_results": sum(review.values()), "kinds": dict(kinds),
            "papers": {k: dict(v) for k, v in papers.items()}, "usage": dict(tokens),
            "summed_worker_seconds": elapsed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-jobs", type=int, default=62)
    parser.add_argument("--max-wall-seconds", type=int, default=3600)
    args = parser.parse_args()
    if not 1 <= args.workers <= 4 or not 1 <= args.max_jobs <= 300 or not 1 <= args.max_wall_seconds <= 14400:
        parser.error("invalid retest budget")
    root = args.root.absolute()
    baseline = json.loads(args.baseline.read_bytes())
    if baseline["schema"] != "materials-ner-paired-baseline/1":
        raise ValueError("unknown baseline")
    config = configuration(model="gpt-6-luna", max_input_tokens=30000, timeout_seconds=300)
    directory = args.baseline.parent / digest(config)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    state_path = directory / "state.json"
    store = Store(root)
    started = time.monotonic()
    completed = 0
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        jobs = {j["id"]: j for j in store.results()}
        pairs = []
        for row in baseline["jobs"]:
            previous = jobs[row["id"]]
            if any(previous[k] != row[k] for k in ("work_id", "bundle_hash", "result_path", "result_hash")):
                raise ValueError("baseline changed")
            new = store.enqueue(work_id=row["work_id"], bundle_hash=row["bundle_hash"], config=config)
            pairs.append({"work_id": row["work_id"], "bundle_sha256": row["bundle_hash"],
                          "old_job_id": row["id"], "new_job_id": new})
        state = {"schema": "materials-ner-paired-retest/1", "baseline_sha256": digest(baseline),
                 "config": config, "pairs": pairs, "state": "running", "scientific_gold": False,
                 "scientific_acceptance": False, "ml_training_eligible": False,
                 "started_at": datetime.now(timezone.utc).isoformat()}
        private_write(state_path, canonical(state).encode())
        jobs = {j["id"]: j for j in store.results()}
        pending = [p["new_job_id"] for p in pairs if jobs[p["new_job_id"]]["state"] == "queued"
                   and jobs[p["new_job_id"]]["available_at"] <= time.time()]
        reason = "all_pairs_attempted"
        while pending and completed < args.max_jobs:
            remaining = args.max_wall_seconds - (time.monotonic() - started)
            if remaining < 1 or (directory / "STOP").exists():
                reason = "wall_budget_or_operator_stop"
                break
            batch, pending = pending[:min(10, args.max_jobs - completed)], pending[min(10, args.max_jobs - completed):]
            outcomes = []
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = [pool.submit(run_one, store, job_id=j, max_seconds=remaining) for j in batch]
                for future in as_completed(futures):
                    result = future.result()
                    if result is None:
                        continue
                    completed += 1
                    with store.connect() as db:
                        terminal = db.execute("SELECT state FROM jobs WHERE id=?", (result["job_id"],)).fetchone()[0]
                    imported = (ingest_job(store, result["job_id"])
                                if terminal not in {"queued", "running"} else {})
                    outcomes.append(result)
                    print(canonical({"event": "paired_window_finished", **result,
                          **{k: imported.get(k) for k in ("candidate_results", "pending_review_results", "quarantined_results")},
                          "remote_readback_verified": bool((imported.get("remote") or {}).get("readback_verified"))}), flush=True)
            jobs = {j["id"]: j for j in store.results()}
            state.update(attempted_this_run=completed,
                         old=summarize(root, [jobs[p["old_job_id"]] for p in pairs]),
                         new=summarize(root, [jobs[p["new_job_id"]] for p in pairs]))
            private_write(state_path, canonical(state).encode())
            if any(r["state"] in {"failed", "blocked"} for r in outcomes):
                reason = "provider_or_worker_failure"
                break
            if sum(r.get("error_code") in {"output_schema_invalid", "output_source_binding_invalid"}
                   for r in outcomes) >= max(2, len(outcomes) / 2):
                reason = "schema_failure_circuit_breaker"
                break
        jobs = {j["id"]: j for j in store.results()}
        # Resume also verifies import receipts for prior completed attempts.
        for pair in pairs:
            job = jobs[pair["new_job_id"]]
            if job["state"] in {"queued", "running"} or not job["result_hash"]:
                continue
            ingest_job(store, job["id"])
        state.update(state="checkpointed", stop_reason=reason if not pending else (
                     reason if reason != "all_pairs_attempted" else "job_budget_exhausted"),
                     attempted_this_run=completed, elapsed_seconds=time.monotonic() - started,
                     old=summarize(root, [jobs[p["old_job_id"]] for p in pairs]),
                     new=summarize(root, [jobs[p["new_job_id"]] for p in pairs]))
        private_write(state_path, canonical(state).encode())
    print(canonical({"state_path": str(state_path), "stop_reason": state["stop_reason"],
                     "old": state["old"], "new": state["new"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
