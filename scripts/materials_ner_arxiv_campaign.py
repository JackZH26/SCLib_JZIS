"""Advance arXiv papers through Luna source windows and private proposal ingestion."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
from ingestion.materials_ner.campaign import available_bundles  # noqa: E402
from ingestion.materials_ner.contract import canonical, digest  # noqa: E402
from ingestion.materials_ner.planning import acquire_batch, load_plan  # noqa: E402
from ingestion.materials_ner.sources import load_bundle, private_write  # noqa: E402
from ingestion.materials_ner.window_campaign import run_window_campaign  # noqa: E402
from ingestion.materials_ner.worker import configuration  # noqa: E402


def source_exclusions(root):
    excluded = {}
    for path in sorted((root / "source-advisories").glob("*.json")):
        advisory = json.loads(path.read_bytes())
        if advisory.get("schema") != "materials-source-advisory/1":
            raise ValueError("unknown source advisory schema")
        if advisory.get("exclude_from_new_ner"):
            excluded[advisory["work_id"]] = {
                "source_status": advisory["source_status"],
                "advisory_sha256": digest(advisory),
                "evidence_url": advisory["evidence_url"],
            }
    return excluded


def source_readiness(bundle):
    """A PDF inclusion wrapper is not the paper's extracted body.

This conservative hold is tied to the bundle, not the work: a later original
PDF representation is immediately eligible. It never substitutes old NER facts.
    """
    text = "\n".join(block.text for block in bundle.blocks)
    if "\\includepdf" in text and len(text) < 2500:
        return {"ready": False, "reason": "pdf_inclusion_wrapper_requires_body_resolution",
                "text_characters": len(text)}
    return {"ready": True, "text_characters": len(text)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source-ssh-host", "--ssh-host", dest="source_ssh_host", required=True,
                        help="Read-only source transport; proposal staging stays local")
    parser.add_argument("--max-papers", type=int, default=30)
    parser.add_argument("--max-jobs", type=int, default=300)
    parser.add_argument("--max-wall-seconds", type=int, default=14400)
    args = parser.parse_args()
    if not 1 <= args.max_papers <= 1000 or not 1 <= args.max_jobs <= 2000 or not 1 <= args.max_wall_seconds <= 86400:
        parser.error("invalid campaign budgets")
    root = args.root.resolve()
    plan, plan_hash = load_plan(args.plan)
    papers = {p["id"]: p for p in plan["papers"] if p["source"] == "arxiv"}
    config = configuration(model="gpt-6-luna", max_input_tokens=30000, timeout_seconds=300)
    directory = root / "arxiv-manager" / digest(config)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    state_path = directory / "state.json"
    started = time.monotonic()
    attempts, visited, zero_valid_papers = 0, 0, 0
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(state_path.read_bytes()) if state_path.exists() else {
            "schema": "materials-arxiv-manager/1", "plan_sha256": plan_hash,
            "config": config, "papers": {}, "aps_enabled": False}
        if state["plan_sha256"] != plan_hash or state["config"] != config:
            raise ValueError("manager configuration drift")
        state.update(pid=os.getpid(), state="running", started_at=datetime.now(timezone.utc).isoformat())
        state.pop("stop_reason", None)
        private_write(root / "arxiv-manager-current.json", canonical({
            "path": str(state_path), "pid": os.getpid(), "config_sha256": digest(config),
            "max_papers": args.max_papers, "max_jobs": args.max_jobs,
            "max_wall_seconds": args.max_wall_seconds}).encode())
        private_write(state_path, canonical(state).encode())
        try:
            while visited < args.max_papers and attempts < args.max_jobs:
                remaining = args.max_wall_seconds - (time.monotonic() - started)
                if remaining < 1 or (directory / "STOP").exists():
                    state["stop_reason"] = "wall_budget_or_operator_stop"
                    break
                if shutil.disk_usage(root).free < 10 * 1024**3:
                    state["stop_reason"] = "free_disk_below_10GiB"
                    break
                excluded = source_exclusions(root)
                state["source_exclusions"] = excluded
                originals = available_bundles(root, set(papers))
                def already_attempted(work):
                    saved = state["papers"].get(work, {})
                    return (saved.get("all_windows_attempted")
                            and saved.get("parent_bundle_sha256") == originals[work])
                candidates = [w for w in originals if w not in excluded and not already_attempted(w)]
                if not candidates:
                    acquisition = acquire_batch(root, args.plan, limit=10, ssh_host=args.source_ssh_host,
                                                processing_allowed=True)
                    originals = available_bundles(root, set(papers))
                    candidates = [w for w in originals if w not in excluded and not already_attempted(w)]
                    if not candidates:
                        state["stop_reason"] = "no_ready_original_sources"
                        state["last_acquisition_attempted"] = acquisition["attempted_papers"]
                        break
                # Existing material-bearing papers first; shorter inputs provide
                # early heterogeneous batches. This is operational priority, not Gold sampling.
                profiles = {w: source_readiness(load_bundle(
                    root / "bundles" / f"{originals[w]}.json")) for w in candidates}
                holds = {w: {**profile, "bundle_sha256": originals[w]}
                         for w, profile in profiles.items() if not profile["ready"]}
                state.setdefault("source_preflight_holds", {}).update(holds)
                candidates = [w for w in candidates if profiles[w]["ready"]]
                if not candidates:
                    state["stop_reason"] = "original_body_resolution_required"
                    break
                lengths = {w: profiles[w]["text_characters"] for w in candidates}
                candidates.sort(key=lambda w: (not bool(papers[w].get("old_ner_records")), lengths[w], digest(w)))
                work = candidates[0]
                name = f"luna-window-{originals[work][:16]}-{digest(config)[:12]}"
                result = run_window_campaign(root, args.plan, name=name, work_ids=[work],
                                             max_jobs=min(2000, args.max_jobs - attempts), workers=2,
                                             max_wall_seconds=max(1, int(remaining)),
                                             progress=lambda value: print(value, flush=True))
                attempts += result["attempted_this_run"]
                visited += 1
                paper = result["papers"][work]
                state["papers"][work] = {**paper, "campaign": name,
                                         "parent_bundle_sha256": originals[work]}
                window_state = json.loads((root / "campaigns" / name / "windows-state.json").read_bytes())
                candidates_count = sum(r.get("candidate_results", 0) for r in window_state["outcomes"])
                valid_count = sum(r.get("pending_review_results", 0) for r in window_state["outcomes"])
                # An empty response with quantitative source hints is not a
                # successful empty paper. Count it in the same quality breaker.
                unresolved_windows = any(r.get("state") in {"quarantined", "failed", "blocked"}
                                         for r in window_state["outcomes"])
                zero_valid_papers = (zero_valid_papers + 1
                                     if (candidates_count or unresolved_windows) and not valid_count else 0)
                state.update(attempts_this_run=attempts, visited_this_run=visited,
                             elapsed_seconds=time.monotonic() - started)
                private_write(state_path, canonical(state).encode())
                if result["stop_reason"] in {"provider_or_worker_failure", "schema_failure_circuit_breaker"}:
                    state["stop_reason"] = result["stop_reason"]
                    break
                if zero_valid_papers >= 3:
                    state["stop_reason"] = "three_papers_without_valid_proposals"
                    break
                if not result["attempted_this_run"] and not paper["all_windows_attempted"]:
                    state["stop_reason"] = "pending_retry_or_lease"
                    break
            state.update(state="checkpointed", stop_reason=state.get("stop_reason", "run_budget_exhausted"))
        except Exception as error:
            state.update(state="failed", error_class=type(error).__name__)
        finally:
            state["elapsed_seconds"] = time.monotonic() - started
            private_write(state_path, canonical(state).encode())
    print(canonical({"state": state["state"], "stop_reason": state.get("stop_reason"),
                     "attempts_this_run": attempts, "visited_this_run": visited}), flush=True)
    return int(state["state"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
