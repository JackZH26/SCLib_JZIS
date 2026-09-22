# Engineering issue closure audit: DR03 / EN03

Date: 2026-09-08. Audited local revision: `0461e996d40affc6125193c46a33727fe2781d57` on `codex/sclib-research-v2`.

**Status: targeted local acceptance checks passed; source-suite/type-check completion and implementation publication remain pending. Neither issue is ready for an immediate GitHub closure.** The parent task performed the guarded reruns recorded in section 5; the independent audit itself used read-only source/issue inspection and wrote this report. No code publication, issue-state change, deployment, scientific-provider call or development/production database mutation was performed for this audit.

The scope is only [#56 / DR03](https://github.com/JackZH26/SCLib_JZIS/issues/56) and [#59 / EN03](https://github.com/JackZH26/SCLib_JZIS/issues/59), plus the minimum safe-test dependency check for [#42 / EN01](https://github.com/JackZH26/SCLib_JZIS/issues/42). Their live issue bodies were read on the audit date. References below identify source and tests at the audited local revision, not the older `44fd6ce` worktree referenced in the issue bodies. Parent work on new Batch 30 files is outside this audit; the audited tracked implementation had no working-tree diff from this revision when inspected.

## 1. Delivery status: distinguish local implementation from published completion

Both issues require implementation PR links, exact versions, regression evidence, and compatibility notes. Read-only remote checks on 2026-09-08 found:

- `git branch -vv`: the local `codex/sclib-research-v2` branch has no upstream.
- GitHub's branch inventory does not contain that branch. Remote `main` is `d26fc098565492b78b416fb30b6b1ec7087b24c7`.
- `gh pr list --state all --head codex/sclib-research-v2` returned an empty list.
- The repository commit API returned HTTP 422, “No commit found for SHA,” for `0461e996d40affc6125193c46a33727fe2781d57`.

Consequently, this document deliberately supplies local file references, **not fabricated GitHub commit or PR links**. Local implementation commits include `c6f05f1ca757f692d3f5169768b2fd75c6f685eb` for the shared Discovery feed foundation and `da01f0da1f280ac4ea5ad840db879bd03578d5d8` for background coordination and private status. The complete audit pin is the HEAD above; individual introduction commits do not replace that pin.

| Decision layer | DR03 / #56 | EN03 / #59 |
| --- | --- | --- |
| Current source-to-acceptance mapping | All seven criteria have implementation and targeted regression coverage identified below | All five criteria, operational visibility, and safety dependency have coverage identified below |
| Fresh targeted execution | Passed within the combined 166-test guarded API run and 13-test component run; source suite/type check pending | Passed within the same guarded runs, including independent-process/crash recovery; 15 safe-test tests plus 20 subtests also passed |
| Published implementation / PR delivery | Pending; no matching remote branch or PR found | Pending; no matching remote branch or PR found |
| Production deployment / operating SLA | Not established and not authorized by closure | Not established and not authorized by closure |
| Scientific review / rights / training approval | Neither supplied nor implied | Neither supplied nor implied |

The old #56 implementation comment's then-current “unpublished worktree” wording must not be reused as a current code-status description: there are now local commits. Conversely, local commits do not satisfy the missing remote PR delivery requirement.

## 2. DR03 / #56: validated atomic legacy Discovery feeds

Relevant contracts: strict Discovery API schema `1`, cache envelope `discovery-cache/1`, and content-derived `discovery-v1-<digest>` identity. This is a legacy feed reliability contract, not RPS calibration or a scientific acceptance decision. Its source schema validates representational consistency; it cannot establish that a candidate's scientific claims are true.

### Acceptance mapping

| Live acceptance criterion | Implementation at the audited revision | Targeted regression evidence to rerun |
| --- | --- | --- |
| 1. Shared strict validation rejects malformed values, nonfinite JSON, duplicate keys/IDs, and mismatched metadata without inventing one universal score range | [discovery_contract.py](../../../api/services/discovery_contract.py), lines 14–20, 29–98: bounded nonempty IDs, strict types, forbidden extras, finite numbers, unique IDs, explicit planned-empty semantics. [discovery_feed.py](../../../api/services/discovery_feed.py), lines 27–94: duplicate-key/nonfinite JSON refusal and one `validate_feed` path for feed/model/metadata agreement. [pull_discovery_feed.sh](../../../scripts/pull_discovery_feed.sh), lines 45–51, invokes the same Python validator. Numeric scores retain their per-field contract; no new global score range is imposed. | [test_discovery_feed_validation.py](../../../api/tests/test_discovery_feed_validation.py): `test_strict_json_rejects_nonfinite_duplicates_and_nonobjects` (57), `test_strict_scores_do_not_coerce` (63), identity/required-status/empty-feed cases (71–91), metadata cases (108), actual standalone validator subprocess (148). |
| 2. Invalid or interrupted publication preserves a matched last-good feed/metadata pair, including restart | [discovery_feed.py](../../../api/services/discovery_feed.py), lines 63–77 and 155–194: one validated envelope, sibling temporary file, file and directory synchronization, atomic replacement, previous-good preservation. [discovery.py](../../../api/routers/discovery.py), lines 172–205: durable last-good recovery rather than replacing good data with an invalid placeholder. Pull staging and failure cleanup are scoped to this pull's files (script lines 23–51). | Same test file: matched envelope and invalid-update preservation (116), injected interrupted promotion (128), standalone failed-attempt marker (148), invalid update and new-store restart recovery (164). Restart is a new loader instance reading persisted bytes, not a claim of a deployed service restart test. |
| 3. Invalid updates retain usable candidates with explicit stale/last-success metadata; no-good is honest unavailable/planned | [discovery_feed.py](../../../api/services/discovery_feed.py), lines 134–153: sanitized failed-update marker. [discovery.py](../../../api/routers/discovery.py), lines 124–168, 192–205 and 250–252: last-good content keeps its identity; status and last-success time are explicit; absent valid content yields 503 for data routes. [DiscoveryFeed.tsx](../../../frontend/components/DiscoveryFeed.tsx), line 387: visible English last-validated warning. | Feed-validation tests at 164, 181, 197 and 242; [discovery-feed-versioning.test.tsx](../../../frontend/tests/component/discovery-feed-versioning.test.tsx), line 96. |
| 4. Accepted list/detail IDs, counts, roles, and revisions agree; duplicates are refused before publication | Contract uniqueness precedes [discovery.py](../../../api/routers/discovery.py), lines 134–165, which derives summaries, role counts and detail map from the same immutable snapshot. Pages/details at lines 328–383 use that snapshot. | [test_discovery_cache.py](../../../api/tests/test_discovery_cache.py), `test_additive_endpoints_page_filter_and_lazy_detail` (102); duplicate refusal (feed-validation line 71); frontend identity/role/count checks at component-test lines 42 and 90. |
| 5. Page/detail requests cannot silently switch from V to V+1 | [discovery.py](../../../api/routers/discovery.py), lines 250–259 and 328–383: explicit 409 conflict for a different version; continuation and details require a pin (428 when missing). First-page bootstrap may omit a pin; the frontend always sends its initial version. Source order, filters, totals, and detail map come from one snapshot. Old versions need not be retained: the documented contract is explicit restart. | `test_version_pinned_pages_and_details_reject_mix_and_unpinned_continuations` (feed-validation line 212); frontend pinned load-more, 409 clearing, role filters, and lazy detail tests (51–90). |
| 6. ETags, content version and stale representations agree; frontend clears rather than merges mismatched pages | [discovery.py](../../../api/routers/discovery.py), lines 220–246: response representation drives conditional caching while content version remains explicit. [api.ts](../../../frontend/lib/api.ts), lines 1764–1804: runtime page/detail identity checks. [DiscoveryFeed.tsx](../../../frontend/components/DiscoveryFeed.tsx), lines 320–379: sequence invalidation, clearing old items and disabling continuation on conflict. | Stale ETag/content-identity regression (feed-validation line 242); cache reuse by file signature ([test_discovery_cache.py](../../../api/tests/test_discovery_cache.py), 71); frontend versioning cases (42–96). |
| 7. Legacy roles and heuristic scores remain distinct from RPS; negative controls are not fabricated measured negatives | [DiscoveryFeed.tsx](../../../frontend/components/DiscoveryFeed.tsx), lines 50–52 explicitly separates research-control roles from experimental negative outcomes. [discovery/page.tsx](../../../frontend/app/discovery/page.tsx), lines 71–72 labels the retained original feed and heuristic scores as historical leads, not RPS, probabilities, or experimental discovery. | Legacy extension/control contract (feed-validation line 91); frontend legacy report label, role/control behavior (34, 70); English/source regressions in `pnpm test:source`. |

### Compatibility and remaining rollout conditions

The [Discovery feed contract](../../DISCOVERY_FEED_CONTRACT.md) describes the changed on-disk envelope, legacy raw-feed validation path, durable last-good sidecar, failure marker, ETag semantics, and deliberate conflict/reload behavior. Existing pull jobs need an API Python environment with Pydantic v2 (`DISCOVERY_VALIDATOR_PYTHON`) and a persistent cache directory writable by the intended loader/publisher. Backend and frontend version behavior must be released coherently. A source pull outage or cache permission failure is not a license to synthesize a validated empty feed.

These are implementation compatibility and rollout prerequisites. Actual deployment, upstream feed scientific review, a production incident rate, RPS conversion, and source redistribution have **not** been established by this audit and are **not** added as invented acceptance criteria for DR03.

## 3. EN03 / #59: durable cross-process background cycles

Relevant contracts: migration `0059_background_jobs`, operational table `background_job_cycles`, policy/receipt version `background-cycle/1.0.0`, and five fixed job identities (`stats_refresh`, `timeline_projection`, `formula_audit`, `nightly_audit`, `ask_history_prune`). This is a SQL-side effect coordination protocol, not a general workflow engine or external delivery ledger.

### Acceptance mapping

| Live acceptance criterion | Implementation at the audited revision | Targeted regression evidence to rerun |
| --- | --- | --- |
| 1. Two independent processes trigger one cycle but produce one effective audit/report set | [background_jobs_v1.py](../../../api/models/background_jobs_v1.py), lines 14–19, 32–80 and 101: exact per-job session lock, current-backend guard, stable unique `(job_name, scheduled_for)` and immutable successful cycles. [background_jobs.py](../../../api/services/background_jobs.py), lines 129–214: dedicated physical connection retains the lock across claim commit and atomic handler/success transaction. All five lifespan paths use the coordinator ([main.py](../../../api/main.py), 69–150, 189–293). | [test_background_job_processes.py](../../../api/tests/test_background_job_processes.py), `test_two_processes_produce_one_effective_audit_set_for_same_cycle` (113): distinct OS processes, held uncommitted effect, busy contender, one committed report, then exact replay. Schema lock/unique/owner tests and all-lifespan-writer wiring tests supplement this actual process test. |
| 2. Delayed older refresh cannot move a watermark backward | Coordinator [background_jobs.py](../../../api/services/background_jobs.py), lines 58–80: oldest unfinished work first and superseded refusal for a previously unrecorded older cycle after a newer success. [timeline_projection.py](../../../api/services/timeline_projection.py), lines 205–216 and 351–376: source-task fence before inputs, nondecreasing refresh time and `greatest` committed watermark. Recovery computes current evidence rather than backdating the refresh to the cycle time. | [test_background_jobs.py](../../../api/tests/test_background_jobs.py), exact replay/superseded cycle (131), pending-cycle/configuration ordering (187); [test_background_job_handlers.py](../../../api/tests/test_background_job_handlers.py), non-backdated Timeline recovery (84); real Timeline failure/recovery preserves nondecreasing values ([test_background_projection_recovery.py](../../../api/tests/test_background_projection_recovery.py), 23–68). |
| 3. Crashed executor recovers without lost or duplicate effective cycle | [background_jobs.py](../../../api/services/background_jobs.py), lines 69–100 and 175–214: same cycle retained, attempts increase, owner changes, known failure rolls back effects, commit uncertainty reconciles durable status, uncertain lock acquisition/release invalidates the connection instead of returning a lock-holding backend to its pool. Session lifetime, not an expiring lease, fences the writer. | Actual SIGKILL-after-uncommitted-effect and new-owner recovery ([test_background_job_processes.py](../../../api/tests/test_background_job_processes.py), 142). [test_background_job_recovery.py](../../../api/tests/test_background_job_recovery.py): uncertain acquisition (80), failed unlock (104), lost acknowledgment after commit (129), forbidden callback commit/rollback (154), permitted nested savepoint (184). |
| 4. Failed refresh preserves the last valid Stats/Timeline projection for serving | [background_jobs.py](../../../api/services/background_jobs.py), lines 109–126 and 175–192: handler effects plus success atomically commit; failure rolls back. [stats_refresh.py](../../../api/services/stats_refresh.py), lines 131–193 and [main.py](../../../api/main.py), 103–116 defer scheduled commit/metrics. [stats.py](../../../api/routers/stats.py), lines 44–60 serves the committed dashboard row. Timeline refresh is caller-transactional ([timeline_projection.py](../../../api/services/timeline_projection.py), 188–210). Existing source/governance holds still override eligibility to serve stale evidence. | Actual SQL `StatsCache` last-good preservation across six failure modes ([test_background_jobs.py](../../../api/tests/test_background_jobs.py), 150–184); real Timeline refresh failure after projection writes and recovery ([test_background_projection_recovery.py](../../../api/tests/test_background_projection_recovery.py), 23); deferred-commit and post-commit handler tests (handlers 26, 213). [test_stats_consistency.py](../../../api/tests/test_stats_consistency.py), 117 proves cached timestamp serving; [test_timeline_projection.py](../../../api/tests/test_timeline_projection.py), 284 and 357 cover fallback/ready-projection route behavior. These are layered transactional and serving proofs, not a single live-site outage experiment. |
| 5. Audit deltas compare intended adjacent successful cycles | [audit_runner.py](../../../api/services/audit_runner.py), lines 161–200: scheduled full-audit atomicity, manual writers participate in the job fence. Lines 203–250 choose previous successful scheduled reports for the same rule and count policy; retain explicit cycle markers and avoid mixing old newly-flagged counts or interleaved manual reports. | [test_background_job_handlers.py](../../../api/tests/test_background_job_handlers.py): actual audit failure rolls back earlier rules/reports (95), preceding successful scheduled cycle rather than interleaved manual report (119), manual writer waits before reading inputs (153). |

### Scope items beyond the five checkboxes

- **Inspection and metrics:** [background_jobs.py](../../../api/services/background_jobs.py), lines 217–245 returns last success, oldest unfinished work, latest-attempt duration/failure and 20 recent cycles per fixed job. Owner is reported only when its lock is observed. Lines 163, 172 and 195–196 emit bounded-label contention, duplicate replay, failure and duration metrics. [background_jobs.py router](../../../api/routers/background_jobs.py), lines 17–46 authenticates an administrator inside a fresh read-only repeatable-read snapshot with time limits; responses are private/no-store, failures sanitized, and there is no HTTP writer. The English [admin jobs page](../../../frontend/app/dashboard/admin/jobs/page.tsx), lines 49–135 shows operational status without exposing raw arbitrary result fields. [test_background_jobs_http.py](../../../api/tests/test_background_jobs_http.py), 23–101 and [background-jobs.test.tsx](../../../frontend/tests/component/background-jobs.test.tsx), 42–84 cover authorization, currentness, unavailable states and visibility.
- **History and migration:** [0059_background_jobs.py](../../../api/alembic/versions/0059_background_jobs.py), lines 17–27 permits empty downgrade only and refuses deletion of populated cycle history. [run_test_migrations.py](../../../scripts/run_test_migrations.py), lines 498–637 exercises empty round-trip, actual migrated-schema work/failure/replay and independent nonempty downgrade refusal after older history guards. [test_schema_lifecycle.py](../../../scripts/tests/test_schema_lifecycle.py), lines 101–119 guards that ordering. Do not infer these migration cases were rerun in this audit.
- **All five handlers, including retention:** [test_background_job_handlers.py](../../../api/tests/test_background_job_handlers.py), lines 58–84 checks wiring and that pruning retains the original cycle's cutoff. This does not authorize a new retention policy or unrelated deletion.

### Required limitations; do not overclaim at closure

The [coordination contract](../../BACKGROUND_JOB_COORDINATION.md) defines these limits, which remain after software acceptance:

> “A successful cycle means the SQL handler effects and its success record committed in one transaction.”

An uncommitted attempt can execute again. The guarantee is one effective committed cycle under participating writers, **not exactly-once callback invocation**, and not Redis/vector delivery. `scheduled_for` is an operational slot, not scientific source availability. Failed refreshes preserve committed rows, not permission to serve a source that current governance excludes.

The latest attempt state/count is retained per cycle; this is not an immutable event log of every failed attempt. Owner visibility is a point-in-time lock observation, not a future liveness guarantee. Metrics are process-local and can reset; durable SQL state is authoritative. The 900-second callback/result timeout and 60-second statement timeout do not bound connection acquisition, claim, failure-recording and cleanup as a single SLA.

Recovery coalesces missed intervals rather than inventing a historical run for every interval. All replicas must share cadence/policy and preserve the physical PostgreSQL session; transaction/statement pooling is unsupported. Old application versions do not participate in the new lock, so they must be drained or disabled during a separately approved rollout. Original deployment configuration must be retained: a stored configuration hash is not enough to reconstruct it. Persistent failures or configuration conflicts need operator investigation, not ledger deletion. Actual-corpus contention/capacity measurement and approved staging/production rollout remain separate operational work.

## 4. Minimum EN01 / #42 dependency check

This is a dependency check, **not a full independent closure recommendation for #42**. Its issue remains open and has the same publication-delivery gap.

- [test_safety.py](../../../scripts/test_safety.py), lines 126–213 validates private short-lived capability, exact DSNs and owned disposable runtime identity before application/client import; it does not accept a name containing `test` as authority.
- [conftest.py](../../../api/tests/conftest.py), lines 3–21 runs the pre-client guard. Lines 70–84 and 166–178 revalidate PostgreSQL/Redis identity before schema destruction or cleanup. Approved services have run-specific least-privilege identities ([run_disposable_tests.py](../../../scripts/run_disposable_tests.py), 163–186 and 227–260).
- [test_test_safety.py](../../../scripts/tests/test_test_safety.py), lines 79–218 covers missing/expired/private-file sentinel, changed PostgreSQL/Redis DSNs, unsafe grammar, credentials in errors, mismatched runtime and instrumented pre-client refusal. [test_disposable_environment.py](../../../api/tests/test_disposable_environment.py), lines 17–49 checks actual disposable database marker/role and Redis cleanup/ACL isolation.
- [test.yml](../../../.github/workflows/test.yml), lines 31–45 and 82 uses the same guard and disposable runner; [TESTING_SAFELY.md](../../TESTING_SAFELY.md) documents the developer entry point. No existing reviewed source corpus is needed for these fixtures.

A successful guarded target run, preceded by the refusal tests, is the minimum fresh dependency evidence for this EN03 audit. It does not close #42 by implication.

## 5. Targeted rerun evidence and reproduction

The parent task reported these completed executions on 2026-09-08 after the source mapping. The guarded API selection was exactly the twelve files listed below, not an inferred subset of an older full-suite result.

| Execution | Actual result | Duration / notes |
| --- | --- | --- |
| EN01 source-only instrumented refusal tests, `scripts/tests/test_test_safety.py` | 15 passed, plus 20 subtests | 0.08 seconds |
| Guarded native API selection, twelve files below | 166 passed | 12.35 seconds; one existing FastAPI warning; disposable cleanup completed |
| Two frontend component files below | 13 passed | 1.89 seconds |
| `pnpm test:source` | 35 passed | 0.63 seconds; current audit execution |
| `pnpm exec tsc --noEmit` | Passed, exit 0 | Current audit execution, not a previous batch's result |

These results establish the local synthetic engineering behavior exercised by the tests. They do not establish production deployment, operating capacity or scientific approval. Counts above were reported by the executing parent task; this audit did not independently repeat the same destructive fixture run.

Run from repository root. This plan adds no tests or schema changes and uses no development/production service targets. The first command is source-only and instruments refusal before client import. The second creates its own guarded native PostgreSQL/Redis instances; do not replace it with an unguarded API pytest call or reuse application DSNs.

```bash
api/.venv/bin/python -m pytest scripts/tests/test_test_safety.py -q

api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --suite api -- -q \
  tests/test_disposable_environment.py \
  tests/test_discovery_feed_validation.py \
  tests/test_discovery_cache.py \
  tests/test_background_job_schema.py \
  tests/test_background_jobs.py \
  tests/test_background_job_recovery.py \
  tests/test_background_job_processes.py \
  tests/test_background_projection_recovery.py \
  tests/test_background_job_handlers.py \
  tests/test_background_jobs_http.py \
  tests/test_stats_consistency.py \
  tests/test_timeline_projection.py --tb=short
```

The core DR03 subset is its two API files; core EN03 uses the seven background-job files. The disposable-environment test makes the dependency explicit, and Stats/Timeline files cover serving compatibility. No whole-corpus benchmark, provider call or new migration is necessary for this bounded software rerun. If migration execution evidence from the audited revision cannot be independently retained, also run `scripts/run_disposable_tests.py` with the same native binary arguments and `--suite migrations`; static migration-harness tests alone do not prove PostgreSQL executed the migration.

After reading `frontend/AGENTS.md`, run from `frontend/`:

```bash
pnpm exec vitest run \
  tests/component/discovery-feed-versioning.test.tsx \
  tests/component/background-jobs.test.tsx --maxWorkers=2
pnpm test:source
pnpm exec tsc --noEmit
```

The two component files contain 8 and 5 explicit tests respectively; their combined 13-test execution passed as recorded above. The source suite also checks English-default and existing source-level contracts. TypeScript checking is a compatibility check, not a test count. All rows above now record actual current-audit execution evidence.

## 6. Provisional decision and closure handoff

No additional implementation defect blocking the stated DR03 or EN03 acceptance was found in this bounded source audit, and the targeted API/component/safety and compatibility checks passed. The next delivery action is authorized publication of the implementation and its PR, without adding unrelated scientific requirements to these engineering issues.

Before a GitHub close action, retain all of the following:

1. Exact revision and successful targeted results above, with individual failures investigated rather than waived by a total pass percentage; #59 must retain the real two-process/SIGKILL evidence.
2. An authorized published implementation and real PR link(s). The local branch/remote absence observed here must not be presented as a completed delivery. This audit does not authorize a push or PR creation.
3. The contract versions and compatibility notes in sections 2–4, and explicit #42 safe-test dependency evidence. Any subsequent relevant code change requires a recheck against the new revision.
4. A closure statement scoped to the software invariants only, retaining operational rollout work separately.

Both live issues explicitly state: **“Creating this issue does not authorize production backfills, deployment, source redistribution or paid computation.”** This boundary is unchanged by local tests, a PR, or later issue closure. No human scientific review, source rights, ML-training approval, calibrated superconductivity probability, production incident history, or real-scale SLA is established by the engineering fixtures.

Until publication delivery is recorded, the correct status is **local targeted acceptance and compatibility checks passed; remote delivery pending**, not “closed,” “deployed,” or “all upgrade issues completed.”
