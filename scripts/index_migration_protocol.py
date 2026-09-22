"""Closed, metadata-only synthetic index-migration measurement contract.

This is a protocol canary, not a model-quality benchmark or a production SLO.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from uuid import UUID

VERSION = "index-migration-measurement/1.0.0"
QUERY_IDS = ["synthetic-corpus-overview", "synthetic-material-comparison", "synthetic-evidence-limits"]
PHASES = ["before", "after", "rollback"]
TIMINGS = ["ingest_before", "stage_before", "publish_before", "retain_history",
           "ingest_after", "stage_after", "partial_publication", "publish_after", "rollback"]
AUTHORITY = {"scientific_acceptance": False, "ml_training_approved": False,
             "public_release_authorized": False, "production_migration_verified": False}
CHECKS = ["complete_combined_generations", "partial_validation_rejected", "partial_activation_refused",
          "pointer_unchanged_until_explicit_promotion", "generation_filtered_queries",
          "exact_retained_hydration", "same_position_revision_changed", "removed_chunks_not_current",
          "old_answer_receipt_verified", "old_release_dependencies_verified", "explicit_rollback_verified",
          "activation_outer_rollback_verified", "activation_idempotent_replay_verified"]
MAX_BYTES = 128 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class MigrationProtocolError(ValueError):
    pass


def require(condition):
    if not condition:
        raise MigrationProtocolError("index_migration_measurement_invalid")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _keys(value, keys):
    require(type(value) is dict and set(value) == set(keys))


def _sha(value):
    require(type(value) is str and _SHA.fullmatch(value) is not None)


def _uuid(value):
    require(type(value) is str and str(UUID(value)) == value)


def _number(value):
    require(type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 600_000)


def validate_migration_report(value):
    """Reject incomplete/mismatched observations; never create missing checks."""
    try:
        require(len(canonical(value)) <= MAX_BYTES)
        _keys(value, ["version", "run_id", "schema_revision", "logical_index", "query_order", "generations", "partial_publication", "activation_checks",
                      "queries", "retention", "replacement", "timings_ms", "embedding", "checks", "authority"])
        require(value["version"] == VERSION and type(value["run_id"]) is str
                and re.fullmatch(r"[0-9a-f]{32}", value["run_id"]) is not None)
        require(type(value["schema_revision"]) is str and re.fullmatch(r"[A-Za-z0-9_]{1,64}", value["schema_revision"]) is not None)
        require(value["logical_index"] == "migration-" + value["run_id"])
        require(value["query_order"] == "synthetic_vector_id_order")
        require(value["checks"] == CHECKS and value["authority"] == AUTHORITY
                and all(item is False for item in value["authority"].values()))
        _keys(value["generations"], ["before", "after"])
        for phase, expected in (("before", 7), ("after", 5)):
            row = value["generations"][phase]
            _keys(row, ["generation_id", "activation_event_id", "manifest_sha256", "member_inventory_sha256",
                        "member_count", "paper_counts", "vector_bytes", "local_document_tokens"])
            for key in ("generation_id", "activation_event_id"):
                _uuid(row[key])
            for key in ("manifest_sha256", "member_inventory_sha256"):
                _sha(row[key])
            require(type(row["member_count"]) is int and row["member_count"] == expected
                    and type(row["vector_bytes"]) is int and row["vector_bytes"] == expected * 768 * 4)
            require(row["paper_counts"] == {"arxiv:2609.00011": expected - 2, "arxiv:2609.00012": 2}
                    and all(type(n) is int for n in row["paper_counts"].values()))
            require(type(row["local_document_tokens"]) is int and 1 <= row["local_document_tokens"] <= expected * 512)
        before, after = (value["generations"][phase] for phase in ("before", "after"))
        require(before["generation_id"] != after["generation_id"])
        partial = value["partial_publication"]
        _keys(partial, ["expected_count", "observed_count", "missing_count", "validation_outcome",
                        "activation_refused", "active_generation_id", "active_event_id", "publication_failed",
                        "repair_plan_sha256", "repair_before_sha256", "repair_after_sha256",
                        "recovery_acknowledged_count", "recovery_already_present_count"])
        require(partial["publication_failed"] is True and partial["repair_before_sha256"] == partial["repair_after_sha256"])
        for key in ("repair_plan_sha256", "repair_before_sha256", "repair_after_sha256"):
            _sha(partial[key])
        require(type(partial["recovery_acknowledged_count"]) is int and partial["recovery_acknowledged_count"] == 4
                and type(partial["recovery_already_present_count"]) is int and partial["recovery_already_present_count"] == 1)
        require(type(partial["expected_count"]) is int and partial["expected_count"] == 5
                and type(partial["observed_count"]) is int and partial["observed_count"] == 1
                and type(partial["missing_count"]) is int and partial["missing_count"] == 4
                and partial["validation_outcome"] == "rejected" and partial["activation_refused"] is True
                and partial["active_generation_id"] == before["generation_id"]
                and partial["active_event_id"] == before["activation_event_id"])
        _keys(value["activation_checks"], ["outer_rollback", "idempotent_replay"])
        for key, expected in (("outer_rollback", 1), ("idempotent_replay", 2)):
            check = value["activation_checks"][key]
            _keys(check, ["before_sha256", "after_sha256", "before_event_count", "after_event_count"])
            _sha(check["before_sha256"])
            require(check["before_sha256"] == check["after_sha256"]
                    and type(check["before_event_count"]) is int and type(check["after_event_count"]) is int
                    and check["before_event_count"] == check["after_event_count"] == expected)
        _keys(value["queries"], PHASES)
        for phase in PHASES:
            row = value["queries"][phase]
            _keys(row, ["generation_id", "activation_event_id", "hit_ids", "hydration_sha256", "samples"])
            generation = after if phase == "after" else before
            require(row["generation_id"] == generation["generation_id"])
            _uuid(row["activation_event_id"])
            if phase != "rollback":
                require(row["activation_event_id"] == generation["activation_event_id"])
            _sha(row["hydration_sha256"])
            require(type(row["hit_ids"]) is list and len(row["hit_ids"]) == generation["member_count"]
                    and row["hit_ids"] == sorted(set(row["hit_ids"])))
            prefix = "ig62_" + UUID(row["generation_id"]).hex + "_"
            require(all(type(item) is str and item.startswith(prefix) and _SHA.fullmatch(item[len(prefix):])
                        for item in row["hit_ids"]))
            require(type(row["samples"]) is list and len(row["samples"]) == len(QUERY_IDS))
            for sample, identifier in zip(row["samples"], QUERY_IDS, strict=True):
                _keys(sample, ["query_id", "latency_ms", "hit_count", "hydrated_count"])
                require(sample["query_id"] == identifier and type(sample["hit_count"]) is int
                        and type(sample["hydrated_count"]) is int
                        and sample["hit_count"] == sample["hydrated_count"] == generation["member_count"])
                _number(sample["latency_ms"])
        first, final = value["queries"]["before"], value["queries"]["rollback"]
        require(first["hit_ids"] == final["hit_ids"] and first["hydration_sha256"] == final["hydration_sha256"]
                and first["activation_event_id"] != final["activation_event_id"]
                and set(first["hit_ids"]).isdisjoint(value["queries"]["after"]["hit_ids"]))
        _keys(value["retention"], PHASES)
        for row in value["retention"].values():
            _keys(row, ["answer_receipt_sha256", "answer_row_sha256", "release_manifest_sha256",
                        "release_row_sha256", "release_pins_sha256", "release_pin_count", "artifact_inventory_sha256",
                        "measured_paper_pin_count", "answer_generation_id", "answer_activation_event_id"])
            for key in ("answer_receipt_sha256", "answer_row_sha256", "release_manifest_sha256", "release_row_sha256",
                        "release_pins_sha256", "artifact_inventory_sha256"):
                _sha(row[key])
            require(type(row["release_pin_count"]) is int and 1 <= row["release_pin_count"] <= 1000
                    and type(row["measured_paper_pin_count"]) is int and row["measured_paper_pin_count"] == 2
                    and row["answer_generation_id"] == before["generation_id"]
                    and row["answer_activation_event_id"] == before["activation_event_id"])
        require(value["retention"]["before"] == value["retention"]["after"] == value["retention"]["rollback"])
        replacement = value["replacement"]
        _keys(replacement, ["removed_current_chunk_count", "changed_same_position_count", "retained_old_member_count",
                            "current_chunk_count", "current_chunk_inventory_sha256"])
        require(all(type(replacement[key]) is int for key in replacement if key != "current_chunk_inventory_sha256"))
        require(replacement["removed_current_chunk_count"] == 2 and replacement["changed_same_position_count"] >= 1
                and replacement["retained_old_member_count"] == 7 and replacement["current_chunk_count"] == 5)
        _sha(replacement["current_chunk_inventory_sha256"])
        _keys(value["timings_ms"], TIMINGS)
        for elapsed in value["timings_ms"].values():
            _number(elapsed)
        require(value["embedding"] == {"synthetic": True, "provider_calls": 0, "provider_attempts": 0, "provider_tokens": None,
                                      "provider_cost_usd": None, "production_embedding_quality_measured": False})
        require(value["embedding"]["synthetic"] is True and type(value["embedding"]["provider_calls"]) is int
                and type(value["embedding"]["provider_attempts"]) is int
                and value["embedding"]["production_embedding_quality_measured"] is False)
        return copy.deepcopy(value)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise MigrationProtocolError("index_migration_measurement_invalid") from None
