"""Freeze the paper denominator and acquire bounded, resumable original-source batches."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re
import time

from .contract import canonical, digest
from .gcs import capture
from .sources import load_bundle, parse_local, private_write, save_bundle


def arxiv_key(value: str) -> str:
    value = value.removeprefix("arxiv:")
    return re.sub(r"v\d+$", "", value).replace("/", "_")


def compile_plan(inventory: dict) -> dict:
    if inventory.get("schema") != "materials-ner-source-inventory/1":
        raise ValueError("unsupported inventory")
    papers = inventory.get("paper_plan")
    gcs = inventory.get("gcs", {})
    if not papers or not gcs.get("listing_complete") or inventory.get("errors"):
        raise ValueError("complete paper and GCS inventories are required")
    if len({paper["id"] for paper in papers}) != len(papers):
        raise ValueError("duplicate paper IDs")
    objects = defaultdict(list)
    unmapped_objects = []
    for item in gcs.get("objects", []):
        match = re.fullmatch(r"(src|pdf)/\d{4}/(.+?)(?:\.tar\.gz|\.pdf)", item["name"])
        if not match or not item.get("generation") or not item.get("size"):
            unmapped_objects.append(item["name"])
            continue
        objects[arxiv_key(match[2])].append({
            **item, "generation": str(item["generation"]), "bucket": gcs["bucket"],
            "source_kind": "archive" if match[1] == "src" else "pdf",
        })
    by_id = {paper["id"]: paper for paper in papers}
    arxiv_by_doi = defaultdict(set)
    for paper in papers:
        if paper["source"] == "arxiv" and paper.get("doi"):
            arxiv_by_doi[paper["doi"].lower()].add(paper["id"])
    rows, referenced_objects = [], set()
    for paper in papers:
        row = {key: paper.get(key) for key in
               ("id", "source", "title", "arxiv_id", "doi", "material_family",
                "status", "old_ner_records", "chunk_count")}
        row.update(candidates=[], alternate_work_ids=[], publication_version_verified=False)
        if paper["source"] == "arxiv":
            candidates = objects.get(arxiv_key(paper.get("arxiv_id") or paper["id"]), [])
            row["candidates"] = sorted(candidates, key=lambda obj: (
                obj["source_kind"] != "archive", obj["name"], obj["generation"]))
            referenced_objects.update(obj["name"] for obj in candidates)
            row["acquisition_status"] = "available_in_gcs" if candidates else "missing_archive"
        elif paper["source"] == "aps":
            alternatives = set(arxiv_by_doi.get((paper.get("doi") or "").lower(), set()))
            related = by_id.get(paper.get("related_paper_id"), {})
            if related.get("source") == "arxiv":
                alternatives.add(related["id"])
            row["alternate_work_ids"] = sorted(alternatives)
            row["acquisition_status"] = "aps_authorization_pending"
        else:
            row["acquisition_status"] = "unsupported_source"
        rows.append(row)
    counts = Counter(row["acquisition_status"] for row in rows)
    arxiv = [row for row in rows if row["source"] == "arxiv"]
    aps = [row for row in rows if row["source"] == "aps"]
    available_ids = {row["id"] for row in arxiv if row["candidates"]}
    return {
        "schema": "materials-ner-source-plan/1",
        "inventory_sha256": digest(inventory), "inventory_captured_at": inventory.get("captured_at"),
        "gcs_listing_complete": True, "harvest_allowed": False, "papers": rows,
        "summary": {
            "papers": len(rows), "acquisition_states": dict(sorted(counts.items())),
            "gcs_objects": len(gcs.get("objects", [])),
            "arxiv_with_source_archive": sum(any(c["source_kind"] == "archive" for c in r["candidates"]) for r in arxiv),
            "arxiv_with_pdf": sum(any(c["source_kind"] == "pdf" for c in r["candidates"]) for r in arxiv),
            "arxiv_with_both": sum({c["source_kind"] for c in r["candidates"]} == {"archive", "pdf"} for r in arxiv),
            "aps_with_arxiv_candidate": sum(bool(row["alternate_work_ids"]) for row in aps),
            "aps_with_gcs_arxiv_candidate": sum(bool(set(row["alternate_work_ids"]) & available_ids) for row in aps),
            "unmatched_objects": len(gcs.get("objects", [])) - len(referenced_objects),
        },
        "unmapped_object_names": unmapped_objects,
        "scientific_acceptance": False, "ml_training_eligible": False,
        "limitations": [
            "An arXiv/APS match is a version-reconciliation candidate, not interchangeable full text.",
            "The corpus is an inventory denominator, not a list of superconducting ground-truth samples.",
            "GCS object generation and checksums do not identify the publication version.",
            "Currentness, supplementary material and table/figure coverage require separate review.",
        ],
    }


def save_plan(root: Path, inventory_path: Path) -> tuple[str, Path]:
    plan = compile_plan(json.loads(inventory_path.read_bytes()))
    identifier = digest(plan)
    path = root / "plans" / f"{identifier}.json"
    raw = canonical(plan).encode()
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("immutable source plan collision")
    if not path.exists():
        private_write(path, raw)
    return identifier, path


def load_plan(path: Path):
    plan = json.loads(path.read_bytes())
    if plan.get("schema") != "materials-ner-source-plan/1":
        raise ValueError("unsupported source plan")
    return plan, digest(plan)


def diverse_order(rows: list[dict]) -> list[dict]:
    """Reproducible round robin by existing family; these are sampling strata, not labels."""
    groups = defaultdict(list)
    for row in rows:
        groups[row.get("material_family") or "unclassified"].append(row)
    for rows_in_group in groups.values():
        rows_in_group.sort(key=lambda row: digest(row["id"]))
    ordered = []
    for index in range(max((len(group) for group in groups.values()), default=0)):
        for family in sorted(groups):
            if index < len(groups[family]):
                ordered.append(groups[family][index])
    return ordered


def acquire_batch(root: Path, plan_path: Path, *, limit=10, max_bytes=256 * 1024 * 1024,
                  ssh_host=None, processing_allowed=False, work_ids=None, retry_failed=False,
                  text_encoding="utf-8", capture_fn=capture) -> dict:
    if not 1 <= limit <= 100 or not 1 <= max_bytes <= 2 * 1024**3:
        raise ValueError("invalid batch bound")
    if not processing_allowed:
        raise ValueError("source-processing authorization must be recorded")
    plan, identifier = load_plan(plan_path)
    by_id = {row["id"]: row for row in plan["papers"]}
    selected = set(work_ids or [])
    if selected - by_id.keys():
        raise ValueError("work ID absent from the frozen source plan")
    if selected and any(by_id[key]["acquisition_status"] != "available_in_gcs" for key in selected):
        raise ValueError("requested work lacks a GCS source; APS cannot silently use an arXiv substitute")
    ordered = diverse_order([row for row in plan["papers"] if
                             row["acquisition_status"] == "available_in_gcs"
                             and (not selected or row["id"] in selected)])
    batch_root = root / "acquisitions" / identifier
    batch_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    outcomes, reserved_bytes = [], 0
    with (batch_root / ".lock").open("a") as lock:
        # A second acquisition process fails explicitly instead of duplicating transfers.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for paper in ordered:
            receipt_path = batch_root / f'{digest(paper["id"])}.json'
            if receipt_path.exists():
                previous = json.loads(receipt_path.read_bytes())
                if previous["state"] == "bundled":
                    bundle = load_bundle(root / "bundles" / f'{previous["bundle_sha256"]}.json')
                    if digest(bundle.model_dump()) != previous["bundle_sha256"]:
                        raise ValueError("cached bundle integrity failure")
                    continue
                if not retry_failed:
                    continue
            if len(outcomes) >= limit:
                break
            attempt = {
                "schema": "materials-source-acquisition/1", "plan_sha256": identifier,
                "work_id": paper["id"], "started_at": datetime.now(timezone.utc).isoformat(),
                "state": "failed", "candidate_attempts": [], "scientific_acceptance": False,
                "text_encoding": text_encoding,
            }
            started = time.monotonic()
            exhausted_budget = False
            for candidate in paper["candidates"]:
                # Reserve every attempted source, even failed transfers, in the batch byte budget.
                if reserved_bytes + candidate["size"] > max_bytes:
                    exhausted_budget = True
                    break
                reserved_bytes += candidate["size"]
                event = {"object": candidate["name"], "generation": candidate["generation"],
                         "declared_bytes": candidate["size"]}
                try:
                    captured = capture_fn(root, candidate["name"], bucket=candidate["bucket"],
                                          generation=candidate["generation"], ssh_host=ssh_host)
                    bundle = parse_local(
                        Path(captured["local_path"]), work_id=paper["id"], title=paper["title"],
                        source_uri=captured["source_uri"], family=paper.get("material_family"),
                        processing_permission="allowed", text_encoding=text_encoding,
                    )
                    bundle_hash, _ = save_bundle(root, bundle)
                    attempt.update(state="bundled", bundle_sha256=bundle_hash,
                                   source_sha256=captured["sha256"], blocks=len(bundle.blocks),
                                   characters=sum(len(block.text) for block in bundle.blocks))
                    event["state"] = "bundled"
                except Exception as error:
                    # Keep source-specific failures; do not leak authentication/provider error text.
                    event.update(state="failed", error_class=type(error).__name__)
                attempt["candidate_attempts"].append(event)
                if attempt["state"] == "bundled":
                    break
            if exhausted_budget and not attempt["candidate_attempts"]:
                break  # No work was attempted; leave it eligible for the next batch.
            attempt["elapsed_seconds"] = time.monotonic() - started
            # Retain each acquisition attempt, including failed decoding and subsequent repair.
            attempt_hash = digest(attempt)
            private_write(batch_root / "attempts" / f"{attempt_hash}.json", canonical(attempt).encode())
            if receipt_path.exists():
                previous_raw = receipt_path.read_bytes()
                private_write(batch_root / "attempts" / f"{digest(json.loads(previous_raw))}.json", previous_raw)
            private_write(receipt_path, canonical(attempt).encode())
            outcomes.append(attempt)
            if exhausted_budget:
                break
    return {
        "plan_sha256": identifier, "attempted_papers": len(outcomes),
        "reserved_download_bytes": reserved_bytes, "outcomes": outcomes,
        "source_plan_denominator": len(plan["papers"]), "scientific_acceptance": False,
    }
