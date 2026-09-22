"""Strict, bounded configuration for an internal observed-Tc compiler.

This is a supported task contract, not a universal superconductivity dataset
schema. Unsupported targets/feature budgets fail closed before compilation.
"""
from __future__ import annotations

import re

from services.research_release_manifest import canonical
from services.temporal_provenance import utc_datetime

VERSION = "ml-task/1.0.0"
HASH = re.compile(r"^[0-9a-f]{64}$")


class MlTaskError(ValueError):
    """Invalid task or unverifiable task dataset."""


def require(condition, message):
    if not condition:
        raise MlTaskError(message)


def default_task(*, cutoff="2026-01-01T00:00:00Z"):
    """Explicit draft defaults; no scientific/rights approval is implied."""
    return {
        "version": VERSION,
        "task_id": "observed-tc-composition-baseline-v1",
        "estimand": "observed_tc_point_given_reported_state",
        "target": "tc_kelvin",
        "knowledge_origin": "Observed",
        "tc_definition": "zero_resistance",
        "label_window_k": {"minimum": 0.0, "maximum": 1000.0},
        "measurement_window": {"require_reported_minimum_temperature": False,
                               "maximum_measurement_temperature": "not_in_current_schema"},
        "pressure": {"mode": "explicit_ambient", "minimum_gpa": 0.0, "maximum_gpa": 0.0},
        "magnetic_field": {"unknown": "allow_explicit_missing", "maximum_t": 1000.0},
        "censoring": "exclude_nonpoint_and_not_detected",
        "review_policy": "declared_approved_event_and_qc_not_authenticated",
        "feature_budget": "composition",
        "feature_input_policy": "audit_and_exclude_unsupported_bindings",
        "cutoff": cutoff,
        "temporal_mode": "public_knowledge",
        "preprocessing": "median_train+zscore_train",
        "split": {"mode": "grouped_interpolation", "seed": "ml06-v1",
                  "fractions_percent": [60, 20, 20],
                  "validation_families": [], "test_families": []},
        "grouping_links": [],
    }


def _object(value, fields, name):
    require(type(value) is dict and set(value) == set(fields), f"invalid {name} fields")


def _number(value, *, minimum=0, maximum=1e9):
    return type(value) in {int, float} and minimum <= value <= maximum


def validate_task(task):
    canonical(task)  # bounded JSON, finite numbers, no arbitrary Python objects
    _object(task, default_task(), "task")
    for key, value in default_task().items():
        if type(value) is str:
            require(type(task[key]) is str, f"invalid {key} type")
    require(task["version"] == VERSION, "unsupported task version")
    require(type(task["task_id"]) is str and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}", task["task_id"]),
            "invalid task id")
    fixed = default_task()
    for key in ("estimand", "target", "knowledge_origin", "censoring", "review_policy",
                "feature_input_policy", "preprocessing"):
        require(task[key] == fixed[key], f"unsupported {key}")
    require(task["tc_definition"] in {"onset", "zero_resistance", "midpoint", "diamagnetic", "heat_capacity"},
            "one explicit Tc criterion required")
    require(task["feature_budget"] in {"composition", "composition_conditions"}, "unsupported feature budget")
    require(type(task["cutoff"]) is str and utc_datetime(task["cutoff"]) is not None, "aware cutoff required")
    require(task["temporal_mode"] in {"public_knowledge", "operational_capture"}, "unsupported temporal mode")
    window = task["label_window_k"]
    _object(window, {"minimum", "maximum"}, "label window")
    require(_number(window["minimum"]) and _number(window["maximum"])
            and window["minimum"] < window["maximum"], "invalid label window")
    measurement = task["measurement_window"]
    _object(measurement, fixed["measurement_window"], "measurement window")
    require(type(measurement["require_reported_minimum_temperature"]) is bool
            and measurement["maximum_measurement_temperature"] == "not_in_current_schema",
            "unsupported measurement window")
    pressure = task["pressure"]
    _object(pressure, fixed["pressure"], "pressure")
    require(type(pressure["mode"]) is str and pressure["mode"] in {"explicit_ambient", "reported_range"}
            and _number(pressure["minimum_gpa"]) and _number(pressure["maximum_gpa"])
            and pressure["minimum_gpa"] <= pressure["maximum_gpa"], "invalid pressure policy")
    require(pressure["mode"] != "explicit_ambient" or pressure["minimum_gpa"] == pressure["maximum_gpa"] == 0,
            "ambient pressure bounds must be zero")
    field = task["magnetic_field"]
    _object(field, fixed["magnetic_field"], "magnetic field")
    require(type(field["unknown"]) is str and field["unknown"] in {"exclude", "allow_explicit_missing"} and _number(field["maximum_t"]),
            "invalid magnetic field policy")
    split = task["split"]
    _object(split, fixed["split"], "split")
    require(type(split["mode"]) is str and split["mode"] in {"grouped_interpolation", "chemical_system_extrapolation", "family_holdout"},
            "unsupported split mode")
    require(type(split["seed"]) is str and 0 < len(split["seed"]) <= 100, "invalid split seed")
    fractions = split["fractions_percent"]
    require(type(fractions) is list and len(fractions) == 3 and all(type(x) is int and 0 < x < 100 for x in fractions)
            and sum(fractions) == 100, "invalid split fractions")
    for key in ("validation_families", "test_families"):
        values = split[key]
        require(type(values) is list and len(values) <= 100
                and all(type(x) is str and x.strip() == x and 0 < len(x) <= 50 for x in values)
                and values == sorted(set(values)), "family sets must be sorted unique labels")
    require(not set(split["test_families"]) & set(split["validation_families"]), "overlapping held-out families")
    if split["mode"] == "family_holdout":
        require(split["test_families"] and split["validation_families"], "explicit held-out families required")
    else:
        require(not split["test_families"] and not split["validation_families"], "unused family holdouts forbidden")
    links = task["grouping_links"]
    require(type(links) is list and len(links) <= 500, "grouping link budget")
    seen = set()
    for link in links:
        _object(link, {"kind", "left_id", "right_id", "review_artifact_id"}, "grouping link")
        require(type(link["kind"]) is str and link["kind"] in {"sample_trajectory", "structure_near_duplicate"}, "unsupported grouping link")
        require(all(type(link[key]) is str and 0 < len(link[key]) <= 200
                    for key in ("left_id", "right_id", "review_artifact_id")), "invalid grouping references")
        require(link["left_id"] < link["right_id"], "grouping endpoints must be distinct and ordered")
        identity = (link["kind"], link["left_id"], link["right_id"])
        require(identity not in seen, "duplicate grouping link")
        seen.add(identity)
    return task
