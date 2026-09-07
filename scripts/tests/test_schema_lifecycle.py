"""Dependency-free source and executable entrypoint guards for EN02."""
from __future__ import annotations

import ast
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SchemaLifecycleBoundaryTests(unittest.TestCase):
    def test_entrypoint_never_migrates_and_executes_only_after_admission(self):
        entrypoint = ROOT / "api/entrypoint.sh"
        source = entrypoint.read_text()
        self.assertNotIn("alembic", source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, body in {
                "python": '#!/bin/sh\nprintf "check:%s\\n" "$*" >> "$SCLIB_TEST_LOG"\nexit "${SCLIB_TEST_CHECK_EXIT:-0}"\n',
                "uvicorn": '#!/bin/sh\nprintf "serve:%s\\n" "$*" >> "$SCLIB_TEST_LOG"\n',
            }.items():
                path = root / name
                path.write_text(body)
                path.chmod(0o700)
            log = root / "calls"
            environment = {"PATH": f"{root}:/usr/bin:/bin", "SCLIB_TEST_LOG": str(log)}
            success = subprocess.run(["/bin/sh", str(entrypoint), "uvicorn", "main:app"], env=environment, capture_output=True, text=True)
            self.assertEqual(success.returncode, 0)
            self.assertEqual(log.read_text().splitlines(), ["check:-m services.schema_lifecycle check", "serve:main:app"])
            log.unlink()
            rejected = subprocess.run(["/bin/sh", str(entrypoint), "uvicorn", "main:app"], env={**environment, "SCLIB_TEST_CHECK_EXIT": "1"}, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(log.read_text().splitlines(), ["check:-m services.schema_lifecycle check"])

    def test_deployment_orders_credential_backup_signature_migration_admission_cutover(self):
        source = (ROOT / ".github/workflows/deploy.yml").read_text()
        positions = [source.index(value) for value in (
            "test -s /etc/sclib/credentials/migration-database-url",
            "bash scripts/backup_postgres.sh",
            "cosign verify",
            'run --rm --no-deps migration',
            'python -m services.schema_lifecycle check',
            'up -d --no-build --wait --wait-timeout 180',
        )]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("api alembic", source)
        self.assertIn("set -euo pipefail", source)

    def test_migration_service_does_not_inherit_api_env_or_cloud_credentials(self):
        base = (ROOT / "docker-compose.yml").read_text().split("\n  migration:\n", 1)[1].split("\n  ingestion:\n", 1)[0]
        production = (ROOT / "docker-compose.prod.yml").read_text().split("\n  migration:\n", 1)[1].split("\n  ingestion:\n", 1)[0]
        self.assertNotIn("\n    env_file:", base)
        self.assertNotIn("GOOGLE_APPLICATION_CREDENTIALS", base + production)
        self.assertNotIn("\n    ports:", base + production)
        self.assertIn('profiles: ["tools"]', base)
        self.assertIn('restart: "no"', base)
        self.assertIn('DATABASE_URL: ""', production)
        self.assertIn("SCLIB_MIGRATION_DATABASE_URL_FILE:", production)
        self.assertIn("image: ${SCLIB_API_IMAGE:?", production)
        self.assertIn(":/run/secrets/sclib-migration-database-url:ro", production)

    def test_startup_gate_precedes_all_background_tasks(self):
        source = (ROOT / "api/main.py").read_text().split("async def lifespan", 1)[1]
        self.assertLess(source.index("await check_application_schema"), source.index("asyncio.create_task"))
        environment = (ROOT / "api/alembic/env.py").read_text().split("def run_migrations_online", 1)[1]
        self.assertLess(environment.index("acquire_migration_lock"), environment.index("context.run_migrations"))
        self.assertIn("pool.NullPool", environment)

    def test_populated_task_history_does_not_mask_independent_older_guards(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        tree = ast.parse(source)
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        called = sorted((node.lineno, node.func.id) for node in ast.walk(main)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name))
        positions = {name: line for line, name in called}
        ordered = [positions[name] for name in (
            "_freeze_on_migrated_schema", "_publication_on_migrated_schema",
            "_source_lifecycle_on_migrated_schema", "_source_impact_indexes_on_migrated_schema",
            "_source_tasks_on_migrated_schema", "_source_task_downgrade_guard",
            "_background_jobs_empty_roundtrip", "_background_jobs_on_migrated_schema", "_background_job_downgrade_guard",
        )]
        self.assertEqual(ordered, sorted(ordered))
        for marker in ("preserve scientific correction proposals", "registry contains records",
                       "shadow history contains records", "release history contains records",
                       "governance history contains records"):
            self.assertLess(source.index(marker), source.index("request_id = asyncio.run(_source_tasks_on_migrated_schema"))

    def test_migrated_task_checks_exercise_effect_and_rollback_not_only_metadata(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _source_tasks_on_migrated_schema", 1)[1].split("\ndef _source_task_downgrade_guard", 1)[0]
        for marker in ("enqueue_source_task(session", "execute_source_task(session", "record_source_task_failure(session",
                       "assert await state(session) == before_request", "assert await state(session) == before_attempt",
                       'assert after_attempt["timeline_projection_state"] == expected_state',
                       'assert replay["replayed"] is True', 'assert await state(session) == after_attempt'):
            self.assertIn(marker, body)

    def test_background_history_is_populated_only_after_every_prior_guard(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        main = source.split("def main()", 1)[1]
        positions = [main.index(value) for value in (
            "_source_impact_indexes_on_migrated_schema(capability", "_source_tasks_on_migrated_schema(capability",
            "_source_task_downgrade_guard(capability", "_background_jobs_empty_roundtrip(capability",
            "_background_jobs_on_migrated_schema(capability", "_background_job_downgrade_guard(capability")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('assert before["background_job_cycles"] == []', source)
        self.assertGreaterEqual(source.count('SELECT count(*) FROM background_job_cycles'), 5)

    def test_migrated_background_service_proves_effect_rollback_and_exact_replay(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _background_jobs_on_migrated_schema", 1)[1].split("\ndef _background_job_downgrade_guard", 1)[0]
        for marker in ("run_background_cycle(", "insert(AuditReport)", 'assert failed["status"] == "failed"',
                       'assert after_failure["audit_reports"] == before["audit_reports"]',
                       'assert succeeded["status"] == "succeeded"', 'assert len(reports) == 1',
                       'assert replay["status"] == "already_succeeded"', "assert await snapshot() == after_success",
                       "run_sync(check_connection_schema)", "pg_locks"):
            self.assertIn(marker, body)


if __name__ == "__main__":
    unittest.main()
