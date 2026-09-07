# Twelfth implementation batch — research freeze and schema lifecycle

Date: 2026-09-07. Branch: `codex/sclib-research-v2`.
Base checkpoint: `602f40f` (ML03 shadow import).

Priority: [ML04 #64](https://github.com/JackZH26/SCLib_JZIS/issues/64), with
the independently testable schema-lifecycle boundary from
[EN02 #58](https://github.com/JackZH26/SCLib_JZIS/issues/58).
This is local implementation and synthetic verification, not closure of either
issue, a real canary, deployment, source redistribution or training approval.
No production database, website, vector index or source archive was changed.

## Why this batch precedes public research and ML datasets

A source import receipt records what was loaded; it does not freeze every input
that determines a training example. A manifest hash also does not prove that an
existing feature, result property or evidence link was not omitted. This batch
adds database-derived dependency enumeration, immutable historical copies,
actual artifact-byte verification and shared concurrency guards.

The resulting object is deliberately an **internal integrity capsule**, not a
scientifically approved public release. This distinction keeps pending source
interpretations out of accepted training labels while the remaining scientific,
permission and dataset contracts are built.

## Delivered implementation

| Area | Implemented locally | Not implied |
| --- | --- | --- |
| Schema 0054 | Four additive tables for serialization epoch, capsules, row pins and append-only notices | No duplicate canonical Tc registry or data backfill |
| Closure | Fixed 28-table contract, real FK/composite references, all owned inputs and selected source/revision/receipt dependencies | No discovery of undocumented scientific inputs inside arbitrary text/JSON |
| Atomic freeze | Clean SERIALIZABLE session, shared nonblocking writer guard, rollbackable dry run, exact processing review and committed-history replay | No automatic outer commit, authenticated reviewer UI or production execution CLI |
| Database integrity | Actual-row pin matching, deferred completeness, concurrent-cycle checks and frozen-row/owned-child guards | Hashes are not scientific truth or authority |
| Offline verification | Independent expected manifest hash, bounded canonical manifest and actual byte leaves, strict fields/references/DAG checks | No source permission or legal clearance from a checksum |
| Historical notices | Reviewed withdrawal/correction/supersession records without rewriting the original manifest | No automatic propagation to caches, public warnings or current eligibility |
| API schema lifecycle | Read-only entrypoint/lifespan admission, one explicit migration job, shared session lock and separate credential path | Production roles/grants are not provisioned or audited by this code |
| Rollout protocol | Expand, shadow, parity, read cutover, read-model rollback and later contract stages | No zero-downtime guarantee or rehearsed production cutover |

### Scientific and source dependency capture

An existing dataset must contain 1–100 examples with an exact declared row count.
The closure follows examples and feature inputs to claims, QC, states, structures,
events, properties, evidence, source snapshots, runs and artifacts. It retains
referenced catalogue rows and explicitly selected source witnesses or shadow
import receipts/memberships. Receipt inventories are traversed, not treated as
opaque hashes. Policy artifacts and an isolated processing-review artifact are
separate roots.

The complete bounded row set is retained with full-row hashes, independently of
any existing interpretation/file hashes. Source capture and evidence-artifact
bytes must actually be supplied and verified. The fixed specification matches
all 28 current ORM tables, including nullable fields, types, exact composite
foreign keys and ownership rules; user-profile records are deliberately excluded.
Opaque reviewer IDs do not authenticate a person.

The database independently enumerates required owned children. A direct SQL
writer cannot omit an existing input/property/evidence row by shortening both
its manifest and pin list. Pins require the actual SQL row and the parent's
creation transaction. Release history rejects UPDATE, DELETE and TRUNCATE;
populated history prevents destructive downgrade.

Protected research writers use a shared advisory lock and serialization epoch.
This prevents stale higher-isolation snapshots from permitting concurrent
derivation cycles or a mixed freeze. Parent-run, parent-structure and event
supersession cycles are checked separately from scientific `derives_from` edges.
Reciprocal contextual/support links are not incorrectly classified as derivation
cycles. A new source snapshot may capture an old event without modifying an old
snapshot's memberships.

Catalogue rows are immutable within the capsule but remain mutable in the live
catalogue, without the global research-writer lock. Thus a current source hold or
retraction is not blocked by historical capture. Historical verification does
not reassess present-day admissibility; that separation must remain explicit in
downstream consumers.

### Review and bounded operation

Preview is savepoint-rolled-back, including epoch bookkeeping. A separately
registered processing document binds the exact preview. The final freeze
requires that document's real canonical bytes, consistent artifact metadata and
strict approval flags. Any dependency drift invalidates the reviewed preview.
The operation forces deferred completeness checks even during dry runs, verifies
post-write pins, and never commits the caller's outer transaction.

Retries create no duplicate capsule or pins. A successful live retry can advance
technical epoch bookkeeping but not scientific history. Reviewed historical
notices retain exact document/reference bindings; inspection explicitly reports
that external notice files and reviewer authority are not independently
rechecked/authenticated in that read.

Caps are 100 examples, 1,000 rows, 200 distinct byte artifacts, 8 MiB per manifest
or leaf and 64 MiB combined. Expanded SQL JSON sizes are checked before body
transfer, including a deduplicated cumulative row budget. This bounds client
capture, not PostgreSQL CPU/TOAST serialization or production lock contention.
Representative performance/retry measurements remain necessary.

### Migration and startup separation

API startup only checks exact schema-head equality, both through the container
entrypoint and direct ASGI lifespan, before background writers start. It cannot
create or stamp a version table. Missing, stale, newer, ambiguous or unavailable
schema state blocks admission, as does an active migration.

Online Alembic entrypoints share a nonblocking session lock. Session scope survives
the historical concurrent-index migration's autocommit boundary. The dedicated
Compose migration service uses the same verified API image but receives no API
environment file, application data/GCP mounts or public port. Production requires
a separately provisioned migration-only database credential file.

Deployment retains backup/image verification and smoke gates; migration and
runtime-credential schema checks must pass before replacing the API. Failure
does not prove that all earlier DDL rolled back. Strict head admission also means
an older image cannot simply restart on a newer schema: normal rollback changes
the compatible read model, not historical schema/evidence.

Released migrations and their frozen dependencies cannot be modified in place.
In particular, `services/research_release_spec.py` generates part of 0054's SQL;
future fields require a new versioned specification/module and migration.

## Verification record

All database tests used capability-checked disposable native PostgreSQL/Redis.
The actual migration rehearsal upgraded through Alembic, not `create_all`, then
ran a complete synthetic preview/review/dry-run/freeze/commit/replay/inspect flow.
It verified exact schema admission, original-record preservation, empty-schema
round trips and nonempty correction/source/import/release downgrade refusal.

Final integrated checks:

| Check | Result |
| --- | --- |
| API full suite | 1,663 passed |
| Ingestion full suite | 905 passed |
| Scripts | 164 passed, plus 36 separately reported subtests |
| Frontend source / unit suites | 35 / 245 passed |
| Total ordinary tests | 3,012 passed; excludes the 36 script subtests |
| TypeScript | `tsc --noEmit` passed |
| Migration rehearsal | Actual head/admission, empty round trips, legacy preservation, migrated-schema freeze/replay and populated-history downgrade guards passed |
| Static checks | Scoped changed-module Ruff I/F and `git diff --check` passed |

The API additions comprise 89 database/schema-contract cases, 52 freeze/service
and bounded-input cases, and 22 lifecycle cases. The full run reports one
existing FastAPI `regex` deprecation warning and 19 Alembic legacy path-separator
configuration warnings; no test failed. Tests exercise direct SQL omission and
tampering, two-session opposing edges, stale serialization, freeze/write races,
real review bytes, full dry-run rollback, identical replay, live catalogue
governance updates, and notice forgery rejection.

No real Linux/Docker CI, production role separation, live browser acceptance or
representative staging/load validation is claimed. The frontend was not changed;
English-default source checks remain part of its regression suite. Disposable
services and their temporary data were removed by the guarded runner.

## Remaining acceptance gates and next priority

ML04 and EN02 remain open for full acceptance. In particular:

1. **ML07 / #68 — next P1 implementation:** enforce fail-closed research access
   across lists, direct IDs, counts, manifests and downloads. Neither a feature
   flag nor a legacy `frozen` status can authorize disclosure. Add recursive
   typed export allowlists, explicit source permissions and separately audited
   curator/reviewer/publisher decisions. Internal capsules remain non-public.
2. **Canonical revision and correction workflow:** unresolved live canonical rows
   must not be frozen if they are expected to receive in-place scientific
   approval later; pinning intentionally prevents that update. Until reviewed
   revision/promotion contracts exist, use authorized isolated clones for
   diagnostic exercises. Then complete SC08 propagation and independently
   freeze a legitimately corrected successor without changing old history.
3. **RG02 / #65 and source contracts:** distinguish original from derived Facts,
   prevent circular evidence, and retain corrected source-review/availability
   decisions before temporal datasets rely on them.
4. **ML08 / #54 — human evidence gate:** perform the approved 60-event pilot,
   record missingness and curation effort, and retain unresolved judgments.
   Synthetic regression fixtures do not increase the count of reviewed events.
5. **Operational acceptance:** rehearse exact old/new images, live-role grants,
   migration contention, resource costs and read-model rollback on an authorized
   staging clone. EN03 single-executor jobs and EN05 performance/cancellation can
   proceed as independent engineering work. No production run is authorized by
   this batch.
6. **Later ML delivery:** ML05 validated properties and ML06 task-specific
   temporal/split/dependency-leakage gates precede ML09 baselines and AL01 policy
   evaluation. RPS remains research priority, not superconductivity probability
   or a calibrated cross-family utility claim.

The old dataset `status=frozen` path is not replaced by this batch, task/registry
artifact content is not scientifically validated, and public correction/read
cutover is not implemented. These are visible release restrictions, not waived
acceptance conditions. No GitHub issues were closed; no push or deployment was
performed.

Operational details: [Research integrity capsules](../../RESEARCH_RELEASE_FREEZE.md)
and [Schema rollout](../../SCHEMA_ROLLOUT.md).
