"""Behavioral regression tests for the production daily-ingest wrapper."""

from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "cron_daily_ingest.sh"


class DailyIngestScriptTests(unittest.TestCase):
    def test_recoverable_retry_failure_does_not_skip_aggregate_or_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fake_bin = root / "bin"
            scripts = root / "scripts"
            fake_bin.mkdir()
            scripts.mkdir()
            (root / ".env.release").write_text("# signed release fixture\n")

            docker = fake_bin / "docker"
            docker.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    if [[ "$*" == *"--mode retry"* ]]; then
                        echo "simulated recoverable retry failure"
                        exit 7
                    fi
                    echo "simulated successful stage: $*"
                    exit 0
                    """
                )
            )
            docker.chmod(0o755)

            backup = scripts / "backup_postgres.sh"
            backup.write_text("#!/usr/bin/env bash\necho verified-backup-ran\n")
            backup.chmod(0o755)

            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{fake_bin}:{environment['PATH']}",
                    "SCLIB_LOCKED": "1",
                    "SCLIB_ROOT": str(root),
                    "SCLIB_LOG_DIR": str(root / "logs"),
                    "SCLIB_RELEASE_ENV": str(root / ".env.release"),
                }
            )

            result = subprocess.run(
                ["bash", str(SCRIPT)],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                env=environment,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertIn("retry pass exit=7", output)
            self.assertIn("step 3/5: aggregate", output)
            self.assertIn("verified-backup-ran", output)
            self.assertIn(
                "DONE cron_daily_ingest ingest_rc=0 retry_rc=7 aggregate_rc=0",
                output,
            )
            self.assertNotIn("FAIL cron_daily_ingest", output)


if __name__ == "__main__":
    unittest.main()
