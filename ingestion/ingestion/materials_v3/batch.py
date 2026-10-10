"""Bounded batch execution with one shared provider and per-paper durable receipts."""

from __future__ import annotations

from .blocks import verify_document
from .contract import digest
from .manifest import source_captures, validate_manifest
from .pipeline import Pipeline
from .statistics import run_statistics


def batch_selection(manifest, split):
    if split not in {"development", "validation", "blind_test", "all"}:
        raise ValueError("unknown_batch_split")
    if split in {"blind_test", "all"}:
        body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        if (
            manifest.get("status") != "frozen"
            or manifest.get("manifest_sha256") != digest(body)
            or validate_manifest(manifest, freeze=True)
        ):
            raise ValueError("blind_or_final_batch_requires_frozen_manifest")
    selected = [p for p in manifest["papers"] if split == "all" or p["split"] == split]
    if not selected or len(selected) > 50:
        raise ValueError("batch_work_count_outside_pilot_budget")
    return selected


def run_batch(
    manifest,
    provider,
    ledger,
    *,
    split,
    load_document,
    publish,
    budget=None,
    progress=lambda row: None,
):
    selected = batch_selection(manifest, split)
    captures_by_work = {p["work_id"]: source_captures(p) for p in selected}
    if provider.config.provider != "local_mlx" and any(
        c.get("cloud_inference_allowed") is not True or c.get("transfer_allowed") is not True
        for captures in captures_by_work.values()
        for c in captures
    ):
        raise ValueError("batch_cloud_source_permissions_incomplete")
    pipeline, outputs = Pipeline(provider, ledger, budget=budget), []
    resource_failed = False
    for paper in selected:
        source_outputs, consumed_attempts, consumed_seconds = [], 0, 0.0
        captures = captures_by_work[paper["work_id"]]
        for capture in captures:
            document = load_document(capture)
            verify_document(document)
            if (
                document["source_sha256"] != capture["source_sha256"]
                or document["manifest_sha256"] != capture["content_manifest_sha256"]
            ):
                raise ValueError("batch_source_hash_mismatch")
            run = pipeline.run(
                document,
                paper_id=paper["paper_id"],
                work_id=paper["work_id"],
                cloud_transfer_allowed=capture.get("cloud_inference_allowed") is True
                and capture.get("transfer_allowed") is True,
                prior_scope_attempts=consumed_attempts,
                prior_scope_seconds=consumed_seconds,
            )
            statistics = run_statistics(run)
            consumed_attempts += statistics["attempts"]
            consumed_seconds += statistics["provider_call_seconds"]
            receipt = publish(capture, run)
            source_outputs.append(
                {
                    "capture_kind": capture["capture_kind"],
                    "source_sha256": run["source_sha256"],
                    "content_manifest_sha256": run["input_sha256"],
                    "job_key": run["job_key"],
                    "coverage": run["coverage"],
                    "output_receipt": receipt,
                }
            )
            progress(
                {
                    "paper_id": paper["paper_id"],
                    "capture_kind": capture["capture_kind"],
                    "job_key": run["job_key"],
                    "status": "completed" if run["coverage"]["machine_text_complete"] else "failed",
                }
            )
            if "resource_exhausted" in run["terminal"].values():
                resource_failed = True
                break
        complete = len(source_outputs) == len(captures)
        scope_confirmed = paper.get("supplement_status") in {"included", "confirmed_absent"}
        outputs.append(
            {
                "paper_id": paper["paper_id"],
                "work_id": paper["work_id"],
                "sources": source_outputs,
                "source_scope_confirmed": scope_confirmed,
                "coverage": {
                    "machine_text_complete": complete
                    and all(r["coverage"]["machine_text_complete"] for r in source_outputs),
                    "end_to_end_complete": complete
                    and scope_confirmed
                    and all(r["coverage"]["end_to_end_complete"] for r in source_outputs),
                },
                "not_started_captures": [
                    c["content_manifest_sha256"] for c in captures[len(source_outputs) :]
                ],
            }
        )
        if resource_failed:
            break
    body = {
        "version": "materials-ner-batch/1",
        "manifest_sha256": manifest["manifest_sha256"],
        "split": split,
        "outputs": outputs,
        "not_started_works": [p["work_id"] for p in selected[len(outputs) :]],
        "machine_text_complete": len(outputs) == len(selected)
        and all(r["coverage"]["machine_text_complete"] for r in outputs),
        "end_to_end_complete": len(outputs) == len(selected)
        and all(r["coverage"]["end_to_end_complete"] for r in outputs),
        "scientific_acceptance": False,
    }
    return {**body, "receipt_sha256": digest(body)}
