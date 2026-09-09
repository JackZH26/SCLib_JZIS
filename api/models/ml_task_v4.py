"""Opt-in captured label-currentness policy over the unchanged v3 task.

Negative observations can exclude labels, never repair their frozen scientific
or temporal evidence. They are not live authority or permission to train.
"""
from __future__ import annotations

import json

from models.ml_task import MlTaskError, require
from models.ml_task_v3 import default_task_v3, validate_task_v3
from services.research_release_manifest import canonical

VERSION = "ml-task/4.0.0"
LABEL_CURRENTNESS_POLICY = "captured_negative_only/1.0.0"


def default_task_v4(*, cutoff="2026-01-01T00:00:00Z"):
    return {
        **default_task_v3(cutoff=cutoff),
        "version": VERSION,
        "task_id": "observed-tc-current-labels-v4",
        "label_currentness_policy": LABEL_CURRENTNESS_POLICY,
    }


def validate_task_v4(task):
    """Detach and validate all unchanged v3 scientific/feature policies."""
    try:
        require(type(task) is dict and set(task) == set(default_task_v4()), "invalid_v4_task_fields")
        require(type(task["version"]) is str and task["version"] == VERSION, "unsupported_v4_task_version")
        require(type(task["label_currentness_policy"]) is str
                and task["label_currentness_policy"] == LABEL_CURRENTNESS_POLICY,
                "unsupported_label_currentness_policy")
        detached = json.loads(canonical(task))
        projected = {key: value for key, value in detached.items() if key != "label_currentness_policy"}
        projected["version"] = "ml-task/3.0.0"
        validate_task_v3(projected)
        return detached
    except (KeyError, TypeError, RecursionError, UnicodeError, ValueError) as exc:
        if isinstance(exc, MlTaskError):
            raise
        raise MlTaskError("invalid_v4_task") from None


__all__ = ["VERSION", "LABEL_CURRENTNESS_POLICY", "MlTaskError", "default_task_v4", "validate_task_v4"]
