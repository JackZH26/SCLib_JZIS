"""Bounded, credential-free GET acceptance and latency capture for the public site.

No cache purge, provider query, database access, scientific approval or mutation.
The exclusive output file preserves failures as well as successful measurements.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import re
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.jzis.org/sclib/v1"
SITE = "https://jzis.org"
CATALOGUE = "source-computed-candidates-2026-10-07"
EVIDENCE = "2026-10-08-evidence103-v1"
SEED = "api/services/resources/material_recovery_batch_20261008_seed.json"
MAX_BYTES = 16 * 1024 * 1024
REQUESTS = {
    "default": "/materials?limit=25&offset=0",
    "formula": "/materials?q=MgB2&limit=25&offset=0",
    "observed_cuprate": "/materials?family=cuprate&tc_min=30&pressure_max=1&knowledge_origin=Observed&limit=10&offset=0",
    "source_count": "/materials?sort=total_papers&limit=25&offset=0",
}
REFUSALS = {
    "unreviewed_phase": "/materials?structure_phase=I4&limit=1",
    "missingness_is_not_negative": "/materials?ambient_sc=false&limit=1",
    "inverted_pressure_bounds": "/materials?pressure_min=5&pressure_max=1&limit=1",
    "duplicate_formula_query": "/materials?q=MgB2&q=NbN&limit=1",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decoded_body(body, encoding):
    if encoding == "gzip":
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            body = stream.read(MAX_BYTES + 1)
    elif encoding not in {None, "identity"}:
        raise ValueError("unsupported_content_encoding")
    if len(body) > MAX_BYTES:
        raise ValueError("decoded_response_size_limit")
    return body


def fetch(url, accept_encoding="identity"):
    started = time.monotonic()
    meta = {"url": url, "started_at": utc_now(), "status": None, "error": None,
            "request_accept_encoding": accept_encoding}
    body = None
    try:
        request = Request(url, headers={"User-Agent": "SCLib-public-acceptance/1.0", "Accept-Encoding": accept_encoding})
        with urlopen(request, timeout=45) as response:
            meta["status"] = response.status
            meta["headers"] = {k.lower(): v for k, v in response.headers.items()
                               if k.lower() in {"age", "x-cache", "x-materials-cache", "x-request-id", "server-timing", "x-api-version"}}
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError("response_size_limit")
            meta["wire_bytes"] = len(body)
            meta["content_encoding"] = response.headers.get("Content-Encoding")
            body = decoded_body(body, meta["content_encoding"])
            meta.update(bytes=len(body), sha256=sha(body))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, EOFError) as error:
        meta["status"] = getattr(error, "code", meta["status"])
        # Do not retain server error bodies, arbitrary exception strings or credentials.
        meta["error"] = type(error).__name__
        body = None
    meta["elapsed_seconds"] = round(time.monotonic() - started, 6)
    return meta, body


def json_request(url, accept_encoding="identity"):
    meta, body = fetch(url, accept_encoding)
    try:
        value = json.loads(body) if body is not None else None
        if not isinstance(value, dict):
            raise TypeError("object_required")
    except (ValueError, TypeError, UnicodeDecodeError):
        meta["error"] = meta["error"] or "InvalidJSON"
        value = None
    return meta, value


def percentile(values, fraction):
    """Nearest-rank empirical quantile. Small n is descriptive, not an SLO test."""
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def latency_summary(samples):
    successes = [s["elapsed_seconds"] for s in samples if s["status"] == 200 and not s["error"]]
    return {"attempts": len(samples), "successful": len(successes),
            "failures": len(samples) - len(successes),
            "median_seconds": statistics.median(successes) if successes else None,
            "p95_seconds": percentile(successes, .95),
            "quantile_method": "nearest_rank_successes_only; failures_reported_separately",
            "first_request_seconds": samples[0]["elapsed_seconds"] if samples else None,
            "cache_state": "unknown; first_request_is_not_proven_cold; repeats_are_not_proven_warm",
            "reported_application_cache_states": dict(Counter(
                s.get("headers", {}).get("x-materials-cache", "unknown") for s in samples)),
            "slo_acceptance": None}


def same_version(before, after):
    keys = ("site_version", "dataset_version", "api_version")
    return bool(before and after and all(isinstance(before.get(k), str) and before[k]
                                        and before[k] == after.get(k) for k in keys))


def check_pin(body, pin):
    return bool(body is not None and len(body) == pin["bytes"] and sha(body) == pin["sha256"])


def collect(samples=3, all_details=False, accept_encoding="identity"):
    report = {"schema_version": "sclib-public-acceptance/1.0.0", "started_at": utc_now(),
              "scientific_acceptance": False, "ml_training_approved": False,
              "requests": [], "checks": [], "latency": {}, "recovery": [],
              "catalogue_transaction_snapshot": False,
              "capture_scope": "Software/dataset versions fenced; each GET has its own serving checks, not one database transaction."}
    report["client_profile"] = {"accept_encoding": accept_encoding,
                                "connection": "urllib; individual GETs include connection/TLS/transfer/decode; not browser or server-only timing"}

    def read(url):
        meta, value = json_request(url, accept_encoding)
        report["requests"].append(meta)
        return value

    def check(name, passed):
        report["checks"].append({"name": name, "passed": bool(passed)})

    before = read(API + "/version")
    report["version_before"] = before
    stats = read(API + "/stats")
    keys = ("total_papers", "total_materials", "total_chunks")
    check("coverage_counts_present", stats and all(type(stats.get(k)) is int and stats[k] > 0 for k in keys))
    if stats:
        report["coverage"] = {k: stats.get(k) for k in (*keys, "last_ingest_at", "stats_refreshed_at", "dataset_version")}
        report["coverage"]["arxiv_papers"] = sum(stats.get("papers_by_year_arxiv", {}).values())
        report["coverage"]["aps_papers"] = sum(stats.get("papers_by_year_aps", {}).values())
        check("paper_provider_sum", report["coverage"]["arxiv_papers"] + report["coverage"]["aps_papers"] == stats.get("total_papers"))

    meta, homepage = fetch(SITE + "/", accept_encoding)
    report["requests"].append(meta)
    commits = sorted(set(re.findall(rb"github.com/JackZH26/SCLib_JZIS/commit/([a-f0-9]{7,40})", homepage or b"")))
    report["frontend_commits"] = [c.decode() for c in commits]
    check("frontend_api_version_matches", before and report["frontend_commits"] == [before["site_version"]])

    public = ROOT / "frontend/public/research-hypotheses"
    catalogue_pin = json.loads((public / (CATALOGUE + ".pins.json")).read_bytes())
    meta, body = fetch(SITE + "/research-hypotheses/" + catalogue_pin["data_file"], accept_encoding)
    report["requests"].append(meta)
    check("source_catalogue_bytes_match_checkout_pin", check_pin(body, catalogue_pin))
    catalogue = json.loads(body) if check_pin(body, catalogue_pin) else None
    report["discovery"] = {"version": catalogue.get("version") if catalogue else None,
                           "counts": catalogue.get("counts") if catalogue else None}
    manifest = read(SITE + "/research-hypotheses/" + catalogue_pin["detail_manifest_file"])
    manifest_body = json.dumps(manifest) if manifest else ""
    check("source_detail_manifest_bytes_match_checkout_pin", bool(manifest_body) and
          report["requests"][-1].get("sha256") == catalogue_pin["detail_manifest_sha256"] and
          report["requests"][-1].get("bytes") == catalogue_pin["detail_manifest_bytes"])
    evidence_pin = json.loads((public / (EVIDENCE + ".pins.json")).read_bytes())
    evidence = read(SITE + "/research-hypotheses/" + EVIDENCE + ".json")
    check("evidence_index_bytes_match_checkout_pin", report["requests"][-1].get("sha256") == evidence_pin["sha256"] and
          report["requests"][-1].get("bytes") == evidence_pin["bytes"])
    check("discovery_counts_and_identity", catalogue and manifest and evidence and
          len(catalogue["candidates"]) == len(manifest["details"]) == len(evidence["candidates"]) == 103 and
          {c["id"] for c in catalogue["candidates"]} == {c["id"] for c in evidence["candidates"]} and
          evidence["source_catalogue_sha256"] == catalogue_pin["sha256"])

    # Only local checkout pins select downloads; remote URLs cannot redirect this crawl.
    local_manifest = json.loads((public / (CATALOGUE + ".details.json")).read_bytes())
    local_evidence = json.loads((public / (EVIDENCE + ".json")).read_bytes())
    detail_pins = [{"url": "/research-hypotheses/" + p["file"], **p} for p in local_manifest["details"]]
    detail_pins += [c["detail"] for c in local_evidence["candidates"]]
    chosen = detail_pins if all_details else detail_pins[:3] + detail_pins[103:106]
    def detail(pin):
        url = urljoin(SITE, pin["url"])
        if urlsplit(url).netloc != urlsplit(SITE).netloc or not urlsplit(url).path.startswith("/research-hypotheses/"):
            raise ValueError("local_detail_url_outside_public_scope")
        meta, data = fetch(url, accept_encoding)
        return meta, {"url": pin["url"], "passed": check_pin(data, pin)}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(detail, chosen))
    report["requests"].extend(m for m, _ in results)
    report["detail_checks"] = [c for _, c in results]
    check("requested_detail_pins", all(c["passed"] for c in report["detail_checks"]))
    report["detail_scope"] = {"checked": len(chosen), "available": len(detail_pins), "complete": all_details}

    seed = json.loads((ROOT / SEED).read_bytes())
    for row in seed["rows"]:
        value = read(API + "/materials/" + quote(row["material_id"], safe="") + "/enrichment")
        recovery = value.get("source_recovery_batch", {}) if value else {}
        matched = (recovery.get("seed_id") == seed["seed_id"] and
                   recovery.get("seed_sha256") == seed["seed_sha256"] and
                   recovery.get("observations") == row["observations"] and
                   recovery.get("material_id") == row["material_id"] and
                   recovery.get("unknowns") == row["unknowns"] and
                   value.get("scientific_acceptance") is False and value.get("ml_training_approved") is False)
        report["recovery"].append({"material_id": row["material_id"], "matched": matched,
                                   "observations": len(recovery.get("observations", [])),
                                   "record_coverage_sha256": (value or {}).get("record_coverage", {}).get("coverage_sha256")})
    check("all_16_recovery_windows_match_checkout", all(r["matched"] for r in report["recovery"]))

    for name, path in REQUESTS.items():
        attempts = []
        for _ in range(samples):
            meta, value = json_request(API + path, accept_encoding)
            if value and (type(value.get("total")) is not int or not isinstance(value.get("results"), list)):
                meta["error"] = "InvalidMaterialsEnvelope"
            elif value:
                meta["total"] = value["total"]
                meta["rows"] = len(value["results"])
                meta["sort_basis"] = value.get("sort_basis")
                meta["scientific_display_policy"] = value.get("scientific_display_policy")
                if name == "formula" and (not value["results"] or any("mgb2" not in r.get("formula", "").lower() for r in value["results"])):
                    meta["error"] = "FormulaFilterNotObserved"
            attempts.append(meta)
            report["requests"].append(meta)
        report["latency"][name] = {"request_path": path, "samples": attempts, **latency_summary(attempts)}
        check("materials_request_" + name, all(m["status"] == 200 and not m["error"] for m in attempts))
    first = report["latency"]["default"]["samples"][0]
    report["public_materials"] = {k: first.get(k) for k in ("total", "sort_basis", "scientific_display_policy")}
    for name, path in REFUSALS.items():
        meta, _ = fetch(API + path, accept_encoding)
        meta["expected_status"] = 422
        report["requests"].append(meta)
        check("public_refusal_" + name, meta["status"] == 422)
    after = read(API + "/version")
    report["version_after"] = after
    check("version_stable_across_capture", same_version(before, after))
    check("stats_dataset_matches_version", stats and before and stats.get("dataset_version") == before.get("dataset_version"))
    check("all_http_requests_match_expected_status", all(
        r["status"] == r.get("expected_status", 200) and
        (not r["error"] or (r.get("expected_status") == 422 and r["error"] == "HTTPError"))
        for r in report["requests"]))
    report["finished_at"] = utc_now()
    report["operational_acceptance"] = all(c["passed"] for c in report["checks"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--all-details", action="store_true", help="Verify all 206 static source/evidence detail files (4 concurrent GETs).")
    parser.add_argument("--accept-encoding", choices=("identity", "gzip"), default="identity")
    args = parser.parse_args()
    # Reserve the destination before network activity; never replace old evidence.
    with args.output.open("x", encoding="utf-8") as handle:
        report = collect(args.samples, args.all_details, args.accept_encoding)
        json.dump(report, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"output": str(args.output), "operational_acceptance": report["operational_acceptance"],
                      "failed_checks": [c["name"] for c in report["checks"] if not c["passed"]]}))
    return 0 if report["operational_acceptance"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
