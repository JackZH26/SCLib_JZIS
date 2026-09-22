"""Deterministic display sampling, not population estimation or record discovery.

Summaries describe the complete currently filtered result set. Stratification
deliberately protects small groups and therefore is not a representative sample.
No occurrence is factually deduplicated by this visualization helper.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict

from models.search import TimelinePoint

TIMELINE_POLICY_VERSION = "reported-tc-timeline/2.0.0"
SAMPLING_POLICY_VERSION = "timeline-stratified/1.0.0"


def point_identity(point: TimelinePoint) -> str:
    if point.point_id:
        return point.point_id
    # Compatibility for older internal callers; never numeric display buckets.
    return hashlib.sha256(point.model_dump_json().encode()).hexdigest()


def point_order(point: TimelinePoint):
    return point.year, -point.tc_kelvin, point_identity(point)


def finite_points(points: list[TimelinePoint]) -> list[TimelinePoint]:
    """Defense in depth for persisted projections; originals remain untouched."""
    return sorted((p for p in points
                   if math.isfinite(p.tc_kelvin) and p.tc_kelvin > 0
                   and isinstance(p.year, int) and not isinstance(p.year, bool) and 1900 <= p.year <= 2200
                   and (p.pressure_gpa is None or math.isfinite(p.pressure_gpa) and p.pressure_gpa >= 0)),
                  key=point_order)


def _origin(point):
    return point.knowledge_origin if point.classification_status == "resolved" and point.source_role != "conflicted" else "Unknown"


def _pressure(point):
    return str(point.pressure_semantics.get("pressure_state", "unreported"))


def _stratum(point):
    return point.family or "unknown", _origin(point), _pressure(point), point.year // 10 * 10


def _rank(value):
    return hashlib.sha256((SAMPLING_POLICY_VERSION + "|" + json.dumps(value, sort_keys=True)).encode()).hexdigest()


def sample_timeline(points: list[TimelinePoint], max_points: int | None):
    """Reserve bounds, then round-robin deterministic strata, smallest first.

    If the budget cannot cover every stratum, omitted-group counts are explicit.
    Stable identity hashing orders members, so input permutation is irrelevant.
    Returned chronology remains exact: no date jitter or value substitution.
    """
    if max_points is not None and (isinstance(max_points, bool) or max_points <= 0):
        raise ValueError("max_points must be positive")
    ordered = sorted(points, key=point_order)
    strata = defaultdict(list)
    for index, point in enumerate(ordered):
        strata[_stratum(point)].append(index)
    target = min(len(ordered), max_points) if max_points is not None else len(ordered)
    if target == len(ordered):
        chosen = set(range(target))
    elif target:
        # Bounds are protected when the budget is at least four. Lower budgets
        # retain priorities in the documented order: max Tc, min Tc, first, last.
        anchors = [min(range(len(ordered)), key=lambda i: (-ordered[i].tc_kelvin, point_identity(ordered[i]))),
                   min(range(len(ordered)), key=lambda i: (ordered[i].tc_kelvin, point_identity(ordered[i]))),
                   0, len(ordered) - 1]
        chosen = set()
        for index in anchors:
            if len(chosen) < target:
                chosen.add(index)
        keys = sorted(strata, key=lambda key: (len(strata[key]), _rank(key)))
        queues = {key: sorted(strata[key], key=lambda i: (_rank(point_identity(ordered[i])), point_order(ordered[i]))) for key in keys}
        positions = dict.fromkeys(keys, 0)
        # One member of every not-yet-represented group, before adding density.
        represented = {_stratum(ordered[index]) for index in chosen}
        for key in keys:
            if len(chosen) == target:
                break
            if key not in represented:
                chosen.add(queues[key][0])
        while len(chosen) < target:
            for key in keys:
                queue = queues[key]
                while positions[key] < len(queue) and queue[positions[key]] in chosen:
                    positions[key] += 1
                if positions[key] < len(queue):
                    chosen.add(queue[positions[key]])
                    positions[key] += 1
                if len(chosen) == target:
                    break
    else:
        chosen = set()
    selected = [ordered[i] for i in sorted(chosen)]
    represented = {_stratum(p) for p in selected}
    rare = {key for key, group in strata.items() if len(group) <= 5}
    return selected, {
        "policy_version": SAMPLING_POLICY_VERSION,
        "method": "deterministic_stratified" if len(selected) < len(ordered) else "complete",
        "requested_max_points": max_points,
        "total_points": len(ordered), "selected_points": len(selected),
        "returned_points": len(selected), "is_sampled": len(selected) < len(ordered),
        "strata_by": ["family", "origin", "pressure_state", "decade"],
        "strata_total": len(strata), "strata_represented": len(represented),
        "strata_omitted": len(strata) - len(represented),
        "rare_group_max_size": 5, "rare_groups_omitted": len(rare - represented),
        "source_count": len({p.paper_id for p in ordered if p.paper_id}),
        "selected_source_count": len({p.paper_id for p in selected if p.paper_id}),
        "display_only": True,
        "interpretation": "Display selection protects bounds and small strata; not a representative population sample.",
    }


def summarize_timeline(points: list[TimelinePoint]):
    """Dataset extrema/counts before any display budget or page offset."""
    def counts(values):
        return dict(sorted(Counter(values).items()))

    maximum = max((p.tc_kelvin for p in points), default=None)
    maxima = sorted((p for p in points if p.tc_kelvin == maximum), key=point_order)
    family_maxima = {}
    for point in points:
        family = point.family or "unknown"
        family_maxima[family] = max(family_maxima.get(family, point.tc_kelvin), point.tc_kelvin)
    return {
        "scope": "full_filtered_unsampled", "total_points": len(points),
        "total_materials": len({p.material_id or (p.material, p.family) for p in points}),
        "source_count": len({p.paper_id for p in points if p.paper_id}),
        "source_count_basis": "distinct_bibliographic_ids_not_independent_works",
        "max_tc_kelvin": maximum,
        "min_tc_kelvin": min((p.tc_kelvin for p in points), default=None),
        "by_family": counts(p.family or "unknown" for p in points),
        "by_origin": counts(_origin(p) for p in points),
        "by_year_basis": counts(str(p.result_metadata.get("year_basis", "unknown")) for p in points),
        "by_pressure_state": counts(_pressure(p) for p in points),
        "family_max_tc_kelvin": dict(sorted(family_maxima.items())),
        "record_candidates": [p.model_dump(mode="json") for p in maxima[:20]],
        "record_candidate_count": len(maxima), "record_candidates_truncated": len(maxima) > 20,
        "label": "Highest reported Tc in this filtered dataset; not a world-record claim",
        "scientific_acceptance": False,
        "review_mode": "legacy_unreviewed", "reviewed_only_available": False,
        "coverage_scope": "currently indexed and eligible reported results; not a complete discovery history",
    }
