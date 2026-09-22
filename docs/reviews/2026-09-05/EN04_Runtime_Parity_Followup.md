# EN04 runtime-image parity follow-up

Issue: [EN04 #52](https://github.com/JackZH26/SCLib_JZIS/issues/52).
Implementation starts from local checkpoint `52930eb`. This is local code and
mocked validation, not a successful remote CI run, release, deployment or issue
closure. No Docker/Podman/Colima/uv installation, production connection, image
publish or push was performed. Local integration commits are recorded by the
parent batch report and Git history.

## Implemented

- The existing API, migration and ingestion CI jobs each capture their actual
  locked test interpreter, build their corresponding release Dockerfile and
  compare its actual `/opt/venv` package inventory. API and migration independently
  compare against API images; ingestion uses its separate image. The six-job
  layout, frontend frozen lock installs and EN01-owned DB/Redis runner remain.
- `sclib-runtime-inventory/v2` binds lock and pyproject bytes, collector bytes,
  source revision, project distribution/version, interpreter and platform.
  Installed packages must exist at their captured versions in the lock; every
  runtime package must match the test environment. Old/malformed inventories,
  duplicate JSON/package identities, absent project distribution and unexplained
  test-only packages fail closed. `uv sync --locked` remains the resolver's
  pyproject/lock consistency gate; the inventory does not replace that resolver.
- The only test-only exceptions are pytest, pytest-asyncio, ruff, iniconfig,
  pluggy and pygments. Exceptions apply only when absent from runtime; a runtime
  package bearing one of these names still requires exact version equality.
- `run_runtime_parity.py` verifies a clean revision-bound project/collector,
  local default Unix Docker endpoint and Linux/x86_64 test environment. Builds
  use the checked-out Dockerfile, `linux/amd64` as in `release-images.yml`, and
  API's short GIT_SHA argument. Actual image ID, labels and input digests are
  validated; the Dockerfile hash is retained in the report.
- Capture overrides entrypoint to isolated Python, disables healthchecks, uses
  no network, read-only rootfs, non-root UID 1001, no Linux capabilities and no
  bind/secret/socket mounts. Collector bytes arrive via stdin; no application
  module, API startup/migration, ingestion command or service probe runs.
  Subprocess environment contains PATH and LANG only. Builds need public
  dependency download access; this is distinct from the isolated capture step.
- Exact container ID plus per-run label guards interrupted-container cleanup;
  there is no broad prune, external-service cleanup or image publication.
  Test/image inventories and comparison reports are uploaded outside the build
  context. Failures cannot produce a passing parity report.

## Local verification

| Check | Result |
|---|---|
| Runtime inventory + orchestration mocked tests | 20 passed |
| Entire operations/scripts unittest suite | 76 passed; includes the 20 above |
| Scoped Ruff | Passed |
| Workflow YAML parsing / six-job preservation | Passed |
| `git diff --check` | Passed |
| Linux Docker build / actual inventory comparison | **Not run locally** |
| Remote CI / release / production | **Not run** |

Synthetic tests cover package and provenance mismatches, old/malformed schemas,
lock membership, strict dev allowances, guarded-service workflow preservation,
wrong project/architecture, dirty/untracked inputs, remote Docker rejection,
immutable-image and label checks, no-network/no-mount invocation, clean child
environment, failed builds and ownership-scoped cleanup. Docker execution is
mocked and sockets are forbidden in orchestration tests; these results must not
be described as successful image integration.

## Acceptance still pending

1. Run the reviewed changes in Linux CI; inspect all three test/image inventories,
   comparison reports and actual EN01 service integration. This host has no
   Docker/uv execution evidence. The original earlier EN04 report remains a
   dated observation, not a claim that the new gate has run.
2. Existing `release-images.yml` already requires Test success on the tested
   main/push revision before publishing; new parity failures therefore affect
   that existing gate. No release workflow or branch protection was changed or
   remotely verified by this task.
3. Candidate image IDs are not the subsequently rebuilt/published digest.
   Release promotion still needs its normal revision/digest provenance review.
   This compares Python package versions, not Python patch equivalence, OS
   native libraries, wheel bytes/ABI, scientific correctness or application
   behavior inside the runtime image. Python patch versions are recorded but
   not equality-gated. Mutable base/system layers remain outside this scope.
4. Complete code review and obtain actual CI artifacts before treating EN04 as
   accepted. No old v1 artifact should be relabeled as v2; re-capture it instead.

Operational details and safe commands: [TESTING_SAFELY.md](../../TESTING_SAFELY.md).
