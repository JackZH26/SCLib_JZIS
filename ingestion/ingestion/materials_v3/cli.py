"""Explicit local artifacts, private ledgers, no production database writes."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .assembly import assemble_reports
from .blocks import parse_source, verify_document
from .contract import canonical
from .corpus import prepare_corpus
from .batch import batch_selection, run_batch
from .comparison import comparison_package
from .export import import_package
from .evaluation import blank_annotation, evaluate
from .ledger import Ledger
from .manifest import freeze_manifest, validate_manifest
from .pipeline import Budget, Pipeline
from .providers import HTTPProvider, MLXProvider, ProviderConfig, ResourceLimit
from .runtime import admission, hardware, heavy_lock, memory_observation, verify_model, runtime_lock
from .review import blinded_review


def write(path: Path, value):
    if path.exists() or path.is_symlink():
        raise ValueError("output_exists_use_a_new_versioned_path")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix=".ner-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(canonical(value))
            f.flush()
            os.fsync(f.fileno())
        # Atomic no-replace publication, including against concurrent writers.
        os.link(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temp)


def read(path):
    return json.loads(Path(path).read_bytes())


@contextmanager
def provider_session(args, config):
    if args.model_path:
        if not args.model_manifest:
            raise ValueError("model_manifest_required_for_mlx")
        verify_model(args.model_path, args.model_manifest, config.revision)
        with heavy_lock(args.heavy_lock):
            admission(hardware())
            import mlx.core as mx

            mx.set_memory_limit(32 * 1024**3)

            def guard():
                observed = memory_observation(mx.get_peak_memory())
                if observed["observed_peak_bytes"] > 32 * 1024**3:
                    raise ResourceLimit("local_memory_budget_exhausted")
                if hardware()["reclaimable_memory_estimate_bytes"] < 12 * 1024**3:
                    raise ResourceLimit("local_memory_headroom_exhausted")

            provider = MLXProvider(config, str(args.model_path), guard=guard)
            try:
                guard()
                yield provider
            finally:
                provider.close()
    else:
        if config.provider == "local_mlx":
            raise ValueError("local_ner_requires_verified_in_process_model_path")
        provider = HTTPProvider(config)
        try:
            yield provider
        finally:
            provider.client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("source", type=Path)
    prepare.add_argument("--source-id", required=True)
    prepare.add_argument("--format")
    prepare.add_argument("--output", type=Path, required=True)
    corpus = commands.add_parser("prepare-corpus")
    corpus.add_argument("selection", type=Path)
    corpus.add_argument("--private-root", type=Path, required=True)
    corpus.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("document", type=Path)
    run.add_argument("--paper-id", required=True)
    run.add_argument("--work-id", required=True)
    run.add_argument("--provider-config", type=Path, required=True)
    run.add_argument("--budget", type=Path)
    run.add_argument("--ledger", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument(
        "--source-rights", type=Path, help="Source-bound permission receipt for cloud transport"
    )
    run.add_argument("--model-path", type=Path)
    run.add_argument("--model-manifest", type=Path)
    run.add_argument(
        "--heavy-lock", type=Path, default=Path("/Users/Shared/SCLibCompute/heavy-job.lock")
    )
    batch = commands.add_parser("batch")
    batch.add_argument("manifest", type=Path)
    batch.add_argument(
        "--split", choices=("development", "validation", "blind_test", "all"), required=True
    )
    batch.add_argument("--provider-config", type=Path, required=True)
    batch.add_argument("--budget", type=Path)
    batch.add_argument("--ledger", type=Path, required=True)
    batch.add_argument("--output-dir", type=Path, required=True)
    batch.add_argument("--output", type=Path, required=True)
    batch.add_argument(
        "--documents-root",
        type=Path,
        help="Private content-addressed documents: <manifest-sha256>.json",
    )
    batch.add_argument("--model-path", type=Path)
    batch.add_argument("--model-manifest", type=Path)
    batch.add_argument(
        "--heavy-lock", type=Path, default=Path("/Users/Shared/SCLibCompute/heavy-job.lock")
    )
    package = commands.add_parser("export")
    package.add_argument("run", type=Path)
    package.add_argument("document", type=Path)
    package.add_argument("source_metadata", type=Path)
    package.add_argument("--output", type=Path, required=True)
    comparison = commands.add_parser("comparison-input")
    comparison.add_argument("runs", nargs="+", type=Path)
    comparison.add_argument("--manifest", type=Path, required=True)
    comparison.add_argument("--provider", choices=("local_mlx", "gemini", "openai"), required=True)
    comparison.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("manifest")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--freeze-output", type=Path)
    annotate = commands.add_parser("annotation")
    annotate.add_argument("manifest", type=Path)
    annotate.add_argument("--slot", choices=("A", "B"), required=True)
    annotate.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("evaluate")
    compare.add_argument("--models", type=Path, required=True)
    compare.add_argument("--gold", type=Path, required=True)
    compare.add_argument("--manifest", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    blind_review = commands.add_parser("review-package")
    blind_review.add_argument("--models", type=Path, required=True)
    blind_review.add_argument("--output", type=Path, required=True)
    blind_review.add_argument("--private-mapping-output", type=Path, required=True)
    project = commands.add_parser("project")
    project.add_argument("runs", nargs="+", type=Path)
    project.add_argument("--material-links", type=Path, required=True)
    project.add_argument("--output", type=Path, required=True)
    commands.add_parser("hardware")
    lock = commands.add_parser("runtime-lock")
    lock.add_argument("--output", type=Path, required=True)
    worker = commands.add_parser("worker")
    worker.add_argument("client_config", type=Path)
    worker.add_argument("--state-root", type=Path, required=True)
    worker.add_argument("--runtime-id", required=True)
    worker.add_argument("--runtime-lock", type=Path, required=True)
    worker.add_argument("--provider-config", type=Path, required=True)
    worker.add_argument("--budget", type=Path)
    worker.add_argument("--model-path", type=Path, required=True)
    worker.add_argument("--model-manifest", type=Path, required=True)
    worker.add_argument(
        "--heavy-lock", type=Path, default=Path("/Users/Shared/SCLibCompute/heavy-job.lock")
    )
    worker.add_argument("--cycles", type=int, default=1)
    args = parser.parse_args()
    if args.command == "prepare":
        write(
            args.output,
            parse_source(args.source, source_id=args.source_id, source_format=args.format),
        )
    elif args.command == "prepare-corpus":
        selection = read(args.selection)
        errors = validate_manifest(selection)
        if errors:
            raise ValueError("selection_invalid:" + ";".join(errors))
        result = prepare_corpus(
            selection, args.private_root, progress=lambda row: print(json.dumps(row), flush=True)
        )
        write(args.output, result)
        return 1 if result["source_failures"] else 0
    elif args.command == "hardware":
        print(json.dumps(hardware()))
    elif args.command == "runtime-lock":
        write(args.output, runtime_lock())
    elif args.command == "worker":
        import hashlib
        from scripts.sclib_compute.worker import client_from_config
        from .compute import NERWorker

        if not 1 <= args.cycles <= 50:
            raise ValueError("worker_cycles_outside_pilot_budget")
        config = ProviderConfig(**read(args.provider_config))
        budget = Budget(**read(args.budget)) if args.budget else Budget()
        if canonical(read(args.runtime_lock)) != canonical(runtime_lock()):
            raise ValueError("installed_runtime_differs_from_frozen_lock")
        if args.client_config.is_symlink() or args.client_config.stat().st_mode & 0o077:
            raise ValueError("compute_client_config_must_be_private")
        with client_from_config(read(args.client_config)) as client:
            with provider_session(args, config) as provider:
                import mlx.core as mx

                adapter = NERWorker(
                    client,
                    args.state_root,
                    provider,
                    runtime_id=args.runtime_id,
                    model_manifest_sha256=hashlib.sha256(
                        args.model_manifest.read_bytes()
                    ).hexdigest(),
                    runtime_lock_sha256=hashlib.sha256(args.runtime_lock.read_bytes()).hexdigest(),
                    budget=budget,
                    memory=lambda: memory_observation(mx.get_peak_memory())["observed_peak_bytes"],
                )
                try:
                    for _ in range(args.cycles):
                        receipt = adapter.one_cycle()
                        print(json.dumps(receipt), flush=True)
                        if receipt.get("status") == "empty_claim":
                            break
                finally:
                    adapter.close()
    elif args.command == "manifest":
        value = read(args.manifest)
        if args.freeze_output:
            write(args.freeze_output, freeze_manifest(value))
        else:
            errors = validate_manifest(value)
            print(json.dumps({"status": "valid" if not errors else "invalid", "errors": errors}))
            return 1 if errors else 0
    elif args.command == "annotation":
        write(args.output, blank_annotation(read(args.manifest), args.slot))
    elif args.command == "evaluate":
        write(args.output, evaluate(read(args.models), read(args.gold), read(args.manifest)))
    elif args.command == "review-package":
        if (
            args.output == args.private_mapping_output
            or args.output.exists()
            or args.private_mapping_output.exists()
        ):
            raise ValueError("review_packet_and_mapping_need_distinct_new_paths")
        packet, mapping = blinded_review(read(args.models))
        write(args.private_mapping_output, mapping)
        write(args.output, packet)
    elif args.command == "project":
        write(
            args.output, assemble_reports([read(p) for p in args.runs], read(args.material_links))
        )
    elif args.command == "export":
        write(
            args.output,
            import_package(read(args.run), read(args.document), read(args.source_metadata)),
        )
    elif args.command == "comparison-input":
        write(
            args.output,
            comparison_package([read(p) for p in args.runs], read(args.manifest), args.provider),
        )
    elif args.command == "batch":
        manifest = read(args.manifest)
        batch_selection(manifest, args.split)
        config = ProviderConfig(**read(args.provider_config))
        budget = Budget(**read(args.budget)) if args.budget else Budget()
        ledger = Ledger(args.ledger)

        def load_document(capture):
            if args.documents_root:
                name = capture["content_manifest_sha256"]
                if not __import__("re").fullmatch(r"[0-9a-f]{64}", name):
                    raise ValueError("document_content_address_invalid")
                return read(args.documents_root / (name + ".json"))
            if not capture.get("private_document_path"):
                raise ValueError("frozen_batch_requires_documents_root")
            return read(capture["private_document_path"])

        def publish(paper, result):
            path = args.output_dir / (result["job_key"] + ".json")
            if path.exists():
                if canonical(read(path)) != canonical(result):
                    raise ValueError("immutable_batch_output_conflict")
            else:
                write(path, result)
            return {
                "filename": path.name,
                "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
            }

        try:
            with provider_session(args, config) as provider:
                result = run_batch(
                    manifest,
                    provider,
                    ledger,
                    split=args.split,
                    load_document=load_document,
                    publish=publish,
                    budget=budget,
                    progress=lambda row: print(json.dumps(row), flush=True),
                )
            write(args.output, result)
            return 0 if result["machine_text_complete"] else 1
        finally:
            ledger.close()
    elif args.command == "run":
        document = read(args.document)
        verify_document(document)
        config = ProviderConfig(**read(args.provider_config))
        budget = Budget(**read(args.budget)) if args.budget else Budget()
        rights = read(args.source_rights) if args.source_rights else {}
        transfer = (
            rights.get("source_sha256") == document["source_sha256"]
            and rights.get("cloud_inference_allowed") is True
        )
        ledger = Ledger(args.ledger)
        try:
            with provider_session(args, config) as provider:
                result = Pipeline(provider, ledger, budget=budget).run(
                    document,
                    paper_id=args.paper_id,
                    work_id=args.work_id,
                    cloud_transfer_allowed=transfer,
                )
            write(args.output, result)
            return 0 if result["coverage"]["machine_text_complete"] else 1
        finally:
            ledger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
