"""Mocked orchestration only: never starts Docker, SQL or a native service."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import research_restore_contract as contract
import run_research_restore_rehearsal as runner

from scripts.tests.test_research_restore_contract import provenance, stage_fixture


def scenario(tmp_path, monkeypatch, *, failure=None):
    events, services, roots = [], [], []
    report_path = tmp_path.resolve() / "restore.json"

    class Services:
        def __init__(self, root, backend, postgres_bin, redis_bin):
            self.root, self.backend = root, backend
            self.label = "source" if "-source-" in root.name else "target"
            if failure == "construct:" + self.label:
                raise RuntimeError("PRIVATE constructor failure")
            self.run_id = "1" * 32 if self.label == "source" else "2" * 32
            self.closed = False
            services.append(self)
        def start(self):
            events.append("start:" + self.label)
            if failure == "start:" + self.label:
                raise contract.RestoreContractError("synthetic_start_failure")
            return {"synthetic_owned": self.label}
        def close(self):
            events.append("close:" + self.label)
            if failure == "cleanup" and self.label == "source":
                raise RuntimeError("PRIVATE cleanup details")
            self.closed = True

    def new_root(label):
        root = tmp_path.resolve() / ("sclib-tests-research-restore-" + label + "-fixture")
        root.mkdir(mode=0o700)
        roots.append(root)
        info = root.stat()
        return root, (info.st_dev, info.st_ino)

    def worker(stage, env, root):
        events.append(stage)
        if failure == stage:
            raise contract.RestoreContractError("synthetic_worker_failure")
        assert env["synthetic_owned"] == ("target" if stage == "verify" else "source")
        assert root.exists()
        return stage_fixture(stage)

    def dump(service, env, path):
        events.append("dump")
        if failure == "dump":
            raise contract.RestoreContractError("synthetic_dump_failure")
        assert service.label == env["synthetic_owned"] == "source"
        with runner._private_output(path) as handle:
            handle.write(b"synthetic-dump")
        return runner._dump_fingerprint(path)

    def transfer(source, target, **kwargs):
        events.append("copy")
        if failure == "copy":
            raise contract.RestoreContractError("synthetic_copy_failure")
        assert source != target and source.exists() and target.exists()
        assert kwargs["expected_descriptor_sha256"] == "d" * 64
        return {"descriptor_sha256": "d" * 64, "manifest_sha256": "e" * 64, "bundle_sha256": "f" * 64,
                "artifact_count": 5, "artifact_bytes": 3000}

    def restore(service, env, path, fingerprint):
        events.append("restore")
        if failure == "restore":
            raise contract.RestoreContractError("synthetic_restore_failure")
        assert service.label == env["synthetic_owned"] == "target"
        assert runner._dump_fingerprint(path) == fingerprint

    captures = []
    def capture(_repo):
        value = provenance()
        captures.append(value)
        events.append("provenance")
        if len(captures) > 1:
            assert all(service.closed for service in services)
            assert all(not root.exists() for root in roots)
            if failure == "source_changed":
                value["head_revision"] = "f" * 40
        return value

    monkeypatch.setattr(runner, "DisposableServices", Services)
    monkeypatch.setattr(runner, "_new_root", new_root)
    monkeypatch.setattr(runner, "_identity_probe", lambda env, **kwargs: 160013)
    monkeypatch.setattr(runner, "_worker", worker)
    monkeypatch.setattr(runner, "_dump", dump)
    monkeypatch.setattr(runner, "copy_recovery_inputs", transfer)
    monkeypatch.setattr(runner, "_restore", restore)
    monkeypatch.setattr(runner, "capture_provenance", capture)
    return SimpleNamespace(events=events, services=services, roots=roots, report=report_path,
        args=SimpleNamespace(report=report_path, backend="native", postgres_bin=None, redis_bin=None))


def test_orchestration_publishes_only_after_both_cleanups_and_source_recheck(tmp_path, monkeypatch):
    control = scenario(tmp_path, monkeypatch)
    assert runner._main(control.args) == 0
    assert control.events == ["provenance", "start:source", "start:target", "migrate", "seed", "dump", "copy",
        "restore", "verify", "source-check", "close:target", "close:source", "provenance"]
    report = contract.loads_report(control.report.read_bytes())
    assert report["cleanup_verified"] is True and report["production"] is False
    assert len(report["stages"]) == 4
    assert all(service.closed for service in control.services)
    assert not any(root.exists() for root in control.roots)


@pytest.mark.parametrize("failure", ["construct:source", "construct:target", "start:source", "start:target", "migrate", "seed", "dump", "copy",
    "restore", "verify", "source-check", "cleanup", "source_changed"])
def test_failed_stage_or_cleanup_never_publishes_success(tmp_path, monkeypatch, failure):
    control = scenario(tmp_path, monkeypatch, failure=failure)
    with pytest.raises((contract.RestoreContractError, RuntimeError)):
        runner._main(control.args)
    assert not control.report.exists()
    assert not list(control.report.parent.glob(".sclib-restore-*"))
    assert all("close:" + service.label in control.events for service in control.services)
    if failure != "cleanup":
        assert not any(root.exists() for root in control.roots)
    else:
        assert all(root.exists() for root in control.roots)


def test_report_collision_prevents_even_creating_services(tmp_path, monkeypatch):
    control = scenario(tmp_path, monkeypatch)
    control.report.write_bytes(b"ORIGINAL")
    with pytest.raises(contract.legacy.ReportError):
        runner._main(control.args)
    assert control.report.read_bytes() == b"ORIGINAL"
    assert control.events == [] and control.services == []


def test_inherited_dsns_and_commands_are_not_cli_inputs(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://PRIVATE:password@production/private")
    monkeypatch.setenv("REDIS_URL", "redis://PRIVATE:password@production")
    monkeypatch.setattr(sys, "argv", ["restore", "--report", str(tmp_path / "restore.json"),
                                      "--database-url", "PRIVATE"])
    assert runner.main() == 2
    output = capsys.readouterr()
    assert "PRIVATE" not in output.err and "usage:" not in output.err
    assert "no success report" in output.err
    assert not (tmp_path / "restore.json").exists()


def test_main_sanitizes_worker_and_cleanup_details(tmp_path, monkeypatch, capsys):
    def rejected(_args):
        raise RuntimeError("PRIVATE host /secret/path postgres://password")
    monkeypatch.setattr(runner, "_main", rejected)
    monkeypatch.setattr(sys, "argv", ["restore", "--report", str(tmp_path / "restore.json")])
    assert runner.main() == 2
    assert "PRIVATE" not in capsys.readouterr().err


@pytest.mark.parametrize("result", ["failed", "timeout", "malformed", "wrong_run", "foreign_run"])
def test_worker_process_bounded_and_no_raw_output_escape(tmp_path, monkeypatch, result):
    root = tmp_path.resolve()
    calls = []
    monkeypatch.setattr(runner, "validate_test_environment", lambda env: SimpleNamespace(
        manifest={"root": str(root)}, run_id="1" * 32))
    monkeypatch.setattr(runner, "_identity_probe", lambda env: calls.append("identity"))
    def run(argv, **kwargs):
        calls.append(argv)
        assert calls[0] == "identity"
        assert argv == [sys.executable, str(runner.REPO / "scripts/research_restore_worker.py"), "--stage", "seed"]
        assert kwargs["timeout"] == runner.STAGE_TIMEOUT and kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["env"] == {"owned": "only"}
        assert kwargs["stdout"].name != sys.stdout
        kwargs["stdout"].write(b"PRIVATE child exception")
        if result == "timeout":
            raise subprocess.TimeoutExpired(argv, 1, output=b"PRIVATE stdout")
        if result == "failed":
            return SimpleNamespace(returncode=1)
        value = stage_fixture("seed")
        if result == "malformed":
            value["checks"] = []
        elif result == "wrong_run":
            value["run_id"] = "not-a-run"
        else:
            value["run_id"] = "9" * 32
        contract.safe_write_new(root, "stage-seed.json", contract.canonical(value))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    with pytest.raises(contract.RestoreContractError) as error:
        runner._worker("seed", {"owned": "only"}, root)
    assert "PRIVATE" not in str(error.value)


def test_worker_capability_rejected_before_any_child_launch(tmp_path, monkeypatch):
    def reject(_env):
        raise runner.UnsafeTestEnvironment("synthetic refusal")
    monkeypatch.setattr(runner, "validate_test_environment", reject)
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: pytest.fail("Child launched without capability"))
    with pytest.raises(runner.UnsafeTestEnvironment):
        runner._worker("seed", {}, tmp_path.resolve())
    assert not list(tmp_path.iterdir())


def test_worker_root_must_match_exact_owned_capability_before_sql(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "validate_test_environment", lambda env: SimpleNamespace(
        manifest={"root": str(tmp_path.resolve() / "foreign")}, run_id="1" * 32))
    monkeypatch.setattr(runner, "_identity_probe", lambda *args: pytest.fail("Wrong root reached SQL"))
    with pytest.raises(contract.RestoreContractError, match="root_mismatch"):
        runner._worker("seed", {}, tmp_path.resolve())
    assert not list(tmp_path.iterdir())


def test_restore_reopened_same_size_replacement_rejected_before_pg_restore(tmp_path, monkeypatch):
    source = tmp_path.resolve() / "dump"
    with runner._private_output(source) as handle:
        handle.write(b"trusted-dump")
    pin = runner._dump_fingerprint(source)
    real_fingerprint = runner._dump_fingerprint
    calls = []
    def fingerprint(path):
        value = real_fingerprint(path)
        calls.append("fingerprint")
        if len(calls) == 1:
            path.rename(path.with_name("old-dump"))
            with runner._private_output(path) as handle:
                handle.write(b"corrupt-dump")
        return value
    monkeypatch.setattr(runner, "_identity_probe", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_database_command", lambda *args: (["synthetic-pg-restore"], {}))
    monkeypatch.setattr(runner, "_dump_fingerprint", fingerprint)
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: pytest.fail("Unpinned opened bytes reached pg_restore"))
    with pytest.raises(contract.RestoreContractError, match="dump_changed"):
        runner._restore(SimpleNamespace(root=tmp_path.resolve()), {}, source, pin)


@pytest.mark.parametrize("mode", ["missing", "symlink", "hardlink", "world_readable", "too_large"])
def test_dump_fingerprint_refuses_unsafe_existing_inputs(tmp_path, monkeypatch, mode):
    path = tmp_path.resolve() / "dump"
    with runner._private_output(path) as handle:
        handle.write(b"dump")
    if mode == "missing":
        path.unlink()
    elif mode in {"symlink", "hardlink"}:
        target = path.with_name("saved")
        path.rename(target)
        if mode == "symlink":
            path.symlink_to(target)
        else:
            os.link(target, path)
    elif mode == "world_readable":
        path.chmod(0o644)
    else:
        monkeypatch.setattr(runner, "MAX_DUMP_BYTES", 3)
    with pytest.raises(contract.RestoreContractError):
        runner._dump_fingerprint(path)


def test_fifo_dump_refused_without_blocking_before_file_type_check(tmp_path, monkeypatch):
    path = tmp_path.resolve() / "dump"
    os.mkfifo(path, 0o600)
    original = os.open
    def guarded_open(name, flags, *args, **kwargs):
        if Path(name) == path:
            assert flags & os.O_NONBLOCK, "FIFO may block before file-type validation"
        return original(name, flags, *args, **kwargs)
    monkeypatch.setattr(runner.os, "open", guarded_open)
    with pytest.raises(contract.RestoreContractError):
        runner._dump_fingerprint(path)


def test_cleanup_identity_swap_never_deletes_replacement_directory(tmp_path):
    root = tmp_path.resolve() / "sclib-tests-research-restore-source-synthetic"
    root.mkdir(mode=0o700)
    info = root.stat()
    identity = info.st_dev, info.st_ino
    root.rename(root.with_name("retained"))
    root.mkdir(mode=0o700)
    canary = root / "DO-NOT-DELETE"
    canary.write_bytes(b"original unrelated data")
    service = SimpleNamespace(root=root, close=lambda: None)
    with pytest.raises(contract.RestoreContractError):
        runner._cleanup([(service, identity)])
    assert canary.read_bytes() == b"original unrelated data"


def test_separate_ci_job_uses_owned_runner_and_success_only_metadata_upload():
    # Structural configuration evidence, not a claim that CI or Docker ran.
    workflow = (ROOT / ".github/workflows/restore-drill.yml").read_text(encoding="utf-8")
    job, legacy = workflow.split("  research-release:\n", 1)[1].split("\n  restore:\n", 1)
    assert "services:" not in job and "DATABASE_URL:" not in job and "REDIS_URL:" not in job
    assert "secrets." not in job and "GOOGLE_APPLICATION_CREDENTIALS" not in job
    assert 'python-version: "3.11"' in job and "uv==0.11.16" in job
    assert "uv sync --project api --locked --extra dev --no-editable --python 3.11" in job
    assert "persist-credentials: false" in job
    command = job.index("api/.venv/bin/python scripts/run_research_restore_rehearsal.py")
    assert "--backend docker" in job[command:] and "--report research-restore-evidence/research-restore-drill-report.json" in job[command:]
    upload = job.index("name: Upload successful synthetic recovery evidence")
    assert command < upload
    assert "if: always()" not in job and "continue-on-error:" not in job
    assert "if-no-files-found: error" in job[upload:]
    assert "path: research-restore-evidence/research-restore-drill-report.json" in job[upload:]
    assert "${{ github.run_id }}-${{ github.run_attempt }}" in job[upload:]
    # Keep the old generic operational drill unchanged in this additive batch.
    assert hashlib.sha256(("  restore:\n" + legacy).encode()).hexdigest() == "5144e9853d843b3a64cd5c1819000a0f2cf1b3fd81b46806eda26394b06847c4"
