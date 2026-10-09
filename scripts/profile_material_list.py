"""Bounded public GET profiling with fixed Materials queries and a version fence.

No cache purge, random cache-busting parameters, provider queries or database access.
Headers unavailable on an older release remain unavailable, never inferred timings.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

try:
    from scripts import verify_public_snapshot as public
except ModuleNotFoundError:  # Direct execution from scripts/.
    import verify_public_snapshot as public

REQUESTS = {**public.REQUESTS,
            "source_count_min2": "/materials?sort=total_papers&min_papers=2&limit=25&offset=0"}
STAGES = frozenset({"revision", "lock_wait", "scan_fetch", "scope", "selection", "scan_close",
                    "projection", "ranking_page", "ranking_publish", "serialization", "total"})
PATHS = frozenset({"uncached", "page_hit", "waited_hit", "ranking", "scan"})


def parse_timing(header):
    if not header:
        return {"status": "not_emitted"}
    if len(header) > 2048:
        return {"status": "invalid"}
    parts = header.split(", ")
    first = re.fullmatch(r'materials_path;desc="([a-z_]+)"', parts[0])
    if first is None or first[1] not in PATHS or len(parts) > len(STAGES) + 1:
        return {"status": "invalid"}
    values = {}
    for part in parts[1:]:
        match = re.fullmatch(r"([a-z_]+);dur=(\d{1,12}\.\d{3})", part)
        if match is None or match[1] not in STAGES or match[1] in values:
            return {"status": "invalid"}
        values[match[1]] = float(match[2])
    if "total" not in values or sum(v for k, v in values.items() if k != "total") > values["total"] + .02:
        return {"status": "invalid"}
    return {"status": "available", "path": first[1], "stage_ms": values}


def summarize(attempts):
    result = public.latency_summary(attempts)
    successful = [item for item in attempts if item["status"] == 200 and not item["error"]]
    result["timing_status_counts"] = {
        state: sum(item["timing"]["status"] == state for item in successful)
        for state in ("available", "not_emitted", "invalid")
    }
    result["by_server_path"] = {}
    for path in sorted(PATHS):
        group = [item for item in successful if item["timing"].get("path") == path]
        if not group:
            continue
        result["by_server_path"][path] = {
            "samples": len(group),
            "client_median_seconds": statistics.median(item["elapsed_seconds"] for item in group),
            "stage_median_ms": {stage: statistics.median(values) for stage in sorted(STAGES)
                                if (values := [item["timing"]["stage_ms"][stage] for item in group
                                               if stage in item["timing"]["stage_ms"]])},
        }
    return result


def collect(samples=3):
    if type(samples) is not int or not 1 <= samples <= 10:
        raise ValueError("samples_out_of_range")
    started_at = public.utc_now()
    before_meta, before = public.json_request(public.API + "/version", "gzip")
    report = {"schema_version": "sclib-material-list-profile/1.0.0", "started_at": started_at,
              "scientific_acceptance": False, "slo_acceptance": None,
              "database_transaction_snapshot": False,
              "version_before": before, "version_requests": [before_meta], "profiles": {},
              "measurement_scope": "Sequential urllib GETs include TLS/transfer/decode; server total covers decorated route only. No SQL/root-cause or cold-database claim."}
    for name, path in REQUESTS.items():
        attempts = []
        for _ in range(samples):
            meta, value = public.json_request(public.API + path, "gzip")
            if value is not None and (type(value.get("total")) is not int
                                      or not isinstance(value.get("results"), list)):
                meta["error"] = "InvalidMaterialsEnvelope"
            if value is not None and not meta["error"]:
                meta.update(total=value["total"], rows=len(value["results"]))
            meta["timing"] = parse_timing(meta.get("headers", {}).get("server-timing"))
            attempts.append(meta)
        report["profiles"][name] = {"path": path, "attempts": attempts, "summary": summarize(attempts)}
    after_meta, after = public.json_request(public.API + "/version", "gzip")
    report["version_requests"].append(after_meta)
    report["version_after"] = after
    report["version_stable"] = public.same_version(before, after)
    attempts = [item for profile in report["profiles"].values() for item in profile["attempts"]]
    report["http_capture_complete"] = bool(report["version_stable"] and all(
        item["status"] == 200 and not item["error"] for item in [before_meta, *attempts, after_meta]))
    report["server_profile_complete"] = bool(report["http_capture_complete"] and all(
        item["timing"]["status"] == "available" for item in attempts))
    report["finished_at"] = public.utc_now()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-server-timing", action="store_true")
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as handle:
        report = collect(args.samples)
        json.dump(report, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    print(json.dumps({key: report[key] for key in
                      ("http_capture_complete", "server_profile_complete", "version_stable")}))
    return 0 if report["http_capture_complete"] and (
        not args.require_server_timing or report["server_profile_complete"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
