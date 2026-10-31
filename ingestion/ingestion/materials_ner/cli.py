"""Explicit bounded commands for Mac mini Materials NER."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from .contract import canonical, output_schema
from .doctor import diagnose
from .gcs import capture
from .planning import acquire_batch, save_plan
from .sources import inspect_chunks, load_bundle, parse_local, private_write, save_bundle, TEXT_ENCODINGS
from .store import Store
from .worker import configuration, export_review_packet, run_one


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Private durable state directory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("doctor")
    recovery = commands.add_parser("recover-arxiv")
    recovery.add_argument("--plan", type=Path, required=True)
    recovery.add_argument("--limit", type=int, default=10)
    recovery.add_argument("--max-bytes", type=int, default=256 * 1024**2)
    recovery.add_argument("--max-wall-seconds", type=int, default=900)
    recovery.add_argument("--ssh-host")
    recovery.add_argument("--retry-failed", action="store_true")
    campaign = commands.add_parser("campaign")
    campaign.add_argument("--plan", type=Path, required=True)
    campaign.add_argument("--name", default="arxiv-luna-20261021")
    campaign.add_argument("--batch-size", type=int, default=10)
    campaign.add_argument("--max-batches", type=int, default=1)
    campaign.add_argument("--workers", type=int, default=2)
    campaign.add_argument("--max-wall-seconds", type=int, default=3600)
    campaign.add_argument("--max-input-tokens", type=int, default=90000)
    campaign.add_argument("--timeout-seconds", type=int, default=600)
    campaign.add_argument("--source-ssh-host", "--ssh-host", dest="source_ssh_host",
                          help="Read-only source transport; never a database destination")
    campaign_status = commands.add_parser("campaign-status")
    campaign_status.add_argument("--name", default="arxiv-luna-20261021")
    windows = commands.add_parser("window-campaign")
    windows.add_argument("--plan", type=Path, required=True)
    windows.add_argument("--name", required=True)
    windows.add_argument("--work-id", action="append", dest="work_ids")
    windows.add_argument("--paper-limit", type=int, default=3)
    windows.add_argument("--max-jobs", type=int, default=40)
    windows.add_argument("--workers", type=int, default=2)
    windows.add_argument("--max-wall-seconds", type=int, default=3600)
    windows.add_argument("--max-chars", type=int, default=4000)
    database = commands.add_parser("database")
    database.add_argument("--action", choices=["initialize", "status", "ingest"], default="status")
    database.add_argument("--database-ssh-host", dest="ssh_host",
                          help="Explicit remote database operator destination; omitted means local")
    database.add_argument("--job-id")
    plan = commands.add_parser("plan")
    plan.add_argument("--inventory", type=Path, required=True)
    acquire = commands.add_parser("acquire-batch")
    acquire.add_argument("--plan", type=Path, required=True)
    acquire.add_argument("--limit", type=int, default=10)
    acquire.add_argument("--max-bytes", type=int, default=256 * 1024 * 1024)
    acquire.add_argument("--ssh-host")
    acquire.add_argument("--work-id", action="append", dest="work_ids")
    acquire.add_argument("--processing-allowed", action="store_true")
    acquire.add_argument("--retry-failed", action="store_true")
    acquire.add_argument("--text-encoding", choices=TEXT_ENCODINGS, default="utf-8")
    schema = commands.add_parser("schema")
    schema.add_argument("--out", type=Path, required=True)
    fetch = commands.add_parser("fetch-gcs")
    fetch.add_argument("--object", required=True)
    fetch.add_argument("--bucket", default="sclib-jzis")
    fetch.add_argument("--ssh-host")
    fetch.add_argument("--generation")
    parse = commands.add_parser("bundle")
    parse.add_argument("--source", type=Path, required=True)
    parse.add_argument("--work-id", required=True)
    parse.add_argument("--title", required=True)
    parse.add_argument("--source-uri", required=True)
    parse.add_argument("--publication-version")
    parse.add_argument("--family")
    parse.add_argument("--text-encoding", choices=TEXT_ENCODINGS, default="utf-8")
    parse.add_argument("--processing-allowed", action="store_true",
                       help="Record the operator's source-processing authorization")
    inspect = commands.add_parser("inspect-chunks")
    inspect.add_argument("--input", type=Path, required=True)
    audit = commands.add_parser("audit-source", help="Inspect original-file structure without changing source or queue state")
    audit.add_argument("--source", type=Path, required=True)
    audit.add_argument("--work-id", required=True)
    audit.add_argument("--bundle", type=Path)
    audit.add_argument("--out", type=Path, required=True)
    identity = commands.add_parser("prepare-identity-context", help="Attach exact original title/abstract context before fresh inventory generation")
    identity.add_argument("--parent-bundle", type=Path, required=True)
    identity.add_argument("--window-bundle", type=Path, required=True)
    identity.add_argument("--max-context-chars", type=int, default=12000)
    identity.add_argument("--out", type=Path, required=True)
    enqueue = commands.add_parser("enqueue")
    enqueue.add_argument("--bundle", type=Path, required=True)
    enqueue.add_argument("--provider", choices=["codex", "responses"], default="codex")
    enqueue.add_argument("--model", choices=["gpt-6.1-sol", "gpt-6-luna"], default="gpt-6-luna")
    enqueue.add_argument("--reasoning", choices=["low", "medium", "high", "xhigh", "max"], default="medium")
    enqueue.add_argument("--timeout-seconds", type=int, default=900)
    enqueue.add_argument("--max-input-tokens", type=int, default=60000)
    enqueue.add_argument("--workflow",choices=["single_pass_v1","inventory_v2","inventory_v3","inventory_v4","inventory_v5","inventory_v6","inventory_v7","inventory_v8","inventory_v9","inventory_v10","inventory_v11","inventory_v12"],default="single_pass_v1")
    enqueue.add_argument("--max-output-tokens", type=int, default=16000,
                         help="Responses API limit; Codex CLI has no equivalent enforced limit")
    frozen = commands.add_parser('freeze-inventory', help='Retain a standalone inventory call as a source-bound staged input')
    frozen.add_argument('--bundle', type=Path, required=True)
    frozen.add_argument('--source-receipt', type=Path, required=True)
    frozen.add_argument('--source-occurrences', type=Path,
        help='Required for legacy first reads; typed handoffs generate their own source obligations.')
    frozen.add_argument('--out', type=Path, required=True)
    staged = commands.add_parser("stage-enqueue", help="Extract fixed source items from a verified packet or frozen inventory snapshot")
    compiled=commands.add_parser('compiled-enqueue',help='Compile source-selected field candidates from an explicit source-bound request')
    compiled.add_argument('--bundle',type=Path,required=True)
    compiled.add_argument('--request',type=Path,required=True)
    compiled.add_argument('--model',choices=['gpt-6-luna','gpt-6.1-sol'],default='gpt-6-luna')
    compiled.add_argument('--reasoning',choices=['low','medium','high','xhigh','max'],default='medium')
    compiled.add_argument('--timeout-seconds',type=int,default=600)
    compiled.add_argument('--max-input-tokens',type=int,default=60000)
    compiled.add_argument('--max-output-tokens',type=int,default=16000)
    staged.add_argument("--parent-packet", type=Path, required=True)
    staged.add_argument("--workflow", choices=["source_item_stages_v1", "source_item_stages_v2", "source_item_stages_v3", "source_item_stages_v4", "source_item_stages_v5"], default="source_item_stages_v1")
    staged.add_argument("--group-size", type=int, default=4)
    staged.add_argument("--field-generation-policy", choices=["source_fields_v1", "source_fields_v2", "source_fields_v3", "source_fields_v4", "source_fields_v5", "target_context_v1", "source_atoms_v1", "row_fields_v1", "row_fields_v2", "row_fields_v3", "row_fields_v4", "row_fields_v5", "row_fields_v6"], default=None)
    staged.add_argument("--source-atom-context", type=Path, help="Frozen source/table input JSON for source_atoms_v1")
    staged.add_argument("--catalog-scope", type=Path, help="Frozen requested cells, item IDs and source support spans for row_fields_v1 through row_fields_v6")
    staged.add_argument("--max-source-items", type=int, default=64)
    staged.add_argument("--item-owner-policy", choices=["source_item_owners_v1", "source_item_owners_context_v2", "source_item_owners_references_v3", "source_item_owners_identity_v4"], default=None)
    staged.add_argument("--model", choices=["gpt-6-luna", "gpt-6.1-sol"], default="gpt-6-luna")
    staged.add_argument("--reasoning", choices=["low", "medium", "high", "xhigh", "max"], default="medium")
    staged.add_argument("--timeout-seconds", type=int, default=900)
    staged.add_argument("--max-input-tokens", type=int, default=60000)
    staged.add_argument("--max-output-tokens", type=int, default=16000)
    run = commands.add_parser("run")
    run.add_argument("--max-jobs", type=int, default=1)
    run.add_argument("--max-wall-seconds", type=int, default=3600)
    run.add_argument("--job-id")
    export = commands.add_parser("export-review")
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--plan", type=Path)
    args = parser.parse_args(argv)
    if args.command == "prepare-identity-context":
        from .identity_context import build_index, attach_identity, verify_attachment
        from .contract import digest
        if args.out.exists():
            raise ValueError("identity context output already exists")
        parent, window = load_bundle(args.parent_bundle), load_bundle(args.window_bundle)
        index = build_index(parent)
        enriched, proof = attach_identity(parent, window, index, max_context_chars=args.max_context_chars)
        assert verify_attachment(parent, window, enriched, index, max_context_chars=args.max_context_chars) == proof
        key, path = save_bundle(args.root, enriched)
        report = dict(schema="materials-identity-context-preparation/1", index=index, proof=proof,
                      bundle_path=str(path), bundle_sha256=key, fresh_inventory_required=True,
                      scientific_acceptance=False)
        private_write(args.out, canonical(report).encode())
        print(canonical(dict(report_path=str(args.out), report_sha256=digest(report),
                             bundle_path=str(path), bundle_sha256=key, scientific_acceptance=False)))
        return 0
    if args.command == "audit-source":
        from .source_audit import audit_source
        from .contract import digest
        report = audit_source(args.source, work_id=args.work_id,
                              bundle=load_bundle(args.bundle) if args.bundle else None)
        if args.out.exists():
            raise ValueError("source audit output already exists")
        private_write(args.out, canonical(report).encode())
        print(canonical({"audit_path": str(args.out), "audit_sha256": digest(report),
                         "source_sha256": report['source_sha256'], "scientific_acceptance": False}))
        return 0
    store = Store(args.root)
    exit_code = 0
    if args.command == 'freeze-inventory':
        from .frozen_inventory import from_files, verify
        if args.out.exists():
            raise ValueError('frozen inventory destination already exists')
        snapshot = from_files(load_bundle(args.bundle), args.source_receipt, args.source_occurrences)
        verify(snapshot)
        private_write(args.out, canonical(snapshot).encode())
        result = dict(snapshot=str(args.out), run_id=snapshot['run_id'], new_model_calls=0,
            inventory_items=len(snapshot['inventory']['items']), source_cells=snapshot['source_accounting']['source_cells'],
            scientific_acceptance=False)
    elif args.command == "stage-enqueue":
        from .item_worker import enqueue as enqueue_staged
        parent = json.loads(args.parent_packet.read_text())
        job_id = enqueue_staged(store, parent, group_size=args.group_size, max_source_items=args.max_source_items, workflow=args.workflow,
            item_owner_policy=args.item_owner_policy, field_generation_policy=args.field_generation_policy,
            source_atom_context=json.loads(args.source_atom_context.read_text()) if args.source_atom_context else None,
            catalog_scope=json.loads(args.catalog_scope.read_text()) if args.catalog_scope else None,
            model=args.model, reasoning=args.reasoning, timeout_seconds=args.timeout_seconds,
            max_input_tokens=args.max_input_tokens, max_output_tokens=args.max_output_tokens)
        result = {"job_id": job_id, "workflow": args.workflow, "state": "queued"}
    elif args.command == "status":
        result = store.summary()
    elif args.command == "doctor":
        result = diagnose(store.root)
    elif args.command == "recover-arxiv":
        from .recovery import recover_batch
        result = recover_batch(store.root, args.plan, limit=args.limit, max_bytes=args.max_bytes,
                               max_seconds=args.max_wall_seconds, ssh_host=args.ssh_host,
                               retry_failed=args.retry_failed)
    elif args.command == "campaign":
        from .campaign import run_campaign
        result = run_campaign(store.root, args.plan, name=args.name, batch_size=args.batch_size,
                              max_batches=args.max_batches, workers=args.workers,
                              max_wall_seconds=args.max_wall_seconds, source_ssh_host=args.source_ssh_host,
                              max_input_tokens=args.max_input_tokens, timeout_seconds=args.timeout_seconds,
                              progress=lambda value: print(value, flush=True))
    elif args.command == "campaign-status":
        from .campaign import campaign_status as status
        result = status(store.root, args.name)
    elif args.command == "window-campaign":
        from .window_campaign import run_window_campaign
        result = run_window_campaign(store.root, args.plan, name=args.name, work_ids=args.work_ids,
                                     paper_limit=args.paper_limit, max_jobs=args.max_jobs,
                                     workers=args.workers, max_wall_seconds=args.max_wall_seconds,
                                     max_chars=args.max_chars,
                                     progress=lambda value: print(value, flush=True))
    elif args.command == "database":
        from .database import bridge, ingest_job
        from .proposals import ProposalDatabase
        if args.action == "ingest":
            if not args.job_id:
                parser.error("--job-id is required for ingestion")
            result = ingest_job(store, args.job_id, database_ssh_host=args.ssh_host)
        elif args.ssh_host:
            result = bridge(args.ssh_host, {"action": args.action})
        else:
            result = ProposalDatabase(store.root).summary()
    elif args.command == "plan":
        identifier, path = save_plan(store.root, args.inventory)
        result = {"plan_sha256": identifier, "path": str(path),
                  "summary": json.loads(path.read_bytes())["summary"]}
    elif args.command == "acquire-batch":
        result = acquire_batch(store.root, args.plan, limit=args.limit, max_bytes=args.max_bytes,
                               ssh_host=args.ssh_host, work_ids=args.work_ids,
                               processing_allowed=args.processing_allowed,
                               retry_failed=args.retry_failed, text_encoding=args.text_encoding)
        exit_code = int(any(item["state"] != "bundled" for item in result["outcomes"]))
    elif args.command == "schema":
        private_write(args.out, (json.dumps(output_schema(), indent=2) + "\n").encode())
        result = {"schema_path": str(args.out)}
    elif args.command == "fetch-gcs":
        result = capture(store.root, args.object, bucket=args.bucket, ssh_host=args.ssh_host,
                         generation=args.generation)
    elif args.command == "bundle":
        bundle = parse_local(args.source, work_id=args.work_id, title=args.title,
                             source_uri=args.source_uri, publication_version=args.publication_version,
                             family=args.family, text_encoding=args.text_encoding,
                             processing_permission="allowed" if args.processing_allowed else "unresolved")
        identifier, path = save_bundle(store.root, bundle)
        result = {"bundle_sha256": identifier, "path": str(path), "blocks": len(bundle.blocks),
                  "characters": sum(len(b.text) for b in bundle.blocks),
                  "source_version_verified": False, "scientific_acceptance": False}
    elif args.command == "inspect-chunks":
        result = inspect_chunks(json.loads(args.input.read_text()))
    elif args.command == 'compiled-enqueue':
        from .compiled_field_worker import enqueue as enqueue_compiled
        result={'job_id':enqueue_compiled(store,load_bundle(args.bundle),json.loads(args.request.read_bytes()),
            **{k:getattr(args,k) for k in ['model','reasoning','timeout_seconds','max_input_tokens','max_output_tokens']}),
            'review_only':True,'scientific_acceptance':False}
    elif args.command == "enqueue":
        bundle = load_bundle(args.bundle)
        identifier, _ = save_bundle(store.root, bundle)
        config = configuration(**{key: getattr(args, key) for key in
                                  ("provider", "model", "reasoning", "timeout_seconds",
                                   "max_input_tokens", "max_output_tokens","workflow")})
        result = {"job_id": store.enqueue(work_id=bundle.work_id, bundle_hash=identifier, config=config)}
    elif args.command == "run":
        if not 1 <= args.max_jobs <= 100 or not 1 <= args.max_wall_seconds <= 86400:
            parser.error("use an explicit bounded run: 1..100 jobs, 1..86400 seconds")
        started, completed = time.monotonic(), 0
        while completed < args.max_jobs and time.monotonic() - started < args.max_wall_seconds:
            remaining = args.max_wall_seconds - (time.monotonic() - started)
            result = run_one(store, job_id=args.job_id, max_seconds=remaining)
            if result is None:
                break
            print(canonical(result), flush=True)
            if result["state"] not in {"succeeded", "success_empty"}:
                exit_code = 1
            completed += 1
            if args.job_id:
                break
        result = store.summary()
    else:
        result = export_review_packet(store, args.out, args.plan)
    print(canonical(result), flush=True)
    return exit_code
