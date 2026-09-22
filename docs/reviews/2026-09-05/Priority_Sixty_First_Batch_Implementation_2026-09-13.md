# Batch61 — exact run contracts, independent review and fresh readiness

Base: `85dff80ba2ec2f9bfbfc5f3f291f7a64e1c51f4f` on
`codex/sclib-research-v2`. The previous turn made concrete progress by saving
the user's requested development checkpoint, with its known incomplete schema
and two failing historical source-pin checks explicitly recorded.

Fresh read-only GitHub inspection found **38 open issues**; ML06 #70 and ML09
#76 were read in full. This increment advances the authorization dependencies
of reproducible baselines. It does not establish a scientifically reviewed
ML08 pilot, train a real model, publish evaluation gains or close these issues.

## Implemented contracts

- Completed the 0074 draft with explicit non-null approval expiry in both the
  SQL insert guard and CHECK constraint. Hashes, original owner/grants,
  independent reviewer identity, exact predecessor heads, immutable history
  and original retention remain enforced by PostgreSQL.
- Added owner context and immutable exact run plans, with requester-confirmed
  single-process CPU/wall/memory budgets, task/config/package/prepared-input
  hashes and bounded source/host observations. No arbitrary command or client
  runtime document is accepted.
- Added independent conditional approve/deny/revoke, rollback-only previews,
  exact-intent commits, no-op identical replays and original-key historical
  recovery. Regranting a role cannot revive its old approvals.
- Added an owner-only actual-worker readiness endpoint: retrieve retained
  inputs, rebuild them, then recheck byte equality, complete source/review/label
  currentness, full purpose-specific rights, exact plan/current approval and
  fingerprints in one fresh read-only snapshot.
- Exposed the separate results without granting execution. A current approval
  cannot waive source holds, missing rights, a changed environment or missing
  independent scientific/execution gates. Older preflight responses now say
  `independent_run_approval_not_checked`, not that a registry is unavailable.
- Extended native migration rehearsal to 0074, with empty round trips and
  nonempty-history refusal. New tables are checked empty before older round
  trips and populated only after earlier downgrade guards are independently
  exercised. Older rows and immutable artifact bytes are not rewritten.

The [operator/API contract](../../ML_USE_RUNS.md) documents exact fields,
endpoints, budget limits, current-versus-historical semantics and remaining work.

## Scientific and operational boundaries

Approval is a conditional review of an exact proposed plan, not ground truth,
a source licence, a reviewed pilot or a reusable run capability. Current rights
and source validity are observed separately. The records cannot change the task
contract's label, censoring, temporal, family/state or dependency-leakage rules.

Selected on-disk source hashes and observed host properties/lockfile are not
installed-dependency or release-image attestation, nor proof that loaded code
matches disk. Requested budgets are not resource reservations or an executed
worker's measured/enforced limits. The actual run consumer must validate those
requirements independently; `run_baseline_dataset` remains disabled.

All native fixtures use synthetic accounts/data and explicit synthetic approval
evidence hashes. Most contract tests use an explicitly doubled intake compiler;
the separate SQL/offline preparation/actual-worker pipeline exercises genuine
reconstruction and source-hold/purge refusal. Neither fixture constitutes human
scientific or legal review.

## Verification record

- First native attempt: **1 failed**, 11.14s, before any plan was created. The
  older compiler-double fixture lacked a prepared hash. The new fixture now
  supplies an explicitly synthetic prepared hash; the production exact-binding
  requirement was not relaxed.
- Second native attempt: **1 failed**, 9.93s. SQLAlchemy returned string-subclass
  column keys; the strict canonical codec correctly refused them. Record-body
  construction now normalizes column names to plain strings, matching the
  existing ledger pattern.
- Next scoped native run: **14 passed**, 247.06s, with owned service cleanup.
  This includes the actual SQL → offline preparation → retained actual-worker
  → conditional approval → held readiness pipeline. It predates the subsequent
  extra purge-during-worker, foreign-admitted-requester and preflight-code checks;
  final regression evidence is recorded below when terminal.
- Migration lifecycle source checks: **43 passed**, 1.87s. Full script suite:
  **1,939 passed / 36 subtests passed**, 58.74s.
- Initial complete native migration rehearsal: exit 0, including 0074. A later
  report request using macOS's `/tmp` symlink was refused before services were
  created (`unsafe_report_destination`); the retry uses the verified physical
  `/private/tmp` path, preserving the no-symlink destination guard.
- Scoped Ruff passes for the changed/new run model, services, router and tests.
  A broader Ruff invocation exposed six pre-existing findings in the migration
  harness/lifecycle test (four C408 and two PLW1510); these unrelated lines were
  not rewritten or suppressed. Whitespace checks pass.

- Fresh guarded native HTTP captures: **2 passed**, 27.65s. The ML rights fixture
  contains 15 raw HTTP strings and **555 source pins**; the Discovery fixture
  contains seven raw HTTP strings and **274 source pins**. Every pin was
  independently compared with the current source and matched.
- Refreshed-fixture component checks: **139 passed**, 6.00s, followed by a
  successful nonincremental TypeScript check. These include the two exact-pin
  checks that failed at the prior development checkpoint.
- Isolated Chromium: **4 passed**, 22.1s, covering desktop 1440×1000 and mobile
  390×844 inventory, focus, explicit preview, unknown commit/read-only recovery
  and admission-denial clearing. Desktop inventory and mobile preview were
  visually inspected; long hashes remain readable without horizontal overflow.
  No unexpected synthetic API requests or external browser traffic were
  observed. The owned server on port 32060 was no longer listening afterward.
  These synthetic UI checks do not attest production or new run-plan browser
  controls, which have not been implemented.

- First full frontend run: **1,435 passed / 1 failed**, 50.59s. The pre-existing
  Distribution rights focus test waited for a heading's DOM insertion but
  asserted before React's passive focus effect completed. The test now waits
  for the actual focus condition with `waitFor`; the focus assertion and
  no-write assertion remain intact, and application behavior is unchanged.
  Its scoped **81 tests passed**, 4.42s.
- Final full frontend run: **41 files / 1,436 passed**, 49.46s, followed by
  **38 passing source checks** and successful nonincremental TypeScript.

- Final expanded guarded API suite: **142 passed**, 732.98s, covering run
  contracts, actual-worker request pipeline, source rights and native wire,
  Discovery main barriers, retained submissions and preflight. This final run
  includes the additional purge-during-worker, foreign-admitted-requester,
  historical-plan replay after purge and updated preflight-blocker checks.
  Owned PostgreSQL/Redis and test data were cleaned up. The existing FastAPI
  `regex` deprecation warning remains; no new test failures remain in this scope.
- Final documentation check: **121 relative links resolve**. Both active
  fixture inventories and all 677 migration source pins match the worktree;
  historical archive bytes are unchanged and `git diff --check` passes.

All test processes for this increment have terminal results. This is local
batch61 implementation/verification, not proof that the 38 remaining issues or
the overall research-platform upgrade are complete.

## Frozen 0074 migration evidence

[Native migration report](measurements/schema-rehearsal-0074-native-2026-09-13.json):
**105,494 bytes**, SHA-256
`9faab27a9890a83da206755c402b355061d4d3062cc51be79e42dbb176faff28`;
canonical report-body hash
`9540b061785e00a33524d946e5af5645171fa9307128031f53baab0211bfcf60`.

The final report-producing rehearsal passed in **82,268 ms**, with native
PostgreSQL 16.13 / CPython 3.12.14 / Darwin arm64 and verified owned-service
cleanup. It pins **677 source/runtime-config files** against base `85dff80` plus
the captured dirty backend worktree, source inventory SHA-256
`e146d81f3bd13c840a4b57d984d788d8155731544e4a792ec0434ba7698c0b9a`.
All 677 file hashes were rechecked successfully after copying the exact report
bytes. Unrelated documentation/frontend edits are not claimed as migration
inputs. The receipt retains the existing versioned subset of table counters,
not newly invented run-ledger counters; the pinned executable harness separately
asserts run-plan/review preview, replay, revocation and preservation behavior.
It is synthetic migration evidence, not a production rollout authorization.

## Historical evidence preservation

The checkpoint's failing active fixture pins were not overwritten with guessed
hashes. The exact old files are retained under separate archive names:

- `discovery-main-barrier-native.batch59.wire.json`: 203,654 bytes,
  `837e79928da739ffcd44d7ac95927fa56e7191881f2d31e14ecf05d11d6c83e9`.
- `ml-use-rights-native.batch60.wire.json`: 206,034 bytes,
  `79ad4248be9d5b75d9655a62064b5a4a8a9ab599e3887225cf6e745924e19f21`.

The older 0073 migration receipt remains unchanged historical batch59 evidence.
New active fixtures must come from successful fresh native HTTP captures, not
manually resealed historical responses or browser mocks.

The refreshed active ML rights file is **211,439 bytes**, SHA-256
`35ac35963bf7108560492d3a9b91af69cb62e0ce70748e8be1151be4eac668fb`,
byte-identical to its native output. The refreshed active Discovery file is
**197,211 bytes**, SHA-256
`6ecd0b0b05e52971013cada385f195cc1c2f967a8013eaa2f613e2163272bfc9`;
it differs from the native file only by one final newline outside the JSON
document. All seven raw HTTP strings and outer JSON contents are unchanged.
Frontend tests pin both active captures and both preserved historical archives.

Local diagnostic screenshots are under
`/var/folders/m0/ztnj2ywn613cqhtb3_ym0xyc0000gn/T/sclib-ml-rights-browser-artifacts-KZMLtQ/`;
that temporary directory is not a portable release artifact.

## Reproduction

From the repository root, use only the disposable runner for database tests:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- -q \
  tests/test_ml_use_runs.py tests/test_ml_use_request_pipeline.py \
  tests/test_ml_use_rights.py tests/test_ml_use_rights_wire.py \
  tests/test_discovery_main_barrier.py tests/test_ml_use_submissions.py \
  tests/test_ml_use_preflight.py --maxfail=1
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite migrations
api/.venv/bin/python -m pytest scripts/tests -q
```

The native report option requires a new `.json` destination with no symlink
ancestors; never overwrite an existing rehearsal receipt. From `frontend`:

```bash
pnpm exec vitest run --maxWorkers=2
pnpm test:source
pnpm exec tsc --noEmit --incremental false
pnpm exec playwright test --config tests/e2e/ml-use-rights.config.ts --max-failures=1
```

## Remaining delivery work

1. Owner/approver browser workflows for the new plan and readiness APIs, with
   the same explicit preview/commit and unknown-outcome handling as source rights.
2. Resolvable controlled evidence documents and actual independent human
   source/scientific reviews; an accepted or honestly inconclusive ML08 pilot.
3. Guarded one-shot execution consumption, isolated release-runtime admission,
   resource enforcement and reproducible authorized baseline release evidence.
4. Issue-specific exact-revision PR/CI/runtime delivery and acceptance checks.

No commit, push, deployment, production migration, real role grant, real review,
source redistribution or paid/live computation is performed by this increment.
