# Supply-chain and application-security controls

SCLib treats the tested source revision, locked dependencies, container digest,
SBOM, provenance, signature, and deployed digest as one release identity.

## Pull-request and scheduled controls

- CodeQL `security-extended` analysis for Python and JavaScript/TypeScript.
- Gitleaks full-history secret scanning with redacted output.
- `pip-audit` against both frozen uv lockfiles.
- `pnpm audit --prod --audit-level high` against the frozen frontend lockfile.
- Trivy repository scanning for high/critical vulnerabilities, secrets, and
  infrastructure misconfiguration.
- Weekly ZAP scans against an ephemeral API, PostgreSQL, Redis, and production
  frontend build. Active API attacks never target production.
- Weekly Dependabot updates for Actions, Python, npm, Dockerfiles, and Compose.

Every Action is pinned to a full commit SHA. The readable version comment is
maintained next to the pin, and Dependabot supplies reviewed updates. Trivy is
also pinned to a post-incident action revision and an explicit scanner version;
floating `latest` versions are prohibited.

High and critical dependency findings block the security workflow. As of the
July 13, 2026 baseline, Python audits report no known vulnerabilities and the
frontend reports no high or critical production vulnerability. Two moderate
PostCSS paths remain transitive through Next.js and Plotly; they do not process
attacker-supplied stylesheet source in SCLib and remain under automated update
monitoring.

## Release artifact controls

The release workflow runs only after the complete `Test` workflow succeeds on
`main`. It builds API, frontend, and ingestion images once, publishes them to
GHCR, scans the image, emits SPDX JSON SBOMs, attaches BuildKit and GitHub
provenance, and signs each digest keylessly with GitHub OIDC and Sigstore.

Production consumes the recorded `sha256` digests, never a mutable tag. Before
pull or migration, deployment verifies the Sigstore certificate identity and
OIDC issuer. A signature, digest, test, scan, migration, SLO gate, or read-only
smoke failure stops the release.

## Verification

For an image digest shown in a release run:

```bash
cosign verify \
  --certificate-identity \
  'https://github.com/JackZH26/SCLib_JZIS/.github/workflows/release-images.yml@refs/heads/main' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  ghcr.io/jackzh26/sclib-api@sha256:<digest>
```

SBOM artifacts are retained with the workflow run. Treat a mismatch between an
SBOM subject digest, provenance subject digest, signature subject, and deployment
digest as a release-blocking incident.

The deployment workflow downloads the three component manifests from that exact
successful release run, validates their digest and source-commit shapes, and
requires all three source commits to match before it verifies each Sigstore
certificate. VPS2 uses `docker compose up --no-build`; production cannot
silently rebuild source or substitute a mutable tag.

The same validation applies to manual redeployment: an operator supplies a
`Release images` run ID, and the workflow accepts it only when GitHub reports a
successful `main` release produced by the expected workflow. Connection values
and the pinned SSH host fingerprint are stored as Actions secrets. Production
source is switched only after the error-budget and workload-identity checks
pass, and a PostgreSQL backup must succeed before Alembic runs.
