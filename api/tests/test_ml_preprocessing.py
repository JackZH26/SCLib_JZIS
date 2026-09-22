"""Train-only preprocessing regressions, run with disposable API safety."""

import copy
import json
import math
from decimal import Decimal

import pytest

from services.ml_preprocessing import fit_transform


def test_train_median_then_population_zscore_and_original_missingness():
    matrix = [[1, 10, None], [3, 10, None], [None, 10, None], [1000, None, 4], [None, 20, 5]]
    names = ["fraction", "constant", "test_only"]
    original = copy.deepcopy(matrix)
    result = fit_transform(matrix, ["train", "train", "train", "validation", "test"], names)
    assert matrix == original
    params = result["parameters"]
    assert params["selected_indices"] == [0, 1]
    assert params["selected_feature_names"] == ["fraction", "constant"]
    assert params["dropped_features"] == [{"index": 2, "name": "test_only", "reason": "all_missing_in_train"}]
    assert params["statistics"][0] == {
        "index": 0, "name": "fraction", "observed_train_count": 2, "median": 2,
        "mean": 2, "std": math.sqrt(2 / 3), "scale": math.sqrt(2 / 3), "constant": False,
    }
    assert params["statistics"][1]["scale"] == 1
    assert params["statistics"][1]["std"] == 0
    assert params["statistics"][1]["constant"] is True
    assert result["transformed"][2] == [0, 0]
    assert result["transformed"][4] == [0, 10]
    assert result["missingness"] == [[value is None for value in row] for row in matrix]
    assert result["missingness_scope"] == "original_feature_inventory"
    assert fit_transform(matrix, ["train", "train", "train", "validation", "test"], names) == result


def test_validation_and_test_extremes_never_change_fitted_parameters():
    splits = ["train", "validation", "train", "test"]
    baseline = fit_transform([[1, None], [2, 5], [3, None], [4, 8]], splits, ["a", "b"])
    changed = fit_transform([[1, None], [-1e100, None], [3, None], [1e100, 1e90]], splits, ["a", "b"])
    assert baseline["parameters"] == changed["parameters"]
    assert baseline["transformed"][0] == changed["transformed"][0]
    assert baseline["transformed"][2] == changed["transformed"][2]
    assert baseline["parameters"]["selected_indices"] == [0]


def test_all_missing_training_inventory_is_explicitly_empty_not_imputed_from_test():
    result = fit_transform([[None], [900]], ["train", "test"], ["only_test"])
    assert result["transformed"] == [[], []]
    assert result["parameters"]["selected_indices"] == []
    assert result["parameters"]["statistics"] == []
    assert len(result["parameters"]["dropped_features"]) == 1
    assert result["missingness"] == [[True], [False]]


def test_one_training_row_constant_and_finite_large_median():
    result = fit_transform([[7], [None], [9]], ["train", "test", "validation"], ["a"])
    assert result["transformed"] == [[0], [0], [2]]
    assert result["parameters"]["statistics"][0]["observed_train_count"] == 1
    large = fit_transform([[1e308], [1e308]], ["train", "train"], ["a"])
    assert large["transformed"] == [[0], [0]]
    assert large["parameters"]["statistics"][0]["median"] == 1e308
    json.dumps(large, allow_nan=False)


@pytest.mark.parametrize("value", [0.1, 1e308, 5e-324, -5e-324])
@pytest.mark.parametrize("count", [2, 3, 7])
def test_repeated_finite_values_are_constant_even_at_float_boundaries(value, count):
    result = fit_transform([[value]] * count, ["train"] * count, ["a"])
    statistics = result["parameters"]["statistics"][0]
    assert statistics["constant"] is True
    assert statistics["median"] == value
    assert statistics["mean"] == value
    assert statistics["std"] == 0
    assert statistics["scale"] == 1
    assert result["transformed"] == [[0]] * count


@pytest.mark.parametrize("bad", [True, False, float("nan"), float("inf"), -float("inf"), "3", Decimal("3"), 10**1000, [], {}])
def test_numbers_are_strict_finite_and_never_bool(bad):
    with pytest.raises(ValueError, match="^invalid_preprocessing_input$"):
        fit_transform([[bad]], ["train"], ["a"])


@pytest.mark.parametrize("matrix,splits,names,config", [
    ([], [], ["a"], "median_train+zscore_train"),
    ([[1]], ["test"], ["a"], "median_train+zscore_train"),
    ([[1]], ["Train"], ["a"], "median_train+zscore_train"),
    ([[1]], [True], ["a"], "median_train+zscore_train"),
    ([[1]], [], ["a"], "median_train+zscore_train"),
    ([[1], [1, 2]], ["train", "test"], ["a"], "median_train+zscore_train"),
    ([[1, 2]], ["train"], ["a", "a"], "median_train+zscore_train"),
    ([[1]], ["train"], [True], "median_train+zscore_train"),
    ([[1]], ["train"], [""], "median_train+zscore_train"),
    ([[1]], ["train"], ["a\n"], "median_train+zscore_train"),
    ([[1]], ["train"], ["Tc label"], "median_train+zscore_train"),
    ([[1]], ["train"], ["a" * 121], "median_train+zscore_train"),
    ([[1]], ["train"], ["a"], "mean_all+zscore_all"),
    ([[1]], ["train"], ["a"], True),
    ([[1]], ["train"], ["a"], None),
    (([1],), ["train"], ["a"], "median_train+zscore_train"),
    ([(1,)], ["train"], ["a"], "median_train+zscore_train"),
    ([[1]], ("train",), ["a"], "median_train+zscore_train"),
    ([[1]], ["train"], ("a",), "median_train+zscore_train"),
    ([[]], ["train"], [], "median_train+zscore_train"),
    ([[1] * 1025], ["train"], ["a" + str(i) for i in range(1025)], "median_train+zscore_train"),
])
def test_shapes_names_splits_and_configuration_are_strict(matrix, splits, names, config):
    with pytest.raises(ValueError, match="^invalid_preprocessing_input$"):
        fit_transform(matrix, splits, names, config)


def test_transform_overflow_is_rejected_instead_of_emitting_partial_nonfinite_rows():
    with pytest.raises(ValueError, match="^nonfinite_preprocessing_arithmetic$"):
        fit_transform([[1e308], [-1e308]], ["train", "test"], ["a"])


def test_no_target_argument_or_learned_feature_selection_interface():
    with pytest.raises(TypeError):
        fit_transform([[1]], ["train"], ["a"], labels=[39])


def test_bounded_total_cells_before_arithmetic(monkeypatch):
    from services import ml_preprocessing
    monkeypatch.setattr(ml_preprocessing, "MAX_CELLS", 1)
    with pytest.raises(ValueError, match="^invalid_preprocessing_input$"):
        fit_transform([[1], [2]], ["train", "test"], ["a"])
