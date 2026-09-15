# Batch 78 — installed evidence CI coverage and integration checks

Base HEAD: `02949468802db042e56645e2932b08863a174074`, branch
`codex/sclib-research-v2`. Preserves uncommitted batches 74–77. The preceding
goal turn made actual implementation and verification progress; this turn
continues the delivery dependency rather than claiming issue completion from
local test counts.

## Gap identified and fixed

The CI wheel step covered accounting, registration and review projections, but
did not execute the newer `probe_ml_pilot_evidence_install.py`. Repository tests
alone could therefore miss installation/packaging regressions in the streaming
evidence path. This matters to [EN04 #52](https://github.com/JackZH26/SCLib_JZIS/issues/52)
and the operational delivery of [ML08 #54](https://github.com/JackZH26/SCLib_JZIS/issues/54).

The API Test job now runs a separate, required installed-evidence step after
building and installing its wheel, before offline contracts and image parity.
The new test-only driver:

- Requires explicit absolute interpreter/wheel/new-output paths; performs no
  install, database operation, real-document read or source upload itself.
- Checks the isolated interpreter's prefix and pip `direct_url.json` against
  the actual wheel path and SHA-256. Only SCLib and standard venv packaging
  tools may be installed; server dependencies cannot supply missing imports.
- Builds synthetic frames in the locked repository test environment, then runs
  the existing installed probe with `-I -B`, a minimal environment and an owned
  empty working directory. The probe forbids repository/server imports and
  network access, and admits exactly one owned streaming child per passing case.
- Independently compares installed output with the repository kernel's actual
  input hash, complete integrity proof and selected implementation hashes.
- Covers zero context, both superseded/current contexts across 63 review rows,
  and a real 8 MiB context passed in 997-byte chunks. A fourth corrupted-context
  attempt retains the original hash and must fail without success JSON output.
- Creates an exclusive mode-0600 observation report only after successful
  checks and temporary working-directory cleanup. The attempt-qualified CI
  artifact is required. No raw frame or source prose is retained in it.

Details and the explicit invocation are in
[the clean-wheel procedure](../../ML_PILOT_EVIDENCE.md#clean-wheel-ci-verification).
The driver lives under `scripts/tests`, not in the application or user intake
CLI. No API implementation, schema, lockfile, feature flag or installed runtime
dependency was changed by this batch.

## Actual installed-wheel evidence

A new owned wheel was built with existing uv 0.11.16 in offline mode, then
installed into a new venv using `--no-index --no-deps`. The build logged cached
resolver warnings about `packaging`; it still completed successfully under
`--offline`, without a dependency-install change to the project environment.
The resulting wheel is byte-identical to the earlier batch75 build, consistent
with unchanged packaged application sources.

The actual [native observation](Installed_Evidence_Wheel_Batch78.json) records:

| Case | Context files | Actual context bytes checked | Owned child count |
| --- | ---: | ---: | ---: |
| Zero context | 0 | 0 | 1 |
| All revisions | 2 | 99 | 1 |
| Full single-context bound | 1 | 8,388,608 | 1 |

The separate corrupted-context attempt was rejected. The installed interpreter
was Python 3.12.14 on macOS arm64, with only `pip` and `sclib-api` distributions.
The three existing accounting, registration and review installed-wheel probes
were also executed successfully against this same new environment. Registration
and review each observed two owned children; neither created an account record,
attestation, scientific acceptance or training authority.
The synthetic work directory was removed before report creation. This is a new
native installed-package execution, not a Linux image execution or a genuine
scientific pilot. Synthetic UUIDs vary; this observation is not a frozen input
bundle or an authority receipt.

| Artifact/source | SHA-256 |
| --- | --- |
| Observation JSON | `6efb93af1e17e451f68c286f9f4b7584010426e96e31d917ebb313d817568c5c` |
| API wheel | `6bcd2cda0f08a45d46cf06ff4724bf9763a0bd277924e1773f5f3d1a32936f6e` |
| Existing installed probe | `a478c000b7f332f94eb3fabeeed6368b10fc020990d5de7baf9d63a7dc0b4ab6` |
| New test-only driver | `14304c2f540ce6e2b6318a7e1588e6f13af676895876b1f7b05933f18bee93f5` |

## Regression and production-mode build

The initial full offline suite completed **2,237 tests and 82 subtests in
125.16 s**. It collected before the new driver tests existed, so it does not
include them. The focused driver/document/workflow run then completed **64 tests
in 2.26 s**, including 20 new driver cases. These counts overlap and must not be
added as if they were disjoint. The final complete rerun passed **2,257 tests
and 82 subtests in 128.03 s**, including the new driver tests.

The new tests cover wrong wheel/path/prefix/distributions, source/proof/hash
mismatches, incorrect or boolean child counts, inherited-environment exclusion,
failed/empty/oversized output, preserved existing output and symlink rejection,
CI ordering/artifact requirements and the superseded synthetic revision case.

Ruff lint/format, workflow YAML parsing and `git diff --check` passed. All six
existing CI jobs remain. All **3,852** selected source pins across seven batch75
native API archives still match, as do the three final batch77 Nginx pins. Those
archives were not rewritten or described as new API/Nginx executions. The new
installed-probe observation's driver/probe pins also match the final source.

An actual `pnpm build` completed in an owned temporary frontend copy with the
existing dependency installation. `.env*`, `.next` and previous test reports
were excluded; the project source/configuration was not rewritten. A minimal
environment disabled telemetry, used the real `/sclib` base path and pointed
API configuration at unavailable loopback port 9, not production. No application
backend or database was launched. The installed Next.js 15.5.21 build compiled,
completed type validation, generated **39/39 static pages** and produced
standalone output/build traces. Public Google font retrieval was not replaced
with a synthetic font. Dynamic scientific data and authenticated browser behavior
are not validated by this build.

This native build uses Node 25.5.0, not the Linux CI Node 20 runtime. It is not a
fresh frozen-lock installation, a shipped frontend image or proof of Linux
dependency parity. No changes to the project's `next-env.d.ts` or `tsconfig.json`
were introduced. Previous batch76/77 UI/native artifacts retain their own scope.

## Remote state and remaining gates

A fresh read-only GitHub check found **38 open review issues (#41–78)** and no
open implementation PR for this branch. Remote `main` is still
`d26fc098565492b78b416fb30b6b1ec7087b24c7`; local HEAD has 61 commits beyond that
base, with 1,230 committed changed files. Exact remote-ref inspection also found
no published `codex/sclib-research-v2` branch. These are historical accumulated
upgrade changes, not work all introduced in this batch; the current uncommitted
batch74–78 files are additional. Dependency-update PRs remain untouched.

No local Docker, Podman, Colima or QEMU system executable was available. No
container/VM runtime was installed as a side effect. The exact-revision Linux
Test/image artifacts and reviewed implementation PR remain necessary. The user
has been asked to confirm committing/pushing the upgrade branch and opening a
draft PR, explicitly excluding merge, deployment, production migration and
feature-flag activation. No remote write is inferred from the local checks.

Independent permitted-source pilot work, human scientific acceptance and actual
ML/RPS empirical evaluation are still required. This batch does not close any
issue or redefine those requirements as synthetic testing.
