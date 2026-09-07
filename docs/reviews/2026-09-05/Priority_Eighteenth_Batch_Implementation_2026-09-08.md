# Eighteenth implementation batch — coordinated background jobs

Date: 2026-09-08. Local branch: `codex/sclib-research-v2`.
Baseline: `e176107` (seventeenth batch).
Priority: [EN03 / #59](https://github.com/JackZH26/SCLib_JZIS/issues/59), building
on the EN01 disposable-test safeguards and existing Timeline source-task fence.
Operational contract: [Background job coordination](../../BACKGROUND_JOB_COORDINATION.md).

## Outcome

The five existing statistics, Timeline, formula-audit, nightly-audit and history
retention loops now use durable, cross-process PostgreSQL coordination. Additive
schema head is `0059_background_jobs`. Each successful cycle commits its actual
database effects and completion record together. The administrator has an English
read-only status page at `/dashboard/admin/jobs`.

This completes a local EN03 implementation and regression-verification batch,
not production rollout, scientific acceptance or closure of the broader upgrade.
No new replicas, production backfill, public release or paid computation is run.

## Implemented safeguards

1. **Stable cycles and ownership.** Exact UTC cadence boundaries and unique
   `(job_name, scheduled_for)` identities prevent per-worker duplicate cycles.
   Configuration hashes prevent silent reinterpretation of a retained cycle.
   Dedicated session locks span both the durable claim and work transaction.
2. **Atomic effects.** Handlers cannot commit their outer session transaction.
   Statistics upserts, Timeline points/readiness, all formula-review rules and
   entire scheduled audit report sets either commit with success or roll back.
   History retention uses the original cycle's cutoff during retries.
3. **Crash and uncertain-outcome recovery.** A new owner reclaims the same
   unfinished cycle after the old database session loses its lock. A known
   failure retains a bounded backoff. A lost success acknowledgement is resolved
   from committed state without repeating the effect. Uncertain lock acquisition
   or failed unlock discards the physical connection rather than leaking a
   session lock into the pool.
4. **Monotonicity and adjacent audit comparisons.** Older unrecorded cycles
   cannot overwrite newer successes. Timeline refresh preserves committed
   timestamps/watermarks and computes against current evidence. Scheduled audit
   deltas use successful scheduled report identities and matching count semantics,
   excluding racing manual reports. Manual statistics/audit writes acquire the
   matching lock before their inputs/effects.
5. **Bounded operational visibility.** An active-administrator endpoint uses one
   bounded read-only snapshot for JWT/session validation, fresh account flags and
   status reads. It returns sanitized no-store responses and no backend IDs or
   connection details. The UI shows last success, observed lock owner, attempts,
   duration, failed/retry state, safe counters and recent history; no writer or
   force-retry control is exposed.
6. **Metrics and retention.** Low-cardinality outcome counters distinguish lock
   contention, duplicate replay, retry wait, configuration conflict and completion.
   Cycle identity and successful results are immutable; deletion/truncation and
   nonempty downgrade are refused. Earlier frozen schema modules are unchanged.

## Acceptance evidence

| EN03 acceptance | Local evidence |
| --- | --- |
| Independent processes yield one effective report set | Two real Python children compete for one cycle; only one report commits; replay preserves the exact set |
| Older refresh cannot regress a watermark | Ordered cycle admission, existing projection fence and real older-timestamp full-refresh regression |
| Crash recovery neither loses nor duplicates a cycle | SIGKILL after uncommitted effect; running claim remains, effect rolls back, fresh process commits the same cycle at attempt 2 |
| Failed refresh preserves last-good state | Real StatsCache failure/recovery and real Timeline refresh writes followed by failure leave committed snapshots unchanged |
| Audit deltas compare intended adjacent cycles | Prior successful scheduled-cycle report selected; interleaved manual, equal/future and uncommitted reports excluded |

Further tests cover pre-epoch floor arithmetic, malformed cadence/configuration
before connecting, exact replay, superseded work, callback commit/rollback abuse,
oversized/non-JSON results, retry wait without mutation, recovery of the original
scheduled instant, configuration conflict, active versus abandoned ownership,
pooled-connection cleanup and legitimate nested savepoints.

The migration harness exercises all independent 0052–0058 populated-history guards
before adding 0059 records. Empty 0059 downgrade/re-upgrade preserves those earlier
histories. Actual coordinator failure rolls back SQL effects; success and exact
replay are checked on migrated PostgreSQL. Populated 0059 downgrade refuses
without losing any application row.

## Verification

| Check | Result |
| --- | --- |
| API full post-review suite | 2,210 passed |
| New background schema / service / independent-process / pooled-recovery cases | 39 / 39 / 2 / 6 passed; included above |
| New handler / private HTTP / real projection recovery and monotonicity cases | 16 / 9 / 2 passed; included above |
| Ingestion full suite | 938 passed |
| Scripts | 268 passed, plus 36 separately reported subtests |
| Frontend source / unit suites | 35 / 252 passed |
| Distinct ordinary tests | 3,703; focused reruns not double-counted; excludes the 36 script subtests |
| TypeScript | `tsc --noEmit` passed |
| Migration rehearsal | Actual 0059 head/admission, empty populated-history round trip, atomic work/failure/replay and independent nonempty downgrade guards passed |
| Static checks | Scoped Ruff I/F and `git diff --check` passed |

The first full API run exposed a test isolation problem: a schema test deliberately
committed a current fractional-second cycle, while later coordinator tests require
exact, past cadence boundaries. The schema fixture now uses an exact historical
UTC cycle; production validation remains unchanged. A 139-case combined run and
the complete 2,210-case rerun passed. The suite retains the existing FastAPI
`regex` warning and 19 Alembic path-separator warnings; ingestion retains its 34
existing SQL-compilation-double `DISTINCT ON` warnings.

All database and Redis execution uses one-run disposable services, never an
inherited production DSN or local application `.env`.

## Operational boundaries and remaining work

- The contract is committed **database effects**, not durable external delivery.
  Redis cleanup and process metrics remain post-commit best effort. Current
  governance-sensitive Timeline responses bypass legacy Redis bodies.
- The coordinator requires direct PostgreSQL or a session-preserving proxy.
  Transaction/statement pooling is unsupported. Old uncoordinated lifespan
  writers must be drained before enabling the new implementation.
- Empty-ledger startup establishes a new coordinated baseline. Downtime coalesces
  to the latest due cycle plus retained unfinished work; it does not fabricate a
  history of every missed scheduled interval.
- Retain the deployment configuration needed to recover a hash-mismatched pending
  cycle. There is no automatic destructive history repair. Persistent failures
  require operator investigation, not fabricated terminal success.
- The status endpoint is bounded; handler timeouts are not an end-to-end bound on
  connection, claim or cleanup. Staging must measure contention, full-corpus work
  duration, service timeouts and read-fallback costs.
- This operational ledger records latest attempt state/count, not complete
  immutable attempt history or scientific provenance. It grants no source
  reinstatement, material acceptance, training-label approval or export rights.
- EN01/EN04 still need actual current-commit Linux/release-image CI evidence.
  Local native testing does not substitute for Docker runtime parity. No remote
  push, PR, merge or deployment is implied by this batch.

Next local priorities remain source/result-scoped correction and curator workflow
(SC08/UX02), typed original-versus-derived Facts lineage and scientific rendering
(RG02), and their downstream research-release/dataset gates. Real reviewed pilot,
rights review and production/cost-bearing operations require their own evidence
and authority. GitHub issue state is not changed by this report.
