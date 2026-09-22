"""Driver contracts; real clean-wheel execution is a separate explicit CI gate."""

from __future__ import annotations

import io
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.tests import run_installed_evidence_probe as driver


def identity(python, wheel, pin):
    return {
        "isolated": 1,
        "prefix": str(python.parent.parent.resolve()),
        "python": "synthetic identity, not actual runtime evidence",
        "direct_url": {
            "url": wheel.as_uri(),
            "archive_info": {"hashes": {"sha256": pin}},
        },
        "distributions": ["pip", "sclib-api"],
    }


@pytest.mark.parametrize(
    "change", ["prefix", "isolated", "url", "sha", "extra", "missing"]
)
def test_installed_identity_rejects_wrong_wheel_or_dependency_fallback(
    tmp_path, change
):
    python = tmp_path / "installed/bin/python"
    wheel = tmp_path / "api.whl"
    value = identity(python, wheel, "a" * 64)
    driver.check_identity(value, python, wheel, "a" * 64)
    if change in {"prefix", "isolated"}:
        value[change] = 0
    elif change == "url":
        value["direct_url"]["url"] = "file:///unrelated.whl"
    elif change == "sha":
        value["direct_url"]["archive_info"]["hashes"]["sha256"] = "b" * 64
    elif change == "extra":
        value["distributions"].append("sqlalchemy")
    else:
        value["distributions"].remove("sclib-api")
    with pytest.raises(ValueError, match="wheel_identity_mismatch"):
        driver.check_identity(value, python, wheel, "a" * 64)


def reply(expected):
    return {
        "scope": driver.NOTICE,
        "python": "synthetic stub, not actual execution evidence",
        "input_sha256": expected["input_sha256"],
        "proof": deepcopy(expected["canary_check"]),
        "implementation": deepcopy(expected["evidence_implementation"]),
        "actual_owned_child_count": 1,
    }


@pytest.mark.parametrize(
    "change", ["hash", "proof", "source", "children", "bool", "extra"]
)
def test_probe_must_match_actual_repository_replay_not_a_success_label(change):
    expected = driver.worker.checked(
        driver.worker.prepare(io.BytesIO(driver.frame(*driver.fixture(empty=True))))
    )
    value = reply(expected)
    driver.check_success(value, expected)
    if change == "hash":
        value["input_sha256"] = "d" * 64
    elif change == "proof":
        value["proof"]["canary_replay_verified"] = False
    elif change == "source":
        value["implementation"]["worker_sha256"] = "e" * 64
    elif change in {"children", "bool"}:
        value["actual_owned_child_count"] = 0 if change == "children" else True
    else:
        value["scientific_acceptance"] = True
    with pytest.raises(ValueError, match="source_replay_mismatch"):
        driver.check_success(value, expected)


def test_invocation_is_isolated_and_does_not_forward_environment(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setenv("DATABASE_URL", "MUST_NOT_REACH_CHILD")
    monkeypatch.setenv("PYTHONPATH", "MUST_NOT_REACH_CHILD")
    monkeypatch.setattr(driver.subprocess, "run", lambda *a, **k: seen.append((a, k)))
    python = tmp_path / "python"
    driver.invoke(python, [str(driver.PROBE)], tmp_path, b"synthetic")
    args, kwargs = seen[0]
    assert args == ([str(python), "-I", "-B", str(driver.PROBE)],)
    assert kwargs["env"] == {"LANG": "C.UTF-8", "PYTHONHASHSEED": "0"}
    assert kwargs["cwd"] == tmp_path and kwargs["timeout"] == 70
    assert kwargs["input"] == b"synthetic"


@pytest.mark.parametrize("case", ["exit", "stderr", "empty", "large"])
def test_failed_probe_output_is_not_reported_or_echoed(case):
    result = subprocess.CompletedProcess(
        [],
        1 if case == "exit" else 0,
        stdout=b""
        if case == "empty"
        else b"x" * (2**20 + 1)
        if case == "large"
        else b"{}",
        stderr=b"PRIVATE_SENTINEL" if case == "stderr" else b"",
    )
    with pytest.raises(ValueError, match="^installed_evidence_probe_failed$"):
        driver.parsed(result)


def test_driver_never_replaces_existing_report_or_follows_output_symlink(tmp_path):
    python = tmp_path / "python"
    python.write_text("Synthetic path check; never executed")
    python.chmod(0o700)
    wheel = tmp_path / "api.whl"
    wheel.write_bytes(b"Synthetic path check; never installed")
    output = tmp_path / "report.json"
    output.write_text("Preserve original")
    link = tmp_path / "link.json"
    link.symlink_to(output)
    for target in (output, link, Path("relative-output.json")):
        with pytest.raises(ValueError, match="explicit_new_paths_required"):
            driver.run(python, wheel, target)
    assert output.read_text() == "Preserve original"


def test_ci_runs_probe_after_wheel_install_and_requires_actual_report():
    workflow = (driver.ROOT / ".github/workflows/test.yml").read_text()
    api = workflow.split("\n  api-tests:", 1)[1].split("\n  migration-tests:", 1)[0]
    assert (
        api.index("pip install --no-index --no-deps")
        < api.index("python -m scripts.tests.run_installed_evidence_probe")
        < api.index("Verify all offline script contracts")
    )
    assert (
        "working-directory: .\n        run: |\n          api/.venv/bin/python -m" in api
    )
    assert "name: installed-evidence-replay-attempt-${{ github.run_attempt }}" in api
    upload = api.split("- name: Upload actual installed evidence replay report", 1)[1]
    assert "if-no-files-found: error" in upload.split("- name:", 1)[0]


def test_fixture_cases_retain_real_context_bytes_and_all_revisions():
    _, originals, contexts = driver.fixture(superseded=True)
    assert len(contexts) == 2
    rows = driver.worker.documents.review_records(originals["reviews"])
    assert len(rows) == 63 and rows[-1]["revision"] == 2
    value = json.loads(originals["canary"])
    assert value["accounting"]["scientific_acceptance"] is False
