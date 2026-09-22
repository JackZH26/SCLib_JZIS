"""Static acceptance checks for supply-chain and DAST workflow invariants."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
# Reviewed immutable findings only. See the batch82 triage and original scan;
# new fixture revisions must be scanned and reviewed, never covered by a glob.
REVIEWED_FIXTURE_FINGERPRINTS = {
    # September 22 r9: exact decoded synthetic request keys.
    'ddce46287d35c013f0c3df623509eab3b3eaec1d:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r9.wire.json:generic-api-key:1',
    'ddce46287d35c013f0c3df623509eab3b3eaec1d:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r9.wire.json:generic-api-key:1',
    'ddce46287d35c013f0c3df623509eab3b3eaec1d:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r9.wire.json:generic-api-key:1',

    # September 22 r8: exact decoded synthetic request keys.
    '83adc706fec25985fab4e12626249cc11f71dd14:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r8.wire.json:generic-api-key:1',
    '83adc706fec25985fab4e12626249cc11f71dd14:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r8.wire.json:generic-api-key:1',
    '83adc706fec25985fab4e12626249cc11f71dd14:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r8.wire.json:generic-api-key:1',

    # September 22 r7: exact decoded synthetic request keys.
    'eeecd636b4e6e4e56005a261b09b437e1584917d:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r7.wire.json:generic-api-key:1',
    'eeecd636b4e6e4e56005a261b09b437e1584917d:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r7.wire.json:generic-api-key:1',
    'eeecd636b4e6e4e56005a261b09b437e1584917d:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r7.wire.json:generic-api-key:1',

    # September 22 r6: exact decoded synthetic request keys.
    '40bde0d4654af4565764fa40a0dc5e5de23b9200:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r6.wire.json:generic-api-key:1',
    '40bde0d4654af4565764fa40a0dc5e5de23b9200:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r6.wire.json:generic-api-key:1',
    '40bde0d4654af4565764fa40a0dc5e5de23b9200:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r6.wire.json:generic-api-key:1',

    # September 22 r5: exact decoded synthetic request keys.
    'a3436b508d87ccfa307c266f7dcada10c404bd9a:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r5.wire.json:generic-api-key:1',
    'a3436b508d87ccfa307c266f7dcada10c404bd9a:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r5.wire.json:generic-api-key:1',
    'a3436b508d87ccfa307c266f7dcada10c404bd9a:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r5.wire.json:generic-api-key:1',

    # September 22 r4: exact decoded synthetic request keys.
    '2a3e548d454c2434f34948c26fe1e2a73daa2242:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r4.wire.json:generic-api-key:1',
    '2a3e548d454c2434f34948c26fe1e2a73daa2242:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r4.wire.json:generic-api-key:1',
    '2a3e548d454c2434f34948c26fe1e2a73daa2242:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r4.wire.json:generic-api-key:1',

    # September 22 r3: individually decoded synthetic request keys.
    'ae860ae6960fbaa002252676b9925093412d8344:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r3.wire.json:generic-api-key:1',
    'ae860ae6960fbaa002252676b9925093412d8344:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r3.wire.json:generic-api-key:1',
    'ae860ae6960fbaa002252676b9925093412d8344:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r3.wire.json:generic-api-key:1',

    # September 22: exact synthetic keys and the public frontend API source hash.
    '5d3095a9fc71d6e5f9c83752035135383afe4fc0:docs/reviews/2026-09-05/delivery-2026-09-22/timeline-display-acceptance.json:generic-api-key:6',
    '5d3095a9fc71d6e5f9c83752035135383afe4fc0:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r2.wire.json:generic-api-key:1',
    '5d3095a9fc71d6e5f9c83752035135383afe4fc0:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r1.wire.json:generic-api-key:1',
    '5d3095a9fc71d6e5f9c83752035135383afe4fc0:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r2.wire.json:generic-api-key:1',
    '5d3095a9fc71d6e5f9c83752035135383afe4fc0:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r1.wire.json:generic-api-key:1',
    '5d3095a9fc71d6e5f9c83752035135383afe4fc0:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r2.wire.json:generic-api-key:1',

    # r9 receipts: three synthetic request-key archives and one public source-file digest.
    'f390087e544cbe3b71c7f7016687b9e8ad8aac23:docs/reviews/2026-09-05/delivery-2026-09-21/remote-release/anomaly-sparse-source-comparison.json:generic-api-key:2',
    'f390087e544cbe3b71c7f7016687b9e8ad8aac23:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921r9.wire.json:generic-api-key:1',
    'f390087e544cbe3b71c7f7016687b9e8ad8aac23:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r9.wire.json:generic-api-key:1',
    'f390087e544cbe3b71c7f7016687b9e8ad8aac23:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r9.wire.json:generic-api-key:1',

    'f189aea10183ef7ea8ed66ee2d66249c151433de:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r8.wire.json:generic-api-key:1',
    'f189aea10183ef7ea8ed66ee2d66249c151433de:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r8.wire.json:generic-api-key:1',

    '2540ee9498d11f5e42e81376b8ef8bc64ceb2f0b:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921r6.wire.json:generic-api-key:1',
    '2540ee9498d11f5e42e81376b8ef8bc64ceb2f0b:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921r7.wire.json:generic-api-key:1',
    '2540ee9498d11f5e42e81376b8ef8bc64ceb2f0b:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r6.wire.json:generic-api-key:1',
    '2540ee9498d11f5e42e81376b8ef8bc64ceb2f0b:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r7.wire.json:generic-api-key:1',
    '2540ee9498d11f5e42e81376b8ef8bc64ceb2f0b:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r6.wire.json:generic-api-key:1',
    '2540ee9498d11f5e42e81376b8ef8bc64ceb2f0b:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r7.wire.json:generic-api-key:1',

    'd0aa52f1de7842e9a76ef47f8e5ec7d8d5589333:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921r5.wire.json:generic-api-key:1',
    'd0aa52f1de7842e9a76ef47f8e5ec7d8d5589333:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r5.wire.json:generic-api-key:1',
    'd0aa52f1de7842e9a76ef47f8e5ec7d8d5589333:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r5.wire.json:generic-api-key:1',
    'b5e32d20142b5d3496fd63b5f21d3c5e58bb10c9:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921r4.wire.json:generic-api-key:1',
    'b5e32d20142b5d3496fd63b5f21d3c5e58bb10c9:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r4.wire.json:generic-api-key:1',
    'b5e32d20142b5d3496fd63b5f21d3c5e58bb10c9:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r4.wire.json:generic-api-key:1',
    'c16f164fdfe5f1ec56fc1a05cf11d9f974894998:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r3.wire.json:generic-api-key:1',
    'c16f164fdfe5f1ec56fc1a05cf11d9f974894998:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r3.wire.json:generic-api-key:1',
    '83096af42d7cab7e0e8be6893581b4d122074b75:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921r2.wire.json:generic-api-key:1',
    '83096af42d7cab7e0e8be6893581b4d122074b75:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r2.wire.json:generic-api-key:1',
    '83096af42d7cab7e0e8be6893581b4d122074b75:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r2.wire.json:generic-api-key:1',
    '20f85421348da25118508aa34c40307fece6579a:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921.wire.json:generic-api-key:1',
    '20f85421348da25118508aa34c40307fece6579a:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921.wire.json:generic-api-key:1',
    '20f85421348da25118508aa34c40307fece6579a:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921.wire.json:generic-api-key:1',

    '2374b5a42608300257316a3a49245e077e53a1ec:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260915r2.wire.json:generic-api-key:1',
    '2374b5a42608300257316a3a49245e077e53a1ec:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260915r2.wire.json:generic-api-key:1',
    '2374b5a42608300257316a3a49245e077e53a1ec:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260915r2.wire.json:generic-api-key:1',

    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/discovery-main-barrier-native.batch75.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/discovery-main-barrier-native.batch82.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260915.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-attestations-native.batch74.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-attestations-native.batch75.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-attestations-native.batch82.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260915.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-participant-native.batch74.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-participant-native.batch75.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-participant-native.batch82.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260915.wire.json:generic-api-key:1',

    (
        "00718749b6eb15926ae8cbfc58e02a9432488815:"
        "frontend/tests/fixtures/discovery-governance/provenance.json:generic-api-key:860"
    ),
    (
        "00718749b6eb15926ae8cbfc58e02a9432488815:"
        "frontend/tests/fixtures/discovery-selection/provenance.json:generic-api-key:217"
    ),
    (
        "02949468802db042e56645e2932b08863a174074:"
        "frontend/tests/fixtures/ml-pilot-attestations-native.batch73.wire.json:generic-api-key:1"
    ),
    (
        "02949468802db042e56645e2932b08863a174074:"
        "frontend/tests/fixtures/ml-pilot-participant-native.batch73.wire.json:generic-api-key:1"
    ),
    (
        "2cff9326c29b8f441f6436ad98ce47466455697f:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch55.wire.json:generic-api-key:83"
    ),
    (
        "2cff9326c29b8f441f6436ad98ce47466455697f:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch56.wire.json:generic-api-key:83"
    ),
    (
        "2cff9326c29b8f441f6436ad98ce47466455697f:"
        "frontend/tests/fixtures/discovery-main-barrier-native.wire.json:generic-api-key:83"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:150"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:188"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:225"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:276"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:469"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:68"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:81"
    ),
    (
        "531975a02ed78e212b6902314ad53328dc29f83f:"
        "frontend/tests/fixtures/discovery-scientific-provenance.json:generic-api-key:67"
    ),
    (
        "634265d7cd2323a077045d4042ee8dbdabe86f19:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch67.wire.json:generic-api-key:1"
    ),
    (
        "add2b2ae76b28588a9eb9aa82dca1d8eae8d30ad:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch57.wire.json:generic-api-key:83"
    ),
    (
        "add2b2ae76b28588a9eb9aa82dca1d8eae8d30ad:"
        "frontend/tests/fixtures/discovery-main-barrier-native.wire.json:generic-api-key:83"
    ),
    (
        "c482a478492d537071676e997616fa6b7d74710b:"
        "frontend/tests/fixtures/discovery-selection/provenance.json:generic-api-key:1"
    ),
    (
        "c4b8fb5cb0dcd04e37406be5014e298b108ee9e5:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch59.wire.json:generic-api-key:83"
    ),
    (
        "c4b8fb5cb0dcd04e37406be5014e298b108ee9e5:"
        "frontend/tests/fixtures/discovery-main-barrier-native.wire.json:generic-api-key:1"
    ),
    (
        "c6f05f1ca757f692d3f5169768b2fd75c6f685eb:"
        "docs/reviews/2026-09-05/issues-discovery-rag.json:generic-api-key:183"
    ),
    (
        "cc769d8df206ba64f4633b3a4802199623dfd82b:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch58.wire.json:generic-api-key:83"
    ),
    (
        "cc769d8df206ba64f4633b3a4802199623dfd82b:"
        "frontend/tests/fixtures/discovery-main-barrier-native.wire.json:generic-api-key:83"
    ),
    (
        "d42d0dd4ed0ae263fd7b4720982e1ed670bc4598:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch52.wire.json:generic-api-key:83"
    ),
    (
        "d42d0dd4ed0ae263fd7b4720982e1ed670bc4598:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch54.wire.json:generic-api-key:83"
    ),
    (
        "d42d0dd4ed0ae263fd7b4720982e1ed670bc4598:"
        "frontend/tests/fixtures/discovery-main-barrier-native.wire.json:generic-api-key:83"
    ),
    (
        "dc716fba4ce14b26623cc70cdd3f5b0c49b0a2f7:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch72.wire.json:generic-api-key:1"
    ),
    (
        "dc716fba4ce14b26623cc70cdd3f5b0c49b0a2f7:"
        "frontend/tests/fixtures/ml-pilot-attestations-native.batch72.wire.json:generic-api-key:1"
    ),
    (
        "dc716fba4ce14b26623cc70cdd3f5b0c49b0a2f7:"
        "frontend/tests/fixtures/ml-pilot-participant-native.batch72.wire.json:generic-api-key:1"
    ),
    (
        "dd4fb7746a8e7707951884f521088e0a262f5d33:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch68.wire.json:generic-api-key:1"
    ),
    (
        "dd4fb7746a8e7707951884f521088e0a262f5d33:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch69.wire.json:generic-api-key:1"
    ),
    (
        "dd4fb7746a8e7707951884f521088e0a262f5d33:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch70.wire.json:generic-api-key:1"
    ),
    (
        "dd4fb7746a8e7707951884f521088e0a262f5d33:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch71.wire.json:generic-api-key:1"
    ),
    (
        "dd4fb7746a8e7707951884f521088e0a262f5d33:"
        "frontend/tests/fixtures/ml-pilot-participant-native.batch70.wire.json:generic-api-key:1"
    ),
    (
        "dd4fb7746a8e7707951884f521088e0a262f5d33:"
        "frontend/tests/fixtures/ml-pilot-participant-native.batch71.wire.json:generic-api-key:1"
    ),
}
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
        self.assertEqual(len(fingerprints), len(set(fingerprints)))
        self.assertEqual(
            set(fingerprints),
            {
                (
                    "d60f0db35de7e46d3f6e1a6907886b134feacef1:"
                    "README.md:curl-auth-header:133"
                ),
                (
                    "7596ef2e5928c46e2b0da6bcfaf48ab6fabe3d35:"
                    "api/tests/test_unified_auth.py:generic-api-key:319"
                ),
                (
                    "3477605e37393b8430068d38a822b758816bc025:"
                    "PROJECT_SPEC.md:generic-api-key:892"
                ),
                (
                    "c499146b223562c5099ab971a149392067ca047e:"
                    "api/tests/test_session_security.py:generic-api-key:17"
                ),
                (
                    "c499146b223562c5099ab971a149392067ca047e:"
                    "api/tests/test_session_security.py:generic-api-key:54"
                ),
            } | REVIEWED_FIXTURE_FINGERPRINTS,
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
            deploy.index('run --rm --no-deps migration'),
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

    def test_ingest_retries_only_the_connection_preflight(self) -> None:
        ingest = (WORKFLOW_DIR / "ingest-daily.yml").read_text()
        for required in (
            "id: ssh_preflight_primary",
            "continue-on-error: true",
            "if: steps.ssh_preflight_primary.outcome == 'failure'",
            "Back off after transient SSH failure",
            "Retry VPS2 SSH connectivity",
            "timeout: 2m",
        ):
            self.assertIn(required, ingest)
        self.assertEqual(ingest.count('script: "true"'), 2)
        self.assertEqual(ingest.count("bash scripts/cron_daily_ingest.sh"), 1)

    def test_dependabot_tracks_every_package_ecosystem(self) -> None:
        dependabot = (ROOT / ".github" / "dependabot.yml").read_text()
        for ecosystem in ("github-actions", "pip", "npm", "docker-compose"):
            self.assertRegex(
                dependabot,
                rf'package-ecosystem:\s+["\']?{re.escape(ecosystem)}["\']?',
            )

    def test_observability_config_validation_matches_runtime_versions(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text()
        workflow = (WORKFLOW_DIR / "test.yml").read_text()
        for image, tool_image in (
            (
                "prom/prometheus:v3.13.1-distroless",
                "prom/prometheus:v3.13.1",
            ),
            (
                "quay.io/prometheus/alertmanager:v0.33.1",
                "quay.io/prometheus/alertmanager:v0.33.1",
            ),
        ):
            self.assertIn(image, compose)
            self.assertIn(tool_image, workflow)
        self.assertIn("grafana/grafana:13.1.0", compose)


if __name__ == "__main__":
    unittest.main()
