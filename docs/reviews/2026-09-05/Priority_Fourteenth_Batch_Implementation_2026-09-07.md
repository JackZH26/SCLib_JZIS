# Fourteenth implementation batch — current-source lifecycle safeguards

Date: 2026-09-07. Branch: `codex/sclib-research-v2`.
Base checkpoint: `987265b` (ML07 research access and metadata publication).
Priority: [SC08 / #66](https://github.com/JackZH26/SCLib_JZIS/issues/66).
Implementation contract: [Source lifecycle guards](../../SOURCE_LIFECYCLE_GUARDS.md).

## Outcome

This batch fixes concrete stale-source pathways in aggregation, audit, Timeline
and saved Ask history. It preserves material identity, retained source records,
private governance notes and immutable release bytes. It is a bounded local
implementation, not completion of the source-event/review propagation ledger.
SC08 remains open; no production changes, migration, push or deployment occurred.

| Surface | Implemented | Deliberately not claimed |
| --- | --- | --- |
| Material summaries | Held source statuses excluded from every derived support/value pool; only-source orphan summary reset; retained mixed-source records kept | No recovery of missing historical records, scientific refutation or family-based dependency identity |
| Material writes | Existing holds/quarantines sticky with or without legacy decisions; actual-change timestamp, SQL no-op replay | No upstream concurrency/out-of-order event guarantee |
| Audit | Current evidence reevaluated despite legacy notes; sole-source rule no longer suggests material dispute flags; live and retained lifecycle holds resist legacy override | No new append-only decision ledger or canonical revision promotion |
| Audit metrics/UI | Comparable count-basis version, failed-check handling and explicit current-match versus queue-reason wording | No artificial increase against old newly-flagged baselines; no propagation SLA |
| Timeline | Source content/date/status snapshot comparison, UTC canonicalization and forced-rebuild hook; cache version 6 | No scientific source-version witness; zero-prior-point/no-timestamp changes still need controlled full rebuild or future dependency inventory |
| Ask history | Immutable saved answer/citations plus bounded current metadata summary in a read-only consistent snapshot; English warnings and no-store | No retrospective revalidation of the answer or unbounded repeated evidence expansion |
| Research publication | Added HTTP regression for all four held source statuses, all public aliases/inventory, conditional caches and exact historical capsule preservation | No automatic review artifacts/notices or retroactive modification of frozen data; existing ML07 behavior reused |

Database head stays `0055_research_publication`. No frozen source-registry,
research-capsule, metadata-publication schema or hashing contract was rewritten.
The Timeline version bump invalidates a rebuildable cache, not the database
migration history or research release versions.

## Scope and review decisions

Three parallel bounded tasks covered aggregation, Timeline and saved-history
propagation. Independent cross-review found and corrected additional risks:

- Re-aggregation could clear a pre-existing hold without `admin_decision`; the
  actual SQL now preserves such holds and quarantine reasons too.
- Mixed-source rebuilding could drop existing held records to regain catalogue
  eligibility; the retained Archive path is kept instead.
- A restored `published` status could allow legacy override of a stored lifecycle
  reason; those reasons now require revision-aware review as well.
- Audit match counts could be compared against old newly-flagged counts; new
  count-basis metadata prevents that misleading baseline comparison.
- History source preflight alone did not bound full material ancestor reads;
  the final read path preflights the complete bounded ancestor set in the same
  REPEATABLE READ snapshot.
- An incomplete top-level history check could leave nested occurrence support
  true; the new projection now returns only checked state counts and no detailed
  per-occurrence eligibility records.
- Repeated saved citations could amplify a small unique source inventory into
  a very large response; the added current-metadata envelope is separately
  limited to 8 MiB of serialized output, including repetitions.

These are safety/consistency changes, not additional real scientific labels.
The website-owned copy remains English. Original user questions, saved answers
and quotations are not translated or rewritten.

## Verification

All database/Redis checks use the capability-guarded disposable native runner,
never inherited production DSNs. A dedicated real PostgreSQL integration test
executes the ingestion upsert statement, rather than relying solely on mocked
driver or compiled-SQL assertions. It checks holds, raw records, identity/links,
changed-write timestamps and replay no-ops across transactions.

Final checks:

| Check | Result |
| --- | --- |
| API full suite, final rerun | 1,896 passed |
| Ingestion full suite | 935 passed |
| Scripts | 264 passed, plus 36 separately reported subtests |
| Frontend source / unit suites | 35 / 247 passed |
| Distinct ordinary tests verified | 3,377; focused reruns are not double-counted; excludes the 36 script subtests |
| TypeScript | `tsc --noEmit` passed |
| Migration rehearsal | Existing head/admission, empty round trips, old-data preservation, migrated freeze/publication/withdrawal and nonempty-history rollback guards passed |
| Static checks | Scoped Ruff I/F and `git diff --check` passed |

The API run reports the existing FastAPI `regex` deprecation and 19 Alembic
legacy path-separator warnings. No new schema migration was introduced.

The first focused audit/report run exposed a test teardown event-loop mismatch,
not a failed production invariant. The new test fixture now owns its transaction
and teardown on the same function loop; final verification includes the fix.
The initial full run also exposed six over-strong Timeline assertions: recently
committed unrelated papers legitimately trigger the pre-existing five-minute
rebuild overlap. Final tests independently assert the SQL content-mismatch probe
converges and that rebuild behavior matches the actual global timestamp signal.
Recent/future unrelated-paper regressions and a history-first execution order
verify that distinction without weakening point-content/identity assertions.
All source/material/result fixtures are synthetic. No live paper was marked
corrected/retracted, no real research publication was withdrawn, and the real
ML08 human-reviewed pilot remains at its previously reported stage.

## Remaining acceptance and next priority

SC08 is not closed. The next implementation should establish the append-only
source-change and review ledger, with exact dependency revisions, idempotency
and explicit successor ordering, then integrate dependency refresh receipts.
The existing mutable `admin_decision` field is still not a historical ledger,
and a persistent unrelated queue reason does not encode every additional hold.

In particular, current source status can still be restored without an ordered
lifecycle event. Live ML07 read admission can then resume unless an explicit
reviewed notice/publication withdrawal or another durable hold exists. A daily
aggregation sweep, no-store headers and point-level date checks are not a
substitute for cross-system event ordering and persistent source invalidation.

Subsequent acceptance must cover:

1. Exact source/result revision-bound review and canonical supersession.
2. Result-level mixed-source admission while retaining independent evidence.
3. An indexed dependency inventory including zero-point Timeline candidates,
   chunks/RAG, prospective ML datasets and file-backed RPS evidence.
4. Idempotent queued refresh, out-of-order/concurrent convergence, retries and
   measured propagation lag/SLA.
5. RG02 post-generation source checks before delivering a long-running Ask
   answer, plus explicit reviewed notices for historical releases.
6. Real staging rehearsal and human scientific/rights review before production
   rollout or any claim of ML-training readiness.
