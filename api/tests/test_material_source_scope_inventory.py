"""Prepared inventory parity, under the guarded disposable API runner."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from services import material_source_scope as policy
from services.material_visibility_adapter import MaterialReadContext
from tests.test_material_source_scope import material, record, scoped, statuses


def context(value):
    visibility, scope = scoped(value)
    assert scope is not None
    return MaterialReadContext(value, visibility, statuses(), scope)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("before,after", [(True, 1), (1, 1.0), (False, 0), (0.0, -0.0), (1, 2)])
def test_flat_inventory_preserves_typed_mutation_rejection(index, before, after):
    value = material()
    value["records"][index]["snapshot_scalar"] = before
    current = context(value)
    assert current.source_scope._flat_inventory is not None
    value["records"][index]["snapshot_scalar"] = after
    with pytest.raises(policy.SourceScopeError, match="source_scope_record_inventory_changed"):
        current.current_records()
    assert current.source_scope._flat_inventory is None


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_mutation_keeps_original_invalid_input_error(index, value):
    raw = material()
    current = context(raw)
    raw["records"][index]["snapshot_scalar"] = value
    with pytest.raises(policy.SourceScopeError, match="source_scope_input_invalid"):
        current.current_records()
    assert current.source_scope._flat_inventory is None


@pytest.mark.parametrize("index", [0, 1])
def test_replacing_actual_key_with_string_subclass_keeps_original_rejection(index):
    class Key(str):
        pass

    raw = material()
    current = context(raw)
    value = raw["records"][index].pop("tc_kelvin")
    raw["records"][index][Key("tc_kelvin")] = value
    with pytest.raises(policy.SourceScopeError, match="source_scope_input_invalid"):
        current.current_records()
    assert current.source_scope._flat_inventory is None


@pytest.mark.parametrize("index", [0, 1])
def test_nested_selected_or_excluded_inventory_uses_original_path(index):
    value = material()
    value["records"][index]["source_locator"] = {"page": 2}
    current = context(value)
    assert current.source_scope._flat_inventory is None
    first = current.current_records()
    if index == 0:
        first[0]["source_locator"]["page"] = 99
        assert value["records"][0]["source_locator"] == {"page": 2}
    value["records"][index]["source_locator"]["page"] = 3
    with pytest.raises(policy.SourceScopeError, match="source_scope_record_inventory_changed"):
        current.current_records()


def test_flat_copies_keep_occurrence_gaps_duplicates_key_order_and_isolation():
    repeated = record()
    value = material([record("held-paper"), repeated, dict(repeated)])
    before = deepcopy(value)
    current = context(value)
    assert current.source_scope.eligible_indices == (1, 2)
    first = current.current_records()
    assert first == [value["records"][1], value["records"][2]]
    assert first[0] is not first[1] and first[0] is not repeated
    first[0]["tc_kelvin"] = "900 K"
    assert value == before
    assert current.current_records()[0]["tc_kelvin"] == "39 K"
    # Canonical JSON ignores dict insertion order, while detached copies must
    # preserve the currently supplied order just as deepcopy does.
    value["records"][1] = dict(reversed(list(value["records"][1].items())))
    assert list(current.current_records()[0]) == list(value["records"][1])


@pytest.mark.parametrize("field,new", [
    ("eligible_indices", (1,)), ("record_sha256", ("a" * 64, "b" * 64)),
    ("fingerprint", "a" * 64), ("_seal", "a" * 64),
])
@pytest.mark.parametrize("replace_field", [False, True])
def test_prepared_inventory_never_bypasses_scope_field_or_seal_replacement(field, new, replace_field):
    raw = material()
    current = context(raw)
    scope = current.source_scope
    assert scope._flat_inventory is not None
    if replace_field:
        scope = replace(scope, **{field: new})
    else:
        object.__setattr__(scope, field, new)
    with pytest.raises(policy.SourceScopeError, match="source_scope_integrity_invalid"):
        scope.eligible_records(raw["records"])


@pytest.mark.parametrize("in_place", [False, True])
def test_replaced_snapshot_cannot_attest_a_changed_raw_inventory(in_place):
    raw = material()
    current = context(raw)
    scope = current.source_scope
    snapshot = scope._flat_inventory
    assert snapshot is not None
    changed = deepcopy(raw["records"])
    changed[1]["tc_kelvin"] = "40 K"
    rows = tuple(tuple(item.items()) for item in changed)
    if in_place:
        object.__setattr__(snapshot, "rows", rows)
    else:
        object.__setattr__(scope, "_flat_inventory", replace(snapshot, rows=rows))
    raw["records"] = changed
    with pytest.raises(policy.SourceScopeError, match="source_scope_record_inventory_changed"):
        current.current_records()
    assert scope._flat_inventory is None


@pytest.mark.parametrize("name,limit", [("MAX_BYTES", 1), ("MAX_NODES", 1), ("MAX_DEPTH", 0)])
def test_changed_budget_vector_runs_original_bounded_validation(monkeypatch, name, limit):
    raw = material()
    current = context(raw)
    assert current.source_scope._flat_inventory is not None
    monkeypatch.setattr(policy, name, limit)
    with pytest.raises(policy.SourceScopeError, match="source_scope_input_limit"):
        current.current_records()
    assert current.source_scope._flat_inventory is None


def test_changed_record_count_limit_preserves_already_authenticated_scope_behavior(monkeypatch):
    raw = material()
    current = context(raw)
    assert current.source_scope._flat_inventory is not None
    monkeypatch.setattr(policy, "MAX_RECORDS", 1)
    with pytest.raises(policy.SourceScopeError, match="source_scope_visibility_invalid"):
        current.current_records()
    # The original cached SourceScope checks this limit on field authentication,
    # rather than adding a new count refusal to an unchanged validated object.
    # The snapshot must miss; the original bounded inventory path decides.
    assert current.source_scope.eligible_records(raw["records"]) == [raw["records"][0]]
    assert current.source_scope._flat_inventory is None


@pytest.mark.parametrize("value", ["a" * 4097, 1 << 257, {"page": 2}, [1]])
def test_snapshot_admission_limits_leave_supported_wide_values_on_original_path(value):
    raw = material()
    raw["records"][1]["snapshot_value"] = value
    current = context(raw)
    assert current.source_scope._flat_inventory is None
    assert current.current_records() == [raw["records"][0]]


def test_invalid_mutation_is_never_captured_as_success(monkeypatch):
    raw = material()
    current = context(raw)
    captures = []
    original = policy._flat_inventory

    def capture(*args, **kwargs):
        captures.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(policy, "_flat_inventory", capture)
    raw["records"][1]["tc_kelvin"] = "40 K"
    with pytest.raises(policy.SourceScopeError, match="source_scope_record_inventory_changed"):
        current.current_records()
    assert captures == []


def test_repeated_current_records_reduce_only_inventory_encoding_and_record_deepcopy(monkeypatch):
    raw = material()
    current = context(raw)
    snapshot = current.source_scope._flat_inventory
    assert snapshot is not None
    counts = {"canonical": 0, "digest": 0, "record_deepcopy": 0}
    original_canonical, original_digest, original_copy = policy._canonical, policy._digest, policy.deepcopy

    def canonical(value):
        counts["canonical"] += 1
        return original_canonical(value)

    def digest(value):
        counts["digest"] += 1
        return original_digest(value)

    def copy(value):
        counts["record_deepcopy"] += int(type(value) is dict and "paper_id" in value)
        return original_copy(value)

    monkeypatch.setattr(policy, "_canonical", canonical)
    monkeypatch.setattr(policy, "_digest", digest)
    monkeypatch.setattr(policy, "deepcopy", copy)
    fast = [current.current_records() for _ in range(3)]
    assert counts == {"canonical": 0, "digest": 0, "record_deepcopy": 0}
    assert current.source_scope._flat_inventory is snapshot
    monkeypatch.setattr(policy, "_flat_inventory", lambda *args, **kwargs: None)
    object.__setattr__(current.source_scope, "_flat_inventory", None)
    assert [current.current_records() for _ in range(3)] == fast
    assert counts == {"canonical": 9, "digest": 6, "record_deepcopy": 3}


def test_v1_records_identity_and_mutability_remain_original():
    value = material()
    visibility, scope = scoped(value, {"active-paper": "published", "held-paper": "published"})
    assert scope is None
    current = MaterialReadContext(value, visibility, {}, scope)
    assert current.current_records() is value["records"]
    value["records"][0]["tc_kelvin"] = "40 K"
    assert current.current_records()[0]["tc_kelvin"] == "40 K"
