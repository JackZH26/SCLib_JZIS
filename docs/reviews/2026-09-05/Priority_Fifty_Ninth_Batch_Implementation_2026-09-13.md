# Batch59 — independent, purpose-bound ML rights review

Base commit `add2b2ae76b28588a9eb9aa82dca1d8eae8d30ad`, branch
`codex/sclib-research-v2`. Read-only GitHub inspection still finds 38 open issues
(including the umbrella). ML06 #70, ML07 #68, ML09 #76 and ML08 #54 were inspected;
the previous goal increment made progress by committing batch58 and verifying
the frontend. This batch advances the remaining exact source-use governance
dependency rather than claiming the scientific pilot or release is complete.

## Delivered implementation

See [the complete operator contract](../../ML_USE_RIGHTS.md) for API fields,
role boundaries, legal-evidence limitations, retention and compatibility.

| Layer | Concrete implementation |
| --- | --- |
| Schema 0073 | Append-only `ml_use_rights_decisions`, exact request/resource/purpose binding, SQL hash/intent/membership/independence/expiry/predecessor guards and nonempty downgrade refusal |
| Service | Paginated exact inventory inspection, rollback-only preview, pinned commit, owner-bound recovery, allow/deny/revoke and current full-resource coverage |
| API | Default-off private rights access, inspection, decisions, recovery and actual-worker owner coverage; authentication before body parsing and fresh session lock before commit |
| Scientific boundary | Distinct row representations and artifact digests; all declared dependencies count; frozen/current drift and source holds cannot be waived by rights decisions |
| Lifecycle | Expiry bounded by original seven-day input retention; purged inputs are inaccessible; revoked/unavailable reviewer grants cease to satisfy the live gate; historic decisions stay recoverable |
| Test/migration harness | SQL-native integrity and no-op recovery, actual elapsed expiry, complete/partial coverage, uncertain commits, concurrency, actual-worker retraction/purge checks, exact older-history preservation |

There is no blanket per-material or per-family permission. Resource identity
includes the exact stored representations and origins, and every decision is
specific to one submission and `private_baseline_evaluation`. The reviewer must
be a different account from the requester and hold current explicit curator and
ML rights memberships plus verified administrator admission.

The registry records a reviewer-declared basis and external document hash; it
does not fetch or legally validate the document. Operators still need resolvable,
controlled evidence and qualified human review. Full current recorded coverage
can satisfy only the exact source-permission gate. Run approval, training,
public release, external dependency completeness and scientific acceptance are
not thereby granted. Negative or insufficient pilot results remain acceptable
research outcomes; no predictive gain is assumed.

The old preflight routes now say `purpose_specific_permissions_not_checked`
instead of incorrectly claiming no registry exists. Their existing response
versions remain unchanged and they still perform no rights lookup or grant.
Positive coverage requires the separate actual-worker `/ml/use/rights/check`.

## Verification record

- New standalone API files and changed preflight/pipeline files pass configured
  Ruff; migration scripts/source guards pass F/I lint.
- Full source-only scripts suite: **1,937 passed, 36 subtests passed**, 94.18s.
- Initial native rights run: **one failed**, 18.57s, with owned service cleanup.
  SQL accepted the correctly bound preview, but service verification rejected
  SQLAlchemy's string-subclass column keys under the strict canonical JSON
  contract. Converting keys to ordinary strings fixes that serialization issue;
  no database integrity or authorization rule was weakened.
- The next rights run failed at the final read-only coverage query after writing
  the full synthetic permission inventory, **one failed**, 271.70s, with owned
  cleanup. Its new query reused a publication helper that locks account rows;
  PostgreSQL correctly refused `SELECT FOR SHARE` in a read-only transaction.
  The fix must use equivalent nonlocking, hash-verified role/account reads in
  that snapshot, preserving the existing write-side locks and read-only gate.
- The first 0073 full migration rehearsal **passed**, 104,610ms measured
  rehearsal time, with owned cleanup; it covered 671 source-file pins. Its
  `/private/tmp/sclib-rights-migration.DradKG/schema-0073.json` receipt predates
  the read-only coverage fix and is not final-source compatibility evidence.
- The initial paired HTTP recovery/actual-worker pipeline run reached durable
  independent decisions but failed both owner coverage calls, **two failed**,
  213.78s, with owned cleanup. The handler referenced `match` through a router
  that did not export it; it now imports the service comparison helper directly.
  The actual worker and durable decision checks had passed up to that boundary.
- Final native rights selection: **11 passed**, 497.21s, with owned cleanup.
  It covers full inventory accounting without waiving the deliberate source
  hold, exact pins/self-review refusal, resealed SQL forgeries, immutable history,
  real expiry, denial/allow transitions, unavailable reviewer, withdrawal after
  purge, HTTP admission/lost reply/recovery and concurrent exact-key commits.
- Isolated conjunction truth table: **8 passed, 11 deselected**, 4.29s, with
  owned cleanup. Explicit source/role gate doubles cover the positive Boolean
  branch as well as missing/denied/revoked/expired/unavailable/held/drift cases.
  This is not an actual permitted scientific dataset or legal-evidence test.
- Final source-only scripts rerun: **1,937 passed, 36 subtests passed**, 110.69s.
  Frontend source checks: **38 passed**; TypeScript check passed.
- A second successful 0073 migration rehearsal measured **139,924ms**, with
  cleanup, before the integration fixture expectation was corrected. A later
  capture correctly refused `rehearsal_inputs_changed` when additional test-only
  truth-table coverage was saved while it was running; it cleaned up and did not
  publish a success receipt. The final frozen-source rehearsal is tracked below.
- Expanded API regression: **108 passed**, 805.80s, with owned cleanup. It
  covers rights HTTP recovery, the actual-worker request pipeline, preflight,
  currentness and Discovery main barriers. Its rights HTTP case overlaps the
  11-case native selection above; these counts are not independent samples.
- Final frozen-source 0073 migration rehearsal: **passed**, 128,746ms, with
  owned cleanup and all **671 source pins** matching the final API/scripts
  worktree. The byte-identical 104,678-byte receipt is
  [archived here](measurements/schema-rehearsal-0073-native-2026-09-13.json),
  full-file SHA-256
  `0f8484c848b87b10c396e685c1338f0535a66e8785d3acbc8c1fafbd8e37fad4`.

The intermediate complete rights run finished **seven passed, two failed**,
383.91s, with owned cleanup. One failure was the already corrected router
reference still loaded in that earlier process. The other exposed a wrong test
expectation: the shared dataset fixture deliberately retains unapproved legacy
catalogue data, including a 7777 K canary. Even complete recorded permissions
must not waive its source/scientific hold. The test now requires both complete
rights coverage and a refused source-permission gate for that fixture; the
production negative gate is unchanged. This is not evidence of a positive
real-data training authorization.

Direct rights tests use explicitly labeled intake compiler doubles with actual
SQL source/review/currentness captures. The separate request pipeline retains
its original offline CLI and actual bounded reconstruction worker. These evidence
types must not be conflated. All SQL testing uses owned disposable services;
no shared database DSN is inherited.

## Historical compatibility evidence

The batch58 0072 migration receipt and Discovery wire remain immutable historical
evidence. The new active fixture and 0073 receipt were obtained from successful
runs against the final source state, with all captured source pins checked; old
hashes are not relabeled as attesting the new source/schema.

The exact batch58 wire is archived at
`frontend/tests/fixtures/discovery-main-barrier-native.batch58.wire.json`, SHA-256
`488b2967d4abbbbbf1a6dcbc2c9232cef5f106b4091fc1321d512b0255ee6167`.
The current API source no longer matches those old pins. The active replacement
comes from the successful expanded native regression, has **271 matching backend
source pins**, and retains all **seven raw HTTP response strings** unchanged
from the captured output. Its 203,654-byte full-file SHA-256 is
`837e79928da739ffcd44d7ac95927fa56e7191881f2d31e14ecf05d11d6c83e9`.
The component test pins both the new active fixture and the batch58 archive.

The earlier intermittent scientific-import component failure was also addressed
at its test teardown boundary: explicit RTL cleanup now runs before globals and
the `scrollIntoView` shim are restored/removed, so mounted effects are not left
with a partially dismantled simulated browser. No production optional chaining
or failure suppression was added. The import component selection passed
**129 tests**, 9.69s. After the native wire refresh, full frontend verification
passed **40 files / 1,353 tests**, 86.01s, with two workers. The 38 source checks
and nonincremental TypeScript check also passed again before the local commit.
The final receipt's closed schema/body hash and 138 relative documentation links
were checked; scoped Ruff and `git diff --check` passed. This local test evidence
does not replace remote CI or issue-specific scientific acceptance.

## Remaining dependencies

1. Exact independent run approval, expiry/revocation and guarded consumption of
   the same current request, permissions, task/data/environment and budget.
2. Private operator UI and controlled, resolvable rights-document evidence.
3. A real independently reviewed 60-event ML08 pilot with preserved inaccessible
   candidates, disputes, missingness and honest human effort measurements.
4. Authorized reproducible baselines, grouped evaluation and release/CI/PR
   evidence required by the issue-specific acceptance contracts.

No real rights decision, role provisioning, feature-flag change, production
migration, source redistribution, model fit, paid calculation, remote issue
closure, push or deployment is performed by this batch.
