"""Fail-closed API selection and exact-revision, isolated batch evidence.

A changed file is core-only only when explicitly classified. New/unknown runtime
code, deleted tests, auth/shared infrastructure and selector changes run all tests.
No arbitrary pytest filters or service URLs are accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from scripts.schema_rehearsal_report import capture_provenance, source_unchanged
from scripts import runtime_inventory
from scripts.tests.run_api_regression import (
    modules,
    counts,
    child_environment,
    write_new,
)

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def git(*args, root=ROOT):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def select(changed, inventory, policy, force_full=False):
    available = set(inventory)
    configured = set(policy["core"]) | {
        m for group in policy["mappings"].values() for m in group
    }
    if not configured <= available or len(policy["core"]) < 4:
        raise ValueError("policy_references_missing_modules")
    selected, reasons = set(policy["core"]), []
    if force_full:
        reasons.append("explicit_full_regression")
    for path in changed:
        if path in policy["critical_files"] or any(
            path.startswith(p) for p in policy["critical_prefixes"]
        ):
            reasons.append("critical:" + path)
        elif path in policy["mappings"]:
            selected.update(policy["mappings"][path])
        elif path.startswith("api/tests/") and path[4:] in available:
            selected.add(path[4:])
        elif path in policy["core_only_files"] or any(
            path.startswith(p) for p in policy["core_only_prefixes"]
        ):
            pass
        else:
            reasons.append("unmapped:" + path)
    return sorted(available if reasons else selected), reasons


def balanced(selected, weights):
    # Eight bounded service lifetimes, two sequential batches in each of four jobs.
    groups, totals = [[] for _ in range(8)], [0.0] * 8
    for module in sorted(selected, key=lambda m: (-weights.get(m, 60), m)):
        index = min(range(8), key=lambda i: (totals[i], len(groups[i]), i))
        groups[index].append(module)
        totals[index] += max(0.01, weights.get(module, 60))
    if any(not g for g in groups) or sorted(m for g in groups for m in g) != selected:
        raise ValueError("invalid_partition")
    # Pair longest with shortest so four jobs have similar estimated totals.
    order = sorted(range(8), key=lambda i: (totals[i], i))
    return [
        sorted(groups[i]) for pair in zip(order[:4], reversed(order[4:])) for i in pair
    ]


def plan(base, force_full=False, root=ROOT):
    head = git("rev-parse", "HEAD", root=root)
    if not re.fullmatch("[0-9a-f]{40}", base) or base == "0" * 40:
        raise ValueError("explicit_valid_base_required")
    git("merge-base", "--is-ancestor", base, head, root=root)
    policy = json.loads((root / "scripts/api_test_policy.json").read_text())
    weights = json.loads((root / "scripts/api_test_timings.json").read_text())[
        "seconds"
    ]
    # No rename detection: both deleted and added names are classified.
    raw = subprocess.check_output(
        ["git", "diff", "--name-only", "--no-renames", "-z", base, head], cwd=root
    )
    changed = sorted(x.decode() for x in raw.split(b"\0") if x)
    inventory = modules(root)
    selected, reasons = select(changed, inventory, policy, force_full)
    body = {
        "version": 1,
        "base": base,
        "revision": head,
        "mode": "full" if reasons else "targeted",
        "reasons": reasons,
        "changed": changed,
        "policy_sha256": digest(policy),
        "inventory": inventory,
        "selected": selected,
        "batches": balanced(selected, weights),
        "force_full": force_full,
    }
    return {**body, "plan_sha256": digest(body)}


def verify_plan(value, root=ROOT):
    if value != plan(value["base"], value["force_full"], root):
        raise ValueError("plan_does_not_match_exact_checkout")


def run_batch(
    value, index, output, backend, postgres_bin=None, redis_bin=None, root=ROOT
):
    verify_plan(value, root)
    if not 0 <= index < 8 or not output.is_absolute():
        raise ValueError("invalid_batch_request")
    output.mkdir(mode=0o700)
    before = capture_provenance(root)
    if before["source_dirty"]:
        raise ValueError("dirty_executed_source")
    report = {
        "revision": value["revision"],
        "plan_sha256": value["plan_sha256"],
        "batch": index,
        "modules": value["batches"][index],
        "status": "failed",
        "duration_seconds": 0,
    }
    start = time.monotonic()
    try:
        report["runtime"] = runtime_inventory.capture(
            root / "api/uv.lock", root / "api/pyproject.toml", value["revision"]
        )
        command = [
            sys.executable,
            str(root / "scripts/run_disposable_tests.py"),
            "--backend",
            backend,
            "--suite",
            "api",
        ]
        if backend == "native":
            if not postgres_bin or not redis_bin:
                raise ValueError("native_binary_paths_required")
            command += [
                "--postgres-bin",
                str(postgres_bin),
                "--redis-bin",
                str(redis_bin),
            ]
        command += [
            "--",
            "-q",
            "--tb=short",
            "--durations=10",
            f"--junitxml={output / 'junit.xml'}",
            *report["modules"],
        ]
        result = subprocess.run(command, cwd=root, env=child_environment(), check=False)
        report["exit_code"] = result.returncode
        report["counts"] = counts(output / "junit.xml", report["modules"])
        source_unchanged(before, capture_provenance(root))
        if (
            runtime_inventory.capture(
                root / "api/uv.lock", root / "api/pyproject.toml", value["revision"]
            )
            != report["runtime"]
        ):
            raise ValueError("test_runtime_changed")
        verify_plan(value, root)
        if (
            result.returncode == 0
            and report["counts"]["failed"] == report["counts"]["errors"] == 0
        ):
            report["status"] = "passed"
    finally:
        report["duration_seconds"] = round(time.monotonic() - start, 3)
        write_new(output / "result.json", report)
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in ("batch", "revision", "status", "duration_seconds")
                }
            ),
            flush=True,
        )
    return 0 if report["status"] == "passed" else 1


def aggregate(value, directory, root=ROOT):
    verify_plan(value, root)
    paths = sorted(directory.rglob("result.json"))
    if len(paths) != 8:
        raise ValueError("missing_or_duplicate_batch_reports")
    seen, results = set(), []
    for path in paths:
        item = json.loads(path.read_text())
        index = item["batch"]
        if type(index) is not int or not 0 <= index < 8 or index in seen:
            raise ValueError("unexpected_or_duplicate_batch")
        seen.add(index)
        if (
            item["status"] != "passed"
            or item.get("exit_code") != 0
            or item["revision"] != value["revision"]
            or item["plan_sha256"] != value["plan_sha256"]
            or item["modules"] != value["batches"][index]
        ):
            raise ValueError("failed_or_mismatched_batch")
        actual = counts(path.parent / "junit.xml", item["modules"])
        if actual != item["counts"] or actual["failed"] or actual["errors"]:
            raise ValueError("invalid_actual_junit")
        runtime_inventory.validate(item["runtime"])
        if results and item["runtime"] != results[0]["runtime"]:
            raise ValueError("batch_runtime_mismatch")
        if item["runtime"]["source_revision"] != value["revision"]:
            raise ValueError("batch_runtime_revision_mismatch")
        results.append(item)
    return {
        "status": "passed",
        "revision": value["revision"],
        "mode": value["mode"],
        "plan_sha256": value["plan_sha256"],
        "modules": len(value["selected"]),
        "full_module_coverage": value["selected"] == value["inventory"],
        "counts": {
            key: sum(x["counts"][key] for x in results)
            for key in ["passed", "failed", "errors", "skipped", "test_cases"]
        },
        "batches": sorted(results, key=lambda x: x["batch"]),
        "runtime": results[0]["runtime"],
    }


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--base", required=True)
    p.add_argument("--force-full", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("batch")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--backend", choices=["native", "docker"], required=True)
    p.add_argument("--postgres-bin", type=Path)
    p.add_argument("--redis-bin", type=Path)
    p = sub.add_parser("aggregate")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    if a.action == "plan":
        value = plan(a.base, a.force_full)
        write_new(a.output, value)
        print(
            json.dumps(
                {
                    "mode": value["mode"],
                    "modules": len(value["selected"]),
                    "revision": value["revision"],
                    "batches": [len(g) for g in value["batches"]],
                }
            )
        )
    elif a.action == "batch":
        return run_batch(
            json.loads(a.plan.read_text()),
            a.index,
            a.output,
            a.backend,
            a.postgres_bin,
            a.redis_bin,
        )
    else:
        value = aggregate(json.loads(a.plan.read_text()), a.directory)
        write_new(a.output, value)
        print(json.dumps(value["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
