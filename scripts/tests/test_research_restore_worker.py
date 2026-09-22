"""Source-only worker entrypoint checks; never creates database clients."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import research_restore_worker as worker


def test_import_requires_only_standard_library_and_cannot_import_conftest():
    process = subprocess.run([sys.executable, "-I", "-S", "-c", """
import importlib.util, sys
spec = importlib.util.spec_from_file_location('isolated_worker', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert not any(x in sys.modules for x in ('sqlalchemy','config','models','redis','google','pytest','conftest'))
""", str(ROOT / "scripts/research_restore_worker.py")], capture_output=True, text=True, timeout=10)
    assert process.returncode == 0, process.stderr


@pytest.mark.parametrize("args", [[], ["--stage", "seed"], ["--stage", "verify"], ["--dsn", "SECRET_DATABASE"], ["--help"]])
def test_missing_capability_refuses_before_any_app_or_client_import(args):
    script = """
import importlib.abc, sys
sys.path.insert(0, sys.argv[1])
class NoClients(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'config','sqlalchemy','redis','google','models','pytest'}:
            raise AssertionError('APP_IMPORTED_BEFORE_CAPABILITY')
sys.meta_path.insert(0, NoClients())
import research_restore_worker
raise SystemExit(research_restore_worker.main(sys.argv[2:]))
"""
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "DATABASE_URL": "SECRET_DATABASE", "REDIS_URL": "SECRET_REDIS"}
    process = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(ROOT / "scripts"), *args],
                             env=environment, capture_output=True, text=True, timeout=10)
    assert process.returncode == 2
    assert process.stdout == ""
    assert process.stderr == "Research restore worker refused: stage_failed\n"
    assert not any(value in process.stderr for value in ("SECRET", "Traceback", "APP_IMPORTED"))


@pytest.mark.parametrize("args", [[], ["--stage", "secret://bad"], ["--stage", "seed", "--dsn", "SECRET"],
    ["--stage", "verify", "--root", "/private/source"], ["--st", "seed"], ["--stage", "drop"]])
def test_cli_has_no_arbitrary_path_dsn_or_stage_escape(monkeypatch, capsys, args):
    monkeypatch.setattr(worker, "_runtime", lambda: SimpleNamespace(run_id="a" * 32))
    assert worker.main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Research restore worker refused: stage_failed\n"


@pytest.mark.parametrize("value", [None, "", "a" * 63, "A" * 64, "SECRET_TOKEN", "a" * 64 + "\n"])
def test_verify_requires_independent_exact_hash_before_reading_descriptor(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("SCLIB_RESTORE_EXPECTED_DESCRIPTOR_SHA256", raising=False)
    else:
        monkeypatch.setenv("SCLIB_RESTORE_EXPECTED_DESCRIPTOR_SHA256", value)
    # API imports are deliberately replaced with inert modules: this test
    # checks entrypoint order, not any DB check or restored-state assertion.
    monkeypatch.setitem(sys.modules, "sqlalchemy", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "sqlalchemy.ext.asyncio", SimpleNamespace(AsyncSession=object))
    monkeypatch.setitem(sys.modules, "services.research_freeze", SimpleNamespace(inspect_research_release=object))
    monkeypatch.setitem(sys.modules, "research_restore_contract", SimpleNamespace(
        capture_bundle=lambda *a, **k: pytest.fail("read before independent pin"),
        read_source_descriptor=lambda *a, **k: pytest.fail("read before independent pin")))
    capability = SimpleNamespace(manifest={"root": "/not-read"})
    with pytest.raises(worker.WorkerError):
        asyncio.run(worker._verify(capability))


def test_stage_checks_match_single_closed_report_contract():
    import research_restore_contract as contract
    assert worker.CHECKS == {key: list(value) for key, value in contract.CHECKS.items()}
    assert worker.VERSION == contract.STAGE_VERSION
    assert worker.DESCRIPTOR_VERSION == contract.DESCRIPTOR_VERSION
    assert worker.FIXTURE_VERSION == contract.FIXTURE_VERSION


def test_canonical_is_utf8_exact_and_forbids_nonfinite_values():
    assert worker._canonical({"β": "材料", "a": 0}) == '{"a":0,"β":"材料"}'.encode()
    assert json.loads(worker._canonical(worker.AUTHORITY)) == {key: False for key in worker.AUTHORITY}
    with pytest.raises(ValueError):
        worker._canonical({"value": float("nan")})


def test_worker_source_never_imports_pytest_or_conftest():
    import ast
    tree = ast.parse((ROOT / "scripts/research_restore_worker.py").read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not any(name.startswith(("pytest", "tests")) or "conftest" in name for name in imports)
