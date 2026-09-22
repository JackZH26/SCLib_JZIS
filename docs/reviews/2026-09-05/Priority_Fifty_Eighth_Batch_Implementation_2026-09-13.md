# Batch58 — durable private ML requests and bounded input retention

Date: 2026-09-13. Base commit `2cff9326c29b8f441f6436ad98ce47466455697f`,
branch `codex/sclib-research-v2`. A fresh read-only issue listing still contains
38 open issues, including the umbrella. This increment follows the unresolved
ML06 #70 / ML07 #68 dependencies of ML09 #76; local implementation/testing is
not a substitute for their full scientific and delivery acceptance criteria.

## Delivered implementation

[The operator contract](../../ML_USE_SUBMISSIONS.md) describes the new private
preview, submission, exact outcome recovery, retained-input reinspection,
owner purge and bounded expired-input cleanup endpoints. All remain under the
existing default-off ML governance flag. No real roles or source rights are
provisioned, and no real input is uploaded by this development work.

| Component | Concrete change |
| --- | --- |
| `api/models/ml_use_submissions_v1.py`, migration 0072 | Immutable owner-bound request records, separate byte storage and append-only purge receipts; atomic completeness, exact grant checks, integrity pins, storage ceilings and guarded downgrade |
| `api/services/ml_use_submissions.py` | Explicit retention intent, exact observation binding, durable idempotency, owner-only history/internal input access, seven-day expiry and atomic purge |
| `api/routers/ml_use_submissions.py` | Authenticated actual-worker/current-SQL preview and submission; independent current account/session checks before commit; recoverable uncertain outcomes and no raw-input download |
| `api/routers/ml_use_preflight.py` | Shared authenticated byte-reconstruction stage for uploads and retained inputs; existing read-only endpoint contracts unchanged |
| `api/services/research_audit_retention.py` | Request/purge identity references participate in the existing account-erasure hold |
| API tests and migrated-schema runner | Exact retention/replay/rollback, orphan-input refusal, resealed scope/authority rejection, owner isolation, expiry, lost replies, concurrency, actual offline-CLI/worker pipeline and nonempty downgrade refusal |

The extra EOF whitespace noted in the previous commit was removed from the
shared deterministic preparation helper. Its logic is unchanged, but its source
hash changes; old preparation/capture identities are not relabeled as current.

## Scientific and permission boundary

The request stores the original **historical pre-submission inspection** with
its own observation timestamp, record hash and explicit scope. That inspection
came from a fresh read-only SQL snapshot after real reconstruction, but the
subsequent persistence transaction is distinct. The record does not assert
commit-time source currentness, human review or a durable authorization lease.
Fresh source/review/permission checks remain mandatory for later approval and
consumption. A source retraction can therefore invalidate `recheck` while the
unaltered historical request remains recoverable.

Seven-day input access is a technical policy, not a legal conclusion. The client
must explicitly name the policy; operators must independently approve storage,
access, encryption, backups and retention before enabling it. Immutable metadata
has no automatic erasure endpoint. Expired bytes cannot be read even before
cleanup, and exact replay cannot renew access or recreate a purged blob. Purge
removes only the relevant input row and preserves the audit; it does not promise
secure erasure from media, WAL or backups. Production cleanup scheduling is not
enabled by this increment.

No source permission or model fitting is enabled. Existing real-data training
entry points still refuse without their separate authorization contracts.

## Verification record

- Full source-only scripts suite after the version-marker updates:
  **1,935 passed, 36 subtests passed**, 85.17s.
  The final runner/admission-order source was subsequently checked by another
  complete scripts run: **1,935 passed, 36 subtests passed**, 121.09s.
- Frontend source checks: **38 passed**; TypeScript passed from the frontend
  package. An initial invocation from the repository root correctly found no
  package and was rerun from the proper directory.
- New/changed standalone API files pass configured Ruff; script changes pass
  F/I checks. The legacy `api/models/db.py` still has its eight pre-existing
  UP037/E402 findings outside the new registration lines; this is not a claim
  that a whole-repository lint is clean.
- Initial native storage run: **14 passed, one failed**, 246.07s. The failure
  exposed a test-fixture scope error: clock aging affected other test requests
  in the same disposable database. Aging and record assertions now target the
  exact owned submission. No production retention rule was relaxed.
- Initial full scripts run: **1,930 passed, three failed**, 86.53s, plus 36
  subtests. Source assertions still required the previous 0071 head or parsed
  through the next function. They now include the separately checked-empty
  0072 tables and use the exact intended function scope; the later full scripts
  result above supersedes this initial checkpoint.
- The first 0072 migration rehearsal reached the new empty roundtrip but was
  rejected because its new test helper queried service identity before the
  existing fresh-connection schema-admission check. Both new helpers now perform
  admission first. The failed run cleaned up its owned services and published
  no successful receipt; the admission requirement was preserved.
- The next native storage/pipeline checkpoint completed **22 storage cases**,
  then failed only the pipeline's final global-empty assertion, 451.00s overall.
  The actual HTTP chain had already demonstrated successful preview, atomic
  submission, replay and retained reinspection, rejection after retraction,
  recovery, purge and refusal of purged reinspection. Other tests' retained
  inputs correctly remained. The final assertion now checks this submission's
  exact identity; the fresh paired run below verifies that fix.
- Final paired lost-reply/owner-isolation and genuine end-to-end pipeline run:
  **2 passed**, 298.39s; owned cleanup confirmed. The first case deliberately
  retains another owner's request, so the second case proves its purge preserves
  that peer's bytes rather than relying on an otherwise empty table.
- Full native migration rehearsal to **0072 passed**, 98.643s measured by its
  retained receipt; owned cleanup confirmed. It exercises new empty roundtrip,
  migrated-schema exact storage/rollback/replay/purge and immutable-history
  downgrade refusal after the existing historical contracts.
- Expanded native admission/reconstruction/currentness/Discovery run:
  **127 passed**, 695.57s; owned cleanup confirmed. This includes 19 new private
  admission/concurrency cases, 36 existing reconstruction-route cases, 20 full
  currentness cases and 52 Discovery cases. The only warning is the existing
  unsuppressed FastAPI `regex` deprecation.

- The first full frontend component run completed **1,352 passed, one failed**,
  128.08s. The scientific-import recovery case encountered a missing
  `scrollIntoView` function in the simulated DOM. No production code or test
  harness was changed to suppress that failure. At the user's subsequent
  request to commit the current work, the unchanged full suite was rerun:
  **40 files passed, 1,353 tests passed**, 99.45s. The earlier intermittent
  failure remains a test-stability follow-up, not a claimed fix.
- Commit preflight also reran frontend source checks (**38 passed**) and
  `tsc --noEmit --incremental false` (**passed**). All **666 migration source
  pins**, **268 Discovery source pins**, three current/historical archive
  hashes, seven raw HTTP response strings and **125 relative Markdown links**
  were verified against the retained artifacts and current worktree.

Selections overlap; test counts are not independent scientific samples or
evidence of real source permission.

The direct storage tests use a labeled worker-proof double alongside actual SQL
review/label observations, to isolate retention and transactional behavior.
The separate request pipeline runs the original offline packaging commands and
actual server reconstruction worker before saving/rechecking/purging its private
upload. A doubled compiler is not substituted for that end-to-end evidence.

## Historical evidence

Batch57's previous active Discovery capture is preserved byte-exact as
`frontend/tests/fixtures/discovery-main-barrier-native.batch57.wire.json`, SHA-256
`b5b131b248e7c5e1f17ae1731db2a466972e0b8b5103cfb40ec0e3e99a5cca40`.
Batch52/54/55/56 archives and prior 0070/0071 migration receipts remain historical.
Any new 0072 receipt must bind the actually executed new source inventory.

The final native [0072 rehearsal receipt](measurements/schema-rehearsal-0072-native-2026-09-13.json)
is retained byte-for-byte (104,002 bytes), file SHA-256
`381da0c5c822d9c226bdc0248fcdf2c8df42aedc2fc99ba97aa871bd9e68d51c`.
Its internal `report_sha256` is
`64f07a32d3c40fef1e66dcc2064a7aa66105d67d64e6aa3daecea2ab75703a5f`,
and its **666 captured API/scripts source-file pins** were verified against the
worktree. This inventory does not mean every file was executed.
The source-inventory hash is
`9de7daec93f4be2c2830c54dfd75d6007c0aa94c79fa8ec6d0c1d00fa35ecf70`.
Runtime: CPython 3.12.14, Darwin/arm64, PostgreSQL 16.13 (160013).
This is native local evidence, not Linux release-image or production parity.
The frozen receipt v1 retains its existing named accounting metrics; the new
storage assertions are in the source-pinned executed migration runner, not
invented additional counters in an old receipt format.

The final successful 127-case run generated a fresh Discovery fixture at
`/tmp/sclib-submission-wire-TVxNfq/test_barrier_edit_needs_new_pr0/main-barrier-wire.json`.
Its seven raw HTTP response strings are preserved unchanged in the active
`frontend/tests/fixtures/discovery-main-barrier-native.wire.json`; only the
outer archive is pretty-printed. The active file has **268 backend source pins**,
203,225 bytes, SHA-256
`488b2967d4abbbbbf1a6dcbc2c9232cef5f106b4091fc1321d512b0255ee6167`.
All seven response strings and all 268 source pins were independently checked.
These scoped pins supplement, rather than replace, the wider migration inventory.
Batch59 preserves this exact capture as
`frontend/tests/fixtures/discovery-main-barrier-native.batch58.wire.json`;
it remains batch58 evidence and does not attest later backend revisions.

## Reproduce the final selections

```bash
api/.venv/bin/python -m pytest scripts/tests -q

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- -q \
  tests/test_ml_use_submission_admission.py tests/test_ml_use_reconstruction.py \
  tests/test_ml_use_currentness.py tests/test_discovery_main_barrier.py

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- -q \
  tests/test_ml_use_submissions.py::test_owner_acl_current_admission_and_lost_commit_recovery \
  tests/test_ml_use_request_pipeline.py

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite migrations
```

Use a new, real nonsymlink path with `--report` when retaining another migration
receipt; never overwrite the archived receipt. The complete storage module can
also be selected as `tests/test_ml_use_submissions.py` in the guarded runner.

## Next dependencies and remaining acceptance

Implement independently reviewed purpose-specific source permissions, their
expiry/revocation and exact run approval/consumption; connect a genuinely
reviewed ML08 pilot before producing authorized baseline results. The private
operator UI and production retention/cleanup deployment are separate remaining
integration decisions. Actual PR/CI delivery, Linux final-image parity and each
issue's required real scientific acceptance remain unproven here.

Delivery scope is local implementation and a user-requested Git checkpoint.
No push, PR, remote issue mutation, production migration/backfill, source
redistribution, real model fit, paid calculation or deployment is performed in
this batch. All SQL exercises use the owned disposable runner.
