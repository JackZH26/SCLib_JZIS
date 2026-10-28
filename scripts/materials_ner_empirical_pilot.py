#!/usr/bin/env python3
"""Reproducible, private arXiv challenge pilot. Never writes canonical data.

prepare captures sources and locks selected page windows BEFORE inference.
run uses the existing Luna worker; all attempts, including failures, survive.
export writes observation JSONL plus descriptive engineering metrics.
This deliberately scoped pilot is neither a full-paper NER campaign nor Gold.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
from ingestion.materials_ner.contract import parse_extraction, canonical, digest
from ingestion.materials_ner.proposals import review_rows
from ingestion.materials_ner.sources import (
    Bundle, Document, load_bundle, make_blocks, parse_local, private_write, save_bundle, sha,
)
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.windows import make_windows
from ingestion.materials_ner.document_context import discover_inventory, attach_context
from ingestion.materials_ner.worker import configuration, run_one

PAPERS = [
    ("2301.01120", "v1", "development", [6, 7]),
    ("2504.00662", "v1", "development", "html_all"),
    ("2508.05010", "v1", "development", [6, 7, 10, 14]),
    ("2509.22278", "v1", "development", [2, 3, 4]),
    ("2604.07807", "v1", "development", [2, 3, 4]),
    ("2012.05654", "v1", "fresh_local_challenge", [2, 3, 8, 9]),
    ("2401.13485", "v1", "fresh_local_challenge", [2, 3, 4]),
    ("2410.02104", "v2", "fresh_local_challenge", [2, 3, 4, 5]),
]


class ArxivArticleText(HTMLParser):
    """Small auditable HTML projection; original bytes remain authoritative."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.article = False
        self.skip = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "article":
            self.article = True
        if not self.article or self.skip:
            return
        values = dict(attrs)
        if tag == "math" and values.get("alttext"):
            self.parts.append(values["alttext"])
            self.skip = "math"
        elif tag in {"script", "style"}:
            self.skip = tag
        elif tag in {"p", "div", "tr", "section", "figcaption", "h1", "h2", "h3", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == self.skip:
            self.skip = None
        if tag == "article":
            self.article = False
        if self.article and not self.skip and tag in {"p", "div", "tr", "section", "figcaption"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.article and not self.skip:
            self.parts.append(data)


def write_json(path, obj):
    private_write(path, (json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode())


def prepare(root: Path, previous: Path):
    import httpx
    if (root / "plan.json").exists():
        raise ValueError("immutable plan already exists; use another pilot root")
    receipts = []
    for name in ("capture_manifest.json", "supplemental_capture_manifest.json"):
        receipts.extend(json.loads((previous / name).read_bytes())["receipts"])
    papers = []
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for aid, version, split, pages in PAPERS:
            kind = "html" if pages == "html_all" else "pdf"
            url = f"https://arxiv.org/{kind}/{aid}{version}"
            prior = next((r for r in receipts if r["url"] == url), None)
            if prior:
                raw = (previous / prior["path"]).read_bytes()
                if sha(raw) != prior["sha256"]:
                    raise ValueError("prior source capture integrity failure")
                receipt = dict(prior, inherited_from=str(previous))
            else:
                response = client.get(url)
                response.raise_for_status()
                raw = response.content
                receipt = {"url": url, "resolved_url": str(response.url),
                           "sha256": sha(raw), "status": response.status_code,
                           "captured_at": datetime.now(timezone.utc).isoformat(),
                           "content_type": response.headers.get("content-type")}
            source = root / "sources" / f"{aid}{version}.{kind}"
            private_write(source, raw)
            receipt["local_path"] = str(source)
            if kind == "pdf":
                if not raw.startswith(b"%PDF"):
                    raise ValueError("PDF request did not return a PDF")
                bundle = parse_local(source, work_id=f"arxiv:{aid}", title=f"arXiv {aid}{version}",
                                     source_uri=url, publication_version=version,
                                     processing_permission="allowed")
            else:
                parser = ArxivArticleText()
                parser.feed(raw.decode("utf-8"))
                text = "".join(parser.parts)
                if not text.strip():
                    raise ValueError("arXiv HTML article unavailable")
                docid = "doc:" + sha(raw)[:20]
                document = Document(id=docid, source_uri=url, source_sha256=sha(raw),
                                    source_kind="original_text", role="main", publication_version=version,
                                    version_status="verified", processing_permission="allowed",
                                    redistribution_permission="unresolved", coverage="partial",
                                    parser="pilot-arxiv-html-text/1:stdlib-math-alttext")
                bundle = Bundle(version="materials-source-bundle/1", work_id=f"arxiv:{aid}",
                                title=f"arXiv {aid}{version}", family=None, source_status="unresolved",
                                supplement_status="not_checked", documents=[document],
                                blocks=make_blocks(docid, [("html_article:0", text)]),
                                acquisition_notes=["HTML fallback: PDF text layer was empty.",
                                                   "Figures and supplementary files are not fully audited."])
            for doc in bundle.documents:
                doc.version_status = "verified" if receipt["resolved_url"] == url else "unresolved"
            bundle.acquisition_notes.append("Private source processing authorized by the user; redistribution unresolved.")
            parent_hash, _ = save_bundle(root, bundle)
            document_context = discover_inventory(bundle)
            context_hash = digest(document_context)
            write_json(root / "context-inventories" / (context_hash + ".json"), document_context)
            windows = make_windows(root, bundle, max_chars=10000, adjacent_pages=True)
            selected = []
            for row in windows["windows"]:
                window = load_bundle(root / "bundles" / (row["bundle_sha256"] + ".json"))
                target = next(b for b in window.blocks if b.locator.startswith("target:"))
                page = int(target.locator.split("pdf_page:")[1].split(":")[0]) if kind == "pdf" else None
                if kind == "pdf" and page not in pages:
                    continue
                # Add exact first-page identity context. No reference answers enter
                # the model input. Context-only text is not a result target.
                first = bundle.blocks[0]
                if first.id != row["source_block_id"]:
                    context = first.model_copy(deep=True)
                    context.id += ":pilot-context"
                    context.ordinal = len(window.blocks)
                    context.locator = "context-identity:" + first.locator
                    window.blocks.append(context)
                window, context_proof = attach_context(bundle, window, document_context)
                whash, _ = save_bundle(root, window)
                selected.append(dict(row, bundle_sha256=whash, page=page, target_locator=target.locator,
                                     document_context=context_proof))
            text_path = root / "source_text" / f"{aid}{version}.txt"
            private_write(text_path, "\n\n".join(f"=== {b.locator} ===\n{b.text}" for b in bundle.blocks).encode())
            papers.append({"work_id": bundle.work_id, "version": version, "split": split,
                           "source_capture": receipt, "parent_bundle_sha256": parent_hash,
                           "available_text_blocks": len(bundle.blocks), "selected_pages": pages,
                           "total_text_characters": sum(len(b.text) for b in bundle.blocks),
                           "document_context_inventory_sha256": context_hash,
                           "document_context_selection_count": len(document_context["selections"]),
                           "all_relevant_context_identified": False,
                           "target_characters": sum(w["end_char"] - w["start_char"] for w in selected),
                           "windows": selected, "full_paper_coverage": False})
            print(canonical({"event": "source_prepared", "work_id": bundle.work_id,
                             "selected_windows": len(selected), "available_blocks": len(bundle.blocks)}), flush=True)
    plan = {"schema": "materials-empirical-pilot/1", "created_at": datetime.now(timezone.utc).isoformat(),
            "papers": papers, "model": "gpt-6-luna", "purpose": "schema and extraction error discovery",
            "independent_gold": False, "population_accuracy_estimate": False,
            "metrics": ["attempt_state", "candidate_yield", "technical_issue_distribution",
                        "source_scoped_reference_agreement", "result_binding_errors", "missing_reference_results"],
            "source_scope": "selected original-text windows; no full-paper completeness claim",
            "scientific_acceptance": False, "ml_training_eligible": False}
    write_json(root / "plan.json", plan)


def run(root: Path, label: str, max_jobs: int, workers: int, wall: int, workflow="single_pass_v1", selection_path=None,reasoning="medium"):
    plan = json.loads((root / "plan.json").read_bytes())
    selection=json.loads(selection_path.read_bytes()) if selection_path else None
    selected=set(selection["bundle_sha256"]) if selection is not None else None
    planned={w["bundle_sha256"] for p in plan["papers"] for w in p["windows"]}
    if selected is not None and (not selected or not selected<=planned or len(selected)!=len(selection["bundle_sha256"])):
        raise ValueError("selection must name distinct frozen plan windows")
    selection_hash=digest(selection) if selection is not None else None
    store = Store(root)
    config = configuration(model="gpt-6-luna",reasoning=reasoning,max_input_tokens=60000,timeout_seconds=300,workflow=workflow)
    path = root / "runs" / label / "state.json"
    if path.exists():
        state = json.loads(path.read_bytes())
        if state["config"] != config or state["plan_sha256"] != digest(plan) or state.get("selection_sha256")!=selection_hash:
            raise ValueError("run drift; use a new label")
    else:
        jobs = []
        for paper in plan["papers"]:
            for window in paper["windows"]:
                if selected is not None and window["bundle_sha256"] not in selected:continue
                job = store.enqueue(work_id=paper["work_id"], bundle_hash=window["bundle_sha256"], config=config)
                jobs.append({"id": job, "work_id": paper["work_id"], "split": paper["split"],
                             "evaluation_role":"development_regression",
                             "bundle_sha256": window["bundle_sha256"], "target_locator": window["target_locator"]})
        state = {"schema": "materials-empirical-run/1", "plan_sha256": digest(plan),
                 "evaluation_role":"development_regression",
                 "evaluation_note":"These papers have informed iterative repairs. Original plan split labels are retained for provenance only; they are no longer held-out tests.",
                 "config": config, "jobs": jobs,"selection_sha256":selection_hash,"started_at": datetime.now(timezone.utc).isoformat(),
                 "outcomes": [], "scientific_acceptance": False, "production_writes": False}
        write_json(path, state)
        if selection is not None:write_json(path.with_name("selection.json"),selection)
    queue = {j["id"]: j for j in store.results()}
    known={r["job_id"] for r in state["outcomes"]}
    for planned_job in state["jobs"]:
        job=queue[planned_job["id"]]
        if job["id"] not in known and job.get("result_path") and job["state"] not in {"running","queued"}:
            raw=(root/job["result_path"]).read_bytes()
            if sha(raw)!=job["result_hash"]:raise ValueError("reused attempt hash mismatch")
            receipt=json.loads(raw)
            state["outcomes"].append({**{k:receipt[k] for k in ("job_id","state","error_code","usage","elapsed_seconds")},"reused_frozen_attempt":True})
    pending = [j["id"] for j in state["jobs"] if queue[j["id"]]["state"] == "queued"][:max_jobs]
    started = time.monotonic()
    for begin in range(0, len(pending), workers):
        remaining = wall - (time.monotonic() - started)
        if remaining <= 1 or (root / "STOP").exists():
            state["stop_reason"] = "budget_or_stop"
            break
        batch = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for f in as_completed([pool.submit(run_one, store, job_id=j, max_seconds=remaining)
                                   for j in pending[begin:begin + workers]]):
                result = f.result()
                if result:
                    state["outcomes"].append(result)
                    batch.append(result)
                    write_json(path, state)
                    print(canonical({"event": "pilot_window_finished", **result}), flush=True)
        if any(r["state"] in {"failed", "blocked"} for r in batch):
            state["stop_reason"] = "provider_or_worker_failure"
            break
    else:
        state["stop_reason"] = "bounded_queue_attempted"
    state["elapsed_seconds_this_run"] = time.monotonic() - started
    state["state"] = "checkpointed"
    write_json(path, state)
    export(root, label)


def export(root: Path, label: str):
    state = json.loads((root / "runs" / label / "state.json").read_bytes())
    queue = {j["id"]: j for j in Store(root).results()}
    counts, issues, kinds, reviews, usage, papers = Counter(), Counter(), Counter(), Counter(), Counter(), {}
    stages,inventory_reads,coverage_reports=Counter(),[],[]
    rows = []
    entity_graphs = []
    for planned in state["jobs"]:
        job = queue[planned["id"]]
        counts[job["state"]] += 1
        p = papers.setdefault(job["work_id"], {"split": planned["split"], "windows": 0, "candidates": 0})
        p["windows"] += 1
        if not job["result_path"]:
            continue
        raw = (root / job["result_path"]).read_bytes()
        if sha(raw) != job["result_hash"]:
            raise ValueError("receipt hash mismatch")
        receipt = json.loads(raw)
        stages.update(s["name"] for s in receipt.get("stages",[]))
        if "inventory_validation" in receipt:
            inventory_reads.append({"job_id":job["id"],"work_id":job["work_id"],
                "reads":receipt.get("inventory_reads",[{"stage":"inventory","validation":receipt["inventory_validation"]}]),
                "effective_validation":receipt["inventory_validation"]})
        if "inventory_coverage" in receipt:
            coverage_reports.append({"job_id":job["id"],"work_id":job["work_id"],**receipt["inventory_coverage"]})
        usage.update(receipt.get("usage", {}))
        validation = receipt.get("validation", {})
        issues.update(i["code"] for i in validation.get("issues", []))
        if receipt.get("error_code") and not validation:
            issues[receipt["error_code"]] += 1
        if "extraction" not in receipt:
            entity_graphs.append({"job_id":job["id"],"receipt_sha256":job["result_hash"],
                "raw_output_sha256":receipt.get("raw_output_sha256"),"error_code":receipt.get("error_code"),
                "structured_graph":None,"scientific_acceptance":False})
            continue
        extraction = parse_extraction(receipt["extraction"])
        entity_graphs.append({"job_id":job["id"],"receipt_sha256":job["result_hash"],
            "structured_graph":extraction.model_dump(),"scientific_acceptance":False})
        statuses = {r["local_id"]: r["review_status"] for r in review_rows(extraction, validation)["results"]}
        samples = {r.id: r.model_dump() for r in extraction.samples}
        states = {r.id: r.model_dump() for r in extraction.states}
        protocols = {r.id: r.model_dump() for r in extraction.protocols}
        for result in extraction.results:
            review = statuses[result.id]
            reviews[review] += 1
            kinds[result.quantity_kind] += 1
            p["candidates"] += 1
            rows.append({"row_id": job["id"] + ":" + result.id, "work_id": job["work_id"],
                         "job_id": job["id"], "bundle_sha256": job["bundle_hash"],
                         "receipt_sha256": job["result_hash"], "split": planned["split"],
                         "evaluation_role":state.get("evaluation_role","historical_role_not_reassessed"),
                         "target_locator": planned["target_locator"], "technical_review_status": review,
                         "sample": samples[result.sample_id], "state": states[result.state_id],
                         "protocol": protocols[result.protocol_id], "result": result.model_dump(),
                         "scientific_acceptance": False, "ml_training_eligible": False})
            if extraction.schema_version == "materials-ner/5":
                rows[-1]["source_schema_version"] = extraction.schema_version
                rows[-1]["context_procedures"] = [{"procedure": p.model_dump(),
                    "condition_indices": [u.condition_index for u in p.context_uses if u.state_id == result.state_id]}
                    for p in extraction.protocols if any(u.state_id == result.state_id for u in p.context_uses)]
            elif extraction.schema_version in {"materials-ner/6", "materials-ner/7"}:
                rows[-1]["source_schema_version"] = extraction.schema_version
                rows[-1]["context_procedures"] = [{"procedure": p.model_dump(),
                    "condition_ids": [u.condition_id for u in p.context_uses if u.state_id == result.state_id]}
                    for p in extraction.protocols if any(u.state_id == result.state_id for u in p.context_uses)]
                # Preserve a closed context, not merely IDs which become dangling
                # when this row is used separately from the full entity graph.
                from ingestion.materials_ner.validation_v6 import connected_samples
                connected = connected_samples(extraction, {result.sample_id})
                rows[-1]["sample_relations"] = [r.model_dump() for r in extraction.sample_relations
                    if r.from_sample_id in connected and r.to_sample_id in connected]
                rows[-1]["related_samples"] = [s.model_dump() for s in extraction.samples
                    if s.id in connected and s.id != result.sample_id]
                supports = [s for s in extraction.condition_supports if s.state_id == result.state_id]
                rows[-1]["condition_supports"] = [s.model_dump() for s in supports]
                support_ids = {s.result_id for s in supports}
                rows[-1]["condition_support_results"] = [{"result": r.model_dump(), "protocol": protocols[r.protocol_id]}
                    for r in extraction.results if r.id in support_ids]
    directory = root / "runs" / label
    private_write(directory / "observations.jsonl", "".join(canonical(r) + "\n" for r in rows).encode())
    private_write(directory / "entity_graphs.jsonl", "".join(canonical(g) + "\n" for g in entity_graphs).encode())
    report = {"planned_windows": len(state["jobs"]), "states": dict(counts), "issues": dict(issues),
              "candidate_results": len(rows), "technical_review_states": dict(reviews), "kinds": dict(kinds),
              "papers": papers, "usage": dict(usage), "independent_gold": False,
              "provider_stages":dict(stages),"provider_calls":sum(stages.values()),
              "evaluation_role":state.get("evaluation_role","historical_role_not_reassessed"),
              "scientific_acceptance": False, "ml_training_eligible": False,
              "full_paper_coverage": False, "usd_cost": None,
              "cost_reason": "Codex account usage; no reliable per-run dollar invoice available"}
    write_json(directory / "engineering_report.json", report)
    write_json(directory / "inventory_audit.json",{
        "schema":"materials-inventory-run-audit/1","run_label":label,
        "inventory_reads":inventory_reads,"extraction_coverage":coverage_reports,
        "independent_gold":False,"source_semantic_coverage_verified":False,
        "scientific_acceptance":False,"ml_training_eligible":False})
    print(canonical(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run", "export"])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--max-jobs", type=int, default=60)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--wall-seconds", type=int, default=1800)
    parser.add_argument("--workflow", choices=["single_pass_v1","inventory_v2","inventory_v3","inventory_v4","inventory_v5","inventory_v6","inventory_v7","inventory_v8","inventory_v9"],default="single_pass_v1")
    parser.add_argument("--selection",type=Path,help="Frozen subset of plan bundle hashes for a diagnostic canary")
    parser.add_argument("--reasoning",choices=["low","medium","high","xhigh","max"],default="medium")
    args = parser.parse_args()
    if not 1 <= args.workers <= 4 or not 1 <= args.max_jobs <= 100 or not 1 <= args.wall_seconds <= 7200:
        parser.error("invalid bounded pilot limits")
    if not args.label.replace("-", "").isalnum():
        parser.error("label must be alphanumeric with optional hyphens")
    if args.action == "prepare":
        if not args.previous:
            parser.error("prepare requires prior capture directory")
        prepare(args.root, args.previous)
    elif args.action == "run":
        run(args.root, args.label, args.max_jobs, args.workers, args.wall_seconds,args.workflow,args.selection,args.reasoning)
    else:
        export(args.root, args.label)


if __name__ == "__main__":
    main()
