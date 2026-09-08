"""Independent compiler boundary regressions using disposable SQL evidence."""

import json
from dataclasses import replace

import pytest
from sqlalchemy.exc import IntegrityError

from models.db import Base
from models.ml_task import MlTaskError, default_task, validate_task
from tests.test_ml_task_dataset_sql import (
    compile_release,
    freeze_task_candidates,
    seed_task_candidates,
)
from tests.test_research_freeze import add
from tests.test_research_freeze import db_session as _serializable_db_session

db_session = _serializable_db_session


@pytest.mark.parametrize("path", [
    ("tc_definition",), ("feature_budget",), ("temporal_mode",),
    ("pressure", "mode"), ("magnetic_field", "unknown"), ("split", "mode"),
])
@pytest.mark.parametrize("bad", [[], {}, [True], {"secret": "not-to-be-printed"}])
def test_unhashable_enum_values_have_controlled_task_rejection(path, bad):
    task = default_task()
    container = task
    for key in path[:-1]:
        container = container[key]
    container[path[-1]] = bad
    with pytest.raises(MlTaskError):
        validate_task(task)


@pytest.mark.parametrize("bad", [[], {}])
def test_group_link_kind_has_controlled_task_rejection(bad):
    task = default_task()
    task["grouping_links"] = [{
        "kind": bad, "left_id": "a", "right_id": "b", "review_artifact_id": "review",
    }]
    with pytest.raises(MlTaskError):
        validate_task(task)


@pytest.mark.parametrize("path", [
    ("label_window_k", "minimum"), ("label_window_k", "maximum"),
    ("pressure", "minimum_gpa"), ("pressure", "maximum_gpa"),
    ("magnetic_field", "maximum_t"),
])
def test_task_boolean_never_becomes_numeric_condition(path):
    task = default_task()
    task[path[0]][path[1]] = True
    with pytest.raises(MlTaskError):
        validate_task(task)


async def test_excluded_event_only_bridge_still_unifies_surviving_family_groups(db_session):
    specs = [
        {"key": "bridge", "formula": "MgB2", "work_group": "left", "reviewed": False},
        {"key": "left", "formula": "FeSe", "work_group": "left", "reviewed": True},
        {"key": "right", "formula": "Nb", "reviewed": True},
        {"key": "train", "formula": "Pb", "reviewed": True},
    ]
    fixture = await seed_task_candidates(db_session, specs)
    candidates = fixture["candidates"]
    # The context link deliberately names an event, not one exact result.
    # It cannot confer feature/temporal acceptance, but remains a leakage edge.
    await add(db_session, "event_evidence", event_id=candidates["bridge"]["event"]["id"],
              link_type="context", input_event_id=candidates["right"]["event"]["id"])
    materials = Base.metadata.tables["materials"]
    for key, family in [("bridge", "family_a"), ("left", "family_a"),
                        ("right", "family_b"), ("train", "family_train")]:
        await db_session.execute(materials.update().where(
            materials.c.id == candidates[key]["material"]["id"],
        ).values(family=family))
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    task = default_task()
    task["split"].update(mode="family_holdout", validation_families=["family_a"],
                         test_families=["family_b"])
    bundle = compile_release(release, artifact_bytes, task)
    by_example = {row["example_id"]: row for row in bundle["candidates"]}
    bridge, left, right = [
        by_example[str(candidates[key]["example"]["id"])]
        for key in ("bridge", "left", "right")
    ]
    assert "event_only_dependency_unresolved" in bridge["reason_codes"]
    assert bridge["status"] == "excluded"
    assert bridge["group_id"] == left["group_id"] == right["group_id"]
    assert left["status"] == right["status"] == "excluded"
    assert left["reason_codes"] == right["reason_codes"] == [
        "family_holdout_component_conflict_or_unknown",
    ]
    assert bundle["gate"]["status"] == "no_go"
    assert all(value is False for value in bundle["authority"].values())


async def test_unknown_family_on_excluded_work_member_cannot_cross_holdout(db_session):
    fixture = await seed_task_candidates(db_session, [
        {"key": "excluded", "formula": "MgB2", "work_group": "joint", "reviewed": False},
        {"key": "validation", "formula": "FeSe", "work_group": "joint", "reviewed": True},
        {"key": "test", "formula": "Nb", "reviewed": True},
        {"key": "train", "formula": "Pb", "reviewed": True},
    ])
    materials = Base.metadata.tables["materials"]
    for key, family in [("validation", "family_a"), ("test", "family_b"), ("train", "family_train")]:
        await db_session.execute(materials.update().where(
            materials.c.id == fixture["candidates"][key]["material"]["id"],
        ).values(family=family))
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    task = default_task()
    task["split"].update(mode="family_holdout", validation_families=["family_a"],
                         test_families=["family_b"])
    bundle = compile_release(release, artifact_bytes, task)
    identifier = str(fixture["candidates"]["validation"]["example"]["id"])
    row = next(row for row in bundle["candidates"] if row["example_id"] == identifier)
    assert row["status"] == "excluded"
    assert row["reason_codes"] == ["family_holdout_component_conflict_or_unknown"]
    assert bundle["gate"]["status"] == "no_go"


@pytest.mark.parametrize("raw_overrides", [
    {"raw_extraction": {"formula_raw": "La2-xSrxCuO4"}},
    {"formula_raw": "MgB2", "raw_extraction": {"formula_raw": "Nb"}},
])
async def test_exact_source_review_does_not_erase_ambiguous_original_formula(db_session, raw_overrides):
    fixture = await seed_task_candidates(db_session, [
        {"key": "ambiguous", "formula": "MgB2", "reviewed": True, "raw_overrides": raw_overrides},
        {"key": "one", "formula": "Pb", "reviewed": True},
        {"key": "two", "formula": "Nb", "reviewed": True},
        {"key": "three", "formula": "Sn", "reviewed": True},
    ])
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    bundle = compile_release(release, artifact_bytes)
    identifier = str(fixture["candidates"]["ambiguous"]["example"]["id"])
    row = next(row for row in bundle["candidates"] if row["example_id"] == identifier)
    assert row["status"] == "excluded"
    assert identifier not in {row["example_id"] for row in bundle["rows"]}


@pytest.mark.parametrize("conditions,reason", [
    ({"magnetic_field_t": False}, "state_magnetic_field_invalid"),
    ([], "state_conditions_not_object"),
    (["magnetic_field_t"], "state_conditions_not_object"),
    ("magnetic_field_t", "state_conditions_not_object"),
    (False, "state_conditions_not_object"),
    (3, "state_conditions_not_object"),
])
async def test_malformed_declared_state_condition_is_not_numeric_agreement(db_session, conditions, reason):
    fixture = await seed_task_candidates(db_session, [
        {"key": "boolean", "formula": "MgB2", "reviewed": True},
        {"key": "one", "formula": "Pb", "reviewed": True},
        {"key": "two", "formula": "Nb", "reviewed": True},
        {"key": "three", "formula": "Sn", "reviewed": True},
    ])
    candidate = fixture["candidates"]["boolean"]
    states = Base.metadata.tables["material_states"]
    if type(conditions) is not dict:
        # Live SQL already has a shape constraint. Do not disable that gate to
        # fabricate an accepted SQL row; separately exercise the offline
        # consumer, whose generic frozen JSONB shape may contain arbitrary JSON.
        with pytest.raises(IntegrityError) as rejected:
            async with db_session.begin_nested():
                await db_session.execute(states.update().where(
                    states.c.id == candidate["state"]["id"],
                ).values(conditions=conditions))
        assert "ck_rv2_material_states_conditions" in str(rejected.value)
        release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
        from services.ml_dataset_builder import _label_reasons
        from services.ml_frozen_provenance import resolve_result_context
        from services.research_release_manifest import canonical

        index = {(row["table"], row["row_id"]): row for row in release["manifest"]["rows"]}
        node = resolve_result_context(
            index, ("material_claims", str(candidate["claim"]["id"])), artifact_bytes,
        ).root
        payload = json.loads(node._json)
        payload["state"]["conditions"] = conditions
        malformed = replace(node, _json=canonical(payload).decode())
        assert reason in _label_reasons(malformed, default_task(), index)
        return
    await db_session.execute(states.update().where(
        states.c.id == candidate["state"]["id"],
    ).values(conditions=conditions))
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    bundle = compile_release(release, artifact_bytes)
    identifier = str(candidate["example"]["id"])
    row = next(row for row in bundle["candidates"] if row["example_id"] == identifier)
    assert row["status"] == "excluded"
    assert reason in row["reason_codes"]
    assert identifier not in {row["example_id"] for row in bundle["rows"]}


@pytest.mark.parametrize("raw", [None, [], "MgB2", False, 3.0, [{"formula": "MgB2"}]])
def test_nonobject_source_records_cannot_supply_features_or_raise_uncontrolled_errors(raw):
    from services.ml_dataset_builder import _claim_composition

    descriptor = _claim_composition(raw)
    assert descriptor["status"] == "unavailable"
    assert descriptor["values"] == [None] * 121
    assert descriptor["reason_codes"] == ["source_record_not_object"]
