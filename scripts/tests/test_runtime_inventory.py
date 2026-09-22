"""Runtime comparison and CI lock-consumption checks; no services required."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from runtime_inventory import SCHEMA, capture, compare, loads, normalize


class RuntimeInventoryTests(unittest.TestCase):
    def setUp(self):
        self.runtime = {"schema": SCHEMA, "lock_sha256": "a" * 64, "python_minor": "3.11",
                        "python_version": "3.11.14", "implementation": "CPython",
                        "system": "Linux", "machine": "x86_64", "source_revision": "b" * 40,
                        "pyproject_sha256": "c" * 64, "collector_sha256": "d" * 64,
                        "project_name": "sclib-api", "project_version": "0.1.0",
                        "packages": {"sclib-api": "0.1.0", "sqlalchemy": "2.0.49"}}
        self.tests = copy.deepcopy(self.runtime)
        self.tests["packages"].update({"pytest": "9.0.2", "pluggy": "1.6.0"})

    def test_documented_dev_only_packages_are_allowed(self):
        self.assertEqual(compare(self.runtime, self.tests), [])
        self.assertEqual(normalize("SCLib_API"), "sclib-api")

    def test_runtime_missing_or_changed_package_fails(self):
        del self.tests["packages"]["sqlalchemy"]
        self.assertIn("runtime package mismatch: sqlalchemy", compare(self.runtime, self.tests))
        self.tests["packages"]["sqlalchemy"] = "2.0.1"
        self.assertIn("runtime package mismatch: sqlalchemy", compare(self.runtime, self.tests))

    def test_different_lock_python_and_unexplained_extras_fail(self):
        self.tests.update(lock_sha256="b" * 64, python_minor="3.12", python_version="3.12.14")
        self.tests["packages"]["unreviewed-package"] = "1.0"
        failures = compare(self.runtime, self.tests)
        self.assertIn("lock mismatch", failures)
        self.assertIn("Python minor mismatch", failures)
        self.assertTrue(any("unreviewed-package" in reason for reason in failures))

    def test_missing_malformed_v1_empty_or_duplicate_inputs_fail_closed(self):
        for value in (None, {}, [], {**self.runtime, "schema": "sclib-runtime-inventory/v1"},
                      {**self.runtime, "packages": {}}, {**self.runtime, "source_revision": "dev"},
                      {**self.runtime, "lock_sha256": True}):
            with self.subTest(value=value):
                self.assertEqual(compare(value, self.tests), ["invalid runtime or test inventory"])
        with self.assertRaises(ValueError):
            loads('{"schema":"first","schema":"second"}')

    def test_every_provenance_and_platform_axis_is_compared(self):
        for field, changed, reason in (
            ("pyproject_sha256", "0" * 64, "pyproject"),
            ("collector_sha256", "0" * 64, "collector"),
            ("source_revision", "0" * 40, "source revision"),
            ("implementation", "PyPy", "Python implementation"),
            ("system", "Darwin", "system"), ("machine", "arm64", "architecture"),
        ):
            altered = {**self.tests, field: changed}
            self.assertIn(f"{reason} mismatch", compare(self.runtime, altered))

    def test_allowance_never_waives_runtime_package_version_mismatch(self):
        self.runtime["packages"]["pytest"] = "8.0"
        self.assertIn("runtime package mismatch: pytest", compare(self.runtime, self.tests))

    def test_capture_binds_real_bytes_and_checks_installed_lock_membership(self):
        with tempfile.TemporaryDirectory() as directory:
            lock, project = Path(directory) / "uv.lock", Path(directory) / "pyproject.toml"
            lock.write_text('[[package]]\nname="sclib-api"\nversion="0.1.0"\n')
            project.write_text('[project]\nname="sclib-api"\nversion="0.1.0"\n')
            distribution = SimpleNamespace(metadata={"Name": "sclib_api"}, version="0.1.0")
            with patch("runtime_inventory.importlib.metadata.distributions", return_value=[distribution]):
                result = capture(lock, project, "b" * 40)
            self.assertEqual(result["packages"], {"sclib-api": "0.1.0"})
            self.assertEqual(loads(json.dumps(result)), result)
            with patch("runtime_inventory.importlib.metadata.distributions", return_value=[distribution, distribution]), self.assertRaises(ValueError):
                capture(lock, project, "b" * 40)
            distribution.version = "99.0"
            with patch("runtime_inventory.importlib.metadata.distributions", return_value=[distribution]), self.assertRaises(ValueError):
                capture(lock, project, "b" * 40)

    def test_python_jobs_use_pinned_uv_and_locked_dev_extra(self):
        workflow = (ROOT / ".github/workflows/test.yml").read_text()
        for name, following in (("api-tests", "migration-tests"),
                                ("migration-tests", "ingestion-tests"),
                                ("ingestion-tests", "frontend-build")):
            block = workflow.split(f"\n  {name}:", 1)[1].split(f"\n  {following}:", 1)[0]
            self.assertIn("uv==0.11.16", block)
            self.assertIn("uv sync --locked --extra dev --python 3.11", block)
            self.assertIn("runtime_inventory.py --lock uv.lock", block)
            self.assertIn("--pyproject pyproject.toml --revision", block)
            self.assertIn("run_runtime_parity.py --project", block)
            self.assertIn("if-no-files-found: error", block)
            self.assertNotIn("uv pip install", block)
        self.assertIn("pnpm install --frozen-lockfile", workflow)
        self.assertEqual(len([line for line in workflow.splitlines() if line.startswith("  ") and not line.startswith("   ") and line.endswith(":") and line.strip() not in {"pull_request:", "push:"}]), 6)

    def test_database_test_jobs_only_use_guarded_runner(self):
        workflow = (ROOT / ".github/workflows/test.yml").read_text()
        for name, following in (("api-tests", "migration-tests"),
                                ("migration-tests", "ingestion-tests")):
            block = workflow.split(f"\n  {name}:", 1)[1].split(f"\n  {following}:", 1)[0]
            self.assertIn("run_disposable_tests.py --backend docker --suite", block)
            self.assertNotIn("DATABASE_URL:", block)
            self.assertNotIn("REDIS_URL:", block)
            self.assertNotIn("run: alembic", block)
            self.assertNotIn("services:", block)


if __name__ == "__main__":
    unittest.main()
