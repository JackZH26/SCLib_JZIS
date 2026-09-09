"""Closed negative-only exact-result review policy over the unchanged v2 task.

A captured acceptance cannot relax source timing, scientific semantics or
training/publication authority. V1/v2 task bytes and validators stay unchanged.
"""

from __future__ import annotations

import json

from models.ml_task import MlTaskError, require
from models.ml_task_v2 import default_task_v2, validate_task_v2
from services.research_release_manifest import canonical

VERSION = "ml-task/3.0.0"
REVIEW_POLICY = "negative_only/1.0.0"


def default_task_v3(*, cutoff="2026-01-01T00:00:00Z"):
    return {
        **default_task_v2(cutoff=cutoff),
        "version": VERSION,
        "task_id": "observed-tc-reviewed-nested-features-v3",
        "exact_result_review_policy": REVIEW_POLICY,
    }


def validate_task_v3(task):
    """Detach the task and reuse the unchanged strict v2 scientific policies."""
    try:
        require(
            type(task) is dict and set(task) == set(default_task_v3()), "invalid_v3_task_fields"
        )
        require(
            type(task["version"]) is str and task["version"] == VERSION,
            "unsupported_v3_task_version",
        )
        require(
            type(task["exact_result_review_policy"]) is str
            and task["exact_result_review_policy"] == REVIEW_POLICY,
            "unsupported_exact_result_review_policy",
        )
        detached = json.loads(canonical(task))
        projected = {
            key: value for key, value in detached.items() if key != "exact_result_review_policy"
        }
        projected["version"] = "ml-task/2.0.0"
        validate_task_v2(projected)
        return detached
    except (KeyError, TypeError, RecursionError, UnicodeError, ValueError) as exc:
        if isinstance(exc, MlTaskError):
            raise
        raise MlTaskError("invalid_v3_task") from None


__all__ = ["VERSION", "REVIEW_POLICY", "MlTaskError", "default_task_v3", "validate_task_v3"]
