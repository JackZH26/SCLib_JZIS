"""Build an import package by replaying the common source/semantic validator."""

from __future__ import annotations

from .blocks import verify_document
from .contract import bound_row_evidence, digest, occurrence_positions, validate_candidate


def import_package(run, document, source_metadata):
    verify_document(document)
    if (
        run["input_sha256"] != document["manifest_sha256"]
        or run["source_sha256"] != document["source_sha256"]
    ):
        raise ValueError("run_document_source_mismatch")
    blocks = {b["block_id"]: b for b in run["blocks"]}
    candidates = []
    for result in run["results"]:
        block = blocks[result["block_id"]]
        inputs = result.get("input_blocks", [block])
        validated = validate_candidate(result["candidate"], inputs)
        if digest(validated["normalized"]) != digest(result["normalized"]):
            raise ValueError("normalized_candidate_replay_mismatch")
        for row in result["candidate"]["results"]:
            positions = occurrence_positions(row, inputs)
            occurrence = digest(positions)
            candidates.append(
                {
                    "local_id": row["local_id"],
                    "position_sha256": occurrence,
                    "positions": {"source_anchors": positions},
                    "payload": row,
                    "validation": {
                        "locator_verified": True,
                        "schema_valid": True,
                        "scientific_acceptance": False,
                        "bound_evidence": bound_row_evidence(row, inputs),
                        "normalized": next(
                            n for n in validated["normalized"] if n["local_id"] == row["local_id"]
                        ),
                    },
                }
            )
    config = run["config"]
    provider = config["provider"]
    return {
        "version": "materials-ner-import/3.0",
        "paper_id": run["paper_id"],
        "sclib_work_id": source_metadata.get("sclib_work_id"),
        "job_key": run["job_key"],
        "source_sha256": document["source_sha256"],
        "manifest_sha256": document["manifest_sha256"],
        "parser_version": document["parser_version"],
        "source_manifest": document,
        "source_version": source_metadata["source_version"],
        "source_license": source_metadata["source_license"],
        "transfer_allowed": source_metadata.get("transfer_allowed") is True,
        "provider": provider["provider"],
        "model": provider["model"],
        "model_revision": provider.get("revision"),
        "config": config,
        "config_sha256": digest(config),
        "prompt_version": config["prompt_version"],
        "status": "completed" if run["coverage"]["machine_text_complete"] else "failed",
        "usage": {"attempts": run["attempts"]},
        "validated_candidates": candidates,
        "block_coverage": [
            {
                "block_id": bid,
                "input_sha256": digest(blocks[bid]),
                "status": status,
                "receipt": {"input_source_sha256": document["source_sha256"]},
            }
            for bid, status in run["terminal"].items()
        ],
    }
