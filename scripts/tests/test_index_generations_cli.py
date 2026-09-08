"""Offline CLI boundaries; never resolve application settings or credentials."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

SPEC = importlib.util.spec_from_file_location("index_generations_cli", Path(__file__).resolve().parents[1] / "index_generations.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


@pytest.mark.parametrize("command", ["inspect", "publish", "observe"])
def test_defaults_never_apply_or_read_remote(command):
    identifier = str(uuid4())
    args = cli.parser().parse_args([command, "--generation-id", identifier])
    assert not getattr(args, "apply", False) and not getattr(args, "read_remote", False)
    assert cli.request_from_args(args) == {"command": command, "generation_id": identifier}


def test_cas_requires_explicit_predecessor_and_idempotency():
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["activate", "--generation-id", str(uuid4())])
    args = cli.parser().parse_args(["activate", "--generation-id", str(uuid4()), "--validation-id", str(uuid4()),
        "--expected-event-id", "none", "--idempotency-key", "test", "--action", "promote"])
    request = cli.request_from_args(args)
    assert request["expected_event_id"] is None and not args.apply


@pytest.mark.parametrize("raw", [b'[]', b'{"generation_id":"a","generation_id":"b"}',
    b'{"generation_id":NaN}', b'{"command":"publish"}', b'not-json'])
def test_private_file_is_closed_and_strict(tmp_path, raw):
    path = tmp_path / "private.json"
    path.write_bytes(raw)
    args = cli.parser().parse_args(["stage", "--input", str(path)])
    with pytest.raises(ValueError):
        cli.request_from_args(args)


def test_private_file_has_hard_read_bound(tmp_path, monkeypatch):
    path = tmp_path / "private.json"
    path.write_bytes(b" " * 101)
    monkeypatch.setattr(cli, "MAX_INPUT_BYTES", 100)
    with pytest.raises(ValueError, match="exceeds"):
        cli.request_from_args(cli.parser().parse_args(["stage", "--input", str(path)]))


def test_failure_output_never_prints_dsn_or_sql_values(monkeypatch, capsys):
    async def failed(*args):
        raise RuntimeError("postgresql://sensitive:password@host/paper private source text")
    monkeypatch.setattr(cli, "run", failed)
    assert cli.main(["inspect", "--generation-id", str(uuid4())]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "failed"
    assert "sensitive" not in output and "private source text" not in output


def test_target_database_must_be_explicit(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert cli.main(["inspect", "--generation-id", str(uuid4())]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_schema_admission_precedes_operator_session(monkeypatch, capsys):
    calls = []
    def check(connection):
        calls.append("schema_check")
        raise ValueError("Unsupported schema head")
    class Connection:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def run_sync(self, operation): return operation(self)
    class Engine:
        def connect(self): return Connection()
        async def dispose(self): calls.append("disposed")
    def forbidden(*args):
        raise AssertionError("Operator session must not open before schema admission")
    monkeypatch.setitem(sys.modules, "models.db", SimpleNamespace(get_engine=Engine, get_session_factory=forbidden))
    monkeypatch.setitem(sys.modules, "services.index_operations", SimpleNamespace(run_operation=forbidden))
    monkeypatch.setitem(sys.modules, "services.schema_lifecycle", SimpleNamespace(check_connection_schema=check))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused:unused@127.0.0.1:1/unused")
    monkeypatch.setattr(sys, "path", sys.path.copy())
    assert cli.main(["inspect", "--generation-id", str(uuid4())]) == 1
    assert calls == ["schema_check", "disposed"]
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
