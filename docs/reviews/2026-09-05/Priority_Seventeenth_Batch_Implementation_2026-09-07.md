# Seventeenth implementation batch — durable source tasks and atomic invalidation

Date: 2026-09-07. Local branch: `codex/sclib-research-v2`.
Baseline: `1ac4fca` (sixteenth batch).
Priority: [SC08 / #66](https://github.com/JackZH26/SCLib_JZIS/issues/66).
Contract and internal operation guide: [Source task execution](../../SOURCE_TASK_EXECUTION.md).

## Outcome

The prior read-only impact inventory now has a durable exact-version request and
attempt protocol with one real, narrowly defined executor: **Timeline readiness
invalidation**. Schema head is `0058_source_tasks`. Success and the actual SQL
effect are atomic; success is not claimed for a merely created task or planned
refresh. This batch is local development and disposable verification only.

The executor changes only an existing readiness singleton's `schema_version` to
`0`. The reader then uses its existing current raw-backed fallback, while the independent
periodic refresher may later rebuild. Missing/already-invalid readiness is an
accurately recorded no-op. Points, raw evidence, source status, scientific claims,
frozen releases, timestamps, watermarks and counts are not rewritten.

## Implementation

1. **Durable bindings.** Immutable request rows retain the exact event, source
   snapshot, actual canonical impact inventory bytes/hash, fixed action version,
   explicit requester grant and idempotency key. No browser-authored impact graph
   or self-reported checksum can replace the trusted service's reinspection.
2. **Bounded attempt history.** At most five recorded attempts form a strict
   predecessor chain. Outcomes distinguish success, obsolete source/graph,
   blocked authorization/inspection and retryable failure/exhaustion. A terminal
   request cannot receive another attempt.
3. **Atomic execution.** The successful INSERT trigger rechecks current source
   and original requester authority, invalidates readiness itself and derives
   effect flags. Invalid DML cannot forge a successful no-effect receipt. The
   service also rederives the graph before execution; SQL validates declared
   bytes/envelope, not the entire dependency graph.
4. **Concurrency.** A shared task/projection epoch and try-lock fence serialize
   invalidation against both Timeline tables. The ordinary READ COMMITTED
   refresher obtains the fence before reading build inputs. Readiness reads
   reload ORM state; stale RR/SERIALIZABLE writers abort.
5. **Controlled operation.** Internal writes require a clean SERIALIZABLE
   session, explicit curator authority, default rollback rehearsal and an
   explicit outer commit. Statement/operation time bounds limit work. No HTTP
   writer, automatic enqueue, new worker, scheduler or durable running lease is
   silently introduced.
6. **Idempotency and recovery.** Replays return historical records without
   re-invalidating a subsequent rebuild. An aborted transaction cannot create a
   receipt. A trusted caller can report an allowlisted transient failure after
   rollback in a fresh transaction with the exact predecessor binding; this is
   attributed reporting, not independent SQL-error attestation.
7. **Inspection and retention.** A private read-only task-history endpoint shows
   bounded records without the inventory text or raw values. Authentication and
   live explicit research roles share its snapshot. Responses are no-store;
   audit-bound requester/executor identities survive grant revocation and block
   destructive account deletion.
8. **Migration safety.** 0058 creates no live tasks or data backfill. Nonempty
   task history blocks downgrade. Older ledgers' independent downgrade guards
   and 0057's populated-history index round trip remain separately tested.

## Scientific and operational limits

- Negative provenance status is not evidence that a material cannot superconduct.
  This batch changes no scientific acceptance, label eligibility or source hold.
- Impact identity is a relationship snapshot, not hashes of every scientific
  value and not proof of complete feature/event lineage.
- A current source version does not freeze future relationships. An execution
  receipt does not promise future cache readiness or cross-system currentness.
- A source-specific task invalidates global readiness conservatively; staging
  must assess the resulting fallback load and shared epoch contention.
- Redis, vector indexes, saved answers, future ML membership, public historical
  notices and positive scientific reinstatement are not executed by this target.
- Existing periodic refresh and its best-effort Redis invalidation are separate;
  this receipt neither proves either operation ran nor establishes a freshness SLA.
- Immutable attempt counts exclude unrecorded delivery/connection failures. There
  is no automated worker/retry delivery in this batch.

## Verification

| Check | Result |
| --- | --- |
| API full suite | 2,097 passed |
| New schema / task service / projection-concurrency / task HTTP cases | 35 / 25 / 8 / 7 passed; included in the full API count |
| Ingestion full suite | 938 passed |
| Scripts | 266 passed, plus 36 separately reported subtests |
| Frontend source / unit suites | 35 / 247 passed |
| Distinct ordinary tests | 3,583; focused reruns not double-counted; excludes the 36 script subtests |
| TypeScript | `tsc --noEmit` passed |
| Migration rehearsal | Actual 0058 head/admission, atomic invalidation/retry/rollback, populated empty-queue round trip and all independent nonempty-history guards passed |
| Static checks | Scoped Ruff I/F and `git diff --check` passed |

The final API suite retains the existing FastAPI `regex` deprecation and 19
Alembic legacy path-separator warnings. Ingestion retains 34 PostgreSQL
`DISTINCT ON` warnings from its SQL-compilation doubles. No new failure remains.
An initial full API run exposed one older fake session missing the new
`populate_existing` keyword; the test double now accepts and asserts it. A fresh
full run passed without weakening production readiness reload behavior.

Focused tests cover actual-byte hashing, exact Paper/Work bindings, authorization
and revocation, source/graph drift, scope failures, bounded retries, terminal
chains, historical replay, same-session identity reload, lock order/contenders,
stale snapshots, no-op effects, atomic rollback, private API errors and identity
retention. Synthetic fixtures are isolated from real databases.

The migration rehearsal executes actual enqueue, failure, retry and success
services on migrated PostgreSQL, compares all application rows around rehearsals,
checks readiness-only changes and validates both empty and nonempty downgrade
boundaries. Old protections are exercised before creating any new queue history,
so a 0058 refusal cannot mask an earlier ledger's missing guard.

## Next priority

Build reviewed curator enqueue/execute controls and bounded worker delivery,
including commit-uncertainty handling. Add separately versioned target receipts
for Redis/vector/ML/historical notices and measure rebuild completion and lag.
Broader lineage, result-scoped mixed-source admission, RG02 source validation,
canonical scientific supersession and reviewed staging cases remain open.

SC08 is not closed. No GitHub issue state, production data or deployment has been
changed; no remote push is included in this local batch.
