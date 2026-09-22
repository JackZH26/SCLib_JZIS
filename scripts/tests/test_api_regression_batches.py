"""Offline coordinator tests; no API/client imports and no actual services."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.tests import run_api_regression as coordinator


def synthetic_root(tmp_path):
    root = tmp_path.resolve() / "repository"
    (root / "api/tests").mkdir(parents=True)
    (root / "api/pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    )
    for name in ("test_a.py", "test_b.py", "test_c.py", "test_d.py", "helper.py"):
        (root / "api/tests" / name).write_text(
            "# Synthetic planner fixture, not executed\n"
        )
    return root


def junit(path, modules, *, skipped=False, failure=False):
    cases = []
    for module in modules:
        prefix = Path(module).with_suffix("").as_posix().replace("/", ".")
        outcome = (
            '<failure message="synthetic" />'
            if failure
            else '<skipped message="explicit external input unavailable" />'
            if skipped
            else ""
        )
        cases.append(
            f'<testcase classname="{prefix}" name="test_synthetic">{outcome}</testcase>'
        )
    path.write_text(
        "<testsuites><testsuite>" + "".join(cases) + "</testsuite></testsuites>"
    )


def test_real_partition_covers_every_module_once_and_excludes_capacity():
    selected = coordinator.modules(coordinator.ROOT)
    groups = coordinator.partition(selected, 8)
    assert len(selected) >= 223 and len(groups) == 8
    assert sorted(path for group in groups for path in group) == selected
    assert all(
        path.startswith("tests/") and "tests_capacity" not in path for path in selected
    )


@pytest.mark.parametrize("batches", [0, 1, 17, True])
def test_invalid_batch_counts_cannot_select_an_easier_subset(batches):
    with pytest.raises(ValueError):
        coordinator.partition([f"tests/test_{i:02}.py" for i in range(20)], batches)


@pytest.mark.parametrize(
    "change", ["nested", "symlink", "discovery", "filter", "empty"]
)
def test_changed_layout_or_discovery_fails_before_services(tmp_path, change):
    root = synthetic_root(tmp_path)
    if change == "nested":
        (root / "api/tests/nested").mkdir()
    elif change == "symlink":
        (root / "api/tests/test_link.py").symlink_to(root / "api/tests/test_a.py")
    elif change in {"discovery", "filter"}:
        with (root / "api/pyproject.toml").open("a") as f:
            f.write(
                'python_files = ["only_this.py"]\n'
                if change == "discovery"
                else 'addopts = "-k selected"\n'
            )
    else:
        for path in (root / "api/tests").glob("test_*.py"):
            path.unlink()  # Only this test's newly created synthetic files.
    with pytest.raises(ValueError):
        coordinator.modules(root)


def test_added_module_is_assigned_without_updating_a_static_allowlist(tmp_path):
    root = synthetic_root(tmp_path)
    (root / "api/tests/additional_test.py").write_text("# synthetic")
    selected = coordinator.modules(root)
    assert "tests/additional_test.py" in selected
    assert (
        sorted(x for group in coordinator.partition(selected, 2) for x in group)
        == selected
    )


def test_data_fixture_directory_cannot_conceal_python_collection(tmp_path):
    root = synthetic_root(tmp_path)
    fixtures = root / "api/tests/fixtures"
    fixtures.mkdir()
    (fixtures / "sample.json").write_text("{}")
    assert len(coordinator.modules(root)) == 4
    (fixtures / "test_hidden.py").write_text("# synthetic")
    with pytest.raises(ValueError, match="nested_test_layout"):
        coordinator.modules(root)


@pytest.mark.parametrize(
    "kind", ["missing", "foreign", "duplicate", "doctype", "empty"]
)
def test_junit_cannot_claim_unreported_or_unrelated_coverage(tmp_path, kind):
    report = tmp_path / "result.xml"
    expected = ["tests/test_a.py", "tests/test_b.py"]
    junit(report, expected)
    if kind == "missing":
        junit(report, expected[:1])
    elif kind == "foreign":
        junit(report, [*expected, "tests/test_other.py"])
    elif kind == "duplicate":
        junit(report, [*expected, expected[0]])
    elif kind == "doctype":
        report.write_text("<!DOCTYPE testsuites><testsuites/>")
    else:
        report.write_text("<testsuites><testsuite/></testsuites>")
    with pytest.raises(ValueError):
        coordinator.counts(report, expected)


def test_skips_remain_visible_and_are_never_counted_as_passes(tmp_path):
    report = tmp_path / "result.xml"
    junit(report, ["tests/test_a.py"], skipped=True)
    assert coordinator.counts(report, ["tests/test_a.py"]) == {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 1,
        "test_cases": 1,
        "module_cases": {"tests/test_a.py": 1},
    }


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "failure",
        "test_failure",
        "interrupted",
        "false_success",
        "changed_source",
        "wrong_junit",
    ],
)
def test_execution_only_delegates_to_owned_runner_and_publishes_truthful_outcomes(
    tmp_path, monkeypatch, mode
):
    root = synthetic_root(tmp_path)
    output = tmp_path.resolve() / "evidence"
    monkeypatch.setattr(
        coordinator, "capture_provenance", lambda root: {"synthetic": True}
    )
    checks = []

    def check(before, after):
        checks.append(None)
        if mode == "changed_source" and len(checks) > 1:
            raise ValueError("synthetic source mutation")

    monkeypatch.setattr(coordinator, "source_unchanged", check)
    calls = []
    monkeypatch.setenv("DATABASE_URL", "private-do-not-inherit")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k must-not-filter")

    def run(command, **kwargs):
        assert command[1] == str(root / "scripts/run_disposable_tests.py")
        assert command[2:6] == ["--backend", "docker", "--suite", "api"]
        assert kwargs["cwd"] == root and kwargs["check"] is False
        assert (
            "DATABASE_URL" not in kwargs["env"]
            and "PYTEST_ADDOPTS" not in kwargs["env"]
        )
        assert "--maxfail" not in command and "-k" not in command
        calls.append(command)
        file = Path(
            next(
                arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")
            )
        )
        selected = [arg for arg in command if arg.startswith("tests/")]
        if mode != "interrupted":
            junit(
                file,
                selected[:-1] if mode == "wrong_junit" else selected,
                failure=mode in {"test_failure", "false_success"},
            )
        return SimpleNamespace(
            returncode=130
            if mode == "interrupted"
            else 1
            if mode in {"failure", "test_failure"}
            else 0
        )

    monkeypatch.setattr(coordinator.subprocess, "run", run)
    code = coordinator.execute(
        output=output,
        backend="docker",
        postgres_bin=None,
        redis_bin=None,
        batches=2,
        root=root,
    )
    result = json.loads((output / "result.json").read_text())
    assert (code == 0) is (mode == "success")
    assert result["full_module_coverage"] is (mode == "success")
    assert result["production_or_scientific_acceptance"] is False
    assert len(calls) == (2 if mode == "success" else 1)
    assert result["counts_scope"] == "complete_verified_junit_batches_only"
    if mode == "success":
        assert result["counts"]["passed"] == 4 and result["counts"]["skipped"] == 0
        assert (
            result["counted_batches"] == [1, 2] and result["unreported_batches"] == []
        )
    elif mode in {"test_failure", "false_success", "failure"}:
        assert result["counted_batches"] == [1] and result["unreported_batches"] == [2]
        assert result["counts"]["failed"] == (0 if mode == "failure" else 2)
        assert result["counts"]["passed"] == (2 if mode == "failure" else 0)
        assert result["batches"][0]["junit_status"] == "complete_junit_verified"
        assert result["status"] == "incomplete"
    elif mode == "interrupted":
        assert result["counted_batches"] == [] and result["unreported_batches"] == [
            1,
            2,
        ]
        assert result["batches"][0]["junit_status"] == "unavailable_or_incomplete"
        assert result["batches"][0]["runner_exit_code"] == 130


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_existing_output_is_preserved_before_any_service(tmp_path, monkeypatch, kind):
    root = synthetic_root(tmp_path)
    target = tmp_path.resolve() / "retained"
    target.write_text("preserve prior evidence")
    output = tmp_path.resolve() / "output"
    if kind == "directory":
        output.mkdir()
    elif kind == "file":
        output.write_text("preserve prior evidence")
    else:
        output.symlink_to(target)
    monkeypatch.setattr(coordinator, "capture_provenance", lambda root: {})
    monkeypatch.setattr(
        coordinator.subprocess, "run", lambda *a, **k: pytest.fail("service started")
    )
    with pytest.raises(FileExistsError):
        coordinator.execute(
            output=output,
            backend="docker",
            postgres_bin=None,
            redis_bin=None,
            batches=2,
            root=root,
        )
    assert target.read_text() == "preserve prior evidence"


def test_cli_does_not_accept_test_filters_or_service_urls(capsys):
    assert (
        coordinator.main(
            ["--backend", "docker", "--output", "/synthetic", "-k", "secret-selection"]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "secret-selection" not in captured.err and captured.out == ""


def test_ci_keeps_capacity_separate_and_requires_batch_evidence():
    workflow = (coordinator.ROOT / ".github/workflows/test.yml").read_text()
    api = workflow.split("\n  api-tests:", 1)[1].split("\n  migration-tests:", 1)[0]
    assert (
        "python -m scripts.tests.run_api_regression --backend docker --batches 8" in api
    )
    assert api.index("run_api_regression") < api.index(
        "--suite api -- -q tests_capacity"
    )
    assert "api-regression-attempt-${{ github.run_attempt }}" in api
    artifact = api.split("- name: Upload actual API module-batch evidence", 1)[1].split(
        "- name:", 1
    )[0]
    assert "if-no-files-found: error" in artifact
    assert "continue-on-error" not in api and "DATABASE_URL:" not in api


def test_ci_job_budget_includes_regression_and_remaining_verification():
    workflow = (coordinator.ROOT / ".github/workflows/test.yml").read_text()
    api = workflow.split("\n  api-tests:", 1)[1].split("\n  migration-tests:", 1)[0]
    assert "timeout-minutes: 180" in api.split("defaults:", 1)[0]
    regression = api.split(
        "- name: Run all API modules in separate owned-service batches", 1
    )[1].split("- name:", 1)[0]
    assert "timeout-minutes: 150" in regression
    assert "--batches 8" in regression
