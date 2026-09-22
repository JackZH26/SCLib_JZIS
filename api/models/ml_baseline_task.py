"""Bounded baseline engineering configuration, never an ML-use authorization."""
from __future__ import annotations

import re

from services.ml_audited_dataset import canonical

VERSION = "ml-baseline-task/1.0.0"
MAX_ARMS = 12
MAX_FEATURES = 256
MAX_CANDIDATES = 16
HASH = re.compile(r"[0-9a-f]{64}\Z")
IDENTIFIER = re.compile(r"[a-zA-Z][a-zA-Z0-9_.:-]{0,119}\Z")
VIEWS = frozenset({"C@B", "C@P", "CP@P", "C@S", "CS@S", "C@PS", "CP@PS", "CS@PS", "CPS@PS"})
SCOPES = frozenset({"composition", "composition_conditions", "view_all"})
POLICIES = {
    "estimand": "observed_tc_point_given_reported_state",
    "selection_rule": "validation_mae_then_candidate_id",
    "refit_policy": "none_after_validation_selection",
    "validation_coverage_policy": "complete_required",
    "failed_candidate_policy": "retain_and_exclude_from_selection",
    "prediction_policy": "finite_unclipped_kelvin",
    "comparison_policy": "exact_shared_assignment_with_nested_coverage",
    "randomness": "none",
}


class MlBaselineTaskError(ValueError):
    """Static task error without private values."""


def require(condition, code="ml_baseline_task_invalid"):
    if not condition:
        raise MlBaselineTaskError(code)


def default_candidates():
    """Engineering examples, not a scientifically approved search space."""
    return [
        {"candidate_id": "family_median", "method": "family_median_train", "alpha": None},
        {"candidate_id": "global_median", "method": "median_train", "alpha": None},
        {"candidate_id": "ols", "method": "ols", "alpha": None},
        {"candidate_id": "ridge_1", "method": "ridge", "alpha": 1.0},
        {"candidate_id": "ridge_10", "method": "ridge", "alpha": 10.0},
    ]


def make_baseline_task(input_sha256, arms):
    task = {"version": VERSION, "task_id": "ml09-engineering-baselines",
            "input_sha256": input_sha256, **POLICIES, "arms": arms,
            "candidates": default_candidates()}
    return validate_baseline_task(task)


def validate_baseline_task(task):
    try:
        raw = canonical(task)
        require(len(raw) <= 256 * 1024, "ml_baseline_task_budget")
        require(type(task) is dict and set(task) == {
            "version", "task_id", "input_sha256", "arms", "candidates", *POLICIES})
        require(task["version"] == VERSION and type(task["task_id"]) is str
                and IDENTIFIER.fullmatch(task["task_id"]))
        require(type(task["input_sha256"]) is str and HASH.fullmatch(task["input_sha256"]))
        require(all(type(task[key]) is str and task[key] == value for key, value in POLICIES.items()))
        arms = task["arms"]
        require(type(arms) is list and 1 <= len(arms) <= MAX_ARMS)
        identifiers = []
        for arm in arms:
            require(type(arm) is dict and set(arm) == {"arm_id", "view", "feature_scope", "feature_names"})
            require(type(arm["arm_id"]) is str and IDENTIFIER.fullmatch(arm["arm_id"]))
            identifiers.append(arm["arm_id"])
            require(type(arm["view"]) is str and arm["view"] in VIEWS
                    and type(arm["feature_scope"]) is str and arm["feature_scope"] in SCOPES)
            names = arm["feature_names"]
            require(type(names) is list and 1 <= len(names) <= MAX_FEATURES
                    and all(type(name) is str and IDENTIFIER.fullmatch(name) for name in names)
                    and len(names) == len(set(names)))
        require(identifiers == sorted(set(identifiers)), "ml_baseline_arm_order")
        candidates = task["candidates"]
        require(type(candidates) is list and 1 <= len(candidates) <= MAX_CANDIDATES)
        identifiers = []
        for item in candidates:
            require(type(item) is dict and set(item) == {"candidate_id", "method", "alpha"})
            require(type(item["candidate_id"]) is str and IDENTIFIER.fullmatch(item["candidate_id"]))
            identifiers.append(item["candidate_id"])
            require(type(item["method"]) is str
                    and item["method"] in {"median_train", "family_median_train", "ridge", "ols"})
            require((type(item["alpha"]) in {int, float} and 0 < item["alpha"] <= 1e12)
                    if item["method"] == "ridge" else item["alpha"] is None)
        require(identifiers == sorted(set(identifiers)), "ml_baseline_candidate_order")
        return task
    except MlBaselineTaskError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise MlBaselineTaskError("ml_baseline_task_invalid") from None
