"""Run bounded, resumable arXiv gap recovery on the Mac; no model or APS calls."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
from ingestion.materials_ner.contract import canonical  # noqa: E402
from ingestion.materials_ner.recovery import recover_batch  # noqa: E402
from ingestion.materials_ner.sources import private_write  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--max-papers", type=int, default=2327)
    parser.add_argument("--max-wall-seconds", type=int, default=43200)
    parser.add_argument("--max-bytes", type=int, default=16 * 1024**3)
    args = parser.parse_args()
    if (not 1 <= args.max_papers <= 3000 or not 1 <= args.max_wall_seconds <= 86400
            or not 1 <= args.max_bytes <= 64 * 1024**3):
        parser.error("use a bounded recovery run")
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    progress_path = root / "recovery-campaign-status.json"
    started = time.monotonic()
    state = {"schema": "materials-arxiv-recovery-campaign/1", "pid": os.getpid(),
             "started_at": datetime.now(timezone.utc).isoformat(), "state": "running",
             "attempted_this_run": 0, "downloaded_bytes_this_run": 0, "batches": [],
             "aps_enabled": False, "model_calls": 0}
    with (root / "recovery-campaign.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        private_write(progress_path, canonical(state).encode())
        try:
            while state["attempted_this_run"] < args.max_papers:
                remaining_seconds = args.max_wall_seconds - (time.monotonic() - started)
                remaining_bytes = args.max_bytes - state["downloaded_bytes_this_run"]
                if remaining_seconds < 1 or remaining_bytes < 1:
                    state.update(state="checkpointed", stop_reason="run_budget_exhausted")
                    break
                if (root / "RECOVERY_STOP").exists():
                    state.update(state="checkpointed", stop_reason="operator_stop_file")
                    break
                if shutil.disk_usage(root).free < 10 * 1024**3:
                    state.update(state="checkpointed", stop_reason="free_disk_below_10GiB")
                    break
                result = recover_batch(root, args.plan,
                                       limit=min(25, args.max_papers - state["attempted_this_run"]),
                                       max_bytes=min(256 * 1024**2, remaining_bytes),
                                       max_seconds=max(1, int(min(1800, remaining_seconds))),
                                       ssh_host=args.ssh_host)
                state["attempted_this_run"] += result["attempted"]
                state["downloaded_bytes_this_run"] += result["downloaded_bytes"]
                record = {key: value for key, value in result.items() if key != "outcomes"}
                record["bundled"] = sum(row["state"] == "bundled" for row in result["outcomes"])
                state["batches"].append(record)
                private_write(root / "recovery-campaign-batches" /
                              f"{os.getpid()}-{len(state['batches']):05d}.json", canonical(result).encode())
                private_write(progress_path, canonical(state).encode())
                print(canonical(record), flush=True)
                if result["stop_reason"] or result["attempted"] == 0:
                    state.update(state="checkpointed",
                                 stop_reason=result["stop_reason"] or "no_unattempted_gaps")
                    break
            state["state"] = "checkpointed"
            state.setdefault("stop_reason", "paper_budget_exhausted")
        except Exception as error:
            state.update(state="failed", error_class=type(error).__name__)
        finally:
            state["elapsed_seconds"] = time.monotonic() - started
            private_write(progress_path, canonical(state).encode())
    print(canonical(state), flush=True)
    return int(state["state"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
