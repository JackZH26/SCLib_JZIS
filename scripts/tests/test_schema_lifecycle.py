"""Dependency-free source and executable entrypoint guards for EN02."""
from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
