"""Unit tests for verifiable disaster-recovery backup manifests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.backup_manifest import ManifestError, create_manifest, verify_manifest


class BackupManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.dump = self.root / "sclib-20260713T120000Z.dump"
        self.dump.write_bytes(b"PGDMP" + bytes(range(256)))
        self.manifest = self.root / "sclib-20260713T120000Z.manifest.json"

    def _write_manifest(self) -> dict[str, object]:
        payload = create_manifest(
            self.dump,
            postgres_version="16.9",
            git_sha="a" * 40,
            created_at="2026-07-13T12:00:00+00:00",
        )
        self.manifest.write_text(json.dumps(payload))
        return payload

    def test_round_trip_verifies_digest_size_and_source(self) -> None:
        payload = self._write_manifest()
        verified = verify_manifest(self.dump, self.manifest)
        self.assertEqual(verified, payload)
        self.assertEqual(verified["artifact"]["format"], "postgres-custom")

    def test_tampered_dump_is_rejected(self) -> None:
        self._write_manifest()
        self.dump.write_bytes(self.dump.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ManifestError, "byte count"):
            verify_manifest(self.dump, self.manifest)

    def test_wrong_filename_is_rejected(self) -> None:
        payload = self._write_manifest()
        payload["artifact"]["filename"] = "other.dump"
        self.manifest.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ManifestError, "filename"):
            verify_manifest(self.dump, self.manifest)

    def test_empty_dump_cannot_create_manifest(self) -> None:
        self.dump.write_bytes(b"")
        with self.assertRaisesRegex(ManifestError, "non-empty"):
            create_manifest(
                self.dump,
                postgres_version="16.9",
                git_sha="a" * 40,
            )

    def test_disaster_recovery_scripts_fail_closed_and_restore_isolated(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        backup = (repository / "scripts" / "backup_postgres.sh").read_text()
        cron = (repository / "scripts" / "cron_daily_ingest.sh").read_text()
        restore = (repository / "scripts" / "restore_postgres_drill.sh").read_text()
        workflow = (
            repository / ".github" / "workflows" / "restore-drill.yml"
        ).read_text()
        for required in (
            "pg_dump --format=custom",
            "backup_manifest.py create",
            "backup_manifest.py verify",
            "remote_bytes",
            "SCLIB_BACKUP_BUCKET:?",
        ):
            self.assertIn(required, backup)
        self.assertNotIn("skipping backup", backup)
        self.assertNotIn('backup_postgres.sh" ||', cron)
        for required in (
            "org.jzis.sclib.purpose=restore-drill",
            "--single-transaction",
            "--exit-on-error",
            "docker rm --force --volumes",
        ):
            self.assertIn(required, restore)
        self.assertIn("schedule:", workflow)
        self.assertIn("restore_postgres_drill.sh", workflow)
