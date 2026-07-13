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

    def test_release_binds_scan_signature_and_provenance_to_digest(self) -> None:
        release = (WORKFLOW_DIR / "release-images.yml").read_text()
        for required in (
            "workflows: [Test]",
            "github.event.workflow_run.head_sha",
            "@${{ steps.build.outputs.digest }}",
            "cosign sign --yes",
            "actions/attest-build-provenance@",
            "anchore/sbom-action@",
            "aquasecurity/trivy-action@",
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

    def test_dependabot_tracks_every_package_ecosystem(self) -> None:
        dependabot = (ROOT / ".github" / "dependabot.yml").read_text()
        for ecosystem in ("github-actions", "pip", "npm", "docker-compose"):
            self.assertRegex(
                dependabot,
                rf'package-ecosystem:\s+["\']?{re.escape(ecosystem)}["\']?',
            )


if __name__ == "__main__":
    unittest.main()
