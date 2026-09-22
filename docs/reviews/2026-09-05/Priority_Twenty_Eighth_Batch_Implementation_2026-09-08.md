# Twenty-eighth implementation batch — governed RPS structured distribution

Date: 2026-09-08. Branch: `codex/sclib-research-v2`.
Baseline: `8d2cfdd` (twenty-seventh batch).
Priority: [ML07 / #68](https://github.com/JackZH26/SCLib_JZIS/issues/68), with
the existing [ML04 / #64](https://github.com/JackZH26/SCLib_JZIS/issues/64) and
[SC07 / #49](https://github.com/JackZH26/SCLib_JZIS/issues/49) dependencies.
Specification: [RPS distribution governance](../../RPS_DISTRIBUTION_GOVERNANCE.md).

## Outcome

Connected Discovery's existing catalogue, assessment list, detail and public
bundle download to exact database-backed distribution approval. Both existing
configuration hash pins remain necessary, but are no longer sufficient. The
public scoring policy and RPS algorithm are unchanged; no superconductivity
probability, empirical calibration or scientific approval is inferred.

The complete real workflow is now executable through private authenticated
operator endpoints: exact source/capsule registration, each recursive dependency's
rights decision, independent disclosure review, third-account publication,
revocation and withdrawal. Preview is the default. The new schema is not an
unused ledger disconnected from public consumers.

No real source or private ML dataset was published, no real rights review was
invented, no role or production configuration was enabled, and no production
migration, backfill, deployment, push, PR or remote issue closure was performed.
All positive test data and approvals are synthetic. #68 and the overall goal
remain open; local code verification is not their complete release acceptance.

## Delivered

1. Complete `research-distribution-bindings/1.0.0` coverage of every RPS artifact,
   not just row-level evidence. Real material/state IDs and projection hashes
   supplement artifact identity, with exact physical context checks.
2. Three actual root mechanisms: 0052 literature source capture with accepted
   Paper-to-Work mapping; exact 0054 frozen claim/property with the entire capsule;
   and exact complete original RPS bytes for non-evidence internal descriptors.
   Curation/calculation cannot inherit an experimental origin declaration.
3. Trusted, bounded SQL loading and byte verification. Client-supplied row JSON,
   URLs, titles, formulas and license strings are not database authentication.
4. Additive 0063 immutable packages, normalized dependencies, permissions,
   reviews/actions and transaction epoch. All supported target identities receive
   actual foreign keys; complete registration is atomically sealed. Existing
   0054 and 0055 contracts and scopes are unchanged.
5. One exact purpose-specific rights artifact and allow/revoke chain per
   dependency. A complete permission manifest is frozen by each positive review;
   a renewed permission requires renewed review, even if still permissive.
6. Live curator/reviewer/publisher grants, three distinct accounts, no admin-flag
   bypass, exact audit hashes, immutable history and account-retention handling.
   Negative reviews, revokes and withdrawals remain possible after a prior
   positive source/rights/actor condition becomes unavailable.
7. Authenticated private HTTP operations with actor spoofing refusal, browser
   CSRF protection, early role preflight, bounded streamed strict JSON/base64,
   limited in-flight large requests, fresh transactional role/session checks,
   explicit durable commit receipts and full rollback on failures/cancellation.
8. Default dry runs and exact request-key replays that leave all database rows,
   including the ordered guard epochs, unchanged. No-op is tested as actual
   state equality, not only equal response IDs.
9. Fresh bounded database admission and second-snapshot revalidation before
   public output, with final synchronous file/configuration checks. Pending IDs
   do not leak through catalogue entries or approval fingerprints. Hot files and
   matching ETags cannot bypass changed permissions, sources, accounts or roles.
10. Independent migration rehearsal: empty 0063 down/up round trip, unchanged
    older populated ledgers, exact schema admission, actual publication workflow,
    previews/outer rollback/replays, withdrawal and nonempty downgrade refusal.

## Independent findings resolved

- A declaration-only RPS source reference needed a real database and actual-byte
  binding before current source or rights policy could be enforced.
- A frozen result's permission scope could not be reduced to one selected claim
  while silently omitting its underlying source/run/review dependencies.
- PostgreSQL's `0` and JSON's `0.0` must agree physically without treating a
  Boolean or missing condition as zero.
- Exact service replays initially advanced guard epochs; savepoint and outer
  HTTP transaction rollback now preserve full database state on no-op.
- Revoke/withdraw paths must not re-require old rights bytes, an active old
  reviewer or a still-eligible source before recording the protective decision.
- A file/configuration could change during the final database await. The last
  synchronous witness check now occurs after that await on all release paths.
- New per-dependency SQL insertion originally rescanned the full JSON inventory.
  Exact set equality is checked at atomic deferred completion instead of a
  quadratic per-row whole-inventory scan.
- Direct internal reads needed a clean stable snapshot and UTC-normalized
  projections; the caller's time zone must not create false data drift.
- A normal logged-in account could previously trigger bulk parsing before the
  role check. Upload preflight and a nonblocking operation-capacity bound now
  complement the final transaction's live authorization checks.
- Existing pin-only HTTP tests were migrated to real SQL publication fixtures;
  an unconditional allow mock would have hidden the missing integration.

## Verification

Final executable code and test inventories were frozen before the concluding
complete API run. Intermediate focused runs and the earlier pre-hardening full
run are not summed into the final suite totals.

| Check | Result |
| --- | --- |
| Full API, owned native PostgreSQL/Redis | 4,378 passed; 20 existing warnings; 796.88 s |
| Full ingestion, inert database/Redis endpoints | 1,275 passed; 34 existing warnings; 14.19 s |
| Full scripts | 584 passed plus 36 subtests; 15.08 s |
| Full frontend components | 507 passed across 27 files; 22.02 s |
| Frontend source checks | 35 passed |
| TypeScript | `tsc --noEmit` passed |
| API/ingestion dependency locks | Both `uv lock --check` passed |
| Independent native migration rehearsal | Passed, including all earlier independent guards and new 0063 workflow |
| Changed Python modules/tests | Ruff `I,F` passed |
| Patch whitespace | Staged and unstaged `git diff --check` passed |

Total: **6,779 ordinary tests plus 36 subtests**, with no skipped cases in these
complete suites. This batch adds **217 ordinary tests**: 215 API and two script
checks. The new API inventory comprises 53 pure contract, 62 private operator,
49 direct SQL/schema, 19 service workflow and 32 actual source/HTTP cases.
The final independent migration rehearsal was rerun after the read-boundary
hardening and passed on the final executable code.

Actual source positives include a captured literature version with accepted
mapping, an Inferred curation capsule, and a Computed producer with an actual
research run and verified run manifest. Each goes through real registration,
rights review/publication and every public read path; tampered bytes, mismatched
provider version, incompatible event origin or withdrawn transitive permissions
do not become acceptable evidence. None constitutes a real scientific result.
Typed public fields cannot automatically detect sensitive content hidden in
otherwise allowed prose or authenticate real consent. Those reviews remain
explicit human release gates, not capabilities claimed from schema validation.

Native tests are not Linux image/PR CI, a backed-up staging rehearsal, external
cache propagation measurements, production canary or empirical model evaluation.
Disposable test runners remove only their own test services and temporary data.

## Remaining work and next technical priority

The live issue was reread for this batch and remains OPEN. This iteration closes
the RPS distribution implementation gap, but does not complete all ML07 purpose-
specific exports, authorize real third-party material, or satisfy production
release gates. A usable artifact/rights preparation interface, real operator
review, dataset-sized performance evidence and an approved rollout remain work,
not implicit capabilities attributed to the tests.

Next ML06 work remains task-specific typed physical/structure features with exact
source availability and dependency checks, explicit state applicability,
negative/censored-label policy, comparable feature subsets and fair evaluation.
The current source-bound formula compiler must not silently admit Tc-derived EPC
or renamed target-derived descriptors. RPS distribution permission also cannot
serve as model-training permission. These are concrete technical and scientific
dependencies, not an excuse to declare every remaining task externally blocked.
