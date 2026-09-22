# Final-release Python runtime parity

Version: `sclib-release-runtime-parity/1.0.0`

Implemented: 2026-09-08

Issue: [EN04 / #52](https://github.com/JackZH26/SCLib_JZIS/issues/52)

## Purpose and evidence boundary

The release workflow rebuilds an image after Test completes. A matching source
revision and lock file do not, by themselves, establish that this final image
contains the same Python distributions as the tested environment. The new
`scripts/verify_release_runtime.py` gate compares the **actual final digest's
installed-package inventory** with authenticated inventories from the exact
triggering Test run and attempt.

This closes a delivery-chain implementation gap; it is not a claim that this
checkout has already passed a real Linux image release. Development validation
used isolated mocked GitHub/Docker orchestration and local standard-library
subprocesses only. No image was built, pulled, pushed, signed or deployed, no
release workflow was dispatched, and no production database was contacted for
this change. An exact-revision successful remote run and retained reports are
still required before claiming operational EN04 acceptance.

The unchanged `runtime_inventory.py` comparison covers Python distribution
versions, Python minor version and implementation, platform identity, project,
collector, lock and source pins. It records the Python patch version without
requiring patch equality. Its existing dev-only exceptions are unchanged:
`pytest`, `pytest-asyncio`, `ruff`, `iniconfig`, `pluggy`, and `pygments`.
It does **not** establish OS-library or wheel-ABI equivalence, scientific model
equivalence, vulnerability absence, or successful application execution.

## Release ordering

The release jobs require the fixed repository, same-repository main-branch push
and successful Test before privileged checkout/build steps. Existing matching
Security checks remain in place. For API and ingestion, the order is:

1. Build and push the digest-pinned candidate, retaining the existing BuildKit
   `provenance: mode=max` and `sbom: true` settings.
2. Retrieve the exact triggering Test attempt's authenticated artifacts; collect
   the final published digest's actual inventory and compare it.
3. Retain the final-digest parity report and captured input inventories.
4. Only after success, proceed to release scanning/SBOM, Cosign signing,
   explicit GitHub build provenance and deployment-digest artifacts.

The gate therefore does **not** prevent the initial registry write or the
BuildKit build-origin/SBOM attestations. Those attestations do not assert runtime
parity. A pushed candidate that fails the gate receives no successful release
eligibility from this workflow. The aggregate Release workflow failure also
prevents the existing deployment workflow from proceeding. Frontend retains its
separate frozen-lock policy; this Python-specific gate does not claim to audit
the frontend runtime.

## Exact Test evidence

| Final image | Required artifact names from the same Test attempt |
| --- | --- |
| `ghcr.io/jackzh26/sclib-api@sha256:…` | `api-test-runtime-inventory-attempt-N` and `migration-test-runtime-inventory-attempt-N` |
| `ghcr.io/jackzh26/sclib-ingestion@sha256:…` | `ingestion-test-runtime-inventory-attempt-N` |

The helper independently authenticates the repository ID, Test workflow ID and
`.github/workflows/test.yml` path, exact run ID/attempt, successful completed
`push` on `main`, full revision and same repository/head repository. It validates
the workflow event against the exact-attempt REST response, not a latest-run
query or a shared SHA alone. GitHub exposes a dedicated exact-attempt endpoint.
[GitHub workflow-run REST reference](https://docs.github.com/en/rest/actions/workflow-runs)

Artifact enumeration is bounded to five pages of 100 entries. Missing or
duplicate required names, duplicate IDs, expired artifacts, inconsistent counts,
wrong run/repository/revision witnesses and artifacts outside the current
attempt's time window fail closed. Explicit attempt-qualified upload names are
necessary because the artifact's run witness alone does not establish which
rerun produced it. A failed-jobs-only rerun may lack a complete fresh inventory
set; rerun **all Test jobs** when release eligibility requires a new attempt.
Older unsuffixed artifacts are deliberately not accepted as a fallback.

Each archive's actual bytes must match its authenticated SHA-256 and byte size
before ZIP parsing. Exactly three regular JSON members are admitted:
`test-runtime.json`, `image-runtime.json`, and `parity-report.json`. Their actual
contents and comparisons are checked; a reported `matches: true` alone is not
trusted. GitHub's artifact metadata supplies archive digest/size and a workflow
run witness; the upload action documents immutable archive outputs.
[Artifact REST reference](https://docs.github.com/en/rest/actions/artifacts),
[upload-artifact documentation](https://github.com/actions/upload-artifact)

## Trust and resource limits

- Repository and image paths are fixed in code. Only a lowercase 64-hex SHA-256
  image digest is accepted; there is no arbitrary image URL, mutable-tag or
  cross-repository artifact option.
- GitHub API requests use the job token only at the fixed API repository origin.
  Automatic redirects and ambient HTTP proxies are disabled. The signed HTTPS
  archive storage request is separate and receives **no Authorization header**.
  Unknown storage domains or additional redirects fail closed.
- JSON is duplicate-key/nonfinite rejecting and bounded to 2 MiB; archives are
  bounded to 4 MiB compressed and total uncompressed, with 2 MiB per member.
  ZIP contents are read in memory, never extracted or executed.
- HTTP reads use bounded chunks, a 30-second monotonic deadline and a 15-second
  socket timeout. An in-progress socket read can consume its remaining socket
  timeout before the deadline check returns; slow progress cannot renew the
  overall request indefinitely. External commands have bounded elapsed time and
  a combined 2 MiB stdout/stderr cap.
- The trusted checkout is checked for exact revision and dirty/untracked inputs
  before and after capture. Actual collector, project, lock, Dockerfile, gate and
  release-workflow hashes are retained. Test inventories must match their
  unchanged source-input pins. Reading a file changing only access time does
  not falsely invalidate it; content/identity changes do.
- Docker must use the default local Unix-socket context, with no custom Docker
  host/config/TLS overrides. The registry digest is joined to the inspected
  local immutable image ID, Linux/amd64 platform and OCI source/revision labels.
  The collector executes that immutable ID with `--pull never`.
- The existing isolated collector command has network disabled, read-only
  rootfs, no mounts, no forwarded environment/credentials, no health check,
  dropped capabilities, no-new-privileges, bounded memory/PIDs and an explicit
  nonroot Python entrypoint. It receives only trusted checkout collector bytes
  on stdin. Artifact-provided executable code is never used.
- Host Docker may use its pre-existing login configuration to pull the private
  candidate; that host credential is not forwarded into the container. Cleanup
  removes only the exact container ID bearing this invocation's ownership label.

## Invocation and retained output

The workflow invokes the helper only in its authenticated `workflow_run` job:

```bash
python scripts/verify_release_runtime.py \
  --project api \
  --image-digest "$RELEASE_DIGEST" \
  --test-run-id "$TEST_RUN_ID" \
  --test-run-attempt "$TEST_RUN_ATTEMPT" \
  --revision "$TARGET_SHA" \
  --output "$RUNNER_TEMP/release-runtime-api"
```

The output directory must be new, have an existing nonsymlink parent, and cannot
be reused or overwritten. It is created mode `0700`, with exclusive `0600` JSON
files. A partial output caused by I/O failure is not a success receipt and is
not reused. Files contain the actual validated input inventories, final runtime
inventory and `release-parity-report.json`; tokens, signed URLs and command
stderr are not retained. The report pins the final registry digest, local image
ID, platform, exact Test run/attempt/workflow, source inputs, artifact IDs/archive
hashes and each independent comparison.

A valid comparison mismatch creates a report with `matches: false` and a static
reason code; process exit is nonzero. Invalid input, unavailable evidence,
timeouts and malformed CLI arguments fail with a static sanitized message.
No missing evidence is silently converted to success. The workflow retains
available evidence on noncancelled failures, but later signing/deployment steps
still require success.

## Local verification recorded for this change

- New final-release orchestration tests: **90 passed**.
- Combined with existing inventory, candidate-parity and security-workflow
  tests: **124 passed, 9 subtests passed**.
- Full offline scripts regression after the final error-boundary fix:
  **943 passed, 36 subtests passed**.
- Scoped Ruff import/undefined-name checks and `git diff --check`: passed.
- Both modified workflow YAML documents parse successfully.

These tests include API-versus-migration divergence despite matching source and
lock pins, wrong run/attempt/project/digest, prior-attempt artifacts, ZIP attacks,
malformed metadata, redirected credential isolation, input mutation during
capture, bounded subprocess failure, exclusive output and gate ordering. They
are not substitutes for a successful final-digest Linux release execution.
