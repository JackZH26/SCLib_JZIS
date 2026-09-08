#!/usr/bin/env python3
"""Deterministic local RPS service rehearsal, not an HTTP/production SLA.

Uses the locked API development runtime and explicitly synthetic fixture
builders. No configured publication directory, database, cloud client or HTTP
endpoint is read. Temporary canonical files are removed by TemporaryDirectory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import resource
import sys
import tempfile
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "rps-delivery-benchmark/1.0.0"


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid_arguments")


def _bounded_int(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError("invalid_arguments")
    return value


def _rss_bytes():
    # macOS reports bytes; Linux reports KiB. This is process-lifetime high
    # water, NOT resident memory attributable to a request or cache object.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _quantile(values, q):
    return sorted(values)[max(0, math.ceil(q * len(values)) - 1)]


def _services():
    sys.path.insert(0, str(ROOT / "api"))
    from services import priority_public_bundle, priority_releases
    from services.research_priority import canonical_json, digest
    from tests.test_priority_public_bundle import disclosure_for, public_release_payload

    return priority_releases, priority_public_bundle, canonical_json, digest, public_release_payload, disclosure_for


def run_benchmark(*, releases=8, iterations=5, workers=4):
    """Measure actual verified readers; fixed limits keep this rehearsal small."""
    _bounded_int(releases, 4, 16)  # release+bundle cache entries <=32
    _bounded_int(iterations, 1, 100)
    _bounded_int(workers, 1, 8)
    reader, bundles, canonical_json, digest, release_fixture, disclosure_for = _services()
    reader.clear_release_cache()
    with tempfile.TemporaryDirectory(prefix="sclib-synthetic-rps-benchmark-") as directory:
        base = Path(directory).resolve()
        release_dir = bundle_dir = base
        inventory = []
        for index in range(releases):
            release = release_fixture()
            release["id"] = f"synthetic-benchmark-{index:02d}"
            release["manifest_sha256"] = digest({key: value for key, value in release.items() if key != "manifest_sha256"})
            bundle = bundles.build_public_bundle(release, disclosure=disclosure_for(release))
            # The bundle digest is obtained from the actual offline verifier,
            # not a count-only stand-in for recomputable artifacts.
            bundle_sha = bundle["bundle_sha256"]
            release_bytes = canonical_json(release).encode("utf-8")
            bundle_bytes = canonical_json(bundle).encode("utf-8")
            (release_dir / (release["id"] + ".json")).write_bytes(release_bytes)
            (bundle_dir / (release["id"] + ".public.json")).write_bytes(bundle_bytes)
            inventory.append({"id": release["id"], "release_manifest_sha256": release["manifest_sha256"],
                "bundle_sha256": bundle_sha, "assessments": len(release["assessments"]),
                "release_bytes": len(release_bytes), "bundle_bytes": len(bundle_bytes)})

        def bundle_read(item):
            receipt = bundles.read_public_bundle(bundle_dir, item["id"], item["bundle_sha256"],
                expected_release_sha256=item["release_manifest_sha256"])
            return {"id": receipt.release_id, "bundle_sha256": receipt.bundle_sha256,
                    "bytes": len(receipt.canonical_bytes)}

        def catalog_read(item):
            release = reader.read_release_projection(release_dir, item["id"], item["release_manifest_sha256"])
            artifact = bundle_read(item)
            return {**release, "bundle_sha256": artifact["bundle_sha256"]}

        def download_read(item):
            # Like the HTTP download gate, the complete bundle reader also
            # checks the separately pinned release, not just its own file.
            reader.read_release_projection(release_dir, item["id"], item["release_manifest_sha256"])
            return bundle_read(item)

        phases = {}
        rss_before = _rss_bytes()
        tracemalloc.start()
        try:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="synthetic-rps-benchmark") as pool:
                for name, function, repeats, cold in [
                    ("catalog_cold", catalog_read, 1, True),
                    ("catalog_warm", catalog_read, iterations, False),
                    ("bundle_cold", download_read, 1, True),
                    ("bundle_warm", download_read, iterations, False),
                ]:
                    if cold:
                        reader.clear_release_cache()
                    before = reader.release_cache_stats()
                    traced_before, _ = tracemalloc.get_traced_memory()
                    tracemalloc.reset_peak()
                    times = []
                    response_hashes = set()
                    for _ in range(repeats):
                        started = time.perf_counter()
                        result = list(pool.map(function, inventory))
                        payload = canonical_json(result)
                        times.append((time.perf_counter() - started) * 1000)
                        response_hashes.add(hashlib.sha256(payload.encode("utf-8")).hexdigest())
                    traced_after, traced_peak = tracemalloc.get_traced_memory()
                    after = reader.release_cache_stats()
                    phases[name] = {
                        "rounds": repeats, "objects_per_round": releases,
                        "round_latency_ms": times, "p50_round_ms": _quantile(times, 0.5),
                        "p95_round_ms": _quantile(times, 0.95), "quantile_method": "nearest_rank",
                        "verification_count": after["verifications"] - before["verifications"],
                        "cache_hits": after["hits"] - before["hits"],
                        "cache_misses": after["misses"] - before["misses"],
                        "cached_entries": after["entries"], "cached_bytes_approximate": after["cached_bytes"],
                        "traced_current_bytes_before": traced_before, "traced_current_bytes_after": traced_after,
                        "traced_peak_bytes": traced_peak, "traced_peak_increase_bytes": max(0, traced_peak - traced_before),
                        "response_identity_count": len(response_hashes),
                    }
            limits = reader.release_cache_stats()["limits"]
        finally:
            tracemalloc.stop()
            reader.clear_release_cache()

    return {
        "version": VERSION, "status": "measured", "synthetic_only": True, "offline": True,
        "measurement_scope": "local_verified_service_threadpool_not_http_or_production",
        "scientific_acceptance": False, "production_sla_established": False,
        "budget_decision": "requires_operator_review_of_representative_workload",
        "fixture_inventory_sha256": digest(inventory), "fixture_inventory": inventory,
        "release_count": releases, "assessment_count": sum(item["assessments"] for item in inventory),
        "fixture_total_bytes": sum(item["release_bytes"] + item["bundle_bytes"] for item in inventory),
        "workers": workers, "iterations": iterations, "cache_limits": limits,
        "python_version": platform.python_version(), "platform": sys.platform,
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixture_provider_sha256": hashlib.sha256((ROOT / "api/tests/test_priority_public_bundle.py").read_bytes()).hexdigest(),
        "memory_methods": {"python_allocator": "tracemalloc", "rss": "process_lifetime_high_water_not_cache_attribution",
                           "process_peak_rss_before_bytes": rss_before, "process_peak_rss_after_bytes": _rss_bytes()},
        "phases": phases,
        "limitations": ["Synthetic release size and concurrency are not representative production demand.",
                        "Warm measurements include fresh file metadata checks and pinned identity checks.",
                        "Memory is approximate Python retention plus separately labeled process high-water RSS.",
                        "Small deterministic samples do not establish a tail-latency or scientific-utility guarantee."],
    }


def main(argv=None):
    parser = _Arguments(description=__doc__, allow_abbrev=False)
    parser.add_argument("--releases", type=int, default=8)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--workers", type=int, default=4)
    try:
        options = parser.parse_args(argv)
        report = run_benchmark(releases=options.releases, iterations=options.iterations, workers=options.workers)
    except ValueError:
        print(json.dumps({"version": VERSION, "status": "rejected", "reason_code": "invalid_arguments_or_fixture"}))
        return 2
    except Exception:
        print(json.dumps({"version": VERSION, "status": "unavailable", "reason_code": "benchmark_failed"}))
        return 2
    print(json.dumps(report, sort_keys=True, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
