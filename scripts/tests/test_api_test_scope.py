"""Selection safety, failure receipts, exact SHA binding, and release latch tests."""

from datetime import datetime, timezone
import json
import subprocess
import urllib.request

import pytest
from scripts import api_test_scope as scope
from scripts import check_api_full_gate as gate

POLICY = json.loads((scope.ROOT / "scripts/api_test_policy.json").read_text())
INVENTORY = scope.modules(scope.ROOT)


@pytest.mark.parametrize(
    "changed",
    [
        ["unknown/new.py"],
        ["api/core/auth.py"],
        ["api/db/base.py"],
        ["api/models/new.py"],
        ["api/uv.lock"],
        ["api/main.py"],
        ["api/tests/conftest.py"],
        ["scripts/api_test_scope.py"],
        ["scripts/api_test_policy.json"],
        [".github/workflows/test.yml"],
        ["frontend/package.json"],
        ["api/tests/test_deleted.py"],
        ["frontend/lib/api.ts"],
    ],
)
def test_critical_unknown_and_deleted_paths_expand_to_full(changed):
    selected, reasons = scope.select(changed, INVENTORY, POLICY)
    assert selected == INVENTORY and reasons


def test_wiki_changes_still_test_auth_privacy_http_core():
    selected, reasons = scope.select(
        ["frontend/content/scwiki/articles/a1.md"], INVENTORY, POLICY
    )
    assert selected == sorted(POLICY["core"]) and not reasons
    assert "tests/test_auth.py" in selected
    assert "tests/test_scientific_query_http.py" in selected


def test_mapped_query_change_includes_consuming_http_and_evidence_modules():
    selected, reasons = scope.select(
        ["api/services/scientific_query.py"], INVENTORY, POLICY
    )
    assert not reasons and len(selected) < len(INVENTORY)
    for name in [
        "home_concept_search",
        "scientific_query_http",
        "answer_evidence",
        "scientific_mixed_ask",
        "index_search",
    ]:
        assert f"tests/test_{name}.py" in selected


def test_added_test_cannot_disappear_and_old_name_of_rename_expands():
    inventory = sorted(INVENTORY + ["tests/test_new.py"])
    selected, _ = scope.select(["api/tests/test_new.py"], inventory, POLICY)
    assert "tests/test_new.py" in selected
    selected, reasons = scope.select(
        ["api/tests/test_removed.py", "api/tests/test_new.py"], inventory, POLICY
    )
    assert selected == inventory and reasons


def test_explicit_full_and_stale_mapping():
    assert scope.select([], INVENTORY, POLICY, True)[0] == INVENTORY
    with pytest.raises(ValueError, match="missing_modules"):
        scope.select([], INVENTORY[1:], POLICY | {"core": INVENTORY[:8]})


def test_balanced_disjoint_batches_cover_each_selected_module_once():
    weights = json.loads((scope.ROOT / "scripts/api_test_timings.json").read_text())[
        "seconds"
    ]
    for selected in [INVENTORY, sorted(POLICY["core"])]:
        batches = scope.balanced(selected, weights)
        assert len(batches) == 8 and all(batches)
        assert sorted(m for g in batches for m in g) == selected
        assert batches == scope.balanced(selected, weights)
    totals = [
        sum(weights.get(m, 60) for m in g) for g in scope.balanced(INVENTORY, weights)
    ]
    jobs = [sum(totals[i : i + 2]) for i in range(0, 8, 2)]
    assert max(jobs) - min(jobs) < 180


def test_plan_rebuild_rejects_tampered_selection(monkeypatch):
    expected = {
        "base": "a" * 40,
        "force_full": False,
        "revision": "b" * 40,
        "selected": ["one"],
    }
    monkeypatch.setattr(scope, "plan", lambda *args: expected)
    scope.verify_plan(expected)
    for key, value in [("selected", []), ("revision", "c" * 40)]:
        with pytest.raises(ValueError, match="exact_checkout"):
            scope.verify_plan(expected | {key: value})


def sample_plan():
    return {
        "base": "a" * 40,
        "revision": "b" * 40,
        "mode": "full",
        "plan_sha256": "c" * 64,
        "selected": [f"tests/test_{i}.py" for i in range(8)],
        "inventory": [f"tests/test_{i}.py" for i in range(8)],
        "batches": [[f"tests/test_{i}.py"] for i in range(8)],
    }


def receipts(tmp_path, monkeypatch):
    value = sample_plan()
    monkeypatch.setattr(scope, "verify_plan", lambda *args: None)
    for i, group in enumerate(value["batches"]):
        folder = tmp_path / str(i)
        folder.mkdir()
        (folder / "junit.xml").write_text(
            f'<testsuites><testsuite><testcase classname="tests.test_{i}" name="works" time="0.1"/></testsuite></testsuites>'
        )
        report = {
            "batch": i,
            "revision": value["revision"],
            "plan_sha256": value["plan_sha256"],
            "status": "passed",
            "exit_code": 0,
            "modules": group,
            "duration_seconds": 1,
            "counts": scope.counts(folder / "junit.xml", group),
            "runtime": scope.runtime_inventory.capture(
                scope.ROOT / "api/uv.lock",
                scope.ROOT / "api/pyproject.toml",
                value["revision"],
            ),
        }
        (folder / "result.json").write_text(json.dumps(report))
    return value


@pytest.mark.parametrize(
    "corrupt",
    [
        "none",
        "missing",
        "duplicate",
        "sha",
        "hash",
        "failed",
        "cleanup",
        "xml",
        "modules",
        "runtime",
    ],
)
def test_aggregate_requires_actual_complete_matching_receipts(
    tmp_path, monkeypatch, corrupt
):
    value = receipts(tmp_path, monkeypatch)
    p = tmp_path / "0/result.json"
    report = json.loads(p.read_text())
    if corrupt == "missing":
        p.unlink()
    elif corrupt == "duplicate":
        report["batch"] = 1
    elif corrupt == "sha":
        report["revision"] = "d" * 40
    elif corrupt == "hash":
        report["plan_sha256"] = "d" * 64
    elif corrupt == "failed":
        report["status"] = "failed"
    elif corrupt == "cleanup":
        report["exit_code"] = 1
    elif corrupt == "modules":
        report["modules"] = []
    elif corrupt == "runtime":
        report["runtime"]["packages"]["fastapi"] = "999.0"
    elif corrupt == "xml":
        (tmp_path / "0/junit.xml").write_text("<testsuites/>")
    if corrupt != "missing":
        p.write_text(json.dumps(report))
    if corrupt == "none":
        result = scope.aggregate(value, tmp_path)
        assert result["full_module_coverage"] and result["counts"]["passed"] == 8
    else:
        with pytest.raises(ValueError):
            scope.aggregate(value, tmp_path)


def test_batch_always_uses_owned_runner_without_service_credentials(
    tmp_path, monkeypatch
):
    value = sample_plan()
    monkeypatch.setattr(scope, "verify_plan", lambda *args: None)
    monkeypatch.setattr(
        scope, "capture_provenance", lambda root: {"source_dirty": False}
    )
    monkeypatch.setattr(scope, "source_unchanged", lambda *args: None)
    monkeypatch.setenv("DATABASE_URL", "must-not-be-forwarded")
    monkeypatch.setenv("GH_TOKEN", "must-not-be-forwarded")
    output = tmp_path / "run"

    def run(command, **kwargs):
        assert command[1].endswith("scripts/run_disposable_tests.py")
        assert command[2:6] == ["--backend", "docker", "--suite", "api"]
        assert command[-1] == "tests/test_0.py"
        assert "DATABASE_URL" not in kwargs["env"] and "GH_TOKEN" not in kwargs["env"]
        (output / "junit.xml").write_text(
            '<testsuites><testsuite><testcase classname="tests.test_0" name="works"/></testsuite></testsuites>'
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(scope.subprocess, "run", run)
    assert scope.run_batch(value, 0, output, "docker") == 0
    assert json.loads((output / "result.json").read_text())["status"] == "passed"


def current(full=False):
    return {
        "head_sha": "b" * 40,
        "updated_at": "2026-10-19T10:00:00Z",
        "summary": {
            "mode": "full" if full else "targeted",
            "full_module_coverage": full,
        },
    }


def full_run(**changes):
    return {
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
        "updated_at": "2026-10-18T10:00:00Z",
        **changes,
    }


def decide(c, latest, ancestor=True):
    return gate.decide(
        c,
        latest,
        now=datetime(2026, 10, 19, 11, tzinfo=timezone.utc),
        is_ancestor=lambda *args: ancestor,
    )


def test_full_bootstrap_and_targeted_recent_baseline():
    assert decide(current(True), None) == "exact_target_full_coverage"
    assert decide(current(), full_run()) == "targeted_plus_recent_full_baseline"
    assert (
        decide(current(True), full_run(conclusion="failure"))
        == "exact_target_full_coverage"
    )


@pytest.mark.parametrize(
    "latest",
    [
        None,
        full_run(conclusion="failure"),
        full_run(conclusion="cancelled"),
        full_run(status="in_progress"),
        full_run(updated_at="2026-10-01T10:00:00Z"),
    ],
)
def test_no_targeted_release_after_failure_missing_or_stale_full(latest):
    with pytest.raises(ValueError):
        decide(current(), latest)


def test_even_full_target_cannot_hide_later_failure_or_wrong_ancestry():
    with pytest.raises(ValueError):
        decide(
            current(True),
            full_run(conclusion="failure", updated_at="2026-10-19T10:30:00Z"),
        )
    with pytest.raises(ValueError):
        decide(current(True), full_run(), False)


def test_artifact_redirect_never_leaks_github_token():
    request = urllib.request.Request(
        "https://api.github.com/repos/x", headers={"Authorization": "Bearer secret"}
    )
    redirected = gate.SafeRedirect().redirect_request(
        request, None, 302, "", {}, "https://example.blob.core.windows.net/artifact"
    )
    assert redirected.get_header("Authorization") is None
    with pytest.raises(ValueError):
        gate.SafeRedirect().redirect_request(
            request, None, 302, "", {}, "http://example.com"
        )


def test_independent_full_is_not_a_publication_trigger_and_gate_precedes_publish():
    full = (scope.ROOT / ".github/workflows/api-full.yml").read_text()
    release = (scope.ROOT / ".github/workflows/release-images.yml").read_text()
    assert (
        "force_full: true" in full
        and "workflow_dispatch:" in full
        and "schedule:" in full
    )
    assert "workflows: [Test]" in release
    assert release.index("scripts.check_api_full_gate") < release.index("\n  publish:")
    assert "needs: verify-security" in release


def test_real_git_diff_binds_commit_and_classifies_both_names_of_rename(tmp_path):
    root = tmp_path / "repo"
    (root / "api/tests").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "docs").mkdir()
    (root / "api/pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths=["tests"]\n'
    )
    for module in POLICY["core"]:
        (root / "api" / module).write_text("def test_contract(): pass\n")
    policy = POLICY | {"mappings": {}}
    (root / "scripts/api_test_policy.json").write_text(json.dumps(policy))
    (root / "scripts/api_test_timings.json").write_text(json.dumps({"seconds": {}}))
    (root / "unknown.py").write_text("# moved\n")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test fixture")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("mv", "unknown.py", "docs/moved.md")
    git("commit", "-qm", "rename")
    value = scope.plan(base, root=root)
    assert value["revision"] == git("rev-parse", "HEAD")
    assert value["base"] == base and value["mode"] == "full"
    assert value["changed"] == ["docs/moved.md", "unknown.py"]
    scope.verify_plan(value, root)
    with pytest.raises(ValueError):
        scope.plan("0" * 40, root=root)
    (root / "scripts/api_test_policy.json").write_text(
        json.dumps(policy | {"core_only_files": ["unknown.py"]})
    )
    with pytest.raises(ValueError, match="exact_checkout"):
        scope.verify_plan(value, root)


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "wrong_sha",
        "missing_summary",
        "old_attempt",
        "missing_runtime",
        "runtime_drift",
        "failed_counts",
    ],
)
def test_release_gate_reads_exact_attempt_and_compares_real_test_runtimes(
    monkeypatch, capsys, fault
):
    import io
    import sys
    import zipfile

    revision = "b" * 40
    runtime = scope.runtime_inventory.capture(
        scope.ROOT / "api/uv.lock", scope.ROOT / "api/pyproject.toml", revision
    )
    run = {
        "head_sha": revision,
        "path": ".github/workflows/test.yml",
        "event": "push",
        "head_branch": "main",
        "conclusion": "success",
        "status": "completed",
        "head_repository": {"full_name": gate.REPO},
        "run_attempt": 2,
        "updated_at": "2026-10-19T10:00:00Z",
    }
    summary = {
        "status": "passed",
        "revision": revision,
        "counts": {"failed": 0, "errors": 0},
        "batches": [{}] * 8,
        "runtime": runtime,
        "full_module_coverage": True,
        "mode": "full",
    }
    artifacts = [
        {"id": 1, "name": "api-validation-summary-attempt-2", "expired": False},
        {"id": 2, "name": "api-test-runtime-inventory-attempt-2", "expired": False},
    ]
    image_runtime = json.loads(json.dumps(runtime))
    if fault == "wrong_sha":
        summary["revision"] = "d" * 40
    elif fault == "missing_summary":
        artifacts = artifacts[1:]
    elif fault == "old_attempt":
        artifacts[0]["name"] = "api-validation-summary-attempt-1"
    elif fault == "missing_runtime":
        artifacts = artifacts[:1]
    elif fault == "runtime_drift":
        image_runtime["packages"]["fastapi"] = "999.0"
    elif fault == "failed_counts":
        summary["counts"]["failed"] = 1

    def archive(name, payload):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as z:
            z.writestr(name, json.dumps(payload))
        return output.getvalue()

    data = {
        "actions/runs/123": run,
        "actions/runs/123/artifacts?per_page=100": {"artifacts": artifacts},
        "actions/artifacts/1/zip": archive("api-summary.json", summary),
        "actions/artifacts/2/zip": archive("test-runtime.json", image_runtime),
        "actions/workflows/api-full.yml/runs?branch=main&per_page=100": {
            "workflow_runs": []
        },
    }
    monkeypatch.setattr(gate, "api", lambda path, binary=False: data[path])
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_api_full_gate", "--test-run", "123", "--revision", revision],
    )
    if fault == "none":
        gate.main()
        assert (
            json.loads(capsys.readouterr().out)["basis"] == "exact_target_full_coverage"
        )
    else:
        with pytest.raises(ValueError):
            gate.main()
