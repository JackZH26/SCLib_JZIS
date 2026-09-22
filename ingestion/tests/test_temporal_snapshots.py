"""Synthetic temporal graph tests; no database, network, approval or real dates."""
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ingestion.temporal_snapshots import evaluate_temporal_snapshot, utc_instant

CUTOFF = "2020-06-01T00:00:00Z"
EARLY = "2020-01-01T00:00:00Z"
LATE = "2021-01-01T00:00:00Z"


def node(*dependencies, complete=True):
    return {"dependency_ids": list(dependencies), "dependencies_complete": complete}


def provenance(at=EARLY, captured=LATE, **updates):
    return {"version": "temporal-provenance/1.0.0", "status": "known_by",
            "result_available_at": at, "captured_at": captured,
            "availability_basis": "source_version_witness", "scientific_acceptance": False, "assessment_complete": True,
            **updates}


def evaluate(nodes, resolved, **kwargs):
    return evaluate_temporal_snapshot(nodes, cutoff=CUTOFF, resolve_provenance=resolved.get, **kwargs)


def test_exact_source_v1_does_not_backdate_new_v2_tc_structure_or_derived_feature():
    graph = {"v1-result": node(), "v2-tc": node(), "v2-structure": node(),
             "feature": node("v1-result", "v2-structure"), "prediction": node("feature", "v2-tc")}
    resolved = {key: provenance(LATE if key.startswith("v2") else EARLY) for key in graph}
    result = evaluate(graph, resolved)
    assert result["admitted_ids"] == ["v1-result"]
    assert result["nodes"]["feature"]["effective_result_available_at"] == LATE
    assert result["nodes"]["prediction"]["effective_admission_at"] == LATE
    assert "dependency_not_admitted" in result["nodes"]["prediction"]["reason_codes"]
    assert result["counts"] == {"total_nodes": 5, "admitted_nodes": 1, "excluded_nodes": 4}
    assert result["scientific_acceptance"] is False
    assert result["reproducible_snapshot_established"] is False
    assert result["llm_pretraining_contamination_assessed"] is False


@pytest.mark.parametrize("update,reason", [
    ({"status": "unknown", "result_available_at": None}, "result_availability_unknown"),
    ({"status": "uncertain"}, "result_availability_uncertain"),
    ({"version": "future"}, "provenance_unresolved_or_unsupported"),
    ({"availability_basis": "work_first_public_at"}, "result_availability_basis_unsupported"),
    ({"assessment_complete": False}, "provenance_assessment_incomplete"),
    ({"result_available_at": "2000-01-01"}, "result_available_at_missing_or_invalid"),
    ({"result_available_at": "2000-01-01T00:00:00"}, "result_available_at_missing_or_invalid"),
])
def test_unknown_or_malformed_provenance_blocks_descendants_without_partial_max(update, reason):
    result = evaluate({"a": node(), "b": node("a")}, {"a": provenance(**update), "b": provenance()})
    assert result["admitted_ids"] == []
    assert reason in result["nodes"]["a"]["reason_codes"]
    assert result["nodes"]["b"]["effective_result_available_at"] is None


def test_missing_dependency_and_incomplete_declaration_fail_closed():
    graph = {"missing-input": node("absent"), "incomplete": node(complete=False),
             "boolean-like": node(complete=1), "downstream": node("incomplete"), "independent": node()}
    result = evaluate(graph, {key: provenance() for key in graph})
    assert result["admitted_ids"] == ["independent"]
    assert "dependency_missing" in result["nodes"]["missing-input"]["reason_codes"]
    assert "dependency_declaration_incomplete" in result["nodes"]["boolean-like"]["reason_codes"]
    assert result["nodes"]["downstream"]["effective_result_available_at"] is None


def test_early_inputs_do_not_backdate_later_own_derived_result():
    graph = {"early-input": node(), "later-calculation": node("early-input")}
    result = evaluate(graph, {"early-input": provenance(), "later-calculation": provenance(LATE)})
    assert result["admitted_ids"] == ["early-input"]
    assert result["nodes"]["later-calculation"]["effective_result_available_at"] == LATE


@pytest.mark.parametrize("cycle", [("a",), ("a", "b"), ("a", "b", "c")])
def test_cycle_and_descendants_held_but_unrelated_nodes_survive(cycle):
    graph = {key: node(cycle[(index + 1) % len(cycle)]) for index, key in enumerate(cycle)}
    graph.update({"downstream": node(cycle[0]), "independent": node()})
    resolved = {key: provenance() for key in graph}
    result = evaluate(graph, resolved)
    assert result["admitted_ids"] == ["independent"]
    for key in (*cycle, "downstream"):
        assert "dependency_cycle_in_closure" in result["nodes"][key]["reason_codes"]
        assert result["nodes"][key]["effective_result_available_at"] is None
    assert result == evaluate(dict(reversed(list(graph.items()))), resolved)


def test_public_knowledge_and_capture_replay_are_separate_and_do_not_overwrite_times():
    graph = {"a": node(), "b": node("a")}
    resolved = {"a": provenance(), "b": provenance(captured=EARLY)}
    public = evaluate(graph, resolved)
    operational = evaluate(graph, resolved, mode="operational_capture")
    assert public["admitted_ids"] == ["a", "b"]
    assert operational["admitted_ids"] == []
    assert operational["nodes"]["b"]["effective_result_available_at"] == EARLY
    assert operational["nodes"]["b"]["effective_admission_at"] == LATE


def test_missing_capture_only_blocks_operational_mode():
    graph = {"a": node(), "b": node("a")}
    resolved = {"a": provenance(captured=None), "b": provenance(captured=EARLY)}
    assert evaluate(graph, resolved)["admitted_ids"] == ["a", "b"]
    result = evaluate(graph, resolved, mode="operational_capture")
    assert result["admitted_ids"] == []
    assert result["nodes"]["b"]["effective_result_available_at"] == EARLY
    assert result["nodes"]["b"]["effective_admission_at"] is None


def test_boundary_is_inclusive_and_offsets_are_normalized():
    instant = "2020-06-01T08:00:00+08:00"
    result = evaluate({"boundary": node()}, {"boundary": provenance(instant)})
    assert result["admitted_ids"] == ["boundary"]
    assert result["nodes"]["boundary"]["effective_result_available_at"] == CUTOFF


def test_resolver_required_and_failures_are_not_replaced_with_legacy_dates():
    result = evaluate({"legacy": node()}, {})
    assert result["admitted_ids"] == []
    def broken(_):
        raise RuntimeError("PRIVATE resolver detail")
    result = evaluate_temporal_snapshot({"legacy": node()}, cutoff=CUTOFF, resolve_provenance=broken)
    assert "provenance_resolution_failed" in result["nodes"]["legacy"]["reason_codes"]
    assert "PRIVATE" not in str(result)
    with pytest.raises(ValueError, match="resolver_required"):
        evaluate_temporal_snapshot({}, cutoff=CUTOFF, resolve_provenance=None)
    with pytest.raises(ValueError, match="invalid_node_shape"):
        evaluate({"legacy": {**node(), "provenance": provenance("1990-01-01T00:00:00Z")}}, {})


@pytest.mark.parametrize("graph", [
    {"bad id": node()}, {"a": {"dependency_ids": []}}, {"a": node("b", "b")},
    {"a": {"dependency_ids": "a", "dependencies_complete": True}},
    {"a": node(*[f"dep-{index}" for index in range(201)])},
])
def test_malformed_or_oversized_graph_raises_without_silent_truncation(graph):
    with pytest.raises(ValueError):
        evaluate(graph, {})


def test_global_budgets_fail_closed(monkeypatch):
    import ingestion.temporal_snapshots as snapshots
    monkeypatch.setattr(snapshots, "MAX_NODES", 1)
    with pytest.raises(ValueError, match="node_budget"):
        evaluate({"a": node(), "b": node()}, {})
    monkeypatch.setattr(snapshots, "MAX_NODES", 10)
    monkeypatch.setattr(snapshots, "MAX_EDGES", 0)
    with pytest.raises(ValueError, match="edge_budget"):
        evaluate({"a": node("b"), "b": node()}, {})


def test_iterative_long_chain_and_no_mutation_or_input_order_effect():
    graph = {f"node-{index}": node(f"node-{index - 1}") if index else node() for index in range(1500)}
    resolved = {key: provenance() for key in graph}
    before = deepcopy((graph, resolved))
    result = evaluate(graph, resolved)
    assert len(result["admitted_ids"]) == 1500
    assert evaluate(dict(reversed(list(graph.items()))), resolved) == result
    assert (graph, resolved) == before


@pytest.mark.parametrize("value", [None, "2020-01-01", "2020-01-01T00:00:00", datetime(2020, 1, 1), True])
def test_cutoff_requires_aware_instant(value):
    assert utc_instant(value) is None
    with pytest.raises(ValueError, match="cutoff_requires_aware"):
        evaluate_temporal_snapshot({}, cutoff=value, resolve_provenance={}.get)


def test_empty_graph_and_utc_datetime_are_supported_without_claiming_completion():
    result = evaluate_temporal_snapshot({}, cutoff=datetime(2020, 1, 1, tzinfo=UTC), resolve_provenance={}.get)
    assert result["counts"]["total_nodes"] == 0
    assert result["reproducible_snapshot_established"] is False
    with pytest.raises(ValueError, match="mode_unsupported"):
        evaluate({}, {}, mode="anything")


def test_api_and_ingestion_modules_are_identical():
    root = Path(__file__).resolve().parents[2]
    assert (root / "api/services/temporal_snapshots.py").read_bytes() == (root / "ingestion/ingestion/temporal_snapshots.py").read_bytes()
