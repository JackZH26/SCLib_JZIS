"""Bounded, offline temporal admission over an explicitly declared dependency DAG.

The resolver is an application trust boundary: it must resolve exact server-side
source/result revisions, never return a caller's record or public envelope. This
function cannot authenticate that resolver, discover omitted scientific inputs,
freeze a database, grant source permissions, or assess LLM training contamination.
API and ingestion vendor this pure module byte-for-byte.
"""
from __future__ import annotations

import heapq
import re
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

TEMPORAL_SNAPSHOT_POLICY_VERSION = "temporal-snapshot/1.0.0"
TEMPORAL_PROVENANCE_VERSION = "temporal-provenance/1.0.0"
MAX_NODES = 10000
MAX_EDGES = 50000
MAX_DEPENDENCIES = 200
_IDENTIFIER = re.compile(r"^[A-Za-z0-9:_.@/+\-]{1,200}$")


def utc_instant(value: Any) -> datetime | None:
    """Parse an explicit aware instant; dates/naive times are not invented UTC."""
    if isinstance(value, str):
        if len(value) > 64 or "T" not in value:
            return None
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    try:
        return value.astimezone(UTC) if value.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def evaluate_temporal_snapshot(
    nodes: Mapping[str, Mapping[str, Any]],
    *,
    cutoff: datetime | str,
    resolve_provenance: Callable[[str], Mapping[str, Any] | None],
    mode: str = "public_knowledge",
) -> dict[str, Any]:
    """Evaluate declared result/feature nodes, without mutation or persistence.

    Each node has only ``dependency_ids`` and ``dependencies_complete``. An
    explicitly complete empty list is a leaf, not a missingness default. Input
    provenance must come through the resolver, not through the node payload.
    ``public_knowledge`` uses conservative result known-by bounds. The separate
    ``operational_capture`` mode additionally requires every node to have been
    captured locally by cutoff; it does not rewrite public availability.

    Invalid graph shape/budget fails the whole call. Missing/unknown dependencies,
    cycles and incomplete declarations hold the affected node and all dependents.
    The report is not an immutable or scientifically accepted dataset release.
    """
    cutoff_at = utc_instant(cutoff)
    if cutoff_at is None:
        raise ValueError("temporal_cutoff_requires_aware_instant")
    if mode not in {"public_knowledge", "operational_capture"}:
        raise ValueError("temporal_mode_unsupported")
    if not callable(resolve_provenance):
        raise ValueError("authoritative_provenance_resolver_required")
    if not isinstance(nodes, Mapping) or len(nodes) > MAX_NODES:
        raise ValueError("temporal_graph_node_budget_or_shape")
    if any(not isinstance(key, str) or not _IDENTIFIER.fullmatch(key) for key in nodes):
        raise ValueError("temporal_graph_invalid_node_id")

    dependencies: dict[str, tuple[str, ...]] = {}
    reasons: dict[str, set[str]] = {}
    own_public: dict[str, datetime | None] = {}
    own_capture: dict[str, datetime | None] = {}
    reverse: dict[str, list[str]] = {key: [] for key in nodes}
    pending: dict[str, int] = {}
    edges = 0
    for key in sorted(nodes):
        node = nodes[key]
        if not isinstance(node, Mapping) or set(node) != {"dependency_ids", "dependencies_complete"}:
            raise ValueError("temporal_graph_invalid_node_shape")
        raw_dependencies = node["dependency_ids"]
        if not isinstance(raw_dependencies, (list, tuple)) or len(raw_dependencies) > MAX_DEPENDENCIES:
            raise ValueError("temporal_graph_dependency_budget_or_shape")
        if any(not isinstance(dep, str) or not _IDENTIFIER.fullmatch(dep) for dep in raw_dependencies):
            raise ValueError("temporal_graph_invalid_dependency_id")
        if len(set(raw_dependencies)) != len(raw_dependencies):
            raise ValueError("temporal_graph_duplicate_dependency")
        edges += len(raw_dependencies)
        if edges > MAX_EDGES:
            raise ValueError("temporal_graph_edge_budget")
        dependencies[key] = tuple(sorted(raw_dependencies))
        reasons[key] = set()
        if node["dependencies_complete"] is not True:
            reasons[key].add("dependency_declaration_incomplete")
        if any(dep not in nodes for dep in raw_dependencies):
            reasons[key].add("dependency_missing")
        pending[key] = sum(dep in nodes for dep in raw_dependencies)
        for dep in raw_dependencies:
            if dep in nodes:
                reverse[dep].append(key)

        # Never fall back to graph/record metadata when registry resolution fails.
        try:
            provenance = resolve_provenance(key)
        except Exception:
            provenance = None
            reasons[key].add("provenance_resolution_failed")
        if not isinstance(provenance, Mapping):
            provenance = {}
        if provenance.get("version") != TEMPORAL_PROVENANCE_VERSION:
            reasons[key].add("provenance_unresolved_or_unsupported")
        if provenance.get("assessment_complete") is not True:
            reasons[key].add("provenance_assessment_incomplete")
        if provenance.get("status") != "known_by":
            reasons[key].add("result_availability_uncertain" if provenance.get("status") == "uncertain" else "result_availability_unknown")
        elif provenance.get("availability_basis") != "source_version_witness":
            reasons[key].add("result_availability_basis_unsupported")
        own_public[key] = utc_instant(provenance.get("result_available_at"))
        if own_public[key] is None:
            reasons[key].add("result_available_at_missing_or_invalid")
        own_capture[key] = utc_instant(provenance.get("captured_at"))
        if mode == "operational_capture" and own_capture[key] is None:
            reasons[key].add("capture_time_missing_or_invalid")

    ready = [key for key in nodes if pending[key] == 0]
    heapq.heapify(ready)
    results: dict[str, dict[str, Any]] = {}
    public_times: dict[str, datetime | None] = {}
    admission_times: dict[str, datetime | None] = {}
    while ready:
        key = heapq.heappop(ready)
        blocked = [dep for dep in dependencies[key] if dep not in results or not results[dep]["eligible"]]
        if blocked:
            reasons[key].add("dependency_not_admitted")
        # A post-cutoff dependency still has a known time. Unknown/invalid lineage
        # never acquires a fabricated effective time through max(known subset).
        dependency_public = [public_times.get(dep) for dep in dependencies[key]]
        dependency_admission = [admission_times.get(dep) for dep in dependencies[key]]
        own_invalid = reasons[key] - {"dependency_not_admitted", "capture_time_missing_or_invalid"}
        times_known = not own_invalid and all(value is not None for value in dependency_public)
        effective_public = max([own_public[key], *dependency_public]) if times_known else None
        effective_admission = effective_public
        if mode == "operational_capture":
            capture_known = times_known and own_capture[key] is not None and all(value is not None for value in dependency_admission)
            effective_admission = max([effective_public, own_capture[key], *dependency_admission]) if capture_known else None
        if effective_admission is not None and effective_admission > cutoff_at:
            reasons[key].add("available_after_cutoff")
        public_times[key] = effective_public
        admission_times[key] = effective_admission
        results[key] = {
            "eligible": not reasons[key],
            "effective_result_available_at": _iso(effective_public),
            "effective_admission_at": _iso(effective_admission),
            "reason_codes": sorted(reasons[key]),
            "blocked_dependency_ids": blocked,
        }
        for dependent in sorted(reverse[key]):
            pending[dependent] -= 1
            if pending[dependent] == 0:
                heapq.heappush(ready, dependent)

    # Kahn's remaining nodes are cycles or their downstream dependents. Do not
    # pretend every remaining node is itself a cycle member.
    for key in sorted(set(nodes) - set(results)):
        reasons[key].add("dependency_cycle_in_closure")
        results[key] = {
            "eligible": False,
            "effective_result_available_at": None,
            "effective_admission_at": None,
            "reason_codes": sorted(reasons[key]),
            "blocked_dependency_ids": [dep for dep in dependencies[key] if dep not in results or not results[dep]["eligible"]],
        }
    ordered = {key: results[key] for key in sorted(results)}
    admitted = [key for key, result in ordered.items() if result["eligible"]]
    reason_counts = Counter(reason for result in ordered.values() for reason in result["reason_codes"])
    return {
        "version": TEMPORAL_SNAPSHOT_POLICY_VERSION,
        "cutoff": _iso(cutoff_at),
        "mode": mode,
        "nodes": ordered,
        "admitted_ids": admitted,
        "counts": {"total_nodes": len(nodes), "admitted_nodes": len(admitted), "excluded_nodes": len(nodes) - len(admitted)},
        "exclusion_reason_counts": dict(sorted(reason_counts.items())),
        "dependency_completeness": "caller_declared_not_independently_proven",
        "reproducible_snapshot_established": False,
        "scientific_acceptance": False,
        "llm_pretraining_contamination_assessed": False,
    }
