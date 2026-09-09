# Exact-source tasks — bounded Timeline cache invalidation

Updated: 2026-09-09. Task schema: `0058_source_tasks`; application schema head:
`0067_scientific_adjudication` (this operator workflow adds no migration).
Issue: [SC08 / #66](https://github.com/JackZH26/SCLib_JZIS/issues/66).
Preconditions: [source lifecycle](SOURCE_LIFECYCLE_LEDGER.md) and
[declared-scope impact inspection](SOURCE_IMPACT_INSPECTION.md).

## Delivered outcome and strict meaning

An explicitly authorized curator can now persist an exact-source impact request,
execute one bounded database action, inspect its immutable receipt, and record
allowlisted transient failures for a subsequent controlled retry. Internal
mutation services default to `dry_run=True` and never own the outer commit.
The private [operator workflow](#private-preview-commit-and-recovery-workflow)
now exposes explicit preview-first HTTP writers. There is no new scheduler or automatically enqueued
work. Existing periodic Timeline refresh remains a separate operation.

The only action is `timeline-cache-invalidation/1.0.0`:

- If the Timeline readiness singleton exists, set **only** its `schema_version`
  to `0`. If absent or already invalid, acknowledge the safe no-op accurately.
- Do not create a missing singleton, change any Timeline point, advance a
  watermark, change timestamps/counts, or announce a successful rebuild.
- The existing Timeline reader falls back to current raw-backed extraction when readiness
  is absent or incompatible. Existing source and material holds still apply.
- A later ordinary refresh sees version `0` and takes the existing full-rebuild
  path. This request neither runs nor acknowledges that potentially unbounded job.

Invalidating the global readiness singleton is deliberately conservative: a
source-specific request can make the whole projected Timeline unavailable until
rebuild. It may increase fallback read cost, including for unrelated materials.
This is a bounded safety action, not a selective incremental regeneration engine.
No source is scientifically reinstated, and no raw or frozen evidence is removed.

## Records and state transitions

| Record | Essential binding | Protection |
| --- | --- | --- |
| `source_task_requests` | Exact lifecycle event ID/hash and source snapshot hash; impact version/hash and actual canonical UTF-8 inventory text; fixed action version; requester and exact curator grant; actor-scoped request key | Append-only; immutable source/user/grant FKs; generated audit hash and database timestamp |
| `source_task_attempts` | Request ID; consecutive number; exact previous attempt ID; executor and curator grant; request-scoped execution key; status/outcome and derived effect flags | At most 5 recorded attempts; unique root/successor; no append after terminal state; generated audit hash/timestamp |
| `source_task_epoch` | Singleton serialization fence shared with Timeline writes | Transaction advisory lock plus epoch update; stale RR/SERIALIZABLE writers fail |

Requests retain the actual deterministic `source-impact/1.0.0` body, excluding
the transient `observation` and outer `inventory_sha256`. The text is bounded to
1 MiB. Its SHA-256 is checked against actual bytes. Request/attempt record hashes
cover all scalar columns except `created_at`, `record_sha256` and `inventory_json`;
the latter is independently bound by its included inventory hash. The service
also checks canonical JSON encoding on replay/read.

SQL independently verifies inventory version/event envelope, current lifecycle
event/live source hash and active explicit actor grants. **SQL does not rebuild
the full impact graph.** The trusted service recomputes that graph before enqueue
and before success. Direct SQL access is a trusted backend boundary, not a public
scientific-validation API; hashes do not themselves prove scientific correctness.

| Stored state | Outcome | Next action |
| --- | --- | --- |
| `queued` (derived: no attempts) | No execution recorded | Explicit controlled execution |
| `succeeded` | `timeline_cache_invalidated` | Terminal for this request; inspect the separate refresher for rebuild status |
| `obsolete` | `source_changed` / `inventory_changed` | Terminal; inspect fresh source/graph and create a new exact request |
| `blocked` | `request_authority_unavailable` / `scope_limit` / `inventory_unavailable` | Terminal; resolve the condition, re-inspect and create a new request |
| `retryable_failure` | `database_busy` / `statement_timeout` / `serialization_failure` | Explicit retry with a new execution key, never automatic |
| `exhausted` | Fifth recorded transient failure | Terminal; operator investigation required |

These are recorded attempts, not an independently measured count of every
delivery, crashed process or failed connection. A DB outage may prevent recording
a failure. No record is fabricated in an aborted transaction.

## Transaction and concurrency protocol

1. Use a clean dedicated **SERIALIZABLE** session. Identity must come from a
   trusted authenticated caller; a caller-supplied UUID or legacy admin/reviewer
   flag is not a research grant.
2. Acquire locks in the fixed order `540017026 → 550017026 → 560017026 →
   580017026` (scientific integrity, publication/authority, source lifecycle,
   task/projection). Try-lock contention fails promptly; epoch updates fence stale
   snapshots. Current source rows are also checked/locked at SQL insertion.
3. Enqueue only after recomputing and matching the operator's expected inventory
   hash. Persist the resulting exact bytes and actor grant, not a browser-authored
   task plan.
4. Execute only after verifying the immutable request/chain, current executor,
   original requester's **same** still-active grant, current source head and fresh
   impact fingerprint. A replacement grant does not revive the original request.
5. The attempt INSERT trigger performs successful readiness invalidation and
   derives `state_present` / `state_changed`. Effect and receipt succeed or roll
   back together, including a failure after the effect but before transaction end.
6. Commit the outer transaction explicitly only after a successful service return.
   Returned `committed=false` is intentional; `requires_outer_commit=true` means
   changes remain provisional. Default rehearsals roll back their savepoint,
   including ledger rows, readiness and epoch changes.

`executed_now=true` means this invocation completed the bounded SQL action
provisionally in the caller's transaction, not that it durably committed. Only
successful outer commit establishes persistence. A successful safe no-op can
also report `executed_now=true`; inspect `state_changed` for an actual change.

Both Timeline tables have shared lock guards for INSERT, UPDATE, DELETE and
TRUNCATE. The regular refresher obtains the same lock **before its first state or
material read**, while retaining READ COMMITTED compatibility. Projection reads
reload readiness rather than trusting an earlier ORM identity-map value.

The service limits statements to 5 seconds within a 10-second operation timeout
and restores the caller's statement timeout after a successful non-dry-run call.
The caller still owns outer-transaction lifetime and rollback. There is no durable
`running` lease: a crash before commit leaves no partial effect or success receipt.

This is a snapshot-scoped relationship check, not a global forever-current graph
fence. Independent material/identity/chunk writes may create later dependencies.
The receipt acknowledges the bounded action at its execution snapshot; it cannot
promise future readiness, global propagation or a completed rebuild.

## Internal operation example

The following illustrates a trusted curator handler, not a runnable production
backfill. `trusted_actor_id`, event binding and inventory hash must be supplied
through the authenticated, reviewed workflow. Each operation owns a fresh outer
transaction; this module does not grant roles or fetch source documents.

```python
from sqlalchemy.ext.asyncio import AsyncSession
from models.db import get_engine
from services.source_tasks import enqueue_source_task, execute_source_task

engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
async with AsyncSession(engine) as db, db.begin():
    queued = await enqueue_source_task(
        db, actor_user_id=trusted_actor_id,
        event_id=reviewed_event_id,
        expected_event_sha256=reviewed_event_hash,
        expected_inventory_sha256=reviewed_inventory_hash,
        request_key=unique_request_key,
        dry_run=False,  # omit this argument for a rollback rehearsal
    )

async with AsyncSession(engine) as db, db.begin():
    receipt = await execute_source_task(
        db, actor_user_id=trusted_actor_id,
        request_id=queued["request"]["id"],
        expected_request_sha256=queued["request"]["record_sha256"],
        execution_key=unique_execution_key,
        dry_run=False,
    )
```

An enqueue key is unique per requester; changing its event/hash/inventory binding
is rejected. Execution keys are unique per request and bound to the executor.
Replaying a known key returns its **historical** receipt and `executed_now=false`,
even after a later rebuild or source revision. It does not re-invalidate anything.
A new key cannot append to a terminal request. A new attempt after a recorded
transient failure must use a new execution key.

After an execution SQL failure, roll back and close that transaction. A trusted
runner may then call `record_source_task_failure` in a fresh SERIALIZABLE
transaction, with the same failed execution key and the exact prior attempt ID
and hash (both absent for a root). It accepts only the three transient codes
above, no raw exception/DSN text. This is an attributed runner report, **not an
independent attestation of the original SQL error**. A concurrent success/changed
head prevents appending a contradictory failure. If commit outcome is uncertain,
first resolve the same execution key; do not invent a new execution or retry key.

## Private inspection and explicit non-claims

`GET /v1/ml/source-lifecycle/tasks/{request_id}` returns bounded request metadata,
at most five attempts and the derived stored state. It does not return the 1 MiB
inventory text or raw scientific source values. The existing
`ML_FOUNDATION_PUBLIC_ENABLED` kill switch defaults off; JWT and a current explicit
research role are checked in the same read-only REPEATABLE READ snapshot. All
responses, including errors, are `private, no-store`; no ETag/304 bypass exists.
The newer curator-only writers and recovery reads below use a dedicated
authentication/session check, not the broader research-role read admission.

Receipt semantics explicitly report:

- `currentness=historical_receipt_not_live_projection_state`;
- `timeline_rebuilt=false`, `propagation_complete=false`;
- `external_cache_invalidated=false`;
- `scientific_acceptance=false`, `ml_training_approved=false`,
  `source_reinstatement=false`.

The periodic refresh's existing best-effort Redis invalidation is separate from
this transaction. Redis responses can remain until their existing invalidation
or expiry; vector indexes, saved answers, ML membership and published historical
notices are not acknowledged or changed. This action alone is not a complete
source-correction delivery guarantee or freshness SLA.

## Private preview, commit and recovery workflow

The dashboard page `/dashboard/research/source-tasks` supports source inspection,
explicit request creation, exact-head execution and original-key outcome lookup.
All default UI copy is English. A legacy administrator or reviewer flag does not
authorize these actions. The feature kill switch still defaults off.

Under `/v1/ml/source-lifecycle/task-operations`:

| Endpoint | Contract and effect |
| --- | --- |
| `GET /capabilities` | Current verified account plus explicit curator grant; returns the authenticated actor/grant and fixed negative semantics. Unauthorized actors receive 403, not reviewer-derived write access. |
| `POST /preview` | Closed `source-task-operation/1.0.0` request, real rollback rehearsal, deterministic preview hash. No committed rows, cache change or guard-epoch change. |
| `POST /commit` | Exactly `{request, expected_preview_sha256}`; rechecks operation, actor/grant, source/inventory and exact attempt head inside the write fence. |
| `GET /requests/{request_key}` | Original actor-scoped enqueue receipt. Does not substitute current task status or a later attempt for the original operation. |
| `GET /requests/{request_id}/executions/{execution_key}` | Exact historical execution receipt for that executor. Does not return whichever attempt happened most recently. |

An enqueue request contains only `version`, `operation="enqueue"`, `request_key`,
`event_id`, `expected_event_sha256` and `expected_inventory_sha256`. Bind these
to the inspected lifecycle event and actual impact response; do not invent a
browser-authored impact inventory.

An execute request contains only `version`, `operation="execute"`, `request_id`,
`expected_request_sha256`, `execution_key`, `expected_predecessor_id` and
`expected_predecessor_sha256`. The predecessor fields are both null for a root,
or the exact current retryable attempt's ID/hash. A terminal request cannot acquire
a new successor. The browser cannot record arbitrary database-failure claims;
the trusted failure-report service remains internal.

Preview hashes bind the normalized operation, actor and exact grant, predicted
record status/outcome and fixed semantics. They exclude rolled-back generated
IDs, timestamps and record hashes. An unchanged preview is reproducible across
transactions. The hash is a consistency token, **not authentication, a signed
approval or proof that a preview HTTP call occurred**. Authorization is checked
independently on every request, including before consuming an upload body.
The early read-only admission transaction is closed before streaming the body;
the writer then reauthenticates the JWT/session and curator in a **fresh**
transaction. Repeating a role query in the original snapshot would not detect a
session-version change during upload, especially for a historical replay with no
INSERT trigger. Both new writes and replays use the fresh admission protocol.

The writer uses a dedicated UTC SERIALIZABLE transaction and the existing
`540 → 550 → 560 → 580` lock/epoch fence. The real rehearsal rolls back a nested
savepoint while the outer fence stays held through the actual write. A changed
head or preview fails closed; no unlocked preflight-to-insert gap is introduced.
An obsolete or blocked attempt can be successfully committed as an audit record;
`committed=true` must not be read as successful invalidation.

The router rolls back the entire dedicated transaction for both preview and
durable replay, including any provisional epoch increments. A replay therefore
does not re-invalidate a Timeline rebuilt since the original receipt. Only after
a new outer transaction actually commits can the HTTP response acknowledge
`committed=true` and `requires_outer_commit=false`. Internal service returns
remain provisional and require the documented caller protocol.

Request JSON is bounded to 8 KiB (the commit envelope to 8 KiB + 256 bytes), with
closed fields, canonical UUIDs, lower-case SHA-256, bounded idempotency keys,
strict UTF-8, duplicate-key rejection and bounded nesting. Responses are bounded
to 32 KiB. Two in-process nonblocking slots, a 20-second route deadline,
10-second operation deadline and 5-second SQL statements bound local resource use;
these are not fleet-wide capacity limits or an operational propagation SLA.
Errors are static and private/no-store; raw SQL, connection details and supplied
exception text are never browser error messages.

For a timeout, cancellation, connection loss or malformed success response after
submission, the outcome is **unknown**. Retain the original operation key and
inspect its exact outcome. A 404 means only “not found in the current snapshot”;
it does not prove that an in-flight transaction failed. Do not auto-generate a
new key, auto-submit another mutation, or fabricate a failure attempt. Recovery
may return a historical grant ID: current curator admission permits inspection,
but does not revive the original requester's revoked authority or source support.
The UI keeps recovery state only in the mounted page's memory and warns on
browser unload while submission/recovery is unresolved. It stores no source
payload or recovery key in browser storage. This is not durable client recovery:
reload, closing the tab or client-side navigation may discard the key, and
browser unload warnings are not a universal navigation guard. Retain the shown
original key securely before leaving; the manual lookup fields accept it later.

## Migration, rollout and next gates

Migration 0058 adds three tables, guards and functions; it creates no tasks,
changes no projection data and performs no source backfill. Upgrade requires a
write lock on both Timeline tables during upgrade; no duration is guaranteed.
Benchmark lock duration and global epoch contention in staging. Apply the schema before starting this code: the
existing read-only startup schema admission rejects a mismatched head.

Empty-ledger downgrade removes only this migration's projection guards and
objects. Any request/attempt history makes downgrade refuse under exclusive
locks; do not delete the audit ledger to force rollback. Requester/executor
identity is retained after grant revocation; audit-bound account deletion returns
a controlled conflict without erasing private account data.

Next priority: bounded worker delivery; separately versioned
Redis/vector/ML/historical-notice targets; broader dependency coverage; monitored
rebuild results and propagation lag. Real reviewed source cases, rights review,
scientific supersession/reinstatement and production rollout remain unfinished.
SC08 is still open. This local batch does not change any live issue or production
data and does not deploy or push code.
