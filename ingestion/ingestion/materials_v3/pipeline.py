"""Resumable full-text pilot, never importing the production aggregator."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .blocks import block_inputs, coverage, make_blocks, verify_document
from .contract import CandidateError, digest, occurrence_key, parse_json, schema, validate_candidate
from .ledger import Ledger
from .prompt import VERSION as PROMPT_VERSION
from .prompt import messages
from .providers import OutputLimit, ProviderError, ResourceLimit
from . import NORMALIZER_VERSION


def implementation_hash():
    import hashlib

    root = Path(__file__).parent
    return digest(
        {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.iterdir())
            if p.suffix in {".py", ".json"}
        }
    )


@dataclass(frozen=True)
class Budget:
    max_tokens_per_block: int = 5000
    paper_seconds: int = 3600
    max_attempts_per_paper: int = 120
    infrastructure_retries: int = 2
    syntax_repairs: int = 1
    split_depth: int = 6

    def __post_init__(self):
        if self.infrastructure_retries not in range(3) or self.syntax_repairs not in range(2):
            raise ValueError("retry_budget_exceeds_protocol")
        if (
            min(self.paper_seconds, self.max_attempts_per_paper) < 1
            or self.max_tokens_per_block < 128
        ):
            raise ValueError("invalid_paper_budget")


class Pipeline:
    def __init__(self, provider, ledger: Ledger, *, budget=None):
        self.provider, self.ledger, self.budget = provider, ledger, budget or Budget()

    def run(
        self,
        document: dict,
        *,
        paper_id: str,
        work_id: str,
        cloud_transfer_allowed=False,
        prior_scope_attempts=0,
        prior_scope_seconds=0.0,
    ) -> dict:
        import math

        if (
            not isinstance(prior_scope_attempts, int)
            or isinstance(prior_scope_attempts, bool)
            or prior_scope_attempts < 0
            or not math.isfinite(prior_scope_seconds)
            or prior_scope_seconds < 0
        ):
            raise ValueError("invalid_prior_source_scope_usage")
        verify_document(document)
        if self.provider.config.provider != "local_mlx" and not cloud_transfer_allowed:
            raise ValueError("cloud_transfer_not_authorized_for_source")
        config = {
            "provider": asdict(self.provider.config),
            "prompt_version": PROMPT_VERSION,
            "schema_sha256": digest(schema()),
            "normalizer_version": NORMALIZER_VERSION,
            "implementation_sha256": implementation_hash(),
            "budget": asdict(self.budget),
        }
        identity = {
            "paper_id": paper_id,
            "work_id": work_id,
            "document_sha256": document["manifest_sha256"],
            "config": config,
        }
        key = "ner-" + digest(identity)
        self.ledger.enqueue(key, digest(config), document["manifest_sha256"])
        fence = self.ledger.claim(
            key, lease_seconds=self.budget.paper_seconds + self.provider.config.timeout_seconds + 60
        )
        if fence is None:
            return self.ledger.result(key)
        started = time.monotonic()
        previous_provider_seconds = sum(
            a["receipt"].get("wall_call_seconds", a["receipt"].get("seconds", 0))
            for a in self.ledger.attempts(key)
        )
        terminal, results, all_blocks = {}, [], []
        resource_failure = None

        def error_receipt(exc, call_started):
            return {
                "error": str(exc),
                **(asdict(exc.receipt) if exc.receipt else {}),
                "wall_call_seconds": time.monotonic() - call_started,
            }

        def split(block, depth):
            if depth >= self.budget.split_depth or len(block["text"]) < 256:
                return False
            middle, children = len(block["text"]) // 2, []
            for lo, hi in ((0, middle), (middle, len(block["text"]))):
                children.append(
                    {
                        **block,
                        "text": block["text"][lo:hi],
                        "source_start": block["source_start"] + lo,
                        "source_end": block["source_start"] + hi,
                        "parent_block_id": block["block_id"],
                        "block_id": "b-"
                        + digest({"parent": block["block_id"], "lo": lo, "hi": hi})[:24],
                    }
                )
            self.ledger.put_block(key, fence, block, "split", {"children": children})
            terminal[block["block_id"]] = "split"
            for child in children:
                process(child, depth + 1)
            return True

        def process(block, depth=0):
            nonlocal resource_failure
            all_blocks.append(block)
            cached = self.ledger.cached_block(key, block)
            if cached:
                status, value = cached
                terminal[block["block_id"]] = status
                if status == "split":
                    for child in value["children"]:
                        process(child, depth + 1)
                elif status in {"validated", "empty"}:
                    results.append(value)
                elif status == "resource_exhausted":
                    resource_failure = value["error"]
                return
            inputs = block_inputs(block, document)
            history = [a for a in self.ledger.attempts(key) if a["block_id"] == block["block_id"]]
            if history and history[-1]["status"] in {"output_limit", "resource_exhausted"}:
                last = history[-1]
                if last["status"] == "output_limit" and split(block, depth):
                    return
                if last["status"] == "resource_exhausted":
                    resource_failure = last["receipt"]["error"]
                status = last["status"]
                result = {"error": resource_failure or "split_budget_exhausted"}
                self.ledger.put_block(key, fence, block, status, result)
                terminal[block["block_id"]] = status
                return
            attempts = sum(a["status"] == "provider_failed" for a in history)
            failures = [a for a in history if a["status"] == "validation_failed"]
            repairs, previous, errors = 0, None, None
            if failures:
                receipt = failures[-1]["receipt"]
                repairs, previous, errors = (
                    receipt["repair"] + 1,
                    receipt["text"],
                    receipt["errors"],
                )
            valid = next((a for a in reversed(history) if a["status"] == "validated"), None)
            if valid:
                # Crash after attempt fsync but before block fsync: replay validation,
                # not a second provider request for the same successful response.
                value = parse_json(valid["receipt"]["text"])
                result = validate_candidate(value, inputs)
                result.update(
                    block_id=block["block_id"],
                    input_blocks=inputs,
                    occurrences=[occurrence_key(r, inputs) for r in value["results"]],
                )
                status = "validated" if value["results"] or value["unresolved_links"] else "empty"
                results.append(result)
                self.ledger.put_block(key, fence, block, status, result)
                terminal[block["block_id"]] = status
                return
            while True:
                if resource_failure:
                    status, result = (
                        "resource_exhausted",
                        {"error": resource_failure, "generation_attempted": False},
                    )
                    break
                if repairs > self.budget.syntax_repairs:
                    status, result = "validation_failed", {"errors": errors}
                    break
                if attempts > self.budget.infrastructure_retries:
                    status, result = "provider_failed", {"error": history[-1]["receipt"]["error"]}
                    break
                if (
                    prior_scope_seconds + previous_provider_seconds + time.monotonic() - started
                    >= self.budget.paper_seconds
                    or prior_scope_attempts + self.ledger.attempt_count(key)
                    >= self.budget.max_attempts_per_paper
                ):
                    status, result = "budget_exhausted", {"error": "paper_budget_exhausted"}
                    break
                self.ledger.heartbeat(
                    key, fence, lease_seconds=self.provider.config.timeout_seconds + 120
                )
                call_started = time.monotonic()
                try:
                    response = self.provider.generate(
                        messages(inputs, repair_errors=errors, previous=previous)
                    )
                    receipt = asdict(response)
                    receipt["wall_call_seconds"] = time.monotonic() - call_started
                    syntax_valid = False
                    try:
                        value = parse_json(response.text)
                        syntax_valid = True
                        result = validate_candidate(value, inputs)
                    except CandidateError as exc:
                        self.ledger.record_attempt(
                            key,
                            fence,
                            block["block_id"],
                            "validation_failed",
                            {
                                **receipt,
                                "errors": exc.errors,
                                "repair": repairs,
                                "raw_json_syntax_valid": syntax_valid,
                            },
                        )
                        if repairs >= self.budget.syntax_repairs:
                            status, result = "validation_failed", {"errors": exc.errors}
                            break
                        repairs += 1
                        errors, previous = exc.errors, response.text
                        continue
                    self.ledger.record_attempt(
                        key,
                        fence,
                        block["block_id"],
                        "validated",
                        {**receipt, "repair": repairs, "raw_json_syntax_valid": True},
                    )
                    result.update(
                        block_id=block["block_id"],
                        input_blocks=inputs,
                        occurrences=[occurrence_key(r, inputs) for r in value["results"]],
                    )
                    status = (
                        "validated" if value["results"] or value["unresolved_links"] else "empty"
                    )
                    results.append(result)
                    break
                except OutputLimit as exc:
                    self.ledger.record_attempt(
                        key,
                        fence,
                        block["block_id"],
                        "output_limit",
                        error_receipt(exc, call_started),
                    )
                    if split(block, depth):
                        return
                    status, result = "output_limit", {"error": "split_budget_exhausted"}
                    break
                except ResourceLimit as exc:
                    self.ledger.record_attempt(
                        key,
                        fence,
                        block["block_id"],
                        "resource_exhausted",
                        error_receipt(exc, call_started),
                    )
                    resource_failure = str(exc)
                    status, result = "resource_exhausted", {"error": str(exc)}
                    break
                except ProviderError as exc:
                    self.ledger.record_attempt(
                        key,
                        fence,
                        block["block_id"],
                        "provider_failed",
                        error_receipt(exc, call_started),
                    )
                    if attempts >= self.budget.infrastructure_retries:
                        status, result = "provider_failed", {"error": str(exc)}
                        break
                    attempts += 1
            self.ledger.put_block(key, fence, block, status, result)
            terminal[block["block_id"]] = status

        for block in make_blocks(document, max_tokens=self.budget.max_tokens_per_block):
            process(block)
        report = {
            "version": "materials-ner-run/3.0",
            "job_key": key,
            "paper_id": paper_id,
            "work_id": work_id,
            "config": config,
            "input_sha256": document["manifest_sha256"],
            "source_sha256": document["source_sha256"],
            "blocks": all_blocks,
            "terminal": terminal,
            "results": results,
            "coverage": coverage(document, all_blocks, terminal),
            "attempts": self.ledger.attempts(key),
            "seconds_this_attempt": time.monotonic() - started,
            "prior_source_scope_usage": {
                "attempts": prior_scope_attempts,
                "provider_seconds": prior_scope_seconds,
            },
            "scientific_acceptance": False,
            "production_database_changed": False,
        }
        self.ledger.complete(key, fence, report)
        return report
