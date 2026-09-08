"""Fit median imputation and population z-scores using training rows only.

This pure helper accepts no targets, labels, fitted-test statistics, or feature
selection feedback. It describes reproducible preprocessing, not ML readiness.
"""

from __future__ import annotations

import math
import re
from fractions import Fraction

VERSION = "ml-preprocessing/1.0.0"
CONFIG = "median_train+zscore_train"
MAX_ROWS = 100_000
MAX_FEATURES = 1024
MAX_CELLS = 2_000_000
_FEATURE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,119}\Z")


def _reject() -> None:
    raise ValueError("invalid_preprocessing_input")


def fit_transform(
    matrix: list[list[float | None]],
    splits: list[str],
    feature_names: list[str],
    config: str = CONFIG,
) -> dict:
    """Fit on train after train-median imputation, then transform every row.

    All-missing training columns are dropped even when validation/test values
    exist. Missingness retains the original column inventory. Constant training
    columns use scale 1. The empty retained inventory is explicit, not evidence
    that a downstream model can train. Reject non-finite arithmetic atomically.
    """
    if (
        type(config) is not str or config != CONFIG
        or type(matrix) is not list or not 1 <= len(matrix) <= MAX_ROWS
        or type(feature_names) is not list or not 1 <= len(feature_names) <= MAX_FEATURES
        or len(matrix) * len(feature_names) > MAX_CELLS
        or any(type(name) is not str or not _FEATURE_NAME.fullmatch(name) for name in feature_names)
        or len(set(feature_names)) != len(feature_names)
        or type(splits) is not list or len(splits) != len(matrix)
        or any(type(split) is not str or split not in {"train", "validation", "test"} for split in splits)
        or "train" not in splits
    ):
        _reject()
    numbers = []
    missingness = []
    for row in matrix:
        if type(row) is not list or len(row) != len(feature_names):
            _reject()
        converted = []
        for value in row:
            if value is None:
                converted.append(None)
                continue
            if type(value) not in (int, float):
                _reject()
            try:
                number = float(value)
            except (ValueError, OverflowError):
                _reject()
            if not math.isfinite(number):
                _reject()
            converted.append(number)
        numbers.append(converted)
        missingness.append([value is None for value in row])
    train_rows = [row for row, split in zip(numbers, splits) if split == "train"]
    statistics = []
    dropped = []
    indices = []
    try:
        for index, name in enumerate(feature_names):
            observed = [row[index] for row in train_rows if row[index] is not None]
            if not observed:
                dropped.append({"index": index, "name": name, "reason": "all_missing_in_train"})
                continue
            # An exact rational midpoint avoids finite float overflow and
            # subnormal underflow; convert only the bounded average to float.
            ordered = sorted(observed)
            middle = len(ordered) // 2
            center = (ordered[middle] if len(ordered) % 2
                      else float((Fraction(ordered[middle - 1]) + Fraction(ordered[middle])) / 2))
            fitted = [row[index] if row[index] is not None else center for row in train_rows]
            # Exact equal observations must stay constant even when dividing a
            # subnormal value by n would underflow during mean computation.
            is_constant = ordered[0] == ordered[-1]
            mean = fitted[0] if is_constant else math.fsum(value / len(fitted) for value in fitted)
            # Scaled sum of squares avoids squaring finite values into infinity.
            deviations = [value - mean for value in fitted]
            maximum = max(abs(value) for value in deviations)
            std = (maximum * math.sqrt(math.fsum((value / maximum) ** 2 for value in deviations)
                                      / len(fitted))) if maximum else 0.0
            scale = std if std else 1.0
            if (
                not all(math.isfinite(value) for value in (center, mean, std, scale))
                or scale <= 0 or (not is_constant and std == 0)
            ):
                raise ArithmeticError
            statistics.append({
                "index": index, "name": name, "observed_train_count": len(observed),
                "median": center, "mean": mean, "std": std, "scale": scale,
                "constant": std == 0.0,
            })
            indices.append(index)
        transformed = []
        for row in numbers:
            values = [
                ((row[item["index"]] if row[item["index"]] is not None else item["median"])
                 - item["mean"]) / item["scale"]
                for item in statistics
            ]
            if not all(math.isfinite(value) for value in values):
                raise ArithmeticError
            transformed.append(values)
    except (ArithmeticError, ValueError):
        raise ValueError("nonfinite_preprocessing_arithmetic") from None
    return {
        "version": VERSION,
        "parameters": {
            "config": CONFIG,
            "feature_names": list(feature_names),
            "selected_indices": indices,
            "selected_feature_names": [feature_names[index] for index in indices],
            "dropped_features": dropped,
            "train_row_count": len(train_rows),
            "statistics": statistics,
        },
        "transformed": transformed,
        "missingness": missingness,
        "missingness_scope": "original_feature_inventory",
    }
