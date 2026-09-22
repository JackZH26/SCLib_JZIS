"""Shared deterministic preparation content; provenance remains a recorded claim."""
from __future__ import annotations

import itertools

from services.ml_audited_dataset import digest
from services.ml_dataset_builder import AUTHORITY

VERSION = "ml-baseline-preparation/1.0.0"
SCOPE = "private_offline_preparation_not_training_authorization"
SPLITS = ("train", "validation", "test")
TRAINING_BLOCKERS = (
    "authenticated_ml_use_grant_unavailable",
    "live_recursive_source_rights_not_checked",
    "real_reviewed_pilot_acceptance_not_checked",
)

def diagnostics(prepared):
    """Coverage only: no held-out targets, scores, tuning or power inference."""
    arms, populations, failures = [], {}, []
    for arm in prepared["arms"]:
        rows = arm["rows"]
        populations[arm["arm_id"]] = {row["example_id"] for row in rows}
        split_counts = []
        for split in SPLITS:
            selected = [row for row in rows if row["split"] == split]
            split_counts.append({"split": split, "row_count": len(selected),
                                 "captured_component_count": len({row["group_id"] for row in selected})})
        reasons = []
        if not arm["selected_feature_names"]:
            reasons.append("arm_no_training_features")
        for split in split_counts:
            if split["row_count"] == 0:
                reasons.append("arm_missing_" + split["split"] + "_rows")
        if reasons:
            failures.append({"arm_id": arm["arm_id"], "reason_codes": reasons})
        features = []
        for index, name in enumerate(arm["feature_names"]):
            counts = []
            for split in SPLITS:
                selected = [row for row in rows if row["split"] == split]
                missing = sum(row["missingness"][index] for row in selected)
                counts.append({"split": split, "row_count": len(selected),
                               "missing_count": missing, "present_count": len(selected) - missing})
            features.append({"name": name, "retained_by_train_preprocessing": name in arm["selected_feature_names"],
                             "by_split": counts})
        parameters = arm["preprocessing"]["parameters"]
        arms.append({"arm_id": arm["arm_id"], "view": arm["view"], "feature_scope": arm["feature_scope"],
                     "cohort_sha256": arm["cohort_sha256"], "row_count": len(rows),
                     "requested_feature_count": len(arm["feature_names"]),
                     "retained_feature_count": len(arm["selected_feature_names"]),
                     "train_row_count": parameters["train_row_count"],
                     "source_parameters_sha256": arm["preprocessing"]["source_parameters_sha256"],
                     "dropped_features": parameters["dropped_features"],
                     "by_split": split_counts, "features": features, "reason_codes": reasons})
    comparisons = []
    for left, right in itertools.combinations(arms, 2):
        a, b = populations[left["arm_id"]], populations[right["arm_id"]]
        relation = ("identical" if a == b else "left_subset" if a < b else "right_subset" if b < a
                    else "overlapping" if a & b else "disjoint")
        comparisons.append({"left_arm_id": left["arm_id"], "right_arm_id": right["arm_id"],
                            "population_relation": relation, "common_row_count": len(a & b),
                            "left_only_row_count": len(a - b), "right_only_row_count": len(b - a)})
    return {"gate": {"status": "no_go" if failures else "pass", "arm_failures": failures},
            "arms": arms, "population_comparisons": comparisons,
            "independent_support_count": None,
            "limits": ["Captured components are leakage groups, not independent experiments.",
                       "Feature presence is not scientific validity or source permission.",
                       "Nested cohorts must not be treated as same-case model comparisons.",
                       "Nonempty splits do not establish statistical sufficiency."]}


def receipt(prepared, config, pins, source):
    return {"version": VERSION, "scope": SCOPE, "input_pins": pins,
            "config": config, "prepared": prepared, "prepared_sha256": digest(prepared),
            "diagnostics": diagnostics(prepared), "implementation": source,
            "training_execution": "disabled", "training_blockers": list(TRAINING_BLOCKERS),
            "authority": dict(AUTHORITY)}
