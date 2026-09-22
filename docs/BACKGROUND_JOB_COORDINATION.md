# Coordinated background jobs

Status: local implementation and disposable verification, 2026-09-08.
Issue: [EN03 / #59](https://github.com/JackZH26/SCLib_JZIS/issues/59).
Schema: additive `0059_background_jobs`; policy: `background-cycle/1.0.0`.

## Scope and guarantee

The five existing API lifespan writers now share PostgreSQL cycle identities and
cross-process ownership. No new task runner product, replica, production job or
scientific approval is introduced. Existing enable/disable settings still apply.

`scheduled_for` identifies an operational schedule slot, not the historical
availability of scientific evidence. Refreshes and audits inspect data available
when they actually run or recover; never reuse this timestamp as a research
known-by date, source publication date or leakage-safe dataset cutoff.

A successful cycle means **the SQL handler effects and its success record
committed in one transaction**. A replay of that cycle performs no handler work.
An uncommitted attempt may run again after failure; this is not a claim that a
handler executes only once, nor that Redis, vector indexes or other external
systems received anything. Handlers are trusted internal SQL-only functions.

| Job | Coordinated effect | Time semantics |
| --- | --- | --- |
| `stats_refresh` | Dashboard cache upsert | Recompute current counts after ownership; publish process metrics only after commit |
| `timeline_projection` | Points and readiness/watermark | Recompute current evidence, never backdate to the recovered cycle; serialize with source-task invalidation |
| `formula_audit` | Existing formula-review rules | All rule effects commit together or roll back together |
| `nightly_audit` | Rule flags, reports and comparison counts | Stable daily UTC cycle; compare prior successful scheduled cycle reports for the same metric |
| `ask_history_prune` | Existing history-retention deletion | Fixed cutoff = original scheduled instant minus configured retention days |

Source-task requests in `0058_source_tasks` remain a different, explicitly
authorized protocol. The new coordinator does not automatically enqueue or
execute that queue, reinstate sources, publish claims or modify scientific
labels. A source hold can still force the Timeline's current-raw fallback even
when an older projection exists. A failed refresh preserves committed projection
rows, not permission to serve evidence that current governance excludes.

## Identity, ownership and atomic completion

1. A cycle is identified by `(job_name, scheduled_for)`. Times use exact UTC
   cadence boundaries, with an explicit daily offset where applicable. The
   policy, interval, offset and job configuration have a canonical SHA-256 hash.
   An explicit replay must be aligned and not in the future according to the
   database clock.
2. A dedicated physical database connection acquires a **session advisory lock**
   for that job. The lock spans the claim transaction, handler transaction and
   failure recording. There is no expiring lease that can admit a new writer
   while the old database session still owns its lock.
3. The coordinator commits a running claim with owner UUID, backend identity,
   attempt number and start time before calling the handler. This makes a
   crashed attempt discoverable without prematurely committing its effects.
4. A fresh outer transaction runs the handler and writes the success result.
   Callbacks cannot commit the outer session transaction themselves. Rule-level
   savepoints are allowed. Results must be bounded JSON objects.
5. On a known failed transaction, the effects roll back and a separate transaction
   records an allowlisted failure code and retry time. On uncertain connection
   or commit outcome, recovery must inspect the retained cycle rather than
   inventing a success/failure result or rerunning the effect immediately.
6. The session lock is explicitly released before a connection can return to its
   pool. Uncertain acquisition or failed release invalidates the physical
   connection; ordinary transaction rollback does not release session locks.

Fixed lock keys `589017031` through `589017035` are reserved in the model module.
Timeline refresh additionally obtains the existing `580017026` source-task fence
before reading projection state. Source-task invalidation does not acquire the
background-job lock, avoiding a reversed lock order. Manual statistics refresh
uses the statistics transaction lock before computing inputs. Manual audit work
also shares the nightly lock at its transaction boundary.

Database triggers require current-backend ownership of the proper lock, enforce
status transitions and immutable cycle identity/configuration, reject deletion
and truncation, and prevent changes to completed success records. PostgreSQL's
lock inventory cannot distinguish transaction from session advisory ownership;
the trusted coordinator, not the trigger alone, provides the session-lifetime
guarantee. This is not a sandbox for arbitrary SQL or a hostile database owner.

**Deployment precondition:** use direct PostgreSQL connections or a
session-preserving proxy. Transaction/statement pooling is unsupported: the
claim commit and handler transaction must remain on the same physical backend.
Do not enable this coordinator through a transaction-mode connection pool merely
because ordinary request queries work through it.

## Retry and restart behavior

- A contender returns `busy` without creating an attempt or running a handler.
- An already successful exact cycle returns `already_succeeded` unchanged.
- The oldest unfinished due cycle takes precedence over a newer requested cycle.
  Crashed `running` rows are reclaimed only after acquiring the job lock. Retry
  increments the attempt count, changes the owner and retains the original cycle.
- Failed attempts wait 30, 60, 120, 240 and then at most 300 seconds. Retry is
  ongoing while the job is enabled; there is no false terminal success after a
  fixed number of failures. Operators must investigate persistent failure.
- A configuration-hash mismatch returns `configuration_conflict` without
  silently reinterpreting retained work. Reconcile by restoring the original
  configuration and draining unfinished cycles before changing cadence/policy.
  There is no browser control to edit/delete history or force past this guard.
- A previously unrecorded older invocation cannot overtake a newer successful
  cycle: it returns `superseded` without manufacturing an old success record.
  An existing old success still replays as `already_succeeded`. Timeline timestamps
  and source watermarks also retain the maximum committed value under the
  projection fence.
- Polling is bounded to every 30 seconds or the shorter configured interval.
  Startup processes the latest due cycle and any retained older unfinished work.
  It **does not fabricate one row for every missed interval during downtime**;
  this coalescing policy is appropriate to refresh/audit/retention jobs, not
  general event delivery.

All replicas must use the same cadence and policy configuration. A rolling policy
change needs operational coordination; a per-cycle hash is not a deployment
configuration registry. Restarting the process alone does not resolve a retained
configuration conflict. If completion uncertainty persists, inspect the same
cycle after restoring connectivity; do not issue ad hoc row repairs.
Retain versioned deployment configuration snapshots: the ledger's hash alone
cannot reconstruct the original cadence or handler policy needed for recovery.

Mixed-version rollout is not protected: old API processes do not participate in
the new job-lock protocol. Drain or disable those old lifespan writers before
enabling the coordinated versions. With an empty new ledger, startup runs the
latest due cycle even if an old writer recently ran it; this establishes a fresh
coordinated baseline and does not deduplicate pre-upgrade execution history.

## Observability and bounds

The administrator-only `GET /v1/admin/background-jobs` and English page
`/dashboard/admin/jobs` show all five jobs, last success, oldest unfinished cycle,
current observed owner, attempts, duration, retry/failure state and 20 recent
cycles per job. They are read-only. Authorization and data use a fresh read-only
repeatable-read snapshot, with 5-second statement and 10-second operation bounds;
responses are private/no-store. Database errors are sanitized. Backend process
IDs and connection details are not returned.

`active_owner_id` is shown only when the recorded backend currently holds the job
lock. It is a point-in-time observation, not proof of process health after the
query. Cycle tables record the latest attempt state and total attempts, not an
immutable log of every failed attempt. Duration describes that latest attempt.

Prometheus exposes low-cardinality
`sclib_background_cycle_results_total{job,outcome}` and
`sclib_background_cycle_duration_seconds{job,outcome}`. Outcomes distinguish
success, failure, busy, duplicate replay, retry wait, configuration conflict and
superseded work. Metrics are process-local and can reset on restart; durable
cycle status is authoritative. No cycle IDs, formulas, users or exception strings
become metric labels.

The default callback/result-validation timeout is 900 seconds (supported override
up to 3600 seconds), with a 60-second per-statement timeout inside the handler
transaction. These do not bound the entire connection/claim/failure-recording or
lock-cleanup lifecycle; those phases still depend on database/driver connection
and server timeouts. Results have both a 16-KiB
canonical service bound and a 16-KiB PostgreSQL JSONB-text bound; a value exceeding
either fails atomically. Configuration is bounded to 4 KiB. These are initial
operational limits, not a measured production latency SLA.

Legacy Timeline Redis cleanup remains best effort after a new successful SQL
commit, with 200-key batches and a 10-second overall budget. It is not durably
retried or part of the SQL receipt. Current governance-sensitive Timeline reads
bypass those Redis response bodies; cleanup failure must not be described as a
guarantee that such bodies are fresh. Do not re-enable those cached reads without
a separate currentness/delivery protocol.

## Migration and acceptance

0059 adds the operational table and guards only; it performs no production
backfill and changes no earlier frozen schema modules. Empty downgrade/re-upgrade
preserves earlier populated histories. Once cycle records exist, downgrade
refuses; deletion is not an acceptable rollback procedure. Use the existing
explicit migration/admission workflow, never API-startup mutation.

Disposable PostgreSQL tests include real independent Python processes competing
for one cycle, SIGKILL after an uncommitted effect, fresh-owner recovery, exact
replay, callback rollback, cache/projection preservation and migration round
trips. Synthetic examples establish implementation behavior, not production
capacity, scientific validity or human acceptance.

Before rollout: obtain current-commit CI evidence, review configuration consistency
across replicas, rehearse restart/failure and migration on approved staging,
measure contention and runtime at actual corpus size, and separately approve
production changes. No replicas should be added merely because local tests pass.
