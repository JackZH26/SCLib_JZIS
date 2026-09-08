"""Pure metrics over independently validated, frozen evaluation objects.

The caller verifies all references, hashes and declared review resolutions.
These calculations do not authenticate a reviewer, a scientific root, a cloud
run, or the completeness of a real-world relevance inventory. Missing counts
are always cases; denominator units are explicit and may instead be claims,
declared roots or citation occurrences. No model creates labels here.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from models.scientific_evaluation import (
    METRICS_VERSION,
    OutputLabels,
    ScientificEvaluationPackage,
)

_LABEL_METRICS = ("condition_match", "numerical_correct", "unit_correct", "refusal_correct")
_DECISIONS = ("accept", "reject", "needs_revision", "unreviewed", "disputed")
_CITATION = re.compile(r"\[(\d+)\]")
_GROUPED = re.compile(r"\[\d+(?:\s*[,;–-]\s*\d+)+\]")


def _ratio(unit):
    return {"numerator": 0, "denominator": 0, "scored_cases": 0, "missing": 0, "undetermined": 0,
            "not_applicable": 0, "value": None, "denominator_unit": unit,
            "missing_unit": "case", "not_applicable_unit": "case"}


def _finish(value):
    value["value"] = value["numerator"] / value["denominator"] if value["denominator"] else None
    return value


def _empty_metrics(k_values):
    result = {name: _ratio("case_label") for name in _LABEL_METRICS}
    result.update(claim_support_precision=_ratio("declared_answer_claim"),
                  expected_claim_coverage=_ratio("expected_claim"),
                  mechanical_citation_precision=_ratio("citation_occurrence"))
    for k in k_values:
        result[f"evidence_bundle_completion_at_{k}"] = _ratio("expected_claim")
        result[f"declared_root_recall_at_{k}"] = _ratio("declared_relevant_root")
    return result


def _case_metrics(case, observation, labels, decision, sources, k_values):
    metrics = _empty_metrics(k_values)
    completed = observation.status == "completed"
    accepted = decision == "accept"
    expected = case.expected.claims
    for k in k_values:
        bundle = metrics[f"evidence_bundle_completion_at_{k}"]
        roots = metrics[f"declared_root_recall_at_{k}"]
        if not accepted or not completed:
            bundle["missing"] = roots["missing"] = 1
            continue
        if not expected:
            bundle["not_applicable"] = roots["not_applicable"] = 1
            continue
        retrieved = set(observation.retrieved_source_ids[:k])
        bundle["denominator"] = len(expected)
        bundle["numerator"] = sum(any(set(alternative) <= retrieved for alternative in claim.evidence_alternatives)
                                  for claim in expected)
        relevant_ids = {identifier for claim in expected for alternative in claim.evidence_alternatives for identifier in alternative}
        if any(sources[identifier].root_id is None for identifier in relevant_ids):
            # The number of unknown roots itself is unknown. Missing is one
            # case, never an invented root based on Paper or Work identity.
            roots["missing"] = 1
            continue
        relevant_roots = {sources[identifier].root_id for identifier in relevant_ids}
        retrieved_roots = {sources[identifier].root_id for identifier in retrieved if sources[identifier].root_id is not None}
        roots["denominator"] = len(relevant_roots)
        roots["numerator"] = len(relevant_roots & retrieved_roots)

    for name in _LABEL_METRICS:
        value = metrics[name]
        if not accepted or not completed or labels is None:
            value["missing"] = 1
            continue
        judgment = getattr(labels, name)
        if judgment == "not_applicable":
            value["not_applicable"] = 1
        else:
            # Undetermined is deliberately retained in the denominator.
            value["denominator"] = 1
            value["numerator"] = int(judgment == "correct")
            value["undetermined"] = int(judgment == "undetermined")

    precision = metrics["claim_support_precision"]
    coverage = metrics["expected_claim_coverage"]
    if not accepted or not completed or labels is None or not labels.answer_claims_complete:
        precision["missing"] = coverage["missing"] = 1
    else:
        precision["denominator"] = len(labels.claims)
        precision["numerator"] = sum(claim.status == "supported" for claim in labels.claims)
        precision["undetermined"] = sum(claim.status == "undetermined" for claim in labels.claims)
        if not labels.claims:
            precision["not_applicable"] = 1
        expected_ids = {claim.id for claim in expected}
        supported = {identifier for claim in labels.claims if claim.status == "supported" for identifier in claim.expected_claim_ids}
        undetermined = {identifier for claim in labels.claims if claim.status == "undetermined" for identifier in claim.expected_claim_ids}
        coverage["denominator"] = len(expected_ids)
        coverage["numerator"] = len(expected_ids & supported)
        coverage["undetermined"] = len((expected_ids & undetermined) - supported)
        if not expected_ids:
            coverage["not_applicable"] = 1

    citation = metrics["mechanical_citation_precision"]
    grouped = 0
    if not completed:
        citation["missing"] = 1
    else:
        raw_indices = _CITATION.findall(observation.answer)
        grouped = len(_GROUPED.findall(observation.answer))
        # Selected source position is the sole citation map. Grouped syntax
        # is not silently expanded into valid single-index citations.
        citation["denominator"] = len(raw_indices) + grouped
        citation["numerator"] = sum(raw.isascii() and not raw.startswith("0") and len(raw) <= 2
                                    and 1 <= int(raw) <= len(observation.selected_source_ids) for raw in raw_indices)
        if not citation["denominator"]:
            citation["not_applicable"] = 1
    for value in metrics.values():
        value["scored_cases"] = int(value["denominator"] > 0)
    return {name: _finish(value) for name, value in metrics.items()}, grouped


def _aggregate(items, names):
    result = {}
    for name in names:
        value = _ratio(items[0][name]["denominator_unit"]) if items else names[name].copy()
        for field in ("numerator", "denominator", "scored_cases", "missing", "undetermined", "not_applicable"):
            value[field] = sum(item[name][field] for item in items)
        result[name] = _finish(value)
    return result


def _known_sum(observations, field):
    values = [getattr(item, field) for item in observations if getattr(item, field) is not None]
    try:
        known = math.fsum(values) if field == "cost_usd" and values else sum(values) if values else None
    except OverflowError:
        raise ValueError("Observed evaluation cost total exceeds finite numeric bounds") from None
    return {"known_total": known, "observed_count": len(values), "missing_count": len(observations) - len(values),
            "complete_total": known if len(values) == len(observations) and values else None}


def _operations(cases, observations, labels, decisions, execution):
    latencies = sorted(item.latency_ms for item in observations if item.latency_ms is not None)
    fallback = _ratio("observed_provider_fallback_flag")
    for item in observations:
        if type(item.provider_fallback) is bool:
            fallback["denominator"] += 1
            fallback["scored_cases"] += 1
            fallback["numerator"] += int(item.provider_fallback)
        else:
            fallback["missing"] += 1
    supported_answers = 0
    adjudication_complete = bool(cases)
    for case, observation in zip(cases, observations, strict=True):
        label = labels.get(case.id)
        if (decisions[case.id] != "accept" or observation.status != "completed"
                or label is None or not label.answer_claims_complete
                or any(claim.status == "undetermined" for claim in label.claims)):
            adjudication_complete = False
            continue
        if label.claims and all(claim.status == "supported" for claim in label.claims):
            supported_answers += 1
    cost = _known_sum(observations, "cost_usd")
    return {
        "measurement_scope": "synthetic_not_production" if execution == "synthetic" else "captured_observations_not_production_benchmark",
        "status_counts": {status: sum(item.status == status for item in observations) for status in ("completed", "unavailable", "not_run")},
        "latency_ms": {"observed_count": len(latencies), "missing_count": len(observations) - len(latencies),
                       "p95_nearest_rank": latencies[math.ceil(0.95 * len(latencies)) - 1] if latencies else None},
        "provider_fallback": _finish(fallback),
        "input_tokens": _known_sum(observations, "input_tokens"),
        "total_tokens": _known_sum(observations, "total_tokens"),
        "cost_usd": cost,
        "supported_answer_count": supported_answers,
        "support_adjudication_complete": adjudication_complete,
        "cost_per_supported_answer_usd": cost["complete_total"] / supported_answers
            if adjudication_complete and cost["complete_total"] is not None and supported_answers else None,
    }


def _strata(cases, decisions, observations=None):
    result = {dimension: {} for dimension in ("task", "language", "family", "tag")}
    for case in cases:
        values = {"task": [case.task], "language": [case.language], "family": case.families, "tag": case.tags}
        for dimension, keys in values.items():
            for key in keys:
                bucket = result[dimension].setdefault(key, {"planned_cases": 0, "accepted_cases": 0, "completed_cases": 0})
                bucket["planned_cases"] += 1
                bucket["accepted_cases"] += int(decisions[case.id] == "accept")
                bucket["completed_cases"] += int(observations is not None and observations[case.id].status == "completed")
    return result


def compute_metrics(package: ScientificEvaluationPackage, *, case_decisions: dict[str, str],
                    output_labels: dict[str, dict[str, OutputLabels | None]]) -> dict:
    """Compute explicit denominators; validation/authority remain caller-owned.

    Defensive inventory checks prevent silently intersecting cases even if this
    function is invoked directly. It does not replace the package verifier.
    """
    cases = package.cases
    case_ids = {case.id for case in cases}
    run_ids = {run.id for run in package.runs}
    if (len(case_ids) != len(cases) or set(case_decisions) != case_ids
            or any(value not in _DECISIONS for value in case_decisions.values())
            or len(run_ids) != len(package.runs) or set(output_labels) != run_ids):
        raise ValueError("Complete unique evaluation case and review inventories are required")
    if len(package.runs) != 2 or {run.arm for run in package.runs} != {"baseline", "candidate"}:
        raise ValueError("One baseline and one candidate are required")
    sources = {source.id: source for source in package.corpus.sources}
    if len(sources) != len(package.corpus.sources):
        raise ValueError("Captured source IDs must be unique")
    template = _empty_metrics(package.protocol.k_values)
    arms, case_values = {}, {}
    for run in package.runs:
        observations = {item.case_id: item for item in run.observations}
        if (len(observations) != len(run.observations) or set(observations) != case_ids
                or set(output_labels[run.id]) != case_ids):
            raise ValueError("Run and output-review inventories must equal all planned cases")
        case_values[run.id] = {}
        grouped_counts = {}
        for case in cases:
            metrics, grouped = _case_metrics(case, observations[case.id], output_labels[run.id][case.id],
                                             case_decisions[case.id], sources, package.protocol.k_values)
            case_values[run.id][case.id] = metrics
            grouped_counts[case.id] = grouped
        splits = {}
        for split in ("all", "development", "held_out"):
            subset = [case for case in cases if split == "all" or case.split == split]
            decisions = Counter(case_decisions[case.id] for case in subset)
            splits[split] = {
                "planned_cases": len(subset), "accepted_cases": decisions["accept"],
                "decision_counts": {decision: decisions[decision] for decision in _DECISIONS},
                "metrics": _aggregate([case_values[run.id][case.id] for case in subset], template),
                "unsupported_grouped_citation_count": sum(grouped_counts[case.id] for case in subset),
                "operations": _operations(subset, [observations[case.id] for case in subset],
                                           output_labels[run.id], case_decisions, run.execution),
                "strata": _strata(subset, case_decisions, observations),
            }
        arms[run.id] = {"arm": run.arm, "execution": run.execution, "all_planned_cases": len(cases), "splits": splits}

    baseline = next(run for run in package.runs if run.arm == "baseline")
    candidate = next(run for run in package.runs if run.arm == "candidate")
    paired = {name: {"improved": 0, "regressed": 0, "tied": 0, "unscored": 0, "planned_pairs": len(cases)} for name in template}
    paired_cases = []
    for case in cases:
        changes = {}
        for name in template:
            before = case_values[baseline.id][case.id][name]
            after = case_values[candidate.id][case.id][name]
            if before["value"] is None or after["value"] is None:
                outcome = "unscored"
            else:
                # Exact rational comparison, never epsilon-rounding a change.
                delta = after["numerator"] * before["denominator"] - before["numerator"] * after["denominator"]
                outcome = "improved" if delta > 0 else "regressed" if delta < 0 else "tied"
            paired[name][outcome] += 1
            changes[name] = outcome
        paired_cases.append({"case_id": case.id, "split": case.split, "metrics": changes})

    coverage = _strata(cases, case_decisions)
    held_out = _strata([case for case in cases if case.split == "held_out"], case_decisions)
    quotas = []
    for quota in package.protocol.strata:
        bucket = coverage[quota.dimension].get(quota.key, {})
        held = held_out[quota.dimension].get(quota.key, {})
        quotas.append({"dimension": quota.dimension, "key": quota.key, "min_n": quota.min_n,
                       "planned_cases": bucket.get("planned_cases", 0), "accepted_cases": bucket.get("accepted_cases", 0),
                       "held_out_planned_cases": held.get("planned_cases", 0), "held_out_accepted_cases": held.get("accepted_cases", 0),
                       "declared_quota_met": bucket.get("accepted_cases", 0) >= quota.min_n})
    return {"version": METRICS_VERSION, "scientific_acceptance": False, "reviewer_authority_authenticated": False,
            "source_roots_authenticated": False, "independent_support_established": False,
            "arms": arms, "paired": {"baseline_run_id": baseline.id, "candidate_run_id": candidate.id,
                                      "metrics": paired, "cases": paired_cases},
            "coverage": {"planned_cases": len(cases), "target_question_count": package.protocol.target_question_count,
                         "accepted_cases": sum(value == "accept" for value in case_decisions.values()),
                         "strata": coverage, "quotas": quotas,
                         "multi_label_strata_may_overlap": True}}
