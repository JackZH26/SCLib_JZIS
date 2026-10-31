"""Resume the frozen arXiv archive gaps, with one rate-limited connection.

Only originals are fetched. A failed/withdrawn/unparseable item remains in the
denominator; it never becomes an empty successful NER result.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
from urllib.parse import urlsplit

import httpx
from pypdf.errors import PyPdfError

from .contract import canonical, digest
from .planning import load_plan
from .sources import MAX_SOURCE_BYTES, parse_local, private_write, save_bundle, sha

ARXIV_ID = re.compile(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v[1-9]\d*)?$")


class RecoveryFailure(ValueError):
    def __init__(self, code, cooldown=0):
        super().__init__(code)
        self.code, self.cooldown = code, cooldown


def validate_url(url: str, arxiv_id: str):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc not in {"export.arxiv.org", "arxiv.org"}
            or parts.query or parts.fragment):
        raise RecoveryFailure("untrusted_arxiv_redirect")
    match = re.fullmatch(r"/(?:src|e-print|pdf)/(.+?)(?:\.pdf)?", parts.path)
    if not match or re.sub(r"v\d+$", "", match[1]) != re.sub(r"v\d+$", "", arxiv_id):
        raise RecoveryFailure("arxiv_response_identity_mismatch")
    if re.search(r"v\d+$", arxiv_id) and match[1] != arxiv_id:
        raise RecoveryFailure("arxiv_response_version_mismatch")


def fetch_original(client: httpx.Client, root: Path, arxiv_id: str, kind: str,
                   max_bytes=MAX_SOURCE_BYTES) -> tuple[bytes, dict]:
    if not ARXIV_ID.fullmatch(arxiv_id) or kind not in {"src", "pdf"}:
        raise ValueError("invalid arXiv request")
    url = f"https://export.arxiv.org/{kind}/{arxiv_id}"
    requested_url = url
    throttle = root / "arxiv-throttle.json"
    for _ in range(6):
        validate_url(url, arxiv_id)
        previous = json.loads(throttle.read_bytes()) if throttle.exists() else {}
        wait = max(0, previous.get("last_request", 0) + 3.1 - time.time())
        if previous.get("backoff_until", 0) > time.time():
            raise RecoveryFailure("arxiv_backoff_active",
                                  previous["backoff_until"] - time.time())
        if wait:
            time.sleep(wait)
        private_write(throttle, canonical({"last_request": time.time()}).encode())
        with client.stream("GET", url, follow_redirects=False) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise RecoveryFailure("arxiv_redirect_without_location")
                url = str(response.url.join(location))
                continue
            if response.status_code in {429, 503}:
                try:
                    cooldown = max(120, min(86400, int(response.headers.get("Retry-After", "300"))))
                except ValueError:
                    cooldown = 300
                private_write(throttle, canonical({
                    "last_request": time.time(), "backoff_until": time.time() + cooldown,
                }).encode())
                raise RecoveryFailure(f"arxiv_http_{response.status_code}", cooldown)
            if response.status_code != 200:
                raise RecoveryFailure(f"arxiv_http_{response.status_code}")
            if "text/html" in response.headers.get("content-type", "").lower():
                raise RecoveryFailure("arxiv_html_is_not_original")
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > max_bytes:
                    raise RecoveryFailure("arxiv_source_byte_limit")
            data = bytes(raw)
            if not data or data.lstrip()[:100].lower().startswith((b"<!doctype html", b"<html")):
                raise RecoveryFailure("arxiv_empty_or_html")
            if kind == "pdf" and not data.startswith(b"%PDF-"):
                raise RecoveryFailure("arxiv_non_pdf_response")
            version = re.search(r"(v[1-9]\d*)(?:\.pdf)?$", str(response.url))
            return data, {
                "requested_url": requested_url, "resolved_url": str(response.url),
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source_version": version[1] if version else None,
                "version_status": "explicit_version_url" if version else "unversioned_unknown",
                "kind": "pdf" if data.startswith(b"%PDF-") else "source",
                "sha256": sha(data), "byte_length": len(data),
            }
    raise RecoveryFailure("too_many_arxiv_redirects")


def archive_gcs(root: Path, raw: bytes, arxiv_id: str, kind: str, ssh_host: str) -> dict:
    script = Path(__file__).resolve().parents[3] / "scripts" / "materials_ner_gcs_archive.py"
    object_name = f"captures/arxiv/{arxiv_id.replace('/', '_')}/{kind}/sha256/{sha(raw)}"
    request = {"object": object_name, "sha256": sha(raw), "size": len(raw)}
    remote = shlex.join(["docker", "exec", "-i", "sclib-api", "python", "-c", script.read_text()])
    process = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                              ssh_host, remote], input=canonical(request).encode() + b"\n" + raw,
                             capture_output=True, timeout=180)
    if process.returncode:
        raise RecoveryFailure("gcs_archive_bridge_failed")
    receipt = json.loads(process.stdout)
    if (not receipt.get("ok") or receipt.get("sha256") != sha(raw)
            or receipt.get("name") != object_name or receipt.get("size") != len(raw)):
        raise RecoveryFailure("gcs_archive_readback_failed")
    private_write(root / "recovery-gcs" / f"{sha(raw)}.json", canonical(receipt).encode())
    return receipt


def recover_batch(root: Path, plan_path: Path, *, limit=10, max_bytes=256 * 1024**2,
                  max_seconds=900, ssh_host=None, retry_failed=False, fetch_fn=fetch_original):
    if not 1 <= limit <= 100 or not 1 <= max_bytes <= 2 * 1024**3 or not 1 <= max_seconds <= 86400:
        raise ValueError("invalid recovery budget")
    plan, plan_hash = load_plan(plan_path)
    missing = sorted((p for p in plan["papers"] if p["source"] == "arxiv"
                      and p["acquisition_status"] == "missing_archive"),
                     key=lambda p: (-(p.get("old_ner_records") or 0), digest(p["id"])))
    directory = root / "recovery" / plan_hash
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    start, transferred, outcomes, stop_reason = time.monotonic(), 0, [], None
    with (root / "arxiv-download.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with httpx.Client(timeout=httpx.Timeout(60, connect=15),
                          headers={"User-Agent": "SCLib-MaterialsNER/1.0 (research archive recovery)"}) as client:
            for paper in missing:
                if len(outcomes) >= limit or time.monotonic() - start >= max_seconds:
                    break
                receipt_path = directory / f'{digest(paper["id"])}.json'
                previous = json.loads(receipt_path.read_bytes()) if receipt_path.exists() else {}
                if previous.get("state") == "bundled" or previous and not retry_failed:
                    continue
                if transferred >= max_bytes:
                    break
                item = {"work_id": paper["id"], "plan_sha256": plan_hash, "state": "failed",
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "attempts": [], "scientific_acceptance": False}
                for kind in ("src", "pdf"):
                    remaining = min(MAX_SOURCE_BYTES, max_bytes - transferred)
                    if remaining <= 0:
                        stop_reason = "byte_budget_exhausted"
                        break
                    try:
                        raw, observed = fetch_fn(client, root, paper["arxiv_id"], kind, remaining)
                        transferred += len(raw)
                        source_path = root / "sources" / sha(raw)
                        if not source_path.exists():
                            private_write(source_path, raw)
                        elif sha(source_path.read_bytes()) != sha(raw):
                            raise RecoveryFailure("immutable_source_collision")
                        event = {"state": "captured", "source": observed}
                        item["attempts"].append(event)
                        # Local byte capture is durable even if GCS or parsing fails.
                        if ssh_host:
                            try:
                                event["gcs"] = archive_gcs(root, raw, paper["arxiv_id"], observed["kind"], ssh_host)
                            except (RecoveryFailure, subprocess.SubprocessError) as error:
                                event["gcs_error"] = type(error).__name__
                        bundle = parse_local(source_path, work_id=paper["id"], title=paper["title"],
                                             source_uri=observed["resolved_url"],
                                             publication_version=observed["source_version"],
                                             processing_permission="allowed")
                        identifier, _ = save_bundle(root, bundle)
                        item.update(state="bundled", bundle_sha256=identifier, source_sha256=sha(raw),
                                    blocks=len(bundle.blocks),
                                    characters=sum(len(block.text) for block in bundle.blocks))
                        break
                    except (ValueError, httpx.HTTPError, OSError, PyPdfError) as error:
                        item["attempts"].append({"endpoint": kind, "state": "failed",
                                                 "code": getattr(error, "code", type(error).__name__)})
                        if isinstance(error, RecoveryFailure) and error.cooldown:
                            stop_reason = error.code
                            break
                item["elapsed_batch_seconds"] = time.monotonic() - start
                private_write(directory / "attempts" / f"{digest(item)}.json", canonical(item).encode())
                private_write(receipt_path, canonical(item).encode())
                outcomes.append(item)
                if stop_reason:
                    break
    return {"plan_sha256": plan_hash, "missing_denominator": len(missing),
            "attempted": len(outcomes), "downloaded_bytes": transferred, "outcomes": outcomes,
            "stop_reason": stop_reason, "elapsed_seconds": time.monotonic() - start}
