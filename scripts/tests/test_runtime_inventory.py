"""Runtime comparison and CI lock-consumption checks; no services required."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from runtime_inventory import compare, normalize


class RuntimeInventoryTests(unittest.TestCase):
    def setUp(self):
        self.runtime = {"lock_sha256": "a" * 64, "python_minor": "3.11",
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
        self.tests.update(lock_sha256="b" * 64, python_minor="3.12")
        self.tests["packages"]["unreviewed-package"] = "1.0"
        failures = compare(self.runtime, self.tests)
        self.assertIn("lock mismatch", failures)
        self.assertIn("Python minor mismatch", failures)
        self.assertTrue(any("unreviewed-package" in reason for reason in failures))

    def test_python_jobs_use_pinned_uv_and_locked_dev_extra(self):
        workflow = (ROOT / ".github/workflows/test.yml").read_text()
        for name, following in (("api-tests", "migration-tests"),
                                ("migration-tests", "ingestion-tests"),
                                ("ingestion-tests", "frontend-build")):
            block = workflow.split(f"\n  {name}:", 1)[1].split(f"\n  {following}:", 1)[0]
            self.assertIn("uv==0.11.16", block)
            self.assertIn("uv sync --locked --extra dev --python 3.11", block)
            self.assertIn("runtime_inventory.py --lock uv.lock", block)
            self.assertNotIn("uv pip install", block)
        self.assertIn("pnpm install --frozen-lockfile", workflow)

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
