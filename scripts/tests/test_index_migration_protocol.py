"""Pure shape/adversarial tests, not an executed migration measurement."""
from __future__ import annotations

import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import index_migration_protocol as protocol


def migration_report():
    """Declared synthetic wire fixture; callers must not label this observed."""
    generations = {}
    for phase, count, number in (("before", 7, 1), ("after", 5, 2)):
        generations[phase] = {"generation_id": str(UUID(int=number)), "activation_event_id": str(UUID(int=10 + number)),
            "manifest_sha256": str(number) * 64, "member_inventory_sha256": "a" * 64, "member_count": count,
            "paper_counts": {"arxiv:2609.00011": count - 2, "arxiv:2609.00012": 2},
            "vector_bytes": count * 3072, "local_document_tokens": count * 20}
    queries = {}
    for phase in protocol.PHASES:
        generation = generations["after" if phase == "after" else "before"]
        queries[phase] = {"generation_id": generation["generation_id"], "activation_event_id":
            str(UUID(int=13)) if phase == "rollback" else generation["activation_event_id"],
            "hit_ids": ["ig62_" + UUID(generation["generation_id"]).hex + "_" + f"{n:064x}"
                        for n in range(generation["member_count"])], "hydration_sha256": "b" * 64,
            "samples": [{"query_id": identifier, "latency_ms": 1.0, "hit_count": generation["member_count"],
                         "hydrated_count": generation["member_count"]} for identifier in protocol.QUERY_IDS]}
    retained = {**{key: "c" * 64 for key in ("answer_receipt_sha256", "answer_row_sha256", "release_manifest_sha256",
        "release_row_sha256", "release_pins_sha256", "artifact_inventory_sha256")}, "release_pin_count": 18,
        "measured_paper_pin_count": 2, "answer_generation_id": generations["before"]["generation_id"],
        "answer_activation_event_id": generations["before"]["activation_event_id"]}
    return {"version": protocol.VERSION, "run_id": "d" * 32, "schema_revision": "0068_answer_evidence",
        "logical_index": "migration-" + "d" * 32, "query_order": "synthetic_vector_id_order", "generations": generations,
        "partial_publication": {"expected_count": 5, "observed_count": 1, "missing_count": 4,
            "validation_outcome": "rejected", "activation_refused": True,
            "publication_failed": True, "repair_plan_sha256": "1" * 64, "repair_before_sha256": "2" * 64,
            "repair_after_sha256": "2" * 64, "recovery_acknowledged_count": 4, "recovery_already_present_count": 1,
            "active_generation_id": generations["before"]["generation_id"],
            "active_event_id": generations["before"]["activation_event_id"]}, "queries": queries,
        "activation_checks": {key: {"before_sha256": str(n) * 64, "after_sha256": str(n) * 64,
            "before_event_count": n, "after_event_count": n} for key, n in (("outer_rollback", 1), ("idempotent_replay", 2))},
        "retention": {phase: deepcopy(retained) for phase in protocol.PHASES},
        "replacement": {"removed_current_chunk_count": 2, "changed_same_position_count": 1,
            "retained_old_member_count": 7, "current_chunk_count": 5, "current_chunk_inventory_sha256": "e" * 64},
        "timings_ms": {phase: 1.0 for phase in protocol.TIMINGS}, "checks": list(protocol.CHECKS),
        "authority": deepcopy(protocol.AUTHORITY), "embedding": {"synthetic": True, "provider_calls": 0, "provider_attempts": 0,
            "provider_tokens": None, "provider_cost_usd": None, "production_embedding_quality_measured": False}}


def test_closed_fixture_is_detached_not_scientific_evidence():
    value = migration_report()
    result = protocol.validate_migration_report(value)
    assert result == value and result is not value
    result["queries"]["before"]["hit_ids"].clear()
    assert value["queries"]["before"]["hit_ids"]


@pytest.mark.parametrize("path,value", [
    (("extra",), True), (("run_id",), "invalid"), (("schema_revision",), None),
    (("query_order",), "semantic_recall"), (("authority", "scientific_acceptance"), 0),
    (("authority", "production_migration_verified"), True), (("checks",), protocol.CHECKS[:-1]),
    (("generations", "after", "member_count"), True), (("generations", "before", "vector_bytes"), 1),
    (("generations", "after", "paper_counts"), {"arxiv:2609.00011": 2, "arxiv:2609.00012": 3}),
    (("generations", "before", "local_document_tokens"), None),
    (("partial_publication", "observed_count"), 5), (("partial_publication", "missing_count"), 0),
    (("partial_publication", "validation_outcome"), "validated"), (("partial_publication", "activation_refused"), 1),
    (("partial_publication", "active_generation_id"), str(UUID(int=2))),
    (("partial_publication", "publication_failed"), False),
    (("partial_publication", "repair_after_sha256"), "f" * 64),
    (("partial_publication", "recovery_already_present_count"), 0),
    (("partial_publication", "recovery_acknowledged_count"), 5),
    (("activation_checks", "outer_rollback", "after_sha256"), "f" * 64),
    (("activation_checks", "idempotent_replay", "after_event_count"), 3),
    (("embedding", "provider_attempts"), True),
    (("queries", "before", "hit_ids"), []), (("queries", "after", "samples"), []),
    (("queries", "rollback", "hydration_sha256"), "9" * 64),
    (("queries", "rollback", "activation_event_id"), str(UUID(int=11))),
    (("retention", "after", "answer_receipt_sha256"), "f" * 64),
    (("retention", "rollback", "release_pins_sha256"), "f" * 64),
    (("retention", "before", "measured_paper_pin_count"), 0),
    (("replacement", "removed_current_chunk_count"), 0), (("replacement", "changed_same_position_count"), 0),
    (("timings_ms", "rollback"), float("nan")), (("timings_ms", "rollback"), True),
    (("timings_ms", "rollback"), -1), (("embedding", "provider_calls"), False),
    (("embedding", "provider_tokens"), 0), (("embedding", "provider_cost_usd"), 0.0),
])
def test_rejects_missing_ambiguous_inflated_or_changed_observations(path, value):
    report = migration_report()
    target = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(protocol.MigrationProtocolError, match="index_migration_measurement_invalid"):
        protocol.validate_migration_report(report)


def test_duplicate_ids_query_id_mismatch_and_missing_top_field():
    for mutation in (lambda r: r["queries"]["before"]["hit_ids"].__setitem__(1, r["queries"]["before"]["hit_ids"][0]),
                     lambda r: r["queries"]["after"]["samples"][0].__setitem__("query_id", "unknown"),
                     lambda r: r.pop("retention")):
        report = migration_report()
        mutation(report)
        with pytest.raises(protocol.MigrationProtocolError):
            protocol.validate_migration_report(report)


def test_protocol_import_without_site_api_database_or_provider_libraries():
    script = Path(protocol.__file__).resolve()
    code = "import runpy,sys; runpy.run_path(sys.argv[1]); assert not any(x in sys.modules for x in ['sqlalchemy','models','google','pytest'])"
    result = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("arguments", [[], ["--sta", "measure"], ["--stage", "SECRET"],
                                      ["--stage", "measure", "--database-url", "SECRET"]])
def test_worker_cli_rejects_arguments_before_any_capability_or_client(arguments):
    worker = Path(__file__).resolve().parents[1] / "index_migration_worker.py"
    result = subprocess.run([sys.executable, str(worker), *arguments], env={}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert result.stdout == "" and result.stderr == "index_migration_worker_failed\n"
