"""Mocked parent/child orchestration only; never starts DB, Docker or providers.

Report assembly/publication is stubbed only in scenario() to isolate cleanup
ordering. The companion contract tests separately exercise real validators/IO.
"""
from __future__ import annotations

import builtins
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import index_migration_contract as contract
import run_index_migration_rehearsal as runner

from scripts.tests.test_index_migration_contract import migrate, provenance


def scenario(tmp_path, monkeypatch, failure=None):
    events, roots, instances = [], [], []
    destination = tmp_path.resolve() / "report.json"
    class Services:
        def __init__(self, root, backend, postgres_bin, redis_bin):
            if failure == "construct": raise RuntimeError("PRIVATE constructor")
            self.root, self.closed = root, False
            instances.append(self)
        def start(self):
            events.append("start")
            if failure == "start": raise RuntimeError("PRIVATE start")
            return {"owned_unit_environment": "yes"}
        def close(self):
            events.append("close")
            if failure == "cleanup": raise RuntimeError("PRIVATE cleanup")
            self.closed = True
    def new_root():
        path = tmp_path.resolve() / (runner.ROOT_PREFIX + "unit")
        path.mkdir(mode=0o700)
        roots.append(path)
        info = path.stat()
        return path, (info.st_dev, info.st_ino)
    def worker(stage, env, root):
        events.append(stage)
        assert env == {"owned_unit_environment": "yes"} and root.exists()
        if failure == stage: raise contract.IndexMigrationError("unit_stage_failure")
        if failure == "cancel" and stage == "measure": raise KeyboardInterrupt
        return {"unit_orchestration_only": True, "stage": stage}
    def capture(_repo):
        events.append("source")
        if events.count("source") == 2:
            assert all(item.closed for item in instances) and not any(path.exists() for path in roots)
        value = provenance()
        if failure == "source_changed" and events.count("source") == 2: value["head_revision"] = "f" * 40
        return value
    def assemble(**kwargs):
        events.append("assemble")
        assert kwargs["cleanup_verified"] is True and set(kwargs["stages"]) == {"migrate", "measure"}
        return {"unit_orchestration_only": True}
    def publish(self, value):
        events.append("publish")
        assert value == {"unit_orchestration_only": True}
        if failure == "publish": raise contract.IndexMigrationError("unit_publication_failure")
        self.recheck()
        destination.write_bytes(b"UNIT_ORCHESTRATION_ONLY_NOT_A_REPORT")
    monkeypatch.setattr(runner, "DisposableServices", Services)
    monkeypatch.setattr(runner, "_new_root", new_root)
    monkeypatch.setattr(runner, "_worker", worker)
    monkeypatch.setattr(runner, "_identity_probe", lambda *_args, **_kwargs: 160013)
    monkeypatch.setattr(runner, "capture_provenance", capture)
    monkeypatch.setattr(runner, "build_report", assemble)
    monkeypatch.setattr(runner.IndexMigrationDestination, "publish", publish)
    return SimpleNamespace(events=events, roots=roots, instances=instances, report=destination,
        args=SimpleNamespace(report=destination, backend="native", postgres_bin=None, redis_bin=None))


def test_mocked_parent_orders_cleanup_and_recheck_before_publication(tmp_path, monkeypatch):
    state = scenario(tmp_path, monkeypatch)
    assert runner._main(state.args) == 0
    assert state.events == ["source", "start", "migrate", "measure", "close", "source", "assemble", "publish"]
    assert state.report.read_bytes() == b"UNIT_ORCHESTRATION_ONLY_NOT_A_REPORT"


@pytest.mark.parametrize("failure", ["construct", "start", "migrate", "measure", "cleanup", "source_changed", "publish", "cancel"])
def test_failure_never_publishes_success_and_cleanup_owns_only_its_roots(tmp_path, monkeypatch, failure):
    state = scenario(tmp_path, monkeypatch, failure)
    with pytest.raises(KeyboardInterrupt if failure == "cancel" else (RuntimeError, contract.IndexMigrationError)):
        runner._main(state.args)
    assert not state.report.exists()
    assert all("close" in state.events for _ in state.instances)
    assert all(path.exists() == (failure == "cleanup") for path in state.roots)


def test_existing_report_prevents_source_capture_and_service_creation(tmp_path, monkeypatch):
    state = scenario(tmp_path, monkeypatch)
    state.report.write_bytes(b"ORIGINAL")
    with pytest.raises(runner.ReportError):
        runner._main(state.args)
    assert state.events == [] and state.roots == [] and state.report.read_bytes() == b"ORIGINAL"


@pytest.mark.parametrize("option", ["--database-url", "--redis-url", "--corpus", "--baseline", "--command", "--index", "--report-existing"])
def test_cli_has_no_existing_target_or_arbitrary_input_escape(tmp_path, monkeypatch, capsys, option):
    monkeypatch.setenv("DATABASE_URL", "postgresql://PRIVATE:credential@production/database")
    monkeypatch.setenv("REDIS_URL", "redis://PRIVATE:credential@production")
    monkeypatch.setattr(runner, "_main", lambda *_: pytest.fail("Unsafe arguments reached runtime"))
    assert runner.main(["--report", str(tmp_path / "report.json"), option, "PRIVATE"]) == 2
    output = capsys.readouterr()
    assert "PRIVATE" not in output.err and "usage:" not in output.err and "no success report" in output.err


def test_help_never_starts_a_client_and_does_not_require_report(monkeypatch, capsys):
    monkeypatch.setattr(runner, "_main", lambda *_: pytest.fail("Help starts no services"))
    with pytest.raises(SystemExit) as result:
        runner.main(["--help"])
    assert result.value.code == 0 and "--report" in capsys.readouterr().out


@pytest.mark.parametrize("error", [RuntimeError("PRIVATE runtime"), OSError("PRIVATE path"), KeyboardInterrupt()])
def test_main_sanitizes_failures_and_interruptions(tmp_path, monkeypatch, capsys, error):
    def reject(_args): raise error
    monkeypatch.setattr(runner, "_main", reject)
    assert runner.main(["--report", str(tmp_path / "report.json")]) == (130 if isinstance(error, KeyboardInterrupt) else 2)
    output = capsys.readouterr()
    assert "PRIVATE" not in output.err and "Traceback" not in output.err and "no success report" in output.err


@pytest.mark.parametrize("fault", ["exit", "timeout", "malformed", "cross_run", "missing", "valid"])
def test_worker_command_is_fixed_private_bounded_and_run_pinned(tmp_path, monkeypatch, fault):
    root, calls = tmp_path.resolve(), []
    monkeypatch.setattr(runner, "validate_test_environment", lambda env: SimpleNamespace(manifest={"root": str(root)}, run_id="1" * 32))
    monkeypatch.setattr(runner, "_identity_probe", lambda env: calls.append("identity"))
    def execute(argv, **kwargs):
        assert calls == ["identity"]
        calls.append("child")
        assert argv == [sys.executable, str(runner.REPO / "scripts/index_migration_worker.py"), "--stage", "migrate"]
        assert kwargs["stdin"] is subprocess.DEVNULL and kwargs["timeout"] == runner.STAGE_TIMEOUT
        assert kwargs["env"] == {"owned": "only"} and kwargs["cwd"] == runner.REPO / "api"
        kwargs["stdout"].write(b"PRIVATE CHILD OUTPUT")
        if fault == "timeout": raise subprocess.TimeoutExpired(argv, 1, output=b"PRIVATE timeout")
        if fault == "exit": return SimpleNamespace(returncode=1)
        if fault != "missing":
            value = migrate()
            if fault == "cross_run": value["run_id"] = "2" * 32
            payload = b"malformed PRIVATE" if fault == "malformed" else contract.canonical(value)
            path = root / "index-migration-migrate.json"
            path.write_bytes(payload)
            path.chmod(0o600)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", execute)
    if fault == "valid":
        assert runner._worker("migrate", {"owned": "only"}, root) == migrate()
        assert calls == ["identity", "child", "identity"]
    else:
        with pytest.raises((contract.IndexMigrationError, runner.ReportError)) as error:
            runner._worker("migrate", {"owned": "only"}, root)
        assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("fault", ["capability", "root", "identity", "stage"])
def test_invalid_worker_environment_precedes_child_and_private_files(tmp_path, monkeypatch, fault):
    def capability(_env):
        if fault == "capability": raise runner.UnsafeTestEnvironment("unit refusal")
        return SimpleNamespace(manifest={"root": str(tmp_path.resolve() / "other" if fault == "root" else tmp_path.resolve())}, run_id="1" * 32)
    def identity(_env):
        if fault == "identity": raise runner.UnsafeTestEnvironment("unit identity refusal")
        pytest.fail("Invalid scope must not reach database identity")
    monkeypatch.setattr(runner, "validate_test_environment", capability)
    monkeypatch.setattr(runner, "_identity_probe", identity)
    monkeypatch.setattr(runner.subprocess, "run", lambda *_a, **_k: pytest.fail("Unverified child launched"))
    with pytest.raises((contract.IndexMigrationError, runner.UnsafeTestEnvironment)):
        runner._worker("foreign" if fault == "stage" else "migrate", {}, tmp_path.resolve())
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("replacement", ["directory", "symlink"])
def test_cleanup_rejects_changed_owned_identity_without_deleting_foreign_files(tmp_path, replacement):
    root = tmp_path.resolve() / (runner.ROOT_PREFIX + "unit")
    root.mkdir(mode=0o700)
    info = root.stat()
    identity = info.st_dev, info.st_ino
    original = root.with_name("original")
    root.rename(original)
    foreign = root.with_name("foreign")
    foreign.mkdir()
    canary = foreign / "KEEP"
    canary.write_bytes(b"UNRELATED")
    root.symlink_to(foreign, target_is_directory=True) if replacement == "symlink" else root.mkdir()
    with pytest.raises(contract.IndexMigrationError):
        runner._remove_owned_root(root, identity)
    assert original.is_dir() and canary.read_bytes() == b"UNRELATED"


@pytest.mark.parametrize("kind", ["file", "symlink", "hardlink", "fifo"])
def test_private_worker_log_never_overwrites_or_follows_existing_leaf(tmp_path, kind):
    path = tmp_path.resolve() / "worker.log"
    retained = tmp_path / "retained"
    retained.write_bytes(b"PRIVATE RETAINED")
    if kind == "fifo": os.mkfifo(path)
    elif kind == "symlink": path.symlink_to(retained)
    elif kind == "hardlink": os.link(retained, path)
    else: path.write_bytes(b"PRIVATE RETAINED")
    with pytest.raises(OSError):
        runner._private_output(path)
    assert retained.read_bytes() == b"PRIVATE RETAINED"


def test_identity_gate_rejects_inherited_urls_before_any_database_client_import(monkeypatch):
    original_import, attempted = builtins.__import__, []
    def guarded_import(name, *args, **kwargs):
        if name == "sqlalchemy":
            attempted.append(name)
            pytest.fail("Unverified environment reached a database client")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(runner.UnsafeTestEnvironment):
        runner._identity_probe({"DATABASE_URL": "postgresql://PRIVATE@production/prod",
            "REDIS_URL": "redis://PRIVATE@production/0"})
    assert attempted == []


@pytest.mark.parametrize("fault", ["connect", "identity", "nonempty", "valid"])
def test_identity_probe_client_double_checks_empty_target_and_disposes_on_every_exit(monkeypatch, fault):
    """Connection doubles only: test admission order/options, never contact a database."""
    calls = []
    capability = SimpleNamespace(database_url="owned-capability-url")
    class Connection:
        def __enter__(self):
            calls.append("enter")
            return self
        def __exit__(self, *args): calls.append("exit")
        def execute(self, query):
            assert query == "SHOW server_version_num"
            return SimpleNamespace(scalar_one=lambda: "160013")
    class Engine:
        def connect(self):
            calls.append("connect")
            if fault == "connect": raise OSError("PRIVATE connection detail")
            return Connection()
        def dispose(self): calls.append("dispose")
    def validate(env):
        assert env == {"private_capability": "unit"}
        calls.append("capability")
        return capability
    def create_engine(url, **kwargs):
        assert calls == ["capability"] and url == capability.database_url
        assert kwargs == {"connect_args": {"connect_timeout": 5,
            "options": "-c statement_timeout=5000 -c TimeZone=UTC"}}
        calls.append("engine")
        return Engine()
    def verify(connection, selected):
        assert selected is capability and isinstance(connection, Connection)
        calls.append("identity")
        if fault == "identity": raise runner.UnsafeTestEnvironment("synthetic identity refusal")
    def inspect(connection):
        assert calls[-1] == "identity" and isinstance(connection, Connection)
        def tables(*, schema):
            assert schema == "public"
            calls.append("empty")
            return ["existing_table"] if fault == "nonempty" else []
        return SimpleNamespace(get_table_names=tables)
    monkeypatch.setattr(runner, "validate_test_environment", validate)
    monkeypatch.setattr(runner, "verify_postgres_identity", verify)
    monkeypatch.setitem(sys.modules, "sqlalchemy", SimpleNamespace(create_engine=create_engine, inspect=inspect, text=lambda item: item))
    if fault == "valid":
        assert runner._identity_probe({"private_capability": "unit"}, empty=True) == 160013
        assert calls == ["capability", "engine", "connect", "enter", "identity", "empty", "exit", "dispose"]
    else:
        with pytest.raises((OSError, runner.UnsafeTestEnvironment, contract.IndexMigrationError)):
            runner._identity_probe({"private_capability": "unit"}, empty=True)
    assert calls[-1] == "dispose"
