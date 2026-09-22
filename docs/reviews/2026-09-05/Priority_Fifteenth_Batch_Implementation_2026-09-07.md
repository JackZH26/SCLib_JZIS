# Fifteenth implementation batch — durable negative source lifecycle history

Date: 2026-09-07. Branch: `codex/sclib-research-v2`.
Base checkpoint: `6a327cf` (current-source lifecycle safeguards).
Priority: [SC08 / #66](https://github.com/JackZH26/SCLib_JZIS/issues/66).
Implementation contract: [Observed source lifecycle ledger](../../SOURCE_LIFECYCLE_LEDGER.md).

## Outcome

The previous batch's automatic-restoration gap is closed for tracked sources:
once Paper or Work enters correction/retraction/withdrawal/dispute history,
resetting its mutable status does not restore current eligibility. An append-only
database ledger binds observations and negative processing reviews to exact
revisions. All historical research capsule/publication bytes stay unchanged.

This is local implementation and isolated migration rehearsal, not deployment,
production backfill, scientific approval, canonical promotion or SC08 completion.
No remote issue was closed, repository pushed, production source changed, or
human reviewer impersonated. Website-owned strings remain English.

| Layer | Implemented | Deliberately retained gate |
| --- | --- | --- |
| Database 0056 | Source epoch, immutable Paper/Work observation chains, negative review receipts; held-row bootstrap at observation time | No invented pre-migration history or provider event ordering |
| Source semantics | Frozen catalogue snapshot fields; operational update no-ops; exact predecessor and live-head binding | These hashes do not identify provider bytes or ML01 source versions |
| Review | Explicit active reviewer grant, exact event/optional claim revision, actual canonical artifact bytes, scoped idempotency and supersession | No positive reinstatement, accepted ML labels, HTTP write route or curator UI |
| Admission | Durable separate overlay across material/ancestor/source/claim/search/Ask/history/Timeline/shadow/publication paths | No whole-system asynchronous propagation guarantee or result-level independence adjudication |
| Ingestion | Held direct/accepted-Work source histories excluded from new support after status reset | Existing sweep is not a revision-acknowledged refresh queue |
| Historical integrity | Existing source/capsule/publication contracts untouched; events/reviews/artifacts retained; audit-aware account deletion | No fabricated review notices, retrospective saved-answer validation or file-backed RPS linkage |
| Concurrency | Ordered nonblocking locks, epochs, current-row checks and whole-transaction retry behavior | No measured production throughput, latency or lag SLA |

## Key review decisions

The implementation intentionally distinguishes a database observation from an
upstream source version. Ordinary never-held sources have no baseline; existing
held sources get an honest current-time observation during migration. Previously
unrecorded changes cannot be reconstructed by a hash.

Negative review decisions are `retain_hold` and `requires_supersession`. Neither
authorizes a corrected source, an old claim or a frozen release to regain
eligibility. A positive recovery workflow needs a separately specified successor
contract and scientific adjudication; it is not hidden inside a status field.

Paper and Work are both first-class ledger targets. Accepted current identity
maps conservatively propagate a Work hold to Paper-backed views, while exact
claim review requires the claim's explicit source FK. Formula/family similarity
and generic same-work membership are not result-equivalence evidence.

Independent review found that attaching a review artifact also needs the existing
scientific epoch fence: a stale transaction must not mutate a newly referenced
artifact. Review locks therefore use scientific → publication → source order.
Missing-source resolver results are omitted rather than returned as apparently
present `None` entries, preserving exact publication-inventory admission checks.
Inspection also distinguishes direct history from the effective inherited Work
hold, so a Paper with no direct events cannot display an apparently clear
effective state. Non-iterable source inputs and oversized revision cursors are
rejected before a database binding error.

## Verification

All source/material/claim/reviewer/artifact fixtures are synthetic. PostgreSQL
and Redis checks run only through the capability-guarded disposable native runner.
No test inherits the repository's production DSNs.

Final checks:

| Check | Result |
| --- | --- |
| API full suite, final rerun | 1,965 passed |
| Ingestion full suite | 938 passed |
| Scripts | 264 passed, plus 36 separately reported subtests |
| Frontend source / unit suites | 35 / 247 passed |
| Distinct ordinary tests | 3,449; focused reruns are not double-counted; excludes the 36 script subtests |
| TypeScript | `tsc --noEmit` passed |
| Migration rehearsal | Actual 0056 head/admission, empty round trips, held-source bootstrap/transitions, original capsule/publication preservation and independent nonempty downgrade guards passed |
| Static checks | Scoped Ruff I/F and `git diff --check` passed |

The API run retains the existing FastAPI `regex` deprecation and 19 Alembic
legacy path-separator warnings. Ingestion's SQL-compilation doubles report 34
PostgreSQL `DISTINCT ON` portability deprecations; actual PostgreSQL migration
and integration tests use the supported PostgreSQL dialect. No production
performance or scientific validation is inferred from these synthetic checks.

Focused tests already establish: exact canonical bytes and hashes; unauthorized
review rejection; full dry-run rollback; exact idempotency; revision/grant-stale
reviews; source identity/history/artifact retention; accepted-Work propagation;
bounded history cursors; stale RR artifact/source writes; nonblocking contention
and successful retry without a chain fork. Migration rehearsal exercises actual
held-row bootstrap, status reset, date revision, semantic no-ops, hash chains,
old-history preservation and independent nonempty downgrade guards.

The first integrated run exposed test-fixture issues while parallel code was
still changing (raw SQL defaults, event-loop ownership and obsolete read mocks);
those were corrected without weakening source holds or history retention. A
later full run passed 1,964 tests but its additional oversized-byte test could
not finish setup because pytest embedded the entire 1 MiB parameter in its test
name. Giving that case an explicit short ID retained the full oversized payload;
the complete 29-test service suite then passed. The final full run below includes
that corrected test, rather than counting a setup error as a successful limit check.

## Next priority and acceptance

SC08 remains open. Next implement an indexed exact-source dependency inventory
and bounded refresh/impact receipts. This should identify affected results,
Timeline candidates (including those without points), chunks, prospective ML
membership and release references without silently treating a formula match as
a dependency. Requested/completed revisions, failures and retries must be
observable before claiming propagation performance or an SLA.

Canonical successor admission, unaffected mixed-source results, RG02
post-generation source checks, file-backed RPS evidence bindings, human-reviewed
staging cases and positive source recovery remain explicitly unfinished.
