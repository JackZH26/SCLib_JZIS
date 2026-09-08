"""Offline CLI and task-policy adversaries; all artifacts are synthetic."""
from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from models.ml_task import MlTaskError, default_task, validate_task
from services.ml_dataset_builder import _claim_composition, _split, build_task_dataset
from services.research_release_manifest import canonical, digest

from scripts.ml_task_dataset import main, read_json, run, write_new_json
from scripts.tests.test_research_release_verifier import fixture, write_bundle


def test_default_policy_is_explicit_and_does_not_mutate():
    task = default_task()
    before = deepcopy(task)
    assert validate_task(task) == before
    task["split"]["fractions_percent"][0] = 1
    assert default_task() == before


@pytest.mark.parametrize("path", [
    ("version",), ("task_id",), ("estimand",), ("target",), ("knowledge_origin",),
    ("tc_definition",), ("censoring",), ("review_policy",), ("feature_budget",),
    ("feature_input_policy",), ("cutoff",), ("temporal_mode",), ("preprocessing",),
    ("pressure", "mode"), ("magnetic_field", "unknown"), ("split", "mode"), ("split", "seed"),
])
@pytest.mark.parametrize("bad", [None, True, 1, [], {}, "unsupported"])
def test_malformed_or_unsupported_scalar_tasks_fail_closed(path, bad):
    task = default_task()
    target = task
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad
    # task_id/seed are identifiers, not fixed enums.
    if bad == "unsupported" and path in {("task_id",), ("split", "seed")}:
        assert validate_task(task) == task
        return
    with pytest.raises(ValueError):
        validate_task(task)


@pytest.mark.parametrize("mutation", [
    {"extra": True}, {"label_window_k": {"minimum": True, "maximum": 100}},
    {"label_window_k": {"minimum": 10, "maximum": 1}},
    {"measurement_window": {}}, {"grouping_links": [None]},
    {"cutoff": "2020-01-01"}, {"cutoff": "2020-01-01T00:00:00"},
    {"feature_budget": "physics"}, {"knowledge_origin": "Computed"},
    {"grouping_links": [{"kind": [], "left_id": "a", "right_id": "b", "review_artifact_id": "c"}]},
])
def test_policy_not_silently_broadened(mutation):
    with pytest.raises(ValueError):
        validate_task({**default_task(), **mutation})


@pytest.mark.parametrize("raw", [
    {"formula": "MgB2", "raw_extraction": {"formula_raw": "La2-xSrxCuO4"}},
    {"formula": "MgB2", "formula_raw": "Nb"},
    {"formula": "MgB2", "raw_extraction": {"formula": "Pb"}},
    {"formula": "MgB2", "formula_raw": "Mg[10B]2"},
    {"formula": "MgB2", "formula_raw": 12}, {},
])
def test_conflicting_or_unresolved_source_formula_cannot_be_normalized_away(raw):
    assert _claim_composition(raw)["status"] == "unavailable"


def test_equivalent_raw_formulas_keep_original_source_hash():
    selected = _claim_composition({"formula_raw": "MgB2", "formula": "B2Mg"})
    assert selected["status"] == "computed"
    assert selected["formula_raw"] == "MgB2"


def test_split_is_deterministic_and_cannot_repair_family_overlap():
    task = default_task()
    first = _split(["a", "b", "c", "d", "e"], {}, task)
    assert first == _split(["e", "d", "b", "c", "a"], {}, task)
    assert set(first[0].values()) == {"train", "validation", "test"}
    assert _split(["a", "b"], {}, task)[0] == {}
    task["split"].update(mode="family_holdout", validation_families=["iron"], test_families=["cuprate"])
    validate_task(task)
    assignments, held = _split(["a", "b", "c"], {"a": {"cuprate", "iron"}, "b": {None}, "c": {"iron"}}, task)
    assert assignments == {"c": "validation"} and set(held) == {"a", "b"}


def test_extreme_valid_split_quotas_are_no_go_not_zero_train():
    task = default_task()
    task["split"]["fractions_percent"] = [1, 98, 1]
    validate_task(task)
    assert _split(["a", "b", "c"], {}, task)[0] == {}


def test_valid_capsule_is_not_a_valid_training_dataset(tmp_path):
    manifest, artifacts = fixture()
    task = default_task()
    bundle = build_task_dataset(manifest, artifact_bytes=artifacts,
        expected_manifest_sha256=digest(manifest), task=task, expected_task_sha256=digest(task))
    assert bundle["gate"]["status"] == "no_go"
    assert bundle["rows"] == [] and len(bundle["candidates"]) == 1
    assert not any(bundle["authority"].values())
    capsule = write_bundle(tmp_path.resolve(), manifest, artifacts)
    task_path = tmp_path.resolve() / "task.json"
    write_new_json(task_path, task)
    output = tmp_path.resolve() / "dataset.json"
    report = run(mode="build", manifest_path=capsule, expected_manifest_sha256=digest(manifest),
        task_path=task_path, expected_task_sha256=digest(task), output_path=output)
    assert report["technical_gate"] == "no_go" and report["output_written"] is False
    assert not output.exists()
    assert main(["build", "--manifest", str(capsule), "--manifest-sha256", digest(manifest),
                 "--task", str(task_path), "--task-sha256", digest(task), "--output", str(output)]) == 3


def test_atomic_write_never_replaces_and_uses_private_permissions(tmp_path):
    path = tmp_path.resolve() / "output.json"
    write_new_json(path, {"synthetic": 1})
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_new_json(path, {"synthetic": 2})
    assert path.read_bytes() == canonical({"synthetic": 1})
    assert [p.name for p in path.parent.iterdir()] == ["output.json"]


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory", "ancestor_symlink"])
def test_nonregular_aliased_paths_refused(tmp_path, kind):
    directory = tmp_path.resolve()
    real = directory / "real.json"
    real.write_bytes(canonical({"synthetic": True}))
    path = directory / "input.json"
    if kind == "symlink": path.symlink_to(real)
    elif kind == "hardlink": os.link(real, path)
    elif kind == "fifo": os.mkfifo(path)
    elif kind == "directory": path.mkdir()
    else:
        alias = directory / "alias"
        alias.symlink_to(directory, target_is_directory=True)
        path = alias / "real.json"
    with pytest.raises((OSError, ValueError)):
        read_json(path, digest({"synthetic": True}))


@pytest.mark.parametrize("payload", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b'{ "a":1 }', b'[]\n'])
def test_duplicate_nonfinite_noncanonical_json_refused(tmp_path, payload):
    import hashlib
    path = tmp_path.resolve() / "input.json"
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        read_json(path, hashlib.sha256(payload).hexdigest())


def test_bad_pin_error_redacts_paths_and_source(capsys):
    code = main(["build", "--manifest", "/private/secret/manifest.json", "--manifest-sha256", "bad",
                 "--task", "/secret.json", "--task-sha256", "bad", "--output", "/output.json"])
    assert code == 2
    output = capsys.readouterr()
    assert "secret" not in output.err and "invalid" in output.err


def test_absent_pins_and_relative_paths_refused(tmp_path):
    path = tmp_path.resolve() / "input.json"
    write_new_json(path, {})
    with pytest.raises(MlTaskError): read_json(path, None)
    with pytest.raises(ValueError): read_json(Path("input.json"), digest({}))
