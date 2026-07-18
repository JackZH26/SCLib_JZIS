"""Static acceptance checks for supply-chain and DAST workflow invariants."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
PINNED_ACTION = re.compile(r"^\s*-?\s*uses:\s+[^\s@]+@[0-9a-f]{40}(?:\s+#.*)?$")


class SecurityWorkflowTests(unittest.TestCase):
    def test_all_remote_actions_are_pinned_to_full_commit_sha(self) -> None:
        for workflow in sorted(WORKFLOW_DIR.glob("*.yml")):
            for line_number, line in enumerate(workflow.read_text().splitlines(), 1):
                if "uses:" not in line or "uses: ./" in line:
                    continue
                self.assertRegex(
                    line,
                    PINNED_ACTION,
                    f"{workflow.name}:{line_number} must pin uses: to a full SHA",
                )

    def test_dast_targets_only_ephemeral_loopback_services(self) -> None:
        dast = (WORKFLOW_DIR / "dast.yml").read_text()
        self.assertIn("sclib_dast", dast)
        self.assertIn("127.0.0.1:8000", dast)
        self.assertIn("127.0.0.1:3000", dast)
        self.assertNotIn("jzis.org", dast)
        self.assertNotIn("72.62.251.29", dast)

    def test_security_workflow_covers_required_scanners(self) -> None:
        security = (WORKFLOW_DIR / "security.yml").read_text()
        for required in (
            "github/codeql-action/init@",
            "gitleaks/gitleaks-action@",
            "pip-audit==2.9.0",
            "pnpm audit --prod --audit-level high",
            "aquasecurity/trivy-action@",
            "version: v0.70.0",
        ):
            self.assertIn(required, security)
        self.assertIn("working-directory: api", security)
        self.assertIn("working-directory: ingestion", security)
        self.assertNotIn("uv --quiet export --project", security)

    def test_gitleaks_exceptions_are_exact_fingerprints(self) -> None:
        ignore_file = ROOT / ".gitleaksignore"
        fingerprints = [
            line
            for line in ignore_file.read_text().splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(
            set(fingerprints),
            {
                "d60f0db35de7e46d3f6e1a6907886b134feacef1:"
                "README.md:curl-auth-header:133",
                "7596ef2e5928c46e2b0da6bcfaf48ab6fabe3d35:"
                "api/tests/test_unified_auth.py:generic-api-key:319",
                "3477605e37393b8430068d38a822b758816bc025:"
                "PROJECT_SPEC.md:generic-api-key:892",
                "c499146b223562c5099ab971a149392067ca047e:"
                "api/tests/test_session_security.py:generic-api-key:17",
                "c499146b223562c5099ab971a149392067ca047e:"
                "api/tests/test_session_security.py:generic-api-key:54",
            },
        )

    def test_release_binds_scan_signature_and_provenance_to_digest(self) -> None:
        release = (WORKFLOW_DIR / "release-images.yml").read_text()
        for required in (
            "workflows: [Test]",
            "github.event.workflow_run.head_sha",
            "Require matching Security success",
            "actions/workflows/security.yml/runs",
            ".head_sha == $sha",
            "needs: verify-security",
            "@${{ steps.build.outputs.digest }}",
            "cosign sign --yes",
            "actions/attest-build-provenance@",
            "anchore/sbom-action@",
            "aquasecurity/trivy-action@",
            "limit-severities-for-sarif: true",
            '${{ matrix.component }}.sha',
        ):
            self.assertIn(required, release)
        self.assertNotIn(":latest", release)

    def test_deploy_consumes_only_verified_release_digests(self) -> None:
        deploy = (WORKFLOW_DIR / "deploy.yml").read_text()
        compose = (ROOT / "docker-compose.prod.yml").read_text()
        installer = (ROOT / "scripts" / "install_cosign.sh").read_text()
        for required in (
            "workflows: [Release images]",
            "actions/download-artifact@",
            "^sha256:[0-9a-f]{64}$",
            "cosign verify",
            "scripts/check_error_budget.py",
            "--no-build",
        ):
            self.assertIn(required, deploy)
        self.assertNotIn("docker compose build", deploy)
        self.assertNotRegex(deploy, r"(?<!no-)--build\b")
        for variable in (
            "SCLIB_FRONTEND_IMAGE",
            "SCLIB_API_IMAGE",
            "SCLIB_INGESTION_IMAGE",
        ):
            self.assertIn(f"${{{variable}:?", compose)
        self.assertIn('readonly VERSION="v3.0.6"', installer)
        self.assertIn("EXPECTED_SHA256", installer)

    def test_production_api_command_survives_entrypoint_override(self) -> None:
        compose = (ROOT / "docker-compose.prod.yml").read_text()
        api_block = compose.split("\n  ingestion:", 1)[0]
        self.assertIn("entrypoint:", api_block)
        self.assertIn("command:", api_block)
        self.assertIn("- uvicorn", api_block)
        self.assertIn('- "8000"', api_block)

    def test_scheduled_jobs_reuse_last_signed_release_manifest(self) -> None:
        deploy = (WORKFLOW_DIR / "deploy.yml").read_text()
        ingest = (WORKFLOW_DIR / "ingest-daily.yml").read_text()
        cron = (ROOT / "scripts" / "cron_daily_ingest.sh").read_text()
        aggregate = (ROOT / "scripts" / "sclib-daily-aggregate.sh").read_text()

        self.assertIn(".env.release", deploy)
        self.assertIn('mv -f "$release_env"', deploy)
        self.assertIn("bash scripts/cron_daily_ingest.sh", ingest)
        for script in (cron, aggregate):
            self.assertIn(".env.release", script)
            self.assertIn("docker-compose.prod.yml", script)
        self.assertNotIn('source "${SCLIB_ROOT}/.env"', cron)

    def test_runtime_images_remove_build_package_managers(self) -> None:
        api = (ROOT / "api" / "Dockerfile").read_text()
        ingestion = (ROOT / "ingestion" / "Dockerfile").read_text()
        frontend = (ROOT / "frontend" / "Dockerfile").read_text()
        for dockerfile in (api, ingestion):
            self.assertIn("/usr/local/lib/python3.11/site-packages/pip*", dockerfile)
            self.assertIn("/usr/local/lib/python3.11/site-packages/setuptools*", dockerfile)
            self.assertIn("/root/.cache/uv", dockerfile)
            self.assertIn("/bin/uvx", dockerfile)
        self.assertIn("apk upgrade --no-cache", frontend)
        self.assertIn("/usr/local/lib/node_modules/npm", frontend)
        self.assertIn("/usr/local/bin/corepack", frontend)

    def test_deploy_connection_and_manual_redeploy_are_fail_closed(self) -> None:
        deploy = (WORKFLOW_DIR / "deploy.yml").read_text()
        for required in (
            "workflow_dispatch:",
            "release_run_id:",
            '.name == "Release images"',
            '.path == ".github/workflows/release-images.yml"',
            '.head_branch == "main"',
            '.conclusion == "success"',
            "secrets.VPS2_HOST",
            "secrets.VPS2_USER",
            "secrets.VPS2_DEPLOY_PATH",
            "secrets.VPS2_HOST_FINGERPRINT",
            "fingerprint:",
            "scripts/backup_postgres.sh",
            "steps.images.outputs.target_sha",
        ):
            self.assertIn(required, deploy)
        for prohibited in (
            "host: 72.62.251.29",
            "username: root",
            "git reset --hard",
            "StrictHostKeyChecking=no",
            "script_stop:",
        ):
            self.assertNotIn(prohibited, deploy)
        self.assertLess(
            deploy.index("scripts/backup_postgres.sh"),
            deploy.index("alembic upgrade head"),
        )

    def test_ingest_uses_the_same_verified_ssh_connection(self) -> None:
        ingest = (WORKFLOW_DIR / "ingest-daily.yml").read_text()
        for required in (
            "secrets.VPS2_HOST",
            "secrets.VPS2_USER",
            "secrets.VPS2_DEPLOY_PATH",
            "secrets.VPS2_HOST_FINGERPRINT",
            "fingerprint:",
        ):
            self.assertIn(required, ingest)
        for prohibited in (
            "host: 72.62.251.29",
            "username: root",
            "StrictHostKeyChecking=no",
            "script_stop:",
        ):
            self.assertNotIn(prohibited, ingest)

    def test_dependabot_tracks_every_package_ecosystem(self) -> None:
        dependabot = (ROOT / ".github" / "dependabot.yml").read_text()
        for ecosystem in ("github-actions", "pip", "npm", "docker-compose"):
            self.assertRegex(
                dependabot,
                rf'package-ecosystem:\s+["\']?{re.escape(ecosystem)}["\']?',
            )


if __name__ == "__main__":
    unittest.main()
