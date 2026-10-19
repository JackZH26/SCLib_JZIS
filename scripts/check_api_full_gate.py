"""Release latch: exact Test summary plus recent successful full coverage.

Known independent full-suite failures block targeted releases. A full passing
Test at the target revision can supersede an older ancestor's failed full run.
GitHub errors, unknown run states and missing/expired evidence fail closed.
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import io
import json
import os
import re
import subprocess
import urllib.request
import zipfile

from scripts import runtime_inventory

REPO = "JackZH26/SCLib_JZIS"


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit

        if urlsplit(newurl).scheme != "https":
            raise ValueError("insecure_artifact_redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urlsplit(req.full_url).netloc != urlsplit(newurl).netloc:
            redirected.remove_header("Authorization")
        return redirected


def api(path, binary=False):
    request = urllib.request.Request(
        "https://api.github.com/repos/" + REPO + "/" + path,
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.build_opener(SafeRedirect()).open(
        request, timeout=45
    ) as response:
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("oversized_github_response")
    return raw if binary else json.loads(raw)


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def ancestor(old, new):
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", old, new], check=False
        ).returncode
        == 0
    )


def decide(current, latest, *, now, is_ancestor):
    full = (
        current["summary"]["full_module_coverage"]
        and current["summary"]["mode"] == "full"
    )
    if latest:
        if latest["status"] != "completed":
            raise ValueError("independent_full_regression_unfinished")
        if not is_ancestor(latest["head_sha"], current["head_sha"]):
            raise ValueError("full_regression_is_not_target_ancestor")
        if stamp(latest["updated_at"]) > stamp(current["updated_at"]):
            if latest["conclusion"] != "success":
                raise ValueError("newer_full_regression_not_successful")
        elif latest["conclusion"] != "success" and not full:
            raise ValueError("unresolved_full_regression_failure")
    if full:
        return "exact_target_full_coverage"
    if not latest or latest["conclusion"] != "success":
        raise ValueError("no_successful_full_baseline")
    age = (now - stamp(latest["updated_at"])).total_seconds()
    if not 0 <= age <= 7 * 86400:
        raise ValueError("full_baseline_expired")
    return "targeted_plus_recent_full_baseline"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--test-run", type=int, required=True)
    p.add_argument("--revision", required=True)
    a = p.parse_args()
    if not re.fullmatch("[0-9a-f]{40}", a.revision):
        raise ValueError("invalid_revision")
    current = api(f"actions/runs/{a.test_run}")
    if any(
        (
            current["head_sha"] != a.revision,
            current["path"] != ".github/workflows/test.yml",
            current["event"] != "push",
            current["head_branch"] != "main",
            current["conclusion"] != "success",
            current["status"] != "completed",
            current["head_repository"]["full_name"] != REPO,
        )
    ):
        raise ValueError("not_successful_exact_main_test")
    artifacts = api(f"actions/runs/{a.test_run}/artifacts?per_page=100")["artifacts"]
    matches = [
        x
        for x in artifacts
        if x["name"] == f"api-validation-summary-attempt-{current['run_attempt']}"
        and not x["expired"]
    ]
    if len(matches) != 1:
        raise ValueError("missing_unique_api_summary")
    with zipfile.ZipFile(
        io.BytesIO(api(f"actions/artifacts/{matches[0]['id']}/zip", True))
    ) as archive:
        if (
            archive.namelist() != ["api-summary.json"]
            or archive.getinfo("api-summary.json").file_size > 2 * 1024 * 1024
        ):
            raise ValueError("invalid_summary_archive")
        summary = json.loads(archive.read("api-summary.json"))
    if (
        summary["status"] != "passed"
        or summary["revision"] != a.revision
        or summary["counts"]["failed"]
        or summary["counts"]["errors"]
        or len(summary["batches"]) != 8
    ):
        raise ValueError("failed_or_wrong_revision_api_summary")
    inventories = [
        x
        for x in artifacts
        if x["name"] == f"api-test-runtime-inventory-attempt-{current['run_attempt']}"
        and not x["expired"]
    ]
    if len(inventories) != 1:
        raise ValueError("missing_unique_image_parity_inventory")
    with zipfile.ZipFile(
        io.BytesIO(api(f"actions/artifacts/{inventories[0]['id']}/zip", True))
    ) as archive:
        if (
            archive.namelist().count("test-runtime.json") != 1
            or archive.getinfo("test-runtime.json").file_size > 2 * 1024 * 1024
        ):
            raise ValueError("invalid_image_parity_inventory_archive")
        image_test_runtime = runtime_inventory.loads(
            archive.read("test-runtime.json").decode()
        )
    if runtime_inventory.compare(
        summary["runtime"], image_test_runtime
    ) or runtime_inventory.compare(image_test_runtime, summary["runtime"]):
        raise ValueError("parallel_tests_differ_from_image_parity_runtime")
    current["summary"] = summary
    # The committed workflow must exist; API/auth/history failures never pass.
    runs = api("actions/workflows/api-full.yml/runs?branch=main&per_page=100")[
        "workflow_runs"
    ]
    full = [
        x
        for x in runs
        if x["path"] == ".github/workflows/api-full.yml"
        and x["event"] in ("schedule", "workflow_dispatch")
        and x["head_repository"]["full_name"] == REPO
    ]
    latest = (
        max(full, key=lambda x: (x["updated_at"], x["run_attempt"])) if full else None
    )
    result = decide(
        current, latest, now=datetime.now(timezone.utc), is_ancestor=ancestor
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "revision": a.revision,
                "basis": result,
                "independent_full_run": latest["id"] if latest else None,
            }
        )
    )


if __name__ == "__main__":
    main()
